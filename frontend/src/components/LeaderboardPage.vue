<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { api } from "../lib/core";
import { Account, refreshAccount } from "../lib/account";

const props = defineProps({ params: { type: Object, default: null } });

const SCOPES = ["sprint", "daily", "xp", "streak", "accuracy"];
const SCOPE_LABELS = {
  sprint: "冲刺最高分", daily: "每日最佳", xp: "总经验",
  streak: "连续打卡", accuracy: "首答准确率",
};
// 这两个 scope 服务端强制 all，前端不显示周期筛选
const PERIODLESS = { sprint: true, streak: true };
const PERIODS = ["all", "monthly", "weekly"];
const PERIOD_LABELS = { all: "全部时间", monthly: "本月", weekly: "本周" };

const data = ref(null);
const meUser = ref(null);
const loading = ref(true);
const error = ref("");
let mounted = true;

const scope = ref("sprint");
const period = ref("all");

function rankBadge(rank) {
  if (rank === 1) return "🥇";
  if (rank === 2) return "🥈";
  if (rank === 3) return "🥉";
  return String(rank);
}

function fmtValue(row) {
  if (scope.value === "accuracy") return `${row.value}%`;
  return Number(row.value).toLocaleString("zh-CN");
}

function go(nextScope, nextPeriod) {
  const qs = new URLSearchParams();
  qs.set("scope", nextScope);
  if (nextPeriod && !PERIODLESS[nextScope]) qs.set("period", nextPeriod);
  location.hash = "#/leaderboard?" + qs.toString();
}

onMounted(async () => {
  // 登录判断：刷新账户单例；未登录只展示引导块，不拉榜单数据
  try {
    await refreshAccount();
  } catch { /* 网络错也按未登录处理，引导登录 */ }
  scope.value = props.params?.get("scope") || "sprint";
  if (!SCOPES.includes(scope.value)) scope.value = "sprint";
  period.value = props.params?.get("period") || "all";
  if (!PERIODS.includes(period.value)) period.value = "all";
  if (Account.authenticated) await load();
  else { loading.value = false; }
});

onUnmounted(() => { mounted = false; });

async function load() {
  if (!Account.authenticated) { loading.value = false; return; }
  loading.value = true;
  error.value = "";
  try {
    const qs = new URLSearchParams({ scope: scope.value, period: period.value });
    const [me, lb] = await Promise.all([
      api("/auth/me"),
      api(`/leaderboard?${qs}`),
    ]);
    if (!mounted) return;
    meUser.value = me.user;
    data.value = lb;
    loading.value = false;
  } catch (err) {
    if (!mounted) return;
    error.value = err.message || "排行榜加载失败";
    loading.value = false;
  }
}

function retry() { load(); }
</script>

