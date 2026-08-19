/* 事务证据工作台。
 * ===========================================================================
 *
 * 这一页原先是一条七拍的导览：页面决定讲哪一件事，从头讲到尾，看的人只能跟着走。
 * 那一份已经整体搬到 /stage（逐条去处见 `D:\YouHuo\proposals\judge-beats-removed.md`）。
 *
 * 现在这一页做的是另一件事：**给定一笔事务，把它的证据摊开**。主动权换了方向——
 * 查的人指定编号，页面负责把那一笔的链、那一步的记录、那件事的决策依据摆出来。
 *
 * 三条贯穿全文的规矩：
 *
 *   一、**单笔的链用 `entity_id` 参数取**，不是取 200 条再在浏览器里筛。
 *       筛出来的条数取决于这个家庭最近有多忙：忙的那天同一笔会少几条，而页面
 *       不会有任何异样。这是"读到的值不等于决定结果的值"那一类，最难发现。
 *
 *   二、**枚举一律翻译，认不出就说认不出，不回落到原值。** 回落成原值等于这层翻译
 *       在遇到新枚举时自动失效——而那恰好是它该起作用的时候。原始值留在每一块下面
 *       可展开的完整记录里，那里是它该在的地方。
 *
 *   三、**时间不过 `new Date()`。** 后端写的是 ISO 串，直接切片显示。丢给 Date 解析
 *       再格式化，等于让浏览器所在时区去改写一条审计记录上的时刻——这个项目已经
 *       为同一个形状付过一次代价。
 */

const statusEl = document.querySelector('#judgeStatus');

/** 身份、登录、401 重放都在 common.js 里。
 *
 * 只要家属身份：审计链（`/v2/audit`）和运行指标（`/v5/metrics`）都只对绑定家属开放，
 * 而这一页从头到尾只读不写，没有任何一步需要以老人的身份发出。
 */
let IDS = {elderId: 'elder-demo', daughterId: 'daughter-demo'};

function api(path, options = {}, role = 'family') {
  return window.YouHuo.api(path, options, role);
}

const byId = (id) => document.getElementById(id);

function showJSON(id, data) {
  window.YouHuo.renderResult(document.querySelector(id), data);
}

/* --- 绑定 -----------------------------------------------------------------
 *
 * 这一段刻意放在文件很靠前的位置，而且**每一个控件 id 在整个文件里的第一次出现
 * 都在这里**。
 *
 * 理由不是排版：`backend/scripts/build_control_inventory.py` 按"id 字符串第一次
 * 出现之后 600 字符内有没有 addEventListener"来判定一个控件的交互类型，并按
 * 那一处所在的函数体去归属它调用了哪些接口。把绑定散在各个 loader 里，清单会
 * 把"这个按钮是干什么的"记成空，而它在报告里和"没有这个控件"长得一样。
 *
 * 回调一律写成**具名函数引用**，不写内联箭头：内联箭头会在这里引入一层花括号，
 * 归属算法就会把那一层当成控件所在的函数体。
 *
 * `addEventListener` 而不是直接给属性赋值：后者是覆盖而不是叠加，哪天有人给同一个
 * 按钮再挂一件事，先挂的那件会无声消失。
 */
function bindControls() {
  document.querySelector('#txnForm').addEventListener('submit', onSubmit);
  document.querySelector('#txnPick').addEventListener('change', onPickChanged);
  document.querySelector('#txnRefresh').addEventListener('click', onRefresh);
  document.querySelector('#tlKey').addEventListener('click', onKeyOnly);
  document.querySelector('#tlAll').addEventListener('click', onShowAll);
  document.querySelector('#tlList').addEventListener('click', onStepPicked);
  document.querySelector('#tabEvidence').addEventListener('click', onTab);
  document.querySelector('#tabSafety').addEventListener('click', onTab);
  document.querySelector('#tabAudit').addEventListener('click', onTab);
  document.querySelector('#tabApi').addEventListener('click', onTab);
  document.querySelector('#tabRuntime').addEventListener('click', onTab);
  document.querySelector('#tabTests').addEventListener('click', onTab);
}
// `#txnGo` 不在上面：它是这个表单的提交按钮（不写 type，`<button>` 在 `<form>` 里
// 默认就是提交）。给它再挂一个 click 就会和 submit 各跑一次，同一笔事务连取两遍。
// 它的禁用与恢复在 `busy()` 里；`#txnId` 由 `wantedId()` 读，两者都不需要监听器。
//
// 这里原先写着「刻意不写 type，这样 `components.css` 的 `form > button:not([type])`
// 会给它 56px 的关键操作触控高度」。**两个前提都不成立**：HTML 里它写着
// `type="submit"`，而且它在 `.controls` 里、从来不是 `<form>` 的直接子元素——
// 那条规则一次都没有选中过它。一段描述着不存在机制的注释，比没有注释更贵：
// 下一个人会以为这个高度有人管着。它拿的是 48px 触控下限，对「读一笔」是对的。

//: 六格系统面板：格子按钮 → 面板 → 出处说明 → 落点表里的哪一行。
//:
//: 放在这里（而不是挨着那六个 loader）是有理由的：清单脚本按「这个 id 在文件里
//: 第一次出现在哪个函数体内」去归属它调用了哪些接口。挨着 loader 写的话，
//: 六个 `srcXxx` 会被算成"这个 `<summary>` 会调那个接口"——它不会，它只是一段说明。
const SYSTEM_TABS = [
  {tab: 'tabEvidence', panel: 'sysEvidence', source: 'srcEvidence', beat: 'evidence'},
  {tab: 'tabSafety', panel: 'sysSafety', source: 'srcSafety', beat: 'safety'},
  {tab: 'tabAudit', panel: 'sysAudit', source: 'srcAudit', beat: 'audit'},
  {tab: 'tabApi', panel: 'sysApi', source: 'srcApi', beat: 'api'},
  {tab: 'tabRuntime', panel: 'sysRuntime', source: 'srcRuntime', beat: 'runtime'},
  {tab: 'tabTests', panel: 'sysTests', source: 'srcTests', beat: 'tests'},
];

