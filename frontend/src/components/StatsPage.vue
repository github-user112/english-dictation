<script setup>
import { computed, onMounted, ref } from "vue";
import { api } from "../lib/core";
import { activity } from "../lib/stats";
import { Account } from "../lib/account";
import { Profile, refreshProfile } from "../lib/profile";
import TreeArt from "./TreeArt.vue";
import ShareCard from "./ShareCard.vue";

const stats = ref(null);
const error = ref("");
const badges = ref(null);
const celebrating = ref([]);
const badgeShareOpen = ref(false);
const weeklyShareOpen = ref(false);
const weeklyLoading = ref(false);
const weekly = ref(null);
const typing = ref(null);

async function openWeekly() {
  weeklyLoading.value = true;
  try {
    const d = await api("/report/weekly");
    weekly.value = {
      name: Account.username || "游客",
      weekStart: d.week_start.slice(5).replace("-", "."),
      weekEnd: d.week_end.slice(5).replace("-", "."),
      items: d.items, accuracy: d.accuracy, accuracyDelta: d.accuracy_delta,
      memorizeRight: d.memorize_right, daysActive: d.days_active, streak: d.streak,
      link: location.origin + "/#/",
    };
    weeklyShareOpen.value = true;
  } catch (err) {
    alert(err.message || "周报加载失败");
  } finally {
    weeklyLoading.value = false;
  }
}

function badgeSharePayload() {
  return {
    name: Account.username || "游客",
    level: Profile.level,
    levelTitle: Profile.title,
    streak: Profile.streak,
    xp: Profile.xp,
    link: location.origin + "/#/",
  };
}

onMounted(async () => {
  await load();
  // 等两帧让圆环以满偏移渲染，再过渡到目标值形成生长动画
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  donutGrown.value = true;
});

const modeNames = { pure: "纯听写", assisted: "辅助听写", follow: "跟打", quiz: "听音选词", sprint: "限时冲刺", boss: "错词Boss战", match: "配对消消乐", arrange: "听音排句", wrong: "错词回收" };
const last14 = computed(() => {
  if (!stats.value) return [];
  const dayMap = new Map((stats.value.days || []).map((d) => [d.day, d]));
  const out = [];
  for (let i = 13; i >= 0; i--) {
    const dt = new Date(Date.now() - i * 86400000);
    const d = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
    const row = dayMap.get(d);
    out.push({ day: d.slice(5), total: row ? row.right + row.wrong : 0 });
  }
  return out;
});
const maxDay = computed(() => Math.max(1, ...last14.value.map((d) => d.total)));
/* 听打累计正确率环 */
const DONUT_LEN = 2 * Math.PI * 52;
const donutGrown = ref(false);
const dictationAcc = computed(() => {
  if (!stats.value) return 0;
  const t = (stats.value.total_right || 0) + (stats.value.total_wrong || 0);
  return t ? (stats.value.total_right || 0) / t : 0;
});

async function load() {
  error.value = "";
  try {
    stats.value = await api("/stats");
  } catch (err) {
    error.value = err.message || "统计加载失败";
    return;
  }
  // 词力档案独立加载：失败只隐藏等级卡，不拖垮整页统计
  refreshProfile(true).catch(() => {});
  // 徽章独立加载：成就接口故障只隐藏徽章墙，不拖垮整页统计
  try {
    const a = await api("/achievements");
    badges.value = a.badges || [];
    checkNewBadges();
  } catch { /* 徽章加载失败时保持隐藏 */ }
  // 打字数据独立加载：失败只隐藏 WPM/错键区，不拖垮整页统计
  api("/stats/typing").then((d) => { typing.value = d; }).catch(() => {});
}

