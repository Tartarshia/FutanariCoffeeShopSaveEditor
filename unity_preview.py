"""Bounded, read-only readers for the supported Unity 6000.3 preview objects.

Own implementation: selected objects are sought in the user's local assets.
No Unity library, resource catalogue or third-party code is distributed.
"""
import json
import math
from pathlib import Path
import sqlite3
import struct
import zlib
import unity_assets

def count(r, limit=1000000):
    n,=r.unpack('i')
    if not 0<=n<=limit:raise ValueError('Preview array exceeds bounds')
    return n

def pointer(r):
    file_id,pid=r.unpack('iq')
    if file_id!=0:raise ValueError('External preview object is unsupported')
    return pid

def blob(r,limit=32*1048576):
    data=r.read(count(r,limit));r.align();return data

def vector(r,size,limit=1000000):
    data=r.read(count(r,limit)*size);r.align();return data

def gameobject(r):
    components=[pointer(r) for _ in range(count(r,256))]
    r.align();r.read(4)
    name=r.string(500);r.read(3)
    return {'name':name,'components':components}

def transform(r):
    obj=pointer(r);q=r.unpack('4f');t=r.unpack('3f');s=r.unpack('3f');r.align()
    children=[pointer(r) for _ in range(count(r,2000))];r.align()
    return {'object':obj,'rotation':q,'position':t,'scale':s,'children':children,'parent':pointer(r)}

def renderer(r):
    obj=pointer(r)
    r.read(13);r.align();r.read(2);r.align();r.read(48)
    materials=[pointer(r) for _ in range(count(r,32))];r.align()
    r.read(48);r.align();r.read(8);r.read(2);r.align()
    mesh=pointer(r)
    bones=[pointer(r) for _ in range(count(r,512))];r.align()
    weights=list(r.unpack(str(count(r,256))+'f'));r.align()
    root=pointer(r);r.read(24);r.read(1);r.align()
    return {'object':obj,'mesh':mesh,'materials':materials,'weights':weights,'bones':bones,'root':root}

def material(r):
    name=r.string(500);r.read(12)  # shader code is not loaded by the browser
    for _ in range(2):
        for __ in range(count(r,256)):r.string(500)
        r.align()
    r.read(4);r.read(2);r.align();r.read(4)
    for _ in range(count(r,256)):r.string(500);r.string(500)
    for _ in range(count(r,256)):r.string(500)
    textures={}
    for _ in range(count(r,64)):
        key=r.string(500);file_id,pid=r.unpack('iq')
        textures[key]={'id':pid if file_id==0 else 0,'scale':r.unpack('2f'),'offset':r.unpack('2f')}
    ints={r.string(500):r.unpack('i')[0] for _ in range(count(r,256))}
    floats={r.string(500):r.unpack('f')[0] for _ in range(count(r,256))}
    colors={r.string(500):r.unpack('4f') for _ in range(count(r,64))}
    for _ in range(count(r,64)):r.string(500);r.string(500)
    return {'name':name,'textures':textures,'colors':colors,'floats':floats,'ints':ints}

def texture(r):
    name=r.string(500);r.read(1);r.align()
    width,height,size,stripped,fmt,mips=r.unpack('6i')
    if not 1<=width<=4096 or not 1<=height<=4096:raise ValueError('Texture dimensions exceed bounds')
    r.read(3);r.align();r.string(500);r.read(1);r.align();r.read(12+24+8)
    blob(r,1048576);inline=blob(r,32*1048576)
    offset,stream_size=r.unpack('QI');path=r.string(500)
    return {'name':name,'width':width,'height':height,'format':fmt,'inline':inline,
            'offset':offset,'size':stream_size,'path':path}

