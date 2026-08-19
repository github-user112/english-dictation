<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, Settings } from "../lib/core";

const lists = ref([]);
const today = ref(null);
const active = ref([]);
const lessons = ref({});
const lessonErrors = ref({});
const lessonLoading = ref({});
const selectedLesson = ref({});
const loading = ref(true);
const error = ref("");
let mounted = true;
const words = computed(() => lists.value.filter((l) => l.type === "words"));
const sents = computed(() => lists.value.filter((l) => l.type === "sentences"));

onMounted(load);
onUnmounted(() => { mounted = false; });

async function load() {
  loading.value = true;
  error.value = "";
  lessons.value = {};
  lessonErrors.value = {};
  lessonLoading.value = {};
  try {
    const d = await api("/lists");
    lists.value = d.lists || [];
    today.value = d.today;
    active.value = d.active_sessions || [];
  } catch (err) {
    lists.value = [];
    active.value = [];
    error.value = err.message || "素材库加载失败";
    loading.value = false;
    return;
  }
  // 先渲染页面（词汇/句子卡片立即可见），课程数据异步加载，不阻塞首屏
  loading.value = false;
  loadLessons();
}

async function loadLessons() {
  const lessonLists = lists.value.filter((l) => l.lesson_count);
  for (const l of lessonLists) {
    lessonLoading.value[l.key] = true;
    api(`/lessons?list=${l.key}`).then((res) => {
      if (!mounted) return;
      if (res?.lessons?.length) {
        lessons.value[l.key] = res.lessons;
        const saved = Number(localStorage.getItem(`dict_lesson_${l.key}`)) || 0;
        selectedLesson.value[l.key] = res.lessons.find((x) => x.lesson === saved)?.lesson
          || res.lessons[0].lesson;
      } else {
        lessonErrors.value[l.key] = "暂无可用课程";
      }
    }).catch(() => {
      if (mounted) lessonErrors.value[l.key] = "课程加载失败，请刷新重试";
    }).finally(() => {
      if (mounted) lessonLoading.value[l.key] = false;
    });
  }
}

function pickLesson(key, ev) {
  selectedLesson.value[key] = Number(ev.target.value);
  localStorage.setItem(`dict_lesson_${key}`, String(ev.target.value));
}
function activeLesson(l) {
  const sel = selectedLesson.value[l.key];
  const mode = Settings.get().practiceMode;
  return active.value.find((s) => s.list === l.key && s.lesson === sel && s.mode === mode);
}
function lessonLabel(l, x) {
  const done = x.known + x.learning;
  const mode = Settings.get().practiceMode;
  const sess = active.value.find((s) => s.list === l.key && s.lesson === x.lesson && s.mode === mode);
  return `第 ${x.lesson} 课 · ${x.total} 句 · ${done ? `打过 ${done}` : "未开始"}${sess ? " · 继续→" : ""}`;
}

function start(l) {
  if (l.lesson_count && !selectedLesson.value[l.key]) return;
  const p = new URLSearchParams({ list: l.key, mode: Settings.get().practiceMode });
  if (l.lesson_count) p.set("lesson", selectedLesson.value[l.key]);
  location.hash = `#/${l.type === "words" ? "word" : "sentence"}?${p}`;
}
function resume(s) {
  const p = new URLSearchParams({ list: s.list, mode: s.mode, scope: s.scope || "all" });
  if (s.lesson) p.set("lesson", s.lesson);
  location.hash = `#/${lists.value.find((l) => l.key === s.list)?.type === "words" ? "word" : "sentence"}?${p}`;
}
function memorize(key) { window.location.hash = `#/memorize?list=${key}`; }
function title(key) { return lists.value.find((l) => l.key === key)?.title || key; }
</script>

