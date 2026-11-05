"""Modal dialogs: confirmations, prompts and the forms for entries, columns, logbooks, recovery and reports."""
import json
import os

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDialog, QFrame,
                               QGridLayout, QHeaderView, QLineEdit, QListWidget, QListWidgetItem, QScrollArea,
                               QTableWidget, QTableWidgetItem, QTextEdit, QToolButton, QWidget)

from . import icons, theme
from .constants import DEFAULT_ICON, LOGBOOK_ICONS, TYPE_NAMES
from .store import TYPES
from .util import fmt_timestamp, is_true, plural
from .widgets import (IconTile, button, divider, hbox, icon_label, label, set_button_icon, vbox)

T = theme.current


def size_button(b):
    """Make a dialog button big enough for its text (the stylesheet adds padding and a heavier weight)."""
    b.setMinimumHeight(40)
    b.setMinimumWidth(max(104, b.fontMetrics().horizontalAdvance(b.text()) + 56))
    return b


def field_block(caption, widget, hint=''):
    """A caption above an input, optionally followed by a faint hint line."""
    box = QWidget()
    lay = vbox(box, (0, 0, 0, 0), 6)
    lay.addWidget(label(caption, 'h3'))
    lay.addWidget(widget)
    if hint:
        lay.addWidget(label(hint, 'faint', wrap=True))
    return box


