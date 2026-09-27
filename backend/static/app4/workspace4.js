// The same business controllers run inside an app subpage, without a second shell.
const view = new URLSearchParams(location.search).get('view');
if (new URLSearchParams(location.search).get('pet') === '1') document.documentElement.dataset.petTheme = 'cloud';
if (parent !== window) {
  try {
    if (parent.document.body.classList.contains('a4-elder')) {
      document.body.dataset.appRole = 'elder';
      if (parent.document.body.dataset.fontTier === 'huge') document.body.dataset.fontTier = 'huge';
    }
  } catch (_) { /* Standalone documents retain their normal type scale. */ }
}
const businessReady = new Set(['elder','family','care','trust'].filter(name =>
  document.documentElement.dataset['businessReady'+name[0].toUpperCase()+name.slice(1)] === 'true'));
function publishReady() {
  const expected = document.getElementById('elderPhone') ? ['elder']
    : document.getElementById('familyPhone') ? ['care','family'] : ['trust'];
  if (!expected.every(name => businessReady.has(name))) return;
  simplifyForms();
  document.querySelectorAll('.app-viewport > .panel').forEach(panel => { panel.scrollTop = 0; });
  document.documentElement.dataset.workspaceReady = 'true';
  requestAnimationFrame(()=>requestAnimationFrame(()=>parent.postMessage({type:'app4:ready'}, location.origin)));
}
document.addEventListener('app4:business-ready', event => {
  businessReady.add(event.detail); publishReady();
});
if (['habits','privacy','reminders','assistant','history','safety','med','body','mood','trend','today'].includes(view)) document.documentElement.dataset.view = view;

// Recompose the actual controls, preserving nodes, IDs, form state and handlers.
// The business modules can continue to fill their original output containers.
document.querySelectorAll('.panel[data-panel] > .section-head').forEach(heading => {
  const group = document.createElement('section');
  group.className = 'workspace-group';
  heading.before(group);
  let node = heading;
  while (node && !(node !== heading && node.matches?.('.section-head'))) {
    const next = node.nextSibling;
    group.append(node); node = next;
  }
});
document.querySelectorAll('.data-tools > .service-entry').forEach(button => {
  const card = document.createElement('section');
  card.className = 'workspace-data-card';
  card.dataset.kind = button.id;
  button.before(card);
  const output = button.nextElementSibling;
  card.append(button);
  if (output?.classList.contains('data-out')) card.append(output);
});
const introductions = {
  habits:['看得清，听得舒服','选好后，记得保存。'],
  privacy:['我的资料','查看记录，管理记忆。'],
  reminders:['记下一件事','先提醒本人，需要时再通知家人。'],
  safety:['家人的守护','联系人与安全设置。'],
  history:['办过的事','进度和结果，都在这里。'],
  med:['用药手账','照医嘱登记，由本人确认。'],
  body:['身体手账','记下读数和就医安排。'],
  mood:['心情小记','只看变化，不展示聊天原文。'],
  trend:['这一周','和自己的往常比一比。'],
  today:['今日足迹','看看今天留下的记录。'],
};
const active = document.getElementById('elderPhone')
  ? document.querySelector(`[data-panel="${view === 'history' ? 'log' : view === 'reminders' ? 'home' : 'me'}"]`)
  : document.querySelector(`[data-panel="${view === 'history' ? 'mine' : view === 'reminders' ? 'todo' : 'care'}"]`);
