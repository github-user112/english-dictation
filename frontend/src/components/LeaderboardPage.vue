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
  <div v-if="!Account.loading && !Account.authenticated" class="empty login-gate" role="alert">
    <p class="gate-title">登录后可上榜并追踪名次</p>
    <p class="gate-sub">注册一个账户，你的冲刺、每日、经验都会进入榜单，和所有人同台较量。</p>
    <a class="btn primary" href="#/account">去登录 / 注册</a>
  </div>

  <div v-else-if="error" class="empty" role="alert">
    <p>{{ error }}</p>
    <button class="btn primary" @click="retry">重试</button>
  </div>
  <div v-else-if="loading || !data" class="empty">加载中…</div>

  <div v-else class="leaderboard-page">
    <div class="page-heading compact">
      <span class="eyebrow">GLOBAL RANKING</span>
      <h1>排行榜</h1>
      <p>分数都来自真实学习记录，无法提交伪造。</p>
    </div>

    <div class="lb-controls">
      <div class="scope-group" role="tablist" aria-label="榜单分类">
        <button v-for="s in SCOPES" :key="s" class="btn"
          :class="{ active: scope === s }" role="tab"
          :aria-selected="scope === s" @click="go(s, period)">{{ SCOPE_LABELS[s] }}</button>
      </div>
      <div v-if="!PERIODLESS[scope]" class="scope-group period-group" role="group" aria-label="时间范围">
        <button v-for="p in PERIODS" :key="p" class="btn"
          :class="{ active: period === p }" @click="go(scope, p)">{{ PERIOD_LABELS[p] }}</button>
      </div>
    </div>

    <div class="lb-stat-bar">
      共 <b>{{ data.total_players }}</b> 人 · 我的排名 <b>{{ data.me_rank ? "#" + data.me_rank : "未上榜" }}</b>
    </div>

    <div v-if="!data.rows.length" class="empty lb-empty">这个榜单还没有人上榜，练一练就是第一</div>

    <ol v-else class="lb-list">
      <li v-for="row in data.rows" :key="row.user" class="lb-row"
        :class="{ me: row.user === meUser }">
        <span class="lb-rank">{{ rankBadge(row.rank) }}</span>
        <span class="lb-name">
          <b>{{ row.name }}</b>
          <small v-if="scope === 'xp' && row.level_title" class="lb-sub">{{ row.level_title }}</small>
        </span>
        <span class="lb-value">
          <b>{{ fmtValue(row) }}</b>
          <small v-if="scope === 'sprint'" class="lb-sub">连击 {{ row.combo }} · 共 {{ row.total }} 词</small>
        </span>
      </li>
    </ol>

    <p class="lb-note">accuracy 榜需首答 ≥20 次才上榜；分数均来自真实学习记录，无法提交伪造。</p>
  </div>
</template>

<style scoped>
.lb-controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.period-group { margin-left: auto; }
.lb-stat-bar { display: flex; gap: 6px; align-items: baseline; color: var(--dim); font-size: 13.5px; font-weight: 650; margin-bottom: 12px; }
.lb-stat-bar b { color: var(--text); }
.lb-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 7px; }
.lb-row { display: grid; grid-template-columns: 40px 1fr auto; align-items: center; gap: 12px;
  padding: 12px 14px; background: linear-gradient(165deg, var(--panel), color-mix(in srgb, var(--panel), var(--bg) 15%));
  border: 1px solid var(--border); border-radius: 16px 16px 16px 6px; }
.lb-row.me { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent) inset; background: color-mix(in srgb, var(--accent-grad) 8%, var(--panel)); }
.lb-rank { font-size: 18px; text-align: center; font-variant-numeric: tabular-nums; color: var(--dim); font-weight: 800; }
.lb-name { display: flex; flex-direction: column; min-width: 0; }
.lb-name b { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lb-value { text-align: right; display: flex; flex-direction: column; align-items: flex-end; }
.lb-value b { font-size: 18px; font-variant-numeric: tabular-nums; }
.lb-sub { color: var(--dim2); font-size: 11.5px; font-weight: 500; }
.lb-note { margin-top: 16px; color: var(--dim2); font-size: 12px; }
.login-gate { text-align: center; gap: 10px; }
.gate-title { font-size: 17px; font-weight: 750; margin: 0; }
.gate-sub { color: var(--dim); margin: 0 0 6px; max-width: 420px; }
</style>
