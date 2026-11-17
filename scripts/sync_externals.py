#!/usr/bin/env python3
"""Synchronize public upstream source snapshots without executing their code."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

import yaml


ROOT = Path(__file__).resolve().parents[1]
START = '<!-- EXTERNALS:START -->'
END = '<!-- EXTERNALS:END -->'
MAX_CONTENT = 256 * 1024 * 1024
SHA = re.compile(r'[0-9a-f]{40}')


def relative_path(value, allow_root=False):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError(f'Invalid relative path: {value!r}')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part.lower() in ('..', '.git') for part in path.parts) or any(ord(c) < 32 for c in value):
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


class Git:
    def __init__(self, root, index=None):
        self.root = root
        self.env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_NO_REPLACE_OBJECTS='1')
        if index is not None:
            self.env['GIT_INDEX_FILE'] = str(index)

    def run(self, *args, data=None, ok=(0,)):
        result = subprocess.run(
            ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.autocrlf=false',
             '-c', 'core.filemode=true', '-c', 'submodule.recurse=false',
             '-c', 'credential.helper=', *args],
            cwd=self.root, env=self.env, input=data, capture_output=True,
        )
        if result.returncode not in ok:
            message = result.stderr or result.stdout
            raise ValueError(f'git {args[0]}: {message.decode(errors="replace").strip()}')
        return result

    def text(self, *args):
        return self.run(*args).stdout.decode().strip()

    def ancestor(self, commit, head):
        if self.run('cat-file', '-e', f'{commit}^{{commit}}', ok=(0, 1, 128)).returncode:
            return False
        result = self.run('merge-base', '--is-ancestor', commit, head, ok=(0, 1))
        return result.returncode == 0

    def latest(self, source):
        branch = f'refs/heads/{source["ref"]}'
        self.run('check-ref-format', branch)
        ref = f'refs/externals/{source["name"]}'
        url = f'https://github.com/{source["repository"]}.git'
        self.run('fetch', '--no-tags', '--no-recurse-submodules', '--no-write-fetch-head',
                 '--', url, f'+{branch}:{ref}')
        args = ['log', '-1', '--format=%H%n%cI', ref]
        if source['path'] != '.':
            args.extend(['--', f':(top,literal){source["path"]}'])
        version = self.text(*args).splitlines()
        if len(version) != 2 or not SHA.fullmatch(version[0]):
            raise ValueError(f'{source["name"]}: no upstream commit found for the configured branch/path')
        commit, date = version
        committed_at = datetime.fromisoformat(date).astimezone(timezone.utc)
        return commit, committed_at.isoformat().replace('+00:00', 'Z')

    def tree(self, commit, path):
        spec = f'{commit}^{{tree}}' if path == '.' else f'{commit}:{path}'
        tree = self.text('rev-parse', '--verify', spec)
        if self.text('cat-file', '-t', tree) != 'tree':
            raise ValueError(f'Configured source must be a directory: {path}')
        return tree

    def files(self, tree):
        entries = []
        for record in self.run('ls-tree', '-rlz', tree).stdout.split(b'\0')[:-1]:
            metadata, raw_name = record.split(b'\t', 1)
            mode, kind, blob, size = metadata.split()
            name = relative_path(raw_name.decode())
            if kind != b'blob' or mode not in (b'100644', b'100755'):
                raise ValueError(f'Unsupported upstream link or special file: {name}')
            entries.append((name, mode, blob, int(size)))
        if not entries:
            raise ValueError('Configured subtree has no files')
        if len(entries) > 10000 or sum(size for _, _, _, size in entries) > MAX_CONTENT:
            raise ValueError('Selected upstream files exceed the extraction limit')

        # Read raw blobs so Git attributes cannot omit files or substitute their contents.
        data = b''.join(blob + b'\n' for _, _, blob, _ in entries)
        output = BytesIO(self.run('cat-file', '--batch', data=data).stdout)
        files = {}
        for name, mode, blob, size in entries:
            if output.readline().split() != [blob, b'blob', str(size).encode()]:
                raise ValueError(f'Cannot read upstream blob for {name}')
            content = output.read(size)
            if len(content) != size or output.read(1) != b'\n':
                raise ValueError(f'Incomplete upstream blob for {name}')
            files[name] = {'sha256': hashlib.sha256(content).hexdigest(),
                           'mode': mode[2:].decode()}
        return files

    def index_text(self, path, text):
        blob = self.run('hash-object', '-w', '--stdin', data=text.encode()).stdout.strip().decode()
        self.run('update-index', '--add', '--cacheinfo', f'100644,{blob},{path}')


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


def check(root, history=False):
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
    if history:
        verify_history(Git(root), 'HEAD', lock)
    return lock


def verify_history(git, head, lock):
    for name, entry in lock['sources'].items():
        commit = entry['commit']
        if not git.ancestor(commit, head):
            raise ValueError(f'{name}: upstream {commit} is not in the synchronization history')
        if git.tree(commit, entry['path']) != git.tree(head, f'external/{name}'):
            raise ValueError(f'{name}: committed snapshot does not match upstream {commit}')


def write_if_changed(path, text):
    if not path.exists() or path.read_text(encoding='utf-8') != text:
        path.write_text(text, encoding='utf-8')


def report(updates, imports):
    lines = ['## 外部專案來源同步', '', '保留上游原始 Git 提交。請使用 **Create a merge commit** 合併此 PR，讓上游提交進入預設分支歷史。', '']
    for item in updates:
        name, old, new = item['name'], item['old'], item['new']
        repo = new['repository'] if new else old['repository']
        base = f'https://github.com/{repo}'
        if new is None:
            lines.append(f'- **{name}**：依來源清單移除同步副本。')
        else:
            link = f'{base}/compare/{old["commit"]}...{new["commit"]}' if old and old['repository'] == repo else f'{base}/commit/{new["commit"]}'
            before = old['files'] if old else {}
            after = new['files']
            added, deleted = set(after) - set(before), set(before) - set(after)
            modified = {p for p in set(before) & set(after) if before[p] != after[p]}
            lines.append(f'- **{name}**：[{new["commit"][:7]}]({link})；新增 {len(added)}、修改 {len(modified)}、刪除 {len(deleted)} 個檔案。')
    if not updates:
        lines.append('- 上游來源版本沒有變更。')
    histories = [name for name, _ in imports]
    if histories:
        lines.append(f"- 納入 Git 歷史：{', '.join(histories)}。")
    return '\n'.join(lines) + '\n'


def update(root):
    sources, old_lock = load_manifest(root), load_lock(root)
    verify_destinations(root, sources, old_lock)

    git = Git(root)
    if Path(git.text('rev-parse', '--show-toplevel')).resolve() != root.resolve():
        raise ValueError('Update must run from the root of the agent-skills Git repository')
    if git.text('rev-parse', '--is-shallow-repository') == 'true':
        raise ValueError('Fetch the full repository history before running update')
    head = git.text('rev-parse', 'HEAD')
    require_clean(git, head)
    readme = (root / 'README.md').read_text(encoding='utf-8')
    new_lock = {'version': 1, 'sources': {}}
    updates, imports, trees = [], [], {}
    for source in sources:
        name = source['name']
        old = old_lock['sources'].get(name)
        commit, committed_at = git.latest(source)
        tree = git.tree(commit, source['path'])
        trees[name] = tree
        # Existing snapshots may have come from an archive that honors export attributes.
        same_tree = (
            old and old['commit'] == commit and
            git.run('cat-file', '-e', f'{head}:external/{name}', ok=(0, 1, 128)).returncode == 0
            and git.tree(head, f'external/{name}') == tree
        )
        files = old['files'] if same_tree else git.files(tree)
        if not set(source['required_files']).issubset(files):
            raise ValueError(f'{name}: upstream is missing required_files')
        entry = {key: source[key] for key in ('repository', 'ref', 'path')}
        entry.update(commit=commit, committed_at=committed_at, files=files)
        new_lock['sources'][name] = entry
        if old != entry:
            updates.append({'name': name, 'old': old, 'new': entry})
        if not git.ancestor(commit, head):
            imports.append((name, commit))
    for name, old in old_lock['sources'].items():
        if name not in new_lock['sources']:
            updates.append({'name': name, 'old': old, 'new': None})
    new_readme = render_readme(readme, sources, new_lock)

    # Compose and validate the entire commit before changing the working tree or branch.
    with tempfile.TemporaryDirectory(prefix='external-sync-') as folder:
        index = Git(root, index=Path(folder) / 'index')
        index.run('read-tree', head)
        managed = [f'external/{name}' for name in sorted(old_lock['sources'].keys() | trees.keys())]
        tracked = index.run('ls-files', '-z', '--', *managed).stdout
        if tracked:
            index.run('update-index', '--force-remove', '-z', '--stdin', data=tracked)
        for name, tree in trees.items():
            index.run('read-tree', f'--prefix=external/{name}/', tree)
        index.index_text('externals.lock.json', json.dumps(new_lock, ensure_ascii=False, indent=2) + '\n')
        index.index_text('README.md', new_readme)
        tree = index.text('write-tree')

    if tree != git.tree(head, '.') or imports:
        parents = [head, *dict.fromkeys(commit for _, commit in imports)]
        parent_args = [arg for parent in parents for arg in ('-p', parent)]
        candidate = git.text('commit-tree', tree, *parent_args, '-m', 'chore(externals): 同步外部專案來源')
        verify_history(git, candidate, new_lock)
        verify_destinations(root, sources, old_lock)
        require_clean(git, head)
        git.run('merge', '--ff-only', '--no-autostash', '--no-overwrite-ignore', candidate)
    return report(updates, imports)


def require_clean(git, head):
    if git.text('rev-parse', 'HEAD') != head or git.text('status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Use a clean Git working tree to synchronize external sources')


def verify_destinations(root, sources, lock):
    verify_snapshots(root, lock)
    for source in sources:
        name = source['name']
        destination = root / 'external' / name
        if name not in lock['sources'] and (destination.exists() or destination.is_symlink()):
            raise ValueError(f'Refusing to overwrite an unmanaged directory: {destination}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('update', 'check', 'render'))
    parser.add_argument('--history', action='store_true', help='Verify locked upstream commits and Git trees offline')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--report', type=Path, help='Write an update PR body outside the tracked source files')
    args = parser.parse_args()
    if args.history and args.command != 'check':
        parser.error('--history requires check')
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
            lock = check(root, history=args.history)
            counts = Counter({name: len(entry['files']) for name, entry in lock['sources'].items()})
            print(f'PASS {len(counts)} snapshots, {sum(counts.values())} files: hashes, modes, required files and README table')
    except (ValueError, OSError, KeyError, TypeError, yaml.YAMLError) as error:
        print(f'FAIL {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
