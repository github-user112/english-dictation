<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, Settings, audioEl, ensureAudio, playUrl, preloadAudio, playWord, sndRight, sndWrong, audioPlaying, todayNextStep, goTodayStep } from "../lib/core";
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
const wrongTask = ref(false);   // 今日错词回收任务：作答记入 daily_practice_log 的 wrong 桶
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
const fromToday = ref(false); // 今日动线入口带 from=today：打完跳下一关而不是下一课
const todayNext = ref(null);  // 今日动线的下一关（完成本关时拉取）
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
  fromToday.value = qs.get("from") === "today";
  wrongTask.value = qs.get("wrongtask") === "1";
  // 自定义练习（错词重练/易混词/自定义文章）：凭 URL 的 custom=1 认领 sessionStorage 里的题组。
  // 不删 dict_custom——刷新后同 URL 重新认领同一份题组；storage 被清（关标签页）则明确报错，
  // 不再退回普通会话（否则会按 list 参数莫名变成句子听打）
  const wantCustom = qs.get("custom") === "1";
  const c = wantCustom ? sessionStorage.getItem("dict_custom") : null;
  if (c) {
    items.value = JSON.parse(c);
    customLabel.value = sessionStorage.getItem("dict_custom_label") || "错词重练";
    custom.value = true;
  } else if (wantCustom) {
    error.value = "练习数据已失效，请返回重新发起";
    loading.value = false;
    return;
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
  if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") {   // 方向键移动格内光标，配合点击定位改中间的字
    ev.preventDefault();
    if (!retrying.value) cells.value?.moveCursor?.(ev.key === "ArrowLeft" ? -1 : 1);
    return;
  }
  if (ev.key === "Backspace") {
    ev.preventDefault();
    if (!retrying.value) {
      cells.value.backspace();
      saveInputSnapshot();
      submitIfCorrect();   // 删除后同样判对：修好末词应自动过关，与输入路径对称
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
  onCharInput(ev, typeChar, () => !submitted.value && !peeking.value, () => {
    // 与 onKey 的 Backspace 一致：判错红字保持期间不允许删除
    if (!retrying.value) { cells.value?.backspace(); saveInputSnapshot(); submitIfCorrect(); }
  });
}
function submitIfCorrect() {
  // 删除路径的自动过关：只对“改对了”负责，判错仍由 Enter/满格触发（词模式 isFull 语义不变）
  if (practiceMode.value !== "pure" && !submitted.value && cells.value?.isCorrect?.()) submit();
}
function typeChar(ch) {
  if (!cells.value || submitted.value) return;
  if (retrying.value) return;   // 判错后红色保持，按 Enter 才清空重输
  let wrong = false;
  if (mode.value === "sentence" && ch.length > 1 && cells.value.typeText) {
    // IME 组字/粘贴整句灌入：按词分发进格，错词标红留在原格，不会整句堵进第一格
    wrong = cells.value.typeText(ch);
  } else {
    for (const c of ch) {
      wrong = (mode.value === "word" ? cells.value.typeLetter(c) : cells.value.typeWordChar(c)) || wrong;
    }
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
  // 单词不预拉：有道 dictvoice 不返回缓存头，预拉=白下载两遍，播放时照样重新请求
  if (ni.kind === "word") return;
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
    list: item.value.list || list.value, id: item.value.id,
    mode: wrongTask.value ? "wrong" : practiceMode.value,
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
    // 今日动线来的：本关完成 → 自动串联下一关，不推进课次（错词回收虽走 custom 题组，同样是动线一关）
    if (fromToday.value && (!custom.value || wrongTask.value)) {
      finishTodayStep();
      return;
    }
    // 按课练习且还有下一课：提示后自动跳转；否则回今日动线（全站首页）
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
function goLists() { location.hash = "#/lists"; }
async function finishTodayStep() {
  lessonDone.value = true;
  // 此刻末题已保存，/api/today 已把本关标为完成；按五环顺序找下一关（本页路由区分听打/听写/错词回收）
  const stepKey = wrongTask.value ? "wrong"
    : location.hash.replace(/^#\/?/, "").split("?")[0] === "sentence" ? "sentence" : "dictation";
  todayNext.value = await todayNextStep(stepKey);
  if (!mounted) return;
  clearTimeout(nextTimer.value);
  nextTimer.value = setTimeout(goNextStep, 2500);
}
function goNextStep() { goTodayStep(todayNext.value); }
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
    <template v-if="fromToday">
      <div style="font-size:20px;font-weight:700;margin-bottom:8px;">{{ lesson ? `第 ${lessonRank(lesson)} 课完成！` : "本关完成！" }}</div>
      <p>{{ todayNext ? `即将进入下一关：${todayNext.title}…` : "今日五环全通，正在返回…" }}</p>
      <div class="controls" style="margin-top:14px;">
        <button class="btn primary big" @click="goNextStep">{{ todayNext ? "下一关 →" : "返回今日 →" }}</button>
        <button class="btn ghost" @click="goCatalog">返回今日动线</button>
      </div>
    </template>
    <template v-else>
      <div style="font-size:20px;font-weight:700;margin-bottom:8px;">第 {{ lessonRank(lesson) }} 课听打完成！</div>
      <p>即将自动进入第 {{ lessonRank(nextLessonNo) }} 课…</p>
      <div class="controls" style="margin-top:14px;">
        <button class="btn primary big" @click="goNextLesson">立即开始 →</button>
        <button class="btn ghost" @click="goLists">返回素材库</button>
      </div>
    </template>
  </div>
  <div v-else-if="error" class="empty" role="alert"><p>{{ error }}</p><button class="btn primary" @click="retryLoad">重试</button></div>
  <div v-else-if="loading" class="empty loading"><span class="spin" aria-hidden="true"></span><span class="load-text">加载中…</span></div>
  <div v-else-if="!items.length" class="empty">没有可练的词了，换个素材或明天再来</div>
  <div v-else class="practice" @pointerdown="focusCatch">

    <!-- 会话驾驶舱：模式切换 / 进度 / 作用域 + 速度 -->
    <div class="cockpit">
      <!-- 今日动线引导中隐藏模式切换：词/句是不同的关，由动线串联，词库也不同（nceN ↔ ncN） -->
      <div class="mode-tabs" v-if="!fromToday">
        <a class="mode-tab" :class="{ active: mode === 'word' }"
           :href="'#/word?list=' + encodeURIComponent(list) + '&amp;scope=' + encodeURIComponent(scope) + '&amp;mode=' + encodeURIComponent(practiceMode) + (lesson ? '&amp;lesson=' + lesson : '')">
          <span class="ic">🔤</span> 单词听打
        </a>
        <a class="mode-tab blue" :class="{ active: mode === 'sentence' }"
           :href="'#/sentence?list=' + encodeURIComponent(list) + '&amp;scope=' + encodeURIComponent(scope) + '&amp;mode=' + encodeURIComponent(practiceMode) + (lesson ? '&amp;lesson=' + lesson : '')">
          <span class="ic">💬</span> 句子听写
        </a>
      </div>
      <div class="progress-zone">
        <div class="pz-head">
          <span class="num">{{ prog }}<span v-if="custom" style="color:var(--yellow);">（{{ customLabel }}）</span><span v-else-if="mode==='word' && scope==='memorized'" style="color:var(--green);">（只看已背）</span></span>
          <span class="mini-bar" aria-hidden="true"><i :style="{ width: pbarWidth }"></i></span>
        </div>
        <div class="seg-bar" v-if="items.length <= 60" aria-hidden="true">
          <div v-for="(it, i) in items" :key="i" class="pseg"
               :class="{ ok: i < completedAtLoad && items[i].first_right !== false,
                         bad: i < completedAtLoad && items[i].first_right === false,
                         cur: i === completedAtLoad + cur }"></div>
        </div>
      </div>
      <div class="ctrl-cluster">
        <div class="seg-toggle" v-if="mode === 'word' && !custom">
          <button class="btn ghost sm" :class="{ active: scope === 'all' }" :aria-pressed="scope === 'all'" @click="scope !== 'all' && toggleScope()">全部</button>
          <button class="btn ghost sm" :class="{ active: scope === 'memorized' }" :aria-pressed="scope === 'memorized'" @click="scope !== 'memorized' && toggleScope()">已背</button>
        </div>
        <button class="speed-btn" aria-label="调节播放速度" @click="cycleSpeed"><span class="ic">🎚️</span> {{ speedLabel }}</button>
      </div>
    </div>

    <!-- 听打主舞台 -->
    <div class="arena" :class="{ 'err-state': retrying && !submitted }">
      <div id="arena-topbar"></div>
      <div class="arena-inner">

        <div class="arena-head">
          <div class="left">
            <span class="qnum"><span class="ic">🎯</span> 第 {{ completedAtLoad + cur + 1 }} 题</span>
            <span class="badge-soft blue mode-badge">
              <span class="ic">{{ practiceMode === 'pure' ? '🎧' : practiceMode === 'follow' ? '🎵' : '📝' }}</span>
              {{ practiceMode === 'pure' ? '纯听写' : practiceMode === 'follow' ? '跟打' : '辅助听写' }}
            </span>
          </div>
        </div>

        <div class="audio-row">
          <button class="btn" :class="{ playing: audioPlaying }" id="play-btn" aria-label="播放音频"
                  @mousedown.prevent @click="play">
            <span class="pulse-ring" aria-hidden="true"></span>
            <span v-if="audioPlaying" class="eq" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
            <template v-else>🔊</template>
          </button>
          <div class="audio-meta">
            <div class="status" :class="audioPlaying ? 'live' : 'idle'">
              <span class="dot"></span>
              {{ audioPlaying ? '正在听第 ' + (replayCount + 1) + ' 遍' : '点击按钮播放音频' }}
            </div>
            <div class="sub">
              <span><span class="ic">🔁</span> 自动重播 {{ Math.max(0, (settings.replayTimes ?? 2) - replayCount) }} 次</span>
              <span><span class="ic">⏲️</span> 间隔 {{ settings.replayInterval || 5 }}s</span>
              <span><span class="ic">🎚️</span> 速度 {{ speedLabel }}</span>
            </div>
            <div class="replay-dots">
              <span v-for="(d, k) in (settings.replayTimes ?? 2)" :key="k" class="replay-dot"
                    :class="{ on: k < replayCount }"></span>
              <span class="rdot-lbl">已重播 {{ replayCount }} 次</span>
            </div>
          </div>
        </div>

        <div class="info-line">
          <span id="phonetic">{{ practiceMode !== 'pure' && settings.showPhonetic && item.phonetic ? item.phonetic : '' }}</span>
          <span id="meaning">{{ practiceMode !== 'pure' && settings.showMeaning && item.meaning ? item.meaning : '' }}</span>
        </div>

        <div class="cells-section">
          <div class="cells-label">
            <span class="lbl">{{ mode === 'word' ? '🔤 逐字母输入' : '💬 逐词填格' }}</span>
            <span class="hint">{{ practiceMode === 'pure' ? '纯听写 · 无提示' : practiceMode === 'follow' ? '跟打 · 看答案打字' : '辅助听写 · 即时判分' }}</span>
          </div>
          <component :is="mode === 'word' ? WordCells : SentenceCells"
            ref="cells" :tokens="item" :submitted="submitted" :feedback="retrying || submitted"
            :practice-mode="practiceMode"></component>
        </div>

        <div class="peek-line" v-if="peeking && !submitted && !retrying && practiceMode !== 'follow'" aria-live="polite">
          <span class="peek-label">答案：</span><span class="peek-word">{{ item.text }}</span>
          <span class="peek-note">查看答案已记为答错</span>
        </div>
        <div class="follow-line" v-if="practiceMode === 'follow' && !submitted">{{ item.text }}</div>

        <div id="answer-line" class="feedback" :class="{ ok: submitted && lastRight, bad: retrying }" aria-live="polite">
          <span v-if="retrying" class="txt" style="color:var(--red);">✗ 答错了，答案：<span class="show-word">{{ item.text }}</span> · 按 Enter 重输</span>
          <span v-if="submitted && lastRight" class="txt">✔ 正确 · 即将进入下一题</span>
          <span v-if="saveError" class="save-error" role="alert">保存失败：{{ saveError }}</span>
        </div>

        <SpeechDrill v-if="mode === 'word' && (submitted || retrying)" :text="item.text"></SpeechDrill>

        <div class="controls">
          <button class="btn ghost" aria-label="重播音频" @mousedown.prevent @click="play"><span class="ic">↻</span> 重播</button>
          <button class="btn ghost" :disabled="saving" aria-label="跳过当前题目" @mousedown.prevent @click="skip"><span class="ic">⏭</span> 跳过</button>
          <button v-if="saveError && submitted" class="btn primary" :disabled="saving" @click="retrySave">重试保存</button>
          <button v-if="practiceMode === 'pure' && !retrying && !submitted" class="btn primary" :disabled="saving" aria-label="提交答案" @click="submit">提交答案</button>
        </div>

        <div class="hint">
          <span class="ic">💡</span>
          <span>打字输入 · 答对自动下一题 · 答错红色保持，按 Enter 重输直到正确 · Esc 重听 · 忘了拼写可按住 Alt 看答案（记为答错）· 自动重播间隔可在设置调整</span>
        </div>

      </div>
    </div>

    <input id="catch" ref="catchEl" autofocus autocomplete="off" autocorrect="off"
           autocapitalize="off" spellcheck="false" enterkeyhint="done"
           style="position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none;"
           @compositionstart="evCompStart" @compositionend="evCompEnd"
           @input="onInput" @blur="evBlurCatch">
  </div>
</template>
