(function(){
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const STORE = {
    family: [
      {id:'f1',time:'09:00',title:'挂号 · 心血管科',status:'已完成',done:true},
      {id:'f2',time:'14:00',title:'取药 · 西药房',status:'已完成',done:true},
      {id:'f3',time:'18:30',title:'确认燃气费缴纳',status:'正在等家人点头',done:false}
    ],
    care: [
      {id:'c1',time:'08:42',title:'今天起床',status:'比常态晚约 40 分钟 · 正常记录',done:true,level:'normal'},
      {id:'c2',time:'12:30',title:'午休 32 分钟',status:'和平常接近 · 正常记录',done:true,level:'normal'},
      {id:'c3',time:'16:10',title:'血压记录',status:'略高于近日均值 · 建议关注',done:false,level:'focus'},
      {id:'c4',time:'19:10',title:'晚间复测',status:'等待老人补充语音记录',done:false,level:'waiting',needVoice:true}
    ]
  };

  const flows = [...document.querySelectorAll('.bubble-flow')];

  function esc(s){
    return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function itemHTML(item){
    return `
      <article class="flow-item ${item.done?'completed':'pending'}"
               data-id="${esc(item.id)}"
               tabindex="0">
        <time class="flow-time">${esc(item.time)}</time>
        <span class="flow-title">${esc(item.title)}</span>
        <span class="flow-status">${esc(item.status)}</span>
        <span class="breath-mic" aria-label="等待语音确认"><span class="mic-core"></span></span>
        <button class="flow-delete" type="button" aria-label="删除 ${esc(item.title)}">×</button>
      </article>`;
  }

  function installGradient(svg){
    svg.innerHTML = `
      <defs>
        <linearGradient id="flowLineGradient" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#a56d1f" stop-opacity=".88"/>
          <stop offset=".48" stop-color="#8c6b3d" stop-opacity=".76"/>
          <stop offset="1" stop-color="#356757" stop-opacity=".82"/>
        </linearGradient>
      </defs>`;
  }

  function curvePath(a,b,canvasRect){
    const ar=a.getBoundingClientRect(), br=b.getBoundingClientRect();
    const ax=ar.left-canvasRect.left+ar.width*.72;
    const ay=ar.bottom-canvasRect.top-3;
    const bx=br.left-canvasRect.left+br.width*.27;
    const by=br.top-canvasRect.top+3;
    const dy=Math.max(18,by-ay);
    const bend=((br.left-ar.left)>10?1:-1)*Math.min(34,Math.max(18,Math.abs(br.left-ar.left)+18));
    const c1x=ax+bend, c1y=ay+dy*.36;
    const c2x=bx-bend*.72, c2y=by-dy*.34;
    return `M ${ax.toFixed(1)} ${ay.toFixed(1)} C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${bx.toFixed(1)} ${by.toFixed(1)}`;
  }

  function redraw(flow,{animateIndex=-1}={}){
    const svg=flow.querySelector('.flow-links');
    const canvas=flow.querySelector('.flow-canvas');
    const items=[...flow.querySelectorAll('.flow-item')];
    installGradient(svg);
    if(items.length<2) return;
    const rect=canvas.getBoundingClientRect();

    for(let i=0;i<items.length-1;i++){
      const d=curvePath(items[i],items[i+1],rect);
      const ghost=document.createElementNS('http://www.w3.org/2000/svg','path');
      ghost.setAttribute('class','flow-link ghost');
      ghost.setAttribute('d',d);
      ghost.setAttribute('pathLength','1');
      svg.appendChild(ghost);

      const p=document.createElementNS('http://www.w3.org/2000/svg','path');
      p.setAttribute('class','flow-link');
      p.setAttribute('d',d);
      p.setAttribute('pathLength','1');
      p.dataset.segment=String(i);
      svg.appendChild(p);

      if(animateIndex===i && !reduce){
        p.classList.add('is-drawing');
      }
    }
  }

  function bindItems(flow){
    flow.querySelectorAll('.flow-delete').forEach(btn=>{
      btn.addEventListener('click',e=>{
        e.stopPropagation();
        removeItem(flow,btn.closest('.flow-item').dataset.id);
      });
    });
  }

  function render(flow,{reveal=true}={}){
    const type=flow.dataset.flow;
    const holder=flow.querySelector('.flow-items');
    const data=STORE[type];
    flow.classList.toggle('flow-dense',data.length>=4);
    flow.classList.toggle('flow-very-dense',data.length>=5);

    if(!data.length){
      holder.innerHTML='<div class="flow-empty">这里暂时没有记录</div>';
      redraw(flow);
      return;
    }

    holder.innerHTML=data.map(itemHTML).join('');
    bindItems(flow);
    requestAnimationFrame(()=>{
      redraw(flow);
      if(reveal || reduce){
        holder.querySelectorAll('.flow-item').forEach(x=>x.classList.add('revealed'));
      }
    });
  }

  function playFlow(flow){
    if(!flow || flow.closest('.workspace')?.hidden) return;

    // V5.4.3.5: the flow is a completely separate third act.
    // Reveal its heading first, then generate bubble -> curve -> bubble.
    flow.classList.remove('flow-sequence-active');
    void flow.offsetWidth;
    flow.classList.add('flow-sequence-active');

    const items=[...flow.querySelectorAll('.flow-item')];
    if(!items.length || reduce){
      items.forEach(x=>x.classList.add('revealed'));
      redraw(flow);
      return;
    }

    flow.classList.remove('flow-entering');
    void flow.offsetWidth;
    flow.classList.add('flow-entering');
    items.forEach(x=>x.classList.remove('revealed'));
    redraw(flow);

    // 生长顺序：椭圆 -> 曲线 -> 椭圆 -> 曲线 ...
    let t=260;
    items.forEach((item,i)=>{
      setTimeout(()=>item.classList.add('revealed'),t);
      t+=430;
      if(i<items.length-1){
        setTimeout(()=>{
          const p=flow.querySelector(`.flow-link[data-segment="${i}"]`);
          if(p){
            p.classList.remove('is-drawing');
            void p.getTotalLength();
            p.classList.add('is-drawing');
          }
        },t-80);
        t+=420;
      }
    });
  }

  function removeItem(flow,id){
    const type=flow.dataset.flow;
    const data=STORE[type];
    const node=flow.querySelector(`.flow-item[data-id="${CSS.escape(id)}"]`);
    if(!node) return;

    node.classList.add('removing');

    setTimeout(()=>{
      const idx=data.findIndex(x=>x.id===id);
      if(idx>-1) data.splice(idx,1);
      render(flow,{reveal:true});

      // 删除后，已有气泡保持；重新连接的曲线自然长出来。
      requestAnimationFrame(()=>requestAnimationFrame(()=>{
        const seg=Math.max(0,Math.min(idx-1,data.length-2));
        redraw(flow,{animateIndex:data.length>1?seg:-1});
      }));
    },370);
  }

  function addItem(flow,time,title){
    const type=flow.dataset.flow;
    const data=STORE[type];
    const id=type[0]+Date.now().toString(36);
    const item={
      id,time,title,
      status:type==='family'?'等待确认 · 可语音回应':'等待后续记录',
      done:false
    };
    const oldCount=data.length;
    data.push(item);

    render(flow,{reveal:true});
    requestAnimationFrame(()=>requestAnimationFrame(()=>{
      const nodes=[...flow.querySelectorAll('.flow-item')];
      const newNode=nodes[nodes.length-1];
      if(!newNode) return;

      // Existing bubbles stay visible; the new one is born after its connector.
      newNode.classList.remove('revealed');
      redraw(flow);

      if(oldCount>0){
        setTimeout(()=>{
          const p=flow.querySelector(`.flow-link[data-segment="${oldCount-1}"]`);
          if(p){
            p.classList.remove('is-drawing');
            void p.getTotalLength();
            p.classList.add('is-drawing');
          }
        },80);
        setTimeout(()=>newNode.classList.add('revealed'),560);
      }else{
        setTimeout(()=>newNode.classList.add('revealed'),120);
      }
    }));
  }

  flows.forEach(flow=>{
    render(flow,{reveal:false});
    const add=flow.querySelector('.flow-add');
    const editor=flow.querySelector('.flow-editor');
    const cancel=flow.querySelector('.flow-cancel');

    add?.addEventListener('click',()=>{
      editor.hidden=false;
      editor.querySelector('input[name="title"]')?.focus();
    });
    cancel?.addEventListener('click',()=>editor.hidden=true);
    editor?.addEventListener('submit',e=>{
      e.preventDefault();
      const fd=new FormData(editor);
      const time=(fd.get('time')||'19:30').toString();
      const title=(fd.get('title')||'新事项').toString().trim();
      if(!title) return;
      editor.hidden=true;
      addItem(flow,time,title);
    });
  });

  /* ---- 接线用的出口（`family3.js`）------------------------------------------
   *
   * 这一行是接后端时加的，**行为一个字都没改**；补丁在 `install_v3.py` 里，
   * 直接改这个文件会在下次重装时被原包无声覆盖。
   *
   * 约定：接线只**替换 `store[type]` 数组的内容**，然后调 `render` / `playFlow`。
   * 不去碰这个 IIFE 里的任何别的东西。 */
  window.YouHuoFlow = {store: STORE, flows, render, redraw, playFlow, addItem, removeItem};

  // Recalculate natural curves whenever layout changes.
  const ro=new ResizeObserver(()=>{
    flows.forEach(f=>redraw(f));
  });
  flows.forEach(f=>ro.observe(f.querySelector('.flow-canvas')));

  // Initial entry: wait until the opening screen has fully left.
  const opening=document.getElementById('lotusOpening');
  function waitOpening(){
    if(opening && !opening.classList.contains('is-done')){
      setTimeout(waitOpening,180);
      return;
    }
    const visible=document.querySelector('.workspace:not([hidden]) .bubble-flow');
    setTimeout(()=>playFlow(visible),180);
  }
  setTimeout(waitOpening,300);

  // After EVERY full cinematic finishes, grow the bubble chain on the entered page.
  const scene=document.getElementById('pageScene');
  if(scene){
    let wasPlaying=scene.classList.contains('playing');
    const mo=new MutationObserver(()=>{
      const now=scene.classList.contains('playing');
      if(now){
        wasPlaying=true;
        // Reset visible flow while cinematic covers the page.
        const visible=document.querySelector('.workspace:not([hidden]) .bubble-flow');
        if(visible){
          visible.classList.remove('flow-sequence-active');
          visible.querySelectorAll('.flow-item').forEach(x=>x.classList.remove('revealed'));
        }
      }else if(wasPlaying){
        wasPlaying=false;
        const visible=document.querySelector('.workspace:not([hidden]) .bubble-flow');
        setTimeout(()=>playFlow(visible),180);
      }
    });
    mo.observe(scene,{attributes:true,attributeFilter:['class']});
  }

  // Useful for preview.
  window.playYouHuoBubbleFlow=()=>{
    const visible=document.querySelector('.workspace:not([hidden]) .bubble-flow');
    playFlow(visible);
  };
})();
