(function(){
  const reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const vine=document.getElementById('vineField');
  const scene=document.getElementById('pageScene');
  if(!vine || reduce) return;

  let growTimer=null;
  let settleTimer=null;
  let generation=0;

  function clearTimers(){
    clearTimeout(growTimer);
    clearTimeout(settleTimer);
  }

  function resetVine(){
    clearTimers();
    generation++;
    vine.classList.remove('grow','scene-grow','post-entry-grow','post-entry-settled');
  }

  function growAfterEntry(delay=260){
    const token=++generation;
    clearTimers();

    // First show a calm empty edge, then let the plant begin.
    vine.classList.remove('grow','scene-grow','post-entry-grow','post-entry-settled');

    growTimer=setTimeout(()=>{
      if(token!==generation) return;
      if(scene && scene.classList.contains('playing')){
        // Cinematic is still visible: wait. The plant must never grow inside it.
        growAfterEntry(180);
        return;
      }

      vine.classList.add('post-entry-grow');

      // Total visual growth ~4.9s. Then freeze in the completed state.
      settleTimer=setTimeout(()=>{
        if(token!==generation) return;
        vine.classList.remove('post-entry-grow');
        vine.classList.add('post-entry-settled');
      },5050);
    },delay);
  }

  /* Initial app opening:
     wait for the lotus opening to fully disappear, THEN grow on the real home page. */
  const opening=document.getElementById('lotusOpening');
  function waitInitialEntry(){
    if(opening && !opening.classList.contains('is-done')){
      setTimeout(waitInitialEntry,180);
      return;
    }
    growAfterEntry(420);
  }
  setTimeout(waitInitialEntry,300);

  /* Every full cinematic page switch:
     reset immediately, then observe until cinematic is fully gone.
     Only then begin the slow ivy growth. */
  const observer=new MutationObserver(()=>{
    if(!scene) return;

    if(scene.classList.contains('playing')){
      resetVine();
      return;
    }

    // "playing" has been removed = the cinematic is completely finished.
    if(!scene.classList.contains('playing')){
      growAfterEntry(320);
    }
  });

  if(scene){
    observer.observe(scene,{attributes:true,attributeFilter:['class']});
  }

  /* Expose for preview/debug. */
  window.restartYouHuoPostEntryVine=()=>growAfterEntry(0);
})();
