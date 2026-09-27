/* One recording session at a time. No audio is kept in browser storage. */
export function createVoiceInput({role='elder',onText,onHint,onState}) {
  let session=null, generation=0, phase="idle";
  const state=value=>{phase=value;onState(value);};
  async function request(path,options={},timeout=20000){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);try{return await window.YouHuo.api(path,{...options,signal:controller.signal},role);}catch(e){if(e.name==='AbortError')throw new Error('连接超时，请稍后再试。');throw e;}finally{clearTimeout(timer);}}
  const status=()=>request('/api/v1/listen/web/status');
  const hint=message=>onHint(message);
  function cleanup(s){clearTimeout(s.timer);if(s.processor){s.processor.onaudioprocess=null;try{s.processor.disconnect();}catch(_){}}for(const node of [s.source,s.gain]){try{node?.disconnect();}catch(_){}}s.stream?.getTracks().forEach(t=>t.stop());s.context?.close().catch(()=>{});}
  function cancel(){generation++;const s=session;session=null;if(s){s.cancelled=true;try{s.recognition?.abort();}catch(_){}cleanup(s);}state('idle');}
  async function finish(){const s=session;if(!s)return;if(s.recognition){s.recognition.stop();return;}session=null;cleanup(s);state('processing');hint('正在把您的话转成文字…');
    try {
      const length=s.chunks.reduce((n,a)=>n+a.length,0);if(length<s.rate*.25)throw new Error('按住说一句话，松开后再识别。');
      const Offline=window.OfflineAudioContext||window.webkitOfflineAudioContext;
      const offline=new Offline(1,Math.ceil(length*16000/s.rate),16000),buffer=offline.createBuffer(1,length,s.rate),channel=buffer.getChannelData(0);let at=0;for(const chunk of s.chunks){channel.set(chunk,at);at+=chunk.length;}
      const source=offline.createBufferSource();source.buffer=buffer;source.connect(offline.destination);source.start();const rendered=await offline.startRendering();if(s.cancelled||s.id!==generation)return;
      const samples=rendered.getChannelData(0),bytes=new ArrayBuffer(44+samples.length*2),view=new DataView(bytes);const word=(o,w)=>{for(let i=0;i<w.length;i++)view.setUint8(o+i,w.charCodeAt(i));};word(0,'RIFF');view.setUint32(4,36+samples.length*2,true);word(8,'WAVE');word(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);word(36,'data');view.setUint32(40,samples.length*2,true);for(let i=0;i<samples.length;i++)view.setInt16(44+i*2,Math.max(-32768,Math.min(32767,Math.round(samples[i]*32767))),true);
      const result=await request('/api/v1/listen/web',{method:'POST',headers:{'Content-Type':'audio/wav'},body:new Blob([bytes],{type:'audio/wav'})},45000);
      if(s.id!==generation)return;if(result.heard&&result.text){onText(result.text);hint('听写好了，核对后点发送。');}else hint('没有听清，靠近话筒再说一次吧。');
    }catch(e){if(s.id===generation)hint(e.message||'识别暂时没成功，请重试。');}finally{if(s.id===generation)state('idle');}
  }
  async function start(){if(session||phase==='preparing'||phase==='processing')return;const id=++generation;state('preparing');hint('正在准备话筒…');
    if(!window.isSecureContext&&!window.YouhuoNative){hint('语音输入需要安全连接，请使用 https://youhuo.onrender.com/phone');state('idle');return;}
    try {
      let available;try{available=await status();}catch(_){available=null;}if(id!==generation)return;
      const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
      if(!available?.available&&Recognition){
        const recognition=new Recognition(),s={id,recognition,cancelled:false};session=s;recognition.lang='zh-CN';recognition.continuous=true;recognition.interimResults=true;recognition.maxAlternatives=1;let finalText='',failed=false;
        recognition.onstart=()=>{if(id!==generation)return;state('listening');hint('正在听，松开后转成文字。');};
        recognition.onresult=e=>{if(id!==generation)return;let final=[],interim=[];for(const r of e.results)(r.isFinal?final:interim).push(r[0].transcript);finalText=final.join('');hint(finalText||interim.join('')||'我在听…');};
        recognition.onerror=e=>{failed=true;const messages={'not-allowed':'请在地址栏的网站权限中允许麦克风，再试一次。','service-not-allowed':'浏览器识别不可用，服务端正在准备，请稍后再点话筒。','audio-capture':'没有找到可用话筒，请检查麦克风。','network':'浏览器识别连接失败，服务端正在准备，请稍后再试。','no-speech':'没有听到声音，请靠近话筒再说一次。'};if(id===generation)hint(messages[e.error]||'这次没听清，请再试一次。');};
        recognition.onend=()=>{cleanup(s);if(session===s)session=null;if(id!==generation)return;state('idle');if(!s.cancelled&&finalText){onText(finalText);hint('听写好了，核对后点发送。');}else if(!failed&&!s.cancelled)hint('没有听到完整的话，请再试一次。');};
        s.timer=setTimeout(()=>recognition.stop(),20000);try{recognition.start();}catch(e){cleanup(s);session=null;throw e;}return;
      }
      if(!available?.available){hint(available?.note||'语音识别暂未就绪，请稍后再点话筒。');state('idle');return;}
      if(!navigator.mediaDevices?.getUserMedia)throw new Error('当前浏览器不支持录音，请使用系统浏览器打开。');
      const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true},video:false});if(id!==generation){stream.getTracks().forEach(t=>t.stop());return;}
      const s={id,stream,chunks:[]};session=s;const Context=window.AudioContext||window.webkitAudioContext,context=new Context();s.context=context;await context.resume();if(id!==generation){stream.getTracks().forEach(t=>t.stop());await context.close();return;}
      const source=context.createMediaStreamSource(stream),processor=context.createScriptProcessor(4096,1,1),gain=context.createGain();gain.gain.value=0;Object.assign(s,{source,processor,gain,rate:context.sampleRate});
      processor.onaudioprocess=e=>{if(session!==s)return;const max=Math.floor(s.rate*19),used=s.chunks.reduce((n,a)=>n+a.length,0);if(used>=max){finish();return;}s.chunks.push(e.inputBuffer.getChannelData(0).slice(0,max-used));};source.connect(processor);processor.connect(gain);gain.connect(context.destination);s.timer=setTimeout(finish,19000);state('listening');hint('正在听，松开后转文字（最多20秒）。');
    }catch(e){if(id!==generation)return;if(session){cleanup(session);session=null;}state('idle');hint(e.name==='NotAllowedError'?'请在地址栏的网站权限中允许麦克风，再试一次。':e.name==='NotFoundError'?'没有找到话筒，请检查设备。':e.message||'话筒未能启动，请重试。');}
  }
  window.addEventListener('pagehide',cancel);
  return {start,stop:()=>phase==='preparing'?cancel():finish(),cancel,warm:()=>status().catch(()=>null)};
}

// Pointer capture preserves release even when the finger leaves the button.
export function bindHoldToTalk(button, voice, beforeStart=()=>{}) {
  let pressed=false;
  button.style.touchAction='none';button.style.userSelect='none';
  button.setAttribute('aria-label','按住说话，松开转文字');
  const begin=()=>{if(pressed||button.disabled)return;pressed=true;beforeStart();voice.start();};
  const end=()=>{if(!pressed)return;pressed=false;voice.stop();};
  const cancel=()=>{if(!pressed)return;pressed=false;voice.cancel();};
  button.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();button.setPointerCapture(e.pointerId);begin();});
  button.addEventListener('pointerup',e=>{e.preventDefault();end();});
  button.addEventListener('pointercancel',cancel);
  button.addEventListener('lostpointercapture',cancel);
  button.addEventListener('keydown',e=>{if([' ','Enter'].includes(e.key)){e.preventDefault();if(!e.repeat)begin();}});
  button.addEventListener('keyup',e=>{if([' ','Enter'].includes(e.key)){e.preventDefault();end();}});
  button.addEventListener('click',e=>e.preventDefault());
  button.addEventListener('contextmenu',e=>e.preventDefault());
  window.addEventListener('blur',cancel);
}
