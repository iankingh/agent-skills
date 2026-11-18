#!/usr/bin/env python3
"""Update external Git submodule pins without executing upstream code."""

import argparse
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
SHA = re.compile(r'[0-9a-f]{40}')
NAME = r'[a-z0-9]+(?:-[a-z0-9]+)*'
URL = re.compile(r'https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\.git')


class Git:
    def __init__(self, root, index=None):
        self.root = root
        self.env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_NO_REPLACE_OBJECTS='1')
        if index is not None:
            self.env['GIT_INDEX_FILE'] = str(index)

    def run(self, *args, data=None):
        result = subprocess.run(
            ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.autocrlf=false',
             '-c', 'core.filemode=true', '-c', 'submodule.recurse=false',
             '-c', 'credential.helper=', *args],
            cwd=self.root, env=self.env, input=data, capture_output=True,
        )
        if result.returncode:
            message = result.stderr or result.stdout
            raise ValueError(f'git {args[0]}: {message.decode(errors="replace").strip()}')
        return result.stdout

    def text(self, *args):
        return self.run(*args).decode().strip()

    def latest(self, source):
        self.run('fetch', '--no-tags', '--no-recurse-submodules', '--', source['url'],
                 f'refs/heads/{source["ref"]}')
        args = ['log', '-1', '--format=%H', 'FETCH_HEAD']
        if source['path'] != '.':
            args.extend(['--', f':(top,literal){source["path"]}'])
        commit = self.text(*args)
        if not SHA.fullmatch(commit):
            raise ValueError(f'{source["name"]}: no upstream commit for the configured branch and path')
        return commit

    def index_text(self, path, text):
        blob = self.run('hash-object', '-w', '--stdin', data=text.encode()).decode().strip()
        self.run('update-index', '--add', '--cacheinfo', f'100644,{blob},{path}')


def relative_path(value, allow_root=False):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError(f'Invalid relative path: {value!r}')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part.lower() in ('..', '.git') for part in path.parts) or any(ord(c) < 32 for c in value):
        raise ValueError(f'Unsafe relative path: {value!r}')
    if str(path) == '.' and not allow_root:
        raise ValueError('A file path must not be the root directory')
    return str(path)


def read_modules(git):
    raw = git.run('config', '--no-includes', '--file', '.gitmodules', '--null', '--list')
    modules = {}
    for record in raw.decode().split('\0')[:-1]:
        key, value = record.split('\n', 1)
        match = re.fullmatch(rf'submodule\.({NAME})\.(path|url|branch)', key)
        if not match or not value:
            raise ValueError(f'Invalid .gitmodules setting: {key}')
        name, field = match.groups()
        config = modules.setdefault(name, {})
        if field in config:
            raise ValueError(f'Duplicate .gitmodules setting: {key}')
        config[field] = value
    return modules


def load_sources(git):
    data = yaml.safe_load((git.root / 'externals.yaml').read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('sources'), list):
        raise ValueError('externals.yaml must contain version: 1 and a sources list')
    modules = read_modules(git)
    sources = {}
    paths = set()
    for source in data['sources']:
        if not isinstance(source, dict):
            raise ValueError('Each source must be a mapping')
        for key in ('name', 'path', 'description', 'reason', 'trial_status'):
            value = source.get(key)
            if not isinstance(value, str) or not value.strip() or '\n' in value or '\r' in value:
                raise ValueError(f'Invalid source field: {key}')
        name = source['name']
        if name in sources or name not in modules:
            raise ValueError(f'Duplicate source or missing submodule: {name}')
        module = modules[name]
        url = URL.fullmatch(module.get('url', ''))
        path = module.get('path', '')
        branch = module.get('branch', '')
        if not url or not re.fullmatch(rf'external/{NAME}', path) or path in paths or not branch:
            raise ValueError(f'{name}: invalid URL, path or branch in .gitmodules')
        git.run('check-ref-format', f'refs/heads/{branch}')
        paths.add(path)
        required = source.get('required_files')
        if not isinstance(required, list) or not required:
            raise ValueError(f'{name}: required_files must be a nonempty list')
        sources[name] = dict(source, path=relative_path(source['path'], allow_root=True),
                             required_files=[relative_path(file) for file in required],
                             module_path=path, url=module['url'], repository=url.group(1), ref=branch)
    if not sources or sources.keys() != modules.keys():
        raise ValueError('externals.yaml source names must match .gitmodules')
    return sources


