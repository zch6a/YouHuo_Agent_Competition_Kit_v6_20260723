/* 小优原版像素绘制，提取自 elder-v6-b.js；行为由 pet4.js 接入新版。 */


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




export {drawFrame};
