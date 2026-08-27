<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api } from "../lib/core";
import { Account, refreshAccount } from "../lib/account";

const loading = ref(true);
const error = ref("");
const data = ref(null);
const meUser = ref(null);
const myUserId = ref("");
const activity = ref([]);
const searchQuery = ref("");
const searchResults = ref([]);
const searching = ref(false);
const copiedInvite = ref(false);
let mounted = true;
let searchTimer = null;

onMounted(async () => {
  try {
    await refreshAccount();
  } catch { /* 网络错也按未登录处理 */ }
  if (Account.authenticated) await load();
  else { loading.value = false; }
});

onUnmounted(() => {
  mounted = false;
  if (searchTimer) clearTimeout(searchTimer);
});

async function load() {
  if (!Account.authenticated) { loading.value = false; return; }
  loading.value = true;
  error.value = "";
  try {
    const [me, friendsData, actData] = await Promise.all([
      api("/auth/me"),
      api("/friends"),
      api("/friends/activity"),
    ]);
    if (!mounted) return;
    meUser.value = me.user;
    myUserId.value = me.user;
    data.value = friendsData;
    activity.value = actData.events || [];
    loading.value = false;
  } catch (err) {
    if (!mounted) return;
    if (isAuthError(err)) { handleLogout(); return; }
    error.value = err.message || "好友数据加载失败";
    loading.value = false;
  }
}

function isAuthError(err) {
  return err.message && (err.message.includes("请先登录") || err.message.includes("401"));
}

function handleLogout() {
  Account.authenticated = false;
  Account.guest = true;
  loading.value = false;
}

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer);
  const q = searchQuery.value.trim();
  if (!q) { searchResults.value = []; return; }
  searchTimer = setTimeout(() => doSearch(q), 350);
}

async function doSearch(q) {
  searching.value = true;
  try {
    const d = await api(`/friends/search?q=${encodeURIComponent(q)}`);
    if (!mounted) return;
    searchResults.value = d.users || [];
  } catch {
    searchResults.value = [];
  }
  searching.value = false;
}

async function addFriend(u) {
  try {
    await api("/friends/add", { method: "POST", body: JSON.stringify({ user_id: u.user_id }) });
    await reloadFriends();
    // 更新搜索结果中的 relation 状态
    searchResults.value = searchResults.value.map((r) =>
      r.user_id === u.user_id ? { ...r, relation: "outgoing" } : r);
  } catch (err) {
    if (isAuthError(err)) { handleLogout(); return; }
    alert(err.message || "操作失败");
  }
}

async function acceptRequest(u) {
  try {
    await api("/friends/accept", { method: "POST", body: JSON.stringify({ user_id: u.user_id }) });
    await reloadFriends();
  } catch (err) {
    if (isAuthError(err)) { handleLogout(); return; }
    alert(err.message || "操作失败");
  }
}

async function rejectOrRemove(u) {
  if (!confirm(`确定要移除 ${u.username} 吗？`)) return;
  try {
    await api("/friends/reject", { method: "POST", body: JSON.stringify({ user_id: u.user_id }) });
    await reloadFriends();
    // 更新搜索结果
    searchResults.value = searchResults.value.map((r) =>
      r.user_id === u.user_id ? { ...r, relation: "none" } : r);
  } catch (err) {
    if (isAuthError(err)) { handleLogout(); return; }
    alert(err.message || "操作失败");
  }
}

async function removeFriendFromCard(u) {
  if (!confirm(`确定要删除好友 ${u.username} 吗？`)) return;
  try {
    await api("/friends/reject", { method: "POST", body: JSON.stringify({ user_id: u.user_id }) });
    await reloadFriends();
  } catch (err) {
    if (isAuthError(err)) { handleLogout(); return; }
    alert(err.message || "操作失败");
  }
}

async function reloadFriends() {
  try {
    const [friendsData, actData] = await Promise.all([
      api("/friends"),
      api("/friends/activity"),
    ]);
    if (!mounted) return;
    data.value = friendsData;
    activity.value = actData.events || [];
  } catch { /* 刷新失败不阻塞页面 */ }
}

async function copyInviteLink() {
  try {
    const link = `${location.origin}/#/account?invite=${myUserId.value}`;
    await navigator.clipboard.writeText(link);
    copiedInvite.value = true;
    setTimeout(() => { copiedInvite.value = false; }, 2000);
  } catch { /* 剪贴板不可用 */ }
}

function relationLabel(r) {
  if (r === "none") return null;
  if (r === "friends") return "已是好友";
  if (r === "outgoing") return "已申请";
  if (r === "incoming") return "对方已申请";
  return null;
}

function timeAgo(iso) {
  if (!iso) return "很久没来";
  // 后端 SQLite 返回 UTC 时间但不带时区后缀，需追加 Z 让 Date 按 UTC 解析
  const normalized = /Z|[+-]\d{2}:\d{2}$/.test(iso) ? iso : iso + "Z";
  const diff = Date.now() - new Date(normalized).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  return `${days} 天前`;
}

function avatarLetter(name) {
  return (name || "?").charAt(0).toUpperCase();
}

