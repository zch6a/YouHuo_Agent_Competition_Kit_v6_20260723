const statusEl = document.querySelector('#judgeStatus');

// 身份、登录、401 重放都在 common.js 里；此前这一页没有 401 重放，令牌一过期，
// 导览就会在评委面前静默失败。
//
// 老人和家人两个身份都要：七拍里有三拍走的是真实任务状态机（开口、复述、家人接力），
// 那三步分别以老人和家人的身份发出——用同一个身份跑完全程，"第二个人点头"就成了
// 自己跟自己点头，而那恰好是这一页要证明的反面。
let IDS = {elderId: 'elder-demo', daughterId: 'daughter-demo'};

/** 这一次演示的那件事。七拍共享它——七拍讲的是同一件事，不是七件事。
 *
 * `mode` 有两种，而且**必须让评委知道是哪一种**：
 *
 *   fresh   这一遍真的办了一笔。
 *   replay  这个月的水费上一次已经交过了，后端回 `duplicate_blocked`。这不是失败，
 *           恰恰是这个产品该有的样子——它不会为了演示再扣一次钱。这时候第 5、6 拍
 *           改成从审计链里把上一次的记录读出来，并且在正文里说清楚"这是上一次的
 *           记录"。假装又办了一遍，就是在一页专门讲可信的页面上撒谎。
 */
const story = {session: null, taskId: null, amount: null, digest: null, mode: 'fresh'};

async function login() {
  IDS = await window.YouHuo.ready();
  await Promise.all([window.YouHuo.login('family'), window.YouHuo.login('elder')]);
}

function api(path, options = {}, role = 'family') {
  return window.YouHuo.api(path, options, role);
}

function post(path, body, role = 'family') {
  return api(path, {method: 'POST', body: JSON.stringify(body)}, role);
}

function showJSON(id, data) {
  window.YouHuo.renderResult(document.querySelector(id), data);
}

/* 翻译层。Product 层里一个英文枚举都不许有。
 *
 * 第一版演完之后那七句话里漏出了三个：语音结论 `clarify`、预演决策 `clarify`、
 * 任务状态 `awaiting_family_approval`，外加一个四位小数的负荷分数 `0.6684`。
 * 它们是从真实响应里直接插进去的——"用真实数据填 Product 层"这个决定本身是对的，
 * 但真实数据是给机器读的，翻译不能省。原始值都在下面 Proof 层的原始响应里。
 *
 * **不保留原始值做兜底。** 兜底成原始码，等于这层翻译在遇到新枚举时自动失效，
 * 而那正是它该起作用的时候（family.js 的 auditLabel 为同样的理由这么写）。 */
const VOICE_WORD = {
  clarify: '要问清楚', accept: '可以照办', reject: '不办',
  escalate: '交给家人', conflict: '两路打架，不执行',
};
const DECISION_WORD = {
  clarify: '要问清楚', allow: '放行', deny: '拒绝',
  require_human: '要人来定', escalate: '交给家人',
};
const STATE_WORD = {
  collecting: '还在收集信息', awaiting_elder_confirmation: '等她确认',
  awaiting_family_approval: '等家人接力', executing: '正在办理',
  completed: '已完成并核验', cancelled: '已取消', failed: '未成功，已安全停下',
};
function word(table, value, kind) {
  return table[value] || `（这个${kind}还没有中文说法，原值在下面的原始响应里）`;
}

/** Product 层那一句。
 *
 * 这是七拍改造的核心：这句话由**真实响应**填写，不是写死在 HTML 里的文案。写死的
 * 文案在接口改坏之后照样好看，那就不是演示，是插图。HTML 里的初始文本是演之前的
 * 剧情提要，演过之后被真实结果替换。
 */
function say(beat, text) {
  const node = document.querySelector(`#say-${beat}`);
  if (node) node.textContent = text;
  const article = document.querySelector(`.beat[data-beat="${beat}"]`);
  if (article) article.classList.add('is-played');
}

function activate(beat) {
  document.querySelectorAll('.beat').forEach(
    el => el.classList.toggle('is-current', el.dataset.beat === beat));
}

// --- 七拍 ---------------------------------------------------------------

