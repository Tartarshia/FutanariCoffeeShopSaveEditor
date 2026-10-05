"""Verified gameplay fields, bounds, explanations, and cross-field validation."""
import json
import math
import re
import appearance

LABELS = {
 'TotalCash':'资金','HPoint':'H 点','ShopLevel':'店铺等级','ShopExp':'店铺经验',
 'CoffeeShopName':'店铺名称','Difficulty':'难度','FinancingCount':'剩余融资次数',
 'DaysInGame':'游戏天数','IsNight':'当前是否夜间','PlayTime_Minutes':'游玩分钟数',
 'GameVer':'游戏版本','SlotNum':'槽位编号','Seed':'随机种子','SaveCount':'保存次数',
 'CreateDate':'创建时间（.NET ticks）','LastChangeDate':'最近保存时间（.NET ticks）',
 'PlayerCharaType':'玩家角色类型','MaxHp':'最大体力','HpRecovery':'体力恢复 / 秒',
 'MoveSpeed':'移动速度','CookingTime':'料理耗时 / 秒','OrderingTime':'点单耗时 / 秒',
 'CheckoutTime':'结账耗时 / 秒','CleaningUpTime':'清桌耗时 / 秒',
 'CookingHpCost':'料理体力消耗','OrderingHpCost':'点单体力消耗',
 'CheckoutHpCost':'结账体力消耗','CleaningUpHpCost':'清桌体力消耗',
 'ExpGetRate':'经验获得倍率','HPointGetRate':'H 点获得倍率',
 'UseMaidDeviceRate':'休息室设备使用概率','MaidLevel':'员工等级','MaidLevelExp':'员工当前等级经验',
 'NowLike':'当前好感度','BasicSalary':'基本工资','CharaCharm':'基础魅力',
 'OrderingPriority':'点单优先级','CheckoutPriority':'结账优先级',
 'CleaningUpPriority':'清桌优先级','DeliveryPriority':'送餐优先级','Rarity':'稀有度',
 'Work':'工作区域','CustomName':'自定义姓名','DefName':'默认姓名','Description':'角色简介',
 'SkillMstID':'技能 ID','Exp':'技能经验（保留字段）','IsPlayerChara':'是否为玩家',
 'ItemMstID':'物品 ID','Dir':'摆放朝向'}

ATTRS = {
 'MaxHp':('integer',1,1000000),'HpRecovery':('number',0,1000000),
 'MoveSpeed':('number',0.1,1000),'CharaCharm':('integer',0,9999),
 'CookingTime':('number',1,999),'OrderingTime':('number',1,999),
 'CheckoutTime':('number',1,999),'CleaningUpTime':('number',1,999),
 'CookingHpCost':('number',1,999),'OrderingHpCost':('number',1,999),
 'CheckoutHpCost':('number',1,999),'CleaningUpHpCost':('number',1,999),
 'ExpGetRate':('number',1,99),'HPointGetRate':('number',1,99),
 'UseMaidDeviceRate':('number',0.01,1),'NowLike':('integer',0,100),
 'BasicSalary':('integer',0,1000000),
 'OrderingPriority':('integer',0,3),'CheckoutPriority':('integer',0,3),
 'CleaningUpPriority':('integer',0,3),'DeliveryPriority':('integer',0,3)}

def scalar(db, path, default=None):
    row = db.execute('SELECT value FROM fields WHERE path=?', (path,)).fetchone()
    return json.loads(row[0]) if row else default

def rule(kind, lo=None, hi=None, help='', choices=None):
    return {'type':kind, 'min':lo, 'max':hi, 'help':help, 'choices':choices}

