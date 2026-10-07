"""Bounded, validated gameplay shortcuts; generate edits without writing a save."""
from pathlib import Path
from itertools import combinations
from copy import deepcopy
import math
import struct
import codec
import schema

MODES = {'skills'}


def boss_reference(cat):
    """SSR birth and 14 upgrades using local growth interval midpoints."""
    m=cat.get('maid_settings',{})
    if cat.get('maid_limits',[None]*4)[3]!=15:
        raise ValueError('本机配置不支持已核对的 SSR Lv15 成长规则')
    def f(x):
        return struct.unpack('<f',struct.pack('<f',x))[0]
    def rnd(x,digits=3):
        return f(round(f(x),digits))
    def number(key):
        x=m[key]
        if type(x) not in (int,float) or not math.isfinite(x) or x<=0:
            raise ValueError('无效本机成长配置：'+key)
        return f(x)
    def mean_pair(key):
        x=m[key]
        if not isinstance(x,list) or len(x)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in x) or x[0]>x[1]:
            raise ValueError('无效本机成长区间：'+key)
        return f(f(x[0]+x[1])*0.5)
    general=f(f(m['_Rarity_N_Rate'][0]+m['_Rarity_SSR_Rate'][1])*0.5)
    ssr=mean_pair('_Rarity_SSR_Rate')
    move=mean_pair('_Rarity_SSR_MoveSpeed')
    get=mean_pair('_Rarity_SSR_GetRate')
    divisor=round(f(f(cat['maid_limits'][0]+cat['maid_limits'][3])/2))
    if general<=0 or divisor<=0:
        raise ValueError('无效本机成长基准')
    fields={'MaxHp':('_maxHp','Hp'),'HpRecovery':('_hpRecovery','HpRecovery'),
        'MoveSpeed':('_moveSpeed','MoveSpeed'),'CharaCharm':('_charaCharm','Data'),
        'CookingTime':('_cookingTime','Data'),'OrderingTime':('_orderingTime','Data'),
        'CheckoutTime':('_checkoutTime','Data'),'CleaningUpTime':('_cleaningUpTime','Data'),
        'CookingHpCost':('_cookingCostHp','WorkHp'),'OrderingHpCost':('_orderingCostHp','WorkHp'),
        'CheckoutHpCost':('_checkoutCostHp','WorkHp'),'CleaningUpHpCost':('_cleaningUpCostHp','WorkHp'),
        'ExpGetRate':(None,'Data'),'HPointGetRate':(None,'Data')}
    result={}
    for key,(setting,group) in fields.items():
        integer=key in ('MaxHp','CharaCharm')
        cost=key.endswith('HpCost')
        lower=cost or key.endswith('Time')
        if setting is None:
            base=round(general)
            current=rnd(get,2)
        else:
            raw=number(setting)
            base_value=f(raw/general) if lower else f(raw*general)
            initial=f(raw/ssr) if lower else f(raw*(move if key=='MoveSpeed' else ssr))
            base=round(base_value) if integer or cost else rnd(base_value,1)
            current=round(initial) if integer or cost else rnd(initial,1)
        growth=[]
        for edge in ('min','max'):
            rate=number('_'+edge+group+'ChangeRate')
            target=f(base/rate) if lower else f(base*rate)
            if integer:
                target=round(target)
            delta=f(f(target-base)/divisor)
            growth.append(round(delta) if key=='MaxHp' else rnd(delta))
        if growth[0]>growth[1]:
            growth.reverse()
        step=f(f(growth[0]+growth[1])*0.5)
        step=round(step) if integer else rnd(step)
        for _ in range(14):
            current=current+step if integer else f(current+step)
            if lower:
                current=max(1,current)
        result[key]=int(current) if integer else round(current,3)
    return result


def boss_plan(folder):
    folder=Path(folder)
    cat=codec.catalogue(folder)
    if not cat or 'error' in cat:
        raise ValueError('请先载入本机游戏配置')
    targets=boss_reference(cat)
    changes,originals,labels={},{},{}
    with codec.connection(folder/'index.sqlite') as db:
        players=db.execute("SELECT path FROM fields WHERE path GLOB '/Charas/*/IsPlayerChara' AND value='true' LIMIT 2").fetchall()
        if len(players)!=1:
            raise ValueError('存档中未找到唯一的老板角色')
        idx=int(players[0][0].split('/')[2])
        for key,val in targets.items():
            path=f'/Charas/{idx}/Attr/{key}'
            row=db.execute('SELECT kind FROM fields WHERE path=?',(path,)).fetchone()
            if not row:
                raise ValueError('老板缺少属性字段：'+key)
            schema.validate_value(path,val,schema.describe(path,db,cat),row[0])
            changes[path],originals[path]=val,schema.scalar(db,path)
            labels[path]=schema.LABELS[key]
    return {'id':idx,'changes':changes,'originals':originals,'labels':labels}


def clothing_stock(values, original, cat):
    """Set every addable clothing/accessory stock to 20 without touching wearers."""
    if not cat or 'error' in cat:
        raise ValueError('请先载入本机游戏配置')
    schema.inventory_valid(values,original,cat)
    targets = {key:v for key,v in cat['items'].items() if v['type']=='Clothes' and v['addable']}
    if not targets:
        raise ValueError('本机配置没有可添加的服装或配件')
    if any(v['stack']<20 for v in targets.values()):
        raise ValueError('存在堆叠上限不足 20 的服装，本次操作未应用')
    result = deepcopy(values)
    present = {v['m']:v for v in result}
    changed, added = 0,0
    for key in sorted(targets):
        if key in present:
            if present[key]['c']!=20:
                present[key]['c']=20
                changed+=1
        else:
            result.append({'m':key,'c':20})
            added+=1
    schema.inventory_valid(result,original,cat)
    return {'items':result,'total':len(targets),'changed':changed,'added':added}


