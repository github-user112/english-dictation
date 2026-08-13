/* 核心工具：设置 / API / 音频 */

/* ---- 设置 ---- */
export const Settings = {
  KEY: "dict_settings",
  DEFAULTS: { showMeaning: true, showPhonetic: true, speed: 1.0, newPerDay: 10,
    practiceMode: "assisted", theme: "dark", replayInterval: 5, replayTimes: 2 },
  get() {
    try {
      const saved = JSON.parse(localStorage.getItem(this.KEY) || "{}");
      if (!saved.practiceMode && Object.prototype.hasOwnProperty.call(saved, "showWord")) {
        saved.practiceMode = saved.showWord ? "follow" : "assisted";
      }
      return Object.assign({}, this.DEFAULTS, saved);
    }
    catch { return { ...this.DEFAULTS }; }
  },
  set(p) {
    const v = Object.assign(this.get(), p);
    localStorage.setItem(this.KEY, JSON.stringify(v));
    document.documentElement.setAttribute("data-theme", v.theme);
  },
};

/* ---- URL uuid ---- */
export const User = {
  get() {
    const u = new URLSearchParams(location.search).get("u");
    return u || localStorage.getItem("dict_u") || "";
  },
  save(u) {
    localStorage.setItem("dict_u", u);
    if (!new URLSearchParams(location.search).get("u") && u) {
      const url = location.pathname + "?u=" + u + location.hash;
      history.replaceState(null, "", url);
    }
  },
};

/* ---- API ---- */
export async function api(path, opts = {}) {
  const sep = path.includes("?") ? "&" : "?";
  const url = "/api" + path + sep + "u=" + User.get();
  const r = await fetch(url, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
  });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || `请求失败 (${r.status})`);
  if (d.user) User.save(d.user);
  return d;
}

/* ---- 音频 ---- */
export const audioEl = new Audio();
audioEl.preload = "auto";

let actx = null;
function unlockActx() {
  if (!actx) {
    try { actx = new (window.AudioContext || window.webkitAudioContext)(); } catch { return; }
  }
  if (actx.state === "suspended") actx.resume().catch(() => {});
}
document.addEventListener("pointerdown", () => {
  audioEl.play().catch(() => {});
  unlockActx();
}, { passive: true, once: false });
document.addEventListener("keydown", unlockActx, { passive: true, once: false });

function beep(freq, dur, delay = 0) {
  if (!actx) return;
  if (actx.state === "suspended") actx.resume();
  const o = actx.createOscillator(), g = actx.createGain();
  o.type = "sine"; o.frequency.value = freq;
  g.gain.setValueAtTime(0.001, actx.currentTime + delay);
  g.gain.exponentialRampToValueAtTime(0.25, actx.currentTime + delay + 0.01);
  g.gain.exponentialRampToValueAtTime(0.001, actx.currentTime + delay + dur);
  o.connect(g).connect(actx.destination);
  o.start(actx.currentTime + delay);
  o.stop(actx.currentTime + delay + dur + 0.05);
}
export const sndRight = () => { beep(660, 0.09); beep(880, 0.12, 0.09); };
export const sndWrong = () => { beep(250, 0.13); beep(150, 0.3, 0.13); };

export function playUrl(url) {
  if (!url) return;
  audioEl.src = url;
  audioEl.playbackRate = Settings.get().speed;
  audioEl.play().catch(() => {});
}
export async function ensureAudio(item) {
  try {
    const r = await fetch(item.audio, { method: "HEAD" });
    if (r.ok) return item.audio;
  } catch (e) { /* 懒生成 */ }
  return (await api("/tts", { method: "POST", body: JSON.stringify({ text: item.text }) })).url;
}

/* ---- 工具 ---- */
export function es(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
