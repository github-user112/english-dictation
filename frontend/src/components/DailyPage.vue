<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, playWord, sndRight, sndWrong } from "../lib/core";
import { dailyEmojiGrid, shareGridText } from "../lib/progress";
import { PALETTES, currentTheme, roundRect } from "../lib/poster";

const props = defineProps({ params: { type: Object, default: null } });

const KIND_LABELS = {
  audio_en: "听音选词",
  en_zh: "听词选义",
  zh_en: "看义选词",
};
const HINTS = {
  audio_en: "听发音，选出正确的单词 · 答对自动下一题 · 快捷键 1-4 · 空格重听",
  en_zh: "听发音，选出正确的中文意思 · 快捷键 1-4 · 空格重听",
  zh_en: "看中文意思，选出正确的单词 · 快捷键 1-4",
};

const list = ref("cet4");
const wordLists = ref([]);      // 可选词汇素材（句子素材不参与每日挑战）
const questions = ref([]);
const day = ref("");
const listTitle = ref("");
const qi = ref(0);
const picked = ref(null);
const graded = ref(false);
const nextTimer = ref(null);
const lastRight = ref(false);
const picks = ref([]);          // [{id, picked}] 提交与服务端判分的依据
const stage = ref("play");      // play | done
const completed = ref(false);   // 今日成绩是否已计分
const result = ref(null);       // 服务端返回的正式成绩 {score,total,detail,profile,...}
const fallbackProfile = ref(null);   // 回访结算页没有随成绩返回 profile，单独兜底
const replaying = ref(false);   // 完成后的重玩：只练不计分
const round = ref(0);           // 练习局轮次：每 +1 服务端换一批题
const copied = ref(false);
const loading = ref(true);
const error = ref("");
let mounted = true;

const q = computed(() => questions.value[qi.value] || null);
const progress = computed(() => `${qi.value + 1} / ${questions.value.length}`);
const kindLabel = computed(() => (q.value ? KIND_LABELS[q.value.kind] : ""));

// 结算数据：正式成绩优先；重玩则用本地作答推导
const doneScore = computed(() =>
  result.value ? result.value.score : picks.value.filter((p) => p.picked === p.id).length);
const doneTotal = computed(() => (result.value ? result.value.total : questions.value.length));
const doneAcc = computed(() =>
  doneTotal.value ? Math.round((doneScore.value / doneTotal.value) * 100) : 0);
const gridCells = computed(() => {
  const detail = result.value?.detail
    || picks.value.map((p) => ({ right: p.picked === p.id }));
  return Array.from(dailyEmojiGrid(detail));   // emoji 是星面字符，不能 split("")
});
const shareText = computed(() => shareGridText({
  day: result.value?.day || day.value,
  listTitle: listTitle.value,
  score: doneScore.value,
  total: doneTotal.value,
  streak: profile.value?.daily_streak,
  detail: result.value?.detail || picks.value.map((p) => ({ right: p.picked === p.id })),
}));
const profile = computed(() => result.value?.profile || fallbackProfile.value);

onMounted(async () => {
  window.addEventListener("keydown", onKey);
  try {
    const d = await api("/lists");
    if (!mounted) return;
    wordLists.value = (d.lists || []).filter((l) => l.type === "words");
  } catch { /* 选择器加载失败不阻塞挑战本身 */ }
  // 词库优先级：URL 参数 > 上次记忆 > 默认；词表拉取失败也不阻塞挑战
  list.value = props.params?.get("list")
    || localStorage.getItem("dict_daily_list") || "cet4";
  api("/profile").then((p) => { fallbackProfile.value = p; }).catch(() => {});
  await load();
});

