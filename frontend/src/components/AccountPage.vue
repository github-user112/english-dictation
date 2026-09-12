<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { Account, applyAccount, logout, refreshAccount } from "../lib/account";
import { api } from "../lib/core";

const props = defineProps({ params: { type: Object, default: null } });

const mode = ref(Account.authenticated ? "account" : "login");
const form = reactive({ username: "", password: "", currentPassword: "", newPassword: "" });
const busy = ref(false);
const error = ref("");
const notice = ref("");
const isSignedIn = computed(() => Account.authenticated && mode.value === "account");

/* 邀请注册：URL 带 ?invite=<32hex> 时拉取邀请人信息，注册时带上 inviter */
const inviteId = ref("");
const inviteName = ref("");
const inviteBanner = ref(false);

function loadInvite() {
  const raw = props.params?.get("invite") || "";
  if (!/^[0-9a-fA-F]{32}$/.test(raw)) return;   // 非法的 invite 静默忽略
  inviteId.value = raw;
  api(`/friends/invite-info?user=${encodeURIComponent(raw)}`)
    .then((d) => { inviteName.value = d.username || ""; inviteBanner.value = true; })
    .catch(() => { /* 404 等：静默不显示横幅 */ });
}

function switchMode(next) {
  mode.value = next;
  error.value = "";
  notice.value = "";
}

async function submitCredentials() {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const data = await api(`/auth/${mode.value}`, {
      method: "POST",
      body: JSON.stringify({ username: form.username, password: form.password,
        ...(inviteId.value ? { inviter: inviteId.value } : {}) }),
    });
    applyAccount(data);
    notice.value = mode.value === "register" ? "账户已创建，当前学习进度已受到保护。" : "登录成功。";
    mode.value = "account";
    form.password = "";
    if (mode.value === "account" && inviteId.value) {
      history.replaceState(null, "", "#/account");   // 清掉 invite 参数，不触发重渲染
      inviteBanner.value = false;
    }
  } catch (err) {
    error.value = err.message;
  } finally {
    busy.value = false;
  }
}

async function changePassword() {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    applyAccount(await api("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: form.currentPassword, new_password: form.newPassword }),
    }));
    form.currentPassword = "";
    form.newPassword = "";
    notice.value = "密码已更新，其他设备上的登录已失效。";
  } catch (err) {
    error.value = err.message;
  } finally {
    busy.value = false;
  }
}

async function signOut() {
  try {
    await logout();
    location.hash = "#/catalog";
  } catch { /* 刷新后可重试 */ }
}

watch(() => Account.authenticated, (signedIn) => {
  if (signedIn) mode.value = "account";
});

refreshAccount()
  .then(() => { if (!Account.authenticated) loadInvite(); })
  .catch(() => loadInvite());
</script>

