<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, Settings, audioEl, ensureAudio, playUrl, sndRight, sndWrong } from "../lib/core";
import WordCells from "./WordCells.vue";
import SentenceCells from "./SentenceCells.vue";

const props = defineProps({ params: { type: Object, default: null } });

const list = ref("cet4");
const mode = ref("word");
const items = ref([]);
const cur = ref(0);
const submitted = ref(false);
const lastRight = ref(false);
const loading = ref(true);
const custom = ref(false);
const audioCache = ref({});
const replayTimer = ref(null);
const nextTimer = ref(null);
const replayCount = ref(0);
const cells = ref(null);

const speed = ref(Settings.get().speed);
const item = computed(() => items.value[cur.value]);
const prog = computed(() => items.value.length ? `${cur.value + 1} / ${items.value.length}` : "");
const speedLabel = computed(() => speed.value.toFixed(2).replace(/0$/, "").replace(/\.0/, "") + "x");
const settings = computed(() => Settings.get());

onMounted(async () => {
  const h = location.hash.replace(/^#\/?/, "").split("?");
  list.value = new URLSearchParams(h[1] || "").get("list") || "cet4";
  mode.value = new URLSearchParams(h[1] || "").get("mode") || (list.value === "oral900" ? "sentence" : "word");
  const c = sessionStorage.getItem("dict_custom");
  if (c) {
    items.value = JSON.parse(c);
    sessionStorage.removeItem("dict_custom");
    custom.value = true;
  } else {
    const d = await api(`/session?list=${list.value}&new=${Settings.get().newPerDay}`);
    items.value = d.items || [];
  }
  loading.value = false;
  if (items.value.length) {
    await nextTick();
    replayCount.value = 0;
    focusCatch();
    play();
  }
  document.addEventListener("pointerdown", onDocDown, true);
  window.addEventListener("keydown", onGlobalKey, true);
});

onUnmounted(() => {
  clearReplay();
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  document.removeEventListener("pointerdown", onDocDown, true);
  window.removeEventListener("keydown", onGlobalKey, true);
});

async function nextTick() { await new Promise((r) => setTimeout(r, 0)); }

function focusCatch() {
  const el = document.getElementById("catch");
  if (el) {
    el.removeAttribute("readonly");
    el.focus({ preventScroll: true });
  }
}
function onDocDown(ev) {
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
  if (ev.key === "Enter") { ev.preventDefault(); submit(); return; }
  if (ev.key === "Escape") { clearReplay(); play(); return; }
  if (ev.key === "Backspace") {
    ev.preventDefault();
    cells.value.backspace();
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
  for (const c of ch) {
    if (mode.value === "word") cells.value.typeLetter(c);
    else cells.value.typeWordChar(c);
  }
  const done = mode.value === "word" ? cells.value.isFull() : cells.value.isCorrect();
  if (done) submit();
}
async function play() {
  if (!item.value) return;
  clearReplay();
  const it = item.value;
  let url = audioCache.value[it.text];
  if (!url) {
    url = await ensureAudio(it);
    audioCache.value[it.text] = url;
  }
  playUrl(url);
  audioEl.onended = () => {
    if (submitted.value) return;
    const s = Settings.get();
    if (replayCount.value < (s.replayTimes ?? 2)) {
      replayCount.value++;
      replayTimer.value = setTimeout(() => play(), Math.max(1, s.replayInterval || 5) * 1000);
    }
  };
}
function submit() {
  const right = cells.value.isCorrect();
  submitted.value = true;
  lastRight.value = right;
  cells.value.paint(right);
  clearReplay();
  audioEl.pause();
  if (right) sndRight();
  else sndWrong();
  api("/result", { method: "POST", body: JSON.stringify({ list: list.value, id: item.value.id, right }) });
  if (right) {
    clearTimeout(nextTimer.value);
    nextTimer.value = setTimeout(() => next(), 2000);
  }
}
function next() {
  clearReplay();
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  if (cur.value + 1 >= items.value.length) {
    location.hash = "#/catalog";
    return;
  }
  cur.value++;
  submitted.value = false;
  replayCount.value = 0;
  setTimeout(() => { focusCatch(); play(); }, 130);
}
function skip() {
  api("/result", { method: "POST", body: JSON.stringify({ list: list.value, id: item.value.id, right: false }) });
  next();
}
function again() { location.reload(); }
function cycleSpeed() {
  const s = Settings.get();
  const next = s.speed === 0.75 ? 1.0 : s.speed === 1.0 ? 1.25 : 0.75;
  Settings.set({ speed: next });
  speed.value = next;
  audioEl.playbackRate = next;
}
</script>

<template>
  <div v-if="loading" class="empty">加载中…</div>
  <div v-else-if="!items.length" class="empty">没有可练的词了，换个素材或明天再来</div>
  <div v-else @pointerdown="focusCatch">
    <div class="practice-top">
      <span class="progress-line">{{ prog }}<span v-if="custom" style="color:var(--yellow);">（错词重练）</span></span>
      <button class="btn ghost" @click="cycleSpeed">{{ speedLabel }}</button>
    </div>
    <div class="practice-card">
      <div class="info-line">
        <span id="phonetic">{{ settings.showPhonetic && item.phonetic ? item.phonetic : '' }}</span>
        <span id="meaning">{{ settings.showMeaning && item.meaning ? item.meaning : '' }}</span>
      </div>
      <div class="cells-wrap">
        <component :is="mode === 'word' ? WordCells : SentenceCells"
          ref="cells" :tokens="item" :submitted="submitted"></component>
      </div>
      <div class="follow-line" v-if="settings.showWord && !submitted">{{ item.text }}</div>
      <div id="answer-line">
        <span v-if="submitted && !lastRight" class="show-word">✗ 答案：{{ item.text }}</span>
        <span v-if="submitted && lastRight">✔ 正确，继续！</span>
      </div>
      <div class="controls">
        <button class="btn ghost" @click="again">↻ 再来一轮</button>
        <button class="btn ghost" @click="skip">跳过</button>
        <button class="btn primary big" id="play-btn" @click="play">🔊</button>
      </div>
      <div class="hint">打字输入 · 打对 2 秒后自动下一题 · Enter 提交 · Esc 重听 · 自动重播间隔可在设置调整</div>
    </div>
    <input id="catch" autocomplete="off" autocorrect="off"
           autocapitalize="off" spellcheck="false" enterkeyhint="done"
           style="position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none;"
           @input="onInput" @blur="onBlurCatch">
  </div>
</template>