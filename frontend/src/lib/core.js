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
    if (!r.ok) {
      // 失败时保留 URL 上的旧链接参数，重试时游客身份不丢
      const error = new Error(d.error || `请求失败 (${r.status})`);
      error.accountProtected = Boolean(d.account_protected);
      throw error;
    }
    if (legacyUser) User.clearLegacyLink();
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

// 静音音频元素：首次用户手势里播放一次以解锁自动播放策略。
// 不复用主播放元素，避免把用户刚暂停的音频"复活"。
let mediaUnlocked = false;
let blockedOnce = false;   // 当前音频的自动播放被浏览器拦截，等首次手势补播
const UNLOCK_WAV = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAACAgICA";

function markBlocked(error) {
  if (error && error.name === "NotAllowedError") blockedOnce = true;
}

function unlockMedia() {
  if (!mediaUnlocked) {
    mediaUnlocked = true;
    try {
      const el = new Audio(UNLOCK_WAV);
      el.muted = true;
      const p = el.play();
      if (p && p.catch) p.catch(() => {});
    } catch { /* 解锁失败不影响正常播放 */ }
  }
  // 页面加载后的首次自动播放可能被策略拦截；首次手势时补播当前音频
  if (blockedOnce && audioEl.src) {
    blockedOnce = false;
    audioEl.play().catch(() => {});
  }
}
document.addEventListener("pointerdown", () => { unlockActx(); unlockMedia(); }, { passive: true });
document.addEventListener("keydown", () => { unlockActx(); unlockMedia(); }, { passive: true });

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
// 连击音：连击数越高音调越高，封顶避免刺耳
export const sndCombo = (combo) => {
  const step = Math.min(combo, 12);
  beep(520 + step * 45, 0.07);
  beep(780 + step * 45, 0.1, 0.07);
};

export function playUrl(url) {
  if (!url) return;
  blockedOnce = false;
  audioEl.src = url;
  audioEl.playbackRate = Settings.get().speed;
  audioEl.play().catch(markBlocked);
}

// 预加载音频字节：用隐藏 Audio 提前拉取，播放时命中 HTTP 缓存，秒开
let preloadEl = null;
export function preloadAudio(url) {
  if (!url) return;
  try {
    if (!preloadEl) {
      preloadEl = new Audio();
      preloadEl.preload = "auto";
      preloadEl.muted = true;
    }
    if (preloadEl.src !== url) {
      preloadEl.src = url;
      preloadEl.load();
    }
  } catch { /* 预加载失败不影响正常播放 */ }
}

// 路由切换时取消当前语音。清空 src 也会中止尚在加载中的媒体请求，
// 防止离开练习页后仍继续播放。
export function stopAudio() {
  audioEl.onended = null;
  audioEl.onerror = null;
  blockedOnce = false;
  audioEl.pause();
  try { audioEl.currentTime = 0; } catch { /* 尚未加载元数据时可忽略 */ }
  audioEl.removeAttribute?.("src");
  audioEl.load?.();
}
export async function ensureAudio(item) {
  // 自定义文章等素材 audio 为空串：fetch("") 会 HEAD 到页面自身并因 200 误判可用，
  // 导致永远不回落 TTS；必须先排除空值
  if (item.audio) {
    try {
      const r = await fetch(item.audio, { method: "HEAD" });
      if (r.ok) return item.audio;
    } catch (e) { /* 懒生成 */ }
  }
  return (await api("/tts", { method: "POST", body: JSON.stringify({ text: item.text }) })).url;
}

/* ---- 有道真人读音：前端直连，失败回落后端音频 ---- */
export const YOUDAO_BASE = "https://dict.youdao.com/dictvoice";
const youdaoFailed = new Set();  // 本次会话内已确认有道不可用的单词，后续直接走后端

export function wordAudioUrl(text, type = 2) {
  return `${YOUDAO_BASE}?audio=${encodeURIComponent(text)}&type=${type}`;
}

// 播放单词真人音：优先有道，加载/解码失败则回落 item.audio（后端音频）
export function playWord(item, onended = null) {
  if (!item) return;
  blockedOnce = false;
  audioEl.playbackRate = Settings.get().speed;
  audioEl.onended = onended;
  if (youdaoFailed.has(item.text)) {
    audioEl.src = item.audio;
    audioEl.play().catch(markBlocked);
    return;
  }
  audioEl.onerror = () => {
    audioEl.onerror = null;
    youdaoFailed.add(item.text);
    audioEl.src = item.audio;
    audioEl.play().catch(markBlocked);
  };
  audioEl.src = wordAudioUrl(item.text);
  audioEl.play().catch(markBlocked);
}

// 预加载单词真人音（失败回落后端音频）
export function preloadWord(item) {
  if (!item) return;
  preloadAudio(youdaoFailed.has(item.text) ? item.audio : wordAudioUrl(item.text));
}
