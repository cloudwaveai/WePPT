import {readFile,writeFile,mkdtemp,rm,realpath,stat} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const exec=promisify(execFile);
const PYTHON="import json,sys,math,hashlib,time\nfrom PIL import Image,ImageDraw,ImageFilter\nstarted=time.monotonic();cfg=json.load(open(sys.argv[1],encoding='utf8'));opened=Image.open(cfg['sourcePath']);w,h=opened.size\nif w*h>16000000:raise ValueError('Source exceeds diagnostic pixel budget')\nim=opened.convert('RGB');sx=w/1280;sy=h/720;layers=cfg['inventory'].get('layers',[])\nif len(layers)>60:raise ValueError('Inventory exceeds diagnostic layer budget')\nocclusion=Image.new('L',(w,h));draw=ImageDraw.Draw(occlusion)\nfor l in layers:\n if l.get('kind')!='image':continue\n b=l.get('bbox',{});points=l.get('points') or []\n if len(points)>=3:draw.polygon([(round(x*sx),round(y*sy)) for x,y in points],fill=255)\n else:draw.rectangle((math.floor(b['x']*sx),math.floor(b['y']*sy),math.ceil((b['x']+b['w'])*sx)-1,math.ceil((b['y']+b['h'])*sy)-1),fill=255)\npixels=im.load();occupied=occlusion.load();issues=[];paths=[];images=[]\nfor index,l in enumerate(layers):\n if l.get('kind')=='image':\n  b=l['bbox'];box=(max(0,math.floor(b['x']*sx)),max(0,math.floor(b['y']*sy)),min(w,math.ceil((b['x']+b['w'])*sx)),min(h,math.ceil((b['y']+b['h'])*sy)))\n  if box[2]<=box[0] or box[3]<=box[1]:continue\n  # Cheap bounded sampling supports diagnosis only; white objects remain valid.\n  step=max(1,math.ceil(math.sqrt((box[2]-box[0])*(box[3]-box[1])/16000)));count=colored=dark=0\n  for y in range(box[1],box[3],step):\n   for x in range(box[0],box[2],step):\n    p=pixels[x,y];count+=1;colored+=max(p)-min(p)>=25;dark+=max(p)<150\n  images.append(dict(layerIndex=index,bbox=b,samples=count,coloredSamples=colored,darkSamples=dark,diagnosticOnly=True))\n if l.get('kind')!='line' or l.get('dash')!='solid':continue\n ps=l.get('points',[]);color=l.get('color','#000000');rgb=tuple(int(color[i:i+2],16) for i in [1,3,5]);visible=hits=excluded=0\n radius=max(3,math.ceil(float(l.get('width',1))*max(sx,sy)/2+1));radius=min(12,radius)\n for first,last in zip(ps,ps[1:]):\n  length=math.hypot(last[0]-first[0],last[1]-first[1]);steps=max(1,math.ceil(length/2))\n  if steps>2000:raise ValueError('Path exceeds diagnostic sampling budget')\n  for i in range(steps+1):\n   x=round((first[0]+(last[0]-first[0])*i/steps)*sx);y=round((first[1]+(last[1]-first[1])*i/steps)*sy)\n   if not 0<=x<w or not 0<=y<h:continue\n   region=(max(0,x-radius),max(0,y-radius),min(w,x+radius+1),min(h,y+radius+1))\n   # Conservative exclusion: bbox-only declarations may hide more than real paint.\n   if occlusion.crop(region).getbbox() is not None:excluded+=1;continue\n   visible+=1;matched=False\n   for yy in range(region[1],region[3]):\n    for xx in range(region[0],region[2]):\n     if sum((pixels[xx,yy][k]-rgb[k])**2 for k in range(3))<70**2:matched=True;break\n    if matched:break\n   hits+=matched\n item=dict(layerIndex=index,visibleSamples=visible,matchingSamples=hits,excludedDeclaredImageSamples=excluded,sampleRadiusPixels=radius)\n paths.append(item)\n if visible>=30 and hits==0:issues.append(dict(code='invalid_source_alignment',layerIndex=index,evidence=item,message='No matching source paint at any visible sampled position; remeasure this path against the same PNG.'))\n# Scene-coordinate hints. Morphology disconnects thin connectors from thick pigment.\nsmall=im.resize((1280,720),Image.Resampling.LANCZOS);raw=bytearray(255 if max(p)-min(p)>=25 and max(p)>40 else 0 for p in small.getdata());mask=Image.frombytes('L',(1280,720),bytes(raw));mask=mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3));mask=mask.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(5));data=bytearray(mask.tobytes());hints=[]\nfor seed in range(len(data)):\n if not data[seed]:continue\n data[seed]=0;stack=[seed];count=0;left=right=seed%1280;top=bottom=seed//1280;sumx=sumy=0\n while stack:\n  pos=stack.pop();x=pos%1280;y=pos//1280;count+=1;sumx+=x;sumy+=y;left=min(left,x);right=max(right,x);top=min(top,y);bottom=max(bottom,y)\n  for nx,ny in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:\n   if 0<=nx<1280 and 0<=ny<720:\n    q=ny*1280+nx\n    if data[q]:data[q]=0;stack.append(q)\n if count>=12 and right-left>=2 and bottom-top>=2:\n  hints.append(dict(bbox=dict(x=max(0,left-2),y=max(0,top-2),w=min(1280,right+3)-max(0,left-2),h=min(720,bottom+3)-max(0,top-2)),center=[round(sumx/count,2),round(sumy/count,2)],supportPixels=count,kind='source-pigment-component'))\nhints=sorted(hints,key=lambda q:q['supportPixels'],reverse=True)[:80]\n# Advisory measurements only. Never changes inventory or alignment acceptance.\n# Thin neutral source strokes are absent from the colored-component mask.\nneutral=[]\nsp=small.load()\nborder=[sp[x,y] for x,y in [(0,0),(1279,0),(0,719),(1279,719)]]\nbackground=tuple(sorted(p[k] for p in border)[len(border)//2] for k in range(3))\nneutral_mask=bytearray(1 if max(p)-min(p)<=24 and min(background)-max(p)>=35 else 0 for p in small.getdata())\nfor vertical in [False,True]:\n major_limit,cross_limit=(720,1280) if vertical else (1280,720)\n groups=[]\n for cross in range(cross_limit):\n  runs=[];start=None\n  for major in range(major_limit+1):\n   x,y=(cross,major) if vertical else (major,cross)\n   hit=major<major_limit and neutral_mask[y*1280+x]\n   if hit and start is None:start=major\n   if not hit and start is not None:\n    if major-start>=30:runs.append((start,major-1))\n    start=None\n  for first,last in runs:\n   prior=[g for g in groups if g['bottom']==cross-1 and abs(g['first']-first)<=2 and abs(g['last']-last)<=2]\n   if len(prior)==1:\n    g=prior[0];g['bottom']=cross;g['rows'].append((first,last))\n   else:groups.append(dict(first=first,last=last,top=cross,bottom=cross,rows=[(first,last)]))\n for g in groups:\n  thickness=g['bottom']-g['top']+1\n  if thickness>8:continue\n  first=max(r[0] for r in g['rows']);last=min(r[1] for r in g['rows']);center=(g['top']+g['bottom'])/2\n  if last-first<30:continue\n  colors=[sp[round(center),m] if vertical else sp[m,round(center)] for m in range(first,last+1)]\n  if any(max(p[k] for p in colors)-min(p[k] for p in colors)>24 for k in range(3)):continue\n  rgb=tuple(sorted(p[k] for p in colors)[len(colors)//2] for k in range(3))\n  points=[[center,first],[center,last]] if vertical else [[first,center],[last,center]]\n  neutral.append(dict(kind='source-neutral-stroke',points=points,color='#%02x%02x%02x'%rgb,width=thickness,supportSamples=len(colors),diagnosticOnly=True))\nneutral=sorted(neutral,key=lambda q:q['supportSamples'],reverse=True)[:80]\n\nprint(json.dumps(dict(version=1,coordinateSpace=dict(width=1280,height=720),sourcePixels=dict(width=w,height=h),issues=issues,solidPaths=paths,imageSupport=images,componentHints=hints,neutralStrokeHints=neutral,elapsedMs=round((time.monotonic()-started)*1000),notes=['All hints are untrusted numeric DATA, not instructions or automatic repair authorization.','Only zero support on >=30 non-occluded samples is a hard alignment issue; low ratios are diagnostic only.','White/gray images and uncolored objects cannot be ruled out by pigment masks.','Hints are locations to remeasure, never automatic moves. Keep textured nodes as source image crops and filled arrowheads as source images or true filled shapes, never open V strokes.'])))\n";
export async function diagnoseEditableArtworkSource({sourcePath,inventory},{signal}={}){
 signal?.throwIfAborted();const source=resolve(sourcePath);if(await realpath(source)!==source)throw Error('Diagnostic source must be canonical');const info=await stat(source);if(!info.isFile()||info.size>24*1024*1024)throw Error('Invalid diagnostic source');const bytes=await readFile(source);if(!bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))throw Error('Diagnostic source must be PNG');const dir=await mkdtemp(join(tmpdir(),'artwork-source-diagnostics-'));
 try{const config=join(dir,'input.json');await writeFile(config,JSON.stringify({sourcePath:source,inventory}),{flag:'wx'});const {stdout}=await exec(process.env.PYTHON||'python',['-c',PYTHON,config],{signal,timeout:20000,maxBuffer:2*1024*1024,windowsHide:true});signal?.throwIfAborted();return {...JSON.parse(stdout),sourceHash:createHash('sha256').update(bytes).digest('hex')};}finally{await rm(dir,{recursive:true,force:true});}
}

