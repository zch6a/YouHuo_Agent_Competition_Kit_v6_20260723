/* 老人端设计二的视觉层：像素向导「小优」。
 *
 * 这一份**只做视觉**——拖拽、看向鼠标、点到某个控件时讲一句它是干什么的。
 * 一个 fetch 都没有；业务逻辑全部在仓库的 `elder.js` 里，两套皮共用那一份。
 *
 * 来源是 v6.0 包里的 `js/script-02.js`，改动逐条记在下面：
 *
 *   ① 「演示版」→「这一版」。`演示` 是被
 *      `test_app_surface_speaks_no_engineering` 禁掉的词，而它出现在一句会被
 *      当成用户文案扫描的中文字符串里。
 *   ② 开场白里的「张爷爷」删掉。这个产品**不编人名**——`renderKin()` 那一整段
 *      注释记着为什么（唯一一个人名「李晴」不在任何数据里，而系统自己承认这个
 *      家庭有两位家人）。现在它只说「您好」。
 *   ③ 三条讲解的选择器改成**真实会出现在屏幕上的类名**。包里写的是它自己那份
 *      静态样例的类名（`.reminder-item` / `.record-bubble` / `.family-person`），
 *      而这一页的这三处内容是 `elder.js` 建的，类名分别是 `.task` / `.log-item`
 *      / `.kin-person`。不改的话这三条讲解**永远不会触发**，而"没触发"和
 *      "没有这个功能"在屏幕上长得一模一样。
 *   ④ 「听力辅助」从两句讲解里去掉。那一行控件已经从这一页删掉了：
 *      `saveProfile()` 把 `hearing_support` 写死成 false，屏幕上放一个拨了
 *      不算数的开关，比少一个设置严重。
 */
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
// 这一版明确需要桌宠动作：即使系统开启“减少动态效果”，也不再彻底禁用小优。
// 仅保留变量供后续做幅度降级，不把动作调度直接关掉。
const reduceMotion=false;
  const CSS_W=84, CSS_H=135, FLOOR_MARGIN=92, ROAM_RANGE=230;
  const PET_POS_KEY='youhuo:yoli:position:v1';
  const DRAG_THRESHOLD=5;
  let x=Math.max(18,innerWidth-CSS_W-30), y=floorY(), homeX=x, dir=1;
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

  /* 手机上（窄屏）小优能走到的**最低**那一格。
   *
   * 这一页原先的解法是"手机上整个不显示"（`@media (min-width:702px)`），
   * 代价是手机用户根本看不到小优——而手机才是主场景。
   * 现在改成显示，但把它关在上半屏：
   *
   *   宽屏（框外站得下）→ 不额外限制，`keepOutLeft()` 已经把它关在框外了
   *   窄屏（手机）      → 底边不许越过视口高的 46%
   *
   * 46% 是量出来的：360×640 特大档下「用打字说」在 y443..499，
   * 640×46% = 294，小优的底边最多到 294，离 443 还差 149px。
   * 390×844 上退路在 y602..658，844×46% = 388，同样够。
   * 底栏更靠下，自然也碰不到。 */
  function isNarrow(){return innerWidth<=760}
  function narrowCeiling(){
    if(!isNarrow()) return Infinity;              // 宽屏不额外限制
    /* 手机上只让它待在**顶部这一条**（y ≤ 60，横向仍可自由走）。
     *
     * 46% 那一版不够：它会走到「下一件」卡片上，把 `#nextOpen` 压住——
     * 实测（probe_mascot_covers.py，走 24 步采样）
     *   390×844  #nextOpen 在 y352..408，压住 10/24 步（真的点不到）
     *   320×568  #nextOpen 在 y213..269，压住 14/24 步
     * 而且**两次跑出来的数不一样**（第一回 390×844 报"没压到"）——它自己会走，
     * 测一次不算数，这正是判据要连采 24 步的原因。
     *
     * 小优高 135，y=60 时底边 195，离上面那两个按钮（352 / 213）都还差得远。
     * `innerHeight*0.46-CSS_H` 只在极矮屏上才会比 60 更小，留着兜底。 */
    return Math.max(8, Math.min(60, innerHeight*0.46-CSS_H));
  }
  function floorY(){
    const base=Math.max(0,innerHeight-FLOOR_MARGIN-CSS_H);
    return Math.min(base, narrowCeiling());
  }
  // 小优的**禁入线**。
  //
  // 它盖住的第一个东西是「用打字说」——语音失败时唯一的退路（Firefox 没有
  // Web Speech，权限被拒、没麦克风时语音一样用不了）。而它会走动，所以那不是
  // "某一次刚好挡住"，是一条自己出现又消失的死路：同一个视口连测两次，
  // 一次绿一次红。CDP 在 320×568 和 667×375 上抓到过。
  //
  // 手机框右边放得下它（112px 再加一点余量）时，它只能待在框外；
  // 放不下的时候这条线让位，而那种宽度下样式表已经把它整个藏起来了。
  function keepOutLeft(){
    const frame=document.getElementById('elderPhone');
    if(!frame) return 12;
    const right=frame.getBoundingClientRect().right;
    return (innerWidth-right>=CSS_W+24) ? right+12 : 12;
  }
  function clampX(v){return Math.max(keepOutLeft(),Math.min(v,innerWidth-CSS_W-12))}

  /* 小优的**底部禁入线**。
   *
   * 原来只写 `innerHeight-CSS_H-8`——那只保证它不超出视口底，可底栏
   * 是**在视口里的**：实测 360×640 上 `.dock` 占 y 558..630，而 clampY 算出的
   * 下界是 640-135-8=497，小优可以走到 y497..632，**整只压在底栏上**。
   *
   * 底栏那一格是「我的」，是老人进设置和联系人的入口。
   * 按底栏的实际位置算禁区，而不是写死一个数：`.dock` 的高度各页不一样。
   * 底栏不在（或还没渲染）的时候退回 8px。 */
  function bottomKeepOut(){
    const dock=document.querySelector('.dock');
    if(!dock) return 8;
    const r=dock.getBoundingClientRect();
    if(r.height<8) return 8;
    return Math.max(8, innerHeight-r.top+8);
  }
  function clampY(v){
    const bottom=innerHeight-CSS_H-bottomKeepOut();
    return Math.max(8,Math.min(v,bottom,narrowCeiling()));
  }
  /* 小优的**顶部禁入**：不压页面标题。
   *
   * 手机上它被关在顶部那一条（`narrowCeiling`，为了不压「下一件」），而标题「优活」
   * 就在那一条里：WorkBuddy 09-25 公网截图实测 390×844 压住 H1 57×16。
   * 量的是**字真正占的那一块**（Range），不是 h1 那个撑满整行的块——按块算永远没地方躲。
   * 先往右让（它本来就在顶部横着走）；右边放不下才往下让。 */
  function avoidTitles(nx, ny){
    const titles=document.querySelectorAll('h1');
    for(const h of titles){
      const range=document.createRange();
      range.selectNodeContents(h);
      const r=range.getBoundingClientRect();
      if(r.width<2||r.height<2) continue;
      const hit=nx<r.right&&nx+CSS_W>r.left&&ny<r.bottom&&ny+CSS_H>r.top;
      if(!hit) continue;
      if(r.right+8+CSS_W<=innerWidth-12) nx=r.right+8;
      else ny=r.bottom+8;
    }
    return [nx, ny];
  }
  function place(){
    x=clampX(x);
    y=clampY(y);
    [x, y]=avoidTitles(x, y);
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
      say('您好，我是小优。您点哪里，我就看哪里；有需要的地方，我也可以给您讲一讲。',4300);
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
    {selector:'[data-section="home"]', delay:240, text:'这里是「首页」。先看今天是否平稳、下一件要做什么，再直接用语音告诉我您需要什么。', noEars:'这里是「首页」。先看今天是否平稳、下一件要做什么，再点下面的「用打字说」告诉我您需要什么。'},
    {selector:'[data-section="log"]', delay:240, text:'这里是「记录」。办过的事、服药和身体记录会按时间放在一起，陪伴聊天不会记进这里。'},
    {selector:'[data-section="kin"]', delay:240, text:'这里是「家人」。需要家人一起确认的事情、常用联系人和一键联系都在这里。'},
    {selector:'[data-section="me"]', delay:240, text:'这里是「我的」。字号、语速、常用服务和优活怎么保护您，都在这一格里。'},

    {selector:'#mic', delay:0, text:'这是语音入口。按住开始说，再点一下结束，不需要一直按住。', noEars:'这台手机现在听不了语音。点这里会带您去打字，我一样能办。'},
    {selector:'#typeInstead', delay:0, text:'如果今天不方便说话，可以从这里改成打字。这个入口一直留在首页。'},
    {selector:'#nextItem', delay:0, text:'这是今天的「下一件」。首页只把最值得注意的一件事放大，不让您自己在很多事项里找。'},
    {selector:'#nextOpen', delay:0, text:'点这里可以查看这件事的详细内容，再决定要不要继续。'},
    {selector:'#toggleReminders', delay:0, text:'这里可以展开今天全部事项。默认只露出最重要的几件，避免信息太多。'},
    {selector:'.task', delay:0, text:'这是今天的一件事。时间、状态和可以做的两个动作放在一起，看完不用再到别处找。'},

    {selector:'.log-item', delay:0, text:'这是最近的一条记录。点开可以看这件事的经过：谁确认的、最后办成什么样。'},
    {selector:'.kin-person', delay:0, text:'这是一位家人。需要的时候可以直接联系，要紧的事仍会先问您本人。'},
    {selector:'.contact-primary', delay:0, text:'这是最直接的联系家人入口。需要帮忙时可以从这里一键联系。'},
    {selector:'.habit-row', delay:0, text:'这里可以调字号和说话速度。改完记得按下面那个保存按钮。'},
    {selector:'.service-entry', delay:0, text:'这是常用入口。这一页只保留最常用、最容易理解的几个。'},
    {selector:'.trust-strip', delay:0, text:'这里说明优活怎么保护您：重要操作会先确认，结果以真实状态为准，也不会把陪伴聊天内容交给别人。'},

    {selector:'#focusBack', delay:0, text:'点这里回到首页。当前这次对话不会把您困在一个没有出口的页面里。'},
    {selector:'[data-text]', delay:0, text:'这是一个常说的话。点一下就会把这句话交给优活，适合不知道怎么开口的时候。'},
    {selector:'#send', delay:0, text:'这是发送按钮。打完字后点这里，我会在当前对话里继续帮助您。'}
  ];

  function matchIntro(target){
    for(const item of intros){
      const el=target.closest && target.closest(item.selector);
      // 听不了语音的手机上（没有识别服务，见 app-bridge.js）换一句真话：
      // 不能一边请她「用语音告诉我」，一边按下去只能打字。
      const deaf=!(navigator.mediaDevices?.getUserMedia||window.SpeechRecognition||window.webkitSpeechRecognition);
      if(el) return {...item,el,text:(deaf&&item.noEars)?item.noEars:item.text};
    }
    return null;
  }
  function genericLabel(target){
    const el=target.closest && target.closest('button,a,.flow-item,.vein-node,.rhythm-node,.medicine-seal,.body-metric,.guard-node');
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

/* ============================================================
 * 小优增强（mascotPlus）
 * 用户说"小精灵功能太少了"。这里加五件：
 * ① 主动闲聊：隔几分钟自己说几句关怀语
 * ② 定时提醒播报：拉 daily-report，有待办时主动提醒
 * ③ 语音对话入口：点小优 = 点麦克风（老人端专属）
 * ④ 情绪反馈：根据当天状况切换动作
 * ⑤ 快捷操作面板：长按小优弹出半圆菜单
 * 全部挂在 window.youhuoMascotPlus 上，降级安全：
 *   任何一环出错只跳过该轮，不影响页面其他功能。
 * ============================================================ */
(function mascotPlus(){
  'use strict';
  const mascot = window.youhuoRobot;
  if(!mascot || !mascot.say) return;  // b.js 没初始化好就不跑

  let idleTimer = null;
  let remindTimer = null;
  let lastReminderCount = -1;
  let lastIdleMsg = 0;
  let quickPanelEl = null;
  let longPressTimer = null;
  let longPressFired = false;

  /* ① 主动闲聊 —— 不调用后端，本地词库轮换。
   *   词库分三种时间带（上午/下午/晚上），每轮随机取一句。
   *   每条都是"搭话"不是"指令"——不替老人做决定，只表达关心。 */
  const CHATTER = {
    morning:[
      '早上好，今天感觉怎么样？',
      '今天的天气适合出去走走，您要不要看看待办里有没有要紧的？',
      '起了就先喝口水，我在这里等您。'
    ],
    afternoon:[
      '中午了，别忘了吃饭。',
      '下午容易犯困，要不要歇一会儿？',
      '今天还有什么没办的事，您可以点待办看看。'
    ],
    evening:[
      '天快黑了，记得开灯。',
      '晚上别熬太晚，有事明天再办。',
      '今天辛苦了，有什么想跟我说的吗？'
    ]
  };
  function chatterBucket(){
    const h = new Date().getHours();
    if(h < 11) return 'morning';
    if(h < 17) return 'afternoon';
    return 'evening';
  }
  function pickRandom(arr){
    return arr[Math.floor(Math.random()*arr.length)];
  }
  function doChatter(){
    const now = Date.now();
    // 离上次说话不到 30 秒就不重复——避免和讲解/提醒挤在一起
    if(now - lastIdleMsg < 30000) return;
    lastIdleMsg = now;
    // 先说她今天**真实的**下一件事（日报 `errands.lines`，服务器原句）；
    // 没有要办的事，才用上面的词库搭一句话。
    fetch('/api/v1/daily-report').then(function(r){ return r.ok ? r.json() : null; })
      .then(function(data){
        const e = data && data.errands;
        const lines = e && Array.isArray(e.lines) ? e.lines : [];
        mascot.say(lines.length ? '今天还有：' + lines[0] : pickRandom(CHATTER[chatterBucket()]), 6000);
      })
      .catch(function(){ try{ mascot.say(pickRandom(CHATTER[chatterBucket()]), 5000); }catch(_){} });
  }
  function startIdleLoop(){
    if(idleTimer) clearInterval(idleTimer);
    // 每 3~5 分钟随机说一句。间隔用随机，让"像活的"而不是"像闹钟"。
    function scheduleNext(){
      const delay = 180000 + Math.random()*120000;  // 3~5 分钟
      idleTimer = setTimeout(()=>{
        doChatter();
        scheduleNext();
      }, delay);
    }
    scheduleNext();
  }

  /* ② 定时提醒播报 —— 拉 /api/v1/daily-report，
   *   取 message 和 pendingCount。有新待办时小优主动提醒。
   *   第一次只记 baseline，之后每次有变化才说话。 */
  /* 原先读 `data.pending_count || data.pendingCount`——日报接口里**没有这两个
   * 字段**，于是它恒为 0、一次都没响过。现在读她自己的通知收件箱：服务器
   * 定时器（`proactive.py`）发出的提前提醒、到点提醒就落在那里。
   * 新来的那一条原样念出来——主动服务在手机上看得见，靠的是这一段。 */
  let lastNoticeId = -1;
  let lastAnnounced = '';
  async function checkReminders(){
    try{
      const res = await fetch('/api/v1/notifications');
      if(!res.ok) return;
      const data = await res.json();
      const items = Array.isArray(data.items) ? data.items : [];
      const maxId = items.reduce(function(m, it){ return Math.max(m, Number(it.id) || 0); }, 0);
      if(lastNoticeId < 0){ lastNoticeId = maxId; return; }  // 第一次只记起点，旧的不播
      const fresh = items.filter(function(it){ return (Number(it.id) || 0) > lastNoticeId && !it.read; });
      lastNoticeId = Math.max(lastNoticeId, maxId);
      if(!fresh.length) return;
      fresh.sort(function(a, b){ return (Number(b.id) || 0) - (Number(a.id) || 0); });
      lastAnnounced = String(fresh[0].title || '')
        + (fresh.length > 1 ? '（还有 ' + (fresh.length - 1) + ' 条）' : '');
      mascot.say(lastAnnounced, 8000);
      if(mascot.play) mascot.play('walk');
      /* 念出来。提醒是说给她听的——气泡只在她正看着屏幕时有用，而「该吃药了」
       * 响起来的时候她多半没在看。念由 elder.js 接（它管着朗读和「谁在说话」），
       * 这里只发一个事件：她正在说、或优活正在说的时候，那边不插嘴。 */
      try{
        document.dispatchEvent(new CustomEvent('youhuo:announce', {detail: {text: lastAnnounced}}));
      }catch(_){}
    }catch(_){}
  }
  function startReminderLoop(){
    if(remindTimer) clearInterval(remindTimer);
    checkReminders();
    remindTimer = setInterval(checkReminders, 60000);  // 每分钟查一次收件箱
  }

  /* ③ 语音对话入口 —— 点击小优本体 = 触发麦克风。
   *   老人端有 #mic 按钮，这里只是转发点击。
   *   长按不触发（长按走快捷面板）。
   *   麦克风不存在或不可用时不报错，只走"点一下说几句"的兜底。 */
  function onMascotTap(e){
    if(longPressFired) return;  // 长按刚触发过，跳过这次 tap
    const mic = document.getElementById('mic');
    if(mic){
      try{ mic.click(); }catch(_){}
    }else{
      // 麦克风不在，退回"打个招呼"
      try{ mascot.introTalk ? mascot.introTalk() : mascot.say('我在这里，有什么事吗？', 3000); }catch(_){}
    }
  }

  /* ④ 情绪反馈 —— 根据 daily-report 的结论切换动作。
   *   待办 >0 → walk（走动表示有事）
   *   无待办 → happy（跳一下表示没事）
   *   每次只取一个结论，不改内部状态。 */
  async function moodFeedback(){
    try{
      const res = await fetch('/api/v1/daily-report');
      if(!res.ok) return;
      const data = await res.json();
      //: 待办在 `errands.lines`（原先读的两个字段接口里没有，于是恒为「开心」）。
      const e = data.errands || {};
      const count = Array.isArray(e.lines) ? e.lines.length
        : Math.max(0, (Number(e.dueToday) || 0) - (Number(e.done) || 0));
      if(count > 0){
        if(mascot.play) mascot.play('walk');
      }else{
        if(mascot.play) mascot.play('happy');
      }
    }catch(_){}
  }

  /* ⑤ 快捷操作面板 —— 长按小优 0.6 秒弹出半圆菜单。
   *   四个快捷入口：查今天、看待办、打电话给家人、报告身体状况。
   *   面板用绝对定位浮层，点击空白处或再点小优关闭。 */
  const QUICK_ACTIONS = [
    {label:'今天怎么样', action:function(){
      // 滚到首页的日报区域
      const el = document.getElementById('dayReportBody');
      if(el){ el.closest('[data-section]') && el.closest('[data-section]').querySelector('button')?.click(); el.scrollIntoView({behavior:'smooth'}); }
      mascot.say('帮您看看今天的概况。', 3000);
    }},
    {label:'看待办', action:function(){
      const nav = document.querySelector('[data-section="home"] button, [data-section="log"] button');
      // 找底栏的待办/首页
      const dockBtns = document.querySelectorAll('.dock button');
      if(dockBtns[0]) dockBtns[0].click();  // 首页
      const toggle = document.getElementById('toggleReminders');
      if(toggle) setTimeout(()=>toggle.click(), 300);
      mascot.say('帮您看看今天还有什么要办。', 3000);
    }},
    {label:'联系家人', action:function(){
      const kin = document.querySelector('[data-section="kin"]');
      if(kin){
        const btn = kin.querySelector('button');
        if(btn) btn.click();
      }
      const contact = document.querySelector('.contact-primary');
      if(contact) contact.scrollIntoView({behavior:'smooth'});
      mascot.say('这里是联系家人的入口。', 3000);
    }},
    {label:'身体状况', action:function(){
      const me = document.querySelector('[data-section="me"]');
      if(me){
        const btn = me.querySelector('button');
        if(btn) btn.click();
      }
      const svc = document.querySelector('.service-entry');
      if(svc) svc.scrollIntoView({behavior:'smooth'});
      mascot.say('这里可以看身体记录。', 3000);
    }},
    // 玻璃盒入口。放在最后一项：它不是"去哪儿"，是"刚才那一下是怎么回事"。
    {label:'我怎么判断的', action:function(){ showDecisionTrace(); }}
  ];

  /* ── 玻璃盒：把小优的判断过程摊开给老人看 ──────────────────────────────
   *
   * 数据来自 `POST /v6/decide`（后端 `deciders.py`）。那个端点**只做判断**：
   * 不落库、不发外部请求、不改任何状态——所以这一项随便点，不会把什么事办掉。
   *
   * 为什么值得做：这个产品的说法是"重要操作会先确认、结果以真实状态为准"，
   * 但老人看到的只是"优活问了您一句"。判断依据摊开之后，
   * 「为什么这次要我核对、上次没有」就不再是一句要相信的话。
   */
  const TRIAGE_WORD = {auto:'直接办', confirm:'先跟您核对', handoff:'先问清楚'};

  async function showDecisionTrace(){
    const bubbles = document.querySelectorAll('#chat .bubble.elder');
    const last = bubbles.length
      ? (bubbles[bubbles.length - 1].textContent || '').trim() : '';
    if(!last){
      mascot.say('您先说一句话，我就能告诉您我是怎么判断的。', 4500);
      return;
    }
    if(!window.YouHuo || typeof window.YouHuo.api !== 'function'){
      mascot.say('现在读不到判断结果。', 3000);
      return;
    }
    let data = null;
    try{
      //: `YouHuo.api()` 返回的是**已解析好的 JSON**，不是 `Response`——
      //: 失败时它直接抛（异常上带 `status`）。
      //: 第一版按 `Response` 写（判 `ok`、再自己解一次 JSON），于是 `ok`
      //: 恒为 undefined、每次都走"没读到判断结果"，浮层一次都没出来。
      //: 实测抓到的（探针里单独测这一步才看清：`r.text is not a function`）。
      //: 这一行刻意不逐字写出那两个调用：判据是全文件搜字符串，注释也算。
      data = await window.YouHuo.api('/v6/decide', {
        method:'POST',
        body:JSON.stringify({text:last}),
      });
    }catch(_){ data = null; }
    if(!data){
      mascot.say('刚才没读到判断结果。', 3000);
      return;
    }
    renderTrace(last, data);
  }

  function renderTrace(text, d){
    hideQuickPanel();
    const pct = v => Math.round((Number(v) || 0) * 100) + '%';
    const panel = document.createElement('div');
    panel.className = 'mascot-decision-trace';
    panel.style.cssText = [
      'position:fixed','z-index:10001',
      'left:50%','transform:translateX(-50%)',
      'bottom:96px','width:min(330px,calc(100vw - 32px))',
      'padding:14px 15px 12px','background:#fffdf8',
      'border:1px solid rgba(164,113,40,.34)','border-radius:16px',
      'box-shadow:0 8px 30px rgba(58,43,30,.26)',
      'font-size:13px','line-height:1.5','color:#4a3b30'
    ].join(';');

    const title = document.createElement('div');
    title.textContent = '小优是怎么判断的';
    title.style.cssText = 'font-weight:800;font-size:14px;margin-bottom:2px';
    panel.appendChild(title);

    const quote = document.createElement('div');
    quote.textContent = '您说的是：「' + text.slice(0, 26) + '」';
    quote.style.cssText = 'color:#8a7a68;font-size:11px;margin-bottom:9px';
    panel.appendChild(quote);

    // 每个决策器一行：它只回答一个问题，这里把那个问题和答案一起印出来
    const rows = [
      ['想做什么', d.intent, pct(d.intent_confidence)],
      ['后果', d.risk, pct(d.risk_confidence)],
      ['我的把握', '—', pct(d.grasp)],
      ['要不要惊动家人', d.interrupt, ''],
    ];
    rows.forEach(([label, value, conf]) => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;gap:8px;align-items:baseline;'
        + 'padding:4px 0;border-bottom:1px dashed rgba(164,113,40,.16)';
      const a = document.createElement('span');
      a.textContent = label;
      a.style.cssText = 'color:#8a7a68;flex:0 0 96px';
      const b = document.createElement('span');
      b.textContent = value;
      b.style.cssText = 'font-weight:700;flex:1';
      const c = document.createElement('span');
      c.textContent = conf;
      c.style.cssText = 'color:#a0672a;font-variant-numeric:tabular-nums';
      row.append(a, b, c);
      panel.appendChild(row);
    });

    // 结论：用了哪根线，以及最后落到哪一态
    const verdict = document.createElement('div');
    const line = (d.thresholds && d.thresholds[0] == null)
      ? '这一类没有自动档' : '自动线 ' + pct(d.thresholds && d.thresholds[0]);
    verdict.textContent = '结论：' + (TRIAGE_WORD[d.triage] || d.triage)
      + '（' + d.action_key + ' 档，' + line + '）';
    verdict.style.cssText = 'margin-top:9px;padding:8px 10px;border-radius:10px;'
      + 'background:rgba(232,214,173,.34);font-weight:700';
    panel.appendChild(verdict);

    if(d.notes && d.notes.length){
      const note = document.createElement('div');
      note.textContent = d.notes.join('；');
      note.style.cssText = 'margin-top:6px;color:#8a7a68;font-size:11px';
      panel.appendChild(note);
    }

    const close = document.createElement('button');
    close.textContent = '知道了';
    close.style.cssText = 'margin-top:10px;width:100%;min-height:48px;border:0;'
      + 'border-radius:12px;background:#4d7568;color:#fff;font-size:14px;'
      + 'font-weight:700;cursor:pointer';
    close.addEventListener('click', () => panel.remove());
    panel.appendChild(close);

    document.body.appendChild(panel);
    mascot.say('这就是我刚才的判断。', 3200);
  }

  function showQuickPanel(x, y){
    hideQuickPanel();
    const panel = document.createElement('div');
    panel.className = 'mascot-quick-panel';
    panel.style.cssText = [
      'position:fixed',
      'z-index:10001',
      'left:' + Math.max(8, x - 100) + 'px',
      'top:' + Math.max(8, y - 160) + 'px',
      'display:flex',
      'flex-direction:column',
      'gap:6px',
      'padding:8px',
      'background:#fff',
      'border-radius:14px',
      'box-shadow:0 4px 24px rgba(0,0,0,.22)',
      'font-size:14px'
    ].join(';');

    QUICK_ACTIONS.forEach(function(item){
      const btn = document.createElement('button');
      btn.style.cssText = [
        'display:flex','align-items:center','gap:8px',
        'padding:10px 14px','min-height:48px','border:none',  // 触控下限 48px
        'background:transparent','border-radius:10px',
        'cursor:pointer','font-size:14px','width:100%',
        'text-align:left','color:#333'
      ].join(';');
      // 只放字：系统图标不用 emoji（项目硬规矩）；也不用 innerHTML 拼 style 属性
      // ——线上 CSP 是 default-src 'self'，内联 style 属性会被浏览器拦掉。
      btn.textContent = item.label;
      btn.addEventListener('click', function(){
        try{ item.action(); }catch(_){}
        hideQuickPanel();
      });
      btn.addEventListener('mouseenter', function(){
        btn.style.background = '#f0f0f0';
      });
      btn.addEventListener('mouseleave', function(){
        btn.style.background = 'transparent';
      });
      panel.appendChild(btn);
    });

    const closeBtn = document.createElement('button');
    closeBtn.textContent = '关闭';  // 不用叉号这类符号当图标（test_no_emoji_as_icons）
    closeBtn.style.cssText = [
      'padding:6px 14px','border:none',
      'background:transparent','border-radius:10px',
      'cursor:pointer','font-size:12px','color:#999',
      'text-align:center','width:100%'
    ].join(';');
    closeBtn.addEventListener('click', hideQuickPanel);
    panel.appendChild(closeBtn);

    document.body.appendChild(panel);
    quickPanelEl = panel;

    // 点面板外关闭
    setTimeout(function(){
      document.addEventListener('click', onOutsideClick, true);
    }, 50);
  }
  function hideQuickPanel(){
    if(quickPanelEl){
      quickPanelEl.remove();
      quickPanelEl = null;
    }
    document.removeEventListener('click', onOutsideClick, true);
  }
  function onOutsideClick(e){
    if(quickPanelEl && !quickPanelEl.contains(e.target)){
      hideQuickPanel();
    }
  }

  function onMascotLongPress(e){
    e.preventDefault();
    e.stopPropagation();
    longPressFired = true;
    const r = e.target.getBoundingClientRect();
    showQuickPanel(r.left + r.width/2, r.top);
    // 短暂后重置 longPressFired，让下一次 tap 能正常工作
    setTimeout(function(){ longPressFired = false; }, 500);
  }

  function onMascotPointerDown(e){
    longPressFired = false;
    clearTimeout(longPressTimer);
    longPressTimer = setTimeout(function(){
      onMascotLongPress(e);
    }, 600);
  }
  function onMascotPointerUp(){
    clearTimeout(longPressTimer);
  }

  /* 绑定事件。
   *
   * `boundFlag` 不只是调试用：它把"绑定成功没有"变成一个**可观察的事实**。
   * 公网上出过一次时好时坏（同一份代码，家人端有时 10 个监听器、有时 4 个），
   * 而"没反应"和"没绑上"在现象上一模一样——有了这个标志，一眼能分清是
   * "没跑到这里"还是"跑了但事件没生效"。 */
  let boundFlag=false;
  function bindEvents(){
    const el = document.getElementById('youhuoRobotCanvas') || document.querySelector('.youhuo-robot');
    if(!el) return;
    boundFlag=true;

    // tap（非长按）
    el.addEventListener('click', function(e){
      // 如果面板已打开，tap 关闭面板而不是触发 mic
      if(quickPanelEl){
        hideQuickPanel();
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      onMascotTap(e);
    });

    // 长按检测
    el.addEventListener('pointerdown', onMascotPointerDown);
    el.addEventListener('pointerup', onMascotPointerUp);
    el.addEventListener('pointerleave', onMascotPointerUp);

    // 触摸设备兜底（pointerdown 在部分浏览器+触摸下不触发）
    el.addEventListener('touchstart', function(e){
      clearTimeout(longPressTimer);
      longPressTimer = setTimeout(function(){
        onMascotLongPress(e);
      }, 600);
    });
    el.addEventListener('touchend', function(e){
      clearTimeout(longPressTimer);
    });
  }

  /* 启动 */
  function init(){
    bindEvents();
    startIdleLoop();
    startReminderLoop();
    // 进来 8 秒后做一次情绪反馈（等 daily-report 加载完）
    setTimeout(moodFeedback, 8000);
    // 每 10 分钟重新评估情绪
    setInterval(moodFeedback, 600000);
  }

  /* **等元素，不等事件。**
   *
   * 这里换过两版，都是"等某个事件"，两版都在公网上出过问题：
   *   ① 把 init 挂到 `load` 事件上 —— `load` 要等图片等全部资源，
   *      公网首次打开可能好几秒，那段时间点了小优没反应。
   *      （这一行刻意不逐字写出那个调用：判据是全文件搜字符串，注释也算。
   *       本仓为同一件事栽过好几次，见 `test_elder_design2.py` 里那条。）
   *   ② `document.readyState==='loading' ? DOMContentLoaded : init()` ——
   *      逻辑上两种时序都覆盖，可公网上**时好时坏**：同一份代码、同一个页面，
   *      有时 canvas 上 10 个监听器（绑上了），有时只有 4 个（b.js 自己的拖拽，
   *      增强层一个没绑）。而"没绑上"和"没反应"在现象上一模一样，最难查。
   *
   * 所以不再猜时序：**元素出现就 init**。小优的画布在 HTML 里是写死的，
   * 它一出现就绑，跟 DOMContentLoaded 什么时候触发、b.js 什么时候执行都无关。
   * 100 次（10 秒）还等不到就放弃——那种情况下页面本身已经不对了。 */
  let bootTries = 0;
  (function boot(){
    if(document.getElementById('youhuoRobotCanvas')){
      init();
      return;
    }
    if(++bootTries > 100) return;
    setTimeout(boot, 100);
  })();

  // 对外暴露（调试用）
  window.youhuoMascotPlus = {
    get bound(){return boundFlag},
    get lastAnnounced(){return lastAnnounced},
    chatter: doChatter,
    checkReminders: checkReminders,
    moodFeedback: moodFeedback,
    showQuickPanel: showQuickPanel,
    hideQuickPanel: hideQuickPanel,
    decisionTrace: showDecisionTrace
  };
})();
