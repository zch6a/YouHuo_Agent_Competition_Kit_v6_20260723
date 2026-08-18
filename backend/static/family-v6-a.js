(function(){
  const phone=document.getElementById('familyPhone');
  const panels=[...document.querySelectorAll('.app-viewport > [data-panel]')];
  const tabs=[...document.querySelectorAll('.family-tabs [data-section]')];

  function show(name){
    panels.forEach(p=>p.hidden=p.dataset.panel!==name);
    tabs.forEach(b=>{
      const on=b.dataset.section===name;
      b.classList.toggle('is-current',on);
      if(on)b.setAttribute('aria-current','page'); else b.removeAttribute('aria-current');
    });
    phone.dataset.tab=name;
    const panel=document.querySelector(`.app-viewport > [data-panel="${name}"]`);
    if(panel) panel.scrollTop=0;
  }
  tabs.forEach(b=>b.addEventListener('click',()=>show(b.dataset.section)));

  const careBtns=[...document.querySelectorAll('.care-seg button')];
  const careDetails=[...document.querySelectorAll('.care-detail')];
  function showCare(name){
    careBtns.forEach(b=>b.classList.toggle('is-current',b.dataset.careSection===name));
    careDetails.forEach(p=>p.hidden=p.dataset.carePanel!==name);
  }
  careBtns.forEach(b=>b.addEventListener('click',()=>showCare(b.dataset.careSection)));
  document.querySelectorAll('.care-row[data-care-target]').forEach(row=>row.addEventListener('click',()=>{
    showCare(row.dataset.careTarget);
    document.querySelector('.panel[data-panel="care"]').scrollTo({top:0,behavior:'smooth'});
  }));

  document.getElementById('refresh').addEventListener('click',()=>{
    const el=document.getElementById('famUpdated');
    el.textContent='刚刚更新 · 数据已重新核对';
    const n=document.getElementById('familyNotice');
    n.hidden=false;n.textContent='已更新今天的家庭情况。';
    setTimeout(()=>n.hidden=true,1800);
  });

  document.getElementById('reminderForm').addEventListener('submit',e=>{
    e.preventDefault();
    const title=document.getElementById('reminderTitle').value.trim()||'新的提醒';
    const notice=document.getElementById('notices');
    notice.innerHTML=`<div class="notice-line"><strong>${title}</strong><br>已加入待办，会同步到他的手机。</div>`;
    e.target.reset();
  });
})();