/** 上一次办成的那笔水费。演第二遍时第 5、6 拍从它的审计记录里取事实。 */
async function lastCompletedBill() {
  const tasks = await api('/v2/tasks?limit=100');
  const done = tasks.filter(t => t.task_type === 'bill_payment' && t.status === 'completed');
  return done.length ? done[done.length - 1] : null;
}

async function runOpen() {
  activate('01');
  statusEl.textContent = '正在以老人身份说第一句话……';
  story.session = (await post('/v2/sessions', {}, 'elder')).session_id;
  const data = await post('/v2/chat',
    {session_id: story.session, text: '帮我交这个月的水费'}, 'elder');

  if (data.code === 'duplicate_blocked') {
    // 不是失败。这是"同一笔账不会扣两次"这条规则在起作用，而它值得单独说一句。
    const prior = await lastCompletedBill();
    if (!prior) throw new Error('后端说这个月已经交过，但库里找不到那笔任务');
    story.mode = 'replay';
    story.taskId = prior.id;
    story.amount = (prior.details || {}).amount_yuan;
    say('01', '她说：「帮我交这个月的水费。」——这个月已经交过了，优活直接回'
      + '「不用再交」，没有为了演示再扣一次。下面第 5、6 拍读的是上一次留在链上的记录。');
    showJSON('#beatOpen', {
      这一轮的结论: '同一笔账不会扣两次', 任务状态: data.task_status,
      屏幕上的话: data.message, 上一次那笔: prior.summary, 那笔的状态: prior.status,
    });
    statusEl.textContent = '第 1 拍：重复缴费被拦下——这是规则在起作用，不是演示失败。';
    return;
  }

  story.mode = 'fresh';
  story.taskId = data.task_id;
  story.amount = (data.data || {}).amount_yuan
    || (String(data.message).match(/(\d+\.\d{2})\s*元/) || [])[1];
  if (!story.amount) throw new Error('账单金额没回来，后面六拍无从谈起');
  say('01', `她说：「帮我交这个月的水费。」优活查到 ${story.amount} 元，`
    + '并且没有直接去付——它先停下来问。');
  showJSON('#beatOpen', {
    这一轮的结论: data.code, 任务状态: data.task_status,
    金额从哪来: '账单接口，不是她说的数字', 账单金额: story.amount, 屏幕上的话: data.message,
  });
  statusEl.textContent = '第 1 拍：任务已立，等她确认。';
}

async function runVoice() {
  activate('02');
  statusEl.textContent = '正在模拟两路语音识别候选冲突……';
  const data = await post('/v5/voice/resolve', {
    elder_id: IDS.elderId, side_effect_possible: true,
    candidates: [
      {text: '确认办理本月水费', confidence: 0.91, engine: 'core-speech-primary'},
      {text: '取消办理本月水费', confidence: 0.89, engine: 'core-speech-backup'},
    ],
  });
  say('02', `两路识别一个听成「确认办理」（0.91）、一个听成「取消办理」（0.89）。`
    + `优活的结论是「${word(VOICE_WORD, data.status, '结论')}」`
    + `——它没有按分高的那个执行，而是回头问她。`);
  showJSON('#demoVoiceOut', {
    结论: data.status, 澄清语: data.clarification_prompt,
    安全标记: data.safety_flags, 理由: data.rationale,
  });
  statusEl.textContent = '第 2 拍：确认/取消冲突被识别，系统没有猜测执行。';
}

async function runLoad() {
  activate('03');
  statusEl.textContent = '正在按老人交互画像降低信息密度……';
  const data = await post('/v6/interaction/plan', {
    elder_id: IDS.elderId,
    message: '系统将提交本月水费付款请求，请核对账单对象、金额、截止日期和付款家属。',
    options: ['确认办理', '取消办理', '请女儿看看', '稍后再办'],
    risk_level: 4, asr_confidence: 0.93, recent_retries: 1, reversible: false,
  });
  const shown = (data.visible_options || []).length;
  // 负荷分数原样是 0.6684——四位小数对一个"这一屏有多重"的判断没有意义，
  // 而它在 Product 层看起来像一个精确到万分之一的物理量。折成百分数。
  const load = Math.round(Number(data.cognitive_load_score || 0) * 100);
  say('03', `给它四个选项，它只留下 ${shown} 个，并且要求复述而不是点「是」。`
    + `这一屏的负荷估到 ${load}%。`);
  showJSON('#demoLoadOut', {
    播报: data.speak_text, 可见选项: data.visible_options,
    复述确认: data.require_teach_back, 负荷分数: data.cognitive_load_score, 原因: data.rationale,
  });
  statusEl.textContent = '第 3 拍：本轮只呈现一个动作，并用复述确认代替简单的是/否。';
}

