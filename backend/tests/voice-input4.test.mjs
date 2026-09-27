import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const source=await fs.readFile('backend/static/app4/voice-input4.js','utf8');
const {createVoiceInput,bindHoldToTalk}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
let rec,calls=0;
class Recognition { constructor(){rec=this;} start(){this.onstart();} stop(){this.onend();} abort(){this.onend();} }
globalThis.window={isSecureContext:true,SpeechRecognition:Recognition,YouHuo:{api:async()=>{calls++;return {available:false};}},addEventListener(){}};
const words=[],hints=[],states=[];
let voice=createVoiceInput({onText:t=>words.push(t),onHint:t=>hints.push(t),onState:s=>states.push(s)});
await Promise.all([voice.start(),voice.start()]);assert.equal(calls,1);assert.equal(states.at(-1),'listening');
const results=['明天','浇花'].map(t=>Object.assign([{transcript:t}],{isFinal:true}));
rec.onresult({results});await voice.stop();assert.deepEqual(words,['明天浇花']);assert.equal(states.at(-1),'idle');
await voice.start();const old=rec;voice.cancel();old.onresult({results});old.onend();assert.equal(words.length,1);
await voice.start();rec.onerror({error:'not-allowed'});rec.onend();assert.match(hints.at(-1),/允许麦克风/);
window.isSecureContext=false;await voice.start();assert.match(hints.at(-1),/https/);assert.equal(states.at(-1),'idle');
console.log('PASS duplicate click, transcript, cancellation, denied permission, insecure context');
// Server microphone path: samples -> WAV -> transcript, plus cleanup on denial/cancel.
window.isSecureContext=true;delete window.SpeechRecognition;
let processor,stopped=0,posted;
Object.defineProperty(globalThis,'navigator',{value:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop(){stopped++;}}]})}},configurable:true});
class Context{sampleRate=48000;async resume(){} async close(){} createMediaStreamSource(){return {connect(){},disconnect(){}};}createScriptProcessor(){return processor={connect(){},disconnect(){}};}createGain(){return {gain:{},connect(){},disconnect(){}};}}
class Offline{constructor(ch,len,rate){this.len=len;}createBuffer(ch,len){return {getChannelData:()=>new Float32Array(len)};}createBufferSource(){return {connect(){},start(){}};}async startRendering(){return {getChannelData:()=>new Float32Array(this.len)};}}
window.AudioContext=Context;window.OfflineAudioContext=Offline;voice=createVoiceInput({onText:t=>words.push(t),onHint:t=>hints.push(t),onState:s=>states.push(s)});
window.YouHuo.api=async(path,options)=>{if(path.endsWith('status'))return {available:true};posted=options.body;return {heard:true,text:'提醒我浇花'};};
await voice.start();processor.onaudioprocess({inputBuffer:{getChannelData:()=>new Float32Array(48000)}});await voice.stop();assert.equal(stopped,1);assert.equal(words.at(-1),'提醒我浇花');const data=new DataView(await posted.arrayBuffer());assert.equal(data.getUint32(24,true),16000);assert.equal(data.byteLength,32044);assert.equal(states.at(-1),'idle');
navigator.mediaDevices.getUserMedia=async()=>{throw Object.assign(new Error(),{name:'NotAllowedError'});};await voice.start();assert.match(hints.at(-1),/允许麦克风/);assert.equal(states.at(-1),'idle');
let release;navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>release=resolve);const pending=voice.start();await new Promise(resolve=>setImmediate(resolve));voice.cancel();release({getTracks:()=>[{stop(){stopped++;}}]});await pending;assert.equal(stopped,2);assert.equal(states.at(-1),'idle');
console.log('PASS WAV resampling/upload, track release, denied recording, cancel during permission');

const handlers={},events=[],control={style:{},setAttribute(){},setPointerCapture(){},addEventListener(name,fn){handlers[name]=fn;}};
bindHoldToTalk(control,{start(){events.push('start');},stop(){events.push('stop');},cancel(){events.push('cancel');}});
const pointer={button:0,pointerId:1,preventDefault(){}};
handlers.pointerdown(pointer);handlers.pointerup(pointer);handlers.lostpointercapture(pointer);assert.deepEqual(events,['start','stop']);
handlers.pointerdown(pointer);handlers.pointercancel(pointer);assert.deepEqual(events,['start','stop','start','cancel']);
handlers.keydown({key:' ',preventDefault(){}});handlers.keyup({key:' ',preventDefault(){}});assert.deepEqual(events.slice(-2),['start','stop']);
console.log('PASS hold/release/cancel and keyboard hold gestures');
