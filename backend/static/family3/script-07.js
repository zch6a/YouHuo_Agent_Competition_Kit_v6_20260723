(function(){
  const reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function bloomWorkspace(ws){
    if(!ws || ws.hidden || reduce) return;
    ws.querySelector('.bubble-flow')?.classList.remove('flow-sequence-active');
    ws.classList.remove('page-bloom');
    void ws.offsetWidth;
    ws.classList.add('page-bloom');
  }

  function visibleWorkspace(){
    return document.querySelector('.workspace:not([hidden])');
  }

  /* initial page: wait until lotus opening is gone */
  const opening=document.getElementById('lotusOpening');
  function waitOpening(){
    if(opening && !opening.classList.contains('is-done')){
      setTimeout(waitOpening,160);return;
    }
    bloomWorkspace(visibleWorkspace());
  }
  setTimeout(waitOpening,260);

  /* after each cinematic completely ends, replay the page growth sequence */
  const scene=document.getElementById('pageScene');
  if(scene){
    let wasPlaying=false;
    new MutationObserver(()=>{
      const playing=scene.classList.contains('playing');
      if(playing){
        wasPlaying=true;
        visibleWorkspace()?.classList.remove('page-bloom');
      }else if(wasPlaying){
        wasPlaying=false;
        setTimeout(()=>bloomWorkspace(visibleWorkspace()),180);
      }
    }).observe(scene,{attributes:true,attributeFilter:['class']});
  }

  /* mode tags: animate underline and swap */
  document.querySelectorAll('.identity-island .mode').forEach(mode=>{
    mode.querySelectorAll('button').forEach(btn=>{
      btn.addEventListener('click',()=>{
        mode.querySelectorAll('button').forEach(x=>x.classList.remove('active'));
        btn.classList.add('active');
      });
    });
  });

  /* subtle three-depth pointer parallax */
  document.querySelectorAll('.workspace').forEach(ws=>{
    let tx=0,ty=0,raf=0;
    function apply(){
      raf=0;
      ws.style.setProperty('--scene-px',tx.toFixed(1)+'px');
      ws.style.setProperty('--scene-py',ty.toFixed(1)+'px');
    }
    ws.addEventListener('pointermove',e=>{
      if(e.pointerType==='touch') return;
      const r=ws.getBoundingClientRect();
      tx=((e.clientX-r.left)/r.width-.5)*22;
      ty=((e.clientY-r.top)/r.height-.5)*16;
      if(!raf) raf=requestAnimationFrame(apply);
    });
    ws.addEventListener('pointerleave',()=>{
      tx=0;ty=0;if(!raf)raf=requestAnimationFrame(apply);
    });
  });
})();
