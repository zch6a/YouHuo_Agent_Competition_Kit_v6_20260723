const familyView=document.getElementById('familyView');
const careView=document.getElementById('careView');
const appBtns=[...document.querySelectorAll('[data-app]')];
function showApp(name){
  const care=name==='care';
  familyView.hidden=care; careView.hidden=!care;
  appBtns.forEach(b=>b.classList.toggle('active',b.dataset.app===name));
}
appBtns.forEach(b=>b.addEventListener('click',()=>showApp(b.dataset.app)));
document.getElementById('goCare').onclick=()=>showApp('care');
document.getElementById('backFamily').onclick=()=>showApp('family');

const headline=document.getElementById('mainHeadline');
const copy=document.getElementById('mainCopy');
const stageTitle=document.getElementById('stageTitle');
const main=document.getElementById('familyMain');

const states={
 today:['今天最重要的事','有一件事需要您确认','燃气费缴纳已经核对到最后一步。金额 ¥86.50，确认后系统才会继续执行。'],
 todo:['待办与提醒','接下来最重要的是周五复诊','病历已经整理，系统会在明天早上再次提醒。'],
 mine:['我的记录','最近完成了 5 件重要事项','确认、提醒和照护记录都会在这里留下清晰的时间线。']
};
document.querySelectorAll('[data-family]').forEach(btn=>btn.addEventListener('click',()=>{
 document.querySelectorAll('[data-family]').forEach(x=>x.classList.remove('active'));
 btn.classList.add('active');
 const s=states[btn.dataset.family];
 stageTitle.textContent=s[0];headline.textContent=s[1];copy.textContent=s[2];
 main.classList.remove('todo-stage','mine-stage');
 if(btn.dataset.family==='todo')main.classList.add('todo-stage');
 if(btn.dataset.family==='mine')main.classList.add('mine-stage');
 headline.animate([{opacity:.2,transform:'translateY(8px)'},{opacity:1,transform:'none'}],{duration:300,easing:'cubic-bezier(.2,.8,.2,1)'});
}));

document.querySelectorAll('.clickable').forEach(el=>{
  el.addEventListener('pointerdown',()=>{el.classList.remove('pressed');void el.offsetWidth;el.classList.add('pressed')});
  el.addEventListener('animationend',()=>el.classList.remove('pressed'));
});
