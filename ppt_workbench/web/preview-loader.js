/* Secondary previews only. The editable canvas retains its direct, priority load. */
(() => {
  class PreviewLoader {
    constructor() {
      this.items=new Map();this.jobs=new Map();this.cache=new Map();this.active=0;this.timer=null;
      this.observer=new IntersectionObserver(entries=>{
        for(const entry of entries){const item=this.items.get(entry.target);if(item){item.visible=entry.isIntersecting;if(!item.visible)item.failed=false;}}
        this.schedule();
      },{rootMargin:'0px',threshold:0});
    }
    watch(element,url) {
      const absolute=new URL(url,location.href);
      if(absolute.origin!==location.origin)return;
      const item={element,url:absolute.href,kind:element.tagName==='IMG'?'image':'html',visible:false,loaded:false};
      element.dataset.previewResource=absolute.href;element.dataset.previewState='waiting';
      this.items.set(element,item);this.observer.observe(element);
    }
    clear(root) {
      for(const [element] of this.items)if(root.contains(element)){this.observer.unobserve(element);this.items.delete(element);}
      this.schedule();
    }
    schedule() {
      clearTimeout(this.timer);this.timer=setTimeout(()=>this.pump(),120);
    }
    wanted(url) {
      return [...this.items.values()].filter(i=>i.url===url&&i.visible&&i.element.isConnected&&!i.loaded);
    }
    apply(item,entry) {
      if(!item.element.isConnected || !item.visible)return;
      if(entry.kind==='image')item.element.src=entry.value;
      else item.element.srcdoc=entry.value;
      item.loaded=true;item.element.dataset.previewState='ready';
    }
    remember(url,entry) {
      this.cache.delete(url);this.cache.set(url,entry);
      while(this.cache.size>32){const [key,old]=this.cache.entries().next().value;this.cache.delete(key);if(old.kind==='image')URL.revokeObjectURL(old.value);}
    }
    pump() {
      for(const [element] of this.items)if(!element.isConnected){this.observer.unobserve(element);this.items.delete(element);}
      for(const [url,job] of this.jobs)if(!this.wanted(url).length){job.cancelled=true;job.controller.abort();}
      for(const item of this.items.values()){
        if(item.loaded||!item.visible||!item.element.isConnected)continue;
        const cached=this.cache.get(item.url);
        if(cached){this.cache.delete(item.url);this.cache.set(item.url,cached);this.apply(item,cached);continue;}
        if(this.jobs.has(item.url)||this.active>=2||item.failed)continue;
        this.start(item);
      }
    }
    async start(item) {
      const job={controller:new AbortController()};this.jobs.set(item.url,job);this.active++;
      const timer=setTimeout(()=>job.controller.abort(),30000);
      try{
        const response=await fetch(item.url,{credentials:'same-origin',signal:job.controller.signal});
        if(!response.ok)throw Error('Preview unavailable');
        const value=item.kind==='image'?URL.createObjectURL(await response.blob()):await response.text();
        const entry={kind:item.kind,value};this.remember(item.url,entry);
        for(const target of this.wanted(item.url))this.apply(target,entry);
      }catch(error){
        // A removed/hidden card can be requested again when it re-enters view.
        if(!job.cancelled)for(const target of this.wanted(item.url)){target.failed=true;target.element.dataset.previewState='error';}
      }finally{
        clearTimeout(timer);this.jobs.delete(item.url);this.active--;this.schedule();
      }
    }
  }
  globalThis.WePPTPreviewLoader=PreviewLoader;
})();
