"""Ready-made column sets for new logbooks (Qt-free). Every template is an ordinary logbook afterwards: its columns
can be renamed, retyped, reordered or removed like any other."""


def _f(key, label, typ='text', **extra):
    return dict(key=key, label=label, type=typ, visible=True, **extra)


TEMPLATES = {
    'Blank': dict(icon='▤', description='', fields=[
        _f('entry_date', 'Date', 'date'), _f('title', 'Entry'), _f('notes', 'Notes')]),
    'Vehicle maintenance': dict(icon='🚗', description='Services, repairs and what is due next.', fields=[
        _f('entry_date', 'Date', 'date'), _f('title', 'Service'), _f('reading', 'Odometer', 'number'),
        _f('cost', 'Cost', 'number'), _f('next_due', 'Next due', 'due'), _f('shop', 'Shop'),
        _f('notes', 'Notes', 'multiline')]),
    'Equipment & calibration': dict(icon='🔧', description='Calibration and inspection records with due dates.',
                                    fields=[
        _f('entry_date', 'Date', 'date'), _f('title', 'Equipment'), _f('serial', 'Serial number'),
        _f('result', 'Result', 'select', options=['Pass', 'Adjusted', 'Fail']),
        _f('next_due', 'Next calibration', 'due'), _f('certificate', 'Certificate', 'attachment'),
        _f('notes', 'Notes', 'multiline')]),
    'Expenses': dict(icon='💳', description='What was spent, on what, with receipts.', fields=[
        _f('entry_date', 'Date', 'date'), _f('title', 'Item'),
        _f('category', 'Category', 'select', options=['Materials', 'Tools', 'Services', 'Travel', 'Other']),
        _f('cost', 'Amount', 'number'), _f('paid', 'Paid', 'checkbox'), _f('receipt', 'Receipt', 'attachment'),
        _f('notes', 'Notes')]),
    'Inspections': dict(icon='☑️', description='Inspections, findings and the next one due.', fields=[
        _f('entry_date', 'Date', 'date'), _f('title', 'Asset or area'), _f('inspector', 'Inspector'),
        _f('result', 'Result', 'select', options=['Pass', 'Needs attention', 'Fail']),
        _f('next_due', 'Next inspection', 'due'), _f('notes', 'Findings', 'multiline')]),
    'Project log': dict(icon='📝', description='Work done on a project, hours and the drawings involved.', fields=[
        _f('entry_date', 'Date', 'date'), _f('title', 'Entry'), _f('hours', 'Hours', 'number'),
        _f('drawing', 'Drawing', 'revision'), _f('notes', 'Notes', 'multiline')]),
}
NAMES = list(TEMPLATES)


def fields(name):
    """A fresh copy of a template's columns (callers may change it)."""
    return [dict(f, options=list(f['options'])) if 'options' in f else dict(f) for f in TEMPLATES[name]['fields']]
