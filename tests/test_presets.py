"""Synthetic route presets, rejection boundaries and byte-preserving exports."""
import gzip
import json
from unittest.mock import patch
import unittest
import codec
import presets
import schema
import test_gameplay


def fixture_catalog():
    cat = test_gameplay.catalog()
    cat['skills'] = {}
    effects = [('FoodQuality', 'FoodQualityUp'), ('CookingSpeed', 'ReduceCookingTime'),
               ('AddCharm', 'AddCharaCharmRate'), ('AddHPoint', 'AddHPointGetRate')]
    for family, effect in effects:
        for level in (1, 2):
            key = f'fixture_{family}_{level}'
            cat['skills'][key] = {'id': key, 'type': family, 'rarities': ['SSR'],
                'buffs': [{'type': effect, 'value': level * 10, 'value2': level}]}
    for i, values in enumerate(((6, 10, 10), (6, 10, 0), (6, 0, 10), (0, 10, 10), (1, 0, 0))):
        key = f'fixture_tip_{i}'
        cat['skills'][key] = {'id': key, 'type': 'Tip', 'rarities': ['SSR'],
            'buffs': [{'type': e, 'value': v, 'value2': 0} for e, v in
                      zip(('TipCheckout', 'TipOrdering', 'TipDelivery'), values) if v]}
    return cat


class PresetTests(unittest.TestCase):
    def setUp(self):
        f = test_gameplay.GameplayTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.fixture = f
        attr = f.document['Charas'][0]['Attr']
        for k, (typ, lo, hi) in schema.ATTRS.items():
            attr.setdefault(k, int(lo) if typ == 'integer' else lo)
        attr['SkillSDatas'] = []
        attr['Rarity'] = 3
        f.document['Charas'].append({'IsPlayerChara': True, 'Attr': dict(attr), 'Work': 0})
        self.raw = json.dumps(f.document, ensure_ascii=False, indent=2).encode('utf8') + b'\r\n'
        f.source.write_bytes(gzip.compress(self.raw))
        self.source_bytes = f.source.read_bytes()
        f.folder = f.root / 'preset-cache'
        with patch('game_data.load_install', return_value=fixture_catalog()):
            codec.prepare(f.source, f.folder)

    def test_routes_export_and_preserve_all_base_attributes(self):
        f = self.fixture
        for route in ('kitchen', 'hall'):
            result = presets.plan(f.folder, 0, 'skills', route=route)
            expected = self.raw
            replacements = []
            with codec.connection(f.folder / 'index.sqlite') as db:
                for p, v in result['changes'].items():
                    row = db.execute('SELECT start,stop FROM fields WHERE path=?', (p,)).fetchone()
                    if not row:
                        row = db.execute('SELECT start,stop FROM containers WHERE path=?', (p,)).fetchone()
                    replacements.append((*row, json.dumps(v, ensure_ascii=True, allow_nan=False).encode('ascii')))
            for start, stop, v in sorted(replacements, reverse=True):
                expected = expected[:start] + v + expected[stop:]
            out = f.root / (route + '.sd')
            codec.export(f.folder, result['changes'], out)
            self.assertEqual(gzip.decompress(out.read_bytes()), expected)
            a = json.loads(expected)['Charas'][0]['Attr']
            self.assertEqual((a['Rarity'], a['MaidLevel'], a['MaidLevelExp']), (3, 2, 2))
            for key in schema.ATTRS:
                self.assertEqual(a[key], f.document['Charas'][0]['Attr'][key], key)
            self.assertEqual(set(result['changes']), {'/Charas/0/Attr/SkillSDatas'})
            ids = [s['SkillMstID'] for s in a['SkillSDatas']]
            if route == 'kitchen':
                self.assertEqual(ids[0], 'fixture_FoodQuality_2')
                self.assertEqual(ids[1], 'fixture_CookingSpeed_2')
                self.assertNotIn('/Charas/0/Attr/OrderingTime', result['changes'])
            else:
                self.assertEqual(set(ids), {f'fixture_tip_{i}' for i in range(4)})
                self.assertNotIn('/Charas/0/Attr/CookingTime', result['changes'])
            self.assertEqual(len(ids), 4)
        self.assertEqual(f.source.read_bytes(), self.source_bytes)

    def test_only_level_and_old_extreme_modes_rejected(self):
        f = self.fixture.folder
        for mode in ('extreme','practical','efficient','like','optimize','level'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                presets.plan(f, 0, mode)

    def test_skills_only_preserves_ssr_level_experience_and_attributes(self):
        f = self.fixture
        attr = f.document['Charas'][0]['Attr']
        attr.update(Rarity=3, CharaCharm=123, MaidLevel=2, MaidLevelExp=7)
        raw = json.dumps(f.document, ensure_ascii=False, indent=2).encode('utf8')
        f.source.write_bytes(gzip.compress(raw))
        folder = f.root / 'ssr-cache'
        with patch('game_data.load_install', return_value=fixture_catalog()):
            codec.prepare(f.source, folder)
        result = presets.plan(folder, 0, 'skills', route='hall')
        self.assertEqual(set(result['changes']), {'/Charas/0/Attr/SkillSDatas'})
        out = f.root / 'skills-only.sd'
        codec.export(folder, result['changes'], out)
        edited = json.loads(gzip.decompress(out.read_bytes()))['Charas'][0]['Attr']
        for key, val in attr.items():
            if key != 'SkillSDatas':
                self.assertEqual(edited[key], val, key)

    def test_current_rarity_slots_do_not_change_rarity_or_level(self):
        f = self.fixture
        for rarity in range(4):
            for route in ('kitchen','hall'):
                attr = f.document['Charas'][0]['Attr']
                attr.update(Rarity=rarity, MaidLevel=1, MaidLevelExp=0)
                f.source.write_bytes(gzip.compress(json.dumps(f.document).encode('utf8')))
                folder = f.root / f'rarity-{rarity}-{route}'
                with patch('game_data.load_install', return_value=fixture_catalog()):
                    codec.prepare(f.source, folder)
                result = presets.plan(folder, 0, 'skills', route=route)
                self.assertEqual(set(result['changes']), {'/Charas/0/Attr/SkillSDatas'})
                skills = result['changes']['/Charas/0/Attr/SkillSDatas']
                self.assertEqual(len(skills), fixture_catalog()['skill_slots'][rarity])
                schema.skills_valid(skills, rarity, fixture_catalog())
                if route == 'kitchen':
                    self.assertEqual(skills[0]['SkillMstID'], 'fixture_FoodQuality_2')

    def test_invalid_targets_and_missing_verified_skills_fail_closed(self):
        for idx, mode, route in ((1, 'skills', 'hall'), (99, 'skills', 'hall'),
                                  (True, 'skills', 'hall'), (0, 'unknown', 'hall'), (0, 'skills', 'bad')):
            with self.subTest(idx=idx, mode=mode, route=route), self.assertRaises(ValueError):
                presets.plan(self.fixture.folder, idx, mode, route=route)
        cat = fixture_catalog()
        del cat['skills']['fixture_FoodQuality_2']
        del cat['skills']['fixture_FoodQuality_1']
        with self.assertRaises(ValueError):
            presets.best_skills(cat, 'kitchen')
