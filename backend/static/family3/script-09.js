(function(){
  const tabs=[...document.querySelectorAll('#careTabs [data-care-panel]')];
  const panels=[...document.querySelectorAll('[data-care-page]')];
  if(!tabs.length||!panels.length) return;

  function showCarePage(name){
    tabs.forEach(t=>t.classList.toggle('active',t.dataset.carePanel===name));
    panels.forEach(p=>{
      const on=p.dataset.carePage===name;
      p.classList.toggle('active',on);
      p.classList.remove('entering');
      if(on){
        void p.offsetWidth;
        p.classList.add('entering');
        if(name==='overview'){
          const cv=document.getElementById('careView');
          cv?.classList.remove('five-vein-ready');
          void cv?.offsetWidth;
          cv?.classList.add('five-vein-ready');
        }
      }
    });
  }

  tabs.forEach(tab=>{
    tab.addEventListener('click',e=>{
      e.stopPropagation();
      showCarePage(tab.dataset.carePanel);
    },true);
  });

  // Start on overview.
  showCarePage('overview');
  window.showYouHuoCarePage=showCarePage;
})();
