import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from hyperreview import d1_shadow


def request():
    return {'change_inventory': {'complete': False, 'files': [
        {'before_path': 'main.py', 'after_path': 'main.py', 'status': 'modified'},
        {'before_path': None, 'after_path': None, 'status': 'added'}]},
        'sources': [
            {'id': 'old', 'path': 'main.py', 'side': 'before', 'content': 'a' * 1300, 'line_start': 1, 'line_end': 20},
            {'id': 'new', 'path': 'main.py', 'side': 'after', 'content': 'b' * 1300, 'line_start': 1, 'line_end': 22},
            {'id': 'context', 'path': 'unrelated.py', 'side': 'after', 'content': 'secret_context', 'line_start': 1, 'line_end': 1},
        ]}


class ShadowTests(unittest.TestCase):
    def test_only_changed_bounded_excerpts_and_explicit_limitations(self):
        state, coverage = d1_shadow.build_input(request())
        self.assertNotIn('secret_context', state)
        self.assertLess(len(state), 3000)
        self.assertIn('Diff of supplied excerpt windows only', state)
        self.assertEqual([x['id'] for x in coverage['selected_sources']], ['old', 'new'])
        self.assertTrue(all(x['truncated'] for x in coverage['selected_sources']))
        self.assertFalse(coverage['inventory_complete'])
        self.assertIn('not complete diffs', state)

    def test_empty_or_hidden_changes_do_not_produce_guessed_input(self):
        data = request()
        data['change_inventory']['files'] = [{'before_path': None, 'after_path': None, 'status': 'added'}]
        with self.assertRaises(ValueError):
            d1_shadow.build_input(data)

    def test_read_only_query_observes_cutoff_and_skips_busy_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dbpath = root / 'journal.sqlite3'
            with sqlite3.connect(dbpath) as db:
                db.executescript('''CREATE TABLE tasks (candidate TEXT, state TEXT, artifact TEXT, repository TEXT);
                    CREATE TABLE preview_jobs (candidate TEXT, job TEXT, state TEXT, artifact TEXT, bundle_digest TEXT, updated_at INTEGER);
                    INSERT INTO tasks VALUES ('a','request_prepared','input','SoundBlaster/Hunter');
                    INSERT INTO preview_jobs VALUES ('a','job','preview_ready','preview','digest',101);''')
            os.chmod(dbpath, 0o600)
            self.assertEqual(len(d1_shadow._rows(root, 101)), 1)
            self.assertEqual(d1_shadow._rows(root, 102), [])
            with sqlite3.connect(dbpath) as db:
                db.execute("INSERT INTO preview_jobs VALUES ('b','busy','analyzing',NULL,NULL,102)")
            self.assertEqual(d1_shadow._rows(root, 0), [])

    def test_success_is_private_and_claimed_only_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / 'input'
            input_root.mkdir(mode=0o700)
            output_root = root / 'output'
            task = {'job':'a'*64,'repository':'SoundBlaster/Hunter','pr':1,'head_sha':'b'*40,
                    'request_digest':'c'*64,'bundle_digest':'d'*64,'preview_artifact':'p'}
            result = {'answers': {'kind': {'choice':'implementation','confidence':0.7},
                                  'signals': {'choices':['implementation'],'probabilities':{'implementation':0.8}}}}
            calls = []
            def invoke(_config, state):
                calls.append(state)
                return result
            config = {'input_root':str(input_root),'output_root':str(output_root),'not_before':0}
            with patch.object(d1_shadow, '_rows', return_value=[task]), patch.object(d1_shadow, '_verify', return_value=(request(), root)):
                first = d1_shadow.run(config, invoke=invoke)
                second = d1_shadow.run(config, invoke=invoke)
            self.assertEqual(first['status'], 'complete')
            self.assertEqual(second['status'], 'idle')
            self.assertEqual(len(calls), 1)
            output = Path(first['result'])
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(output.read_text())['head_sha'], task['head_sha'])
            self.assertTrue(output.with_suffix('.md').exists())

    def test_failed_inference_never_replays_automatically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); inp = root / 'input'; inp.mkdir(mode=0o700)
            config = {'input_root':str(inp),'output_root':str(root / 'out'),'not_before':0}
            task = {'job':'e'*64}
            count = []
            def fail(*_):
                count.append(1)
                raise RuntimeError('unavailable')
            with patch.object(d1_shadow, '_rows', return_value=[task]), patch.object(d1_shadow, '_verify', return_value=(request(), root)):
                first = d1_shadow.run(config, invoke=fail)
                again = d1_shadow.run(config, invoke=fail)
            self.assertEqual((first['status'], again['status']), ('failed', 'idle'))
            self.assertEqual(len(count), 1)

    def test_stale_preview_cannot_be_published_as_a_shadow_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); inp = root / 'input'; inp.mkdir(mode=0o700)
            task = {'job':'f'*64, 'head_sha':'b'*40, 'request_digest':'c'*64,
                    'bundle_digest':'d'*64, 'preview_artifact':'p'}
            config = {'input_root':str(inp), 'output_root':str(root / 'out'), 'not_before':0}
            with patch.object(d1_shadow, '_rows', side_effect=[[task], []]), \
                 patch.object(d1_shadow, '_verify', return_value=(request(), root)):
                result = d1_shadow.run(config, invoke=lambda *_: {})
            self.assertEqual(result['failure_code'], 'invalid_or_stale_input')
            self.assertEqual(list((root / 'out' / 'results').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