<template>
  <div v-if="loading" class="empty">加载中…</div>
  <div v-else-if="error" class="empty" role="alert">
    <p>{{ error }}</p>
    <button class="btn primary" @click="load">重试</button>
  </div>
  <div v-else class="catalog-page">
    <section class="catalog-hero">
      <div>
        <span class="eyebrow">DAILY LISTENING PRACTICE</span>
        <h1>听清每一句，<br><em>写下每个词。</em></h1>
        <p>从熟悉声音开始，把英语变成一种自然反应。</p>
      </div>
      <div v-if="today" class="hero-stats" aria-label="今日学习数据">
        <div><b>{{ today.new + today.review }}</b><span>今日练习</span></div>
        <div><b>{{ today.right }}</b><span>首答正确</span></div>
        <div><b>{{ today.memorize_right }}</b><span>背诵答对</span></div>
      </div>
    </section>
    <template v-if="active.length">
      <div class="section-title"><span>继续学习</span><small>从上次停下的地方开始</small></div>
      <div class="resume-list">
        <button v-for="s in active" :key="s.id" class="resume-card" :aria-label="'继续：' + title(s.list) + '，进度 ' + (s.total - s.pending) + ' / ' + s.total" @click="resume(s)">
          <span><b>{{ title(s.list) }}</b><small>{{ s.mode === 'pure' ? '纯听写' : s.mode === 'follow' ? '跟打' : '辅助听写' }}<template v-if="s.lesson"> · 第 {{ s.lesson }} 课</template></small></span>
          <span>{{ s.total - s.pending }}/{{ s.total }} · 继续 →</span>
        </button>
      </div>
    </template>

    <div class="section-title"><span>词汇听打</span><small>先背诵，再通过听写巩固</small></div>
    <div class="card-grid word-grid">
      <div v-for="l in words" :key="l.key" class="card" :aria-label="l.title + ' 词汇听打，共 ' + l.total + ' 个'">
        <div class="name">{{ l.title }}<span class="badge type" aria-hidden="true">单词</span><span v-if="l.audio_done >= l.total" class="badge audio" aria-label="音频已就绪">✓ 音频</span></div>
        <div class="meta">共 {{ l.total }} · 已背 {{ l.memorized }} · 掌握 {{ l.known }} · 未开始 {{ l.new }}</div>
        <div class="progress" role="progressbar" :aria-valuenow="(l.total ? l.known : 0)" :aria-valuemax="l.total" :aria-label="'掌握进度：' + (l.total ? Math.round(l.known / l.total * 100) : 0) + '%'"><div :style="{width: (l.total ? l.known / l.total * 100 : 0) + '%'}"></div></div>
        <div class="card-actions">
          <button class="btn ghost sm" aria-label="背单词" @click="memorize(l.key)">📖 背单词</button>
          <button class="btn primary sm" aria-label="开始听打" @click="start(l)">👂 开始听打</button>
        </div>
      </div>
    </div>

    <div class="section-title"><span>句子听写</span><small>在完整语境里训练听力</small></div>
    <div class="card-grid sentence-grid">
      <div v-for="l in sents" :key="l.key" class="card" :aria-label="l.title + ' 句子听写，共 ' + l.total + ' 个'">
        <div class="name">{{ l.title }}<span class="badge type" aria-hidden="true">句子</span><span v-if="l.audio_done >= l.total" class="badge audio" aria-label="音频已就绪">✓ 音频</span></div>
        <div class="meta">共 {{ l.total }} · 掌握 {{ l.known }} · 未开始 {{ l.new }}</div>
        <div class="progress" role="progressbar" :aria-valuenow="l.known" :aria-valuemax="l.total" :aria-label="'掌握进度：' + (l.total ? Math.round(l.known / l.total * 100) : 0) + '%'"><div :style="{width: (l.total ? l.known / l.total * 100 : 0) + '%'}"></div></div>
        <select v-if="l.lesson_count && lessons[l.key]" v-model.number="selectedLesson[l.key]" class="lesson-select"
                aria-label="选择课程" @change="pickLesson(l.key, $event)">
          <option v-for="x in lessons[l.key]" :key="x.lesson" :value="x.lesson">{{ lessonLabel(l, x) }}</option>
        </select>
        <div v-else-if="lessonErrors[l.key]" class="meta" role="alert">{{ lessonErrors[l.key] }}</div>
        <div v-else-if="lessonLoading[l.key]" class="meta">课程加载中…</div>
        <div class="card-actions">
          <button class="btn primary sm" :disabled="Boolean(l.lesson_count && !selectedLesson[l.key])" :aria-label="(activeLesson(l) ? '继续第 ' + selectedLesson[l.key] + ' 课' : l.lesson_count ? '按课学习' : '开始听写')" @click="start(l)">👂 {{ activeLesson(l) ? `继续第 ${selectedLesson[l.key]} 课` : l.lesson_count ? '按课学习' : '开始听写' }}</button>
        </div>
      </div>
    </div>
    <div v-if="today" class="section-title today-summary">今日：新词 {{ today.new }} · 复习 {{ today.review }} · 背单词对 {{ today.memorize_right }} / 错 {{ today.memorize_wrong }} · 听打首答对 {{ today.right }} / 错 {{ today.wrong }}</div>
  </div>
</template>
