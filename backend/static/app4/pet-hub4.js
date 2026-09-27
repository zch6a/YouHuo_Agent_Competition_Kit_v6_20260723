import {features} from './shell4.js';
import {chatterPreference,cycleChatter} from './pet-chatter4.js';

// The pet hosts existing business controls, retaining their handlers and identity.
// No cloned forms, second login or alternate source of business state.
export function createPetHub(pet, family) {
  const menu = document.createElement('section');
  menu.className = 'a4-pet-menu a4-pet-hub'; menu.hidden = true;
  menu.setAttribute('role','dialog'); menu.setAttribute('aria-label','和小优互动');
  menu.setAttribute('aria-modal','true');
  menu.innerHTML = '<header class="pet-hub-head"><button type="button" class="pet-hub-back" aria-label="返回小优">‹</button><div><strong>小优在这里</strong></div><button type="button" class="pet-hub-close" aria-label="收起小优">收起</button></header><div class="pet-hub-body"></div>';
  const body = menu.querySelector('.pet-hub-body');
  const title = menu.querySelector('strong');
  let moved = null, timer = null, quiet = false, activeFeature = null;
  let warmed=false;
  function warm(){
    if(warmed)return;warmed=true;
    for(const href of [`/static/app4/${family?"family":"elder"}-workspace.html`,"/static/app4/pet-art/pocket-note.png"]){const link=document.createElement("link");link.rel="prefetch";link.href=href;document.head.append(link);}
  }
  function button(label, action, note) {
    const b = document.createElement('button'); b.type='button';
    const name=document.createElement('span');name.textContent=label;b.append(name);
    if(note){const s=document.createElement('small');s.textContent=note;b.append(s);}
    b.addEventListener('click',action);return b;
  }
  function release() {
    clearTimeout(timer);activeFeature=null;
    if(moved){
      const {node,marker,hidden}=moved;
      if(node.id==='sheet'){document.getElementById('sheetClose')?.click();const shortcuts=node.querySelector('.pet-chat-shortcuts');if(shortcuts){const quick=shortcuts.querySelector('.a4-quick');shortcuts.replaceWith(quick);}}
      marker.replaceWith(node);node.hidden=hidden;moved=null;
    }
    body.replaceChildren();
  }
  function home() {
    release(); title.textContent='小优在这里';
    const grid=document.createElement('div');grid.className='pet-hub-tools';body.append(grid);
    const primary=family?['reminders','med','body','mood']:['assistant','reminders','privacy','history'];
    const names={reminders:'记个提醒',med:'记下用药',body:'记个读数',mood:'记下心情',assistant:'聊一聊',privacy:'替我记着',history:'查进度'};
    for(const key of primary){const b=button(names[key],()=>key==='assistant'?chat(false):feature(key));b.dataset.petFeature=key;grid.append(b);}
    const chatter=button(`碎碎念：${{normal:'偶尔说说',lively:'活泼一点',off:'已关闭'}[chatterPreference()]}`,()=>{cycleChatter();home();});
    chatter.className='pet-chatter-setting';body.append(chatter);
    const controls=document.createElement('div');controls.className='pet-hub-companion';
    controls.append(button('摸摸头',()=>window.dispatchEvent(new CustomEvent('app4:agent-state',{detail:{state:'greeting'}}))),button(quiet?'恢复动作':'安静陪着',()=>{quiet=!quiet;window.dispatchEvent(new CustomEvent('app4:pet-quiet',{detail:{quiet}}));home();}));body.append(controls);
  }
  function mount(node, label) {
    release();title.textContent=label;
    const marker=document.createComment('pet-host-return');
    moved={node,marker,hidden:node.hidden};node.replaceWith(marker);body.append(node);node.hidden=false;
  }
  function panel(key,label){if(key==='care'){release();title.textContent='照顾一下';const grid=document.createElement('div');grid.className='pet-hub-tools';for(const k of ['med','body','mood','safety','trend']){const b=button(features[k][0],()=>feature(k));b.dataset.petFeature=k;grid.append(b);}body.append(grid);return;}const node=document.querySelector(`[data-panel="${key}"]`);if(node)mount(node,label);}
  function chat(voice){
    const sheet=document.getElementById('sheet');if(!sheet)return;
    mount(sheet,'和小优说说');
    const quick=sheet.querySelector('.a4-quick');
    if(quick){const shortcuts=document.createElement('details');shortcuts.className='pet-chat-shortcuts';const summary=document.createElement('summary');summary.textContent='常用说法';quick.before(shortcuts);shortcuts.append(summary,quick);}
    sheet.hidden=true;
    window.dispatchEvent(new CustomEvent('app4:pet-chat',{detail:{voice}}));
  }
  function feature(key){
    if(key==='assistant'&&!family){chat(false);return;}
    const spec=features[key];if(!spec)return;
    if(activeFeature===key&&body.querySelector("iframe"))return;
    release();activeFeature=key;title.textContent=spec[0];
    const loading=document.createElement('p');loading.className='pet-hub-loading';loading.setAttribute('role','status');loading.textContent='小优正在打开…';
    const frame=document.createElement('iframe');frame.title=spec[0];frame.allow='microphone';frame.setAttribute('aria-busy','true');frame.inert=true;
    frame.src=key==='trust'?'/static/app4/trust-workspace.html?pet=1':`/static/app4/${family?'family':'elder'}-workspace.html?view=${key}&pet=1#${spec[1]}`;
    body.append(loading,frame);timer=setTimeout(()=>loading.textContent='打开较慢，可以返回小优再试。',12000);
  }
  window.addEventListener('message',e=>{
    const frame=body.querySelector('iframe');if(!frame||e.origin!==location.origin||e.source!==frame.contentWindow)return;
    if(e.data?.type==='app4:ready'){frame.inert=false;frame.removeAttribute('aria-busy');body.querySelector('.pet-hub-loading')?.remove();clearTimeout(timer);}
    if(e.data?.type==='app4:close')home();
    if(e.data?.type==='app4:trust')feature('trust');
  });
  window.addEventListener('app4:pet-feature',e=>{if(!menu.hidden)feature(e.detail?.key);});
  function show(){menu.hidden=false;pet.setAttribute('aria-expanded','true');document.querySelector('.a4-app').inert=true;document.querySelector('.a4-tabs').inert=true;}
  function hide(){menu.hidden=true;pet.setAttribute('aria-expanded','false');if(moved){release();home();}if(!document.body.classList.contains('a4-workspace-open')){document.querySelector('.a4-app').inert=false;document.querySelector('.a4-tabs').inert=false;}pet.focus({preventScroll:true});window.dispatchEvent(new Event('app4:refresh'));}
  menu.querySelector('.pet-hub-back').onclick=home;menu.querySelector('.pet-hub-close').onclick=hide;
  menu.addEventListener('keydown',e=>{if(e.key!=='Tab')return;const controls=[...menu.querySelectorAll('button,input,textarea,select,summary,iframe')].filter(n=>!n.disabled&&n.getClientRects().length);const first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}});
  home();return {menu,show,hide,home,feature,panel,chat,warm};
}

