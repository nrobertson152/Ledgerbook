"""RevisionWorx integration (optional, Qt-free).

A logbook column of type ``revision`` ("RevisionWorx document") holds a document number such as ``DWG-100``. The
value stays plain text, so search, sorting, CSV, PDF and .ledgerbook files work as for any text column. When
RevisionWorx is installed the table shows the document's live revision and state next to the number, and an entry
can show the document in RevisionWorx. Ledgerbook reaches RevisionWorx only through ``revisionworx link``
(ledgerbook/rwx_client.py, a copy of RevisionWorx's contrib/rwx_client.py)."""
from .rwx_client import RevisionWorx, RwxError  # noqa: F401  (re-exported)

TONE_FOR_STATE = {'released': 'good', 'approved': 'good', 'in_review': 'warn', 'obsolete': 'faint'}


def probe():
    """A ready client, or None when RevisionWorx is not installed (runs a process: call it off the UI thread)."""
    try:
        rwx = RevisionWorx()
        return rwx if rwx.available() else None
    except Exception:  # noqa: BLE001 - optional integration never breaks Ledgerbook
        return None


def index(docs):
    """number (case-insensitive) -> list of documents with that number (normally one)."""
    out = {}
    for d in docs or []:
        key = str(d.get('number') or '').strip().casefold()
        if key:
            out.setdefault(key, []).append(d)
    return out


def lookup(value, idx):
    """The document a cell refers to: (doc or None, problem or '')."""
    key = str(value or '').strip().casefold()
    if not key:
        return None, ''
    hits = (idx or {}).get(key, [])
    if not hits:
        return None, 'not in RevisionWorx'
    if len(hits) > 1:
        return None, 'number used in %d projects' % len(hits)
    return hits[0], ''


def cell(value, idx):
    """(text, tone) for a table cell: 'DWG-100 · rev C · Released', 'good'. Without an index: the value as is."""
    value = str(value or '').strip()
    if not value or idx is None:
        return value, ''
    doc, problem = lookup(value, idx)
    if doc is None:
        return '%s · %s' % (value, problem), 'warn'
    latest = doc.get('latest') or {}
    text = '%s · rev %s · %s' % (value, latest.get('label', '?'), latest.get('state_name', ''))
    if doc.get('checkout'):
        text += ' · checked out'
    return text, TONE_FOR_STATE.get(latest.get('state'), '')


def choices(docs):
    """Display strings for a document picker, in the order of ``docs``."""
    return ['%s  ·  %s  ·  %s' % (d.get('number', ''), d.get('title', ''), (d.get('project') or {}).get('name', ''))
            for d in docs]
