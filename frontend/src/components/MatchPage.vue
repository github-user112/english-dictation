<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { api, playWord, stopAudio } from "../lib/core";

const PAIR_OPTIONS = [4, 6, 8, 10];
const isMobile = window.matchMedia("(max-width: 620px)").matches;
const MIN_FS = 10;             // 牌面自动缩字的下限（px）

const phase = ref("start");    // start | run | done
const wordLists = ref([]);
const list = ref("cet4");
const pairsWanted = ref(isMobile ? 6 : 8);
const gridEl = ref(null);
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
// 手机端固定 3 列（6 对 = 3×4 共 12 格）
const gridCols = computed(() =>
  isMobile ? 3 : Math.min(4, Math.max(2, Math.ceil(Math.sqrt(totalPairs.value * 2)))));
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
    nextTick(fitTiles);
    playWord(items.value[0]);   // 开局先听第一个词，顺便暖声
  } catch (err) {
    loadError.value = err.message || "发牌失败";
  }
}

// 逐牌缩字：一行放不下就逐步减小字号，到下限仍超长则横向滚动
function fitTiles() {
  const grid = gridEl.value;
  if (!grid) return;
  for (const b of grid.querySelectorAll(".pair-tile b")) {
    b.style.fontSize = "";
    b.classList.remove("scroll");
    b.classList.add("nowrap");
    let fs = parseFloat(getComputedStyle(b).fontSize);
    while (fs > MIN_FS && b.scrollWidth > b.clientWidth) {
      fs -= 0.5;
      b.style.fontSize = `${fs}px`;
    }
    if (b.scrollWidth > b.clientWidth) b.classList.add("scroll");
    else b.classList.remove("nowrap");
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

function goLists() { location.hash = "#/lists"; }
function mmss(s) { return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }
</script>

<template>
  <div class="match-page">
    <!-- ============ 开始页 ============ -->
    <div v-if="phase === 'start'" class="match-start">
      <section class="match-hero">
        <div class="mh-top">
          <span class="mh-eyebrow"><span class="ic">🃏</span> 记忆配对</span>
          <span class="mh-badge"><span class="ic">🀄</span> 英中互译</span>
        </div>
        <h1>英中配对消消乐</h1>
        <p class="mh-lead">词与释义两两配对，配上一对消一对，清空桌面即通关。</p>
        <p class="mh-rule">配错双方都会抖一下并记一次失误——首配即中的词才有满额经验。</p>
      </section>

      <section class="card match-setup-card">
        <div class="card-title"><span class="card-icon">⚙️</span> 开局设置</div>
        <div class="setup-grid">
          <div class="form-group">
            <label class="form-label" for="match-list">📚 词库</label>
            <select id="match-list" v-model="list" class="match-select form-select" aria-label="选择词库">
              <option v-for="l in wordLists" :key="l.key" :value="l.key">{{ l.title }}</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label" for="match-pairs">🎯 对数</label>
            <select id="match-pairs" v-model.number="pairsWanted" class="match-select form-select" aria-label="选择对数">
              <option v-for="n in PAIR_OPTIONS" :key="n" :value="n">{{ n }} 对</option>
            </select>
          </div>
        </div>
        <p v-if="loadError" role="alert" class="setup-error">⚠️ {{ loadError }}</p>
        <div class="controls match-cta">
          <button class="btn primary big full" @click="deal">🎮 开始配对</button>
          <button class="btn ghost full" @click="goLists">📚 返回素材库</button>
        </div>
      </section>

      <section class="card match-tips">
        <div class="card-title"><span class="card-icon">💡</span> 玩法技巧</div>
        <div class="card-desc">三条心得，命中率翻倍</div>
        <div class="tip-row">
          <div class="tip-ic g">🔊</div>
          <div class="tip-body">
            <b>先听后配</b>
            <p>开局会自动念第一个词，点英文牌也会发音——耳朵先记住读音，再找释义更快。</p>
          </div>
        </div>
        <div class="tip-row">
          <div class="tip-ic b">🎯</div>
          <div class="tip-body">
            <b>首配即中才拿满经验</b>
            <p>配错一次，双方这个词都失去「首配即中」资格。先扫一眼整盘，优先消掉最有把握的一对。</p>
          </div>
        </div>
        <div class="tip-row">
          <div class="tip-ic o">🔄</div>
          <div class="tip-body">
            <b>点错不用慌</b>
            <p>再点一次就取消选中；连对 2 次进入连击，连击越高经验加成越多。</p>
          </div>
        </div>
      </section>
    </div>

    <!-- ============ 对局中 ============ -->
    <template v-else-if="phase === 'run'">
      <div class="cockpit">
        <span class="hud-brand"><span class="ic">🃏</span> 配对中</span>
        <div class="cockpit-divider"></div>
        <div class="hud">
          <span class="timer-pill hud-item" role="timer" :aria-label="`已用时 ${seconds} 秒`">⏱ {{ mmss(seconds) }}</span>
          <span v-if="combo >= 2" class="hud-item combo" aria-hidden="true">🔥 ×{{ combo }}</span>
          <span class="hud-item pairs">✅ 已消 {{ matchedCount }}/{{ totalPairs }}</span>
          <span class="hud-item moves">👣 步数 {{ moves }} · 失误 {{ mistakes }}</span>
        </div>
      </div>

      <div class="arena">
        <div class="arena-top"></div>
        <div class="arena-inner">
          <div class="arena-head">
            <div class="ah-left">
              <span class="ah-badge"><span class="ic">🎯</span> {{ totalPairs }} 对挑战</span>
              <span class="ah-title">翻牌配对<small>连对 2 次进入连击加成</small></span>
            </div>
            <div class="ah-prog">
              <div class="progress-bar">
                <div class="progress-fill green"
                     :style="{ width: totalPairs ? matchedCount / totalPairs * 100 + '%' : '0%' }"></div>
              </div>
              <span class="ah-num">{{ matchedCount }}<small>/{{ totalPairs }}</small></span>
            </div>
          </div>

          <div ref="gridEl" class="pair-grid" :style="{ '--cols': gridCols }">
            <button v-for="t in tiles" :key="t.key" class="pair-tile"
                    :class="tileClass(t)"
                    :aria-label="`${t.side === 'en' ? '英文' : '中文'}：${t.text}`"
                    @click="pick(t)">
              <b>{{ t.text }}</b>
              <small v-if="t.sub">{{ t.sub }}</small>
            </button>
          </div>

          <div class="arena-foot">
            <p class="hint">点一个词再点它的释义（顺序随意）· 点英文会发音 · 再点一次取消选中</p>
            <div class="legend">
              <span class="lg lg-en">🔤 英文</span>
              <span class="lg lg-zh">🀄 中文</span>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ============ 结算 ============ -->
    <div v-else class="match-done">
      <section class="hero-card match-result">
        <div class="mr-stars">{{ '⭐'.repeat(stars) }}</div>
        <h2>桌面清空！</h2>
        <p class="mr-lead">{{ totalPairs }} 对 · 用时 {{ mmss(seconds) }} · 步数 {{ moves }} · 失误 {{ mistakes }}</p>
        <div class="mr-grid">
          <div class="mr-chip"><div class="v">{{ totalPairs }}</div><div class="l">✅ 消除对数</div></div>
          <div class="mr-chip"><div class="v">{{ mmss(seconds) }}</div><div class="l">⏱ 用时</div></div>
          <div class="mr-chip"><div class="v">{{ moves }}</div><div class="l">👣 步数</div></div>
          <div class="mr-chip"><div class="v">{{ mistakes }}</div><div class="l">⚠️ 失误</div></div>
        </div>
        <p v-if="result && result.perfect === result.total" class="mr-perfect">
          🎉 全部首配即中，经验拿满！</p>
        <p v-else-if="result" class="mr-partial">
          首配即中 {{ result.perfect }}/{{ result.total }} 个词</p>
        <div class="controls match-cta">
          <button class="btn white big full" @click="deal">🎮 再来一局</button>
          <button class="btn mr-ghost big full" @click="phase = 'start'; loadError = ''">📚 换词库</button>
        </div>
      </section>
    </div>
  </div>
</template>
