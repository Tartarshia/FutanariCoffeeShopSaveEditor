"""Synthetic SSR growth; boss-only scope and byte-preserving writes."""
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
    cat['maid_limits']=[5,7,9,15]
    cat['maid_exps']=[100]*15
    m={'_Rarity_N_Rate':[1,1],'_Rarity_SSR_Rate':[2,2],
       '_Rarity_SSR_MoveSpeed':[2,2],'_Rarity_SSR_GetRate':[2,2],
       '_maxHp':20,'_hpRecovery':2,'_moveSpeed':4,'_charaCharm':10}
    for field in ('cookingTime','orderingTime','checkoutTime','cleaningUpTime',
                  'cookingCostHp','orderingCostHp','checkoutCostHp','cleaningUpCostHp'):
        m['_'+field]=12
    for group in ('Hp','HpRecovery','MoveSpeed','Data','WorkHp'):
        m['_min'+group+'ChangeRate']=1.5
        m['_max'+group+'ChangeRate']=2
    cat['maid_settings']=m
    return cat


class BossReferenceTests(unittest.TestCase):
    def test_growth_uses_fourteen_steps_and_real_growth_baseline(self):
        values=presets.boss_reference(catalogue())
        self.assertEqual(values['MaxHp'],68)
        self.assertEqual(values['CharaCharm'],34)
        self.assertAlmostEqual(values['MoveSpeed'],14.3,places=3)
        self.assertAlmostEqual(values['HpRecovery'],7.15,places=3)
        self.assertAlmostEqual(values['ExpGetRate'],4.1,places=3)
        self.assertEqual(len(values),14)
        cat=catalogue()
        cat['maid_settings']['_cookingTime']=0.2
        self.assertEqual(presets.boss_reference(cat)['CookingTime'],1)
        cat['maid_limits'][3]=14
        with self.assertRaises(ValueError):
            presets.boss_reference(cat)

    def test_unique_player_only_preserves_level_skills_employees_and_other_bytes(self):
        f=test_gameplay.GameplayTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        attr=deepcopy(f.document['Charas'][0]['Attr'])
        for key in presets.boss_reference(catalogue()):
            attr.setdefault(key,5)
        attr.update(MaidLevel=1,MaidLevelExp=0,CharaCharm=99)
        f.document['Charas'].append({'IsPlayerChara':True,'Work':0,'Attr':attr,
                                    'Looks':{'DefName':'Fixture boss','CustomName':''}})
        raw=json.dumps(f.document,ensure_ascii=False,indent=2).encode('utf8')
        packed=gzip.compress(raw)
        f.source.write_bytes(packed)
        folder=f.root/'boss-cache'
        with patch('game_data.load_install',return_value=catalogue()):
            codec.prepare(f.source,folder)
        result=presets.boss_plan(folder)
        self.assertEqual(result['id'],1)  # Never assume the boss is Charas/0.
        self.assertEqual(set(result['changes']),{f'/Charas/1/Attr/{key}' for key in presets.boss_reference(catalogue())})
        expected=raw
        with codec.connection(folder/'index.sqlite') as db:
            spans=[(*db.execute('SELECT start,stop FROM fields WHERE path=?',(p,)).fetchone(),
                    json.dumps(v).encode('ascii')) for p,v in result['changes'].items()]
        for start,stop,v in sorted(spans,reverse=True):
            expected=expected[:start]+v+expected[stop:]
        output=f.root/'boss.sd'
        codec.export(folder,result['changes'],output)
        self.assertEqual(gzip.decompress(output.read_bytes()),expected)
        edited=json.loads(expected)
        self.assertEqual(edited['Charas'][0],f.document['Charas'][0])
        for key in ('Rarity','MaidLevel','MaidLevelExp','SkillSDatas'):
            self.assertEqual(edited['Charas'][1]['Attr'][key],attr[key])
        self.assertEqual(f.source.read_bytes(),packed)
        with codec.connection(folder/'index.sqlite') as db:
            db.execute("UPDATE fields SET value='true' WHERE path='/Charas/0/IsPlayerChara'")
        with self.assertRaisesRegex(ValueError,'唯一的老板'):
            presets.boss_plan(folder)
