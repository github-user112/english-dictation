<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, playWord, sndRight, sndWrong } from "../lib/core";

const props = defineProps({ params: { type: Object, default: null } });

const KINDS = [
  { k: "audio_en", label: "听音选词" },   // 音→形
  { k: "en_zh", label: "听词选义" },      // 音→义
  { k: "zh_en", label: "看义选词" },      // 义→形
];
const HINTS = {
  audio_en: "听发音，选出正确的单词 · 答对自动下一题 · 快捷键 1-4 · 空格重听",
  en_zh: "听发音，选出正确的中文意思 · 答对自动下一题 · 快捷键 1-4 · 空格重听",
  zh_en: "看中文意思，选出正确的单词 · 答对自动下一题 · 快捷键 1-4",
};

const list = ref("cet4");
const kind = ref("audio_en");
const questions = ref([]);
const qi = ref(0);
const picked = ref(null);      // 已选中的 option id
const graded = ref(false);
const nextTimer = ref(null);
const lastRight = ref(false);
const score = ref(0);
const loading = ref(true);
const error = ref("");
let mounted = true;

const q = computed(() => questions.value[qi.value] || null);
const targetOpt = computed(() =>
  q.value ? q.value.options.find((o) => o.id === q.value.id) || null : null);
const progress = computed(() => `${qi.value + 1} / ${questions.value.length}`);
const accuracy = computed(() =>
  questions.value.length ? Math.round((score.value / questions.value.length) * 100) : 0);
// 义→形 题型：作答前不能出声（会泄露答案）
const audible = computed(() => kind.value !== "zh_en");

onMounted(async () => {
  // 同步段先挂监听：请求失败/卸载时序都不会留下僵尸监听器
  window.addEventListener("keydown", onKey);
  list.value = props.params?.get("list") || "cet4";
  const saved = localStorage.getItem("dict_quiz_kind");
  if (saved && HINTS[saved]) kind.value = saved;
  const fromUrl = props.params?.get("kind");
  if (fromUrl && HINTS[fromUrl]) kind.value = fromUrl;
  await load();
});

onUnmounted(() => {
  mounted = false;
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  window.removeEventListener("keydown", onKey);
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const d = await api(`/quiz/session?list=${encodeURIComponent(list.value)}&kind=${kind.value}`);
    if (!mounted) return;
    questions.value = d.questions || [];
    qi.value = 0;
    picked.value = null;
    graded.value = false;
    lastRight.value = false;
    score.value = 0;
    loading.value = false;
    if (questions.value.length) play();
  } catch (err) {
    if (!mounted) return;
    error.value = err.message || "题目加载失败";
    loading.value = false;
  }
}

function switchKind(k) {
  if (k === kind.value || !HINTS[k]) return;
  kind.value = k;
  localStorage.setItem("dict_quiz_kind", k);
  load();
}

function play() {
  if (!audible.value) return;   // 看义选词：作答前不出声
  if (q.value) playWord(q.value);
}

function onKey(ev) {
  if (graded.value && ev.key === "Enter") { ev.preventDefault(); next(); return; }
  if (!graded.value && ["1", "2", "3", "4"].includes(ev.key)) {
    const idx = Number(ev.key) - 1;
    if (q.value && q.value.options[idx]) answer(q.value.options[idx]);
    return;
  }
  if (ev.key === "Escape" || ev.key === " ") { ev.preventDefault(); play(); }
}

function answer(opt) {
  if (graded.value || !q.value) return;
  graded.value = true;
  picked.value = opt.id;
  lastRight.value = opt.id === q.value.id;
  if (lastRight.value) {
    score.value++;
    sndRight();
    // 选对 1 秒后自动进下一题；期间手动触发过下一题的话 graded 已复位，定时器不会重复跳
    if (nextTimer.value) clearTimeout(nextTimer.value);
    nextTimer.value = setTimeout(() => { if (mounted && graded.value) next(); }, 1000);
  } else {
    sndWrong();
    if (kind.value === "zh_en") playWord(q.value);   // 义→形答错时朗读单词加深印象（无自动跳，播得完整）
  }
  // 计入掌握度与错词本：走旧版结果通道，失败静默（练习数据不阻塞下一题）
  api("/result", { method: "POST", body: JSON.stringify({
    list: list.value, id: q.value.id, mode: "quiz",
    first_right: lastRight.value, final_right: lastRight.value,
    right: lastRight.value, outcome: "completed",
  }) }).catch(() => {});
}

