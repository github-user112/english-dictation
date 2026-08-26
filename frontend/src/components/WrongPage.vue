<script setup>
import { onMounted, ref } from "vue";
import { api, playUrl, playWord } from "../lib/core";

const items = ref([]);
const loading = ref(true);
const error = ref("");
const confusions = ref([]);

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
  api("/confusions").then((d) => { confusions.value = (d.items || []).slice(0, 6); }).catch(() => {});
}

/* 易混词特练：把挖出的混淆词打包成一次自定义听打 */
function drillConfusions() {
  const practice = confusions.value.map((c) => ({
    id: c.id, text: c.word, kind: "word",
    phonetic: c.phonetic, meaning: c.meaning, audio: c.audio, phase: "review", list: c.list,
  }));
  if (!practice.length) return;
  sessionStorage.setItem("dict_custom", JSON.stringify(practice));
  sessionStorage.setItem("dict_custom_label", "易混词特练");
  location.hash = "#/word?list=" + practice[0].list;
}

function play(item) {
  if (item.kind === "word") playWord(item);
  else playUrl(item.audio);
}
function redo() {
  const practice = items.value.map((i) => ({ ...i, phase: "review" }));
  sessionStorage.setItem("dict_custom", JSON.stringify(practice));
  sessionStorage.setItem("dict_custom_label", "错词重练");
  location.hash = "#/word?list=" + (items.value[0]?.list || "cet4");
}
/* 错词 Boss 战：最常错的词打包成 Boss，集中讨伐 */
function goBoss() {
  location.hash = "#/boss";
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
      <span v-if="items.length" class="wrong-actions">
        <button class="btn ghost" @click="goBoss">⚔️ 错词Boss战</button>
        <button class="btn primary" @click="redo">全部重练</button>
      </span>
    </div>
    <div v-if="error" class="empty" role="alert"><p>{{ error }}</p><button class="btn primary" @click="load">重试</button></div>
    <div v-else-if="!loading && !items.length && !confusions.length" class="empty">太棒了，错词本里没有词 🎉</div>

    <!-- 易混词特训：从你的真实错拼里挖出的最小对立体 -->
    <template v-if="confusions.length">
      <div class="section-title"><span>易混词特训</span><small>来自你最近的真实错拼 · 编辑距离匹配</small></div>
      <div class="confuse-box">
        <div v-for="c in confusions" :key="c.list + c.word" class="confuse-row">
          <button class="btn ghost sm" aria-label="播放正确发音" @click="play({ kind: 'word', audio: c.audio, text: c.word })">🔊</button>
          <b class="cw">{{ c.word }}</b>
          <span class="cm">{{ c.meaning }}</span>
          <span class="ct">
            常打成
            <code v-for="t in c.typos" :key="t.typed">{{ t.typed }}<i v-if="t.count > 1">×{{ t.count }}</i></code>
          </span>
        </div>
        <div style="text-align:center;margin-top:14px;">
          <button class="btn primary big" @click="drillConfusions">🎯 特练这 {{ confusions.length }} 个词</button>
        </div>
      </div>
    </template>

    <div v-if="items.length || confusions.length" class="practice-top" style="margin-top:26px;">
      <span class="progress-line">共 {{ items.length }} 个需巩固</span>
      <button v-if="items.length" class="btn primary" @click="redo">全部重练</button>
    </div>
    <template v-if="items.length">
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
    </template>
  </div>
</template>
