"""Synthetic appearance/export and vertex/texture fixtures; no game resources."""
import copy
import gzip
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import appearance
import codec
import model
import unity_assets
import unity_preview as unity
from test_gameplay import catalog

class AppearanceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.source=self.root/'source.sd';self.folder=self.root/'save'
        colors={key:{'r':0.123456789,'g':0.5,'b':0.8,'a':1.0} for key in appearance.COLORS}
        colors.update({key:'fixture_'+kind for key,(_,kind) in appearance.SELECTORS.items()})
        colors['BreastSize']=23
        maid={'IsPlayerChara':False,'Work':0,'Attr':{'Rarity':1,'MaidLevel':2,'MaidLevelExp':2},
              'Looks':{'IsMaleChara':False,'CharaType':1,'PrefabName':'new_chara_body',
                       'Colors':colors,'CustomName':'Fixture','DefName':'Fixture',
                       '_charaIconByte':list(unity.png(1,1,b'\xff\xff\xff\xff')),'WearingClothes':[]}}
        player=copy.deepcopy(maid);player['IsPlayerChara']=True;player['Looks']['CharaType']=0
        self.raw=json.dumps({'TotalCash':10,'ShopLevel':1,'ShopExp':0,'Charas':[maid,player],
                             'Unknown':{'keep':1.1234567890123456}},indent=2).encode()
        self.source.write_bytes(gzip.compress(self.raw));self.original=self.source.read_bytes()
        self.cat=catalog();self.cat['appearance']={}
        for _,kind in appearance.SELECTORS.values():
            self.cat['appearance'][kind]=[{'id':'fixture_'+kind,'name':'fixture'},
                                         {'id':'fixture_other_'+kind,'name':'other fixture'}]
        with patch('game_data.load_install',return_value=self.cat):codec.prepare(self.source,self.folder)

    def test_scalars_preserve_every_other_original_byte(self):
        changes={'/Charas/0/Looks/Colors/BreastSize':80,
                 '/Charas/0/Looks/Colors/HairModel':'fixture_other_hair',
                 '/Charas/0/Looks/Colors/SkinColor/r':0.9}
        with codec.connection(self.folder/'index.sqlite') as db:
            patches=[]
            for p,v in changes.items():
                start,stop=db.execute('SELECT start,stop FROM fields WHERE path=?',(p,)).fetchone()
                patches.append((start,stop,json.dumps(v).encode()))
        expected=self.raw
        for start,stop,raw in sorted(patches,reverse=True):expected=expected[:start]+raw+expected[stop:]
        out=self.root/'edited.sd';codec.export(self.folder,changes,out)
        self.assertEqual(gzip.decompress(out.read_bytes()),expected)
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_invalid_shapes_ids_rgba_and_roles_rejected(self):
        paths={'/Charas/0/Looks/Colors/BreastSize':[-1,101,12.5,True],
               '/Charas/0/Looks/Colors/EyeTex':['unknown','fixture_EarType'],
               '/Charas/0/Looks/Colors/SkinColor/a':[-0.1,1.1,float('nan')],
               '/Charas/1/Looks/Colors/BreastSize':[50],
               '/Charas/0/Looks/PrefabName':['other'],
               '/Charas/0/Looks/_charaIconByte': [[]]}
        for path,values in paths.items():
            for value in values:
                with self.subTest(path=path,value=value),self.assertRaises(ValueError):
                    codec.export(self.folder,{path:value},self.root/'invalid.sd')
        self.assertFalse((self.root/'invalid.sd').exists())

    def test_appearance_view_and_bounded_png(self):
        result=model.view(self.folder,'appearance',0)
        self.assertTrue(result['supported'])
        self.assertFalse(model.view(self.folder,'appearance',1)['supported'])
        self.assertTrue(any(f['label']=='胸部尺寸 / 0–100' for f in result['fields']))
        with codec.connection(self.folder/'index.sqlite') as db:
            self.assertEqual(appearance.portrait(db,0),unity.png(1,1,b'\xff\xff\xff\xff'))
            db.execute("UPDATE containers SET count=524289 WHERE path='/Charas/0/Looks/_charaIconByte'")
            with self.assertRaises(ValueError):appearance.portrait(db,0)

    def test_unsupported_context_stays_readonly(self):
        for field,value in [('IsMaleChara',True),('CharaType',2),('PrefabName','other')]:
            with codec.connection(self.folder/'index.sqlite') as db:
                db.execute('UPDATE fields SET value=? WHERE path=?',(json.dumps(value),'/Charas/0/Looks/'+field))
                self.assertIsNone(appearance.describe('/Charas/0/Looks/Colors/BreastSize',db,self.cat))
                db.rollback()

