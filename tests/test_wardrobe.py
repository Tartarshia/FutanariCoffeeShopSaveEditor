"""Synthetic equipment slots, inventory transfers, and lossless array export."""
import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import codec
import wardrobe
from test_gameplay import catalog

class WardrobeTests(unittest.TestCase):
    def setUp(self):
        self.cat=catalog()
        for key,slots in [('top','STops'),('under','SInner_Top'),('set','STops,SBottoms,SInner_Top'),
                          ('arm','SArm_Right,SArm_Left'),('bottom','SBottoms')]:
            self.cat['items'][key]={'id':key,'name':key,'addable':True,'stack':4,'model':key,
                'clothes':{'Gender':'Female','OccupiedSlots':slots}}
        self.original=[{'ItemMstID':'top','Slots':[1]},{'ItemMstID':'under','Slots':[3]}]

    def test_replacement_returns_all_conflicting_garments_and_consumes_one(self):
        result=wardrobe.transition(self.original,[{'m':'set','c':2}],self.original,self.cat,
            'equip','set',[1,2,3])
        self.assertEqual(result['wearing'],[{'ItemMstID':'set','Slots':[1,2,3]}])
        self.assertEqual({v['m']:v['c'] for v in result['items']},{'set':1,'top':1,'under':1})
        self.assertEqual(self.original[0]['ItemMstID'],'top')

    def test_new_garment_and_unequip_return(self):
        result=wardrobe.transition([],[],[],self.cat,'equip','arm',[33],'new')
        self.assertEqual(result['items'],[])
        result=wardrobe.transition(result['wearing'],[],[],self.cat,'unequip','arm',[33])
        self.assertEqual(result,{'wearing':[],'items':[{'m':'arm','c':1}]})

    def test_missing_stock_or_return_overflow_leaves_inputs_unchanged(self):
        items=[{'m':'top','c':4}];prior=copy.deepcopy(items)
        for key,slots in [('set',[1,2,3]),('bottom',[2])]:
            with self.assertRaises(ValueError):
                wardrobe.transition(self.original,items,self.original,self.cat,'equip',key,slots)
        self.assertEqual(items,prior)
        self.assertEqual(len(self.original),2)

    def test_wrong_slots_overlap_and_unknown_ids_are_rejected(self):
        for values in [[{'ItemMstID':'arm','Slots':[32,33]}],
                       [{'ItemMstID':'top','Slots':[2]}],
                       [{'ItemMstID':'unknown','Slots':[1]}],
                       self.original+[{'ItemMstID':'top','Slots':[1]}]]:
            with self.assertRaises(ValueError):wardrobe.valid(values,self.original,self.cat)
        self.assertEqual(wardrobe.choices(self.cat['items']['arm']),[[32],[33]])

    def test_export_changes_only_wardrobe_and_inventory_arrays(self):
        self.cat['appearance']={'hair':[]}
        doc={'TotalCash':10,'Charas':[{'IsPlayerChara':False,'Attr':{'Rarity':1,'MaidLevel':2,'MaidLevelExp':0},
            'Looks':{'IsMaleChara':False,'CharaType':1,'PrefabName':'new_chara_body',
                     'WearingClothes':self.original}}], 'Items':[{'m':'set','c':1}],
             'unknown':'unaltered fixture', 'number':1.23456789012345}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'fixture.sd';folder=root/'cache'
            raw=json.dumps(doc,indent=2).encode();source.write_bytes(gzip.compress(raw));original=source.read_bytes()
            with patch('game_data.load_install',return_value=self.cat):codec.prepare(source,folder)
            result=wardrobe.transition(self.original,doc['Items'],self.original,self.cat,'equip','set',[1,2,3])
            changes={'/Charas/0/Looks/WearingClothes':result['wearing'],'/Items':result['items']}
            with codec.connection(folder/'index.sqlite') as db:
                patches=[(*db.execute('SELECT start,stop FROM containers WHERE path=?',(p,)).fetchone(),json.dumps(v).encode()) for p,v in changes.items()]
            expected=raw
            for start,stop,value in sorted(patches,reverse=True):expected=expected[:start]+value+expected[stop:]
            target=root/'edited.sd';codec.export(folder,changes,target)
            self.assertEqual(gzip.decompress(target.read_bytes()),expected)
            self.assertEqual(source.read_bytes(),original)
