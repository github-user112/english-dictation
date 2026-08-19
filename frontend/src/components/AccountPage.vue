<script setup>
import { computed, reactive, ref, watch } from "vue";
import { Account, applyAccount, refreshAccount } from "../lib/account";
import { api } from "../lib/core";

const mode = ref(Account.authenticated ? "account" : "login");
const form = reactive({ username: "", password: "", currentPassword: "", newPassword: "" });
const busy = ref(false);
const error = ref("");
const notice = ref("");
const isSignedIn = computed(() => Account.authenticated && mode.value === "account");

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
      body: JSON.stringify({ username: form.username, password: form.password }),
    });
    applyAccount(data);
    notice.value = mode.value === "register" ? "账户已创建，当前学习进度已受到保护。" : "登录成功。";
    mode.value = "account";
    form.password = "";
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

watch(() => Account.authenticated, (signedIn) => {
  if (signedIn) mode.value = "account";
});

refreshAccount().catch(() => {});
</script>

<template>
  <div class="account-page">
    <div class="page-heading">
      <span class="eyebrow">ACCOUNT</span>
      <h1>{{ isSignedIn ? '账户与安全' : (mode === 'register' ? '保护你的进度' : '欢迎回来') }}</h1>
      <p>{{ isSignedIn ? '管理登录方式和账户安全。' : '注册后可在不同设备继续学习，并保护已有进度。' }}</p>
    </div>

    <section v-if="!isSignedIn" class="account-card">
      <div class="account-tabs" role="tablist" aria-label="账户操作">
        <button class="btn ghost" :class="{ primary: mode === 'login' }" @click="switchMode('login')">登录</button>
        <button class="btn ghost" :class="{ primary: mode === 'register' }" @click="switchMode('register')">注册</button>
      </div>
      <p v-if="mode === 'register'" class="account-hint">会直接认领当前游客学习进度；无需导入或重新开始。</p>
      <form class="account-form" @submit.prevent="submitCredentials">
        <label>用户名或邮箱
          <input v-model.trim="form.username" autocomplete="username" :minlength="mode === 'register' ? 6 : 3" maxlength="254" required placeholder="用户名（6–32 位）或常用邮箱">
        </label>
        <label>密码
          <input v-model="form.password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" :minlength="mode === 'register' ? 6 : undefined" maxlength="128" required :placeholder="mode === 'register' ? '至少 6 位，建议使用不易猜测的组合' : '输入密码'">
        </label>
        <p v-if="error" class="account-message error" role="alert">{{ error }}</p>
        <p v-if="notice" class="account-message success">{{ notice }}</p>
        <button class="btn primary big" type="submit" :disabled="busy">{{ busy ? '处理中…' : (mode === 'login' ? '登录' : '创建账户') }}</button>
      </form>
    </section>

    <section v-else class="account-card">
      <div class="account-identity"><span class="brand-mark">D</span><div><b>{{ Account.username }}</b><small>已登录账户</small></div></div>
      <div class="section-title"><span>修改密码</span><small>修改后会退出其他设备</small></div>
      <form class="account-form" @submit.prevent="changePassword">
        <label>当前密码
          <input v-model="form.currentPassword" type="password" autocomplete="current-password" required>
        </label>
        <label>新密码
          <input v-model="form.newPassword" type="password" autocomplete="new-password" minlength="6" maxlength="128" required placeholder="至少 6 位，建议使用不易猜测的组合">
        </label>
        <p v-if="error" class="account-message error" role="alert">{{ error }}</p>
        <p v-if="notice" class="account-message success">{{ notice }}</p>
        <button class="btn primary" type="submit" :disabled="busy">{{ busy ? '保存中…' : '更新密码' }}</button>
      </form>
    </section>
  </div>
</template>
