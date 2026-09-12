// 键盘 / 输入法调试日志（移动端 IME 排障用）
// 触发：URL 加 ?log=1，或在控制台执行 window.__kbdEnable()
// 每次事件同时 console.info（前缀 [KB]）并写入下方浮窗 + localStorage 环形缓冲。

const TAG = "[KB]";
const MAX = 300;
const buf = [];
let enabled = false;
let panel = null;

export function kbdLog(label, detail = null) {
  const rec = { ts: Date.now(), label, detail };
  buf.push(rec);
  if (buf.length > MAX) buf.shift();
  if (!enabled) return;
  if (detail) console.info(TAG, label, detail);
  else console.info(TAG, label);
  try { localStorage.setItem("kbd_log_buf", JSON.stringify(buf)); } catch {}
  renderPanel();
}
export function getKbdLogs() { return buf.slice(); }

export function setKbdEnabled(v) {
  const on = Boolean(v);
  if (on === enabled) return;
  enabled = on;
  localStorage.setItem("kbdlog", on ? "1" : "0");
  if (on) buildPanel();
  else if (panel) { panel.remove(); panel = null; }
  if (enabled) console.info(TAG, "键盘日志已开启");
}

function init() {
  const p = new URLSearchParams(location.search);
  if (p.get("log") === "1") setKbdEnabled(true);
}

// 原始事件探针：keydown/keyup/beforeinput/input/compositionupdate 全部落环形缓冲，
// 只盯隐藏输入框 #catch，只读不拦截。移动端 IME 排障就靠它看真实事件序列。
function probe(label) {
  return (e) => {
    const t = e.target;
    if (!t || t.id !== "catch") return;
    kbdLog(label, { key: e.key, code: e.code, inputType: e.inputType,
      data: e.data, val: t.value, composing: e.isComposing || undefined });
  };
}
if (typeof document !== "undefined") {
  for (const [ev, label] of [["keydown", "keydown"], ["keyup", "keyup"],
    ["beforeinput", "beforeinput"], ["input", "inputRaw"],
    ["compositionupdate", "compUpdate"]]) {
    document.addEventListener(ev, probe(label), true);
  }
}

if (typeof document !== "undefined") {
  window.__kbdEnable = () => setKbdEnabled(true);
  window.__kbdDisable = () => setKbdEnabled(false);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
}

function buildPanel() {
  if (panel) { renderPanel(); return; }
  const ns = "kbd-log";
  const st = document.createElement("style");
  st.textContent = `
.${ns}{position:fixed;left:8px;bottom:8px;width:min(360px,92vw);max-height:60vh;
  background:#1e1e2e;color:#cdd6f4;font:11px/1.4 ui-monospace,Menlo,Consolas,monospace;
  border:1px solid #585b70;border-radius:8px;box-shadow:0 4px 18px rgba(0,0,0,.45);
  z-index:99999;display:flex;flex-direction:column;}
.${ns}-head{display:flex;align-items:center;gap:6px;padding:6px 8px;border-bottom:1px solid #585b70;}
.${ns}-head span{font-weight:700;}
.${ns}-head button{background:#313244;color:#cdd6f4;border:1px solid #585b70;border-radius:4px;padding:1px 7px;font:11px monospace;}
.${ns}-list{flex:1;overflow-y:auto;margin:0;padding:4px 8px;list-style:none;}
.${ns}-list li{word-break:break-all;}`;
  document.head.appendChild(st);
  panel = document.createElement("div");
  panel.className = ns;
  panel.id = "kbd-log-panel";
  panel.innerHTML = `<div class="${ns}-head"><span>KB LOG</span><button class="${ns}-copy">复制</button><button class="${ns}-clear">清空</button><button class="${ns}-close">×</button></div><ul class="${ns}-list"></ul>`;
  document.body.appendChild(panel);
  panel.querySelector(".kbd-log-close").onclick = () => setKbdEnabled(false);
  panel.querySelector(".kbd-log-clear").onclick = () => { buf.length = 0; renderPanel(); };
  panel.querySelector(".kbd-log-copy").onclick = () => {
    const text = buf.map(fmt).join("\n");
    navigator.clipboard?.writeText(text);
  };
  renderPanel();
}

function fmt(r) {
  const t = new Date(r.ts);
  const tm = t.toTimeString().slice(0, 8) + "." + String(t.getMilliseconds()).padStart(3, "0");
  const d = r.detail ? JSON.stringify(r.detail) : "";
  return `${tm} ${r.label}${d ? " " + d : ""}`;
}
function renderPanel() {
  if (!panel) return;
  const ul = panel.querySelector(".kbd-log-list");
  if (!ul) return;
  const show = buf.slice(-80);
  ul.innerHTML = show.map(r => `<li>${esc(fmt(r))}</li>`).join("");
  ul.scrollTop = ul.scrollHeight;
}
function esc(s) {
  return s.replace(/[<>&"']/g, c => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&#39;" }[c]));
}
