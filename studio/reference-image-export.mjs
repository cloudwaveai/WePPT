/** Bound generated photographic artwork in the temporary export scene only. */
export async function prepareReferenceArtworkForExport(pages,tab){
 for(const page of pages){
  if(!page.imageDesign?.editableText)continue;
  for(const object of page.objects||[]){
   if(object.type!=='image'||object.custom||!object.layoutManaged||object.x!==0||object.y!==0||object.w!==1280||object.h!==720||!String(object.src).startsWith('data:image/png;base64,')||object.src.length<900000)continue;
   object.src=await tab.evaluate(async src=>{
    const image=new Image();image.src=src;await image.decode();
    const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
    const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);
    const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;
    for(let i=3;i<pixels.length;i+=4)if(pixels[i]!==255)return src;
    const encoded=canvas.toDataURL('image/jpeg',.94);if(encoded.length>1500000)throw Error('生成底图仍过大，无法安全导出。');return encoded;
   },object.src);
  }
 }
}
