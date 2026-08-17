<script setup>
import { computed, onMounted, ref } from "vue";
import { api, Settings } from "../lib/core";

const lists = ref([]);
const today = ref(null);
const active = ref([]);
const lessons = ref({});
const selectedLesson = ref({});
const words = computed(() => lists.value.filter((l) => l.type === "words"));
const sents = computed(() => lists.value.filter((l) => l.type === "sentences"));

onMounted(async () => {
  const d = await api("/lists");
  lists.value = d.lists || [];
  today.value = d.today;
  active.value = d.active_sessions || [];
  await Promise.allSettled(lists.value.filter((l) => l.lesson_count).map(async (l) => {
    try {
      const r = await api(`/lessons?list=${l.key}`);
      lessons.value[l.key] = r.lessons || [];
      // 记住上次选的课（localStorage），没有则默认第一课
      const saved = Number(localStorage.getItem(`dict_lesson_${l.key}`)) || 0;
      selectedLesson.value[l.key] = r.lessons?.find((x) => x.lesson === saved)?.lesson
        || r.lessons?.[0]?.lesson || 1;
    } catch { /* 单个素材课程列表加载失败不阻塞页面 */ }
  }));
});

function pickLesson(key, ev) {
  selectedLesson.value[key] = Number(ev.target.value);
  localStorage.setItem(`dict_lesson_${key}`, String(ev.target.value));
}
function activeLesson(l) {
  const sel = selectedLesson.value[l.key];
  return active.value.find((s) => s.list === l.key && s.lesson === sel);
}
function lessonLabel(l, x) {
  const done = x.known + x.learning;
  const active = active.value.find((s) => s.list === l.key && s.lesson === x.lesson);
  return `第 ${x.lesson} 课 · ${x.total} 句 · ${done ? `打过 ${done}` : "未开始"}${active ? " · 继续→" : ""}`;
}

function start(l) {
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
  <div>
    <template v-if="active.length">
      <div class="section-title">继续今日任务</div>
      <div class="resume-list">
        <button v-for="s in active" :key="s.id" class="resume-card" :aria-label="'继续：' + title(s.list) + '，进度 ' + (s.total - s.pending) + ' / ' + s.total" @click="resume(s)">
          <span><b>{{ title(s.list) }}</b><small>{{ s.mode === 'pure' ? '纯听写' : s.mode === 'follow' ? '跟打' : '辅助听写' }}<template v-if="s.lesson"> · 第 {{ s.lesson }} 课</template></small></span>
          <span>{{ s.total - s.pending }}/{{ s.total }} · 继续 →</span>
        </button>
      </div>
    </template>

    <div class="section-title">词汇听打</div>
    <div class="card-grid">
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

    <div class="section-title">句子听写</div>
    <div class="card-grid">
      <div v-for="l in sents" :key="l.key" class="card" :aria-label="l.title + ' 句子听写，共 ' + l.total + ' 个'">
        <div class="name">{{ l.title }}<span class="badge type" aria-hidden="true">句子</span><span v-if="l.audio_done >= l.total" class="badge audio" aria-label="音频已就绪">✓ 音频</span></div>
        <div class="meta">共 {{ l.total }} · 掌握 {{ l.known }} · 未开始 {{ l.new }}</div>
        <div class="progress" role="progressbar" :aria-valuenow="l.known" :aria-valuemax="l.total" :aria-label="'掌握进度：' + (l.total ? Math.round(l.known / l.total * 100) : 0) + '%'"><div :style="{width: (l.total ? l.known / l.total * 100 : 0) + '%'}"></div></div>
        <select v-if="l.lesson_count" v-model.number="selectedLesson[l.key]" class="lesson-select"
                aria-label="选择课程" @change="pickLesson(l.key, $event)">
          <option v-for="x in lessons[l.key]" :key="x.lesson" :value="x.lesson">{{ lessonLabel(l.key, x) }}</option>
        </select>
        <div class="card-actions">
          <button class="btn primary sm" :aria-label="(activeLesson(l) ? '继续第 ' + selectedLesson[l.key] + ' 课' : l.lesson_count ? '按课学习' : '开始听写')" @click="start(l)">👂 {{ activeLesson(l) ? `继续第 ${selectedLesson[l.key]} 课` : l.lesson_count ? '按课学习' : '开始听写' }}</button>
        </div>
      </div>
    </div>
    <div v-if="today" class="section-title today-summary">今日：新词 {{ today.new }} · 复习 {{ today.review }} · 背单词对 {{ today.memorize_right }} / 错 {{ today.memorize_wrong }} · 听打首答对 {{ today.right }} / 错 {{ today.wrong }}</div>
  </div>
</template>
