(function(){
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* opening */
  const opening = document.getElementById('lotusOpening');
  const replay = document.getElementById('motionReplay');
  let openingTimer = null;
  function closeOpening(){
    if (!opening) return;
    opening.classList.add('is-done');
    clearTimeout(openingTimer);
  }
  function playOpening(){
    if (!opening || reduce) return;
    opening.classList.remove('is-done');
    // Force animation restart for pseudo-elements by cloning.
    const clone = opening.cloneNode(true);
    opening.replaceWith(clone);
    clone.addEventListener('click',()=>clone.classList.add('is-done'));
    openingTimer=setTimeout(()=>clone.classList.add('is-done'),2350);
  }
  if(opening && !reduce){
    opening.addEventListener('click',closeOpening);
    openingTimer=setTimeout(closeOpening,2350);
  } else if(opening) {
    opening.classList.add('is-done');
  }
  if(replay) replay.addEventListener('click',playOpening);

  /* character-by-character ink reveal */
  function inkReveal(el, baseDelay=0){
    if(!el || reduce) return;
    const label = el.textContent;
    el.setAttribute('aria-label', label);
    el.classList.add('ink-reveal');
    el.textContent='';
    [...label].forEach((ch,i)=>{
      const s=document.createElement('span');
      s.className='ink-char';
      s.setAttribute('aria-hidden','true');
      s.textContent=ch === ' ' ? '\u00a0' : ch;
      s.style.animationDelay=(baseDelay+i*42)+'ms';
      el.appendChild(s);
    });
  }
  document.querySelectorAll('.identity-island h1, .center-message h3, .care-center h3').forEach((el,i)=>inkReveal(el, 80+i*55));

  /* Pointer drag: move the spatial layers, then spring home */
  document.querySelectorAll('.main-stage').forEach(stage=>{
    let down=false, sx=0, sy=0, px=0, py=0, moved=false;
    const maxX=24, maxY=18;
    const setVars=(x,y)=>{
      stage.style.setProperty('--drag-x', x+'px');
      stage.style.setProperty('--drag-y', y+'px');
      stage.style.setProperty('--drag-x-soft', (x*.55)+'px');
      stage.style.setProperty('--drag-y-soft', (y*.55)+'px');
    };
    const reset=()=>{
      stage.classList.remove('is-dragging');
      setVars(0,0);
      down=false;
    };
    stage.addEventListener('pointerdown',e=>{
      if(reduce || e.target.closest('button,a')) return;
      down=true; moved=false; sx=e.clientX; sy=e.clientY; px=0; py=0;
      stage.classList.add('is-dragging');
      stage.setPointerCapture?.(e.pointerId);
    });
    stage.addEventListener('pointermove',e=>{
      if(!down) return;
      const dx=Math.max(-maxX,Math.min(maxX,(e.clientX-sx)*.16));
      const dy=Math.max(-maxY,Math.min(maxY,(e.clientY-sy)*.16));
      if(Math.abs(dx)>1 || Math.abs(dy)>1) moved=true;
      px=dx;py=dy;setVars(dx,dy);
    });
    stage.addEventListener('pointerup',e=>{
      if(down && !moved) spawnRipple(e.clientX,e.clientY);
      reset();
    });
    stage.addEventListener('pointercancel',reset);
    stage.addEventListener('lostpointercapture',reset);
  });

  function spawnRipple(x,y){
    if(reduce) return;
    const r=document.createElement('span');
    r.className='stage-ripple';
    r.style.left=x+'px';r.style.top=y+'px';
    document.body.appendChild(r);
    setTimeout(()=>r.remove(),700);
  }

  function spawnLotus(x,y){
    if(reduce) return;
    const l=document.createElement('span');
    l.className='lotus-burst';
    l.style.left=x+'px';l.style.top=y+'px';
    document.body.appendChild(l);
    setTimeout(()=>l.remove(),650);
  }

  /* click feedback */
  document.addEventListener('pointerup',e=>{
    const target=e.target.closest('.dock button, .app-switch button, .care-tabs button, .mode button');
    if(target){
      spawnLotus(e.clientX,e.clientY);
    } else if(e.target.closest('button,.orbit')){
      spawnRipple(e.clientX,e.clientY);
    }
  });

  /* Re-run slow ink reveal when main state changes */
  const stageTitle = document.getElementById('stageTitle');
  const mainHeadline = document.getElementById('mainHeadline');
  document.querySelectorAll('[data-family]').forEach(btn=>{
    btn.addEventListener('click',()=>{
      if(reduce) return;
      setTimeout(()=>{
        [stageTitle,mainHeadline].forEach((el,i)=>{
          if(!el) return;
          const plain=el.getAttribute('aria-label') || el.textContent;
          // Only if current nodes are not already freshly animated
          el.classList.remove('ink-reveal');
          el.textContent=plain;
          inkReveal(el,70+i*40);
        });
      },20);
    });
  });
})();
