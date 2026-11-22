export async function requestImageAssistant(input,signal,onProgress=()=>{}){
 const response=await fetch('/api/ai',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...input,stream:true}),signal});
 if(!response.headers.get('content-type')?.includes('application/x-ndjson')){const data=await response.json();if(!response.ok)throw Error(data.error?.message||data.error||'请求失败');return data;}
 if(!response.ok||!response.body)throw Error('助手连接失败，原稿已保留。');
 const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',result,received=false;
 const consume=line=>{if(!line.trim())return;const event=JSON.parse(line);if(event.type==='error')throw Error(event.error);if(event.type==='progress')onProgress(event);if(event.type==='result'){if(received)throw Error('助手返回重复结果');received=true;result=event.result;}};
 try{for(;;){const {done,value}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});if(buffer.length>20*1024*1024)throw Error('助手结果过大');let index;while((index=buffer.indexOf('\n'))>=0){consume(buffer.slice(0,index));buffer=buffer.slice(index+1);}}buffer+=decoder.decode();consume(buffer);signal?.throwIfAborted();if(!received)throw Error('助手连接中断，原稿已保留。');return result;}
 finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
}
