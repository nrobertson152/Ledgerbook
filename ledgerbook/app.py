"""Ledgerbook 1.0: Qt 6 desktop interface, fully compatible with the existing SQLite store."""
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QMainWindow, QMenu, QPushButton, QStackedWidget,
                               QWidget)

from . import VERSION, icons, insights, templates, theme
from . import revisionworx as rwxlink
from .constants import DEFAULT_ICON
from .dialogs import (ArchiveDialog, ColumnsDialog, EntryDialog, FullTextDialog, LogbookDialog, PdfDialog,
                      RecycleDialog, WhatsNewDialog, choose, confirm, error, notify, pick_item, prompt)
from .palette import CommandPalette
from .pdf import pdf_report
from .prefs import Prefs
from .settings import AboutDialog, SettingsDialog
from .sidebar import R_COLOR, R_COUNT, R_GLYPH, R_KIND, R_NAME, R_PIN, Sidebar
from .store import Store
from .util import fmt_date, plural
from .views import MAX_CELL, LogbookView, WelcomeView
from .widgets import Toast, fade_in, hbox, icon_button, icon_label, label, retint, vbox

RESOURCES = Path(__file__).resolve().parent / 'resources'
APP_ICON = RESOURCES / 'ledgerbook.png'
_fonts_loaded = False


def slug(text):
    return re.sub(r'[^A-Za-z0-9._-]+', '-', str(text)).strip('-').lower() or 'logbook'