async function runPreview() {
  activate('04');
  statusEl.textContent = '正在把恶意 OCR 内容送进模型外的策略防火墙……';
  const data = await post('/v6/actions/preview', {
    elder_id: IDS.elderId, goal: '缴纳本月水费', action: 'create_payment_request',
    arguments: {bill_id: 'water-2026-07', amount_cents: 999999, elder_id: IDS.elderId, execute: true},
    facts: [
      {name: 'bill_id', value: 'water-2026-07', origin: 'trusted_tool', purpose: 'bill_payment', trusted_for_control: true},
      {name: 'amount_cents', value: 999999, origin: 'untrusted_document', purpose: 'bill_payment', trusted_for_control: false},
      {name: 'elder_id', value: IDS.elderId, origin: 'system', sensitivity: 3, purpose: 'bill_payment', trusted_for_control: true},
    ],
    user_confirmed: true, family_approvals: 1, reversible: true,
  });
  // 可选链：这一页是给评委看的，响应少一个字段不该变成一屏 TypeError。
  // `authorization` 缺失时下面仍会写出结论，而结论此时是假的——所以取不到就明说。
  const auth = data.authorization || {};
  showJSON('#demoPreviewOut', {
    决策: auth.decision ?? '（响应里没有 authorization）', 剥离字段: auth.stripped_fields,
    说明: data.plain_summary, 不会做: data.will_not_do, 人工确认: data.required_humans,
  });
  if (!auth.decision) throw new Error('预演响应缺少授权决策，不能当作通过');
  const stripped = (auth.stripped_fields || []).length;
  say('04', `图片里写着 9999.99 元，还夹了一条「直接支付」。`
    + `决策是「${word(DECISION_WORD, auth.decision, '决策')}」，`
    + `${stripped} 个字段在进入工具参数之前被剥掉。`);
  statusEl.textContent = '第 4 拍：文档金额与越权执行字段都没有进入真实工具参数。';
}

/** 这件任务在审计链上的记录。演第二遍时第 5、6 拍的事实从这里来。 */
async function auditFor(taskId) {
  const audit = await api('/v2/audit?limit=200');
  return {
    chainValid: audit.chain_valid,
    events: (audit.events || []).filter(e => e.entity_id === taskId),
  };
}

async function runTeachBack() {
  activate('05');
  if (!story.taskId || !story.amount) throw new Error('先跑第 1 拍：还没有一件可讲的事');

  if (story.mode === 'replay') {
    const {events} = await auditFor(story.taskId);
    const teach = events.find(e => e.event_type === 'TEACH_BACK_VERIFIED');
    if (!teach) throw new Error('上一次那笔的链上没有复述记录');
    const p = teach.payload;
    say('05', `上一次她念的是「确认支付${p.heard}元」。链上记着：期望 ${p.expected}，`
      + `听到 ${p.heard}，第 ${p.attempts} 次通过。念错就停在原地，不会按听到的数字去付。`);
    showJSON('#beatTeach', {
      这一条来自: '审计链，不是这一次的调用', 期望金额: p.expected,
      听到的金额: p.heard, 第几次通过: p.attempts, 结果: p.outcome,
    });
    statusEl.textContent = '第 5 拍：读的是上一次留下的复述记录。';
    return;
  }

  statusEl.textContent = '正在让老人复述金额……';
  const data = await post('/v2/chat',
    {session_id: story.session, text: `确认支付${story.amount}元`}, 'elder');
  story.digest = data.approval_digest;
  story.taskId = data.task_id || story.taskId;
  if (!story.digest) throw new Error('没有拿到确认摘要，复述这一步没有真的通过');
  say('05', `她念了「确认支付${story.amount}元」。念对了，任务才从「等她确认」`
    + `走到「${word(STATE_WORD, data.task_status, '状态')}」。`
    + '念错就停在原地，不会按听到的数字去付。');
  showJSON('#beatTeach', {
    这一轮的结论: data.code, 任务状态: data.task_status,
    确认摘要: story.digest, 屏幕上的话: data.message,
  });
  statusEl.textContent = '第 5 拍：复述通过，现在等第二个人。';
}

