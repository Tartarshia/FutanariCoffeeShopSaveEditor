"""Small, paginated gameplay views backed by the disk index."""
import json
from pathlib import Path
import re
import codec
import schema
import appearance

SECTIONS = {
 'Charas':('员工与玩家','基础属性、工作分组、技能、外观、衣装与动作解锁；头像字节不属于玩法属性。'),
 'Items':('仓库','持有物品；料理书决定已学菜谱。已摆放家具不在这里。'),
 'MenusSaveData':('菜单','m = 菜品 ID，c = 剩余份数，s = 单份售价；按同一索引关联。'),
 'MapObjs':('已摆放物品','家具 ID、网格坐标和朝向；需要占地、子物体和房间校验，当前只读。'),
 'MapSaveData':('房间扩建','大厅、厨房、休息室已解锁网格编号；当前只读。'),
 'ShopStars':('近期评分','最多七条评分，索引 0 最新；平均值由游戏计算。'),
 'MissionSaveData':('任务进度','id = 任务 ID，v = 当前进度，i = 是否已领取奖励；可能与成就联动，当前只读。'),
 'Mails':('邮件','发件人、标题、正文和游戏日期；当前只读。'),
 'OldEvents':('历史事件','事件 ID、日期等；当前只读。'),
 'PriceRercods':('物价记录','历史游戏日期及各食材价格倍率；不是仓库数量。当前只读。'),
 'KnownHObjTypes':('已见设备类型','玩家获得设备时更新的类型列表；当前只读。'),
 'TutorialFlags':('教程状态','各教程和初始对话是否完成；当前只读。'),
 'SaveNewMark':('界面新内容标记','物品等内容是否显示新标记；当前只读。'),
 'CameraPos':('镜头位置','三维坐标；当前只读。'),
 'CameraRot':('镜头角度','三维旋转；当前只读。')}

def field(db,cat,path):
    row=db.execute('SELECT kind,value FROM fields WHERE path=?',(path,)).fetchone()
    if not row:
        return None
    k,v=row
    spec=schema.describe(path,db,cat)
    label=appearance.label(path) if '/Looks/Colors/' in path else schema.LABELS.get(path.rsplit('/',1)[-1],path)
    if path.startswith('/ShopStars/'):
        label='近期评分 #'+str(int(path.rsplit('/',1)[-1])+1)
    if '/MenusSaveData/c/' in path:
        label='剩余份数'
    if '/MenusSaveData/s/' in path:
        label='单份售价'
    value=json.loads(v)
    if type(value) is int and abs(value)>9007199254740991:
        value=str(value)  # preserve exact ticks in browsers with IEEE-754 numbers
    return {'path':path,'kind':k,'value':value,'label':label,'rule':spec,'editable':spec is not None}

def staff(db):
    result=[]
    for (p,) in db.execute("SELECT path FROM fields WHERE path GLOB '/Charas/*/IsPlayerChara' ORDER BY CAST(substr(path,9) AS INTEGER) LIMIT 1001"):
        if len(result)>=1000:
            raise ValueError('员工数量超过当前视图上限，请使用分页字段浏览')
        prefix=p.rsplit('/',1)[0]
        result.append({'id':int(prefix.rsplit('/',1)[-1]),
            'name':schema.scalar(db,prefix+'/Looks/CustomName') or schema.scalar(db,prefix+'/Looks/DefName') or prefix,
            'player':schema.scalar(db,p),'level':schema.scalar(db,prefix+'/Attr/MaidLevel'),
            'rarity':schema.scalar(db,prefix+'/Attr/Rarity'),'work':schema.scalar(db,prefix+'/Work')})
    return result

def overview(folder):
    cat=codec.catalogue(folder)
    with codec.connection(Path(folder)/'index.sqlite') as db:
        sections=[]
        for path,start,stop,kind,count in db.execute("SELECT * FROM containers WHERE path<>'' AND instr(substr(path,2),'/')=0 ORDER BY start"):
            key=path[1:]
            title,help=SECTIONS.get(key,(key,'未知结构，原样保留并可查看字段。'))
            sections.append({'path':path,'title':title,'help':help,'count':count,'bytes':stop-start})
        return {'staff':staff(db),'sections':sections,'catalogue_error':cat.get('error'),
                'catalogue':{} if 'error' in cat else {'items':len(cat['items']),'skills':len(cat['skills']),
                    'levels':len(cat['levels']),'maid_limits':cat['maid_limits'],'skill_slots':cat['skill_slots']},
                'roots':[field(db,cat,p) for (p,) in db.execute("SELECT path FROM fields WHERE instr(substr(path,2),'/')=0 ORDER BY start")]}

