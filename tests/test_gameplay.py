"""Synthetic regression fixtures; contains no extracted game catalogues or saves."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import codec
import model
import schema

def catalog():
    item=lambda key,stack,addable:{'id':key,'name':key,'stack':stack,'addable':addable,
        'type':'Furniture','group':'Furniture','price':10,'sell':5,'description':'fixture',
        'map':{},'food':{}}
    return {'items':{'fixture_item':item('fixture_item',9,True),
                     'fixture_new':item('fixture_new',4,True),
                     'fixture_banned':item('fixture_banned',9,False)},
            'skills':{'fixture_skill':{'id':'fixture_skill','name':'fixture skill','type':'AddExp'},
                      'fixture_same_type':{'id':'fixture_same_type','name':'same family','type':'AddExp'},
                      'fixture_tip':{'id':'fixture_tip','name':'tip','type':'Tip'}},
            'levels':{'1':{'level':1,'next_exp':100,'maids':5,'guests':4},
                      '2':{'level':2,'next_exp':200,'maids':6,'guests':5}},
            'maid_limits':[1,3,4,5],'skill_slots':[1,2,3,4],
            'maid_exps':[50,60,70,80,90],'financing_max':3,'missions':{}}

class GameplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'source.sd'
        self.folder=self.root/'cache'
        self.document={'TotalCash':47,'HPoint':13,'ShopExp':3,'ShopLevel':1,
            'CoffeeShopName':'Fixture','Difficulty':0,'FinancingCount':3,'ShopStars':[3.5],
            'Charas':[{'IsPlayerChara':False,'Work':0,'Attr':{'MaxHp':100,'MoveSpeed':4.25,
                      'MaidLevel':2,'MaidLevelExp':2,'Rarity':1,'NowLike':10,
                      'SkillSDatas':[{'SkillMstID':'fixture_skill','Exp':0}]},
                      'Looks':{'DefName':'Fixture employee','CustomName':'','_charaIconByte':[1,2,3]},
                      'UnlockHPoses':{'u':[]}}],
            'Items':[{'m':'fixture_item','c':3}],
            'MenusSaveData':{'m':['fixture_menu'],'c':[4],'s':[10]},
            'MapObjs':[],'MapSaveData':{'Hall_UnlockedGridIndexs':[]},'MissionSaveData':{'ms':[]},
            'unknown':{'keep':'\\ " Unicode ☕','float':1.234e-5}}
        self.raw=json.dumps(self.document,ensure_ascii=False,indent=2).encode('utf8')+b'\r\n'
        self.original=gzip.compress(self.raw)
        self.source.write_bytes(self.original)
        with patch('game_data.load_install',return_value=catalog()):
            codec.prepare(self.source,self.folder)

    def export(self,changes):
        target=self.root/'output.sd'
        codec.export(self.folder,changes,target)
        return gzip.decompress(target.read_bytes())

    def test_scalar_edits_preserve_every_other_byte(self):
        edited=self.export({'/TotalCash':50,'/Charas/0/Attr/MaxHp':120,
                            '/Charas/0/Attr/MoveSpeed':5.5,'/MenusSaveData/c/0':8})
        expected=self.raw.replace(b'"TotalCash": 47',b'"TotalCash": 50').replace(
            b'"MaxHp": 100',b'"MaxHp": 120').replace(b'"MoveSpeed": 4.25',b'"MoveSpeed": 5.5').replace(
            b'"c": [\n      4\n    ]',b'"c": [\n      8\n    ]')
        self.assertEqual(edited,expected)
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_inventory_and_skill_additions(self):
        items=[{'m':'fixture_item','c':4},{'m':'fixture_new','c':2}]
        skills=[{'SkillMstID':'fixture_skill','Exp':0},{'SkillMstID':'fixture_tip','Exp':10}]
        raw=self.export({'/Items':items,'/Charas/0/Attr/SkillSDatas':skills})
        d=json.loads(raw)
        self.assertEqual(d['Items'],items)
        self.assertEqual(d['Charas'][0]['Attr']['SkillSDatas'],skills)
        self.assertEqual(d['unknown'],self.document['unknown'])
        self.assertEqual(d['Charas'][0]['Looks'],self.document['Charas'][0]['Looks'])

    def test_remove_last_item_and_all_skills(self):
        d=json.loads(self.export({'/Items':[],'/Charas/0/Attr/SkillSDatas':[]}))
        self.assertEqual(d['Items'],[])
        self.assertEqual(d['Charas'][0]['Attr']['SkillSDatas'],[])

    def test_final_shop_level_controls_exp_limit(self):
        d=json.loads(self.export({'/ShopLevel':2,'/ShopExp':150}))
        self.assertEqual((d['ShopLevel'],d['ShopExp']),(2,150))

    def test_unknown_ids_and_impossible_combinations_rejected(self):
        cases=[{'/Items':[{'m':'missing','c':1}]},
               {'/Items':[{'m':'fixture_new','c':5}]},
               {'/Items':[{'m':'fixture_banned','c':1}]},
               {'/Items':[{'m':'fixture_item','c':3},{'m':'fixture_item','c':1}]},
               {'/Charas/0/Attr/SkillSDatas':[{'SkillMstID':'missing','Exp':0}]},
               {'/Charas/0/Attr/SkillSDatas':[{'SkillMstID':k,'Exp':0} for k in ('fixture_skill','fixture_same_type')]},
               {'/Charas/0/Attr/Rarity':0},
               {'/Charas/0/Attr/MaidLevel':3},  # at max level, old exp 2 is invalid
               {'/Charas/0/Attr/MaidLevelExp':60},
               {'/ShopExp':100},
               {'/MenusSaveData/c/0':31},
               {'/Charas/0/Attr/MoveSpeed':float('nan')},
               {'/MissionSaveData/ms':[]},
               {'/Items':[],'/Items/0/c':1}]
        for changes in cases:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.export(changes)
            self.assertFalse((self.root/'output.sd').exists())
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_character_level_rarity_and_experience_batch(self):
        d=json.loads(self.export({'/Charas/0/Attr/Rarity':0,'/Charas/0/Attr/MaidLevel':1,
                                 '/Charas/0/Attr/MaidLevelExp':0}))
        self.assertEqual(d['Charas'][0]['Attr']['MaidLevelExp'],0)

    def test_original_unknown_inventory_entry_is_preserved(self):
        original=[{'m':'unknown_fixture','c':7,'unrecognized':True}]
        schema.inventory_valid(original,original,catalog())
        with self.assertRaises(ValueError):
            schema.inventory_valid([{'m':'unknown_fixture','c':8}],original,catalog())

    def test_views_and_icon_suppression(self):
        self.assertEqual(len(model.overview(self.folder)['staff']),1)
        employee=model.view(self.folder,'employee')
        self.assertTrue(any(f['path'].endswith('/MaxHp') and f['editable'] for f in employee['fields']))
        self.assertEqual(model.view(self.folder,'inventory')['count'],1)
        self.assertFalse(any('_charaIconByte' in r['path'] for r in codec.rows(self.folder)['rows']))
        self.assertEqual(codec.rows(self.folder,query='_charaIconByte')['count'],3)

    def test_index_tampering_rejected(self):
        with codec.connection(self.folder/'index.sqlite') as db:
            db.execute("UPDATE fields SET start=start+1 WHERE path='/TotalCash'")
        with self.assertRaises(ValueError):
            self.export({'/TotalCash':50})