def mesh(r):
    name=r.string(500)
    subs=[]
    for _ in range(count(r,32)):
        first,n,topology,base,vfirst,vcount=r.unpack('IIiIII');r.read(24)
        if topology!=0 or n%3:raise ValueError('Only triangle preview meshes are supported')
        subs.append({'first':first,'count':n,'base':base})
    r.align()
    raw_shapes=vector(r,40,500000)
    frames=[]
    for _ in range(count(r,256)):
        first,n=r.unpack('II');r.read(2);r.align();frames.append((first,n))
    channels=[]
    for _ in range(count(r,256)):
        key=r.string(500);_,frame,n=r.unpack('Iii');channels.append((key,frame,n))
    weights=list(r.unpack(str(count(r,256))+'f'));r.align()
    bind_raw=vector(r,64,512)
    bindposes=[]
    for at in range(0,len(bind_raw),64):
        values=struct.unpack_from('<16f',bind_raw,at)
        bindposes.append(list(values))
    vector(r,4,512);r.read(4);vector(r,24,512);vector(r,4,1000000)
    compression,_,_,_=r.unpack('4B');r.align()
    if compression:raise ValueError('Compressed preview meshes are unsupported')
    index_format,=r.unpack('i');indices=blob(r)
    n,=r.unpack('I')
    if not 0<n<=200000:raise ValueError('Too many preview vertices')
    channel_count=count(r,16)
    attrs=[r.unpack('4B') for _ in range(channel_count)];r.align();data=blob(r)
    # The supported asset uses ordinary vertex buffers, not compressed vectors.
    for is_float in [True,True,True,True,False,False,False,True,False,False]:
        packed_count,=r.unpack('I')
        if packed_count:raise ValueError('Packed preview vertex buffers are unsupported')
        if is_float:r.read(8)
        blob(r);r.read(1);r.align()
    r.read(4+24+8);blob(r);blob(r);r.read(8);offset,size=r.unpack('QI');path=r.string(500)
    if size or offset or path:raise ValueError('Streamed preview mesh buffers are unsupported')
    # Unity 6000.3 MeshLodInfo follows the stream header.
    r.read(8);r.read(4);r.align()
    for _ in range(count(r,32)):vector(r,8,32)
    r.align()
    return {'name':name,'submeshes':subs,'vertices':n,'channels':attrs,'data':data,
            'index_format':index_format,'indices':indices,'shape_bytes':raw_shapes,
            'frames':frames,'shapes':channels,'weights':weights,'bindposes':bindposes}

PARSERS={1:gameobject,4:transform,137:renderer,21:material,28:texture,43:mesh}