onUnmounted(() => {
  mounted = false;
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  window.removeEventListener("keydown", onKey);
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const qs = new URLSearchParams({ list: list.value });
    if (round.value > 0) qs.set("r", String(round.value));   // 练习局：服务端换一批题
    const d = await api(`/daily?${qs}`);
    if (!mounted) return;
    applySession(d);
    loading.value = false;
    if (stage.value === "play") play();
  } catch (err) {
    if (!mounted) return;
    error.value = err.message || "题目加载失败";
    loading.value = false;
  }
}

function applySession(d) {
  questions.value = d.questions || [];
  day.value = d.day;
  listTitle.value = d.list_title || "";
  localStorage.setItem("dict_daily_list", list.value);
  if (d.practice || round.value > 0) {
    // 练习局：只练不计分，提交被 finish 直接拦下
    completed.value = false;
    replaying.value = true;
    resetRun();
  } else if (d.completed) {
    // 今日已计分：直接落结算页展示首成绩，重玩不再提交
    completed.value = true;
    replaying.value = false;
    result.value = d.my_result;
    stage.value = "done";
  } else {
    completed.value = false;
    replaying.value = false;
    resetRun();
  }
}

function resetRun() {
  qi.value = 0;
  picked.value = null;
  graded.value = false;
  lastRight.value = false;
  picks.value = [];
  stage.value = "play";
}

function switchList() {
  if (stage.value === "play" && picks.value.length) return;   // 作答中不允许换库换题
  round.value = 0;          // 换库回到该词库的正式局
  replaying.value = false;
  load();
}

function play() {
  // 每日挑战题型逐题而定：看义选词作答前不能出声（会泄露答案）
  if (q.value && q.value.kind !== "zh_en") playWord(q.value);
}

function onKey(ev) {
  if (stage.value !== "play") return;
  if (graded.value && ev.key === "Enter") { ev.preventDefault(); next(); return; }
  if (!graded.value && ["1", "2", "3", "4"].includes(ev.key)) {
    const idx = Number(ev.key) - 1;
    if (q.value && q.value.options[idx]) answer(q.value.options[idx]);
    return;
  }
  if (ev.key === "Escape" || ev.key === " ") { ev.preventDefault(); play(); }
}

function answer(opt) {
  if (graded.value || !q.value) return;
  graded.value = true;
  picked.value = opt.id;
  lastRight.value = opt.id === q.value.id;
  picks.value.push({ id: q.value.id, picked: opt.id });
  if (lastRight.value) {
    sndRight();
    if (nextTimer.value) clearTimeout(nextTimer.value);
    nextTimer.value = setTimeout(() => { if (mounted && graded.value) next(); }, 1000);
  } else {
    sndWrong();
    if (q.value.kind === "zh_en") playWord(q.value);   // 义→形答错时朗读单词加深印象
  }
}

function next() {
  if (!graded.value) return;
  if (nextTimer.value) { clearTimeout(nextTimer.value); nextTimer.value = null; }
  qi.value++;
  graded.value = false;
  picked.value = null;
  if (q.value) play();
  else finish();
}

async function finish() {
  if (completed.value || replaying.value) { stage.value = "done"; return; }   // 重玩：只练不计分
  try {
    const d = await api("/daily/result", {
      method: "POST",
      body: JSON.stringify({ list: list.value, answers: picks.value }),
    });
    result.value = d;
    completed.value = !d.duplicate;
    window.dispatchEvent(new CustomEvent("profile-changed"));
  } catch { /* 成绩上报失败也进结算页，网格用本地作答兜底 */ }
  stage.value = "done";
}

function startReplay() {
  result.value = null;
  replaying.value = true;
  round.value++;            // 轮次前进 → 服务端出另一批词
  load();
}

async function copyShare() {
  try {
    await navigator.clipboard.writeText(shareText.value);
    copied.value = true;
    setTimeout(() => { copied.value = false; }, 2000);
  } catch { /* 剪贴板不可用时分享文本块始终可见，可手动复制 */ }
}

