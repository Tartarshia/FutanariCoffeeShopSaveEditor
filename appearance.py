"""Verified appearance scalars for the game's ordinary female maid model."""
import json
import re
import struct

COLOR_GROUPS = {
 '主发色': {'HairMainColor':'主色','HairOutlineColor':'轮廓','HairShadowColor':'阴影',
           'HairRimLightColor':'边缘光','HairHighlightColor':'高光'},
 '第二发色': {'Hair2_MainColor':'主色','Hair2_OutlineColor':'轮廓','Hair2_ShadowColor':'阴影',
             'Hair2_RimLightColor':'边缘光','Hair2_HighlightColor':'高光'},
 '肤色': {'SkinColor':'主色','SkinShadowColor':'阴影','SkinRimLightColor':'边缘光',
         'NippleColor':'局部主色','NippleShadowColor':'局部阴影'},
 '眼睛与眉睫': {'Eye':'虹膜','EyeBg':'眼白','Eyebrow':'眉毛','Eyelash':'睫毛'},
 '妆容': {'LipsColor':'唇色','LipsShadowColor':'唇色阴影',
         'Eyeshadow1Color':'第一层眼影','Eyeshadow2Color':'第二层眼影'},
 '指甲': {'NailColor':'主色','NailShadowColor':'阴影'},
 '纹身': {'Tattoo1Color':'第一层颜色','Tattoo2Color':'第二层颜色'}}
COLORS = {key:group+' · '+label for group,entries in COLOR_GROUPS.items() for key,label in entries.items()}
SELECTORS = {'HairModel':('发型','hair'), 'EarType':('耳型','EarType'),
 'EyeTex':('虹膜样式','EyeType'), 'EyeHighLightTex':('眼睛高光','EyeHighType'),
 'Tattoo1Tex':('第一层纹身','TattooType'), 'Tattoo2Tex':('第二层纹身','TattooType')}

def scalar(db, path, default=None):
    row=db.execute('SELECT value FROM fields WHERE path=?',(path,)).fetchone()
    return json.loads(row[0]) if row else default

def supported(db,idx,cat):
    prefix=f'/Charas/{idx}'
    return bool(cat.get('appearance') and
        scalar(db,prefix+'/IsPlayerChara') is False and
        scalar(db,prefix+'/Looks/IsMaleChara') is False and
        scalar(db,prefix+'/Looks/CharaType') == 1 and
        scalar(db,prefix+'/Looks/PrefabName') == 'new_chara_body')

def label(path):
    key=path.rsplit('/',1)[-1]
    if key=='BreastSize':return '胸部尺寸 / 0–100'
    if key in SELECTORS:return SELECTORS[key][0]
    if key in ('r','g','b','a'):
        return COLORS.get(path.rsplit('/',2)[-2],path)+' · '+key.upper()
    return path

def describe(path,db,cat):
    m=re.fullmatch(r'/Charas/(\d+)/Looks/Colors/(\w+)(?:/([rgba]))?',path)
    if not m or not supported(db,m[1],cat):return None
    key,component=m[2],m[3]
    help='载入存档后应用外观；原存档头像是缓存，不随离线编辑自动重绘。'
    if key=='BreastSize' and component is None:
        return {'type':'integer','min':0,'max':100,'choices':None,
                'help':help+' 这是模型变形权重，不是罩杯或厘米；服装也会影响显示。'}
    if key in COLORS and component:
        return {'type':'number','min':0,'max':1,'choices':None,
                'help':help+' RGBA 通道范围 0–1；颜色控件只修改实际操作的通道。'}
    if key in SELECTORS and component is None:
        catalogue=cat['appearance'][SELECTORS[key][1]]
        return {'type':'choice','min':None,'max':None,'help':help,
                'choices':[{'value':v['id'],'label':v['name']+' · '+v['id']} for v in catalogue]}
    return None

def portrait(db,idx):
    """Decode one bounded cached PNG; never materialize icon JSON or whole save."""
    path=f'/Charas/{idx}/Looks/_charaIconByte'
    row=db.execute('SELECT kind,count FROM containers WHERE path=?',(path,)).fetchone()
    if not row or row[0]!='array' or not 0<row[1]<=524288:
        raise ValueError('此角色没有受支持的缓存头像')
    image=bytearray()
    for p,kind,v in db.execute('SELECT path,kind,value FROM fields WHERE path>=? AND path<? '
            'ORDER BY start LIMIT 524289',(path+'/',path+'/\uffff')):
        index=p[len(path)+1:]
        value=json.loads(v)
        if index!=str(len(image)) or kind!='number' or type(value) is not int or not 0<=value<=255:
            raise ValueError('缓存头像字节无效')
        image.append(value)
    if len(image)!=row[1] or len(image)<33 or image[:8]!=b'\x89PNG\r\n\x1a\n' or image[12:16]!=b'IHDR':
        raise ValueError('缓存头像不是受支持的 PNG')
    width,height=struct.unpack('>II',image[16:24])
    if not 0<width<=2048 or not 0<height<=2048:
        raise ValueError('缓存头像尺寸超出限制')
    return bytes(image)
