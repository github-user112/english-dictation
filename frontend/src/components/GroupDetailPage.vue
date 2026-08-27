<script setup>
import { ref, onMounted } from "vue";
import { api } from "../lib/core";
import { Account, refreshAccount } from "../lib/account";

const props = defineProps({ params: { type: Object, default: null } });

const gid = ref("");
const loading = ref(true);
const error = ref("");
const data = ref(null);
const challengeOpen = ref(false);
const challengeKind = ref("daily");
const challengeDays = ref(7);
const challengeTarget = ref(50);
const challengeLoading = ref(false);
const challengeError = ref("");
const actionLoading = ref("");
const copied = ref(false);
const inviteCopied = ref(false);

onMounted(async () => {
  gid.value = props.params?.get("id") || "";
  if (!gid.value) {
    error.value = "未指定小组";
    loading.value = false;
    return;
  }
  try {
    await refreshAccount();
  } catch { /* 网络错也按未登录处理 */ }
  if (!Account.authenticated) { loading.value = false; return; }
  await load();
});

async function load() {
  if (!gid.value) return;
  loading.value = true;
  error.value = "";
  try {
    const d = await api(`/groups/${gid.value}`);
    data.value = d;
    loading.value = false;
  } catch (err) {
    error.value = err.message || "小组加载失败";
    loading.value = false;
  }
}

async function join() {
  actionLoading.value = "join";
  try {
    await api(`/groups/${gid.value}/join`, { method: "POST" });
    await load();
  } catch (err) {
    alert(err.message || "加入失败");
  }
  actionLoading.value = "";
}

async function leave() {
  if (!confirm("确定要退出该小组吗？")) return;
  actionLoading.value = "leave";
  try {
    await api(`/groups/${gid.value}/leave`, { method: "POST" });
    location.hash = "#/groups";
  } catch (err) {
    alert(err.message || "退出失败");
    actionLoading.value = "";
  }
}

async function dissolve() {
  if (!confirm("确定要解散该小组吗？此操作不可恢复。")) return;
  actionLoading.value = "dissolve";
  try {
    await api(`/groups/${gid.value}/dissolve`, { method: "POST" });
    location.hash = "#/groups";
  } catch (err) {
    alert(err.message || "解散失败");
    actionLoading.value = "";
  }
}

async function copyInvite() {
  const link = `${location.origin}/#/groups?join=${gid.value}`;
  try {
    await navigator.clipboard.writeText(link);
    inviteCopied.value = true;
    setTimeout(() => { inviteCopied.value = false; }, 2000);
  } catch {
    prompt("复制邀请链接", link);
  }
}

async function submitChallenge() {
  challengeError.value = "";
  const kind = challengeKind.value;
  if (!["daily", "words_target"].includes(kind)) {
    challengeError.value = "未知挑战类型";
    return;
  }
  let days = Number(challengeDays.value) || 7;
  days = Math.max(1, Math.min(30, Math.round(days)));
  let body = { kind, days };
  if (kind === "words_target") {
    let tw = Number(challengeTarget.value) || 50;
    tw = Math.max(1, Math.min(100000, Math.round(tw)));
    body.target_words = tw;
  }
  challengeLoading.value = true;
  try {
    await api(`/groups/${gid.value}/challenge`, { method: "POST", body: JSON.stringify(body) });
    challengeOpen.value = false;
    await load();
  } catch (err) {
    challengeError.value = err.message || "发起挑战失败";
  }
  challengeLoading.value = false;
}

function challengeTitle(c) {
  if (c.kind === "daily") return "每日挑战同题比分";
  const tw = c.target_words ?? c.config?.target_words ?? 50;
  // 计算窗口天数
  const s = String(c.created_at).slice(0, 10);
  const e = String(c.expires_at).slice(0, 10);
  let days = 7;
  try {
    const ds = new Date(s);
    const de = new Date(e);
    const diff = Math.round((de - ds) / 86400000);
    if (diff >= 1 && diff <= 30) days = diff;
  } catch { /* ignore */ }
  return `${days} 天累计答对 ${tw} 词`;
}