/* --- 这一次在看的东西 ------------------------------------------------------ */

const state = {
  tasks: [],        // 这个家庭的全部事务，用来填选单
  task: null,       // 现在这一笔
  events: [],       // 现在这一笔在链上的全部记录，最早在前
  chainValid: null, // 整条链的自校验结果。**这是家庭级的**，不是这一笔的
  keyOnly: true,    // 时间轴是否只显示关键步骤
  picked: null,     // 时间轴上选中的那一条（审计记录的序号）
  truth: null,      // /v5/capability-truth 的缓存，安全与测试两格共用
  loaded: new Set(),// 已经取过的系统格，切回来不重取
  contextReads: 0,  // 调阅这一笔之后，这一页自己往链上写了几条调阅记录
};

/* --- 翻译层 ---------------------------------------------------------------
 *
 * 一个英文枚举都不许走到屏幕上，而且**不保留原值做兜底**。兜底成原始码等于这层
 * 翻译在遇到新枚举时自动失效，而那正是它该起作用的时候。
 * 原值都在同一块下面那份可展开的完整记录里。
 */

//: 审计事件码 → 这一步在人话里叫什么。
//:
//: 这张表刻意不含任何任务状态键（`collecting` / `executing` …）：那一套由
//: `window.YouHuo.statusWord()` 统一负责，各页各抄一份正是这个项目漂过的地方。
const EVENT_WORD = {
  SESSION_CREATED: '开始一次对话',
  SEMANTIC_ROUTED: '听出她要办什么',
  TASK_CREATED: '立下这件事',
  TASK_SLOT_CORRECTED: '更正了其中一项信息',
  COGNITIVE_LOAD_PLAN_CREATED: '把这一屏的信息量压低',
  SAFE_ACTION_PREVIEWED: '执行前先预演一遍',
  PURPOSE_BOUND_POLICY_DECISION: '按目的绑定判定该不该放行',
  SUSPICIOUS_INSTRUCTION_BLOCKED: '拦下一条可疑指令',
  VOICE_CONSENSUS_RESOLVED: '两路识别打架，取共识',
  TEACH_BACK_VERIFIED: '她复述通过',
  TEACH_BACK_REJECTED: '她复述没通过，停在原地',
  ELDER_CONFIRMED: '老人确认',
  FAMILY_APPROVAL_RECORDED: '家人点头，已记下',
  FAMILY_APPROVED_AND_EXECUTED: '家人点头，随即执行',
  FAMILY_APPROVED_EXECUTION_FAILED: '家人点头了，但没能执行',
  FAMILY_REJECTED: '家人不同意',
  FAMILY_REMINDER_CREATED: '家人建了一条提醒',
  TASK_EXECUTED: '这件事办妥了',
  TASK_FAILED: '没能办成，已安全停下',
  TASK_CANCELLED: '这件事停下了',
  NOTIFICATION_CREATED: '发出一条通知',
  SCHEDULER_TICK: '定时巡检走了一遍',
  RELIANCE_CARD_CREATED: '生成一张给她看的说明卡',
  TASK_EXPLANATION_VIEWED: '有人调阅了这件事的说明',
  TASK_PROOF_GENERATED: '生成了一份完成证明',
  MODE_SWITCHED: '换了交互模式',
  EMOTIONAL_TASK_PAUSE: '察觉情绪不对，先停一停',
  EMOTIONAL_TASK_RESUMED: '情绪平复，接着办',
  SAFETY_SIGNAL: '一条安全信号',
  DEMO_LOGIN: '一次沙箱登录',
  DEMO_SEEDED: '铺好了一套沙箱数据',
};

//: 会改变这一笔去向的那些步骤。「只看关键步骤」留下的就是它们。
//:
//: 这是一个人做的取舍，所以它同时被写进页面上那段说明里——由这个常量生成，
//: 不是在 HTML 里另写一份。两份会漂，而漂了之后页面上那段话会开始说谎。
const KEY_EVENTS = [
  'TASK_CREATED', 'TEACH_BACK_VERIFIED', 'TEACH_BACK_REJECTED', 'ELDER_CONFIRMED',
  'FAMILY_APPROVAL_RECORDED', 'FAMILY_APPROVED_AND_EXECUTED',
  'FAMILY_APPROVED_EXECUTION_FAILED', 'FAMILY_REJECTED',
  'TASK_EXECUTED', 'TASK_FAILED', 'TASK_CANCELLED',
  'SUSPICIOUS_INSTRUCTION_BLOCKED',
];

//: 这一笔上出现过就值得单独说一句的安全动作。
const SAFETY_EVENTS = [
  'SUSPICIOUS_INSTRUCTION_BLOCKED', 'SAFE_ACTION_PREVIEWED',
  'PURPOSE_BOUND_POLICY_DECISION', 'VOICE_CONSENSUS_RESOLVED',
  'TEACH_BACK_REJECTED', 'SAFETY_SIGNAL',
];

//: `/v6/competition/evidence` 的成熟度取值。
const READINESS_WORD = {
  strong_prototype: '原型已经很完整',
  high_backend_medium_native: '后端扎实，端侧还在补',
  credible: '站得住',
  strong: '扎实',
};

