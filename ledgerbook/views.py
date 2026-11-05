"""The two main screens: the home dashboard and the logbook table."""
from datetime import date
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHeaderView, QLabel, QScrollArea, QSizePolicy,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QWidget, QGridLayout)

from . import insights
from . import revisionworx as rwxlink
from . import theme
from .constants import DEFAULT_ICON
from .util import fmt_date, greeting, is_true, plural, relative_day
from .widgets import (Card, ClickCard, IconTile, Pill, SearchBox, button, divider, hbox, icon_button, label, vbox)

T = theme.current
MAX_CELL = 110


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


# ===================================================================================== home dashboard
class WelcomeView(QScrollArea):
    """Shown when no logbook is open: totals, recent logbooks and quick actions."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer = QWidget()
        self.setWidget(outer)
        row = hbox(outer, (32, 0, 32, 0))
        row.addStretch(1)
        self.content = QWidget()
        self.content.setMaximumWidth(1060)
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(self.content, 100)
        row.addStretch(1)
        self.col = vbox(self.content, (0, 28, 0, 40), 22)

    def refresh(self, overview, recent, upcoming=()):
        """``recent`` is a list of (book row, last entry date or None); ``upcoming`` comes from
        ``insights.upcoming`` (what is overdue or due soon)."""
        win = self.win
        clear_layout(self.col)
        # ---- hero
        hero = Card(28, 8, 'hero')
        top = hbox(None, (0, 0, 0, 0), 18)
        words = vbox(None, (0, 0, 0, 0), 6)
        words.addWidget(label(greeting(), 'display'))
        if overview['logbooks']:
            sub = 'You have %s holding %s.' % (plural(overview['logbooks'], 'logbook'),
                                               plural(overview['entries'], 'entry', 'entries'))
        else:
            sub = 'A private, offline home for your logbooks, records and maintenance history.'
        words.addWidget(label(sub, 'muted', wrap=True))
        top.addLayout(words, 1)
        top.addWidget(button('Import logbook', '', 'upload', win.import_book))
        top.addWidget(button('New logbook', 'primary', 'book_plus', win.add_book))
        hero.body.addLayout(top)
        self.col.addWidget(hero)
        if not overview['logbooks']:
            self.col.addWidget(self._empty_state())
            self.col.addStretch(1)
            return
        # ---- stats
        stats = hbox(None, (0, 0, 0, 0), 16)
        last = overview['last_entry']
        for title, value, note in (
                ('LOGBOOKS', str(overview['logbooks']), plural(overview['folders'], 'folder')),
                ('ENTRIES', '{:,}'.format(overview['entries']), 'across all logbooks'),
                ('LAST ENTRY', relative_day(last) if last else '—', fmt_date(last) if last else 'nothing logged yet')):
            card = Card(20, 4)
            card.body.addWidget(label(title, 'eyebrow'))
            card.body.addWidget(label(value, 'statValue'))
            card.body.addWidget(label(note, 'faint'))
            stats.addWidget(card, 1)
        self.col.addLayout(stats)
        # ---- coming up (Due date columns)
        if upcoming:
            self.col.addWidget(self._upcoming_card(list(upcoming)))
        # ---- recent logbooks
        head = hbox(None, (0, 6, 0, 0), 8)
        head.addWidget(label('Pick up where you left off', 'h2'))
        head.addStretch(1)
        self.col.addLayout(head)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        for n, (book, last_date) in enumerate(recent):
            grid.addWidget(self._book_card(book, last_date), n // 3, n % 3)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        self.col.addLayout(grid)
        # ---- tip
        tip = hbox(None, (0, 6, 0, 0), 8)
        tip.addStretch(1)
        tip.addWidget(label('Tip: press', 'faint'))
        tip.addWidget(label('Ctrl', 'kbd'))
        tip.addWidget(label('K', 'kbd'))
        tip.addWidget(label('to jump to any logbook or action.', 'faint'))
        tip.addStretch(1)
        self.col.addLayout(tip)
        self.col.addStretch(1)

    def _upcoming_card(self, items, limit=8):
        card = Card(20, 6)
        head = hbox(None, (0, 0, 0, 4), 8)
        head.addWidget(label('Coming up', 'h2'))
        overdue = sum(1 for it in items if it['days'] < 0)
        head.addWidget(label(('%d overdue  ·  ' % overdue if overdue else '') +
                             'due in the next %d days' % insights.HORIZON_DAYS, 'faint'))
        head.addStretch(1)
        card.body.addLayout(head)
        t = theme.current()
        self.upcoming_rows = []
        for it in items[:limit]:
            row = ClickCard(10, 2)
            line = hbox(None, (0, 0, 0, 0), 12)
            when = label(insights.due_text(it['days']), 'h3')
            tone = 'bad' if it['days'] < 0 else ('warn' if it['days'] <= insights.SOON_DAYS else 'muted')
            when.setStyleSheet('color: %s;' % t[tone])
            when.setMinimumWidth(130)
            line.addWidget(when)
            what = label('%s  ·  %s' % (it['item'], it['field']), 'h3')
            what.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            what.setMinimumWidth(10)
            line.addWidget(what, 1)
            line.addWidget(label('%s  ·  %s' % (it['book'], fmt_date(it['due'])), 'faint'))
            row.body.addLayout(line)
            row.setToolTip('Open %s at this entry' % it['book'])
            row.clicked.connect(lambda b=it['book_id'], e=it['entry_id']: self.win.open_entry(b, e))
            card.body.addWidget(row)
            self.upcoming_rows.append((it, row))
        if len(items) > limit:
            card.body.addWidget(label('…and %d more' % (len(items) - limit), 'faint'))
        return card

    def _book_card(self, book, last_date):
        card = ClickCard(18, 12)
        top = hbox(None, (0, 0, 0, 0), 12)
        top.addWidget(IconTile(44, book['icon'] or DEFAULT_ICON, '', theme.book_color(book['id'], book['accent'])),
                      0, Qt.AlignmentFlag.AlignTop)
        names = vbox(None, (0, 0, 0, 0), 2)
        title = label(book['name'], 'h2')
        title.setMinimumWidth(10)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        names.addWidget(title)
        names.addWidget(label(plural(book['entry_count'], 'entry', 'entries'), 'muted'))
        top.addLayout(names, 1)
        card.body.addLayout(top)
        desc = (book['description'] or '').strip().replace('\n', ' ')
        info = label(desc if desc else ('Last entry: %s' % relative_day(last_date) if last_date else 'No entries yet'),
                     'faint', wrap=False)
        info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        info.setMinimumWidth(10)
        card.body.addWidget(info)
        card.clicked.connect(lambda bid=book['id']: self.win.select_book(bid))
        return card

    def _empty_state(self):
        frame = QFrame()
        frame.setObjectName('empty')
        lay = vbox(frame, (40, 48, 40, 48), 10)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(IconTile(64, '', 'book'), 0, Qt.AlignmentFlag.AlignHCenter)
        title = label('Create your first logbook', 'h1')
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(title)
        text = label('A logbook is a table you design: add the columns you need, then log entries as they happen. '
                     'Everything stays on this computer.', 'muted', wrap=True)
        text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        text.setMaximumWidth(460)
        lay.addWidget(text, 0, Qt.AlignmentFlag.AlignHCenter)
        row = hbox(None, (0, 12, 0, 0), 10)
        row.addStretch(1)
        row.addWidget(button('New logbook', 'primary', 'book_plus', self.win.add_book))
        row.addWidget(button('Import logbook', '', 'upload', self.win.import_book))
        row.addStretch(1)
        lay.addLayout(row)
        return frame


# ===================================================================================== logbook screen
class LogbookView(QWidget):
    """Header, toolbar, table (with empty states) and footer for one open logbook."""
    TABLE, EMPTY, NO_RESULTS = 0, 1, 2

    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = vbox(self, (32, 24, 32, 18), 16)
        # ---- header
        head = hbox(None, (0, 0, 0, 0), 16)
        self.tile = IconTile(58, DEFAULT_ICON)
        head.addWidget(self.tile, 0, Qt.AlignmentFlag.AlignTop)
        names = vbox(None, (0, 0, 0, 0), 4)
        self.title = label('', 'h1')
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title.setMinimumWidth(10)
        self.desc = label('', 'muted')
        self.desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.desc.setMinimumWidth(10)
        names.addWidget(self.title)
        names.addWidget(self.desc)
        chips = hbox(None, (0, 6, 0, 0), 8)
        self.chip_entries = Pill('0 entries')
        self.chip_columns = Pill('', 'pillMuted')
        self.chip_last = Pill('', 'pillMuted')
        self.chip_folder = Pill('', 'pillMuted')
        for c in (self.chip_entries, self.chip_columns, self.chip_last, self.chip_folder):
            chips.addWidget(c)
        chips.addStretch(1)
        names.addLayout(chips)
        head.addLayout(names, 1)
        actions = hbox(None, (0, 0, 0, 0), 8)
        self.new_btn = button('New entry', 'primary', 'plus', win.add_entry)
        self.new_btn.setMinimumHeight(40)
        self.columns_btn = button('Columns', 'ghost', 'columns', win.columns)
        self.columns_btn.setMinimumHeight(40)
        self.data_btn = button('Import / Export', 'ghost', 'download', None)
        self.data_btn.setMinimumHeight(40)
        self.data_btn.clicked.connect(lambda: win.popup(win.data_menu(), self.data_btn))
        self.more_btn = icon_button('more', 'Logbook actions', None, 40, 20, 'muted')
        self.more_btn.clicked.connect(lambda: win.popup(win.book_menu(), self.more_btn))
        for w in (self.new_btn, self.columns_btn, self.data_btn, self.more_btn):
            actions.addWidget(w)
        head.addLayout(actions)
        lay.addLayout(head)
        # ---- toolbar
        bar = hbox(None, (0, 0, 0, 0), 12)
        self.search = SearchBox('Search entries…', 40)
        self.search.setMaximumWidth(420)
        self.search.setMinimumWidth(220)
        bar.addWidget(self.search, 1)
        self.sort_chip = button('', 'chip', 'x', None)
        self.sort_chip.clicked.connect(lambda: win.clear_sort())
        self.sort_chip.hide()
        bar.addWidget(self.sort_chip)
        bar.addStretch(1)
        self.selbar = QFrame()
        self.selbar.setObjectName('selbar')
        sl = hbox(self.selbar, (14, 4, 6, 4), 6)
        self.sel_label = label('', 'h3')
        sl.addWidget(self.sel_label)
        self.edit_btn = button('Edit', 'ghost', 'pencil', win.edit_entry)
        self.dup_btn = button('Duplicate', 'ghost', 'copy', win.duplicate_entry)
        self.del_btn = button('Delete', 'danger', 'trash', win.delete_entries)
        for b in (self.edit_btn, self.dup_btn, self.del_btn):
            b.setMinimumHeight(32)
            sl.addWidget(b)
        self.selbar.hide()
        bar.addWidget(self.selbar)
        lay.addLayout(bar)
        # ---- table and states
        self.stack = QStackedWidget()
        self.table = QTableWidget()
        self._setup_table()
        self.stack.addWidget(self.table)
        self.empty_page, self.empty_title, self.empty_text, self.empty_buttons = self._state_page('inbox')
        self.stack.addWidget(self.empty_page)
        self.nores_page, self.nores_title, self.nores_text, self.nores_buttons = self._state_page('search')
        self.stack.addWidget(self.nores_page)
        self.empty_title.setText('No entries yet')
        self.empty_text.setText('Add your first entry, or import a CSV file whose headings match your columns.')
        self.empty_buttons.addWidget(button('Add first entry', 'primary', 'plus', win.add_entry))
        self.empty_buttons.addWidget(button('Import CSV', '', 'upload', win.import_csv))
        self.nores_title.setText('Nothing matches')
        self.nores_buttons.addWidget(button('Clear search', '', 'x', self.search.clear))
        lay.addWidget(self.stack, 1)
        # ---- footer
        foot = hbox(None, (2, 0, 2, 0), 8)
        self.count = label('', 'faint')
        foot.addWidget(self.count)
        self.totals = label('', 'muted')
        self.totals.setObjectName('totals')
        self.totals.setAccessibleName('Totals of the number columns for the entries shown')
        self.totals.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        foot.addSpacing(18)
        foot.addWidget(self.totals)
        foot.addStretch(1)
        foot.addWidget(label('Double-click to edit  ·  Right-click for more  ·  Hover truncated cells for the full text',
                             'faint'))
        lay.addLayout(foot)

    def _state_page(self, icon_name):
        page = QWidget()
        outer = vbox(page, (0, 30, 0, 30), 0)
        frame = QFrame()
        frame.setObjectName('empty')
        lay = vbox(frame, (40, 44, 40, 44), 10)
        lay.addWidget(IconTile(60, '', icon_name), 0, Qt.AlignmentFlag.AlignHCenter)
        title = label('', 'h1')
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        text = label('', 'muted', wrap=True)
        text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(title)
        lay.addWidget(text)
        buttons = hbox(None, (0, 10, 0, 0), 10)
        row = hbox(None, (0, 0, 0, 0), 10)
        row.addStretch(1)
        row.addLayout(buttons)
        row.addStretch(1)
        lay.addLayout(row)
        outer.addWidget(frame)
        outer.addStretch(1)
        return page, title, text, buttons

    def _setup_table(self):
        t = self.table
        t.setAlternatingRowColors(True)
        t.setShowGrid(False)
        t.verticalHeader().hide()
        t.verticalHeader().setDefaultSectionSize(46)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSortingEnabled(False)
        t.setWordWrap(False)
        t.setTextElideMode(Qt.TextElideMode.ElideRight)
        t.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        t.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t.setMouseTracking(True)
        header = t.horizontalHeader()
        header.setSectionsMovable(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setHighlightSections(False)
        header.setFixedHeight(42)
        header.setCursor(Qt.CursorShape.PointingHandCursor)

    # ------------------------------------------------------------------------------------ content
    def set_book(self, book, field_count, last_date, folder_name):
        color = theme.book_color(book['id'], book['accent'])
        self.tile.configure(book['icon'] or DEFAULT_ICON, '', color)
        self.title.setText(book['name'])
        desc = (book['description'] or '').strip().replace('\n', ' ')
        self.desc.setText(desc or 'No description yet. Open Logbook actions → Edit logbook to add one.')
        self.desc.setObjectName('muted' if desc else 'faint')
        self.desc.style().unpolish(self.desc)
        self.desc.style().polish(self.desc)
        self.chip_columns.setText(plural(field_count, 'column'))
        self.chip_last.setText('Last entry: %s' % relative_day(last_date) if last_date else 'No entries yet')
        self.chip_folder.setText(folder_name or 'Unfiled')

    def show_state(self, state, query=''):
        self.stack.setCurrentIndex(state)
        if state == self.NO_RESULTS:
            self.nores_text.setText('No entries match “%s”. Try a different word, or clear the search.' % query)

    def update_selection(self, n):
        self.selbar.setVisible(n > 0)
        if n:
            self.sel_label.setText('%d selected' % n)
            self.edit_btn.setEnabled(n == 1)
            self.dup_btn.setEnabled(n == 1)

    def set_totals(self, text):
        self.totals.setText(text)
        self.totals.setVisible(bool(text))

    def set_sort_chip(self, text):
        self.sort_chip.setVisible(bool(text))
        self.sort_chip.setText(text)

    def populate(self, fields, rows, sort_key, sort_reverse, saved_widths, rwx_index=None):
        """rows: list of (entry_id, values dict) in display order. ``rwx_index``: RevisionWorx documents by number
        (revisionworx.index) for live status in RevisionWorx document columns, or None."""
        t = T()
        table = self.table
        today = date.today()
        table.setUpdatesEnabled(False)
        table.clearContents()
        table.setColumnCount(len(fields) + 1)
        table.setRowCount(len(rows))
        arrow = ' ▼' if sort_reverse else ' ▲'
        key_to_col = {f['key']: j for j, f in enumerate(fields, 1)}
        arrow_col = key_to_col.get(sort_key, 0 if sort_key == 'entry_date' else None) if sort_key else None
        headers = ['#'] + [str(f['label']).upper() for f in fields]
        if arrow_col is not None:
            headers[arrow_col] += arrow
        table.setHorizontalHeaderLabels(headers)
        faint, accent = QColor(t['faint']), QColor(t['accent'])
        bold = QFont(table.font())
        bold.setWeight(QFont.Weight.DemiBold)
        for i, (entry_id, vals) in enumerate(rows):
            number = QTableWidgetItem(str(i + 1))
            number.setData(Qt.ItemDataRole.UserRole, entry_id)
            number.setForeground(faint)
            number.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(i, 0, number)
            for j, f in enumerate(fields, 1):
                full = str(vals.get(f['key'], '') or '')
                if f['type'] == 'checkbox':
                    cell = QTableWidgetItem('✓' if is_true(full) else '—')
                    cell.setForeground(accent if is_true(full) else faint)
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    cell.setData(Qt.ItemDataRole.UserRole, full)
                    table.setItem(i, j, cell)
                    continue
                if f['type'] == 'due':
                    text, tone = insights.due_cell(full, today)
                    cell = QTableWidgetItem(text)
                    cell.setData(Qt.ItemDataRole.UserRole, full)
                    if tone:
                        cell.setForeground(QColor(t[tone]))
                    table.setItem(i, j, cell)
                    continue
                if f['type'] == 'attachment' and full.strip():
                    cell = QTableWidgetItem(Path(full.strip()).name or full)
                    cell.setData(Qt.ItemDataRole.UserRole, full)
                    cell.setToolTip(full + ('' if Path(full.strip()).exists() else '\n(file not found)'))
                    table.setItem(i, j, cell)
                    continue
                if f['type'] == 'revision':
                    text, tone = rwxlink.cell(full, rwx_index)
                    cell = QTableWidgetItem(text)
                    cell.setData(Qt.ItemDataRole.UserRole, full)
                    if tone:
                        cell.setForeground(QColor(t[tone]))
                    cell.setToolTip(text)
                    table.setItem(i, j, cell)
                    continue
                display = full.replace('\n', ' ⏎ ')
                truncated = len(display) > MAX_CELL
                if truncated:
                    display = display[:MAX_CELL - 3] + '…'
                cell = QTableWidgetItem(display)
                cell.setData(Qt.ItemDataRole.UserRole, full)
                if truncated or '\n' in full:
                    cell.setToolTip(full[:1200] + ('…' if len(full) > 1200 else ''))
                if f['type'] == 'number':
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if f['key'] == 'title':
                    cell.setFont(bold)
                table.setItem(i, j, cell)
        header_font = table.horizontalHeader().font()
        header_font.setBold(True)
        metrics = QFontMetrics(header_font)
        table.setColumnWidth(0, 64)
        for j, f in enumerate(fields, 1):
            need = metrics.horizontalAdvance(str(f['label']).upper() + ' ▼') + 44
            try:
                saved = int(saved_widths.get(f['key'], 200))
            except (TypeError, ValueError):
                saved = 200
            table.setColumnWidth(j, max(130, need, saved))
        table.setUpdatesEnabled(True)
