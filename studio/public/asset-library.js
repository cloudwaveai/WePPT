import {validateSvg} from './vector-scene.js';
import {createLibraryObject} from './library-assets.js';

export const libraryLabels={geometry:'基础几何',coolshapes:'几何图形 · Coolshapes',geopattern:'底纹 · GeoPattern',blobshape:'有机形状 · Blobshape',tabler:'图标 · Tabler'};
const safeAssetPath=src=>typeof src==='string'&&/^\/assets\/library\/[a-z\d_./-]+\.svg$/i.test(src)&&!src.includes('..');

export function validateAssetCatalog(catalog){
 if(!catalog||!Array.isArray(catalog.items)||!Array.isArray(catalog.libraries))throw Error('素材目录格式不正确。');
 const ids=new Set();
 for(const item of catalog.items){
  if(!item||typeof item.id!=='string'||ids.has(item.id)||!Object.hasOwn(libraryLabels,item.library)||!safeAssetPath(item.src))throw Error('素材目录包含无效或重复的项目。');
  if(!Number.isFinite(item.width)||!Number.isFinite(item.height)||item.width<=0||item.height<=0)throw Error('素材尺寸不正确。');
  ids.add(item.id);
 }
 return catalog;
}

export function filterLibraryItems(items,{library='',query=''}={}){
 const terms=String(query).trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
 return items.filter(item=>(!library||item.library===library)&&terms.every(term=>[item.name,item.id,libraryLabels[item.library],item.style,...(item.tags||[])].join(' ').toLocaleLowerCase().includes(term)));
}

export async function loadAssetCatalog({signal,fetcher=fetch}={}){
 const response=await fetcher('/assets/library/catalog.json',{signal});
 if(!response.ok)throw Error('素材目录暂时无法读取，请重试。');
 return validateAssetCatalog(await response.json());
}

export async function loadLibraryVector(item,{signal,fetcher=fetch,library}={}){
 if(!safeAssetPath(item?.src))throw Error('素材地址无效。');
 const response=await fetcher(item.src,{signal});
 if(!response.ok)throw Error('素材读取失败，请重试。');
 const svg=await response.text();validateSvg(svg);signal?.throwIfAborted();
 const ratio=item.width/item.height,w=ratio>=1?280:280*ratio,h=ratio>=1?280/ratio:280;
 return {...createLibraryObject(item,svg,{w,h,custom:true}),assetLibrary:{id:item.id,library:item.library,version:library?.version,license:item.license||library?.license,source:item.source||library?.source}};
}

