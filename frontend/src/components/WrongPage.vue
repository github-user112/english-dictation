<script setup>
import { onMounted, ref } from "vue";
import { api, playUrl } from "../lib/core";

const items = ref([]);
const loading = ref(true);
const error = ref("");

onMounted(load);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const d = await api("/wrong");
    items.value = d.items || [];
  } catch (err) {
    items.value = [];
    error.value = err.message || "错词本加载失败";
  } finally {
    loading.value = false;
  }
}

function play(item) { playUrl(item.audio); }
function redo() {
  const practice = items.value.map((i) => ({ ...i, phase: "review" }));
  sessionStorage.setItem("dict_custom", JSON.stringify(practice));
  location.hash = "#/word?list=" + (items.value[0]?.list || "cet4");
}
async function remove(item) {
  await api("/wrong/remove", { method: "POST", body: JSON.stringify({ list: item.list, id: item.id }) });
  location.reload();
}
function grouped() {
  const g = {};
  items.value.forEach((i) => { (g[i.list] = g[i.list] || []).push(i); });
  return g;
}
</script>

<template>
  <div class="wrong-page">
    <div class="page-heading compact"><span class="eyebrow">REVIEW & REBUILD</span><h1>错词不是终点</h1><p>集中处理还不够熟悉的内容。</p></div>
    <div class="practice-top">
      <span class="progress-line">共 {{ items.length }} 个需巩固</span>
      <button v-if="items.length" class="btn primary" @click="redo">全部重练</button>
    </div>
    <div v-if="error" class="empty" role="alert"><p>{{ error }}</p><button class="btn primary" @click="load">重试</button></div>
    <div v-else-if="!loading && !items.length" class="empty">太棒了，错词本里没有词 🎉</div>
    <template v-for="(list, key) in grouped()" :key="key">
      <div class="section-title">{{ key }}</div>
      <div v-for="i in list" :key="i.id" class="wrong-item">
        <button class="btn ghost" @click="play(i)">🔊</button>
        <div class="w">{{ i.text }}</div>
        <div class="m">{{ i.meaning }}</div>
        <div class="cnt">错 {{ i.wrong_count }}次</div>
        <button class="btn ghost" @click="remove(i)">删除</button>
      </div>
    </template>
  </div>
</template>
