(function(){
  const reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const scene=document.getElementById('pageScene');
  const vine=document.getElementById('vineField');
  const nameEl=document.getElementById('sceneName');
  const subEl=document.getElementById('sceneSub');
  const kickerEl=document.getElementById('sceneKicker');
  if(!scene || reduce) return;

  const SCENES={
    today:{name:'今天',kicker:'YOUHUO · TODAY',sub:'先看今天最重要的一件事',duration:1680},
    todo:{name:'待办',kicker:'YOUHUO · TO-DO',sub:'把接下来的事情理清楚',duration:1680},
    care:{name:'照护',kicker:'YOUHUO · CARE',sub:'从整体状态进入照护细节',duration:1820},
    mine:{name:'我的',kicker:'YOUHUO · MEMORY',sub:'让做过的事留下清晰痕迹',duration:1840}
  };

  let timer1=null,timer2=null,busy=false;

  function fillName(txt){
    nameEl.textContent='';
    [...txt].forEach(ch=>{
      const s=document.createElement('span');
      s.textContent=ch;
      nameEl.appendChild(s);
    });
  }

  function playCinematic(type,x=innerWidth*.5,y=innerHeight*.55){
    const cfg=SCENES[type]||SCENES.today;
    clearTimeout(timer1);clearTimeout(timer2);
    busy=true;

    scene.classList.remove('finishing','playing');
    scene.removeAttribute('data-scene');
    vine?.classList.remove('scene-grow');

    kickerEl.textContent=cfg.kicker;
    subEl.textContent=cfg.sub;
    fillName(cfg.name);
    scene.style.setProperty('--scene-x',x+'px');
    scene.style.setProperty('--scene-y',y+'px');

    void scene.offsetWidth;
    document.body.classList.add('scene-transition');
    scene.dataset.scene=type;
    scene.classList.add('playing');
    /* V5.4.3.2:
       Cinematic is intentionally vine-free.
       Vine starts only AFTER this full-screen scene has completely left. */
    if(vine){
      vine.classList.remove('grow','scene-grow','post-entry-grow','post-entry-settled');
    }

    timer1=setTimeout(()=>{
      scene.classList.add('finishing');
      document.body.classList.remove('scene-transition');
    },cfg.duration-500);

    timer2=setTimeout(()=>{
      scene.classList.remove('playing','finishing');
      scene.removeAttribute('data-scene');
      busy=false;
    },cfg.duration);
  }

  // Capture the major navigation events so the cinematic always fires,
  // even if the underlying preview switches state immediately.
  document.addEventListener('pointerup',e=>{
    const family=e.target.closest('[data-family]');
    if(family){
      const t=family.dataset.family;
      if(t==='today'||t==='todo'||t==='mine'){
        playCinematic(t,e.clientX,e.clientY);
        return;
      }
    }
    if(e.target.closest('#goCare')){
      playCinematic('care',e.clientX,e.clientY);return;
    }
    if(e.target.closest('#backFamily')){
      playCinematic('today',e.clientX,e.clientY);return;
    }
    const app=e.target.closest('[data-app]');
    if(app){
      playCinematic(app.dataset.app==='care'?'care':'today',e.clientX,e.clientY);return;
    }
    const careTab=e.target.closest('.care-tabs button');
    if(careTab){
      playCinematic('care',e.clientX,e.clientY);return;
    }
  },true);

  // Expose for testing / replay.
  window.playYouHuoCinematic=playCinematic;
})();
