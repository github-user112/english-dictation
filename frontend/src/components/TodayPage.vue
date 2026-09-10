<script setup>
/* 今日动线首页：五环任务卡，数据全部由 /api/today 服务端算好，这里纯渲染 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api } from "../lib/core";
import { Profile, refreshProfile } from "../lib/profile";

const data = ref(null);
const loading = ref(true);
const error = ref("");
let mounted = true;

onMounted(load);
onUnmounted(() => { mounted = false; });

async function load() {
  loading.value = true;
  error.value = "";
  try {
    await refreshProfile(true).catch(() => {});   // 先拿打卡状态，庆祝卡文案才不闪
    const want = localStorage.getItem("dict_today_list");
    const d = await api("/today" + (want ? `?list=${encodeURIComponent(want)}` : ""));
    if (mounted) data.value = d;
  } catch (err) {
    if (mounted) error.value = err.message || "加载失败";
  } finally {
    if (mounted) loading.value = false;
  }
}

/* 主线词库切换：localStorage 记住选择，换词库后重新拉任务卡 */
function pickList(ev) {
  const v = ev.target.value;
  if (v) localStorage.setItem("dict_today_list", v);
  else localStorage.removeItem("dict_today_list");
  load();
}

const steps = computed(() => data.value?.steps || []);
const nextIdx = computed(() => steps.value.findIndex((s) => !s.done));
/* 切换器回显：localStorage 里的选择，或后端推导出的当前词库 */
const currentList = computed(() =>
  localStorage.getItem("dict_today_list") || data.value?.word_list?.key || "");
const ringPct = computed(() => {
  if (!data.value || !steps.value.length) return 0;
  return Math.round(data.value.done_count / steps.value.length * 100);
});
const dateLabel = computed(() => {
  if (!data.value) return "";
  const d = new Date(data.value.date + "T00:00:00");
  return `${d.getMonth() + 1}月${d.getDate()}日 周${"日一二三四五六"[d.getDay()]}`;
});
const STEP_ICONS = { memorize: "📖", dictation: "👂", sentence: "✍️", arrange: "🧩", wrong: "🗑️" };
/* 路径节点左右交错（多邻国式弯曲路径）：以节点中心偏移量表达 */
const NODE_OFFSETS = [0, 44, 62, 44, 0, -44, -62, -44];
function nodeOffset(i) { return NODE_OFFSETS[i % NODE_OFFSETS.length]; }
</script>