//: `/health` 里那个语义档位。
const SEMANTIC_WORD = {
  model_advised: '模型只出建议，不做决定',
  deterministic_only: '完全按规则走，不用模型',
};

//: `/v5/metrics` 的计数键。
const METRIC_WORD = {
  voice_total: '语音判定次数',
  voice_clarify: '其中停下来问清楚的',
  policy_total: '策略判定次数',
  policy_deny: '其中直接拒绝的',
  saga_total: '长流程总数',
  saga_completed: '其中走完的',
  saga_compensated: '其中回滚补偿的',
  sync_total: '离线同步次数',
  sync_conflict: '其中出现版本冲突的',
  open_break_glass: '还开着的限时破窗',
  trace_errors: '记下的错误条数',
};

//: `/v5/.../explain` 的 `what_i_understood` 里那些槽位名。
//:
//: 后端把它拼成 `键：值` 的字符串再发过来（`v5_services.py:706`），所以屏幕上是
//: 「任务类型：bill_payment」「amount_cents：6840」——**一个英文枚举值加两个英文
//: 字段名**，就在「系统听懂了什么」这一格里。文件头第二条说的就是这件事。
//:
//: 只翻**认得的**键，认不出的连键带值原样留着：这一格叫「系统听懂了什么」，
//: 少列一条比改写一条糟得多，而原值本来就在下面那份完整记录里。
//:
//: 「任务类型」这个键**不在表里**，是有意的：它本来就是中文，改写它只是换个说法，
//: 而这一格的缺陷从来不是它——是它的**值**（`bill_payment`）。值由 `slotLine`
//: 单独过一遍 `taskWord`。
const SLOT_WORD = {
  amount_cents: '金额（分）',
  amount_yuan: '金额（元）',
  bill_type: '账单种类',
  bill_id: '账单编号',
  period: '所属月份',
  hospital: '医院',
  department: '科室',
  appointment_date: '号源日期',
  appointment_time: '号源时间',
  due_date: '到期日',
  due_time: '到期时刻',
  title: '标题',
  goal: '她说的目标',
  teach_back_attempts: '复述了几遍',
  family_approved: '家人点过头了吗',
  family_approval_count: '几位家人点过头',
};

/** 查表。认不出说认不出，**不回落到原值**。 */
function word(table, value, kind) {
  return Object.prototype.hasOwnProperty.call(table, String(value))
    ? table[String(value)]
    : `（这个${kind}还没有中文说法，原值在下面的完整记录里）`;
}

function eventWord(type) {
  return word(EVENT_WORD, type, '步骤');
}

/** 后端拼好的一行 `键：值`，把认得的部分翻成中文。
 *
 * 第一条永远是 `任务类型：<TaskType 枚举>`，所以它的**值**也要翻——那是这一格里
 * 唯一一个走到屏幕上的英文枚举值，其余是字段名。
 * 认不出的键原样留下：这一层是翻译，不是过滤。
 */
function slotLine(line) {
  const text = String(line == null ? '' : line);
  const cut = text.indexOf('：');
  if (cut < 0) return text;
  const key = text.slice(0, cut);
  const rest = text.slice(cut + 1);
  const name = Object.prototype.hasOwnProperty.call(SLOT_WORD, key) ? SLOT_WORD[key] : key;
  const shown = key === '任务类型' ? window.YouHuo.taskWord(rest) : rest;
  return `${name}：${shown}`;
}

/** 「第 N 档（共 4 档）」，**N 真的是个数才说**。
 *
 * 两处原先都是裸插值（`第 ${card.risk_level} 档`、`第 ${state.task.risk_level} 档`）。
 * 这一页此前印过一次 `第 undefined 次通过` 的同门缺陷就在隔壁 `/trust` 上，
 * 而这两处的字段来自两个不同的接口，任一个改形状都会以同样的方式漏出来。
 */
function riskWords(level) {
  const n = Number(level);
  return Number.isFinite(n)
    ? `第 ${n} 档（共 4 档，档位越高越要人来定）`
    : '这一条上没有记下风险档位';
}

/** 这一条是谁做的。
 *
 * 判据按可靠性排序：老人比的是**这一笔自己的** `elder_id`（那是权威的），
 * 家属比的是这个浏览器拿到的家属身份。两个都对不上时不猜成「系统」——
 * 一个家庭可以有第二个家属，把他记成系统就是在一页讲权责的页面上记错责任人。
 */
function actorWord(actorId) {
  const id = String(actorId || '');
  if (state.task && id === state.task.elder_id) return '老人本人';
  if (id === IDS.daughterId) return '家人';
  if (id === IDS.elderId) return '老人本人';
  if (/^(system|scheduler|youhuo|seed)/.test(id)) return '系统';
  return '这个家庭的另一位成员';
}

/** ISO 串里的那一刻，原样切出来。见文件头第三条。 */
const dayOf = (iso) => String(iso || '').slice(0, 10);
const clockOf = (iso) => String(iso || '').slice(11, 16);

/* --- 主值与权威方 ---------------------------------------------------------
 *
 * 「主值」是这一笔最要紧的那个数：缴费是金额，挂号是号源时间，提醒是到期时刻。
 * 它**不是**这一页算出来的，是任务记录里那一个字段——所以下面这张表只决定
 * "读哪个字段"，不做任何换算。
 */
