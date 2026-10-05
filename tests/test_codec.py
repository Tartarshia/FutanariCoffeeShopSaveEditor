import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import codec

class CodecTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.sd'
        self.raw = b'{\r\n "TotalCash" : 10, "HPoint":3,"ShopExp":4, "CoffeeShopName":"Cafe", "Charas":[{"Looks":{"DefName":"A"}}],"unknown":1.2300e+02,"large":"' + b'a' * 20000 + b'"}\n'
        self.source.write_bytes(gzip.compress(self.raw))
        self.original = self.source.read_bytes()
        self.folder = self.root / 'cache'
        with patch('game_data.load_install',return_value={'error':'Synthetic test, no game needed'}):
            codec.prepare(self.source, self.folder)

    def test_lossless_patch_and_source_unchanged(self):
        target = self.root / 'new.sd'
        codec.export(self.folder, {'/TotalCash': 1000, '/CoffeeShopName': '新店'}, target)
        expected = self.raw.replace(b'10,', b'1000,', 1).replace(b'"Cafe"', json.dumps('新店').encode())
        self.assertEqual(gzip.decompress(target.read_bytes()), expected)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_pagination_large_string_and_literal_search(self):
        self.assertEqual(codec.rows(self.folder, query='/large')['rows'][0]['kind'], 'large string')
        self.assertEqual(codec.rows(self.folder, query='%')['count'], 0)
        self.assertEqual(codec.rows(self.folder, page=100)['rows'], [])

    def test_reject_overwrite_and_unsafe_fields(self):
        for target, changes in [(self.source, {'/TotalCash': 1}),
                                (self.root/'new.sd', {'/unknown': 2}),
                                (self.root/'new.sd', {'/TotalCash': True}),
                                (self.root/'new.sd', {'/TotalCash': -1}),
                                (self.root/'new.sd', {'/TotalCash': 2147483648}),
                                (self.root/'new.sd', {'/CoffeeShopName': ''})]:
            with self.assertRaises(ValueError):
                codec.export(self.folder, changes, target)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_detect_changed_source(self):
        self.source.write_bytes(gzip.compress(b'{"TotalCash":20}'))
        with self.assertRaises(ValueError):
            codec.export(self.folder, {'/TotalCash': 3}, self.root/'new.sd')

    def test_save_updates_original_and_previous_version_backup(self):
        result = codec.save_with_backup(self.folder, {'/TotalCash': 11})
        backup = Path(result['backup'])
        self.assertEqual(backup.read_bytes(), self.original)
        self.assertEqual(gzip.decompress(self.source.read_bytes()), self.raw.replace(b'10,', b'11,', 1))
        first = self.source.read_bytes()
        fresh = self.root / 'fresh-cache'
        with patch('game_data.load_install', return_value={'error':'Synthetic test'}):
            codec.prepare(self.source, fresh)
        codec.save_with_backup(fresh, {'/TotalCash': 12})
        self.assertEqual(backup.read_bytes(), first)
        self.assertEqual(gzip.decompress(self.source.read_bytes()), self.raw.replace(b'10,', b'12,', 1))
        self.assertFalse(self.source.with_name(self.source.name+'.editor-lock').exists())

    def test_failed_replace_preserves_original_and_backup(self):
        replace = codec.os.replace
        def fail_source(src, dst):
            if Path(dst).resolve() == self.source.resolve():
                raise PermissionError('Synthetic locked save')
            return replace(src, dst)
        with patch('codec.os.replace', side_effect=fail_source):
            with self.assertRaises(PermissionError):
                codec.save_with_backup(self.folder, {'/TotalCash': 11})
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.source.with_name(self.source.name+'.bak').read_bytes(), self.original)
        self.assertFalse(self.source.with_name(self.source.name+'.editor-lock').exists())

    def test_stale_save_cannot_overwrite_existing_backup(self):
        backup = self.source.with_name(self.source.name+'.bak')
        backup.write_bytes(b'previous backup')
        self.source.write_bytes(gzip.compress(b'{"TotalCash":20}'))
        changed = self.source.read_bytes()
        with self.assertRaises(ValueError):
            codec.save_with_backup(self.folder, {'/TotalCash': 11})
        self.assertEqual(backup.read_bytes(), b'previous backup')
        self.assertEqual(self.source.read_bytes(), changed)

    def test_invalid_json_and_duplicates(self):
        invalid = [b'{"TotalCash":01}', b'{"TotalCash":1,"TotalCash":2}',
                   b'{"TotalCash":1,"a":{},"a":[]}',
                   b'{"TotalCash":1,}', b'{"TotalCash":1} trailing',
                   b'{"TotalCash":1,"s":"\\q"}', b'{"TotalCash":1,"s":"\xff"}',
                   b'{"TotalCash":1,"s":"unterminated}', b'{"TotalCash":1e999}']
        for i, raw in enumerate(invalid):
            with self.subTest(raw=raw):
                p = self.root / f'bad{i}.json'
                p.write_bytes(raw)
                with self.assertRaises((ValueError, UnicodeError)):
                    codec.index_json(p, self.root / f'bad{i}.sqlite')

    def test_truncated_gzip(self):
        self.source.write_bytes(self.original[:-6])
        with self.assertRaises((EOFError, OSError)):
            codec.prepare(self.source, self.root/'badgzip')

    def test_existing_export_preserved(self):
        target = self.root/'new.sd'
        target.write_bytes(b'KEEP')
        with self.assertRaises(ValueError):
            codec.export(self.folder, {'/TotalCash': 3}, target)
        self.assertEqual(target.read_bytes(), b'KEEP')

if __name__ == '__main__':
    unittest.main()
