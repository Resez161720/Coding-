"use strict";

// สีที่ใช้แสดงตัวอย่างกระดาษ (ชื่อสีต้องตรงกับ config.toml)
const PAPER = {
  "ชมพู": "#f8bbd0", "เขียว": "#c5e1a5", "เหลือง": "#fff59d", "ฟ้า": "#b3e5fc",
  "ส้ม": "#ffcc80", "ขาว": "#ffffff", "ม่วง": "#d1c4e9",
};
const QUESTION_TITLES = {
  paper: "ใส่กระดาษ", final: "ยืนยันการพิมพ์", color: "เปลี่ยนสีกระดาษ", home: "จอเขียวไม่ได้อยู่หน้าแรก",
};
const WORKER_TEXT = { idle: "ว่าง", running: "กำลังพิมพ์", asking: "รอคำตอบ" };
const FIELD_TH = {
  machine: "เครื่อง", work_order: "ใบสั่งงาน", mat_do: "D/O", mat_coil: "Coil", die: "ดาย",
  emp: "พนักงาน", cart: "รถเข็น", qty: "จำนวน", ng: "NG", color: "สี",
};

let state = null;
let filter = "todo";
let shownQuestionId = null;
let editing = null;

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function chip(color) {
  return `<span class="chip" style="background:${PAPER[color] || "#ccc"}"></span>`;
}

function toast(message, bad = false) {
  const box = $("toast");
  box.textContent = message;
  box.className = bad ? "toast bad" : "toast";
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { box.hidden = true; }, 5000);
}

async function api(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Tagbot": "1" },
    body: JSON.stringify(body || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

async function act(promise, successMessage) {
  try {
    const result = await promise;
    if (successMessage) toast(successMessage);
    await refresh();
    return result;
  } catch (error) {
    toast(error.message, true);
    return null;
  }
}

async function refresh() {
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    state = await response.json();
    $("offline").hidden = true;
    render();
  } catch (error) {
    $("offline").hidden = false;
  }
}

// ---------- แสดงผล ----------

function render() {
  const busy = state.worker.state !== "idle";
  $("mode").textContent = state.mode === "demo" ? "โหมดทดลอง (จอเขียวจำลอง)" : "เชื่อมต่อจอเขียวจริง";
  $("mode").className = "badge " + (state.mode === "demo" ? "demo" : "live");
  $("worker-state").textContent = "สถานะ: " + (WORKER_TEXT[state.worker.state] || state.worker.state) +
    (state.worker.color ? ` (สี${state.worker.color})` : "");
  $("master-error").hidden = !state.master_error;
  $("master-error").textContent = state.master_error || "";
  $("sample").hidden = !state.demo_scans;
  $("stop").disabled = !busy;
  $("worker-message").textContent = state.worker.message || "";

  $("groups").innerHTML = state.groups.map((group) => `
    <div class="group">${chip(group.color)} สี${esc(group.color)}
      <button class="primary" data-run="${esc(group.color)}"
        ${group.ready === 0 || busy || state.master_error ? "disabled" : ""}>
        เริ่มพิมพ์ ${group.ready} ใบ</button>
    </div>`).join("");

  $("needs-color").innerHTML = state.needs_color.length === 0 ? "" : `
    <div class="needs-color"><b>เลือกสีกระดาษให้ใบสั่งงานเหล่านี้ (เครื่องทำได้หลายประเภทงาน)</b>
      ${state.needs_color.map((item) => `
        <div class="item">${esc(item.work_order)} (${item.count} ใบ)
          ${state.colors.map((color) => `<button class="small" data-wo="${esc(item.work_order)}"
            data-color="${esc(color)}">${chip(color)} ${esc(color)}</button>`).join("")}
        </div>`).join("")}
    </div>`;

  renderRequests();
  renderQuestion();
}

function needsAction(row) {
  return row.status === "failed" || row.status === "attention" || (row.status === "pending" && row.issues.length > 0);
}

function renderRequests() {
  const rows = state.requests;
  const groups = {
    todo: rows.filter(needsAction),
    pending: rows.filter((r) => r.status === "pending"),
    done: rows.filter((r) => r.status === "done"),
    all: rows,
  };
  $("count-todo").textContent = `(${groups.todo.length})`;
  $("count-pending").textContent = `(${groups.pending.length})`;
  $("count-done").textContent = `(${groups.done.length})`;
  const visible = groups[filter].slice().reverse();
  $("empty").hidden = visible.length > 0;
  $("empty").textContent = {
    todo: "ไม่มีรายการที่ต้องแก้ไข", pending: "ไม่มีรายการรอพิมพ์", done: "วันนี้ยังไม่ได้พิมพ์", all: "ไม่มีรายการ",
  }[filter];
  document.querySelector("#requests tbody").innerHTML = visible.map((row) => {
    const notes = [
      row.error ? `<div class="err">${esc(row.error)}</div>` : "",
      ...row.issues.map((issue) => `<div class="issue">${esc(issue.message)}</div>`),
    ].join("");
    const actions = [];
    if (row.status === "pending" || row.status === "failed") actions.push(`<button class="small" data-edit="${row.id}">แก้ไข</button>`);
    if (row.status === "failed") actions.push(`<button class="small" data-action="retry" data-id="${row.id}">ลองใหม่</button>`);
    if (row.status === "attention") actions.push(`<button class="small" data-action="resolve" data-id="${row.id}">ทำเองบนจอเขียวแล้ว</button>`);
    if (["pending", "failed", "attention"].includes(row.status)) actions.push(`<button class="small" data-action="cancel" data-id="${row.id}">ยกเลิก</button>`);
    return `<tr>
      <td>${row.id}</td>
      <td><span class="status ${esc(row.status)}">${esc(row.status_th)}</span></td>
      <td>${row.color ? chip(row.color) + " " + esc(row.color) : "-"}</td>
      <td>${esc(row.machine)}</td><td>${esc(row.work_order)}</td><td>${esc(row.cart)}</td>
      <td>${row.full ? "เต็ม" + (row.lot_qty ? ` (${row.lot_qty})` : "") : esc(row.qty)}</td>
      <td>${esc(row.ng)}</td><td>${esc(row.emp)}</td><td>${esc(row.die)}</td>
      <td>${esc(row.mat_do)}</td><td>${esc(row.mat_coil)}</td><td>${esc(row.mo_no)}</td>
      <td class="note">${notes}</td><td>${actions.join(" ")}</td>
    </tr>`;
  }).join("");
}

function renderQuestion() {
  const dialog = $("question");
  const question = state.question;
  if (!question) {
    if (dialog.open) dialog.close();
    shownQuestionId = null;
    return;
  }
  if (shownQuestionId === question.id) return;
  shownQuestionId = question.id;
  $("q-title").textContent = QUESTION_TITLES[question.kind] || "คำถาม";
  $("q-message").textContent = question.message;
  $("q-screen").hidden = !question.screen;
  $("q-screen").textContent = question.screen || "";
  $("q-yes").textContent = question.yes;
  $("q-no").textContent = question.no;
  if (!dialog.open) dialog.showModal();
  $("q-yes").focus();
}

// ---------- การกดปุ่ม ----------

$("import").addEventListener("click", async () => {
  const text = $("scan-text").value;
  if (!text.trim()) return toast("ยังไม่มีข้อมูลจากเครื่องยิง", true);
  let result = await act(api("/api/import", { text }));
  if (result && result.duplicate) {
    if (!confirm("ข้อมูลชุดนี้เคยนำเข้าแล้ว ต้องการนำเข้าซ้ำจริงหรือไม่?")) return;
    result = await act(api("/api/import", { text, force: true }));
  }
  if (!result) return;
  const problems = result.problems.map((p) =>
    `<li>บรรทัด ${p.line}: ${esc(p.raw)} - ${esc(p.message)}</li>`).join("");
  $("import-result").className = "import-result";
  $("import-result").innerHTML = `<b>${esc(result.message)}</b>` +
    (problems ? `<div>barcode ที่มีปัญหา:</div><ul>${problems}</ul>` : "");
  if (result.added > 0) $("scan-text").value = "";
});

$("clear").addEventListener("click", () => { $("scan-text").value = ""; $("import-result").innerHTML = ""; });
$("sample").addEventListener("click", () => { $("scan-text").value = state.demo_scans; });
$("stop").addEventListener("click", () => act(api("/api/stop"), "จะหยุดหลังจบใบที่กำลังทำ"));
$("dump").addEventListener("click", async () => {
  const result = await act(api("/api/dump"));
  if (result) toast("บันทึกหน้าจอไว้ที่ " + result.path);
});
$("reload").addEventListener("click", async () => {
  const result = await act(api("/api/reload"));
  if (result) toast(result.error || "โหลดตารางข้อมูลใหม่แล้ว", Boolean(result.error));
});

$("tabs").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-filter]");
  if (!button) return;
  filter = button.dataset.filter;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b === button));
  renderRequests();
});