function next() {
  if (!graded.value) return;
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  qi.value++;               // 越过末尾后 q 为 null，模板切换到结算页
  graded.value = false;
  picked.value = null;
  if (q.value) play();
}

function restart() { location.reload(); }
function goCatalog() { location.hash = "#/catalog"; }
</script>

<template>
  <div v-if="error && !questions.length" class="empty" role="alert"><p>{{ error }}</p><button class="btn primary" @click="restart">重试</button></div>
  <div v-else-if="loading" class="empty">加载中…</div>
  <div v-else-if="!questions.length" class="empty">没有可出题的词</div>

  <div v-else-if="q" class="quiz-page">
    <div class="practice-top">
      <span class="progress-line">{{ progress }} · 得分 {{ score }}</span>
      <span class="badge mode-badge">{{ KINDS.find((x) => x.k === kind)?.label }}</span>
    </div>
    <div class="practice-card">
      <div class="quiz-kinds" role="tablist" aria-label="题型切换">
        <button v-for="x in KINDS" :key="x.k" class="btn ghost sm"
          :class="{ primary: kind === x.k }" :aria-pressed="kind === x.k"
          @click="switchKind(x.k)">{{ x.label }}</button>
      </div>
      <div id="answer-line" aria-live="polite">
        <span v-if="graded && lastRight" style="color:var(--green);">✔ 答对了！</span>
        <span v-else-if="graded" style="color:var(--red);">
          ✗ 正确答案：<span class="show-word">{{ q.text }}</span>
          <template v-if="targetOpt?.phonetic"> · {{ targetOpt.phonetic }}</template>
          <template v-if="targetOpt?.meaning && kind !== 'en_zh'"> · {{ targetOpt.meaning }}</template>
        </span>
      </div>
      <!-- 看义选词：题干是中文释义 -->
      <div v-if="kind === 'zh_en'" class="quiz-prompt">{{ targetOpt?.meaning || '（该词暂无释义）' }}</div>
      <div v-else class="quiz-play">
        <button class="btn primary big" aria-label="播放单词发音" @click="play">🔊</button>
      </div>
      <div class="hint">{{ HINTS[kind] }}</div>
      <div class="quiz-options">
        <button v-for="(o, i) in q.options" :key="o.id" class="quiz-option"
          :class="{ picked: picked === o.id, right: graded && o.id === q.id,
                    wrong: graded && picked === o.id && o.id !== q.id }"
          :disabled="graded" :aria-label="'选项 ' + (i + 1) + '：' + (kind === 'en_zh' ? o.meaning : o.text)"
          @click="answer(o)">
          <b>{{ kind === 'en_zh' ? (o.meaning || '（无释义）') : o.text }}</b>
          <small v-if="graded">{{ kind === 'en_zh' ? o.text : o.meaning }}</small>
        </button>
      </div>
      <div class="controls" v-if="graded && !lastRight">
        <button class="btn primary big" @click="next">{{ qi + 1 >= questions.length ? '查看结果' : '下一题 →' }}</button>
      </div>
    </div>
  </div>

  <div v-else class="empty">
    <div style="font-size:20px;font-weight:700;margin-bottom:10px;">本轮完成 🎉</div>
    <p>答对 {{ score }} / {{ questions.length }} · 正确率 {{ accuracy }}%</p>
    <div class="controls" style="margin-top:16px;">
      <button class="btn primary big" @click="restart">再来一轮</button>
      <button class="btn ghost" @click="goCatalog">返回素材库</button>
    </div>
  </div>
</template>