class Assets:
    def __init__(self,game,cache):
        self.path=Path(game)/'cs_Data/resources.assets'
        cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(cache/'objects.sqlite',timeout=60)
        self.db.execute('CREATE TABLE IF NOT EXISTS objects (id INTEGER PRIMARY KEY,class INTEGER,start INTEGER,length INTEGER,name TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS metadata (signature TEXT)')
        signature=json.dumps([str(self.path.resolve()),self.path.stat().st_size,self.path.stat().st_mtime_ns])
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT signature FROM metadata').fetchone()
            if not row or row[0]!=signature:
                self.db.execute('DELETE FROM objects');self.db.execute('DELETE FROM metadata')
                batch=[]
                with self.path.open('rb') as f:
                    for pid,cid,start,length in unity_assets.objects(self.path):
                        name=''
                        if cid in (1,43,21,28):
                            f.seek(start);r=unity_assets.Reader(f,start+length)
                            if cid==1:r.read(count(r,256)*12+4)
                            name=r.string(500)
                        batch.append((pid,cid,start,length,name))
                        if len(batch)>=1000:self.db.executemany('INSERT INTO objects VALUES (?,?,?,?,?)',batch);batch=[]
                self.db.executemany('INSERT INTO objects VALUES (?,?,?,?,?)',batch)
                self.db.execute('CREATE INDEX IF NOT EXISTS names ON objects(class,name)')
                self.db.execute('INSERT INTO metadata VALUES (?)',(signature,))
            self.db.commit()
        except Exception:self.db.rollback();self.db.close();raise

    def close(self):self.db.close()

    def class_id(self,pid):
        row=self.db.execute('SELECT class FROM objects WHERE id=?',(pid,)).fetchone()
        if not row:raise ValueError('Missing preview object')
        return row[0]

    def read(self,pid):
        row=self.db.execute('SELECT class,start,length FROM objects WHERE id=?',(pid,)).fetchone()
        if not row or row[0] not in PARSERS or row[2]>32*1048576:raise ValueError('Unsupported preview object')
        with self.path.open('rb') as f:
            f.seek(row[1]);r=unity_assets.Reader(f,row[1]+row[2]);data=PARSERS[row[0]](r)
            if f.tell()!=row[1]+row[2]:raise ValueError('Unexpected preview object layout: '+str(row[0]))
        return data

    def named(self,cls,name):
        rows=self.db.execute('SELECT id FROM objects WHERE class=? AND name=? LIMIT 100',(cls,name)).fetchall()
        if cls!=1:return rows[0][0] if rows else 0
        for pid, in rows:
            go=self.read(pid)
            for component in go['components']:
                if self.class_id(component)==4 and not self.read(component)['parent']:return pid
        raise ValueError('Preview prefab not found: '+name)

    def prefab(self,name):
        root=self.named(1,name);result=[];world={};stack=[(root,identity(),0)]
        while stack:
            pid,parent,depth=stack.pop()
            if depth>32 or len(result)>100:raise ValueError('Preview hierarchy exceeds bounds')
            go=self.read(pid)
            if go['name'] in ('LOD_low','LOD_middle','jj_for_ef') or go['name'].startswith('face_flush'):continue
            tr=next((self.read(c) for c in go['components'] if self.class_id(c)==4),None)
            if tr is None:continue
            mat=parent if pid==root else multiply(parent,trs(tr))
            for c in go['components']:
                if self.class_id(c)==4:world[c]=mat
            for c in go['components']:
                if self.class_id(c)==137:
                    result.append({'name':go['name'],'renderer':self.read(c),'transform':mat})
            for child in tr['children']:
                if self.class_id(child)==4:
                    stack.append((self.read(child)['object'],mat,depth+1))
        def bone_world(pid,depth=0):
            if pid in world:return world[pid]
            if depth>64:raise ValueError('Preview bone hierarchy exceeds bounds')
            tr=self.read(pid)
            if not tr['parent']:raise ValueError('Preview bone is outside the prefab')
            world[pid]=multiply(bone_world(tr['parent'],depth+1),trs(tr))
            return world[pid]
        for part in result:
            if part['name']=='eyeballs_bg':
                part['bone_transforms']=[bone_world(bone) for bone in part['renderer']['bones']]
        return result

    def texture_data(self,info):
        if info['inline']:return info['inline']
        path=(self.path.parent/info['path']).resolve()
        if path.parent!=self.path.parent.resolve() or not 0<info['size']<=32*1048576 or info['offset']+info['size']>path.stat().st_size:
            raise ValueError('Texture stream bounds exceeded')
        with path.open('rb') as f:f.seek(info['offset']);data=f.read(info['size'])
        if len(data)!=info['size']:raise ValueError('Truncated texture stream')
        return data

def identity():return [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]

def multiply(a,b):return [sum(a[row*4+k]*b[k*4+col] for k in range(4)) for row in range(4) for col in range(4)]

def trs(tr):
    x,y,z,w=tr['rotation'];sx,sy,sz=tr['scale'];tx,ty,tz=tr['position']
    return [(1-2*y*y-2*z*z)*sx,(2*x*y-2*z*w)*sy,(2*x*z+2*y*w)*sz,tx,
        (2*x*y+2*z*w)*sx,(1-2*x*x-2*z*z)*sy,(2*y*z-2*x*w)*sz,ty,
        (2*x*z-2*y*w)*sx,(2*y*z+2*x*w)*sy,(1-2*x*x-2*y*y)*sz,tz,0,0,0,1]

def apply(mat,v,delta=False):
    return [sum(mat[i*4+k]*v[k] for k in range(3))+(0 if delta else mat[i*4+3]) for i in range(3)]