def read_pins(git, sources):
    pins_by_path = {}
    raw = git.run('ls-files', '--stage', '-z', '--', 'external/')
    for record in raw.decode().split('\0')[:-1]:
        info, path = record.split('\t', 1)
        mode, commit, stage = info.split()
        if mode != '160000' or stage != '0' or not SHA.fullmatch(commit):
            raise ValueError(f'Expected a Git submodule pin: {path}')
        pins_by_path[path] = commit
    if not pins_by_path:
        return {}
    if pins_by_path.keys() != {source['module_path'] for source in sources.values()}:
        raise ValueError('Git index submodule paths must match .gitmodules')
    return {name: pins_by_path[source['module_path']] for name, source in sources.items()}


def verify_required_files(git, source, commit):
    prefix = PurePosixPath(source['path'])
    required = {str(prefix / file) for file in source['required_files']}
    paths = [f':(top,literal){file}' for file in sorted(required)]
    entries = git.run('ls-tree', '--full-tree', '-rz', commit, '--', *paths)
    for record in entries.decode().split('\0')[:-1]:
        info, path = record.split('\t', 1)
        if info.split()[0] in ('100644', '100755'):
            required.discard(path)
    if required:
        raise ValueError(f'{source["name"]}: missing required upstream files: {", ".join(sorted(required))}')


def render_readme(text, sources, pins):
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise ValueError('README must contain exactly one ordered EXTERNALS marker pair')
    lines = ['| 項目 | 用途 | 收藏理由 | 試用狀態 | 鎖定版本 |',
             '| --- | --- | --- | --- | --- |']
    for name, source in sources.items():
        repo = f'https://github.com/{source["repository"]}'
        commit = pins.get(name)
        versioned_path = f'{repo}/tree/{commit or source["ref"]}'
        if source['path'] != '.':
            versioned_path += f'/{source["path"]}'
        cells = [f'[{name}]({versioned_path})', source['description'], source['reason'],
                 source['trial_status'], f'[{commit[:7]}]({repo}/commit/{commit})' if commit else '待同步']
        lines.append('| ' + ' | '.join(cell.replace('|', '\\|') for cell in cells) + ' |')
    before, rest = text.split(START)
    _, after = rest.split(END)
    return before + START + '\n\n' + '\n'.join(lines) + '\n\n' + END + after


def unmodified(git):
    return not git.text('status', '--porcelain', '--untracked-files=no', '--ignore-submodules=none')


def sparse_pattern(path):
    escaped = re.sub(r'([*?\[\]])', r'\\\1', path)
    return f'/{escaped}/\n'.encode()


def verify_sparse_checkout(child, source):
    path = source['path']
    if child.run('sparse-checkout', 'list') != sparse_pattern(path):
        raise ValueError(f'{source["name"]}: expected sparse checkout of {path}/')
    for file in source['required_files']:
        target = child.root / path / file
        if not target.is_file() or target.is_symlink():
            raise ValueError(f'{source["name"]}: missing required checkout file: {path}/{file}')
    outside = child.run('ls-files', '-z', '--', f':(top,exclude,literal){path}')
    for file in os.fsdecode(outside).split('\0')[:-1]:
        if os.path.lexists(child.root / file):
            raise ValueError(f'{source["name"]}: tracked path outside sparse checkout: {file}')


def checkout(root):
    git = Git(root)
    sources = load_sources(git)
    pins = read_pins(git, sources)
    update = ('-c', 'protocol.allow=never', '-c', 'protocol.https.allow=always',
              'submodule', 'update', '--init', '--checkout')
    for name in pins:
        source = sources[name]
        path = source['module_path']
        if source['path'] == '.':
            git.run(*update, '--', path)
            continue

        child = Git(root / path)
        if child.root.is_symlink() or (root / 'external').is_symlink():
            raise ValueError(f'{name}: expected a submodule directory')
        patterns = sparse_pattern(source['path'])
        if (child.root / '.git').exists():
            if child.text('status', '--porcelain', '--untracked-files=all', '--ignored=matching'):
                raise ValueError(f'{name}: preserve local changes before changing the checkout scope')
            child.run('sparse-checkout', 'set', '--no-cone', '--stdin', data=patterns)
            git.run(*update, '--', path)
            continue

        # Set the pattern before Git's first checkout, including when reusing a deinitialized submodule.
        storage = Path(git.text('rev-parse', '--path-format=absolute', '--git-path', f'modules/{name}'))
        with tempfile.TemporaryDirectory(prefix='external-checkout-') as template:
            pattern_file = (storage if storage.is_dir() else Path(template)) / 'info/sparse-checkout'
            pattern_file.parent.mkdir(parents=True, exist_ok=True)
            pattern_file.write_bytes(patterns)
            git.run('-c', f'init.templateDir={template}', '-c', 'core.sparseCheckout=true',
                    '-c', 'core.sparseCheckoutCone=false', *update, '--filter=blob:none', '--', path)
        child.run('sparse-checkout', 'set', '--no-cone', '--stdin', data=patterns)
    return pins


