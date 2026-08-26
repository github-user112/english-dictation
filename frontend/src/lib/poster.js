/* 海报绘制共享件：双主题调色板与画布小工具（ReportPage / DailyPage 共用）。
 * 色值与 styles.css 的 tokens 保持一致；good/bad 取自 --green/--red。 */

export function currentTheme() {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

export const PALETTES = {
  dark: {
    bgTop: "#0e1631", bgMid: "#0b1020", bgBottom: "#070a14",
    glow: "rgba(245,168,60,.22)", grid: "rgba(158,174,222,.07)",
    title: "#f2efe6", sub: "#a7b0c8", dim: "#667089",
    big: "#ffd37a", cardStroke: "rgba(158,174,222,.18)", cardFill: "rgba(27,35,64,.55)",
    label: "#a7b0c8", num: "#f2efe6",
    good: "#3edc97", bad: "#ff6b7a",
  },
  light: {
    bgTop: "#fffdf8", bgMid: "#f3efe7", bgBottom: "#eae4d6",
    glow: "rgba(217,138,29,.16)", grid: "rgba(31,42,66,.06)",
    title: "#1d2436", sub: "#5c6579", dim: "#9aa0b0",
    big: "#b06e0e", cardStroke: "rgba(31,42,66,.15)", cardFill: "rgba(255,255,255,.72)",
    label: "#5c6579", num: "#1d2436",
    good: "#149a64", bad: "#d24d5a",
  },
};

export function roundRect(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}
