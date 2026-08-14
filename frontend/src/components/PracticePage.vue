<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, Settings, audioEl, ensureAudio, playUrl, sndRight, sndWrong } from "../lib/core";
import WordCells from "./WordCells.vue";
import SentenceCells from "./SentenceCells.vue";

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
const firstRight = ref(null);
const attemptCount = ref(0);
const saving = ref(false);
const firstAttemptSent = ref(false);
const loading = ref(true);
const custom = ref(false);
const audioCache = ref({});
const playToken = ref(0);
const replayTimer = ref(null);
const nextTimer = ref(null);
const replayCount = ref(0);
const cells = ref(null);
const catchEl = ref(null);
let mounted = true;

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
    sessionStorage.removeItem("dict_custom");
    custom.value = true;
  } else {
    await loadSession();
    if (!mounted) return;
  }
  loading.value = false;
  if (items.value.length) {
    await nextTick();
    if (!mounted) return;
    restoreAttempt();
    restoreInputSnapshot();
    replayCount.value = 0;
    focusCatch();
    play();
  }
  setTimeout(focusCatch, 150);
  setTimeout(focusCatch, 450);
  document.addEventListener("pointerdown", onDocDown, true);
  window.addEventListener("keydown", onGlobalKey, true);
});

onUnmounted(() => {
  mounted = false;
  playToken.value++;
  clearReplay();
  audioEl.pause();
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  document.removeEventListener("pointerdown", onDocDown, true);
  window.removeEventListener("keydown", onGlobalKey, true);
});

async function nextTick() { await new Promise((r) => setTimeout(r, 0)); }

