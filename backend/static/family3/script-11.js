(function(){
  const careView=document.getElementById('careView');
  const tabs=[...document.querySelectorAll('#careTabs [data-care-panel]')];
  const panels=[...document.querySelectorAll('[data-care-page]')];

  function syncOverviewClean(){
    const careVisible=careView && !careView.hidden;
    const overview=panels.find(p=>p.dataset.carePage==='overview');
    const overviewActive=!!(overview && overview.classList.contains('active'));
    document.body.classList.toggle('care-overview-clean',careVisible && overviewActive);
  }

  tabs.forEach(tab=>{
    tab.addEventListener('click',()=>requestAnimationFrame(syncOverviewClean));
  });

  if(careView){
    new MutationObserver(syncOverviewClean).observe(careView,{
      attributes:true,
      attributeFilter:['hidden']
    });
  }

  panels.forEach(panel=>{
    new MutationObserver(syncOverviewClean).observe(panel,{
      attributes:true,
      attributeFilter:['class']
    });
  });

  syncOverviewClean();
})();
