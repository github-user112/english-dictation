<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, playWord, sndWrong, sndCombo, stopAudio, audioPlaying } from "../lib/core";
import { makeTapGuard, onBlurCatch, onCharInput, onCompEnd, onCompStart } from "../lib/input";
import { ghostScore } from "../lib/progress";
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
const ghost = ref(0);          // 幽灵的实时期望分（个人最佳按均匀配速换算）
const ghostTarget = ref(0);    // 开局捕获的个人最佳分；finish 更新 best 不影响本局对比
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
const ghostDelta = computed(() => score.value - ghost.value);   // 正=领先
/* 异步挑战模式：URL 带 ?c=<挑战id> 时进入 */
const challengeId = new URLSearchParams(location.hash.split("?")[1] || "").get("c") || "";
const challenge = ref(null);
const challengeLink = ref("");
const creatingChallenge = ref(false);
const pkCreating = ref(false);
const pkError = ref("");

onMounted(async () => {
  // 同步段先挂监听：无论请求成败/卸载时序，onUnmounted 都能成对移除
  window.addEventListener("keydown", onGlobalKey, true);
  document.addEventListener("pointerdown", onDocDown, true);
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
  document.removeEventListener("pointerdown", onDocDown, true);
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
// 冲刺中持键盘：点页面任何非交互位置都不收起软键盘
const onDocDown = makeTapGuard(focusCatch, () => phase.value === "run");

async function start() {
  if (!items.value.length) return;
  phase.value = "run";
  score.value = 0; combo.value = 0; maxCombo.value = 0; answered.value = 0;
  idx.value = 0; remain.value = DURATION; revealing.value = false; locked = false;
  // 开局捕获幽灵目标分：finish() 更新 best 不影响本局的对手
  ghostTarget.value = best.value && best.value.score > 0 ? best.value.score : 0;
  ghost.value = 0;
  deadline = Date.now() + DURATION * 1000;
  tickTimer.value = setInterval(() => {
    remain.value = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    ghost.value = ghostScore(ghostTarget.value, remain.value, DURATION);
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
  const ok = phase.value === "run" && mounted;
  onBlurCatch(catchEl.value, ok ? focusCatch : null);
}
function evCompStart(ev) { onCompStart(ev, catchEl.value); }
function evCompEnd(ev) { onCompEnd(ev, catchEl.value, typeChar, () => phase.value === "run" && !revealing.value && !locked); }

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
  onCharInput(ev, typeChar, () => phase.value === "run" && !revealing.value && !locked,
    () => cells.value?.backspace());
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

function makeId() {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? uuid.replaceAll("-", "") : `${Date.now()}${Math.random().toString(36).slice(2)}`;
}

/* 结果异步上报，不阻塞冲刺节奏；失败静默丢弃 */
function saveResult(right) {
  api("/result", { method: "POST", body: JSON.stringify({
    list: list.value, id: item.value.id, mode: "sprint",
    first_right: right, final_right: right, right,
    outcome: right === null ? "skipped" : "completed",
    attempt_id: makeId(),
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

async function createPkRoom() {
  if (pkCreating.value) return;
  pkCreating.value = true;
  pkError.value = "";
  try {
    const d = await api(`/pk/room?list=${encodeURIComponent(list.value)}`, { method: "POST" });
    location.hash = `#/pk?room=${d.code}&list=${list.value}`;
  } catch (err) {
    pkError.value = err.message || "创建对战房间失败";
  } finally {
    pkCreating.value = false;
  }
}

async function nextFrame() { await new Promise((r) => setTimeout(r, 0)); }
</script>

<template>
  <div class="sprint-page">
    <!-- ============ 开始页 ============ -->
    <div v-if="phase === 'start'" class="start-wrap">
      <template v-if="loadError">
        <div class="sprint-err">
          <div class="err-emoji" aria-hidden="true">🚧</div>
          <h3>题目加载失败</h3>
          <p role="alert">{{ loadError }}</p>
          <div class="start-actions">
            <button class="btn primary big" @click="restart">重试</button>
          </div>
        </div>
      </template>

      <template v-else>
        <!-- 赛道主题：标题 + 倒计时大环 + 战绩与出发 -->
        <section class="race-hero">
          <div class="speed-lines" aria-hidden="true"></div>
          <div class="race-body">

            <!-- 左：标题 + 模式 -->
            <div class="race-left">
              <div class="race-live"><span class="pulse-dot" aria-hidden="true"></span> 冲刺进行中 · 服务端权威判分</div>
              <h1 class="race-title">🏁 限时单词听打</h1>
              <p class="race-sub">{{ DURATION }} 秒内听音打词 · 打对自动切下一个 · 连击越久音调越高</p>
              <div class="mode-row">
                <div class="mode-pill active">
                  <div class="mi" aria-hidden="true">⚡</div>
                  <div class="mt">{{ DURATION }}s</div>
                  <div class="ms">标准冲刺</div>
                </div>
              </div>
            </div>

            <!-- 中：倒计时大环 -->
            <div class="race-center">
              <div class="cd-wrap">
                <svg class="cd-svg" viewBox="0 0 52 52" aria-hidden="true">
                  <defs>
                    <linearGradient id="cd-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" style="stop-color:#58cc02"></stop>
                      <stop offset="55%" style="stop-color:#ffc800"></stop>
                      <stop offset="100%" style="stop-color:#ff9600"></stop>
                    </linearGradient>
                  </defs>
                  <circle class="cd-bg" cx="26" cy="26" r="22"></circle>
                  <circle class="cd-fg" cx="26" cy="26" r="22"
                          :stroke-dasharray="RING_LEN"
                          :stroke-dashoffset="RING_LEN * (1 - remain / DURATION)"></circle>
                  <g class="cd-ticks">
                    <line x1="26" y1="0.8" x2="26" y2="5.6"></line>
                    <line x1="51.2" y1="26" x2="46.4" y2="26"></line>
                    <line x1="26" y1="51.2" x2="26" y2="46.4"></line>
                    <line x1="0.8" y1="26" x2="5.6" y2="26"></line>
                  </g>
                </svg>
                <div class="cd-num">
                  <div class="cn-big">{{ remain }}</div>
                  <div class="cn-lbl">剩余秒数</div>
                </div>
              </div>
            </div>

            <!-- 右：战绩 + 出发 -->
            <div class="race-right">
              <div class="rr-block">
                <div class="rr-emoji" aria-hidden="true">⭐</div>
                <div class="rr-body">
                  <div class="rr-lbl">个人最佳</div>
                  <div class="rr-val gold">{{ best ? best.score : '—' }} <small>分</small></div>
                </div>
              </div>
              <div class="rr-block">
                <div class="rr-emoji" aria-hidden="true">🔥</div>
                <div class="rr-body">
                  <div class="rr-lbl">最高连击</div>
                  <div class="rr-val orange">×{{ best ? best.combo : '—' }}</div>
                </div>
              </div>
              <button class="btn-start" :disabled="!items.length" @click="start">
                ▶ 立即开始冲刺
                <span class="arrow" aria-hidden="true">🏁</span>
              </button>
            </div>

          </div>
        </section>

        <!-- 挑战对战信息 -->
        <section v-if="challenge" class="card challenge-card">
          <div class="card-title"><span class="card-icon">⚔️</span> 来自 {{ challenge.owner }} 的冲刺挑战</div>
          <p class="card-desc">{{ challenge.items.length }} 个词 · 同一条词流，看看谁的手速和耳力更强。</p>
          <div v-if="challenge.scores?.length" class="score-list">
            <div v-for="(s, i) in challenge.scores" :key="s.name + i" class="score-row">
              <span class="sr-rank">{{ ['🥇','🥈','🥉'][i] || (i + 1) + '.' }}</span>
              <b class="sr-name">{{ s.name }}</b>
              <span class="sr-combo">×{{ s.combo }}</span>
              <b class="sr-score">{{ s.score }}</b>
            </div>
          </div>
        </section>

        <!-- 玩法说明 -->
        <section v-if="!challenge" class="card start-info">
          <div class="card-title"><span class="card-icon">🎧</span> 玩法</div>
          <p class="card-desc">听音 → 打字 → 判分。打对自动切下一个词，连击不断，音调随连击逐题升高。</p>
          <ul class="rule-list">
            <li><span class="rl-ic" aria-hidden="true">🔊</span> 点绿色发音按钮或按 <kbd>Esc</kbd> 重听</li>
            <li><span class="rl-ic" aria-hidden="true">⌨️</span> 逐字母输入，打满自动提交；按 <kbd>Enter</kbd> 可手动提交</li>
            <li><span class="rl-ic" aria-hidden="true">⏭️</span> 不确定可跳过，跳过不计入连击</li>
            <li><span class="rl-ic" aria-hidden="true">✍️</span> 打错看一眼答案再继续，答错的词自动收入错词本</li>
          </ul>
        </section>

        <div class="start-actions">
          <button class="btn ghost big" @click="goCatalog">返回素材库</button>
          <button class="btn ghost big" :disabled="pkCreating || !items.length" @click="createPkRoom">
            {{ pkCreating ? "生成中…" : "⚔️ 实时PK对战" }}
          </button>
        </div>
        <p v-if="pkError" role="alert" class="err-text">{{ pkError }}</p>
      </template>
    </div>

    <!-- ============ 冲刺中 ============ -->
    <div v-else-if="phase === 'run'" class="run-wrap">
      <div v-if="remain <= 10" class="urg" aria-hidden="true"></div>

      <div class="live-card">
        <div class="live-top-bar" aria-hidden="true"></div>
        <div class="live-inner">

          <!-- 状态栏 -->
          <div class="live-head">
            <div class="live-head-l">
              <span class="live-head-emoji" aria-hidden="true">🎧</span>
              <div>
                <div class="live-head-title">正在冲刺 · 第 {{ idx + 1 }} 题</div>
                <div class="live-head-sub">听音 → 打字 → 计分 · 服务端权威判分</div>
              </div>
            </div>
            <div class="live-head-badge"><span class="pulse-dot" aria-hidden="true"></span> LIVE · {{ remain }}s</div>
          </div>

          <!-- 计分条 -->
          <div class="score-bar">
            <div class="sb-block">
              <span class="sb-emoji" aria-hidden="true">⭐</span>
              <div class="sb-body">
                <div class="sb-lbl">得分</div>
                <div class="sb-val gold">{{ score }}</div>
              </div>
            </div>
            <div class="sb-block">
              <span class="sb-emoji" aria-hidden="true">🔥</span>
              <div class="sb-body">
                <div class="sb-lbl">连击</div>
                <div class="sb-val orange">
                  <Transition name="combo-pop" mode="out-in"><b class="combo-num" :key="combo">×{{ combo }}</b></Transition>
                </div>
              </div>
            </div>

            <!-- 幽灵竞速：个人最佳按均匀配速换算的实时期望分 -->
            <span v-if="ghostTarget > 0" class="ghost-pill" :class="{ ahead: ghostDelta >= 0 }"
                  :aria-label="`幽灵期望 ${ghost} 分，你${ghostDelta >= 0 ? '领先' : '落后'} ${Math.abs(ghostDelta)} 分`">
              👻 {{ ghost }} · 你 {{ score }}
              <b>{{ ghostDelta >= 0 ? `领先 ${ghostDelta}` : `落后 ${-ghostDelta}` }}</b>
            </span>

            <!-- 倒计时环：stroke-dashoffset 随剩余时间更新 -->
            <div class="cd-mini" :class="{ urgent: remain <= 10 }" role="timer" :aria-label="`剩余 ${remain} 秒`">
              <svg viewBox="0 0 52 52" aria-hidden="true">
                <circle class="cm-bg" cx="26" cy="26" r="22"></circle>
                <circle class="cm-fg" cx="26" cy="26" r="22"
                        :stroke-dasharray="RING_LEN"
                        :stroke-dashoffset="RING_LEN * (1 - remain / DURATION)"></circle>
              </svg>
              <b class="cm-num">{{ remain }}<small>s</small></b>
            </div>
          </div>

          <!-- 当前题目 -->
          <div class="qnow">
            <button class="qnow-play" type="button" aria-label="重播发音"
                    :class="{ playing: audioPlaying }" @mousedown.prevent @click="play">🔊</button>
            <div class="qnow-body">
              <div class="qnow-label">Q{{ idx + 1 }} · 请听音拼写</div>
              <div class="info-line"><span id="meaning"></span></div>
              <div class="cells-wrap">
                <WordCells ref="cells" :tokens="item" :submitted="false"
                  :feedback="revealing" practice-mode="assisted"></WordCells>
              </div>
              <div id="answer-line" aria-live="polite">
                <span v-if="revealing" class="reveal-ans">✗ 答案：<span class="show-word">{{ item.text }}</span></span>
              </div>
            </div>
          </div>

          <!-- 时间进度 -->
          <div class="time-progress">
            <div class="time-fill" :style="{ width: (100 * (1 - remain / DURATION)) + '%' }"></div>
          </div>
          <div class="time-labels">
            <span class="tl-left">⏱️ 已过 {{ DURATION - remain }}s</span>
            <span class="tl-right">🎯 剩余 {{ remain }}s</span>
          </div>

          <!-- 连击条 -->
          <div class="combo-strip">
            <span class="cs-emoji" aria-hidden="true">🔥</span>
            <div class="cs-body">
              <div class="cs-title">{{ combo >= 10 ? '超神连击' : combo >= 5 ? '连击火热' : '连击进行中' }}</div>
              <div class="cs-sub">答错即清零 · 答对自动切下一个词</div>
            </div>
            <div class="cs-mult">
              <Transition name="combo-pop" mode="out-in"><b class="combo-num" :key="combo">{{ combo }}</b></Transition> 连
            </div>
          </div>

          <div class="controls">
            <button class="btn ghost" :class="{ playing: audioPlaying }" aria-label="重播发音" @mousedown.prevent @click="play">🔊 重听</button>
            <button class="btn ghost" :disabled="revealing" aria-label="跳过当前词" @mousedown.prevent @click="skip">⏭ 跳过</button>
          </div>
          <div class="hint">听音打词 · 打对自动下一个 · 打错看一眼答案继续 · Esc 重听</div>
        </div>
      </div>

      <input id="catch" ref="catchEl" autocomplete="off" autocorrect="off"
             autocapitalize="off" spellcheck="false" enterkeyhint="done"
             style="position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none;"
             @compositionstart="evCompStart" @compositionend="evCompEnd"
             @input="onInput" @focusout="onCatchBlur">
    </div>

    <!-- ============ 结算 ============ -->
    <div v-else>
      <section v-if="challenge" class="result-card">
        <div class="rc-emoji" aria-hidden="true">⚔️</div>
        <h2 class="rc-title">战报</h2>
        <div class="rc-big gold">{{ score }}<small>分</small></div>
        <p class="rc-sub">你得到 {{ score }} 分</p>

        <div class="score-list">
          <div v-for="(s, i) in challenge.scores || []" :key="s.name + i" class="score-row">
            <span class="sr-rank">{{ ['🥇','🥈','🥉'][i] || (i + 1) + '.' }}</span>
            <b class="sr-name">{{ s.name }}</b>
            <span class="sr-combo">×{{ s.combo }}</span>
            <b class="sr-score">{{ s.score }}</b>
          </div>
        </div>

        <div class="controls">
          <button class="btn primary big" @click="restart">{{ challengeId ? '再战一局' : '再来一轮' }}</button>
          <button class="btn ghost big" @click="goCatalog">返回素材库</button>
        </div>
      </section>

      <section v-else class="result-card">
        <div class="rc-emoji" aria-hidden="true">{{ isRecord ? '🏆' : '⏰' }}</div>
        <h2 class="rc-title">时间到！{{ isRecord ? '🏆 新纪录！' : '' }}</h2>
        <div class="rc-big gold">{{ score }}<small>分</small></div>

        <div class="rc-stats">
          <div class="rc-stat">
            <div class="rs-emoji" aria-hidden="true">✅</div>
            <div class="rs-val green">{{ score }}</div>
            <div class="rs-lbl">答对</div>
          </div>
          <div class="rc-stat">
            <div class="rs-emoji" aria-hidden="true">🔥</div>
            <div class="rs-val orange">×{{ maxCombo }}</div>
            <div class="rs-lbl">最高连击</div>
          </div>
          <div class="rc-stat">
            <div class="rs-emoji" aria-hidden="true">⌨️</div>
            <div class="rs-val blue">{{ answered }}</div>
            <div class="rs-lbl">作答次数</div>
          </div>
        </div>

        <!-- 幽灵竞速结果：ghostTarget 是开局捕获的个人最佳 -->
        <p v-if="ghostTarget > 0" class="ghost-verdict" :class="{ ahead: score >= ghostTarget }">
          {{ score >= ghostTarget
            ? (score === ghostTarget ? `👻 与幽灵战平（${ghostTarget} 分）` : `👻 胜过幽灵！超出 ${score - ghostTarget} 分`)
            : `👻 惜败幽灵，还差 ${ghostTarget - score} 分` }}
        </p>

        <p v-if="best" class="best-line">📌 个人最佳：{{ best.score }} 分 · 连击 ×{{ best.combo }}</p>

        <!-- 发起挑战：生成同题链接 -->
        <div v-if="!challengeId && challengeLink" class="pk-share">
          挑战链接已复制，发给好友吧：<br><code>{{ challengeLink }}</code>
        </div>

        <div class="controls">
          <button class="btn primary big" @click="restart">{{ challengeId ? '再战一局' : '再来一轮' }}</button>
          <button v-if="!challengeId && !challengeLink" class="btn ghost big" :disabled="creatingChallenge" @click="createChallenge">
            {{ creatingChallenge ? '生成中…' : '⚔️ 向好友发起挑战' }}
          </button>
          <button class="btn ghost big" @click="goCatalog">返回素材库</button>
        </div>
      </section>
    </div>
  </div>
</template>
