/* 跟读打分：Web Speech API 语音识别 + 文本相似度评分（纯浏览器端，无后端） */

export function speechSupported() {
  return typeof window !== "undefined" &&
    Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
}

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

/* 单次聆听：recognition 生命周期包装，返回实例便于调用方 abort() */
export function listenOnce({ lang = "en-US", onResult, onError, onEnd } = {}) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    onError && onError("unsupported");
    return null;
  }
  const rec = new SR();
  rec.lang = lang;
  rec.interimResults = false;
  rec.maxAlternatives = 3;
  rec.onresult = (e) => {
    const alts = [];
    for (let i = 0; i < e.results[0].length; i++) alts.push(e.results[0][i].transcript);
    onResult && onResult(alts);
  };
  rec.onerror = (e) => onError && onError(e.error);
  rec.onend = () => onEnd && onEnd();
  // start 失败必须上报并返回 null，否则调用方会卡在"正在听…"状态
  try { rec.start(); } catch { onError && onError("start-failed"); return null; }
  return rec;
}
