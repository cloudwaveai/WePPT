// Export only the visible pixels of cropped bitmap objects. This avoids Office
// treating SVG clip geometry as a new picture frame and stretching the full source.
// Text, shapes, and each picture remain independent editable slide objects.
export async function prepareExportImageCrops(pages,tab,{signal}={}){
 for(const page of pages)for(const object of page.objects||[]){
  if(object.type!=='image'||!object.crop)continue;
  signal?.throwIfAborted();
  if(!/^data:image\/(?:png|jpeg|webp);base64,/i.test(object.src||''))throw Error('裁剪图片尚未内嵌，无法导出。');
  object.src=await tab.evaluate(async({src,crop})=>{
   const number=(v,f)=>Number.isFinite(Number(v))?Number(v):f;
   const cw=Math.min(1,Math.max(.01,number(crop.w,1))),ch=Math.min(1,Math.max(.01,number(crop.h,1)));
   const cx=Math.min(1-cw,Math.max(0,number(crop.x,0))),cy=Math.min(1-ch,Math.max(0,number(crop.y,0)));
   const image=new Image();image.src=src;await image.decode();
   const sw=image.naturalWidth*cw,sh=image.naturalHeight*ch;
   const scale=Math.min(1,4096/sw,4096/sh);
   const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.ceil(sw*scale));canvas.height=Math.max(1,Math.ceil(sh*scale));
   canvas.getContext('2d').drawImage(image,image.naturalWidth*cx,image.naturalHeight*cy,sw,sh,0,0,canvas.width,canvas.height);
   return canvas.toDataURL('image/png');
  },{src:object.src,crop:object.crop});
  signal?.throwIfAborted();delete object.crop;object.fit='stretch';
 }
}
