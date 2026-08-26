<script setup>
import { computed, onMounted, ref } from "vue";
import { api } from "../lib/core";
import { activity } from "../lib/stats";
import { Profile, refreshProfile } from "../lib/profile";

const stats = ref(null);
const error = ref("");
const badges = ref(null);
const celebrating = ref([]);

onMounted(async () => {
  await load();
  // 等两帧让圆环以满偏移渲染，再过渡到目标值形成生长动画
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  donutGrown.value = true;
});

const modeNames = { pure: "纯听写", assisted: "辅助听写", follow: "跟打", quiz: "听音选词", sprint: "限时冲刺", boss: "错词Boss战", match: "配对消消乐", arrange: "听音排句" };
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
  <div v-if="error" class="empty" role="alert"><p>{{ error }}</p><button class="btn primary" @click="load">重试</button></div>
  <div v-else-if="!stats" class="empty">加载中…</div>
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

    <div class="page-heading compact"><span class="eyebrow">LEARNING PULSE</span><h1>你的学习节奏</h1><p>每一次听懂，都在累积。</p></div>
    <div class="stat-cards">
      <div class="stat-card"><div class="num">{{ stats.streak }}</div><div class="lab">连续打卡(天)</div></div>
      <div class="stat-card"><div class="num" :style="stats.due_soon ? 'color:var(--red)' : ''">{{ stats.due_soon || 0 }}</div><div class="lab">⏳ 两天内到期复习</div></div>
      <div class="stat-card"><div class="num">{{ stats.total_memorize_right }}</div><div class="lab">累计背诵对</div></div>
      <div class="stat-card"><div class="num">{{ stats.total_right }}</div><div class="lab">累计听打对</div></div>
      <div class="stat-card"><div class="num">{{ stats.total_wrong }}</div><div class="lab">累计答错</div></div>
      <div class="stat-card"><div class="num">{{ stats.wrong_words }}</div><div class="lab">错词本</div></div>
    </div>
    <!-- 词力等级：全程可见的成长线；小树入口 -->
    <template v-if="Profile.ready">
      <div class="section-title">词力等级<small>听打 · 背诵 · 选词 · 冲刺 · 每日挑战都算经验</small></div>
      <div class="stat-card level-card">
        <div class="donut-chart" role="img" :aria-label="`词力等级 ${Profile.level} 级 ${Profile.title}`">
          <svg width="132" height="132" viewBox="0 0 132 132" aria-hidden="true">
            <circle cx="66" cy="66" r="52" fill="none" stroke="var(--panel3)" stroke-width="12"></circle>
            <circle class="dn-fg" cx="66" cy="66" r="52" fill="none" stroke-width="12"
                    :stroke-dasharray="DONUT_LEN"
                    :stroke-dashoffset="donutGrown ? DONUT_LEN * (1 - Profile.levelProgress) : DONUT_LEN"></circle>
          </svg>
          <b>Lv.{{ Profile.level }}</b>
          <small>{{ Profile.title }}</small>
        </div>
        <div class="level-side">
          <p class="level-xp">
            经验 {{ Profile.xp }}<template v-if="Profile.nextLevelXp != null"> · 距下一级还差 <b>{{ Profile.nextLevelXp - Profile.xp }}</b></template><template v-else> · 已达最高称号 🎉</template>
          </p>
          <a class="tree-mini" href="#/tree" :class="{ wilted: Profile.treeWilted }">
            <span class="tm-icon" aria-hidden="true">{{ Profile.treeIcon }}</span>
            <span class="tm-body"><b>单词树 · {{ Profile.treeLabel }}</b>
              <small>连续活跃 {{ Profile.streak }} 天 · 累计 {{ Profile.totalActiveDays }} 天{{ Profile.treeWilted ? " · 枯萎了，快去浇水" : (Profile.treeNeedsWater ? " · 今天还没浇水" : "") }}</small>
            </span>
            <em aria-hidden="true">→</em>
          </a>
        </div>
      </div>
    </template>

    <div class="section-title">首答真实统计</div>
    <div class="stat-cards">
      <div v-for="(m, key) in stats.practice_modes" :key="key" class="stat-card">
        <div class="num">{{ Math.round(m.first_accuracy * 100) }}%</div>
        <div class="lab">{{ modeNames[key] || key }} · 首答 {{ m.first_right }} 对 / {{ m.first_wrong }} 错</div>
      </div>
    </div>
    <div class="section-title">听打累计正确率</div>
    <div class="stat-card" style="padding:22px 16px 18px;">
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
      <div class="lab" style="margin-top:12px;">累计听打 {{ stats.total_right }} 对 / {{ stats.total_wrong }} 错</div>
    </div>
    <div class="section-title">最近 14 天</div>
    <div class="stat-card" style="padding:14px 10px 26px;">
      <div class="bars">
        <div v-for="(d, bi) in last14" :key="d.day" class="bar">
          <div class="fill" :style="{ height: (d.total / maxDay * 100) + '%', '--bi': bi }"></div>
          <div class="day">{{ d.day }}</div>
        </div>
      </div>
    </div>

    <div class="section-title">打卡热力图<small>近半年 · 颜色越亮练得越多</small></div>
    <div class="stat-card" style="padding:18px 16px;">
      <div class="heat-grid" role="img" aria-label="近半年打卡热力图">
        <span v-for="c in heatmap" :key="c.day" class="heat-cell"
              :class="'lvl' + c.lvl" :title="`${c.day} · ${c.n} 题`"></span>
      </div>
      <div class="heat-legend"><span>少</span>
        <span class="heat-cell lvl0"></span><span class="heat-cell lvl1"></span><span class="heat-cell lvl2"></span><span class="heat-cell lvl3"></span><span class="heat-cell lvl4"></span>
        <span>多</span>
      </div>
    </div>

    <template v-if="speedView">
      <div class="section-title">打字速度<small>正确完成每词平均耗时 · 秒</small></div>
      <div class="stat-card" style="padding:18px 16px 12px;">
        <svg viewBox="0 0 100 40" preserveAspectRatio="none" class="spark" aria-hidden="true">
          <polyline :points="speedView.points" fill="none" stroke="var(--accent)" stroke-width="1.6"
                    stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
        </svg>
        <div class="spark-cap">
          <span>平均 {{ speedView.avg }}s / 词</span>
          <span style="color:var(--accent-strong)">最近 {{ speedView.latest }}s</span>
          <span>{{ speedView.n }} 天样本</span>
        </div>
      </div>
    </template>

    <template v-if="badges">
    <div class="section-title">成就徽章<small>{{ badges.filter(b => b.unlocked).length }} / {{ badges.length }} 已解锁</small></div>
    <div class="badge-wall">
      <div v-for="b in badges" :key="b.id" class="badge-chip" :class="{ on: b.unlocked }"
           :title="`${b.desc}（${b.progress}/${b.target}）`">
        <span class="bc-icon">{{ b.icon }}</span>
        <span class="bc-body"><b>{{ b.title }}</b><small>{{ b.unlocked ? b.desc : `${b.progress} / ${b.target}` }}</small></span>
      </div>
    </div>
    </template>
  </div>
</template>