async function runRelay() {
  activate('06');
  if (!story.taskId) throw new Error('先跑第 1 拍：还没有一件可讲的事');
  let status = null;
  if (story.mode === 'replay') {
    statusEl.textContent = '正在从审计链里读上一次的接力记录……';
  } else {
    if (!story.digest) throw new Error('先跑第 5 拍：还没有待确认的摘要');
    statusEl.textContent = '正在以家人身份点同意……';
    status = (await post('/v2/family/approve',
      {task_id: story.taskId, approve: true, approval_digest: story.digest})).task_status;
  }

  // 摘要是否一致这件事，两种模式下都从**审计链**里读——链是权威来源，而接口回包
  // 只是它的一个侧面。
  const {events, chainValid} = await auditFor(story.taskId);
  const elderConfirm = events.find(e => e.event_type === 'ELDER_CONFIRMED');
  const familyOk = events.find(e => String(e.event_type).startsWith('FAMILY_APPROVED'));
  const same = !!(elderConfirm && familyOk
    && elderConfirm.payload.approval_digest === familyOk.payload.approval_digest);
  if (!status) {
    status = (await lastCompletedBill() || {}).status || 'completed';
  }
  const prefix = story.mode === 'replay' ? '上一次女儿点了同意' : '女儿点了同意';
  say('06', `${prefix}。她同意的摘要和老人确认的${same ? '是同一个' : '不一致'}`
    + `——${same ? '对得上才执行' : '对不上就不执行'}。`
    + `任务状态：${word(STATE_WORD, status, '状态')}。`);
  showJSON('#beatRelay', {
    这一条来自: story.mode === 'replay' ? '审计链，不是这一次的调用' : '这一次的真实调用',
    任务状态: status,
    老人确认的摘要: elderConfirm ? elderConfirm.payload.approval_digest : '（没找到）',
    家人同意的摘要: familyOk ? familyOk.payload.approval_digest : '（没找到）',
    两者一致: same, 审计链自校验: chainValid,
  });
  if (!same) throw new Error('两个摘要对不上，这一拍不能算通过');
  statusEl.textContent = '第 6 拍：两个摘要一致，任务执行。';
}

async function runCard() {
  activate('07');
  statusEl.textContent = '正在生成老人看得懂的玻璃盒解释……';
  const data = await post('/v6/reliance/card', {
    elder_id: IDS.elderId, heard_text: '帮我交水费', goal: '处理本月水费',
    current_step: '核对账单', action: '创建付款请求', risk_level: 4, reversible: true,
    confirmations: ['老人复述金额', '女儿扫码支付'],
    evidence: [
      {label: '水务账单', source: '可信账单沙箱', trusted: true, verified: true},
      {label: '上传图片备注', source: 'OCR', trusted: false, verified: false},
    ],
    next_step: '请老人复述账单金额，随后通知女儿扫码',
  });
  const box = document.querySelector('#glassCard');
  box.replaceChildren();
  const rows = [
    ['我听到', data.heard], ['正在做', data.current_step], ['谁决定', data.who_decides],
    ['下一步', data.next_step], ['能否撤销', data.reversible ? '可以按规则撤销或补偿' : '不可自动撤销'],
    ['核验情况', data.confidence_message],
  ];
  rows.forEach(([k, v]) => {
    const row = document.createElement('div');
    const key = document.createElement('strong');
    const value = document.createElement('span');
    key.textContent = k; value.textContent = v;
    row.append(key, value); box.appendChild(row);
  });
  if (data.warning) {
    const warning = document.createElement('p');
    warning.className = 'notice warning';
    warning.textContent = data.warning;
    box.appendChild(warning);
  }
  say('07', `${data.confidence_message} 决定权在「${data.who_decides}」。`);
  statusEl.textContent = '第 7 拍：老人不用懂技术词，也知道系统凭什么、谁说了算。';
}

