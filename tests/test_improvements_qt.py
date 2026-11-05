"""Templates, totals, due dates, attachments and CSV import in the real window (offscreen). Skipped without PySide6."""
import csv
import os
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

try:
    import PySide6  # noqa: F401
except ImportError:
    PySide6 = None


@unittest.skipIf(PySide6 is None, 'PySide6 not installed')
class Improvements(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        self.tmp = tempfile.mkdtemp()
        os.environ['XDG_DATA_HOME'] = self.tmp + '/d'
        os.environ['XDG_CONFIG_HOME'] = self.tmp + '/c'
        from PySide6.QtWidgets import QApplication
        from ledgerbook import VERSION
        from ledgerbook import app as A
        from ledgerbook import store as S
        from ledgerbook.prefs import Prefs
        Prefs().set('seen_version', VERSION)
        self.qt = QApplication.instance() or QApplication([])
        original = A.Main.show_whats_new
        A.Main.show_whats_new = lambda self, force=False: None
        self.addCleanup(setattr, A.Main, 'show_whats_new', original)
        S.DEFAULT_DB = S.Path(os.environ['XDG_DATA_HOME']) / 'ledgerbook' / 'ledgerbook.sqlite3'
        self.A = A
        self.w = A.Main(rwx=False)
        self.addCleanup(self.w.close)
        self.notes = []
        self.w.say = lambda text, *a, **k: self.notes.append(text)

    def book(self, template):
        from ledgerbook import templates
        bid = self.w.store.add_book(template, fields=templates.fields(template))
        self.w.reload_tree(fresh=True)
        return bid

    def test_new_logbook_dialog_offers_templates(self):
        from ledgerbook.dialogs import LogbookDialog
        dlg = LogbookDialog(self.w, self.w.store)
        self.assertIn('Notes', dlg.template_columns.text())           # Blank by default
        dlg.template_combo.setCurrentIndex(dlg.template_combo.findData('Expenses'))
        self.assertIn('Amount', dlg.template_columns.text())
        self.assertEqual(dlg.icon, '💳')
        self.assertEqual(dlg.desc_edit.toPlainText(), 'What was spent, on what, with receipts.')
        dlg.name_edit.setText('Shop costs')
        dlg.save()
        self.assertEqual(dlg.result_data['template'], 'Expenses')
        edit = LogbookDialog(self.w, self.w.store, self.w.store.book(self.book('Blank')))
        self.assertIsNone(edit.template_combo)                         # existing logbooks keep their columns

    def test_totals_follow_the_search(self):
        bid = self.book('Expenses')
        for title, amount in (('Saw', '$1,200'), ('Blades', '34.50'), ('Glue', '')):
            self.w.store.save_entry(bid, {'title': title, 'cost': amount})
        self.w.select_book(bid)
        self.assertEqual(self.w.view.totals.text(), 'Amount: total 1,234.50 · average 617.25')
        self.w.view.search.edit.setText('saw')
        self.w.load_rows()
        self.assertEqual(self.w.view.totals.text(), 'Amount: total 1,200')
        self.w.view.search.edit.setText('glue')
        self.w.load_rows()
        self.assertFalse(self.w.view.totals.isVisibleTo(self.w.view))

    def test_due_cells_and_home_coming_up(self):
        from ledgerbook import theme
        bid = self.book('Vehicle maintenance')
        today = date.today()
        late = self.w.store.save_entry(bid, {'title': 'Tyres', 'next_due': (today - timedelta(days=3)).isoformat()})
        self.w.store.save_entry(bid, {'title': 'Oil', 'next_due': (today + timedelta(days=200)).isoformat()})
        self.w.select_book(bid)
        cells = {self.w.view.table.item(r, 5).text(): self.w.view.table.item(r, 5) for r in range(2)}
        overdue = next(c for t, c in cells.items() if 'overdue 3 days' in t)
        self.assertEqual(overdue.foreground().color().name().lower(), theme.current()['bad'].lower())
        self.w.go_home()
        rows = self.w.welcome.upcoming_rows
        self.assertEqual([(it['item'], it['days']) for it, _row in rows], [('Tyres', -3)])   # Oil is 200 days away
        rows[0][1].clicked.emit()
        self.assertEqual(self.w.current, bid)
        self.assertEqual([self.w.row_ids[r] for r in self.w.selected_rows()], [late])

    def test_entry_dialog_due_buttons_and_attachment_browse(self):
        from PySide6.QtCore import QDate
        from ledgerbook import dialogs as D
        bid = self.book('Equipment & calibration')
        dlg = D.EntryDialog(self.w, self.w.store, bid, None, 'Calibration')
        dlg.widgets['entry_date'].setDate(QDate(2026, 1, 31))
        dlg.set_due(dlg.widgets['next_due'], 1)
        self.assertEqual(dlg.widgets['next_due'].text(), '2026-02-28')
        cert = Path(self.tmp) / 'cert 42.pdf'
        cert.write_bytes(b'%PDF')
        original = D.QFileDialog
        D.QFileDialog = type('FileDialogStub', (), {'getOpenFileName': staticmethod(lambda *a, **k: (str(cert), ''))})
        try:
            dlg.browse_file(dlg.widgets['certificate'])
        finally:
            D.QFileDialog = original
        self.assertEqual(dlg.widgets['certificate'].text(), str(cert))
        dlg.widgets['title'].setText('Torque wrench')
        dlg.save()
        self.w.select_book(bid)
        self.assertEqual(self.w.view.table.item(0, 6).text(), 'cert 42.pdf')
        actions = self.w.entry_extra_actions(0)
        self.assertEqual([t for t, _a in actions], ['Open cert 42.pdf'])
        opened = []
        original = self.A.QDesktopServices
        self.A.QDesktopServices = type('DesktopStub', (), {'openUrl': staticmethod(lambda url: opened.append(url.toLocalFile()))})
        try:
            actions[0][1]()
            cert.unlink()
            self.assertFalse(self.w.open_attachment(str(cert)))
        finally:
            self.A.QDesktopServices = original
        self.assertEqual(opened, [str(cert.resolve())])
        self.assertTrue(any('File not found' in n for n in self.notes))

    def test_csv_import_reports_ignored_columns(self):
        bid = self.book('Expenses')
        self.w.select_book(bid)
        path = Path(self.tmp) / 'in.csv'
        with path.open('w', newline='', encoding='utf-8') as fp:
            csv.writer(fp).writerows([['item', 'AMOUNT', 'Colour'], ['Saw', '$45', 'red']])
        self.w.pick_open = lambda *a, **k: str(path)
        self.w.import_csv()
        self.assertEqual(len(self.w.row_ids), 1)
        self.assertTrue(any('ignored column: Colour' in n for n in self.notes), self.notes)


def tearDownModule():
    """Delete every window before the interpreter tears Qt down (see test_rwx_qt)."""
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
