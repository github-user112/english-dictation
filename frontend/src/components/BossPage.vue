<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, playWord, sndWrong, sndCombo, stopAudio } from "../lib/core";
import WordCells from "./WordCells.vue";

const HEARTS = 3;

const phase = ref("start");    // start | run | done
const items = ref([]);
const idx = ref(0);
const hp = ref(0);             // Boss 血量 = 未斩落的词数
const hearts = ref(HEARTS);
const score = ref(0);
const combo = ref(0);
const answers = ref([]);       // [{id,right}] id 唯一，战毕一次性提交
const revealing = ref(false);
const outcome = ref("");       // win | lose | flee
const result = ref(null);      // 服务端结算 {score,total,cleared,wrong_remaining}
const loadError = ref("");
const hurtFx = ref(false);     // Boss 受击抖动
const advanceTimer = ref(null);
const cells = ref(null);
const catchEl = ref(null);
const focusTimers = ref([]);
let mounted = true;
let locked = false;            // 提交→切词之间的硬锁：防长按 Enter 重复计分/双跳词

const item = computed(() => items.value[idx.value] || null);
const totalHp = computed(() => items.value.length);
const hpPct = computed(() => (totalHp.value ? Math.round((hp.value / totalHp.value) * 100) : 0));
const heartsLine = computed(() =>
  "❤️".repeat(hearts.value) + "🖤".repeat(Math.max(0, HEARTS - hearts.value)));

onMounted(async () => {
  window.addEventListener("keydown", onGlobalKey, true);
  try {
    const d = await api("/boss/session");
    if (!mounted) return;
    items.value = d.items || [];
    hp.value = items.value.length;
  } catch (err) {
    if (mounted) loadError.value = err.message || "Boss 集结失败";
  }
});

onUnmounted(() => {
  mounted = false;
  stopTimers();
  stopAudio();
  window.removeEventListener("keydown", onGlobalKey, true);
});

function stopTimers() {
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
  idx.value = 0; hp.value = items.value.length; hearts.value = HEARTS;
  score.value = 0; combo.value = 0; answers.value = [];
  revealing.value = false; result.value = null; locked = false;
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
  if (idx.value + 1 >= items.value.length) return finish("flee");   // 部队打完，Boss 残血逃脱
  idx.value++;
  cells.value?.reset();
  play();
  // 不重挂载 WordCells（靠组件内 watch 重置），避免移动端 DOM 重建把
  // 隐藏输入框 blur 掉、软键盘收起；这里只做一次补偿聚焦。
  focusCatch();
}

function onCatchBlur() {
  // 焦点守护：战斗中输入框失焦（按钮点击等）立刻补聚焦，保住软键盘
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
  answers.value.push({ id: item.value.id, right });
  if (right) {
    score.value++; combo.value++; hp.value--;
    cells.value.paint(true);
    sndCombo(combo.value);
    hurtFx.value = true;
    setTimeout(() => { hurtFx.value = false; }, 360);
    const won = hp.value <= 0;
    lockAdvance(won ? 520 : 340, () => (won ? finish("win") : nextWord()));
  } else {
    combo.value = 0; hearts.value--;
    cells.value.markWrong();
    sndWrong();
    revealing.value = true;
    const lost = hearts.value <= 0;
    lockAdvance(lost ? 950 : 780, () => (lost ? finish("lose") : nextWord()));
  }
}

/* 撤退：保留已有战果提前结算 */
function retreat() {
  if (phase.value !== "run" || locked) return;
  locked = true;
  finish("flee");
}

function lockAdvance(ms, fn) {
  if (advanceTimer.value) clearTimeout(advanceTimer.value);
  advanceTimer.value = setTimeout(() => { if (mounted && phase.value === "run") fn(); }, ms);
}

async function finish(kind) {
  if (kind) outcome.value = kind;
  else outcome.value = outcome.value || "flee";
  if (advanceTimer.value) { clearTimeout(advanceTimer.value); advanceTimer.value = null; }
  stopAudio();
  phase.value = "done";
  if (!answers.value.length) return;   // 不战而退：没有可记账的答案
  try {
    const d = await api("/boss/result", {
      method: "POST",
      body: JSON.stringify({ answers: answers.value }),
    });
    result.value = d;
    window.dispatchEvent(new CustomEvent("profile-changed"));
  } catch { /* 结算失败不影响战报展示 */ }
}

function restart() { location.reload(); }
function goWrong() { location.hash = "#/wrong"; }

async function nextFrame() { await new Promise((r) => setTimeout(r, 0)); }
</script>

