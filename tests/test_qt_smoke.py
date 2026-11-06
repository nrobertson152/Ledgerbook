"""Builds the main window offscreen and walks the main flows. Skipped when PySide6 is missing."""
import os
import tempfile
import unittest

try:
    import PySide6  # noqa: F401
except ImportError:
    PySide6 = None

import qt_cleanup


@unittest.skipIf(PySide6 is None, 'PySide6 not installed')
class Smoke(unittest.TestCase):
    def test_window_and_themes(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        tmp = tempfile.mkdtemp()
        os.environ['XDG_DATA_HOME'] = tmp + '/d'
        os.environ['XDG_CONFIG_HOME'] = tmp + '/c'
        from PySide6.QtWidgets import QApplication
        from ledgerbook import app as A
        qt = QApplication.instance() or QApplication([])
        w = A.Main()
        bid = w.store.add_book('Smoke')
        w.store.save_entry(bid, {'title': 'Hello'})
        w.reload_tree(fresh=True)
        w.select_book(bid)
        self.assertEqual(w.view.table.rowCount(), 1)
        for name in ('Graphite', 'Terracotta', 'Light', 'Midnight'):
            w.change_theme(name)
        w.close()
        self.assertTrue(qt)


def tearDownModule():
    if PySide6 is not None:
        qt_cleanup.delete_windows()
        qt_cleanup.install()


if __name__ == '__main__':
    unittest.main()
