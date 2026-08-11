<script setup>
import { ref, onMounted } from "vue";
import TopBar from "./components/TopBar.vue";
import CatalogPage from "./components/CatalogPage.vue";
import PracticePage from "./components/PracticePage.vue";
import WrongPage from "./components/WrongPage.vue";
import StatsPage from "./components/StatsPage.vue";
import SettingsPage from "./components/SettingsPage.vue";

const ROUTES = {
  catalog: CatalogPage, word: PracticePage, sentence: PracticePage,
  wrong: WrongPage, stats: StatsPage, settings: SettingsPage,
};
const view = ref(CatalogPage);
const params = ref(new URLSearchParams());
const APP_VERSION = __APP_VERSION__;

onMounted(() => {
  window.addEventListener("hashchange", route);
  route();
});

function route() {
  const h = location.hash.replace(/^#\/?/, "") || "catalog";
  const [page, qs] = h.split("?");
  params.value = new URLSearchParams(qs || "");
  view.value = ROUTES[page] || CatalogPage;
  window.scrollTo(0, 0);
}
</script>

<template>
  <TopBar />
  <main @click="route">
    <component :is="view" :params="params" />
  </main>
  <footer class="app-footer">英语听打 v{{ APP_VERSION.replace(/\.0$/, "") }}</footer>
</template>