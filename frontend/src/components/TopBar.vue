<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Account, logout } from "../lib/account";

const page = ref("catalog");
const TITLES = {
  catalog: "素材库", word: "单词听打", sentence: "句子听写", memorize: "背单词",
  wrong: "错词本", stats: "统计", settings: "设置", account: "账户",
};
const title = computed(() => TITLES[page.value] || "英语听打");
const accountInitial = computed(() => (Account.username || "D").slice(0, 1).toUpperCase());

function sync() {
  const h = location.hash.replace(/^#\/?/, "") || "catalog";
  page.value = h.split("?")[0];
}
async function signOut() {
  try {
    await logout();
    location.hash = "#/catalog";
  } catch { /* 账户页仍可通过刷新重试 */ }
}
onMounted(() => { window.addEventListener("hashchange", sync); sync(); });
onUnmounted(() => window.removeEventListener("hashchange", sync));
</script>

<template>
  <header id="topbar">
    <div class="top-left">
      <a href="#/catalog" class="brand" aria-label="返回素材库">
        <span class="brand-mark">D</span>
        <span class="brand-copy"><b>Dictation</b><small>听见，然后写下</small></span>
      </a>
      <span id="title">/ {{ title }}</span>
    </div>
    <div class="mobile-session">
      <a v-if="!Account.loading && !Account.authenticated" class="mobile-login" href="#/account">登录</a>
      <template v-else-if="Account.authenticated">
        <a class="mobile-user" href="#/account" :aria-label="`账户：${Account.username}`">
          <span class="mobile-avatar" aria-hidden="true">{{ accountInitial }}</span>
          <span class="mobile-username">{{ Account.username }}</span>
        </a>
        <button class="mobile-logout" aria-label="退出登录" @click="signOut">退出</button>
      </template>
    </div>
    <nav id="nav">
      <a class="nav-link" :class="{active: page==='catalog'}" href="#/catalog">素材</a>
      <a class="nav-link" :class="{active: page==='wrong'}" href="#/wrong">错词</a>
      <a class="nav-link" :class="{active: page==='stats'}" href="#/stats">统计</a>
      <a class="nav-link" :class="{active: page==='settings'}" href="#/settings">设置</a>
      <a v-if="!Account.loading && !Account.authenticated" class="nav-link account-link" :class="{active: page==='account'}" href="#/account">登录 / 注册</a>
      <div v-else-if="Account.authenticated" class="account-nav"><a class="nav-link account-link" :class="{active: page==='account'}" href="#/account">{{ Account.username }}</a><button class="btn ghost sm" @click="signOut">退出</button></div>
    </nav>
  </header>
</template>
