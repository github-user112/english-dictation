<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, audioEl, ensureAudio, playUrl, preloadAudio, playWord, sndRight, sndWrong, audioPlaying } from "../lib/core";
import { makeTapGuard, onBlurCatch, onCharInput, onCompEnd, onCompStart } from "../lib/input";
import WordCells from "./WordCells.vue";

const props = defineProps({ params: { type: Object, default: null } });

const list = ref("cet4");
const lesson = ref(null);            // 按课背诵时的课号（今日动线入口带入）
const reviewAll = ref(false);        // 已学课重学：整课重出，不按已背过滤
const fromToday = ref(false);        // 今日动线入口带 from=today：透传给听打，打完跳下一关
const phase = ref("learn");            // learn | quiz | done
const items = ref([]);                 // 全部任务
const queue = ref([]);                 // 自测队列
const cur = ref(null);
const flipped = ref(false);
const submitted = ref(false);
const lastRight = ref(false);
const retrying = ref(false);          // 自测答错已亮答案，等待照着重打（不换题）
const lastNote = ref("");
const loading = ref(true);
const cells = ref(null);
const catchEl = ref(null);
const audioCache = ref({});
const playToken = ref(0);
const nextTimer = ref(null);
const focusTimers = ref([]);
const quizRound = ref(0);
const stat = ref({ right: 0, wrong: 0, memorized: 0 });
const learnIndex = ref(0);            // 学习态当前索引（用于恢复）
const attemptId = ref("");
const saveError = ref("");
const saving = ref(false);
const error = ref("");
let mounted = true;

const prog = computed(() => "剩余 " + (queue.value.length + (cur.value && phase.value === "quiz" ? 1 : 0)));
const learnTotal = computed(() => items.value.length);

/* ---- 进度环百分比 ---- */
const ringPct = computed(() => {
  if (!learnTotal.value) return 0;
  return Math.round(((learnIndex.value + (flipped.value ? 1 : 0)) / learnTotal.value) * 100);
});
const ringOffset = computed(() => 100 - ringPct.value);
const doneCount = computed(() => learnIndex.value + (flipped.value ? 1 : 0));
const correctPct = computed(() => {
  const total = stat.value.right + stat.value.wrong;
  return total ? Math.round((stat.value.right / total) * 100) : 0;
});

const SS_KEY = "dict_memorize";

function saveState() {
  if (!items.value.length) return;
  try {
    sessionStorage.setItem(SS_KEY, JSON.stringify({
      list: list.value, lesson: lesson.value, review: reviewAll.value, phase: phase.value, items: items.value,
      queue: queue.value, cur: cur.value, stat: stat.value,
      submitted: submitted.value, lastRight: lastRight.value, lastNote: lastNote.value,
      retrying: retrying.value,
      attemptId: attemptId.value, saveError: saveError.value,
      quizRound: quizRound.value, learnIndex: learnIndex.value,
    }));
  } catch { /* ignore quota */ }
}

