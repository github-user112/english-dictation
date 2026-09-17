/* 跟读匹配分：移动端录音上传 /api/asr，桌面保留原生识别及服务端兜底。
   识别失败不产生结果；录音只在当前页面保留以便回放。 */
import { cookie } from "./core";

export function speechSupported() {
  return typeof window !== "undefined" &&
    (preferServerRecognition() ? serverSupported() :
      (Boolean(window.SpeechRecognition || window.webkitSpeechRecognition) || serverSupported()));
}

function serverSupported() {
  return Boolean(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== "undefined";
}

/* 原生识别遇到这些错误码说明这条路彻底走不通（不是没听清），自动回退服务端 */
const NATIVE_FATAL = new Set(["not-allowed", "service-not-allowed", "network", "language-not-supported"]);

function normalizeWord(s) {
  return String(s || "").toLowerCase().replace(/[^a-z]/g, "");
}

function levenshtein(a, b) {
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[b.length];
}

/* 把识别文本与目标词打分：0-100。
   命中整词 100 分；前缀包含按长度比给分（accept→accepting 记 67）；
   其余按编辑距离相似度取最接近的词。 */
export function scorePronunciation(target, heard) {
  const t = normalizeWord(target);
  const words = String(heard || "").toLowerCase()
    .replace(/[^a-z\s']/g, " ").split(/\s+/).filter(Boolean);
  if (!t || !words.length) return { score: 0, hit: null };
  if (words.includes(t)) return { score: 100, hit: t };
  let best = 0;
  let hit = null;
  for (const w of words) {
    let s;
    if (w.startsWith(t) || t.startsWith(w)) {
      s = Math.round((Math.min(w.length, t.length) / Math.max(w.length, t.length)) * 100);
    } else {
      const d = levenshtein(w, t);
      s = Math.round((1 - d / Math.max(w.length, t.length)) * 100);
    }
    if (s > best) { best = s; hit = w; }
  }
  return { score: Math.max(0, best), hit };
}

/* 取多候选识别结果里的最高分 */
export function bestAlternativeScore(target, transcripts) {
  let out = { score: 0, hit: null };
  for (const text of transcripts || []) {
    const r = scorePronunciation(target, text);
    if (r.score > out.score) out = r;
  }
  return out;
}

function wordsOf(s) {
  return String(s || "").toLowerCase().replace(/[^a-z\s]/g, " ").split(/\s+/).filter(Boolean);
}

/* 整句跟读打分：0-100。按词序列求编辑距离（漏词/多词/错词都计入），
   相似度 = 1 - 距离/较长词数。levenshtein 只用 length 与下标，词数组可直接复用。 */
export function scoreSentence(target, heard) {
  const t = wordsOf(target);
  const h = wordsOf(heard);
  if (!t.length || !h.length) return { score: 0, hit: null };
  const d = levenshtein(t, h);
  const score = Math.max(0, Math.round((1 - d / Math.max(t.length, h.length)) * 100));
  return { score, hit: h.join(" ") };
}

export function bestSentenceScore(target, transcripts) {
  let out = { score: 0, hit: null };
  for (const text of transcripts || []) {
    const r = scoreSentence(target, text);
    if (r.score > out.score) out = r;
  }
  return out;
}

export function preferServerRecognition() {
  // iPadOS 桌面 UA 也按移动设备处理；不依赖 SpeechRecognition 是否“存在”。
  return Boolean(navigator.userAgentData?.mobile) ||
    /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent) ||
    (/Macintosh/i.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
}

export function speechStateLabel(state) {
  return ({ requesting: "正在申请麦克风权限…", recording: "录音中…",
    encoding: "正在处理录音…", uploading: "上传中…",
    recognizing: "识别中…" })[state] || "准备好了";
}

export function speechErrorMessage(code) {
  return ({
    "not-allowed": "麦克风权限被拒：请在浏览器网站设置中允许麦克风，再点击跟读",
    "no-speech": "没听到清晰声音，请靠近麦克风重新录音（本次不计分）",
    "decode-failed": "录音解码失败，请重录；仍失败请换系统浏览器（本次不计分）",
    "recording-failed": "录音失败，请关闭其他占用麦克风的应用后重试",
    "audio-capture": "麦克风不可用，请检查设备或关闭占用麦克风的应用",
    "audio-too-long": "录音太长，请分成较短的句子重录",
    "service-busy": "识别服务忙，请稍后重试（本次不计分）",
    "rate-limited": "识别次数过于频繁，请稍后再试（本次不计分）",
    "service-unavailable": "语音识别服务暂不可用，请稍后再试",
    "upload-timeout": "录音上传超时，请检查网络后重试（本次不计分）",
    "asr-timeout": "语音识别超时，请稍后重试（本次不计分）",
    "network": "网络连接失败，请检查网络后重试（本次不计分）",
    "auth-failed": "会话验证失败，请刷新页面后重试",
    "unsupported": "当前浏览器无法录音，请使用 HTTPS 下的系统浏览器并允许麦克风",
    "start-failed": "语音识别未能启动，请点击跟读重试",
  })[code] || "语音识别失败，请重试（本次不计分）";
}

/* 调用方必须从按钮点击直接进入此函数，以保留麦克风权限请求的用户手势。 */
export function listenOnce(options = {}) {
  const { lang = "en-US", onResult, onError, onEnd, onFallback, onState } = options;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR || preferServerRecognition()) {
    if (serverSupported()) return listenServerOnce(options);
    onError?.("unsupported");
    return null;
  }
  let rec, fallback = null, handled = false, ended = false, nativeTimer = null;
  const end = () => { if (!ended) { ended = true; clearTimeout(nativeTimer); onEnd?.(); } };
  const startFallback = () => {
    handled = true;
    clearTimeout(nativeTimer);
    try { rec?.abort(); } catch { /* 已结束 */ }
    onFallback?.();
    fallback = listenServerOnce(options);
  };
  try {
    rec = new SR();
    rec.lang = lang;
    rec.interimResults = false;
    rec.maxAlternatives = 3;
    rec.onresult = (e) => {
      if (handled || ended) return;
      handled = true;
      const alts = Array.from(e.results[0] || [], (r) => r.transcript).filter((t) => t?.trim());
      if (alts.length) onResult?.(alts);
      else onError?.("no-speech");
      end();
    };
    rec.onerror = (e) => {
      if (handled || ended) return;
      if (NATIVE_FATAL.has(e.error) && serverSupported()) { startFallback(); return; }
      handled = true;
      onError?.(e.error);
      end();
    };
    rec.onend = () => {
      if (handled || ended) return;
      handled = true;
      onError?.("no-speech");
      end();
    };
    onState?.("recording");
    nativeTimer = setTimeout(() => {
      if (handled || ended) return;
      handled = true;
      try { rec.abort(); } catch { /* 已结束 */ }
      onError?.("asr-timeout");
      end();
    }, 30000);
    rec.start();
  } catch {
    if (serverSupported()) startFallback();
    else { handled = true; onError?.("start-failed"); end(); return null; }
  }
  return {
    get mode() { return fallback ? "server" : "native"; },
    abort() {
      handled = true;
      clearTimeout(nativeTimer);
      if (fallback) { fallback.abort(); return; }
      try { rec?.abort(); } catch { /* 已结束 */ }
      end();
    },
    finish() {
      if (fallback) fallback.finish();
      else if (!handled && !ended) { onState?.("recognizing"); try { rec.stop(); } catch { /* 已结束 */ } }
    },
  };
}

/* XMLHttpRequest 的 upload.load 表示请求体已发出。识别中指等待服务端结果，
   其中也可能包含网络/代理和服务端排队时间，不伪造服务端内部进度。 */
function uploadRecording(wav, { onState, onResult, onError, active, setRequest }) {
  const xhr = new XMLHttpRequest();
  setRequest(xhr);
  let uploaded = false;
  xhr.open("POST", "/api/asr");
  xhr.timeout = 30000;
  xhr.withCredentials = true;
  xhr.setRequestHeader("Content-Type", "audio/wav");
  xhr.setRequestHeader("X-CSRF-Token", cookie("dict_csrf"));
  xhr.upload.onload = () => {
    if (!active()) return;
    uploaded = true;
    onState?.("recognizing");
  };
  xhr.onerror = () => { if (active()) onError("network"); };
  xhr.ontimeout = () => { if (active()) onError(uploaded ? "asr-timeout" : "upload-timeout"); };
  xhr.onload = () => {
    if (!active()) return;
    let d = {};
    try { d = JSON.parse(xhr.responseText); } catch { /* nginx 非 JSON 错误页 */ }
    if (xhr.status < 200 || xhr.status >= 300) {
      const code = ({ 401: "auth-failed", 403: "auth-failed", 413: "audio-too-long",
        429: "service-busy", 503: "service-unavailable", 504: "asr-timeout" })[xhr.status];
      onError(d?.code || code || "asr-failed");
      return;
    }
    if (typeof d?.text !== "string") { onError("asr-failed"); return; }
    const text = d.text.trim();
    if (!text) onError("no-speech");
    else onResult([text]);
  };
  onState?.("uploading");
  xhr.send(wav);
}

/* 15s 硬上限；停止后立即关麦。取消对权限等待、解码和上传各阶段均有效。 */
export function listenServerOnce({ onResult, onError, onEnd, onState, onRecording } = {}) {
  let settled = false, recorder = null, stream = null, xhr = null;
  let maxTimer = null, decodeTimer = null, stopping = false;
  const stopTracks = () => stream?.getTracks().forEach((t) => t.stop());
  const finish_ = (cb, arg) => {
    if (settled) return;
    settled = true;
    clearTimeout(maxTimer);
    clearTimeout(decodeTimer);
    try { if (recorder && recorder.state !== "inactive") recorder.stop(); } catch { /* 已停 */ }
    stopTracks();
    cb?.(arg);
    onEnd?.();
  };
  const fail = (code) => finish_(onError, code);
  const stopRec = () => {
    if (settled || stopping || !recorder || recorder.state === "inactive") return;
    stopping = true;
    clearTimeout(maxTimer);
    onState?.("encoding");
    try { recorder.stop(); stopTracks(); } catch { fail("recording-failed"); }
  };
  const handle = {
    mode: "server",
    abort() {
      if (settled) return;
      finish_(null);
      try { if (recorder && recorder.state !== "inactive") recorder.stop(); } catch { /* 已停 */ }
      xhr?.abort();
    },
    finish: stopRec,
  };
  if (!serverSupported()) { fail("unsupported"); return handle; }
  onState?.("requesting");
  let permission;
  try { permission = navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) { fail(microphoneError(e)); return handle; }
  permission.then((s) => {
    if (settled) { s.getTracks().forEach((t) => t.stop()); return; }
    stream = s;
    const chunks = [];
    try {
      const mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"]
        .find((m) => MediaRecorder.isTypeSupported?.(m));
      recorder = new MediaRecorder(s, mime ? { mimeType: mime } : undefined);
      recorder.ondataavailable = (e) => { if (!settled && e.data.size) chunks.push(e.data); };
      recorder.onerror = () => fail("recording-failed");
      recorder.onstop = async () => {
        stopTracks();
        clearTimeout(maxTimer);
        if (settled) return;
        stopping = true;
        onState?.("encoding");
        const blob = new Blob(chunks, { type: recorder.mimeType });
        if (!blob.size) { fail("no-speech"); return; }
        onRecording?.(blob);
        let wav;
        decodeTimer = setTimeout(() => fail("decode-failed"), 15000);
        try { wav = await blobToWav16k(blob); }
        catch (e) { fail(e?.message === "no-speech" ? "no-speech" : "decode-failed"); return; }
        clearTimeout(decodeTimer);
        if (settled) return;
        try {
          uploadRecording(wav, { onState, onResult: (alts) => finish_(onResult, alts),
            onError: fail, active: () => !settled, setRequest: (r) => { xhr = r; } });
        } catch { fail("network"); }
      };
      recorder.start(250);
      onState?.("recording");
      maxTimer = setTimeout(stopRec, 15000);
    } catch { fail("recording-failed"); }
  }, (e) => fail(microphoneError(e)));
  return handle;
}

function microphoneError(e) {
  return ["NotAllowedError", "SecurityError"].includes(e?.name) ? "not-allowed" : "audio-capture";
}

/* 录制的 webm/mp4 → 16kHz 单声道 16bit WAV（Whisper 最稳的输入格式） */
async function blobToWav16k(blob) {
  const AC = window.AudioContext || window.webkitAudioContext;
  const actx = new AC();
  let decoded;
  try { decoded = await actx.decodeAudioData(await blob.arrayBuffer()); }
  finally { actx.close().catch(() => {}); }
  const rate = 16000;
  const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * rate)), rate);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start();
  let rendered;
  try { rendered = await off.startRendering(); }
  finally { try { off.close(); } catch { /* 旧内核无 close */ } }
  const samples = rendered.getChannelData(0);
  // 仅拦截近乎数字静音，不能把音量检测当作真正 VAD 或武断拒绝轻声朗读。
  let peak = 0;
  for (const sample of samples) peak = Math.max(peak, Math.abs(sample));
  if (samples.length < rate * 0.15 || peak < 0.0001) throw new Error("no-speech");
  return encodeWav(samples, rate);
}

function encodeWav(samples, sampleRate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const ws = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  ws(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); ws(8, "WAVEfmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  ws(36, "data"); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}
