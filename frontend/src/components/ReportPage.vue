<script setup>
import { computed, onMounted, onUnmounted, ref, watch, nextTick } from "vue";
import { api } from "../lib/core";
import { activity, goldenHour } from "../lib/stats";

const stats = ref(null);
const error = ref("");
const poster = ref(null);   // canvas ref
let themeObserver = null;

onMounted(() => {
  load();
  // 跟随亮 / 暗主题切换，用对应调色板重绘海报
  themeObserver = new MutationObserver(() => {
    if (view.value) drawPoster();
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
});
onUnmounted(() => themeObserver?.disconnect());

async function load() {
  error.value = "";
  try {
    stats.value = await api("/stats");
  } catch (err) {
    error.value = err.message || "报告加载失败";
  }
}

const view = computed(() => {
  if (!stats.value) return null;
  const s = stats.value;
  const totalWords = (s.total_right || 0) + (s.total_wrong || 0);
  let fr = 0, fw = 0;
  for (const m of Object.values(s.practice_modes || {})) { fr += m.first_right; fw += m.first_wrong; }
  const acc = fr + fw ? Math.round((fr / (fr + fw)) * 100) : 0;
  let bestDay = null, activeDays = 0;
  for (const d of s.days || []) {
    const n = activity(d);
    if (n > 0) activeDays++;
    if (!bestDay || n > bestDay.n) bestDay = { day: d.day.slice(5), n };
  }
  const hours = s.hours || [];
  const peak = goldenHour(hours);
  const golden = peak ? `${peak} 点` : null;
  const maxHours = Math.max(1, ...hours);
  return { totalWords, acc, streak: s.streak || 0,
           memorized: s.total_memorize_right || 0,
           bestDay: bestDay && bestDay.n > 0 ? bestDay : null,
           activeDays, golden, hours, maxHours };
});
/* 数据就绪后绘制海报 */
watch(view, async (v) => {
  if (!v) return;
  await nextTick();
  drawPoster();
});

/* 海报双主题调色板：与 styles.css 的 tokens 保持一致 */
function currentTheme() {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}
const PALETTES = {
  dark: {
    bgTop: "#0e1631", bgMid: "#0b1020", bgBottom: "#070a14",
    glow: "rgba(245,168,60,.22)", grid: "rgba(158,174,222,.07)",
    title: "#f2efe6", sub: "#a7b0c8", dim: "#667089",
    big: "#ffd37a", cardStroke: "rgba(158,174,222,.18)", cardFill: "rgba(27,35,64,.55)",
    label: "#a7b0c8", num: "#f2efe6",
  },
  light: {
    bgTop: "#fffdf8", bgMid: "#f3efe7", bgBottom: "#eae4d6",
    glow: "rgba(217,138,29,.16)", grid: "rgba(31,42,66,.06)",
    title: "#1d2436", sub: "#5c6579", dim: "#9aa0b0",
    big: "#b06e0e", cardStroke: "rgba(31,42,66,.15)", cardFill: "rgba(255,255,255,.72)",
    label: "#5c6579", num: "#1d2436",
  },
};

/* 预览画布按显示尺寸渲染即可；全分辨率（dpr=2，约 18MB 位图）只在保存时离屏出一次 */
function paintPoster(cv, v, dpr, P) {
  const W = 900, H = 1260;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext("2d");
  g.scale(dpr, dpr);
  // 背景：主题渐变 + 主色辉光
  const bg = g.createLinearGradient(0, 0, W * .4, H);
  bg.addColorStop(0, P.bgTop); bg.addColorStop(.55, P.bgMid); bg.addColorStop(1, P.bgBottom);
  g.fillStyle = bg; g.fillRect(0, 0, W, H);
  const glow = g.createRadialGradient(120, -40, 20, 120, -40, 520);
  glow.addColorStop(0, P.glow); glow.addColorStop(1, "transparent");
  g.fillStyle = glow; g.fillRect(0, 0, W, 620);
  // 细网格
  g.strokeStyle = P.grid; g.lineWidth = 1;
  for (let x = 44; x < W; x += 44) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); }
  for (let y = 44; y < H; y += 44) { g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
  // 品牌行
  g.fillStyle = "#f5a83c"; roundRect(g, 64, 64, 56, 56, 14); g.fill();
  g.fillStyle = "#241703"; g.font = "800 34px Georgia, 'Noto Serif SC', serif";
  g.textBaseline = "middle"; g.textAlign = "center"; g.fillText("E", 92, 94);
  g.textAlign = "left";
  g.fillStyle = P.title; g.font = "700 30px 'PingFang SC','Microsoft YaHei',sans-serif";
  g.fillText("英语听打 · 学习报告", 138, 86);
  g.fillStyle = P.dim; g.font = "600 15px Inter,'PingFang SC',sans-serif";
  g.fillText("DICTATION STUDIO", 139, 112);
  // 大数字
  g.fillStyle = P.big; g.font = "700 150px Georgia,'Noto Serif SC',serif";
  g.fillText(String(v.totalWords), 60, 300);
  g.fillStyle = P.sub; g.font = "500 26px 'PingFang SC',sans-serif";
  g.fillText(`个词被你听写下来 · 首答正确率 ${v.acc}%`, 64, 392);
  // 指标卡
  const cards = [
    ["🔥", `${v.streak} 天`, "连续打卡"],
    ["🧠", `${v.memorized}`, "已背下的词"],
    ["📅", `${v.activeDays} 天`, "有学习记录"],
    ...(v.golden ? [["⏰", v.golden, "你的黄金时段"]] : []),
    ...(v.bestDay ? [["💪", `${v.bestDay.n} 题`, `单日之最（${v.bestDay.day}）`]] : []),
  ];
  cards.forEach(([icon, num, lab], i) => {
    const x = 64 + (i % 2) * 400, y = 470 + Math.floor(i / 2) * 190;
    g.strokeStyle = P.cardStroke; g.lineWidth = 1.5;
    roundRect(g, x, y, 372, 160, 20); g.stroke();
    g.fillStyle = P.cardFill; roundRect(g, x, y, 372, 160, 20); g.fill();
    g.font = "44px serif"; g.fillStyle = "#f5a83c"; g.textAlign = "left";
    g.fillText(icon, x + 28, y + 62);
    g.fillStyle = P.num; g.font = "700 52px Georgia,'Noto Serif SC',serif";
    g.fillText(num, x + 92, y + 66);
    g.fillStyle = P.label; g.font = "400 24px 'PingFang SC',sans-serif";
    g.fillText(lab, x + 30, y + 122);
  });
  // 页脚
  g.fillStyle = P.dim; g.font = "500 22px 'PingFang SC',sans-serif"; g.textAlign = "center";
  g.fillText("mi2.cc.cd · 听清每一个词，写下每一句", W / 2, H - 70);
}
function drawPoster() {
  const cv = poster.value;
  const v = view.value;
  if (!cv || !v) return;
  paintPoster(cv, v, 1, PALETTES[currentTheme()]);   // CSS 显示约 400px 宽，900px 内部宽度已足够清晰
}
function roundRect(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

/* ---- 打卡海报下载：离屏重绘 dpr=2 全分辨率再导出 ---- */
function savePoster() {
  const v = view.value;
  if (!v) return;
  const off = document.createElement("canvas");
  paintPoster(off, v, 2, PALETTES[currentTheme()]);
  const a = document.createElement("a");
  a.download = `英语听打报告-${new Date().toISOString().slice(0, 10)}.png`;
  a.href = off.toDataURL("image/png");
  a.click();
}
</script>

<template>
  <div v-if="error" class="empty" role="alert"><p>{{ error }}</p><button class="btn primary" @click="load">重试</button></div>
  <div v-else-if="!view" class="empty">加载中…</div>
  <div v-else class="report-page">
    <div class="page-heading compact">
      <span class="eyebrow">YOUR WRAPPED</span>
      <h1>这一年，<em style="font-style:normal;color:var(--accent-strong)">你听写了 {{ view.totalWords }} 个词。</em></h1>
      <p>数据全部来自你的真实练习，随时可以保存成海报留念。</p>
    </div>

    <div class="report-grid">
      <canvas ref="poster" class="report-poster" width="450" height="630"
              aria-label="学习报告海报预览"></canvas>
      <div class="report-side">
        <div class="stat-cards" style="grid-template-columns:1fr 1fr;">
          <div class="stat-card"><div class="num">{{ view.streak }}<small> 天</small></div><div class="lab">连续打卡</div></div>
          <div class="stat-card"><div class="num">{{ view.acc }}<small>%</small></div><div class="lab">首答正确率</div></div>
          <div class="stat-card"><div class="num">{{ view.memorized }}</div><div class="lab">背下的词</div></div>
          <div class="stat-card"><div class="num">{{ view.activeDays }}</div><div class="lab">有记录的天数</div></div>
        </div>
        <p v-if="view.golden" class="sub">你常在 <b style="color:var(--accent-strong)">{{ view.golden }}</b> 坐到麦克风前——那是一天里你的黄金时段。</p>
        <p v-if="view.bestDay" class="sub">最拼的一天是 <b style="color:var(--green)">{{ view.bestDay.day }}</b>，一口气拿下了 {{ view.bestDay.n }} 题。</p>
        <div style="display:flex;gap:12px;margin-top:18px;">
          <button class="btn primary big" @click="savePoster">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>
            保存海报 PNG
          </button>
          <button class="btn ghost big" onclick="window.print()">打印 / 存 PDF</button>
        </div>
      </div>
    </div>
  </div>
</template>