async function runBoard() {
  statusEl.textContent = '正在汇总评分证据与剩余缺口……';
  const data = await api('/v6/competition/evidence');
  const board = document.querySelector('#evidenceBoard');
  board.replaceChildren();
  data.items.forEach(item => {
    const card = document.createElement('article');
    card.className = 'evidence-mini';
    const h = document.createElement('h3');
    h.textContent = `${item.dimension} · ${item.score_weight}分`;
    const ready = document.createElement('p');
    ready.textContent = `当前成熟度：${item.readiness}`;
    const list = document.createElement('ul');
    item.evidence.slice(0, 3).forEach(x => {
      const li = document.createElement('li'); li.textContent = x; list.appendChild(li);
    });
    const gap = document.createElement('p');
    gap.className = 'meta';
    gap.textContent = '剩余：' + item.remaining_gap.join('；');
    card.append(h, ready, list, gap);
    board.appendChild(card);
  });
  statusEl.textContent = '证据板已加载：已实现、待真机验证和禁止宣传的内容分开列出。';
}

// --- 绑定 ---------------------------------------------------------------

// 顺序即剧情。第 5、6 拍依赖第 1 拍立下的那件事，所以整场演出必须按这个顺序走。
const BEATS = [
  ['01', runOpen, '#beatOpen'],
  ['02', runVoice, '#demoVoiceOut'],
  ['03', runLoad, '#demoLoadOut'],
  ['04', runPreview, '#demoPreviewOut'],
  ['05', runTeachBack, '#beatTeach'],
  ['06', runRelay, '#beatRelay'],
  ['07', runCard, '#glassCard'],
];
const HANDLERS = {
  runOpen, runVoice, runLoad, runPreview, runTeachBack, runRelay, runCard, runBoard,
};

/** 失败时同时写进状态行**和**这一拍自己的输出区。
 *
 * 原先只写状态行——那一行在页面顶部，而评委的眼睛在他刚点的那个按钮上，于是
 * "点了没反应"。
 */
function report(error, outSelector) {
  statusEl.textContent = error.message;
  const out = outSelector && document.querySelector(outSelector);
  if (out) { out.replaceChildren(); out.textContent = error.message; }
}

// `addEventListener` 而不是 `.onclick =`：后者是覆盖而不是叠加，哪天有人给同一个
// 按钮再挂一件事，先挂的那件会无声消失。
document.querySelectorAll('[data-run]').forEach(button => {
  const name = button.dataset.run;
  const beat = BEATS.find(([, fn]) => fn === HANDLERS[name]);
  button.addEventListener('click', () => {
    const fn = HANDLERS[name];
    if (!fn) return;
    fn().catch(error => report(error, beat ? beat[2] : null));
  });
});
document.querySelector('#demoBoard').addEventListener('click',
  () => runBoard().catch(error => report(error, '#evidenceBoard')));

const playButton = document.querySelector('#playStory');
playButton.addEventListener('click', async () => {
  playButton.disabled = true;
  // 演出期间禁用整排按钮。原先没有这层保护——演到一半再点一次「从头演一遍」，
  // 两场演出会争同一个 story 对象，第二场的第 6 拍会拿第一场的摘要去批第二场的任务。
  document.querySelectorAll('[data-run]').forEach(b => { b.disabled = true; });
  const original = playButton.textContent;
  try {
    for (const [beat, run, out] of BEATS) {
      playButton.textContent = `正在演第 ${Number(beat)} 拍……`;
      try {
        await run();
      } catch (error) {
        report(error, out);
        throw error;
      }
      // 一拍一顿。全部瞬间跑完的话，评委看到的是七块同时出现的文字，
      // 而这一页的论点恰恰是"这件事有先后顺序"。
      await new Promise(resolve => window.setTimeout(resolve, 420));
    }
    statusEl.textContent = '七拍全部走完，全部是真实接口的真实返回。'
      + '每一拍都可以展开看原始响应，也可以单独重跑。';
  } catch (_) {
    statusEl.textContent += '（演出在这里停下了。没有跳过失败的那一拍。）';
  } finally {
    playButton.textContent = original;
    playButton.disabled = false;
    document.querySelectorAll('[data-run]').forEach(b => { b.disabled = false; });
  }
});

login()
  .then(() => { statusEl.textContent = '演示环境已就绪。按「从头演一遍」，或展开任意一拍单独跑。'; })
  .catch(error => { statusEl.textContent = error.message; });