class Main(QMainWindow):
    RWX_STALE_SECONDS = 30

    def __init__(self, rwx=None):
        super().__init__()
        global _fonts_loaded
        if not _fonts_loaded:
            theme.load_fonts(RESOURCES)
            _fonts_loaded = True
        self.store = Store()
        self.prefs = Prefs()
        self.qsettings = QSettings('Nate Robertson', 'Ledgerbook')
        saved = self.prefs.get('theme') or self.qsettings.value('theme', theme.DEFAULT_THEME)
        self.theme = saved if saved in theme.THEMES else theme.DEFAULT_THEME
        self.current = None
        self.row_ids = []
        self.sort_key = None
        self.sort_reverse = False
        self.tree_filter = ''
        self.settings_dialog = None
        self._last_deleted = []
        self._rendering = False
        self._building_tree = False
        self._recent_order = [str(x) for x in self.prefs.get('recent_books', [])]
        self._visible_fields = []
        # RevisionWorx (optional): None while looking for it, False when not installed, else a client.
        self.rwx = rwx
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='ledgerbook-bg')
        self._rwx_index = None
        self._rwx_docs = None
        self._rwx_loaded_at = 0.0
        self._rwx_loading = False
        self._closing = False
        self.setWindowTitle('Ledgerbook · ' + VERSION)
        if APP_ICON.exists():
            self.setWindowIcon(QIcon(str(APP_ICON)))
        self.resize(1320, 840)
        self.setMinimumSize(920, 600)
        self.apply_theme()
        self.make_ui()
        self.make_menus()
        self.make_shortcuts()
        self.restore_geometry()
        self.reload_tree(fresh=True)
        self.go_home()
        self.auto_backup()
        if self.rwx is None:
            self.in_background(rwxlink.probe, self._rwx_ready)
        QTimer.singleShot(300, self.show_whats_new)

    # ===================================================================================== layout
    def make_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = hbox(central, (0, 0, 0, 0), 0)
        self.sidebar = Sidebar(self.add_book, self.add_folder, self.toggle_sidebar, self.filter_tree,
                               self.archived_books, self.recycle_bin, self.settings)
        self.tree = self.sidebar.tree
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        self.tree.itemClicked.connect(self.choose_tree)
        self.tree.itemActivated.connect(self.choose_tree)
        self.tree.itemExpanded.connect(self._save_expanded)
        self.tree.itemCollapsed.connect(self._save_expanded)
        root.addWidget(self.sidebar)
        right = QWidget()
        rl = vbox(right, (0, 0, 0, 0), 0)
        # ---- top bar
        top = QFrame()
        top.setObjectName('topbar')
        top.setFixedHeight(58)
        tl = hbox(top, (16, 0, 16, 0), 10)
        self.nav_toggle = icon_button('sidebar', 'Show or hide the sidebar  (Ctrl+B)', self.toggle_sidebar, 38, 19)
        tl.addWidget(self.nav_toggle)
        self.crumb = label('', 'h3')
        tl.addWidget(self.crumb, 1)
        self.palette_btn = QPushButton()
        self.palette_btn.setObjectName('searchBtn')
        self.palette_btn.setFixedSize(330, 38)
        self.palette_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.palette_btn.clicked.connect(self.open_palette)
        pl = hbox(self.palette_btn, (12, 0, 10, 0), 10)
        pl.addWidget(icon_label('search', 'faint', 16))
        pl.addWidget(label('Search or jump to…', 'faint'), 1)
        pl.addWidget(label('Ctrl', 'kbd'))
        pl.addWidget(label('K', 'kbd'))
        for i in range(pl.count()):
            pl.itemAt(i).widget().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        tl.addWidget(self.palette_btn)
        tl.addWidget(icon_button('sliders', 'Settings', self.settings, 38, 19))
        rl.addWidget(top)
        # ---- pages
        self.pages = QStackedWidget()
        self.welcome = WelcomeView(self)
        self.view = LogbookView(self)
        self.pages.addWidget(self.welcome)
        self.pages.addWidget(self.view)
        rl.addWidget(self.pages, 1)
        root.addWidget(right, 1)
        # handy aliases (kept from earlier releases)
        self.table = self.view.table
        self.search = self.view.search
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(140)
        self.search_timer.timeout.connect(self.load_rows)
        self.view.search.textChanged.connect(lambda _t: self.search_timer.start())
        header = self.table.horizontalHeader()
        header.sectionClicked.connect(self.sort_column)
        header.sectionResized.connect(self.save_width)
        self.table.doubleClicked.connect(self.cell_double_click)
        self.table.customContextMenuRequested.connect(self.entry_menu)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.toast = Toast(central)
        self.statusBar().showMessage('Offline  ·  Your data stays on this computer')

    def make_menus(self):
        bar = self.menuBar()

        def add(menu, text, cb, hint=''):
            act = menu.addAction(text + ('\t' + hint if hint else ''))
            act.triggered.connect(lambda checked=False: cb())
            return act

        f = bar.addMenu('File')
        add(f, 'New logbook…', self.add_book, 'Ctrl+Shift+N')
        add(f, 'New folder…', self.add_folder)
        f.addSeparator()
        add(f, 'Import logbook…', self.import_book)
        add(f, 'Import CSV…', self.import_csv)
        f.addSeparator()
        add(f, 'Export logbook…', self.export_book)
        add(f, 'Export CSV…', self.export_csv)
        add(f, 'PDF report…', self.export_pdf)
        add(f, 'Export due dates to a calendar…', self.export_calendar)
        f.addSeparator()
        add(f, 'Back up database…', self.backup)
        add(f, 'Restore backup…', self.restore_backup)
        m = bar.addMenu('Manage')
        add(m, 'Manage logbook…', self.manage_book)
        add(m, 'Manage columns…', self.columns)
        m.addSeparator()
        add(m, 'Archived logbooks…', self.archived_books)
        add(m, 'Recycle Bin…', self.recycle_bin)
        add(m, 'Undo last deletion', self.undo_delete, 'Ctrl+Z')
        v = bar.addMenu('View')
        add(v, 'Home', self.go_home)
        add(v, 'Command palette…', self.open_palette, 'Ctrl+K')
        add(v, 'Show or hide sidebar', self.toggle_sidebar, 'Ctrl+B')
        themes = v.addMenu('Theme')
        for name in theme.THEMES:
            add(themes, name, lambda n=name: self.change_theme(n))
        t = bar.addMenu('Tools')
        add(t, 'Database integrity check', self.integrity_check)
        add(t, 'Settings', self.settings)
        add(t, 'What’s new', self.show_whats_new_now)
        add(t, 'About Ledgerbook', self.about)

    def make_shortcuts(self):
        def bind(keys, fn, widget=None, context=None):
            sc = QShortcut(QKeySequence(keys), widget or self)
            if context is not None:
                sc.setContext(context)
            sc.activated.connect(fn)
            setattr(self, 'shortcut_' + re.sub(r'\W', '_', keys), sc)

        for keys, fn in (('Ctrl+N', self.add_entry), ('Ctrl+Shift+N', self.add_book),
                         ('Ctrl+F', self.focus_search), ('Ctrl+S', self.save_widths), ('Ctrl+D', self.duplicate_entry),
                         ('Ctrl+Z', self.undo_delete), ('Ctrl+K', self.open_palette), ('Ctrl+B', self.toggle_sidebar)):
            bind(keys, fn)
        bind('Delete', self.delete_entries, self.table, Qt.ShortcutContext.WidgetShortcut)
        bind('Return', self.edit_entry, self.table, Qt.ShortcutContext.WidgetShortcut)
        bind('F5', self.refresh_rwx)

    def restore_geometry(self):
        match = re.match(r'(\d+)x(\d+)', str(self.prefs.get('geometry', '')))
        if match:
            self.resize(max(920, int(match[1])), max(600, int(match[2])))
        self.sidebar.setVisible(not bool(self.prefs.get('sidebar_collapsed', False)))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, 'toast'):
            self.toast.reposition()

    # ===================================================================================== theme
    def apply_theme(self):
        theme.apply(QApplication.instance(), self.theme)
        self.prefs.set('theme', self.theme)
        self.qsettings.setValue('theme', self.theme)

    def change_theme(self, name):
        if name not in theme.THEMES:
            return
        self.theme = name
        self.apply_theme()
        retint(self)
        self.tree.viewport().update()
        if self.current:
            self.load_rows()
        else:
            self.refresh_welcome()
        if self.settings_dialog is not None:
            retint(self.settings_dialog)

    def say(self, text, kind='good', action=None, callback=None):
        self.toast.show_message(text, kind, action, callback)

    # ===================================================================================== file pickers
    def _start_dir(self):
        d = self.prefs.get('last_dir')
        return d if d and Path(d).is_dir() else str(Path.home())

    def pick_save(self, title, name, filt):
        path, _ = QFileDialog.getSaveFileName(self, title, str(Path(self._start_dir()) / name), filt)
        if path:
            self.prefs.set('last_dir', str(Path(path).parent))
        return path

    def pick_open(self, title, filt):
        path, _ = QFileDialog.getOpenFileName(self, title, self._start_dir(), filt)
        if path:
            self.prefs.set('last_dir', str(Path(path).parent))
        return path

    # ===================================================================================== sidebar / tree
    def filter_tree(self, text):
        self.tree_filter = text
        self.reload_tree()

    def _folder_item(self, folder, count, pinned):
        from PySide6.QtWidgets import QTreeWidgetItem
        item = QTreeWidgetItem([folder['name']])
        item.setData(0, R_KIND, ('folder', folder['id']))
        item.setData(0, R_NAME, folder['name'])
        item.setData(0, R_COUNT, count)
        item.setData(0, R_PIN, pinned)
        item.setToolTip(0, 'Click to expand or collapse. Right-click to pin, rename or delete.')
        return item

    def _book_item(self, book, pinned):
        from PySide6.QtWidgets import QTreeWidgetItem
        item = QTreeWidgetItem([book['name']])
        item.setData(0, R_KIND, ('book', book['id']))
        item.setData(0, R_NAME, book['name'])
        item.setData(0, R_GLYPH, book['icon'] or DEFAULT_ICON)
        item.setData(0, R_COLOR, theme.book_color(book['id'], book['accent']))
        item.setData(0, R_COUNT, book['entry_count'])
        item.setData(0, R_PIN, pinned)
        item.setToolTip(0, book['description'] or 'Right-click to pin, move, duplicate, archive or delete.')
        return item

    def reload_tree(self, fresh=False):
        """Rebuild the sidebar. ``fresh`` re-reads the recent-logbook order; otherwise the on-screen order is kept
        so rows do not jump around while you work."""
        if fresh:
            self._recent_order = [str(x) for x in self.prefs.get('recent_books', [])]
        self._building_tree = True
        try:
            tree = self.tree
            tree.clear()
            pins_f = set(self.prefs.id_list('pinned_folders'))
            pins_b = set(self.prefs.id_list('pinned_books'))
            closed = set(self.prefs.id_list('closed_folders'))
            recent = self._recent_order
            query = self.tree_filter.strip().casefold()
            books = list(self.store.books())
            books.sort(key=lambda b: (0 if str(b['id']) in pins_b else 1,
                                      recent.index(str(b['id'])) if str(b['id']) in recent else 999999 - b['id']))
            if query:
                books = [b for b in books if query in b['name'].casefold()]
            folders = sorted(self.store.folders(), key=lambda f: (0 if str(f['id']) in pins_f else 1,
                                                                  f['name'].casefold()))
            folder_ids = {f['id'] for f in folders}
            inside, loose = {}, []
            for b in books:
                if b['folder_id'] in folder_ids:
                    inside.setdefault(b['folder_id'], []).append(b)
                else:
                    loose.append(b)
            for b in [b for b in loose if str(b['id']) in pins_b]:
                tree.addTopLevelItem(self._book_item(b, True))
            for f in folders:
                kids = inside.get(f['id'], [])
                if query and not kids:
                    continue
                item = self._folder_item(f, len(kids), str(f['id']) in pins_f)
                tree.addTopLevelItem(item)
                for b in kids:
                    item.addChild(self._book_item(b, str(b['id']) in pins_b))
                item.setExpanded(True if query else str(f['id']) not in closed)
            for b in [b for b in loose if str(b['id']) not in pins_b]:
                tree.addTopLevelItem(self._book_item(b, False))
            self.highlight_tree()
        finally:
            self._building_tree = False

    def _all_items(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            yield top
            for j in range(top.childCount()):
                yield top.child(j)

    def highlight_tree(self):
        self.tree.clearSelection()
        self.tree.setCurrentItem(None)
        if not self.current:
            return
        for item in self._all_items():
            if item.data(0, R_KIND) == ('book', self.current):
                self.tree.setCurrentItem(item)
                return

    def choose_tree(self, item, _column=0):
        data = item.data(0, R_KIND)
        if data and data[0] == 'book':
            self.select_book(data[1])
        elif data and data[0] == 'folder':
            item.setExpanded(not item.isExpanded())

    def _save_expanded(self, *_):
        if self._building_tree:
            return
        closed = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            data = it.data(0, R_KIND)
            if data and data[0] == 'folder' and not it.isExpanded():
                closed.append(str(data[1]))
        self.prefs.set('closed_folders', closed)
        self.tree.viewport().update()

    def toggle_sidebar(self):
        show = self.sidebar.isHidden()
        self.sidebar.setVisible(show)
        self.prefs.set('sidebar_collapsed', not show)

    def pin_selected(self):
        item = self.tree.currentItem()
        data = item.data(0, R_KIND) if item else None
        if data:
            self.toggle_pin(*data)

    def toggle_pin(self, kind, ident):
        present = self.prefs.toggle_in('pinned_folders' if kind == 'folder' else 'pinned_books', ident)
        self.reload_tree(fresh=True)
        self.say('Pinned to the top' if present else 'Unpinned', 'info')

    def tree_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        if item is None:
            menu.addAction('New logbook…', self.add_book)
            menu.addAction('New folder…', self.add_folder)
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        data = item.data(0, R_KIND)
        if not data:
            return
        kind, ident = data
        key = 'pinned_folders' if kind == 'folder' else 'pinned_books'
        pinned = str(ident) in self.prefs.id_list(key)
        menu.addAction('Unpin' if pinned else 'Pin to top', lambda: self.toggle_pin(kind, ident))
        menu.addSeparator()
        if kind == 'folder':
            menu.addAction('Rename folder…', lambda: self.rename_folder(ident))
            menu.addAction('Delete folder', lambda: self.remove_folder(ident))
        else:
            menu.addAction('Open', lambda: self.select_book(ident))
            menu.addAction('Move to folder…', lambda: self.move_book(ident))
            menu.addAction('Duplicate logbook…', lambda: self.copy_book(ident))
            menu.addAction('Archive logbook', lambda: self.archive_book(ident))
            menu.addSeparator()
            menu.addAction('Delete logbook', lambda: self.delete_book(ident))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ===================================================================================== screens
    def popup(self, menu, anchor):
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))

    def refresh_welcome(self):
        overview = self.store.overview()
        last = self.store.last_dates()
        books = {str(b['id']): b for b in self.store.books()}
        order = [i for i in self._recent_order if i in books]
        rest = sorted((i for i in books if i not in order), key=lambda i: -int(i))
        recent = [(books[i], last.get(books[i]['id'])) for i in (order + rest)[:6]]
        try:
            upcoming = insights.upcoming(self.store)
        except Exception:  # noqa: BLE001 - a summary must never stop Home from showing
            upcoming = []
        self.welcome.refresh(overview, recent, upcoming)
        self.sidebar.set_counts(overview['archived'], overview['recycled'])

    def go_home(self):
        self.current = None
        self.sort_key, self.sort_reverse = None, False
        self.row_ids = []
        self.refresh_welcome()
        self.pages.setCurrentWidget(self.welcome)
        fade_in(self.welcome)
        self.highlight_tree()
        self.crumb.setText('Home')
        self.setWindowTitle('Ledgerbook · ' + VERSION)

    def book_row(self, bid=None):
        return self.store.book(bid or self.current) if (bid or self.current) else None

    def select_book(self, bid):
        book = self.store.book(bid)
        if not book:
            return
        switching = bid != self.current
        self.current = bid
        self.prefs.touch_recent(bid)
        if switching:
            self.sort_key, self.sort_reverse = None, False
            self.view.search.edit.blockSignals(True)
            self.view.search.clear()
            self.view.search.edit.blockSignals(False)
            self.view.search.clear_btn.hide()
        self.pages.setCurrentWidget(self.view)
        if switching:
            fade_in(self.view, 150)
        self.highlight_tree()
        self.load_rows()
        self.update_header()
        self.sidebar.set_counts(*self._counts())

    def _counts(self):
        o = self.store.overview()
        return o['archived'], o['recycled']

    def update_header(self):
        book = self.book_row()
        if not book:
            return
        folder = ''
        if book['folder_id'] is not None:
            for f in self.store.folders():
                if f['id'] == book['folder_id']:
                    folder = f['name']
        last = self.store.last_dates().get(book['id'])
        self.view.set_book(book, len(self.store.columns(book['id'])), last, folder)
        self.crumb.setText(('%s  ›  %s' % (folder, book['name'])) if folder else book['name'])
        self.setWindowTitle('%s · Ledgerbook' % book['name'])

    def after_data_change(self):
        """Refresh everything that depends on stored data without re-sorting the sidebar."""
        self.reload_tree()
        if self.current:
            self.load_rows()
            self.update_header()
        else:
            self.refresh_welcome()
        self.sidebar.set_counts(*self._counts())

    # ===================================================================================== table
    def _sort_rows(self, rows):
        if self.sort_key is None:
            return rows

        def key(r):
            v = self.store.values(r).get(self.sort_key, '')
            try:
                return (0, float(v))
            except (ValueError, TypeError):
                return (1, str(v or '').casefold())

        return sorted(rows, key=key, reverse=self.sort_reverse)

    def load_rows(self, *_):
        if not self.current:
            self.row_ids = []
            return
        fields = [f for f in self.store.columns(self.current) if f.get('visible', True)]
        self._visible_fields = fields
        query = self.view.search.text()
        rows = self._sort_rows(self.store.entries(self.current, query))
        self.row_ids = [r['id'] for r in rows]
        widths = self.prefs.get('column_widths', {}).get(str(self.current), {})
        self._rendering = True
        shown = [(r['id'], self.store.values(r)) for r in rows]
        try:
            self.view.populate(fields, shown, self.sort_key, self.sort_reverse, widths, self._rwx_index_for(fields))
        finally:
            self._rendering = False
        self.view.set_totals(insights.totals_text(fields, [v for _i, v in shown]))
        total = self.store.db.execute('SELECT COUNT(*) FROM entries WHERE book_id=?', (self.current,)).fetchone()[0]
        if rows:
            self.view.show_state(self.view.TABLE)
        elif query.strip():
            self.view.show_state(self.view.NO_RESULTS, query.strip())
        else:
            self.view.show_state(self.view.EMPTY)
        self.view.chip_entries.setText(plural(total, 'entry', 'entries'))
        self.view.count.setText(('%d of %s' % (len(rows), plural(total, 'entry', 'entries'))) if query.strip()
                                else plural(total, 'entry', 'entries'))
        self.view.set_sort_chip(self._sort_text())
        self.selection_changed()

    def _sort_text(self):
        if self.sort_key is None:
            return ''
        label_text = next((f['label'] for f in self._visible_fields if f['key'] == self.sort_key), 'Date')
        return 'Sorted by %s %s  ✕' % (label_text, '▼' if self.sort_reverse else '▲')

    def sort_column(self, idx):
        if idx == 0:
            key = 'entry_date'
        else:
            if idx - 1 >= len(self._visible_fields):
                return
            key = self._visible_fields[idx - 1]['key']
        self.sort_reverse = (not self.sort_reverse) if key == self.sort_key else False
        self.sort_key = key
        self.load_rows()

    def clear_sort(self):
        self.sort_key, self.sort_reverse = None, False
        self.load_rows()

    def save_width(self, idx, old, new):
        if not self.current or idx < 1 or self._rendering or idx > len(self._visible_fields):
            return
        widths = self.prefs.data.setdefault('column_widths', {}).setdefault(str(self.current), {})
        widths[self._visible_fields[idx - 1]['key']] = new

    def save_widths(self):
        if not self.current:
            return
        widths = self.prefs.data.setdefault('column_widths', {}).setdefault(str(self.current), {})
        for i, f in enumerate(self._visible_fields, 1):
            widths[f['key']] = self.table.columnWidth(i)
        self.prefs.save()

    def selected_rows(self):
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def selection_changed(self):
        self.view.update_selection(len(self.selected_rows()))

    def focus_search(self):
        if self.current:
            self.view.search.focus()
        else:
            self.open_palette()

    def cell_double_click(self, index):
        if not index.isValid() or index.column() == 0:
            return
        item = self.table.item(index.row(), index.column())
        full = str(item.data(Qt.ItemDataRole.UserRole) or '') if item else ''
        if item and (len(full) > MAX_CELL or '\n' in full) and index.column() - 1 < len(self._visible_fields):
            FullTextDialog(self, self._visible_fields[index.column() - 1]['label'], full).run()
        else:
            self.edit_entry()

    def entry_menu(self, pos):
        item = self.table.itemAt(pos)
        if item is not None and not item.isSelected():
            self.table.selectRow(item.row())
        n = len(self.selected_rows())
        if not n:
            return
        menu = QMenu(self)
        edit = menu.addAction('Edit entry', self.edit_entry)
        edit.setEnabled(n == 1)
        menu.addAction('Duplicate' if n == 1 else 'Duplicate %d entries' % n, self.duplicate_entry)
        for text, action in (self.entry_extra_actions(self.selected_rows()[0]) if n == 1 else []):
            menu.addAction(text, action)
        menu.addSeparator()
        menu.addAction('Delete' if n == 1 else 'Delete %d entries' % n, self.delete_entries)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def entry_extra_actions(self, row_index):
        """Menu actions that depend on one entry's values: open its attachments, show its RevisionWorx documents."""
        out = []
        for path in self.attachment_values(row_index):
            out.append(('Open %s' % (Path(path).name or path), lambda p=path: self.open_attachment(p)))
        for number in (self.revision_values(row_index) if self.rwx else []):
            out.append(('Show %s in RevisionWorx' % number, lambda num=number: self.show_in_rwx(num)))
        return out

    def _row_values(self, row_index):
        if not self.current or row_index >= len(self.row_ids):
            return None
        row = self.store.db.execute('SELECT * FROM entries WHERE id=?', (self.row_ids[row_index],)).fetchone()
        return self.store.values(row) if row is not None else None

    def attachment_values(self, row_index):
        if not self.current:
            return []
        values = self._row_values(row_index) or {}
        return [str(values[f['key']]).strip() for f in self.store.columns(self.current)
                if f['type'] == 'attachment' and str(values.get(f['key'], '') or '').strip()]

    def open_attachment(self, path):
        if not Path(path).exists():
            self.say('File not found: %s' % path, 'bad')
            return False
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))
        return True

    def open_entry(self, book_id, entry_id):
        """Open a logbook with one entry selected (from Home's Coming up list)."""
        self.select_book(book_id)
        if self.view.search.text():
            self.view.search.clear()
            self.load_rows()
        if entry_id in self.row_ids:
            row = self.row_ids.index(entry_id)
            self.table.clearSelection()
            self.table.selectRow(row)
            self.table.scrollToItem(self.table.item(row, 0))
            return True
        return False

    # ===================================================================================== RevisionWorx (optional)
    def in_background(self, fn, done):
        """Run ``fn`` off the UI thread; ``done(value, error)`` runs on the UI thread afterwards."""
        fut = self._pool.submit(fn)

        def check():
            if self._closing:              # the window (and its database) is gone: drop late results
                return
            if not fut.done():
                QTimer.singleShot(50, check)
                return
            try:
                value, err = fut.result(), None
            except Exception as e:  # noqa: BLE001
                value, err = None, e
            try:
                done(value, err)
            except RuntimeError:
                pass
        QTimer.singleShot(50, check)

    def _rwx_ready(self, rwx, _err):
        self.rwx = rwx or False
        if self.rwx and self.current:
            self.load_rows()

    def _rwx_index_for(self, fields):
        """The document index when the shown columns need it; starts a background refresh when it is stale."""
        if not self.rwx or not any(f['type'] == 'revision' for f in fields):
            return None
        if time.monotonic() - self._rwx_loaded_at > self.RWX_STALE_SECONDS and not self._rwx_loading:
            self._rwx_loading = True
            self.in_background(self.rwx.documents, self._rwx_documents_loaded)
        return self._rwx_index

    def _rwx_documents_loaded(self, docs, err):
        self._rwx_loading = False
        self._rwx_loaded_at = time.monotonic()
        if err is None:
            self._rwx_docs, self._rwx_index = docs, rwxlink.index(docs)
        elif self._rwx_index is None:
            self.say('RevisionWorx status unavailable: %s' % err, 'warn')
        if self.current:
            self.load_rows()

    def rwx_documents(self, fresh=False):
        """Every RevisionWorx document (for pickers). Raises RwxError."""
        if fresh or self._rwx_docs is None:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                docs = self.rwx.documents()
            finally:
                QApplication.restoreOverrideCursor()
            self._rwx_docs, self._rwx_index, self._rwx_loaded_at = docs, rwxlink.index(docs), time.monotonic()
        return self._rwx_docs

    def refresh_rwx(self):
        self._rwx_loaded_at = 0.0
        if self.current:
            self.load_rows()

    def revision_values(self, row_index):
        """Document numbers in the RevisionWorx document columns of a table row."""
        if not self.current or row_index >= len(self.row_ids):
            return []
        row = self.store.db.execute('SELECT * FROM entries WHERE id=?', (self.row_ids[row_index],)).fetchone()
        if row is None:
            return []
        values = self.store.values(row)
        out = []
        for f in self.store.columns(self.current):
            v = str(values.get(f['key'], '') or '').strip()
            if f['type'] == 'revision' and v and v not in out:
                out.append(v)
        return out

    def show_in_rwx(self, number):
        """Open the document in the RevisionWorx window."""
        doc, _problem = rwxlink.lookup(number, self._rwx_index)
        ref = doc['id'] if doc else number
        self.in_background(lambda: self.rwx.open(document=ref),
                           lambda _v, e: e is not None and self.say(str(e), 'bad'))

    # ===================================================================================== entries
    def _need_book(self):
        if self.current:
            return True
        self.say('Open a logbook first', 'info')
        return False

    def add_entry(self):
        if not self._need_book():
            return
        book = self.book_row()
        if EntryDialog(self, self.store, self.current, None, book['name']).run():
            self.after_data_change()
            self.say('Entry added')

    def edit_entry(self, *_):
        selected = self.selected_rows()
        if not self.current or not selected:
            return
        row = self.store.db.execute('SELECT * FROM entries WHERE id=?', (self.row_ids[selected[0]],)).fetchone()
        if row and EntryDialog(self, self.store, self.current, row, self.book_row()['name']).run():
            self.load_rows()
            self.update_header()
            self.say('Entry saved')

    def duplicate_entry(self):
        selected = self.selected_rows()
        if not selected or not self.current:
            return
        try:
            for i in selected:
                row = self.store.db.execute('SELECT * FROM entries WHERE id=?', (self.row_ids[i],)).fetchone()
                if row:
                    self.store.save_entry(self.current, self.store.values(row))
        except Exception as e:  # noqa: BLE001
            error(self, e)
            return
        self.after_data_change()
        self.say('Duplicated %s' % plural(len(selected), 'entry', 'entries'))

    def delete_entries(self):
        selected = self.selected_rows()
        if not selected or not self.current:
            return
        self._last_deleted = []
        for i in selected:
            self.store.delete_entry(self.row_ids[i])
            self._last_deleted.append(self.store.db.execute('SELECT MAX(id) FROM deleted_entries').fetchone()[0])
        self.after_data_change()
        self.say('Moved %s to the Recycle Bin' % plural(len(selected), 'entry', 'entries'), 'info', 'Undo',
                 self.undo_delete)

    def undo_delete(self):
        if not self._last_deleted:
            self.say('Nothing to undo', 'info')
            return
        restored = 0
        for ident in self._last_deleted:
            try:
                self.store.restore_deleted_entry(ident)
                restored += 1
            except ValueError:
                pass
        self._last_deleted = []
        self.after_data_change()
        self.say('Restored %s' % plural(restored, 'entry', 'entries'))

    # ===================================================================================== logbooks & folders
    def add_book(self):
        dlg = LogbookDialog(self, self.store)
        if not dlg.run():
            return
        d = dlg.result_data
        try:
            tpl = d.get('template')
            fields = templates.fields(tpl) if tpl and tpl != 'Blank' else None
            bid = self.store.add_book(d['name'], d['description'], fields=fields)
            self.store.configure_book(bid, icon=d['icon'], accent=d['accent'])
            if d['folder_id'] is not None:
                self.store.configure_book(bid, folder_id=d['folder_id'])
        except Exception as e:  # noqa: BLE001
            error(self, e)
            return
        self.prefs.touch_recent(bid)
        self.reload_tree(fresh=True)
        self.select_book(bid)
        self.say('Created “%s”' % d['name'])

    def add_folder(self):
        name = prompt(self, 'New folder', 'Folder name', ok='Create folder', placeholder='e.g. Workshop')
        if not name:
            return
        try:
            self.store.add_folder(name)
        except sqlite3.IntegrityError:
            error(self, 'A folder named “%s” already exists.' % name)
            return
        except Exception as e:  # noqa: BLE001
            error(self, e)
            return
        self.reload_tree(fresh=True)
        self.say('Folder “%s” created' % name)

    def rename_folder(self, fid):
        current = next((f['name'] for f in self.store.folders() if f['id'] == fid), '')
        name = prompt(self, 'Rename folder', 'Folder name', current, 'Rename')
        if not name or name == current:
            return
        try:
            self.store.rename_folder(fid, name)
        except sqlite3.IntegrityError:
            error(self, 'A folder named “%s” already exists.' % name)
            return
        self.reload_tree(fresh=True)
        self.update_header() if self.current else None

    def remove_folder(self, fid):
        if confirm(self, 'Delete folder?', 'Its logbooks are not deleted; they move back to the top level of your '
                   'library.', 'Delete folder', True):
            self.store.delete_folder(fid)
            self.reload_tree(fresh=True)
            self.update_header() if self.current else None

    def move_book(self, bid):
        folders = list(self.store.folders())
        labels = ['Unfiled'] + [f['name'] for f in folders]
        book = self.store.book(bid)
        start = 0
        for n, f in enumerate(folders, 1):
            if book and f['id'] == book['folder_id']:
                start = n
        choice = pick_item(self, 'Move logbook', 'Destination', labels, start, 'Move')
        if choice is None:
            return
        if choice == 0:
            with self.store.db:
                self.store.db.execute('UPDATE books SET folder_id=NULL WHERE id=?', (bid,))
        else:
            self.store.configure_book(bid, folder_id=folders[choice - 1]['id'])
        self.reload_tree(fresh=True)
        self.update_header() if self.current else None
        self.say('Moved to %s' % labels[choice])

    def copy_book(self, bid):
        pick = choose(self, 'Duplicate logbook', 'Copy this logbook’s columns, and optionally all of its entries too.',
                      'Copy with entries', 'Structure only')
        if pick is None:
            return
        try:
            new = self.store.duplicate_book(bid, pick == 'primary')
        except Exception as e:  # noqa: BLE001
            error(self, e)
            return
        self.reload_tree(fresh=True)
        self.select_book(new)
        self.say('Logbook duplicated')

    def archive_book(self, bid):
        if confirm(self, 'Archive logbook?', 'It disappears from the sidebar but keeps all of its data. Bring it back '
                   'any time from Archived logbooks.', 'Archive'):
            self.store.configure_book(bid, archived=1)
            if self.current == bid:
                self.go_home()
            self.reload_tree(fresh=True)
            self.refresh_welcome()
            self.say('Logbook archived', 'info')

    def delete_book(self, bid):
        book = self.store.book(bid)
        if not book:
            return
        if confirm(self, 'Delete logbook?', '“%s” and its entries move to the Recycle Bin, where you can restore them.'
                   % book['name'], 'Delete logbook', True):
            self.store.delete_book(bid)
            if self.current == bid:
                self.go_home()
            self.reload_tree(fresh=True)
            self.refresh_welcome()
            self.say('Moved “%s” to the Recycle Bin' % book['name'], 'info')

    def manage_book(self):
        if not self._need_book():
            return
        book = self.book_row()
        dlg = LogbookDialog(self, self.store, book)
        if not dlg.run():
            return
        d = dlg.result_data
        try:
            self.store.update_book(self.current, d['name'], d['description'])
            self.store.configure_book(self.current, icon=d['icon'], accent=d['accent'])
            with self.store.db:
                self.store.db.execute('UPDATE books SET folder_id=? WHERE id=?', (d['folder_id'], self.current))
        except Exception as e:  # noqa: BLE001
            error(self, e)
            return
        self.reload_tree(fresh=True)
        self.update_header()
        self.say('Logbook updated')

    def columns(self):
        if not self._need_book():
            return
        if ColumnsDialog(self, self.store, self.current, self.book_row()['name']).run():
            self.load_rows()
            self.update_header()
            self.say('Columns updated')

    def book_menu(self):
        menu = QMenu(self)
        menu.addAction('Edit logbook…', self.manage_book)
        pinned = str(self.current) in self.prefs.id_list('pinned_books')
        menu.addAction('Unpin from top' if pinned else 'Pin to top', lambda: self.toggle_pin('book', self.current))
        menu.addAction('Move to folder…', lambda: self.move_book(self.current))
        menu.addAction('Duplicate logbook…', lambda: self.copy_book(self.current))
        menu.addAction('Archive logbook', lambda: self.archive_book(self.current))
        menu.addSeparator()
        menu.addAction('Delete logbook', lambda: self.delete_book(self.current))
        return menu

    def data_menu(self):
        menu = QMenu(self)
        menu.addAction('Import CSV…', self.import_csv)
        menu.addAction('Export CSV…', self.export_csv)
        menu.addAction('PDF report…', self.export_pdf)
        menu.addSeparator()
        menu.addAction('Export complete logbook (.ledgerbook)…', self.export_book)
        menu.addAction('Import logbook (.ledgerbook)…', self.import_book)
        return menu

    # ===================================================================================== recovery
    def recycle_bin(self):
        def changed(done):
            self.after_data_change()
            if done:
                self.say('Restored %d item%s' % (done, '' if done == 1 else 's'))

        RecycleDialog(self, self.store, changed).run()
        self.after_data_change()

    def archived_books(self):
        def changed(done):
            self.reload_tree(fresh=True)
            self.refresh_welcome()
            self.sidebar.set_counts(*self._counts())
            if done:
                self.say('Restored %d logbook%s' % (done, '' if done == 1 else 's'))

        ArchiveDialog(self, self.store, changed).run()

    # ===================================================================================== import / export
    def import_csv(self):
        if not self._need_book():
            return
        path = self.pick_open('Import CSV', 'CSV files (*.csv);;All files (*)')
        if not path:
            return
        try:
            rep = self.store.import_csv_report(self.current, path)
        except Exception as e:  # noqa: BLE001
            error(self, e, 'Nothing was imported')
            return
        n = rep['imported']
        if n == 0:
            labels = ', '.join(f['label'] for f in self.store.columns(self.current))
            found = (' Headings found: %s.' % ', '.join(rep['ignored'])) if rep['ignored'] else ''
            notify(self, 'Nothing imported', 'No rows were imported. The first row of the CSV must contain column '
                   'headings that match this logbook (case and spacing do not matter): %s.%s' % (labels, found))
            return
        self.after_data_change()
        extra = ('; ignored column%s: %s' % ('' if len(rep['ignored']) == 1 else 's', ', '.join(rep['ignored']))
                 if rep['ignored'] else '')
        self.say('Imported %s%s' % (plural(n, 'entry', 'entries'), extra), 'warn' if extra else 'good')

    def export_csv(self):
        if not self._need_book():
            return
        path = self.pick_save('Export CSV', slug(self.book_row()['name']) + '.csv', 'CSV files (*.csv)')
        if path:
            try:
                self.store.export_csv(self.current, path)
            except Exception as e:  # noqa: BLE001
                error(self, e)
                return
            self.say('CSV exported', 'good', 'Show', lambda: self._reveal(path))

    def export_calendar(self, path=None):
        """Every logbook's current due dates as an iCalendar (.ics) file, for Google Calendar, Outlook, Thunderbird or Apple's Calendar.
        ``path`` stands in for the file dialog."""
        items = insights.due_dates(self.store)
        if not items:
            notify(self, 'No due dates', 'None of your logbooks has a due date yet. A Due date column in a logbook gives it some.')
            return False
        path = path or self.pick_save('Export due dates', 'ledgerbook-due-dates.ics', 'Calendar files (*.ics)')
        if not path:
            return False
        destination = Path(path)
        if not destination.suffix:                       # calendars look for .ics
            destination = destination.with_suffix('.ics')
            path = str(destination)
        temporary = destination.with_name(destination.name + '.tmp')
        try:
            temporary.write_bytes(insights.calendar(items))
            temporary.replace(destination)
        except OSError as e:
            error(self, e)
            return False
        finally:
            temporary.unlink(missing_ok=True)
        self.say('Exported %s for your calendar' % plural(len(items), 'due date', 'due dates'), 'good', 'Show', lambda: self._reveal(path))
        return True

    def export_book(self):
        if not self._need_book():
            return
        path = self.pick_save('Export logbook', slug(self.book_row()['name']) + '.ledgerbook',
                              'Ledgerbook (*.ledgerbook)')
        if path:
            try:
                n = self.store.export_logbook(self.current, path)
            except Exception as e:  # noqa: BLE001
                error(self, e)
                return
            self.say('Exported %s' % plural(n, 'entry', 'entries'), 'good', 'Show', lambda: self._reveal(path))

    def import_book(self):
        path = self.pick_open('Import logbook', 'Ledgerbook (*.ledgerbook);;All files (*)')
        if not path:
            return
        try:
            bid, n = self.store.import_logbook(path)
        except Exception as e:  # noqa: BLE001
            error(self, e, 'Could not import logbook')
            return
        self.prefs.touch_recent(bid)
        self.reload_tree(fresh=True)
        self.select_book(bid)
        self.say('Imported logbook with %s' % plural(n, 'entry', 'entries'))

    def export_pdf(self):
        if not self._need_book():
            return
        selected = len(self.selected_rows())
        dlg = PdfDialog(self, self.store.columns(self.current), len(self.row_ids), selected)
        if not dlg.run():
            return
        opts = dlg.result_data
        path = self.pick_save('Save PDF', slug(self.book_row()['name']) + '-report.pdf', 'PDF files (*.pdf)')
        if not path:
            return
        ids = list(self.row_ids)
        if opts['rng']:
            a, b = opts['rng']
            ids = ids[a - 1:b]
        try:
            rows = []
            for i in ids:
                row = self.store.db.execute('SELECT * FROM entries WHERE id=?', (i,)).fetchone()
                if row:
                    rows.append(self.store.values(row))
            book = self.book_row()
            subtitle = '%s  ·  generated %s' % (plural(len(rows), 'entry', 'entries'), fmt_date(date.today().isoformat()))
            pages = pdf_report(path, book['name'], opts['fields'], rows, subtitle, opts['landscape'],
                               summary=insights.totals_text(opts['fields'], rows))
        except Exception as e:  # noqa: BLE001
            error(self, e, 'Could not create the report')
            return
        self.say('PDF saved (%s)' % plural(pages, 'page'), 'good', 'Open',
                 lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))

    def _reveal(self, path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    # ===================================================================================== backup
    def backup(self):
        name = 'ledgerbook-backup-%s.sqlite3' % date.today().isoformat()
        path = self.pick_save('Back up database', name, 'SQLite (*.sqlite3)')
        if path:
            try:
                self.store.backup(path)
            except Exception as e:  # noqa: BLE001
                error(self, e)
                return
            self.say('Backup saved', 'good', 'Show', lambda: self._reveal(path))

    def restore_backup(self):
        path = self.pick_open('Restore database backup', 'SQLite (*.sqlite3 *.db);;All files (*)')
        if not path:
            return
        if not confirm(self, 'Restore this backup?', 'This replaces ALL current logbooks with the backup. A safety copy '
                       'of your current library is saved first.', 'Replace library', True):
            return
        try:
            source = sqlite3.connect('file:' + Path(path).resolve().as_posix() + '?mode=ro', uri=True)
            try:
                if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Selected backup is corrupt')
                self.store.backup(str(self.store.path.with_name(
                    'before-restore-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.sqlite3')))
                source.backup(self.store.db)
            finally:
                source.close()
        except Exception as e:  # noqa: BLE001
            error(self, e, 'Could not restore the backup')
            return
        self.go_home()
        self.reload_tree(fresh=True)
        self.say('Backup restored')

    def integrity_check(self):
        try:
            result = self.store.integrity_check()
        except Exception as e:  # noqa: BLE001
            error(self, e)
            return
        if result == 'ok':
            notify(self, 'Database is healthy', 'SQLite integrity check passed. No problems were found.')
        else:
            error(self, result, 'Integrity check found problems')

    def auto_backup(self):
        try:
            folder = self.store.path.parent / 'backups'
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / ('ledgerbook-' + date.today().isoformat() + '.sqlite3')
            if not target.exists():
                if self.store.integrity_check() != 'ok':
                    return
                self.store.backup(target)
            backups = sorted(folder.glob('ledgerbook-????-??-??.sqlite3'), reverse=True)
            for old in backups[7:]:
                old.unlink()
        except (OSError, ValueError):
            pass

    # ===================================================================================== palette / dialogs
    def open_palette(self):
        items = []
        folders = {f['id']: f['name'] for f in self.store.folders()}
        for b in self.store.books():
            where = folders.get(b['folder_id'], 'Library')
            items.append(dict(title=b['name'], subtitle='Open logbook  ·  %s  ·  %s' % (where, plural(
                b['entry_count'], 'entry', 'entries')), icon='book', action=lambda i=b['id']: self.select_book(i)))
        actions = [
            ('New entry', 'plus', self.add_entry), ('New logbook', 'book_plus', self.add_book),
            ('New folder', 'folder_plus', self.add_folder), ('Go to Home', 'home', self.go_home),
            ('Manage columns', 'columns', self.columns), ('Edit logbook', 'pencil', self.manage_book),
            ('Import logbook', 'upload', self.import_book), ('Import CSV', 'inbox', self.import_csv),
            ('Export logbook', 'download', self.export_book), ('Export CSV', 'table', self.export_csv),
            ('PDF report', 'file', self.export_pdf), ('Export due dates to a calendar', 'download', self.export_calendar),
            ('Back up database', 'database', self.backup),
            ('Restore backup', 'reset', self.restore_backup), ('Recycle Bin', 'trash', self.recycle_bin),
            ('Archived logbooks', 'archive', self.archived_books), ('Settings', 'sliders', self.settings),
            ('Toggle sidebar', 'sidebar', self.toggle_sidebar), ('Database integrity check', 'shield', self.integrity_check),
            ('About Ledgerbook', 'info', self.about),
        ]
        for title, icon_name, fn in actions:
            items.append(dict(title=title, subtitle='Action', icon=icon_name, action=fn))
        for name in theme.THEMES:
            items.append(dict(title='Theme: ' + name, subtitle='Appearance', icon='palette',
                              action=lambda n=name: self.change_theme(n)))
        action = CommandPalette(self, items).run()
        if action:
            QTimer.singleShot(0, action)

    def settings(self):
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.show()

    def about(self):
        AboutDialog(self).run()

    def show_whats_new(self, force=False):
        if not force and (self.prefs.get('seen_version') == VERSION
                          or self.prefs.get('release_notes_dismissed') == VERSION):
            return
        dlg = WhatsNewDialog(self, VERSION)
        dlg.run()
        if dlg.skip.isChecked():
            self.qsettings.setValue('release_seen', VERSION)
            self.prefs.set('seen_version', VERSION, save=False)
            self.prefs.set('release_notes_dismissed', VERSION)

    def show_whats_new_now(self):
        self.show_whats_new(force=True)

    def closeEvent(self, event):
        self._closing = True
        self._pool.shutdown(wait=False)
        if self.settings_dialog is not None:
            self.settings_dialog.close()
        self.save_widths()
        self.prefs.set('geometry', '%dx%d' % (self.width(), self.height()))
        try:
            self.store.close()
        except sqlite3.Error:
            pass
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Ledgerbook')
    app.setOrganizationName('Nate Robertson')
    app.setApplicationVersion(VERSION)
    app.setDesktopFileName('ledgerbook')  # matches ledgerbook.desktop so the taskbar shows the right icon
    if APP_ICON.exists():
        app.setWindowIcon(QIcon(str(APP_ICON)))
    window = Main()
    window.show()
    sys.exit(app.exec())
