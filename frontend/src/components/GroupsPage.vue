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
  searching.value = true;
  searchError.value = "";
  try {
    const d = await api(`/groups/search?q=${encodeURIComponent(q)}`);
    if (!mounted) return;
    searchResults.value = d.groups || [];
  } catch (err) {
    if (!mounted) return;
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
    <p class="gate-title">小组需要登录</p>
    <p class="gate-sub">登录后可以创建或加入学习小组，和好友一起挑战。</p>
    <a class="btn primary" href="#/account">去登录 / 注册</a>
  </div>

  <div v-else-if="error" class="empty" role="alert">
    <p>{{ error }}</p>
    <button class="btn primary" @click="loadMyGroups">重试</button>
  </div>
  <div v-else-if="loading" class="empty">加载中…</div>

  <div v-else class="groups-page">
    <div class="page-heading compact">
      <span class="eyebrow">STUDY GROUPS</span>
      <h1>学习小组</h1>
      <p>和伙伴一起坚持，互相督促。</p>
    </div>

    <div v-if="autoMsg" class="account-message error" style="margin-bottom:14px;">{{ autoMsg }}</div>

    <div class="section-title">
      <span>我的小组</span>
      <button class="btn ghost sm" @click="showCreate = !showCreate">{{ showCreate ? "收起" : "创建小组" }}</button>
    </div>

    <div v-if="showCreate" class="create-box">
      <div class="create-row">
        <input v-model="newName" type="text" maxlength="24" placeholder="小组名（1–24 字）" class="create-input">
        <button class="btn primary sm" :disabled="createLoading" @click="createGroup">{{ createLoading ? "创建中…" : "创建" }}</button>
        <button class="btn ghost sm" @click="showCreate = false">取消</button>
      </div>
      <p v-if="createError" class="field-error">{{ createError }}</p>
    </div>

    <div v-if="!groups.length" class="empty" style="padding:36px;">
      <p>还没有加入任何小组</p>
      <p style="color:var(--dim2);font-size:12px;margin:6px 0 10px;">创建一个小组，或在下方搜索加入。</p>
      <button v-if="!showCreate" class="btn primary sm" @click="showCreate = true">创建小组</button>
    </div>

    <div v-else class="card-grid group-grid">
      <a v-for="g in groups" :key="g.id" class="card group-card" :href="`#/group?id=${g.id}`">
        <div class="name">{{ g.name }}</div>
        <div class="meta">成员 {{ g.member_count }} / {{ g.max_members }} · <span class="role-tag">{{ roleLabel(g.role) }}</span> · 创建者 {{ g.creator_name }}</div>
        <div class="meta" style="margin-top:4px;">加入于 {{ String(g.joined_at).slice(0,10) }}</div>
      </a>
    </div>

    <div class="section-title"><span>找小组</span></div>
    <div class="search-row">
      <input v-model="searchQ" type="text" placeholder="搜索小组名" class="friends-search" maxlength="32" @input="onSearchInput" @keydown.enter="triggerSearch">
      <button class="btn primary sm" :disabled="searching" @click="triggerSearch">{{ searching ? "搜索中…" : "搜索" }}</button>
    </div>
    <p v-if="searchError" class="field-error">{{ searchError }}</p>
    <div v-if="searchResults.length" class="search-results">
      <div v-for="r in searchResults" :key="r.id" class="search-item">
        <span class="sr-name">{{ r.name }}</span>
        <span class="sr-meta">{{ r.members }} / {{ r.max_members }}</span>
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
    <div v-else-if="searchQ.trim() && !searching && !searchError" class="empty" style="padding:18px;margin-top:10px;">没有找到相关小组，换个关键词试试</div>
  </div>
</template>

<style scoped>
.login-gate { text-align: center; gap: 10px; }
.gate-title { font-size: 17px; font-weight: 750; margin: 0; }
.gate-sub { color: var(--dim); margin: 0 0 6px; max-width: 420px; }
.group-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.group-card { min-height: 132px; text-decoration: none; color: inherit; }
.group-card .role-tag { color: var(--accent-strong); font-weight: 700; }
.create-box { margin-bottom: 14px; padding: 14px; background: var(--panel); border: 1px solid var(--border); border-radius: 14px; }
.create-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.create-input { flex: 1; min-width: 160px; padding: 9px 12px; color: var(--text); background: var(--panel2); border: 1px solid var(--border); border-radius: 10px; font-size: 13px; outline: none; }
.create-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent), transparent 86%); }
.field-error { margin-top: 8px; color: var(--red); font-size: 12px; }
.search-row { display: flex; gap: 10px; align-items: center; }
.friends-search { flex: 1; padding: 10px 14px; color: var(--text); background: var(--panel2); border: 1px solid var(--border); border-radius: 12px; font-size: 14px; outline: none; }
.friends-search:focus { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent), transparent 86%); }
.search-results { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; padding: 12px; background: var(--panel); border: 1px solid var(--border); border-radius: 14px; }
.search-item { display: flex; align-items: center; gap: 10px; padding: 8px 6px; border-bottom: 1px solid var(--border); }
.search-item:last-child { border-bottom: 0; }
.sr-name { flex: 1; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sr-meta { color: var(--dim2); font-size: 12px; white-space: nowrap; }
.account-message.error { padding: 9px 11px; border-radius: 10px; font-size: 12px; color: var(--red); background: color-mix(in srgb, var(--red), transparent 91%); }
@media (max-width: 620px) { .group-grid { grid-template-columns: 1fr; } }
</style>
