<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, playWord, stopAudio } from "../lib/core";

const PAIR_OPTIONS = [4, 6, 8, 10];

const phase = ref("start");    // start | run | done
const wordLists = ref([]);
const list = ref("cet4");
const pairsWanted = ref(8);
const items = ref([]);         // 服务端发的词（含释义/音频）
const tiles = ref([]);         // 洗牌后的桌面：每词两张（en/zh）
const pickedKey = ref("");     // 当前选中的第一张牌
const matched = ref([]);       // 已消除的 id
const dirtyIds = ref([]);      // 配错过的词：失去"首配即中"资格
const wrongKeys = ref([]);     // 抖动中的两张牌
const mistakes = ref(0);
const moves = ref(0);
const combo = ref(0);
const seconds = ref(0);
const result = ref(null);
const loadError = ref("");
let timer = null;
let shakeTimer = null;
let mounted = true;

const totalPairs = computed(() => items.value.length);
const matchedCount = computed(() => matched.value.length);
/* 星级：零失误三星，≤3 失误两星，其余一星 */
const stars = computed(() => (mistakes.value === 0 ? 3 : mistakes.value <= 3 ? 2 : 1));

onMounted(async () => {
  try {
    const d = await api("/lists");
    if (!mounted) return;
    wordLists.value = (d.lists || []).filter((l) => l.type === "words");
    if (!wordLists.value.some((l) => l.key === list.value)) {
      list.value = wordLists.value[0]?.key || "cet4";
    }
  } catch { /* 开始时再试 */ }
});

onUnmounted(stopTimers);

function stopTimers() {
  mounted = false;
  stopAudio();
  if (timer) { clearInterval(timer); timer = null; }
  if (shakeTimer) { clearTimeout(shakeTimer); shakeTimer = null; }
}

function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

async function deal() {
  loadError.value = "";
  try {
    const d = await api(`/match/session?list=${encodeURIComponent(list.value)}&n=${pairsWanted.value}`);
    items.value = d.items || [];
    if (!items.value.length) return;
    // 每个词两张牌：英文面 + 中文面，洗匀上桌
    tiles.value = shuffle(items.value.flatMap((it) => [
      { key: `${it.id}:en`, id: it.id, side: "en", text: it.text, sub: it.phonetic },
      { key: `${it.id}:zh`, id: it.id, side: "zh", text: it.meaning, sub: "" },
    ]));
    pickedKey.value = ""; matched.value = []; dirtyIds.value = []; wrongKeys.value = [];
    mistakes.value = 0; moves.value = 0; combo.value = 0; seconds.value = 0;
    result.value = null;
    phase.value = "run";
    if (timer) clearInterval(timer);
    timer = setInterval(() => { seconds.value++; }, 1000);
    playWord(items.value[0]);   // 开局先听第一个词，顺便暖声
  } catch (err) {
    loadError.value = err.message || "发牌失败";
  }
}

function tileClass(t) {
  return {
    en: t.side === "en",
    zh: t.side === "zh",
    picked: pickedKey.value === t.key,
    gone: matched.value.includes(t.id),
    shaking: wrongKeys.value.includes(t.key),
  };
}

function pick(t) {
  if (phase.value !== "run" || matched.value.includes(t.id)) return;
  if (pickedKey.value === t.key) { pickedKey.value = ""; return; }   // 再点一次取消
  const first = tiles.value.find((x) => x.key === pickedKey.value);
  if (!first) {
    pickedKey.value = t.key;
    if (t.side === "en") speak(t.id);
    return;
  }
  moves.value++;
  if (first.id === t.id && first.side !== t.side) {
    // 配对成功：双牌消散；英文面上桌即发音
    matched.value = [...matched.value, t.id];
    combo.value++;
    pickedKey.value = "";
    speak(t.id);
    if (matched.value.length >= totalPairs.value) win();
  } else {
    // 配对失手：双双抖动示错，两词都失去"首配即中"
    combo.value = 0;
    mistakes.value++;
    dirtyIds.value = [...new Set([...dirtyIds.value, first.id, t.id])];
    wrongKeys.value = [first.key, t.key];
    pickedKey.value = "";
    if (shakeTimer) clearTimeout(shakeTimer);
    shakeTimer = setTimeout(() => { wrongKeys.value = []; }, 620);
  }
}

