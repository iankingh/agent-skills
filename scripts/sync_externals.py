#!/usr/bin/env python3
"""Synchronize public upstream source snapshots without executing their code."""

import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import tempfile
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import yaml


ROOT = Path(__file__).resolve().parents[1]
START = '<!-- EXTERNALS:START -->'
END = '<!-- EXTERNALS:END -->'
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_CONTENT = 256 * 1024 * 1024
SHA = re.compile(r'[0-9a-f]{40}')


def relative_path(value, allow_root=False):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError(f'Invalid relative path: {value!r}')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or any(ord(c) < 32 for c in value):
        raise ValueError(f'Unsafe relative path: {value!r}')
    if str(path) == '.' and not allow_root:
        raise ValueError('A file path must not be the root directory')
    return str(path)


def load_manifest(root):
    data = yaml.safe_load((root / 'externals.yaml').read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('sources'), list):
        raise ValueError('externals.yaml must contain version: 1 and a sources list')
    names = set()
    for source in data['sources']:
        if not isinstance(source, dict):
            raise ValueError('Each source must be a mapping')
        for key in ('name', 'repository', 'ref', 'path', 'description', 'reason', 'trial_status'):
            value = source.get(key)
            if not isinstance(value, str) or not value.strip() or '\n' in value or '\r' in value:
                raise ValueError(f'Invalid source field: {key}')
        name = source['name']
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or name in names:
            raise ValueError(f'Duplicate or invalid source name: {name}')
        names.add(name)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', source['repository']):
            raise ValueError(f'Invalid GitHub repository: {source["repository"]}')
        source['path'] = relative_path(source['path'], allow_root=True)
        required = source.get('required_files')
        if not isinstance(required, list) or not required:
            raise ValueError(f'{name}: required_files must be a nonempty list')
        source['required_files'] = [relative_path(path) for path in required]
    if not names:
        raise ValueError('At least one external source is required')
    return data['sources']


def load_lock(root):
    path = root / 'externals.lock.json'
    if not path.exists():
        return {'version': 1, 'sources': {}}
    lock = json.loads(path.read_text(encoding='utf-8'))
    if lock.get('version') != 1 or not isinstance(lock.get('sources'), dict):
        raise ValueError('Invalid externals.lock.json')
    for name, entry in lock['sources'].items():
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
            raise ValueError(f'Invalid locked source name: {name}')
        if not SHA.fullmatch(entry.get('commit', '')) or not entry.get('files'):
            raise ValueError(f'{name}: missing locked commit or files')
        for path in entry['files']:
            relative_path(path)
    return lock


def inventory(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f'Expected a managed directory: {directory}')
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Symlinks are not supported in snapshots: {path}')
        if path.is_file():
            name = path.relative_to(directory).as_posix()
            relative_path(name)
            result[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'mode': '0755' if path.stat().st_mode & 0o111 else '0644'}
        elif not path.is_dir():
            raise ValueError(f'Unsupported file type: {path}')
    return result


def verify_snapshots(root, lock):
    if (root / 'external').is_symlink():
        raise ValueError('external/ must not be a symlink')
    for name, entry in lock['sources'].items():
        if inventory(root / 'external' / name) != entry['files']:
            raise ValueError(f'{name}: local snapshot differs from its lock; preserve your edits before updating')


class SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if (urlsplit(newurl).scheme, urlsplit(newurl).hostname) != ('https', urlsplit(request.full_url).hostname):
            raise ValueError('Refusing a cross-host or non-HTTPS download redirect')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class GitHub:
    def read(self, url):
        host = urlsplit(url).hostname
        if urlsplit(url).scheme != 'https' or host not in ('api.github.com', 'codeload.github.com'):
            raise ValueError('Only GitHub API and codeload HTTPS URLs are supported')
        headers = {'User-Agent': 'agent-skills-external-sync', 'Accept': 'application/vnd.github+json'}
        token = os.environ.get('GH_TOKEN')
        if token and host == 'api.github.com':
            headers['Authorization'] = f'Bearer {token}'
        with build_opener(SameHostRedirect()).open(Request(url, headers=headers), timeout=90) as response:
            data = response.read(MAX_ARCHIVE + 1)
        if len(data) > MAX_ARCHIVE:
            raise ValueError('Upstream response exceeds the download limit')
        return data

    def latest(self, source):
        query = {'sha': source['ref'], 'per_page': 1}
        if source['path'] != '.':
            query['path'] = source['path']
        url = f'https://api.github.com/repos/{source["repository"]}/commits?{urlencode(query)}'
        commits = json.loads(self.read(url))
        if not isinstance(commits, list) or not commits or not SHA.fullmatch(commits[0].get('sha', '')):
            raise ValueError(f'{source["name"]}: no upstream commit found for the configured branch/path')
        return commits[0]['sha'], commits[0]['commit']['committer']['date']

    def archive(self, source, commit):
        return self.read(f'https://codeload.github.com/{source["repository"]}/tar.gz/{commit}')


