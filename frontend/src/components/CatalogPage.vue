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
  await Promise.all(lists.value.filter((l) => l.lesson_count).map(async (l) => {
    const r = await api(`/lessons?list=${l.key}`);
    lessons.value[l.key] = r.lessons || [];
    selectedLesson.value[l.key] = r.lessons?.[0]?.lesson || 1;
  }));
});

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
function title(key) { return lists.value.find((l) => l.key === key)?.title || key; }
</script>

<template>
  <div>
    <template v-if="active.length">
      <div class="section-title">继续今日任务</div>
      <div class="resume-list">
        <button v-for="s in active" :key="s.id" class="resume-card" @click="resume(s)">
          <span><b>{{ title(s.list) }}</b><small>{{ s.mode === 'pure' ? '纯听写' : s.mode === 'follow' ? '跟打' : '辅助听写' }}<template v-if="s.lesson"> · 第 {{ s.lesson }} 课</template></small></span>
          <span>{{ s.total - s.pending }}/{{ s.total }} · 继续 →</span>
        </button>
      </div>
    </template>

    <div class="section-title">词汇听打</div>
    <div class="card-grid">
      <div v-for="l in words" :key="l.key" class="card">
        <div class="name">{{ l.title }}<span class="badge type">单词</span><span v-if="l.audio_done >= l.total" class="badge audio">✓ 音频</span></div>
        <div class="meta">共 {{ l.total }} · 已背 {{ l.memorized }} · 掌握 {{ l.known }} · 未开始 {{ l.new }}</div>
        <div class="progress"><div :style="{width: (l.total ? l.known / l.total * 100 : 0) + '%'}"></div></div>
        <div class="card-actions">
          <button class="btn ghost sm" @click="location.hash='#/memorize?list=' + l.key">📖 背单词</button>
          <button class="btn primary sm" @click="start(l)">👂 开始听打</button>
        </div>
      </div>
    </div>

    <div class="section-title">句子听写</div>
    <div class="card-grid">
      <div v-for="l in sents" :key="l.key" class="card">
        <div class="name">{{ l.title }}<span class="badge type">句子</span><span v-if="l.audio_done >= l.total" class="badge audio">✓ 音频</span></div>
        <div class="meta">共 {{ l.total }} · 掌握 {{ l.known }} · 未开始 {{ l.new }}</div>
        <div class="progress"><div :style="{width: (l.total ? l.known / l.total * 100 : 0) + '%'}"></div></div>
        <select v-if="l.lesson_count" v-model.number="selectedLesson[l.key]" class="lesson-select">
          <option v-for="x in lessons[l.key]" :key="x.lesson" :value="x.lesson">第 {{ x.lesson }} 课 · {{ x.total }} 句 · 掌握 {{ x.known }}</option>
        </select>
        <div class="card-actions"><button class="btn primary sm" @click="start(l)">👂 {{ l.lesson_count ? '按课学习' : '开始听写' }}</button></div>
      </div>
    </div>
    <div v-if="today" class="section-title today-summary">今日：新词 {{ today.new }} · 复习 {{ today.review }} · 背单词对 {{ today.memorize_right }} / 错 {{ today.memorize_wrong }} · 听打首答对 {{ today.right }} / 错 {{ today.wrong }}</div>
  </div>
</template>