<template>
  <div class="account-page">

    <!-- ==================== 未登录：登录 / 注册 ==================== -->
    <div v-if="!isSignedIn" class="auth-wrap">

      <!-- 左：品牌 + 卖点（桌面两列，手机折成顶部横幅） -->
      <aside class="auth-left">
        <div class="auth-left-inner">
          <div class="auth-brand">
            <span class="owl">🦉</span>
            <span>英语听打</span>
          </div>
          <h2 class="auth-headline">免费学英文<br>每天进步一点</h2>
          <p class="auth-sub">加入数万名学习者，用游戏化的方式提升你的英语听力和拼写能力</p>
          <ul class="auth-features">
            <li><span class="f-ic">🎯</span><span>今日五环任务，科学规划学习路径</span></li>
            <li><span class="f-ic">🔥</span><span>连续打卡系统，培养每日学习习惯</span></li>
            <li><span class="f-ic">🏆</span><span>排行榜与 PK 对战，和好友一起进步</span></li>
            <li><span class="f-ic">📊</span><span>词汇量测试与详细学习报告</span></li>
          </ul>
        </div>
      </aside>

      <!-- 右：表单 -->
      <section class="auth-right">
        <div class="page-heading auth-head">
          <span class="eyebrow">ACCOUNT</span>
          <h1>
            <span class="h-emoji">{{ mode === 'register' ? '🛡️' : '👋' }}</span>{{ isSignedIn ? '账户与安全' : (mode === 'register' ? '保护你的进度' : '欢迎回来') }}
          </h1>
          <p>{{ isSignedIn ? '管理登录方式和账户安全。' : '注册后可在不同设备继续学习，并保护已有进度。' }}</p>
        </div>

        <div v-if="inviteBanner" class="account-message success invite-banner" role="status">
          <span class="m-ic">🎉</span>
          <span class="m-txt">好友 {{ inviteName || "好友" }} 邀请你加入，注册后自动成为好友</span>
        </div>

        <div class="account-tabs" role="tablist" aria-label="账户操作">
          <button class="btn ghost" :class="{ primary: mode === 'login' }" @click="switchMode('login')">
            <span class="t-ic">🔑</span>登录
          </button>
          <button class="btn ghost" :class="{ primary: mode === 'register' }" @click="switchMode('register')">
            <span class="t-ic">✨</span>注册
          </button>
        </div>

        <p v-if="mode === 'register'" class="account-hint">
          <span class="h-ic">🎁</span>会直接认领当前游客学习进度；无需导入或重新开始。
        </p>

        <form class="account-form" @submit.prevent="submitCredentials">
          <label class="form-group">
            <span class="form-label">用户名或邮箱</span>
            <span class="field">
              <span class="field-icon">📧</span>
              <input v-model.trim="form.username" class="form-input" autocomplete="username"
                     :minlength="mode === 'register' ? 6 : 3" maxlength="254" required
                     placeholder="用户名（6–32 位）或常用邮箱">
            </span>
          </label>
          <label class="form-group">
            <span class="form-label">密码</span>
            <span class="field">
              <span class="field-icon">🔒</span>
              <input v-model="form.password" type="password" class="form-input"
                     :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
                     :minlength="mode === 'register' ? 6 : undefined" maxlength="128" required
                     :placeholder="mode === 'register' ? '至少 6 位，建议使用不易猜测的组合' : '输入密码'">
            </span>
          </label>
          <p v-if="error" class="account-message error" role="alert">
            <span class="m-ic">⚠️</span><span class="m-txt">{{ error }}</span>
          </p>
          <p v-if="notice" class="account-message success">
            <span class="m-ic">✅</span><span class="m-txt">{{ notice }}</span>
          </p>
          <button class="btn primary big full" type="submit" :disabled="busy">
            {{ busy ? '处理中…' : (mode === 'login' ? '🔓 登录' : '🚀 创建账户') }}
          </button>
        </form>
      </section>
    </div>

    <!-- ==================== 已登录：左身份 + 右改密码 ==================== -->
    <div v-else class="acct-grid">
      <div class="page-heading acct-head">
        <span class="eyebrow">ACCOUNT</span>
        <h1>
          <span class="h-emoji">👤</span>{{ isSignedIn ? '账户与安全' : (mode === 'register' ? '保护你的进度' : '欢迎回来') }}
        </h1>
        <p>{{ isSignedIn ? '管理登录方式和账户安全。' : '注册后可在不同设备继续学习，并保护已有进度。' }}</p>
      </div>

      <!-- 左：身份卡 -->
      <aside class="acct-identity-card">
        <div class="acct-card-head">
          <span class="ac-emoji">🌟</span>
          <span>已登录账户</span>
        </div>
        <div class="account-identity">
          <span class="brand-mark">D</span>
          <div><b>{{ Account.username }}</b><small>已登录账户</small></div>
        </div>
        <ul class="acct-benefits">
          <li><span class="b-ic">☁️</span><span>学习进度已自动同步到云端</span></li>
          <li><span class="b-ic">📱</span><span>换设备登录即可继续，不用重新开始</span></li>
          <li><span class="b-ic">🔒</span><span>错题本、词力等级与成就全部保留</span></li>
        </ul>
        <button class="btn ghost full" @click="signOut">🚪 退出登录</button>
      </aside>

      <!-- 右：改密码 -->
      <section class="acct-form-card">
        <div class="section-title">
          <span><span class="st-emoji">🔑</span>修改密码</span>
          <small>修改后会退出其他设备</small>
        </div>
        <form class="account-form" @submit.prevent="changePassword">
          <label class="form-group">
            <span class="form-label">当前密码</span>
            <span class="field">
              <span class="field-icon">🔒</span>
              <input v-model="form.currentPassword" type="password" class="form-input"
                     autocomplete="current-password" required placeholder="输入当前密码">
            </span>
          </label>
          <label class="form-group">
            <span class="form-label">新密码</span>
            <span class="field">
              <span class="field-icon">✨</span>
              <input v-model="form.newPassword" type="password" class="form-input"
                     autocomplete="new-password" minlength="6" maxlength="128" required
                     placeholder="至少 6 位，建议使用不易猜测的组合">
            </span>
          </label>
          <p v-if="error" class="account-message error" role="alert">
            <span class="m-ic">⚠️</span><span class="m-txt">{{ error }}</span>
          </p>
          <p v-if="notice" class="account-message success">
            <span class="m-ic">✅</span><span class="m-txt">{{ notice }}</span>
          </p>
          <button class="btn primary big full" type="submit" :disabled="busy">
            {{ busy ? '保存中…' : '🔒 更新密码' }}
          </button>
        </form>
      </section>
    </div>
  </div>
</template>
