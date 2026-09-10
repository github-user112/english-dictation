<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Account, logout } from "../lib/account";
import { Profile, refreshProfile } from "../lib/profile";

const page = ref("catalog");
const TITLES = {
  catalog: "今日", lists: "素材库", word: "单词听打", sentence: "句子听写", memorize: "背单词",
  quiz: "听音选词", sprint: "限时冲刺", daily: "每日挑战", tree: "单词树",
  boss: "错词Boss战", match: "配对消消乐", arrange: "听音排句",
  wrong: "错词本", stats: "统计", report: "学习报告", settings: "设置", account: "账户", leaderboard: "排行榜", friends: "好友", groups: "小组", group: "小组详情", pk: "实时对战", wordtest: "词汇量测试", shadow: "听读",
};
const title = computed(() => TITLES[page.value] || "英语听打");
const accountInitial = computed(() => (Account.username || "D").slice(0, 1).toUpperCase());
const lvWidth = computed(() => `${Math.round((Profile.levelProgress || 0) * 100)}%`);

/* 次要入口收进「更多」：功能多了导航换行难看，只留每日动线在顶栏。
   组内顺序 = 学习工具 → 社交 → 系统；sep 表示与该组开头之间画分隔线 */
const MORE = [
  { p: "lists", t: "素材库", s: "素材" },
  { p: "wordtest", t: "词汇量测试", s: "词测" },
  { p: "report", t: "学习报告", s: "报告" },
  { p: "leaderboard", t: "排行榜", s: "排行", sep: true },
  { p: "friends", t: "好友", s: "好友" },
  { p: "groups", t: "小组", s: "小组" },
  { p: "settings", t: "设置", s: "设置", sep: true },
];
const moreOpen = ref(false);
const moreActive = computed(() => MORE.some((m) => m.p === page.value));

function closeMore() { moreOpen.value = false; }
function onDocClick(e) {
  if (!e.target.closest?.(".nav-more")) closeMore();
}
function onDocKey(e) {
  if (e.key === "Escape") closeMore();
}

function sync() {
  const h = location.hash.replace(/^#\/?/, "") || "catalog";
  page.value = h.split("?")[0];
  closeMore();
}
async function signOut() {
  try {
    await logout();
    location.hash = "#/catalog";
  } catch { /* 账户页仍可通过刷新重试 */ }
}
function onProfileChanged() { refreshProfile(true).catch(() => {}); }
onMounted(() => {
  window.addEventListener("hashchange", sync);
  window.addEventListener("profile-changed", onProfileChanged);
  document.addEventListener("click", onDocClick);
  document.addEventListener("keydown", onDocKey);
  sync();
  refreshProfile().catch(() => {});   // 失败静默：徽章位隐藏即可
});
onUnmounted(() => {
  window.removeEventListener("hashchange", sync);
  window.removeEventListener("profile-changed", onProfileChanged);
  document.removeEventListener("click", onDocClick);
  document.removeEventListener("keydown", onDocKey);
});
</script>

<template>
  <header id="topbar">
    <div class="top-left">
      <a href="#/catalog" class="brand" aria-label="返回今日动线">
        <span class="brand-mark" aria-hidden="true">🦉</span>
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
      <!-- 顶栏成长线：🔥连击 / ⚡经验（多邻国式常驻成长指标） -->
      <div v-if="Profile.ready" class="topbar-stats">
        <div class="stat-item streak" :title="`${Profile.streak} 天连续学习 · 今天${Profile.todayDone ? '已打卡' : '还没打卡'}`">
          <span class="icon" aria-hidden="true">🔥</span><span>{{ Profile.streak }}</span>
        </div>
        <div class="stat-item xp" :title="`经验 ${Profile.xp}`">
          <span class="icon" aria-hidden="true">⚡</span><span>{{ Profile.xp }}</span>
        </div>
      </div>
      <!-- 词力等级徽章：常驻成长线，点击看统计 -->
      <a v-if="Profile.ready" class="nav-link lv-chip" href="#/stats"
         :title="`经验 ${Profile.xp}${Profile.nextLevelXp != null ? ` · 距下一级还差 ${Profile.nextLevelXp - Profile.xp}` : ' · 已达最高称号'}`">
        <span class="lv-icon" aria-hidden="true">🏆</span>
        <b>Lv.{{ Profile.level }}</b><span>{{ Profile.title }}</span>
        <i class="lv-bar" aria-hidden="true"><i :style="{ width: lvWidth }"></i></i>
      </a>
      <a class="nav-link" :class="{active: page==='catalog'}" href="#/catalog">今日</a>
      <a class="nav-link" :class="{active: page==='wrong'}" href="#/wrong">错词</a>
      <a class="nav-link" :class="{active: page==='daily'}" href="#/daily">每日</a>
      <a class="nav-link" :class="{active: page==='tree'}" href="#/tree">小树</a>
      <a class="nav-link" :class="{active: page==='stats'}" href="#/stats">统计</a>
      <div class="nav-more">
        <button class="nav-link nav-more-btn" :class="{active: moreActive, open: moreOpen}"
                :aria-expanded="moreOpen" aria-haspopup="menu" @click.stop="moreOpen = !moreOpen">
          更多<span class="nav-caret" aria-hidden="true">▾</span>
        </button>
        <div v-if="moreOpen" class="nav-menu" role="menu">
          <template v-for="m in MORE" :key="m.p">
            <div v-if="m.sep" class="nav-menu-sep" aria-hidden="true"></div>
            <a class="nav-menu-item" role="menuitem"
               :class="{active: page === m.p}" :href="`#/${m.p}`">{{ m.t }}</a>
          </template>
        </div>
      </div>
      <!-- 移动端导航条本可横滑，次要项直接内联（下拉会被 overflow 裁掉） -->
      <a v-for="m in MORE" :key="`i-${m.p}`" class="nav-link nav-more-inline"
         :class="{active: page === m.p}" :href="`#/${m.p}`">{{ m.s }}</a>
      <a v-if="!Account.loading && !Account.authenticated" class="nav-link account-link" :class="{active: page==='account'}" href="#/account">登录 / 注册</a>
      <div v-else-if="Account.authenticated" class="account-nav"><a class="nav-link account-link" :class="{active: page==='account'}" href="#/account">{{ Account.username }}</a><button class="btn sm ghost" @click="signOut">退出</button></div>
    </nav>
  </header>
</template>
