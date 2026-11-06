"""Numbers, totals and due dates (Qt-free, so everything here is unit-tested without a display)."""
import re
from datetime import date, datetime

CURRENCY = '$€£¥'
_GROUPED = re.compile(r'^\d{1,3}(,\d{3})+(\.\d*)?$')        # 1,234 or 12,345,678.90
_PLAIN = re.compile(r'^(\d+\.?\d*|\.\d+)$')
SOON_DAYS = 14                                               # "due soon" when this many days or fewer remain
HORIZON_DAYS = 30                                            # the Home screen lists what is due within this window


def normalize_number(text):
    """The canonical text of a number as people type it: ``$1,234.50`` -> ``1234.50``, ``(12.50)`` -> ``-12.50``,
    ``€ 45`` -> ``45``. The digits are kept as typed (no rounding). Raises ValueError for anything else, including
    a decimal comma such as ``12,5`` (ambiguous with a thousands separator)."""
    s = str(text).strip().replace(' ', '').replace(' ', '')
    if not s:
        return ''
    negative = False
    if len(s) > 2 and s.startswith('(') and s.endswith(')'):
        negative, s = True, s[1:-1]
    if s.startswith(('+', '-')):
        negative, s = negative ^ s.startswith('-'), s[1:]
    if s.startswith(tuple(CURRENCY)):
        s = s[1:]
        if s.startswith(('+', '-')) and not negative:         # $-5 is seen as well as -$5
            negative, s = s.startswith('-'), s[1:]
    elif s.endswith(tuple(CURRENCY)):
        s = s[:-1]
    if not s:
        raise ValueError('“%s” is not a number' % text)
    if _GROUPED.match(s):
        s = s.replace(',', '')
    if not _PLAIN.match(s):
        try:                                                  # still accept what float() always did (1e5, 2.5E-3)
            value = float(s)
        except ValueError:
            raise ValueError('“%s” is not a number' % text) from None
        if value != value or value in (float('inf'), float('-inf')) or ',' in s or s.startswith(('+', '-')):
            raise ValueError('“%s” is not a number' % text)
    return ('-' if negative and float(s) != 0 else '') + s


def parse_number(text):
    """``normalize_number`` as a float (None for an empty value)."""
    n = normalize_number(text)
    return float(n) if n else None


def fmt_number(value):
    """A total for display: thousands separators, at most two decimals, no trailing zeros."""
    text = '{:,.2f}'.format(value)
    return text[:-3] if text.endswith('.00') else text


def shows_total(field):
    """Whether a number column is totalled under the table. A sum is meaningless for readings such as an
    odometer, so the old fixed "reading" (Measurement / Odometer) column is off unless switched on; every other
    number column is on unless switched off (Columns → Show a total)."""
    if field.get('type') != 'number':
        return False
    return bool(field.get('total', field.get('key') != 'reading'))


def column_totals(fields, rows):
    """For each totalled number field with at least one value among ``rows`` (value dicts): count, sum, average,
    min, max."""
    out = []
    for f in fields:
        if not shows_total(f):
            continue
        nums = []
        for values in rows:
            try:
                n = parse_number(values.get(f['key'], ''))
            except ValueError:
                n = None
            if n is not None:
                nums.append(n)
        if nums:
            out.append({'key': f['key'], 'label': f['label'], 'count': len(nums), 'sum': sum(nums),
                        'avg': sum(nums) / len(nums), 'min': min(nums), 'max': max(nums)})
    return out


def totals_text(fields, rows):
    """One line for the footer under the table, e.g. ``Cost: total 1,234.50 · average 102.88``."""
    parts = []
    for t in column_totals(fields, rows):
        part = '%s: total %s' % (t['label'], fmt_number(t['sum']))
        if t['count'] > 1:
            part += ' · average %s' % fmt_number(t['avg'])
        parts.append(part)
    return '     '.join(parts)