function focusCatch() {
  const el = catchEl.value;
  if (el) {
    el.removeAttribute("readonly");
    try { el.focus({ preventScroll: true }); } catch { el.focus(); }
  }
}
function onDocDown(ev) {
  // 不对按钮/链接/输入框等元素阻止默认行为，仅捕获焦点
  if (ev.target.tagName === "BUTTON" || ev.target.tagName === "A" ||
      ev.target.tagName === "INPUT" || ev.target.tagName === "SELECT" ||
      ev.target.tagName === "TEXTAREA" || ev.target.closest(".btn") ||
      ev.target.closest("a") || ev.target.closest("select")) {
    return;
  }
  ev.preventDefault();
  focusCatch();
}
function onBlurCatch(ev) {
  ev.target.setAttribute("readonly", "");
}
function onGlobalKey(ev) {
  const t = ev.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) && t.id !== "catch") return;
  onKey(ev);
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
    ev.preventDefault();
    typeChar(ev.key);
  }
}
function onInput(ev) {
  const ch = ev.data || ev.target.value;
  ev.target.value = "";
  if (!ch || submitted.value || ev.isComposing) return;
  typeChar(ch);
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
async function submit() {
  if (saving.value || submitted.value) return;
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
    } finally {
      saving.value = false;
    }
    failed.value = false;
    clearTimeout(nextTimer.value);
    nextTimer.value = setTimeout(() => next(), 2000);
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
      try { await saveResult("attempt", false); }
      finally { saving.value = false; }
    }
  }
}
async function saveResult(outcome, finalRight) {
  return api("/result", { method: "POST", body: JSON.stringify({
    session_id: sessionId.value || undefined,
    list: list.value, id: item.value.id, mode: practiceMode.value,
    first_right: firstRight.value, final_right: finalRight,
    attempt_count: attemptCount.value, outcome,
    right: finalRight, retried: firstRight.value === false,
  }) });
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
  playToken.value++;
  clearReplay();
  audioEl.pause();
  scope.value = scope.value === "memorized" ? "all" : "memorized";
  loadSession().then(() => {
    if (!mounted) return;
    cur.value = 0;
    submitted.value = false;
    if (items.value.length) {
      replayCount.value = 0;
      resetAttempt();
      focusCatch();
      play();
    }
  });
}
function next() {
  playToken.value++;
  clearReplay();
  audioEl.pause();
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  clearInputSnapshot();
  if (cur.value + 1 >= items.value.length) {
    location.hash = "#/catalog";
    return;
  }
  cur.value++;
  submitted.value = false;
  retrying.value = false;
  failed.value = false;
  inputError.value = false;
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
function resetAttempt() {
  firstRight.value = null;
  attemptCount.value = 0;
  saving.value = false;
  firstAttemptSent.value = false;
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
  firstRight.value = first === null || first === undefined ? null : Boolean(first);
  attemptCount.value = Number(item.value?.attempt_count) || 0;
  failed.value = first === false;
  retrying.value = first === false;
  firstAttemptSent.value = first !== null && first !== undefined;
  if (retrying.value) setTimeout(() => { if (mounted) cells.value?.markWrong(); }, 0);
}
function again() { location.reload(); }
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
  <div v-if="loading" class="empty">加载中…</div>
  <div v-else-if="!items.length" class="empty">没有可练的词了，换个素材或明天再来</div>
  <div v-else @pointerdown="focusCatch">
    <div class="practice-top">
      <span class="progress-line">{{ prog }}<span v-if="custom" style="color:var(--yellow);">（错词重练）</span><span v-else-if="mode==='word' && scope==='memorized'" style="color:var(--green);">（只看已背）</span></span>
      <span class="badge mode-badge">{{ practiceMode === 'pure' ? '纯听写' : practiceMode === 'follow' ? '跟打' : '辅助听写' }}</span>
      <div class="scope-group" v-if="mode === 'word' && !custom">
        <button class="btn ghost sm" :class="{ active: scope === 'all' }" @click="scope !== 'all' && toggleScope()">全部</button>
        <button class="btn ghost sm" :class="{ active: scope === 'memorized' }" @click="scope !== 'memorized' && toggleScope()">已背</button>
      </div>
      <button class="btn ghost" @click="cycleSpeed">{{ speedLabel }}</button>
    </div>
    <div class="practice-card">
      <div class="info-line">
        <span id="phonetic">{{ practiceMode !== 'pure' && settings.showPhonetic && item.phonetic ? item.phonetic : '' }}</span>
        <span id="meaning">{{ practiceMode !== 'pure' && settings.showMeaning && item.meaning ? item.meaning : '' }}</span>
      </div>
      <div class="cells-wrap">
        <component :is="mode === 'word' ? WordCells : SentenceCells"
          ref="cells" :tokens="item" :submitted="submitted" :feedback="retrying || submitted"
          :practice-mode="practiceMode"></component>
      </div>
      <div class="follow-line" v-if="practiceMode === 'follow' && !submitted">{{ item.text }}</div>
      <div id="answer-line">
        <span v-if="retrying" style="color:var(--red);">✗ 答错了，答案：<span class="show-word">{{ item.text }}</span> · 按 Enter 重输</span>
        <span v-if="submitted && lastRight">✔ 正确，继续！</span>
      </div>
      <div class="controls">
        <button class="btn ghost" @click="again">↻ 再来一轮</button>
        <button class="btn ghost" :disabled="saving" @click="skip">跳过</button>
        <button v-if="practiceMode === 'pure' && !retrying && !submitted" class="btn primary" :disabled="saving" @click="submit">提交答案</button>
        <button class="btn primary big" id="play-btn" @click="play">🔊</button>
      </div>
      <div class="hint">打字输入 · 答对自动下一题 · 答错红色保持，按 Enter 重输直到正确 · Esc 重听 · 自动重播间隔可在设置调整</div>
    </div>
    <input id="catch" ref="catchEl" autofocus autocomplete="off" autocorrect="off"
           autocapitalize="off" spellcheck="false" enterkeyhint="done"
           style="position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none;"
           @input="onInput" @blur="onBlurCatch">
  </div>
</template>
