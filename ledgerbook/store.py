"""Ledgerbook v3 persistence. Generic field definitions, backwards compatible with v1/v2."""
import csv
import copy
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .insights import normalize_number

DEFAULT_DB = Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share'))) / 'ledgerbook' / 'ledgerbook.sqlite3'
DEFAULT_FIELDS = [
    {'key':'entry_date','label':'Date','type':'date','visible':True},
    {'key':'title','label':'Entry','type':'text','visible':True},
    {'key':'notes','label':'Notes','type':'text','visible':True},
]
LEGACY_FIELDS = [
    {'key':'entry_date','label':'Date','type':'date','visible':True},
    {'key':'title','label':'Title','type':'text','visible':True},
    {'key':'category','label':'Category','type':'text','visible':True},
    {'key':'reading','label':'Measurement','type':'number','visible':True},
    {'key':'notes','label':'Notes','type':'text','visible':True},
]
LEGACY_KEYS = {'entry_date','title','category','reading','cost','notes'}
TYPES = {'text','number','date','checkbox','select','multiline','attachment','revision','due'}

def _legacy_number(value,default):
    """The value for the old fixed `reading` / `cost` columns. Columns can be retyped since v3, so a text value
    there is kept in the entry's own data and the fixed column gets the default, never an error."""
    try:
        n=normalize_number(value) if str(value or '').strip() else ''
        return float(n) if n else default
    except ValueError:
        return default

