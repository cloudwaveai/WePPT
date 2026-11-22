/** Playback is local, read-only, and uses the editor's actual object renderer. */
export function startPresentation({pages,startIndex=0,renderPage,onClose}){
 const slides=structuredClone(pages);if(!slides.length)return null;
 let index=Math.max(0,Math.min(slides.length-1,startIndex)),closed=false,hadFullscreen=false;
 const previousFocus=document.activeElement,host=document.createElement('section');
 host.className='ed-presentation';host.tabIndex=-1;host.setAttribute('role','dialog');host.setAttribute('aria-modal','true');host.setAttribute('aria-label','PPT 播放');
 host.innerHTML='<div class="ed-presentation-viewport"><div class="ed-presentation-frame"><div class="ed-presentation-slide"></div></div></div><nav class="ed-presentation-controls" aria-label="播放控制"><button type="button" data-prev aria-label="播放上一页">← 上一页</button><span data-position aria-live="polite"></span><button type="button" data-next aria-label="播放下一页">下一页 →</button><span class="ed-presentation-help">方向键 / 空格翻页 · Esc 退出</span><button type="button" data-exit>退出播放</button></nav>';
 const viewport=host.querySelector('.ed-presentation-viewport'),frame=host.querySelector('.ed-presentation-frame'),slide=host.querySelector('.ed-presentation-slide'),prev=host.querySelector('[data-prev]'),next=host.querySelector('[data-next]');
 const inertStates=[...document.body.children].map(node=>[node,node.inert]);for(const [node]of inertStates)node.inert=true;
 document.body.append(host);
 function fit(){const scale=Math.max(.01,Math.min((viewport.clientWidth-24)/1280,(viewport.clientHeight-24)/720));frame.style.width=1280*scale+'px';frame.style.height=720*scale+'px';slide.style.transform=`scale(${scale})`;}
 function show(){const page=slides[index];slide.replaceChildren(renderPage(page));slide.style.background=page.background||'#fff';slide.setAttribute('aria-label',`第 ${index+1} 页：${page.title||''}`);host.querySelector('[data-position]').textContent=`${index+1} / ${slides.length}`;prev.disabled=index===0;next.disabled=index===slides.length-1;fit();}
 function go(value){index=Math.max(0,Math.min(slides.length-1,value));show();}
 function close(){if(closed)return;closed=true;observer.disconnect();window.removeEventListener('keydown',keys,true);document.removeEventListener('fullscreenchange',fullscreenChanged);if(document.fullscreenElement===host)document.exitFullscreen().catch(()=>{});host.remove();for(const [node,inert]of inertStates)node.inert=inert;onClose?.(slides[index].id);if(previousFocus?.isConnected&&!previousFocus.closest('[inert]'))previousFocus.focus();}
 function keys(event){
  if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close();return;}
  if(['ArrowRight','ArrowDown','PageDown',' ','ArrowLeft','ArrowUp','PageUp','Home','End'].includes(event.key)){event.preventDefault();event.stopImmediatePropagation();go(event.key==='Home'?0:event.key==='End'?slides.length-1:index+(['ArrowLeft','ArrowUp','PageUp'].includes(event.key)?-1:1));return;}
  if(event.key==='Tab'){event.preventDefault();const buttons=[...host.querySelectorAll('button:not(:disabled)')],at=buttons.indexOf(document.activeElement),step=event.shiftKey?-1:1;buttons[(at+step+buttons.length)%buttons.length]?.focus();}
 }
 function fullscreenChanged(){if(document.fullscreenElement===host)hadFullscreen=true;else if(hadFullscreen)close();}
 prev.onclick=()=>go(index-1);next.onclick=()=>go(index+1);host.querySelector('[data-exit]').onclick=close;
 viewport.onclick=()=>go(index+1);
 const observer=new ResizeObserver(fit);observer.observe(viewport);window.addEventListener('keydown',keys,true);document.addEventListener('fullscreenchange',fullscreenChanged);show();host.focus();
 // A browser that declines fullscreen still gets viewport-filling playback.
 try{host.requestFullscreen?.().then(()=>{hadFullscreen=true;if(!closed&&document.fullscreenElement!==host)close();}).catch(()=>{});}catch{}
 return {close};
}
