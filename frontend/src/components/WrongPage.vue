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
    items.value = items.value.filter((x) => x !== item);
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

    <!-- ============ Hero：标题 + 总览进度环 + 快捷入口 ============ -->
    <section class="wrong-hero" :class="{ 'wh-loading': loading }">
      <div class="wh-left">
        <span class="wh-badge">
          <span class="wh-pulse"></span>{{ items.length }} 个词待复习
        </span>
        <h1 class="wh-title">
          <span class="emoji">📕</span><span>错词本</span>
        </h1>
        <p class="wh-desc">
          各模式答错的词自动收录于此，按 1 → 3 → 7 天间隔重复复习。连续答对 3 次即可毕业，标记为已掌握。
        </p>
        <div class="wh-cta">
          <button class="btn primary big" @click="redo" :disabled="!items.length">🎯 开始复习</button>
          <button class="btn purple" @click="openStory(false)" :disabled="!items.length || storyLoading">✨ 错词串记</button>
        </div>
      </div>
      <div class="wh-right">
        <div class="wh-ring">
          <svg viewBox="0 0 36 36">
            <circle class="wr-ring-bg" cx="18" cy="18" r="15.9155" pathLength="100"/>
            <circle class="wr-ring-fg" cx="18" cy="18" r="15.9155" pathLength="100"
                    :style="{ strokeDashoffset: String(100 - items.length) }"/>
          </svg>
          <div class="wr-center">
            <span class="wr-big">{{ items.length }}</span>
            <span class="wr-sub">总错词数</span>
          </div>
        </div>
        <div class="wh-stats">
          <div class="wh-stat">
            <span class="wh-emoji">⏰</span>
            <div class="wh-stat-body">
              <b class="orange">{{ items.length }}</b><small>今日待复习</small>
            </div>
          </div>
          <div class="wh-stat">
            <span class="wh-emoji">🧩</span>
            <div class="wh-stat-body">
              <b class="green">{{ confusions.length }}</b><small>易混词</small>
            </div>
          </div>
          <div class="wh-stat">
            <span class="wh-emoji">📚</span>
            <div class="wh-stat-body">
              <b>{{ Object.keys(grouped()).length }}</b><small>涉及词表</small>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ============ 错误态 ============ -->
    <div v-if="error" class="wr-error" role="alert">
      <span class="wr-error-icon">⚠️</span>
      <p>{{ error }}</p>
      <button class="btn red sm" @click="load">重试</button>
    </div>

    <!-- ============ 加载骨架 ============ -->
    <div v-else-if="loading" class="wr-load">
      <span class="spin"></span><span>正在加载错词本…</span>
    </div>

    <!-- ============ 空态 ============ -->
    <div v-else-if="!items.length && !confusions.length" class="wr-empty">
      <span class="emoji">🎉</span>
      <span class="badge-soft green">✅ 全部掌握</span>
      <h3>太棒了，错词本是空的</h3>
      <p>各模式答错的词会自动收录到这里，目前还没有任何词需要巩固。继续保持这个势头！</p>
      <button class="btn primary" @click="load">🔄 刷新</button>
    </div>

    <!-- ============ 主区：词表 + 侧栏 ============ -->
    <div v-else class="wrong-main">
      <div>

        <!-- 顶部信息条：词表分布速览 -->
        <div v-if="items.length" class="wr-filter">
          <span class="wr-filter-label">🔍 共 <b>{{ items.length }}</b> 个待巩固</span>
          <span v-for="(list, key) in grouped()" :key="key" class="wr-filter-chip">
            {{ key === 'news' ? '📰' : key === 'oral900' ? '🗣️' : key.startsWith('nc') ? '📝' : '🎧' }}
            <span>{{ key }}</span>
            <b>{{ list.length }}</b>
          </span>
          <small class="wr-filter-note">按错词来源分组 · 点组标题可折叠</small>
        </div>

        <!-- 词表 -->
        <div v-if="items.length" class="wr-list">
          <div class="wr-list-head">
            <div class="h-left">
              <h2><span>📕</span> 待复习词表</h2>
              <small>共 {{ items.length }} 个词 · 按错词次数排序</small>
            </div>
            <span class="badge-soft orange">⏰ 今日到期</span>
          </div>

          <template v-for="(list, key) in grouped()" :key="key">
            <details class="wr-group" open>
              <summary>
                <span class="wg-emoji">{{ key === 'news' ? '📰' : key === 'oral900' ? '🗣️' : key.startsWith('nc') ? '📝' : '🎧' }}</span>
                <span class="wg-name">{{ key }}</span>
                <span class="wg-count">{{ list.length }} 词</span>
              </summary>

              <template v-for="i in list" :key="i.id">
                <div class="wr-row">
                  <div class="wr-rank"></div>
                  <div class="wr-item">
                    <button class="wr-audio" aria-label="播放" @click="play(i)">🔊</button>
                    <div class="wr-en">
                      <span class="txt">{{ i.text }}</span>
                      <span v-if="i.phonetic" class="phon">{{ i.phonetic }}</span>
                    </div>
                    <div class="wr-zh">{{ i.meaning }}</div>
                    <div class="wr-right">
                      <span class="wr-cnt" :title="`答对 ${i.right_count} 次`">
                        <small>错</small>{{ i.wrong_count }}
                      </span>
                      <button v-if="i.kind === 'word'" class="btn ghost sm"
                              :disabled="mnemonicLoading === i.list + '|' + i.id"
                              aria-label="AI 助记与辨析" @click="toggleMnemonic(i)">
                        {{ mnemonicLoading === i.list + '|' + i.id ? '…' : '✨' }}
                      </button>
                      <button class="wr-del" aria-label="删除" @click="remove(i)">×</button>
                    </div>
                    <div v-if="mnemonics[i.list + '|' + i.id]" class="wr-mnemonic" v-html="storyHtml(mnemonics[i.list + '|' + i.id])"></div>
                  </div>
                </div>
              </template>
            </details>
          </template>
        </div>

        <!-- AI 错词串记：错词编成情境小故事 -->
        <template v-if="story || storyLoading || storyError">
          <div class="section-title"><span>✨ 错词串记</span><small>{{ story ? `${story.words.length} 个错词 · AI 情境故事` : "生成中…" }}</small></div>
          <div class="card wr-story">
            <div v-if="storyLoading" class="wr-story-loading">AI 正在编故事…（约 10 秒）</div>
            <div v-else-if="storyError" class="wr-error" role="alert">
              <span class="wr-error-icon">⚠️</span>
              <p>{{ storyError }}</p>
              <button class="btn red sm" @click="openStory(false)">重试</button>
            </div>
            <template v-else>
              <p class="story-text" v-html="storyHtml(story.story)"></p>
              <div class="wr-story-actions">
                <button class="btn ghost sm" @click="openStory(true)">🔁 换个故事</button>
                <button class="btn ghost sm" @click="story = null">收起</button>
              </div>
            </template>
          </div>
        </template>

        <!-- 易混词特训：从你的真实错拼里挖出的最小对立体 -->
        <template v-if="confusions.length">
          <div class="section-title"><span>🧩 易混词特训</span><small>来自你最近的真实错拼 · 编辑距离匹配</small></div>
          <div class="card wr-confuse">
            <div class="wr-confuse-box">
              <div v-for="c in confusions" :key="c.list + c.word" class="wr-confuse-row">
                <button class="wr-audio" aria-label="播放正确发音" @click="play({ kind: 'word', audio: c.audio, text: c.word })">🔊</button>
                <b class="cw">{{ c.word }}</b>
                <span class="cm">{{ c.meaning }}</span>
                <span class="ct">
                  常打成
                  <code v-for="t in c.typos" :key="t.typed">{{ t.typed }}<i v-if="t.count > 1">×{{ t.count }}</i></code>
                </span>
              </div>
            </div>
            <div class="wr-confuse-cta">
              <button class="btn orange big" @click="drillConfusions">🎯 特练这 {{ confusions.length }} 个词</button>
            </div>
          </div>
        </template>

        <!-- 底部提示条 -->
        <div class="wr-tip">
          <span class="wr-tip-emoji">💡</span>
          <p>错词本采用间隔重复算法（1 天 → 3 天 → 7 天），每次复习答对后间隔翻倍。连续答对 3 次即"毕业"，标记为已掌握，不再重复出现。</p>
        </div>
      </div>

      <!-- ============ 右侧栏 ============ -->
      <aside class="wrong-side">
        <!-- 错词 Boss 战入口 -->
        <button v-if="items.length" type="button" class="banner purple wr-boss" @click="goBoss">
          <span class="b-icon">⚔️</span>
          <span class="b-body">
            <b>错词 Boss 战</b>
            <small>把最常错的 {{ items.length }} 个词打包成 Boss，集中讨伐</small>
          </span>
          <span class="b-go">出击 →</span>
        </button>

        <!-- 错词分布：按来源词表 -->
        <div v-if="items.length" class="card wr-dist">
          <div class="card-title"><span class="card-icon">📚</span> 词表分布</div>
          <div class="wr-dist-list">
            <div v-for="(list, key) in grouped()" :key="key" class="wr-dist-row">
              <div class="wr-src-icon">{{ key === 'news' ? '📰' : key === 'oral900' ? '🗣️' : key.startsWith('nc') ? '📝' : '🎧' }}</div>
              <div class="wr-src-body">
                <b>{{ key }}</b>
                <small>错词来源词表</small>
              </div>
              <div class="wr-src-count">{{ list.length }}<small>词</small></div>
            </div>
          </div>
        </div>

        <!-- AI 错词串记入口卡 -->
        <div v-if="items.length" class="card wr-storycard">
          <div class="card-title"><span class="card-icon">✨</span> AI 错词串记</div>
          <p class="card-desc">把错词编成一段情境小故事，在语境里记牢 —— 比硬背更有画面感。</p>
          <button class="btn purple full" @click="openStory(false)" :disabled="storyLoading">
            {{ storyLoading ? '生成中…' : '🪄 生成故事' }}
          </button>
        </div>
      </aside>
    </div>

  </div>
</template>
