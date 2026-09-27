const KEY='youhuo.pet.chatter.v1';
export function chatterPreference(){try{const p=localStorage.getItem(KEY);return ['normal','lively','off'].includes(p)?p:'normal';}catch{return 'normal';}}
export function cycleChatter(){const next={normal:'lively',lively:'off',off:'normal'}[chatterPreference()];try{localStorage.setItem(KEY,next);}catch{}window.dispatchEvent(new CustomEvent('app4:chatter-preference',{detail:{value:next}}));return next;}
export const IDLE_LINES = [
  '小优就位，光环也戴好啦。','让我把小翅膀理一理～','今天也是一只认真营业的小精灵。','偷偷伸个懒腰，嘿咻！',
  '光环亮晶晶，心情软绵绵。','小翅膀扑棱一下，继续陪着您。','我在练习优雅地发呆。','小优的口袋里，装着一朵想象的小云。',
  '刚才数了数，我有两只翅膀！','把光环扶正，继续神气。','我想给自己的翅膀放个小假。','如果云朵有味道，会是棉花糖吗？',
  '一只小优，正在这里冒泡。','叮咚，掉落一颗小小的好心情。','今天想当一颗蓝色的小糖豆。','让我摆个精神一点的姿势。',
  '嘿，接住这颗想象的小星星。','我会一点点魔法：把嘴角往上提。','小优的拿手本领：认真听您说话。','您忙您的，我在旁边待一会儿。',
  '不用招呼我，我会自己乖乖待着。','想说话的时候，点点我就好。','今天想听您讲一个小故事。','哪天有空，讲讲您小时候的趣事吧。',
  '您喜欢晴天的云，还是雨后的彩虹？','给今天起个可爱的名字怎么样？','小优想收集一百种笑眯眯。','我先替想象中的花浇一点阳光。',
  '要是能坐在云朵上，我想晃晃脚。','今天的发呆姿势，我给自己打满分。','我是不是有一点像蓝色汤圆？','小翅膀不大，架势得足。',
  '咻——小优的想象力出发啦。','我把一句“慢慢来”放在这里。','一件一件来，小优陪着您。','小优安静站岗中，偶尔可爱一下。',
  '我的光环，可不是甜甜圈哦。','刚想耍个帅，翅膀先抖了一下。','小小一只，也要站得端端正正。','嗯，今天这个位置很适合发呆。',
  '给生活加一点点可爱，刚刚好。','小优没有尾巴，但可以开心地晃一晃。','想象一下：一片云正慢悠悠地散步。','我正在研究怎么把招呼打得更可爱。',
  '先把小脸抬起来，再说一声：我在呢。','今天也想做您身边的小帮手。','不用一直陪我玩，您自在就好。','悄悄冒个头，再乖乖待好。',
];
export function createIdleChatter(pet,{canSpeak,clock=window,random=Math.random}={}){
  const bubble=document.createElement('aside');bubble.className='a4-pet-chatter';bubble.hidden=true;bubble.setAttribute('aria-label','小优的碎碎念');
  const words=document.createElement('span');const dismiss=document.createElement('button');dismiss.type='button';dismiss.textContent='×';dismiss.setAttribute('aria-label','收起这句话');bubble.append(words,dismiss);document.body.append(bubble);
  let timer,endTimer,bag=[],last=null,quiet=false,stopped=false;
  function hide(){bubble.hidden=true;clock.clearTimeout(endTimer);}
  function position(){const r=pet.getBoundingClientRect(),v=window.visualViewport;const x=v?.offsetLeft||0,y=v?.offsetTop||0,w=v?.width||innerWidth,h=v?.height||innerHeight;
    bubble.style.left=`${Math.max(x+8,Math.min(r.left+r.width/2-bubble.offsetWidth/2,x+w-bubble.offsetWidth-8))}px`;
    bubble.dataset.side=r.top-bubble.offsetHeight-10>=y+8?'above':'below';
    bubble.style.setProperty('--pet-tail',`${Math.max(24,Math.min(r.left+r.width/2-parseFloat(bubble.style.left),bubble.offsetWidth-24))}px`);
    bubble.style.top=`${Math.max(y+8,Math.min(r.top-bubble.offsetHeight-10>=y+8?r.top-bubble.offsetHeight-10:r.bottom+8,y+h-bubble.offsetHeight-8))}px`;
  }
  function available(){return !stopped&&!quiet&&chatterPreference()!=='off'&&!document.hidden&&(!canSpeak||canSpeak())&&!document.activeElement?.matches('input,textarea,select,[contenteditable="true"]')&&!window.speechSynthesis?.speaking;}
  function next(){if(!bag.length){bag=IDLE_LINES.slice();for(let i=bag.length-1;i>0;i--){const j=Math.floor(random()*(i+1));[bag[i],bag[j]]=[bag[j],bag[i]];}if(bag.at(-1)===last)[bag[0],bag[bag.length-1]]=[bag.at(-1),bag[0]];}last=bag.pop();return last;}
  function show(line){if(!available())return false;words.textContent=line; bubble.hidden=false;position();clock.clearTimeout(endTimer);endTimer=clock.setTimeout(hide,10000);return true;}
  function schedule(first=false){clock.clearTimeout(timer);if(stopped||quiet||chatterPreference()==='off'||document.hidden)return;const delay=first?5000:chatterPreference()==='lively'?18000+random()*10000:28000+random()*15000;timer=clock.setTimeout(()=>{if(available()){show(next());schedule();}else schedule(true);},delay);}
  function activity(){hide();}
  function visibility(){hide();schedule(true);}
  function preference(){hide();schedule(true);}
  function hush(e){quiet=!!e.detail?.quiet;hide();schedule(true);}
  function stateChanged(){hide();schedule(true);}
  function moved(){hide();clock.clearTimeout(timer);timer=clock.setTimeout(()=>{show('嘿咻，搬到这里啦！小翅膀站稳～');schedule();},1200);}
  dismiss.onclick=activity;
  document.addEventListener('pointerdown',activity,true);document.addEventListener('keydown',activity,true);document.addEventListener('visibilitychange',visibility);
  window.addEventListener('app4:chatter-preference',preference);window.addEventListener('app4:pet-quiet',hush);window.addEventListener('app4:agent-state',stateChanged);window.addEventListener('app4:pet-moved',moved);
  window.addEventListener('resize',position);window.visualViewport?.addEventListener('resize',position);window.visualViewport?.addEventListener('scroll',position);
  schedule(true);
  return {bubble,show,hide,destroy(){stopped=true;hide();clock.clearTimeout(timer);bubble.remove();document.removeEventListener('pointerdown',activity,true);document.removeEventListener('keydown',activity,true);document.removeEventListener('visibilitychange',visibility);window.removeEventListener('app4:chatter-preference',preference);window.removeEventListener('app4:pet-quiet',hush);window.removeEventListener('app4:agent-state',stateChanged);window.removeEventListener('app4:pet-moved',moved);window.removeEventListener('resize',position);window.visualViewport?.removeEventListener('resize',position);window.visualViewport?.removeEventListener('scroll',position);}};
}