/* ---- 分享海报：离屏绘制，专为社媒竖图（900×1080）优化 ---- */
// 根据正确率评定等级，返回 {tier, label, color}
function dailyTier(acc) {
  if (acc >= 100) return { tier: "S", label: "全对封神", color: "#ffd37a" };
  if (acc >= 90)  return { tier: "A", label: "词力高手", color: "#3edc97" };
  if (acc >= 75)  return { tier: "B", label: "稳扎稳打", color: "#5fb0ff" };
  if (acc >= 60)  return { tier: "C", label: "继续加油", color: "#f5a83c" };
  return { tier: "D", label: "明日再战", color: "#ff8a9a" };
}

function paintDailyPoster(cv, m, dpr, P) {
  const W = 900, H = 1080;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext("2d");
  if (!g) return;
  g.scale(dpr, dpr);
  g.textBaseline = "middle";

  // —— 背景：对角渐变 + 右上辉光 + 细网格 ——
  const bg = g.createLinearGradient(0, 0, W * .35, H);
  bg.addColorStop(0, P.bgTop); bg.addColorStop(.55, P.bgMid); bg.addColorStop(1, P.bgBottom);
  g.fillStyle = bg; g.fillRect(0, 0, W, H);
  const glow = g.createRadialGradient(W + 40, -60, 30, W + 40, -60, 620);
  glow.addColorStop(0, P.glow); glow.addColorStop(1, "transparent");
  g.fillStyle = glow; g.fillRect(0, 0, W, 700);
  g.strokeStyle = P.grid; g.lineWidth = 1;
  for (let x = 50; x < W; x += 50) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); }
  for (let y = 50; y < H; y += 50) { g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }

  // —— 外框：圆角描边卡片感 ——
  g.strokeStyle = P.cardStroke; g.lineWidth = 2;
  roundRect(g, 26, 26, W - 52, H - 52, 36); g.stroke();

  // —— 品牌行 ——
  g.fillStyle = "#f5a83c"; roundRect(g, 64, 64, 56, 56, 16); g.fill();
  g.fillStyle = "#241703"; g.font = "800 34px Georgia, 'Noto Serif SC', serif";
  g.textAlign = "center"; g.fillText("E", 92, 94);
  g.textAlign = "left";
  g.fillStyle = P.title; g.font = "700 30px 'PingFang SC','Microsoft YaHei',sans-serif";
  g.fillText("英语听打 · 每日挑战", 142, 86);
  g.fillStyle = P.dim; g.font = "600 15px Inter,'PingFang SC',sans-serif";
  g.fillText("DAILY CHALLENGE", 143, 113);

  // —— 日期 / 词库胶囊 ——
  const chip = `📅 ${String(m.day || "").slice(0, 4)} 年 ${String(m.day || "").slice(5, 7)} 月 ${String(m.day || "").slice(8, 10)} 日  ·  ${m.listTitle}`;
  g.font = "500 24px 'PingFang SC',sans-serif";
  const chipW = g.measureText(chip).width + 52;
  g.fillStyle = P.cardFill; roundRect(g, (W - chipW) / 2, 156, chipW, 56, 28); g.fill();
  g.fillStyle = P.sub; g.textAlign = "center"; g.fillText(chip, W / 2, 185);

  // —— 中心正确率环 ——
  const cx = W / 2, cy = 470, R = 168, sw = 28;
  const acc = m.total ? Math.round((m.score / m.total) * 100) : 0;
  // 环后光晕
  const rg = g.createRadialGradient(cx, cy, R - 60, cx, cy, R + 70);
  rg.addColorStop(0, "transparent"); rg.addColorStop(1, P.glow);
  g.fillStyle = rg; g.beginPath(); g.arc(cx, cy, R + 70, 0, Math.PI * 2); g.fill();
  // 轨道
  g.strokeStyle = P.cardStroke; g.lineWidth = sw; g.lineCap = "round";
  g.beginPath(); g.arc(cx, cy, R, 0, Math.PI * 2); g.stroke();
  // 进度
  const tier = dailyTier(acc);
  const grad = g.createLinearGradient(cx - R, cy - R, cx + R, cy + R);
  grad.addColorStop(0, tier.color); grad.addColorStop(1, P.big);
  g.strokeStyle = grad;
  g.beginPath(); g.arc(cx, cy, R, -Math.PI / 2, -Math.PI / 2 + (Math.PI * 2 * acc) / 100); g.stroke();
  // 环内文字
  g.textAlign = "center";
  g.fillStyle = P.big; g.font = "700 116px Georgia,'Noto Serif SC',serif";
  g.fillText(`${acc}%`, cx, cy - 14);
  g.fillStyle = P.sub; g.font = "500 26px 'PingFang SC',sans-serif";
  g.fillText("正确率", cx, cy + 66);

  // —— 战绩与等级徽章 ——
  g.fillStyle = P.title; g.font = "700 34px 'PingFang SC',sans-serif";
  g.fillText(`答对 ${m.score} / ${m.total} 题`, cx, 700);
  const badge = `${tier.tier} 级 · ${tier.label}`;
  g.font = "700 26px 'PingFang SC',sans-serif";
  const bw = g.measureText(badge).width + 56;
  g.fillStyle = tier.color; roundRect(g, (W - bw) / 2, 738, bw, 60, 30); g.fill();
  g.fillStyle = "#10131f"; g.fillText(badge, cx, 769);

  // —— 答题网格（自动换行，居中）——
  const detail = m.detail || [];
  const cell = 50, gap = 12, perRow = 11;
  const rows = Math.ceil(detail.length / perRow);
  let gy = 838;
  for (let r = 0; r < rows; r++) {
    const slice = detail.slice(r * perRow, (r + 1) * perRow);
    const rw = slice.length * cell + Math.max(0, slice.length - 1) * gap;
    let gx = (W - rw) / 2;
    for (const d of slice) {
      g.fillStyle = d.right ? P.good : P.bad;
      roundRect(g, gx, gy, cell, cell, 12); g.fill();
      gx += cell + gap;
    }
    gy += cell + gap;
  }

  // —— 连续打卡 ——
  if (m.streak > 0) {
    g.fillStyle = P.num; g.font = "600 28px 'PingFang SC',sans-serif"; g.textAlign = "center";
    g.fillText(`🔥 每日挑战连续 ${m.streak} 天`, cx, 980);
  }

  // —— 页脚 ——
  g.fillStyle = P.dim; g.font = "500 22px 'PingFang SC',sans-serif"; g.textAlign = "center";
  g.fillText("mi2.cc.cd · 听清每一个词，写下每一句", cx, H - 64);
}