/** A bounded, keyboard-accessible picker. Its insertion callback uses the editor's undoable commit. */
export function openAssetLibrary({host,onInsert,onError=()=>{},getAssets=()=>[],onUpload}){
 const node=(tag,cls,text)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;};
 const modal=node('dialog','ed-dialog ed-asset-dialog'),heading=node('div','ed-dialog-heading'),content=node('div','ed-dialog-content'),actions=node('div','ed-dialog-actions');
 const title=node('h2','','素材库'),closeButton=node('button','ed-button','关闭'),cancel=node('button','ed-button','取消'),insert=node('button','ed-button ed-primary','插入选中素材');
 closeButton.type=cancel.type=insert.type='button';closeButton.setAttribute('aria-label','关闭素材库');insert.disabled=true;heading.append(title,closeButton);actions.append(cancel,insert);
 const upload=node('button','ed-button','上传素材'),file=node('input');upload.type='button';upload.hidden=!onUpload;file.type='file';file.accept='image/*';file.multiple=true;file.hidden=true;file.setAttribute('aria-label','上传素材文件');
 const headingActions=node('div','ed-asset-heading-actions');headingActions.append(upload,closeButton);heading.append(headingActions);modal.append(file);
 const search=node('input','ed-asset-search');search.type='search';search.placeholder='搜索名称或关键词，如 圆环、页角、底板、纹理';search.setAttribute('aria-label','搜索素材');
 const tabs=node('div','ed-asset-tabs');tabs.setAttribute('aria-label','素材分类');
 const status=node('p','ed-pane-note');status.setAttribute('role','status');const grid=node('div','ed-asset-grid');grid.setAttribute('aria-label','素材列表');
 const pagebar=node('div','ed-asset-pages'),previous=node('button','ed-button','上一页'),pageLabel=node('span'),next=node('button','ed-button','下一页'),selection=node('p','ed-asset-selection','选择一个素材后插入到当前页。');previous.type=next.type='button';pagebar.append(previous,pageLabel,next);
 const retry=node('button','ed-button','重新加载素材');retry.type='button';retry.hidden=true;
 const exportNote=node('p','ed-pane-note','导出说明：带蒙版、模糊或裁剪效果的素材以高清透明图片保留效果，可移动缩放，内部路径不能逐个编辑；原始 SVG 另存于文件内。其余素材导出为可编辑形状。');
 content.append(search,tabs,status,retry,grid,pagebar,selection,exportNote);modal.append(heading,content,actions);host.append(modal);
 const controller=new AbortController();let catalog=null,selected=null,category='',page=0,inserting=false,uploading=false,closed=false;const pageSize=48;
 const close=()=>{if(closed)return;closed=true;controller.abort();modal.close();modal.remove();};
 modal.addEventListener('cancel',event=>{event.preventDefault();close();});closeButton.onclick=cancel.onclick=close;
 const labelFor=item=>item.library==='project'?'我的素材':libraryLabels[item.library];
 function resetSelection(){selected=null;insert.disabled=true;selection.textContent='选择一个素材后插入到当前页。';}
 for(const [id,label] of [['','全部'],['project','我的素材'],...Object.entries(libraryLabels)]){const button=node('button','ed-button',label);button.type='button';button.dataset.library=id;button.onclick=()=>{if(uploading||inserting)return;category=id;page=0;resetSelection();render();};tabs.append(button);}
 function render(){
  if(closed)return;
  const personal=getAssets().map(a=>({id:'project:'+a.id,name:a.name,src:a.src,library:'project',projectAsset:a}));
  const terms=search.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const own=personal.filter(a=>terms.every(t=>(a.name+' 我的素材').toLocaleLowerCase().includes(t)));
  const builtIn=filterLibraryItems(catalog?.items||[],{library:category,query:search.value});
  const items=category==='project'?own:category?builtIn:[...own,...builtIn],total=Math.max(1,Math.ceil(items.length/pageSize));page=Math.min(page,total-1);
  grid.replaceChildren();status.textContent=`${items.length} 个素材${category?' · '+(category==='project'?'我的素材':libraryLabels[category]):''}`;exportNote.hidden=category==='project';
  for(const item of items.slice(page*pageSize,(page+1)*pageSize)){
   const button=node('button','ed-asset-card');button.type='button';button.title=item.name;button.setAttribute('aria-label',item.name);button.setAttribute('aria-pressed',String(selected?.id===item.id));button.dataset.assetId=item.id;
   const image=node('img');image.src=item.src;image.alt='';image.loading='lazy';image.width=96;image.height=96;
   button.append(image,node('span','',item.name));button.onclick=()=>{if(inserting||uploading)return;selected=item;selection.textContent=`已选择：${item.name} · ${labelFor(item)}${item.usage?' · '+item.usage:''}`;insert.disabled=false;grid.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.assetId===item.id)));};grid.append(button);
  }
  if(!items.length)grid.append(node('p','ed-asset-empty',category==='project'&&!search.value?'还没有上传素材。点击右上角“上传素材”，图片和 Logo 都会保存在这里。':'没有找到匹配的素材，请换个关键词或分类。'));
  previous.disabled=page===0;next.disabled=page>=total-1;pageLabel.textContent=`${page+1} / ${total}`;
  tabs.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.library===category)));
 }
 async function load(){
  status.textContent='正在加载素材库…';retry.hidden=true;
  try{catalog=await loadAssetCatalog({signal:controller.signal});if(closed)return;
   render();
  }catch(error){if(!closed){status.textContent=error.message;retry.hidden=false;}}
 }
 search.oninput=()=>{page=0;render();};previous.onclick=()=>{page--;render();};next.onclick=()=>{page++;render();};retry.onclick=load;
 upload.onclick=()=>{if(!uploading&&!inserting)file.click();};
 file.onchange=async()=>{
  const files=[...file.files];file.value='';if(!files.length||uploading||!onUpload)return;
  uploading=true;upload.disabled=true;upload.textContent='正在上传…';insert.disabled=true;
  try{
   const assets=await onUpload(files);if(closed)return;
   category='project';page=0;search.value='';resetSelection();
   const first=assets?.[0];if(first){selected={id:'project:'+first.id,name:first.name,src:first.src,library:'project',projectAsset:first};insert.disabled=false;selection.textContent=`已上传 ${assets.length} 个素材，点击“插入选中素材”添加到当前页。`;}
   render();
  }catch(error){if(!closed){selection.textContent=error.message||'上传失败，请重试。';onError(selection.textContent);}}
  finally{uploading=false;if(!closed){upload.disabled=false;upload.textContent='上传素材';insert.disabled=!selected;}}
 };
 insert.onclick=async()=>{
  if(!selected||inserting||uploading)return;inserting=true;insert.disabled=true;insert.textContent='正在插入…';
  try{const asset=selected.projectAsset,vector=asset?{type:'image',src:asset.src,assetId:asset.id,name:asset.name,kind:asset.kind,w:asset.kind==='logo'?160:400,h:asset.kind==='logo'?90:240,fit:'contain',custom:true}:await loadLibraryVector(selected,{signal:controller.signal,library:catalog.libraries.find(l=>l.id===selected.library)});if(closed)return;await onInsert(vector);close();}
  catch(error){if(!closed){selection.textContent=error.message;onError(error.message);}}
  finally{inserting=false;if(!closed){insert.disabled=!selected;insert.textContent='插入选中素材';}}
 };
 modal.showModal();search.focus();load();return{close};
}