function mainValue(task) {
  const d = (task && task.details) || {};
  if (d.amount_yuan) return {text: `${d.amount_yuan} 元`, from: '账单接口给出的金额，不是她说的数字'};
  if (d.appointment_date || d.appointment_time) {
    return {text: `${d.appointment_date || ''} ${d.appointment_time || ''}`.trim(),
            from: '医院号源给出的时间'};
  }
  if (d.due_date) return {text: `${d.due_date} ${d.due_time || ''}`.trim(), from: '这件事的到期时刻'};
  if (d.goal) return {text: d.goal, from: '她自己说的目标'};
  return {text: '这一类事务没有单一主值', from: '这一类事务的要点不落在某一个数字上'};
}

/** 这一笔用一句话说是什么。
 *
 * **不许用 `card.summary`。** 那不是一句摘要，是后端拼的
 * `f"{task_type.value} · {status.value}"`（`v5_services.py:729`）——两个英文枚举。
 * 它原先直接落在「这件事是什么」这一行上，屏幕上是
 * 「这件事是什么：bill_payment · completed」，而**下一行**的 `current_status`
 * 就被翻成了「办好了」。半边翻译比不翻更难看，也正是文件头第二条禁的那件事。
 *
 * 任务记录自己的摘要（「2026-07水费 68.40元」）信息量更大，有就用它。
 * 没有任务记录时（链比任务活得久）才去拆 `card.summary`，两半各自翻译。
 */
function taskSummary(card) {
  const own = String((state.task || {}).summary || '').trim();
  if (own) return own;
  const type = String((card || {}).summary || '').split('·')[0].trim();
  return `${window.YouHuo.taskWord(type)} · ${window.YouHuo.statusWord((card || {}).current_status)}`;
}

/** 谁的确认让这一笔往下走。全部从链上读，不从任务状态推。 */
function authority(events) {
  const has = (type) => events.some((e) => String(e.event_type).startsWith(type));
  if (has('FAMILY_APPROVED') || has('FAMILY_APPROVAL_RECORDED')) return '家人点头';
  if (has('FAMILY_REJECTED')) return '家人否决';
  if (has('SUSPICIOUS_INSTRUCTION_BLOCKED')) return '规则拦下';
  if (has('TEACH_BACK_VERIFIED') || has('ELDER_CONFIRMED')) return '老人复述';
  if (has('TASK_CANCELLED')) return '规则停下';
  return '还没有人拍板';
}

/* --- 事务清单与跳转 -------------------------------------------------------- */

async function loadTaskList() {
  state.tasks = await api('/v2/tasks?limit=100');
  const pick = byId('txnPick');
  const options = byId('txnOptions');
  pick.replaceChildren();
  options.replaceChildren();
  if (!state.tasks.length) {
    const none = document.createElement('option');
    none.value = '';
    none.textContent = '这个家庭现在一笔事务都没有';
    pick.appendChild(none);
    return;
  }
  state.tasks.forEach((task) => {
    const option = document.createElement('option');
    option.value = task.id;
    option.textContent = `${window.YouHuo.taskWord(task.task_type)} · ${task.summary}`
      + ` · ${window.YouHuo.statusWord(task.status)}`;
    pick.appendChild(option);
    // datalist 给的是编号本身：粘编号的人要补全的是编号，不是摘要。
    const hint = document.createElement('option');
    hint.value = task.id;
    options.appendChild(hint);
  });
}