function savePoster() {
  const off = document.createElement("canvas");
  paintDailyPoster(off, {
    day: result.value?.day || day.value,
    listTitle: listTitle.value,
    score: doneScore.value,
    total: doneTotal.value,
    streak: result.value?.profile?.daily_streak || 0,
    detail: result.value?.detail || picks.value.map((p) => ({ right: p.picked === p.id })),
  }, 2, PALETTES[currentTheme()]);
  if (!off.width) return;
  const a = document.createElement("a");
  a.download = `每日挑战-${result.value?.day || day.value}.png`;
  a.href = off.toDataURL("image/png");
  a.click();
}
</script>

<template>
  <div v-if="error && !questions.length" class="empty" role="alert"><p>{{ error }}</p><button class="btn primary" @click="load">重试</button></div>
  <div v-else-if="loading" class="empty">加载中…</div>
  <div v-else-if="!questions.length" class="empty">没有可出题的词</div>

  <div v-else-if="stage === 'play' && q" class="quiz-page daily-page">
    <div class="practice-top">
      <span class="progress-line">{{ progress }} · 得分 {{ picks.filter((p) => p.picked === p.id).length }}</span>
      <span class="badge mode-badge">
        <select v-model="list" class="daily-list-select" aria-label="选择词库"
                :disabled="picks.length > 0" @change="switchList">
          <option v-for="l in wordLists" :key="l.key" :value="l.key">{{ l.title }}</option>
        </select>
        <em class="daily-kind-tag">{{ kindLabel }}</em>
      </span>
    </div>
    <div class="practice-card">
      <div id="answer-line" aria-live="polite">
        <span v-if="graded && lastRight" style="color:var(--green);">✔ 答对了！</span>
        <span v-else-if="graded" style="color:var(--red);">
          ✗ 正确答案：<span class="show-word">{{ q.text }}</span>
        </span>
      </div>
      <div v-if="q.kind === 'zh_en'" class="quiz-prompt">
        {{ q.options.find((o) => o.id === q.id)?.meaning || '（该词暂无释义）' }}
      </div>
      <div v-else class="quiz-play">
        <button class="btn primary big" aria-label="播放单词发音" @click="play">🔊</button>
      </div>
      <div class="hint">{{ HINTS[q.kind] }}</div>
      <div class="quiz-options">
        <button v-for="(o, i) in q.options" :key="o.id" class="quiz-option"
          :style="{ '--qi': i }"
          :class="{ picked: picked === o.id, right: graded && o.id === q.id,
                    wrong: graded && picked === o.id && o.id !== q.id }"
          :disabled="graded" :aria-label="'选项 ' + (i + 1) + '：' + (q.kind === 'en_zh' ? o.meaning : o.text)"
          @click="answer(o)">
          <b>{{ q.kind === 'en_zh' ? (o.meaning || '（无释义）') : o.text }}</b>
          <small v-if="graded">{{ q.kind === 'en_zh' ? o.text : o.meaning }}</small>
        </button>
      </div>
      <div class="controls" v-if="graded && !lastRight">
        <button class="btn primary big" @click="next">{{ qi + 1 >= questions.length ? '查看结果' : '下一题 →' }}</button>
      </div>
    </div>
  </div>

  <div v-else class="empty daily-done">
    <div class="daily-done-title">
      {{ completed ? '今日挑战完成 🎉' : replaying ? '练习局完成' : '本轮完成' }}
      <small v-if="replaying">换一批词练手 · 不计成绩</small>
    </div>
    <p class="done-score-line">答对 {{ doneScore }} / {{ doneTotal }} · 正确率 {{ doneAcc }}%</p>
    <div class="daily-grid" aria-label="今日答题网格">
      <span v-for="(c, i) in gridCells" :key="i" class="grid-cell"
            :class="c === '🟩' ? 'right' : 'wrong'" :style="{ '--ci': i }"></span>
    </div>
    <p v-if="profile && !replaying" class="daily-xp-line">
      词力 <b>{{ profile.title }}</b> Lv.{{ profile.level }}
      <template v-if="profile.daily_streak"> · 每日挑战连续 <b>{{ profile.daily_streak }}</b> 天</template>
    </p>
    <template v-if="!replaying">
      <pre class="share-box" aria-label="分享文本">{{ shareText }}</pre>
      <div class="controls share-actions">
        <button class="btn primary big" @click="copyShare">{{ copied ? '已复制 ✓' : '复制文本' }}</button>
        <button class="btn ghost big" @click="savePoster">保存海报 PNG</button>
      </div>
    </template>
    <div class="controls more-actions">
      <button class="btn primary sm" @click="startReplay">再玩一次（新词 · 不计分）</button>
      <a class="btn ghost sm" href="#/tree">看看我的小树 →</a>
    </div>
  </div>
</template>

<style scoped>
/* 词库切换的配色在全局 styles.css（跟随主题胶囊），这里只留题型标签 */
.daily-kind-tag { font-style: normal; color: inherit; opacity: .75; margin-left: 8px; }
</style>
