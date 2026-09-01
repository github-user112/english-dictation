<script setup>
import { onMounted, ref } from "vue";
import { api, playUrl, playWord } from "../lib/core";

const items = ref([]);
const loading = ref(true);
const error = ref("");
const confusions = ref([]);
const story = ref(null);
const storyLoading = ref(false);
const storyError = ref("");

onMounted(load);

/* AI 错词串记：把错词编成一段小故事，语境里记牢 */
async function openStory(fresh) {
  storyLoading.value = true;
  storyError.value = "";
  try {
    const d = await api("/ai/story" + (fresh ? "?fresh=1" : ""));
    story.value = d;
  } catch (err) {
    storyError.value = err.message || "故事生成失败";
  } finally {
    storyLoading.value = false;
  }
}
/* 服务端输出仅 **加粗** 标记：先转义再还原 <b>，防注入 */
function storyHtml(text) {
  const esc = (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>");
}

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

/* AI 助记：按词展开/收起，全站共享缓存 */
const mnemonics = ref({});
const mnemonicLoading = ref("");
async function toggleMnemonic(item) {
  const key = item.list + "|" + item.id;
  if (mnemonics.value[key]) {
    const next = { ...mnemonics.value };
    delete next[key];
    mnemonics.value = next;
    return;
  }
  mnemonicLoading.value = key;
  try {
    const d = await api(`/ai/mnemonic?list=${item.list}&id=${encodeURIComponent(item.id)}`);
    mnemonics.value = { ...mnemonics.value, [key]: d.text };
  } catch (err) {
    mnemonics.value = { ...mnemonics.value, [key]: "⚠ " + (err.message || "生成失败") };
  } finally {
    mnemonicLoading.value = "";
  }
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
  try {
    await api("/wrong/remove", { method: "POST", body: JSON.stringify({ list: item.list, id: item.id }) });
    location.reload();
  } catch (err) {
    alert(err.message || "删除失败，请检查网络");
  }
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
        <button class="btn ghost" @click="openStory(false)">✨ 错词串记</button>
        <button class="btn ghost" @click="goBoss">⚔️ 错词Boss战</button>
        <button class="btn primary" @click="redo">全部重练</button>
      </span>
    </div>
    <div v-if="error" class="empty" role="alert"><p>{{ error }}</p><button class="btn primary" @click="load">重试</button></div>
    <div v-else-if="!loading && !items.length && !confusions.length" class="empty">太棒了，错词本里没有词 🎉</div>

    <!-- AI 错词串记：错词编成情境小故事 -->
    <template v-if="story || storyLoading || storyError">
      <div class="section-title"><span>错词串记</span><small>{{ story ? `${story.words.length} 个错词 · AI 情境故事` : "生成中…" }}</small></div>
      <div class="confuse-box">
        <div v-if="storyLoading" class="empty" style="padding:20px;">AI 正在编故事…（约 10 秒）</div>
        <div v-else-if="storyError" class="empty" role="alert" style="padding:20px;">
          <p>{{ storyError }}</p>
          <button class="btn primary sm" @click="openStory(false)">重试</button>
        </div>
        <template v-else>
          <p class="story-text" v-html="storyHtml(story.story)"></p>
          <div style="text-align:center;margin-top:12px;">
            <button class="btn ghost sm" @click="openStory(true)">🔁 换个故事</button>
            <button class="btn ghost sm" @click="story = null">收起</button>
          </div>
        </template>
      </div>
    </template>

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
        <template v-for="i in list" :key="i.id">
          <div class="wrong-item">
            <button class="btn ghost" @click="play(i)">🔊</button>
            <div class="w">{{ i.text }}</div>
            <div class="m">{{ i.meaning }}</div>
            <div class="cnt">错 {{ i.wrong_count }}次</div>
            <button v-if="i.kind === 'word'" class="btn ghost" :disabled="mnemonicLoading === i.list + '|' + i.id"
                    aria-label="AI 助记与辨析" @click="toggleMnemonic(i)">{{ mnemonicLoading === i.list + '|' + i.id ? '…' : '✨' }}</button>
            <button class="btn ghost" @click="remove(i)">删除</button>
          </div>
          <div v-if="mnemonics[i.list + '|' + i.id]" class="mnemonic-line" v-html="storyHtml(mnemonics[i.list + '|' + i.id])"></div>
        </template>
      </template>
    </template>
  </div>
</template>
