"""Bounded streaming JSON index and lossless scalar patches. Standard library only."""
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
import schema
import game_data

LIMIT = 512 * 1024 * 1024
@contextmanager
def connection(path):
    db = sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

class Parser:
    def __init__(self, f, db):
        self.f, self.db, self.pos = f, db, 0
        self.c = f.read(1)
        self.count = 0

    def advance(self):
        c = self.c
        self.pos += len(c)
        self.c = self.f.read(1)
        return c

    def ws(self):
        while self.c and self.c in b' \r\n\t':
            self.advance()

    def string(self, key=False):
        start = self.pos
        self.advance()
        small = bytearray(b'"')
        # Validate UTF-8 incrementally, including strings too large for display.
        import codecs
        decoder = codecs.getincrementaldecoder('utf-8')('strict')
        chunk = bytearray()
        while self.c and self.c != b'"':
            c = self.advance()
            if c[0] < 32:
                raise ValueError('JSON string contains control character')
            chunk.extend(c)
            if len(small) <= 4096:
                small.extend(c)
            if c == b'\\':
                e = self.advance()
                if not e or e not in b'"\\/bfnrtu':
                    raise ValueError('Invalid JSON escape')
                chunk.extend(e)
                if len(small) <= 4096:
                    small.extend(e)
                if e == b'u':
                    for _ in range(4):
                        h = self.advance()
                        if not h or h not in b'0123456789abcdefABCDEF':
                            raise ValueError('Invalid Unicode escape')
                        chunk.extend(h)
                        if len(small) <= 4096:
                            small.extend(h)
            if len(chunk) >= 4096:
                decoder.decode(bytes(chunk))
                chunk.clear()
        if self.c != b'"':
            raise ValueError('Unterminated JSON string')
        decoder.decode(bytes(chunk), final=True)
        self.advance()
        if self.pos - start <= 4096:
            small.extend(b'"')
            return json.loads(small), start, self.pos
        if key:
            raise ValueError('Object key too long')
        return None, start, self.pos

    def value(self, path='', depth=0):
        if depth > 100:
            raise ValueError('JSON nesting too deep')
        self.ws()
        start = self.pos
        if self.c in (b'{', b'['):
            obj = self.advance() == b'{'
            end = b'}' if obj else b']'
            self.ws()
            i = 0
            if self.c == end:
                self.advance()
                self.db.execute('INSERT INTO containers VALUES (?,?,?,?,?)',
                                (path,start,self.pos,'object' if obj else 'array',0))
                return
            while True:
                if obj:
                    if self.c != b'"':
                        raise ValueError('Expected object key')
                    key, _, _ = self.string(True)
                    try:
                        self.db.execute('INSERT INTO members VALUES (?,?)',(path,key))
                    except sqlite3.IntegrityError as e:
                        raise ValueError('Duplicate object key: '+key) from e
                    self.ws()
                    if self.advance() != b':':
                        raise ValueError('Expected colon')
                    part = key.replace('~', '~0').replace('/', '~1')
                else:
                    part = str(i)
                self.value(path + '/' + part, depth + 1)
                self.ws()
                if self.c == end:
                    self.advance()
                    self.db.execute('INSERT INTO containers VALUES (?,?,?,?,?)',
                                    (path,start,self.pos,'object' if obj else 'array',i+1))
                    return
                if self.advance() != b',':
                    raise ValueError('Expected comma')
                self.ws()
                i += 1
        if self.c == b'"':
            val, start, stop = self.string()
            kind = 'string' if val is not None else 'large string'
        else:
            token = bytearray()
            while self.c and self.c not in b',]} \r\n\t':
                token.extend(self.advance())
                if len(token) > 128:
                    raise ValueError('Scalar too long')
            if not re.fullmatch(rb'(?:null|true|false|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)', token):
                raise ValueError('Invalid JSON scalar')
            val = json.loads(token)
            if isinstance(val, float) and not math.isfinite(val):
                raise ValueError('Nonfinite number')
            kind = 'null' if val is None else 'boolean' if isinstance(val, bool) else 'number'
            stop = self.pos
        preview = json.dumps(val, ensure_ascii=True) if kind != 'large string' else '"[large string]"'
        try:
            self.db.execute('INSERT INTO fields VALUES (?,?,?,?,?)', (path, start, stop, kind, preview))
        except sqlite3.IntegrityError as e:
            raise ValueError('Duplicate JSON key: ' + path) from e
        self.count += 1

