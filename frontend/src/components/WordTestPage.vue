<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { api, playWord, playUrl, sndRight, sndWrong, stopAudio } from "../lib/core";
import { Account } from "../lib/account";
import { Profile, refreshProfile } from "../lib/profile";
import ShareCard from "./ShareCard.vue";

const props = defineProps({ params: { type: Object, default: null } });

const phase = ref("idle");       // idle | testing | done
const question = ref(null);
const selected = ref(null);       // 选中的选项文本
const submitting = ref(false);
const level = ref(9);
const answered = ref(0);
const consecutiveWrong = ref(0);
const usedIds = ref("");
const correctCount = ref(0);      // 已答对数：随请求回传，服务端累计落表
const history = ref([]);          // 答题历史 [{word, right}]
const error = ref("");

const result = ref(null);
const shareOpen = ref(false);
const historyList = ref([]);
const loading = ref(false);

const PROGRESS_LEN = 2 * Math.PI * 22;
const MAX_QUESTIONS = 25;

const progressPct = () => Math.min(100, Math.round(answered.value / MAX_QUESTIONS * 100));

const CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"];
const CEFR_TITLE = { A1: "入门", A2: "基础", B1: "中级", B2: "中高级", C1: "高级", C2: "精通" };
const CEFR_COLOR = { A1: "var(--green)", A2: "var(--green)", B1: "var(--accent)", B2: "var(--accent-strong)", C1: "var(--red)", C2: "var(--red)" };

onMounted(async () => {
  await loadHistory();
});

onUnmounted(() => {
  stopAudio();
});

function usedSet() {
  return new Set(usedIds.value ? usedIds.value.split(",") : []);
}

async function start() {
  error.value = "";
  question.value = null;
  selected.value = null;
  submitting.value = false;
  level.value = 9;
  answered.value = 0;
  consecutiveWrong.value = 0;
  usedIds.value = "";
  correctCount.value = 0;
  history.value = [];
  result.value = null;

  try {
    const d = await api(`/wordtest/question?level=${level.value}&answered=${answered.value}&consecutive_wrong=${consecutiveWrong.value}&used_ids=${encodeURIComponent(usedIds.value)}`);
    if (d.done) {
      phase.value = "done";
      result.value = { cefr: "A1", word_count: 0, level: level.value, answered: 0, correct: 0 };
      return;
    }
    question.value = d.question;
    phase.value = "testing";
    play();
  } catch (err) {
    error.value = err.message || "开局失败";
  }
}

function play() {
  if (!question.value) return;
  if (question.value.audio) {
    playUrl(question.value.audio);
  } else {
    playWord({ text: question.value.word });
  }
}

async function answer(opt) {
  if (submitting.value || !question.value) return;
  selected.value = opt.text;
  submitting.value = true;

  try {
    const d = await api("/wordtest/answer", {
      method: "POST",
      body: JSON.stringify({
        option: opt.text,
        level: level.value,
        answered: answered.value,
        consecutive_wrong: consecutiveWrong.value,
        correct_count: correctCount.value,
        used_ids: usedIds.value,
      }),
    });

    const right = d.right;
    history.value.push({ word: question.value.word, right });
    if (right) {
      correctCount.value++;
      sndRight();
    } else {
      sndWrong();
    }

    if (d.done) {
      result.value = {
        cefr: d.cefr,
        cefr_title: d.cefr_title,
        word_count: d.word_count,
        level: d.level,
        answered: d.answered,
        correct: d.correct_count,
      };
      phase.value = "done";
      loadHistory();
    } else {
      level.value = d.level;
      answered.value = d.answered;
      consecutiveWrong.value = d.consecutive_wrong;
      const ids = usedSet();
      ids.add(question.value.id);
      usedIds.value = Array.from(ids).join(",");
      question.value = d.question;
      selected.value = null;
      submitting.value = false;   // 解锁下一题：成功路径不复位会永远 disabled
      await play();
    }
  } catch (err) {
    error.value = err.message || "答题失败";
    submitting.value = false;
  }
}

async function loadHistory() {
  try {
    const d = await api("/wordtest/history");
    historyList.value = d.history || [];
  } catch { /* 旧后端无此接口时静默 */ }
}