def vertex_channels(m,skin=False):
    sizes={0:4,1:2,2:1,3:1,4:2,5:2,6:1,7:1,8:2,9:2,10:4,11:4}
    stride={}
    for stream,offset,fmt,dim in m['channels']:
        if not dim:continue
        if fmt not in sizes or not 1<=dim<=4:raise ValueError('Unsupported preview vertex format')
        stride[stream]=max(stride.get(stream,0),offset+sizes[fmt]*dim)
    streams={};base=0
    for stream,s in sorted(stride.items()):streams[stream]=base;base=(base+s*m['vertices']+15)&~15
    if base>len(m['data'])+15:raise ValueError('Vertex buffer bounds exceeded')
    result={}
    for idx in ((0,1,4,5,12,13) if skin else (0,1,4,5)):
        if idx>=len(m['channels']):continue
        stream,offset,fmt,dim=m['channels'][idx]
        if not dim:continue
        if fmt not in (0,1,10):raise ValueError('Unsupported position/normal/UV format')
        values=[];form='<'+{0:'f',1:'e',10:'I'}[fmt]*dim
        for i in range(m['vertices']):values.extend(struct.unpack_from(form,m['data'],streams[stream]+i*stride[stream]+offset))
        result[idx]=values
    if 0 not in result or len(result[0])!=m['vertices']*3:raise ValueError('Missing preview positions')
    return result

def mesh_payload(m,mat,bones=None):
    channels=vertex_channels(m,bones is not None);n=m['vertices'];positions=[];normals=[]
    matrices=None
    if bones is not None:
        binds=m.get('bindposes',[])
        bone_indices=channels.get(13,[])
        influences=len(bone_indices)//n
        bone_weights=channels.get(12,[1.0]*n if influences==1 else [])
        if len(binds)!=len(bones) or influences not in (1,2,4) or len(bone_weights)!=n*influences or len(bone_indices)!=n*influences:
            raise ValueError('Unsupported preview bone layout')
        skin=[multiply(bone,bind) if bone is not None else None for bone,bind in zip(bones,binds)]
        matrices=[]
        for i in range(n):
            current=[0.0]*16;total=0
            for weight,index in zip(bone_weights[i*influences:(i+1)*influences],bone_indices[i*influences:(i+1)*influences]):
                if weight==0:continue
                if not math.isfinite(weight) or weight<0 or index>=len(skin) or skin[index] is None:
                    raise ValueError('Invalid preview bone influence')
                total+=weight
                for k in range(16):current[k]+=skin[index][k]*weight
            if not .99<=total<=1.01:raise ValueError('Invalid preview bone weights')
            matrices.append([v/total for v in current])
    for i in range(n):positions.extend(apply(matrices[i] if matrices else mat,channels[0][3*i:3*i+3]))
    if 1 in channels:
        for i in range(n):
            normal=apply(matrices[i] if matrices else mat,channels[1][3*i:3*i+3],True);length=math.sqrt(sum(v*v for v in normal)) or 1
            normals.extend(v/length for v in normal)
    else:normals=[0.0]*(n*3)
    uv=channels.get(4,[0.0]*(n*2))
    if len(uv)!=n*2:raise ValueError('Unexpected preview UV dimensions')
    width=2 if m['index_format']==0 else 4 if m['index_format']==1 else 0
    if not width:raise ValueError('Unknown mesh index format')
    indices=[];submeshes=[]
    for sub in m['submeshes']:
        if sub['first']+sub['count']*width>len(m['indices']):raise ValueError('Mesh indices exceed buffer')
        current=struct.unpack_from('<'+('H' if width==2 else 'I')*sub['count'],m['indices'],sub['first'])
        submeshes.append({'start':len(indices),'count':len(current)})
        for v in current:
            index=v+sub['base']
            if index>=n:raise ValueError('Mesh index exceeds vertex count')
            indices.append(index)
    if 1 not in channels:
        for j in range(0,len(indices),3):
            a,b,c=[v*3 for v in indices[j:j+3]];u=[positions[b+k]-positions[a+k] for k in range(3)];v=[positions[c+k]-positions[a+k] for k in range(3)]
            cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
            for start in (a,b,c):
                for k in range(3):normals[start+k]+=cross[k]
        for i in range(n):
            length=math.sqrt(sum(v*v for v in normals[i*3:i*3+3])) or 1
            for k in range(3):normals[i*3+k]/=length
    chunks=[];offset=0;fields={}
    def add(key,values,fmt='f'):
        nonlocal offset
        raw=struct.pack('<'+str(len(values))+fmt,*values);fields[key]={'offset':offset,'count':len(values),'type':fmt};chunks.append(raw);offset+=len(raw)
    add('positions',positions);add('normals',normals);add('uv',uv);add('uv1',channels.get(5,uv));add('indices',indices,'I')
    shapes={}
    for key,frame,frame_count in m['shapes']:
        if key not in ('breasts_size','clothes_breasts_size','breasts_with_bras','pointed_ears1','pointed_ears2','pointed_ears3','wear_high_heel'):continue
        if frame_count!=1 or not 0<=frame<len(m['frames']):raise ValueError('Unsupported blend shape frames')
        first,length=m['frames'][frame];values=[0.0]*(n*3)
        if (first+length)*40>len(m['shape_bytes']):raise ValueError('Blend shape bounds exceeded')
        for i in range(first,first+length):
            row=struct.unpack_from('<9fI',m['shape_bytes'],i*40);idx=row[9]
            if idx>=n:raise ValueError('Blend shape vertex index exceeds mesh')
            values[idx*3:idx*3+3]=apply(matrices[idx] if matrices else mat,row[:3],True)
        add('shape_'+key,values);shapes[key]={'field':'shape_'+key,'weight':m['weights'][frame]}
    header={'vertices':n,'fields':fields,'submeshes':submeshes,'shapes':shapes}
    meta=json.dumps(header,separators=(',',':')).encode()
    return struct.pack('<I',len(meta))+meta+b''.join(chunks)