const incoming = computed(() => data.value?.requests?.incoming || []);
const outgoing = computed(() => data.value?.requests?.outgoing || []);
const friends = computed(() => data.value?.friends || []);
const maxFriends = computed(() => data.value?.max || 100);

const activityIcons = {
  sprint_record: { icon: "⚡", text: (e) => `${e.name} 冲刺新纪录 ${e.score} 分` },
  daily_complete: { icon: "📅", text: (e) => `${e.name} 完成每日挑战，得分 ${e.score}/${e.total}` },
  level_up: { icon: "🎖", text: (e) => `${e.name} 升到 Lv.${e.level} ${e.title || ""}` },
  friend_join: { icon: "🤝", text: (e) => {
    const partner = e.with ? activity.value.find((a) => a.kind === "friend_join" && a.user === e.with) : null;
    return partner ? `${e.name} 和 ${partner.name} 结为好友` : `${e.name} 结交了新好友`;
  }},
};
</script>

<template>
  <div v-if="!Account.loading && !Account.authenticated" class="empty login-gate" role="alert">
    <p class="gate-title">好友与动态需要登录</p>
    <p class="gate-sub">登录后可以搜索好友、查看彼此的学习动态。</p>
    <a class="btn primary" href="#/account">去登录 / 注册</a>
  </div>

  <div v-else-if="error" class="empty" role="alert">
    <p>{{ error }}</p>
    <button class="btn primary" @click="load">重试</button>
  </div>
  <div v-else-if="loading || !data" class="empty">加载中…</div>

  <div v-else class="friends-page">
    <div class="page-heading compact">
      <span class="eyebrow">SOCIAL HUB</span>
      <h1>好友与动态</h1>
      <p>一起学，一起进步。</p>
    </div>

    <!-- 搜索栏 -->
    <div class="friends-search-row">
      <div class="search-input-wrap">
        <input v-model="searchQuery" type="text" placeholder="搜索用户名"
          class="friends-search" @input="onSearchInput">
        <span v-if="searching" class="search-spin">…</span>
      </div>
      <button class="btn ghost sm" @click="copyInviteLink">
        {{ copiedInvite ? '已复制 ✓' : '我的邀请链接' }}
      </button>
    </div>

    <!-- 搜索结果 -->
    <div v-if="searchResults.length" class="search-results">
      <div v-for="u in searchResults" :key="u.user_id" class="search-row">
        <span class="sr-avatar">{{ avatarLetter(u.username) }}</span>
        <span class="sr-name">{{ u.username }}</span>
        <template v-if="u.relation === 'none'">
          <button class="btn primary sm" @click="addFriend(u)">加好友</button>
        </template>
        <template v-else-if="u.relation === 'outgoing'">
          <button class="btn ghost sm" @click="rejectOrRemove(u)">已申请 · 撤销</button>
        </template>
        <template v-else-if="u.relation === 'incoming'">
          <button class="btn primary sm" @click="acceptRequest(u)">回通过</button>
        </template>
        <template v-else>
          <span class="sr-tag">{{ relationLabel(u.relation) }}</span>
        </template>
      </div>
    </div>

    <!-- 申请区 -->
    <template v-if="incoming.length || outgoing.length">
      <div class="section-title" v-if="incoming.length"><span>收到的申请</span></div>
      <div v-for="u in incoming" :key="u.user_id" class="request-row">
        <span class="sr-avatar">{{ avatarLetter(u.username) }}</span>
        <span class="sr-name">{{ u.username }}</span>
        <button class="btn primary sm" @click="acceptRequest(u)">通过</button>
        <button class="btn ghost sm" @click="rejectOrRemove(u)">拒绝</button>
      </div>

      <div class="section-title" v-if="outgoing.length"><span>已发出的申请</span></div>
      <div v-for="u in outgoing" :key="u.user_id" class="request-row">
        <span class="sr-avatar">{{ avatarLetter(u.username) }}</span>
        <span class="sr-name">{{ u.username }}</span>
        <button class="btn ghost sm" @click="rejectOrRemove(u)">撤销</button>
      </div>
    </template>

    <!-- 好友列表 -->
    <div class="section-title">
      <span>好友 <small>{{ friends.length }} / {{ maxFriends }}</small></span>
      <span class="friends-links">
        <a href="#/groups" class="btn ghost sm">小组</a>
        <a href="#/leaderboard" class="btn ghost sm">排行</a>
      </span>
    </div>

    <div v-if="!friends.length" class="empty" style="padding:36px;">
      还没有好友，搜索用户名添加一个吧
    </div>

    <div v-else class="friend-grid">
      <div v-for="f in friends" :key="f.user_id" class="friend-card">
        <button class="fc-remove" title="删除好友" @click="removeFriendFromCard(f)">✕</button>
        <div class="fc-avatar">{{ avatarLetter(f.username) }}</div>
        <div class="fc-name">{{ f.username }}</div>
        <div class="fc-meta">
          <span class="chip lv-chip"><b>Lv.{{ f.level }}</b><span>{{ f.level_title }}</span></span>
        </div>
        <div class="fc-stats">
          <span>🔥 {{ f.streak }} 天</span>
          <span v-if="f.today_done">✓ 今日已练</span>
          <span v-else class="dim">今日未练</span>
        </div>
        <div class="fc-active">{{ timeAgo(f.last_active_at) }}</div>
      </div>
    </div>

    <!-- 动态时间线 -->
    <div class="section-title"><span>动态</span></div>
    <div v-if="!activity.length" class="empty" style="padding:36px;">
      还没有动态，练起来才有戏
    </div>
    <div v-else class="activity-timeline">
      <div v-for="(e, i) in activity" :key="i" class="act-row">
        <span class="act-icon">{{ (activityIcons[e.kind] || { icon: "📝" }).icon }}</span>
        <span class="act-text">{{ (activityIcons[e.kind] || { icon: "📝", text: () => e.kind }).text(e) }}</span>
        <span class="act-time">{{ timeAgo(e.created_at) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-gate { text-align: center; gap: 10px; }
.gate-title { font-size: 17px; font-weight: 750; margin: 0; }
.gate-sub { color: var(--dim); margin: 0 0 6px; max-width: 420px; }

.friends-search-row {
  display: flex; gap: 10px; align-items: center;
  margin-bottom: 16px;
}
.search-input-wrap {
  position: relative; flex: 1;
}
.friends-search {
  width: 100%; padding: 10px 14px;
  color: var(--text); background: var(--panel2);
  border: 1px solid var(--border); border-radius: 12px;
  font-size: 14px; outline: none;
  transition: border-color var(--dur-1), box-shadow var(--dur-1);
}
.friends-search:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent), transparent 86%);
}
.search-spin {
  position: absolute; right: 12px; top: 50%; transform: translateY(-50%);
  color: var(--dim2); font-size: 13px;
}

