/** Remove only unreachable SVG definitions; preserve visible content and IDs. */
export function compactSvgDefinitions(source){
 if(typeof source!=='string'||!/<defs\b/i.test(source))return source;
 // Imported sub-scenes can inherit xlink from the page root. They must also
 // declare it when serialized as standalone image documents in the editor.
 if(/\bxlink:/.test(source)&&!/^\s*<svg\b[^>]*\bxmlns:xlink\s*=/.test(source))source=source.replace(/<svg\b/,'<svg xmlns:xlink="http://www.w3.org/1999/xlink"');
 const document=new DOMParser().parseFromString(source,'image/svg+xml');
 if(document.querySelector('parsererror'))throw Error('SVG 定义格式不正确。');
 const root=document.documentElement,definitions=[...root.querySelectorAll('defs')].filter(node=>!node.parentElement?.closest('defs'));
 const owners=new Map(),children=definitions.flatMap(node=>[...node.children]);
 for(const child of children)for(const node of [child,...child.querySelectorAll('[id]')]){
  const id=node.getAttribute('id');if(!id)continue;
  if(!owners.has(id))owners.set(id,new Set());owners.get(id).add(child);
 }
 const referenced=new Set(),queue=[];
 function scan(node){for(const attribute of node.attributes||[]){
  const value=attribute.value;
  if(attribute.localName==='href'&&/^#[\w:.-]+$/.test(value))reference(value.slice(1));
  for(const match of value.matchAll(/url\(\s*["']?#([\w:.-]+)["']?\s*\)/gi))reference(match[1]);
 }}
 function reference(id){if(!referenced.has(id)){referenced.add(id);queue.push(id);}}
 for(const node of [root,...root.querySelectorAll('*')])if(!node.closest('defs'))scan(node);
 const keep=new Set();
 for(let i=0;i<queue.length;i++)for(const owner of owners.get(queue[i])||[]){
  if(keep.has(owner))continue;keep.add(owner);for(const node of [owner,...owner.querySelectorAll('*')])scan(node);
 }
 let removed=0;
 for(const child of children)if(!keep.has(child)){child.remove();removed++;}
 if(!removed)return source;
 for(const definition of definitions)if(!definition.children.length)definition.remove();
 return new XMLSerializer().serializeToString(root);
}
