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
    <span class="emoji">🔍</span>
    <h3>未指定小组</h3>
    <p>请从小组列表进入。</p>
    <a class="btn primary" href="#/groups">返回小组列表</a>
  </div>

  <div v-else-if="!Account.loading && !Account.authenticated" class="empty login-gate" role="alert">
    <span class="emoji">🔒</span>
    <h3>小组详情需要登录</h3>
    <p>登录后可查看小组信息、成员与挑战。</p>
    <a class="btn primary" href="#/account">去登录 / 注册</a>
  </div>

  <div v-else-if="error" class="empty" role="alert">
    <span class="emoji">⚠️</span>
    <h3>加载失败</h3>
    <p>{{ error }}</p>
    <button class="btn primary" @click="load">重试</button>
  </div>
  <div v-else-if="loading || !data" class="empty loading"><span class="spin" aria-hidden="true"></span><span class="load-text">加载中…</span></div>

  <div v-else class="group-detail">
    <!-- Hero -->
    <section class="gd-hero">
      <div class="gd-hero-avatar">⚔️</div>
      <div class="gd-hero-body">
        <div class="gd-hero-eyebrow">GROUP DETAIL</div>
        <h1>{{ data.name }}</h1>
        <p>创建者 {{ data.creator_name }} · 创建于 {{ String(data.created_at).slice(0,10) }}</p>
        <div class="gd-hero-tags">
          <span class="gd-hero-tag">👥 {{ data.member_count }} / {{ data.max_members }} 人</span>
          <span class="gd-hero-tag" v-if="data.role === 'owner'">👑 我是组长</span>
          <span class="gd-hero-tag" v-else-if="data.is_member">🤝 我是成员</span>
        </div>
      </div>
      <div class="gd-hero-stats">
        <div class="gd-hero-stat">
          <div class="ic">👥</div>
          <div class="val">{{ data.member_count }}</div>
          <div class="lbl">成员</div>
        </div>
        <div class="gd-hero-stat">
          <div class="ic">🎯</div>
          <div class="val">{{ data.challenges.length }}</div>
          <div class="lbl">挑战</div>
        </div>
      </div>
    </section>

    <!-- Actions -->
    <div class="gd-actions">
      <template v-if="!data.is_member">
        <button class="btn primary" :disabled="actionLoading === 'join'" @click="join">{{ actionLoading === 'join' ? '加入中…' : '加入小组' }}</button>
      </template>
      <template v-else>
        <button class="btn ghost sm" @click="copyInvite">{{ inviteCopied ? '已复制 ✓' : '复制邀请链接' }}</button>
        <button class="btn primary sm" @click="challengeOpen = !challengeOpen">{{ challengeOpen ? '收起' : '发起挑战' }}</button>
        <button v-if="data.role !== 'owner'" class="btn ghost sm" :disabled="actionLoading === 'leave'" @click="leave">退出小组</button>
        <button v-if="data.role === 'owner'" class="btn danger sm" :disabled="actionLoading === 'dissolve'" @click="dissolve">解散小组</button>
      </template>
      <a class="btn ghost sm" href="#/groups">返回列表</a>
    </div>

    <!-- Challenge Form -->
    <div v-if="challengeOpen" class="gd-challenge">
      <div class="gd-challenge-head">
        <span class="emoji">🎯</span>
        <b>发起挑战</b>
      </div>
      <div class="gd-cf-kinds">
        <label class="gd-cf-kind"><input type="radio" value="daily" v-model="challengeKind"> 每日挑战比分</label>
        <label class="gd-cf-kind"><input type="radio" value="words_target" v-model="challengeKind"> 累计答对词数</label>
      </div>
      <div class="gd-cf-fields">
        <label>天数 <input type="number" v-model.number="challengeDays" :min="1" :max="30" class="gd-cf-input"></label>
        <label v-if="challengeKind === 'words_target'">目标词数 <input type="number" v-model.number="challengeTarget" :min="1" :max="100000" class="gd-cf-input"></label>
      </div>
      <p v-if="challengeError" class="gd-field-error">{{ challengeError }}</p>
      <div style="margin-top:10px;display:flex;gap:8px;">
        <button class="btn primary sm" :disabled="challengeLoading" @click="submitChallenge">{{ challengeLoading ? '提交中…' : '提交' }}</button>
        <button class="btn ghost sm" @click="challengeOpen = false">取消</button>
      </div>
    </div>

    <!-- Members -->
    <div class="gd-section-head">
      <span class="emoji">👥</span>
      <h2>成员</h2>
      <span class="count">{{ data.members.length }} 人</span>
    </div>
    <div v-if="!data.members.length" class="empty gd-empty-inline">
      <span class="emoji">👥</span>
      <p>还没有成员</p>
    </div>
    <div v-else class="gd-member-list stagger-in">
      <div v-for="(m, mIdx) in data.members" :key="m.user_id" class="gd-member" :class="{ me: m.me }">
        <div class="gd-mi-avatar" :class="[`gc-av-${mIdx % 4}`, m.today_done ? 'online' : '']">
          <span>{{ ['🧑','👩','🧔','👧','👦','👨','👩‍🦰','🧑‍🦱'][mIdx % 8] }}</span>
        </div>
        <div class="gd-mi-info">
          <div class="gd-mi-name">
            <span>{{ m.name }}</span>
            <span v-if="m.me" class="gd-me-badge">我</span>
            <span v-if="m.role === 'owner'" class="gd-role-badge">组长</span>
          </div>
          <div class="gd-mi-detail">
            <span>Lv.{{ m.level }} {{ m.level_title }}</span>
            <span class="gd-dot">·</span>
            <span class="gd-mi-streak">🔥 连续 {{ m.streak }} 天</span>
            <span class="gd-dot">·</span>
            <span>{{ m.xp }} XP</span>
            <span v-if="m.today_done">· 今日已练 ✓</span>
          </div>
          <div class="gd-mi-joined">加入于 {{ String(m.joined_at).slice(0,10) }}</div>
        </div>
        <div class="gd-mi-right">
          <span class="gd-mi-lv">🏆 Lv.{{ m.level }}</span>
          <span class="gd-mi-xp">{{ m.xp }}</span>
        </div>
      </div>
    </div>

    <!-- Challenges -->
    <div class="gd-section-head">
      <span class="emoji">🎯</span>
      <h2>挑战</h2>
      <span class="count">{{ data.challenges.length }} 个</span>
    </div>
    <div v-if="!data.challenges.length" class="empty gd-empty-inline">
      <span class="emoji">🎯</span>
      <p>还没有挑战，发起一个吧</p>
    </div>
    <div v-else class="gd-challenge-list">
      <div v-for="(c, cIdx) in data.challenges" :key="c.id" class="gd-challenge-card" :class="{ active: c.active }">
        <div class="gd-ch-head">
          <b><span class="gd-ch-icon">{{ c.active ? '🏆' : '📋' }}</span>{{ challengeTitle(c) }}</b>
          <span class="chip" :class="c.active ? 'active-chip' : 'ended-chip'">{{ c.active ? '进行中' : '已结束' }}</span>
        </div>
        <div class="gd-ch-window">{{ windowLabel(c) }} · 由 {{ c.created_by }} 发起</div>
        <div v-if="!c.scores.length" class="gd-ch-empty">暂无比分</div>
        <div v-else class="gd-scores">
          <div v-for="(s, idx) in c.scores" :key="s.user_id" class="gd-score" :class="{ 'top-1': idx === 0, 'top-2': idx === 1, 'top-3': idx === 2 }">
            <span class="gd-score-rank" :class="{ top: idx < 3 }">{{ idx === 0 ? '👑' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : idx + 1 }}</span>
            <span class="gd-score-name">{{ s.name }}</span>
            <span class="gd-score-value">{{ s.value }}</span>
            <span v-if="c.played_counts && c.played_counts[s.user_id] != null" class="gd-score-played">({{ c.played_counts[s.user_id] }} 局)</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