# ================================================================================ small frameless sheets
class Sheet(QDialog):
    """Small frameless modal used for confirmations and prompts. ``body`` takes extra widgets."""

    def __init__(self, parent, title, text='', ok='OK', danger=False, width=460, cancel='Cancel', extra=None):
        super().__init__(parent)
        self.setObjectName('sheet')
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setWindowTitle(title)
        self.setFixedWidth(width)
        lay = vbox(self, (28, 26, 28, 22), 12)
        lay.addWidget(label(title, 'h2'))
        if text:
            lay.addWidget(label(text, 'muted', wrap=True))
        self.body = vbox(None, (0, 4, 0, 4), 10)
        lay.addLayout(self.body)
        row = hbox(None, (0, 10, 0, 0), 10)
        row.addStretch(1)
        if cancel:
            row.addWidget(size_button(button(cancel, 'ghost', None, self.reject)))
        if extra:
            row.addWidget(size_button(button(extra, '', None, self._pick_extra)))
        self.ok_btn = size_button(button(ok, 'dangerSolid' if danger else 'primary', None, self.accept))
        row.addWidget(self.ok_btn)
        lay.addLayout(row)
        self._accepted, self.picked = False, None
        self.accepted.connect(self._mark)

    def _mark(self):
        self._accepted = True
        if self.picked is None:
            self.picked = 'ok'

    def _pick_extra(self):
        self.picked = 'extra'
        self.accept()

    def _fit(self):
        """Give the dialog the height its wrapped text really needs (a word-wrapped QLabel reports its height for an
        unwrapped width, which would squeeze the buttons)."""
        self.ensurePolished()
        lay = self.layout()
        lay.activate()
        need = lay.sizeHint().height()
        if lay.hasHeightForWidth():
            need = max(need, lay.heightForWidth(self.width()))
        self.setFixedHeight(need + 4)

    def run(self):
        """Show modally; True only when a primary/extra button (not Cancel) was used."""
        self._fit()
        self.exec()
        return self._accepted

    def showEvent(self, ev):
        super().showEvent(ev)
        par = self.parentWidget()
        if par is not None:
            win = par.window()
            c = win.mapToGlobal(win.rect().center())
            self.move(c.x() - self.width() // 2, c.y() - self.height() // 2 - 40)


def confirm(parent, title, text, ok='Confirm', danger=False):
    return Sheet(parent, title, text, ok, danger).run()


def error(parent, message, title='Something went wrong'):
    return Sheet(parent, title, str(message), 'OK', cancel=None).run()


def notify(parent, title, text):
    return Sheet(parent, title, text, 'OK', cancel=None).run()


def choose(parent, title, text, primary, secondary, cancel='Cancel'):
    """Three-way decision. Returns 'primary', 'secondary' or None (cancelled)."""
    dlg = Sheet(parent, title, text, primary, False, 520, cancel, extra=secondary)
    if not dlg.run():
        return None
    return 'primary' if dlg.picked == 'ok' else 'secondary'


def prompt(parent, title, caption, value='', ok='Save', placeholder=''):
    """Ask for one line of text. Returns the stripped string, or None when cancelled or empty."""
    dlg = Sheet(parent, title, '', ok)
    dlg.body.addWidget(label(caption, 'muted'))
    edit = QLineEdit(value)
    edit.setPlaceholderText(placeholder)
    edit.returnPressed.connect(dlg.accept)
    dlg.body.addWidget(edit)
    QTimer.singleShot(0, lambda: (edit.setFocus(), edit.selectAll()))
    if dlg.run() and edit.text().strip():
        return edit.text().strip()
    return None


def pick_item(parent, title, caption, items, current=0, ok='Choose'):
    """Choose one of ``items`` (list of display strings). Returns the index or None."""
    dlg = Sheet(parent, title, '', ok)
    dlg.body.addWidget(label(caption, 'muted'))
    combo = QComboBox()
    combo.addItems(items)
    combo.setCurrentIndex(current)
    dlg.body.addWidget(combo)
    return combo.currentIndex() if dlg.run() else None


# ================================================================================ full-size panels
class Panel(QDialog):
    """Framed dialog with a header, a body (optionally scrolling), an inline error bar and a footer."""

    def __init__(self, parent, title, subtitle='', width=580, height=520, modal=True, scrolling=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(modal)
        if modal:
            self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(width, height)
        self.setMinimumSize(min(width, 460), min(height, 340))
        self._accepted = False
        self.accepted.connect(self._mark)
        outer = vbox(self, (0, 0, 0, 0), 0)
        head = QFrame()
        head.setObjectName('panelHead')
        hl = vbox(head, (28, 24, 28, 12), 4)
        hl.addWidget(label(title, 'h1'))
        self.subtitle = label(subtitle, 'muted', wrap=True)
        self.subtitle.setVisible(bool(subtitle))
        hl.addWidget(self.subtitle)
        outer.addWidget(head)
        inner = QWidget()
        self.body = vbox(inner, (28, 6, 28, 16), 14)
        if scrolling:
            self.scroll = QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QFrame.Shape.NoFrame)
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.scroll.setWidget(inner)
            outer.addWidget(self.scroll, 1)
        else:
            outer.addWidget(inner, 1)
        self.error_bar = QFrame()
        self.error_bar.setObjectName('errorBar')
        eb = hbox(self.error_bar, (12, 9, 12, 9), 8)
        eb.addWidget(icon_label('alert', 'bad', 16))
        self.error_text = label('', 'h3', wrap=True)
        eb.addWidget(self.error_text, 1)
        self.error_bar.hide()
        err_row = vbox(None, (28, 0, 28, 10), 0)
        err_row.addWidget(self.error_bar)
        outer.addLayout(err_row)
        foot = QFrame()
        foot.setObjectName('panelFoot')
        self.foot = hbox(foot, (24, 14, 24, 14), 10)
        outer.addWidget(foot)

    def _mark(self):
        self._accepted = True

    def set_error(self, message):
        self.error_text.setText(str(message))
        self.error_bar.setVisible(bool(message))

    def add_buttons(self, primary='Save', on_primary=None, cancel='Cancel', left=None):
        for w in (left or []):
            self.foot.addWidget(w)
        self.foot.addStretch(1)
        if cancel:
            self.foot.addWidget(size_button(button(cancel, 'ghost', None, self.reject)))
        if primary:
            self.primary_btn = size_button(button(primary, 'primary', None, on_primary or self.accept))
            self.primary_btn.setDefault(True)
            self.foot.addWidget(self.primary_btn)

    def run(self):
        self.exec()
        return self._accepted


# ================================================================================ entries
class EntryDialog(Panel):
    def __init__(self, parent, store, bid, row=None, book_name=''):
        super().__init__(parent, 'Edit entry' if row else 'New entry', book_name, 580, 660, scrolling=True)
        self.store, self.bid, self.row = store, bid, row
        self.fields = store.columns(bid)
        self.widgets = {}
        values = store.values(row) if row else {}
        for f in self.fields:
            typ, key, v = f['type'], f['key'], str(values.get(f['key'], '') or '')
            if typ == 'checkbox':
                w = QCheckBox('Yes')
                w.setChecked(is_true(v))
            elif typ == 'multiline':
                w = QTextEdit()
                w.setAcceptRichText(False)
                w.setTabChangesFocus(True)
                w.setMinimumHeight(110)
                w.setPlainText(v)
            elif typ == 'select':
                w = QComboBox()
                w.setEditable(True)
                w.addItems(f.get('options', []) if isinstance(f.get('options'), list) else [])
                w.setCurrentText(v)
            elif typ == 'date':
                w = QDateEdit()
                w.setCalendarPopup(True)
                w.setDisplayFormat('yyyy-MM-dd')
                w.setDate(QDate.fromString(v, 'yyyy-MM-dd') if v else QDate.currentDate())
            elif typ == 'revision':
                w = QLineEdit(v)
                w.setPlaceholderText('Document number, for example DWG-100')
            else:
                w = QLineEdit(v)
                w.setPlaceholderText({'number': 'Number', 'attachment': 'File name or path'}.get(typ, 'Optional'))
            self.widgets[key] = w
            if typ == 'revision' and getattr(parent, 'rwx', None):
                row = QWidget()
                rl = hbox(row, (0, 0, 0, 0), 8)
                rl.addWidget(w, 1)
                rl.addWidget(size_button(button('Choose…', '', None, lambda e=w: self.choose_document(e))))
                self.body.addWidget(field_block(f['label'], row))
            else:
                self.body.addWidget(field_block(f['label'], w))
        self.body.addStretch(1)
        self.add_buttons('Save entry', self.save)
        QShortcut(QKeySequence('Ctrl+Return'), self, activated=self.save)
        first = next(iter(self.widgets.values()), None)
        if first is not None:
            QTimer.singleShot(0, first.setFocus)

    def choose_document(self, edit):
        """Pick a RevisionWorx document for a RevisionWorx document field."""
        from . import revisionworx as rwxlink
        try:
            docs = self.parent().rwx_documents(fresh=True)
        except rwxlink.RwxError as e:
            self.set_error(e)
            return None
        if not docs:
            self.set_error('There are no documents in RevisionWorx yet.')
            return None
        current = next((i for i, d in enumerate(docs) if str(d.get('number', '')).casefold()
                        == edit.text().strip().casefold()), 0)
        picked = pick_item(self, 'RevisionWorx document', 'Choose the document this entry refers to.',
                           rwxlink.choices(docs), current, 'Use document')
        if picked is None:
            return None
        edit.setText(docs[picked].get('number', ''))
        return docs[picked]

    def collect(self):
        values = {}
        for f in self.fields:
            w = self.widgets[f['key']]
            if isinstance(w, QCheckBox):
                v = 'true' if w.isChecked() else 'false'
            elif isinstance(w, QDateEdit):
                v = w.date().toString('yyyy-MM-dd')
            elif isinstance(w, QTextEdit):
                v = w.toPlainText()
            elif isinstance(w, QComboBox):
                v = w.currentText()
            else:
                v = w.text()
            values[f['key']] = v
        return values

    def save(self):
        values = self.collect()
        for f in self.fields:
            if f['type'] == 'number' and values[f['key']].strip():
                try:
                    float(values[f['key']])
                except ValueError:
                    self.set_error('“%s” must be a number.' % f['label'])
                    return
        try:
            self.saved_id = self.store.save_entry(self.bid, values, self.row['id'] if self.row else None)
        except Exception as e:  # noqa: BLE001 - surface any validation message inline
            self.set_error(e)
            return
        self.accept()


class FullTextDialog(Panel):
    def __init__(self, parent, title, value):
        super().__init__(parent, title, 'Full value', 680, 440)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(value)
        self.body.addWidget(view, 1)
        copy = button('Copy', '', 'copy', lambda: QGuiApplication.clipboard().setText(value))
        self.add_buttons(None, None, None, left=[copy])
        self.foot.addWidget(size_button(button('Close', 'primary', None, self.accept)))


# ================================================================================ columns
class ColumnsDialog(Panel):
    def __init__(self, parent, store, bid, book_name=''):
        super().__init__(parent, 'Manage columns', 'Customize the fields in “%s”. Changes apply to every entry.'
                         % book_name if book_name else 'Customize the fields in this logbook.', 760, 560)
        self.store, self.bid = store, bid
        self.fields = [dict(f) for f in store.columns(bid)]
        self._loading = False
        row = hbox(None, (0, 0, 0, 0), 18)
        left = vbox(None, (0, 0, 0, 0), 8)
        self.list = QListWidget()
        self.list.setMinimumWidth(250)
        left.addWidget(self.list, 1)
        tools = hbox(None, (0, 0, 0, 0), 4)
        tools.addWidget(button('Add field', '', 'plus', self.add))
        tools.addStretch(1)
        self.up_btn = self._tool('arrow_up', 'Move up', lambda: self.move(-1))
        self.down_btn = self._tool('arrow_down', 'Move down', lambda: self.move(1))
        self.remove_btn = self._tool('trash', 'Remove field', self.remove)
        for b in (self.up_btn, self.down_btn, self.remove_btn):
            tools.addWidget(b)
        left.addLayout(tools)
        row.addLayout(left, 5)
        right = vbox(None, (0, 0, 0, 0), 12)
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._name_changed)
        right.addWidget(field_block('Label', self.name_edit))
        self.type_combo = QComboBox()
        self.types = sorted(TYPES, key=lambda k: TYPE_NAMES.get(k, k))
        for k in self.types:
            self.type_combo.addItem(TYPE_NAMES.get(k, k.title()), k)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        right.addWidget(field_block('Type', self.type_combo))
        self.options_edit = QLineEdit()
        self.options_edit.setPlaceholderText('Option one, Option two, …')
        self.options_edit.textChanged.connect(self._options_changed)
        self.options_block = field_block('Dropdown options', self.options_edit, 'Separate choices with commas.')
        right.addWidget(self.options_block)
        self.visible_box = QCheckBox('Show this column in the logbook table')
        self.visible_box.toggled.connect(self._visible_changed)
        right.addWidget(self.visible_box)
        self.key_label = label('', 'faint')
        right.addWidget(self.key_label)
        right.addStretch(1)
        row.addLayout(right, 6)
        self.body.addLayout(row, 1)
        self.list.currentRowChanged.connect(self._select)
        self.add_buttons('Save columns', self.save)
        self.refresh(0)

    def _tool(self, icon, tip, cb):
        from .widgets import icon_button
        return icon_button(icon, tip, cb, 34, 16)

    # -- list ----------------------------------------------------------------------------------
    def refresh(self, sel=None):
        self._loading = True
        self.list.clear()
        t = T()
        for f in self.fields:
            visible = f.get('visible', True)
            it = QListWidgetItem('  %s    ·  %s' % (f['label'], TYPE_NAMES.get(f['type'], f['type'])))
            it.setIcon(icons.icon('eye' if visible else 'eye_off', t['accent'] if visible else t['faint'], 16))
            self.list.addItem(it)
        self._loading = False
        if sel is not None and 0 <= sel < len(self.fields):
            self.list.setCurrentRow(sel)
        self._select(self.list.currentRow())

    def current(self):
        i = self.list.currentRow()
        return self.fields[i] if 0 <= i < len(self.fields) else None

    def _select(self, index):
        if self._loading:
            return
        f = self.current()
        enabled = f is not None
        for w in (self.name_edit, self.type_combo, self.options_edit, self.visible_box, self.up_btn, self.down_btn,
                  self.remove_btn):
            w.setEnabled(enabled)
        self._loading = True
        if f:
            self.name_edit.setText(f['label'])
            self.type_combo.setCurrentIndex(max(0, self.types.index(f['type']) if f['type'] in self.types else 0))
            self.options_edit.setText(', '.join(f.get('options', [])) if isinstance(f.get('options'), list) else '')
            self.visible_box.setChecked(bool(f.get('visible', True)))
            self.key_label.setText('Internal key: %s' % f['key'])
        else:
            self.name_edit.clear()
            self.options_edit.clear()
            self.key_label.clear()
        self.options_block.setVisible(bool(f) and f['type'] == 'select')
        self._loading = False

    # -- edits ----------------------------------------------------------------------------------
    def _touch(self, keep_selection=True):
        i = self.list.currentRow()
        self.refresh(i if keep_selection else None)

    def _name_changed(self, text):
        f = self.current()
        if self._loading or not f:
            return
        f['label'] = text
        item = self.list.currentItem()
        if item is not None:
            item.setText('  %s    ·  %s' % (text or '(unnamed)', TYPE_NAMES.get(f['type'], f['type'])))

    def _type_changed(self, _index):
        f = self.current()
        if self._loading or not f:
            return
        f['type'] = self.type_combo.currentData()
        self.options_block.setVisible(f['type'] == 'select')
        self._touch()

    def _options_changed(self, text):
        f = self.current()
        if self._loading or not f:
            return
        f['options'] = [v.strip() for v in text.split(',') if v.strip()]

    def _visible_changed(self, checked):
        f = self.current()
        if self._loading or not f:
            return
        f['visible'] = bool(checked)
        self._touch()

    def add(self):
        f = {'key': 'field_' + os.urandom(5).hex(), 'label': 'New field', 'type': 'text', 'visible': True}
        self.fields.append(f)
        self.refresh(len(self.fields) - 1)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def remove(self):
        i = self.list.currentRow()
        if i < 0:
            return
        if confirm(self, 'Remove column?', 'Remove “%s”? Values already stored in this column become hidden from the '
                   'logbook (the data itself is kept in the database).' % self.fields[i]['label'], 'Remove', True):
            self.fields.pop(i)
            self.refresh(min(i, len(self.fields) - 1))

    def move(self, d):
        i = self.list.currentRow()
        j = i + d
        if 0 <= i < len(self.fields) and 0 <= j < len(self.fields):
            self.fields[i], self.fields[j] = self.fields[j], self.fields[i]
            self.refresh(j)

    def save(self):
        try:
            self.store.set_columns(self.bid, self.fields)
        except Exception as e:  # noqa: BLE001
            self.set_error(e)
            return
        self.accept()


