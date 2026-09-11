"""Regression for the audited missing-root/index fallback, in the current runtime."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import unittest

from retrieval.facade import retrieve_linux_knowledge


class ExplicitRetrievalRootTests(unittest.TestCase):
    def test_T17_missing_explicit_root_has_zero_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / 'missing-runtime'
            response = retrieve_linux_knowledge('ls', max_results=3, project_dir=missing)
            self.assertEqual(len(response.results), 0)
            self.assertEqual(response.status, 'refused')

    def test_T17_empty_index_never_uses_bundled_corpus(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'knowledge').mkdir()
            for query in ['ls', 'networking', 'permission', 'systemctl daemon-reload']:
                with self.subTest(query=query):
                    self.assertEqual(retrieve_linux_knowledge(query, project_dir=root).results, ())

    def test_T17_explicit_corpora_and_caches_are_isolated_concurrently(self):
        with tempfile.TemporaryDirectory() as temporary:
            roots = [Path(temporary) / name for name in ['one', 'two']]
            for index, root in enumerate(roots):
                examples = root / 'knowledge/examples'
                examples.mkdir(parents=True)
                (examples / 'sample.json').write_text(json.dumps({'id': f'corpus-{index}',
                    'command': 'fixturecmd', 'category': 'synthetic', 'notes': f'corpus-{index}'}))
            def lookup(index):
                response = retrieve_linux_knowledge('fixturecmd', project_dir=roots[index])
                self.assertEqual(len(response.results), 1)
                self.assertEqual(response.results[0]['topic'], f'corpus-{index}')
                self.assertTrue(response.results[0]['provenance']['source_file'].startswith(str(roots[index])))
                self.assertEqual(response.results[0]['provenance']['canonical_source'], 'UNSPECIFIED_LOCAL_SOURCE')
                self.assertEqual(retrieve_linux_knowledge('ls', project_dir=roots[index]).results, ())
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lookup, [0, 1] * 4))

    def test_T17_default_bundled_lookup_is_retained(self):
        self.assertTrue(retrieve_linux_knowledge('ls').answered)


if __name__ == '__main__':
    unittest.main()