<template>
  <div v-if="loading" class="empty loading"><span class="spin" aria-hidden="true"></span><span class="load-text">加载中…</span></div>
  <div v-else-if="error" class="empty" role="alert">
    <p>{{ error }}</p>
    <button class="btn primary" @click="load">重试</button>
  </div>
  <div v-else-if="data" class="duo-page">
    <!-- 顶条：日期 + 连续天数 + 进度环 -->
    <header class="duo-top">
      <div class="duo-date">
        <b>{{ dateLabel }}</b>
        <span class="duo-streak" :class="{ cold: !data.streak }">
          🔥 {{ data.streak > 0 ? `连续 ${data.streak} 天` : "今天开始第 1 天" }}
        </span>
      </div>
      <svg class="duo-ring" viewBox="0 0 36 36" role="img"
           :aria-label="`今日完成 ${data.done_count}/${steps.length}`">
        <circle class="r-bg" cx="18" cy="18" r="15.9155" pathLength="100"/>
        <circle class="r-fg" cx="18" cy="18" r="15.9155" pathLength="100"
                :stroke-dasharray="`${ringPct} 100`"/>
        <text x="18" y="22" class="r-text">{{ data.done_count }}/{{ steps.length }}</text>
      </svg>
    </header>

    <!-- 未测词汇量：先定位再进环线 -->
    <a v-if="!data.has_wordtest" class="duo-wordtest" href="#/wordtest">
      <span class="dw-icon" aria-hidden="true">🧭</span>
      <span class="dw-body">
        <b>先花 2 分钟测测词汇量</b>
        <small>测完按你的水平推荐词库，路径会更合身</small>
      </span>
      <span class="dw-go">GO</span>
    </a>

    <!-- 主线词库切换：默认新概念1册，可换；句子课自动跟随 nce 册数 -->
    <div class="duo-track">
      <span class="dt-label">学习路线</span>
      <select class="dt-select" :value="currentList" aria-label="切换主线词库" @change="pickList">
        <option v-for="o in data.word_options" :key="o.key" :value="o.key">{{ o.title }}</option>
      </select>
      <span v-if="data.lesson_mode && data.lesson" class="dt-lesson">
        第 {{ data.lesson }}<small v-if="data.lesson_total">/{{ data.lesson_total }}</small> 课
      </span>
    </div>

    <!-- 多邻国式学习路径。pad-first：第一关是当前关时顶部留白，气泡才不会压到上面的路线选择器 -->
    <div class="duo-path" :class="{ 'pad-first': nextIdx === 0 }" role="list" aria-label="今日学习路径">
      <div v-for="(s, i) in steps" :key="s.key" class="duo-node-row" role="listitem"
           :style="{ '--off': nodeOffset(i) + 'px' }">
        <div class="duo-node-wrap">
          <!-- 当前节点：悬浮提示 + 呼吸圈 -->
          <template v-if="i === nextIdx">
            <div class="duo-bubble" aria-hidden="true">
              <b>{{ s.title }}</b><small>{{ s.desc }}</small>
            </div>
            <span class="duo-pulse" aria-hidden="true"></span>
          </template>
          <a class="duo-node" :class="{ done: s.done, current: i === nextIdx, locked: nextIdx >= 0 && i > nextIdx }"
             :href="s.link"
             :aria-label="`${s.title}：${s.desc}${s.done ? '（已完成）' : ''}`">
            <span class="duo-node-icon" aria-hidden="true">{{ s.done ? "✓" : STEP_ICONS[s.key] || "⭐" }}</span>
            <span v-if="!s.done && s.target > 0" class="duo-node-badge">{{ s.progress }}/{{ s.target }}</span>
          </a>
          <span class="duo-node-label" :class="{ dim: s.done }">{{ s.title }} · {{ s.minutes }}′</span>
        </div>
      </div>

      <!-- 终点奖杯 -->
      <div class="duo-node-row" style="--off: 0px">
        <div class="duo-node-wrap">
          <div class="duo-node duo-trophy" :class="{ won: data.all_done }" aria-hidden="true">🏆</div>
          <span class="duo-node-label" :class="{ dim: !data.all_done }">
            {{ data.all_done ? "今日全部完成！" : "终点" }}
          </span>
        </div>
      </div>
    </div>

    <!-- 全部完成庆祝卡 -->
    <section v-if="data.all_done" class="duo-celebrate">
      <h2>🎉 太棒了！今日五环全通</h2>
      <p>{{ Profile.ready && !Profile.dailyDoneToday ? "来个每日挑战收官？" : "明天继续，小树在等你浇水" }}</p>
      <a v-if="Profile.ready && !Profile.dailyDoneToday" class="duo-btn green" href="#/daily">每日挑战 →</a>
      <a v-else class="duo-btn blue" href="#/stats">看看统计 →</a>
    </section>

    <!-- 每日挑战：加分项，不占环 -->
    <a v-if="Profile.ready" class="daily-banner" href="#/daily"
       :aria-label="Profile.dailyDoneToday ? '每日挑战今日已完成' : '开始每日挑战'">
      <span class="db-icon" aria-hidden="true">🗓️</span>
      <span class="db-body">
        <b>今日词力 · 每日挑战</b>
        <small>{{ Profile.dailyDoneToday
          ? `今天已完成 · 连续 ${Profile.dailyStreak} 天，重玩不计分`
          : "10 道全站同题 · 完成即给小树浇水" }}</small>
      </span>
      <em class="db-go">{{ Profile.dailyDoneToday ? "已打卡 ✓" : "去挑战 →" }}</em>
    </a>

    <p class="today-foot">
      <a href="#/lists">全部素材与自由练习 →</a>
    </p>
  </div>
</template>
