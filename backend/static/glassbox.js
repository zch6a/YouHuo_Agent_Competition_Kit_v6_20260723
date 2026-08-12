/* 玻璃盒信任卡的渲染。
 *
 * 从 elder.js 里抽出来的。那个文件同时管会话流、语音、玻璃盒、档案和日报，760 行；
 * 这一块是其中边界最清楚的一段——它只依赖传进来的 card / preview 两个对象和一个宿主
 * 节点，不碰会话状态、不发请求。请求仍留在 elder.js（它需要那边的 api 和任务号）。
 *
 * 卡片的措辞由服务端按已存任务生成，所以说的话和引擎真正会执行的动作永远一致；
 * 这里只负责把它摆出来。
 */

// 策略字段名是工程标识符，老人看到的必须是日常词。
const FIELD_LABEL = {
  elder_id: '您的身份', hospital: '医院', department: '科室', doctor: '医生',
  date: '就诊日期', time: '就诊时间', bill_id: '账单编号', amount_cents: '金额',
  recipient_family_id: '接力的家人', title: '事项', due_at: '提醒时间',
  summary: '摘要', source_digest: '来源指纹', event_type: '事件类型',
  urgency: '紧急程度', reason: '原因', location: '位置', period: '账期',
  bill_type: '账单类型', timezone: '时区', health_summary: '健康摘要',
};

// 决定 → 安全预演横幅的语气。"在等您"不该和"被拦下"长成同一种警报。
const DECISION_TONE = {
  allow: 'good',
  require_elder_confirmation: 'info',
  require_family_approval: 'info',
  clarify: 'warning',
  deny: 'warning',
};

function relianceRow(label, value) {
  const row = document.createElement('div');
  row.className = 'reliance-row';
  const strong = document.createElement('strong');
  strong.textContent = label;
  const body = document.createElement('div');
  body.textContent = value;
  row.append(strong, body);
  return row;
}

function bulletList(items) {
  const ul = document.createElement('ul');
  items.forEach(item => {
    const li = document.createElement('li');
    li.textContent = item;
    ul.appendChild(li);
  });
  return ul;
}

/** 把信任卡与安全预演画进 `host`。`preview` 可以为空。 */
export function renderGlassBox(host, card, preview) {
  host.replaceChildren();
  const box = document.createElement('div');
  box.className = 'reliance-card';
  const heading = document.createElement('h3');
  // 标题前原先有一个 `🔍`。这个项目八条硬约束的第七条是**不用 emoji 当图标**，
  // 而这里是全站最后一处（其余的在别的轮次里已经清掉了）。
  //
  // 三个理由，越往后越要紧：
  //   一，emoji 的字形由**系统**决定——同一个码位在鸿蒙、iOS、Windows 上是三个不同
  //       的画法、三种不同的粗细，和这一套统一描边的 SVG 图标放在一起永远是异物；
  //   二，读屏软件会把它念出来（「放大镜」），而这张卡是要念给一位视力在下降的
  //       老人听的，开头多一个"放大镜"没有任何意义；
  //   三，它**不携带信息**——这张卡的身份由它自己的底色、阴影和标题文字承担，
  //       一个放大镜既不表示状态也不表示类别。
  //
  // 所以是去掉，不是换成一个 SVG：先要回答"这里需不需要一个图标"，答案是不需要。
  heading.textContent = card.title;
  box.appendChild(heading);
  box.appendChild(relianceRow('我听到', card.heard));
  box.appendChild(relianceRow('要办的事', card.goal));
  box.appendChild(relianceRow('现在这一步', card.current_step));
  box.appendChild(relianceRow('准备做', card.action_summary));
  box.appendChild(relianceRow('谁来决定', card.who_decides));
  box.appendChild(relianceRow('能否撤销', card.reversible ? '可以撤销' : '不能自动撤销，所以要多确认一次'));
  box.appendChild(relianceRow('下一步', card.next_step));
  box.appendChild(relianceRow('信息核验', card.confidence_message));
  if (card.warning) {
    const warn = document.createElement('div');
    warn.className = 'notice warning';
    warn.textContent = card.warning;
    box.appendChild(warn);
  }

  if (preview) {
    const auth = preview.authorization;
    const summary = document.createElement('div');
    summary.className = `notice ${DECISION_TONE[auth.decision] || 'warning'}`;
    summary.textContent = `安全预演：${preview.plain_summary}`;
    box.appendChild(summary);

    // 设计稿 §4.2 限制一次呈现的信息量，所以字段级细节收在折叠区里，而不是给卡片
    // 再加十几行。
    const details = document.createElement('details');
    details.className = 'preview-details';
    const marker = document.createElement('summary');
    marker.textContent = '看看具体会用到哪些信息';
    details.appendChild(marker);

    const columns = document.createElement('div');
    columns.className = 'preview-columns';

    // 直接读授权里的白名单，而不是去解析服务端那句话——老人看到的是有名字的字段，
    // 用的是日常词。
    const fields = Object.keys(auth.allowed_arguments || {});
    const willDoItems = fields.length
      ? fields.map(key => `只会用到：${FIELD_LABEL[key] || key}`)
      : ['不会产生真实副作用'];
    const willDo = document.createElement('section');
    willDo.appendChild(Object.assign(document.createElement('h4'), {textContent: '会做的事'}));
    willDo.appendChild(bulletList(willDoItems));

    const willNotItems = [...preview.will_not_do];
    if (auth.stripped_fields?.length) {
      willNotItems.push('不会使用被剥离的信息：' + auth.stripped_fields.map(k => FIELD_LABEL[k] || k).join('、'));
    }
    const willNot = document.createElement('section');
    willNot.appendChild(Object.assign(document.createElement('h4'), {textContent: '不会做的事'}));
    willNot.appendChild(bulletList(willNotItems));

    columns.append(willDo, willNot);
    details.appendChild(columns);

    if (preview.required_humans.length) {
      details.appendChild(relianceRow('需要谁确认', preview.required_humans.join('、')));
    }
    details.appendChild(relianceRow('失败怎么办', preview.rollback_plan));
    box.appendChild(details);
  }

  host.appendChild(box);
}
