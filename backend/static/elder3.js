/* 老人端设计三（网页端 `/elder3`）的接线。
 *
 * ## 这个文件只做一件事
 *
 * 把设计三那套 DOM 接到**和设计一二完全相同的后端端点**上。它不含业务判断，
 * 不含第二套文案表，不含第二套字号语速映射——这个项目已经因为「两套实现
 * 各自往返都绿、跨子系统才红」栽过一次（字号语速和 SOS 各有两套实现）。
 *
 * ## 交付包里带着四个「假控件」，必须先摘掉
 *
 * `page-motion-and-ui.js` 已经给下面这些绑了监听，而它们**只演不做**：
 *
 *     #savePref   显示「✓ 已保存」1.5 秒，一个字节都不存
 *     #voiceOrb   把说明改成「正在听，请慢慢说…」2.1 秒，什么都没听
 *     .segmented  只切 `active` 类，值不去任何地方
 *     模式切换     只弹一条 toast
 *
 * 光加一个自己的监听是不够的：两个监听都会跑，于是**我这边失败的时候，
 * 屏幕上照样先弹出「✓ 已保存」**。一个说"已保存"却没保存的按钮，
 * 比没有这个按钮更糟。所以对前两个用 `cloneNode` 把匿名监听整个摘掉再接。
 *
 * `.segmented` 和模式切换的那两个监听是**纯视觉**的（切 class、弹 toast），
 * 那正是我想要的，留着；我在旁边加自己的那一份读值。
 *
 * ## 不重建 DOM
 *
 * `.story-node` / `.record-event` 的位置靠 CSS 的 n1/n2/n3、e1..e4 决定，
 * 而 `crane-animation-master.js` 和入场动画持有这些节点。所以**原地改文字、
 * 多的隐藏**，不 replaceChildren。这也对应交付包 README 的第 8 条：
 * 「UI 最终状态必须默认可见，避免再次出现文字/卡片突然消失」。
 */