# ------------------------------------------------------------------------------------------------ due dates
def add_months(day, months):
    """``day`` moved by whole months, clamped to the month's end (31 Jan + 1 month = 28/29 Feb)."""
    import calendar
    total = day.month - 1 + months
    year, month = day.year + total // 12, total % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def parse_day(value):
    try:
        return datetime.strptime(str(value).strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def days_until(value, today=None):
    d = parse_day(value)
    return None if d is None else (d - (today or date.today())).days


def due_text(days):
    if days is None:
        return ''
    if days < 0:
        return 'overdue %d day%s' % (-days, '' if days == -1 else 's')
    if days == 0:
        return 'due today'
    if days == 1:
        return 'due tomorrow'
    return 'in %d days' % days


def due_cell(value, today=None):
    """(text, tone) for a Due date cell: tone 'bad' when overdue, 'warn' when due soon, '' otherwise."""
    value = str(value or '').strip()
    days = days_until(value, today)
    if days is None:
        return value, ''
    tone = 'bad' if days < 0 else ('warn' if days <= SOON_DAYS else '')
    return '%s · %s' % (value, due_text(days)), tone


def item_name(fields, values):
    """What an entry is about, used to group repeated tasks: the Entry/title column, else the first text column."""
    if str(values.get('title', '') or '').strip():
        return str(values['title']).strip()
    for f in fields:
        if f.get('type') in ('text', 'select') and str(values.get(f['key'], '') or '').strip():
            return str(values[f['key']]).strip()
    return ''


def upcoming(store, today=None, horizon=HORIZON_DAYS):
    """What is overdue or due within ``horizon`` days, across all active logbooks.

    Logbooks repeat tasks ("Oil change" every few months), and each new entry carries the next due date. Only the
    newest entry for each item name counts, so a due date that a later entry has superseded is not reported."""
    today = today or date.today()
    out = []
    for book in store.books():
        fields = store.columns(book['id'])
        due_fields = [f for f in fields if f.get('type') == 'due']
        if not due_fields:
            continue
        newest = {}                                          # (field key, item name) -> (entry date, id, values)
        for row in store.entries(book['id']):
            values = store.values(row)
            name = item_name(fields, values).casefold()
            for f in due_fields:
                if not str(values.get(f['key'], '') or '').strip():
                    continue
                key = (f['key'], name)
                rank = (str(row['entry_date'] or ''), row['id'])
                if key not in newest or rank > newest[key][0]:
                    newest[key] = (rank, row['id'], values, f)
        for (_k, _name), (_rank, entry_id, values, f) in newest.items():
            days = days_until(values.get(f['key']), today)
            if days is not None and days <= horizon:
                out.append({'book_id': book['id'], 'book': book['name'], 'entry_id': entry_id,
                            'item': item_name(fields, values) or 'Entry', 'field': f['label'], 'key': f['key'],
                            'due': str(values.get(f['key'])).strip(), 'days': days})
    out.sort(key=lambda d: (d['days'], d['book'].casefold(), d['item'].casefold()))
    return out


# ======================================================================================== due dates in a calendar

def due_dates(store, today=None):
    """Every logbook's current due dates, overdue or not, as ``upcoming`` lists them."""
    return upcoming(store, today, horizon=10 ** 6)


def _ics_text(value):
    """A value as iCalendar text (RFC 5545 3.3.11): backslash, semicolon, comma and line breaks escaped."""
    return (str(value).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
            .replace('\r\n', '\\n').replace('\n', '\\n').replace('\r', '\\n'))


def _ics_line(line):
    """One content line, folded so no line is longer than 75 octets (RFC 5545 3.1), never inside a character."""
    out, chunk, size = [], '', 0
    for ch in line:
        n = len(ch.encode('utf-8'))
        if size + n > (75 if not out else 74):
            out.append(chunk)
            chunk, size = '', 0
        chunk += ch
        size += n
    out.append(chunk)
    return '\r\n '.join(out)


def calendar(items, stamp=None):
    """Due dates (as ``upcoming`` lists them) as an iCalendar file, for Google Calendar, Outlook, Thunderbird or Apple's Calendar:
    one all-day event on each due date, with a reminder the day before. Each has the same UID every time it's exported, so importing
    a newer export updates the events instead of adding them again. ``stamp`` is when it was made (UTC), for DTSTAMP."""
    from datetime import timedelta, timezone
    stamp = stamp or datetime.now(timezone.utc)
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Ledgerbook//Due dates//EN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
             'X-WR-CALNAME:Ledgerbook due dates']
    for it in items:
        day = parse_day(it.get('due'))
        if day is None:
            continue
        summary = '%s due · %s' % (it.get('item') or 'Entry', it.get('book') or 'Ledgerbook')
        lines += ['BEGIN:VEVENT',
                  'UID:ledgerbook-%s-%s-%s@ledgerbook' % (it.get('book_id'), it.get('entry_id'), it.get('key') or 'due'),
                  'DTSTAMP:%s' % stamp.strftime('%Y%m%dT%H%M%SZ'),
                  'DTSTART;VALUE=DATE:%s' % day.strftime('%Y%m%d'),
                  'DTEND;VALUE=DATE:%s' % (day + timedelta(days=1)).strftime('%Y%m%d'),
                  'SUMMARY:%s' % _ics_text(summary),
                  'DESCRIPTION:%s' % _ics_text('%s in the %s logbook, from Ledgerbook.' % (it.get('field') or 'Due date', it.get('book') or '')),
                  'TRANSP:TRANSPARENT',
                  'BEGIN:VALARM', 'ACTION:DISPLAY', 'TRIGGER:-P1D', 'DESCRIPTION:%s' % _ics_text(summary), 'END:VALARM',
                  'END:VEVENT']
    lines.append('END:VCALENDAR')
    return ''.join(_ics_line(x) + '\r\n' for x in lines).encode('utf-8')