def index_json(raw, index):
    with connection(index) as db:
        db.execute('CREATE TABLE fields(path TEXT PRIMARY KEY,start INTEGER,stop INTEGER,kind TEXT,value TEXT)')
        db.execute('CREATE TABLE containers(path TEXT PRIMARY KEY,start INTEGER,stop INTEGER,kind TEXT,count INTEGER)')
        db.execute('CREATE TABLE members(parent TEXT,name TEXT,PRIMARY KEY(parent,name))')
        with open(raw, 'rb') as f:
            p = Parser(f, db)
            p.value()
            p.ws()
            if p.c:
                raise ValueError('Trailing JSON bytes')
        if not db.execute("SELECT 1 FROM fields WHERE path='/TotalCash'").fetchone():
            raise ValueError('Not a supported CoffeeShop save')
        return p.count

def prepare(source, folder, game=None):
    source, folder = Path(source), Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    before = digest(source)
    raw = folder / 'raw.json'
    total = 0
    with gzip.open(source, 'rb') as f, open(raw, 'xb') as out:
        for b in iter(lambda: f.read(1048576), b''):
            total += len(b)
            if total > LIMIT:
                raise ValueError('Save exceeds 512 MiB decompression limit')
            out.write(b)
    count = index_json(raw, folder / 'index.sqlite')
    if digest(source) != before:
        raise ValueError('Source changed during parsing; reopen it')
    try:
        catalogue = game_data.load_install(source,game)
    except (ValueError,OSError,KeyError) as e:
        catalogue = {'error':str(e)}
    catfile = folder / 'catalogue.json'
    catfile.write_text(json.dumps(catalogue,ensure_ascii=True),encoding='utf-8')
    meta = {'source': str(source.resolve()), 'sha256': before, 'raw_sha256': digest(raw),
            'bytes': total, 'fields': count, 'index_sha256':digest(folder/'index.sqlite'),
            'catalogue_sha256':digest(catfile), 'catalogue_error':catalogue.get('error')}
    (folder / 'meta.json').write_text(json.dumps(meta), encoding='utf-8')
    return meta

def rows(folder, page=0, query=''):
    cat = catalogue(folder)
    with connection(Path(folder) / 'index.sqlite') as db:
        # Literal substring search, rather than SQL LIKE wildcard interpretation.
        where = ' WHERE instr(path,?) > 0'
        args = (query,)
        if '_charaIconByte' not in query:
            where += " AND path NOT GLOB '/Charas/*/Looks/_charaIconByte/*'"
        if query == '@global':
            where = " WHERE instr(substr(path,2),'/')=0"
            args = ()
        count = db.execute('SELECT count(*) FROM fields' + where, args).fetchone()[0]
        result = db.execute('SELECT path,kind,value FROM fields' + where + ' ORDER BY path LIMIT 60 OFFSET ?',
                            (*args, page * 60)).fetchall()
        def browser_value(v):
            value=json.loads(v)
            return str(value) if type(value) is int and abs(value)>9007199254740991 else value
        return {'count': count, 'page': page, 'rows': [
            {'path': p, 'kind': k, 'value': browser_value(v), 'editable':schema.describe(p,db,cat) is not None,
             'rule':schema.describe(p,db,cat),
             'label':schema.LABELS.get(p.rsplit('/', 1)[-1], '')} for p, k, v in result]}

def catalogue(folder):
    p = Path(folder)/'catalogue.json'
    if not p.exists() or p.stat().st_size>4*1048576:
        return {'error':'请重新打开存档以建立本机资料索引'}
    return json.loads(p.read_text(encoding='utf-8'))