class PreviewGeometryTests(unittest.TestCase):
    def test_sclera_uses_single_bone_binding_instead_of_renderer_transform(self):
        attrs=[(0,0,0,3)]+[(0,0,0,0)]*12+[(0,12,10,1)]
        m={'vertices':3,'channels':attrs,
            'data':b''.join(struct.pack('<3fI',*v) for v in [(0,0,0,0),(1,0,0,0),(0,1,0,0)]),
            'index_format':0,'indices':struct.pack('<3H',0,1,2),
            'submeshes':[{'first':0,'count':3,'base':0}],'shapes':[],
            'bindposes':[unity.identity()]}
        bone=unity.identity();bone[3]=2;bone[7]=3
        wrong=unity.identity();wrong[3]=100
        payload=unity.mesh_payload(m,wrong,[bone]);size=struct.unpack_from('<I',payload)[0]
        meta=json.loads(payload[4:4+size]);field=meta['fields']['positions']
        self.assertEqual(struct.unpack_from('<9f',payload,4+size+field['offset']),
            (2,3,0,3,3,0,2,4,0))
        with self.assertRaises(ValueError):unity.mesh_payload(m,wrong,[None])

    def test_second_uv_set_is_preserved_for_lip_mask(self):
        attrs=[(0,0,0,3)]+[(0,0,0,0)]*3+[(0,12,0,2),(0,20,0,2)]
        raw=b''.join(struct.pack('<7f',*v) for v in
            [(0,0,0,0,0,.2,.3),(1,0,0,1,0,.4,.5),(0,1,0,0,1,.6,.7)])
        m={'vertices':3,'channels':attrs,'data':raw,'index_format':0,
            'indices':struct.pack('<3H',0,1,2),'submeshes':[{'first':0,'count':3,'base':0}],
            'shapes':[]}
        payload=unity.mesh_payload(m,unity.identity());size=struct.unpack_from('<I',payload)[0]
        meta=json.loads(payload[4:4+size]);field=meta['fields']['uv1']
        values=struct.unpack_from('<6f',payload,4+size+field['offset'])
        for actual,expected in zip(values,(.2,.3,.4,.5,.6,.7)):
            self.assertAlmostEqual(actual,expected)

    def test_real_morph_layout_with_synthetic_triangle(self):
        attrs=[(0,0,0,3)]+[(0,0,0,0)]*3+[(0,12,0,2)]
        raw=b''.join(struct.pack('<5f',*v) for v in [(0,0,0,0,0),(1,0,0,1,0),(0,1,0,0,1)])
        shape=struct.pack('<9fI',0,0,0.25,0,0,0,0,0,0,1)
        m={'vertices':3,'channels':attrs,'data':raw,'index_format':0,
            'indices':struct.pack('<3H',0,1,2),'submeshes':[{'first':0,'count':3,'base':0}],
            'shapes':[('breasts_size',0,1)],'frames':[(0,1)],'weights':[100],'shape_bytes':shape}
        payload=unity.mesh_payload(m,unity.identity());size=struct.unpack_from('<I',payload)[0]
        meta=json.loads(payload[4:4+size]);field=meta['fields']['shape_breasts_size']
        values=struct.unpack_from('<9f',payload,4+size+field['offset'])
        self.assertEqual(values[5],0.25)
        self.assertEqual(meta['shapes']['breasts_size']['weight'],100)
        self.assertEqual(meta['submeshes'][0]['count'],3)
        m['shapes']=[('clothes_breasts_size',0,1)]
        payload=unity.mesh_payload(m,unity.identity());size=struct.unpack_from('<I',payload)[0]
        self.assertIn('clothes_breasts_size',json.loads(payload[4:4+size])['shapes'])
        m['frames']=[(0,2)]
        with self.assertRaises(ValueError):unity.mesh_payload(m,unity.identity())

    def test_texture_formats_alpha_and_bounds(self):
        # A BC1 red block, and a BC3 red block with uniform half opacity.
        bc1=struct.pack('<HHI',0xf800,0,0)
        pixels=unity.decode_texture(4,4,10,bc1)
        self.assertEqual(pixels,bytes([255,0,0,255])*16)
        bc3=bytes([128,0])+bytes(6)+bc1
        self.assertEqual(unity.decode_texture(4,4,12,bc3),bytes([255,0,0,128])*16)
        self.assertEqual(unity.decode_texture(1,1,3,b'\x11\x22\x33'),b'\x11\x22\x33\xff')
        for fmt,data in [(10,b''),(12,bc1),(3,b''),(999,b'')]:
            with self.assertRaises(ValueError):unity.decode_texture(4,4,fmt,data)

    def test_stream_paths_cannot_escape_install(self):
        with tempfile.TemporaryDirectory() as temp:
            assets=object.__new__(unity.Assets);assets.path=Path(temp)/'resources.assets'
            with self.assertRaises(ValueError):
                assets.texture_data({'inline':b'','path':'../outside.resS','size':1,'offset':0})

    def test_truncated_selected_asset_fails(self):
        r=unity_assets.Reader(io.BytesIO(b'\xff'*8),8)
        with self.assertRaises(ValueError):unity.mesh(r)
