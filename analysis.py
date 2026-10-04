"""Generate a private report from the disk index; no full save object is built."""
import argparse
import json
from pathlib import Path
import secrets
import codec
import model
import schema

def cell(value):
    if value is None:
        return '—'
    if not isinstance(value,str):
        value=json.dumps(value,ensure_ascii=False)
    return value.replace('|','\\|').replace('\r','').replace('\n','<br>')

def write_report(folder,target):
    folder,target=Path(folder),Path(target)
    cat=codec.catalogue(folder)
    info=model.overview(folder)
    meta=json.loads((folder/'meta.json').read_text(encoding='utf8'))
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf8') as out,codec.connection(folder/'index.sqlite') as db:
        def line(s=''):
            out.write(s+'\n')
        def table(header,rows):
            line('| '+' | '.join(header)+' |')
            line('| '+' | '.join(['---']*len(header))+' |')
            for row in rows:
                line('| '+' | '.join(cell(v) for v in row)+' |')
            line()
        line('# 当前存档分析（私有本机报告）')
        line('本报告包含当前存档内容与角色姓名，保留在 `.local/` 中，不属于可发布源码。')
        line('所有数值均来自原存档；修改过的验证文件没有安装到游戏。游戏内载入验证尚未进行。')
        line(f"源文件：`{Path(meta['source']).name}`；GZip → UTF-8 JSON；解压大小 {meta['bytes']:,} 字节。")
        line(f"源 SHA-256：`{meta['sha256']}`。")
        line(f"原始标量字段 {meta['fields']:,} 个；其中头像字节 "+str(db.execute("SELECT count(*) FROM fields WHERE path GLOB '/Charas/*/Looks/_charaIconByte/*'").fetchone()[0])+" 个。")
        line()
        line('## 数据结构总览')
        table(['数据区','条目数','解压字节','含义'],((s['path'],s['count'],s['bytes'],s['help']) for s in info['sections']))
        line('## 店铺与存档元信息')
        table(['名称','原始路径','原值','编辑范围'],((f['label'],f['path'],f['value'],
            f['rule'].get('help') or f['rule']['type'] if f['rule'] else '只读') for f in info['roots']))
        lv=cat.get('levels',{}).get(str(schema.scalar(db,'/ShopLevel')))
        if lv:
            line(f"当前店铺等级 {lv['level']}：基础客流 {lv['guests']}，工作员工上限 {lv['maids']}，升级经验 {lv['next_exp']}。")
        stars=codec.read_node(folder,'/ShopStars',db)
        line('最近评分（最新在前）：'+cell(stars)+'。平均值为游戏计算值，不另存单独字段。')
        line()
        line('## 逐员工与玩家解析')
        if 'error' not in cat:
            line('N/R/SR/SSR 最大等级：'+cell(cat['maid_limits'])+'；技能数上限：'+cell(cat['skill_slots'])+'。')
            line('每一级升级经验：'+cell(cat['maid_exps'])+'。按本机配置的单精度运算及舍入生成。')
        for who in info['staff']:
            prefix=f"/Charas/{who['id']}"
            line(f"### {'玩家' if who['player'] else '员工'} #{who['id']}：{who['name']}")
            line('当前体力 NowHp 不在存档中；载入时初始化为最大体力。下面为基础属性，不含临时增益。')
            values=model.view(folder,'employee',who['id'])
            table(['名称','字段','原值','约束或含义'],((f['label'],f['path'],f['value'],
                f['rule'].get('help') or f['rule']['type'] if f['rule'] else '只读') for f in values['fields']))
            line('技能：')
            table(['技能 ID','中文名称','经验','类型','配置效果'],((s['SkillMstID'],
                cat.get('skills',{}).get(s['SkillMstID'],{}).get('name','未知'),s['Exp'],
                cat.get('skills',{}).get(s['SkillMstID'],{}).get('type','未知'),
                '；'.join(b['description'] for b in cat.get('skills',{}).get(s['SkillMstID'],{}).get('buffs',[])))
                for s in values['skills']))
            line('<details><summary>外观、衣装、位置与动作解锁原始数据（只读）</summary>\n')
            table(['路径','值'],((p,json.loads(v)) for p,v in db.execute(
                "SELECT path,value FROM fields WHERE path>=? AND path<? AND path NOT GLOB '/Charas/*/Looks/_charaIconByte/*' AND path NOT LIKE ? AND path NOT LIKE ? ORDER BY start",
                (prefix+'/',prefix+'/\uffff',prefix+'/Attr/%',prefix+'/IsPlayerChara'))
                if p!=prefix+'/Work'))
            line('</details>\n')
        line('## 仓库与持有物品')
        items=codec.read_node(folder,'/Items',db)
        line('Items[].m = 物品 ID，Items[].c = 持有数量。共 '+str(len(items))+' 条，数量合计 '+str(sum(v['c'] for v in items))+'。')
        line('仓库不包含已摆放家具。料理书持有记录决定可制作菜谱；零数量条目仍可能被当作持有，移除须删除条目。')
        table(['序号','ID','名称','数量','类型','分类','堆叠上限','购入基价','卖出价'],
            ((i,v['m'],cat.get('items',{}).get(v['m'],{}).get('name','未知'),v['c'],
              cat.get('items',{}).get(v['m'],{}).get('type','未知'),cat.get('items',{}).get(v['m'],{}).get('group','未知'),
              cat.get('items',{}).get(v['m'],{}).get('stack','未知'),cat.get('items',{}).get(v['m'],{}).get('price','未知'),
              cat.get('items',{}).get(v['m'],{}).get('sell','未知')) for i,v in enumerate(items)))
        learned={}
        for v in items:
            if cat.get('items',{}).get(v['m'],{}).get('type')=='CookingBook':
                for key,mst in cat.get('items',{}).items():
                    if mst.get('food',{}).get('CookingBook')==v['m']:
                        learned[key]=mst
        line('持有料理书解锁的菜谱：'+str(len(learned))+' 种（按条目存在性计算，不排除零数量条目）。')
        table(['菜谱 ID','名称','料理书','食材 ID'],((k,v['name'],v['food'].get('CookingBook'),v['food'].get('Materials')) for k,v in learned.items()))
        line('## 当前菜单')
        menus=model.view(folder,'menus')
        line(menus['help'])
        table(['ID','名称','剩余份数','单份售价','所需食材 ID'],((v['id'],v['name'],
            v['fields'][0]['value'] if v['fields'][0] else None,v['fields'][1]['value'] if v['fields'][1] else None,v['ingredients']) for v in menus['entries']))
        line('## 已摆放物件与扩建')
        line('MapObjs[].ItemMstID 是物品 ID，GridIndex.x/y 是网格坐标，Dir 为朝向枚举。只读，不猜测碰撞及子物体关联。')
        count=db.execute("SELECT count(*) FROM fields WHERE path GLOB '/MapObjs/*/ItemMstID'").fetchone()[0]
        line('共 '+str(count)+' 个已摆放物件。')
        for room in ('Hall','Kitchen','MaidRoom'):
            path='/MapSaveData/'+room+'_UnlockedGridIndexs'
            line(path+'：'+cell(codec.read_node(folder,path,db)))
        def placed():
            for (p,v) in db.execute("SELECT path,value FROM fields WHERE path GLOB '/MapObjs/*/ItemMstID' ORDER BY start"):
                key=json.loads(v);parent=p.rsplit('/',1)[0];mst=cat.get('items',{}).get(key,{})
                yield parent,key,mst.get('name','未知'),schema.scalar(db,parent+'/GridIndex/x'),schema.scalar(db,parent+'/GridIndex/y'),schema.scalar(db,parent+'/Dir')
        table(['路径','ID','名称','x','y','Dir'],placed())
        line('## 任务进度与奖励标志')
        line('MissionSaveData.ms[].id 是任务 ID，v 是当前进度，i 是已经领取奖励。任务值可由游戏按当前状态更新；修改这些字段可能影响奖励及关联成就，因此当前只读。')
        missions=codec.read_node(folder,'/MissionSaveData/ms',db)
        table(['ID','类型','当前值','目标','奖励已领取','资金奖励','H 点奖励','关联成就'],
            ((v['id'],cat.get('missions',{}).get(v['id'],{}).get('MissionType'),v['v'],
              cat.get('missions',{}).get(v['id'],{}).get('MaxValue'),v['i'],
              cat.get('missions',{}).get(v['id'],{}).get('RewardG'),
              cat.get('missions',{}).get(v['id'],{}).get('RewardH'),
              cat.get('missions',{}).get(v['id'],{}).get('Achievement')) for v in missions))
        line('## 其余存档字段')
        line('包括邮件、物价记录、历史事件、教程、新内容标记、已见设备和镜头。空数组已经列入总览，不遗漏。')
        excluded=('/Charas/','/Items/','/MapObjs/','/MapSaveData/','/MissionSaveData/','/MenusSaveData/','/ShopStars/')
        table(['路径','值'],((p,json.loads(v)) for p,v in db.execute('SELECT path,value FROM fields ORDER BY start')
            if p.count('/')>1 and not p.startswith(excluded)))
        if 'error' not in cat:
            line('## 本机全部技能目录（仅此私有报告）')
            table(['ID','名称','类型','招聘稀有度','技能效果'],((key,v['name'],v['type'],v['rarities'],
                '；'.join(b['description'] for b in v['buffs'])) for key,v in cat['skills'].items()))
            line('## 本机全部店铺等级配置（仅此私有报告）')
            table(['等级','升级经验','基础客流','员工上限'],((v['level'],v['next_exp'],v['guests'],v['maids']) for v in cat['levels'].values()))
        line('## 修改行为边界')
        line('编辑器可修改全部已确认的员工基础属性、分组、姓名、稀有度、等级经验、技能；店铺资金、名称、等级、经验、评分、难度、融资次数；仓库数量、添加与删除；菜单份数和售价。')
        line('等级修改不会模拟随机成长，不领取任务奖励。技能效果按 ID 配置；技能 Exp 的持久化已确认，但当前代码未发现以其触发技能升级。')
        line('原存档不写回；修改只导出新文件。标量修改仅替换对应值，仓库和技能增删仅重写明确选择的小数组，其余解压字节保持不变。')
    return {'file':str(target),'bytes':target.stat().st_size}

def main():
    p=argparse.ArgumentParser(description='生成保留在本机的详细存档分析报告')
    p.add_argument('--source')
    p.add_argument('--session')
    p.add_argument('--game')
    p.add_argument('--output',default='.local/analysis/save-analysis.md')
    args=p.parse_args()
    if args.session:
        folder=Path(args.session)
    elif args.source:
        folder=Path('.local/analysis')/secrets.token_hex(8)
        codec.prepare(args.source,folder,args.game)
    else:
        p.error('提供 --source 存档文件，或 --session 已建立的本地索引目录')
    print(json.dumps(write_report(folder,args.output),ensure_ascii=True))

if __name__=='__main__':
    main()