# ================================================================================ create / edit logbook
class LogbookDialog(Panel):
    """Create a logbook or edit its name, description, symbol, colour and folder."""

    def __init__(self, parent, store, book=None):
        super().__init__(parent, 'Logbook settings' if book else 'New logbook',
                         'Choose a name, symbol and colour so it is easy to spot in the sidebar.', 600, 700,
                         scrolling=True)
        self.store, self.book = store, book
        self.icon = (book['icon'] if book else '') or DEFAULT_ICON
        self.accent = (book['accent'] if book else '') or ''
        self.original_accent = self.accent
        self.result_data = None
        # identity row: live preview + name
        top = hbox(None, (0, 0, 0, 0), 14)
        self.preview = IconTile(54, self.icon, '', theme.book_color(book['id'] if book else 0, self.accent))
        top.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignBottom)
        self.name_edit = QLineEdit(book['name'] if book else '')
        self.name_edit.setPlaceholderText('e.g. Vehicle maintenance')
        top.addWidget(field_block('Name', self.name_edit), 1)
        self.body.addLayout(top)
        self.desc_edit = QTextEdit(book['description'] if book else '')
        self.desc_edit.setAcceptRichText(False)
        self.desc_edit.setTabChangesFocus(True)
        self.desc_edit.setFixedHeight(84)
        self.desc_edit.setPlaceholderText('What is this logbook for? (optional)')
        self.body.addWidget(field_block('Description', self.desc_edit))
        # symbol grid
        grid_box = QWidget()
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        glyphs = list(LOGBOOK_ICONS)
        if self.icon not in [g for g, _ in glyphs]:
            glyphs.insert(0, (self.icon, 'Existing custom symbol'))
        for n, (glyph, name) in enumerate(glyphs):
            b = QToolButton()
            b.setObjectName('glyph')
            b.setText(glyph)
            b.setToolTip(name)
            b.setCheckable(True)
            b.setFixedSize(46, 42)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(glyph == self.icon)
            b.clicked.connect(lambda checked=False, g=glyph: self.pick_icon(g))
            self.group.addButton(b)
            grid.addWidget(b, n // 9, n % 9)
        self.body.addWidget(field_block('Symbol', grid_box))
        # colour
        colors = QWidget()
        cl = hbox(colors, (0, 0, 0, 0), 8)
        self.swatches = []
        auto = button('Auto', '', None, lambda: self.pick_color(''))
        auto.setObjectName('chip')
        cl.addWidget(auto)
        for hexv in theme.BOOK_COLORS:
            b = QToolButton()
            b.setObjectName('swatch')
            b.setStyleSheet('QToolButton#swatch { background: %s; }' % hexv)
            b.setCheckable(True)
            b.setFixedSize(28, 28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(hexv)
            b.setChecked(hexv.lower() == self.accent.lower())
            b.clicked.connect(lambda checked=False, c=hexv: self.pick_color(c))
            self.swatches.append((hexv, b))
            cl.addWidget(b)
        self.hex_edit = QLineEdit(self.accent)
        self.hex_edit.setPlaceholderText('#4f8cff')
        self.hex_edit.setFixedWidth(110)
        self.hex_edit.textChanged.connect(self._hex_typed)
        cl.addStretch(1)
        cl.addWidget(self.hex_edit)
        self.body.addWidget(field_block('Colour', colors, 'Auto picks a colour for you. Use a hex value for any other.'))
        # folder
        self.folder_combo = QComboBox()
        self.folder_combo.addItem('Unfiled', None)
        for f in store.folders():
            self.folder_combo.addItem(f['name'], f['id'])
        if book is not None:
            self.folder_combo.setCurrentIndex(max(0, self.folder_combo.findData(book['folder_id'])))
        self.body.addWidget(field_block('Folder', self.folder_combo))
        self.body.addStretch(1)
        self.add_buttons('Save changes' if book else 'Create logbook', self.save)
        QTimer.singleShot(0, self.name_edit.setFocus)

    def _refresh_preview(self):
        self.preview.configure(self.icon, '', theme.book_color(self.book['id'] if self.book else 0, self.accent))

    def pick_icon(self, glyph):
        self.icon = glyph
        self._refresh_preview()

    def pick_color(self, hexv):
        self.accent = hexv
        self.hex_edit.blockSignals(True)
        self.hex_edit.setText(hexv)
        self.hex_edit.blockSignals(False)
        self._sync_swatches()
        self._refresh_preview()

    def _sync_swatches(self):
        for hexv, b in self.swatches:
            b.setChecked(hexv.lower() == self.accent.lower())

    def _hex_typed(self, text):
        text = text.strip()
        ok = not text or theme.valid_hex(text)
        self.hex_edit.setProperty('invalid', not ok)
        self.hex_edit.style().unpolish(self.hex_edit)
        self.hex_edit.style().polish(self.hex_edit)
        if ok:
            self.accent = text
            self._sync_swatches()
            self._refresh_preview()

    def save(self):
        name = self.name_edit.text().strip()
        if not name:
            self.set_error('Enter a name for the logbook.')
            return
        text = self.hex_edit.text().strip()
        if text and not theme.valid_hex(text) and text != self.original_accent:
            self.set_error('Use a colour like #4f8cff, or choose Auto.')
            return
        self.result_data = dict(name=name, description=self.desc_edit.toPlainText(), icon=self.icon or DEFAULT_ICON,
                                accent=text, folder_id=self.folder_combo.currentData())
        self.accept()


# ================================================================================ recovery dialogs
class _TableDialog(Panel):
    def __init__(self, parent, title, subtitle, headers, width=720, height=520):
        super().__init__(parent, title, subtitle, width, height)
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setFixedHeight(38)
        self.empty = label('', 'muted', wrap=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.table, 1)
        self.body.addWidget(self.empty)

    def set_rows(self, rows, empty_text):
        """rows: list of (payload, [cell texts]). Payload is stored on the first cell."""
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for i, (payload, cells) in enumerate(rows):
            for j, text in enumerate(cells):
                item = QTableWidgetItem(str(text))
                if j == 0:
                    item.setData(Qt.ItemDataRole.UserRole, payload)
                self.table.setItem(i, j, item)
        self.table.setVisible(bool(rows))
        self.empty.setText(empty_text)
        self.empty.setVisible(not rows)

    def selected_payloads(self):
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in rows]


class RecycleDialog(_TableDialog):
    def __init__(self, parent, store, on_change):
        super().__init__(parent, 'Recycle Bin', 'Deleted entries and logbooks stay here until you empty the bin.',
                         ['ITEM', 'TYPE', 'FROM', 'DELETED'], 760, 540)
        self.store, self.on_change = store, on_change
        self.table.setColumnWidth(0, 280)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 170)
        self.status = label('', 'faint')
        self.body.addWidget(self.status)
        self.restore_btn = size_button(button('Restore selected', 'primary', 'reset', self.restore))
        self.empty_btn = button('Empty Recycle Bin', 'danger', 'trash', self.empty)
        self.foot.addWidget(self.empty_btn)
        self.foot.addStretch(1)
        self.foot.addWidget(size_button(button('Close', 'ghost', None, self.accept)))
        self.foot.addWidget(self.restore_btn)
        self.reload()

    def reload(self):
        rows = []
        for r in self.store.deleted_items():
            data = json.loads(r['payload'])
            title = str(data.get('title') or data.get('notes') or 'Untitled').replace('\n', ' ')[:80]
            src = self.store.db.execute('SELECT name FROM books WHERE id=?', (r['book_id'],)).fetchone()
            rows.append((('entry', r['id']), [title, 'Entry', src['name'] if src else '(deleted logbook)',
                                              fmt_timestamp(r['deleted_at'])]))
        for r in self.store.db.execute('SELECT * FROM deleted_books ORDER BY deleted_at DESC'):
            data = json.loads(r['payload'])
            count = len(data.get('entries', []))
            rows.append((('book', r['id']), [data['book']['name'], 'Logbook', plural(count, 'entry', 'entries'),
                                             fmt_timestamp(r['deleted_at'])]))
        self.set_rows(rows, 'The Recycle Bin is empty.')
        self.restore_btn.setEnabled(bool(rows))
        self.empty_btn.setEnabled(bool(rows))

    def restore(self):
        chosen = self.selected_payloads()
        if not chosen:
            self.set_error('Select one or more items to restore.')
            return
        self.set_error('')
        problems = []
        done = 0
        for kind, ident in chosen:
            try:
                if kind == 'entry':
                    self.store.restore_deleted_entry(ident)
                else:
                    self.store.restore_deleted_book(ident)
                done += 1
            except Exception as e:  # noqa: BLE001
                problems.append(str(e))
        self.reload()
        self.on_change(done)
        if problems:
            self.set_error('; '.join(sorted(set(problems))))

    def empty(self):
        if confirm(self, 'Empty Recycle Bin?', 'Permanently delete ALL recycled entries and logbooks? '
                   'This cannot be undone.', 'Delete permanently', True):
            self.store.empty_all_recycle()
            self.reload()
            self.on_change(0)