def read_node(folder,path,db=None,raw=None):
    if db is None:
        with connection(Path(folder)/'index.sqlite') as con:
            return read_node(folder,path,con,raw)
    row = db.execute('SELECT start,stop FROM containers WHERE path=?',(path,)).fetchone()
    if not row or row[1]-row[0]>262144:
        raise ValueError('该数据块不存在或超过有界编辑大小：'+path)
    with open(raw or Path(folder)/'raw.json','rb') as f:
        f.seek(row[0])
        return json.loads(f.read(row[1]-row[0]))

def export(folder, changes, target):
    folder, target = Path(folder), Path(target)
    if not isinstance(changes,dict) or not changes or len(changes) > 2048:
        raise ValueError('No edits or too many edits')
    meta = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
    if target.resolve() == Path(meta['source']).resolve() or target.exists():
        raise ValueError('Export must be a new file; overwriting is forbidden')
    def unchanged():
        return (digest(meta['source'])==meta['sha256'] and digest(folder/'raw.json')==meta['raw_sha256']
                and digest(folder/'index.sqlite')==meta['index_sha256']
                and digest(folder/'catalogue.json')==meta['catalogue_sha256'])
    if not unchanged():
        raise ValueError('Source/cache changed; reopen the save')
    patches = []
    cat = catalogue(folder)
    with connection(folder / 'index.sqlite') as db:
        for path, value in changes.items():
            row = db.execute('SELECT start,stop,kind FROM fields WHERE path=? UNION ALL SELECT start,stop,kind FROM containers WHERE path=?', (path,path)).fetchone()
            if not row:
                raise ValueError('Unknown field')
            start, stop, kind = row
            spec = schema.describe(path,db,cat)
            if path=='/ShopExp' and '/ShopLevel' in changes and 'error' not in cat and spec:
                lv=cat['levels'].get(str(changes['/ShopLevel']))
                if lv:
                    spec['max']=max(0,lv['next_exp']-1)
            patches.append((start,stop,schema.validate_value(path,value,spec,kind)))
        schema.validate_links(changes,db,cat,lambda p:read_node(folder,p,db))
    ordered = sorted(patches)
    if any(a[1]>b[0] for a,b in zip(ordered,ordered[1:])):
        raise ValueError('同一数据块及其子字段不能同时修改；请保留一种修改方式')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as td:
        td = Path(td)
        edited = td / 'edited.json'
        with open(folder / 'raw.json', 'rb') as src, open(edited, 'wb') as out:
            for start, stop, replacement in ordered:
                remaining = start - src.tell()
                if remaining < 0:
                    raise ValueError('Overlapping edits')
                while remaining:
                    b = src.read(min(1048576, remaining))
                    if not b:
                        raise ValueError('Truncated cache')
                    out.write(b)
                    remaining -= len(b)
                src.seek(stop)
                out.write(replacement)
            shutil.copyfileobj(src, out, 1048576)
        index_json(edited, td / 'verify.sqlite')
        with connection(td / 'verify.sqlite') as db:
            for path, value in changes.items():
                row=db.execute('SELECT value FROM fields WHERE path=?',(path,)).fetchone()
                readback=json.loads(row[0]) if row else read_node(folder,path,db,edited)
                if readback != value:
                    raise ValueError('Read-back validation failed')
        packed = td / 'export.sd'
        with open(edited, 'rb') as src, gzip.open(packed, 'wb', compresslevel=6) as out:
            shutil.copyfileobj(src, out, 1048576)
        h = hashlib.sha256()
        with gzip.open(packed, 'rb') as f:
            for b in iter(lambda: f.read(1048576), b''):
                h.update(b)
        if h.hexdigest() != digest(edited):
            raise ValueError('Compressed read-back failed')
        if not unchanged():
            raise ValueError('源存档或缓存在导出时发生变化；请重新打开')
        # Atomic exclusive publication: the complete validated file appears at once.
        try:
            os.link(packed, target)
        except FileExistsError:
            raise ValueError('Export already exists') from None
    return {'file': str(target), 'sha256': digest(target), 'changes': len(changes)}
