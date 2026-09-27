// 「我的资料」这一页。姓名由 app.js 的 bindData 填（`data-bind="profile.name"`），
// 这里只补它填不了的三块：家里有谁、提醒有几条、记录有几条。
//
// 三个请求都用 allSettled：任何一个挂了，其余两块照样出来。
// 这一页没有一个数字是写死的——取不到就说取不到。
(function () {
  const ROLE_ORDER = { 家人: 0, 系统: 1, 本人: 2 };

  function row(name, right, muted) {
    const line = document.createElement("div");
    line.className = "line";
    line.style.minHeight = "56px";
    const left = document.createElement("span");
    left.textContent = name;
    const val = document.createElement("span");
    val.textContent = right;
    if (muted) val.className = "muted";
    line.appendChild(left);
    line.appendChild(val);
    return line;
  }

  async function render() {
    const [contacts, reminders, records] = await Promise.allSettled([
      YouhuoAPI.get("/contacts"),
      YouhuoAPI.get("/reminders"),
      YouhuoAPI.get("/records"),
    ]);
    const val = (r) => (r.status === "fulfilled" ? r.value : null);

    const box = document.querySelector("#meFamily");
    const note = document.querySelector("#meFamilyNote");
    const people = (val(contacts) || {}).items || [];
    if (box) {
      box.innerHTML = "";
      if (!people.length) {
        // 空表也要有话说。留白会被当成「加载中」，而它其实已经加载完了。
        box.appendChild(row("还没有登记家人", "", true));
      } else {
        people
          .slice()
          .sort((a, b) => (ROLE_ORDER[a.role] ?? 9) - (ROLE_ORDER[b.role] ?? 9))
          .forEach((p) => {
            box.appendChild(row(p.name, p.primary ? "主要联系人" : p.role, !p.primary));
          });
      }
    }
    if (note && people.length) {
      // 电话号码后端确实没有这个字段。说出来，而不是画一个假号码——
      // 老人真按下去会拨错人。
      const missing = people.filter((p) => !p.phone).length;
      note.hidden = missing === 0;
      note.textContent = missing
        ? `其中 ${missing} 位还没有留电话，可以请家人在自己那一端补上。`
        : "";
    }

    const put = (sel, text) => {
      const el = document.querySelector(sel);
      if (el) el.textContent = text;
    };
    const rem = val(reminders);
    const rec = val(records);
    put("#meReminderCount", rem ? `${rem.count} 条` : "读不到");
    put("#meRecordCount", rec ? `${(rec.items || []).length} 条` : "读不到");
  }

  document.addEventListener("DOMContentLoaded", () => {
    render().catch((e) => {
      console.warn(e);
      toast("这一页有一部分没读出来");
    });
  });
})();
