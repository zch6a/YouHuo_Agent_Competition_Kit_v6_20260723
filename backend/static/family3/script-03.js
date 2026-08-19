(function(){
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const scene = document.getElementById('pageScene');
  const vine = document.getElementById('vineField');

  function restartVine(){
    if(!vine || reduce) return;
    vine.classList.remove('grow');
    void vine.offsetWidth;
    vine.classList.add('grow');
  }

  function playScene(type, x=window.innerWidth*.58, y=window.innerHeight*.48){
    if(!scene || reduce) return;
    scene.classList.remove('playing');
    scene.removeAttribute('data-scene');
    scene.style.setProperty('--scene-x', x+'px');
    scene.style.setProperty('--scene-y', y+'px');
    void scene.offsetWidth;
    scene.dataset.scene=type;
    scene.classList.add('playing');
    setTimeout(()=>scene.classList.remove('playing'), type==='mine' ? 1180 : 980);
  }

  /* V5.4.3.2: no vine animation during opening/cinematic.
     The post-entry controller below owns vine growth. */

  /* Family page buttons: today / todo / mine get distinct scenes */
  document.querySelectorAll('[data-family]').forEach(btn=>{
    btn.addEventListener('pointerup',e=>{
      const type=btn.dataset.family;
      if(type==='today'||type==='todo'||type==='mine'){
        playScene(type,e.clientX,e.clientY);
      }
    });
  });

  /* Care entry gets its own crane scene */
  const goCare=document.getElementById('goCare');
  if(goCare){
    goCare.addEventListener('pointerup',e=>playScene('care',e.clientX,e.clientY));
  }

  /* App switch: direct care/family transition */
  document.querySelectorAll('[data-app]').forEach(btn=>{
    btn.addEventListener('pointerup',e=>{
      const type=btn.dataset.app==='care'?'care':'today';
      playScene(type,e.clientX,e.clientY);
    });
  });

  /* Care bottom back-to-today button */
  const back=document.getElementById('backFamily');
  if(back){
    back.addEventListener('pointerup',e=>playScene('today',e.clientX,e.clientY));
  }

  /* Care top module tabs: keep care language, but replay smaller */
  document.querySelectorAll('.care-tabs button').forEach(btn=>{
    btn.addEventListener('pointerup',e=>playScene('care',e.clientX,e.clientY));
  });

  window.playYouHuoScene=playScene;
})();
