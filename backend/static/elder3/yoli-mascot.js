(function(){
'use strict';

const C={
  O:'#3f352d',
  S:'#f5efe7',
  SH:'#d7ccc2',
  HI:'#fffdf8',
  F:'#173d37',
  FH:'#315b50',
  J:'#5e8d7a',
  JH:'#a1bbaa',
  G:'#c39443',
  GH:'#e4c075',
  R:'#db6857',
  RH:'#f2a993',
  W:'#fffdf8',
  SOLE:'#31594e',
  SD:'rgba(65,48,33,.15)'
};
const DUR={hold:1600,toss:2300,walk:1350,run:1180,talk:1600,happy:1450};

function px(c,x,y,w,h,col){
  c.fillStyle=col;
  c.fillRect(Math.round(x),Math.round(y),Math.round(w),Math.round(h));
}
function line(c,x0,y0,x1,y1,t,col){
  x0=Math.round(x0);y0=Math.round(y0);x1=Math.round(x1);y1=Math.round(y1);
  const dx=Math.abs(x1-x0),sx=x0<x1?1:-1,dy=-Math.abs(y1-y0),sy=y0<y1?1:-1;
  let err=dx+dy;
  while(true){
    px(c,x0-Math.floor(t/2),y0-Math.floor(t/2),t,t,col);
    if(x0===x1&&y0===y1)break;
    const e2=2*err;
    if(e2>=dy){err+=dy;x0+=sx}
    if(e2<=dx){err+=dx;y0+=sy}
  }
}
function rounded(c,x,y,w,h,fill){
  px(c,x+2,y,w-4,1,C.O);
  px(c,x+1,y+1,w-2,1,C.O);
  px(c,x,y+2,w,h-4,C.O);
  px(c,x+1,y+h-2,w-2,1,C.O);
  px(c,x+2,y+h-1,w-4,1,C.O);
  px(c,x+2,y+1,w-4,1,fill);
  px(c,x+1,y+2,w-2,h-4,fill);
  px(c,x+2,y+h-2,w-4,1,fill);
}
function heart(c,x,y,glow=false){
  const r=glow?C.RH:C.R;
  // dark contour
  px(c,x+4,y,5,1,C.O); px(c,x+12,y,5,1,C.O);
  px(c,x+2,y+1,8,1,C.O); px(c,x+11,y+1,8,1,C.O);
  px(c,x+1,y+2,19,2,C.O);
  px(c,x,y+4,21,7,C.O);
  px(c,x+1,y+11,19,2,C.O);
  px(c,x+2,y+13,17,2,C.O);
  px(c,x+4,y+15,13,2,C.O);
  px(c,x+6,y+17,9,2,C.O);
  px(c,x+8,y+19,5,1,C.O);
  px(c,x+10,y+20,1,1,C.O);

  // fill
  px(c,x+4,y+1,5,1,r); px(c,x+12,y+1,5,1,r);
  px(c,x+2,y+2,17,2,r);
  px(c,x+1,y+4,19,6,r);
  px(c,x+2,y+10,17,2,r);
  px(c,x+3,y+12,15,2,r);
  px(c,x+4,y+14,13,2,r);
  px(c,x+6,y+16,9,2,r);
  px(c,x+8,y+18,5,1,r);
  px(c,x+9,y+19,3,1,r);

  // highlight
  px(c,x+4,y+3,3,1,C.W);
  px(c,x+3,y+4,2,3,C.W);
  px(c,x+4,y+7,1,2,'rgba(255,253,248,.70)');
}
function eye(c,x,y,blink=false){
  if(blink){px(c,x,y+2,3,1,C.W);return}
  px(c,x,y,3,5,C.W);
  px(c,x+1,y,1,1,'rgba(255,255,255,.75)');
}
function smile(c,x,y,open=false){
  if(open){
    px(c,x+1,y,7,1,C.W);
    px(c,x+2,y+1,5,1,C.W);
    px(c,x+3,y+2,3,1,C.W);
    return;
  }
  px(c,x,y,1,1,C.W);
  px(c,x+1,y+1,1,1,C.W);
  px(c,x+2,y+2,4,1,C.W);
  px(c,x+6,y+1,1,1,C.W);
  px(c,x+7,y,1,1,C.W);
}
function foot(c,x,y,flip=false){
  px(c,x,y,7,2,C.O);
  px(c,x+(flip?1:0),y,6,1,C.SH);
  px(c,x,y+2,8,1,C.O);
  px(c,x+(flip?1:0),y+2,7,1,C.SOLE);
}
function joint(c,x,y){
  px(c,x-2,y-2,5,5,C.O);
  px(c,x-1,y-1,3,3,C.SH);
  px(c,x,y-1,1,1,C.HI);
}
function segment(c,x0,y0,x1,y1){
  line(c,x0,y0,x1,y1,5,C.O);
  line(c,x0,y0,x1,y1,3,C.S);
  line(c,x0,y0-1,x1,y1-1,1,C.HI);
}
function wrist(c,x,y){
  px(c,x-2,y-2,5,4,C.O);
  px(c,x-1,y-1,3,2,C.SH);
}
function palm(c,x,y,flip=false,open=false){
  if(open){
    px(c,x-2,y-2,5,5,C.O);
    px(c,x-1,y-1,3,3,C.HI);
    const s=flip?-1:1;
    px(c,x+s*2,y-5,1,4,C.O);px(c,x+s*2,y-4,1,3,C.HI);
    px(c,x+s*1,y-6,1,5,C.O);px(c,x+s*1,y-5,1,4,C.HI);
    px(c,x,y-6,1,5,C.O);px(c,x,y-5,1,4,C.HI);
    px(c,x-s*1,y-5,1,4,C.O);px(c,x-s*1,y-4,1,3,C.HI);
    px(c,x-s*2,y,2,1,C.O);
    return
  }

  // cupped hand: palm overlaps heart edge and fingers lie on heart front.
  const s=flip?-1:1;
  px(c,x-2,y-2,5,5,C.O);
  px(c,x-1,y-1,3,3,C.HI);
  px(c,x+s*1,y-3,2,1,C.O);
  px(c,x+s*2,y-2,1,2,C.HI);
  px(c,x+s*2,y-1,4,1,C.O);
  px(c,x+s*2,y,5,1,C.O);
  px(c,x+s*2,y+1,4,1,C.O);
  px(c,x+s*2,y-1,3,1,C.HI);
  px(c,x+s*2,y,4,1,C.HI);
  px(c,x+s*2,y+1,3,1,C.HI);
}
function arm(c,left,pose,oy){
  const s=left?-1:1;
  const shoulderX=left?17:39;
  const shoulderY=38+oy;
  const lift=left?pose.armL:pose.armR;
  const bend=left?pose.foreL:pose.foreR;
  const dx=left?pose.handLX:pose.handRX;
  const open=left?pose.openL:pose.openR;

  const elbowX=shoulderX+s*(5+lift*.045);
  const elbowY=shoulderY+3-lift*.15;
  const wristX=(left?22:34)+s*bend*.02+dx;
  const wristY=41+oy+pose.handY-bend*.14;

  joint(c,shoulderX,shoulderY);
  segment(c,shoulderX+s,shoulderY+1,elbowX,elbowY);
  joint(c,elbowX,elbowY);
  segment(c,elbowX-s,elbowY,wristX,wristY);
  return {x:wristX,y:wristY,open};
}

function drawFront(c,p={}){
  const pose={
    bob:0,crouch:0,blink:0,mouth:0,
    headX:0,headY:0,eyeX:0,eyeY:0,
    armL:0,armR:0,foreL:0,foreR:0,
    handLX:0,handRX:0,handY:0,openL:0,openR:0,
    legL:0,legR:0,footL:0,footR:0,
    heartX:0,heartY:0,heartGlow:0,heartHeld:1,heartFree:0,heartSpin:0,
    ...p
  };
  c.clearRect(0,0,56,90);
  c.save();
  c.translate(0,34);
  const oy=pose.bob+pose.crouch;

  px(c,16,53,24,1,C.SD);

  // legs
  px(c,18+pose.legL,45+oy,6,6,C.O);px(c,19+pose.legL,45+oy,4,5,C.SH);
  px(c,32+pose.legR,45+oy,6,6,C.O);px(c,33+pose.legR,45+oy,4,5,C.SH);
  foot(c,16+pose.legL+pose.footL,50+oy,false);
  foot(c,31+pose.legR+pose.footR,50+oy,true);

  // compact body
  rounded(c,18,34+oy,20,13,C.S);
  px(c,20,34+oy,6,1,C.HI);
  px(c,21,45+oy,14,1,C.G);
  px(c,26,38+oy,4,4,C.R);
  px(c,27,39+oy,2,1,C.W);px(c,27,41+oy,2,1,C.W);


  // arms first; hands are deferred until the final foreground pass.
  const L=arm(c,true,pose,oy);
  const R=arm(c,false,pose,oy);

  // head: cute, balanced rounded rectangle
  const hx=11+pose.headX,hy=15+oy+pose.headY;
  // ears
  px(c,hx-3,hy+7,4,7,C.O);px(c,hx-2,hy+8,2,5,C.SH);
  px(c,hx+31,hy+7,4,7,C.O);px(c,hx+32,hy+8,2,5,C.SH);

  rounded(c,hx,hy,32,20,C.S);
  px(c,hx+6,hy+1,20,1,C.G);

  // smaller face screen with good white margin
  px(c,hx+7,hy+6,18,1,C.F);
  px(c,hx+6,hy+7,20,8,C.F);
  px(c,hx+7,hy+15,18,1,C.F);
  px(c,hx+8,hy+6,16,1,C.FH);

  eye(c,hx+10+pose.eyeX,hy+8+pose.eyeY,pose.blink);
  eye(c,hx+19+pose.eyeX,hy+8+pose.eyeY,pose.blink);
  smile(c,hx+12,hy+14,pose.mouth);

  // top sprout
  px(c,hx+15,hy-4,2,5,C.G);
  px(c,hx+12,hy-5,5,2,C.GH);
  px(c,hx+17,hy-5,6,1,C.JH);

  // FINAL HELD-HEART COMPOSITION:
  // wrist is behind the heart; the whole heart is in front of head/body/arms;
  // only the palms/fingers overlap its side pixels, creating a real “捧住” relation.
  wrist(c,L.x,L.y);wrist(c,R.x,R.y);
  if(pose.heartHeld&&!pose.heartFree){
    heart(c,18+pose.heartX,31+oy+pose.heartY,pose.heartGlow);
  }
  palm(c,L.x,L.y,false,!!L.open);
  palm(c,R.x,R.y,true,!!R.open);

  // free heart is top-most object
  if(pose.heartFree){
    c.save();
    const cx=28+pose.heartX,cy=38+oy+pose.heartY;
    c.translate(cx,cy);
    c.rotate(pose.heartSpin*Math.PI/180);
    heart(c,-10,-10,pose.heartGlow);
    c.restore();
  }

  c.restore();
}

function drawSide(c,p={}){
  const pose={phase:0,bob:0,blink:0,dir:1,heartGlow:0,...p};
  c.clearRect(0,0,56,90);
  c.save();
  c.translate(0,34);
  if(pose.dir<0){c.translate(56,0);c.scale(-1,1)}
  const oy=pose.bob;

  px(c,16,53,24,1,C.SD);

  px(c,19-pose.phase,45+oy,6,6,C.O);px(c,20-pose.phase,45+oy,4,5,C.SH);
  foot(c,16-pose.phase,50+oy,false);
  px(c,33+pose.phase,45+oy,6,6,C.O);px(c,34+pose.phase,45+oy,4,5,C.SH);
  foot(c,33+pose.phase,50+oy,false);

  rounded(c,20,34+oy,18,13,C.S);
  px(c,22,34+oy,6,1,C.HI);px(c,23,45+oy,12,1,C.G);


  // arm hugging heart
  joint(c,19,38+oy);
  segment(c,19,38+oy,16,42+oy);
  joint(c,16,42+oy);
  segment(c,17,42+oy,24,45+oy);

  // side head — no neck: head shell drops directly onto the torso.
  c.save();
  c.translate(0,5);
  rounded(c,15,11+oy,28,19,C.S);
  px(c,21,12+oy,16,1,C.G);
  px(c,25,17+oy,13,1,C.F);
  px(c,24,18+oy,15,7,C.F);
  px(c,25,25+oy,13,1,C.F);
  eye(c,33,19+oy,pose.blink);
  px(c,36,24+oy,2,1,C.W);

  px(c,13,18+oy,3,7,C.O);px(c,14,19+oy,2,5,C.J);

  px(c,29,7+oy,2,5,C.G);
  px(c,26,8+oy,5,1,C.GH);
  px(c,31,8+oy,6,1,C.JH);
  c.restore();

  // heart + hand front layer
  heart(c,22,32+oy,pose.heartGlow);
  wrist(c,24,42+oy);
  palm(c,24,42+oy,false,false);

  c.restore();
}

function smooth(t){return t*t*(3-2*t)}
function ping(t){return Math.sin(t*Math.PI)}
function clamp(v,a=0,b=1){return Math.max(a,Math.min(b,v))}
function cyc(t){return Math.sin(t*Math.PI*2)}

function poseFor(name,t){
  if(name==='hold'){
    const breath=Math.sin(t*Math.PI*2);
    return {
      bob:-ping(t)*1.0,
      heartY:-Math.max(0,breath)*.55,
      handY:-Math.max(0,breath)*.28,
      armL:Math.max(0,breath)*1.8,
      armR:Math.max(0,breath)*1.8,
      heartGlow:(t>.12&&t<.44)||(t>.58&&t<.70)?1:0,
      blink:(t>.72&&t<.77)||(t>.84&&t<.87)?1:0
    }
  }

  if(name==='walk'){
    const a=cyc(t),b=Math.sin(t*Math.PI*4);
    return {
      bob:b<0?-.6:0,
      legL:Math.round(a*1.5),legR:Math.round(-a*1.5),
      footL:Math.round(a),footR:Math.round(-a),
      heartX:a*.35,handLX:a*.22,handRX:-a*.22
    }
  }

  if(name==='run'){
    const a=Math.sin(t*Math.PI*4);
    return {
      side:1,
      phase:Math.round(a*3),
      bob:Math.sin(t*Math.PI*8)<0?-.7:0,
      blink:t>.49&&t<.52?1:0,
      heartGlow:t>.12&&t<.18?1:0
    }
  }

  if(name==='talk'){
    const m=Math.floor(t*10)%2;
    const g=Math.max(0,Math.sin(t*Math.PI*4));
    return {
      mouth:m,
      headY:-g*.55,
      armR:8+g*6,
      foreR:10+g*6,
      blink:t>.71&&t<.75?1:0
    }
  }

  if(name==='happy'){
    if(t<.16){
      const u=smooth(t/.16);return {crouch:u,heartGlow:1}
    }
    if(t<.52){
      const u=ping((t-.16)/.36);
      return {bob:-u*5,armL:u*13,armR:u*13,heartY:-u*4,heartGlow:1}
    }
    if(t<.82){
      const u=smooth((t-.52)/.30);
      return {bob:-5*(1-u),armL:13*(1-u),armR:13*(1-u),heartY:-4*(1-u),heartGlow:1}
    }
    return {crouch:(1-smooth((t-.82)/.18))}
  }

  if(name==='toss'){
    if(t<.12){
      const u=smooth(t/.12);
      return {crouch:u*2,heartY:u}
    }
    if(t<.28){
      const u=smooth((t-.12)/.16);
      return {
        crouch:2*(1-u),bob:-u*5,
        armL:u*25,armR:u*25,foreL:u*23,foreR:u*23,
        handY:-u*4,heartY:1-u*11,heartGlow:1,
        eyeY:-Math.round(u)
      }
    }
    if(t<.34){
      const u=smooth((t-.28)/.06);
      return {
        bob:-5,
        armL:25+u*5,armR:25+u*5,foreL:23+u*6,foreR:23+u*6,
        handY:-4-u,openL:1,openR:1,
        heartHeld:0,heartFree:1,
        heartY:-10-u*8,heartGlow:1,heartSpin:u*8,
        headY:-1,eyeY:-1
      }
    }
    if(t<.51){
      const u=smooth((t-.34)/.17);
      return {
        bob:-5-ping(u)*.8,
        armL:30-u*5,armR:30-u*5,foreL:29-u*4,foreR:29-u*4,
        openL:1,openR:1,handY:-5,
        heartHeld:0,heartFree:1,
        heartY:-18-u*25,heartGlow:1,heartSpin:8+u*18,
        headY:-1.3,eyeY:-1
      }
    }
    if(t<.61){
      const u=(t-.51)/.10;
      return {
        bob:-5.3,
        armL:25,armR:25,foreL:25,foreR:25,
        openL:1,openR:1,handY:-5,
        heartHeld:0,heartFree:1,
        heartY:-43-ping(u)*1.4,heartGlow:1,heartSpin:26-u*8,
        headY:-1.5,eyeY:-1
      }
    }
    if(t<.78){
      const u=smooth((t-.61)/.17);
      return {
        bob:-5+u*2,
        armL:25+u*5,armR:25+u*5,foreL:25+u*5,foreR:25+u*5,
        openL:1,openR:1,handY:-5+u*.5,
        heartHeld:0,heartFree:1,
        heartY:-43+u*30,heartGlow:1,heartSpin:18-u*12,
        headY:-1.5+u*.7,eyeY:-1
      }
    }
    if(t<.85){
      const u=smooth((t-.78)/.07);
      return {
        bob:-3+u*.4,
        armL:30-u*6,armR:30-u*6,foreL:30-u*6,foreR:30-u*6,
        openL:u<.5?1:0,openR:u<.5?1:0,
        handY:-4.5+u*2,
        heartHeld:1,heartFree:0,
        heartY:-13+u*7,heartGlow:1,
        headY:-.8+u*.4
      }
    }
    const u=smooth((t-.85)/.15);
    return {
      bob:-2.6*(1-u),crouch:ping(u),
      armL:24*(1-u),armR:24*(1-u),foreL:24*(1-u),foreR:24*(1-u),
      handY:-2.5*(1-u),heartY:-6*(1-u),heartGlow:u<.55?1:0
    }
  }

  return {}
}

function drawFrame(c,name,t,dir=1,lookX=0,lookY=0){
  const p=poseFor(name,t);
  // Pixel gaze is intentionally amplified: one CSS click should be
  // visually readable even on the small 56px mother canvas.
  p.eyeX=lookX*2.0;
  p.eyeY=(p.eyeY||0)+lookY*1.35;
  p.headX=lookX*.8;
  p.headY=(p.headY||0)+lookY*.35;
  if(p.side)drawSide(c,{...p,dir});
  else drawFront(c,p);
}



  const mascot=document.getElementById('youhuoRobotMascot');
  const canvas=document.getElementById('youhuoRobotCanvas');
  const bubble=document.getElementById('youhuoRobotBubble');
  if(!mascot || !canvas || !bubble) return;
  const ctx=canvas.getContext('2d');
  ctx.imageSmoothingEnabled=false;

  const systemReduceMotion=window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
// 演示版明确需要桌宠动作：即使系统开启“减少动态效果”，也不再彻底禁用小优。
// 仅保留变量供后续做幅度降级，不把动作调度直接关掉。
const reduceMotion=false;
  const CSS_W=112, CSS_H=180, FLOOR_MARGIN=70, ROAM_RANGE=410;
  const PET_POS_KEY='youhuo:elder:yoli:position:v1';
  const DRAG_THRESHOLD=5;
  let x=Math.max(18,innerWidth-CSS_W-30), y=Math.max(0,innerHeight-FLOOR_MARGIN-CSS_H), homeX=x, dir=1;
  let current='hold', actionStart=performance.now(), actionDuration=Infinity, busy=false, movePlan=null;
  let autoTimer=null, bubbleTimer=null, explainTimer=null, gazeResumeTimer=null, explainToken=0;
  let dragging=false, dragPointerId=null, dragMoved=false;
  let dragStartClientX=0, dragStartClientY=0, dragStartX=0, dragStartY=0;
  let lookX=0,lookY=0,targetLookX=0,targetLookY=0,gazeUntil=0;
  let bag=[],lastAuto=null;
  let ready=false;
  let lastVisibleActionAt=performance.now();
  let watchdogCooldownUntil=0;
  const AUTO_BAG=['toss','walk','run','happy'];

  function floorY(){return Math.max(0,innerHeight-FLOOR_MARGIN-CSS_H)}
  function clampX(v){return Math.max(12,Math.min(v,innerWidth-CSS_W-12))}
  function clampY(v){return Math.max(8,Math.min(v,innerHeight-CSS_H-8))}
  function place(){
    x=clampX(x);
    y=clampY(y);
    mascot.style.transform=`translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0)`;
    mascot.classList.toggle('bubble-right',x<innerWidth*.47);
  }
  function savePetPosition(){
    try{
      localStorage.setItem(PET_POS_KEY,JSON.stringify({x,y}));
    }catch(_){}
  }
  function loadPetPosition(){
    try{
      const saved=JSON.parse(localStorage.getItem(PET_POS_KEY)||'null');
      if(saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)){
        x=saved.x;
        y=saved.y;
      }
    }catch(_){}
    place();
  }
  function shuffle(a){
    const b=a.slice();
    for(let i=b.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[b[i],b[j]]=[b[j],b[i]]}
    if(lastAuto && b[0]===lastAuto && b.length>1) [b[0],b[1]]=[b[1],b[0]];
    return b;
  }
  function nextAuto(){
    if(!bag.length) bag=shuffle(AUTO_BAG);
    const a=bag.shift(); lastAuto=a; return a;
  }
  function stopAuto(){clearTimeout(autoTimer);autoTimer=null}
  function scheduleAuto(){
    stopAuto();
    // V5.8.3: deliberately lively rhythm.
    // A full action finishes, rests only ~0.75–1.45 s, then the next
    // item from the four-action shuffle bag begins.
    autoTimer=setTimeout(()=>{
      if(!busy && performance.now()>gazeUntil){
        runAuto(nextAuto());
      }else{
        scheduleAuto();
      }
    },750+Math.random()*700);
  }
  function setAction(name,duration,move=null){
    current=name;
    actionStart=performance.now();
    actionDuration=duration;
    busy=Number.isFinite(duration);
    movePlan=move;
    if(name!=='hold'){
      lastVisibleActionAt=actionStart;
      watchdogCooldownUntil=actionStart+Math.max(1800,duration||0);
    }
  }
  function interruptToHold(ms=0){
    movePlan=null; busy=false; current='hold'; actionStart=performance.now(); actionDuration=Infinity;
    if(ms>0) gazeUntil=Math.max(gazeUntil,performance.now()+ms);
  }
  function startSimple(name,duration=DUR[name]){
    stopAuto();
    setAction(name,duration,null);
  }
  function startMove(name,distance){
    stopAuto();
    const sx=x, ex=clampX(x+distance);
    dir=ex>=sx?1:-1;
    const stride=name==='run'?118:82;
    const cycles=Math.max(1,Math.min(5,Math.round(Math.abs(ex-sx)/stride)||1));
    const duration=DUR[name]*cycles;
    setAction(name,duration,{sx,ex,cycles});
  }
  function runAuto(name){
    if(name==='walk') return startMove('walk',(Math.random()>.5?1:-1)*(90+Math.random()*125));
    if(name==='run') return startMove('run',(Math.random()>.5?1:-1)*(130+Math.random()*175));
    if(name==='talk') return startSimple('talk',1500);
    startSimple(name,DUR[name]);
  }
  function say(text,ms=4300){
    bubble.textContent='小优：'+text;
    bubble.classList.add('show');
    clearTimeout(bubbleTimer);
    bubbleTimer=setTimeout(()=>bubble.classList.remove('show'),ms);
  }
  function lookAt(clientX,clientY,ms=2800){
    const r=mascot.getBoundingClientRect();
    const cx=r.left+r.width*.5, cy=r.top+r.height*.57;
    dir=clientX<cx?-1:1;

    const nx=clamp((clientX-cx)/105,-1,1);
    const ny=clamp((clientY-cy)/92,-1,1);
    targetLookX=nx;
    targetLookY=ny;

    // Click response must be obvious immediately, not after many RAF easing frames.
    lookX=nx*.82;
    lookY=ny*.82;
    gazeUntil=performance.now()+ms;
  }

  function reactToPagePoint(clientX,clientY,ms=1850){
    // A normal page click gets priority over autonomous motion.
    // Force the front-facing hold pose so even a currently side-running
    // robot can visibly turn its eyes/head toward the click.
    stopAuto();
    clearTimeout(gazeResumeTimer);
    interruptToHold(ms);
    lookAt(clientX,clientY,ms);
    gazeResumeTimer=setTimeout(()=>{
      if(ready && !busy && performance.now()>=gazeUntil) scheduleAuto();
    },ms+80);
  }
  function finishAction(){
    busy=false; movePlan=null; current='hold'; actionStart=performance.now(); actionDuration=Infinity;
    scheduleAuto();
  }

  function actionT(now){
    const elapsed=now-actionStart;
    if(current==='hold') return ((elapsed%DUR.hold)+DUR.hold)%DUR.hold/DUR.hold;
    if(current==='talk' && actionDuration>DUR.talk) return ((elapsed%DUR.talk)+DUR.talk)%DUR.talk/DUR.talk;
    if((current==='walk'||current==='run') && movePlan){
      const cycle=(elapsed%DUR[current])/DUR[current];
      return cycle;
    }
    return clamp(elapsed/Math.max(1,actionDuration));
  }
  function tick(now){
    if(busy && now-actionStart>=actionDuration) finishAction();

    if(movePlan && busy){
      const p=clamp((now-actionStart)/actionDuration);
      x=movePlan.sx+(movePlan.ex-movePlan.sx)*smooth(p);
      place();
    }

    if(now>gazeUntil){targetLookX=0;targetLookY=0}
    lookX += (targetLookX-lookX)*.18;
    lookY += (targetLookY-lookY)*.18;

    // 动作看门狗：复杂页面切换/点击如果把自动定时器打断，
    // 只要小优连续待机过久，就自动恢复下一套可见动作。
    if(ready && !busy && now>gazeUntil && now>watchdogCooldownUntil && now-lastVisibleActionAt>3200){
      lastVisibleActionAt=now;
      runAuto(nextAuto());
    }

    const t=actionT(now);
    drawFrame(ctx,current,t,dir,lookX,lookY);
    requestAnimationFrame(tick);
  }

  function startMascot(){
    if(ready) return;
    ready=true; loadPetPosition(); mascot.classList.add('is-ready');
    requestAnimationFrame(tick);
    scheduleAuto();
    setTimeout(()=>{
      if(!ready) return;
      interruptToHold(4700);
      say('我是优活的小向导。点页面里的功能，我会看向您点的位置，再告诉您这里是做什么的。',4500);
      // No autonomous talking on startup.
      // Enter the four-action pseudo-random cycle quickly.
      setTimeout(()=>{
        if(ready && !busy && performance.now()>gazeUntil) runAuto(nextAuto());
      },650);
    },700);
  }
  function waitForWorkspace(){
    const opening=document.getElementById('lotusOpening');
    if(opening && !opening.classList.contains('is-done')){setTimeout(waitForWorkspace,180);return}
    startMascot();
  }
  setTimeout(waitForWorkspace,260);

  const intros = [
    {selector:'[data-page="today"]', delay:920, text:'这里是「今天」。先看下一件要做的事，再用语音告诉我您想办什么。'},
    {selector:'[data-page="records"]', delay:920, text:'这里是「记录」。您让优活办过的事、确认过的步骤和最近记录都会留在这里。'},
    {selector:'[data-page="family"]', delay:920, text:'这里是「家人」。重要付款和高风险操作会先问您，再请家人一起确认。'},
    {selector:'[data-page="mine"]', delay:920, text:'这里是「我的」。语速、文字大小、常用服务和保护方式，都可以调成您舒服的样子。'},

    {selector:'#voiceOrb', delay:0, text:'这是语音入口。按一下，然后慢慢说；优活一次只听一件事。'},
    {selector:'#keyboardEntry', delay:0, text:'如果不方便说话，也可以从这里改成打字告诉优活。'},
    {selector:'.next-card', delay:0, text:'这里是下一件事。时间、事项和地点会放在一起，您只要看这一件就够了。'},
    {selector:'.quick-chip', delay:0, text:'这是常用说法。点一下就可以直接开始，例如问今天有什么事、交水费或挂号。'},
    {selector:'.timeline-node', delay:0, text:'这是今天的一件事。完成的会变淡，还没完成的会继续提醒。'},
    {selector:'.record-event', delay:0, text:'这是一条办事记录。这里会保留发生时间、做了什么，以及现在的状态。'},
    {selector:'.family-branch', delay:0, text:'这里说明家人能帮您的事情。优活不会把家人页做成复杂的社交系统。'},
    {selector:'#contactFamily', delay:0, text:'这是「联系家人」。需要的时候可以直接联系，不必在很多菜单里找。'},
    {selector:'.seg-btn', delay:0, text:'这是您的使用习惯。点一下就能调整，优活会记住您喜欢的语速和文字大小。'},
    {selector:'.service-row', delay:0, text:'这是常用服务入口。把经常用的功能放在这里，减少来回找菜单。'},
    {selector:'.guard-row', delay:0, text:'这里说明优活怎么保护您：一次只问一件事、要紧的事请您复述、不会自动扣钱。'},
    {selector:'#modeCompanion', delay:0, text:'切到「无忧伴」以后，可以只聊聊天；聊天内容不会混进办事记录。'},
    {selector:'#modeYouhuo', delay:0, text:'切回「优活」以后，我会继续帮您记事、办事和做必要的确认。'},
    {selector:'#repeatLast', delay:0, text:'如果刚才没听清，可以点「再说一遍」，优活会把上一句重新念出来。'},
    {selector:'#stepBack', delay:0, text:'如果刚才走错一步，可以从这里返回上一步，不需要重新开始。'},
    {selector:'#refreshRecords', delay:0, text:'这里可以刷新最近记录，看看刚才办的事情有没有更新。'}
  ];
  function matchIntro(target){
    for(const item of intros){
      const el=target.closest && target.closest(item.selector);
      if(el) return {...item,el};
    }
    return null;
  }
  function genericLabel(target){
    const el=target.closest && target.closest('button,a,.timeline-node,.record-event,.family-branch,.service-row,.guard-row,.seg-btn');
    if(!el) return '';
    return (el.getAttribute('aria-label')||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,26);
  }
  function explainAt(clientX,clientY,text,delay=0){
    const token=++explainToken;
    clearTimeout(explainTimer);
    stopAuto();
    interruptToHold(delay+4700);
    lookAt(clientX,clientY,delay+4700);

    explainTimer=setTimeout(()=>{
      if(token!==explainToken) return;
      lookAt(clientX,clientY,4300);
      say(text,4300);
      setAction('talk',4300,null);
    },delay);
  }

  function beginPetDrag(e){
    if(!ready || e.button>0) return;
    dragging=true;
    dragMoved=false;
    dragPointerId=e.pointerId;
    dragStartClientX=e.clientX;
    dragStartClientY=e.clientY;
    dragStartX=x;
    dragStartY=y;

    // Dragging owns the mascot until pointerup.
    stopAuto();
    clearTimeout(gazeResumeTimer);
    clearTimeout(explainTimer);
    ++explainToken;
    bubble.classList.remove('show');
    interruptToHold(0);
    mascot.classList.add('is-dragging');

    try{canvas.setPointerCapture(e.pointerId)}catch(_){}
    e.preventDefault();
    e.stopPropagation();
  }

  function movePetDrag(e){
    if(!dragging || e.pointerId!==dragPointerId) return;
    const dx=e.clientX-dragStartClientX;
    const dy=e.clientY-dragStartClientY;

    if(!dragMoved && Math.hypot(dx,dy)>=DRAG_THRESHOLD) dragMoved=true;
    if(!dragMoved) return;

    x=clampX(dragStartX+dx);
    y=clampY(dragStartY+dy);
    place();

    // While held, the face follows the hand/mouse.
    lookAt(e.clientX,e.clientY,180);
    e.preventDefault();
    e.stopPropagation();
  }

  function endPetDrag(e){
    if(!dragging || e.pointerId!==dragPointerId) return;
    try{canvas.releasePointerCapture(e.pointerId)}catch(_){}
    dragging=false;
    dragPointerId=null;
    mascot.classList.remove('is-dragging');

    if(dragMoved){
      savePetPosition();
      interruptToHold(360);
      lookAt(e.clientX,e.clientY,520);
      setTimeout(()=>{
        if(ready && !busy) scheduleAuto();
      },560);
    }else{
      // A short tap on the mascot is not a drag.
      lookAt(e.clientX,e.clientY,900);
      setTimeout(()=>{
        if(ready && !busy) scheduleAuto();
      },980);
    }

    e.preventDefault();
    e.stopPropagation();
  }

  canvas.addEventListener('pointerdown',beginPetDrag);
  canvas.addEventListener('pointermove',movePetDrag);
  canvas.addEventListener('pointerup',endPetDrag);
  canvas.addEventListener('pointercancel',endPetDrag);

  document.addEventListener('pointerdown',e=>{
    if(!ready) return;
    if(e.target.closest('#youhuoRobotMascot,#motionReplay,.lotus-opening')) return;

    // Immediate mouse-down eye contact. The following click handler
    // will either turn this into a component introduction or resume
    // the normal short gaze reaction.
    const intro=matchIntro(e.target);
    const label=genericLabel(e.target);
    if(!intro && !label){
      reactToPagePoint(e.clientX,e.clientY,1850);
    }else{
      lookAt(e.clientX,e.clientY,2600);
    }
  },true);

  document.addEventListener('click',e=>{
    if(!ready) return;
    if(e.target.closest('#youhuoRobotMascot,#motionReplay,.lotus-opening')) return;

    const intro=matchIntro(e.target);
    if(intro){
      explainAt(e.clientX,e.clientY,intro.text,intro.delay);
      return;
    }
    const label=genericLabel(e.target);
    if(label){
      explainAt(e.clientX,e.clientY,'这里是「'+label+'」。点开后可以继续查看或操作这一部分。',0);
      return;
    }

    // 普通页面点击：不讲话，但必须明确看向点击位置。
    // 当前即使正在侧跑，也会先停回正面捧心，再看向鼠标。
    reactToPagePoint(e.clientX,e.clientY,1850);
  },true);

  // 点击后的一小段时间里，继续跟随鼠标位置，让“看向鼠标”不是一帧反应。
  document.addEventListener('pointermove',e=>{
    if(!ready || dragging || performance.now()>gazeUntil) return;
    const r=mascot.getBoundingClientRect();
    const cx=r.left+r.width*.5, cy=r.top+r.height*.57;
    targetLookX=clamp((e.clientX-cx)/105,-1,1);
    targetLookY=clamp((e.clientY-cy)/92,-1,1);
  },{passive:true});

  addEventListener('resize',()=>{
    homeX=Math.max(18,innerWidth-CSS_W-30);
    x=clampX(x);
    y=clampY(y);
    place();
    savePetPosition();
  });

  const api={
    say(text){explainAt(innerWidth*.5,innerHeight*.5,String(text||''),0)},
    lookAt(x,y){lookAt(Number(x)||innerWidth*.5,Number(y)||innerHeight*.5,2800)},
    play(name){
      if(name==='hold') interruptToHold();
      else if(name==='talk') startSimple('talk',DUR.talk); // explicit intro only
      else if(AUTO_BAG.includes(name)) runAuto(name)
    },
    pause(ms=1200){interruptToHold(ms)},
    faceX(clientX){lookAt(Number(clientX)||innerWidth*.5,mascot.getBoundingClientRect().top+70,2000)},
    moveTo(clientX,clientY){
      x=clampX(Number(clientX)||x);
      y=clampY(Number(clientY)||y);
      place();
      savePetPosition();
    },
    resetPosition(){
      x=Math.max(18,innerWidth-CSS_W-30);
      y=floorY();
      place();
      savePetPosition();
    },
    get x(){return x}, get y(){return y}
  };
  window.youhuoMascot={get pet(){return api},say:api.say,play:api.play,lookAt:api.lookAt};
  window.youhuoRobot=api;
  window.youhuoRobotDebug={
    get current(){return current},
    get busy(){return busy},
    get bag(){return bag.slice()},
    next(){if(!busy)runAuto(nextAuto())},
    toss(){if(!busy)runAuto('toss')},
    walk(){if(!busy)runAuto('walk')},
    run(){if(!busy)runAuto('run')},
    happy(){if(!busy)runAuto('happy')},
    introTalk(){if(!busy)startSimple('talk',DUR.talk)},
    resetPosition(){api.resetPosition()}
  };
})();
