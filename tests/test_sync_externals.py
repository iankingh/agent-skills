"""Exercise source updates using local archives; never execute downloaded code."""

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import yaml


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/sync_externals.py'
spec = importlib.util.spec_from_file_location('sync_externals', SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def archive(files, special=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as tar:
        root = tarfile.TarInfo('source-commit/')
        root.type = tarfile.DIRTYPE
        tar.addfile(root)
        for path, value in files.items():
            data, mode = value if isinstance(value, tuple) else (value, 0o644)
            member = tarfile.TarInfo('source-commit/' + path)
            member.size, member.mode = len(data), mode
            tar.addfile(member, io.BytesIO(data))
        if special:
            tar.addfile(special)
    return output.getvalue()


class FixtureGitHub:
    def __init__(self):
        self.commits = {'alpha': 'a' * 40, 'beta': 'b' * 40}
        self.files = {
            'alpha': {'README.md': b'alpha readme\n', 'SKILL.md': b'alpha skill\n',
                      'LICENSE': b'fixture license\n', 'old.txt': b'old\n'},
            'beta': {'plugin/README.md': b'beta readme\n', 'plugin/skills/demo/SKILL.md': b'demo\n',
                     'plugin/assets/icon.bin': b'\x00\xff\x01',
                     'plugin/install.sh': (b'#!/bin/sh\ntouch should-not-run\n', 0o755),
                     'plugin/.cursor-plugin/plugin.json': b'{"name":"beta"}\n',
                     'other-plugin/SKILL.md': b'must not be copied\n',
                     'plugin-extra/README.md': b'also excluded\n'}}
        self.downloads = []

    def latest(self, source):
        return self.commits[source['name']], '2026-10-31T01:00:00Z'

    def archive(self, source, commit):
        self.downloads.append(source['name'])
        return archive(self.files[source['name']])


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='test-external-sync-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
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
        self.client = FixtureGitHub()

    def save_manifest(self):
        (self.root / 'externals.yaml').write_text(yaml.safe_dump(self.manifest, allow_unicode=True, sort_keys=False))

    def state(self):
        return {p.relative_to(self.root).as_posix(): (p.read_bytes(), bool(p.stat().st_mode & 0o111))
                for p in self.root.rglob('*') if p.is_file()}

    def bootstrap(self):
        return sync.update(self.root, self.client)

    def test_initial_sync_copies_full_selected_tree_and_preserves_bytes_modes(self):
        body = self.bootstrap()
        lock = sync.check(self.root)
        self.assertEqual(set(lock['sources']), {'alpha', 'beta'})
        self.assertEqual((self.root / 'external/beta/assets/icon.bin').read_bytes(), b'\x00\xff\x01')
        self.assertTrue((self.root / 'external/beta/install.sh').stat().st_mode & 0o111)
        self.assertFalse((self.root / 'should-not-run').exists())
        self.assertFalse((self.root / 'external/beta/other-plugin').exists())
        self.assertFalse((self.root / 'external/beta/plugin-extra').exists())
        self.assertEqual(lock['sources']['alpha']['files']['SKILL.md']['sha256'], hashlib.sha256(b'alpha skill\n').hexdigest())
        self.assertIn('新增 4', body)
        self.assertTrue((self.root / 'README.md').read_text().startswith('人工維護的開頭'))
        self.assertTrue((self.root / 'README.md').read_text().endswith('人工維護的結尾\n'))

    def test_unchanged_upstream_produces_no_file_diff_or_repeat_download(self):
        self.bootstrap()
        before = self.state()
        self.client.downloads.clear()
        body = sync.update(self.root, self.client)
        self.assertEqual(before, self.state())
        self.assertEqual(self.client.downloads, [])
        self.assertIn('沒有變更', body)

    def test_update_replaces_modifications_additions_and_upstream_deletions(self):
        self.bootstrap()
        self.client.commits['alpha'] = 'c' * 40
        self.client.files['alpha']['SKILL.md'] = b'new skill\n'
        self.client.files['alpha']['references/guide.md'] = b'guide\n'
        del self.client.files['alpha']['old.txt']
        body = sync.update(self.root, self.client)
        self.assertEqual((self.root / 'external/alpha/SKILL.md').read_bytes(), b'new skill\n')
        self.assertTrue((self.root / 'external/alpha/references/guide.md').exists())
        self.assertFalse((self.root / 'external/alpha/old.txt').exists())
        self.assertIn('/compare/' + 'a' * 40 + '...' + 'c' * 40, body)
        self.assertIn('新增 1、修改 1、刪除 1', body)
        sync.check(self.root)

    def test_local_edits_are_preserved_and_update_stops_before_network(self):
        self.bootstrap()
        target = self.root / 'external/alpha/SKILL.md'
        target.write_text('local work\n')
        self.client.latest = lambda _: self.fail('Network must not run with local changes')
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'local snapshot differs'):
            sync.update(self.root, self.client)
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

    def test_network_failure_leaves_all_existing_sources_intact(self):
        self.bootstrap()
        self.client.commits = {'alpha': 'c' * 40, 'beta': 'd' * 40}
        download = self.client.archive
        def fail_second(source, commit):
            if source['name'] == 'beta':
                raise OSError('download failed')
            return download(source, commit)
        self.client.archive = fail_second
        before = self.state()
        with self.assertRaisesRegex(OSError, 'download failed'):
            sync.update(self.root, self.client)
        self.assertEqual(before, self.state())
        self.assertEqual(list(self.root.glob('.external-sync-*')), [])

    def test_local_edit_during_download_is_preserved(self):
        self.bootstrap()
        self.client.commits['alpha'] = 'c' * 40
        download = self.client.archive
        def edit_during_download(source, commit):
            (self.root / 'external/alpha/SKILL.md').write_text('concurrent local edit\n')
            return download(source, commit)
        self.client.archive = edit_during_download
        old_lock = (self.root / 'externals.lock.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'local snapshot differs'):
            sync.update(self.root, self.client)
        self.assertEqual((self.root / 'external/alpha/SKILL.md').read_text(), 'concurrent local edit\n')
        self.assertEqual((self.root / 'externals.lock.json').read_bytes(), old_lock)

    def test_readme_edit_during_download_is_preserved(self):
        self.bootstrap()
        self.client.commits['alpha'] = 'c' * 40
        download = self.client.archive
        def edit_during_download(source, commit):
            path = self.root / 'README.md'
            path.write_text(path.read_text() + '\nconcurrent note\n')
            return download(source, commit)
        self.client.archive = edit_during_download
        old_lock = (self.root / 'externals.lock.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'README changed'):
            sync.update(self.root, self.client)
        self.assertTrue((self.root / 'README.md').read_text().endswith('concurrent note\n'))
        self.assertEqual((self.root / 'externals.lock.json').read_bytes(), old_lock)

    def test_missing_required_file_preserves_previous_snapshot(self):
        self.bootstrap()
        self.client.commits['beta'] = 'd' * 40
        del self.client.files['beta']['plugin/skills/demo/SKILL.md']
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'required_files'):
            sync.update(self.root, self.client)
        self.assertEqual(before, self.state())

    def test_write_failure_rolls_back_sources_lock_and_readme(self):
        self.bootstrap()
        self.client.commits = {'alpha': 'c' * 40, 'beta': 'd' * 40}
        self.client.files['alpha']['SKILL.md'] = b'new\n'
        before = self.state()
        write = sync.write_if_changed
        def fail_readme(path, text):
            if path.name == 'README.md':
                raise OSError('simulated write failure')
            write(path, text)
        with patch.object(sync, 'write_if_changed', side_effect=fail_readme):
            with self.assertRaisesRegex(OSError, 'simulated write failure'):
                sync.update(self.root, self.client)
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
        self.manifest['sources'].pop()
        self.save_manifest()
        body = sync.update(self.root, self.client)
        self.assertFalse((self.root / 'external/beta').exists())
        self.assertTrue((self.root / 'external/alpha/SKILL.md').exists())
        self.assertIn('依來源清單移除', body)
        sync.check(self.root)

    def test_invalid_manifest_paths_names_and_duplicates_are_rejected(self):
        original = copy.deepcopy(self.manifest)
        for field, value in [('path', '../escape'), ('path', '/absolute'), ('name', '../alpha'),
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

    def test_archive_path_traversal_links_special_files_and_duplicate_files_fail(self):
        for path, kind in [('source-commit/../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('source-commit/link', tarfile.SYMTYPE), ('source-commit/hard', tarfile.LNKTYPE),
                           ('source-commit/fifo', tarfile.FIFOTYPE), ('source-commit/.git/config', tarfile.REGTYPE),
                           ('source-commit/README.md', tarfile.REGTYPE)]:
            with self.subTest(path=path, kind=kind), tempfile.TemporaryDirectory() as folder:
                member = tarfile.TarInfo(path)
                member.type, member.linkname = kind, '/outside'
                payload = archive({'README.md': b'readme\n'}, special=member)
                with self.assertRaises(ValueError):
                    sync.unpack(payload, '.', Path(folder) / 'out')

    def test_empty_or_wrong_subtree_and_malformed_archive_fail(self):
        with self.assertRaisesRegex(ValueError, 'no files'):
            sync.unpack(archive({'other/README.md': b'x'}), 'plugin', self.root / 'wrong')
        with self.assertRaises(tarfile.TarError):
            sync.unpack(b'not a gzip file', '.', self.root / 'bad')

    def test_missing_readme_markers_stops_before_replacing_existing_files(self):
        self.bootstrap()
        (self.root / 'README.md').write_text('no markers\n')
        before = self.state()
        self.client.commits['alpha'] = 'c' * 40
        with self.assertRaisesRegex(ValueError, 'marker pair'):
            sync.update(self.root, self.client)
        self.assertEqual(before, self.state())

    def test_offline_cli_check_fails_on_corruption(self):
        self.bootstrap()
        run = lambda: subprocess.run([sys.executable, '-B', str(SCRIPT), 'check', '--root', str(self.root)], capture_output=True, text=True)
        self.assertEqual(run().returncode, 0)
        (self.root / 'external/alpha/SKILL.md').write_text('corruption\n')
        failed = run()
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn('local snapshot differs', failed.stderr)

    def test_latest_commit_query_filters_monorepo_path(self):
        client = sync.GitHub()
        urls = []
        def read(url):
            urls.append(url)
            return json.dumps([{'sha': 'a' * 40, 'commit': {'committer': {'date': '2026-10-31T00:00:00Z'}}}]).encode()
        client.read = read
        sources = sync.load_manifest(self.root)
        client.latest(sources[0])
        client.latest(sources[1])
        self.assertNotIn('path=', urls[0])
        self.assertIn('path=plugin', urls[1])
        self.assertIn('sha=main', urls[1])

    def test_http_errors_and_empty_commit_results_are_not_success(self):
        client = sync.GitHub()
        source = sync.load_manifest(self.root)[0]
        for payload in [[], {'message': 'API rate limit exceeded'}, [{'sha': 'invalid'}]]:
            with self.subTest(payload=payload):
                client.read = lambda _, data=payload: json.dumps(data).encode()
                with self.assertRaises(ValueError):
                    client.latest(source)

    def test_archive_limits_fail_before_installing(self):
        with patch.object(sync, 'MAX_CONTENT', 2):
            with self.assertRaisesRegex(ValueError, 'extraction limit'):
                sync.unpack(archive({'README.md': b'long data'}), '.', self.root / 'limited')


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
        check_index = next(i for i, step in enumerate(steps) if step.get('run') == 'python -B scripts/sync_externals.py check')
        publish_index = next(i for i, step in enumerate(steps) if step.get('uses', '').startswith('peter-evans/create-pull-request@'))
        self.assertLess(check_index, publish_index)
        self.assertEqual(steps[publish_index]['with']['branch'], 'codex/sync-external-skills')
        self.assertEqual(set(steps[publish_index]['with']['add-paths'].split()), {'external/', 'externals.lock.json', 'README.md'})


if __name__ == '__main__':
    unittest.main()
