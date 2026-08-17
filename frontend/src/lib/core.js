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

/* ---- 旧链接迁移 ---- */
export const User = {
  get() {
    return new URLSearchParams(location.search).get("u") || "";
  },
  clearLegacyLink() {
    if (!this.get()) return;
    history.replaceState(null, "", location.pathname + location.hash);
  },
};

function cookie(name) {
  const prefix = name + "=";
  return document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith(prefix))?.slice(prefix.length) || "";
}

/* ---- API ---- */
const API_TIMEOUT = 15000;  // 15 秒超时

export async function api(path, opts = {}) {
  const legacyUser = User.get();
  const sep = path.includes("?") ? "&" : "?";
  const url = "/api" + path + (legacyUser ? sep + "u=" + encodeURIComponent(legacyUser) : "");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.timeout || API_TIMEOUT);
  try {
    const r = await fetch(url, {
      ...opts,
      credentials: "same-origin",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": cookie("dict_csrf"),
        ...(opts.headers || {}),
      },
    });
    const text = await r.text();
    let d = {};
    if (text) {
      try { d = JSON.parse(text); }
      catch {
        throw new Error(r.ok ? "服务返回了无效响应" : `请求失败 (${r.status})`);
      }
    }
    if (legacyUser) User.clearLegacyLink();
    if (!r.ok) {
      const error = new Error(d.error || `请求失败 (${r.status})`);
      error.accountProtected = Boolean(d.account_protected);
      throw error;
    }
    return d;
  } catch (e) {
    if (e.name === "AbortError") throw new Error("请求超时，请检查网络");
    throw e;
  } finally {
    clearTimeout(timer);
  }
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
