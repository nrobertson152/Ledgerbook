"""Qt-native PDF report: shaded header band, banded rows, page numbers, optional landscape.

Rows that are taller than the space left on a page continue on the next page; separators are always drawn
below the lowest rendered line."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPageLayout, QPageSize, QPainter, QPdfWriter

from .util import is_true

INK, MUTED, RULE, BAND, ZEBRA, ACCENT = '#1f2937', '#64748b', '#dfe3ea', '#eef1f6', '#f7f8fa', '#2f6be0'
FAMILIES = ['Inter', 'DejaVu Sans', 'Sans Serif']


def column_weight(field):
    """Relative width of a column: long-text fields get more room than dates or numbers."""
    typ, key, name = field.get('type'), field.get('key', ''), str(field.get('label', '')).lower()
    if typ == 'multiline' or key == 'notes' or 'note' in name or 'description' in name:
        return 2.2
    return {'date': 0.9, 'due': 1.0, 'number': 0.8, 'checkbox': 0.6, 'select': 1.0}.get(typ, 1.4 if key == 'title' else 1.2)


def wrap_text(text, metrics, max_width):
    """Split ``text`` into lines no wider than ``max_width`` (honouring explicit line breaks and long words)."""
    out = []
    for para in str(text).replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if not para:
            out.append('')
            continue
        buf = ''
        for word in para.split(' '):
            candidate = (buf + ' ' + word).strip()
            if metrics.horizontalAdvance(candidate) <= max_width:
                buf = candidate
                continue
            if buf:
                out.append(buf)
                buf = ''
            while metrics.horizontalAdvance(word) > max_width and len(word) > 1:
                k = max(1, len(word) // 2)
                while k > 1 and metrics.horizontalAdvance(word[:k]) > max_width:
                    k -= 1
                out.append(word[:k])
                word = word[k:]
            buf = word
        out.append(buf)
    return out or ['']


def _font(size, bold=False):
    f = QFont()
    f.setFamilies(FAMILIES)
    f.setPointSizeF(size)
    f.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    return f


def pdf_report(path, title, fields, rows, subtitle='', landscape=False, summary=''):
    """Write a PDF to ``path``. ``rows`` are value dictionaries in display order. ``summary`` (for example the
    number-column totals) is printed under the table. Returns the page count."""
    if not fields:
        raise ValueError('Select at least one column')
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    if landscape:
        writer.setPageOrientation(QPageLayout.Orientation.Landscape)
    writer.setResolution(120)
    writer.setTitle(title)
    writer.setCreator('Ledgerbook')
    painter = QPainter(writer)
    state = {'page': 1, 'y': 0}
    try:
        width, height = writer.width(), writer.height()
        margin, pad = 60, 8
        usable = width - 2 * margin
        weights = [column_weight(f) for f in fields]
        widths = [usable * w / sum(weights) for w in weights]
        xs = [margin]
        for w in widths:
            xs.append(xs[-1] + w)
        body, small, head, big = _font(9), _font(8), _font(8, True), _font(19, True)
        body_m, head_m = QFontMetrics(body), QFontMetrics(head)
        line = body_m.height() + 4
        band_h = head_m.height() + 16
        bottom = height - margin - 26

        def footer():
            painter.setFont(small)
            painter.setPen(QColor(MUTED))
            painter.drawText(QRectF(margin, height - margin - 6, usable, 22),
                             int(0x0001 | 0x0080), 'Ledgerbook  ·  %s' % title)
            painter.drawText(QRectF(margin, height - margin - 6, usable, 22),
                             int(0x0002 | 0x0080), 'Page %d' % state['page'])

        def header():
            y = margin
            if state['page'] == 1:
                painter.fillRect(QRectF(margin, y, 46, 4), QColor(ACCENT))
                y += 18
                painter.setFont(big)
                painter.setPen(QColor(INK))
                fm = QFontMetrics(big)
                painter.drawText(margin, y + fm.ascent(), title)
                y += fm.height() + 4
                if subtitle:
                    painter.setFont(body)
                    painter.setPen(QColor(MUTED))
                    painter.drawText(margin, y + body_m.ascent(), subtitle)
                    y += body_m.height()
                y += 16
            else:
                painter.setFont(small)
                painter.setPen(QColor(MUTED))
                painter.drawText(margin, y + QFontMetrics(small).ascent(), title)
                y += QFontMetrics(small).height() + 12
            painter.fillRect(QRectF(margin, y, usable, band_h), QColor(BAND))
            painter.setFont(head)
            painter.setPen(QColor(MUTED))
            for j, f in enumerate(fields):
                label = head_m.elidedText(str(f['label']).upper(), Qt.TextElideMode.ElideRight, int(widths[j] - 2 * pad))
                painter.drawText(int(xs[j] + pad), int(y + (band_h + head_m.ascent() - head_m.descent()) / 2), label)
            state['y'] = y + band_h
            footer()

        def new_page():
            writer.newPage()
            state['page'] += 1
            header()

        header()
        painter.setFont(body)
        for index, values in enumerate(rows):
            cells = []
            for j, f in enumerate(fields):
                raw = values.get(f['key'], '')
                text = ('Yes' if is_true(raw) else 'No') if f['type'] == 'checkbox' else str(raw if raw is not None else '')
                cells.append(wrap_text(text, body_m, widths[j] - 2 * pad))
            total = max(len(c) for c in cells)
            offset = 0
            while offset < total:
                fit = int((bottom - state['y'] - 2 * pad) // line)
                if fit < 1:
                    new_page()
                    painter.setFont(body)
                    continue
                take = min(fit, total - offset)
                row_h = take * line + 2 * pad
                y = state['y']
                if index % 2 == 1:
                    painter.fillRect(QRectF(margin, y, usable, row_h), QColor(ZEBRA))
                painter.setFont(body)
                painter.setPen(QColor(INK))
                for j, lines in enumerate(cells):
                    for k in range(take):
                        if offset + k < len(lines):
                            painter.drawText(int(xs[j] + pad), int(y + pad + k * line + body_m.ascent() + 2),
                                             lines[offset + k])
                painter.setPen(QColor(RULE))
                painter.drawLine(margin, int(y + row_h), width - margin, int(y + row_h))
                state['y'] = y + row_h
                offset += take
                if offset < total:
                    new_page()
                    painter.setFont(body)
        if not rows:
            painter.setFont(body)
            painter.setPen(QColor(MUTED))
            painter.drawText(int(margin + pad), int(state['y'] + 30), 'No entries in the selected range.')
        elif summary:
            head_lines = wrap_text(summary, head_m, usable - 2 * pad)
            if state['y'] + 18 + len(head_lines) * line > bottom:
                new_page()
            painter.setFont(head)
            painter.setPen(QColor(INK))
            for k, text in enumerate(head_lines):
                painter.drawText(int(margin + pad), int(state['y'] + 18 + k * line + head_m.ascent()), text)
    finally:
        painter.end()
    return state['page']
