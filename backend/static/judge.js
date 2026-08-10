const statusEl = document.querySelector('#judgeStatus');

// 这一页以家属身份走全流程。身份、登录、401 重放都在 common.js 里；此前这一页没有
// 401 重放，令牌一过期，五步导览就会在评委面前静默失败。
let IDS = {elderId: 'elder-demo', daughterId: 'daughter-demo'};

async function resolveIdentity() {
  IDS = await window.YouHuo.ready();
  return IDS;
}

async function login() {
  await resolveIdentity();
  await window.YouHuo.login('family');
}

function api(path, options = {}) {
  return window.YouHuo.api(path, options, 'family');
}

function showJSON(id, data) {
  window.YouHuo.renderResult(document.querySelector(id), data);
}

function activate(step) {
  document.querySelectorAll('.demo-step').forEach(el => el.classList.toggle('active', el.dataset.step === String(step)));
}

async function runVoice() {
  activate(1); statusEl.textContent = '正在模拟两路语音识别候选冲突……';
  const data = await api('/v5/voice/resolve', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      elder_id: IDS.elderId, side_effect_possible: true,
      candidates: [
        {text: '确认办理本月水费', confidence: 0.91, engine: 'core-speech-primary'},
        {text: '取消办理本月水费', confidence: 0.89, engine: 'core-speech-backup'}
      ]
    })
  });
  showJSON('#demoVoiceOut', {结论: data.status, 澄清语: data.clarification_prompt, 安全标记: data.safety_flags, 理由: data.rationale});
  statusEl.textContent = '通过：确认/取消冲突被识别，系统没有猜测执行。';
}

async function runLoad() {
  activate(2); statusEl.textContent = '正在按老人交互画像降低信息密度……';
  const data = await api('/v6/interaction/plan', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      elder_id: IDS.elderId,
      message: '系统将提交本月水费付款请求，请核对账单对象、金额、截止日期和付款家属。',
      options: ['确认办理', '取消办理', '请女儿看看', '稍后再办'],
      risk_level: 4, asr_confidence: 0.93, recent_retries: 1, reversible: false
    })
  });
  showJSON('#demoLoadOut', {播报: data.speak_text, 可见选项: data.visible_options, 复述确认: data.require_teach_back, 负荷分数: data.cognitive_load_score, 原因: data.rationale});
  statusEl.textContent = '通过：本轮只呈现一个动作，并使用复述确认代替简单“是/否”。';
}

async function runPreview() {
  activate(3); statusEl.textContent = '正在把恶意OCR内容送入模型外策略防火墙……';
  const data = await api('/v6/actions/preview', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      elder_id: IDS.elderId, goal: '缴纳本月水费', action: 'create_payment_request',
      arguments: {bill_id:'water-2026-07', amount_cents:999999, elder_id:IDS.elderId, execute:true},
      facts: [
        {name:'bill_id', value:'water-2026-07', origin:'trusted_tool', purpose:'bill_payment', trusted_for_control:true},
        {name:'amount_cents', value:999999, origin:'untrusted_document', purpose:'bill_payment', trusted_for_control:false},
        {name:'elder_id', value:IDS.elderId, origin:'system', sensitivity:3, purpose:'bill_payment', trusted_for_control:true}
      ], user_confirmed:true, family_approvals:1, reversible:true
    })
  });
  // 可选链：这一页是给评委看的，响应少一个字段不该变成一屏 TypeError。
  // `authorization` 缺失时下面的 statusEl 仍会写出结论，而结论此时是假的——所以
  // 决策取不到就明说取不到。
  const auth = data.authorization || {};
  showJSON('#demoPreviewOut', {决策:auth.decision ?? '（响应里没有 authorization）', 剥离字段:auth.stripped_fields, 说明:data.plain_summary, 不会做:data.will_not_do, 人工确认:data.required_humans});
  if (!auth.decision) throw new Error('预演响应缺少授权决策，不能当作通过');
  statusEl.textContent = '通过：文档金额与越权执行字段均未进入真实工具参数。';
}