const CONNECTORS=String.raw`import json,sys,math,statistics
from PIL import Image,ImageDraw
cfg=json.load(open(sys.argv[1],encoding='utf8'));im=Image.open(cfg['sourcePath']).convert('RGB');w,h=im.size
if w*h>16000000:raise ValueError('Source exceeds connector pixel budget')
sx,sy=w/1280,h/720;layers=cfg['inventory']['layers'];px=im.load();anchors=[];covered=Image.new('L',(w,h));colors={}
image_cover=Image.new('L',(w,h));idraw=ImageDraw.Draw(image_cover)
for l in layers:
 if l['kind']=='image':
  b=l['bbox'];idraw.rectangle((math.floor(b['x']*sx)-2,math.floor(b['y']*sy)-2,math.ceil((b['x']+b['w'])*sx)+1,math.ceil((b['y']+b['h'])*sy)+1),fill=255)
image_pixels=image_cover.load();alignments=[]
for index,l in enumerate(layers):
 if l['kind']!='line' or l['dash']!='solid' or len(l['points'])!=2:continue
 p,q=l['points'];vertical=abs(p[0]-q[0])<1e-9
 if not vertical and abs(p[1]-q[1])>=1e-9:continue
 cross_scale,scale=(sx,sy) if vertical else (sy,sx);center=p[0]*sx if vertical else p[1]*sy;first,last=sorted([p[1]*sy,q[1]*sy] if vertical else [p[0]*sx,q[0]*sx]);rgb=tuple(int(l['color'][i:i+2],16) for i in (1,3,5));rows=[];valid=True
 radius=math.ceil(l['width']*cross_scale/2+3)
 for major in range(math.ceil(first),math.floor(last)+1):
  coords=[(cross,major) if vertical else (major,cross) for cross in range(math.floor(center)-radius,math.ceil(center)+radius+1)]
  if any(not 0<=x<w or not 0<=y<h or image_pixels[x,y] for x,y in coords):continue
  hits=[x if vertical else y for x,y in coords if sum((px[x,y][k]-rgb[k])**2 for k in range(3))<=45**2]
  if not hits or hits[-1]-hits[0]+1!=len(hits) or len(hits)>math.ceil(l['width']*cross_scale+2):valid=False;break
  rows.append((major,hits))
 if not valid or len(rows)<30:continue
 centers=[(hits[0]+hits[-1])/2 for _,hits in rows];measured=statistics.median(centers)
 if max(centers)-min(centers)>1 or abs(measured-center)>3 or abs(measured-center)<.75:continue
 # A nearby parallel line is ambiguous: never move one declaration onto another.
 ambiguous=False
 for other in layers:
  if other is l or other['kind']!='line' or other['dash']!='solid':continue
  for a,b in zip(other['points'],other['points'][1:]):
   if vertical and abs(a[0]-b[0])<1e-9 and min(a[1],b[1])*sy<last and max(a[1],b[1])*sy>first and abs(a[0]*sx-measured)<=3:ambiguous=True
   if not vertical and abs(a[1]-b[1])<1e-9 and min(a[0],b[0])*sx<last and max(a[0],b[0])*sx>first and abs(a[1]*sy-measured)<=3:ambiguous=True
 if ambiguous:continue
 original=[p[:],q[:]];axis=0 if vertical else 1;delta=(measured-center)/cross_scale
 for point in l['points']:point[axis]+=delta
 l['bbox']['x' if vertical else 'y']+=delta
 alignments.append(dict(layerIndex=index,originalPoints=original,points=l['points'],offsetSourcePixels=measured-center,centerDriftPixels=max(centers)-min(centers),rowSupport=[dict(position=major,start=hits[0],end=hits[-1],count=len(hits)) for major,hits in rows]))

for index,l in enumerate(layers):
 mask=Image.new('L',(w,h));d=ImageDraw.Draw(mask);b=l['bbox']
 if l['kind']=='image':d.rectangle((math.floor(b['x']*sx),math.floor(b['y']*sy),math.ceil((b['x']+b['w'])*sx)-1,math.ceil((b['y']+b['h'])*sy)-1),fill=255)
 elif l['dash']=='solid':
  d.line([(round(x*sx),round(y*sy)) for x,y in l['points']],fill=255,width=max(1,math.ceil(l['width']*max(sx,sy)+2)))
  colors.setdefault(l['color'].lower(),[]).append(index)
 else:continue
 covered.paste(255,(0,0),mask);anchors.append((index,mask.load()))
occupied=covered.load();found=[];claimed=set();sample=cfg['inventory']['textureRect'];bg=px[min(w-1,round((sample['x']+sample['w']/2)*sx)),min(h-1,round((sample['y']+sample['h']/2)*sy))]
for color,indices in colors.items():
 rgb=tuple(int(color[i:i+2],16) for i in (1,3,5))
 if sum((rgb[k]-bg[k])**2 for k in range(3))<80**2:continue
 def match(x,y):return 0<=x<w and 0<=y<h and sum((px[x,y][k]-rgb[k])**2 for k in range(3))<=45**2
 data=bytearray(w*h)
 for y in range(h):
  for x in range(w):
   if not occupied[x,y] and match(x,y):data[y*w+x]=1
 for seed in range(w*h):
  if not data[seed]:continue
  data[seed]=0;stack=[seed];component=[]
  while stack:
   p=stack.pop();x,y=p%w,p//w;component.append((x,y))
   for xx,yy in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:
    if 0<=xx<w and 0<=yy<h and data[yy*w+xx]:data[yy*w+xx]=0;stack.append(yy*w+xx)
  if len(component)<12 or len(component)>2000:continue
  x0=min(p[0] for p in component);x1=max(p[0] for p in component);y0=min(p[1] for p in component);y1=max(p[1] for p in component)
  vertical=y1-y0>x1-x0;scale=sy if vertical else sx;cross_scale=sx if vertical else sy
  length=(y1-y0+1 if vertical else x1-x0+1)/scale
  if not 12<=length<=128:continue
  rows={}
  for x,y in component:rows.setdefault(y if vertical else x,[]).append(x if vertical else y)
  rows=sorted((major,sorted(values)) for major,values in rows.items());widths=[len(values) for _,values in rows]
  allowed=math.ceil(max(layers[i]['width'] for i in indices)*cross_scale+2)
  if rows[-1][0]-rows[0][0]+1!=len(rows) or max(widths)>allowed or max(widths)-min(widths)>1:continue
  if any(values[-1]-values[0]+1!=len(values) for _,values in rows):continue
  centers=[(values[0]+values[-1])/2 for _,values in rows]
  if max(centers)-min(centers)>1:continue
  # Stable core color excludes shaded/patterned strips even if some pixels match.
  samples=[px[round(center),major] if vertical else px[major,round(center)] for (major,_),center in zip(rows,centers)]
  if any(max(p[k] for p in samples)-min(p[k] for p in samples)>32 for k in range(3)):continue
  center=statistics.median(centers);middle=(rows[0][0]+rows[-1][0])/2;parallel=False
  for l in layers:
   if l['kind']!='line' or l['dash']!='solid':continue
   for p,q in zip(l['points'],l['points'][1:]):
    a,b=(p[1]*sy,q[1]*sy) if vertical else (p[0]*sx,q[0]*sx);c,d=(p[0]*sx,q[0]*sx) if vertical else (p[1]*sy,q[1]*sy)
    if abs(b-a)<1 or abs(d-c)>abs(b-a)*.05 or not min(a,b)<=middle<=max(a,b):continue
    cross=c+(d-c)*(middle-a)/(b-a)
    if abs(center-cross)<=max(6,l['width']*cross_scale/2+max(widths)/2+2):parallel=True
  if parallel:continue
  ends=[]
  for end,sign in [(rows[0][0],-1),(rows[-1][0],1)]:
   hit=None
   for distance in range(1,math.ceil(2*scale)+2):
    major=end+sign*distance;x,y=(round(center),major) if vertical else (major,round(center))
    if not match(x,y):break
    owners=[index for index,mask in anchors if mask[x,y]]
    if owners:hit=dict(layerIndex=owners[0],sourcePixel=[x,y],gapPixels=distance);break
   if hit is None:break
   ends.append(hit)
  if len(ends)!=2 or ends[0]['layerIndex']==ends[1]['layerIndex']:continue
  key=(x0,y0,x1,y1)
  if key in claimed:continue
  claimed.add(key);width=statistics.median(widths)/cross_scale
  first,last=rows[0][0],rows[-1][0]
  points=[[(center+.5)/sx,first/sy],[(center+.5)/sx,(last+1)/sy]] if vertical else [[first/sx,(center+.5)/sy],[(last+1)/sx,(center+.5)/sy]]
  bbox=dict(x=(center+.5)/sx-width/2,y=first/sy,w=width,h=(last-first+1)/sy) if vertical else dict(x=first/sx,y=(center+.5)/sy-width/2,w=(last-first+1)/sx,h=width)
  line=dict(kind='line',bbox=bbox,points=points,color=color,width=width,dash='solid',roundCaps=False,spacing=0)
  found.append(dict(line=line,evidence=dict(sourcePixelBounds=[x0,y0,x1+1,y1+1],axis='vertical' if vertical else 'horizontal',declaredColorLayerIndices=indices,anchors=ends,rowSupport=[dict(position=major,start=values[0],end=values[-1],count=len(values)) for major,values in rows],centerDriftPixels=max(centers)-min(centers))))
print(json.dumps(dict(additions=found,alignments=alignments,layers=layers,sourcePixels=dict(width=w,height=h))))`;