function windowLabel(c) {
  return `${String(c.created_at).slice(0, 10)} ~ ${String(c.expires_at).slice(0, 10)}`;
}
</script>

<template>
  <div v-if="!gid" class="empty" role="alert">
    <p>未指定小组</p>
    <a class="btn primary" href="#/groups">返回小组列表</a>
  </div>

  <div v-else-if="!Account.loading && !Account.authenticated" class="empty login-gate" role="alert">
    <p class="gate-title">小组详情需要登录</p>
    <p class="gate-sub">登录后可查看小组信息、成员与挑战。</p>
    <a class="btn primary" href="#/account">去登录 / 注册</a>
  </div>

  <div v-else-if="error" class="empty" role="alert">
    <p>{{ error }}</p>
    <button class="btn primary" @click="load">重试</button>
  </div>
  <div v-else-if="loading || !data" class="empty">加载中…</div>

  <div v-else class="group-detail">
    <div class="page-heading compact">
      <span class="eyebrow">GROUP DETAIL</span>
      <h1>{{ data.name }}</h1>
      <p>创建者 {{ data.creator_name }} · 成员 {{ data.member_count }} / {{ data.max_members }} · 创建于 {{ String(data.created_at).slice(0,10) }}</p>
    </div>

    <div class="detail-actions">
      <template v-if="!data.is_member">
        <button class="btn primary" :disabled="actionLoading === 'join'" @click="join">{{ actionLoading === 'join' ? '加入中…' : '加入小组' }}</button>
      </template>
      <template v-else>
        <button class="btn ghost sm" @click="copyInvite">{{ inviteCopied ? '已复制 ✓' : '复制邀请链接' }}</button>
        <button class="btn primary sm" @click="challengeOpen = !challengeOpen">{{ challengeOpen ? '收起' : '发起挑战' }}</button>
        <button v-if="data.role !== 'owner'" class="btn ghost sm" :disabled="actionLoading === 'leave'" @click="leave">退出小组</button>
        <button v-if="data.role === 'owner'" class="btn ghost sm" :disabled="actionLoading === 'dissolve'" style="color:var(--red);border-color:color-mix(in srgb, var(--red), transparent 60%);" @click="dissolve">解散小组</button>
      </template>
      <a class="btn ghost sm" href="#/groups">返回列表</a>
    </div>

    <div v-if="challengeOpen" class="challenge-form">
      <div class="cf-title">发起挑战</div>
      <div class="cf-kinds">
        <label class="cf-kind"><input type="radio" value="daily" v-model="challengeKind"> 每日挑战比分</label>
        <label class="cf-kind"><input type="radio" value="words_target" v-model="challengeKind"> 累计答对词数</label>
      </div>
      <div class="cf-fields">
        <label>天数 <input type="number" v-model.number="challengeDays" :min="1" :max="30" class="cf-input"></label>
        <label v-if="challengeKind === 'words_target'">目标词数 <input type="number" v-model.number="challengeTarget" :min="1" :max="100000" class="cf-input"></label>
      </div>
      <p v-if="challengeError" class="field-error">{{ challengeError }}</p>
      <div style="margin-top:10px;display:flex;gap:8px;">
        <button class="btn primary sm" :disabled="challengeLoading" @click="submitChallenge">{{ challengeLoading ? '提交中…' : '提交' }}</button>
        <button class="btn ghost sm" @click="challengeOpen = false">取消</button>
      </div>
    </div>

    <div class="section-title"><span>成员</span><small>{{ data.members.length }} 人</small></div>
    <div class="member-grid">
      <div v-for="m in data.members" :key="m.user_id" class="member-card" :class="{ me: m.me }">
        <div class="mc-head">
          <span class="mc-name">{{ m.name }}</span>
          <span v-if="m.me" class="chip me-chip">我</span>
          <span v-if="m.role === 'owner'" class="chip owner-chip">组长</span>
        </div>
        <div class="mc-meta">Lv.{{ m.level }} {{ m.level_title }} · 连续 {{ m.streak }} 天 · {{ m.xp }} XP<span v-if="m.today_done"> · 今日已练 ✓</span></div>
        <div class="mc-joined">加入于 {{ String(m.joined_at).slice(0,10) }}</div>
      </div>
    </div>

    <div class="section-title"><span>挑战</span><small>{{ data.challenges.length }} 个</small></div>
    <div v-if="!data.challenges.length" class="empty" style="padding:28px;">还没有挑战，发起一个吧</div>
    <div v-else class="challenge-list">
      <div v-for="c in data.challenges" :key="c.id" class="challenge-card">
        <div class="ch-head">
          <b>{{ challengeTitle(c) }}</b>
          <span class="chip" :class="c.active ? 'active-chip' : 'ended-chip'">{{ c.active ? '进行中' : '已结束' }}</span>
        </div>
        <div class="ch-window">{{ windowLabel(c) }} · 由 {{ c.created_by }} 发起</div>
        <div v-if="!c.scores.length" class="ch-empty">暂无比分</div>
        <ol v-else class="ch-scores">
          <li v-for="(s, idx) in c.scores" :key="s.user_id" class="ch-row">
            <span class="ch-rank">{{ idx === 0 ? '👑' : idx + 1 }}</span>
            <span class="ch-name">{{ s.name }}</span>
            <span class="ch-value">{{ s.value }}</span>
            <span v-if="c.played_counts && c.played_counts[s.user_id] != null" class="ch-played">({{ c.played_counts[s.user_id] }} 局)</span>
          </li>
        </ol>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-gate { text-align: center; gap: 10px; }
