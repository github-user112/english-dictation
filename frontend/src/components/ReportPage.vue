<script setup>
import { computed, onMounted, onUnmounted, ref, watch, nextTick } from "vue";
import { api } from "../lib/core";
import { activity, goldenHour } from "../lib/stats";
import { PALETTES, currentTheme, roundRect } from "../lib/poster";

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

/* 双主题调色板与圆角路径已抽到 lib/poster.js，与 DailyPage 共用 */

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
  <div v-if="error" class="empty" role="alert">
    <span class="emoji" aria-hidden="true">⚠️</span>
    <h3>报告加载失败</h3>
    <p>{{ error }}</p>
    <button class="btn primary" @click="load">🔁 重试</button>
  </div>
  <div v-else-if="!view" class="empty loading">
    <span class="spin" aria-hidden="true"></span>
    <span class="load-text">加载中…</span>
  </div>
  <div v-else class="report-page">

    <!-- 成就庆祝弹层：里程碑达成时显示，点击关闭 -->
    <div v-if="view.streak >= 7 || view.totalWords >= 1000 || view.acc >= 90"
         class="ach-celebrate" onclick="this.style.display='none'">
      <div class="ach-box">
        <span class="ach-title">🎉 里程碑达成</span>
        <div v-if="view.streak >= 7" class="ach-item">
          <span class="ach-icon">🔥</span>
          <span><b>周连胜</b><small>连续打卡 7 天，毅力满满！</small></span>
        </div>
        <div v-if="view.streak >= 30" class="ach-item">
          <span class="ach-icon">🏆</span>
          <span><b>月之铁人</b><small>连续打卡 30 天，你是真的狠！</small></span>
        </div>
        <div v-if="view.totalWords >= 1000" class="ach-item">
          <span class="ach-icon">📚</span>
          <span><b>千词达人</b><small>累计听写 1000 个词，词汇量稳步增长！</small></span>
        </div>
        <div v-if="view.totalWords >= 5000" class="ach-item">
          <span class="ach-icon">👑</span>
          <span><b>万词先锋</b><small>累计听写 5000 个词，词汇量已破局！</small></span>
        </div>
        <div v-if="view.acc >= 90" class="ach-item">
          <span class="ach-icon">🎯</span>
          <span><b>精准射手</b><small>正确率突破 90%，听写能力过硬！</small></span>
        </div>
        <span class="ach-close">点击关闭</span>
      </div>
    </div>

    <!-- 页头 -->
    <div class="report-head">
      <div>
        <h1><span class="emoji">📋</span> 学习报告</h1>
        <p>数据全部来自你的真实练习，随时可以保存成海报留念。</p>
      </div>
      <div class="report-head-actions">
        <button class="btn white sm" @click="savePoster">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>
          保存海报
        </button>
      </div>
    </div>

    <!-- Hero 区：完成度圆环 + 核心统计 + 连胜徽章 -->
    <div class="report-hero">
      <div class="hero-row">
        <div class="hero-ring-wrap">
          <svg viewBox="0 0 130 130">
            <circle cx="65" cy="65" r="55" fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="10"/>
            <circle cx="65" cy="65" r="55" fill="none" stroke="#fff" stroke-width="10"
                    stroke-linecap="round"
                    stroke-dasharray="345.6"
                    :stroke-dashoffset="(345.6 * (100 - view.acc) / 100).toFixed(1)"
                    transform="rotate(-90 65 65)"
                    filter="drop-shadow(0 0 4px rgba(255,255,255,0.4))"/>
          </svg>
          <div class="hero-ring-center">
            <div class="n">{{ view.acc }}%</div>
            <div class="lbl">正确率</div>
          </div>
        </div>

        <div class="hero-main">
          <div class="hero-headline">
            <span class="emoji">🎉</span>
            <span>这一年，你听写了 <b>{{ view.totalWords }}</b> 个词。</span>
          </div>
          <div class="hero-subline">
            连续打卡 <b>{{ view.streak }}</b> 天 · 有学习记录 <b>{{ view.activeDays }}</b> 天 · 背下 <b>{{ view.memorized }}</b> 个词
          </div>
        </div>

        <div class="hero-streak-badge">
          <div class="flame">🔥</div>
          <div class="day">{{ view.streak }}</div>
          <div class="day-label">连续天数</div>
        </div>
      </div>
    </div>

    <!-- 周报行：近 7 天柱状 + 模式分布 + 成长指标 -->
    <div class="weekly-row">
      <!-- 近 7 天学习量 -->
      <div class="weekly-card">
        <div class="card-title"><span class="ic">📈</span> 近 7 天学习量</div>
        <div class="sub">每天练习了多少题</div>
        <div class="day-bars">
          <div v-for="(d, i) in stats.days.slice(-7)" :key="d.day" class="day-bar-col">
            <div class="day-bar-val" :class="{ today: i === 6 }">
              {{ d.right + d.wrong + d.memorize_right + d.memorize_wrong || 0 }}
            </div>
            <div class="day-bar" :class="{ today: i === 6 }"
                 :style="{ height: Math.max(3, ((d.right + d.wrong + d.memorize_right + d.memorize_wrong) / Math.max(1, ...stats.days.slice(-7).map(x => x.right + x.wrong + x.memorize_right + x.memorize_wrong))) * 100) + '%' }"></div>
            <div class="day-bar-label" :class="{ today: i === 6 }">
              {{ ['日','一','二','三','四','五','六'][new Date(d.day).getDay()] }}
            </div>
          </div>
        </div>
      </div>

      <!-- 模式分布 -->
      <div class="weekly-card">
        <div class="card-title"><span class="ic">🎯</span> 模式分布</div>
        <div class="sub">各模式首答正确率</div>
        <div class="mode-breakdown">
          <div v-for="(m, mode, idx) in stats.practice_modes" :key="mode" class="mode-bar-item">
            <div class="head">
              <div class="name">
                <span class="em">{{ ['🎧','📝','🎤','✂️','🎮','📖'][idx % 6] }}</span>
                {{ mode }}
              </div>
              <div class="val">{{ m.first_right + m.first_wrong }} 题</div>
            </div>
            <div class="mode-bar-track">
              <div class="mode-bar-fill"
                   :style="{ width: (m.first_accuracy * 100).toFixed(1) + '%',
                             background: ['linear-gradient(90deg, var(--green), #6fdd1a)',
                                          'linear-gradient(90deg, var(--blue), #4dd0ff)',
                                          'linear-gradient(90deg, var(--purple), #e0aaff)',
                                          'linear-gradient(90deg, var(--orange), #ffb347)',
                                          'linear-gradient(90deg, var(--gold), #ffdf6b)',
                                          'linear-gradient(90deg, var(--red), #ff7b7b)'][idx % 6] }"></div>
            </div>
          </div>
          <div v-if="!stats.practice_modes || Object.keys(stats.practice_modes).length === 0" class="empty" style="padding:20px 0">
            <p style="font-size:12px">暂无模式数据</p>
          </div>
        </div>
      </div>

      <!-- 成长指标 -->
      <div class="weekly-card">
        <div class="card-title"><span class="ic">📊</span> 成长指标</div>
        <div class="sub">关键数据一览</div>
        <div class="metric-list">
          <div class="metric-item">
            <div class="metric-icon-wrap green">🎯</div>
            <div class="metric-body">
              <b>正确率</b>
              <small>{{ view.acc }}% 首答正确</small>
            </div>
            <div class="metric-trend up">↑</div>
          </div>
          <div class="metric-item">
            <div class="metric-icon-wrap blue">📝</div>
            <div class="metric-body">
              <b>累计听写</b>
              <small>{{ view.totalWords }} 词</small>
            </div>
            <div class="metric-trend up">↑</div>
          </div>
          <div class="metric-item">
            <div class="metric-icon-wrap gold">🧠</div>
            <div class="metric-body">
              <b>背下的词</b>
              <small>{{ view.memorized }} 个</small>
            </div>
            <div class="metric-trend up">↑</div>
          </div>
          <div class="metric-item">
            <div class="metric-icon-wrap purple">⚠️</div>
            <div class="metric-body">
              <b>错词本</b>
              <small>{{ stats.wrong_words }} 个待复习</small>
            </div>
            <div class="metric-trend flat">·</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 打卡热力图 -->
    <div class="heatmap-card">
      <div class="hm-head">
        <div class="title"><span class="ic">🗓️</span> 打卡热力图</div>
      </div>
      <div class="hm-sub">绿色越深表示当天练习量越大，共 {{ view.activeDays }} 天有记录</div>
      <div class="hm-grid-wrap">
        <div class="heat-grid">
          <span v-for="d in stats.days.slice(-60)" :key="d.day"
                class="heat-cell"
                :class="(d.right + d.wrong + d.memorize_right + d.memorize_wrong) > 0
                  ? 'lvl' + ((d.right + d.wrong + d.memorize_right + d.memorize_wrong) <= 5 ? 1
                    : (d.right + d.wrong + d.memorize_right + d.memorize_wrong) <= 20 ? 2
                    : (d.right + d.wrong + d.memorize_right + d.memorize_wrong) <= 50 ? 3 : 4)
                  : ''"
                :title="d.day + '：' + (d.right + d.wrong + d.memorize_right + d.memorize_wrong) + ' 题'">
          </span>
        </div>
      </div>
      <div class="heat-legend">
        <span>少</span>
        <span class="heat-cell"></span>
        <span class="heat-cell lvl1"></span>
        <span class="heat-cell lvl2"></span>
        <span class="heat-cell lvl3"></span>
        <span class="heat-cell lvl4"></span>
        <span>多</span>
      </div>
    </div>

    <!-- 最佳学习时段 -->
    <div class="besttime-card">
      <div class="bt-head">
        <div class="title"><span class="ic">⏰</span> 最佳学习时段</div>
      </div>
      <div class="bt-sub">过去一年的作答小时分布，找到你的黄金时段 💡</div>
      <div class="hour-chart">
        <div v-for="(n, h) in view.hours" :key="h" class="hour-col">
          <div class="hour-bar"
               :class="{ peak: view.golden && String(h).padStart(2, '0') === view.golden.replace(' 点', ''),
                         zero: n === 0 }"
               :style="{ height: n > 0 ? (n / view.maxHours * 100) + '%' : '2px' }"></div>
          <div class="hour-label"
               :class="{ peak: view.golden && String(h).padStart(2, '0') === view.golden.replace(' 点', '') }">
            {{ h }}
          </div>
        </div>
      </div>
      <div v-if="view.golden" class="peak-cards">
        <div class="peak-item best">
          <div class="peak-tag">最佳</div>
          <div class="em">⭐</div>
          <div class="time">{{ view.golden }}</div>
          <div class="day">你的黄金时段</div>
          <div class="acc">这一小时你最多坐在麦克风前</div>
        </div>
        <div class="peak-item">
          <div class="em">🌙</div>
          <div class="time">夜间</div>
          <div class="day">21:00 - 23:00</div>
          <div class="acc">晚间学习也很高效</div>
        </div>
        <div class="peak-item">
          <div class="em">⚠️</div>
          <div class="time">午间</div>
          <div class="day">13:00 - 14:00</div>
          <div class="acc">建议适当休息</div>
        </div>
      </div>
    </div>

    <!-- 学习洞察 -->
    <div class="insight-card">
      <div class="sec-head">
        <span class="sh-emoji">💡</span>
        <div>
          <div class="sh-title">学习洞察</div>
          <div class="sh-sub">基于你的真实数据生成</div>
        </div>
      </div>
      <div class="insight-grid">
        <div v-if="view.golden" class="insight green">
          <div class="ic">⭐</div>
          <b>黄金时段：{{ view.golden }}</b>
          <small>你在这个时间段练习最多，是继续保持的最佳时机！</small>
        </div>
        <div v-if="view.bestDay" class="insight blue">
          <div class="ic">💪</div>
          <b>最拼的一天：{{ view.bestDay.day }}</b>
          <small>一口气拿下了 {{ view.bestDay.n }} 题，状态拉满！</small>
        </div>
        <div class="insight purple">
          <div class="ic">🔥</div>
          <b>{{ view.streak }} 天连胜！</b>
          <small>坚持每天练习，你的词汇量正在稳步增长。继续加油！</small>
        </div>
        <div class="insight orange">
          <div class="ic">📈</div>
          <b>已背下 {{ view.memorized }} 个词</b>
          <small>背词是听写的基础，继续保持每天复习的习惯！</small>
        </div>
      </div>
    </div>

    <!-- 成就徽章墙 -->
    <div class="badge-section">
      <div class="sec-head">
        <span class="sh-emoji">🏅</span>
        <div>
          <div class="sh-title">成就徽章</div>
          <div class="sh-sub">解锁你的学习里程碑</div>
        </div>
      </div>
      <div class="badge-wall">
        <div v-for="b in [
          { icon: '🌱', title: '初出茅庐', desc: '开始听写第一个词', on: view.totalWords >= 1 },
          { icon: '📚', title: '千词达人', desc: '累计听写 1000 个词', on: view.totalWords >= 1000 },
          { icon: '👑', title: '万词先锋', desc: '累计听写 5000 个词', on: view.totalWords >= 5000 },
          { icon: '🔥', title: '周连胜', desc: '连续打卡 7 天', on: view.streak >= 7 },
          { icon: '🏆', title: '月之铁人', desc: '连续打卡 30 天', on: view.streak >= 30 },
          { icon: '⏳', title: '百日坚持', desc: '连续打卡 100 天', on: view.streak >= 100 },
          { icon: '🎯', title: '精准射手', desc: '正确率突破 80%', on: view.acc >= 80 },
          { icon: '🎯', title: '完美主义者', desc: '正确率突破 90%', on: view.acc >= 90 },
          { icon: '🧠', title: '记忆大师', desc: '背下 100 个词', on: view.memorized >= 100 },
          { icon: '🧠', title: '超级大脑', desc: '背下 500 个词', on: view.memorized >= 500 },
          { icon: '📅', title: '月活达人', desc: '30 天有学习记录', on: view.activeDays >= 30 },
          { icon: '📅', title: '百日活跃', desc: '100 天有学习记录', on: view.activeDays >= 100 },
        ]" :key="b.title" class="badge-chip" :class="{ on: b.on }">
          <span class="bc-icon">{{ b.icon }}</span>
          <div class="bc-body">
            <b>{{ b.title }}</b>
            <small>{{ b.desc }}</small>
          </div>
        </div>
      </div>
    </div>

    <!-- 海报预览与保存 -->
    <div class="poster-section">
      <div class="sec-head">
        <span class="sh-emoji">🖼️</span>
        <div>
          <div class="sh-title">学习报告海报</div>
          <div class="sh-sub">一键保存，分享你的学习成果</div>
        </div>
      </div>
      <div class="poster-grid">
        <div class="poster-frame">
          <canvas ref="poster" class="report-poster" width="450" height="630"
                  aria-label="学习报告海报预览"></canvas>
        </div>
        <div class="poster-side">
          <div class="stat-cards" style="grid-template-columns:1fr 1fr;">
            <div class="stat-card"><div class="num">{{ view.streak }}<small> 天</small></div><div class="lab">连续打卡</div></div>
            <div class="stat-card"><div class="num">{{ view.acc }}<small>%</small></div><div class="lab">首答正确率</div></div>
            <div class="stat-card"><div class="num">{{ view.memorized }}</div><div class="lab">背下的词</div></div>
            <div class="stat-card"><div class="num">{{ view.activeDays }}</div><div class="lab">有记录的天数</div></div>
          </div>
          <p v-if="view.golden" class="sub">你常在 <b style="color:var(--accent-strong)">{{ view.golden }}</b> 坐到麦克风前——那是一天里你的黄金时段。</p>
          <p v-if="view.bestDay" class="sub">最拼的一天是 <b style="color:var(--green)">{{ view.bestDay.day }}</b>，一口气拿下了 {{ view.bestDay.n }} 题。</p>
          <div class="poster-actions" style="display:flex;gap:12px;margin-top:18px;">
            <button class="btn primary big" @click="savePoster">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>
              保存海报 PNG
            </button>
            <button class="btn ghost big" onclick="window.print()">打印 / 存 PDF</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 页脚 -->
    <div class="report-foot">📋 学习报告每日自动生成 · 数据实时分析 · 鼓励文案 AI 生成</div>

  </div>
</template>