class ArchiveDialog(_TableDialog):
    def __init__(self, parent, store, on_change):
        super().__init__(parent, 'Archived logbooks', 'Archived logbooks are hidden from the sidebar but keep all data.',
                         ['LOGBOOK', 'ENTRIES', 'FOLDER'], 640, 480)
        self.store, self.on_change = store, on_change
        self.table.setColumnWidth(0, 300)
        self.table.setColumnWidth(1, 100)
        self.restore_btn = size_button(button('Restore selected', 'primary', 'reset', self.restore))
        self.foot.addStretch(1)
        self.foot.addWidget(size_button(button('Close', 'ghost', None, self.accept)))
        self.foot.addWidget(self.restore_btn)
        self.reload()

    def reload(self):
        folders = {f['id']: f['name'] for f in self.store.folders()}
        rows = []
        for b in self.store.books(True):
            if b['archived']:
                rows.append((b['id'], ['%s  %s' % (b['icon'] or DEFAULT_ICON, b['name']), b['entry_count'],
                                       folders.get(b['folder_id'], 'Unfiled')]))
        self.set_rows(rows, 'No archived logbooks.')
        self.restore_btn.setEnabled(bool(rows))

    def restore(self):
        chosen = self.selected_payloads()
        if not chosen:
            self.set_error('Select one or more logbooks to restore.')
            return
        for ident in chosen:
            self.store.configure_book(ident, archived=0)
        self.reload()
        self.on_change(len(chosen))


