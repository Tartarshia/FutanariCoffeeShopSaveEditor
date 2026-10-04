"""Import catalogues and settings from the user's local game, never bundled data."""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import unity_assets

SUPPORTED_ASSEMBLY = '3c49bb55acd33b52aabb6eeaaccecfed9ca180f139e2af749949a8a49fd95acf'
TABLES = {'CSItemMst', 'CSSkillMst', 'CSShopLevelMst', 'CSBuffMst',
          'CSFoodMst', 'CSMapObjMst', 'CSMissionMst', 'CSLan_SCN'}

def fingerprint(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

def installations():
    roots = [Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Steam']
    for root in list(roots):
        vdf = root / 'steamapps/libraryfolders.vdf'
        if vdf.exists():
            roots.extend(Path(p.replace('\\\\', '\\')) for p in re.findall(
                r'"path"\s+"([^"]+)"', vdf.read_text(encoding='utf-8')))
    return list(dict.fromkeys(p for root in roots
        if (p := root / 'steamapps/common/Futanari_CoffeeShop').is_dir()))

def find_install(source, explicit=None):
    candidates = [Path(explicit)] if explicit else [Path(source).parent.parent, *installations()]
    for p in candidates:
        if (p / 'cs_Data/resources.assets').is_file():
            return p
    raise ValueError('未找到本机游戏目录；请填写包含 cs.exe 的文件夹')

def split_rows(lines):
    header = [x.strip() for x in lines[0].split('| ~ |') if x.strip()]
    result = {}
    for line in lines[1:]:
        cols = [x.strip() for x in line.split('| ~ |')]
        if not cols[0] or cols[0] in ('-', '.', 'null') or cols[0].startswith('.'):
            continue
        if len(cols) < len(header):
            raise ValueError('Master table has truncated row')
        if cols[0] in result:
            raise ValueError('Duplicate master ID: ' + cols[0])
        result[cols[0]] = dict(zip(header, cols))
    return result

def params(text):
    if not text or text in ('-', '--'):
        return {}
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('Master parameters must be an object')
    return value

def boolean(text):
    return str(text).strip().lower() == 'true'

def strings(text):
    return [v.strip() for v in text.replace('\\n', '').split(',') if v.strip()]

def script_ids(path):
    result = {}
    with open(path, 'rb') as f:
        for pid, cid, start, size in unity_assets.objects(path):
            if cid != 115:
                continue
            f.seek(start)
            r = unity_assets.Reader(f, start + size)
            name = r.string(512)
            r.read(20)  # execution order and properties hash
            cls = r.string(512)
            namespace = r.string(512)
            assembly = r.string(512)
            if namespace == 'CoffeeShop' and assembly == 'Assembly-CSharp':
                result[pid] = cls
    return result

def read_layout(r, layout):
    result = {}
    formats = {'int': 'i', 'float': 'f', 'Vector2': 'ff', 'Vector2Int': 'ii',
               'Vector3': 'fff', 'Color': 'ffff', 'CSMapObjGroup': 'i',
               'MaidRecruitRate': 'iiii', 'PublicizeAdData': 'iiiii',
               'CSMaidUpdateData': 'ii' + 'f' * 26}
    for typ, key in layout:
        if typ == 'bool':
            v = r.unpack('?')[0]
            r.align()
        elif typ in ('List<int>', 'List<string>'):
            n, = r.unpack('i')
            if not 0 <= n <= 2000:
                raise ValueError('Invalid settings array size')
            v = [r.string(512) for _ in range(n)] if typ == 'List<string>' else list(r.unpack('i' * n))
        elif typ == 'CSMaidLvUpExp':
            first, rate, n = r.unpack('ifi')
            if not 0 <= n <= 1000:
                raise ValueError('Invalid experience settings')
            v = {'first': first, 'rate': rate, 'exps': list(r.unpack('i' * n))}
        else:
            vals = r.unpack(formats[typ])
            v = vals[0] if len(vals) == 1 else list(vals)
        result[key] = v
    return result

def read_settings(data):
    scripts = script_ids(data / 'globalgamemanagers.assets')
    result = {}
    # The active scene settings and the prefab settings must agree.
    for af in ('level0', 'resources.assets'):
        with open(data / af, 'rb') as f:
            for pid, cid, start, size in unity_assets.objects(data / af):
                if cid != 114 or size < 36:
                    continue
                f.seek(start + 16)
                file_id, script = struct.unpack('<iq', f.read(12))
                name = scripts.get(script) if file_id == 1 else None
                if name not in ('CSMaidSettings', 'CSSettings'):
                    continue
                r = unity_assets.Reader(f, start + size)
                r.string(200)
                value = read_layout(r, MAID_LAYOUT if name == 'CSMaidSettings' else SHOP_LAYOUT)
                if f.tell() != start + size:
                    raise ValueError('Settings layout changed: ' + name)
                if name in result and result[name] != value:
                    raise ValueError('Scene and prefab settings disagree: ' + name)
                result[name] = value
    if len(result) != 2:
        raise ValueError('Missing gameplay settings')
    return result

def load_install(source, explicit=None):
    game = find_install(source, explicit)
    data = game / 'cs_Data'
    assembly = fingerprint(data / 'Managed/Assembly-CSharp.dll')
    if assembly != SUPPORTED_ASSEMBLY:
        raise ValueError('游戏代码版本已变化；需重新核对属性、技能和物品规则后才能编辑扩展字段')
    tables, versions = {}, {}
    for name, updated, lines in unity_assets.table_rows(data / 'resources.assets', TABLES):
        tables[name] = split_rows(lines)
        versions[name] = updated
    if set(tables) != TABLES:
        raise ValueError('Missing local master tables')
    lan = tables['CSLan_SCN']
    def text(key, column='Txt'):
        return lan.get(key, {}).get(column) or key
    items = {}
    for key, row in tables['CSItemMst'].items():
        p = params(row['Params'])
        mo = tables['CSMapObjMst'].get(row['MapObjMstID'], {})
        mp = params(mo.get('Params', ''))
        # CSInventory accepts usable items; sub-objects are parts of placed furniture.
        forbidden = (boolean(row['IsBanned']) or boolean(p.get('is_unlimited'))
                     or boolean(p.get('is_no_get')) or boolean(p.get('not_implemented'))
                     or 'test' in key.lower() or boolean(mp.get('is_sub_obj')))
        food = tables['CSFoodMst'].get(row['FoodMstID'], {})
        items[key] = {'id': key, 'name': text(key), 'description': text(key, 'Txt2'),
            'type': row['ItemType'], 'group': row['ItemGroup'], 'stack': int(row['StackLimit'] or 0),
            'price': int(row['BasePrice'] or 0), 'sell': int(row['SellPrice'] or 0),
            'params': p, 'food': food, 'map': mo, 'map_params': mp,
            'addable': not forbidden and row['ItemType'] in ('UseItem', 'Gifts', 'Furniture', 'Clothes', 'CookingBook')}
    buffs = {}
    for key,row in tables['CSBuffMst'].items():
        v,v2=float(row['Value'] or 0),float(row['Value2'] or 0)
        desc=text(key,'Txt2').replace('{0}',format(v,'g')).replace('{1}',format(v2,'g'))
        buffs[key]={'type':row['BuffType'],'value':v,'value2':v2,'description':desc}
    skills = {key: {'id': key, 'name': text(key), 'description': text(key, 'Txt2'),
        'type': row['SkillType'], 'tag': row['SkillTypeTag'], 'rarities': strings(row['HiringRaritys']),
        'buffs': [buffs[b] for b in strings(row['BuffID'])]}
        for key, row in tables['CSSkillMst'].items()}
    levels = {key: {'level': int(key), 'next_exp': int(row['NextExp']),
                   'guests': int(row['BaseGuest']), 'maids': int(row['MaidLimit'])}
              for key, row in tables['CSShopLevelMst'].items()}
    settings = read_settings(data)
    maids, shop = settings['CSMaidSettings'], settings['CSSettings']
    limits = [maids['_Rarity_' + n + '_LvLimit'] for n in ('N','R','SR','SSR')]
    slots = [maids['_Rarity_' + n + '_SkillCount'][1] for n in ('N','R','SR','SSR')]
    exp_settings = maids['_maidLvUpExp']
    exps = [exp_settings['first']]
    f32 = lambda x: struct.unpack('<f', struct.pack('<f', x))[0]
    for _ in range(max(limits) - 1):
        exps.append(round(f32(f32(exps[-1]) * exp_settings['rate'])))
    return {'assembly': assembly, 'versions': versions, 'items': items, 'skills': skills,
            'levels': levels, 'maid_limits': limits, 'skill_slots': slots, 'maid_exps': exps,
            'financing_max': shop['_financingMaxCount'], 'shop_settings': shop,
            'maid_settings': maids, 'missions': tables['CSMissionMst']}

# Field order verified against this supported local assembly and asset layout.
MAID_LAYOUT = [
    ('bool', 'IsLocked'),
    ('float', '_followPlayerKeepTime'),
    ('Vector2', '_randomMoveRestTime'),
    ('Vector2', '_randomMoveRestTime_MaidRoom'),
    ('float', '_maidRoomUseDeviceRate'),
    ('int', '_maxHp'),
    ('int', '_maidLevelMax'),
    ('int', '_charaCharm'),
    ('float', '_tiredHpPrec'),
    ('float', '_healthHpPrec'),
    ('float', '_hpRecovery'),
    ('float', '_cookingTime'),
    ('float', '_orderingTime'),
    ('float', '_checkoutTime'),
    ('float', '_cleaningUpTime'),
    ('float', '_useMaidDeviceRate'),
    ('float', '_cookingCostHp'),
    ('float', '_orderingCostHp'),
    ('float', '_checkoutCostHp'),
    ('float', '_cleaningUpCostHp'),
    ('float', '_moveSpeed'),
    ('float', '_moveAniSpeed'),
    ('List<string>', '_allFaceTexName'),
    ('Vector2', '_Rarity_N_Rate'),
    ('Vector2', '_Rarity_R_Rate'),
    ('Vector2', '_Rarity_SR_Rate'),
    ('Vector2', '_Rarity_SSR_Rate'),
    ('Vector2Int', '_Rarity_N_SkillCount'),
    ('Vector2Int', '_Rarity_R_SkillCount'),
    ('Vector2Int', '_Rarity_SR_SkillCount'),
    ('Vector2Int', '_Rarity_SSR_SkillCount'),
    ('Vector2', '_Rarity_N_GetRate'),
    ('Vector2', '_Rarity_R_GetRate'),
    ('Vector2', '_Rarity_SR_GetRate'),
    ('Vector2', '_Rarity_SSR_GetRate'),
    ('int', '_Rarity_N_BasicSalary'),
    ('int', '_Rarity_R_BasicSalary'),
    ('int', '_Rarity_SR_BasicSalary'),
    ('int', '_Rarity_SSR_BasicSalary'),
    ('Vector2', '_Rarity_N_MoveSpeed'),
    ('Vector2', '_Rarity_R_MoveSpeed'),
    ('Vector2', '_Rarity_SR_MoveSpeed'),
    ('Vector2', '_Rarity_SSR_MoveSpeed'),
    ('Vector2Int', 'adBreastSize_Small'),
    ('Vector2Int', 'adBreastSize_Medium'),
    ('Vector2Int', 'adBreastSize_Large'),
    ('int', '_Rarity_N_LvLimit'),
    ('int', '_Rarity_R_LvLimit'),
    ('int', '_Rarity_SR_LvLimit'),
    ('int', '_Rarity_SSR_LvLimit'),
    ('int', '_AddSalaryByLv'),
    ('float', '_minDataChangeRate'),
    ('float', '_maxDataChangeRate'),
    ('float', '_minMoveSpeedChangeRate'),
    ('float', '_maxMoveSpeedChangeRate'),
    ('float', '_minHpRecoveryChangeRate'),
    ('float', '_maxHpRecoveryChangeRate'),
    ('float', '_minHpChangeRate'),
    ('float', '_maxHpChangeRate'),
    ('float', '_minWorkHpChangeRate'),
    ('float', '_maxWorkHpChangeRate'),
    ('CSMaidUpdateData', '_maidUpdateData'),
    ('CSMaidLvUpExp', '_maidLvUpExp'),
    ('int', '_maidActivityExp'),
    ('int', '_maidHActGetHPoint'),
    ('int', '_chatWithPlayerAddLike'),
    ('int', '_likeLimit_ReceiveGift'),
    ('int', '_likeLimit_CanH'),
    ('int', '_initMaidLike'),
    ('float', '_maidRecruitment_SkillRate'),
]
SHOP_LAYOUT = [
    ('bool', 'IsLocked'),
    ('float', '_mapObjOperationDis'),
    ('bool', '_logDefWallsGenerateInfos'),
    ('bool', '_logDefFloorsGenerateInfos'),
    ('CSMapObjGroup', '_defMapObjGroup'),
    ('Color', 'selectMOOutlineColor'),
    ('Color', 'selectMORimLightColor'),
    ('Color', 'selectGuestOutlineColor'),
    ('int', '_moOutlineWidth'),
    ('int', '_moOutlineWidthForRange'),
    ('Color', '_gridTipColor_Normal'),
    ('Color', '_gridTipColor_CanPlace'),
    ('Color', '_gridTipColor_Occupied'),
    ('Color', '_gridTipColor_CannotPlace'),
    ('Color', '_gridTipColor_Locked'),
    ('bool', '_isHideInWall'),
    ('bool', '_isHideOutWall'),
    ('Vector3', '_charaInitPos'),
    ('Vector3', '_maidInitPos'),
    ('float', '_searchRangeRadius'),
    ('float', '_playerSearchRangeRadius'),
    ('float', '_playerSearchRangeRadiusForLarge'),
    ('Color', '_sRangeColor_Talk'),
    ('Color', '_sRangeColor_Mischief'),
    ('Color', '_hallAreaColor'),
    ('Color', '_hallAreaColorUnlock'),
    ('Color', '_kitchenAreaColor'),
    ('Color', '_kitchenAreaColorUnlock'),
    ('Color', '_maidRoomAreaColor'),
    ('Color', '_maidRoomAreaColorUnlock'),
    ('List<int>', '_extendCostByCount'),
    ('int', '_gameSpeed1st'),
    ('int', '_gameSpeed2nd'),
    ('int', '_gameSpeed3rd'),
    ('float', '_sellFoodProfitRate'),
    ('int', '_financingMaxCount'),
    ('int', '_amountOfFinancing'),
    ('int', '_initialFunding'),
    ('int', '_initialFundingForEasy'),
    ('int', '_tableSetMaxCount'),
    ('int', '_recyclingBoxMaxCount'),
    ('int', '_checkoutCounterMaxCount'),
    ('int', '_cookingDeviceMaxCount'),
    ('int', '_receivingTableMaxCount'),
    ('float', '_maidAdPriceRate'),
    ('int', '_darkMerchantMinLevel'),
    ('float', '_star0_1'),
    ('float', '_star1_2'),
    ('float', '_star2_3'),
    ('float', '_star3_4'),
    ('float', '_star5'),
    ('int', '_charmToGuestAddPrec'),
    ('float', '_charmToGuestAddPrecMax'),
    ('int', '_star1Exp'),
    ('int', '_star2Exp'),
    ('int', '_star3Exp'),
    ('int', '_star4Exp'),
    ('int', '_star5Exp'),
    ('int', '_adLevel1_NeedShopLv'),
    ('int', '_adLevel2_NeedShopLv'),
    ('int', '_adLevel3_NeedShopLv'),
    ('int', '_adLevel4_NeedShopLv'),
    ('int', '_maidAd_Lv1_One'),
    ('int', '_maidAd_Lv2_One'),
    ('int', '_maidAd_Lv3_One'),
    ('int', '_maidAd_Lv4_One'),
    ('MaidRecruitRate', '_adLevel1'),
    ('MaidRecruitRate', '_adLevel2'),
    ('MaidRecruitRate', '_adLevel3'),
    ('MaidRecruitRate', '_adLevel4'),
    ('PublicizeAdData', '_publicizeAd'),
    ('float', '_priceChangeLowerLimit'),
    ('float', '_priceChangeUpperLimit'),
    ('float', '_star3_TipsPrec'),
    ('float', '_star4_TipsPrec'),
    ('float', '_star5_TipsPrec'),
]
