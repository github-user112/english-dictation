<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, Settings, audioEl, ensureAudio, playUrl, preloadAudio, playWord, preloadWord, sndRight, sndWrong, audioPlaying } from "../lib/core";
import { makeTapGuard, onBlurCatch, onCharInput, onCompEnd, onCompStart } from "../lib/input";
import WordCells from "./WordCells.vue";
import SentenceCells from "./SentenceCells.vue";
import SpeechDrill from "./SpeechDrill.vue";

const props = defineProps({ params: { type: Object, default: null } });

const list = ref("cet4");
const scope = ref("all");
const lesson = ref(null);
const practiceMode = ref(Settings.get().practiceMode);
const sessionId = ref("");
const quota = ref(null);
const items = ref([]);
const cur = ref(0);
const submitted = ref(false);
const lastRight = ref(false);
const retrying = ref(false);   // 本题答错，等待重输
const failed = ref(false);     // 本题是否错过（最终提交时告知后端）
const inputError = ref(false); // 当前尝试已播放过即时错误音
const peeking = ref(false);    // 正按住 Alt 查看答案（记为答错）
const firstRight = ref(null);
const attemptCount = ref(0);
const saving = ref(false);
const firstAttemptSent = ref(false);
const loading = ref(true);
const error = ref("");
const saveError = ref("");
const custom = ref(false);
const customLabel = ref("错词重练");
const audioCache = ref({});
const playToken = ref(0);
const replayTimer = ref(null);
const nextTimer = ref(null);
const focusTimers = ref([]);
const replayCount = ref(0);
const cells = ref(null);
const catchEl = ref(null);
const itemShownAt = ref(0);   // 当前题出现时刻，用于打字速度统计
const lessonList = ref([]);   // 本素材的课次表（按课练习时拉取，用于自动跳下一课）
const lessonDone = ref(false);// 本课打完，展示提示后自动跳下一课
let mounted = true;

function markItemShown() { itemShownAt.value = Date.now(); }

const speed = ref(Settings.get().speed);
const item = computed(() => items.value[cur.value]);
const mode = computed(() => (item.value && item.value.kind === "sentence") ? "sentence" : "word");
const completedAtLoad = ref(0);
const prog = computed(() => {
  if (!items.value.length) return "";
  if (sessionProgress.value?.total) return `${completedAtLoad.value + cur.value + 1} / ${sessionProgress.value.total}`;
  return `${cur.value + 1} / ${items.value.length}`;
});
const speedLabel = computed(() => speed.value.toFixed(2).replace(/0$/, "").replace(/\.0/, "") + "x");
const settings = computed(() => Settings.get());
const sessionProgress = ref(null);
// 课次表里的下一课（课号不一定连续，按表顺序取）
const nextLessonNo = computed(() => {
  const i = lessonList.value.findIndex((x) => x.lesson === lesson.value);
  return i >= 0 ? (lessonList.value[i + 1]?.lesson ?? null) : null;
});
// 展示用课号：课次表里的序号（nce1 词汇等素材课号是 1,3,5…，展示统一成 1,2,3…）
function lessonRank(no) {
  const i = lessonList.value.findIndex((x) => x.lesson === no);
  return i >= 0 ? i + 1 : no;
}
/* 判对后的停留节奏与卡片进度发丝线 */
const NEXT_DELAY_MS = 1100;
const pbarWidth = computed(() => {
  if (!items.value.length) return "0%";
  const done = completedAtLoad.value + cur.value + (submitted.value && lastRight.value ? 1 : 0);
  const total = sessionProgress.value?.total || items.value.length;
  return Math.min(100, Math.round((done / total) * 100)) + "%";
});

