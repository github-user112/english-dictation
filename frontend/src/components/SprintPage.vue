<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, playWord, sndWrong, sndCombo, stopAudio } from "../lib/core";
import WordCells from "./WordCells.vue";

const props = defineProps({ params: { type: Object, default: null } });

const DURATION = 60;   // 冲刺时长（秒）
const RING_LEN = 2 * Math.PI * 22;   // 倒计时环周长（r=22）

const list = ref("cet4");
const phase = ref("start");    // start | run | done
const items = ref([]);
const idx = ref(0);
const score = ref(0);
const combo = ref(0);
const maxCombo = ref(0);
const answered = ref(0);
const remain = ref(DURATION);
const best = ref(null);        // { score, combo, total }
const isRecord = ref(false);
const loadError = ref("");
const revealing = ref(false);  // 答错展示答案的短暂锁定
const advanceTimer = ref(null);
const tickTimer = ref(null);
const cells = ref(null);
const catchEl = ref(null);
const focusTimers = ref([]);
let mounted = true;
let deadline = 0;                 // 基于时间戳计时，后台标签页节流也不会变相暂停
let locked = false;               // 提交→切词之间的硬锁：防长按 Enter 重复计分/双跳词

const item = computed(() => items.value[idx.value] || null);
/* 异步挑战模式：URL 带 ?c=<挑战id> 时进入 */
const challengeId = new URLSearchParams(location.hash.split("?")[1] || "").get("c") || "";
const challenge = ref(null);
const challengeLink = ref("");
const creatingChallenge = ref(false);

onMounted(async () => {
  // 同步段先挂监听：无论请求成败/卸载时序，onUnmounted 都能成对移除
  window.addEventListener("keydown", onGlobalKey, true);
  list.value = props.params?.get("list") || "cet4";
  try {
    if (challengeId) {
      const c = await api(`/sprint/challenge?id=${encodeURIComponent(challengeId)}`);
      if (!mounted) return;
      challenge.value = c;
      list.value = c.list;
      items.value = c.items || [];
      return;
    }
    const [d, b] = await Promise.all([
      api(`/sprint/session?list=${encodeURIComponent(list.value)}`),
      api("/sprint/best"),
    ]);
    if (!mounted) return;
    items.value = d.items || [];
    best.value = b.best || null;
  } catch (err) {
    if (mounted) loadError.value = err.message || "题目加载失败";
  }
});

async function submitChallengeScore() {
  if (!challengeId) return;
  try {
    const d = await api(`/sprint/challenge/${challengeId}/score`, {
      method: "POST",
      body: JSON.stringify({ score: score.value, combo: maxCombo.value, total: answered.value }),
    });
    if (challenge.value) challenge.value.scores = d.scores || [];
  } catch { /* 挑战可能已过期，不影响结算展示 */ }
}

async function createChallenge() {
  if (creatingChallenge.value) return;
  creatingChallenge.value = true;
  try {
    const d = await api(`/sprint/challenge?list=${encodeURIComponent(list.value)}`, { method: "POST" });
    challengeLink.value = `${location.origin}/#/sprint?c=${d.id}`;
    await navigator.clipboard?.writeText(challengeLink.value).catch(() => {});
  } catch (err) {
    alert(err.message || "创建挑战失败");
  } finally {
    creatingChallenge.value = false;
  }
}

onUnmounted(() => {
  mounted = false;
  stopTimers();
  stopAudio();
  window.removeEventListener("keydown", onGlobalKey, true);
});

function stopTimers() {
  if (tickTimer.value) { clearInterval(tickTimer.value); tickTimer.value = null; }
  if (advanceTimer.value) { clearTimeout(advanceTimer.value); advanceTimer.value = null; }
  for (const t of focusTimers.value) clearTimeout(t);
  focusTimers.value = [];
}

function focusCatch() {
  const el = catchEl.value;
  if (el) {
    el.removeAttribute("readonly");
    try { el.focus({ preventScroll: true }); } catch { el.focus(); }
  }
}

async function start() {
  if (!items.value.length) return;
  phase.value = "run";
  score.value = 0; combo.value = 0; maxCombo.value = 0; answered.value = 0;
  idx.value = 0; remain.value = DURATION; revealing.value = false; locked = false;
  deadline = Date.now() + DURATION * 1000;
  tickTimer.value = setInterval(() => {
    remain.value = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    if (remain.value <= 0) finish();
  }, 250);
  focusCatch();   // 手势调用栈内同步聚焦，iOS 才会弹出软键盘
  await nextFrame();
  if (!mounted) return;
  focusTimers.value = [setTimeout(focusCatch, 200)];
  play();
}

