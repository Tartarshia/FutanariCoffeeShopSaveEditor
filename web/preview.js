'use strict';
// Small WebGL 2 viewer; local game resources are provided by a background worker.
class MaidPreview {
 constructor(canvas){
  this.canvas=canvas;this.gl=canvas.getContext('webgl2',{antialias:true,alpha:false,preserveDrawingBuffer:true});
  if(!this.gl)throw Error('浏览器未提供 WebGL 2，请启用硬件加速后重试');
  this.parts=[];this.textures=[];this.buffers=[];this.yaw=0;this.pitch=0.08;this.distance=5.6;this.target=[0,1.35,0];this.values={};this.closed=false;this.ready=false;canvas.dataset.loaded='false';
  const gl=this.gl,vs=`#version 300 es
  precision highp float;
  in vec3 position;in vec3 normal;in vec2 uv;in vec2 uv1;uniform mat4 camera;
  out vec3 N;out vec3 P;out vec2 U;out vec2 V;
  void main(){P=position;N=normal;U=uv;V=uv1;gl_Position=camera*vec4(position,1.0);}`,
  fs=`#version 300 es
  precision highp float;
  in vec3 N;in vec3 P;in vec2 U;in vec2 V;out vec4 result;
  uniform vec4 tint;uniform vec3 shadow;uniform vec3 rim;uniform vec3 outline;uniform vec3 highlight;uniform vec3 eyePosition;
  uniform sampler2D mainTex;uniform sampler2D layer0;uniform sampler2D layer1;uniform sampler2D layer2;uniform sampler2D layer3;uniform sampler2D layer4;
  uniform vec4 color0;uniform vec4 color1;uniform vec4 color2;uniform vec4 color3;uniform vec4 color4;uniform int eyeLayer;uniform int lipUV;uniform vec4 lipShadow;uniform ivec3 masks;uniform ivec2 masksExtra;
  vec3 overlay(vec3 base,vec4 tex,vec4 color,int mask){float a=mask==1?tex.r:tex.a;return mix(base,color.rgb,a*color.a);}
  void main(){vec4 tex=texture(mainTex,U);float alpha=tex.a*tint.a;if(alpha<0.04)discard;
   vec3 base=tex.rgb*tint.rgb; if(eyeLayer>0){float gain=eyeLayer==2?1.0:2.0;result=vec4(base*gain,min(alpha*gain,1.0));return;}
   base=overlay(base,texture(layer0,lipUV==1?V:U),mix(lipShadow,color0,smoothstep(-0.15,0.35,dot(normalize(N),normalize(vec3(-0.3,0.7,1.0))))),masks.x);base=overlay(base,texture(layer1,U),color1,masks.y);base=overlay(base,texture(layer2,U),color2,masks.z);
   base=overlay(base,texture(layer3,U),color3,masksExtra.x);base=overlay(base,texture(layer4,U),color4,masksExtra.y);
   vec3 n=normalize(N);float light=dot(n,normalize(vec3(-0.3,0.7,1.0)));float shade=smoothstep(-0.15,0.35,light);
   vec3 shaded=mix(base*mix(vec3(0.68),shadow,0.22),base,shade);float edge=pow(1.0-max(dot(n,normalize(eyePosition-P)),0.0),4.0);
   float spec=pow(max(dot(reflect(-normalize(vec3(-0.3,0.7,1.0)),n),normalize(eyePosition-P)),0.0),35.0);
   result=vec4(mix(shaded,outline,edge*0.22)+rim*edge*0.08+highlight*spec*0.08,alpha);}`;
  const shader=(type,text)=>{const s=gl.createShader(type);gl.shaderSource(s,text);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
  this.program=gl.createProgram();const a=shader(gl.VERTEX_SHADER,vs),b=shader(gl.FRAGMENT_SHADER,fs);gl.attachShader(this.program,a);gl.attachShader(this.program,b);gl.linkProgram(this.program);gl.deleteShader(a);gl.deleteShader(b);if(!gl.getProgramParameter(this.program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(this.program));
  this.uniform={};for(const name of ['camera','tint','shadow','rim','outline','highlight','eyePosition','mainTex','layer0','layer1','layer2','layer3','layer4','color0','color1','color2','color3','color4','masks','masksExtra','lipUV','lipShadow','eyeLayer'])this.uniform[name]=gl.getUniformLocation(this.program,name);
  this.attribute={};for(const name of ['position','normal','uv','uv1'])this.attribute[name]=gl.getAttribLocation(this.program,name);
  this.white=this.makeTexture(null,[255,255,255,255]);this.clear=this.makeTexture(null,[0,0,0,0]);
  this.events=new AbortController();const opt={signal:this.events.signal};let drag=null;
  canvas.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);},opt);
  canvas.addEventListener('pointermove',e=>{if(!drag)return;this.yaw+=(e.clientX-drag[0])*0.009;this.pitch=Math.max(-1.2,Math.min(1.2,this.pitch+(e.clientY-drag[1])*0.006));drag=[e.clientX,e.clientY];this.draw();},opt);
  canvas.addEventListener('pointerup',()=>{drag=null;},opt);canvas.addEventListener('pointercancel',()=>{drag=null;},opt);
  canvas.addEventListener('wheel',e=>{e.preventDefault();this.distance=Math.max(0.45,Math.min(12,this.distance*Math.exp(e.deltaY*0.001)));this.draw();},{...opt,passive:false});
  this.observer=new ResizeObserver(()=>this.draw());this.observer.observe(canvas);
 }
 makeTexture(image,pixel){const gl=this.gl,t=gl.createTexture();this.textures.push(t);gl.bindTexture(gl.TEXTURE_2D,t);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);if(image)gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,image);else gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,1,1,0,gl.RGBA,gl.UNSIGNED_BYTE,new Uint8Array(pixel));gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);return t;}
 buffer(data,target=this.gl.ARRAY_BUFFER){const gl=this.gl,b=gl.createBuffer();this.buffers.push(b);gl.bindBuffer(target,b);gl.bufferData(target,data,gl.DYNAMIC_DRAW);return b;}
 async load(manifest,url,headers){
  this.manifest=manifest;const textures=new Map(),gl=this.gl;
  const texture=async name=>{if(!name)return null;if(textures.has(name))return textures.get(name);const task=new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(this.closed?null:this.makeTexture(image));image.onerror=()=>reject(Error('无法读取本机模型贴图'));image.src=url(name);});textures.set(name,task);return task;};
  for(const part of manifest.parts){
   const response=await fetch(url(part.file),{headers});if(!response.ok)throw Error('读取模型网格失败');const raw=await response.arrayBuffer(),size=new DataView(raw).getUint32(0,true);if(size>65536||size+4>raw.byteLength)throw Error('模型网格头无效');const meta=JSON.parse(new TextDecoder().decode(new Uint8Array(raw,4,size))),start=4+size,arrays={};
   for(const [key,f] of Object.entries(meta.fields)){const end=start+f.offset+f.count*4;if(!Number.isInteger(f.count)||f.count<0||end>raw.byteLength)throw Error('模型缓冲区边界无效');const slice=raw.slice(start+f.offset,end);arrays[key]=f.type==='I'?new Uint32Array(slice):new Float32Array(slice);}
   if(this.closed)return;
   const materials=[];for(const m of part.materials){const overlays=[];for(const layer of m.overlays)overlays.push({...layer,glTexture:await texture(layer.texture)});materials.push({...m,glTexture:await texture(m.texture),overlays});}
   if(this.closed)return;
   this.parts.push({...part,meta,arrays,materials,positionBuffer:this.buffer(arrays.positions),normalBuffer:this.buffer(arrays.normals),uvBuffer:this.buffer(arrays.uv),uv1Buffer:this.buffer(arrays.uv1||arrays.uv),indexBuffer:this.buffer(arrays.indices,gl.ELEMENT_ARRAY_BUFFER)});
  }
  this.ready=true;this.update(this.values);this.canvas.dataset.hair=manifest.hair;this.canvas.dataset.loaded='true';
 }
 update(values){
  this.values=values;if(!this.manifest||this.closed)return;const gl=this.gl;
  for(const part of this.parts){const result=new Float32Array(part.arrays.positions);
   for(const [key,shape] of Object.entries(part.meta.shapes)){let weight=key==='breasts_size'||key==='clothes_breasts_size'?(values.BreastSize||0):key==='breasts_with_bras'?(this.manifest.tied?100:0):key==='wear_high_heel'?(this.manifest.heel?100:0):key.startsWith('pointed_ears')?this.manifest.ear[Number(key.slice(-1))-1]:0;
    const data=part.arrays[shape.field];weight/=shape.weight||100;for(let i=0;i<result.length;i++)result[i]+=data[i]*weight;
   }
   gl.bindBuffer(gl.ARRAY_BUFFER,part.positionBuffer);gl.bufferSubData(gl.ARRAY_BUFFER,0,result);
  }this.draw();
 }
 focus(mode){this.yaw=0;this.pitch=0.05;this.target=mode==='face'?[0,2.48,0]:mode==='upper'?[0,2.05,0]:[0,1.35,0];this.distance=mode==='face'?1.05:mode==='upper'?2.55:5.6;this.draw();}
 draw(){
  if(this.closed)return;const gl=this.gl,canvas=this.canvas,ratio=Math.min(devicePixelRatio||1,2),w=Math.max(1,Math.round(canvas.clientWidth*ratio)),h=Math.max(1,Math.round(canvas.clientHeight*ratio));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}gl.viewport(0,0,w,h);gl.clearColor(0.12,0.15,0.18,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);if(!this.manifest||!this.ready)return;
  gl.useProgram(this.program);gl.enable(gl.DEPTH_TEST);gl.depthMask(true);gl.depthFunc(gl.LEQUAL);gl.disable(gl.CULL_FACE);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
  const eye=[Math.sin(this.yaw)*Math.cos(this.pitch)*this.distance,this.target[1]+Math.sin(this.pitch)*this.distance,Math.cos(this.yaw)*Math.cos(this.pitch)*this.distance],camera=MaidPreview.multiply(MaidPreview.perspective(w/h),MaidPreview.lookAt(eye,this.target));gl.uniformMatrix4fv(this.uniform.camera,false,camera);gl.uniform3fv(this.uniform.eyePosition,eye);
  const color=(key,otherwise)=>this.values[key]||otherwise;
  const rank=p=>p.name==='eyeballs_bg'?1:p.name==='eyeballs'?2:p.name==='eyeballs_front'?3:p.name==='eyebrows'?4:0;const ordered=[...this.parts].sort((a,b)=>rank(a)-rank(b));
  for(const part of ordered){
   for(const [key,b,size] of [['position',part.positionBuffer,3],['normal',part.normalBuffer,3],['uv',part.uvBuffer,2],['uv1',part.uv1Buffer,2]]){gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.enableVertexAttribArray(this.attribute[key]);gl.vertexAttribPointer(this.attribute[key],size,gl.FLOAT,false,0,0);}gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,part.indexBuffer);
   for(let i=0;i<part.materials.length;i++){const m=part.materials[i],sub=part.meta.submeshes[i],mapping={skin:'SkinColor',face:'SkinColor',hair:'HairMainColor',hair2:'Hair2_MainColor',eye:'Eye',eye_bg:'EyeBg',eye_high:null,brow:'Eyebrow',lash:'Eyelash',nail:'NailColor'},key=mapping[m.kind],tint=key?color(key,m.color):m.color;
    const eyeLayer=['eye','eye_bg','eye_high','lash','brow'].includes(m.kind);gl.uniform1i(this.uniform.eyeLayer,m.kind==='eye_high'?2:eyeLayer?1:0);gl.depthMask(!eyeLayer);gl.blendFunc(gl.SRC_ALPHA,m.kind==='eye_high'?gl.ONE:gl.ONE_MINUS_SRC_ALPHA);
    const shadowKey=m.kind.startsWith('hair')?(m.kind==='hair2'?'Hair2_ShadowColor':'HairShadowColor'):m.kind==='skin'||m.kind==='face'?'SkinShadowColor':null;
    const rimKey=m.kind.startsWith('hair')?(m.kind==='hair2'?'Hair2_RimLightColor':'HairRimLightColor'):'SkinRimLightColor';
    const outlineKey=m.kind.startsWith('hair')?(m.kind==='hair2'?'Hair2_OutlineColor':'HairOutlineColor'):null,highlightKey=m.kind.startsWith('hair')?(m.kind==='hair2'?'Hair2_HighlightColor':'HairHighlightColor'):null;gl.uniform3fv(this.uniform.outline,outlineKey?color(outlineKey,[0.1,0.1,0.1,1]).slice(0,3):[0.1,0.1,0.1]);gl.uniform3fv(this.uniform.highlight,highlightKey?color(highlightKey,[0,0,0,1]).slice(0,3):[0,0,0]);
    gl.uniform4fv(this.uniform.tint,tint);gl.uniform3fv(this.uniform.shadow,(shadowKey?color(shadowKey,[0.8,0.8,0.8,1]):[0.8,0.8,0.8]).slice(0,3));gl.uniform3fv(this.uniform.rim,color(rimKey,[0,0,0,1]).slice(0,3));
    gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,m.glTexture||this.white);gl.uniform1i(this.uniform.mainTex,0);const masks=[];const first=m.overlays[0];gl.uniform1i(this.uniform.lipUV,first?.uv||0);gl.uniform4fv(this.uniform.lipShadow,first?color(first.shadow||first.color,[1,1,1,1]):[0,0,0,0]);
    for(let j=0;j<5;j++){const layer=m.overlays[j];gl.activeTexture(gl.TEXTURE0+j+1);gl.bindTexture(gl.TEXTURE_2D,layer?.glTexture||this.clear);gl.uniform1i(this.uniform['layer'+j],j+1);gl.uniform4fv(this.uniform['color'+j],layer?color(layer.color,[1,1,1,1]):[0,0,0,0]);masks.push(layer?.mask==='r'?1:0);}gl.uniform3iv(this.uniform.masks,masks.slice(0,3));gl.uniform2iv(this.uniform.masksExtra,masks.slice(3,5));gl.drawElements(gl.TRIANGLES,sub.count,gl.UNSIGNED_INT,sub.start*4);
   }
  }
  gl.depthMask(true);this.canvas.dataset.parts=this.parts.length;this.canvas.dataset.glError=gl.getError();
 }
 destroy(){this.closed=true;this.events.abort();this.observer.disconnect();for(const b of this.buffers)this.gl.deleteBuffer(b);for(const t of this.textures)this.gl.deleteTexture(t);this.gl.deleteProgram(this.program);}
 static multiply(a,b){const out=new Float32Array(16);for(let c=0;c<4;c++)for(let r=0;r<4;r++)out[c*4+r]=[0,1,2,3].reduce((s,k)=>s+a[k*4+r]*b[c*4+k],0);return out;}
 static perspective(aspect){const f=1/Math.tan(Math.PI/8),n=0.01,z=100;return new Float32Array([f/aspect,0,0,0,0,f,0,0,0,0,(z+n)/(n-z),-1,0,0,2*z*n/(n-z),0]);}
 static lookAt(eye,target){const norm=a=>{const n=Math.hypot(...a)||1;return a.map(v=>v/n);},cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],z=norm(eye.map((v,i)=>v-target[i])),x=norm(cross([0,1,0],z)),y=cross(z,x),dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);return new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1]);}
}
