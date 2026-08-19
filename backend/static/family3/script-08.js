(function(){
  const careView=document.getElementById('careView');
  const stage=document.getElementById('fiveVeinStage');
  const scene=document.getElementById('pageScene');
  if(!careView || !stage) return;

  function playFiveVein(){
    if(careView.hidden) return;
    careView.classList.remove('five-vein-ready');
    void careView.offsetWidth;
    careView.classList.add('five-vein-ready');
  }

  new MutationObserver(()=>{
    if(!careView.hidden && !(scene && scene.classList.contains('playing'))){
      setTimeout(playFiveVein,170);
    }
  }).observe(careView,{attributes:true,attributeFilter:['hidden']});

  if(scene){
    let wasCare=false;
    new MutationObserver(()=>{
      const playing=scene.classList.contains('playing');
      const type=scene.dataset.scene;
      if(playing && type==='care'){
        wasCare=true;
        careView.classList.remove('five-vein-ready');
      }else if(!playing && wasCare){
        wasCare=false;
        setTimeout(playFiveVein,180);
      }
    }).observe(scene,{attributes:true,attributeFilter:['class','data-scene']});
  }

  let raf=0,px=0,py=0;
  stage.addEventListener('pointermove',e=>{
    if(e.pointerType==='touch') return;
    const r=stage.getBoundingClientRect();
    px=((e.clientX-r.left)/r.width-.5)*22;
    py=((e.clientY-r.top)/r.height-.5)*16;
    if(!raf){
      raf=requestAnimationFrame(()=>{
        raf=0;
        stage.style.setProperty('--care-px',px.toFixed(1)+'px');
        stage.style.setProperty('--care-py',py.toFixed(1)+'px');
      });
    }
  });
  stage.addEventListener('pointerleave',()=>{
    stage.style.setProperty('--care-px','0px');
    stage.style.setProperty('--care-py','0px');
  });

  const whisper=document.getElementById('careDetailWhisper');
  const labels={
    today:'今天：查看起居与日常节律',
    med:'用药：查看今日服药与长期用药',
    body:'身体：查看体征、体检与就诊记录',
    mood:'心情：查看近期情绪与陪伴趋势',
    safety:'安全：查看联系人、提醒与异常事件'
  };

  stage.querySelectorAll('[data-vein-node]').forEach(node=>{
    const key=node.dataset.veinNode;
    const branch=stage.querySelector('.branch-'+key);
    const shadow=stage.querySelector('.shadow-'+key);
    node.addEventListener('pointerenter',()=>{
      if(branch){branch.style.strokeWidth='2.05';branch.style.opacity='.92';}
      if(shadow) shadow.style.opacity='.22';
      if(whisper) whisper.textContent=labels[key]||'';
    });
    node.addEventListener('pointerleave',()=>{
      if(branch){branch.style.strokeWidth='';branch.style.opacity='';}
      if(shadow) shadow.style.opacity='';
      if(whisper) whisper.textContent='把鼠标移到任一分支，枝条会回应。';
    });
  });

  setTimeout(()=>{if(!careView.hidden) playFiveVein()},600);
})();