function nextWord() {
  combo.value = 0;
  revealing.value = false;
  locked = false;
  if (advanceTimer.value) { clearTimeout(advanceTimer.value); advanceTimer.value = null; }
  cells.value?.reset();
  if (idx.value + 1 >= items.value.length) idx.value = 0;   // 词流循环
  else idx.value++;
  play();
  // 不重挂载 WordCells（靠组件内 watch 重置），避免移动端 DOM 重建把
  // 隐藏输入框 blur 掉、软键盘收起；这里只做一次补偿聚焦。
  focusCatch();
}

function onCatchBlur() {
  // 焦点守护：冲刺中输入框失焦（按钮点击等）立刻补聚焦，保住软键盘
  if (phase.value !== "run" || !mounted) return;
  setTimeout(() => {
    if (mounted && phase.value === "run") focusCatch();
  }, 60);
}

function play() {
  if (item.value) playWord(item.value);
}

function onGlobalKey(ev) {
  if (phase.value !== "run" || revealing.value || locked) return;
  const t = ev.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) && t.id !== "catch") return;
  if (ev.key === "Enter") { ev.preventDefault(); submit(); return; }
  if (ev.key === "Escape") { ev.preventDefault(); play(); return; }
  if (ev.key === "Backspace") { ev.preventDefault(); cells.value?.backspace(); return; }
  if (ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
    if (ev.isComposing) return;
    ev.preventDefault();
    typeChar(ev.key);
  }
}

function onInput(ev) {
  const ch = ev.data || ev.target.value;
  ev.target.value = "";
  if (!ch || phase.value !== "run" || revealing.value || locked || ev.isComposing) return;
  typeChar(ch);
}

function typeChar(ch) {
  if (!cells.value || revealing.value || locked) return;
  for (const c of ch) cells.value.typeLetter(c);
  if (cells.value.isFull()) submit();
}

function submit() {
  if (!cells.value || revealing.value || locked) return;
  locked = true;   // 从提交到切词之间封死重复入口（长按 Enter / 满格续敲）
  const right = cells.value.isCorrect();
  answered.value++;
  saveResult(right);
  if (right) {
    score.value++;
    combo.value++;
    maxCombo.value = Math.max(maxCombo.value, combo.value);
    cells.value.paint(true);
    sndCombo(combo.value);
    lockAdvance(320, nextWord);
  } else {
    combo.value = 0;
    cells.value.markWrong();
    sndWrong();
    revealing.value = true;
    lockAdvance(750, nextWord);
  }
}

function skip() {
  // locked 期间 advanceTimer 已在排队，再 skip 会双跳吞词
  if (phase.value !== "run" || revealing.value || locked) return;
  saveResult(null);
  nextWord();
}

/* 结果异步上报，不阻塞冲刺节奏；失败静默丢弃 */
function saveResult(right) {
  api("/result", { method: "POST", body: JSON.stringify({
    list: list.value, id: item.value.id, mode: "sprint",
    first_right: right, final_right: right, right,
    outcome: right === null ? "skipped" : "completed",
  }) }).catch(() => {});
}

function lockAdvance(ms, fn) {
  if (advanceTimer.value) clearTimeout(advanceTimer.value);
  advanceTimer.value = setTimeout(() => { if (mounted && phase.value === "run") fn(); }, ms);
}

function finish() {
  stopTimers();
  stopAudio();
  phase.value = "done";
  api("/sprint/best", { method: "POST", body: JSON.stringify({
    score: score.value, combo: maxCombo.value, total: answered.value,
  }) }).then((d) => {
    isRecord.value = Boolean(d.record);
    best.value = d.best || best.value;
  }).catch(() => {});
  if (challengeId) submitChallengeScore();
}

function restart() { location.reload(); }
function goCatalog() { location.hash = "#/catalog"; }

async function nextFrame() { await new Promise((r) => setTimeout(r, 0)); }
</script>

