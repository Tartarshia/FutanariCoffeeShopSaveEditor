"""Read-only, bounded reader for the installed game's v22 stripped assets.

Only metadata and selected ScriptableObject tables are read. No game assets are
copied into the source distribution. Unsupported layouts fail closed.
"""
import struct
from pathlib import Path

class Reader:
    def __init__(self, f, end=None):
        self.f, self.end = f, end

    def read(self, n):
        if n < 0 or (self.end is not None and self.f.tell() + n > self.end):
            raise ValueError('Unity asset bounds exceeded')
        b = self.f.read(n)
        if len(b) != n:
            raise ValueError('Truncated Unity asset')
        return b

    def unpack(self, fmt):
        s = struct.Struct('<' + fmt)
        return s.unpack(self.read(s.size))

    def align(self):
        self.read((-self.f.tell()) % 4)

    def string(self, limit=1048576):
        n, = self.unpack('i')
        if not 0 <= n <= limit:
            raise ValueError('Invalid Unity string size')
        v = self.read(n).decode('utf-8')
        self.align()
        return v

    def cstring(self):
        b = bytearray()
        while True:
            c = self.read(1)
            if c == b'\0':
                return b.decode('utf-8')
            b.extend(c)
            if len(b) > 256:
                raise ValueError('Unity metadata string too long')

def objects(path):
    """Yield (path ID, class ID, byte start, byte size) without loading assets."""
    path = Path(path)
    size = path.stat().st_size
    with path.open('rb') as f:
        h = f.read(48)
        if len(h) != 48 or struct.unpack('>I', h[8:12])[0] != 22 or h[16] != 0:
            raise ValueError('Unsupported Unity assets: expected little-endian v22')
        metadata, file_size, offset, _ = struct.unpack('>IQQQ', h[20:48])
        if file_size != size or not 48 <= metadata <= 16 * 1048576 or not metadata <= offset <= size:
            raise ValueError('Invalid Unity assets header')
        r = Reader(f, offset)
        version = r.cstring()
        r.read(4)  # target platform
        enabled, = r.unpack('?')
        if enabled:
            raise ValueError('This reader requires stripped type trees')
        nt, = r.unpack('i')
        if not 0 <= nt <= 10000:
            raise ValueError('Too many Unity asset types')
        types = []
        for _ in range(nt):
            cid, _, _ = r.unpack('i?h')
            if cid == 114:
                r.read(16)
            r.read(16)
            types.append(cid)
        count, = r.unpack('i')
        if not 0 <= count <= 1000000:
            raise ValueError('Too many Unity objects')
        for _ in range(count):
            r.align()
            pid, start, length, tid = r.unpack('qQIi')
            if not 0 <= tid < nt or offset + start + length > size:
                raise ValueError('Invalid Unity object reference')
            yield pid, types[tid], offset + start, length

def table_rows(path, wanted):
    """Yield locally installed MstDataLocalFile rows for requested table names."""
    with open(path, 'rb') as f:
        for pid, cid, start, length in objects(path):
            if cid != 114 or length < 36:
                continue
            f.seek(start + 28)
            r = Reader(f, start + length)
            try:
                name = r.string(200)
            except (ValueError, UnicodeError):
                continue
            if name not in wanted:
                continue
            updated = r.string(200)
            count, = r.unpack('i')
            if not 0 <= count <= 20000:
                raise ValueError('Invalid master table row count')
            lines = [r.string() for _ in range(count)]
            if f.tell() != start + length:
                raise ValueError('Unexpected master table layout: ' + name)
            yield name, updated, lines
