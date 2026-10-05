"""Prepare selected real game meshes/textures in a background process."""
import hashlib
import json
from pathlib import Path
import shutil
import os
import tempfile
import codec
import game_data
import appearance
import wardrobe
import unity_preview as unity

def build(folder,output,idx,game=None,selected=None,wearing=None):
    folder,output=Path(folder),Path(output)
    cat=codec.catalogue(folder)
    meta=json.loads((folder/'meta.json').read_text(encoding='utf8'))
    install=game_data.find_install(meta['source'],game)
    if game_data.fingerprint(install/'cs_Data/Managed/Assembly-CSharp.dll')!=cat.get('assembly'):
        raise ValueError('Game version changed; reopen the save')
    with codec.connection(folder/'index.sqlite') as db:
        if not appearance.supported(db,idx,cat):raise ValueError('此角色模型尚不支持 3D 预览')
        colors={k:appearance.scalar(db,f'/Charas/{idx}/Looks/Colors/{k}') for k in appearance.SELECTORS}
        for key,value in (selected or {}).items():
            if key not in appearance.SELECTORS:raise ValueError('Unknown preview selector')
            choices=cat['appearance'][appearance.SELECTORS[key][1]]
            if value not in [v['id'] for v in choices]:raise ValueError('Unknown preview appearance ID')
            colors[key]=value
        original=codec.read_node(folder,f'/Charas/{idx}/Looks/WearingClothes',db)
        wearing=original if wearing is None else wearing
        wardrobe.valid(wearing,original,cat)
    for key,value in colors.items():
        if value not in [v['id'] for v in cat['appearance'][appearance.SELECTORS[key][1]]]:
            raise ValueError('Unknown original appearance ID; select a supported value: '+key)
    output.mkdir(parents=True,exist_ok=False)
    data=install/'cs_Data'
    source_signature=json.dumps([(p.name,p.stat().st_size,p.stat().st_mtime_ns)
        for p in (data/'resources.assets',data/'resources.assets.resS')])
    cache=folder.parent.parent/'preview-cache'/hashlib.sha256(source_signature.encode()).hexdigest()[:16]
    assets=unity.Assets(install,cache)
    try:
        warnings=[];textures={};parts=[];total=0
        def texture(pid):
            if not pid:return None
            if pid in textures:return textures[pid]
            name='texture_'+str(pid)+'.png'
            cached=cache/name
            if not cached.exists():
                info=assets.read(pid)
                pixels=unity.decode_texture(info['width'],info['height'],info['format'],assets.texture_data(info))
                raw=unity.png(info['width'],info['height'],pixels)
                # Each worker may compute the same immutable texture concurrently.
                with tempfile.NamedTemporaryFile(dir=cache,delete=False) as out:
                    temp=Path(out.name);out.write(raw)
                try:
                    try:os.link(temp,cached)
                    except FileExistsError:pass
                finally:temp.unlink()
            shutil.copyfile(cached,output/name)
            textures[pid]=name
            return name
        customs={category:{v['id']:v for v in cat['appearance'][category]}
                 for category in ('EarType','EyeType','EyeHighType','TattooType')}
        def selected_texture(key):
            choice=customs[appearance.SELECTORS[key][1]][colors[key]]
            pid=assets.named(28,choice['texture']) if choice['texture'] else 0
            if not pid and choice['texture']:warnings.append('纹理缺失：'+key)
            return texture(pid)
        dynamic={key:selected_texture(key) for key in ('EyeTex','EyeHighLightTex','Tattoo1Tex','Tattoo2Tex')}
        ear=customs['EarType'][colors['EarType']]['params']
        ear_weights=[int(ear.get('int_value'+str(i),0)) for i in (1,2,3)]
        tied=False;heel=False;clothes_materials={}
        prefabs=[('new_chara_body','body',None)]
        hair=next(v for v in cat['appearance']['hair'] if v['id']==colors['HairModel'])
        prefabs.extend((v,'hair',None) for v in hair['prefabs'])
        for v in wearing:
            item=cat['items'].get(v.get('ItemMstID'),{})
            if not item.get('model'):warnings.append('服装模型缺失：'+str(v.get('ItemMstID')));continue
            states=item.get('clothes',{}).get('SetWearStates','')
            tied=tied or 'TieBreasts' in states
            heel=heel or 'WearHighHeel' in states
            name=item['model']
            # Separate left/right accessory prefabs are identified by their slots.
            occupied=set(game_data.strings(item.get('clothes',{}).get('OccupiedSlots','')))
            if occupied in ({'SArm_Left','SArm_Right'},{'SWrist_Left','SWrist_Right'},{'SThighs_Left','SThighs_Right'}):
                slot=v.get('Slots',[None])[0]
                name+= '_right' if slot in (32,34,36) else '_left'
            clothes_materials[name]=game_data.strings(item.get('clothes',{}).get('Mat',''))
            prefabs.append((name,'clothes',v))
        for prefab,category,garment in prefabs:
            try:objects=assets.prefab(prefab)
            except ValueError:
                if category!='clothes':raise
                warnings.append('尚未支持的服装模型：'+prefab);continue
            for obj in objects:
                r=obj['renderer'];m=assets.read(r['mesh']);name='part_'+str(len(parts))+'.mesh'
                # The sclera renderer has a nontrivial import transform. Its
                # visible position comes from bone matrices and inverse binds.
                bones=obj['bone_transforms'] if category=='body' and obj['name']=='eyeballs_bg' else None
                payload=unity.mesh_payload(m,obj['transform'],bones);total+=len(payload)
                if total>32*1048576:raise ValueError('Preview model exceeds bounds')
                (output/name).write_bytes(payload)
                materials=[]
                for material_index,pid in enumerate(r['materials']):
                    if category=='clothes' and material_index<len(clothes_materials.get(prefab,[])):
                        pid=assets.named(21,clothes_materials[prefab][material_index])
                    if not pid:raise ValueError('Preview material is missing: '+prefab)
                    mat=assets.read(pid);mn=mat['name'];tex=mat['textures']
                    def texfile(key):return texture(tex.get(key,{}).get('id',0))
                    kind='static'
                    if category=='hair':kind='hair2' if '2color' in mn else 'hair'
                    elif category=='body':
                        if 'body' in mn or 'jj' in mn:kind='skin'
                        elif 'face' in mn:kind='face'
                        elif 'eyebrows' in mn:kind='brow'
                        elif 'eyelash' in mn:kind='lash'
                        elif 'eye_highlight' in mn:kind='eye_high'
                        elif 'eye_white' in mn:kind='eye_bg'
                        elif 'eye' in mn:kind='eye'
                        elif 'nail' in mn:kind='nail'
                    primary=dynamic['EyeTex'] if kind=='eye' else dynamic['EyeHighLightTex'] if kind=='eye_high' else texfile('_MainTex') or texfile('_BaseMap')
                    color=next((mat['colors'][key] for key in ('_Color','_BaseColor','_TintColor') if key in mat['colors']),[1,1,1,1])
                    if kind=='eye_high':color=mat['colors'].get('_TintColor',color)
                    overlays=[]
                    if kind=='face':
                        overlays=[{'texture':texfile('_Lips_Mask_Tex'),'color':'LipsColor','mask':'a','uv':1,'shadow':'LipsShadowColor'},
                            {'texture':texture(assets.named(28,'eye_makeup_mask_tex1')),'color':'Eyeshadow1Color','mask':'a'},
                            {'texture':texture(assets.named(28,'eye_makeup_mask_tex2')),'color':'Eyeshadow2Color','mask':'a'},
                            {'texture':dynamic['Tattoo1Tex'],'color':'Tattoo1Color','mask':'a'},
                            {'texture':dynamic['Tattoo2Tex'],'color':'Tattoo2Color','mask':'a'}]
                    if kind=='skin':overlays=[{'texture':texfile('_Sub_Tex'),'color':'NippleColor','mask':'a'}]
                    materials.append({'kind':kind,'texture':primary,'color':color,'overlays':overlays})
                if len(materials)!=len(m['submeshes']):raise ValueError('Material / submesh mismatch')
                parts.append({'name':obj['name'],'category':category,'file':name,'materials':materials,
                    'geometry':hashlib.sha256(payload).hexdigest(),
                    'garment':garment,'tied': 'TieBreasts' in (cat['items'].get(garment['ItemMstID'],{}).get('clothes',{}).get('SetWearStates','')) if garment else False,
                    'heel': 'WearHighHeel' in (cat['items'].get(garment['ItemMstID'],{}).get('clothes',{}).get('SetWearStates','')) if garment else False})
        if len(parts)>100:raise ValueError('Too many preview parts')
        manifest={'parts':parts,'resources':cache.name,'hair':colors['HairModel'],'ear':ear_weights,'tied':tied,'heel':heel,
            'warnings':warnings,'note':'真实游戏网格与贴图；静止绑定姿势。浏览器使用近似光照，未复刻 Unity 动画、物理与完整着色器。'}
        if source_signature!=json.dumps([(p.name,p.stat().st_size,p.stat().st_mtime_ns)
                for p in (data/'resources.assets',data/'resources.assets.resS')]):
            raise ValueError('Game resources changed during preview preparation')
        return manifest
    finally:assets.close()