def unpack(archive, source_path, destination):
    """Extract only regular files in the configured subtree, never archive links."""
    selected = () if source_path == '.' else PurePosixPath(source_path).parts
    destination.mkdir()
    seen, total, roots = set(), 0, set()
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        for member in tar:
            relative_path(member.name)
            parts = PurePosixPath(member.name).parts
            roots.add(parts[0])
            if len(roots) != 1:
                raise ValueError('Archive must have a single repository root')
            inside = parts[1:]
            if inside[:len(selected)] != selected:
                continue
            relative = inside[len(selected):]
            if not relative:
                if not member.isdir():
                    raise ValueError('Configured source must be a directory')
                continue
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f'Unsupported archive link or special file: {member.name}')
            name = relative_path('/'.join(relative))
            if name in seen or '.git' in relative:
                raise ValueError(f'Duplicate or reserved archive path: {name}')
            seen.add(name)
            total += member.size
            if total > MAX_CONTENT or len(seen) > 10000:
                raise ValueError('Selected upstream files exceed the extraction limit')
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as stream:
                path.write_bytes(stream.read())
            path.chmod(0o755 if member.mode & 0o111 else 0o644)
    if not seen:
        raise ValueError(f'Configured subtree has no files: {source_path}')
    return inventory(destination)


def table_cell(value):
    return value.replace('|', '\\|')


def render_readme(text, sources, lock):
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise ValueError('README must contain exactly one ordered EXTERNALS marker pair')
    lines = ['| 項目與同步副本 | 用途 | 收藏理由 | 試用狀態 | 同步版本 |',
             '| --- | --- | --- | --- | --- |']
    for source in sources:
        name = source['name']
        entry = lock['sources'][name]
        repo = f'https://github.com/{source["repository"]}'
        upstream = repo if source['path'] == '.' else f'{repo}/tree/{source["ref"]}/{source["path"]}'
        cells = [f'[{name}](external/{name}/README.md) · [上游]({upstream})', source['description'],
                 source['reason'], source['trial_status'],
                 f'[{entry["commit"][:7]}]({repo}/commit/{entry["commit"]})']
        lines.append('| ' + ' | '.join(map(table_cell, cells)) + ' |')
    before, rest = text.split(START)
    _, after = rest.split(END)
    return before + START + '\n\n' + '\n'.join(lines) + '\n\n' + END + after


def check(root):
    sources, lock = load_manifest(root), load_lock(root)
    if {s['name'] for s in sources} != set(lock['sources']):
        raise ValueError('Manifest and lock source names differ; run update')
    verify_snapshots(root, lock)
    for source in sources:
        entry = lock['sources'][source['name']]
        if any(entry.get(key) != source[key] for key in ('repository', 'ref', 'path')):
            raise ValueError(f'{source["name"]}: source settings differ from the lock; run update')
        if not set(source['required_files']).issubset(entry['files']):
            raise ValueError(f'{source["name"]}: required upstream files are missing')
    text = (root / 'README.md').read_text(encoding='utf-8')
    if render_readme(text, sources, lock) != text:
        raise ValueError('Generated README table is stale; run render')
    return lock


def write_if_changed(path, text):
    if not path.exists() or path.read_text(encoding='utf-8') != text:
        path.write_text(text, encoding='utf-8')


def report(updates):
    lines = ['## 外部專案來源同步', '', '同步完整來源檔案；中文介紹與試用狀態沿用 externals.yaml，未執行上游程式。', '']
    for item in updates:
        name, old, new = item['name'], item['old'], item['new']
        repo = new['repository'] if new else old['repository']
        base = f'https://github.com/{repo}'
        if new is None:
            lines.append(f'- **{name}**：依來源清單移除同步副本。')
        else:
            link = f'{base}/compare/{old["commit"]}...{new["commit"]}' if old and old['repository'] == repo else f'{base}/tree/{new["commit"]}'
            before = old['files'] if old else {}
            after = new['files']
            added, deleted = set(after) - set(before), set(before) - set(after)
            modified = {p for p in set(before) & set(after) if before[p] != after[p]}
            lines.append(f'- **{name}**：[{new["commit"][:7]}]({link})；新增 {len(added)}、修改 {len(modified)}、刪除 {len(deleted)} 個檔案。')
    if not updates:
        lines.append('- 上游來源版本沒有變更。')
    return '\n'.join(lines) + '\n'


