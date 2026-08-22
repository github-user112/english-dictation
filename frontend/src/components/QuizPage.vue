<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, playWord, sndRight, sndWrong } from "../lib/core";

const props = defineProps({ params: { type: Object, default: null } });

const list = ref("cet4");
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

onMounted(async () => {
  list.value = props.params?.get("list") || "cet4";
  try {
    const d = await api(`/quiz/session?list=${encodeURIComponent(list.value)}`);
    if (!mounted) return;
    questions.value = d.questions || [];
    loading.value = false;
    if (questions.value.length) play();
  } catch (err) {
    error.value = err.message || "题目加载失败";
    loading.value = false;
  }
  window.addEventListener("keydown", onKey);
});

onUnmounted(() => {
  mounted = false;
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  window.removeEventListener("keydown", onKey);
});

function play() {
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
  <div v-if="error" class="empty" role="alert"><p>{{ error }}</p><button class="btn primary" @click="restart">重试</button></div>
  <div v-else-if="loading" class="empty">加载中…</div>
  <div v-else-if="!questions.length" class="empty">没有可出题的词</div>

  <div v-else-if="q" class="quiz-page">
    <div class="practice-top">
      <span class="progress-line">{{ progress }} · 得分 {{ score }}</span>
      <span class="badge mode-badge">听音选词</span>
    </div>
    <div class="practice-card">
      <div class="info-line"><span id="meaning"></span></div>
      <div class="quiz-play">
        <button class="btn primary big" aria-label="播放单词发音" @click="play">🔊</button>
        <div class="hint">听发音，选出正确的单词 · 答对自动下一题 · 快捷键 1-4 · 空格重听</div>
      </div>
      <div id="answer-line" aria-live="polite">
        <span v-if="graded && lastRight" style="color:var(--green);">✔ 答对了！</span>
        <span v-else-if="graded" style="color:var(--red);">
          ✗ 正确答案：<span class="show-word">{{ q.text }}</span>
          <template v-if="targetOpt?.phonetic"> · {{ targetOpt.phonetic }}</template>
        </span>
      </div>
      <div class="quiz-options">
        <button v-for="(o, i) in q.options" :key="o.id" class="quiz-option"
          :class="{ picked: picked === o.id, right: graded && o.id === q.id,
                    wrong: graded && picked === o.id && o.id !== q.id }"
          :disabled="graded" :aria-label="'选项 ' + (i + 1) + '：' + o.text" @click="answer(o)">
          <b>{{ o.text }}</b>
          <small v-if="graded && o.meaning">{{ o.meaning }}</small>
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