<template>
  <div class="sprint-page">
    <!-- 开始页 -->
    <div v-if="phase === 'start'" class="empty">
      <template v-if="loadError">
        <p role="alert" style="color:var(--red);">{{ loadError }}</p>
        <div class="controls" style="margin-top:16px;"><button class="btn primary big" @click="restart">重试</button></div>
      </template>
      <template v-else-if="challenge">
        <div style="font-size:20px;font-weight:700;margin-bottom:10px;">⚔️ 来自 {{ challenge.owner }} 的冲刺挑战</div>
        <p>{{ challenge.items.length }} 个词 · 同一条词流，看看谁的手速和耳力更强。</p>
        <div v-if="challenge.scores?.length" style="max-width:340px;margin:12px auto 0;text-align:left;">
          <div v-for="(s, i) in challenge.scores" :key="s.name + i" class="pk-row">
            <span>{{ ['🥇','🥈','🥉'][i] || (i + 1) + '.' }}</span>
            <b style="flex:1;margin-left:8px;">{{ s.name }}</b>
            <span class="combo-num">×{{ s.combo }}</span>
            <b style="width:56px;text-align:right;">{{ s.score }}</b>
          </div>
        </div>
        <div class="controls" style="margin-top:16px;">
          <button class="btn primary big" :disabled="!items.length" @click="start">开始应战</button>
          <button class="btn ghost" @click="goCatalog">返回素材库</button>
        </div>
      </template>
      <template v-else>
        <div style="font-size:20px;font-weight:700;margin-bottom:10px;">⚡ 限时冲刺</div>
        <p>{{ DURATION }} 秒内听音打词，答对越多连击越高，音调随连击上升。</p>
        <p v-if="best" style="color:var(--yellow);">个人最佳：{{ best.score }} 分 · 连击 ×{{ best.combo }}</p>
        <div class="controls" style="margin-top:16px;">
          <button class="btn primary big" :disabled="!items.length" @click="start">开始冲刺</button>
          <button class="btn ghost" @click="goCatalog">返回素材库</button>
        </div>
      </template>
    </div>

    <!-- 冲刺中 -->
    <div v-else-if="phase === 'run'" @pointerdown="focusCatch">
      <div v-if="remain <= 10" class="urg" aria-hidden="true"></div>
      <div class="practice-top">
        <span class="progress-line">得分 {{ score }} · 连击 <Transition name="combo-pop" mode="out-in"><b class="combo-num" :key="combo">×{{ combo }}</b></Transition></span>
        <span class="sprint-timer" :class="{ urgent: remain <= 10 }" role="timer" :aria-label="`剩余 ${remain} 秒`">
          <svg viewBox="0 0 52 52" aria-hidden="true">
            <circle class="st-bg" cx="26" cy="26" r="22"></circle>
            <circle class="st-fg" cx="26" cy="26" r="22"
                    :stroke-dasharray="RING_LEN" :stroke-dashoffset="RING_LEN * (1 - remain / DURATION)"></circle>
          </svg>
          <b>{{ remain }}<small>s</small></b>
        </span>
      </div>
      <div class="practice-card">
        <div class="info-line"><span id="meaning"></span></div>
        <div class="cells-wrap">
          <WordCells ref="cells" :tokens="item" :submitted="false"
            :feedback="revealing" practice-mode="assisted"></WordCells>
        </div>
        <div id="answer-line" aria-live="polite">
          <span v-if="revealing" style="color:var(--red);">✗ 答案：<span class="show-word">{{ item.text }}</span></span>
        </div>
        <div class="controls">
          <button class="btn ghost" aria-label="重播发音" @click="play">🔊</button>
          <button class="btn ghost" :disabled="revealing" aria-label="跳过当前词" @click="skip">跳过</button>
        </div>
        <div class="hint">听音打词 · 打对自动下一个 · 打错看一眼答案继续 · Esc 重听</div>
      </div>
      <input id="catch" ref="catchEl" autocomplete="off" autocorrect="off"
             autocapitalize="off" spellcheck="false" enterkeyhint="done"
             style="position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none;"
             @input="onInput" @focusout="onCatchBlur">
    </div>

    <!-- 结算 -->
    <div v-else class="empty">
      <template v-if="challenge">
        <div style="font-size:20px;font-weight:700;margin-bottom:10px;">⚔️ 战报 · 你得到 {{ score }} 分</div>
        <div style="max-width:340px;margin:12px auto;text-align:left;">
          <div v-for="(s, i) in challenge.scores || []" :key="s.name + i" class="pk-row">
            <span>{{ ['🥇','🥈','🥉'][i] || (i + 1) + '.' }}</span>
            <b style="flex:1;margin-left:8px;">{{ s.name }}</b>
            <span class="combo-num">×{{ s.combo }}</span>
            <b style="width:56px;text-align:right;">{{ s.score }}</b>
          </div>
        </div>
      </template>
      <template v-else>
        <div style="font-size:20px;font-weight:700;margin-bottom:10px;">时间到！{{ isRecord ? '🏆 新纪录！' : '' }}</div>
        <p>答对 {{ score }} 题 · 最高连击 ×{{ maxCombo }} · 作答 {{ answered }} 次</p>
        <p v-if="best" style="color:var(--yellow);">个人最佳：{{ best.score }} 分 · 连击 ×{{ best.combo }}</p>
      </template>

      <!-- 发起挑战：生成同题链接 -->
      <div v-if="!challengeId && challengeLink" class="pk-share">
        挑战链接已复制，发给好友吧：<br><code>{{ challengeLink }}</code>
      </div>
      <div class="controls" style="margin-top:16px;">
        <button class="btn primary big" @click="restart">{{ challengeId ? '再战一局' : '再来一轮' }}</button>
        <button v-if="!challengeId && !challengeLink" class="btn ghost big" :disabled="creatingChallenge" @click="createChallenge">
          {{ creatingChallenge ? '生成中…' : '⚔️ 向好友发起挑战' }}
        </button>
        <button class="btn ghost big" @click="goCatalog">返回素材库</button>
      </div>
    </div>
  </div>
</template>
