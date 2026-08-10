import { createApp } from "vue";
import App from "./App.vue";
import { Settings } from "./lib/core";
import "./styles.css";

document.documentElement.setAttribute("data-theme", Settings.get().theme);
createApp(App).mount("#app");