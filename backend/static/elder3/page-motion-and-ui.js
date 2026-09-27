(function(){
  const scene=document.getElementById('pageScene');
  const nameEl=document.getElementById('sceneName');
  const subEl=document.getElementById('sceneSub');
  const kickerEl=document.getElementById('sceneKicker');
  const vine=document.getElementById('vineField');
  const SCENES={
    today:{name:'今天',kicker:'YOUHUO · TODAY',sub:'先看今天最重要的一件事',duration:1680},
    todo:{name:'记录',kicker:'YOUHUO · RECORDS',sub:'做过的事，都有清楚来路',duration:1680},
    care:{name:'家人',kicker:'YOUHUO · FAMILY',sub:'重要时刻，多问一句更安心',duration:1820},
    mine:{name:'我的',kicker:'YOUHUO · MINE',sub:'调成您最舒服的样子',duration:1840}
  };
  let t1=null,t2=null,navToken=0;

  function fillName(txt){nameEl.textContent='';[...txt].forEach(ch=>{const s=document.createElement('span');s.textContent=ch;nameEl.appendChild(s)})}
  const entryTimers=new WeakMap();
  function settleWorkspace(ws){
    if(!ws)return;
    ws.classList.remove('entering');
    ws.classList.add('settled');
  }
  function replayEntry(ws){
    if(!ws)return;
    const oldTimer=entryTimers.get(ws);
    if(oldTimer)clearTimeout(oldTimer);

    // Start from a stable visible state, then temporarily enter choreography.
    ws.classList.remove('settled','entering');
    void ws.offsetWidth;
    ws.classList.add('entering');

    vine?.classList.remove('grow');
    setTimeout(()=>{void vine?.offsetWidth;vine?.classList.add('grow')},280);

    // Crucial V2.2 fix: transition into an explicit FINAL visible state.
    const timer=setTimeout(()=>settleWorkspace(ws),2600);
    entryTimers.set(ws,timer);
  }
  function activate(page){
    document.querySelectorAll('.workspace').forEach(w=>w.classList.toggle('active',w.dataset.workspace===page));
    document.querySelectorAll('.dock [data-page]').forEach(b=>b.classList.toggle('active',b.dataset.page===page));
    replayEntry(document.querySelector(`.workspace[data-workspace="${page}"]`));
  }

  /* This playCinematic is intentionally the same choreography/controller as family V5.8.4. */
  function playCinematic(type,x=innerWidth*.5,y=innerHeight*.55,page=null){
    const cfg=SCENES[type]||SCENES.today; const token=++navToken;
    clearTimeout(t1);clearTimeout(t2);
    scene.classList.remove('finishing','playing');scene.removeAttribute('data-scene');
    kickerEl.textContent=cfg.kicker;subEl.textContent=cfg.sub;fillName(cfg.name);
    scene.style.setProperty('--scene-x',x+'px');scene.style.setProperty('--scene-y',y+'px');
    void scene.offsetWidth;document.body.classList.add('scene-transition');scene.dataset.scene=type;scene.classList.add('playing');
    vine?.classList.remove('grow');
    setTimeout(()=>{if(token===navToken && page)activate(page)},Math.min(720,cfg.duration*.42));
    t1=setTimeout(()=>{if(token!==navToken)return;scene.classList.add('finishing');document.body.classList.remove('scene-transition')},cfg.duration-500);
    t2=setTimeout(()=>{if(token!==navToken)return;scene.classList.remove('playing','finishing');scene.removeAttribute('data-scene')},cfg.duration);
  }
  window.playYouHuoCinematic=playCinematic;

  document.querySelectorAll('.dock [data-page]').forEach(btn=>btn.addEventListener('pointerup',e=>{
    const current=document.querySelector('.workspace.active')?.dataset.workspace;
    if(current===btn.dataset.page)return;
    playCinematic(btn.dataset.sceneType,e.clientX,e.clientY,btn.dataset.page);
  }));

  document.getElementById('dockContact').addEventListener('pointerup',e=>{
    playCinematic('care',e.clientX,e.clientY,'family');
    setTimeout(()=>document.getElementById('contactFamily')?.animate([{transform:'translateY(0)'},{transform:'translateY(-4px)'},{transform:'translateY(0)'}],{duration:520,easing:'ease-out'}),900);
  });

  /* Immediate initial growth: no full-screen intro so user lands in the real app. */
  setTimeout(()=>replayEntry(document.querySelector('.workspace.active')),120);

  /* V2.2: browser/tab lifecycle safety.
     Some browsers cancel CSS animations when the tab is hidden or when
     rendering is interrupted. Always settle the active workspace afterward. */
  function settleActiveWorkspace(){
    const ws=document.querySelector('.workspace.active');
    if(ws && !ws.classList.contains('entering')) settleWorkspace(ws);
  }
  document.addEventListener('visibilitychange',()=>{
    if(!document.hidden){
      const ws=document.querySelector('.workspace.active');
      if(ws) setTimeout(()=>settleWorkspace(ws),40);
    }
  });
  window.addEventListener('pageshow',()=>{
    const ws=document.querySelector('.workspace.active');
    if(ws) setTimeout(()=>settleWorkspace(ws),40);
  });
  window.addEventListener('resize',()=>{
    const ws=document.querySelector('.workspace.active');
    if(ws && !ws.classList.contains('entering')) settleWorkspace(ws);
  });
  document.addEventListener('animationcancel',e=>{
    const ws=e.target.closest?.('.workspace');
    if(ws && ws.classList.contains('active')) setTimeout(()=>settleWorkspace(ws),0);
  },true);

  /* Same spatial-stage behavior from family: drag empty stage slightly, spring back. */
  document.querySelectorAll('.right-stage').forEach(stage=>{
    let down=false,sx=0,sy=0,moved=false;
    const setVars=(x,y)=>{stage.style.setProperty('--drag-x',x+'px');stage.style.setProperty('--drag-y',y+'px');stage.style.setProperty('--drag-x-soft',(x*.55)+'px');stage.style.setProperty('--drag-y-soft',(y*.55)+'px')};
    const reset=()=>{stage.classList.remove('is-dragging');setVars(0,0);down=false};
    stage.addEventListener('pointerdown',e=>{if(e.target.closest('button,a'))return;down=true;moved=false;sx=e.clientX;sy=e.clientY;stage.classList.add('is-dragging');stage.setPointerCapture?.(e.pointerId)});
    stage.addEventListener('pointermove',e=>{if(!down)return;const dx=Math.max(-22,Math.min(22,(e.clientX-sx)*.15));const dy=Math.max(-16,Math.min(16,(e.clientY-sy)*.15));if(Math.abs(dx)>1||Math.abs(dy)>1)moved=true;setVars(dx,dy)});
    stage.addEventListener('pointerup',e=>{if(down&&!moved)spawnRipple(e.clientX,e.clientY);reset()});stage.addEventListener('pointercancel',reset);
  });
  function spawnRipple(x,y){const r=document.createElement('span');r.className='stage-ripple';r.style.left=x+'px';r.style.top=y+'px';document.body.appendChild(r);setTimeout(()=>r.remove(),700)}
  function spawnLotus(x,y){const r=document.createElement('span');r.className='lotus-burst';r.style.left=x+'px';r.style.top=y+'px';document.body.appendChild(r);setTimeout(()=>r.remove(),650)}
  document.addEventListener('pointerup',e=>{if(e.target.closest('.dock button,.mode-switch button'))spawnLotus(e.clientX,e.clientY);else if(e.target.closest('button'))spawnRipple(e.clientX,e.clientY)});

  document.querySelectorAll('.segmented').forEach(seg=>seg.addEventListener('click',e=>{const b=e.target.closest('.seg-btn');if(!b)return;seg.querySelectorAll('.seg-btn').forEach(x=>x.classList.toggle('active',x===b))}));
  const toast=document.getElementById('companionToast'),you=document.getElementById('modeYouhuo'),comp=document.getElementById('modeCompanion');
  function setMode(c){you.classList.toggle('active',!c);comp.classList.toggle('active',c);toast.textContent=c?'无忧伴模式 · 只聊天，不把聊天内容记进办事记录。':'优活模式 · 继续帮您记事、办事和做必要确认。';toast.classList.add('show');clearTimeout(toast._t);toast._t=setTimeout(()=>toast.classList.remove('show'),2500)} you.onclick=()=>setMode(false);comp.onclick=()=>setMode(true);
  document.getElementById('voiceOrb').addEventListener('click',()=>{const b=document.querySelector('.voice-caption b'),old=b.textContent;b.textContent='正在听，请慢慢说…';setTimeout(()=>b.textContent=old,2100)});
  document.getElementById('savePref').addEventListener('click',e=>{const old=e.currentTarget.textContent;e.currentTarget.textContent='✓ 已保存';setTimeout(()=>e.currentTarget.textContent=old,1500)});
})();
