import {createPetFan} from './pet-fan4.js';
import {createIdleChatter} from './pet-chatter4.js';
import {createPetHub} from './pet-hub4.js';
const KEY = 'youhuo.pet.position.v1';
const family = document.body.classList.contains('a4-family');
const pet = document.createElement('button');
pet.type = 'button';
pet.className = 'a4-pet';
pet.setAttribute('aria-label', '小优，点击互动，按住可以拖动');
pet.setAttribute('aria-haspopup', 'dialog');
pet.setAttribute('aria-expanded', 'false');
pet.innerHTML = '<img src="/static/app4/xiaoyou/poster.webp" width="96" height="96" alt="" draggable="false"><span aria-live="polite">小优</span>';
const hub = createPetHub(pet, family);
const menu = hub.menu;
const radial = createPetFan(pet, family, key => {
  hub.show();
  if(key==='chat') hub.chat(false);
  else if(key==='memory') hub.feature(family?'reminders':'privacy');
  else if(key==='tasks') hub.panel(family?'todo':'record',family?'需要我确认的事':'今天的记录');
  else if(key==='contacts') hub.panel('family','联系家人');
  else if(key==='messages') hub.panel('msg','收到的消息');
  else if(key==='care') hub.panel('care','照护档案');
  else hub.home();
  placeMenu(); menu.querySelector('button').focus({preventScroll:true});
});
function close() { radial.hide(); if (!menu.hidden) hub.hide(); }
document.body.append(pet, menu);
let position;
try { position = JSON.parse(localStorage.getItem(KEY)); } catch (_) {}
if (!position || !Number.isFinite(position.x) || !Number.isFinite(position.y)) {
  const app = document.querySelector('.a4-app')?.getBoundingClientRect();
  position = {x: (app?.right || innerWidth) - 76, y: innerHeight - 216};
}
function bounds() {
  const v = window.visualViewport;
  return {x: v?.offsetLeft || 0, y: v?.offsetTop || 0,
    width: v?.width || innerWidth, height: v?.height || innerHeight};
}
function place() {
  const b = bounds();
  position.x = Math.max(b.x, Math.min(position.x, b.x + b.width - pet.offsetWidth));
  position.y = Math.max(b.y, Math.min(position.y, b.y + b.height - pet.offsetHeight));
  pet.style.left = `${position.x}px`; pet.style.top = `${position.y}px`;
  if (!menu.hidden) placeMenu(); if (!radial.fan.hidden) radial.layout();
}
function save() { try { localStorage.setItem(KEY, JSON.stringify(position)); } catch (_) {} }
function placeMenu() {
  const b = bounds(), gap=10;
  const above=position.y-b.y-gap, below=b.y+b.height-position.y-pet.offsetHeight-gap;
  const side=above>=below?'above':'below';
  const room=Math.max(above,below);
  menu.style.height=`${Math.min(360,Math.max(100,room-8))}px`;
  menu.style.left=`${Math.max(b.x+8,Math.min(position.x-150,b.x+b.width-menu.offsetWidth-8))}px`;
  menu.style.top=`${side==='above'?position.y-menu.offsetHeight-gap:position.y+pet.offsetHeight+gap}px`;

}
function open() {
  hub.warm();
  radial.show();
  if (agentState === 'idle') setState('greeting');
}
let gesture = null, timer, suppressClick = false;
pet.addEventListener('pointerdown', e => {
  if (!e.isPrimary || e.button !== 0) return;
  suppressClick = false;
  gesture = {id:e.pointerId, x:e.clientX, y:e.clientY, origin:{...position}, moved:false};
  pet.setPointerCapture(e.pointerId);
  timer = setTimeout(() => { if (gesture && !gesture.moved) { suppressClick = true; open(); } }, 550);
});
pet.addEventListener('pointermove', e => {
  if (!gesture || e.pointerId !== gesture.id) return;
  const dx = e.clientX - gesture.x, dy = e.clientY - gesture.y;
  if (!gesture.moved && Math.hypot(dx, dy) < 7) return;
  gesture.moved = true; suppressClick = true; clearTimeout(timer); close();
  pet.classList.add('is-dragging');
  position = {x:gesture.origin.x + dx, y:gesture.origin.y + dy}; place();
});
function finish(e) {
  if (!gesture || e.pointerId !== gesture.id) return;
  clearTimeout(timer);
  if (e.type === 'pointercancel') suppressClick = true;
  if (gesture.moved) {
    save();
    if (e.type === 'pointerup') window.dispatchEvent(new Event('app4:pet-moved'));
  }
  gesture = null; pet.classList.remove('is-dragging');
}
pet.addEventListener('pointerup', finish);
pet.addEventListener('pointercancel', finish);
pet.addEventListener('lostpointercapture', finish);
pet.addEventListener('click', e => {
  if (suppressClick && e.detail !== 0) { suppressClick = false; return; }
  (menu.hidden && (radial.fan.hidden || radial.fan.classList.contains("is-closing"))) ? open() : close();
});
pet.addEventListener('contextmenu', e => { e.preventDefault(); clearTimeout(timer); suppressClick = true; open(); });
pet.addEventListener('keydown', e => {
  const delta = {ArrowLeft:[-10,0], ArrowRight:[10,0], ArrowUp:[0,-10], ArrowDown:[0,10]}[e.key];
  if (delta) { e.preventDefault(); position.x += delta[0]; position.y += delta[1]; place(); save(); }
});
document.addEventListener('pointerdown', e => { if (!pet.contains(e.target) && !menu.contains(e.target) && !radial.fan.contains(e.target)) close(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && (!menu.hidden || !radial.fan.hidden)) { close(); pet.focus(); } });
window.addEventListener('resize', place);
window.visualViewport?.addEventListener('resize', place);
window.visualViewport?.addEventListener('scroll', place);
place();
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const states = {
  idle:['idle','小优'], greeting:['happy','我在呢'], listening:['love','我在听'],
  thinking:['guide','正在处理'], confirmation:['guide','等您确认'],
  result:['happy','有回复了'], error:['idle','请看消息'],
};
const portrait = pet.querySelector('img');
portrait.addEventListener('error', () => {
  if (!portrait.getAttribute('src').endsWith('/poster.webp')) portrait.src = '/static/app4/xiaoyou/poster.webp';
});
let agentState = 'idle', resetState, quiet = false;
window.addEventListener('app4:pet-quiet', e => { quiet = !!e.detail?.quiet; renderState(); });
function renderState() {
  const [action, label] = states[agentState];
  const file = document.hidden || reduced.matches || quiet ? 'poster' : action;
  const source = `/static/app4/xiaoyou/${file}.webp`;
  if (portrait.getAttribute('src') !== source) portrait.src = source;
  pet.querySelector('span').textContent = label;
  pet.dataset.state = agentState;
}
function setState(state) {
  if (!Object.hasOwn(states, state)) return;
  if (state === 'greeting' && ['listening','thinking','confirmation'].includes(agentState)) return;
  clearTimeout(resetState);
  agentState = state;
  renderState();
  if (['greeting','result','error'].includes(state)) resetState = setTimeout(() => setState('idle'), 6000);
}
window.addEventListener('app4:agent-state', e => setState(e.detail?.state));
document.addEventListener('visibilitychange', renderState);
reduced.addEventListener('change', renderState);
// Only the current animation is requested; the desktop frame library is never downloaded.
if ('requestIdleCallback' in window) requestIdleCallback(renderState, {timeout:1500});
else setTimeout(renderState, 400);
createIdleChatter(pet,{canSpeak:()=>agentState==='idle'&&!gesture&&menu.hidden&&radial.fan.hidden&&!document.body.classList.contains('a4-workspace-open')&&(document.getElementById('sheet')?.hidden??true)});


