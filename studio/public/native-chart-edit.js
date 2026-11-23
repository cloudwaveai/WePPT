const escape=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
export function canEditNativeChart(o){return o?.type==='vector'&&o.nativeType==='chart'&&o.nativeData?.type==='column'&&Array.isArray(o.nativeData.categories)&&Array.isArray(o.nativeData.series);}
export function updateNativeChart(object,{categories,series}){
 if(!canEditNativeChart(object))throw Error('当前数据编辑支持原生柱形图。');
 if(!Array.isArray(categories)||!categories.length||categories.length>30||categories.some(c=>typeof c!=='string'||!c.trim()||c.length>80))throw Error('请填写1至30个分类，每个名称不超过80字。');
 if(!Array.isArray(series)||!series.length||series.length>6||series.some(s=>typeof s.name!=='string'||s.name.length>80||!Array.isArray(s.values)||s.values.length!==categories.length||s.values.some(v=>typeof v!=='number'||!Number.isFinite(v)||v<0||v>1e12)))throw Error('每个系列需填写所有分类的非负数值（最多6个系列）。');
 const vb=/viewBox\s*=\s*["']([^"']+)["']/i.exec(object.svg)?.[1]?.split(/[ ,]+/).map(Number);if(vb?.length!==4||vb.some(v=>!Number.isFinite(v))||vb[2]<120||vb[3]<100)throw Error('图表尺寸不足以编辑数据。');
 const [x,y,w,h]=vb,data={...structuredClone(object.nativeData),x,y,width:w,height:h,categories:[...categories],series:structuredClone(series)};
 const colors=['#316BF0','#111827','#88B7F3','#597A56','#BD8460','#8F76AF'],left=x+48,top=y+30,pw=w-72,ph=h-90,max=Math.max(1,...series.flatMap(s=>s.values)),slot=pw/categories.length,bw=Math.max(1,slot*.7/series.length);
 let body=`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="#FFFFFF"/><line x1="${left}" y1="${top+ph}" x2="${left+pw}" y2="${top+ph}" stroke="#9AA3B0"/>`;
 for(let i=0;i<categories.length;i++){for(let j=0;j<series.length;j++){const value=series[j].values[i],bh=value/max*(ph-24),bx=left+slot*i+slot*.15+j*bw;body+=`<rect x="${bx}" y="${top+ph-bh}" width="${bw*.9}" height="${bh}" fill="${colors[j]}"/><text x="${bx+bw*.45}" y="${top+ph-bh-5}" text-anchor="middle" font-size="${Math.max(10,Math.min(18,bw*.45))}" fill="#111827">${value}</text>`;}body+=`<text x="${left+slot*(i+.5)}" y="${top+ph+26}" text-anchor="middle" font-size="${Math.max(10,Math.min(20,slot/categories[i].length*.85))}" fill="#111827">${escape(categories[i])}</text>`;}
 for(let j=0;j<series.length;j++)body+=`<text x="${x+16+j*w/series.length}" y="${y+20}" font-size="16" fill="${colors[j]}">${escape(series[j].name)}</text>`;
 const svg=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb.join(' ')}" width="${w}" height="${h}"><g data-pptx-replace-with="chart" data-pptx-native-authority="json"><metadata type="application/json">${escape(JSON.stringify(data))}</metadata>${body}</g></svg>`;
 return {...structuredClone(object),nativeData:data,svg};
}