def check(root, checkout=False):
    git = Git(root)
    sources = load_sources(git)
    pins = read_pins(git, sources)
    text = (root / 'README.md').read_text(encoding='utf-8')
    if render_readme(text, sources, pins) != text:
        raise ValueError('Generated README table is stale; run render')
    if checkout:
        for name, commit in pins.items():
            source = sources[name]
            child = Git(root / source['module_path'])
            if not (child.root / '.git').exists():
                raise ValueError(f'{name}: initialize with scripts/sync_externals.py checkout')
            if child.text('rev-parse', 'HEAD') != commit or not unmodified(child):
                raise ValueError(f'{name}: checkout differs from its pinned Git commit')
            verify_required_files(child, source, commit)
            if source['path'] != '.':
                verify_sparse_checkout(child, source)
    return pins


def report(sources, old_pins, new_pins):
    lines = ['## 外部專案 submodule 更新', '']
    for name, source in sources.items():
        old, new = old_pins.get(name), new_pins[name]
        repo = f'https://github.com/{source["repository"]}'
        if old is None:
            lines.append(f'- **{name}**：建立 [{new[:7]}]({repo}/commit/{new})')
        elif new != old:
            link = f'{repo}/compare/{old}...{new}'
            lines.append(f'- **{name}**：[{old[:7]} → {new[:7]}]({link})')
    if old_pins == new_pins:
        lines.append('- 外部專案的鎖定版本沒有變更。')
    return '\n'.join(lines) + '\n'


def require_clean(git, head):
    if git.text('rev-parse', 'HEAD') != head or not unmodified(git):
        raise ValueError('Use a clean Git working tree to update submodule pins')


def update(root):
    git = Git(root)
    if Path(git.text('rev-parse', '--show-toplevel')).resolve() != root.resolve():
        raise ValueError('Update must run from the root of the agent-skills Git repository')
    head = git.text('rev-parse', 'HEAD')
    require_clean(git, head)
    sources = load_sources(git)
    old_pins = read_pins(git, sources)
    readme = (root / 'README.md').read_text(encoding='utf-8')

    # Fetch upstream objects separately and build the complete commit in a temporary index.
    with tempfile.TemporaryDirectory(prefix='external-sync-') as folder:
        upstream = Git(Path(folder))
        upstream.run('init', '--bare', '--quiet')
        pins = {}
        for name, source in sources.items():
            pins[name] = upstream.latest(source)
            verify_required_files(upstream, source, pins[name])
        index = Git(root, index=Path(folder) / 'agent-skills-index')
        index.run('read-tree', head)
        for name, source in sources.items():
            index.run('update-index', '--add', '--cacheinfo', f'160000,{pins[name]},{source["module_path"]}')
        index.index_text('README.md', render_readme(readme, sources, pins))
        tree = index.text('write-tree')

    if tree != git.text('rev-parse', f'{head}^{{tree}}'):
        message = 'chore(externals): 更新外部專案 submodule 版本'
        candidate = git.text('commit-tree', tree, '-p', head, '-m', message)
        require_clean(git, head)
        git.run('merge', '--ff-only', '--no-autostash', '--no-overwrite-ignore', candidate)
    return report(sources, old_pins, pins)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('update', 'checkout', 'check', 'render'))
    parser.add_argument('--checkout', action='store_true', help='Also verify local, initialized submodules')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--report', type=Path, help='Write a PR body outside the tracked source files')
    args = parser.parse_args()
    if args.checkout and args.command != 'check':
        parser.error('--checkout requires check')
    root = args.root.resolve()
    try:
        if args.command == 'update':
            summary = update(root)
            print(summary)
            if args.report:
                args.report.write_text(summary, encoding='utf-8')
        elif args.command == 'checkout':
            pins = checkout(root)
            print(f'Checked out {len(pins)} pinned submodules.')
        elif args.command == 'render':
            git = Git(root)
            sources = load_sources(git)
            readme = root / 'README.md'
            text = readme.read_text(encoding='utf-8')
            new_text = render_readme(text, sources, read_pins(git, sources))
            if new_text != text:
                readme.write_text(new_text, encoding='utf-8')
            print('README external table rendered.')
        else:
            pins = check(root, checkout=args.checkout)
            if pins:
                details = ', checkouts and required files' if args.checkout else ''
                print(f'PASS {len(pins)} submodule pins and README table{details}')
            else:
                print('PASS submodule configuration and README table; awaiting initial synchronization')
    except (ValueError, OSError, yaml.YAMLError) as error:
        print(f'FAIL {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
