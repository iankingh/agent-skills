"""Exercise submodule synchronization with local Git repositories."""

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/sync_externals.py'
spec = importlib.util.spec_from_file_location('sync_externals', SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def git(root, *args, check=True):
    return subprocess.run(
        ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.autocrlf=false', *args],
        cwd=root, check=check, capture_output=True, text=True,
    )


def git_text(root, *args):
    return git(root, *args).stdout.strip()


def init_repo(root):
    root.mkdir()
    git(root, 'init', '-b', 'main')
    git(root, 'config', 'user.name', 'Fixture author')
    git(root, 'config', 'user.email', 'fixture@example.test')


def commit(root, message):
    git(root, 'add', '-A')
    git(root, 'commit', '-m', message)
    return git_text(root, 'rev-parse', 'HEAD')


class SyncTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='test-external-sync-')
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.root = self.directory / 'agent-skills'
        init_repo(self.root)
        self.manifest = {'version': 1, 'sources': [
            {'name': 'alpha', 'path': '.', 'required_files': ['README.md', 'SKILL.md'],
             'description': '用途 A', 'reason': '收藏理由 A', 'trial_status': '待試用'},
            {'name': 'beta', 'path': 'plugin', 'required_files': ['README.md', 'skills/demo/SKILL.md'],
             'description': '用途 B', 'reason': '收藏理由 B', 'trial_status': '待試用'},
        ]}
        self.save_manifest()
        self.readme = self.root / 'README.md'
        self.readme.write_text(f'前段\n\n{sync.START}\n{sync.END}\n\n後段\n', encoding='utf-8')
        self.upstreams = {}
        self.pins = {}
        settings = [('protocol.file.allow', 'always')]
        fixtures = (
            ('alpha', 'author/alpha', 'external/alpha',
             {'README.md': 'alpha readme', 'SKILL.md': 'alpha skill'}),
            ('beta', 'author/plugins', 'external/plugins',
             {'plugin/README.md': 'beta readme', 'plugin/skills/demo/SKILL.md': 'demo',
              'other-plugin/README.md': 'another plugin in the same upstream repo'}),
        )
        for name, repository, path, files in fixtures:
            upstream = self.directory / name
            init_repo(upstream)
            for file, contents in files.items():
                target = upstream / file
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents, encoding='utf-8')
            self.pins[name] = commit(upstream, 'Add upstream files')
            self.upstreams[name] = upstream
            url = f'https://github.com/{repository}.git'
            settings.append((f'url.{upstream.as_uri()}.insteadOf', url))
        config = {'GIT_CONFIG_COUNT': str(len(settings))}
        for index, (key, value) in enumerate(settings):
            config[f'GIT_CONFIG_KEY_{index}'] = key
            config[f'GIT_CONFIG_VALUE_{index}'] = value
        env = patch.dict(os.environ, config)
        env.start()
        self.addCleanup(env.stop)

        for name, repository, path, _ in fixtures:
            git(self.root, 'submodule', 'add', '--name', name, '-b', 'main',
                f'https://github.com/{repository}.git', path)
        self.render()
        self.base = commit(self.root, 'Add pinned external submodules')
        git(self.root / 'external/plugins', 'sparse-checkout', 'set', '--no-cone', '/plugin/')

    def save_manifest(self):
        (self.root / 'externals.yaml').write_text(
            yaml.safe_dump(self.manifest, allow_unicode=True, sort_keys=False), encoding='utf-8',
        )

    def render(self):
        client = sync.Git(self.root)
        sources = sync.load_sources(client)
        pins = sync.read_pins(client, sources)
        self.readme.write_text(sync.render_readme(self.readme.read_text(encoding='utf-8'), sources, pins),
                               encoding='utf-8')

    def advance(self, source, file, text):
        upstream = self.upstreams[source]
        (upstream / file).write_text(text, encoding='utf-8')
        return commit(upstream, f'Update {file}')

    def test_pins_and_real_checkouts_match(self):
        self.assertEqual(sync.check(self.root, checkout=True), self.pins)
        entries = git_text(self.root, 'ls-tree', 'HEAD:external').splitlines()
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(entry.startswith('160000 commit ') for entry in entries))
        self.assertFalse((self.root / 'external/plugins/other-plugin/README.md').exists())

    def test_check_rejects_full_or_wrong_sparse_checkout_at_pinned_commit(self):
        child = self.root / 'external/plugins'
        for args in [('disable',), ('set', '--no-cone', '/other-plugin/')]:
            with self.subTest(args=args):
                git(child, 'sparse-checkout', *args)
                self.assertEqual(git_text(child, 'rev-parse', 'HEAD'), self.pins['beta'])
                self.assertEqual(sync.check(self.root), self.pins)
                with self.assertRaisesRegex(ValueError, 'sparse'):
                    sync.check(self.root, checkout=True)

    def test_check_requires_materialized_files_in_selected_plugin(self):
        child = self.root / 'external/plugins'
        target = 'plugin/README.md'
        git(child, 'update-index', '--skip-worktree', target)
        (child / target).unlink()
        self.assertEqual(git_text(child, 'status', '--porcelain'), '')
        with self.assertRaisesRegex(ValueError, 'plugin/README.md'):
            sync.check(self.root, checkout=True)

    def test_check_rejects_tracked_file_restored_outside_sparse_scope(self):
        child = self.root / 'external/plugins'
        target = 'other-plugin/README.md'
        git(child, 'restore', '--ignore-skip-worktree-bits', '--', target)
        self.assertTrue((child / target).is_file())
        self.assertEqual(git_text(child, 'status', '--porcelain'), '')
        with self.assertRaisesRegex(ValueError, 'other-plugin/README.md'):
            sync.check(self.root, checkout=True)

    def test_initial_checkout_only_expands_the_selected_plugin(self):
        clone = self.directory / 'sparse-clone'
        git(self.directory, 'clone', self.root.as_uri(), str(clone))
        self.assertEqual(sync.checkout(clone), self.pins)

        child = clone / 'external/plugins'
        self.assertEqual({file.name for file in child.iterdir()}, {'.git', 'plugin'})
        self.assertTrue((clone / 'external/alpha/SKILL.md').is_file())
        self.assertEqual(git_text(child, 'sparse-checkout', 'list'), '/plugin/')
        self.assertEqual(git_text(child, 'cat-file', '-t', 'HEAD:other-plugin'), 'tree')
        self.assertEqual(sync.check(clone, checkout=True), self.pins)

    def test_checkout_reuses_a_deinitialized_full_submodule(self):
        path = 'external/plugins'
        git(self.root / path, 'sparse-checkout', 'disable')
        git(self.root, 'submodule', 'deinit', '--', path)
        self.assertEqual(sync.checkout(self.root), self.pins)
        self.assertEqual({file.name for file in (self.root / path).iterdir()}, {'.git', 'plugin'})
        self.assertEqual(sync.check(self.root, checkout=True), self.pins)

    def test_sparse_checkout_preserves_local_edits_outside_selected_plugin(self):
        git(self.root / 'external/plugins', 'sparse-checkout', 'disable')
        target = self.root / 'external/plugins/other-plugin/README.md'
        target.write_text('local edit')
        with self.assertRaisesRegex(ValueError, 'preserve local changes'):
            sync.checkout(self.root)
        self.assertEqual(target.read_text(), 'local edit')

    def test_only_submodule_pins_and_readme_change(self):
        latest_alpha = self.advance('alpha', 'SKILL.md', 'updated skill')
        latest_beta = self.advance('beta', 'plugin/README.md', 'updated readme')
        self.advance('beta', 'other-plugin/README.md', 'unrelated')
        summary = sync.update(self.root)
        self.assertEqual(sync.check(self.root), {'alpha': latest_alpha, 'beta': latest_beta})
        self.assertEqual(git_text(self.root, 'show', '-s', '--format=%P'), self.base)
        self.assertEqual(git_text(self.root, 'diff', '--name-only', 'HEAD^', 'HEAD').splitlines(),
                         ['README.md', 'external/alpha', 'external/plugins'])
        self.assertNotEqual(git(self.root, 'cat-file', '-e', latest_alpha, check=False).returncode, 0)
        self.assertIn(f'/compare/{self.pins["alpha"]}...{latest_alpha}', summary)
        with self.assertRaisesRegex(ValueError, 'checkout differs'):
            sync.check(self.root, checkout=True)
        sync.checkout(self.root)
        self.assertEqual(sync.check(self.root, checkout=True), {'alpha': latest_alpha, 'beta': latest_beta})
        self.assertIn('沒有變更', sync.update(self.root))

    def test_unrelated_upstream_path_does_not_advance_pin(self):
        self.advance('beta', 'other-plugin/README.md', 'unrelated')
        self.assertIn('沒有變更', sync.update(self.root))
        self.assertEqual(git_text(self.root, 'rev-parse', 'HEAD'), self.base)

    def test_fresh_clone_can_update_without_initialized_submodules(self):
        clone = self.directory / 'clone'
        git(self.directory, 'clone', '--depth', '1', self.root.as_uri(), str(clone))
        git(clone, 'config', 'user.name', 'Fixture author')
        git(clone, 'config', 'user.email', 'fixture@example.test')
        self.assertEqual(sync.check(clone), self.pins)
        with self.assertRaisesRegex(ValueError, 'initialize'):
            sync.check(clone, checkout=True)
        latest = self.advance('alpha', 'SKILL.md', 'updated skill')
        sync.update(clone)
        sync.checkout(clone)
        self.assertEqual(sync.check(clone, checkout=True), dict(self.pins, alpha=latest))

    def test_empty_external_can_bootstrap_all_submodule_pins(self):
        git(self.root, 'submodule', 'deinit', '--all')
        git(self.root, 'update-index', '--force-remove', '--', 'external/alpha', 'external/plugins')
        self.render()
        commit(self.root, 'Prepare a clean external directory')
        self.assertEqual(sync.check(self.root), {})
        self.assertIn('待同步', self.readme.read_text())

        summary = sync.update(self.root)
        self.assertEqual(summary.count('建立'), 2)
        self.assertEqual(sync.check(self.root), self.pins)
        sync.checkout(self.root)
        self.assertEqual(sync.check(self.root, checkout=True), self.pins)

    def test_partial_submodule_set_is_rejected(self):
        git(self.root, 'update-index', '--force-remove', '--', 'external/alpha')
        with self.assertRaisesRegex(ValueError, 'submodule paths must match'):
            sync.check(self.root)

    def test_missing_required_file_aborts_all_updates(self):
        self.advance('alpha', 'SKILL.md', 'updated skill')
        upstream = self.upstreams['beta']
        (upstream / 'plugin/skills/demo/SKILL.md').unlink()
        commit(upstream, 'Remove a required skill')
        with self.assertRaisesRegex(ValueError, 'missing required upstream files'):
            sync.update(self.root)
        self.assertEqual(git_text(self.root, 'rev-parse', 'HEAD'), self.base)
        self.assertEqual(sync.check(self.root, checkout=True), self.pins)

    def test_symlink_does_not_satisfy_required_file(self):
        upstream = self.upstreams['alpha']
        (upstream / 'SKILL.md').unlink()
        (upstream / 'SKILL.md').symlink_to('README.md')
        commit(upstream, 'Replace skill with symlink')
        with self.assertRaisesRegex(ValueError, 'missing required upstream files'):
            sync.update(self.root)

    def test_fetch_failure_leaves_all_pins_intact(self):
        self.advance('alpha', 'SKILL.md', 'updated skill')
        self.upstreams['beta'].rename(self.directory / 'missing')
        with self.assertRaisesRegex(ValueError, 'git fetch'):
            sync.update(self.root)
        self.assertEqual(git_text(self.root, 'rev-parse', 'HEAD'), self.base)
        self.assertEqual(sync.check(self.root, checkout=True), self.pins)

    def test_local_changes_in_submodule_are_preserved(self):
        target = self.root / 'external/alpha/SKILL.md'
        target.write_text('local edit')
        with self.assertRaisesRegex(ValueError, 'checkout differs'):
            sync.check(self.root, checkout=True)
        with patch.object(sync.Git, 'latest', side_effect=AssertionError('Unexpected fetch')):
            with self.assertRaisesRegex(ValueError, 'clean Git working tree'):
                sync.update(self.root)
        self.assertEqual(target.read_text(), 'local edit')

    def test_edits_during_fetch_are_preserved(self):
        self.advance('alpha', 'SKILL.md', 'updated skill')
        fetch = sync.Git.latest

        def edit_during_fetch(client, source):
            self.readme.write_text('concurrent edit')
            return fetch(client, source)

        with patch.object(sync.Git, 'latest', edit_during_fetch):
            with self.assertRaisesRegex(ValueError, 'clean Git working tree'):
                sync.update(self.root)
        self.assertEqual(self.readme.read_text(), 'concurrent edit')
        self.assertEqual(git_text(self.root, 'rev-parse', 'HEAD'), self.base)

    def test_invalid_submodule_config_is_rejected(self):
        git(self.root, 'config', '-f', '.gitmodules', 'submodule.alpha.url', 'file:///tmp/untrusted')
        with self.assertRaisesRegex(ValueError, 'invalid URL'):
            sync.check(self.root)

    def test_legacy_snapshot_entries_are_rejected(self):
        path = self.root / 'external/legacy'
        path.mkdir()
        (path / 'README.md').write_text('legacy file')
        git(self.root, 'add', str(path))
        with self.assertRaisesRegex(ValueError, 'Expected a Git submodule pin'):
            sync.check(self.root)

    def test_render_refreshes_table_and_preserves_other_readme_text(self):
        self.manifest['sources'][0]['description'] = '新的介紹 | 表格'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'table is stale'):
            sync.check(self.root)
        self.render()
        text = self.readme.read_text()
        self.assertTrue(text.startswith('前段\n\n'))
        self.assertTrue(text.endswith('\n\n後段\n'))
        self.assertIn('新的介紹 \\| 表格', text)
        self.assertEqual(sync.check(self.root), self.pins)


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
        self.assertEqual(workflow['on']['schedule'], [{'cron': '17 1 * * MON'}])
        self.assertIn('workflow_dispatch', workflow['on'])
        self.assertEqual(workflow['permissions'], {'contents': 'write', 'pull-requests': 'write'})
        self.assertIn("github.event_name == 'workflow_dispatch'", workflow['jobs']['sync']['if'])
        steps = workflow['jobs']['sync']['steps']
        check_index = next(i for i, step in enumerate(steps)
                           if 'scripts/sync_externals.py check --checkout' in step.get('run', ''))
        publish_index = next(i for i, step in enumerate(steps) if 'origin_git push' in step.get('run', ''))
        self.assertLess(check_index, publish_index)
        self.assertIn('scripts/sync_externals.py checkout', steps[check_index]['run'])
        self.assertEqual(steps[publish_index]['if'],
                         "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)")
        self.assertEqual(steps[publish_index]['env']['SYNC_BRANCH'], 'codex/sync-external-skills')
        self.assertIn('origin "HEAD:$sync_ref"', steps[publish_index]['run'])


if __name__ == '__main__':
    unittest.main()
