"""Exercise synchronization with local Git repositories."""

import copy
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/sync_externals.py'
spec = importlib.util.spec_from_file_location('sync_externals', SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def git(root, *args):
    return subprocess.run(
        ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.autocrlf=false', *args],
        cwd=root, check=True, capture_output=True, text=True,
    ).stdout.strip()


def init_repo(root):
    root.mkdir(exist_ok=True)
    git(root, 'init', '-b', 'main')
    git(root, 'config', 'user.name', 'Fixture author')
    git(root, 'config', 'user.email', 'fixture@example.test')


def save_files(root, files):
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data, mode = value if isinstance(value, tuple) else (value, 0o644)
        path.write_bytes(data)
        path.chmod(mode)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='test-external-sync-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'agent-skills'
        init_repo(self.root)
        git(self.root, 'config', 'protocol.file.allow', 'always')
        self.manifest = {'version': 1, 'sources': [
            {'name': 'alpha', 'repository': 'example/alpha', 'ref': 'main', 'path': '.',
             'required_files': ['README.md', 'SKILL.md'], 'description': '用途 A',
             'reason': '收藏理由 A', 'trial_status': '待試用'},
            {'name': 'beta', 'repository': 'example/plugins', 'ref': 'main', 'path': 'plugin',
             'required_files': ['README.md', '.cursor-plugin/plugin.json', 'skills/demo/SKILL.md'],
             'description': '用途 B', 'reason': '收藏理由 B', 'trial_status': '待試用'}]}
        self.save_manifest()
        self.readme = '人工維護的開頭\n\n' + sync.START + '\nold table\n' + sync.END + '\n\n人工維護的結尾\n'
        (self.root / 'README.md').write_text(self.readme)
        save_files(self.root, {'skills/local/SKILL.md': b'local skill\n'})
        self.base = self.commit(self.root, 'Own skills')
        self.upstreams = {}
        for source, files in zip(self.manifest['sources'], (
            {'README.md': b'alpha readme\n', 'SKILL.md': b'alpha skill\n',
             'LICENSE': b'fixture license\n', 'old.txt': b'old\n'},
            {'plugin/README.md': b'beta readme\n', 'plugin/skills/demo/SKILL.md': b'demo\n',
             'plugin/assets/icon.bin': b'\x00\xff\x01',
             'plugin/install.sh': (b'#!/bin/sh\ntouch should-not-run\n', 0o755),
             'plugin/.cursor-plugin/plugin.json': b'{"name":"beta"}\n',
             'plugin/.gitignore': b'assets/\n',
             'plugin/.gitattributes': b'assets/icon.bin export-ignore\n',
             'other-plugin/SKILL.md': b'must not be copied\n',
             'plugin-extra/README.md': b'also excluded\n'},
        )):
            upstream = Path(self.temp.name) / source['name']
            init_repo(upstream)
            git(upstream, 'commit', '--allow-empty', '-m', 'Upstream root')
            save_files(upstream, files)
            self.commit(upstream, 'Add skills')
            self.upstreams[source['name']] = upstream
            git(self.root, 'config', f'url.{upstream.as_uri()}.insteadOf',
                f'https://github.com/{source["repository"]}.git')

    def commit(self, root, message):
        git(root, 'add', '--force', '--all')
        git(root, 'commit', '-m', message)
        return git(root, 'rev-parse', 'HEAD')

    def update_upstream(self, name, files):
        upstream = self.upstreams[name]
        save_files(upstream, files)
        return self.commit(upstream, 'Update skills')

    def save_manifest(self):
        (self.root / 'externals.yaml').write_text(yaml.safe_dump(self.manifest, allow_unicode=True, sort_keys=False))

    def state(self):
        files = {p.relative_to(self.root).as_posix(): (p.read_bytes(), bool(p.stat().st_mode & 0o111))
                 for p in self.root.rglob('*') if p.is_file() and '.git' not in p.relative_to(self.root).parts}
        return git(self.root, 'rev-parse', 'HEAD'), files

    def bootstrap(self):
        return sync.update(self.root)

    def test_initial_sync_copies_full_selected_tree_and_preserves_bytes_modes(self):
        body = self.bootstrap()
        lock = sync.check(self.root, history=True)
        self.assertEqual(set(lock['sources']), {'alpha', 'beta'})
        self.assertEqual((self.root / 'external/beta/assets/icon.bin').read_bytes(), b'\x00\xff\x01')
        self.assertTrue((self.root / 'external/beta/install.sh').stat().st_mode & 0o111)
        self.assertFalse((self.root / 'should-not-run').exists())
        self.assertFalse((self.root / 'external/beta/other-plugin').exists())
        self.assertFalse((self.root / 'external/beta/plugin-extra').exists())
        self.assertEqual(lock['sources']['alpha']['files']['SKILL.md']['sha256'], hashlib.sha256(b'alpha skill\n').hexdigest())
        self.assertIn('新增 4', body)
        commits = [git(upstream, 'rev-parse', 'HEAD') for upstream in self.upstreams.values()]
        self.assertEqual(git(self.root, 'show', '-s', '--format=%P').split(), [self.base, *commits])
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD^1'), self.base)
        for upstream, commit in zip(self.upstreams.values(), commits):
            self.assertEqual(git(self.root, 'show', '-s', '--format=%an <%ae>', commit),
                             git(upstream, 'show', '-s', '--format=%an <%ae>', commit))
            git(self.root, 'merge-base', '--is-ancestor', f'{commit}^', 'HEAD')
        self.assertEqual(git(self.root, 'diff', self.base, 'HEAD', '--', 'skills'), '')
        self.assertTrue((self.root / 'README.md').read_text().startswith('人工維護的開頭'))
        self.assertTrue((self.root / 'README.md').read_text().endswith('人工維護的結尾\n'))

    def test_unchanged_upstream_produces_no_file_diff_or_commit(self):
        self.bootstrap()
        before = self.state()
        body = self.bootstrap()
        self.assertEqual(before, self.state())
        self.assertIn('沒有變更', body)

    def test_update_replaces_modifications_additions_and_upstream_deletions(self):
        self.bootstrap()
        previous = git(self.upstreams['alpha'], 'rev-parse', 'HEAD')
        (self.upstreams['alpha'] / 'old.txt').unlink()
        latest = self.update_upstream('alpha', {
            'SKILL.md': b'new skill\n',
            'references/guide.md': b'guide\n',
        })
        body = self.bootstrap()
        self.assertEqual((self.root / 'external/alpha/SKILL.md').read_bytes(), b'new skill\n')
        self.assertTrue((self.root / 'external/alpha/references/guide.md').exists())
        self.assertFalse((self.root / 'external/alpha/old.txt').exists())
        self.assertIn(f'/compare/{previous}...{latest}', body)
        self.assertIn('新增 1、修改 1、刪除 1', body)
        sync.check(self.root)

    def test_local_edits_are_preserved_and_update_stops_before_network(self):
        self.bootstrap()
        target = self.root / 'external/alpha/SKILL.md'
        target.write_text('local work\n')
        before = self.state()
        with patch.object(sync.Git, 'latest', side_effect=AssertionError('Unexpected fetch')):
            with self.assertRaisesRegex(ValueError, 'local snapshot differs'):
                self.bootstrap()
        self.assertEqual(before, self.state())

    def test_added_local_file_or_missing_file_fails_offline_check(self):
        self.bootstrap()
        for name, added in [('local.txt', True), ('old.txt', False)]:
            with self.subTest(name=name):
                target = self.root / 'external/alpha' / name
                original = target.read_bytes() if target.exists() else None
                target.write_bytes(b'local\n') if added else target.unlink()
                with self.assertRaisesRegex(ValueError, 'local snapshot differs'):
                    sync.check(self.root)
                if original is None:
                    target.unlink()
                else:
                    target.write_bytes(original)

    def test_mode_changes_are_detected(self):
        self.bootstrap()
        (self.root / 'external/beta/install.sh').chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'local snapshot differs'):
            sync.check(self.root)

    def test_unmanaged_destination_is_never_overwritten(self):
        target = self.root / 'external/alpha'
        target.mkdir(parents=True)
        (target / 'local.txt').write_text('keep\n')
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'unmanaged'):
            self.bootstrap()
        self.assertEqual(before, self.state())

    def test_fetch_failure_leaves_all_existing_sources_intact(self):
        self.bootstrap()
        self.update_upstream('alpha', {'SKILL.md': b'new upstream version\n'})
        self.upstreams['beta'].rename(self.upstreams['beta'].with_name('moved'))
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'fetch'):
            self.bootstrap()
        self.assertEqual(before, self.state())

    def test_edits_during_fetch_are_preserved(self):
        self.bootstrap()
        self.update_upstream('alpha', {'SKILL.md': b'new upstream version\n'})
        fetch = sync.Git.latest
        for name, pattern in [('external/alpha/SKILL.md', 'local snapshot differs'),
                              ('README.md', 'clean Git working tree')]:
            with self.subTest(name=name):
                target = self.root / name
                original = target.read_bytes()
                old_lock = (self.root / 'externals.lock.json').read_bytes()
                old_head = git(self.root, 'rev-parse', 'HEAD')

                def edit_during_fetch(client, source):
                    target.write_bytes(b'concurrent local edit\n')
                    return fetch(client, source)

                with patch.object(sync.Git, 'latest', edit_during_fetch):
                    with self.assertRaisesRegex(ValueError, pattern):
                        self.bootstrap()
                self.assertEqual(target.read_bytes(), b'concurrent local edit\n')
                self.assertEqual((self.root / 'externals.lock.json').read_bytes(), old_lock)
                self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), old_head)
                target.write_bytes(original)

    def test_missing_required_file_preserves_previous_snapshot(self):
        self.bootstrap()
        upstream = self.upstreams['beta']
        (upstream / 'plugin/skills/demo/SKILL.md').unlink()
        self.commit(upstream, 'Remove required file')
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'required_files'):
            self.bootstrap()
        self.assertEqual(before, self.state())

    def test_commit_failure_does_not_replace_sources_lock_or_readme(self):
        self.bootstrap()
        self.update_upstream('alpha', {'SKILL.md': b'new\n'})
        before = self.state()
        run = sync.Git.run

        def fail_commit(client, command, *args, **kwargs):
            if command == 'commit-tree':
                raise OSError('simulated commit failure')
            return run(client, command, *args, **kwargs)

        with patch.object(sync.Git, 'run', fail_commit):
            with self.assertRaisesRegex(OSError, 'simulated commit failure'):
                self.bootstrap()
        self.assertEqual(before, self.state())

    def test_manifest_text_edits_render_without_overwriting_human_sections(self):
        self.bootstrap()
        self.manifest['sources'][0]['description'] = '新的用途 | 保留欄位'
        self.manifest['sources'][0]['trial_status'] = '已試用'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'table is stale'):
            sync.check(self.root)
        result = subprocess.run([sys.executable, '-B', str(SCRIPT), 'render', '--root', str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (self.root / 'README.md').read_text()
        self.assertIn('新的用途 \\| 保留欄位', text)
        self.assertIn('已試用', text)
        self.assertTrue(text.startswith('人工維護的開頭'))
        sync.check(self.root)

    def test_removed_manifest_source_removes_only_its_managed_snapshot(self):
        self.bootstrap()
        removed = git(self.upstreams['beta'], 'rev-parse', 'HEAD')
        self.manifest['sources'].pop()
        self.save_manifest()
        self.commit(self.root, 'Remove beta from manifest')
        body = self.bootstrap()
        git(self.root, 'merge-base', '--is-ancestor', removed, 'HEAD')
        self.assertFalse((self.root / 'external/beta').exists())
        self.assertTrue((self.root / 'external/alpha/SKILL.md').exists())
        self.assertIn('依來源清單移除', body)
        sync.check(self.root)

    def test_invalid_manifest_paths_names_and_duplicates_are_rejected(self):
        original = copy.deepcopy(self.manifest)
        for field, value in [('path', '../escape'), ('path', '/absolute'), ('path', '.git/test'), ('name', '../alpha'),
                             ('repository', 'https://example.com/a'), ('required_files', ['../bad']),
                             ('description', 'line\nbreak')]:
            with self.subTest(field=field, value=value):
                self.manifest = copy.deepcopy(original)
                self.manifest['sources'][0][field] = value
                self.save_manifest()
                with self.assertRaises(ValueError):
                    sync.load_manifest(self.root)
        self.manifest = original
        self.manifest['sources'].append(copy.deepcopy(original['sources'][0]))
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            sync.load_manifest(self.root)

    def test_links_and_gitlinks_in_upstream_tree_are_rejected(self):
        self.bootstrap()
        upstream = self.upstreams['alpha']
        (upstream / 'link').symlink_to('/outside')
        self.commit(upstream, 'Add symbolic link')
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'link or special file'):
            self.bootstrap()
        self.assertEqual(before, self.state())

        (upstream / 'link').unlink()
        git(upstream, 'add', '--all')
        commit = git(self.upstreams['beta'], 'rev-parse', 'HEAD')
        git(upstream, 'update-index', '--add', '--cacheinfo', f'160000,{commit},gitlink')
        git(upstream, 'commit', '-m', 'Add Git submodule entry')
        with self.assertRaisesRegex(ValueError, 'link or special file'):
            self.bootstrap()
        self.assertEqual(before, self.state())

    def test_missing_readme_markers_stops_before_replacing_existing_files(self):
        self.bootstrap()
        (self.root / 'README.md').write_text('no markers\n')
        self.commit(self.root, 'Remove generated table markers')
        before = self.state()
        self.update_upstream('alpha', {'SKILL.md': b'new\n'})
        with self.assertRaisesRegex(ValueError, 'marker pair'):
            self.bootstrap()
        self.assertEqual(before, self.state())

    def test_offline_cli_check_fails_on_corruption(self):
        self.bootstrap()
        run = lambda: subprocess.run([sys.executable, '-B', str(SCRIPT), 'check', '--root', str(self.root)], capture_output=True, text=True)
        self.assertEqual(run().returncode, 0)
        (self.root / 'external/alpha/SKILL.md').write_text('corruption\n')
        failed = run()
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn('local snapshot differs', failed.stderr)

    def test_latest_commit_ignores_changes_outside_monorepo_path(self):
        self.bootstrap()
        before = self.state()
        unrelated = self.update_upstream('beta', {'other-plugin/SKILL.md': b'outside plugin\n'})
        self.bootstrap()
        self.assertEqual(before, self.state())
        self.assertFalse(sync.Git(self.root).ancestor(unrelated, 'HEAD'))

    def test_unchanged_legacy_snapshot_imports_history_and_survives_a_fresh_clone(self):
        self.bootstrap()
        git(self.root, 'reset', '--soft', self.base)
        legacy = self.commit(self.root, 'Legacy snapshot without upstream parents')
        with self.assertRaisesRegex(ValueError, 'not in the synchronization history'):
            sync.check(self.root, history=True)

        self.assertIn('納入 Git 歷史', self.bootstrap())
        self.assertEqual(git(self.root, 'diff', legacy, 'HEAD'), '')
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD^1'), legacy)
        clone = Path(self.temp.name) / 'fresh-clone'
        git(self.root, 'clone', '--no-local', str(self.root), str(clone))
        sync.check(clone, history=True)

    def test_selected_file_limit_fails_before_installing(self):
        with patch.object(sync, 'MAX_CONTENT', 2):
            with self.assertRaisesRegex(ValueError, 'extraction limit'):
                self.bootstrap()


class WorkflowTests(unittest.TestCase):
    def test_workflow_yaml_and_shell_commands_are_valid(self):
        for path in sorted((SCRIPT.parents[1] / '.github/workflows').glob('*.yml')):
            with self.subTest(path=path.name):
                workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
                self.assertIn('on', workflow)
                for job in workflow['jobs'].values():
                    for step in job['steps']:
                        if 'uses' in step:
                            self.assertRegex(step['uses'], r'@[0-9a-f]{40}$')
                        if 'run' in step:
                            result = subprocess.run(['bash', '-n'], input=step['run'], text=True, capture_output=True)
                            self.assertEqual(result.returncode, 0, result.stderr)

    def test_weekly_and_manual_triggers_and_scoped_pr_publication(self):
        path = SCRIPT.parents[1] / '.github/workflows/sync-externals.yml'
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(workflow['on']['schedule'][0]['cron'], '17 1 * * 1')
        self.assertIn('workflow_dispatch', workflow['on'])
        self.assertEqual(workflow['permissions'], {'contents': 'write', 'pull-requests': 'write'})
        steps = workflow['jobs']['sync']['steps']
        check_index = next(i for i, step in enumerate(steps) if step.get('run') == 'python -B scripts/sync_externals.py check --history')
        publish_index = next(i for i, step in enumerate(steps) if 'origin_git push' in step.get('run', ''))
        self.assertLess(check_index, publish_index)
        self.assertEqual(steps[publish_index]['env']['SYNC_BRANCH'], 'codex/sync-external-skills')
        self.assertEqual(steps[0]['with']['fetch-depth'], '0')
        self.assertIn('origin "HEAD:$sync_ref"', steps[publish_index]['run'])


if __name__ == '__main__':
    unittest.main()