(function () {
  'use strict';

  const YH = window.YouHuo;
  if (!YH) return;                       // common.js 没加载就什么都不做，别抛异常
  const {api, once, errorWords} = YH;

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => [...(root || document).querySelectorAll(sel)];
  const ws = (name) => $(`.workspace[data-workspace="${name}"]`);

  /* 语速 / 字号的取值**必须和 `elder.html` 的 `#speechRate` `#fontScale` 一致**。
   * 那两个 select 的 option 就是这六个数。设计三用的是分段按钮，词一样，
   * 所以这里按词映射；`test_elder_design3.py` 有一道判据钉住三处不许分叉。 */
  const SPEED = {'慢': 0.72, '舒适': 0.88, '正常': 1.0};
  const FONT = {'较大': 1.1, '大': 1.25, '特大': 1.5};
  const nearest = (table, value) => {
    let best = null, gap = Infinity;
    for (const [word, v] of Object.entries(table)) {
      const d = Math.abs(Number(value) - v);
      if (d < gap) { gap = d; best = word; }
    }
    return best;
  };

  /* ---- 状态行 -------------------------------------------------------------
   *
   * 这一页原先没有任何地方能说「刚才那一下怎么样了」。加一条，放在麦克风说明
   * 下面——那是她按完按钮眼睛所在的位置。空的时候自己不占位。 */
  let statusEl = null;
  function ensureStatus() {
    if (statusEl) return statusEl;
    const host = $('.voice-caption');
    if (!host) return null;
    statusEl = document.createElement('p');
    statusEl.id = 'e3Status';
    statusEl.className = 'e3-status';
    statusEl.setAttribute('role', 'status');
    statusEl.setAttribute('aria-live', 'polite');
    host.insertAdjacentElement('afterend', statusEl);
    return statusEl;
  }
  function say(text, tone) {
    const el = ensureStatus();
    if (!el) return;
    el.textContent = text || '';
    el.dataset.tone = tone || 'good';
  }
  const trouble = (e, what) => say(errorWords(e, what).text, 'bad');

  /* 念出来。用浏览器自带的合成，语速取她自己存的那个值。 */
  let speechRate = 0.88;
  function speakOut(text) {
    if (!text || !window.speechSynthesis) return;
    try {
      const u = new SpeechSynthesisUtterance(String(text));
      u.lang = 'zh-CN';
      u.rate = speechRate;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
    } catch (_) { /* 合成不可用不影响办事 */ }
  }

  /* ---- 今天 --------------------------------------------------------------- */

  function greeting() {
    const h = new Date().getHours();
    if (h < 6) return '夜里好';
    if (h < 11) return '早上好';
    if (h < 13) return '中午好';
    if (h < 18) return '下午好';
    return '晚上好';
  }

  function stamp(d) {
    const pad = (n) => String(n).padStart(2, '0');
    const week = '日一二三四五六'[d.getDay()];
    return `${d.getFullYear()}年${pad(d.getMonth() + 1)}月${pad(d.getDate())}日 `
         + `周${week} · ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  async function loadToday() {
    const page = ws('today');
    if (!page) return;
    const island = $('.identity-island', page);
    const meta = $('.identity-meta', island);
    if (meta) meta.textContent = stamp(new Date());

    try {
      const me = await api('/api/v1/profile');
      const h1 = $('h1', island);
      if (h1) h1.textContent = `${greeting()} · ${me.name}`;
    } catch (e) { trouble(e, '您的档案'); }

    let agenda = null;
    try {
      agenda = await api('/api/v1/agenda');
    } catch (e) {
      trouble(e, '今天的安排');
      return;
    }

    // 一句话说清今天。没有事就说没有事，不留占位文案。
    const lead = $('.identity-island p', page);
    if (lead) {
      lead.textContent = agenda.next
        ? `今天有 ${agenda.count} 件事。下一件是${agenda.next.title}，别着急，一件一件来。`
        : (agenda.count
            ? `今天有 ${agenda.count} 件事，都已经过去了。`
            : '今天没有要办的事。想起什么，随时按麦克风告诉我。');
    }

    // 「下一件」卡片
    const nextCard = $('.next-card', page);
    if (nextCard) {
      if (agenda.next) {
        const label = $('.label', nextCard);
        const strong = $('strong', nextCard);
        const metas = $$('.meta span', nextCard);
        if (label) label.textContent = `下一件 · ${agenda.next.time}`;
        if (strong) strong.textContent = agenda.next.title;
        /* 两格不许说同一件事。
         *
         * 第一版是 `note` + （过点了 ? '已经过点了' : '到点提醒'），而后端给的
         * `note` 本身就是「这一件已经过点了。」——屏幕上于是并排印着
         * 「这一件已经过点了。　已经过点了」。实测截图上看得清清楚楚。
         * 后一格只在**前一格没说**的时候才补。 */
        const note = agenda.next.note || '';
        const overdue = !!agenda.next.overdue;
        if (metas[0]) {
          metas[0].textContent = note;
          metas[0].hidden = !note;
        }
        if (metas[1]) {
          const extra = overdue ? (note ? '' : '已经过点了') : '到点提醒';
          metas[1].textContent = extra;
          metas[1].hidden = !extra;
        }
        nextCard.hidden = false;
      } else {
        // 藏起来，而不是留着一张写着别人事情的卡片。
        nextCard.hidden = true;
      }
    }

    fillTimeline(page, agenda.today.map((it) => ({
      t: it.time, n: it.title, s: it.done ? '已完成' : '还没办',
      done: it.done, id: it.id,
    })), '今天没有要办的事');
  }

  /* 三个 story-node 原地改文字，多的隐藏。位置靠 CSS 的 n1/n2/n3，不能重建。 */
  function fillTimeline(page, rows, emptyWord) {
    const nodes = $$('.left-story .story-node', page);
    nodes.forEach((node, i) => {
      const row = rows[i];
      if (!row) { node.hidden = true; return; }
      node.hidden = false;
      const t = $('.t', node), n = $('.n', node), s = $('.s', node);
      if (t) t.textContent = row.t || '';
      if (n) n.textContent = row.n || '';
      if (s) s.textContent = row.s || '';
      node.classList.toggle('done', !!row.done);
      node.classList.toggle('pending', !row.done);
      if (row.id) node.dataset.reminderId = row.id;
    });
    const head = $('.left-story .story-head b', page);
    if (head && !rows.length && emptyWord) head.textContent = emptyWord;
  }

  /* ---- 记录 --------------------------------------------------------------- */

  let lastSpoken = '';

  async function loadRecords() {
    const page = ws('records');
    if (!page) return;
    let data;
    try {
      data = await api('/api/v1/records?limit=20');
    } catch (e) { trouble(e, '办事记录'); return; }

    const events = $$('.record-event', page);
    events.forEach((el, i) => {
      const r = data.items[i];
      if (!r) { el.hidden = true; return; }
      el.hidden = false;
      const b = $('b', el), small = $('small', el);
      if (b) b.textContent = r.title;
      if (small) {
        small.textContent = [r.time, r.kind, r.note].filter(Boolean).join(' · ');
      }
    });

    fillTimeline(page, data.items.slice(0, 3).map((r) => ({
      t: r.time || '', n: r.title, s: r.note || r.kind, done: true,
    })), '还没有办过事');

    const meta = $('.identity-meta', page);
    if (meta) {
      meta.textContent = data.total
        ? `一共 ${data.total} 条 · 刚刚已更新`
        : '还没有记录';
    }
    if (data.items[0]) lastSpoken = `${data.items[0].title}。${data.items[0].note || ''}`;
  }

  /* ---- 家人 --------------------------------------------------------------- */

  async function loadFamily() {
    const page = ws('family');
    if (!page) return;
    let data;
    try {
      data = await api('/api/v1/contacts');
    } catch (e) { trouble(e, '家人联系方式'); return; }

    const meta = $('.identity-meta', page);
    if (meta) {
      meta.textContent = data.count
        ? `${data.count} 位家人可以联系`
        : '还没有登记家人';
    }

    // 三条分支换成真的联系人。`phone` 后端永远回 null（`actors` 表没有这一列），
    // 所以这里**不显示号码**——写一个编出来的号码，她真按下去会拨错人。
    const branches = $$('.family-branch', page);
    branches.forEach((el, i) => {
      const c = data.items[i];
      if (!c) { el.hidden = true; return; }
      el.hidden = false;
      const b = $('b', el), small = $('small', el);
      if (b) b.textContent = c.name;
      if (small) {
        small.textContent = c.primary ? `${c.role} · 优先联系` : c.role;
      }
    });

    const core = $('.family-core span', page);
    if (core && data.items.length) {
      const first = data.items.find((c) => c.primary) || data.items[0];
      core.textContent = `重要的事，先找${first.name}`;
    }
  }

  /* ---- 我的 --------------------------------------------------------------- */

  function markSegment(seg, word) {
    $$('.seg-btn', seg).forEach((b) => {
      b.classList.toggle('active', b.textContent.trim() === word);
    });
  }

  async function loadSettings() {
    const page = ws('mine');
    if (!page) return;
    let s;
    try {
      s = await api('/api/v1/settings');
    } catch (e) { trouble(e, '您的设置'); return; }
    speechRate = Number(s.voiceSpeed) || 0.88;
    const speed = $('.segmented[data-seg="speed"]', page);
    const font = $('.segmented[data-seg="font"]', page);
    if (speed) markSegment(speed, nearest(SPEED, s.voiceSpeed));
    if (font) markSegment(font, nearest(FONT, s.fontScale));
    applyFont(Number(s.fontScale) || 1.25);

    const meta = $('.identity-meta', page);
    if (meta) {
      meta.textContent = s.saved ? '这是您自己调过的' : '现在是默认设置';
    }
  }

  /* 字号真的作用在屏幕上。只调根字号，版式跟着 rem 走；
   * 不动 `--` 之外的任何东西，免得和这一页自己的动画打架。 */
  function applyFont(scale) {
    document.documentElement.style.setProperty('--e3-font-scale', String(scale));
  }

  function readSegments() {
    const page = ws('mine');
    const pick = (sel, table, fallback) => {
      const seg = $(sel, page);
      const on = seg && $('.seg-btn.active', seg);
      const word = on ? on.textContent.trim() : '';
      return table[word] !== undefined ? table[word] : fallback;
    };
    return {
      voiceSpeed: pick('.segmented[data-seg="speed"]', SPEED, 0.88),
      fontScale: pick('.segmented[data-seg="font"]', FONT, 1.25),
    };
  }

  /* ---- 说话 ---------------------------------------------------------------
   *
   * 会话与对话走的是和设计一完全相同的两个端点。 */
  let sessionId = null;
  async function ensureSession() {
    if (sessionId) return sessionId;
    const s = await api('/v2/sessions', {method: 'POST', body: JSON.stringify({})});
    sessionId = s.session_id;
    return sessionId;
  }

  async function send(text) {
    const what = String(text || '').trim();
    if (!what) return;
    say('让我想一想……', 'good');
    try {
      const data = await api('/v2/chat', {
        method: 'POST',
        body: JSON.stringify({session_id: await ensureSession(), text: what}),
      });
      say(data.message, YH.toneOf(data));
      lastSpoken = data.message;
      if (data.ui && data.ui.speak) speakOut(data.message);
      // 办完一件事，今天那一屏就该跟着变。
      loadToday();
      loadRecords();
    } catch (e) {
      trouble(e, '这句话');
    }
  }

  /* ---- 接线 --------------------------------------------------------------- */

  /** 把交付包绑在这个元素上的匿名监听整个摘掉，返回替换后的新节点。 */
  function stripListeners(el) {
    if (!el) return null;
    const fresh = el.cloneNode(true);
    el.replaceWith(fresh);
    return fresh;
  }

  function wire() {
    // 常用说法：按钮上写什么就说什么，不另建一张映射表。
    $$('.quick-chip').forEach((chip) => {
      chip.addEventListener('click', () => once(chip, () => send(chip.textContent.trim())));
    });

    // 麦克风。交付包那个「假装在听」的监听先摘掉。
    const orb = stripListeners($('#voiceOrb'));
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const caption = $('.voice-caption b');
    const capWord = caption ? caption.textContent : '';
    if (orb) {
      if (SR) {
        const rec = new SR();
        rec.lang = 'zh-CN';
        rec.interimResults = false;
        rec.maxAlternatives = 3;
        let listening = false;
        rec.onstart = () => {
          listening = true;
          if (caption) caption.textContent = '正在听，请慢慢说…';
          say('正在听，请慢慢说。一次只说一件事也可以。', 'good');
        };
        rec.onresult = (e) => send(e.results[0][0].transcript);
        rec.onend = () => {
          listening = false;
          if (caption) caption.textContent = capWord;
        };
        /* 这六句话照抄 `elder.js` 的 `RECOGNITION_TROUBLE`，不另写一份：
         * Web Speech 的错误枚举是英文标识符，不能给老人看，而「请再说一遍」
         * 在权限被拒时说一百遍也不会成功。 */
        const TROUBLE = {
          'not-allowed': '我没有拿到麦克风的许可。您可以用打字说，或者让家人帮您在设置里打开麦克风权限。',
          'service-not-allowed': '这台电脑暂时不让我用语音。您可以用打字说。',
          'audio-capture': '我找不到麦克风。您可以用打字说。',
          'no-speech': '我没有听到声音。请离麦克风近一点，再按一下慢慢说。',
          'network': '网络不太好，语音没送出去。您可以用打字说，或者等一会儿再试。',
          'aborted': '刚才那次听被打断了。您可以再按一下。',
        };
        rec.onerror = (e) => {
          if (caption) caption.textContent = capWord;
          say(TROUBLE[e.error] || '语音没能用起来。您可以用打字说，我一样能办。', 'bad');
        };
        orb.addEventListener('click', () => {
          // 正在听的时候再按一下，`start()` 会抛 InvalidStateError——
          // 而重复按恰恰是最常见的操作。停下来当作「说完了」。
          if (listening) { try { rec.stop(); } catch (_) {} return; }
          try { rec.start(); } catch (_) { say('刚才那一下没接上，请再按一次。', 'warning'); }
        });
      } else {
        // 没有语音识别（Firefox 就没有）。按下去要说清楚，不能假装在听。
        orb.addEventListener('click', () => {
          say('这个浏览器不支持语音输入。请按下面的「用打字说」，我一样能办。', 'warning');
          const k = $('#keyboardEntry');
          if (k) k.focus();
        });
      }
    }

    // 打字说
    const keyboard = $('#keyboardEntry');
    if (keyboard) {
      keyboard.addEventListener('click', () => {
        let box = $('#e3Composer');
        if (!box) {
          box = document.createElement('form');
          box.id = 'e3Composer';
          box.className = 'e3-composer';
          box.innerHTML = '<input id="e3Text" type="text" autocomplete="off" '
            + 'placeholder="想办什么，写一句就行" aria-label="打字告诉优活">'
            + '<button type="submit">说给优活</button>';
          keyboard.insertAdjacentElement('afterend', box);
          box.addEventListener('submit', (e) => {
            e.preventDefault();
            const input = $('#e3Text');
            const text = input.value;
            input.value = '';
            send(text);
          });
        }
        box.hidden = false;
        const input = $('#e3Text');
        if (input) input.focus();
      });
    }

    // 记录页那三个工具
    const repeat = $('#repeatLast');
    if (repeat) {
      repeat.addEventListener('click', () => {
        if (!lastSpoken) { say('还没有可以再念一遍的事。', 'warning'); return; }
        say(lastSpoken, 'good');
        speakOut(lastSpoken);
      });
    }
    const back = $('#stepBack');
    if (back) {
      /* 「返回上一步」在这一页没有对应的后端动作——它不是撤销一笔事务
       * （那要走 `/v2/chat` 说「取消任务」，而且只对**正在办**的那一件有效）。
       * 所以这里做它字面的意思：回到上一个看过的分区。
       * 不把它接成「取消任务」：一个写着「返回上一步」的按钮撤掉一笔缴费，
       * 是这一整轮在修的那类缺陷。 */
      back.addEventListener('click', () => {
        const prev = history.state && history.state.e3prev;
        const target = prev || 'today';
        const dock = $(`.dock [data-page="${target}"]`);
        if (dock) dock.dispatchEvent(new PointerEvent('pointerup', {bubbles: true}));
        say(`回到「${target === 'today' ? '今天' : '上一页'}」。`, 'good');
      });
    }
    const refresh = $('#refreshRecords');
    if (refresh) {
      refresh.addEventListener('click', () => once(refresh, async () => {
        await loadRecords();
        say('记录已经重新读过了。', 'good');
      }));
    }

    // 家人：联系家人 = 把联系人念出来，**不是**紧急呼叫。
    // 一个写着「联系家人」的按钮触发 SOS，是把破坏性动作挂在别的标签下面。
    const contact = $('#contactFamily');
    if (contact) {
      contact.addEventListener('click', () => once(contact, async () => {
        try {
          const data = await api('/api/v1/contacts');
          if (!data.count) { say('还没有登记家人。让家人在家人端加一下。', 'warning'); return; }
          const who = data.items.map((c) => `${c.name}（${c.role}）`).join('、');
          say(`可以联系的家人：${who}。要现在叫人来，请说「我需要帮忙」。`, 'good');
          speakOut(`可以联系的家人有${who}`);
        } catch (e) { trouble(e, '家人联系方式'); }
      }));
    }

    // 我的：保存。交付包那个「假装保存」的监听先摘掉。
    const save = stripListeners($('#savePref'));
    if (save) {
      const word = save.textContent;
      save.addEventListener('click', () => once(save, async () => {
        const body = readSegments();
        try {
          const saved = await api('/api/v1/settings',
                                  {method: 'PUT', body: JSON.stringify(body)});
          // 以**返回值**为准，不是以我传出去的值为准：服务端会夹范围。
          speechRate = Number(saved.voiceSpeed) || 0.88;
          applyFont(Number(saved.fontScale) || 1.25);
          markSegment($('.segmented[data-seg="speed"]', ws('mine')),
                      nearest(SPEED, saved.voiceSpeed));
          markSegment($('.segmented[data-seg="font"]', ws('mine')),
                      nearest(FONT, saved.fontScale));
          // 交付包那句是「✓ 已保存」。勾号是**图标位置上的字符**，
          // 这个项目不许拿字符当系统图标（`test_no_emoji_as_icons` 守的就是它）。
          save.textContent = '已经保存';
          setTimeout(() => { save.textContent = word; }, 1500);
          say('记住了。下次打开还是这样。', 'good');
          speakOut('记住了');
        } catch (e) {
          // 失败时**不许**出现「已保存」。
          trouble(e, '这次设置');
        }
      }));
    }

    // 字号选一下就立刻看得到，不用等保存——但保存前不写库。
    const fontSeg = $('.segmented[data-seg="font"]', ws('mine'));
    if (fontSeg) {
      fontSeg.addEventListener('click', () => {
        applyFont(readSegments().fontScale);
      });
    }

    // 无忧伴：后端按**每一句话**判定要不要进陪伴（`companion.wants_companion`），
    // 没有一个可以切换的持久状态。所以点它就真的说一句进入陪伴的话。
    const comp = $('#modeCompanion');
    if (comp) {
      comp.addEventListener('click', () => send('陪我说说话'));
    }

    // 记住上一个分区，给「返回上一步」用。
    $$('.dock [data-page]').forEach((btn) => {
      btn.addEventListener('pointerdown', () => {
        const now = $('.workspace.active');
        history.replaceState({e3prev: now ? now.dataset.workspace : 'today'}, '');
      });
    });

    // 切到哪一页就读哪一页的数据。
    const LOADERS = {today: loadToday, records: loadRecords,
                     family: loadFamily, mine: loadSettings};
    $$('.dock [data-page]').forEach((btn) => {
      btn.addEventListener('pointerup', () => {
        const fn = LOADERS[btn.dataset.page];
        if (fn) setTimeout(fn, 260);   // 让切页动效先起来，再填数据
      });
    });
  }

  async function boot() {
    wire();
    // 设置先读：字号语速要在别的内容画上去之前生效。
    await loadSettings();
    await loadToday();
    loadRecords();
    loadFamily();
  }

  boot().catch((e) => {
    // 这一条罩着登录。登录失败的时候屏幕上必须有话，否则整页是一片默认文案，
    // 看起来像是「数据就是长这样」。
    say(errorWords(e, '优活').text, 'bad');
  });
})();
