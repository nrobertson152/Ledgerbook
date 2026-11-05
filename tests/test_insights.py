"""Numbers, totals, due dates, templates and CSV import (no Qt needed)."""
import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from ledgerbook import insights as I
from ledgerbook import templates
from ledgerbook.store import DEFAULT_FIELDS, Store

TODAY = date(2026, 11, 5)


class Numbers(unittest.TestCase):
    def test_what_people_type(self):
        for text, want in (('1234.50', '1234.50'), ('$1,234.50', '1234.50'), ('1,234,567', '1234567'),
                           ('€ 45', '45'), ('45£', '45'), ('(12.50)', '-12.50'), ('-$5', '-5'), ('$-5', '-5'),
                           ('+7', '7'), ('.5', '.5'), ('0', '0'), ('-0', '0'), ('1e5', '1e5'), (' 12 ', '12'), ('', '')):
            self.assertEqual(I.normalize_number(text), want, text)

    def test_rejects_ambiguous_and_non_numbers(self):
        for text in ('12,5', '1,23', 'abc', '1.2.3', 'nan', 'inf', '$', '--5', '12 kg'):
            with self.assertRaises(ValueError, msg=text):
                I.normalize_number(text)

    def test_totals(self):
        fields = [{'key': 'title', 'label': 'Item', 'type': 'text'}, {'key': 'cost', 'label': 'Cost', 'type': 'number'},
                  {'key': 'hours', 'label': 'Hours', 'type': 'number'}]
        rows = [{'cost': '$1,000', 'hours': ''}, {'cost': '234.5'}, {'cost': 'bad'}, {'title': 'x'}]
        (cost,) = I.column_totals(fields, rows)                       # Hours has no values: no total
        self.assertEqual((cost['count'], cost['sum'], cost['min'], cost['max']), (2, 1234.5, 234.5, 1000.0))
        self.assertEqual(I.totals_text(fields, rows), 'Cost: total 1,234.50 · average 617.25')
        self.assertEqual(I.totals_text(fields, [{'cost': '5'}]), 'Cost: total 5')
        self.assertEqual(I.fmt_number(-1234567.0), '-1,234,567')

    def test_readings_are_not_summed(self):
        reading = {'key': 'reading', 'label': 'Odometer', 'type': 'number'}
        self.assertFalse(I.shows_total(reading))                       # a summed odometer means nothing
        self.assertTrue(I.shows_total(dict(reading, total=True)))      # unless switched on
        self.assertFalse(I.shows_total({'key': 'cost', 'label': 'Cost', 'type': 'number', 'total': False}))
        self.assertFalse(I.shows_total({'key': 'x', 'label': 'X', 'type': 'text'}))
        fields = templates.fields('Vehicle maintenance')
        rows = [{'reading': '45000', 'cost': '90'}, {'reading': '47000', 'cost': '10'}]
        self.assertEqual(I.totals_text(fields, rows), 'Cost: total 100 · average 50')