onMounted(async () => {
  const h = location.hash.replace(/^#\/?/, "").split("?");
  const qs = new URLSearchParams(h[1] || "");
  list.value = qs.get("list") || "cet4";
  scope.value = qs.get("scope") || (props.params?.get("scope") || "all");
  lesson.value = Number(qs.get("lesson") || props.params?.get("lesson")) || null;
  practiceMode.value = qs.get("mode") || props.params?.get("mode") || Settings.get().practiceMode;
  const c = sessionStorage.getItem("dict_custom");
  if (c) {
    items.value = JSON.parse(c);
    customLabel.value = sessionStorage.getItem("dict_custom_label") || "错词重练";
    sessionStorage.removeItem("dict_custom");
    sessionStorage.removeItem("dict_custom_label");
    custom.value = true;
  } else {
    try {
      await loadSession();
    } catch (err) {
      error.value = err.message || "练习任务加载失败";
      loading.value = false;
      return;
    }
    if (!mounted) return;
    // 按课练习：拉课次表，打完本课后自动跳下一课用
    if (lesson.value) {
      api(`/lessons?list=${encodeURIComponent(list.value)}`)
        .then((d) => { if (mounted) lessonList.value = d.lessons || []; })
        .catch(() => {});
    }
  }
  loading.value = false;
  if (items.value.length) {
    await nextTick();
    if (!mounted) return;
    restoreAttempt();
    restoreInputSnapshot();
    replayCount.value = 0;
    focusCatch();
    markItemShown();
    play();
  }
  focusTimers.value = [setTimeout(focusCatch, 150), setTimeout(focusCatch, 450)];
  document.addEventListener("pointerdown", onDocDown, true);
  window.addEventListener("keydown", onGlobalKey, true);
  window.addEventListener("keydown", onAltDown, true);
  window.addEventListener("keyup", onAltUp, true);
  window.addEventListener("blur", stopPeek);
});

onUnmounted(() => {
  mounted = false;
  playToken.value++;
  clearReplay();
  audioEl.pause();
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  for (const t of focusTimers.value) { clearTimeout(t); }
  focusTimers.value = [];
  document.removeEventListener("pointerdown", onDocDown, true);
  window.removeEventListener("keydown", onGlobalKey, true);
  window.removeEventListener("keydown", onAltDown, true);
  window.removeEventListener("keyup", onAltUp, true);
  window.removeEventListener("blur", stopPeek);
});

async function nextTick() { await new Promise((r) => setTimeout(r, 0)); }

function focusCatch() {
  const el = catchEl.value;
  if (el) {
    el.removeAttribute("readonly");
    try { el.focus({ preventScroll: true }); } catch { el.focus(); }
  }
}
// 练习页全程持键盘：点页面任何非交互位置都不收起软键盘
const onDocDown = makeTapGuard(focusCatch);
function evBlurCatch(ev) { onBlurCatch(catchEl.value, focusCatch); }
function evCompStart(ev) { onCompStart(ev, catchEl.value); }
function evCompEnd(ev) { onCompEnd(ev, catchEl.value, typeChar, () => !submitted.value && !peeking.value); }
function onGlobalKey(ev) {
  const t = ev.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) && t.id !== "catch") return;
  onKey(ev);
}
function onAltDown(ev) {
  if (ev.key !== "Alt") return;
  // Alt+Shift/AltGr 等组合键（如输入法切换）不当作偷看，也不拦截默认行为
  if (ev.shiftKey || ev.ctrlKey || ev.metaKey || ev.getModifierState?.("AltGraph")) return;
  ev.preventDefault();   // 防止松开 Alt 时触发浏览器菜单栏
  if (ev.repeat || peeking.value) return;
  startPeek();
}
function onAltUp(ev) {
  if (ev.key !== "Alt") return;
  ev.preventDefault();   // Firefox 的菜单栏激活挂在 Alt 松开时，需一并拦截
  peeking.value = false;
}
function stopPeek() { peeking.value = false; }
function startPeek() {
  if (!item.value || submitted.value || saving.value) return;
  // 跟打模式下答案本来就显示在输入框上方，Alt 偷看无从谈起，也不该记错
  if (practiceMode.value === "follow") return;
  peeking.value = true;
  // 偷看答案按答错计：首答记为错，与打错字母的判定一致
  if (!failed.value) {
    failed.value = true;
    if (firstRight.value === null) {
      firstRight.value = false;
      attemptCount.value = 1;
      if (sessionId.value && !firstAttemptSent.value) {
        firstAttemptSent.value = true;
        saveResult("attempt", false).catch(() => { firstAttemptSent.value = false; });
      }
    }
  }
}
function clearReplay() {
  if (replayTimer.value) { clearTimeout(replayTimer.value); replayTimer.value = null; }
  audioEl.onended = null;
}
function onKey(ev) {
  if (submitted.value) {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); next(); return; }
    return;
  }
  if (retrying.value && ev.key === "Enter") {
    ev.preventDefault();
    resetInput();
    return;
  }
  if (ev.key === "Enter") { ev.preventDefault(); submit(); return; }
  if (ev.key === "Escape") { clearReplay(); play(); return; }
  if (ev.key === "Backspace") {
    ev.preventDefault();
    if (!retrying.value) {
      cells.value.backspace();
      saveInputSnapshot();
    }
    return;
  }
  if (ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
    if (ev.isComposing) return;
    ev.preventDefault();
    typeChar(ev.key);
  }
}
function onInput(ev) {
  onCharInput(ev, typeChar, () => !submitted.value && !peeking.value);
}
function typeChar(ch) {
  if (!cells.value || submitted.value) return;
  if (retrying.value) return;   // 判错后红色保持，按 Enter 才清空重输
  let wrong = false;
  for (const c of ch) {
    wrong = (mode.value === "word" ? cells.value.typeLetter(c) : cells.value.typeWordChar(c)) || wrong;
  }
  saveInputSnapshot();
  if (wrong && practiceMode.value !== "pure") {
    inputError.value = true;
    sndWrong();
    if (firstRight.value === null) {
      firstRight.value = false;
      attemptCount.value = 1;
      if (sessionId.value && !firstAttemptSent.value) {
        firstAttemptSent.value = true;
        saveResult("attempt", false).catch(() => { firstAttemptSent.value = false; });
      }
    }
  }
  const done = mode.value === "word" ? cells.value.isFull() : cells.value.isCorrect();
  if (done && practiceMode.value !== "pure") submit();
}
function resetInput() {
  retrying.value = false;
  inputError.value = false;
  cells.value.reset();
  clearInputSnapshot();
  focusCatch();
}
async function play() {
  if (!item.value) return;
  clearReplay();
  const token = ++playToken.value;
  const playingItem = item.value;
  preloadNext();   // 当前音频加载的同时，提前拉取下一题音频
  if (token !== playToken.value || item.value !== playingItem) return;
  if (playingItem.kind === "word") {
    // 单词：前端直连有道真人音，失败回落后端音频
    playWord(playingItem, () => {
      if (token !== playToken.value || item.value !== playingItem || submitted.value) return;
      const s = Settings.get();
      if (replayCount.value < (s.replayTimes ?? 2)) {
        replayCount.value++;
        replayTimer.value = setTimeout(() => {
          if (token === playToken.value && item.value === playingItem) play();
        }, Math.max(1, s.replayInterval || 5) * 1000);
      }
    });
    return;
  }
  let url = audioCache.value[playingItem.text];
  if (!url) {
    url = await ensureAudio(playingItem);
    if (token !== playToken.value || item.value !== playingItem) return;
    audioCache.value[playingItem.text] = url;
  }
  if (token !== playToken.value || item.value !== playingItem) return;
  playUrl(url);
  audioEl.onended = () => {
    if (token !== playToken.value || item.value !== playingItem || submitted.value) return;
    const s = Settings.get();
    if (replayCount.value < (s.replayTimes ?? 2)) {
      replayCount.value++;
      replayTimer.value = setTimeout(() => {
        if (token === playToken.value && item.value === playingItem) play();
      }, Math.max(1, s.replayInterval || 5) * 1000);
    }
  };
}
async function preloadNext() {
  if (!mounted) return;
  const ni = items.value[cur.value + 1];
  if (!ni) return;
  if (ni.kind === "word") {
    preloadWord(ni);   // 单词：预拉取有道真人音
    return;
  }
  if (audioCache.value[ni.text]) return;
  ensureAudio(ni).then((u) => {
    if (mounted) audioCache.value[ni.text] = u;
    preloadAudio(u);
  }).catch(() => { /* 预拉取失败不影响，使用时再按需加载 */ });
}
async function submit() {
  if (saving.value || submitted.value) return;
  saveError.value = "";
  const right = cells.value.isCorrect();
  attemptCount.value++;
  playToken.value++;
  clearReplay();
  audioEl.pause();
  if (firstRight.value === null) firstRight.value = right;
  if (right) {
    const completedItem = item.value;
    const completedIndex = cur.value;
    const completedToken = playToken.value;
    cells.value.paint(true);
    sndRight();
    submitted.value = true;
    lastRight.value = true;
    retrying.value = false;
    saving.value = true;
    try {
      await saveResult("completed", true);
      if (!mounted || playToken.value !== completedToken || item.value !== completedItem ||
          cur.value !== completedIndex || !submitted.value) return;
    } catch (err) {
      saveError.value = err.message || "答案保存失败";
      return;
    } finally {
      saving.value = false;
    }
    failed.value = false;
    clearTimeout(nextTimer.value);
    nextTimer.value = setTimeout(() => next(), NEXT_DELAY_MS);
  } else {
    cells.value.markWrong();
    if (!inputError.value) sndWrong();
    inputError.value = false;
    lastRight.value = false;
    retrying.value = true;
    failed.value = true;
    if (attemptCount.value === 1 && sessionId.value && !firstAttemptSent.value) {
      firstAttemptSent.value = true;
      saving.value = true;
      try {
        await saveResult("attempt", false);
      } catch (err) {
        saveError.value = err.message || "首答保存失败，会在完成本题时重试";
      } finally { saving.value = false; }
    }
  }
}
async function saveResult(outcome, finalRight) {
  const ms = itemShownAt.value ? Math.max(200, Date.now() - itemShownAt.value) : undefined;
  // 词模式下附带实际敲入内容，供易混词挖掘（服务端截断到 64 字符）
  const typed = mode.value === "word" && cells.value?.answerText
    ? cells.value.answerText() : undefined;
  return api("/result", { method: "POST", body: JSON.stringify({
    session_id: sessionId.value || undefined,
    // 易混词特练/错词重练的条目自带真实来源列表，优先于页面级 list
    list: item.value.list || list.value, id: item.value.id, mode: practiceMode.value,
    first_right: firstRight.value, final_right: finalRight,
    attempt_count: attemptCount.value, outcome,
    right: finalRight, retried: firstRight.value === false,
    ms, typed,
  }) });
}
async function retrySave() {
  if (!submitted.value || saving.value) return;
  const completedItem = item.value;
  const completedIndex = cur.value;
  const completedToken = playToken.value;
  saving.value = true;
  saveError.value = "";
  try {
    await saveResult("completed", true);
    if (!mounted || playToken.value !== completedToken || item.value !== completedItem ||
        cur.value !== completedIndex || !submitted.value) return;
  } catch (err) {
    saveError.value = err.message || "答案保存失败";
    return;
  } finally {
    saving.value = false;
  }
  failed.value = false;
  clearTimeout(nextTimer.value);
  nextTimer.value = setTimeout(() => next(), NEXT_DELAY_MS);
}