function sharePayload() {
  return {
    name: Account.username || "游客",
    cefr: result.value?.cefr || "?",
    cefrTitle: result.value?.cefr_title || "",
    wordCount: result.value?.word_count || 0,
    level: result.value?.level || 0,
    answered: result.value?.answered || 0,
    correct: result.value?.correct || 0,
    link: location.origin + "/#/",
  };
}

function goCatalog() {
  location.hash = "#/catalog";
}
</script>

<template>
<div class="wt-page">
  <!-- 开始页 -->
  <div v-if="phase === 'idle'" class="empty">
    <div style="font-size:22px;font-weight:700;margin-bottom:12px;">📊 词汇量等级测试</div>
    <p>25 道「听音选义」题，难度随答对自动上升、答错自动下降。</p>
    <p>最终根据你达到的难度等级，估算 CEFR 等级与可识别词汇量。</p>

    <div class="stat-cards" style="margin:20px 0 12px;">
      <div class="stat-card" v-for="cefr in CEFR_ORDER" :key="cefr">
        <div class="num" :style="{ color: CEFR_COLOR[cefr] }">{{ cefr }}</div>
        <div class="lab">{{ CEFR_TITLE[cefr] }}</div>
      </div>
    </div>

    <div class="controls" style="margin-top:16px;">
      <button class="btn primary big" @click="start">开始测试</button>
      <button class="btn ghost" @click="goCatalog">返回素材库</button>
    </div>

    <div v-if="historyList.length" class="history-box">
      <div class="section-title"><span>最近测试</span><small>{{ historyList.length }} 次</small></div>
      <div v-for="h in historyList.slice(0, 5)" :key="h.created_at" class="history-row">
        <span class="wt-cefr" :style="{ color: CEFR_COLOR[h.cefr] || 'var(--accent)' }">{{ h.cefr }}</span>
        <span>{{ CEFR_TITLE[h.cefr] || h.cefr }}</span>
        <span>≈ {{ h.word_count }} 词</span>
        <span class="hist-meta">{{ h.created_at.slice(5, 10) }}</span>
      </div>
    </div>

    <p v-if="error" role="alert" style="color:var(--red);margin-top:12px;">{{ error }}</p>
  </div>

  <!-- 测试中 -->
  <div v-else-if="phase === 'testing'">
    <div class="practice-top">
      <span class="progress-line">
        难度 <b>L{{ level }}</b> · 第 {{ answered + 1 }} / {{ MAX_QUESTIONS }} 题
      </span>
      <svg class="wt-bar" viewBox="0 0 52 52" aria-hidden="true">
        <circle class="wt-bg" cx="26" cy="26" r="22"/>
        <circle class="wt-fg" cx="26" cy="26" r="22"
          :stroke-dasharray="PROGRESS_LEN"
          :stroke-dashoffset="PROGRESS_LEN * (1 - progressPct() / 100)"/>
      </svg>
    </div>

    <div class="practice-card" style="margin-top:12px;">
      <div class="wt-word">{{ question?.word || "" }}</div>
      <div class="wt-phonetic">{{ question?.phonetic || "" }}</div>
      <div class="controls" style="margin:8px 0 12px;">
        <button class="btn ghost" aria-label="重播发音" @click="play">🔊 重听</button>
      </div>

      <div class="wt-options">
        <button v-for="(opt, i) in question?.options || []" :key="opt.text"
          class="btn wt-option"
          :class="{ selected: selected === opt.text }"
          :disabled="submitting"
          @click="answer(opt)">
          <span class="wt-opt-letter">{{ String.fromCharCode(65 + i) }}</span>
          {{ opt.text }}
        </button>
      </div>

      <div class="wt-hint">
        <span>📈 答对难度+1</span><span>📉 答错难度-1</span>
      </div>

      <div class="wt-history" v-if="history.length > 0">
        <span v-for="h in history.slice(-8)" :key="h.word">
          <span :class="h.right ? 'wt-h-right' : 'wt-h-wrong'">
            {{ h.word }}
          </span>
        </span>
      </div>
    </div>

    <p v-if="error" role="alert" style="color:var(--red);margin-top:8px;">{{ error }}</p>
  </div>

  <!-- 结果页 -->
  <div v-else-if="phase === 'done' && result" class="empty">
    <div class="wt-result">
      <div class="wt-cefr-big" :style="{ color: CEFR_COLOR[result.cefr] || 'var(--accent)' }">
        {{ result.cefr }}
      </div>
      <div class="wt-cefr-title">{{ result.cefr_title }} · ≈ {{ result.word_count }} 词</div>
      <div class="wt-result-stats">
        <div class="wt-stat"><div class="wt-stat-num">{{ result.correct }}</div><div class="wt-stat-lab">答对</div></div>
        <div class="wt-stat"><div class="wt-stat-num">{{ result.answered - result.correct }}</div><div class="wt-stat-lab">答错</div></div>
        <div class="wt-stat"><div class="wt-stat-num">L{{ result.level }}</div><div class="wt-stat-lab">最终难度</div></div>
      </div>
    </div>

    <div class="controls" style="margin-top:18px;">
      <button class="btn primary big" @click="start">🔄 再测一次</button>
      <button class="btn ghost big" @click="shareOpen = true">📤 分享结果</button>
    </div>
    <div class="controls" style="margin-top:6px;">
      <button class="btn ghost" @click="goCatalog">返回素材库</button>
    </div>
  </div>

  <ShareCard v-if="result" :open="shareOpen" kind="wordtest" :payload="sharePayload()" @close="shareOpen = false" />
