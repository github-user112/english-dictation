<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";

const page = ref("catalog");
const TITLES = {
  catalog: "素材库", word: "单词听打", sentence: "句子听写", memorize: "背单词",
  wrong: "错词本", stats: "统计", settings: "设置",
};
const title = computed(() => TITLES[page.value] || "英语听打");

function sync() {
  const h = location.hash.replace(/^#\/?/, "") || "catalog";
  page.value = h.split("?")[0];
}
onMounted(() => { window.addEventListener("hashchange", sync); sync(); });
onUnmounted(() => window.removeEventListener("hashchange", sync));
</script>

<template>
  <header id="topbar">
    <div class="top-left">
      <a href="#/catalog" class="btn ghost" style="padding:6px 10px;">☰ 素材</a>
      <span id="title">{{ title }}</span>
    </div>
    <nav id="nav">
      <a class="nav-link" :class="{active: page==='wrong'}" href="#/wrong">错词</a>
      <a class="nav-link" :class="{active: page==='stats'}" href="#/stats">统计</a>
      <a class="nav-link" :class="{active: page==='settings'}" href="#/settings">设置</a>
    </nav>
  </header>
</template>