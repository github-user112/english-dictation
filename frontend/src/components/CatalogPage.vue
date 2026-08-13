<script setup>
import { computed, onMounted, ref } from "vue";
import { api, es } from "../lib/core";

const lists = ref([]);
const today = ref(null);
const words = computed(() => lists.value.filter((l) => l.type === "words"));
const sents = computed(() => lists.value.filter((l) => l.type === "sentences"));

onMounted(async () => {
  const d = await api("/lists");
  lists.value = d.lists;
  today.value = d.today;
});

function open(l) {
  location.hash = (l.type === "words" ? "#/word?list=" : "#/sentence?list=") + l.key;
}
function openMemorize(l) {
  location.hash = "#/memorize?list=" + l.key;
}
function card(l) {
  const pct = l.total ? Math.round((l.known / l.total) * 100) : 0;
  const audio = l.audio_done >= l.total ? '<span class="badge audio">✓ 音频</span>' : "";
  return `<div class="name">${es(l.title)}<span class="badge type">${l.type === "words" ? "单词" : "句子"}</span>${audio}</div>
    <div class="meta">共 ${l.total} · ${l.type === "words" ? `已背 ${l.memorized} · ` : ""}掌握 ${l.known}</div>
    <div class="progress"><div style="width:${pct}%"></div></div>
    ${l.type === "words" ? `<div class="card-actions">
      <button class="btn ghost sm" onclick="location.hash='#/memorize?list=${l.key}'">📖 背单词${l.total - l.memorized ? ` (${l.total - l.memorized})` : ""}</button>
      <button class="btn primary sm" onclick="location.hash='#/word?list=${l.key}'">👂 听打</button>
    </div>` : `<div class="card-actions">
      <button class="btn primary sm" onclick="location.hash='#/sentence?list=${l.key}'">👂 听写</button>
    </div>`}`;
}
</script>

<template>
  <div>
    <div class="section-title">词汇听打</div>
    <div class="card-grid">
      <div v-for="l in words" :key="l.key" class="card" v-html="card(l)"></div>
    </div>
    <div class="section-title">句子听写</div>
    <div class="card-grid">
      <div v-for="l in sents" :key="l.key" class="card" v-html="card(l)"></div>
    </div>
    <div v-if="today" class="section-title" style="color:var(--dim);font-size:14px;">
      今日：新词 {{ today.new }} · 复习 {{ today.review }} · 背单词对 {{ today.memorize_right }} / 错 {{ today.memorize_wrong }} · 听打对 {{ today.right }} / 错 {{ today.wrong }}
    </div>
  </div>
</template>