</div>
</template>

<style scoped>
.wt-page { display: flex; flex-direction: column; align-items: center; min-height: calc(100vh - 120px); padding: 20px 12px; }

.wt-bar { width: 36px; height: 36px; margin-left: 10px; }
.wt-bar .wt-bg, .wt-bar .wt-fg { fill: none; stroke-width: 4; }
.wt-bar .wt-bg { stroke: var(--panel3); }
.wt-bar .wt-fg { stroke: var(--accent); stroke-linecap: round; transform: rotate(-90deg); transform-origin: 26px 26px; transition: stroke-dashoffset 0.4s var(--ease-out); }

.wt-word { font-size: 34px; font-weight: 700; text-align: center; margin: 4px 0 2px; }
.wt-phonetic { font-size: 16px; color: var(--dim); text-align: center; margin-bottom: 4px; }

.wt-options { display: grid; grid-template-columns: 1fr; gap: 8px; margin-top: 8px; }
.wt-option { display: flex; align-items: center; gap: 10px; padding: 12px 14px; font-size: 15.5px; text-align: left; min-height: 46px; }
.wt-option.selected { outline: 2px solid var(--accent); outline-offset: -2px; }
.wt-opt-letter { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 50%; background: var(--panel3); font-weight: 700; font-size: 13px; color: var(--accent-strong); flex: none; }

.wt-hint { display: flex; justify-content: center; gap: 16px; margin-top: 10px; font-size: 12px; color: var(--dim); }

.wt-history { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--border); max-width: 360px; }
.wt-history span { font-size: 13px; padding: 2px 8px; border-radius: 10px; }
.wt-h-right { background: var(--panel3); color: var(--green); }
.wt-h-wrong { background: var(--panel3); color: var(--red); }

.wt-result { text-align: center; padding: 20px 0; }
.wt-cefr-big { font-size: 72px; font-weight: 800; line-height: 1.1; }
.wt-cefr-title { font-size: 18px; color: var(--dim); margin-top: 4px; }
.wt-result-stats { display: flex; justify-content: center; gap: 24px; margin-top: 18px; }
.wt-stat-num { font-size: 28px; font-weight: 700; color: var(--accent-strong); }
.wt-stat-lab { font-size: 12px; color: var(--dim); }

.history-box { width: 100%; max-width: 420px; margin-top: 12px; }
.history-row { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px dashed var(--border); font-size: 14px; }
.history-row:last-child { border-bottom: none; }
.wt-cefr { font-weight: 700; min-width: 30px; }
.hist-meta { margin-left: auto; color: var(--dim); font-size: 12px; }
</style>