export async function completeSourceVerifiedConnectors({sourcePath,inventory},{signal}={}){
 signal?.throwIfAborted();const source=resolve(sourcePath);if(await realpath(source)!==source)throw Error('Connector source must be canonical');
 const info=await stat(source);if(!info.isFile()||info.size>24*1024*1024)throw Error('Invalid connector source');const bytes=await readFile(source);
 if(!bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))throw Error('Connector source must be PNG');
 const dir=await mkdtemp(join(tmpdir(),'artwork-source-connectors-'));
 try{const file=join(dir,'source.png');await writeFile(file,bytes,{flag:'wx'});const config=join(dir,'input.json');await writeFile(config,JSON.stringify({sourcePath:file,inventory}),{flag:'wx'});
  const {stdout}=await exec(process.env.PYTHON||'python',['-c',CONNECTORS,config],{signal,timeout:20000,maxBuffer:2*1024*1024,windowsHide:true});signal?.throwIfAborted();const result=JSON.parse(stdout);
  if((!result.additions.length&&!result.alignments.length)||inventory.layers.length+result.additions.length>60)return null;
  return {inventory:{...structuredClone(inventory),layers:[...result.layers,...result.additions.map(v=>v.line)]},evidence:{version:1,sourceHash:createHash('sha256').update(bytes).digest('hex'),inventoryHash:createHash('sha256').update(JSON.stringify(inventory)).digest('hex'),sourcePixels:result.sourcePixels,alignments:result.alignments,connectors:result.additions.map(v=>v.evidence)}};
 }finally{await rm(dir,{recursive:true,force:true});}
}
