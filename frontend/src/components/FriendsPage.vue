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
let searchSeq = 0;   // L2: 同上，丢弃乱序返回的旧查询结果

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
  const seq = ++searchSeq;
  searching.value = true;
  try {
    const d = await api(`/friends/search?q=${encodeURIComponent(q)}`);
    if (!mounted || seq !== searchSeq) return;
    searchResults.value = d.users || [];
  } catch {
    if (seq !== searchSeq) return;
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
    <span class="emoji">🔒</span>
    <p class="gate-title">好友与动态需要登录</p>
    <p class="gate-sub">登录后可以搜索好友、查看彼此的学习动态。</p>
    <a class="btn primary" href="#/account">去登录 / 注册</a>
  </div>

  <div v-else-if="error" class="empty fp-err" role="alert">
    <span class="emoji">😵</span>
    <p>{{ error }}</p>
    <button class="btn primary" @click="load">重试</button>
  </div>

  <div v-else-if="loading || !data" class="empty loading"><span class="spin" aria-hidden="true"></span><span class="load-text">加载中…</span></div>

  <div v-else class="friends-page">
    <!-- ============ 页头 ============ -->
    <div class="fp-head">
      <div class="page-heading compact">
        <span class="eyebrow">SOCIAL HUB</span>
        <h1><span class="fp-emoji">👥</span>好友与动态</h1>
        <p>一起学，一起进步。</p>
      </div>
      <div class="fp-actions">
        <button class="btn ghost sm" @click="copyInviteLink">{{ copiedInvite ? '已复制 ✓' : '🔗 我的邀请链接' }}</button>
        <a class="btn ghost sm" href="#/groups">👨‍👩‍👧 小组</a>
        <a class="btn ghost sm" href="#/leaderboard">📊 排行</a>
      </div>
    </div>

    <!-- ============ 社交圈总览 ============ -->
    <div class="fp-hero">
      <div class="fp-hero-id">
        <div class="fp-hero-emoji">🦉</div>
        <div class="fp-hero-text">
          <div class="fp-hero-name">你的社交圈</div>
          <div class="fp-hero-sub">一起练习，一起进步，让学习不再孤单 💪</div>
        </div>
      </div>
      <div class="fp-hero-stats">
        <div class="fp-hs">
          <span class="ic">👥</span>
          <span class="v">{{ friends.length }}<small>/ {{ maxFriends }}</small></span>
          <span class="k">好友数</span>
        </div>
        <div class="fp-hs">
          <span class="ic">🔥</span>
          <span class="v">{{ friends.reduce((m, x) => Math.max(m, x.streak || 0), 0) }}</span>
          <span class="k">最长连胜</span>
        </div>
        <div class="fp-hs">
          <span class="ic">⚡</span>
          <span class="v">{{ friends.reduce((s, x) => s + (x.xp || 0), 0).toLocaleString() }}</span>
          <span class="k">好友总经验</span>
        </div>
        <div class="fp-hs">
          <span class="ic">📢</span>
          <span class="v">{{ activity.length }}</span>
          <span class="k">最新动态</span>
        </div>
      </div>
    </div>

    <!-- ============ 主网格 ============ -->
    <div class="fp-main">
      <!-- ===== 左列：好友列表 + 好友申请 ===== -->
      <div class="fp-col">
        <div class="fp-card fp-list">
          <div class="fp-head-row">
            <div class="t"><span class="ic">📋</span>好友列表</div>
            <div class="c">共 <b>{{ friends.length }}</b> 位 · 上限 {{ maxFriends }}</div>
          </div>

          <div v-if="!friends.length" class="empty fp-empty">
            <span class="emoji">🤝</span>
            <h3>还没有好友</h3>
            <p>在右边搜索用户名，添加第一个练习伙伴吧。</p>
          </div>

          <div v-else class="fp-rows">
            <div v-for="(f, i) in friends" :key="f.user_id" class="step-item fp-row">
              <div class="fp-rank" :class="{ top1: i === 0, top2: i === 1, top3: i === 2 }">{{ i + 1 }}</div>
              <div class="fp-avatar" :class="['green', 'gold', 'orange', 'blue', 'purple', 'red'][(f.username || '?').charCodeAt(0) % 6]">{{ ['🦊', '🦉', '🐯', '🐰', '🐼', '🐻', '🐶', '🦁', '🐨', '🐱', '🐷', '🦄'][(f.username || '?').charCodeAt(0) % 12] }}</div>
              <div class="fp-body">
                <div class="fp-name">
                  <span class="uname">{{ f.username }}</span>
                  <span class="badge badge-purple">🏆 Lv.{{ f.level }}</span>
                  <span class="lv-title">{{ f.level_title }}</span>
                </div>
                <div class="fp-meta">
                  <span><span class="ic">🔥</span>{{ f.streak }} 天连胜</span>
                  <span><span class="ic">⚡</span>{{ (f.xp || 0).toLocaleString() }} XP</span>
                  <span class="fp-dim"><span class="ic">🕒</span>{{ timeAgo(f.last_active_at) }}</span>
                </div>
                <div class="fp-cmp" :title="'好友群最长连胜 ' + friends.reduce((m, x) => Math.max(m, x.streak || 0), 0) + ' 天，虚线为平均连胜'">
                  <span class="fp-cmp-ic">🔥</span>
                  <div class="mini-bar fp-bar">
                    <span class="mini-bar-fill green" :style="{ width: (Math.min(100, (f.streak || 0) / Math.max(1, friends.reduce((m, x) => Math.max(m, x.streak || 0), 0)) * 100)) + '%' }"></span>
                    <span class="fp-cmp-mark" :style="{ left: (Math.min(100, (friends.length ? friends.reduce((s, x) => s + (x.streak || 0), 0) / friends.length : 0) / Math.max(1, friends.reduce((m, x) => Math.max(m, x.streak || 0), 0)) * 100)) + '%' }"></span>
                  </div>
                  <b class="fp-cmp-val">{{ f.streak }}<small>天</small></b>
                </div>
              </div>
              <div class="fp-acts">
                <span v-if="f.today_done" class="badge-soft green">✓ 今日已练</span>
                <span v-else class="badge-soft gray">今日未练</span>
                <button class="fp-del" title="删除好友" @click="removeFriendFromCard(f)">✕</button>
              </div>
            </div>
          </div>
        </div>

        <!-- 好友申请（互相关注） -->
        <template v-if="incoming.length || outgoing.length">
          <div class="fp-card fp-req">
            <div class="fp-head-row">
              <div class="t"><span class="ic">🤝</span>好友申请</div>
              <div class="c">收到 <b>{{ incoming.length }}</b> · 发出 <b>{{ outgoing.length }}</b></div>
            </div>

            <template v-if="incoming.length">
              <div class="fp-req-sub">收到的申请</div>
              <div v-for="u in incoming" :key="u.user_id" class="fp-srow">
                <div class="fp-avatar sm" :class="['green', 'gold', 'orange', 'blue', 'purple', 'red'][(u.username || '?').charCodeAt(0) % 6]">{{ ['🦊', '🦉', '🐯', '🐰', '🐼', '🐻', '🐶', '🦁', '🐨', '🐱', '🐷', '🦄'][(u.username || '?').charCodeAt(0) % 12] }}</div>
                <div class="fp-sinfo">
                  <b>{{ u.username }}</b>
                  <small>发来好友申请</small>
                </div>
                <button class="btn green sm" @click="acceptRequest(u)">✓ 通过</button>
                <button class="btn ghost sm" @click="rejectOrRemove(u)">拒绝</button>
              </div>
            </template>

            <template v-if="outgoing.length">
              <div class="fp-req-sub">已发出的申请</div>
              <div v-for="u in outgoing" :key="u.user_id" class="fp-srow">
                <div class="fp-avatar sm" :class="['green', 'gold', 'orange', 'blue', 'purple', 'red'][(u.username || '?').charCodeAt(0) % 6]">{{ ['🦊', '🦉', '🐯', '🐰', '🐼', '🐻', '🐶', '🦁', '🐨', '🐱', '🐷', '🦄'][(u.username || '?').charCodeAt(0) % 12] }}</div>
                <div class="fp-sinfo">
                  <b>{{ u.username }}</b>
                  <small>等待对方回复</small>
                </div>
                <button class="btn ghost sm" @click="rejectOrRemove(u)">撤销</button>
              </div>
            </template>
          </div>
        </template>
      </div>

      <!-- ===== 右列：添加好友 + 动态 ===== -->
      <div class="fp-col fp-side">
        <div class="fp-card fp-add">
          <div class="fp-head-row">
            <div class="t"><span class="ic">➕</span>添加好友</div>
            <div class="c">输入用户名即可搜索</div>
          </div>

          <div class="fp-search">
            <span class="s-ic">🔍</span>
            <input v-model="searchQuery" type="text" placeholder="搜索用户名" class="form-input" @input="onSearchInput">
            <span v-if="searching" class="search-spin">…</span>
          </div>

          <div v-if="searchResults.length" class="fp-slist">
            <div v-for="u in searchResults" :key="u.user_id" class="fp-srow">
              <div class="fp-avatar sm" :class="['green', 'gold', 'orange', 'blue', 'purple', 'red'][(u.username || '?').charCodeAt(0) % 6]">{{ ['🦊', '🦉', '🐯', '🐰', '🐼', '🐻', '🐶', '🦁', '🐨', '🐱', '🐷', '🦄'][(u.username || '?').charCodeAt(0) % 12] }}</div>
              <div class="fp-sinfo">
                <b>{{ u.username }}</b>
                <small>{{ relationLabel(u.relation) || '还不是好友' }}</small>
              </div>
              <template v-if="u.relation === 'none'">
                <button class="btn green sm" @click="addFriend(u)">➕ 加好友</button>
              </template>
              <template v-else-if="u.relation === 'outgoing'">
                <button class="btn ghost sm" @click="rejectOrRemove(u)">已申请 · 撤销</button>
              </template>
              <template v-else-if="u.relation === 'incoming'">
                <button class="btn green sm" @click="acceptRequest(u)">✓ 回通过</button>
              </template>
              <template v-else>
                <span class="badge-soft gray">{{ relationLabel(u.relation) }}</span>
              </template>
            </div>
          </div>
          <p v-else-if="searchQuery.trim()" class="fp-hint">没有找到匹配的用户，换个用户名试试。</p>
        </div>

        <div class="fp-card fp-feed">
          <div class="fp-head-row">
            <div class="t"><span class="ic">📢</span>好友动态</div>
            <div class="c">最近 <b>{{ activity.length }}</b> 条</div>
          </div>

          <div v-if="!activity.length" class="empty fp-empty">
            <span class="emoji">📭</span>
            <h3>还没有动态</h3>
            <p>好友练起来才有戏。</p>
          </div>

          <div v-else class="fp-actlist">
            <div v-for="(e, i) in activity" :key="i" class="fp-act">
              <div class="fp-act-ic">{{ (activityIcons[e.kind] || { icon: "📝" }).icon }}</div>
              <div class="fp-act-body">
                <p class="fp-act-text">{{ (activityIcons[e.kind] || { icon: "📝", text: () => e.kind }).text(e) }}</p>
                <span class="fp-act-time">{{ timeAgo(e.created_at) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 本页布局 / hero / 卡片 / 行样式全部落在 styles/pages/19-friends.css（级联第 3 层）。
   此处只放组件私有、且渲染在 .friends-page 之外的门控态与错误态。 */
.login-gate { padding: 52px 24px; }
.login-gate .gate-title { font-size: 17px; font-weight: 900; color: var(--text); margin: 0 0 5px; }
.login-gate .gate-sub { color: var(--text-dim); font-size: 13.5px; font-weight: 600; margin: 0 0 16px; max-width: 420px; }
.login-gate .btn { animation: rise-in .5s var(--ease-out) both; animation-delay: .25s; }

.fp-err { padding: 34px 24px; }
.fp-err p { color: var(--red-dark); font-weight: 800; font-size: 14px; margin-bottom: 14px; }
:root[data-theme="dark"] .fp-err p { color: var(--red); }
</style>
