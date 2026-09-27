import {api,el} from './core4.js';
const params=new URLSearchParams(location.search),role=params.get('role')==='family'?'family':'elder',family=role==='family';
document.documentElement.dataset.pet=String(params.get('pet')==='1');
const $=id=>document.getElementById(id),request=(path,options)=>api(role,path,options);
let editing=null,noticeTimer,loading=0;
function notify(text,error=false){clearTimeout(noticeTimer);$('message').textContent=text;$('message').hidden=false;$('message').dataset.error=String(error);noticeTimer=setTimeout(()=>$('message').hidden=true,error?8000:3600);}
function tab(memory){$('reminders').hidden=memory;$('memories').hidden=!memory;$('remTab').setAttribute('aria-pressed',String(!memory));$('memTab').setAttribute('aria-pressed',String(memory));$('message').hidden=true;}
$('remTab').onclick=()=>tab(false);$('memTab').onclick=()=>tab(true);
function localInput(date){const d=new Date(date);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}
function dateText(at){return new Date(at).toLocaleString('zh-CN',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});}
async function action(button,run){if(button.disabled)return;button.disabled=true;try{await run();await load();}catch(e){notify(window.YouHuo.errorWords(e).text,true);}finally{button.disabled=false;}}
function button(text,handler,subtle=true){const b=el('button',subtle?'subtle':'',text);b.type='button';b.onclick=()=>action(b,()=>handler(b));return b;}
function editReminder(item=null){editing=item?.id||null;$('remFormTitle').textContent=item?'修改提醒':'新提醒';$('remTitle').value=item?.title||'';$('remDue').value=localInput(item?.at||Date.now()+3600000);$('escalation').closest('label').hidden=!!item;$('remForm').hidden=false;$('remTitle').focus();}
$('addReminder').onclick=()=>editReminder();$('cancelRem').onclick=()=>$('remForm').hidden=true;
$('remForm').onsubmit=e=>{e.preventDefault();const title=$('remTitle').value.trim(),due=new Date($('remDue').value);if(!title)return notify('请写下要提醒的事。',true);if(!Number.isFinite(due.getTime())||due.getTime()<=Date.now())return notify('请选择还没到的时间。',true);action(e.submitter,async()=>{
 const base={title,at:due.toISOString()};
 if(editing)await request(`/api/v1/reminders/${encodeURIComponent(editing)}`,{method:'PATCH',body:base});
 else if(family){const ids=await window.YouHuo.ready();await request('/v2/family/reminders',{method:'POST',body:{elder_id:ids.elderId,title,due_at:due.toISOString(),escalation_after_minutes:Number($('escalation').value),request_id:crypto.randomUUID()}});}
 else await request('/api/v1/reminders',{method:'POST',body:{...base,escalationAfterMinutes:Number($('escalation').value)}});
 $('remForm').hidden=true;notify(editing?'提醒已修改。':'提醒已保存。');editing=null;
});};
function renderReminders(data){$('remList').replaceChildren();$('pastList').replaceChildren();let active=0,ended=0;
 for(const item of data.items){const closed=item.done||item.cancelled,card=el('article','note');card.append(el('div','time',dateText(item.at)),el('h2','',item.title),el('span','tag',item.overdue?'已过时间 · 待完成':item.status));
 if(!closed){active++;const actions=el('div','actions');if(!family)actions.append(button('已办好',async()=>{await request(`/api/v1/reminders/${encodeURIComponent(item.id)}/done`,{method:'POST'});notify('已记为完成。');},false));actions.append(button('改时间',()=>editReminder(item)),button('取消提醒',async()=>{if(!confirm(`取消“${item.title}”的提醒？`))return;await request(`/api/v1/reminders/${encodeURIComponent(item.id)}/cancel`,{method:'POST'});notify('提醒已取消。');}));card.append(actions);}else ended++;
 $(closed?'pastList':'remList').append(card);
 }if(!active)$('remList').append(el('p','empty','还没有待办，点“＋ 添加”记一件吧。'));$('past').hidden=!ended;
}
$('addMemory').onclick=()=>{$('memForm').hidden=false;$('memKey').focus();};$('cancelMem').onclick=()=>$('memForm').hidden=true;
$('saveMemory').textContent=family?'提议，请本人同意':'保存并同意';$('scopeLabel').hidden=family;$('memoryNote').textContent=family?'家人提议，由老人本人决定。':'由你决定记什么、谁能看。';
$('memForm').onsubmit=e=>{e.preventDefault();const key=$('memKey').value.trim(),detail=$('memDetail').value.trim(),purpose=$('memPurpose').value.trim();if(!key||!detail||!purpose)return notify('请填好名称、内容和用途。',true);action(e.submitter,async()=>{const ids=await window.YouHuo.ready();const item=await request('/v3/memories/propose',{method:'POST',body:{elder_id:ids.elderId,key,value:{说明:detail},purpose,sensitivity:'preference',scope:family?'family_summary':$('memScope').value}});
 if(!family){try{await request(`/api/v1/memories/${encodeURIComponent(item.id)}/approve`,{method:'POST'});}catch(e){$('memForm').hidden=true;notify('内容已保存为待确认，请在列表里点“同意记住”。',true);return;}}
 $('memForm').reset();$('memForm').hidden=true;notify(family?'已提议，等待本人同意。':'已经记住，可随时忘记。');});};
function renderMemories(data){$('memList').replaceChildren();for(const [items,pending] of [[data.pending,true],[data.items,false]])for(const item of items){const card=el('article',`note memory${pending?' pending':''}`);card.append(el('span','tag',pending?(family?'等待本人同意':'等你点头'):item.scope),el('h2','',item.key),el('p','',item.detail),el('p','fine',`用途：${item.purpose}`));if(item.daysLeft!==null&&item.daysLeft!==undefined)card.append(el('p','fine',`剩余 ${item.daysLeft} 天`));
 if(!family){const actions=el('div','actions');for(const [label,endpoint] of pending?[['同意记住','approve'],['不记住','decline']]:[['忘记这条','forget']])actions.append(button(label,async()=>{if(endpoint==='forget'&&!confirm(`让小优忘记“${item.key}”？`))return;await request(`/api/v1/memories/${encodeURIComponent(item.id)}/${endpoint}`,{method:'POST'});notify(endpoint==='approve'?'已同意记住。':endpoint==='decline'?'已拒绝这条记忆。':'已忘记这条。');},endpoint!=='approve'));card.append(actions);} $('memList').append(card);}
 if(!data.pending.length&&!data.items.length)$('memList').append(el('p','empty',data.message||'还没有记忆，点“＋ 添加”记一件吧。'));
}
async function load(){const id=++loading;const results=await Promise.allSettled([request('/api/v1/reminders'),request('/api/v1/memories')]);if(id!==loading)return;for(const [index,result]of results.entries()){if(result.status==='fulfilled')(index?renderMemories:renderReminders)(result.value);else{const target=$(index?'memList':'remList');target.replaceChildren(el('p','empty','暂时没取到记录，请点右上角刷新。'));notify(window.YouHuo.errorWords(result.reason).text,true);}}}
$('reload').onclick=()=>action($('reload'),async()=>{});tab(params.get('tab')==='memory');
parent.postMessage({type:'app4:shell-ready'},location.origin);
load().finally(()=>parent.postMessage({type:'app4:ready'},location.origin));
window.addEventListener('pagehide',()=>clearTimeout(noticeTimer));