function loadState() {
  try {
    const raw = sessionStorage.getItem(SS_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch { return null; }
}

function clearState() {
  sessionStorage.removeItem(SS_KEY);
}

function newAttemptId() {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? uuid.replaceAll("-", "") : `${Date.now()}${Math.random().toString(36).slice(2)}`;
}

onMounted(() => {
  init().catch((err) => {
    error.value = err.message || "背词任务加载失败";
    loading.value = false;
  });
});

async function init() {
  list.value = props.params?.get("list") || "cet4";
  lesson.value = Number(props.params?.get("lesson")) || null;
  reviewAll.value = props.params?.get("review") === "1";
  fromToday.value = props.params?.get("from") === "today";
  const saved = loadState();
  if (saved && saved.list === list.value && (saved.lesson || null) === lesson.value
      && Boolean(saved.review) === reviewAll.value && saved.items?.length) {
    // 恢复刷新前的进度
    items.value = saved.items;
    queue.value = saved.queue || [];
    cur.value = saved.cur;
    phase.value = saved.phase || "learn";
    stat.value = saved.stat || { right: 0, wrong: 0, memorized: 0 };
    submitted.value = Boolean(saved.submitted);
    lastRight.value = Boolean(saved.lastRight);
    retrying.value = Boolean(saved.retrying);
    lastNote.value = saved.lastNote || "";
    attemptId.value = saved.attemptId || newAttemptId();
    saveError.value = saved.saveError || "";
    quizRound.value = saved.quizRound || 0;
    learnIndex.value = saved.learnIndex || 0;
    loading.value = false;
    if (cur.value && phase.value !== "done") {
      await nextTick();
      if (!mounted) return;
      play();
    }
  } else {
    const n = Number(props.params?.get("n")) || 0;
    const d = await api(`/memorize/session?list=${list.value}`
      + (n >= 1 && n <= 100 ? `&n=${n}` : "")
      + (lesson.value ? `&lesson=${lesson.value}` : "")
      + (reviewAll.value ? "&review=1" : ""));
    if (!mounted) return;
    items.value = d.items || [];
    queue.value = [...items.value];
    loading.value = false;
    if (queue.value.length) {
      cur.value = queue.value[0];
      queue.value.shift();
      attemptId.value = newAttemptId();
      play();
    }
    saveState();
  }
  forceFocus();
  document.addEventListener("pointerdown", onDocDown, true);
  window.addEventListener("keydown", onGlobalKey, true);
}

onUnmounted(() => {
  mounted = false;
  playToken.value++;
  audioEl.pause();
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  for (const t of focusTimers.value) { clearTimeout(t); }
  focusTimers.value = [];
  document.removeEventListener("pointerdown", onDocDown, true);
  window.removeEventListener("keydown", onGlobalKey, true);
});

async function nextTick() { await new Promise((r) => setTimeout(r, 0)); }

function focusCatch() {
  if (phase.value !== "quiz") return;   // 学习态/结束态不需要键盘，别唤起软键盘
  const el = catchEl.value;
  if (el) {
    el.removeAttribute("readonly");
    try { el.focus({ preventScroll: true }); } catch { el.focus(); }
  }
}
function forceFocus() {
  if (focusTimers.value.length) return;
  focusTimers.value = [setTimeout(focusCatch, 150), setTimeout(focusCatch, 450)];
}
// 仅自测态需要持键盘：学习态/done 态点页面不应唤起软键盘
const onDocDown = makeTapGuard(focusCatch, () => phase.value === "quiz");
function evBlurCatch(ev) { onBlurCatch(catchEl.value, focusCatch); }
function evCompStart(ev) { onCompStart(ev, catchEl.value); }
function evCompEnd(ev) { onCompEnd(ev, catchEl.value, typeChar, () => !submitted.value); }
function onGlobalKey(ev) {
  const t = ev.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) && t.id !== "catch") return;
  onKey(ev);
}

function onKey(ev) {
  if (phase.value === "learn") {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      if (!flipped.value) flip();
      else learnNext();
    }
    return;
  }
  if (phase.value !== "quiz") return;
  if (submitted.value) {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      if (saveError.value) retrySave();
      else if (retrying.value) retryInput();   // 答错：Enter 清空重打，不跳题
      else quizNext();
      return;
    }
    return;
  }
  if (ev.key === "Enter") {
    ev.preventDefault();
    if (retrying.value && !(cells.value && cells.value.isFull())) return;   // 重打没打完不提交
    submit();
    return;
  }
  if (ev.key === "Backspace") {
    ev.preventDefault();
    cells.value.backspace();
    return;
  }
  if (ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
    if (ev.isComposing) return;
    ev.preventDefault();
    typeChar(ev.key);
  }
}

async function play() {
  if (!cur.value) return;
  const token = ++playToken.value;
  const playingItem = cur.value;
  preloadNext();
  if (token !== playToken.value || cur.value !== playingItem) return;
  if (playingItem.kind === "word") {
    // 单词：前端直连有道真人音，失败回落后端音频
    playWord(playingItem);
    return;
  }
  let url = audioCache.value[playingItem.text];
  if (!url) {
    url = await ensureAudio(playingItem);
    if (token !== playToken.value || cur.value !== playingItem) return;
    audioCache.value[playingItem.text] = url;
  }
  if (token !== playToken.value || cur.value !== playingItem) return;
  playUrl(url);
}

// 播放当前的同时，预加载下一个（学习态下一句 / 自测队列第一题）
function preloadNext() {
  if (!mounted) return;
  let ni = null;
  if (phase.value === "learn") {
    ni = items.value[learnIndex.value + 1];
  } else if (phase.value === "quiz") {
    ni = queue.value[0] || null;
  }
  if (!ni) return;
  // 单词不预拉：有道 dictvoice 不返回缓存头，预拉=白下载两遍，播放时照样重新请求
  if (ni.kind === "word") return;
  if (audioCache.value[ni.text]) return;
  ensureAudio(ni).then((u) => {
    if (!mounted) return;
    audioCache.value[ni.text] = u;
    preloadAudio(u);
  }).catch(() => { /* 预拉取失败不影响，使用时再按需加载 */ });
}

