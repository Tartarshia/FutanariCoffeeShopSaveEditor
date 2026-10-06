"""Synthetic bulk clothing stock, failure atomicity and unrelated-byte checks."""
from copy import deepcopy
import gzip
import json
import unittest
from unittest.mock import patch
import codec
import presets
import test_gameplay


def catalogue():
    cat=test_gameplay.catalog()
    for key in ('fixture_low','fixture_high','fixture_new_clothes','fixture_banned_clothes'):
        cat['items'][key]={'id':key,'name':key,'type':'Clothes','stack':99,
                          'addable':key!='fixture_banned_clothes'}
    return cat


class ClothingStockTests(unittest.TestCase):
    def test_add_missing_set_existing_and_preserve_other_items(self):
        cat=catalogue()
        original=[{'m':'fixture_item','c':3},{'m':'fixture_low','c':2},
                  {'m':'fixture_high','c':70},{'m':'fixture_banned_clothes','c':7},
                  {'m':'unknown_fixture','c':4,'keep':'untouched'}]
        before=deepcopy(original)
        pending=deepcopy(original)
        pending[0]['c']=5
        result=presets.clothing_stock(pending,original,cat)
        self.assertEqual((result['total'],result['added'],result['changed']),(3,1,2))
        values={v['m']:v for v in result['items']}
        for key in ('fixture_low','fixture_high','fixture_new_clothes'):
            self.assertEqual(values[key]['c'],20)
        self.assertEqual(values['fixture_item']['c'],5)
        self.assertEqual(values['fixture_banned_clothes'],original[3])
        self.assertEqual(values['unknown_fixture'],original[4])
        self.assertEqual(original,before)
        self.assertEqual(pending[1]['c'],2)
        self.assertEqual(presets.clothing_stock(result['items'],original,cat)['items'],result['items'])

    def test_invalid_limits_and_inventory_fail_without_mutating_inputs(self):
        cat=catalogue()
        original=[{'m':'fixture_low','c':2}]
        before=deepcopy(original)
        cat['items']['fixture_new_clothes']['stack']=19
        with self.assertRaisesRegex(ValueError,'上限不足 20'):
            presets.clothing_stock(original,original,cat)
        self.assertEqual(original,before)
        full=[{'m':f'unknown_{i}','c':1} for i in range(1000)]
        with self.assertRaisesRegex(ValueError,'仓库清单过大'):
            presets.clothing_stock(full,full,catalogue())
        self.assertEqual(len(full),1000)
        with self.assertRaises(ValueError):
            presets.clothing_stock([{'m':'unknown_fixture','c':5}],[],catalogue())

    def test_export_preserves_wearing_employees_and_all_bytes_outside_items(self):
        f=test_gameplay.GameplayTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.document['Charas'][0]['Looks']['WearingClothes']=[{'ItemMstID':'fixture_high','Slots':[1]}]
        f.document['Items']=[{'m':'fixture_item','c':3},{'m':'fixture_low','c':2}]
        raw=json.dumps(f.document,ensure_ascii=False,indent=2).encode('utf8')
        packed=gzip.compress(raw)
        f.source.write_bytes(packed)
        folder=f.root/'clothes-cache'
        with patch('game_data.load_install',return_value=catalogue()):
            codec.prepare(f.source,folder)
        result=presets.clothing_stock(f.document['Items'],f.document['Items'],catalogue())
        with codec.connection(folder/'index.sqlite') as db:
            start,stop=db.execute("SELECT start,stop FROM containers WHERE path='/Items'").fetchone()
        expected=raw[:start]+json.dumps(result['items'],ensure_ascii=True).encode('ascii')+raw[stop:]
        output=f.root/'stock.sd'
        codec.export(folder,{'/Items':result['items']},output)
        self.assertEqual(gzip.decompress(output.read_bytes()),expected)
        self.assertEqual(f.source.read_bytes(),packed)
        self.assertEqual(json.loads(expected)['Charas'],f.document['Charas'])
