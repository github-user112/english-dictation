<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { api } from "../lib/core";
import { Account, refreshAccount } from "../lib/account";

const props = defineProps({ params: { type: Object, default: null } });

const loading = ref(true);
const error = ref("");
const groups = ref([]);
const showCreate = ref(false);
const newName = ref("");
const createLoading = ref(false);
const createError = ref("");
const searchQ = ref("");
const searching = ref(false);
const searchResults = ref([]);
const searchError = ref("");
const joinLoading = ref("");
const autoMsg = ref("");
let mounted = true;
let searchTimer = null;
let searchSeq = 0;   // L2: 搜索请求序，丢弃乱序返回的旧查询结果

onMounted(async () => {
  try {
    await refreshAccount();
  } catch { /* 网络错也按未登录处理 */ }
  if (!Account.authenticated) { loading.value = false; return; }
  const joinGid = props.params?.get("join");
  if (joinGid) await handleAutoJoin(joinGid);
  await loadMyGroups();
});

onUnmounted(() => {
  mounted = false;
  if (searchTimer) clearTimeout(searchTimer);
});

function clearJoinQuery() {
  try {
    history.replaceState(null, "", location.pathname + "#/groups");
  } catch { /* ignore */ }
}

async function handleAutoJoin(gid) {
  autoMsg.value = "";
  try {
    await api(`/groups/${gid}/join`, { method: "POST" });
    clearJoinQuery();
    location.hash = `#/group?id=${gid}`;
    return;
  } catch (err) {
    autoMsg.value = err.message || "加入失败";
    clearJoinQuery();
  }
}

async function loadMyGroups() {
  loading.value = true;
  error.value = "";
  try {
    const d = await api("/groups");
    if (!mounted) return;
    groups.value = d.groups || [];
    loading.value = false;
  } catch (err) {
    if (!mounted) return;
    error.value = err.message || "小组列表加载失败";
    loading.value = false;
  }
}

async function createGroup() {
  const name = newName.value.trim();
  if (!name || name.length > 24) {
    createError.value = "小组名需 1–24 个字符";
    return;
  }
  createLoading.value = true;
  createError.value = "";
  try {
    await api("/groups", { method: "POST", body: JSON.stringify({ name }) });
    newName.value = "";
    showCreate.value = false;
    await loadMyGroups();
  } catch (err) {
    createError.value = err.message || "创建失败";
  }
  createLoading.value = false;
}

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer);
  const q = searchQ.value.trim();
  searchError.value = "";
  if (!q) { searchResults.value = []; return; }
  searchTimer = setTimeout(() => doSearch(q), 350);
}

async function doSearch(q) {
  if (!q || q.length > 32) {
    searchError.value = q.length > 32 ? "搜索词过长" : "请输入要搜索的小组名";
    return;
  }
  const seq = ++searchSeq;
  searching.value = true;
  searchError.value = "";
  try {
    const d = await api(`/groups/search?q=${encodeURIComponent(q)}`);
    if (!mounted || seq !== searchSeq) return;
    searchResults.value = d.groups || [];
  } catch (err) {
    if (!mounted || seq !== searchSeq) return;
    searchError.value = err.message || "搜索失败";
    searchResults.value = [];
  }
  searching.value = false;
}

function triggerSearch() {
  const q = searchQ.value.trim();
  if (!q) { searchResults.value = []; return; }
  if (searchTimer) clearTimeout(searchTimer);
  doSearch(q);
}

async function joinGroup(gid) {
  joinLoading.value = gid;
  try {
    await api(`/groups/${gid}/join`, { method: "POST" });
    // 更新本地搜索结果状态
    searchResults.value = searchResults.value.map((r) =>
      r.id === gid ? { ...r, joined: true } : r);
    location.hash = `#/group?id=${gid}`;
  } catch (err) {
    alert(err.message || "加入失败");
  }
  joinLoading.value = "";
}

function roleLabel(role) {
  return role === "owner" ? "组长" : "成员";
}
</script>

