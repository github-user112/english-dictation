<script setup>
import { ref, onMounted } from "vue";
import TopBar from "./components/TopBar.vue";
import TodayPage from "./components/TodayPage.vue";
import ListsPage from "./components/ListsPage.vue";
import PracticePage from "./components/PracticePage.vue";
import MemorizePage from "./components/MemorizePage.vue";
import QuizPage from "./components/QuizPage.vue";
import SprintPage from "./components/SprintPage.vue";
import BossPage from "./components/BossPage.vue";
import DailyPage from "./components/DailyPage.vue";
import ArrangePage from "./components/ArrangePage.vue";
import MatchPage from "./components/MatchPage.vue";
import TreePage from "./components/TreePage.vue";
import WrongPage from "./components/WrongPage.vue";
import StatsPage from "./components/StatsPage.vue";
import ReportPage from "./components/ReportPage.vue";
import ImportPage from "./components/ImportPage.vue";
import SettingsPage from "./components/SettingsPage.vue";
import AccountPage from "./components/AccountPage.vue";
import LeaderboardPage from "./components/LeaderboardPage.vue";
import FriendsPage from "./components/FriendsPage.vue";
import GroupsPage from "./components/GroupsPage.vue";
import GroupDetailPage from "./components/GroupDetailPage.vue";
import PkPage from "./components/PkPage.vue";
import WordTestPage from "./components/WordTestPage.vue";
import ShadowPage from "./components/ShadowPage.vue";
import { refreshAccount } from "./lib/account";
import { stopAudio } from "./lib/core";

const ROUTES = {
  catalog: TodayPage, lists: ListsPage, word: PracticePage, sentence: PracticePage,
  memorize: MemorizePage, quiz: QuizPage, sprint: SprintPage,
  daily: DailyPage, tree: TreePage,
  boss: BossPage,
  match: MatchPage,
  arrange: ArrangePage,
  wrong: WrongPage, stats: StatsPage, report: ReportPage,
  import: ImportPage,
  settings: SettingsPage, account: AccountPage,
  leaderboard: LeaderboardPage, friends: FriendsPage,
  groups: GroupsPage, group: GroupDetailPage,
  pk: PkPage,
  wordtest: WordTestPage,
  shadow: ShadowPage,
};
/* 用当前 hash 直接初始化，避免「默认 TodayPage + 空 key → route() 改 key → 重挂载」
   导致首屏页面组件 mounted 两次、/api/today 打两次 */
function currentRoute() {
  const h = location.hash.replace(/^#\/?/, "") || "catalog";
  const [page, qs] = h.split("?");
  return { comp: ROUTES[page] || TodayPage, qs: qs || "", hash: location.hash };
}
const init = currentRoute();
const view = ref(init.comp);
const params = ref(new URLSearchParams(init.qs));
const hashKey = ref(init.hash);
const APP_VERSION = __APP_VERSION__;

onMounted(async () => {
  window.addEventListener("hashchange", route);
  try {
    const account = await refreshAccount();
    if (account.accountProtected && !account.authenticated) location.hash = "#/account";
  } catch { /* 页面自身会展示网络错误；不影响游客离线浏览 */ }
});

function route() {
  stopAudio();
  const r = currentRoute();
  params.value = new URLSearchParams(r.qs);
  view.value = r.comp;
  hashKey.value = r.hash;
  window.scrollTo(0, 0);
}
</script>

<template>
  <TopBar />
  <main>
    <component :is="view" :params="params" :key="hashKey" />
  </main>
  <footer class="app-footer">
    英语听打 v{{ APP_VERSION.replace(/\.0$/, "") }}
    <span class="foot-sep">·</span>
    <a class="foot-mail" href="mailto:jonesc@foxmail.com">联系我：jonesc@foxmail.com</a>
  </footer>
</template>