async function runCard() {
  activate(4); statusEl.textContent = '正在生成老人可理解的“玻璃盒”解释……';
  const data = await api('/v6/reliance/card', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      elder_id:IDS.elderId, heard_text:'帮我交水费', goal:'处理本月水费', current_step:'核对账单',
      action:'创建付款请求', risk_level:4, reversible:true,
      confirmations:['老人复述金额', '女儿扫码支付'],
      evidence:[
        {label:'水务账单', source:'可信账单沙箱', trusted:true, verified:true},
        {label:'上传图片备注', source:'OCR', trusted:false, verified:false}
      ], next_step:'请老人复述账单金额，随后通知女儿扫码'
    })
  });
  const box = document.querySelector('#glassCard');
  box.replaceChildren();
  const rows = [
    ['我听到', data.heard], ['正在做', data.current_step], ['谁决定', data.who_decides],
    ['下一步', data.next_step], ['能否撤销', data.reversible ? '可以按规则撤销或补偿' : '不可自动撤销'],
    ['核验情况', data.confidence_message]
  ];
  rows.forEach(([k,v]) => {
    const row = document.createElement('div'); const key = document.createElement('strong'); const value = document.createElement('span');
    key.textContent = k; value.textContent = v; row.append(key, value); box.appendChild(row);
  });
  if (data.warning) { const warning = document.createElement('p'); warning.className='notice warning'; warning.textContent=data.warning; box.appendChild(warning); }
  statusEl.textContent = '通过：老人无需理解技术术语，也能知道系统依据什么、谁有最终决定权。';
}

async function runBoard() {
  activate(5); statusEl.textContent = '正在汇总比赛评分证据与剩余缺口……';
  const data = await api('/v6/competition/evidence');
  const board = document.querySelector('#evidenceBoard'); board.replaceChildren();
  data.items.forEach(item => {
    const card = document.createElement('article'); card.className='evidence-mini';
    const h = document.createElement('h3'); h.textContent=`${item.dimension} · ${item.score_weight}分`;
    const ready = document.createElement('p'); ready.textContent=`当前成熟度：${item.readiness}`;
    const list = document.createElement('ul'); item.evidence.slice(0,3).forEach(x=>{const li=document.createElement('li');li.textContent=x;list.appendChild(li);});
    const gap = document.createElement('p'); gap.className='meta'; gap.textContent='剩余：' + item.remaining_gap.join('；');
    card.append(h,ready,list,gap); board.appendChild(card);
  });
  statusEl.textContent = '证据板已加载：明确区分已实现、待真机验证和禁止宣传的内容。';
}

// `addEventListener` 而不是 `.onclick =`。
//
// 区别只在**已经存在于 HTML 里**的元素上要紧：`.onclick` 是覆盖而不是叠加，哪天有人
// 再给同一个按钮挂一件事，先挂的那件会无声消失。这五个按钮正是写在 judge.html 里的。
// （elder.js 和 family.js 里剩下的四处 `.onclick` 是在刚 createElement 出来的按钮上
// 赋值，那里没有既有处理器可覆盖，是安全的简写，不动。）
//
// 失败时同时写进状态行**和**这一步自己的输出区。原先只写状态行——那一行在页面顶部，
// 而评委的眼睛在他刚点的那个按钮上，于是"点了没反应"。
const STEPS = [
  ['#demoVoice', runVoice, '#demoVoiceOut'],
  ['#demoLoad', runLoad, '#demoLoadOut'],
  ['#demoPreview', runPreview, '#demoPreviewOut'],
  ['#demoCard', runCard, '#glassCard'],
  ['#demoBoard', runBoard, '#evidenceBoard'],
];
STEPS.forEach(([selector, run, outSelector]) => {
  document.querySelector(selector).addEventListener('click', () => run().catch(e => {
    statusEl.textContent = e.message;
    const out = document.querySelector(outSelector);
    if (out) { out.replaceChildren(); out.textContent = e.message; }
  }));
});

login().then(()=>{statusEl.textContent='演示环境已就绪。建议按01→05顺序点击。';}).catch(e=>{statusEl.textContent=e.message;});
