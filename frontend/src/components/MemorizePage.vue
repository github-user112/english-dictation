<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, audioEl, ensureAudio, playUrl, sndRight, sndWrong } from "../lib/core";
import WordCells from "./WordCells.vue";

const props = defineProps({ params: { type: Object, default: null } });

const list = ref("cet4");
const phase = ref("learn");            // learn | quiz | done
const items = ref([]);                 // 全部任务
const queue = ref([]);                 // 自测队列
const cur = ref(null);
const flipped = ref(false);
const submitted = ref(false);
const lastRight = ref(false);
const lastNote = ref("");
const loading = ref(true);
const cells = ref(null);
const catchEl = ref(null);
const audioCache = ref({});
const playToken = ref(0);
const nextTimer = ref(null);
const quizRound = ref(0);
const stat = ref({ right: 0, wrong: 0, memorized: 0 });
const learnIndex = ref(0);            // 学习态当前索引（用于恢复）
let mounted = true;

const prog = computed(() => "剩余 " + (queue.value.length + (cur.value && phase.value === "quiz" ? 1 : 0)));
const learnTotal = computed(() => items.value.length);

const SS_KEY = "dict_memorize";

function saveState() {
  if (!items.value.length) return;
  try {
    sessionStorage.setItem(SS_KEY, JSON.stringify({
      list: list.value, phase: phase.value, items: items.value,
      queue: queue.value, cur: cur.value, stat: stat.value,
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

onMounted(async () => {
  list.value = props.params?.get("list") || "cet4";
  const saved = loadState();
  if (saved && saved.list === list.value && saved.items?.length) {
    // 恢复刷新前的进度
    items.value = saved.items;
    queue.value = saved.queue || [];
    cur.value = saved.cur;
    phase.value = saved.phase || "learn";
    stat.value = saved.stat || { right: 0, wrong: 0, memorized: 0 };
    quizRound.value = saved.quizRound || 0;
    learnIndex.value = saved.learnIndex || 0;
    loading.value = false;
    if (cur.value && phase.value !== "done") {
      await nextTick();
      if (!mounted) return;
      play();
    }
  } else {
    const d = await api(`/memorize/session?list=${list.value}`);
    if (!mounted) return;
    items.value = d.items || [];
    queue.value = [...items.value];
    loading.value = false;
    if (queue.value.length) {
      cur.value = queue.value[0];
      queue.value.shift();
      play();
    }
    saveState();
  }
  forceFocus();
  document.addEventListener("pointerdown", onDocDown, true);
  window.addEventListener("keydown", onGlobalKey, true);
});

onUnmounted(() => {
  mounted = false;
  playToken.value++;
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
function forceFocus() {
  setTimeout(focusCatch, 150);
  setTimeout(focusCatch, 450);
}
function onDocDown(ev) {
  if (ev.target.tagName === "BUTTON" || ev.target.tagName === "A" ||
      ev.target.tagName === "INPUT" || ev.target.tagName === "SELECT" ||
      ev.target.tagName === "TEXTAREA" || ev.target.closest(".btn") ||
      ev.target.closest("a") || ev.target.closest("select")) {
    return;
  }
  ev.preventDefault();
  focusCatch();
}
function onBlurCatch(ev) { ev.target.setAttribute("readonly", ""); }
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
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); quizNext(); return; }
    return;
  }
  if (ev.key === "Enter") { ev.preventDefault(); submit(); return; }
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
  let url = audioCache.value[playingItem.text];
  if (!url) {
    url = await ensureAudio(playingItem);
    if (token !== playToken.value || cur.value !== playingItem) return;
    audioCache.value[playingItem.text] = url;
  }
  if (token !== playToken.value || cur.value !== playingItem) return;
  playUrl(url);
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
  const ch = ev.data || ev.target.value;
  ev.target.value = "";
  if (!ch || submitted.value || ev.isComposing) return;
  typeChar(ch);
}
async function submit() {
  if (submitted.value) return;
  const right = cells.value.isCorrect();
  playToken.value++;
  audioEl.pause();
  submitted.value = true;
  if (right) cells.value.paint(true);
  else cells.value.markWrong();
  const r = await api("/memorize", {
    method: "POST",
    body: JSON.stringify({ list: list.value, id: cur.value.id, right }),
  });
  if (!mounted) return;
  if (right) {
    sndRight();
    stat.value.right++;
    if (r.memorized) {
      stat.value.memorized++;
      lastNote.value = "✔ 已背过！";
    } else {
      lastNote.value = "✔ 对了，待会再确认一遍";
      queue.value.push({ ...cur.value });   // 连续答对 2 次才已背，排队复测
    }
    lastRight.value = true;
    saveState();
    clearTimeout(nextTimer.value);
    nextTimer.value = setTimeout(() => quizNext(), 900);
  } else {
    sndWrong();
    stat.value.wrong++;
    lastNote.value = "✗ 再背一次，明天还会见到它";
    lastRight.value = false;
    saveState();
  }
}
function quizNext() {
  playToken.value++;
  audioEl.pause();
  quizRound.value++;
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  submitted.value = false;
  lastNote.value = "";
  if (!queue.value.length) {
    phase.value = "done";
    clearState();
    return;
  }
  cur.value = queue.value[0];
  queue.value.shift();
  saveState();
  play();
  nextTick().then(() => { focusCatch(); });
}
function redo() {
  clearState();
  location.reload();
}
function goDictation() {
  window.location.hash = `#/word?list=${list.value}&scope=memorized`;
}
function goCatalog() { window.location.hash = "#/catalog"; }
</script>

<template>
  <div v-if="loading" class="empty">加载中…</div>
  <div v-else-if="!items.length" class="empty">
    <p>本轮没有要背的词（已背的词 7 天内会回来复习）</p>
    <div class="controls" style="margin-top:16px;">
      <button class="btn primary" @click="goDictation">去听打（只看已背）</button>
      <button class="btn ghost" @click="goCatalog">返回素材库</button>
    </div>
  </div>

  <!-- 学习态：英→中翻卡 -->
  <div v-else-if="phase === 'learn'" @pointerdown="focusCatch">
    <div class="practice-top">
      <span class="progress-line">先认个脸：{{ items.indexOf(cur) + 1 }} / {{ learnTotal }}</span>
      <button class="btn ghost" @click="startQuiz">跳过学习，直接自测</button>
    </div>
    <div class="practice-card">
      <div class="flash-card" :class="{ flipped }" @click="flip">
        <div class="face front">
          <div class="fw">{{ cur.text }}</div>
          <div class="fp">{{ cur.phonetic }}</div>
        </div>
        <div class="face back">
          <div class="fm">{{ cur.meaning }}</div>
        </div>
      </div>
      <div class="controls" style="margin-top:16px;">
        <button class="btn ghost" @click="play">🔊 发音</button>
        <button class="btn primary big" @click="learnNext">{{ items.indexOf(cur) === items.length - 1 ? '开始自测 →' : '下一个 →' }}</button>
      </div>
      <div class="hint">点击卡片翻面 · 记住拼写后开始自测</div>
    </div>
  </div>

  <!-- 自测态：中→英打字 -->
  <div v-else-if="phase === 'quiz'" @pointerdown="focusCatch">
    <div class="practice-top">
      <span class="progress-line">{{ prog }} · 已背 {{ stat.memorized }}</span>
      <span class="badge" style="background:#24402d;color:#7fdcab;">{{ cur.phase === 'review' ? '复习' : '新词' }}</span>
    </div>
    <div class="practice-card">
      <div class="info-line" style="margin-bottom:10px;">
        <span id="meaning" style="font-size:18px;">{{ cur.meaning }}</span>
      </div>
      <div class="cells-wrap">
        <WordCells ref="cells" :key="quizRound" :tokens="cur" :submitted="submitted"></WordCells>
      </div>
      <div id="answer-line">
        <template v-if="submitted">
          <span v-if="!lastRight" class="show-word">✗ 答案：{{ cur.text }}</span>
          <span v-if="lastRight">{{ lastNote }}</span>
        </template>
      </div>
      <div class="controls">
        <button class="btn primary big" @click="submitted ? quizNext() : submit()">{{ submitted ? '继续' : '提交' }}</button>
        <button class="btn ghost" @click="play">🔊 听发音</button>
      </div>
      <div class="hint">看中文，打英文 · 答对自动下一题（自动发音）· 答对 2 次算已背</div>
    </div>
  </div>

  <!-- 结束 -->
  <div v-else class="empty">
    <div style="font-size:20px;font-weight:700;margin-bottom:10px;">本轮完成 🎉</div>
    <p>已背 {{ stat.memorized }} 个 · 答对 {{ stat.right }} 次 · 答错 {{ stat.wrong }} 次</p>
    <div class="controls" style="margin-top:16px;">
      <button class="btn primary big" @click="goDictation">去听打（只看已背）</button>
      <button class="btn ghost" @click="redo">再背一轮</button>
      <button class="btn ghost" @click="goCatalog">返回素材库</button>
    </div>
  </div>

  <input id="catch" ref="catchEl" autofocus autocomplete="off" autocorrect="off"
         autocapitalize="off" spellcheck="false" enterkeyhint="done"
         style="position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none;"
         @input="onInput" @blur="onBlurCatch">
</template>