def describe(path, db, cat):
    available = cat and 'error' not in cat
    if path == '/TotalCash':
        return rule('integer',0,999999999, '游戏代码的资金上限为 999,999,999。')
    if path == '/HPoint':
        return rule('integer',0,99999999, '游戏代码的 H 点上限为 99,999,999。')
    if path == '/CoffeeShopName':
        return rule('string',1,80)
    if path == '/ShopExp':
        level = cat.get('levels',{}).get(str(scalar(db,'/ShopLevel')),{}) if available else {}
        upper = max(0,level['next_exp']-1) if level else 2147483647
        return rule('integer',0,upper,'当前等级进度；升级请同时调整店铺等级和经验，导出按最终等级校验。')
    if not available:
        return None
    if '/Looks/Colors/' in path:
        return appearance.describe(path,db,cat)
    if path == '/ShopLevel':
        return rule('integer',1,max(int(x) for x in cat['levels']),
                    '直接设置等级，不领取升级任务奖励；员工人数须在目标等级上限以内。')
    if path == '/Difficulty':
        return rule('integer',0,1,choices=[{'value':0,'label':'普通'},{'value':1,'label':'简单'}])
    if path == '/FinancingCount':
        return rule('integer',0,cat['financing_max'],'不会立即发放融资资金。')
    if re.fullmatch(r'/ShopStars/\d+',path):
        return rule('number',0,5,'最近七次评分，索引 0 为最新；平均值由游戏计算。')
    if re.fullmatch(r'/Charas/\d+/Attr/SkillSDatas',path):
        return rule('skills',help='技能效果由 ID 的配置决定；添加、删除或替换后在载入时生效。')
    if path == '/Items':
        return rule('inventory',help='持有物品清单；已摆放的家具另存于 MapObjs，修改仓库不会改动地图。')
    m = re.fullmatch(r'/Charas/(\d+)/Attr/(\w+)',path)
    if m:
        prefix = '/Charas/'+m[1]+'/Attr/'
        key = m[2]
        if key in ATTRS:
            kind,lo,hi = ATTRS[key]
            help = '编辑基础值；实际值还受技能及临时增益影响。'
            if key.endswith('Time') or key.endswith('HpCost'):
                help += ' 游戏将实际值限制在 1–999；越低越省时或省体力。'
            if key in ('MaxHp','HpRecovery','MoveSpeed','BasicSalary'):
                help += ' 上界为编辑器防溢出限值，不代表自然成长上限。'
            if key.endswith('Priority'):
                help = '游戏工作优先级：0–3。'
            return rule(kind,lo,hi,help)
        rarity = scalar(db,prefix+'Rarity',0)
        level = scalar(db,prefix+'MaidLevel',1)
        if key == 'Rarity':
            return rule('integer',0,3,'不会自动随机成长或增加技能；等级与技能数按最终稀有度校验。',
                        [{'value':i,'label':s} for i,s in enumerate(('N','R','SR','SSR'))])
        if key == 'MaidLevel' and type(rarity) is int and 0 <= rarity <= 3:
            return rule('integer',1,max(cat['maid_limits']),
                        '只设置等级；不会模拟随机升级属性。按最终稀有度上限校验，建议一并调整经验。')
        if key == 'MaidLevelExp':
            maximum = max(cat['maid_exps'])-1
            return rule('integer',0,maximum,'须小于最终等级的升级经验；满级时须为 0。')
    m = re.fullmatch(r'/Charas/(\d+)/Work',path)
    if m and not scalar(db,'/Charas/'+m[1]+'/IsPlayerChara',False):
        return rule('integer',0,3,choices=[{'value':i,'label':s} for i,s in enumerate(('大厅','厨房','休息室','待命'))])
    if re.fullmatch(r'/Charas/\d+/Looks/CustomName',path):
        return rule('string',0,8,'空字符串表示使用默认姓名；游戏姓名上限为 8 个字符。')
    m = re.fullmatch(r'/Charas/(\d+)/Attr/SkillSDatas/(\d+)/(SkillMstID|Exp)',path)
    if m:
        if m[3] == 'Exp':
            return rule('integer',0,2147483647,'已确认随存档读写；当前代码未发现用它升级技能，技能档位由 ID 决定。')
        return rule('choice',choices=[{'value':k,'label':v['name']+' · '+k} for k,v in cat['skills'].items()])
    m = re.fullmatch(r'/Items/(\d+)/c',path)
    if m:
        item = cat['items'].get(scalar(db,'/Items/'+m[1]+'/m'))
        if item and item['stack'] > 0:
            return rule('integer',0,item['stack'],'按本机物品配置的堆叠上限校验；删除条目需使用仓库的移除按钮。')
    m = re.fullmatch(r'/MenusSaveData/(c|s)/(\d+)',path)
    if m:
        return rule('integer',0,30 if m[1]=='c' else 1000000,
                    '剩余份数，游戏菜单配置最多 30 份。' if m[1]=='c' else '单份售价；编辑器采用 1,000,000 防溢出上界。')
    return None

def validate_value(path, value, spec, kind):
    if not spec:
        raise ValueError('只读字段：'+path)
    typ = spec['type']
    if typ in ('skills','inventory'):
        if kind != 'array' or not isinstance(value,list):
            raise ValueError('Expected array: '+path)
        if len(value)>1000:
            raise ValueError('Array too large')
    elif typ == 'string':
        if kind != 'string' or not isinstance(value,str) or not spec['min']<=len(value)<=spec['max'] or any(ord(c)<32 for c in value):
            raise ValueError('文字长度或字符无效：'+path)
    elif typ == 'choice':
        if kind != 'string' or value not in [o['value'] for o in spec['choices']]:
            raise ValueError('未知 ID：'+path)
    else:
        if kind!='number' or type(value) not in (int,float) or not math.isfinite(value) or (typ=='integer' and type(value) is not int):
            raise ValueError('数值类型无效：'+path)
        if not spec['min']<=value<=spec['max']:
            raise ValueError(f"{path} 必须在 {spec['min']}–{spec['max']} 之间")
    encoded = json.dumps(value,ensure_ascii=True,allow_nan=False).encode('ascii')
    if len(encoded)>262144:
        raise ValueError('Edited array too large')
    return encoded