def view(folder,section,idx=0,page=0,query=''):
    if idx<0 or page<0:
        raise ValueError('Invalid index or page')
    cat=codec.catalogue(folder)
    with codec.connection(Path(folder)/'index.sqlite') as db:
        if section=='shop':
            paths=[p for (p,) in db.execute("SELECT path FROM fields WHERE instr(substr(path,2),'/')=0 ORDER BY start")]
            paths.extend(p for (p,) in db.execute("SELECT path FROM fields WHERE path GLOB '/ShopStars/*' ORDER BY start"))
            lv=cat.get('levels',{}).get(str(schema.scalar(db,'/ShopLevel')))
            return {'fields':[field(db,cat,p) for p in paths], 'level_info':lv,
                    'level_catalogue':list(cat.get('levels',{}).values())}
        if section=='employee':
            prefix=f'/Charas/{idx}'
            attrs=prefix+'/Attr/'
            paths=[prefix+'/IsPlayerChara',prefix+'/Work',prefix+'/Looks/CustomName',prefix+'/Looks/DefName']
            paths.extend(p for (p,) in db.execute('SELECT path FROM fields WHERE path>=? AND path<? AND instr(substr(path,?),\'/\')=0 ORDER BY start',(attrs,attrs+'\uffff',len(attrs)+1)))
            fields=[v for p in paths if (v:=field(db,cat,p))]
            if not fields:
                raise ValueError('Employee not found')
            skill_path=attrs+'SkillSDatas'
            try:
                skills=codec.read_node(folder,skill_path,db)
            except ValueError:
                skills=[]
            return {'fields':fields,'skills_path':skill_path,'skills':skills,
                    'skill_catalogue':list(cat.get('skills',{}).values()),
                    'limits':cat.get('maid_limits'), 'slots':cat.get('skill_slots'),
                    'exps':cat.get('maid_exps'), 'readonly_paths':[prefix+'/Looks/',prefix+'/UnlockHPoses/',prefix+'/Pos/']}
        if section=='appearance':
            import wardrobe
            prefix=f'/Charas/{idx}/Looks/Colors/'
            fields=[field(db,cat,p) for (p,) in db.execute(
                'SELECT path FROM fields WHERE path>=? AND path<? ORDER BY start LIMIT 201',
                (prefix,prefix+'\uffff'))]
            if len(fields)>200:
                raise ValueError('外观字段数量超过受支持范围')
            if not fields:
                raise ValueError('此角色没有可解析的外观字段')
            try:
                wearing=codec.read_node(folder,f'/Charas/{idx}/Looks/WearingClothes',db)
            except ValueError:
                wearing=[]
            return {'id':idx,'fields':fields,'supported':appearance.supported(db,idx,cat),
                'wearing_path':f'/Charas/{idx}/Looks/WearingClothes','wearing_value':wearing,
                'clothing_catalogue':wardrobe.catalogue(cat),'clothing_slots':wardrobe.SLOTS,
                'groups':appearance.COLOR_GROUPS,'catalogue':cat.get('appearance',{}),
                'wearing':[{'id':v.get('ItemMstID'),
                    'name':cat.get('items',{}).get(v.get('ItemMstID'),{}).get('name',v.get('ItemMstID')),
                    'slots':v.get('Slots',[])} for v in wearing],
                'reason':'仅开放已验证的普通女仆模型；玩家、男性及其他模型保持只读。'}
        if section=='inventory':
            values=codec.read_node(folder,'/Items',db)
            entries=[]
            for i,v in enumerate(values):
                item=cat.get('items',{}).get(v.get('m'),{})
                name=item.get('name',v.get('m','?'))
                if query.casefold() not in (name+' '+str(v.get('m'))+' '+item.get('group','')).casefold():
                    continue
                entries.append({'index':i,'id':v.get('m'),'count':v.get('c'),'name':name,
                    'description':item.get('description','本机资料中未知的 ID；原样保留'),
                    'type':item.get('type','未知'),'group':item.get('group','未知'),'stack':item.get('stack'),
                    'price':item.get('price'),'sell':item.get('sell'),
                    'rule':schema.describe(f'/Items/{i}/c',db,cat)})
            return {'entries':entries[page*25:(page+1)*25],'count':len(entries),
                    'array_path':'/Items','array_value':values,'editable':'error' not in cat,
                    'item_details':{v['m']:cat.get('items',{}).get(v['m'],{}) for v in values}}
        if section=='menus':
            ids=codec.read_node(folder,'/MenusSaveData/m',db)
            entries=[]
            for i,key in enumerate(ids):
                item=cat.get('items',{}).get(key,{})
                entries.append({'id':key,'name':item.get('name',key),'ingredients':item.get('food',{}).get('Materials',''),
                    'fields':[field(db,cat,f'/MenusSaveData/{k}/{i}') for k in ('c','s')]})
            return {'entries':entries,'help':'三个数组按同一索引对应；份数是保存时的剩余量，不是仓库食材数量。'}
        if section=='map':
            keys=[json.dumps(k,ensure_ascii=True) for k,v in cat.get('items',{}).items()
                  if query.casefold() in (k+' '+v['name']).casefold()]
            where=" WHERE path GLOB '/MapObjs/*/ItemMstID'"
            args=[]
            if query:
                where+=' AND (instr(lower(value),lower(?))>0'
                args.append(query)
                if keys:
                    where+=' OR value IN ('+','.join('?' for _ in keys)+')'
                    args.extend(keys)
                where+=')'
            count=db.execute('SELECT count(*) FROM fields'+where,args).fetchone()[0]
            records=db.execute('SELECT path,value FROM fields'+where+
                ' ORDER BY CAST(substr(path,10) AS INTEGER) LIMIT 25 OFFSET ?',(*args,page*25))
            entries=[]
            for p,v in records:
                key=json.loads(v);item=cat.get('items',{}).get(key,{})
                parent=p.rsplit('/',1)[0]
                entries.append({'id':key,'name':item.get('name',key),'x':schema.scalar(db,parent+'/GridIndex/x'),
                    'y':schema.scalar(db,parent+'/GridIndex/y'),'dir':schema.scalar(db,parent+'/Dir'),
                    'type':item.get('map',{}).get('MapObjType'),'size':item.get('map',{}).get('Size'),
                    'charm':item.get('map',{}).get('Charm'),'path':parent})
            rooms={}
            for room in ('Hall','Kitchen','MaidRoom'):
                path='/MapSaveData/'+room+'_UnlockedGridIndexs'
                try:rooms[room]=codec.read_node(folder,path,db)
                except ValueError:rooms[room]=[]
            return {'entries':entries,'count':count,'rooms':rooms}
        if section=='missions':
            values=codec.read_node(folder,'/MissionSaveData/ms',db)
            entries=[]
            for value in values:
                mst=cat.get('missions',{}).get(value.get('id'),{})
                key=value.get('id','?')
                if query.casefold() not in (key+' '+mst.get('MissionType','')).casefold():continue
                entries.append({'id':key,'type':mst.get('MissionType','未知'),'value':value.get('v'),
                    'max':mst.get('MaxValue'),'received':value.get('i'),
                    'cash':mst.get('RewardG'),'hpoint':mst.get('RewardH'),'achievement':mst.get('Achievement')})
            return {'entries':entries[page*25:(page+1)*25],'count':len(entries)}
        raise ValueError('Unknown view')

def catalogue_page(folder,query='',page=0):
    cat=codec.catalogue(folder)
    values=[v for v in cat.get('items',{}).values() if v['addable'] and query.casefold() in
            (v['name']+' '+v['id']+' '+v['group']+' '+v['type']).casefold()]
    return {'count':len(values),'entries':[{'id':v['id'],'name':v['name'],'description':v['description'],
             'type':v['type'],'group':v['group'],'stack':v['stack'],'price':v['price'],'sell':v['sell']}
             for v in values[page*25:(page+1)*25]]}