function speak(id) {
  const it = items.value.find((x) => x.id === id);
  if (it) playWord(it);
}

async function win() {
  if (timer) { clearInterval(timer); timer = null; }
  phase.value = "done";
  const attemptId = (() => {
    const uuid = globalThis.crypto?.randomUUID?.();
    return uuid ? uuid.replaceAll("-", "") : `${Date.now()}${Math.random().toString(36).slice(2)}`;
  })();
  try {
    const d = await api("/match/result", {
      method: "POST",
      body: JSON.stringify({
        list: list.value,
        answers: items.value.map((it) => ({ id: it.id, right: !dirtyIds.value.includes(it.id) })),
        attempt_id: attemptId,
      }),
    });
    result.value = d;
    window.dispatchEvent(new CustomEvent("profile-changed"));
  } catch { /* 结算失败不影响战报展示 */ }
}

function goCatalog() { location.hash = "#/catalog"; }
function mmss(s) { return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }
</script>

<template>
  <div class="match-page">
    <!-- 开始页 -->
    <div v-if="phase === 'start'" class="empty">
      <div style="font-size:44px;" aria-hidden="true">🀄</div>
      <div style="font-size:20px;font-weight:700;margin-bottom:10px;">英中配对消消乐</div>
      <p>词与释义两两配对，配上一对消一对，清空桌面即通关。</p>
      <p>配错双方都会抖一下并记一次失误——首配即中的词才有满额经验。</p>
      <div class="match-setup">
        <select v-model="list" class="match-select" aria-label="选择词库">
          <option v-for="l in wordLists" :key="l.key" :value="l.key">{{ l.title }}</option>
        </select>
        <select v-model.number="pairsWanted" class="match-select" aria-label="选择对数">
          <option v-for="n in PAIR_OPTIONS" :key="n" :value="n">{{ n }} 对</option>
        </select>
      </div>
      <p v-if="loadError" role="alert" style="color:var(--red);">{{ loadError }}</p>
      <div class="controls" style="margin-top:16px;">
        <button class="btn primary big" @click="deal">🎮 开始配对</button>
        <button class="btn ghost" @click="goCatalog">返回素材库</button>
      </div>
    </div>

    <!-- 对局中 -->
    <template v-else-if="phase === 'run'">
      <div class="practice-top">
        <span class="progress-line">已消 {{ matchedCount }}/{{ totalPairs }} · 步数 {{ moves }} · 失误 {{ mistakes }}</span>
        <span v-if="combo >= 2" class="combo-num" aria-hidden="true">🔥 ×{{ combo }}</span>
        <span class="match-clock" role="timer" :aria-label="`已用时 ${seconds} 秒`">⏱ {{ mmss(seconds) }}</span>
      </div>
      <div class="pair-grid" :style="{ '--cols': Math.min(4, Math.max(2, Math.ceil(Math.sqrt(totalPairs * 2)))) }">
        <button v-for="t in tiles" :key="t.key" class="pair-tile"
                :class="tileClass(t)"
                :aria-label="`${t.side === 'en' ? '英文' : '中文'}：${t.text}`"
                @click="pick(t)">
          <b>{{ t.text }}</b>
          <small v-if="t.sub">{{ t.sub }}</small>
        </button>
      </div>
      <div class="hint" style="text-align:center;margin-top:14px;">
        点一个词再点它的释义（顺序随意）· 点英文会发音 · 再点一次取消选中
      </div>
    </template>

    <!-- 结算 -->
    <div v-else class="empty">
      <div style="font-size:40px;" aria-hidden="true">{{ '⭐'.repeat(stars) }}</div>
      <div style="font-size:20px;font-weight:700;margin-bottom:10px;">桌面清空！</div>
      <p>{{ totalPairs }} 对 · 用时 {{ mmss(seconds) }} · 步数 {{ moves }} · 失误 {{ mistakes }}</p>
      <p v-if="result && result.perfect === result.total" style="color:var(--green);">
        全部首配即中，经验拿满！</p>
      <p v-else-if="result" style="color:var(--yellow);">
        首配即中 {{ result.perfect }}/{{ result.total }} 个词</p>
      <div class="controls" style="margin-top:16px;">
        <button class="btn primary big" @click="deal">再来一局</button>
        <button class="btn ghost big" @click="phase = 'start'; loadError = ''">换词库</button>
      </div>
    </div>
  </div>
</template>