.gate-title { font-size: 17px; font-weight: 750; margin: 0; }
.gate-sub { color: var(--dim); margin: 0 0 6px; max-width: 420px; }
.detail-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }
.challenge-form { margin-bottom: 18px; padding: 16px; background: var(--panel); border: 1px solid var(--border); border-radius: 14px; }
.cf-title { font-weight: 750; margin-bottom: 10px; }
.cf-kinds { display: flex; gap: 16px; margin-bottom: 12px; flex-wrap: wrap; }
.cf-kind { display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }
.cf-fields { display: flex; gap: 14px; flex-wrap: wrap; }
.cf-fields label { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 650; }
.cf-input { width: 110px; padding: 7px 10px; color: var(--text); background: var(--panel2); border: 1px solid var(--border); border-radius: 10px; outline: none; }
.field-error { color: var(--red); font-size: 12px; margin-top: 8px; }
.member-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
.member-card { padding: 14px; background: linear-gradient(160deg, var(--panel), color-mix(in srgb, var(--panel), var(--bg) 12%)); border: 1px solid var(--border); border-radius: 14px; }
.member-card.me { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent) inset; }
.mc-head { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.mc-name { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip { display: inline-flex; align-items: center; gap: 4px; padding: 2px 7px; font-size: 10.5px; border-radius: 7px; font-weight: 700; }
.me-chip { color: var(--accent-text); background: var(--accent-grad); }
.owner-chip { color: var(--type-text); background: var(--type-bg); }
.active-chip { color: var(--green); background: var(--audio-bg); }
.ended-chip { color: var(--dim2); background: var(--panel2); border: 1px solid var(--border); }
.mc-meta { color: var(--dim); font-size: 12px; }
.mc-joined { color: var(--dim2); font-size: 11px; margin-top: 4px; }
.challenge-list { display: flex; flex-direction: column; gap: 12px; }
.challenge-card { padding: 16px; background: var(--panel); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow-soft); }
.ch-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 4px; }
.ch-head b { font-size: 15px; }
.ch-window { color: var(--dim2); font-size: 11.5px; margin-bottom: 10px; }
.ch-empty { color: var(--dim2); font-size: 12px; padding: 8px 0; }
.ch-scores { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.ch-row { display: flex; align-items: center; gap: 10px; padding: 7px 10px; background: color-mix(in srgb, var(--panel2) 70%, transparent); border: 1px solid var(--border); border-radius: 10px; }
.ch-rank { width: 28px; text-align: center; font-weight: 800; color: var(--dim); }
.ch-name { flex: 1; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ch-value { font-weight: 800; font-variant-numeric: tabular-nums; }
.ch-played { color: var(--dim2); font-size: 11px; }
</style>