<template>
  <!-- 登录引导：未登录时不拉榜单数据 -->
  <div v-if="!Account.loading && !Account.authenticated" class="empty login-gate" role="alert">
    <span class="emoji" aria-hidden="true">🔒</span>
    <h3>登录后可上榜</h3>
    <p>注册一个账户，你的冲刺、每日、经验都会进入榜单，和所有人同台较量。</p>
    <a class="btn primary" href="#/account">👤 去登录 / 注册</a>
  </div>

  <!-- 报错 -->
  <div v-else-if="error" class="empty" role="alert">
    <span class="emoji" aria-hidden="true">⚠️</span>
    <h3>加载失败</h3>
    <p>{{ error }}</p>
    <button class="btn primary" @click="retry">🔄 重试</button>
  </div>

  <!-- 加载中 -->
  <div v-else-if="loading || !data" class="empty loading"><span class="spin" aria-hidden="true"></span><span class="load-text">加载中…</span></div>

  <!-- 主内容 -->
  <div v-else class="leaderboard-page stagger-in">
    <!-- 页头 -->
    <div class="page-heading">
      <span class="eyebrow">GLOBAL RANKING</span>
      <h1>排行榜</h1>
      <p>分数都来自真实学习记录，无法提交伪造。</p>
    </div>

    <!-- My Rank Hero：金色皇家卡，展示我的排名与当前范围 -->
    <div class="lb-hero">
      <div class="lb-hero-left">
        <span class="lb-hero-emoji" aria-hidden="true">📊</span>
        <div class="lb-hero-text">
          <div class="lb-hero-lbl">我的排名</div>
          <div class="lb-hero-sub">{{ SCOPE_LABELS[scope] }} · {{ PERIODLESS[scope] ? "全时段" : PERIOD_LABELS[period] }}</div>
        </div>
      </div>
      <div class="lb-hero-rank">
        <span class="lb-hero-hash">#</span><span class="lb-hero-num">{{ data.me_rank || "—" }}</span>
      </div>
      <div class="lb-hero-total">
        <div class="lb-hero-total-num">{{ data.total_players }}</div>
        <div class="lb-hero-total-lbl">上榜人数</div>
      </div>
    </div>

    <!-- 控制区：范围 + 周期 -->
    <div class="lb-controls">
      <div class="scope-group" role="tablist" aria-label="榜单分类">
        <button v-for="s in SCOPES" :key="s" class="btn sm"
          :class="{ active: scope === s }" role="tab"
          :aria-selected="scope === s" @click="go(s, period)">{{ SCOPE_LABELS[s] }}</button>
      </div>
      <div v-if="!PERIODLESS[scope]" class="scope-group period-group" role="group" aria-label="时间范围">
        <button v-for="p in PERIODS" :key="p" class="btn sm"
          :class="{ active: period === p }" @click="go(scope, p)">{{ PERIOD_LABELS[p] }}</button>
      </div>
    </div>

    <!-- 统计条 -->
    <div class="lb-stat-bar">
      共 <b>{{ data.total_players }}</b> 人 · 我的排名 <b>{{ data.me_rank ? "#" + data.me_rank : "未上榜" }}</b>
    </div>

    <!-- 空态：无人上榜 -->
    <div v-if="!data.rows.length" class="empty lb-empty">这个榜单还没有人上榜，练一练就是第一</div>

    <!-- 领奖台（前 3 名）+ 剩余列表（第 4 名起） -->
    <template v-else>
      <div class="lb-podium">
        <div class="lb-podium-head">
          <span class="lb-podium-title">巅峰榜 TOP 3</span>
          <span class="lb-podium-sub">{{ SCOPE_LABELS[scope] }} · {{ PERIODLESS[scope] ? "全时段" : PERIOD_LABELS[period] }}</span>
        </div>
        <div class="lb-podium-row">
          <div v-for="row in data.rows.slice(0, 3)" :key="row.user" class="lb-row"
            :class="{ me: row.user === meUser, t1: row.rank === 1, t2: row.rank === 2, t3: row.rank === 3 }">
            <div class="lb-podium-medal" aria-hidden="true">{{ rankBadge(row.rank) }}</div>
            <div class="lb-podium-avatar" :class="'lb-avatar-' + (row.rank === 1 ? 'gold' : row.rank === 2 ? 'silver' : 'bronze')">
              <span class="lb-avatar-num">#{{ row.rank }}</span>
              <span v-if="row.rank === 1" class="lb-avatar-crown" aria-hidden="true">👑</span>
            </div>
            <div class="lb-podium-base">
              <b class="lb-name">{{ row.name }}</b>
              <div class="lb-value">
                <b>{{ fmtValue(row) }}</b>
              </div>
              <small v-if="scope === 'xp' && row.level_title" class="lb-sub">{{ row.level_title }}</small>
              <small v-else-if="scope === 'sprint'" class="lb-sub">连击 {{ row.combo }} · 共 {{ row.total }} 词</small>
            </div>
          </div>
        </div>
      </div>

      <ol v-if="data.rows.length > 3" class="lb-list">
        <li v-for="row in data.rows.slice(3)" :key="row.user" class="lb-row"
          :class="{ me: row.user === meUser }">
          <span class="lb-rank">
            <span class="lb-rank-num">#{{ row.rank }}</span>
          </span>
          <div class="lb-info">
            <b class="lb-name">{{ row.name }}</b>
            <small v-if="scope === 'xp' && row.level_title" class="lb-sub">{{ row.level_title }}</small>
            <small v-if="scope === 'sprint'" class="lb-sub">连击 {{ row.combo }} · 共 {{ row.total }} 词</small>
          </div>
          <div class="lb-value">
            <b>{{ fmtValue(row) }}</b>
          </div>
        </li>
      </ol>
    </template>

    <p class="lb-note">accuracy 榜需首答 ≥20 次才上榜；分数均来自真实学习记录，无法提交伪造。</p>
  </div>
</template>