# ================================================================================ PDF report options
class PdfDialog(Panel):
    def __init__(self, parent, fields, row_count, selected_count=0):
        super().__init__(parent, 'PDF report', 'Choose what goes into the report. Rows follow the table’s current '
                         'search and sort order.', 600, 600, scrolling=True)
        self.row_count = row_count
        self.result_data = None
        self.checks = []
        grid_box = QWidget()
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        for n, f in enumerate(fields):
            cb = QCheckBox(f['label'])
            cb.setChecked(f.get('visible', True))
            self.checks.append((f, cb))
            grid.addWidget(cb, n // 2, n % 2)
        links = hbox(None, (0, 0, 0, 0), 4)
        all_btn = button('Select all', 'linkBtn', None, lambda: self._set_all(True))
        none_btn = button('Select none', 'linkBtn', None, lambda: self._set_all(False))
        links.addWidget(all_btn)
        links.addWidget(none_btn)
        links.addStretch(1)
        block = QWidget()
        bl = vbox(block, (0, 0, 0, 0), 8)
        bl.addLayout(links)
        bl.addWidget(grid_box)
        self.body.addWidget(field_block('Columns', block))
        self.range_edit = QLineEdit()
        self.range_edit.setPlaceholderText('All %d rows' % row_count if row_count else 'No rows')
        hint = 'Rows are numbered by the # column, for example 56-72 or just 8. Leave blank for everything.'
        if selected_count:
            hint += ' (%s currently selected.)' % plural(selected_count, 'row')
        self.body.addWidget(field_block('Row range', self.range_edit, hint))
        self.landscape = QCheckBox('Landscape page (better for many columns)')
        self.body.addWidget(self.landscape)
        self.body.addStretch(1)
        self.add_buttons('Choose location…', self.proceed)

    def _set_all(self, state):
        for _f, cb in self.checks:
            cb.setChecked(state)

    def proceed(self):
        import re
        fields = [f for f, cb in self.checks if cb.isChecked()]
        if not fields:
            self.set_error('Select at least one column.')
            return
        rng = None
        text = self.range_edit.text().strip()
        if text:
            match = re.fullmatch(r'(\d+)\s*(?:-\s*(\d+))?', text)
            if not match:
                self.set_error('Enter a row or a range such as 56-72.')
                return
            a = int(match[1])
            b = int(match[2] or a)
            if a < 1 or b < a or b > self.row_count:
                self.set_error('The range must fall within rows 1–%d.' % self.row_count)
                return
            rng = (a, b)
        self.result_data = dict(fields=fields, rng=rng, landscape=self.landscape.isChecked())
        self.accept()


# ================================================================================ release notes
class WhatsNewDialog(Panel):
    def __init__(self, parent, version):
        super().__init__(parent, 'What’s new in %s' % version, 'The first stable release. Your data and files are unchanged.',
                         600, 560, scrolling=True)
        items = [
            ('sparkle', 'A completely new look', 'Four refined themes, the Inter typeface, and a calm, spacious layout.'),
            ('command', 'Command palette', 'Press Ctrl+K to jump to any logbook or action instantly.'),
            ('home', 'A home screen that helps', 'Pick up where you left off, with totals and your recent logbooks.'),
            ('undo', 'Undo, right where you are', 'Deleting entries shows an Undo button instead of a confirmation maze.'),
            ('columns', 'Friendlier column editor', 'Rename, retype and reorder fields in one place, with a live preview.'),
            ('file', 'Better PDF reports', 'Shaded headers, banded rows, page numbers, landscape and smarter column widths.'),
        ]
        for icon_name, title, text in items:
            row = hbox(None, (0, 0, 0, 0), 14)
            tile = IconTile(40, '', icon_name)
            row.addWidget(tile, 0, Qt.AlignmentFlag.AlignTop)
            col = vbox(None, (0, 0, 0, 0), 2)
            col.addWidget(label(title, 'h3'))
            col.addWidget(label(text, 'muted', wrap=True))
            row.addLayout(col, 1)
            self.body.addLayout(row)
        self.body.addStretch(1)
        self.skip = QCheckBox('Do not show this again')
        self.add_buttons('Continue', None, None, left=[self.skip])
