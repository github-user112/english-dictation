/* 海报绘制共享件：双主题调色板与画布小工具（ReportPage / DailyPage 共用）。
 * 调色板与 styles/base.css 的 Duolingo tokens 保持一致：
 *   --green #58cc02 / --green-dark #46a302 / --bg #f7f7f7 / --panel #fff
 *   --text #3c3c3c / --border #e5e5e5 / 暗色 --bg #131313
 * 字体用 index.html 引入的 Nunito（圆润粗黑，Duolingo 签名）。 */

export function currentTheme() {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

/* 海报专用字体栈：Nunito 优先，中文用 base.css @font-face 的 "NotoSansSC"，
 * emoji 用 @font-face 的 "NotoColorEmoji"。
 * 注意：canvas 不会自动套用 CSS 的 @font-face 字体，必须先经下方 readyFonts()
 * 显式触发加载，否则中文与 emoji 渲染成豆腐块。 */
export const FONT = {
  title:  "900 32px Nunito,'NotoSansSC','PingFang SC',sans-serif",
  sub:    "800 15px Nunito,'NotoSansSC','PingFang SC',sans-serif",
  hero:   "900 168px Nunito,'NotoSansSC',sans-serif",
  heroSub:"800 27px Nunito,'NotoSansSC','PingFang SC',sans-serif",
  num:    "900 54px Nunito,'NotoSansSC','PingFang SC',sans-serif",
  label:  "800 23px Nunito,'NotoSansSC','PingFang SC',sans-serif",
  foot:   "800 22px Nunito,'NotoSansSC','PingFang SC',sans-serif",
  emoji:  '44px "NotoColorEmoji","Noto Color Emoji",serif',
  emojiSm:'34px "NotoColorEmoji","Noto Color Emoji",serif',
};

/* 触发上述字体加载（已缓存则立即返回）。paintPoster 之前 await。 */
export async function readyFonts() {
  if (!document.fonts || !document.fonts.load) return;
  const reqs = [
    "900 32px Nunito",
    "900 32px 'NotoSansSC'",
    "900 168px Nunito",
    '44px "NotoColorEmoji"',
    '44px "Noto Color Emoji"',
  ];
  await Promise.all(reqs.map(r => document.fonts.load(r).catch(() => {})));
}

export const PALETTES = {
  dark: {
    bgTop: "#131313", bgMid: "#1c1c1c", bgBottom: "#131313",
    band: "#58cc02", bandDark: "#46a302",
    title: "#ffffff", sub: "#c9c9c9", dim: "#7c7c7c",
    big: "#58cc02",
    cardStroke: "rgba(255,255,255,.14)", cardFill: "rgba(255,255,255,.055)",
    label: "#c9c9c9", num: "#ffffff",
    accentBg: "rgba(255,255,255,.12)", accentText: "#ffffff",
    good: "#58cc02", bad: "#ff4b4b",
  },
  light: {
    bgTop: "#ffffff", bgMid: "#f7f7f7", bgBottom: "#efefef",
    band: "#58cc02", bandDark: "#46a302",
    title: "#3c3c3c", sub: "#777777", dim: "#a3a3a3",
    big: "#46a302",
    cardStroke: "#e5e5e5", cardFill: "#ffffff",
    label: "#777777", num: "#3c3c3c",
    accentBg: "#e8f9d9", accentText: "#46a302",
    good: "#58cc02", bad: "#ff4b4b",
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

/* Duolingo 签名：3px 下压实体阴影的圆角卡片（canvas 版） */
export function duoCard(g, x, y, w, h, r, P) {
  g.save();
  g.fillStyle = P.bandDark;
  roundRect(g, x, y + 3, w, h, r); g.fill();   // 下压层
  g.fillStyle = P.cardFill;
  roundRect(g, x, y, w, h, r); g.fill();       // 主体
  g.lineWidth = 2; g.strokeStyle = P.cardStroke;
  roundRect(g, x, y, w, h, r); g.stroke();
  g.restore();
}