/* ---- 打卡热力图：最近 26 周，按周列排布（周一开头） ---- */
const heatmap = computed(() => {
  const map = new Map(((stats.value.days) || []).map((d) => [d.day, activity(d)]));
  const today = new Date();
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const start = new Date(end);
  start.setDate(start.getDate() - 181);   // 26 周 ≈ 182 天
  while ((start.getDay() + 6) % 7 !== 0) start.setDate(start.getDate() - 1);   // 对齐周一
  const cells = [];
  const cursor = new Date(start);
  while (cursor <= end) {
    const iso = `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, "0")}-${String(cursor.getDate()).padStart(2, "0")}`;
    cells.push({ day: iso, n: map.get(iso) || 0 });
    cursor.setDate(cursor.getDate() + 1);
  }
  const max = Math.max(4, ...cells.map((c) => c.n));
  return cells.map((c) => ({
    ...c,
    lvl: c.n === 0 ? 0 : c.n <= max * 0.25 ? 1 : c.n <= max * 0.5 ? 2 : c.n <= max * 0.75 ? 3 : 4,
  }));
});
/* ---- 打字速度曲线：最近 60 个有数据的天 ---- */
const speedView = computed(() => {
  const s = (stats.value?.speed || []).slice(-60);
  if (!s.length) return null;
  const max = Math.max(...s.map((p) => p.sec));
  const pts = s.map((p, i) => {
    const x = s.length === 1 ? 50 : (i / (s.length - 1)) * 100;
    const y = 34 - (p.sec / max) * 30;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const avg = s.reduce((a, p) => a + p.sec, 0) / s.length;
  return { points: pts, avg: avg.toFixed(1), latest: s[s.length - 1].sec.toFixed(1), n: s.length };
});

/* ---- WPM 曲线：近 30 天有数据的天 ---- */
const TIER_ICON = { 钻石: "💎", 铂金: "🏆", 黄金: "🥇", 白银: "🥈", 青铜: "🥉" };
const wpmView = computed(() => {
  const c = (typing.value?.curve || []).slice(-30);
  if (!c.length) return null;
  const max = Math.max(10, ...c.map((p) => p.wpm));
  const pts = c.map((p, i) => {
    const x = c.length === 1 ? 50 : (i / (c.length - 1)) * 100;
    const y = 34 - (p.wpm / max) * 30;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const best = Math.max(...c.map((p) => p.wpm));
  return { points: pts, best: best.toFixed(1), n: c.length };
});

/* ---- 新徽章庆祝：localStorage 记住已见集合，首次访问静默建档 ---- */
function checkNewBadges() {
  const KEY = "ach_seen_v1";
  const unlocked = badges.value.filter((b) => b.unlocked).map((b) => b.id);
  let seen;
  try { seen = JSON.parse(localStorage.getItem(KEY) || "null"); } catch { seen = null; }
  if (!Array.isArray(seen)) {
    localStorage.setItem(KEY, JSON.stringify(unlocked));   // 老用户首次建档不弹窗
    return;
  }
  const fresh = badges.value.filter((b) => b.unlocked && !seen.includes(b.id));
  localStorage.setItem(KEY, JSON.stringify([...new Set([...seen, ...unlocked])]));
  if (fresh.length) {
    celebrating.value = fresh.slice(0, 3);
    setTimeout(() => { celebrating.value = []; }, 3600);
  }
}
</script>

<template>
  <div v-if="error" class="empty" role="alert">
    <span class="emoji" aria-hidden="true">⚠️</span>
    <h3>统计加载失败</h3>
    <p>{{ error }}</p>
    <button class="btn primary" @click="load">🔁 重试</button>
  </div>
  <div v-else-if="!stats" class="empty loading">
    <span class="spin" aria-hidden="true"></span>
    <span class="load-text">加载中…</span>
  </div>
  <div v-else class="stats-page">
    <!-- 新徽章解锁庆祝 -->
    <Teleport to="body">
      <div v-if="celebrating.length" class="ach-celebrate" @click="celebrating = []">
        <div class="ach-box">
          <span class="ach-title">🎉 解锁新成就</span>
          <div v-for="b in celebrating" :key="b.id" class="ach-item">
            <span class="ach-icon">{{ b.icon }}</span>
            <span><b>{{ b.title }}</b><small>{{ b.desc }}</small></span>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 页头 -->
    <div class="page-heading stats-head">
      <span class="eyebrow">LEARNING PULSE</span>
      <h1><span class="ph-emoji" aria-hidden="true">📊</span>你的学习节奏</h1>
      <p>每一次听懂，都在累积。</p>
    </div>

    <template v-if="Profile.ready">
      <!-- 词力档案 Hero -->
      <div class="profile-hero">
        <div class="hero-row">
          <div class="avatar-wrap">
            <div class="avatar-ring"><div class="avatar-inner" aria-hidden="true">🎓</div></div>
            <div class="lvl-badge">Lv.{{ Profile.level }} · {{ Profile.title }}</div>
          </div>

          <div class="hero-title-block">
            <div class="hero-name">
              <span>{{ Account.username || "游客" }}</span>
              <span class="crown" aria-hidden="true">👑</span>
            </div>
            <div class="hero-rank">
              <span class="hr-tag">🌟 {{ Profile.title }}</span>
              <span class="hr-tag">📅 累计活跃 {{ Profile.totalActiveDays }} 天</span>
            </div>
            <div class="xp-bar-wrap">
              <div class="xp-bar-head">
                <span class="cur">⚡ {{ Profile.xp }} XP</span>
                <span class="tgt"><template v-if="Profile.nextLevelXp != null">距下一级还差 <b>{{ Profile.nextLevelXp - Profile.xp }}</b> XP</template><template v-else>已达最高称号 🎉</template></span>
              </div>
              <div class="xp-bar"><div class="xp-fill" :style="{ width: (Profile.levelProgress * 100) + '%' }"></div></div>
            </div>
          </div>

          <div class="lvl-ring">
            <div class="donut-chart" role="img" :aria-label="`词力等级 ${Profile.level} 级 ${Profile.title}`">
              <svg width="124" height="124" viewBox="0 0 132 132" aria-hidden="true">
                <circle cx="66" cy="66" r="52" fill="none" stroke="var(--panel3)" stroke-width="12"></circle>
                <circle class="dn-fg" cx="66" cy="66" r="52" fill="none" stroke-width="12"
                        :stroke-dasharray="DONUT_LEN"
                        :stroke-dashoffset="donutGrown ? DONUT_LEN * (1 - Profile.levelProgress) : DONUT_LEN"></circle>
              </svg>
              <b>Lv.{{ Profile.level }}</b>
              <small>{{ Profile.title }}</small>
            </div>
          </div>
        </div>

        <div class="quick-stats">
          <div class="q-stat">
            <span class="qs-ic" aria-hidden="true">🔥</span>
            <div class="qs-body">
              <div class="qs-v">{{ stats.streak }}</div>
              <div class="qs-k">连续打卡(天)</div>
            </div>
          </div>
          <div class="q-stat">
            <span class="qs-ic" aria-hidden="true">⏳</span>
            <div class="qs-body">
              <div class="qs-v" :style="stats.due_soon ? 'color:var(--red)' : ''">{{ stats.due_soon || 0 }}</div>
              <div class="qs-k">两天内到期复习</div>
            </div>
          </div>
          <div class="q-stat">
            <span class="qs-ic" aria-hidden="true">📝</span>
            <div class="qs-body">
              <div class="qs-v">{{ stats.total_memorize_right }}</div>
              <div class="qs-k">累计背诵对</div>
            </div>
          </div>
          <div class="q-stat">
            <span class="qs-ic" aria-hidden="true">🎧</span>
            <div class="qs-body">
              <div class="qs-v">{{ stats.total_right }}</div>
              <div class="qs-k">累计听打对</div>
            </div>
          </div>
          <div class="q-stat">
            <span class="qs-ic" aria-hidden="true">❌</span>
            <div class="qs-body">
              <div class="qs-v">{{ stats.total_wrong }}</div>
              <div class="qs-k">累计答错</div>
            </div>
          </div>
          <div class="q-stat">
            <span class="qs-ic" aria-hidden="true">📚</span>
            <div class="qs-body">
              <div class="qs-v">{{ stats.wrong_words }}</div>
              <div class="qs-k">错词本</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 词力成长线 + 听打累计正确率 -->
      <div class="grid-2 stat-rows">
        <div class="card level-card">
          <div class="sec-head">
            <span class="sh-emoji" aria-hidden="true">🌳</span>
            <div>
              <div class="sh-title">词力等级</div>
              <div class="sh-sub">听打 · 背诵 · 选词 · 冲刺 · 每日挑战都算经验</div>
            </div>
          </div>
          <p class="level-xp">
            经验 {{ Profile.xp }}<template v-if="Profile.nextLevelXp != null"> · 距下一级还差 <b>{{ Profile.nextLevelXp - Profile.xp }}</b></template><template v-else> · 已达最高称号 🎉</template>
          </p>
          <a class="tree-mini" href="#/tree" :class="{ wilted: Profile.treeWilted }">
            <span class="tm-icon" aria-hidden="true">
              <TreeArt :stage="Profile.treeStage" :wilted="Profile.treeWilted" :size="34"></TreeArt>
            </span>
            <span class="tm-body"><b>单词树 · {{ Profile.treeLabel }}</b>
              <small>连续活跃 {{ Profile.streak }} 天 · 累计 {{ Profile.totalActiveDays }} 天{{ Profile.treeWilted ? " · 枯萎了，快去浇水" : (Profile.treeNeedsWater ? " · 今天还没浇水" : "") }}</small>
            </span>
            <em aria-hidden="true">→</em>
          </a>
          <div class="controls">
            <button class="btn ghost sm" @click="badgeShareOpen = true">🎖 分享我的勋章</button>
            <button class="btn ghost sm" :disabled="weeklyLoading" @click="openWeekly">📅 分享本周周报</button>
          </div>
        </div>

        <div class="card acc-card">
          <div class="sec-head">
            <span class="sh-emoji" aria-hidden="true">🎯</span>
            <div>
              <div class="sh-title">听打累计正确率</div>
              <div class="sh-sub">全部历史数据 · 实时推导</div>
            </div>
          </div>
          <div class="acc-layout">
            <div class="donut-chart" role="img" :aria-label="`听打累计正确率 ${Math.round(dictationAcc * 100)}%`">
              <svg width="132" height="132" viewBox="0 0 132 132" aria-hidden="true">
                <circle cx="66" cy="66" r="52" fill="none" stroke="var(--panel3)" stroke-width="12"></circle>
                <circle class="dn-fg" cx="66" cy="66" r="52" fill="none" stroke-width="12"
                        :stroke-dasharray="DONUT_LEN"
                        :stroke-dashoffset="donutGrown ? DONUT_LEN * (1 - dictationAcc) : DONUT_LEN"></circle>
              </svg>
              <b>{{ Math.round(dictationAcc * 100) }}%</b>
              <small>ALL TIME</small>
            </div>
            <div class="acc-side">
              <div class="acc-line">累计听打 <b>{{ stats.total_right }}</b> 对 / <b>{{ stats.total_wrong }}</b> 错</div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 首答真实统计 + 最近 14 天 -->
    <div class="grid-2 stat-rows">
      <div class="card">
        <div class="sec-head">
          <span class="sh-emoji" aria-hidden="true">🎮</span>
          <div>
            <div class="sh-title">首答真实统计</div>
            <div class="sh-sub">各模式第一次作答的对错 · 不含修改后重答</div>
          </div>
        </div>
        <div class="mode-list">
          <div v-for="(m, key) in stats.practice_modes" :key="key" class="mode-row">
            <span class="mode-dot" aria-hidden="true"></span>
            <span class="mode-name">{{ modeNames[key] || key }}</span>
            <span class="mini-bar mode-bar"><span class="mini-bar-fill" :style="{ width: Math.round(m.first_accuracy * 100) + '%' }"></span></span>
            <span class="mode-val">{{ Math.round(m.first_accuracy * 100) }}%</span>
            <span class="mode-sub">首答 {{ m.first_right }} 对 / {{ m.first_wrong }} 错</span>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="sec-head">
          <span class="sh-emoji" aria-hidden="true">📈</span>
          <div>
            <div class="sh-title">最近 14 天</div>
            <div class="sh-sub">每天答对 + 答错总题数</div>
          </div>
        </div>
        <div class="bars">
          <div v-for="(d, bi) in last14" :key="d.day" class="bar">
            <div class="fill" :style="{ height: (d.total / maxDay * 100) + '%', '--bi': bi }"></div>
            <div class="day">{{ d.day }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 打卡热力图 -->
    <div class="card heatmap-card">
      <div class="sec-head hm-head">
        <span class="sh-emoji" aria-hidden="true">📅</span>
        <div>
          <div class="sh-title">打卡热力图</div>
          <div class="sh-sub">近半年 · 颜色越亮练得越多</div>
        </div>
        <div class="hm-stats">
          <div class="hm-stat"><div class="v green">{{ heatmap.filter((c) => c.n > 0).length }}</div><div class="k">天有记录</div></div>
          <div class="hm-stat"><div class="v orange">{{ stats.streak }}</div><div class="k">当前连续</div></div>
          <div class="hm-stat"><div class="v purple">{{ stats.total_right }}</div><div class="k">累计答对</div></div>
        </div>
      </div>
      <div class="hm-body">
        <div class="hm-days" aria-hidden="true">
          <div>一</div><div>三</div><div>五</div><div>日</div>
        </div>
        <div class="hm-grid-wrap">
          <div class="heat-grid" role="img" aria-label="近半年打卡热力图" :style="{ '--weeks': Math.ceil(heatmap.length / 7) }">
            <span v-for="c in heatmap" :key="c.day" class="heat-cell"
                  :class="'lvl' + c.lvl" :title="`${c.day} · ${c.n} 题`"></span>
          </div>
        </div>
      </div>
      <div class="heat-legend"><span>少</span>
        <span class="heat-cell lvl0"></span><span class="heat-cell lvl1"></span><span class="heat-cell lvl2"></span><span class="heat-cell lvl3"></span><span class="heat-cell lvl4"></span>
        <span>多</span>
      </div>
    </div>

    <template v-if="speedView">
      <div class="card">
        <div class="sec-head">
          <span class="sh-emoji" aria-hidden="true">⚡</span>
          <div>
            <div class="sh-title">打字速度</div>
            <div class="sh-sub">正确完成每词平均耗时 · 秒</div>
          </div>
        </div>
        <svg viewBox="0 0 100 40" preserveAspectRatio="none" class="spark" aria-hidden="true">
          <defs>
            <linearGradient id="sparkAreaSpeed" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="var(--green)" stop-opacity="0.35"></stop>
              <stop offset="100%" stop-color="var(--green)" stop-opacity="0"></stop>
            </linearGradient>
          </defs>
          <polygon :points="speedView.points + ' 100,40 0,40'" fill="url(#sparkAreaSpeed)"></polygon>
          <polyline :points="speedView.points" fill="none" stroke="var(--accent)" stroke-width="1.6"
                    stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
        </svg>
        <div class="spark-cap">
          <span>平均 {{ speedView.avg }}s / 词</span>
          <span class="cap-hi">最近 {{ speedView.latest }}s</span>
          <span>{{ speedView.n }} 天样本</span>
        </div>
      </div>
    </template>

    <template v-if="typing && (wpmView || typing.heatmap.length)">
      <div class="card">
        <div class="sec-head">
          <span class="sh-emoji" aria-hidden="true">⌨️</span>
          <div>
            <div class="sh-title">打字数据</div>
            <div class="sh-sub">近 30 天 WPM · 近 90 天错键</div>
          </div>
        </div>
        <div class="tier-line">
          <span class="tier-badge">{{ TIER_ICON[typing.tier] || "🥉" }} {{ typing.tier }}</span>
          <span class="tier-sub">近 7 天均速 <b>{{ typing.wpm7 }}</b> WPM · 最快 {{ wpmView ? wpmView.best : 0 }} WPM</span>
        </div>
        <svg v-if="wpmView" viewBox="0 0 100 40" preserveAspectRatio="none" class="spark" aria-hidden="true">
          <defs>
            <linearGradient id="sparkAreaWpm" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="var(--blue)" stop-opacity="0.35"></stop>
              <stop offset="100%" stop-color="var(--blue)" stop-opacity="0"></stop>
            </linearGradient>
          </defs>
          <polygon :points="wpmView.points + ' 100,40 0,40'" fill="url(#sparkAreaWpm)"></polygon>
          <polyline :points="wpmView.points" fill="none" stroke="var(--blue)" stroke-width="1.6"
                    stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
        </svg>
        <div v-if="wpmView" class="spark-cap">
          <span>WPM 曲线</span><span class="cap-hi">{{ wpmView.n }} 天样本</span>
        </div>
      </div>
      <div v-if="typing.heatmap.length" class="card">
        <div class="sec-head">
          <span class="sh-emoji" aria-hidden="true">🧩</span>
          <div>
            <div class="sh-title">高频错键</div>
            <div class="sh-sub">按期望键分组 · 括号内为出现次数</div>
          </div>
        </div>
        <div v-for="h in typing.heatmap" :key="h.expect" class="typo-row">
          <code class="typo-expect">{{ h.expect }}</code>
          <span class="typo-arrow">常打成</span>
          <code v-for="g in h.got" :key="g.key" class="typo-got">{{ g.key }}<i v-if="g.count > 1">×{{ g.count }}</i></code>
        </div>
      </div>
    </template>

    <template v-if="badges">
      <div class="card">
        <div class="sec-head">
          <span class="sh-emoji" aria-hidden="true">🏆</span>
          <div>
            <div class="sh-title">成就徽章</div>
            <div class="sh-sub">解锁一枚，就多一份坚持的证据</div>
          </div>
          <span class="sh-count">已解锁 {{ badges.filter(b => b.unlocked).length }} / {{ badges.length }}</span>
        </div>
        <div class="badge-wall">
          <div v-for="b in badges" :key="b.id" class="badge-chip" :class="{ on: b.unlocked }"
               :title="`${b.desc}（${b.progress}/${b.target}）`">
            <span class="bc-icon">{{ b.icon }}</span>
            <span class="bc-body"><b>{{ b.title }}</b><small>{{ b.unlocked ? b.desc : `${b.progress} / ${b.target}` }}</small>
              <span class="bc-bar"><span class="bc-bar-fill" :style="{ width: Math.min(100, (b.progress / (b.target || 1)) * 100) + '%' }"></span></span>
            </span>
          </div>
        </div>
      </div>
    </template>

    <ShareCard :open="badgeShareOpen" kind="badge" :payload="badgeSharePayload()" @close="badgeShareOpen = false" />
    <ShareCard v-if="weekly" :open="weeklyShareOpen" kind="weekly" :payload="weekly" @close="weeklyShareOpen = false" />
  </div>
</template>