/* ---- 学习态 ---- */
function flip() {
  if (phase.value !== "learn") return;
  playToken.value++;
  flipped.value = !flipped.value;
  if (flipped.value) audioEl.pause();
}
function learnNext() {
  playToken.value++;
  audioEl.pause();
  flipped.value = false;
  const idx = items.value.indexOf(cur.value);
  if (idx < items.value.length - 1) {
    learnIndex.value = idx + 1;
    cur.value = items.value[idx + 1];
    play();
    saveState();
  } else {
    startQuiz();
  }
}
function startQuiz() {
  playToken.value++;
  audioEl.pause();
  quizRound.value++;
  phase.value = "quiz";
  flipped.value = false;
  if (queue.value.length) {
    cur.value = queue.value[0];
    queue.value.shift();
    play();
    nextTick().then(() => { focusCatch(); });
  }
  saveState();
}

/* ---- 自测态 ---- */
function typeChar(ch) {
  if (!cells.value || submitted.value) return;
  for (const c of ch) cells.value.typeLetter(c);
  if (cells.value.isFull()) submit();
}
function onInput(ev) {
  onCharInput(ev, typeChar, () => !submitted.value, () => cells.value?.backspace());
}
async function persistAnswer(right) {
  saving.value = true;
  saveError.value = "";
  try {
    return await api("/memorize", {
      method: "POST",
      body: JSON.stringify({ list: list.value, id: cur.value.id, right, attempt_id: attemptId.value }),
    });
  } catch (err) {
    saveError.value = err.message || "保存失败";
    saveState();
    return null;
  } finally {
    saving.value = false;
  }
}

function finishAnswer(right, result) {
  if (right) {
    sndRight();
    stat.value.right++;
    retrying.value = false;
    if (result.memorized) {
      stat.value.memorized++;
      lastNote.value = "✔ 已背过！";
    } else {
      lastNote.value = "✔ 对了，待会再确认一遍";
      queue.value.push({ ...cur.value });
    }
    lastRight.value = true;
    saveState();
    clearTimeout(nextTimer.value);
    nextTimer.value = setTimeout(() => quizNext(), 900);
  } else {
    sndWrong();
    stat.value.wrong++;
    lastNote.value = "✗ 记错了——照答案重打，本轮还会再考它";
    lastRight.value = false;
    retrying.value = true;   // 答错留在本题：亮答案，照着重打
    saveState();
  }
}

async function submit() {
  if (submitted.value) return;
  const right = cells.value.isCorrect();
  playToken.value++;
  audioEl.pause();
  submitted.value = true;
  lastRight.value = right;
  if (right) cells.value.paint(true);
  else cells.value.markWrong();
  saveState();
  const result = await persistAnswer(right);
  if (!mounted || !result) return;
  finishAnswer(right, result);
}

async function retrySave() {
  if (!submitted.value || saving.value) return;
  const result = await persistAnswer(lastRight.value);
  if (!mounted || !result) return;
  finishAnswer(lastRight.value, result);
}
function retryInput() {
  // 答错后照答案重打：清空重输、不换题；换新 attemptId，纠正后的保存才不会被判成重复请求
  retrying.value = true;
  submitted.value = false;
  attemptId.value = newAttemptId();
  cells.value?.reset();
  saveState();
  focusCatch();
}
function quizNext() {
  if (saving.value) return;
  playToken.value++;
  audioEl.pause();
  quizRound.value++;
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  submitted.value = false;
  retrying.value = false;
  lastNote.value = "";
  saveError.value = "";
  if (!queue.value.length) {
    phase.value = "done";
    clearState();
    return;
  }
  cur.value = queue.value[0];
  queue.value.shift();
  attemptId.value = newAttemptId();
  saveState();
  play();
  nextTick().then(() => { focusCatch(); });
}
function redo() {
  clearState();
  location.reload();
}
function goDictation() {
  // 按课模式透传 lesson（听打按课走，scope 参数被忽略）；否则维持"只看已背"
  const q = new URLSearchParams({ list: list.value });
  if (lesson.value) q.set("lesson", lesson.value);
  else q.set("scope", "memorized");
  if (fromToday.value) q.set("from", "today");
  window.location.hash = `#/word?${q}`;
}
function goCatalog() { window.location.hash = "#/catalog"; }
</script>