.search-results {
  display: flex; flex-direction: column; gap: 6px;
  margin-bottom: 20px; padding: 14px;
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 14px;
}
.search-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 6px; border-bottom: 1px solid var(--border);
}
.search-row:last-child { border-bottom: 0; }
.sr-avatar {
  display: grid; place-items: center; flex: none;
  width: 32px; height: 32px; border-radius: 10px;
  background: var(--accent-grad); color: var(--accent-text);
  font-family: var(--serif); font-size: 15px; font-weight: 800;
}
.sr-name { flex: 1; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sr-tag { color: var(--dim2); font-size: 12px; white-space: nowrap; }

.request-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; margin-bottom: 6px;
  background: color-mix(in srgb, var(--panel) 72%, transparent);
  border: 1px solid var(--border); border-radius: 14px;
}

.section-title { display: flex; align-items: center; justify-content: space-between; }
.friends-links { display: flex; gap: 6px; }

.friend-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px; margin-bottom: 10px;
}
.friend-card {
  position: relative;
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  padding: 22px 14px 18px;
  background: linear-gradient(160deg, var(--panel), color-mix(in srgb, var(--panel), var(--bg) 14%));
  border: 1px solid var(--border); border-radius: 18px;
  box-shadow: var(--shadow-soft);
  transition: transform var(--dur-2) var(--ease-out), border-color var(--dur-2);
}
.friend-card:hover {
  transform: translateY(-3px);
  border-color: color-mix(in srgb, var(--accent), var(--border) 55%);
}
.fc-remove {
  position: absolute; top: 10px; right: 10px;
  width: 26px; height: 26px; display: grid; place-items: center;
  border: none; border-radius: 8px; background: transparent;
  color: var(--dim2); font-size: 14px; cursor: pointer;
  transition: background var(--dur-1), color var(--dur-1);
}
.fc-remove:hover { background: color-mix(in srgb, var(--red), transparent 85%); color: var(--red); }
.fc-avatar {
  width: 48px; height: 48px; border-radius: 14px;
  background: var(--accent-grad); color: var(--accent-text);
  display: grid; place-items: center;
  font-family: var(--serif); font-size: 22px; font-weight: 800;
}
.fc-name { font-weight: 700; font-size: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
.fc-meta { display: flex; align-items: center; gap: 6px; }
.chip { display: inline-flex; align-items: center; gap: 4px; padding: 3px 9px;
  font-size: 11px; border-radius: 7px; background: var(--type-bg); color: var(--type-text); }
.chip b { font-size: 12px; }
.chip span { font-size: 11px; }
.fc-stats { display: flex; gap: 10px; color: var(--dim); font-size: 12px; }
.fc-stats .dim { opacity: .55; }
.fc-active { color: var(--dim2); font-size: 11px; }

.activity-timeline {
  display: flex; flex-direction: column; gap: 6px;
}
.act-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px;
  background: color-mix(in srgb, var(--panel) 72%, transparent);
  border: 1px solid var(--border); border-radius: 12px;
}
.act-icon { font-size: 18px; flex: none; }
.act-text { flex: 1; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.act-time { color: var(--dim2); font-size: 11px; white-space: nowrap; }

@media (max-width: 620px) {
  .friend-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .friends-search-row { flex-wrap: wrap; }
}
</style>
