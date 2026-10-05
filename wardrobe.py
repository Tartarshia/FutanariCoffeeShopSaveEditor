"""Bounded clothing arrays and verified equipment/inventory transfers."""
import copy
import game_data

SLOTS={1:('STops','外衣上装'),2:('SBottoms','外衣下装'),3:('SInner_Top','内衣上装'),
    4:('SInner_Bottom','内衣下装'),5:('SGloves','手套'),6:('SPantyhose','连裤袜'),
    7:('SSocks','袜子'),8:('SShoes','鞋子'),30:('SHead','头饰'),31:('SNeck','颈饰'),
    32:('SArm_Right','右臂'),33:('SArm_Left','左臂'),34:('SWrist_Right','右腕'),
    35:('SWrist_Left','左腕'),36:('SThighs_Right','右腿饰'),37:('SThighs_Left','左腿饰')}
SLOT_IDS={name:key for key,(name,label) in SLOTS.items()}
PAIRS=({32,33},{34,35},{36,37})

def choices(item):
    info=item.get('clothes',{})
    if not info or info.get('Gender')!='Female' or not item.get('model'):
        return []
    names=game_data.strings(info.get('OccupiedSlots',''))
    if not names or any(name not in SLOT_IDS for name in names):return []
    slots=sorted({SLOT_IDS[name] for name in names})
    return [[slot] for slot in slots] if set(slots) in PAIRS else [slots]

def valid(values, original, cat):
    if not isinstance(values,list) or len(values)>32:raise ValueError('衣装清单过大')
    occupied=set()
    for value in values:
        if not isinstance(value,dict) or not isinstance(value.get('ItemMstID'),str):
            raise ValueError('衣装条目无效')
        slots=value.get('Slots')
        if not isinstance(slots,list) or not slots or any(type(s) is not int or s not in SLOTS for s in slots):
            raise ValueError('衣装槽位无效')
        if len(set(slots))!=len(slots) or occupied.intersection(slots):raise ValueError('服装槽位冲突')
        occupied.update(slots)
        if value in original:continue
        item=cat.get('items',{}).get(value['ItemMstID'],{})
        if set(value)!={'ItemMstID','Slots'} or sorted(slots) not in choices(item) or not item.get('addable'):
            raise ValueError('未知、禁用或槽位不匹配的衣装：'+value['ItemMstID'])

def catalogue(cat):
    return [{'id':key,'name':v['name'],'slots':choices(v),'stack':v['stack']}
        for key,v in cat.get('items',{}).items() if v.get('addable') and choices(v)]

def transition(wearing, items, original, cat, operation, key=None, slots=None, mode='inventory'):
    valid(wearing,original,cat)
    wearing,items=copy.deepcopy(wearing),copy.deepcopy(items)
    def transfer(key,amount):
        item=cat['items'].get(key,{})
        entry=next((v for v in items if v.get('m')==key),None)
        if not item or not item.get('addable') or type(item.get('stack')) is not int:
            raise ValueError('该衣装不能转入仓库：'+key)
        n=(entry.get('c',0) if entry else 0)+amount
        if type(n) is not int or not 0<=n<=item['stack']:raise ValueError('仓库数量不足或返还后超出上限：'+key)
        if n==0:
            if entry:items.remove(entry)
        elif entry:entry['c']=n
        else:items.append({'m':key,'c':n})
    def remove(value):
        transfer(value['ItemMstID'],1);wearing.remove(value)
    if operation=='unequip':
        value=next((v for v in wearing if v['ItemMstID']==key and sorted(v['Slots'])==sorted(slots or [])),None)
        if value is None:raise ValueError('该衣装未穿戴')
        remove(value)
    elif operation=='equip':
        item=cat['items'].get(key,{})
        if not item.get('addable') or slots not in choices(item):raise ValueError('衣装或槽位无效')
        if mode not in ('inventory','new'):raise ValueError('未知衣装来源')
        # Return conflicting garments before equipping the replacement.
        for value in list(wearing):
            if set(value['Slots']).intersection(slots):remove(value)
        if mode=='inventory':transfer(key,-1)
        wearing.append({'ItemMstID':key,'Slots':list(slots)})
    else:raise ValueError('未知换装操作')
    valid(wearing,original,cat)
    return {'wearing':wearing,'items':items}
