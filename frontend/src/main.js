import { createApp } from "vue";
import App from "./App.vue";
import { Settings } from "./lib/core";
import { applyFavicon, watchFavicon } from "./lib/favicon";
import "./styles.css";

document.documentElement.setAttribute("data-theme", Settings.get().theme);
applyFavicon();     // 站点图标跟随主题（亮=琥珀，暗=墨蓝），此后由观察者自动换
watchFavicon();
createApp(App).mount("#app");