def all_likes(folder):
    """Prepare only NowLike edits for non-player employees, including standby."""
    folder = Path(folder)
    cat = codec.catalogue(folder)
    if not cat or 'error' in cat:
        raise ValueError('请先载入本机游戏配置')
    changes, originals = {}, {}
    with codec.connection(folder/'index.sqlite') as db:
        rows = db.execute("SELECT path FROM fields WHERE path GLOB '/Charas/*/IsPlayerChara' LIMIT 1001").fetchall()
        if len(rows)>1000:
            raise ValueError('员工数量超过快捷操作上限')
        for (identity,) in rows:
            if schema.scalar(db, identity) is not False:
                continue
            path = identity.rsplit('/',1)[0]+'/Attr/NowLike'
            row = db.execute('SELECT kind,value FROM fields WHERE path=?',(path,)).fetchone()
            if not row:
                raise ValueError('员工缺少好感度字段：'+path)
            spec = schema.describe(path, db, cat)
            target = schema.ATTRS['NowLike'][2]
            schema.validate_value(path, target, spec, row[0])
            changes[path], originals[path] = target, schema.scalar(db,path)
    return {'changes':changes,'originals':originals}

SKILL_EFFECTS = (('FoodQuality', ('FoodQualityUp',)),
                 ('CookingSpeed', ('ReduceCookingTime',)),
                 ('AddCharm', ('AddCharaCharmRate',)),
                 ('AddHPoint', ('AddHPointGetRate',)))


def best_skills(cat, route, rarity=3):
    if route not in ('kitchen','hall') or type(rarity) is not int or not 0<=rarity<=3:
        raise ValueError('无效路线或员工稀有度')
    slots = cat['skill_slots'][rarity]
    if type(slots) is not int or not 1<=slots<=4:
        raise ValueError('本机配置的员工技能槽上限不受支持')
    if route == 'hall':
        effects = ('TipCheckout', 'TipOrdering', 'TipDelivery')
        options = []
        for key, skill in cat['skills'].items():
            buffs = skill.get('buffs', [])
            if (skill['type'] != 'Tip' or 'SSR' not in skill.get('rarities', [])
                    or not buffs or any(b['type'] not in effects or b['value'] <= 0 for b in buffs)):
                continue
            totals = tuple(sum(b['value'] for b in buffs if b['type'] == e) for e in effects)
            options.append((key, totals))
        if not 1 <= slots <= 4 or not slots <= len(options) <= 32:
            raise ValueError('本机配置缺少足够的已验证 SSR 小费技能')
        def score(group):
            totals = tuple(sum(v[i] for _, v in group) for i in range(3))
            return (sum(totals), min(totals), tuple(sorted(totals)), tuple(k for k, _ in group))
        selected = max(combinations(sorted(options), slots), key=score)
        result = [{'SkillMstID': key, 'Exp': 0} for key, _ in selected]
        schema.skills_valid(result, rarity, cat)
        return result
    result = []
    for family, effects in SKILL_EFFECTS[:slots]:
        options = []
        for key, skill in cat['skills'].items():
            buffs = skill.get('buffs', [])
            if (skill['type'] != family or 'SSR' not in skill.get('rarities', [])
                    or not buffs or any(b['type'] not in effects or b['value'] < 0
                                           or b.get('value2', 0) < 0 for b in buffs)):
                continue
            totals = tuple(sum(b['value'] for b in buffs if b['type'] == effect) for effect in effects)
            if not all(v > 0 for v in totals):
                continue
            score = (sum(totals), totals, sum(b.get('value2', 0) for b in buffs))
            options.append((score, key))
        if not options:
            raise ValueError('本机配置缺少已验证的最高档技能类型：' + family)
        key = max(options)[1]
        result.append({'SkillMstID': key, 'Exp': 0})
    schema.skills_valid(result, rarity, cat)
    return result


def plan(folder, idx, mode, route='kitchen'):
    if (type(idx) is not int or not 0 <= idx <= 1000 or mode not in MODES
            or route not in ('kitchen', 'hall')):
        raise ValueError('无效员工快捷操作')
    folder = Path(folder)
    cat = codec.catalogue(folder)
    if not cat or 'error' in cat:
        raise ValueError('请先载入本机游戏配置')
    prefix = f'/Charas/{idx}'
    attrs = prefix + '/Attr/'
    with codec.connection(folder / 'index.sqlite') as db:
        if schema.scalar(db, prefix + '/IsPlayerChara') is not False:
            raise ValueError('快捷强化仅适用于员工，不能用于玩家或不存在的角色')
        rarity = schema.scalar(db, attrs+'Rarity')
        targets = {'SkillSDatas': best_skills(cat, route, rarity)}
        changes, originals = {}, {}
        for key, val in targets.items():
            path = attrs + key
            kind = db.execute('SELECT kind FROM fields WHERE path=?', (path,)).fetchone()
            if kind:
                original = schema.scalar(db, path)
                kind = kind[0]
            else:
                row = db.execute('SELECT kind FROM containers WHERE path=?', (path,)).fetchone()
                if not row:
                    raise ValueError('员工缺少强化所需字段：' + key)
                kind = row[0]
                original = codec.read_node(folder, path, db)
            schema.validate_value(path, val, schema.describe(path, db, cat), kind)
            changes[path], originals[path] = val, original
        schema.validate_links(changes, db, cat, lambda path: codec.read_node(folder, path, db))
    return {'changes': changes, 'originals': originals}