<template>
  <div v-if="!Account.loading && !Account.authenticated" class="empty login-gate" role="alert">
    <span class="emoji">🔒</span>
    <h3>小组需要登录</h3>
    <p>登录后可以创建或加入学习小组，和好友一起挑战。</p>
    <a class="btn primary" href="#/account">去登录 / 注册</a>
  </div>

  <div v-else-if="error" class="empty" role="alert">
    <span class="emoji">⚠️</span>
    <h3>加载失败</h3>
    <p>{{ error }}</p>
    <button class="btn primary" @click="loadMyGroups">重试</button>
  </div>
  <div v-else-if="loading" class="empty loading"><span class="spin" aria-hidden="true"></span><span class="load-text">加载中…</span></div>

  <div v-else class="groups-page">
    <!-- Hero -->
    <section class="gh-hero">
      <div class="gh-hero-left">
        <div class="gh-hero-emoji">👥</div>
        <div class="gh-hero-body">
          <div class="gh-hero-eyebrow"><span class="gh-pulse"></span> STUDY GROUPS</div>
          <h1>和小伙伴一起，进步更快！</h1>
          <p>组队听打 · 组队 PK · 排行榜，让学习不再孤单</p>
        </div>
      </div>
      <div class="gh-hero-stats">
        <div class="gh-hero-stat">
          <div class="val">{{ groups.length }}</div>
          <div class="lbl">我的小组</div>
        </div>
        <div class="gh-hero-stat">
          <div class="val">{{ groups.reduce((s, g) => s + (g.member_count || 0), 0) }}</div>
          <div class="lbl">团队成员</div>
        </div>
      </div>
    </section>

    <div v-if="autoMsg" class="gh-msg error" role="alert">{{ autoMsg }}</div>

    <!-- Action cards -->
    <div class="gh-actions">
      <button class="gh-action gh-action-create" type="button" @click="showCreate = !showCreate">
        <span class="gh-action-emoji">🛠️</span>
        <span class="gh-action-body">
          <h3>创建新小组</h3>
          <p>召集好友组建专属学习小组</p>
        </span>
        <span class="gh-action-cta">{{ showCreate ? "收起 ←" : "开始创建 →" }}</span>
      </button>
      <a class="gh-action gh-action-find" href="#gh-search-anchor">
        <span class="gh-action-emoji">🔍</span>
        <span class="gh-action-body">
          <h3>加入小组</h3>
          <p>搜索公开小组，或输入邀请码</p>
        </span>
        <span class="gh-action-cta">浏览加入 →</span>
      </a>
    </div>

    <!-- Create form -->
    <div v-if="showCreate" class="gh-create">
      <div class="gh-create-head">
        <span class="gh-create-emoji">🛠️</span>
        <b>创建新小组</b>
      </div>
      <div class="gh-create-row">
        <input v-model="newName" type="text" maxlength="24" placeholder="小组名（1–24 字）" class="gh-create-input">
        <button class="btn primary sm" :disabled="createLoading" @click="createGroup">{{ createLoading ? "创建中…" : "创建" }}</button>
        <button class="btn ghost sm" @click="showCreate = false">取消</button>
      </div>
      <p v-if="createError" class="gh-field-error">{{ createError }}</p>
    </div>

    <!-- My Groups -->
    <div class="gh-section-head">
      <span class="gh-section-emoji">⭐</span>
      <h2>我的小组</h2>
      <span class="gh-section-count">{{ groups.length }} 个</span>
    </div>

    <div v-if="!groups.length" class="empty">
      <span class="emoji">👥</span>
      <h3>还没有加入任何小组</h3>
      <p>创建一个小组，或在下方搜索加入。</p>
      <button v-if="!showCreate" class="btn primary sm" @click="showCreate = true">创建小组</button>
    </div>

    <div v-else class="card-grid group-grid stagger-in">
      <a v-for="(g, idx) in groups" :key="g.id" class="card group-card" :class="`gc-c${idx % 4}`" :href="`#/group?id=${g.id}`">
        <div class="gc-top">
          <div class="gc-avatar" :class="`gc-av-${idx % 4}`">
            <span>{{ ['📖','🎯','⚔️','🌍'][idx % 4] }}</span>
          </div>
          <div class="gc-info">
            <div class="gc-row1">
              <h3>{{ g.name }}</h3>
              <span class="badge-soft gc-role" :class="g.role === 'owner' ? 'purple' : 'blue'">{{ roleLabel(g.role) }}</span>
            </div>
            <small>创建者 {{ g.creator_name }} · 加入于 {{ String(g.joined_at).slice(0,10) }}</small>
          </div>
        </div>
        <div class="gc-stats">
          <div class="gc-stat">
            <div class="val green">{{ g.member_count }}</div>
            <div class="lbl">成员</div>
          </div>
          <div class="gc-stat-divider"></div>
          <div class="gc-stat">
            <div class="val blue">{{ g.max_members }}</div>
            <div class="lbl">上限</div>
          </div>
          <div class="gc-stat-divider"></div>
          <div class="gc-stat">
            <div class="val purple">{{ Math.round((g.member_count / Math.max(g.max_members, 1)) * 100) }}%</div>
            <div class="lbl">容量</div>
          </div>
        </div>
        <div class="gc-members">
          <div class="gc-member-stack">
            <div class="gc-member" :class="`gc-av-${i % 4}`" v-for="i in Math.min(5, g.member_count)" :key="i">
              <span>{{ ['🧑','👩','🧔','👧','👦'][i % 5] }}</span>
            </div>
            <div v-if="g.member_count > 5" class="gc-member more">+{{ g.member_count - 5 }}</div>
          </div>
          <span class="gc-cnt"><b>{{ g.member_count }}</b> / {{ g.max_members }} 人</span>
        </div>
        <div class="gc-activity">
          <div class="act-head">
            <span>小组容量</span>
            <span class="pct" :class="['blue','green','orange','purple'][idx % 4]">{{ Math.round((g.member_count / Math.max(g.max_members, 1)) * 100) }}%</span>
          </div>
          <div class="act-bar">
            <div class="act-fill" :class="`act-fill-${idx % 4}`" :style="`width:${Math.round((g.member_count / Math.max(g.max_members, 1)) * 100)}%`"></div>
          </div>
        </div>
        <div class="gc-foot">
          <span class="gc-btn" :class="`gc-btn-${idx % 4}`">进入小组 →</span>
        </div>
      </a>
    </div>

    <!-- Find Groups -->
    <div id="gh-search-anchor" class="gh-section-head">
      <span class="gh-section-emoji">🔍</span>
      <h2>找小组</h2>
    </div>
    <div class="gh-search">
      <input v-model="searchQ" type="text" placeholder="搜索小组名" class="gh-search-input" maxlength="32" @input="onSearchInput" @keydown.enter="triggerSearch">
      <button class="btn primary sm" :disabled="searching" @click="triggerSearch">{{ searching ? "搜索中…" : "搜索" }}</button>
    </div>
    <p v-if="searchError" class="gh-field-error">{{ searchError }}</p>
    <div v-if="searchResults.length" class="gh-search-results stagger-in">
      <div v-for="(r, idx) in searchResults" :key="r.id" class="gh-search-item">
        <div class="gc-avatar sm" :class="`gc-av-${idx % 4}`">
          <span>{{ ['📖','🎯','⚔️','🌍'][idx % 4] }}</span>
        </div>
        <div class="gh-sr-info">
          <span class="gh-sr-name">{{ r.name }}</span>
          <span class="gh-sr-meta">{{ r.members }} / {{ r.max_members }}</span>
        </div>
        <template v-if="r.joined">
          <a class="btn ghost sm" :href="`#/group?id=${r.id}`">进入</a>
        </template>
        <template v-else-if="r.full">
          <button class="btn ghost sm" disabled>已满</button>
        </template>
        <template v-else>
          <button class="btn primary sm" :disabled="joinLoading === r.id" @click="joinGroup(r.id)">{{ joinLoading === r.id ? "加入中…" : "加入" }}</button>
        </template>
      </div>
    </div>
    <div v-else-if="searchQ.trim() && !searching && !searchError" class="empty gh-search-empty">
      <span class="emoji">🔍</span>
      <h3>没有找到相关小组</h3>
      <p>换个关键词试试</p>
    </div>
  </div>
</template>