<template>
  <div v-if="error" class="empty" role="alert"><p>{{ error }}</p><button class="btn primary" @click="redo">重试</button></div>
  <div v-else-if="loading" class="empty loading"><span class="spin" aria-hidden="true"></span><span class="load-text">加载中…</span></div>
  <div v-else-if="!items.length" class="empty">
    <p>本轮没有要背的词（已背的词 7 天内会回来复习）</p>
    <div class="controls" style="margin-top:16px;">
      <button class="btn primary" @click="goDictation">{{ lesson ? "去听打本课单词" : "去听打（只看已背）" }}</button>
      <button class="btn ghost" @click="goCatalog">返回素材库</button>
    </div>
  </div>

  <div v-else class="mem-page">

    <!-- ===== Session header ===== -->
    <div class="mem-sess">
      <div class="mem-sess-body">
        <div v-if="phase === 'learn'" class="mem-sess-eyebrow"><span class="pulse-dot" aria-hidden="true"></span> 第 {{ lesson || '—' }} 课 · 英→中 翻卡学习</div>
        <div v-else-if="phase === 'quiz'" class="mem-sess-eyebrow" style="background:var(--blue);box-shadow:0 2px 0 var(--blue-dark);"><span class="pulse-dot" aria-hidden="true"></span> 自测中 · 中→英 拼写</div>
        <div v-else class="mem-sess-eyebrow" style="background:var(--gold);color:#7a5c00;box-shadow:0 2px 0 var(--gold-dark);">🏆 本轮完成</div>
        <div class="mem-sess-title">📖 {{ phase === 'learn' ? '英→中 翻卡学习' : phase === 'quiz' ? '中→英 拼写自测' : '本轮完成 🎉' }}</div>
        <div class="mem-sess-meta">
          <span>📚 本课 <b>{{ learnTotal }}</b> 词</span>
          <span class="sep">·</span>
          <span style="color:var(--blue-dark);">🎯 正确率 <b>{{ correctPct }}%</b></span>
          <span v-if="phase === 'learn'" class="sep">·</span>
          <span v-if="phase === 'learn'" style="color:var(--text-dim);">📖 进度 <b>{{ doneCount }}/{{ learnTotal }}</b></span>
        </div>
      </div>
      <div v-if="phase === 'learn'" class="mem-ring-wrap">
        <svg viewBox="0 0 36 36">
          <circle class="mem-ring-bg" cx="18" cy="18" r="15.9155" pathLength="100"/>
          <circle class="mem-ring-fg" cx="18" cy="18" r="15.9155" pathLength="100" :style="{ strokeDashoffset: ringOffset }"/>
        </svg>
        <div class="mem-ring-center">
          <span class="mem-ring-pct">{{ ringPct }}%</span>
          <span class="mem-ring-sub">{{ doneCount }}/{{ learnTotal }} 词</span>
        </div>
      </div>
    </div>

    <!-- ===== Phase strip ===== -->
    <div class="mem-phase">
      <div class="mem-phase-step" :class="{ active: phase === 'learn', done: phase !== 'learn' }">
        <span class="step-ic">📖</span> 学习
      </div>
      <div class="mem-phase-conn"></div>
      <div class="mem-phase-step" :class="{ active: phase === 'quiz', done: phase === 'done', locked: phase === 'learn' }">
        <span class="step-ic">📝</span> 自测
      </div>
      <div class="mem-phase-conn"></div>
      <div class="mem-phase-step" :class="{ active: phase === 'done', locked: phase !== 'done' }">
        <span class="step-ic">🏆</span> 完成
      </div>
    </div>

    <!-- ===== Learn phase ===== -->
    <template v-if="phase === 'learn'">
      <div class="mem-main">
        <div class="mem-left">
          <div class="flash-card" :key="cur.text" :class="{ flipped }" role="button" aria-label="点击翻面查看释义" tabindex="0" @click="flip">
            <Transition name="pop" mode="out-in">
              <div class="face front" :key="'f-'+cur.text">
                <div class="fw">{{ cur.text }}</div>
                <div class="fp">{{ cur.phonetic }}</div>
              </div>
            </Transition>
            <Transition name="pop" mode="out-in">
              <div class="face back" :key="'b-'+cur.text">
                <div class="fm">{{ cur.meaning }}</div>
              </div>
            </Transition>
          </div>
          <div class="mem-learn-controls">
            <button class="btn ghost" :class="{ playing: audioPlaying }" aria-label="播放发音" @mousedown.prevent @click="play">🔊 发音</button>
            <button class="btn primary big" @mousedown.prevent @click="learnNext">{{ items.indexOf(cur) === items.length - 1 ? '开始自测 →' : '下一个 →' }}</button>
          </div>
          <div class="mem-learn-hint">点击卡片翻面 · 记住拼写后开始自测</div>
        </div>
        <div class="mem-sidebar">
          <div class="mem-acc-hero">
            <div class="mem-ah-label">🎯 当前正确率</div>
            <div class="mem-ah-val">{{ correctPct }}%</div>
            <div class="mem-ah-sub">{{ stat.right }} 知道 · {{ stat.wrong }} 不认识</div>
          </div>
          <div class="mem-stats-mini">
            <div class="mem-stat-box">
              <div class="mem-stat-val" style="color:var(--green);">✓ {{ stat.memorized }}</div>
              <div class="mem-stat-lbl">已掌握</div>
            </div>
            <div class="mem-stat-box">
              <div class="mem-stat-val" style="color:var(--blue);">📖 {{ learnTotal - doneCount }}</div>
              <div class="mem-stat-lbl">剩余</div>
            </div>
          </div>
          <div class="card" style="margin-top:0;">
            <button class="btn ghost btn-full" aria-label="跳过学习，直接自测" @click="startQuiz">跳过学习，直接自测 →</button>
          </div>
        </div>
      </div>
    </template>

    <!-- ===== Quiz phase ===== -->
    <div v-else-if="phase === 'quiz'" class="mem-quiz-wrap" @pointerdown="focusCatch">
      <div class="practice-card">
        <div class="mem-quiz-meaning">
          <div class="mem-quiz-meaning-label">🇨🇳 中文释义</div>
          <div class="mem-quiz-meaning-text" id="meaning">{{ cur.meaning }}</div>
        </div>
        <div class="cells-wrap">
          <WordCells ref="cells" :key="quizRound" :tokens="cur" :submitted="submitted"></WordCells>
        </div>
        <div id="answer-line" aria-live="polite">
          <span v-if="retrying && !submitted" class="show-word">✍️ 照答案重打一遍：<b>{{ cur.text }}</b></span>
          <template v-else-if="submitted">
            <span v-if="!lastRight" class="show-word">✗ 答案：{{ cur.text }}<span v-if="cur.phonetic"> · {{ cur.phonetic }}</span> · 按 Enter 重输</span>
            <span v-if="lastRight" class="mem-note">{{ lastNote }}</span>
          </template>
        </div>
        <div class="mem-quiz-controls">
          <div v-if="saveError" class="mem-save-error" role="alert">保存失败：{{ saveError }}</div>
          <button class="btn primary big" :disabled="saving" @mousedown.prevent @click="saveError ? retrySave() : retrying ? retryInput() : submitted ? quizNext() : submit()">{{ saveError ? '重试保存' : retrying ? '重输一次' : submitted ? '继续' : '提交' }}</button>
          <button class="btn ghost" :class="{ playing: audioPlaying }" aria-label="播放发音" @mousedown.prevent @click="play">🔊 听发音</button>
        </div>
        <div class="mem-quiz-hint">看中文，打英文 · 答对自动下一题（自动发音）· 答错不可跳过，照答案重打 · 连对 2 次才算背过</div>
      </div>
      <div class="mem-phase" style="margin-top:16px;">
        <div class="mem-phase-step done"><span class="step-ic">📖</span> 学习</div>
        <div class="mem-phase-conn"></div>
        <div class="mem-phase-step active"><span class="step-ic">📝</span> 自测</div>
        <div class="mem-phase-conn"></div>
        <div class="mem-phase-step locked"><span class="step-ic">🏆</span> 完成</div>
      </div>
    </div>

    <!-- ===== Done ===== -->
    <div v-else class="mem-done">
      <div class="mem-done-emoji">🎉</div>
      <h3>本轮完成</h3>
      <p>已背 {{ stat.memorized }} 个 · 答对 {{ stat.right }} 次 · 答错 {{ stat.wrong }} 次</p>
      <div class="controls">
        <button class="btn primary big" @click="goDictation">{{ lesson ? "去听打本课单词" : "去听打（只看已背）" }}</button>
        <button class="btn ghost" @click="redo">再背一轮</button>
        <button class="btn ghost" @click="goCatalog">返回素材库</button>
      </div>
    </div>

  </div>

  <input id="catch" ref="catchEl" autocomplete="off" autocorrect="off"
         autocapitalize="off" spellcheck="false" enterkeyhint="done"
         style="position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none;"
         @compositionstart="evCompStart" @compositionend="evCompEnd"
         @input="onInput" @blur="evBlurCatch">
</template>
