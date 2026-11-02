/* DUCKO static-site ASR adapter. Vosk Browser 0.0.8, local Worker/WASM only. */
(()=>{
  'use strict';
  const base=new URL('.',document.currentScript?.src||location.href);
  const models=Object.freeze({zh:'vosk-model-small-cn-0.22-browser-v2.tar.gz',en:'vosk-model-small-en-us-0.15-browser-v2.tar.gz'});
  let libraryPromise=null,current=null,active=null,epoch=0;
  const aborted=()=>new DOMException('识别已取消。','AbortError');
  const supported=()=>['http:','https:'].includes(location.protocol)&&!!window.isSecureContext&&typeof WebAssembly==='object'&&typeof Worker==='function'&&typeof fetch==='function'&&!!window.crypto?.subtle&&!!navigator.mediaDevices?.getUserMedia;
  const info=language=>({language,engine:'vosk-browser',offline:true});
  function report(fn,phase,language,message){try{fn?.({phase,language,message})}catch(_){}}
  function forceFree(record){
    if(!record)return;
    try{record.model?.terminate()}catch(_){}
    // The pinned 0.0.8 Model.terminate() posts to the worker. A busy WASM turn
    // cannot process that message yet; hard termination also stops that work.
    try{record.model?.worker?.terminate()}catch(_){}
    for(const url of record.urls||[]){try{URL.revokeObjectURL(url)}catch(_){}}
    record.urls=[];
    record.ready=false;
    if(current===record)current=null;
  }
  const digest=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
  async function loadArchive(language,record,onProgress){
    const signal=record.downloadController.signal;
    const check=()=>{if(record.cancelled||signal.aborted)throw signal.reason||aborted()};
    const timeout=setTimeout(()=>record.downloadController.abort(new DOMException('模型下载超过三分钟，请检查网络。','TimeoutError')),180000);
    let cache=null;
    try{
      const response=await fetch(new URL('models-browser/manifest.json?delivery=browser-v2',base).href,{signal,cache:'no-cache'});
      if(!response.ok)throw new Error('模型清单加载失败，请检查 models-browser/manifest.json。');
      const list=await response.json(),config=Array.isArray(list)&&list.find(item=>item.language===language);
      if(!config||config.file!==models[language]||!Number.isSafeInteger(config.bytes)||config.bytes<1||config.bytes>128*1024*1024||!/^[0-9a-f]{64}$/.test(config.sha256)||!Array.isArray(config.parts)||config.parts.length<1||config.parts.length>32)throw new Error('模型分片清单无效。');
      let declared=0;
      for(const part of config.parts){if(!/^[A-Za-z0-9._-]+$/.test(part.file)||!part.file.startsWith(config.file+'.part')||!Number.isSafeInteger(part.bytes)||part.bytes<1||part.bytes>8*1024*1024||!/^[0-9a-f]{64}$/.test(part.sha256))throw new Error('模型分片记录无效。');declared+=part.bytes}
      if(declared!==config.bytes)throw new Error('模型分片总长度与清单不符。');
      const stableURL=new URL('models-browser/'+config.file,base).href;
      try{if(window.caches)cache=await caches.open('ducko-vosk-archives-v1-'+base.pathname)}catch(_){}
      if(cache){
        try{
          const cached=await cache.match(stableURL);
          if(cached&&cached.headers.get('x-ducko-sha256')===config.sha256){
            report(onProgress,'verifying-model',language,language==='zh'?'正在校验已缓存的中文模型…':'Checking the cached English model…');
            const bytes=await cached.arrayBuffer();check();
            if(bytes.byteLength===config.bytes&&await digest(bytes)===config.sha256){check();return {blob:new Blob([bytes],{type:'application/gzip'}),stableURL}}
            await cache.delete(stableURL);
          }
        }catch(error){check();cache=null}
      }
      const chunks=[];let received=0;
      for(let i=0;i<config.parts.length;i++){
        check();const part=config.parts[i];
        const chunkResponse=await fetch(new URL('models-browser/'+part.file,base).href,{signal});
        if(!chunkResponse.ok)throw new Error(`模型分片 ${i+1}/${config.parts.length} 下载失败。`);
        const bytes=await chunkResponse.arrayBuffer();check();
        if(bytes.byteLength!==part.bytes||await digest(bytes)!==part.sha256)throw new Error(`模型分片 ${i+1} 校验失败，请重新加载。`);
        check();chunks.push(new Uint8Array(bytes));received+=bytes.byteLength;
        const progress={phase:'downloading-model',language,received,total:config.bytes,message:language==='zh'?`正在下载中文模型 ${(received/1048576).toFixed(1)} / ${(config.bytes/1048576).toFixed(1)} MB`:`Downloading English model ${(received/1048576).toFixed(1)} / ${(config.bytes/1048576).toFixed(1)} MB`};
        try{onProgress?.(progress)}catch(_){}
      }
      report(onProgress,'verifying-model',language,language==='zh'?'正在校验完整模型…':'Verifying the complete model…');
      const combined=new Uint8Array(config.bytes);let offset=0;for(const chunk of chunks){combined.set(chunk,offset);offset+=chunk.length}
      if(await digest(combined)!==config.sha256)throw new Error('模型整体校验失败，请重新加载。');
      check();const blob=new Blob([combined],{type:'application/gzip'});
      if(cache){try{await cache.put(stableURL,new Response(blob,{headers:{'content-type':'application/gzip','x-ducko-sha256':config.sha256}}))}catch(_){}}
      check();return {blob,stableURL};
    }finally{clearTimeout(timeout)}
  }
  function modelFromArchive(stableURL,blob,record){
    const archiveURL=URL.createObjectURL(blob);record.urls.push(archiveURL);
    const NativeWorker=window.Worker;
    // Vosk derives its persistent IDB path from modelUrl. Keep that URL stable,
    // and route only its model fetch to the verified in-memory archive.
    function ArchiveWorker(originalURL,options){
      if(options?.type==='module')throw new Error('该 Vosk 版本需要 classic Worker。');
      const original=String(originalURL);
      if(!original.startsWith('blob:'))throw new Error('识别 Worker 来源不符合已固定版本。');
      const code=`const __duckoFetch=self.fetch.bind(self);self.fetch=function(input,init){const raw=typeof input==='string'?input:(input&&input.url)||String(input);let requested=raw;try{requested=new URL(raw,self.location.href).href}catch(_){}return __duckoFetch(requested===${JSON.stringify(stableURL)}?${JSON.stringify(archiveURL)}:input,init)};importScripts(${JSON.stringify(original)});`;
      const workerURL=URL.createObjectURL(new Blob([code],{type:'application/javascript'}));record.urls.push(workerURL);
      return new NativeWorker(workerURL,options);
    }
    ArchiveWorker.prototype=NativeWorker.prototype;
    Object.setPrototypeOf(ArchiveWorker,NativeWorker);
    // The pinned Vosk constructor synchronously creates exactly one Worker.
    // Restore the global immediately; no unrelated later Workers are routed.
    window.Worker=ArchiveWorker;
    try{return new window.Vosk.Model(stableURL,-1)}finally{window.Worker=NativeWorker}
  }
  function loadLibrary(){
    if(window.Vosk?.Model)return Promise.resolve();
    if(libraryPromise)return libraryPromise;
    libraryPromise=new Promise((resolve,reject)=>{
      const script=document.createElement('script');
      script.src=new URL('vendor/vosk-browser/dist/vosk.js',base).href;
      script.async=true;
      const finish=error=>{clearTimeout(timer);script.onload=script.onerror=null;if(error){script.remove();reject(error)}else resolve()};
      const timer=setTimeout(()=>finish(new Error('浏览器识别库加载超时，请检查网站文件是否完整。')),45000);
      script.onload=()=>finish(window.Vosk?.Model?null:new Error('浏览器识别库没有正确初始化。'));
      script.onerror=()=>finish(new Error('无法加载浏览器识别库，请确认 vendor/vosk-browser 已部署。'));
      document.head.append(script);
    }).catch(error=>{libraryPromise=null;throw error});
    return libraryPromise;
  }
  function cancel(){
    epoch++;
    if(active){active.abort();return}
    if(current&&!current.ready)current.abort();
  }
  function dispose(){cancel();forceFree(current)}
  async function prepare(language='zh',onProgress,signal){
    if(signal?.aborted)throw aborted();
    if(!Object.hasOwn(models,language))throw new Error('不支持该识别语言。');
    if(!supported())throw new Error('浏览器语音需要 HTTPS 或 localhost，并支持麦克风、WebAssembly 和 Web Worker。');
    if(current?.ready&&current.language===language){report(onProgress,'ready',language,language==='zh'?'中文离线识别已就绪。':'Offline English recognition is ready.');return info(language)}
    if(current?.language===language&&current.promise){
      const owner=current;
      const onAbort=()=>owner.abort();signal?.addEventListener('abort',onAbort,{once:true});
      try{const result=await owner.promise;if(signal?.aborted)throw aborted();return result}
      finally{signal?.removeEventListener('abort',onAbort)}
    }
    dispose();
    const token=epoch,record={language,ready:false,model:null,promise:null,cancelled:false,abort:null,urls:[],downloadController:new AbortController()};
    current=record;
    let cancelReject;
    const cancelled=new Promise((_,reject)=>cancelReject=reject);
    record.abort=()=>{if(record.cancelled)return;record.cancelled=true;record.downloadController.abort();cancelReject(aborted());record.rejectLoad?.(aborted());forceFree(record)};
    const onAbort=()=>record.abort();
    signal?.addEventListener('abort',onAbort,{once:true});
    const work=(async()=>{
      report(onProgress,'loading-library',language,language==='zh'?'正在加载本地语音识别程序…':'Loading the local speech engine…');
      await loadLibrary();
      if(record.cancelled||token!==epoch||signal?.aborted)throw aborted();
      const archive=await loadArchive(language,record,onProgress);
      if(record.cancelled||token!==epoch||signal?.aborted)throw aborted();
      report(onProgress,'loading-model',language,language==='zh'?'模型校验完成，正在初始化中文识别…':'Model verified. Initializing English recognition…');
      const model=record.model=modelFromArchive(archive.stableURL,archive.blob,record);
      await new Promise((resolve,reject)=>{
        let finished=false;
        const complete=error=>{if(finished)return;finished=true;clearTimeout(timer);model.removeEventListener('load',onLoad);model.removeEventListener('error',onError);model.worker?.removeEventListener('error',onWorkerError);record.rejectLoad=null;error?reject(error):resolve()};
        const onLoad=e=>complete(e.detail?.result?null:new Error('识别模型加载失败。'));
        const onError=e=>complete(new Error('识别模型加载失败：'+(e.detail?.error||'请刷新页面后重试。')));
        const onWorkerError=()=>complete(new Error('语音识别线程启动失败，请检查浏览器内存和网站资源。'));
        const timer=setTimeout(()=>complete(new Error('模型加载超过三分钟，请检查网络、模型文件或设备内存。')),180000);
        record.rejectLoad=complete;
        model.addEventListener('load',onLoad);model.addEventListener('error',onError);model.worker?.addEventListener('error',onWorkerError);
      });
      if(record.cancelled||token!==epoch||signal?.aborted){forceFree(record);throw aborted()}
      for(const url of record.urls)URL.revokeObjectURL(url);record.urls=[];
      record.ready=true;
      report(onProgress,'ready',language,language==='zh'?'中文离线识别已就绪，录音不会上传。':'Offline English recognition is ready. Audio will not be uploaded.');
      return info(language);
    })();
    record.promise=Promise.race([work,cancelled]).catch(error=>{forceFree(record);throw error}).finally(()=>signal?.removeEventListener('abort',onAbort));
    return record.promise;
  }
  async function transcribe(samples,language='zh',signal){
    if(signal?.aborted)throw aborted();
    if(!(samples instanceof Float32Array)||samples.length<4000||samples.length>320000)throw new Error('识别输入须为 16 kHz 单声道 Float32Array，时长 0.25–20 秒。');
    if(active)throw new Error('已有语音正在识别，请先停止。');
    await prepare(language,undefined,signal);
    if(signal?.aborted)throw aborted();
    if(active)throw new Error('已有语音正在识别，请先停止。');
    const owner=current,started=performance.now();
    // Preserve the caller's buffer; the vendor maps values and transfers its copy.
    const data=Float32Array.from(samples,value=>Number.isFinite(value)?Math.max(-1,Math.min(1,value)):0);
    return new Promise((resolve,reject)=>{
      let recognizer,phase='audio',finished=false,timer;
      const parts=[];
      const task={abort:()=>finish(aborted(),true)};
      const finish=(error,terminate=false)=>{
        if(finished)return;finished=true;clearTimeout(timer);
        signal?.removeEventListener('abort',onAbort);
        if(recognizer){recognizer.removeEventListener('result',onResult);recognizer.removeEventListener('partialresult',onPartial);recognizer.removeEventListener('error',onError);try{recognizer.remove()}catch(_){}}
        owner.model?.removeEventListener('error',onModelError);
        owner.model?.worker?.removeEventListener('error',onWorkerError);
        if(active===task)active=null;
        if(terminate)forceFree(owner);
        if(error){reject(error);return}
        const text=parts.join(' ').replace(/\s+/g,' ').trim();
        resolve({...info(language),text:language==='zh'?text.replace(/\s+/g,''):text,duration_ms:Math.round(performance.now()-started)});
      };
      const onAbort=()=>finish(aborted(),true);
      const onError=e=>finish(new Error('语音识别失败：'+(e.detail?.error||'未知错误')),true);
      const onModelError=e=>onError(e);
      const onWorkerError=()=>finish(new Error('语音识别线程已中止，请重试或输入文字。'),true);
      const requestFinal=()=>{if(phase!=='audio')return;phase='final';try{recognizer.retrieveFinalResult()}catch(e){finish(e,true)}};
      const onResult=e=>{const text=e.detail?.result?.text;if(text)parts.push(String(text).trim());if(phase==='final')finish();else requestFinal()};
      const onPartial=()=>requestFinal();
      try{
        if(!owner?.ready)throw new Error('识别模型已关闭，请重试。');
        recognizer=new owner.model.KaldiRecognizer(16000);
        active=task;
        recognizer.addEventListener('result',onResult);recognizer.addEventListener('partialresult',onPartial);recognizer.addEventListener('error',onError);
        owner.model.addEventListener('error',onModelError);owner.model.worker?.addEventListener('error',onWorkerError);
        signal?.addEventListener('abort',onAbort,{once:true});
        timer=setTimeout(()=>finish(new Error('本机识别超时，请缩短提问或使用文字输入。'),true),45000);
        if(signal?.aborted){onAbort();return}
        recognizer.acceptWaveformFloat(data,16000);
      }catch(error){finish(error,true)}
    });
  }
  window.DuckoBrowserASR=Object.freeze({supported,prepare,transcribe,cancel,dispose,languages:Object.freeze(Object.keys(models)),getStatus:()=>({supported:supported(),ready:!!current?.ready,language:current?.language||null,preparing:!!current&&!current.ready,busy:!!active,engine:'vosk-browser'})});
  window.addEventListener('pagehide',dispose);
})();