<template>
  <div class="boss-page">
    <!-- 开始页 -->
    <div v-if="phase === 'start'" class="empty">
      <template v-if="loadError">
        <p role="alert" style="color:var(--red);">{{ loadError }}</p>
        <div class="controls" style="margin-top:16px;"><button class="btn primary big" @click="restart">重试</button></div>
      </template>
      <template v-else-if="!items.length">
        <div style="font-size:44px;margin-bottom:8px;">🎉</div>
        <div style="font-size:20px;font-weight:700;margin-bottom:10px;">错词本已清空</div>
        <p>Boss 无兵可用——去素材库练新词吧。</p>
        <div class="controls" style="margin-top:16px;">
          <button class="btn primary big" @click="goWrong">返回错词本</button>
        </div>
      </template>
      <template v-else>
        <div style="font-size:52px;" aria-hidden="true">🐲</div>
        <div style="font-size:20px;font-weight:700;margin-bottom:10px;">错词 Boss 战</div>
        <p>{{ items.length }} 个最常错的词盘踞成一只 Boss——它的血条就是它们。</p>
        <p>听音打词：打对扣它一点血、该词从错词本除名；打错扣你一颗心。你有 {{ HEARTS }} 颗心。</p>
        <div class="boss-army" aria-label="本次讨伐的词">
          <span v-for="it in items" :key="it.list + it.id" class="army-chip">
            {{ it.text }}<i>×{{ it.wrong_count }}</i>
          </span>
        </div>
        <div class="controls" style="margin-top:16px;">
          <button class="btn primary big" @click="start">⚔️ 开始讨伐</button>
          <button class="btn ghost" @click="goWrong">返回错词本</button>
        </div>
      </template>
    </div>

    <!-- 战斗中 -->
    <div v-else-if="phase === 'run'" @pointerdown="focusCatch">
      <div class="practice-top">
        <span class="hearts" role="img"
              :aria-label="`剩余 ${hearts} 颗心`">{{ heartsLine }}</span>
        <span class="progress-line">得分 {{ score }} · 连击 ×{{ combo }}</span>
      </div>
      <div class="boss-panel">
        <div class="boss-art" :class="{ hurt: hurtFx }" aria-hidden="true">🐲</div>
        <div class="boss-hp" role="progressbar" :aria-valuenow="hp" aria-valuemin="0"
             :aria-valuemax="totalHp" :aria-label="`Boss 血量 ${hp}/${totalHp}`">
          <i :style="{ width: hpPct + '%' }"></i>
        </div>
        <small class="boss-hp-num">{{ hp }} / {{ totalHp }}</small>
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
          <button class="btn ghost" :disabled="locked" aria-label="撤退并结算" @click="retreat">🏳️ 撤退</button>
        </div>
        <div class="hint">听音打词 · 打对扣 Boss 血并从错词本除名 · 打错扣一颗心 · Esc 重听</div>
      </div>
      <input id="catch" ref="catchEl" autocomplete="off" autocorrect="off"
             autocapitalize="off" spellcheck="false" enterkeyhint="done"
             style="position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none;"
             @input="onInput" @focusout="onCatchBlur">
    </div>

    <!-- 战报 -->
    <div v-else class="empty">
      <div class="boss-verdict" :class="outcome" aria-live="polite">
        <span class="bv-icon" aria-hidden="true">{{ outcome === 'win' ? '🏆' : outcome === 'lose' ? '💀' : '🏳️' }}</span>
        <b>{{ outcome === 'win' ? 'Boss 击破！' : outcome === 'lose' ? '心力耗尽……' : '鸣金收兵' }}</b>
        <p v-if="outcome === 'lose'">Boss 逃回错词本了，喘口气再来讨伐。</p>
        <p v-else-if="outcome === 'flee'">残血 Boss 逃走了，下次它还会回来。</p>
      </div>
      <p>答对 {{ score }} / {{ answers.length }} 题
        <template v-if="result">· 斩落 {{ result.cleared }} 词（已从错词本除名）</template></p>
      <p v-if="result && result.wrong_remaining > 0" style="color:var(--yellow);">
        错词本还剩 {{ result.wrong_remaining }} 个词等着被讨伐</p>
      <p v-if="result && result.wrong_remaining === 0" style="color:var(--green);">🎉 错词本全清！</p>
      <div class="controls" style="margin-top:16px;">
        <button class="btn primary big" @click="restart">再战一局</button>
        <button class="btn ghost big" @click="goWrong">返回错词本</button>
      </div>
    </div>
  </div>
</template>