def update(root, client=None):
    sources, old_lock = load_manifest(root), load_lock(root)
    verify_snapshots(root, old_lock)
    readme = (root / 'README.md').read_text(encoding='utf-8')
    client = client or GitHub()
    new_lock = {'version': 1, 'sources': {}}
    updates = []
    (root / 'external').mkdir(exist_ok=True)
    for source in sources:
        destination = root / 'external' / source['name']
        if source['name'] not in old_lock['sources'] and (destination.exists() or destination.is_symlink()):
            raise ValueError(f'Refusing to overwrite an unmanaged directory: {destination}')
    with tempfile.TemporaryDirectory(prefix='.external-sync-', dir=root) as folder:
        stage = Path(folder)
        for source in sources:
            name = source['name']
            old = old_lock['sources'].get(name)
            commit, committed_at = client.latest(source)
            if old and old['commit'] == commit and all(old.get(k) == source[k] for k in ('repository', 'ref', 'path')):
                entry = old
            else:
                files = unpack(client.archive(source, commit), source['path'], stage / name)
                if not set(source['required_files']).issubset(files):
                    raise ValueError(f'{name}: upstream is missing required_files')
                entry = {k: source[k] for k in ('repository', 'ref', 'path')}
                entry.update(commit=commit, committed_at=committed_at, files=files)
            new_lock['sources'][name] = entry
            if old != entry:
                updates.append({'name': name, 'old': old, 'new': entry})
        for name, old in old_lock['sources'].items():
            if name not in new_lock['sources']:
                updates.append({'name': name, 'old': old, 'new': None})
        new_readme = render_readme(readme, sources, new_lock)
        # A download can take time; preserve edits made while it was in flight.
        verify_snapshots(root, old_lock)
        for source in sources:
            destination = root / 'external' / source['name']
            if source['name'] not in old_lock['sources'] and (destination.exists() or destination.is_symlink()):
                raise ValueError(f'Refusing to overwrite an unmanaged directory: {destination}')
        if (root / 'README.md').read_text(encoding='utf-8') != readme:
            raise ValueError('README changed during download; rerun update to preserve the new text')
        lock_path = root / 'externals.lock.json'
        old_lock_bytes = lock_path.read_bytes() if lock_path.exists() else None
        moved, installed = [], []
        try:
            for item in updates:
                name = item['name']
                destination = root / 'external' / name
                if destination.exists():
                    backup = stage / ('previous-' + name)
                    destination.rename(backup)
                    moved.append((backup, destination))
                if item['new'] is not None:
                    (stage / name).rename(destination)
                    installed.append(destination)
            write_if_changed(lock_path, json.dumps(new_lock, ensure_ascii=False, indent=2) + '\n')
            write_if_changed(root / 'README.md', new_readme)
            check(root)
        except Exception:
            for destination in installed:
                shutil.rmtree(destination)
            for backup, destination in moved:
                backup.rename(destination)
            if old_lock_bytes is None:
                lock_path.unlink(missing_ok=True)
            else:
                lock_path.write_bytes(old_lock_bytes)
            (root / 'README.md').write_text(readme, encoding='utf-8')
            raise
    return report(updates)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('update', 'check', 'render'))
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--report', type=Path, help='Write an update PR body outside the tracked source files')
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == 'update':
            summary = update(root)
            print(summary)
            if args.report:
                args.report.write_text(summary, encoding='utf-8')
        elif args.command == 'render':
            sources, lock = load_manifest(root), load_lock(root)
            text = (root / 'README.md').read_text(encoding='utf-8')
            write_if_changed(root / 'README.md', render_readme(text, sources, lock))
            print('README external table rendered.')
        else:
            lock = check(root)
            counts = Counter({name: len(entry['files']) for name, entry in lock['sources'].items()})
            print(f'PASS {len(counts)} snapshots, {sum(counts.values())} files: hashes, modes, required files and README table')
    except (ValueError, OSError, KeyError, TypeError, tarfile.TarError, yaml.YAMLError) as error:
        print(f'FAIL {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
