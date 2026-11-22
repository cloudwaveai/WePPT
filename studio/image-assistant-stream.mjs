export async function streamImageAssistant(res,run){
 res.writeHead(200,{'Content-Type':'application/x-ndjson; charset=utf-8','Cache-Control':'no-store','X-Accel-Buffering':'no'});res.flushHeaders?.();
 const send=event=>{if(!res.destroyed&&!res.writableEnded)res.write(JSON.stringify(event)+'\n');};
 const heartbeat=setInterval(()=>send({type:'heartbeat'}),15000);
 try{const result=await run(event=>send({type:'progress',...event}));send({type:'result',result});}
 catch(error){send({type:'error',error:error.message||'修改未完成，原稿已保留。'});}
 finally{clearInterval(heartbeat);if(!res.destroyed)res.end();}
}