def skills_valid(values, rarity, cat):
    if not isinstance(values,list) or len(values)>cat['skill_slots'][rarity]:
        raise ValueError('技能数超过最终稀有度的技能上限')
    ids, families = set(),set()
    for value in values:
        if not isinstance(value,dict) or set(value)!={'SkillMstID','Exp'}:
            raise ValueError('技能条目必须包含 SkillMstID 和 Exp')
        key,exp = value['SkillMstID'],value['Exp']
        if not isinstance(key,str) or key not in cat['skills'] or key in ids:
            raise ValueError('未知或重复技能 ID')
        if type(exp) is not int or not 0<=exp<=2147483647:
            raise ValueError('技能经验无效')
        family = cat['skills'][key]['type']
        if family != 'Tip' and family in families:
            raise ValueError('同一类型技能不可叠加：'+family)
        ids.add(key)
        families.add(family)

def inventory_valid(values, original, cat):
    if not isinstance(values,list) or len(values)>1000:
        raise ValueError('仓库清单过大')
    prior = {v['m']:v for v in original if isinstance(v,dict) and isinstance(v.get('m'),str)}
    ids = set()
    for value in values:
        if not isinstance(value,dict) or not isinstance(value.get('m'),str):
            raise ValueError('仓库条目无效')
        key = value['m']
        if key in ids:
            raise ValueError('仓库中不能存在重复 ID：'+key)
        ids.add(key)
        if value == prior.get(key):
            continue  # preserve unknown original entries exactly at the value level
        if set(value)!={'m','c'} or type(value['c']) is not int:
            raise ValueError('仓库条目须为 m / c；未知原有字段只能原样保留')
        item = cat['items'].get(key)
        if not item or item['stack']<=0 or not 0<=value['c']<=item['stack']:
            raise ValueError('物品数量超出本机配置上限或 ID 未知：'+key)
        if key not in prior and (not item['addable'] or value['c']<=0):
            raise ValueError('该物品不可作为新条目加入仓库：'+key)

def validate_links(changes, db, cat, node):
    if not cat or 'error' in cat:
        return
    def current(path, default=None):
        return changes.get(path,scalar(db,path,default))
    if '/Items' in changes:
        inventory_valid(changes['/Items'],node('/Items'),cat)
    employees = {m[1] for path in changes if (m:=re.match(r'/Charas/(\d+)/',path))}
    for idx in employees:
        p = '/Charas/'+idx+'/Attr/'
        rarity,level,exp = current(p+'Rarity'),current(p+'MaidLevel'),current(p+'MaidLevelExp')
        if type(rarity) is not int or not 0<=rarity<=3 or type(level) is not int or not 1<=level<=cat['maid_limits'][rarity]:
            raise ValueError('员工等级超出最终稀有度上限：'+idx)
        if any(p+k in changes for k in ('Rarity','MaidLevel','MaidLevelExp')):
            upper = 0 if level==cat['maid_limits'][rarity] else cat['maid_exps'][level-1]-1
            if type(exp) is not int or not 0<=exp<=upper:
                raise ValueError('员工经验与最终等级不匹配：'+idx+f'，允许 0–{upper}')
        skills_path = p+'SkillSDatas'
        skill_touched = skills_path in changes or any(x.startswith(skills_path+'/') for x in changes)
        if skill_touched or p+'Rarity' in changes:
            values = changes.get(skills_path,node(skills_path))
            # Apply scalar skill patches to a bounded list for relation checks.
            for path,value in changes.items():
                m = re.fullmatch(re.escape(skills_path)+r'/(\d+)/(SkillMstID|Exp)',path)
                if m:
                    values[int(m[1])][m[2]] = value
            skills_valid(values,rarity,cat)
    if any(p in changes for p in ('/ShopLevel','/ShopExp')):
        level,exp = current('/ShopLevel'),current('/ShopExp')
        lv = cat['levels'].get(str(level))
        if not lv:
            raise ValueError('未知店铺等级')
        upper = max(0,lv['next_exp']-1)
        if type(exp) is not int or not 0<=exp<=upper:
            raise ValueError(f'店铺经验与最终等级不匹配，允许 0–{upper}')
    if '/ShopLevel' in changes or any(p.endswith('/Work') for p in changes):
        lv = cat['levels'].get(str(current('/ShopLevel')))
        if lv:
            workers = sum(not scalar(db,p.rsplit('/',1)[0]+'/IsPlayerChara',False)
                          and current(p)!=3 for (p,) in db.execute("SELECT path FROM fields WHERE path GLOB '/Charas/*/Work'"))
            if workers>lv['maids']:
                raise ValueError('工作员工数超出目标店铺等级上限；请先安排待命')
