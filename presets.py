"""Bounded, validated employee presets; generate edits without writing a save."""
from pathlib import Path
from itertools import combinations
import codec
import schema

MODES = {'skills'}


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
