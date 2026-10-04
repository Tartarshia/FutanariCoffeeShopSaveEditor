import struct
import tempfile
from pathlib import Path
import unittest
import unity_assets

def aligned_string(text):
    b=text.encode('utf8')
    data=struct.pack('<i',len(b))+b
    return data+b'\0'*((-len(data))%4)

def synthetic_asset():
    # Independently generated minimal v22 metadata and one table object.
    mono=b'\0'*28+aligned_string('FixtureTable')+aligned_string('fixture-date')
    mono+=struct.pack('<i',2)+aligned_string('ID| ~ |Value| ~ |')+aligned_string('fixture| ~ |7| ~ |')
    metadata=b'6000.fixture\0'+struct.pack('<i?i',19,False,1)
    metadata+=struct.pack('<i?h',114,False,-1)+b'\0'*32
    metadata+=struct.pack('<i',1)
    metadata+=b'\0'*((-(48+len(metadata)))%4)
    metadata+=struct.pack('<qQIi',1,0,len(mono),0)
    offset=48+len(metadata)
    header=struct.pack('>4I',0,0,22,0)+b'\0'*4+struct.pack('>IQQQ',len(metadata),offset+len(mono),offset,0)
    return header+metadata+mono

class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'fixture.assets'

    def test_selected_table_and_object_offsets(self):
        self.path.write_bytes(synthetic_asset())
        refs=list(unity_assets.objects(self.path))
        self.assertEqual(len(refs),1)
        tables=list(unity_assets.table_rows(self.path,{'FixtureTable'}))
        self.assertEqual(tables,[('FixtureTable','fixture-date',['ID| ~ |Value| ~ |','fixture| ~ |7| ~ |'])])
        self.assertEqual(list(unity_assets.table_rows(self.path,{'Absent'})),[])

    def test_version_and_truncation_rejected(self):
        original=synthetic_asset()
        for bad in (original[:30],original[:-1],original[:8]+struct.pack('>I',21)+original[12:]):
            self.path.write_bytes(bad)
            with self.assertRaises(ValueError):
                list(unity_assets.objects(self.path))

    def test_reader_rejects_string_past_object_boundary(self):
        self.path.write_bytes(struct.pack('<i',100)+b'a'*8)
        with self.path.open('rb') as f:
            with self.assertRaises(ValueError):
                unity_assets.Reader(f,12).string()
