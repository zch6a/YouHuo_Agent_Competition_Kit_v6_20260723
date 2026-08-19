// 这一份只管**外壳**：底栏切面板、照护页的二级分区、概览行跳转。
//
// 凡是「按一下会有后果」的控件，处理器一律在 family.js / care.js 里，这里一个都不放。
// 上一版这里另外接了 #refresh 和 #reminderForm，后果是这一页最要紧的写操作是坏的：
//
//   * 经典脚本在解析时执行，模块脚本在解析完之后执行。所以这里的 submit 处理器
//     **排在 family.js 的 createReminder 前面**。它先跑，先 `e.target.reset()`，
//     等 createReminder 再去读 `#reminderTitle.value` 时已经是空串——
//     于是真正的那一条走进「事项还没填」分支，一个请求都不发。
//   * 而这里同时往 `#notices` 写了一句「已加入待办，会同步到他的手机」。
//     那句话在**零请求**的情况下印在屏幕上。这一页的全部主张是「说到做到、
//     每一步可核验」，一句凭空的成功回执正好是它的反面。
//   * `#refresh` 那一条还有第三层：它 1.8 秒后无条件 `familyNotice.hidden=true`。
//     family.js 的 notify() 写的就是这个元素——刷新失败时那句真话会在 1.8 秒后
//     被这里抹掉，屏幕回到一片正常。
//
// 结论：外壳不碰数据，也不替后端说话。
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
    // 七个分区放大到 48px 触控高度之后一行装不下，这排胶囊要横向滚。
    // 不把当前那个滚进视野的话，点「安全」「趋势」时选中的那个只露半个字——
    // 也就是说，屏幕上唯一指示「你在哪一节」的东西正好是被切掉的那一个。
    const on=careBtns.find(b=>b.dataset.careSection===name);
    if(on&&on.scrollIntoView) on.scrollIntoView({block:'nearest',inline:'center'});
  }
  careBtns.forEach(b=>b.addEventListener('click',()=>showCare(b.dataset.careSection)));
  document.querySelectorAll('.care-row[data-care-target]').forEach(row=>row.addEventListener('click',()=>{
    showCare(row.dataset.careTarget);
    document.querySelector('.panel[data-panel="care"]').scrollTo({top:0,behavior:'smooth'});
  }));

  /* 锚点也要能打到二级分区。
   *
   * common.js 的 initSections 认得 `#ovSafety` 这种锚点——它会找到那个 id、
   * 往上找到它所在的 `[data-panel]`，然后把**照护面板**打开。但它到此为止：
   * 照护面板内部还停在「概览」，而 `#ovSafety` 这个名字指的是「安全」那一节。
   * 于是「家庭成员」这个入口会把人送到照护页的顶上，让他自己再找一次。
   *
   * 这里补最后一跳：锚点若是某个概览行，就按它的 data-care-target 把二级分区
   * 一起切过去；锚点若直接是分区名（`#med`），也认。 */
  function followHash(){
    const raw=location.hash.slice(1);
    if(!raw) return;
    const node=document.getElementById(raw);
    const detail=node&&node.closest&&node.closest('.care-detail');
    const target=
      // 概览里的某一行：它自己写着要去哪一节（`#ovSafety` → 安全）。
      (node&&node.dataset.careTarget)
      // 直接写分区名（`#med`）。
      || (careDetails.some(p=>p.dataset.carePanel===raw)?raw:null)
      // 分区里的某个元素：落到它所在的那一节。
      || (detail?detail.dataset.carePanel:null)
      // 写的是**大面板**名（`#care`）：回到第一节。
      // 只有点 <a href="#care"> 才会走到这里；底栏那四个按钮用的是
      // `history.replaceState`，它不触发 hashchange——所以「切走再切回来
      // 还停在原来那一节」不受影响。
      || (raw==='care'&&careDetails.length?careDetails[0].dataset.carePanel:null);
    if(target) showCare(target);
  }
  addEventListener('hashchange',followHash);
  followHash();
})();
