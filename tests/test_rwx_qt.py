"""RevisionWorx document columns in the real window (offscreen), with a stand-in client. Skipped without PySide6."""
import os
import tempfile
import time
import unittest

try:
    import PySide6  # noqa: F401
except ImportError:
    PySide6 = None


class Fake:
    def __init__(self):
        self.calls, self.opened = 0, []
        self.docs = [{'id': 'a', 'number': 'DWG-100', 'title': 'Manifold', 'project': {'name': 'Skid'},
                      'latest': {'label': 'C', 'state': 'released', 'state_name': 'Released'}}]

    def documents(self, project=None, text=''):
        self.calls += 1
        return self.docs

    def open(self, document=None, file=None):
        self.opened.append(document)
        return {'ok': True}


@unittest.skipIf(PySide6 is None, 'PySide6 not installed')
class RevisionColumns(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        tmp = tempfile.mkdtemp()
        os.environ['XDG_DATA_HOME'] = tmp + '/d'
        os.environ['XDG_CONFIG_HOME'] = tmp + '/c'
        from PySide6.QtWidgets import QApplication
        from ledgerbook import VERSION
        from ledgerbook.prefs import Prefs
        Prefs().set('seen_version', VERSION)          # no "What's new" dialog blocking the event loop
        self.qt = QApplication.instance() or QApplication([])
        # A window from an earlier test in this process may still have its startup "What's new" timer pending;
        # processing events here would open that modal dialog and block. These tests never need it.
        from ledgerbook import app as A
        original = A.Main.show_whats_new
        A.Main.show_whats_new = lambda self, force=False: None
        self.addCleanup(setattr, A.Main, 'show_whats_new', original)

    def wait(self, cond, what):
        end = time.time() + 10
        while time.time() < end:
            self.qt.processEvents()
            if cond():
                return
            time.sleep(0.02)
        self.fail('timed out: ' + what)

    def make(self, rwx):
        from ledgerbook import app as A
        from ledgerbook import store as S
        S.DEFAULT_DB = S.Path(os.environ['XDG_DATA_HOME']) / 'ledgerbook' / 'ledgerbook.sqlite3'
        w = A.Main(rwx=rwx)
        bid = w.store.add_book('Changes')
        w.store.set_columns(bid, [{'key': 'title', 'label': 'Entry', 'type': 'text', 'visible': True},
                                  {'key': 'drawing', 'label': 'Drawing', 'type': 'revision', 'visible': True}])
        w.store.save_entry(bid, {'title': 'Weld repair', 'drawing': 'DWG-100'})
        w.store.save_entry(bid, {'title': 'Old part', 'drawing': 'DWG-999'})
        w.reload_tree(fresh=True)
        w.select_book(bid)
        return w, bid

    def cells(self, w):
        return sorted(w.view.table.item(r, 2).text() for r in range(w.view.table.rowCount()))

    def test_live_status_picker_and_show(self):
        fake = Fake()
        w, bid = self.make(fake)
        self.wait(lambda: 'DWG-100 · rev C · Released' in self.cells(w), 'status in the table')
        self.assertIn('DWG-999 · not in RevisionWorx', self.cells(w))
        calls = fake.calls
        w.load_rows()                                     # within 30 s: no new RevisionWorx call
        self.qt.processEvents()
        self.assertEqual(fake.calls, calls)
        w.refresh_rwx()                                   # F5 refreshes
        self.wait(lambda: fake.calls == calls + 1, 'a refresh')
        row = next(r for r in range(w.view.table.rowCount()) if w.view.table.item(r, 2).text().startswith('DWG-100'))
        self.assertEqual(w.revision_values(row), ['DWG-100'])
        w.show_in_rwx('DWG-100')
        self.wait(lambda: fake.opened == ['a'], 'show in RevisionWorx')
        from ledgerbook import dialogs as D
        D.pick_item = lambda *a, **k: 0
        dlg = D.EntryDialog(w, w.store, bid, None, 'Changes')
        self.assertEqual(dlg.choose_document(dlg.widgets['drawing'])['id'], 'a')
        self.assertEqual(dlg.widgets['drawing'].text(), 'DWG-100')
        dlg.reject()
        w.close()

    def test_without_revisionworx_the_number_shows_as_is(self):
        w, bid = self.make(False)
        self.qt.processEvents()
        self.assertEqual(self.cells(w), ['DWG-100', 'DWG-999'])
        from ledgerbook import dialogs as D
        dlg = D.EntryDialog(w, w.store, bid, None, 'Changes')
        from PySide6.QtWidgets import QPushButton
        self.assertFalse([b for b in dlg.findChildren(QPushButton) if b.text() == "Choose…"])
        dlg.reject()
        w.close()

    def test_a_late_result_after_close_is_ignored(self):
        """Regression (CI 06ada7d): a RevisionWorx answer arriving after the window closed ran load_rows() on the
        closed database (sqlite3.ProgrammingError)."""
        import threading
        gate = threading.Event()

        class Slow(Fake):
            def documents(self, project=None, text=''):
                gate.wait(5)
                return super().documents()
        w, bid = self.make(Slow())                       # starts a background listing that waits on the gate
        w.close()
        errors = []
        import sys
        old_hook = sys.excepthook
        sys.excepthook = lambda *exc: errors.append(exc)
        try:
            gate.set()
            end = time.time() + 1.5
            while time.time() < end:
                self.qt.processEvents()
                time.sleep(0.02)
        finally:
            sys.excepthook = old_hook
        self.assertEqual(errors, [])


def tearDownModule():
    """Delete every window (this module's and earlier modules') before the interpreter tears Qt down: Python-owned
    widgets outliving their QApplication segfaulted the process at exit after all tests had passed (CI 622c5cd)."""
    if PySide6 is None:
        return
    import gc
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()


if __name__ == '__main__':
    unittest.main()
