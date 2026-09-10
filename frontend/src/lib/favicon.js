/* 站点图标跟随主题：与顶栏品牌块同款——
   亮色：多邻国绿渐变圆角方 + 白字 E（默认）
   暗色：深灰圆角方 + 细描边 + 绿字 E
   通过 MutationObserver 监听 <html data-theme>，任何改主题的路径都会自动换标。 */

const THEMES = {
  light: {
    bg: "url(#g)",
    stroke: "",
    text: "#ffffff",
    defs: `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#6fdd1a"/><stop offset=".58" stop-color="#58cc02"/>
<stop offset="1" stop-color="#46a302"/></linearGradient></defs>`,
  },
  dark: {
    bg: "#1e1e1e",
    stroke: ` stroke="#3a3a3a" stroke-opacity=".9"`,
    text: "#58cc02",
    defs: "",
  },
};

function svgFor(mode) {
  const t = THEMES[mode] || THEMES.dark;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">${t.defs}` +
    `<rect x="2" y="2" width="60" height="60" rx="15" fill="${t.bg}"${t.stroke}/>` +
    `<text x="32" y="35" font-family="Nunito,'Segoe UI',system-ui,sans-serif" font-size="38" font-weight="800"` +
    ` fill="${t.text}" text-anchor="middle">E</text></svg>`;
}

export function currentTheme() {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

export function applyFavicon(theme = currentTheme()) {
  let link = document.querySelector("link[rel='icon'][type='image/svg+xml']");
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    link.type = "image/svg+xml";
    document.head.appendChild(link);
  }
  link.href = `data:image/svg+xml,${encodeURIComponent(svgFor(theme))}`;
  return link.href;
}

let observer = null;
export function watchFavicon() {
  if (observer || typeof MutationObserver === "undefined") return;
  observer = new MutationObserver(() => { applyFavicon(); });
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
}