class DueDates(unittest.TestCase):
    def test_cells(self):
        self.assertEqual(I.due_cell('2026-11-01', TODAY), ('2026-11-01 · overdue 4 days', 'bad'))
        self.assertEqual(I.due_cell('2026-11-04', TODAY), ('2026-11-04 · overdue 1 day', 'bad'))
        self.assertEqual(I.due_cell('2026-11-05', TODAY), ('2026-11-05 · due today', 'warn'))
        self.assertEqual(I.due_cell('2026-11-06', TODAY), ('2026-11-06 · due tomorrow', 'warn'))
        self.assertEqual(I.due_cell('2026-11-19', TODAY), ('2026-11-19 · in 14 days', 'warn'))
        self.assertEqual(I.due_cell('2026-11-20', TODAY), ('2026-11-20 · in 15 days', ''))
        self.assertEqual(I.due_cell('', TODAY), ('', ''))
        self.assertEqual(I.due_cell('soon', TODAY), ('soon', ''))

    def test_add_months_clamps_to_month_end(self):
        self.assertEqual(I.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(I.add_months(date(2028, 1, 31), 1), date(2028, 2, 29))
        self.assertEqual(I.add_months(date(2026, 11, 5), 3), date(2027, 2, 5))
        self.assertEqual(I.add_months(date(2026, 11, 5), 12), date(2027, 11, 5))
        self.assertEqual(I.add_months(date(2026, 3, 31), -1), date(2026, 2, 28))

    def test_upcoming_uses_the_newest_entry_per_item(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / 'db.sqlite3')
            car = s.add_book('Truck', fields=templates.fields('Vehicle maintenance'))
            s.save_entry(car, {'entry_date': '2026-05-01', 'title': 'Oil change', 'next_due': '2026-08-01'})
            s.save_entry(car, {'entry_date': '2026-08-03', 'title': 'Oil change', 'next_due': '2026-11-10'})
            s.save_entry(car, {'entry_date': '2026-01-10', 'title': 'Tyre rotation', 'next_due': '2026-10-01'})
            s.save_entry(car, {'entry_date': '2026-02-10', 'title': 'Brakes', 'next_due': '2027-06-01'})
            s.save_entry(car, {'entry_date': '2026-03-10', 'title': 'Wipers', 'next_due': ''})
            old = s.add_book('Old car', fields=templates.fields('Vehicle maintenance'))
            s.save_entry(old, {'title': 'Oil change', 'next_due': '2026-11-01'})
            s.configure_book(old, archived=1)                       # archived logbooks are left out
            plain = s.add_book('Notes')                              # no due column: ignored
            s.save_entry(plain, {'title': 'hello'})
            got = I.upcoming(s, TODAY)
            self.assertEqual([(g['item'], g['due'], g['days']) for g in got],
                             [('Tyre rotation', '2026-10-01', -35), ('Oil change', '2026-11-10', 5)])
            self.assertEqual(got[0]['book'], 'Truck')
            self.assertEqual(got[0]['field'], 'Next due')
            self.assertEqual(I.upcoming(s, TODAY, horizon=-100), [])
            s.close()


class Templates(unittest.TestCase):
    def test_every_template_is_a_valid_logbook(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / 'db.sqlite3')
            for name in templates.NAMES:
                bid = s.add_book(name, fields=templates.fields(name))
                self.assertEqual([f['key'] for f in s.columns(bid)], [f['key'] for f in templates.TEMPLATES[name]['fields']])
                self.assertEqual(s.columns(bid)[0]['key'], 'entry_date')
            self.assertEqual(templates.fields('Blank'), DEFAULT_FIELDS)
            s.close()

    def test_every_column_type_has_a_display_name(self):
        from ledgerbook.constants import TYPE_NAMES
        from ledgerbook.store import TYPES
        self.assertEqual(set(TYPE_NAMES), TYPES)
        self.assertEqual(TYPE_NAMES['due'], 'Due date')

    def test_fields_are_copies(self):
        a = templates.fields('Expenses')
        a[2]['options'].append('Changed')
        self.assertNotIn('Changed', templates.fields('Expenses')[2]['options'])

    def test_a_bad_field_list_creates_no_logbook(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / 'db.sqlite3')
            with self.assertRaises(ValueError):
                s.add_book('Broken', fields=[{'key': '1bad', 'label': 'x', 'type': 'text', 'visible': True}])
            self.assertEqual(len(s.books()), 0)
            s.close()


class Entries(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.s = Store(Path(self.dir.name) / 'db.sqlite3')
        self.bid = self.s.add_book('Expenses', fields=templates.fields('Expenses'))

    def tearDown(self):
        self.s.close()
        self.dir.cleanup()

    def test_numbers_are_stored_normalized_and_bad_ones_name_the_column(self):
        eid = self.s.save_entry(self.bid, {'title': 'Drill', 'cost': '$1,299.00'})
        row = self.s.db.execute('SELECT * FROM entries WHERE id=?', (eid,)).fetchone()
        self.assertEqual(self.s.values(row)['cost'], '1299.00')
        self.assertEqual(row['cost'], 1299.0)
        with self.assertRaisesRegex(ValueError, 'Amount'):
            self.s.save_entry(self.bid, {'title': 'x', 'cost': '12,5'})

    def test_due_dates_are_validated(self):
        bid = self.s.add_book('Car', fields=templates.fields('Vehicle maintenance'))
        self.s.save_entry(bid, {'title': 'Oil', 'next_due': '2027-01-31'})
        with self.assertRaisesRegex(ValueError, 'Next due'):
            self.s.save_entry(bid, {'title': 'Oil', 'next_due': '31/01/2027'})

    def test_retyped_legacy_column_never_breaks_saving(self):
        fields = self.s.columns(self.bid)
        for f in fields:
            if f['key'] == 'cost':
                f['type'] = 'text'
        self.s.set_columns(self.bid, fields)
        eid = self.s.save_entry(self.bid, {'title': 'Gift', 'cost': 'a lot'})
        row = self.s.db.execute('SELECT * FROM entries WHERE id=?', (eid,)).fetchone()
        self.assertEqual((self.s.values(row)['cost'], row['cost']), ('a lot', 0.0))

    def _csv(self, rows):
        path = Path(self.dir.name) / 'in.csv'
        with path.open('w', newline='', encoding='utf-8') as fp:
            csv.writer(fp).writerows(rows)
        return path

    def test_csv_headers_match_loosely_and_unknown_ones_are_reported(self):
        path = self._csv([['date', ' ITEM ', 'Amount:', 'Colour'], ['2026-11-01', 'Saw', '$45', 'red'],
                          ['', '', '', ''], ['2026-11-02', 'Blades', '12.5', 'blue']])
        rep = self.s.import_csv_report(self.bid, path)
        self.assertEqual(rep['imported'], 2)
        self.assertEqual(rep['ignored'], ['Colour'])
        self.assertIn('Category', rep['missing'])
        values = sorted((self.s.values(r)['title'], self.s.values(r)['cost']) for r in self.s.entries(self.bid))
        self.assertEqual(values, [('Blades', '12.5'), ('Saw', '45')])

    def test_csv_import_is_all_or_nothing(self):
        path = self._csv([['Date', 'Item', 'Amount'], ['2026-11-01', 'Saw', '45'], ['2026-11-02', 'Bad', 'twelve'],
                          ['2026-11-03', 'Glue', '3']])
        with self.assertRaisesRegex(ValueError, 'Row 3: .*Amount.*Nothing was imported'):
            self.s.import_csv(self.bid, path)
        self.assertEqual(self.s.entries(self.bid), [])
        self.s.save_entry(self.bid, {'title': 'after'})              # the connection is usable afterwards
        self.assertEqual(len(self.s.entries(self.bid)), 1)

    def test_csv_with_no_matching_headers_imports_nothing(self):
        path = self._csv([['Foo', 'Bar'], ['1', '2']])
        rep = self.s.import_csv_report(self.bid, path)
        self.assertEqual((rep['imported'], rep['matched'], rep['ignored']), (0, [], ['Foo', 'Bar']))

    def test_ledgerbook_file_with_formatted_numbers_imports(self):
        path = Path(self.dir.name) / 'x.ledgerbook'
        path.write_text(json.dumps({'format': 'ledgerbook-logbook', 'schema_version': 1, 'name': 'Imported',
                                    'description': '', 'columns': templates.fields('Expenses'),
                                    'entries': [{'title': 'Saw', 'cost': '$1,045.10', 'entry_date': '2026-11-01'}]}),
                        encoding='utf-8')
        new, count = self.s.import_logbook(path)
        row = self.s.entries(new)[0]
        self.assertEqual((count, self.s.values(row)['cost'], row['cost']), (1, '1045.10', 1045.1))


if __name__ == '__main__':
    unittest.main()
