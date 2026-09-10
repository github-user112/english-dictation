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
  <div v-else-if="data" class="today-page">

    <!-- ===== Hero · 今日进度环 ===== -->
    <section class="today-hero" aria-label="今日进度">
      <div class="hero-ring">
        <svg viewBox="0 0 148 148" width="148" height="148" role="img"
             :aria-label="`今日完成 ${data.done_count}/${steps.length}`">
          <circle cx="74" cy="74" r="62" fill="none" stroke="#dcecd2" stroke-width="13" pathLength="100"/>
          <circle cx="74" cy="74" r="62" fill="none" stroke="var(--green)" stroke-width="13"
                  stroke-linecap="round" pathLength="100"
                  :stroke-dasharray="`${ringPct} 100`"
                  transform="rotate(-90 74 74)"
                  style="filter:drop-shadow(0 0 6px rgba(88,204,2,0.4));"/>
        </svg>
        <div class="hero-ring-center">
          <div class="hr-pct">{{ ringPct }}%</div>
          <div class="hr-sub">{{ data.done_count }}/{{ steps.length }} 完成</div>
        </div>
      </div>
      <div class="hero-info">
        <div class="hero-banner" :class="{ win: data.all_done }">
          <template v-if="data.all_done">🎉 今日五环全通，太棒了！</template>
          <template v-else>✅ 继续前进！你已经完成了 {{ ringPct }}% 的五环任务！</template>
        </div>
        <h1 class="hero-title">{{ data.all_done ? "太棒了 🎉" : "继续前进 🚀" }}</h1>
        <div class="hero-meta">
          <span>📅 {{ dateLabel }}</span>
          <span class="dot">·</span>
          <span class="hero-streak" :class="{ cold: !data.streak }">
            <template v-if="data.streak > 0">🔥 连续 <b>{{ data.streak }} 天</b></template>
            <template v-else>🔥 今天开始第 1 天</template>
          </span>
        </div>
        <div v-if="Profile.ready" class="hero-badges">
          <span class="xp-chip">⚡ {{ Profile.xp.toLocaleString() }} XP</span>
          <span class="level-chip">💎 Lv.{{ Profile.level }} · {{ Profile.title }}</span>
        </div>
      </div>
    </section>

    <!-- ===== 主网格 ===== -->
    <div class="today-grid">

      <!-- ===== 左 · 五环旅程 ===== -->
      <div class="card journey-card">
        <div class="sec-head">
          <span class="sh-emoji">🧭</span>
          <div>
            <div class="sh-title">今日五环旅程</div>
            <div class="sh-sub">每天一条主线 · 完成五环即打卡</div>
          </div>
          <span class="sh-count">{{ data.done_count }}/{{ steps.length }} 完成</span>
        </div>

        <!-- 主线词库切换 -->
        <div class="list-picker">
          <span class="list-picker-label">📚 学习路线</span>
          <select class="list-picker-select" :value="currentList" aria-label="切换主线词库" @change="pickList">
            <option v-for="o in data.word_options" :key="o.key" :value="o.key">{{ o.title }}</option>
          </select>
          <span v-if="data.lesson_mode && data.lesson" class="list-picker-lesson">
            第 {{ data.lesson }}<small v-if="data.lesson_total">/{{ data.lesson_total }}</small> 课
          </span>
        </div>

        <!-- 五环旅程 -->
        <div class="journey" :class="{ 'pad-first': nextIdx === 0 }" role="list" aria-label="今日学习路径">
          <div class="journey-line"></div>

          <div v-for="(s, i) in steps" :key="s.key" class="step"
               :class="{ done: s.done, current: i === nextIdx, locked: nextIdx >= 0 && i > nextIdx }"
               :style="{ '--off': nodeOffset(i) + 'px' }"
               role="listitem">
            <div class="step-node">
              <span v-if="i === nextIdx" class="node-pulse" aria-hidden="true"></span>
              <span class="step-em" aria-hidden="true">{{ s.done ? "✓" : STEP_ICONS[s.key] || "⭐" }}</span>
              <span v-if="s.done" class="node-tick" aria-hidden="true">✓</span>
            </div>
            <a class="step-card" :href="s.link"
               :aria-label="`${s.title}：${s.desc}${s.done ? '（已完成）' : ''}`">
              <div class="step-head">
                <span class="step-title" :class="{ dim: s.done }">{{ s.title }}</span>
                <span class="step-status"
                      :class="{ done: s.done, current: i === nextIdx, locked: nextIdx >= 0 && i > nextIdx }">
                  {{ s.done ? "已完成" : (i === nextIdx ? "进行中" : "🔒 待开始") }}
                </span>
              </div>
              <div class="step-desc">
                <span v-if="!s.done && s.target > 0" class="lesson-tag">{{ s.progress }}/{{ s.target }}</span>
                {{ s.desc }}
              </div>
              <div class="step-foot" :class="{ 'with-cta': i === nextIdx && !s.done }">
                <div class="step-bar">
                  <i :class="i === nextIdx ? 'fill-blue' : 'fill-green'"
                     :style="{ width: (s.target > 0 ? s.progress / s.target * 100 : 0) + '%' }"></i>
                </div>
                <span class="step-count">{{ s.progress }}/{{ s.target }}</span>
                <span class="step-time">⏱ {{ s.minutes }}'</span>
                <span v-if="i === nextIdx && !s.done" class="step-cta">继续 ▶</span>
              </div>
            </a>
          </div>

          <!-- 终点奖杯 -->
          <div class="step trophy" :class="{ won: data.all_done }">
            <div class="step-node" aria-hidden="true">
              <span class="step-em">{{ data.all_done ? "🏆" : "🎯" }}</span>
            </div>
            <div class="step-card" style="cursor: default">
              <div class="step-head">
                <span class="step-title" :class="{ dim: !data.all_done }">{{ data.all_done ? "今日全部完成！" : "终点" }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== 右 · 侧栏 ===== -->
      <div class="sidebar">

        <!-- 词汇量测试（未测时显示） -->
        <a v-if="!data.has_wordtest" class="side-test" href="#/wordtest">
          <span class="st-icon" aria-hidden="true">📊</span>
          <div class="st-title">先测词汇量</div>
          <div class="st-desc">花 2 分钟测测词汇量，按你的水平推荐词库和每日量，任务更合身。</div>
          <div class="st-benefits">
            <span class="st-benefit">🎯 CEFR 等级</span>
            <span class="st-benefit">📚 自动推词库</span>
            <span class="st-benefit">📈 每日配额</span>
          </div>
          <span class="st-cta">📊 去测一下 · 2 分钟</span>
        </a>

        <!-- 每日挑战 banner -->
        <a v-if="Profile.ready" class="side-daily" href="#/daily"
           :aria-label="Profile.dailyDoneToday ? '每日挑战今日已完成' : '开始每日挑战'">
          <div class="sd-row">
            <span class="sd-icon" aria-hidden="true">🏆</span>
            <div class="sd-body">
              <div class="sd-title">今日词力 · 每日挑战</div>
              <div class="sd-desc">
                {{ Profile.dailyDoneToday
                  ? `今天已完成 · 连续 ${Profile.dailyStreak} 天，重玩不计分`
                  : "10 道全站同题 · 完成即给小树浇水" }}
              </div>
            </div>
            <span class="sd-go">{{ Profile.dailyDoneToday ? "已打卡 ✓" : "去挑战 →" }}</span>
          </div>
        </a>
      </div>

    </div>

    <!-- ===== 下一步 Hero ===== -->
    <div v-if="nextIdx >= 0 && steps[nextIdx]" class="next-hero">
      <div class="next-node">{{ STEP_ICONS[steps[nextIdx].key] || "⭐" }}</div>
      <div class="next-body">
        <div class="next-tag"><span class="pulse-dot"></span> 下一步 · 约 {{ steps[nextIdx].minutes }} 分钟</div>
        <div class="next-title">{{ steps[nextIdx].title }}</div>
        <div class="next-desc">{{ steps[nextIdx].desc }}</div>
        <div class="next-prog-row">
          <div class="next-prog">
            <i :style="{ width: (steps[nextIdx].target > 0 ? steps[nextIdx].progress / steps[nextIdx].target * 100 : 0) + '%' }"></i>
          </div>
          <span class="next-prog-lbl">进度 {{ steps[nextIdx].progress }}/{{ steps[nextIdx].target }}</span>
        </div>
      </div>
      <a class="next-btn" :href="steps[nextIdx].link">开始练习 →</a>
    </div>

    <!-- ===== 全部完成庆祝卡 ===== -->
    <section v-if="data.all_done" class="today-celebrate">
      <h2>🎉 太棒了！今日五环全通</h2>
      <p>{{ Profile.ready && !Profile.dailyDoneToday ? "来个每日挑战收官？" : "明天继续，小树在等你浇水" }}</p>
      <a v-if="Profile.ready && !Profile.dailyDoneToday" class="duo-btn green" href="#/daily">每日挑战 →</a>
      <a v-else class="duo-btn blue" href="#/stats">看看统计 →</a>
    </section>

    <!-- ===== 页脚 ===== -->
    <p class="today-footer">
      <a href="#/lists">📚 全部素材与自由练习 →</a>
    </p>
  </div>
</template>