if (introductions[view] && active) {
  const hero = document.createElement('div'); hero.className = 'workspace-intro';
  const title = document.createElement('strong'); title.textContent = introductions[view][0];
  const note = document.createElement('p'); note.textContent = introductions[view][1];
  hero.append(title,note); active.prepend(hero);
}
// Keep primary records on screen. Forms and explanations open on demand.
function fold(node, label) {
  if (!node || node.closest('.workspace-fold')) return;
  const details = document.createElement('details'); details.className = 'workspace-fold';
  if (node.matches('form') || node.querySelector('form')) details.classList.add('workspace-add');
  const summary = document.createElement('summary'); summary.textContent = label;
  node.before(details); details.append(summary,node);
}
for (const [id,label] of [['reminderForm','添加提醒'],['memoryForm','提议一条记忆']]) {
  const form = document.getElementById(id);
  if (form) fold(form.closest('.workspace-group') || form,label);
}
fold(document.querySelector('.promise-list'),'使用与隐私说明');
fold(document.getElementById('notices')?.closest('.workspace-group'),'查看通知');
function simplifyForms() {
  document.querySelectorAll('.care-form').forEach(form => {
    if (form.hidden) form.dataset.workspaceManaged = 'true';
    if (form.dataset.workspaceManaged) return;
    // Existing composers already own the visibility of their hidden forms.
    if (form.closest('.workspace-fold') || form.dataset.workspaceFolded) return;
    form.dataset.workspaceFolded = 'true';
    const title = form.querySelector('h3')?.textContent.trim();
    fold(form, title === '记一笔' ? '添加身体记录' : title || '添加记录');
  });
  document.querySelectorAll('.care-detail .meta:not(.bad)').forEach(note => {
    if (note.textContent.length > 95 && !note.closest('details,form') && !note.querySelector('button,input')) fold(note,'了解详情');
  });
}
let simplifyPending=false;
new MutationObserver(()=>{if(simplifyPending)return;simplifyPending=true;requestAnimationFrame(()=>{simplifyPending=false;simplifyForms();});}).observe(document.body,{childList:true,subtree:true});
simplifyForms();
document.addEventListener('invalid', event => {
  const section = event.target.closest('.workspace-fold');
  if (section) section.open = true;
},true);
document.querySelectorAll('.workspace-data-card > .service-entry').forEach(button => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.workspace-data-card .data-out').forEach(output => {
      if (!button.parentElement.contains(output)) output.hidden = true;
    });
  });
});

document.addEventListener('click', event => {
  const link = event.target.closest('a[href]');
  if (!link) return;
  const url = new URL(link.href, location.href);
  if (url.origin === location.origin && url.pathname === '/trust') {
    event.preventDefault(); parent.postMessage({type:'app4:trust'}, location.origin); return;
  }
  if (url.origin === location.origin && ['/', '/elder2', '/family2', '/elder4', '/family4'].includes(url.pathname)) {
    event.preventDefault(); parent.postMessage({type:'app4:close'}, location.origin);
  }
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && document.body.dataset.focus !== 'on' && !document.querySelector('[aria-modal="true"]:not([hidden])')) {
    parent.postMessage({type:'app4:close'}, location.origin);
  }
});

// A cached business script may finish before this deferred adapter installs its listener.
publishReady();

// Pet notes reveal one task at a time, keeping full working controls on demand.
if (new URLSearchParams(location.search).get('pet') === '1') {
  document.querySelectorAll('.workspace-group').forEach(group => {
    if(group.closest('.workspace-fold')) return;
    const heading=group.querySelector('.section-head');
    if(!heading)return;
    const label=heading.querySelector('h2,h3,strong')?.textContent?.trim() || heading.textContent.trim();
    if(!label)return;
    const detail=document.createElement('details');detail.className='pet-section';
    const summary=document.createElement('summary');summary.textContent=label;
    const content=document.createElement("div");content.append(...group.childNodes);detail.append(summary,content);group.append(detail);
    detail.addEventListener('toggle',()=>{if(detail.open)document.querySelectorAll('.pet-section[open]').forEach(other=>{if(other!==detail)other.open=false;});});
  });
}
if (new URLSearchParams(location.search).get('pet') === '1') {
  document.addEventListener('invalid',event=>{let n=event.target.parentElement;while(n){if(n.tagName==='DETAILS')n.open=true;n=n.parentElement;}},true);
}

// Reveal the correct section while its independent data requests finish.
if(new URLSearchParams(location.search).get('pet')==='1'){
  const shellReady=()=>parent.postMessage({type:'app4:shell-ready'},location.origin);
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',shellReady,{once:true});else shellReady();
}