async function loadSession() {
  const p = new URLSearchParams({ list: list.value, new: Settings.get().newPerDay,
    scope: scope.value, mode: practiceMode.value });
  if (lesson.value) p.set("lesson", lesson.value);
  const d = await api(`/session?${p}`);
  items.value = d.items || [];
  sessionId.value = d.session?.id || "";
  quota.value = d.quota || null;
  sessionProgress.value = d.progress || null;
  completedAtLoad.value = (d.progress?.completed || 0) + (d.progress?.skipped || 0);
}
function toggleScope() {
  if (custom.value || mode.value !== "word") return;
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  playToken.value++;
  clearReplay();
  audioEl.pause();
  scope.value = scope.value === "memorized" ? "all" : "memorized";
  loadSession().then(() => {
    if (!mounted) return;
    cur.value = 0;
    markItemShown();   // 重置后首题重新计时，避免把切换前的停留算进速度统计
    submitted.value = false;
    peeking.value = false;
    if (items.value.length) {
      replayCount.value = 0;
      resetAttempt();
      focusCatch();
      play();
    }
  }).catch((err) => {
    if (mounted) error.value = err.message || "练习任务加载失败";
  });
}
function next() {
  playToken.value++;
  clearReplay();
  audioEl.pause();
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  clearInputSnapshot();
  if (cur.value + 1 >= items.value.length) {
    // 按课练习且还有下一课：提示后自动跳转；否则回素材库
    if (!custom.value && lesson.value && nextLessonNo.value != null) {
      lessonDone.value = true;
      nextTimer.value = setTimeout(goNextLesson, 2000);
      return;
    }
    location.hash = "#/catalog";
    return;
  }
  cur.value++;
  markItemShown();
  submitted.value = false;
  retrying.value = false;
  failed.value = false;
  inputError.value = false;
  peeking.value = false;
  replayCount.value = 0;
  resetAttempt();
  setTimeout(() => {
    if (!mounted) return;
    restoreAttempt();
    restoreInputSnapshot();
    focusCatch();
    play();
  }, 130);
}
function goCatalog() { location.hash = "#/catalog"; }
function goNextLesson() {
  if (!mounted || nextLessonNo.value == null) return;
  localStorage.setItem(`dict_lesson_${list.value}`, String(nextLessonNo.value));
  const p = new URLSearchParams({ list: list.value, mode: practiceMode.value, lesson: nextLessonNo.value });
  if (scope.value !== "all") p.set("scope", scope.value);
  const page = mode.value === "sentence" ? "sentence" : "word";
  location.hash = `#/${page}?${p}`;   // hashKey 变化 → 组件重挂载，新课自动开始
}
function resetAttempt() {
  firstRight.value = null;
  attemptCount.value = 0;
  saving.value = false;
  firstAttemptSent.value = false;
  saveError.value = "";
}
async function skip() {
  if (saving.value) return;
  playToken.value++;
  clearReplay();
  audioEl.pause();
  if (firstRight.value === null) firstRight.value = false;
  attemptCount.value = Math.max(1, attemptCount.value);
  saving.value = true;
  try {
    await saveResult("skipped", false);
    if (mounted) next();
  }
  finally { saving.value = false; }
}
function snapshotKey() {
  return sessionId.value && item.value ? `dict_input:${sessionId.value}:${item.value.id}` : "";
}
function saveInputSnapshot() {
  const key = snapshotKey();
  if (key && cells.value?.serialize) sessionStorage.setItem(key, JSON.stringify(cells.value.serialize()));
}
function restoreInputSnapshot() {
  const key = snapshotKey();
  if (!key || !cells.value?.restore) return;
  try { cells.value.restore(JSON.parse(sessionStorage.getItem(key) || "null")); } catch { /* ignore */ }
}
function clearInputSnapshot() {
  const key = snapshotKey();
  if (key) sessionStorage.removeItem(key);
}
function restoreAttempt() {
  const first = item.value?.first_right;
  // 只恢复“不可覆盖”的首答统计（first_right / attempt_count），
  // 不还原上次的错误视觉：进入或切题时一律以干净的输入界面开始，
  // 红格与答案提示只在本次会话内真实答错时出现。
  firstRight.value = first === null || first === undefined ? null : Boolean(first);
  attemptCount.value = Number(item.value?.attempt_count) || 0;
  failed.value = first === false;
  retrying.value = false;
  firstAttemptSent.value = first !== null && first !== undefined;
}
function retryLoad() { location.reload(); }
function cycleSpeed() {
  const s = Settings.get();
  const next = s.speed === 0.75 ? 1.0 : s.speed === 1.0 ? 1.25 : 0.75;
  Settings.set({ speed: next });
  speed.value = next;
  audioEl.playbackRate = next;
  if (audioEl.src && !audioEl.paused) {
    audioEl.currentTime = 0;
    audioEl.play().catch(() => {});
  }
}
</script>

