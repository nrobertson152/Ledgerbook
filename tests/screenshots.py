"""Screenshots for design review (CI prints them base64-encoded between markers; decode from the job log).

    QT_QPA_PLATFORM=offscreen python tests/screenshots.py OUT_DIR"""
import base64
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))     # run as a script: import ledgerbook from the repo


def main(out: Path) -> int:
    tmp = tempfile.mkdtemp(prefix='ledgerbook-shots-')
    os.environ['XDG_DATA_HOME'] = tmp + '/d'
    os.environ['XDG_CONFIG_HOME'] = tmp + '/c'
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from ledgerbook import VERSION, templates
    from ledgerbook import app as A
    from ledgerbook.dialogs import EntryDialog, LogbookDialog
    from ledgerbook.prefs import Prefs
    Prefs().set('seen_version', VERSION)
    qt = QApplication.instance() or QApplication([])
    A.Main.show_whats_new = lambda self, force=False: None
    w = A.Main(rwx=False)
    w.resize(1320, 840)
    w.show()
    s, today = w.store, date.today()
    car = s.add_book('Service truck', 'Ford F-250, VIN …4417', fields=templates.fields('Vehicle maintenance'))
    s.configure_book(car, icon='🚗')
    for days_ago, title, odo, cost, due in ((300, 'Oil change', 41200, 89.95, -120), (95, 'Oil change', 45980, 94.50, 3),
                                             (210, 'Tyre rotation', 43100, 40, -15), (60, 'Brake pads', 47010, 412.80, 600),
                                             (20, 'Wiper blades', 47900, 36.20, None)):
        s.save_entry(car, {'entry_date': (today - timedelta(days=days_ago)).isoformat(), 'title': title,
                           'reading': str(odo), 'cost': '$%.2f' % cost, 'shop': 'Main St Garage',
                           'next_due': (today + timedelta(days=due)).isoformat() if due is not None else ''})
    lab = s.add_book('Calibration', fields=templates.fields('Equipment & calibration'))
    s.configure_book(lab, icon='🔧')
    s.save_entry(lab, {'title': 'Torque wrench TW-3', 'serial': 'TW3-0042', 'result': 'Pass',
                       'next_due': (today + timedelta(days=10)).isoformat()})
    exp = s.add_book('Shop expenses', fields=templates.fields('Expenses'))
    for item, cat, amount in (('Bandsaw blades', 'Tools', '$184.20'), ('Welding wire', 'Materials', '$96.00'),
                              ('Forklift service', 'Services', '$1,250.00')):
        s.save_entry(exp, {'title': item, 'category': cat, 'cost': amount, 'paid': 'true'})
    w.reload_tree(fresh=True)
    out.mkdir(parents=True, exist_ok=True)
    shots = []

    def shot(widget, name):
        import time
        end = time.time() + 0.6                   # let the fade-in animations (150-220 ms) finish
        while time.time() < end:
            qt.processEvents()
            time.sleep(0.02)
        path = out / ('%s.png' % name)
        widget.grab().save(str(path))
        shots.append(path)

    w.go_home()
    shot(w, 'home')
    w.select_book(car)
    shot(w, 'vehicle-log')
    w.select_book(exp)
    shot(w, 'expenses-totals')
    dlg = LogbookDialog(w, s)
    dlg.template_combo.setCurrentIndex(dlg.template_combo.findData('Vehicle maintenance'))
    dlg.resize(600, 760)
    dlg.show()
    shot(dlg, 'new-logbook-template')
    dlg.close()
    from ledgerbook.dialogs import ColumnsDialog
    cd = ColumnsDialog(w, s, car, 'Service truck')
    cd.list.setCurrentRow(2)                      # Odometer: a number column with its total switched off
    cd.resize(760, 560)
    cd.show()
    shot(cd, 'columns-total-option')
    cd.close()
    ed = EntryDialog(w, s, car, None, 'Service truck')
    ed.resize(580, 760)
    ed.show()
    shot(ed, 'entry-dialog')
    ed.close()
    for p in shots:
        print('===BEGIN %s===' % p.name)
        print(base64.b64encode(p.read_bytes()).decode('ascii'))
        print('===END===')
    w.close()
    for widget in QApplication.topLevelWidgets():   # Python-owned widgets outliving Qt segfault at exit
        widget.close()
        widget.deleteLater()
    qt.processEvents()
    return len(shots)


if __name__ == '__main__':
    count = main(Path(sys.argv[1] if len(sys.argv) > 1 else 'shots'))
    sys.stdout.flush()
    os._exit(0 if count == 6 else 1)               # skip interpreter teardown of Qt objects
