<script setup>
import { ref, onMounted } from "vue";
import TopBar from "./components/TopBar.vue";
import CatalogPage from "./components/CatalogPage.vue";
import PracticePage from "./components/PracticePage.vue";
import MemorizePage from "./components/MemorizePage.vue";
import WrongPage from "./components/WrongPage.vue";
import StatsPage from "./components/StatsPage.vue";
import SettingsPage from "./components/SettingsPage.vue";
import AccountPage from "./components/AccountPage.vue";
import { refreshAccount } from "./lib/account";

const ROUTES = {
  catalog: CatalogPage, word: PracticePage, sentence: PracticePage,
  memorize: MemorizePage,
  wrong: WrongPage, stats: StatsPage, settings: SettingsPage, account: AccountPage,
};
const view = ref(CatalogPage);
const params = ref(new URLSearchParams());
const hashKey = ref("");
const APP_VERSION = __APP_VERSION__;

onMounted(async () => {
  window.addEventListener("hashchange", route);
  route();
  try {
    const account = await refreshAccount();
    if (account.accountProtected && !account.authenticated) location.hash = "#/account";
  } catch { /* 页面自身会展示网络错误；不影响游客离线浏览 */ }
});

function route() {
  const h = location.hash.replace(/^#\/?/, "") || "catalog";
  const [page, qs] = h.split("?");
  params.value = new URLSearchParams(qs || "");
  view.value = ROUTES[page] || CatalogPage;
  hashKey.value = location.hash;
  window.scrollTo(0, 0);
}
</script>

<template>
  <TopBar />
  <main>
    <component :is="view" :params="params" :key="hashKey" />
  </main>
  <footer class="app-footer">英语听打 v{{ APP_VERSION.replace(/\.0$/, "") }}</footer>
</template>