<template>
  <div v-if="lessonDone" class="empty" role="status">
    <div style="font-size:42px;" aria-hidden="true">🎉</div>
    <div style="font-size:20px;font-weight:700;margin-bottom:8px;">第 {{ lessonRank(lesson) }} 课听打完成！</div>
    <p>即将自动进入第 {{ lessonRank(nextLessonNo) }} 课…</p>
    <div class="controls" style="margin-top:14px;">
      <button class="btn primary big" @click="goNextLesson">立即开始 →</button>
      <button class="btn ghost" @click="goCatalog">返回素材库</button>
    </div>
  </div>
  <div v-else-if="error" class="empty" role="alert"><p>{{ error }}</p><button class="btn primary" @click="retryLoad">重试</button></div>
  <div v-else-if="loading" class="empty loading"><span class="spin" aria-hidden="true"></span><span class="load-text">加载中…</span></div>
  <div v-else-if="!items.length" class="empty">没有可练的词了，换个素材或明天再来</div>
  <div v-else @pointerdown="focusCatch">
    <div class="practice-top">
      <span class="progress-line">{{ prog }}<span v-if="custom" style="color:var(--yellow);">（{{ customLabel }}）</span><span v-else-if="mode==='word' && scope==='memorized'" style="color:var(--green);">（只看已背）</span><span class="mini-bar"><i :style="{ width: pbarWidth }"></i></span></span>
      <span class="badge mode-badge">{{ practiceMode === 'pure' ? '纯听写' : practiceMode === 'follow' ? '跟打' : '辅助听写' }}</span>
      <div class="scope-group" v-if="mode === 'word' && !custom">
        <button class="btn ghost sm" :class="{ active: scope === 'all' }" :aria-pressed="scope === 'all'" @click="scope !== 'all' && toggleScope()">全部</button>
        <button class="btn ghost sm" :class="{ active: scope === 'memorized' }" :aria-pressed="scope === 'memorized'" @click="scope !== 'memorized' && toggleScope()">已背</button>
      </div>
      <button class="btn ghost" aria-label="调节播放速度" @click="cycleSpeed">{{ speedLabel }}</button>
    </div>
    <div class="practice-card" :class="{ 'err-state': retrying && !submitted }">
      <div class="info-line">
        <span id="phonetic">{{ practiceMode !== 'pure' && settings.showPhonetic && item.phonetic ? item.phonetic : '' }}</span>
        <span id="meaning">{{ practiceMode !== 'pure' && settings.showMeaning && item.meaning ? item.meaning : '' }}</span>
      </div>
      <div class="cells-wrap">
        <component :is="mode === 'word' ? WordCells : SentenceCells"
          ref="cells" :tokens="item" :submitted="submitted" :feedback="retrying || submitted"
          :practice-mode="practiceMode"></component>
      </div>
      <div class="peek-line" v-if="peeking && !submitted && !retrying && practiceMode !== 'follow'" aria-live="polite">
        <span class="peek-label">答案：</span><span class="peek-word">{{ item.text }}</span>
        <span class="peek-note">查看答案已记为答错</span>
      </div>
      <div class="follow-line" v-if="practiceMode === 'follow' && !submitted">{{ item.text }}</div>
      <div id="answer-line" aria-live="polite">
        <span v-if="retrying" style="color:var(--red);">✗ 答错了，答案：<span class="show-word">{{ item.text }}</span> · 按 Enter 重输</span>
        <span v-if="submitted && lastRight">✔ 正确 · 即将进入下一题</span>
        <span v-if="saveError" class="save-error" role="alert">保存失败：{{ saveError }}</span>
      </div>
      <SpeechDrill v-if="mode === 'word' && (submitted || retrying)" :text="item.text"></SpeechDrill>
      <div class="controls">
        <button class="btn ghost" aria-label="重播音频" @mousedown.prevent @click="play">↻ 重播</button>
        <button class="btn ghost" :disabled="saving" aria-label="跳过当前题目" @mousedown.prevent @click="skip">跳过</button>
        <button v-if="saveError && submitted" class="btn primary" :disabled="saving" @click="retrySave">重试保存</button>
        <button v-if="practiceMode === 'pure' && !retrying && !submitted" class="btn primary" :disabled="saving" aria-label="提交答案" @click="submit">提交答案</button>
        <button class="btn primary big" :class="{ playing: audioPlaying }" id="play-btn" aria-label="播放音频" @mousedown.prevent @click="play"><span v-if="audioPlaying" class="eq" aria-hidden="true"><i></i><i></i><i></i><i></i></span><template v-else>🔊</template></button>
      </div>
      <div class="hint">打字输入 · 答对自动下一题 · 答错红色保持，按 Enter 重输直到正确 · Esc 重听 · 忘了拼写可按住 Alt 看答案（记为答错）· 自动重播间隔可在设置调整</div>
    </div>
    <input id="catch" ref="catchEl" autofocus autocomplete="off" autocorrect="off"
           autocapitalize="off" spellcheck="false" enterkeyhint="done"
           style="position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none;"
           @compositionstart="evCompStart" @compositionend="evCompEnd"
           @input="onInput" @blur="evBlurCatch">
  </div>
</template>