class Store:
    def __init__(self, path=None):
        self.path=Path(path) if path else DEFAULT_DB
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS books (id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'General', description TEXT NOT NULL DEFAULT '', unit TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS entries (id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE, entry_date TEXT NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', reading REAL, cost REAL NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS idx_entries_book_date ON entries(book_id,entry_date DESC);
        ''')
        self._migrate()
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS folders(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS deleted_entries(id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL, payload TEXT NOT NULL, deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS deleted_books(id INTEGER PRIMARY KEY, payload TEXT NOT NULL, deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """)
        bc={r['name'] for r in self.db.execute('PRAGMA table_info(books)')}
        for col,definition in [('folder_id','INTEGER'),('archived','INTEGER NOT NULL DEFAULT 0'),('icon',"TEXT NOT NULL DEFAULT '▤'"),('accent',"TEXT NOT NULL DEFAULT ''")]:
            if col not in bc:self.db.execute(f'ALTER TABLE books ADD COLUMN {col} {definition}')
        self.db.commit()

    def _migrate(self):
        bc={r['name'] for r in self.db.execute('PRAGMA table_info(books)')}
        ec={r['name'] for r in self.db.execute('PRAGMA table_info(entries)')}
        if 'columns_json' not in bc:self.db.execute("ALTER TABLE books ADD COLUMN columns_json TEXT NOT NULL DEFAULT ''")
        if 'extras_json' not in ec:self.db.execute("ALTER TABLE entries ADD COLUMN extras_json TEXT NOT NULL DEFAULT '{}'")
        # Keep legacy physical fields intact; never destroy data during upgrades.
        for row in self.db.execute('SELECT id,columns_json FROM books').fetchall():
            if row['columns_json']:
                fields=json.loads(row['columns_json'])
                # Cost is no longer a special built-in; preserve as a normal editable field if used.
                for f in fields:
                    if f['key']=='cost':f['label']=f.get('label') or 'Cost'
                    f.setdefault('visible',True)
                self.db.execute('UPDATE books SET columns_json=? WHERE id=?',(json.dumps(fields),row['id']))
            else:
                # Existing books retain their original information, including costs if nonzero.
                has_cost=self.db.execute('SELECT 1 FROM entries WHERE book_id=? AND cost!=0 LIMIT 1',(row['id'],)).fetchone()
                fields=[dict(f) for f in LEGACY_FIELDS]
                if has_cost:fields.append({'key':'cost','label':'Cost','type':'number','visible':True})
                self.db.execute('UPDATE books SET columns_json=? WHERE id=?',(json.dumps(fields),row['id']))

    def books(self,include_archived=False):
        return self.db.execute('SELECT b.*, COUNT(e.id) entry_count FROM books b LEFT JOIN entries e ON e.book_id=b.id WHERE (? OR b.archived=0) GROUP BY b.id ORDER BY b.id DESC',(int(include_archived),)).fetchall()

    def columns(self,book_id):
        row=self.db.execute('SELECT columns_json FROM books WHERE id=?',(book_id,)).fetchone()
        if row is None:raise ValueError('Logbook not found')
        return json.loads(row['columns_json']) if row['columns_json'] else [dict(f) for f in DEFAULT_FIELDS]

    @staticmethod
    def _check_fields(fields):
        if not fields or not any(f.get('visible',True) for f in fields):raise ValueError('Keep at least one visible column')
        keys=[f['key'] for f in fields]
        if len(set(keys))!=len(keys):raise ValueError('Duplicate field keys')
        for f in fields:
            if not f['label'].strip():raise ValueError('Column labels cannot be blank')
            if f['type'] not in TYPES:raise ValueError('Invalid column type')
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',f['key']):raise ValueError('Invalid column identifier')

    def set_columns(self,book_id,fields):
        self._check_fields(fields)
        if not self.db.execute('SELECT 1 FROM books WHERE id=?',(book_id,)).fetchone():raise ValueError('Logbook not found')
        self.db.execute('UPDATE books SET columns_json=? WHERE id=?',(json.dumps(fields),book_id));self.db.commit()

    def add_book(self,name,description='',fields=None):
        """A new logbook with the default columns, or with ``fields`` (a template's column list)."""
        if not name.strip():raise ValueError('Enter a logbook name')
        with self.db:
            cur=self.db.execute('INSERT INTO books(name,description,columns_json) VALUES(?,?,?)',(name.strip(),description.strip(),json.dumps(DEFAULT_FIELDS)))
            if fields is not None:
                self._check_fields(fields)
                self.db.execute('UPDATE books SET columns_json=? WHERE id=?',(json.dumps(fields),cur.lastrowid))
        return cur.lastrowid

    def update_book(self,book_id,name,description=''):
        if not name.strip():raise ValueError('Enter a logbook name')
        self.db.execute('UPDATE books SET name=?,description=? WHERE id=?',(name.strip(),description.strip(),book_id));self.db.commit()

    def delete_book(self,book_id):
        book=self.db.execute('SELECT * FROM books WHERE id=?',(book_id,)).fetchone()
        if book:
            payload={'book':dict(book),'entries':[dict(r) for r in self.entries(book_id)]}
            self.db.execute('INSERT INTO deleted_books(payload) VALUES(?)',(json.dumps(payload),))
        self.db.execute('DELETE FROM books WHERE id=?',(book_id,));self.db.commit()

    def folders(self):return self.db.execute('SELECT * FROM folders ORDER BY name COLLATE NOCASE').fetchall()
    def add_folder(self,name):
        if not name.strip():raise ValueError('Folder name required')
        with self.db:return self.db.execute('INSERT INTO folders(name) VALUES(?)',(name.strip(),)).lastrowid
    def rename_folder(self,folder_id,name):
        if not name.strip():raise ValueError('Folder name required')
        with self.db:self.db.execute('UPDATE folders SET name=? WHERE id=?',(name.strip(),folder_id))
    def delete_folder(self,folder_id):
        with self.db:
            self.db.execute('UPDATE books SET folder_id=NULL WHERE folder_id=?',(folder_id,))
            self.db.execute('DELETE FROM folders WHERE id=?',(folder_id,))
    def configure_book(self,book_id,folder_id=None,archived=None,icon=None,accent=None):
        changes={k:v for k,v in [('folder_id',folder_id),('archived',archived),('icon',icon),('accent',accent)] if v is not None}
        if changes:
            with self.db:self.db.execute('UPDATE books SET '+','.join(k+'=?' for k in changes)+' WHERE id=?',(*changes.values(),book_id))
    def duplicate_book(self,book_id,include_entries=False):
        book=self.db.execute('SELECT * FROM books WHERE id=?',(book_id,)).fetchone()
        if not book:raise ValueError('Logbook not found')
        with self.db:
            cur=self.db.execute('INSERT INTO books(name,description,columns_json,folder_id,icon,accent) VALUES(?,?,?,?,?,?)',
                (book['name']+' (copy)',book['description'],book['columns_json'],book['folder_id'],book['icon'],book['accent']))
            new_id=cur.lastrowid
            if include_entries:
                for row in self.entries(book_id):
                    self.db.execute('INSERT INTO entries(book_id,entry_date,title,category,reading,cost,notes,extras_json) VALUES(?,?,?,?,?,?,?,?)',
                        (new_id,*[row[k] for k in ('entry_date','title','category','reading','cost','notes','extras_json')]))
        return new_id
    def restore_deleted_entry(self,trash_id):
        r=self.db.execute('SELECT * FROM deleted_entries WHERE id=?',(trash_id,)).fetchone()
        if not r:raise ValueError('Deleted entry not found')
        data=json.loads(r['payload']);bid=r['book_id']
        if not self.db.execute('SELECT 1 FROM books WHERE id=?',(bid,)).fetchone():raise ValueError('Original logbook no longer exists')
        with self.db:
            self.save_entry(bid,data)
            self.db.execute('DELETE FROM deleted_entries WHERE id=?',(trash_id,))
    def empty_recycle_bin(self):
        """Permanently discard deleted entry snapshots in one transaction."""
        with self.db:
            self.db.execute('DELETE FROM deleted_entries')

    def deleted_items(self):return self.db.execute('SELECT * FROM deleted_entries ORDER BY deleted_at DESC').fetchall()
    def import_csv(self,book_id,path):
        return self.import_csv_report(book_id,path)['imported']

    def import_csv_report(self,book_id,path):
        """Import rows from a CSV whose first row names the columns (by label or key; case, spacing and a
        trailing colon do not matter). All or nothing: a bad value stops the import with the row number and
        nothing is added. Returns {'imported', 'matched', 'ignored', 'missing'} (column names)."""
        def norm(text):return re.sub(r'\s+',' ',str(text or '')).strip().rstrip(':').strip().casefold()
        fields=self.columns(book_id)
        lookup={}
        for f in fields:
            lookup.setdefault(norm(f['label']),f['key']);lookup.setdefault(norm(f['key']),f['key'])
        with open(path,encoding='utf-8-sig',newline='') as fp:
            reader=csv.reader(fp)
            header=next(reader,None)
            if not header or not any(str(h).strip() for h in header):raise ValueError('The CSV file has no heading row')
            columns=[lookup.get(norm(h)) for h in header]
            matched=[h for h,k in zip(header,columns) if k];ignored=[h for h,k in zip(header,columns) if not k and str(h).strip()]
            used=set(k for k in columns if k)
            missing=[f['label'] for f in fields if f['key'] not in used]
            count=0
            if used:
                try:
                    with self.db:
                        for n,row in enumerate(reader,start=2):
                            vals={}
                            for k,v in zip(columns,row):
                                if k and not str(vals.get(k,'')).strip():vals[k]=v
                            if not any(str(v).strip() for v in vals.values()):continue
                            try:self.save_entry(book_id,vals,commit=False)
                            except ValueError as e:raise ValueError('Row %d: %s. Nothing was imported.'%(n,e)) from None
                            count+=1
                except Exception:
                    self.db.rollback();raise
        return {'imported':count,'matched':matched,'ignored':ignored,'missing':missing}
    def integrity_check(self):return self.db.execute('PRAGMA integrity_check').fetchone()[0]


    def entries(self,book_id,query=''):
        rows=self.db.execute('SELECT * FROM entries WHERE book_id=? ORDER BY entry_date DESC,id DESC',(book_id,)).fetchall()
        if not query.strip():return rows
        q=query.casefold().strip()
        return [r for r in rows if q in ' '.join(str(v) for v in self.values(r).values()).casefold()]

    def values(self,row):
        data=json.loads(row['extras_json'] or '{}')
        for k in LEGACY_KEYS:
            if k not in data and k in row.keys():data[k]=row[k]
        return data

    def save_entry(self,book_id,values,entry_id=None,commit=True):
        fields=self.columns(book_id)
        cleaned={}
        for f in fields:
            k=f['key'];v=values.get(k,'')
            if f['type'] in ('date','due') and str(v if v is not None else '').strip():
                try:datetime.strptime(str(v).strip(),'%Y-%m-%d')
                except ValueError:raise ValueError('“%s” must be a date like 2026-11-05 (got “%s”)'%(f['label'],v)) from None
            if f['type']=='number' and str(v if v is not None else '').strip():
                try:v=normalize_number(v)
                except ValueError:raise ValueError('“%s” must be a number (got “%s”)'%(f['label'],v)) from None
            cleaned[k]=str(v).strip() if v is not None else ''
        if not any(str(v).strip() for v in cleaned.values()):raise ValueError('Enter at least one value')
        dt=cleaned.get('entry_date') or datetime.now().strftime('%Y-%m-%d')
        title=cleaned.get('title') or next((v for v in cleaned.values() if v),'Entry')
        legacy={'category':cleaned.get('category',''),'notes':cleaned.get('notes',''),'reading':None,'cost':0.0}
        legacy['reading']=_legacy_number(cleaned.get('reading'),None)
        legacy['cost']=_legacy_number(cleaned.get('cost'),0.0)
        params=(dt,title,legacy['category'],legacy['reading'],legacy['cost'],legacy['notes'],json.dumps(cleaned))
        if entry_id is None:
            cur=self.db.execute('INSERT INTO entries(book_id,entry_date,title,category,reading,cost,notes,extras_json) VALUES(?,?,?,?,?,?,?,?)',(book_id,*params))
            result=cur.lastrowid
        else:
            self.db.execute('UPDATE entries SET entry_date=?,title=?,category=?,reading=?,cost=?,notes=?,extras_json=? WHERE id=? AND book_id=?',(*params,entry_id,book_id))
            result=entry_id
        if commit:self.db.commit()
        return result

    def delete_entry(self,entry_id):
        row=self.db.execute('SELECT * FROM entries WHERE id=?',(entry_id,)).fetchone()
        if row:self.db.execute('INSERT INTO deleted_entries(book_id,payload) VALUES(?,?)',(row['book_id'],json.dumps(self.values(row))))
        self.db.execute('DELETE FROM entries WHERE id=?',(entry_id,));self.db.commit()

    def export_csv(self,book_id,path):
        fields=self.columns(book_id)
        with open(path,'w',newline='',encoding='utf-8-sig') as fp:
            writer=csv.writer(fp);writer.writerow([f['label'] for f in fields])
            for row in self.entries(book_id):
                values=self.values(row)
                writer.writerow([values.get(f['key'],'') if values.get(f['key'],'') is not None else '' for f in fields])

    def export_logbook(self,book_id,path):
        book=self.db.execute('SELECT * FROM books WHERE id=?',(book_id,)).fetchone()
        if book is None:raise ValueError('Logbook not found')
        payload={'format':'ledgerbook-logbook','schema_version':1,'name':book['name'],
                 'description':book['description'],'columns':self.columns(book_id),
                 'entries':[self.values(r) for r in self.entries(book_id)]}
        destination=Path(path)
        temporary=destination.with_name(destination.name+'.tmp')
        try:
            with temporary.open('w',encoding='utf-8') as fp:
                json.dump(payload,fp,indent=2,ensure_ascii=False)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return len(payload['entries'])

    def import_logbook(self,path):
        source=Path(path)
        if source.stat().st_size>50_000_000:raise ValueError('Import file exceeds 50 MB')
        with source.open(encoding='utf-8') as fp:payload=json.load(fp)
        if not isinstance(payload,dict) or payload.get('format')!='ledgerbook-logbook' or payload.get('schema_version')!=1:
            raise ValueError('Not a supported Ledgerbook logbook file')
        name=payload.get('name');description=payload.get('description','')
        fields=payload.get('columns');entries=payload.get('entries')
        if not isinstance(name,str) or not name.strip() or len(name)>250:raise ValueError('Invalid logbook name')
        if not isinstance(description,str) or not isinstance(fields,list) or not fields or not isinstance(entries,list):
            raise ValueError('Invalid logbook structure')
        if len(fields)>200 or len(entries)>100000:raise ValueError('Logbook exceeds import limits')
        keys=[]
        for f in fields:
            if not isinstance(f,dict) or not isinstance(f.get('key'),str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',f['key']):raise ValueError('Invalid column identifier')
            if not isinstance(f.get('label'),str) or not f['label'].strip() or len(f['label'])>200 or f.get('type') not in TYPES or not isinstance(f.get('visible',True),bool):raise ValueError('Invalid column definition')
            keys.append(f['key'])
        if len(set(keys))!=len(keys):raise ValueError('Duplicate column identifiers')
        if not any(f.get('visible',True) for f in fields):raise ValueError('At least one column must be visible')
        for entry in entries:
            if not isinstance(entry,dict) or any(not isinstance(k,str) for k in entry):raise ValueError('Invalid entry')
            for f in fields:
                v=entry.get(f['key'],'')
                if v is not None and not isinstance(v,(str,int,float,bool)):raise ValueError('Invalid field value')
                if f['type'] in ('date','due') and str(v or '').strip():datetime.strptime(str(v),'%Y-%m-%d')
                if f['type']=='number' and str(v or '').strip():normalize_number(v)
        # Import is transactional: invalid files never leave partially created books.
        try:
            with self.db:
                cur=self.db.execute('INSERT INTO books(name,description,columns_json) VALUES(?,?,?)',
                                    (name.strip(),description,json.dumps(fields)))
                book_id=cur.lastrowid
                numbers={f['key'] for f in fields if f['type']=='number'}
                for entry in entries:
                    cleaned={k:str(entry.get(k,'') if entry.get(k,'') is not None else '') for k in keys}
                    for k in numbers:
                        if cleaned[k].strip():cleaned[k]=normalize_number(cleaned[k])
                    dt=cleaned.get('entry_date') or datetime.now().strftime('%Y-%m-%d')
                    title=cleaned.get('title') or next((v for v in cleaned.values() if v),'Entry')
                    self.db.execute('INSERT INTO entries(book_id,entry_date,title,category,reading,cost,notes,extras_json) VALUES(?,?,?,?,?,?,?,?)',
                                    (book_id,dt,title,cleaned.get('category',''),_legacy_number(cleaned.get('reading'),None),
                                     _legacy_number(cleaned.get('cost'),0.0),cleaned.get('notes',''),json.dumps(cleaned)))
        except Exception:raise
        return book_id,len(entries)

    def backup(self,path):
        destination=sqlite3.connect(str(path))
        try:self.db.backup(destination)
        finally:destination.close()

    def close(self):self.db.close()

# Additional recovery operations for the Qt edition. The original schema is retained.
def _restore_deleted_book(self, trash_id):
    row=self.db.execute('SELECT * FROM deleted_books WHERE id=?',(trash_id,)).fetchone()
    if row is None:raise ValueError('Deleted logbook not found')
    payload=json.loads(row['payload']);book=payload['book']
    with self.db:
        # Preserve IDs when possible; remap otherwise. This avoids overwriting existing records.
        fields=['name','kind','description','unit','columns_json','folder_id','archived','icon','accent']
        available={r['name'] for r in self.db.execute('PRAGMA table_info(books)')}
        fields=[f for f in fields if f in available]
        vals=[book.get(f) for f in fields]
        if 'folder_id' in fields and book.get('folder_id') is not None:
            if not self.db.execute('SELECT 1 FROM folders WHERE id=?',(book['folder_id'],)).fetchone():
                vals[fields.index('folder_id')]=None
        cur=self.db.execute('INSERT INTO books('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',vals)
        new_id=cur.lastrowid
        for r in payload['entries']:
            self.db.execute('INSERT INTO entries(book_id,entry_date,title,category,reading,cost,notes,extras_json) VALUES(?,?,?,?,?,?,?,?)',
                (new_id,*[r.get(k) for k in ('entry_date','title','category','reading','cost','notes','extras_json')]))
        self.db.execute('DELETE FROM deleted_books WHERE id=?',(trash_id,))
    return new_id

def _empty_all_recycle(self):
    with self.db:
        self.db.execute('DELETE FROM deleted_entries')
        self.db.execute('DELETE FROM deleted_books')

Store.restore_deleted_book=_restore_deleted_book
Store.empty_all_recycle=_empty_all_recycle


# ----------------------------------------------------------------------------------------------------------
# Read-only summaries used by the home screen. The database schema is unchanged.
def _last_dates(self):
    """{book_id: newest entry date} for every logbook that has entries."""
    return {r['book_id']: r['last'] for r in self.db.execute(
        'SELECT book_id, MAX(entry_date) AS last FROM entries GROUP BY book_id')}


def _overview(self):
    one = lambda sql: self.db.execute(sql).fetchone()[0]  # noqa: E731
    return {
        'logbooks': one('SELECT COUNT(*) FROM books WHERE archived=0'),
        'entries': one('SELECT COUNT(*) FROM entries e JOIN books b ON b.id=e.book_id WHERE b.archived=0'),
        'folders': one('SELECT COUNT(*) FROM folders'),
        'archived': one('SELECT COUNT(*) FROM books WHERE archived=1'),
        'recycled': one('SELECT COUNT(*) FROM deleted_entries') + one('SELECT COUNT(*) FROM deleted_books'),
        'last_entry': self.db.execute(
            'SELECT MAX(e.entry_date) FROM entries e JOIN books b ON b.id=e.book_id WHERE b.archived=0').fetchone()[0],
    }


def _book(self, book_id):
    return self.db.execute('SELECT * FROM books WHERE id=?', (book_id,)).fetchone()


Store.last_dates = _last_dates
Store.overview = _overview
Store.book = _book
