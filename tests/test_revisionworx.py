"""RevisionWorx document columns without Qt. The real-RevisionWorx case runs when RevisionWorx is installed (CI
sets LEDGERBOOK_REQUIRE_RWX=1 so it cannot silently skip there)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ledgerbook import revisionworx as R
from ledgerbook.constants import TYPE_NAMES
from ledgerbook.store import Store

DOCS = [
    {'id': 'a', 'number': 'DWG-100', 'title': 'Manifold', 'project': {'name': 'Skid'},
     'latest': {'label': 'C', 'state': 'released', 'state_name': 'Released'}},
    {'id': 'b', 'number': 'dwg-200', 'title': 'Bracket', 'project': {'name': 'Skid'},
     'latest': {'label': 'A', 'state': 'wip', 'state_name': 'Work in Progress'}, 'checkout': {'user': 'sam'}},
    {'id': 'c', 'number': 'SPEC-1', 'title': 'One', 'project': {'name': 'P1'}, 'latest': {'label': 'A'}},
    {'id': 'd', 'number': 'spec-1', 'title': 'Two', 'project': {'name': 'P2'}, 'latest': {'label': 'B'}},
]


class Cells(unittest.TestCase):
    def test_cell_text_and_tone(self):
        idx = R.index(DOCS)
        self.assertEqual(R.cell('DWG-100', idx), ('DWG-100 · rev C · Released', 'good'))
        self.assertEqual(R.cell(' DWG-200 ', idx), ('DWG-200 · rev A · Work in Progress · checked out', ''))
        self.assertEqual(R.cell('NOPE-1', idx), ('NOPE-1 · not in RevisionWorx', 'warn'))
        self.assertEqual(R.cell('SPEC-1', idx), ('SPEC-1 · number used in 2 projects', 'warn'))
        self.assertEqual(R.cell('', idx), ('', ''))
        self.assertEqual(R.cell('DWG-100', None), ('DWG-100', ''))      # RevisionWorx absent: the plain value
        self.assertEqual(R.lookup('dwg-100', idx)[0]['id'], 'a')
        self.assertEqual(R.choices(DOCS[:1]), ['DWG-100  ·  Manifold  ·  Skid'])

    def test_store_accepts_the_column_and_round_trips(self):
        self.assertEqual(TYPE_NAMES['revision'], 'RevisionWorx document')
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / 'db.sqlite3')
            b = s.add_book('Changes')
            s.set_columns(b, [{'key': 'entry_date', 'label': 'Date', 'type': 'date', 'visible': True},
                              {'key': 'title', 'label': 'Entry', 'type': 'text', 'visible': True},
                              {'key': 'drawing', 'label': 'Drawing', 'type': 'revision', 'visible': True}])
            s.save_entry(b, {'entry_date': '2026-11-04', 'title': 'Weld repair', 'drawing': ' DWG-100 '})
            self.assertEqual(s.values(s.entries(b)[0])['drawing'], 'DWG-100')
            self.assertEqual(len(s.entries(b, 'dwg-100')), 1)                 # searchable like text
            path = Path(d) / 'book.ledgerbook'
            s.export_logbook(b, path)
            new, count = s.import_logbook(path)
            self.assertEqual(count, 1)
            self.assertEqual(s.columns(new)[2]['type'], 'revision')
            s.close()


class RealRevisionWorx(unittest.TestCase):
    def test_index_from_a_real_workspace(self):
        try:
            import revisionworx.integration  # noqa: F401
        except ImportError:
            if os.environ.get('LEDGERBOOK_REQUIRE_RWX'):
                raise
            self.skipTest('RevisionWorx is not installed')
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env = dict(os.environ)
            for var in ('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME', 'APPDATA', 'LOCALAPPDATA'):
                env[var] = str(tmp / 'profile' / var)
            ws = tmp / 'ws'
            env['REVISIONWORX_WORKSPACE'] = str(ws)

            def cli(*args):
                out = subprocess.run([sys.executable, '-m', 'revisionworx', *args], capture_output=True, text=True,
                                     env=env, timeout=120)
                self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
                return out.stdout
            cli('init', str(ws), '--name', 'Ledgerbook test')
            (ws / 'Projects').mkdir()
            cli('root', 'add', 'Projects', str(ws / 'Projects'))
            cli('project', 'new', '--name', 'Skid', '--number', 'SK-1')
            src = tmp / 'manifold.txt'
            src.write_text('rev A', encoding='utf-8')
            made = json.loads(cli('link', 'publish', str(src), '--project', 'SK-1', '--number', 'DWG-100',
                                  '--title', 'Manifold'))
            rev = made['document']['latest']['id']
            for state in ('in_review', 'approved', 'released'):
                cli('rev', 'transition', rev, state)
            old = dict(os.environ)
            os.environ.update(env)
            try:
                rwx = R.RevisionWorx()
                rwx.command = [sys.executable, '-m', 'revisionworx']
                self.assertTrue(rwx.available())
                idx = R.index(rwx.documents())
            finally:
                os.environ.clear()
                os.environ.update(old)
            label = made['document']['latest']['label']
            self.assertEqual(R.cell('dwg-100', idx), ('dwg-100 · rev %s · Released' % label, 'good'))


if __name__ == '__main__':
    unittest.main()