def decode_texture(width,height,fmt,data):
    """Decode RGB24/RGBA32, BC1 (DXT1), or BC3 (DXT5) mip zero."""
    if fmt in (3,4):
        size=width*height*(3 if fmt==3 else 4)
        if len(data)<size:raise ValueError('Truncated raw texture')
        if fmt==4:return data[:size]
        out=bytearray(width*height*4)
        for i in range(width*height):out[i*4:i*4+4]=data[i*3:i*3+3]+b'\xff'
        return bytes(out)
    if fmt not in (10,12):raise ValueError('Unsupported preview texture format '+str(fmt))
    blocksize=8 if fmt==10 else 16;bx=(width+3)//4;by=(height+3)//4
    if len(data)<bx*by*blocksize:raise ValueError('Truncated block texture')
    out=bytearray(width*height*4)
    def rgb565(v):return [(v>>11)*255//31,((v>>5)&63)*255//63,(v&31)*255//31]
    for y in range(by):
        for x in range(bx):
            start=(y*bx+x)*blocksize;offset=start+(8 if fmt==12 else 0)
            a,b,bits=struct.unpack_from('<HHI',data,offset);ca,cb=rgb565(a),rgb565(b)
            colors=[ca+[255],cb+[255]]
            if a>b or fmt==12:colors.extend([[(2*ca[k]+cb[k])//3 for k in range(3)]+[255],[(ca[k]+2*cb[k])//3 for k in range(3)]+[255]])
            else:colors.extend([[(ca[k]+cb[k])//2 for k in range(3)]+[255],[0,0,0,0]])
            if fmt==12:
                a0,a1=data[start:start+2];alphas=[a0,a1]
                if a0>a1:alphas.extend(((7-i)*a0+i*a1)//7 for i in range(1,7))
                else:alphas.extend(((5-i)*a0+i*a1)//5 for i in range(1,5));alphas.extend([0,255])
                alpha_bits=int.from_bytes(data[start+2:start+8],'little')
            for i in range(16):
                px=x*4+i%4;py=y*4+i//4
                if px>=width or py>=height:continue
                color=colors[(bits>>(2*i))&3].copy()
                if fmt==12:color[3]=alphas[(alpha_bits>>(3*i))&7]
                at=(py*width+px)*4;out[at:at+4]=bytes(color)
    return bytes(out)

def png(width,height,pixels):
    if len(pixels)!=width*height*4:raise ValueError('Invalid RGBA buffer')
    def chunk(key,data):return struct.pack('>I',len(data))+key+data+struct.pack('>I',zlib.crc32(key+data)&0xffffffff)
    # Unity raw texture rows start at the bottom; PNG starts at the top.
    rows=b''.join(b'\0'+pixels[y*width*4:(y+1)*width*4] for y in range(height-1,-1,-1))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows,6))+chunk(b'IEND',b'')