document.addEventListener("click", async (event) => {
  const run = event.target.closest("button[data-run]");
  if (run) {
    const result = await act(api("/api/run", { color: run.dataset.run }));
    if (result && !result.ok) toast(result.message, true);
    return;
  }
  const colorButton = event.target.closest("button[data-wo]");
  if (colorButton) {
    act(api("/api/wo-color", { work_order: colorButton.dataset.wo, color: colorButton.dataset.color }));
    return;
  }
  const action = event.target.closest("button[data-action]");
  if (action) {
    const names = { retry: "ลองใหม่", resolve: "ยืนยันว่าทำเองบนจอเขียวแล้ว", cancel: "ยกเลิก" };
    if (confirm(`${names[action.dataset.action]} รายการ ${action.dataset.id}?`)) {
      act(api(`/api/requests/${action.dataset.id}/${action.dataset.action}`));
    }
    return;
  }
  const edit = event.target.closest("button[data-edit]");
  if (edit) openEditor(Number(edit.dataset.edit));
});

$("q-yes").addEventListener("click", () => answer(true));
$("q-no").addEventListener("click", () => answer(false));
$("question").addEventListener("cancel", (event) => event.preventDefault());

function answer(yes) {
  if (!state.question) return;
  const id = state.question.id;
  $("question").close();
  act(api("/api/answer", { id, yes }));
}

function openEditor(id) {
  editing = state.requests.find((row) => row.id === id);
  if (!editing) return;
  const form = $("editor-form");
  $("e-id").textContent = "#" + id;
  $("e-error").textContent = "";
  for (const name of ["machine", "work_order", "mat_do", "mat_coil", "die", "emp", "cart"]) {
    form.elements[name].value = editing[name] || "";
  }
  form.elements.qty.value = editing.full ? "" : editing.qty;
  form.elements.ng.value = editing.ng;
  $("editor").showModal();
}

$("editor-form").addEventListener("submit", async (event) => {
  if (event.submitter && event.submitter.value !== "save") return;
  event.preventDefault();
  const form = $("editor-form");
  const changes = {};
  for (const name of ["machine", "work_order", "mat_do", "mat_coil", "die", "emp", "cart", "qty", "ng"]) {
    changes[name] = form.elements[name].value;
  }
  try {
    await api(`/api/requests/${editing.id}/edit`, changes);
    $("editor").close();
    toast("บันทึกแล้ว");
    refresh();
  } catch (error) {
    $("e-error").textContent = error.message;
  }
});

refresh();
setInterval(refresh, 1000);
