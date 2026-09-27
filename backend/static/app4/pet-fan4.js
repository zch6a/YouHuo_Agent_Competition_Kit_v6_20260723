import {icon} from './core4.js';
export function createPetFan(pet, family, choose) {
  const fan=document.createElement('nav');fan.className='a4-pet-fan';fan.hidden=true;
  fan.setAttribute('aria-label','小优快捷功能');
  const items=family?[['办事','check','tasks'],['记忆','record','memory'],['照护','heart','care'],['消息','message','messages'],['更多','more','more']]:[['说话','mic','chat'],['记忆','record','memory'],['进展','check','tasks'],['家人','family','contacts'],['更多','more','more']];
  for(const [label,glyph,key] of items){const b=document.createElement('button');b.type='button';b.dataset.action=key;b.append(icon(glyph));const span=document.createElement('span');span.textContent=label;b.append(span);b.addEventListener('click',()=>{hide();choose(key);});fan.append(b);}
  document.body.append(fan);
  let lastGeometry="";
  function layout(){
    const v=visualViewport, w=v?.width||innerWidth,h=v?.height||innerHeight,ox=v?.offsetLeft||0,oy=v?.offsetTop||0;
    const r=pet.getBoundingClientRect(),cx=r.left+r.width/2,cy=r.top+44;
    const geometry=[w,h,ox,oy,cx,cy].join();if(geometry===lastGeometry)return;lastGeometry=geometry;
    const aim=Math.atan2(oy+h/2-cy,ox+w/2-cx);let best=null;
    // Pick a real arc that fits the available side, including corner positions.
    for(const radius of [112,132,152,176,202,230]) for(const arc of [160,140,120,100,80]) for(const rotate of [0,-15,15,-30,30]){
      const points=items.map((_,i)=>{const a=aim+(rotate-arc/2+arc*i/(items.length-1))*Math.PI/180;return {x:cx+radius*Math.cos(a),y:cy+radius*Math.sin(a)};});
      let score=radius*.08+(160-arc)*.1+Math.abs(rotate)*.02;
      for(const p of points){score+=100*(Math.max(0,ox+38-p.x)+Math.max(0,p.x-(ox+w-38))+Math.max(0,oy+38-p.y)+Math.max(0,p.y-(oy+h-38)));}
      for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++)score+=Math.max(0,70-Math.hypot(points[i].x-points[j].x,points[i].y-points[j].y))*200;
      if(!best||score<best.score)best={points,score};
    }
    [...fan.children].forEach((b,i)=>{const p=best.points[i];const x=Math.max(ox+36,Math.min(ox+w-36,p.x)),y=Math.max(oy+36,Math.min(oy+h-36,p.y));b.style.left=`${x-32}px`;b.style.top=`${y-32}px`;b.style.setProperty('--from-x',`${cx-x}px`);b.style.setProperty('--from-y',`${cy-y}px`);b.style.setProperty('--delay',`${i*18}ms`);});
  }
  function show(){fan.hidden=false;fan.classList.remove('is-closing');layout();pet.setAttribute('aria-expanded','true');fan.querySelector('button').focus({preventScroll:true});}
  let closeTimer;
  function hide(){if(fan.hidden)return;fan.classList.add('is-closing');fan.inert=true;clearTimeout(closeTimer);closeTimer=setTimeout(()=>{fan.hidden=true;fan.inert=false;fan.classList.remove('is-closing');},120);pet.setAttribute('aria-expanded','false');}
  // Opening while the reverse animation runs must not be hidden by its old timer.
  const open=()=>{clearTimeout(closeTimer);fan.inert=false;show();};
  fan.addEventListener('keydown',e=>{const list=[...fan.children],i=list.indexOf(document.activeElement);if(['ArrowRight','ArrowDown','ArrowLeft','ArrowUp'].includes(e.key)){e.preventDefault();list[(i+(['ArrowLeft','ArrowUp'].includes(e.key)?4:1))%5].focus();}});
  return {fan,show:open,hide,layout};
}