//: 地址栏带进来的那个编号，**在这个文档被解析的那一刻**读一次。
//:
//: 必须在这里读、而且必须只读这一次：`loadTransaction` 每次都会把
//: `location.hash` 覆写成它正在看的那一笔，所以载入之后再读 hash 读到的是
//: 页面自己刚写下去的值，不是别人递过来的那个链接。
const INITIAL_HASH = decodeURIComponent(String(location.hash || '').replace(/^#/, '')).trim();

//: 地址栏那一个还没有被用掉。第一次调阅之后清掉——从那以后是人在开车。
let honourInitialHash = Boolean(INITIAL_HASH);

/** 现在该看哪一笔：**第一次载入**看地址栏，之后看输入框 → 选单 → 最近一笔。
 *
 * 这个函数的文档原先写的是「地址栏里指定的 → 输入框里填的 → 选单选中的 → 最近一笔」，
 * 而代码写的是 `typed || picked || fromHash || …`——**地址栏排在第三**。
 * 它因此一次都没生效过：`loadTaskList()` 往 `#txnPick` 里塞选项，浏览器自动选中第一
 * 条，于是 `picked` 永远非空，`fromHash` 永远轮不到。实测把
 * `/judge#task-seed-await-…` 交给一个全新标签页，打开的是 `task-seed-bill-…`
 * ——另一笔事务，而且页面不会说任何一句话。
 *
 * 这一页的主张是「主动权在看的人手里，他指定编号」。递一个链接过去正是"别人指定"
 * 唯一的形式，也是评委之间互相指认一笔事务唯一的办法。
 *
 * 顺序不能简单地改成 `fromHash` 优先：`loadTransaction` 会把 hash 写成当前这一笔，
 * 那样一来在输入框里换一个编号会被上一笔的 hash 顶掉。所以是**一次性**的优先级。
 */
function wantedId() {
  if (honourInitialHash && INITIAL_HASH) return INITIAL_HASH;
  const typed = byId('txnId').value.trim();
  const picked = byId('txnPick').value.trim();
  return typed || picked || (state.tasks[0] && state.tasks[0].id) || '';
}

/* --- 调阅一笔事务 ---------------------------------------------------------- */

async function loadTransaction() {
  const id = wantedId();
  // 地址栏那一次机会用掉了。**放在这里而不是成功之后**：编号打错时也该停在
  // 那个错误上，而不是下一次静默换成别的一笔——「它换了一笔而且不说」正是
  // 这条路径原来的毛病。
  honourInitialHash = false;
  if (!id) throw new Error('还没有指定要看哪一笔事务，而这个家庭的清单也是空的');

  statusEl.textContent = '正在调阅这一笔事务的链……';
  // 换一笔就重新数：下面那句「这一次打开又多了几条」说的是**这一笔**。
  state.contextReads = 0;
  // 两处都对齐到同一个编号，免得输入框和选单各说各的。
  byId('txnId').value = id;
  byId('txnPick').value = state.tasks.some((t) => t.id === id) ? id : '';
  location.hash = encodeURIComponent(id);

  state.task = state.tasks.find((t) => t.id === id) || null;

  // 单笔的链走 `entity_id`。见文件头第一条：**不**取 200 条再在浏览器里筛。
  const chain = await api(`/v2/audit?entity_id=${encodeURIComponent(id)}&limit=200`);
  state.events = chain.events || [];
  state.chainValid = chain.chain_valid;

  if (!state.task && !state.events.length) {
    throw new Error('这个编号在这个家庭里既没有任务记录，也没有任何链上记录');
  }

  renderHead();
  renderTimeline();
  renderNotes();
  pickStep(defaultStep());
  await loadContext(id);

  statusEl.textContent = `这一笔在链上有 ${state.events.length} 条记录。`
    + `整条家庭链的自校验：${state.chainValid ? '通过' : '没通过'}。`;
}

function renderHead() {
  const task = state.task;
  const value = mainValue(task);
  byId('txnWhat').textContent = task ? window.YouHuo.taskWord(task.task_type) : '查无此任务记录';
  byId('txnState').textContent = task ? window.YouHuo.statusWord(task.status) : '不详';
  byId('txnValue').textContent = task ? value.text : '不详';
  byId('txnAuthority').textContent = authority(state.events);

  const bits = [];
  bits.push(`编号 ${byId('txnId').value}`);
  if (task) bits.push(`摘要「${task.summary}」`);
  bits.push(`主值${value.from}`);
  bits.push('权威方读的是链上最后一次有效的人工确认，不是任务状态推出来的');
  if (!task) {
    bits.push('这个编号在任务清单里已经找不到了，下面三栏只剩链上的记录——'
      + '这不是错误，链比任务活得久');
  }
  byId('txnNote').textContent = bits.join('；') + '。';
}

/* --- 时间轴 ---------------------------------------------------------------- */

function visibleEvents() {
  if (!state.keyOnly) return state.events;
  const kept = state.events.filter((e) => KEY_EVENTS.includes(String(e.event_type)));
  // 一条关键步骤都没有的时候不给空白：那会让人以为链是空的。
  return kept.length ? kept : state.events;
}

//: 这一页**自己**在链上留下的记录。取一次决策上下文就多一条（页面上那段
//: 「调阅这一栏，本身也会留下记录」把这件事说在前面了）。
const PAGE_OWN_EVENTS = ['TASK_EXPLANATION_VIEWED'];

/** 默认摊开哪一步。
 *
 * 原先是 `state.events[state.events.length - 1]`，理由写着「查一笔事务的人最先
 * 想知道的是它现在停在哪儿」。那个理由是对的，那行代码在第二次打开这一页之后就
 * 不成立了：链上最后一条变成了**这一页自己刚写下的调阅记录**，于是「它停在哪儿」
 * 的答案成了「有人看过它」。
 *
 * 更糟的是它还看不见：默认档位是「只看关键步骤」，而调阅记录不在关键步骤里——
 * 右边摊开着一条左边列表里根本找不到的记录，时间轴上一条高亮都没有。实测如此。
 *
 * 所以两层：先排掉这一页自己的痕迹，再落在**当前档位真的显示出来的**那一批的
 * 最后一条。两层都空才退回整条链的最后一条——那时链上除了调阅什么都没有，
 * 摊开它才是对的。
 */
function defaultStep() {
  const shown = visibleEvents();
  const real = shown.filter((e) => !PAGE_OWN_EVENTS.includes(String(e.event_type)));
  const pool = real.length ? real : shown;
  return pool.length ? pool[pool.length - 1].id : null;
}

function renderTimeline() {
  const list = byId('tlList');
  list.replaceChildren();
  const rows = visibleEvents();
  if (!rows.length) {
    const empty = document.createElement('p');
    empty.className = 'meta';
    empty.textContent = '这一笔在链上还没有任何记录。';
    list.appendChild(empty);
    return;
  }
  rows.forEach((event) => {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'log-item';
    row.dataset.step = String(event.id);
    if (state.picked === event.id) row.setAttribute('aria-current', 'true');

    const left = document.createElement('div');
    const who = document.createElement('span');
    who.className = 'who';
    who.textContent = actorWord(event.actor_id);
    const when = document.createElement('time');
    when.dateTime = String(event.created_at || '');
    when.textContent = `${dayOf(event.created_at)} ${clockOf(event.created_at)}`;
    left.append(who, when);

    const what = document.createElement('div');
    what.textContent = eventWord(event.event_type);
    row.append(left, what);
    list.appendChild(row);
  });
}

function pickStep(eventId) {
  state.picked = eventId;
  // 上一条的哈希还开着的话，读的人会以为那是这一条的。收起来。
  const chainBox = document.querySelector('#evChain');
  if (chainBox) chainBox.open = false;
  renderTimeline();
  renderEvidence();
}

function renderEvidence() {
  const head = byId('evHead');
  head.replaceChildren();
  const event = state.events.find((e) => e.id === state.picked);
  if (!event) {
    // 「左边」只在三栏并排时成立。720px 以下 `.dashboard-grid` 退成单列，
    // 时间轴在**上面**——那时这两句是在给一个不存在的方向指路。按栏目名说。
    showJSON('#evBody', {这一栏: '时间轴上还没有选中任何一步'});
    showJSON('#evChainBody', {这一栏: '要先在时间轴上选中一步'});
    return;
  }
  const rows = [
    ['这一步', eventWord(event.event_type)],
    ['谁做的', actorWord(event.actor_id)],
    ['什么时候', `${dayOf(event.created_at)} ${clockOf(event.created_at)}`],
    ['链上序号', `第 ${event.id} 条`],
  ];
  rows.forEach(([key, value]) => {
    const row = document.createElement('div');
    row.className = 'digest-row';
    const label = document.createElement('strong');
    label.textContent = key;
    const cell = document.createElement('span');
    cell.textContent = value;
    row.append(label, cell);
    head.appendChild(row);
  });

  showJSON('#evBody', event.payload || {});
  showJSON('#evChainBody', {
    这一条自己的指纹: event.event_hash,
    它记下的上一条指纹: event.prev_hash,
    整条家庭链的自校验: state.chainValid,
    这条链是谁的: '这个家庭，不只是这一笔',
  });
}

/** 三段由数据生成的说明。写在这里而不是写死在 HTML 里，是因为它们各自都在
 *  复述一个常量或一个计数——写死两份，改了一份就开始说谎。 */
function renderNotes() {
  const legend = document.querySelector('#tlLegend');
  const how = document.querySelector('#tlHow');
  const self = document.querySelector('#ctxSelf');

  const named = KEY_EVENTS.map(eventWord).join('、');
  fill(legend, 'tlLegendLine', `这一档现在留下的是：${named}。`
    + '这一行由过滤器用的那份常量生成，不是另写一遍——两份会漂。');

  const key = state.events.filter((e) => KEY_EVENTS.includes(String(e.event_type))).length;
  fill(how, 'tlHowLine', `这一笔一共 ${state.events.length} 条记录，其中关键步骤 ${key} 条；`
    + `整条家庭链此刻的自校验结果是「${state.chainValid ? '通过' : '没通过'}」。`);

  // 这个数**只能**说成「读这条链的时候有几条」。
  //
  // 顺序是钉死的：先取链（`/v2/audit`），再取决策上下文（`/v5/.../explain`），
  // 而后者会往链上写一条 `TASK_EXPLANATION_VIEWED`。也就是说 `state.events` 里
  // 永远缺这一次自己写的那条。原文写的是「这一笔上**现在**有 N 条调阅记录」，
  // 而屏幕上第一次打开时它是 0——同一屏上隔壁那句还写着「每刷新一次这一页就会
  // 多一条」。一个自称「这一页自己不存任何一个值」的页面，第一个说错的就是它
  // 自己的计数。
  const looks = state.events.filter((e) => e.event_type === 'TASK_EXPLANATION_VIEWED').length;
  fill(self, 'ctxSelfLine', `读这条链的时候，这一笔上有 ${looks} 条调阅记录。`
    + (state.contextReads
      ? `取决策上下文又写了 ${state.contextReads} 条，重新调阅一次就看得见它们。`
      : '')
    + '这个数是从链上数出来的，不是页面自己在计数。');
}

/** 往一个 details 里补一行由数据生成的说明；重复调用只更新，不堆叠。 */
function fill(container, lineId, text) {
  if (!container) return;
  let line = byId(lineId);
  if (!line) {
    line = document.createElement('p');
    line.className = 'meta';
    line.id = lineId;
    container.appendChild(line);
  }
  line.textContent = text;
}

/* --- 决策上下文 ------------------------------------------------------------
 *
 * `/v5/tasks/{id}/explain` 会在链上写一条 `TASK_EXPLANATION_VIEWED`。那不是没清
 * 干净的副作用，是这套系统对自己也用同一条规矩：查过的人也要留痕。页面上那段
 * 「调阅这一栏，本身也会留下记录」把这件事说在前面，而时间轴上真的会多出来。
 */
async function loadContext(id) {
  const box = document.querySelector('#ctxBody');
  try {
    const card = await api(`/v5/tasks/${encodeURIComponent(id)}/explain`);
    state.contextReads += 1;
    showJSON('#ctxBody', {
      这件事是什么: taskSummary(card),
      现在到哪一步: window.YouHuo.statusWord(card.current_status),
      风险档位: riskWords(card.risk_level),
      系统听懂了什么: (card.what_i_understood || []).map(slotLine),
      为什么这么办: card.why_this_action,
      // `data_used` 是一串 `{source, purpose}`。`common.js` 的 `FIELD_LABEL` 认得
      // `purpose`（「用途」）但不认得 `source`，于是这一格渲染成一列「source / 用途 /
      // source / 用途」——半边中文半边英文，比两边都英文更像没做完。
      // 键在这里就换掉，不去动那张全站共享的表。
      用到了哪些数据: (card.data_used || []).map(
        (row) => ({来源: (row || {}).source, 用途: (row || {}).purpose})),
      // 「谁确认过」读的是**确认投票表**（`approval_rows`），不是这一笔的链。
      // 两者可以不一致——种子数据就是这样：链上有 `FAMILY_APPROVED_AND_EXECUTED`，
      // 而投票表是空的，于是这一行说「尚无确认记录」，同一屏顶上的「权威方」说
      // 「家人点头」。两句都没说谎，说谎的是把它们摆在一起而不说各自读的是什么。
      谁在确认表上点过头: card.confirmations,
      办成的凭据: card.completion_evidence,
      能不能撤: card.reversible ? '可以按规则撤销或补偿' : '不可自动撤销',
      要撤怎么撤: card.undo_guidance,
      为这件事存下了什么: card.stored_data,
      隐私说明: card.privacy_note,
    });
    // 这一次调阅刚往链上写了一条，那段自述里的条数要跟着走。见 `renderNotes`。
    renderNotes();
  } catch (error) {
    // 这一栏塌了不该把另外两栏一起拖下水：链和证据已经在屏幕上了，
    // 而它们才是这一页的主张。所以这里就地说明，不往上抛。
    box.replaceChildren();
    box.textContent = `这一笔的决策说明没能取到：${error.message}`;
  }
}

/* --- 系统那六格 ------------------------------------------------------------ */

async function loadSysEvidence() {
  const data = await api('/v6/competition/evidence');
  const board = byId('evidenceBoard');
  board.replaceChildren();
  (data.items || []).forEach((item) => {
    const card = document.createElement('article');
    card.className = 'evidence-mini';
    const head = document.createElement('h3');
    head.textContent = `${item.dimension} · 权重 ${item.score_weight}`;
    const ready = document.createElement('p');
    ready.textContent = `成熟度：${word(READINESS_WORD, item.readiness, '成熟度')}`;
    const list = document.createElement('ul');
    (item.evidence || []).slice(0, 3).forEach((line) => {
      const li = document.createElement('li');
      li.textContent = line;
      list.appendChild(li);
    });
    const gap = document.createElement('p');
    gap.className = 'meta';
    gap.textContent = '还差：' + ((item.remaining_gap || []).join('；') || '没有列出缺口');
    card.append(head, ready, list, gap);
    board.appendChild(card);
  });
  note('srcEvidence', `这一次取到 ${(data.items || []).length} 个维度。`);
}

async function loadSysSafety() {
  const truth = await capabilityTruth();
  const fired = state.events.filter((e) => SAFETY_EVENTS.includes(String(e.event_type)));
  showJSON('#sysSafetyBody', {
    这一笔上真的动作过的安全机制: fired.length
      ? fired.map((e) => eventWord(e.event_type))
      : ['这一笔上没有任何安全机制被触发过'],
    我们明确不宣称的能力: truth.adapters_not_claimed_as_production,
    这一笔的风险档位: state.task
      ? riskWords(state.task.risk_level)
      : '这一笔的任务记录已经不在了，档位无从谈起',
  });
  note('srcSafety', `这一次在这一笔的链上数到 ${fired.length} 次安全动作。`);
}

async function loadSysAudit() {
  // 这一格刻意**不带** entity_id：上面三栏看一笔，这一格看它所在的整条链。
  const chain = await api('/v2/audit?limit=200');
  const events = chain.events || [];
  const counts = {};
  events.forEach((e) => {
    const label = eventWord(e.event_type);
    counts[label] = (counts[label] || 0) + 1;
  });
  showJSON('#sysAuditBody', {
    整条链是否自校验通过: chain.chain_valid,
    这一次取到几条: events.length,
    最早一条: events.length ? `${dayOf(events[0].created_at)} ${clockOf(events[0].created_at)}` : '一条都没有',
    最近一条: events.length
      ? `${dayOf(events[events.length - 1].created_at)} ${clockOf(events[events.length - 1].created_at)}`
      : '一条都没有',
    按步骤分类: counts,
  });
  note('srcAudit', `这一次取到 ${events.length} 条，上限 200 条。`);
}

async function loadSysApi() {
  const spec = await api('/openapi.json');
  const paths = Object.keys(spec.paths || {});
  const methods = ['get', 'post', 'put', 'patch', 'delete'];
  let operations = 0;
  const byPrefix = {};
  paths.forEach((path) => {
    const entry = spec.paths[path] || {};
    operations += methods.filter((m) => entry[m]).length;
    const prefix = (path.split('/')[1] || '根路径');
    byPrefix[`以 ${prefix} 开头的路径`] = (byPrefix[`以 ${prefix} 开头的路径`] || 0) + 1;
  });
  showJSON('#sysApiBody', {
    这套服务一共几条路径: paths.length,
    一共几个操作: operations,
    接口定义的版本: (spec.info || {}).version,
    按前缀分: byPrefix,
    这些数字从哪来: '逐条数自这台服务器自己生成的接口定义，不是手写的清单',
  });
  note('srcApi', `这一次数到 ${paths.length} 条路径、${operations} 个操作。`);
}

async function loadSysRuntime() {
  const health = await api('/health');
  let counters = null;
  try {
    const metrics = await api('/v5/metrics');
    counters = {};
    Object.entries(metrics.counters || {}).forEach(([key, value]) => {
      counters[word(METRIC_WORD, key, '计数')] = value;
    });
  } catch (error) {
    counters = {取不到: error.message};
  }
  showJSON('#sysRuntimeBody', {
    这台服务器此刻: health.status === 'ok' ? '正常' : '不正常',
    版本: health.version,
    自检时链是否完好: health.audit_chain_valid,
    是否必须有大模型才能跑: health.llm_required ? '是' : '否，没有模型也能办事',
    语义档位: word(SEMANTIC_WORD, health.semantic_mode, '档位'),
    模型能不能自己授权: health.model_can_authorize ? '能' : '不能，授权永远不经模型',
    是不是沙箱: health.demo_mode ? '是，这是演示沙箱' : '否',
    开机以来的计数: counters,
  });
  note('srcRuntime', '这一次取自 /health 与 /v5/metrics 两个接口。');
}

async function loadSysTests() {
  const truth = await capabilityTruth();
  const done = truth.implemented_and_tested || [];
  showJSON('#sysTestsBody', {
    已经做好并核验过的: done,
    一共几项: done.length,
    用例总数为什么不在这里:
      '那个数字由仓库里的用例集跑出来，这台服务器不知道它。'
      + '一个服务器报不出来的数字，这一页不替它报——要看用例，去跑那一套。',
  });
  note('srcTests', `这一次取到 ${done.length} 项。`);
}

/** 安全与测试两格共用这一份，只取一次。 */
async function capabilityTruth() {
  if (!state.truth) state.truth = await api('/v5/capability-truth');
  return state.truth;
}

/** 往某一格的「这一格取自哪里」里补一行**这一次实际取到了什么**。
 *
 * 这是这一页对自己用的那条规矩：每一块数字都要说得出它是从哪一次请求来的。
 * 静态的一句「取自某某接口」只是声明；这一行是那一次真的发生过的证据。
 */
function note(sourceId, text) {
  fill(document.getElementById(sourceId), `${sourceId}Line`, text);
}

/* --- 落点表 ---------------------------------------------------------------
 *
 * 每一块可加载的区域，配一个**失败时把话写在哪儿**的落点。
 *
 * 变量名 `BEATS` 是被钉住的：`backend/tests/test_pwa_shell.py:558` 按这个名字找它，
 * 并要求恰好七行、七个互不相同的落点，其中必须有 `'#evidenceBoard'`。七拍搬走
 * 之后这个名字对内容已经不贴切了，但改名要同时改那份测试，而这一轮不动
 * backend/tests——所以名字留着，含义在这里写清楚，改名列进了待办。
 */
const BEATS = [
  ['transaction', loadTransaction, '#tlList'],
  ['evidence', loadSysEvidence, '#evidenceBoard'],
  ['safety', loadSysSafety, '#sysSafetyBody'],
  ['audit', loadSysAudit, '#sysAuditBody'],
  ['api', loadSysApi, '#sysApiBody'],
  ['runtime', loadSysRuntime, '#sysRuntimeBody'],
  ['tests', loadSysTests, '#sysTestsBody'],
];

function beatOf(name) {
  return BEATS.find((row) => row[0] === name);
}

/** 失败时同时写进状态行**和**这一块自己的输出区。
 *
 * 只写状态行是不够的：那一行在页面顶部，而看的人的眼睛在他刚点的那个东西上，
 * 于是「点了没反应」。
 */
function report(error, outSelector) {
  statusEl.textContent = error.message;
  const out = outSelector && document.querySelector(outSelector);
  if (out) { out.replaceChildren(); out.textContent = error.message; }
}

/** 取数期间把两个会重新发起请求的控件按住。
 *
 * 不加这一层的话，连点两下「调阅」会有两次取数同时在跑，而它们写的是同一批 DOM：
 * 后回来的那一次覆盖先回来的，于是屏幕上可能是 A 的时间轴配 B 的证据。
 */
function busy(on) {
  const go = byId('txnGo');
  const refresh = byId('txnRefresh');
  if (go) go.disabled = on;
  if (refresh) refresh.disabled = on;
}

function run(name) {
  const beat = beatOf(name);
  if (!beat) return Promise.resolve();
  busy(true);
  return beat[1]()
    .catch((error) => report(error, beat[2]))
    .finally(() => busy(false));
}

/* --- 交互 ------------------------------------------------------------------ */

function onSubmit(event) {
  event.preventDefault();
  run('transaction');
}

function onPickChanged() {
  // 选单动了，输入框跟着走：两处显示同一个编号，谁也别猜现在看的是哪一笔。
  byId('txnId').value = byId('txnPick').value;
  run('transaction');
}

async function onRefresh() {
  // 链会长（这一页自己就会往上加调阅记录），所以要有一个把它重新拉一遍的办法。
  state.loaded.clear();
  state.truth = null;
  try {
    await loadTaskList();
  } catch (error) {
    report(error, '#tlList');
    return;
  }
  await run('transaction');
  await showTab(currentTab());
}

function onKeyOnly() {
  setFilter(true);
}

function onShowAll() {
  setFilter(false);
}

function setFilter(keyOnly) {
  state.keyOnly = keyOnly;
  byId('tlKey').setAttribute('aria-pressed', String(keyOnly));
  byId('tlAll').setAttribute('aria-pressed', String(!keyOnly));
  renderTimeline();
}

function onStepPicked(event) {
  const row = event.target.closest('[data-step]');
  if (!row) return;
  pickStep(Number(row.dataset.step));
}

function currentTab() {
  const on = SYSTEM_TABS.find((entry) => {
    const button = byId(entry.tab);
    return button && button.getAttribute('aria-selected') === 'true';
  });
  return (on || SYSTEM_TABS[0]).tab;
}

function onTab(event) {
  showTab(event.currentTarget.id);
}

async function showTab(tabId) {
  const chosen = SYSTEM_TABS.find((entry) => entry.tab === tabId) || SYSTEM_TABS[0];
  SYSTEM_TABS.forEach((entry) => {
    const button = byId(entry.tab);
    const panel = byId(entry.panel);
    const on = entry.tab === chosen.tab;
    // `aria-selected` 是这一组的真状态，`is-current` 只是它的样子。
    button.setAttribute('aria-selected', String(on));
    button.classList.toggle('is-current', on);
    panel.hidden = !on;
  });
  if (state.loaded.has(chosen.beat)) return;
  state.loaded.add(chosen.beat);
  await run(chosen.beat);
}

/* --- 起步 ------------------------------------------------------------------ */

async function boot() {
  IDS = await window.YouHuo.ready();
  await window.YouHuo.login('family');
  statusEl.textContent = '正在读这个家庭的事务清单……';
  await loadTaskList();
  await run('transaction');
  await showTab(currentTab());
}

bindControls();
boot().catch((error) => { statusEl.textContent = error.message; });
