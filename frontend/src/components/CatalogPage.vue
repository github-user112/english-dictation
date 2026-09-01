<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, Settings } from "../lib/core";
import { Profile, refreshProfile } from "../lib/profile";

const lists = ref([]);
const goals = ref({});
const goalEditing = ref("");
const goalDays = ref(30);
const today = ref(null);
const active = ref([]);
const lessons = ref({});
const lessonErrors = ref({});
const lessonLoading = ref({});
const selectedLesson = ref({});
const loading = ref(true);
const error = ref("");
const customs = ref([]);
let mounted = true;
const words = computed(() => lists.value.filter((l) => l.type === "words"));
const sents = computed(() => lists.value.filter((l) => l.type === "sentences"));

onMounted(load);
onUnmounted(() => { mounted = false; });

async function load() {
  loading.value = true;
  error.value = "";
  lessons.value = {};
  lessonErrors.value = {};
  lessonLoading.value = {};
  try {
    const d = await api("/lists");
    lists.value = d.lists || [];
    today.value = d.today;
    active.value = d.active_sessions || [];
  } catch (err) {
    lists.value = [];
    active.value = [];
    error.value = err.message || "素材库加载失败";
    loading.value = false;
    return;
  }
  // 先渲染页面（词汇/句子卡片立即可见），课程数据异步加载，不阻塞首屏
  loading.value = false;
  loadLessons();
  loadCustoms();
  loadGoals();
  // 每日横幅状态强刷：从每日挑战页回来后能立刻看到"已完成"
  refreshProfile(true).catch(() => {});
}

async function loadGoals() {
  try {
    const d = await api("/goal");
    if (mounted) goals.value = d.goals || {};
  } catch { /* 游客或旧后端无此接口时静默 */ }
}

async function saveGoal(l) {
  const days = Number(goalDays.value);
  if (!Number.isInteger(days) || days < 1 || days > 365) {
    alert("天数需为 1-365 的整数");
    return;
  }
  try {
    const d = await api("/goal", { method: "POST", body: JSON.stringify({ list: l.key, target_days: days }) });
    goals.value = { ...goals.value, [l.key]: d.goal };
    goalEditing.value = "";
  } catch (err) {
    alert(err.message || "保存失败");
  }
}

async function delGoal(l) {
  if (!confirm(`取消「${l.title}」的学习计划？已背进度保留。`)) return;
  try {
    await api(`/goal?list=${l.key}`, { method: "DELETE" });
    const next = { ...goals.value };
    delete next[l.key];
    goals.value = next;
  } catch (err) {
    alert(err.message || "删除失败");
  }
}

function goalPct(g) { return g.total ? Math.min(100, Math.round(g.memorized / g.total * 100)) : 0; }

async function loadCustoms() {
  try {
    const d = await api("/materials/custom");
    if (mounted) customs.value = d.items || [];
  } catch { /* 游客/旧接口无此数据时静默 */ }
}

async function playCustom(m) {
  try {
    const d = await api(`/materials/custom/${m.id}`);
    sessionStorage.setItem("dict_custom", JSON.stringify(d.sentences));
    sessionStorage.setItem("dict_custom_label", `《${d.title}》`);
    location.hash = "#/sentence";
  } catch (err) {
    alert(err.message || "文章加载失败");
  }
}

async function delCustom(m) {
  if (!confirm(`删除《${m.title}》？`)) return;
  try {
    await api(`/materials/custom/${m.id}`, { method: "DELETE" });
    customs.value = customs.value.filter((x) => x.id !== m.id);
  } catch (err) {
    alert(err.message || "删除失败");
  }
}

async function loadLessons() {
  const lessonLists = lists.value.filter((l) => l.lesson_count);
  for (const l of lessonLists) {
    lessonLoading.value[l.key] = true;
    api(`/lessons?list=${l.key}`).then((res) => {
      if (!mounted) return;
      if (res?.lessons?.length) {
        lessons.value[l.key] = res.lessons;
        const saved = Number(localStorage.getItem(`dict_lesson_${l.key}`)) || 0;
        selectedLesson.value[l.key] = res.lessons.find((x) => x.lesson === saved)?.lesson
          || res.lessons[0].lesson;
      } else {
        lessonErrors.value[l.key] = "暂无可用课程";
      }
    }).catch(() => {
      if (mounted) lessonErrors.value[l.key] = "课程加载失败，请刷新重试";
    }).finally(() => {
      if (mounted) lessonLoading.value[l.key] = false;
    });
  }
}

function pickLesson(key, ev) {
  selectedLesson.value[key] = Number(ev.target.value);
  localStorage.setItem(`dict_lesson_${key}`, String(ev.target.value));
}
function activeLesson(l) {
  const sel = selectedLesson.value[l.key];
  const mode = Settings.get().practiceMode;
  return active.value.find((s) => s.list === l.key && s.lesson === sel && s.mode === mode);
}
function lessonLabel(l, x) {
  const done = x.known + x.learning;
  const mode = Settings.get().practiceMode;
  const sess = active.value.find((s) => s.list === l.key && s.lesson === x.lesson && s.mode === mode);
  return `第 ${x.lesson} 课 · ${x.total} 句 · ${done ? `打过 ${done}` : "未开始"}${sess ? " · 继续→" : ""}`;
}

function start(l) {
  if (l.lesson_count && !selectedLesson.value[l.key]) return;
  const p = new URLSearchParams({ list: l.key, mode: Settings.get().practiceMode });
  if (l.lesson_count) p.set("lesson", selectedLesson.value[l.key]);
  location.hash = `#/${l.type === "words" ? "word" : "sentence"}?${p}`;
}
function resume(s) {
  const p = new URLSearchParams({ list: s.list, mode: s.mode, scope: s.scope || "all" });
  if (s.lesson) p.set("lesson", s.lesson);
  location.hash = `#/${lists.value.find((l) => l.key === s.list)?.type === "words" ? "word" : "sentence"}?${p}`;
}
function memorize(key) {
  const g = goals.value[key];
  // 有学习计划时按当日应背新词量开局（后端 n 上限 100），没有则走默认批量
  const n = g && !g.done ? Math.min(g.daily_new, 100) : 0;
  window.location.hash = `#/memorize?list=${key}` + (n ? `&n=${n}` : "");
}
function startQuiz(l) { window.location.hash = `#/quiz?list=${l.key}`; }
function startSprint(l) { window.location.hash = `#/sprint?list=${l.key}`; }
/* 听音排句：听句子把词块点回正确顺序 */
function startArrange(l) {
  const p = new URLSearchParams({ list: l.key });
  if (l.lesson_count && selectedLesson.value[l.key]) p.set("lesson", selectedLesson.value[l.key]);
  location.hash = `#/arrange?${p}`;
}
function title(key) { return lists.value.find((l) => l.key === key)?.title || key; }
</script>

<template>
  <div v-if="loading" class="empty">加载中…</div>
  <div v-else-if="error" class="empty" role="alert">
    <p>{{ error }}</p>
    <button class="btn primary" @click="load">重试</button>
  </div>
  <div v-else class="catalog-page">
    <section class="catalog-hero">
      <div>
        <span class="eyebrow">DAILY LISTENING PRACTICE</span>
        <h1>听清每一句，<br><em>写下每个词。</em></h1>
        <p>从熟悉声音开始，把英语变成一种自然反应。</p>
      </div>
      <div v-if="today" class="hero-stats" aria-label="今日学习数据">
        <div><b>{{ today.new + today.review }}</b><span>今日练习</span></div>
        <div><b>{{ today.right }}</b><span>首答正确</span></div>
        <div><b>{{ today.memorize_right }}</b><span>背诵答对</span></div>
      </div>
    </section>
    <!-- 每日挑战横幅：每天一个固定回来的理由 -->
    <a v-if="Profile.ready" class="daily-banner" href="#/daily"
       :aria-label="Profile.dailyDoneToday ? '每日挑战今日已完成' : '开始每日挑战'">
      <span class="db-icon" aria-hidden="true">🗓️</span>
      <span class="db-body">
        <b>今日词力 · 每日挑战</b>
        <small>{{ Profile.dailyDoneToday
          ? `今天已完成 · 连续 ${Profile.dailyStreak} 天，重玩不计分`
          : "10 道全站同题 · 完成即给小树浇水" }}</small>
      </span>
      <em class="db-go">{{ Profile.dailyDoneToday ? "已打卡 ✓" : "去挑战 →" }}</em>
    </a>
    <!-- 趣味小游戏入口：英中配对消消乐 -->
    <a class="daily-banner fun-banner" href="#/match" aria-label="开始英中配对消消乐">
      <span class="db-icon" aria-hidden="true">🀄</span>
      <span class="db-body">
        <b>英中配对消消乐</b>
        <small>词与释义翻牌配对 · 首配即中拿满经验</small>
      </span>
      <em class="db-go">去玩一局 →</em>
    </a>
    <template v-if="active.length">
      <div class="section-title"><span>继续学习</span><small>从上次停下的地方开始</small></div>
      <div class="resume-list">
        <button v-for="s in active" :key="s.id" class="resume-card" :aria-label="'继续：' + title(s.list) + '，进度 ' + (s.total - s.pending) + ' / ' + s.total" @click="resume(s)">
          <span><b>{{ title(s.list) }}</b><small>{{ s.mode === 'pure' ? '纯听写' : s.mode === 'follow' ? '跟打' : '辅助听写' }}<template v-if="s.lesson"> · 第 {{ s.lesson }} 课</template></small></span>
          <span>{{ s.total - s.pending }}/{{ s.total }} · 继续 →</span>
        </button>
      </div>
    </template>

    <div class="section-title"><span>词汇听打</span><small>先背诵，再通过听写巩固</small></div>
    <div class="card-grid word-grid">
      <div v-for="l in words" :key="l.key" class="card" :aria-label="l.title + ' 词汇听打，共 ' + l.total + ' 个'">
        <div class="name">{{ l.title }}<span class="badge type" aria-hidden="true">单词</span><span v-if="l.audio_done >= l.total" class="badge audio" aria-label="音频已就绪">✓ 音频</span></div>
        <div class="meta">共 {{ l.total }} · 已背 {{ l.memorized }} · 掌握 {{ l.known }} · 未开始 {{ l.new }}</div>
        <div class="progress" role="progressbar" :aria-valuenow="(l.total ? l.known : 0)" :aria-valuemax="l.total" :aria-label="'掌握进度：' + (l.total ? Math.round(l.known / l.total * 100) : 0) + '%'"><div :style="{width: (l.total ? l.known / l.total * 100 : 0) + '%'}"></div></div>
        <!-- 学习计划：N 天背完的进度环 + 每日目标 -->
        <div v-if="goalEditing === l.key" class="goal-row">
          <span class="goal-text"><b>N 天背完：</b></span>
          <input v-model.number="goalDays" class="goal-input" type="number" min="1" max="365" aria-label="目标天数" @keyup.enter="saveGoal(l)">
          <button class="btn primary sm" @click="saveGoal(l)">确定</button>
          <button class="btn ghost sm" @click="goalEditing = ''">取消</button>
        </div>
        <div v-else-if="goals[l.key]" class="goal-row">
          <svg class="goal-ring" viewBox="0 0 36 36" role="img" :aria-label="'已背 ' + goalPct(goals[l.key]) + '%'">
            <circle class="ring-bg" cx="18" cy="18" r="15.9155" pathLength="100"/>
            <circle class="ring-fg" cx="18" cy="18" r="15.9155" pathLength="100" :stroke-dasharray="goalPct(goals[l.key]) + ' 100'"/>
            <text x="18" y="21.5" class="ring-text">{{ goalPct(goals[l.key]) }}%</text>
          </svg>
          <span class="goal-text">
            <b>{{ goals[l.key].done ? "已完成 🎉" : goals[l.key].target_days + " 天计划" }}</b>
            <small>{{ goals[l.key].done
              ? `共 ${goals[l.key].total} 词全部背完`
              : `每天 ${goals[l.key].daily_new} 词 · 剩 ${goals[l.key].days_left} 天 · 今日已背 ${goals[l.key].today_done}` }}</small>
          </span>
          <button class="btn ghost sm" aria-label="修改计划" @click="goalEditing = l.key; goalDays = goals[l.key].target_days">✎</button>
          <button class="btn ghost sm" aria-label="取消计划" @click="delGoal(l)">✕</button>
        </div>
        <div class="card-actions">
          <button v-if="!goals[l.key] && goalEditing !== l.key" class="btn ghost sm" aria-label="设定学习计划" @click="goalEditing = l.key; goalDays = 30">🎯 定目标</button>
          <button class="btn ghost sm" aria-label="背单词" @click="memorize(l.key)">📖 背单词</button>
          <button class="btn ghost sm" aria-label="听音选词" @click="startQuiz(l)">🎧 选词</button>
          <button class="btn ghost sm" aria-label="限时冲刺" @click="startSprint(l)">⚡ 冲刺</button>
          <button class="btn primary sm" aria-label="开始听打" @click="start(l)">👂 开始听打</button>
        </div>
      </div>
    </div>

    <div class="section-title"><span>句子听写</span><small>在完整语境里训练听力</small></div>
    <div class="card-grid sentence-grid">
      <div v-for="l in sents" :key="l.key" class="card" :aria-label="l.title + ' 句子听写，共 ' + l.total + ' 个'">
        <div class="name">{{ l.title }}<span class="badge type" aria-hidden="true">句子</span><span v-if="l.audio_done >= l.total" class="badge audio" aria-label="音频已就绪">✓ 音频</span></div>
        <div class="meta">共 {{ l.total }} · 掌握 {{ l.known }} · 未开始 {{ l.new }}</div>
        <div class="progress" role="progressbar" :aria-valuenow="l.known" :aria-valuemax="l.total" :aria-label="'掌握进度：' + (l.total ? Math.round(l.known / l.total * 100) : 0) + '%'"><div :style="{width: (l.total ? l.known / l.total * 100 : 0) + '%'}"></div></div>
        <select v-if="l.lesson_count && lessons[l.key]" v-model.number="selectedLesson[l.key]" class="lesson-select"
                aria-label="选择课程" @change="pickLesson(l.key, $event)">
          <option v-for="x in lessons[l.key]" :key="x.lesson" :value="x.lesson">{{ lessonLabel(l, x) }}</option>
        </select>
        <div v-else-if="lessonErrors[l.key]" class="meta" role="alert">{{ lessonErrors[l.key] }}</div>
        <div v-else-if="lessonLoading[l.key]" class="meta">课程加载中…</div>
        <div class="card-actions">
          <button class="btn ghost sm" aria-label="听音排句" @click="startArrange(l)">🧩 排句</button>
          <button class="btn primary sm" :disabled="Boolean(l.lesson_count && !selectedLesson[l.key])" :aria-label="(activeLesson(l) ? '继续第 ' + selectedLesson[l.key] + ' 课' : l.lesson_count ? '按课学习' : '开始听写')" @click="start(l)">👂 {{ activeLesson(l) ? `继续第 ${selectedLesson[l.key]} 课` : l.lesson_count ? '按课学习' : '开始听写' }}</button>
        </div>
      </div>
    </div>
    <div class="section-title"><span>我的文章</span><small>粘贴任意英文，自动分句变成听写素材 · <a href="#/import" style="color:var(--accent);font-weight:700;">＋ 导入文章</a></small></div>
    <div v-if="customs.length" class="resume-list">
      <div v-for="m in customs" :key="m.id" class="resume-card" style="cursor:default;">
        <span class="t"><b>📄 {{ m.title }}</b><small>{{ m.count }} 句 · {{ m.created_at.slice(0, 10) }}</small></span>
        <button class="btn ghost sm" aria-label="删除文章" @click="delCustom(m)">删除</button>
        <button class="btn primary sm" aria-label="开始听写这篇文章" @click="playCustom(m)">👂 开始听写</button>
      </div>
    </div>
    <div v-else class="empty" style="padding:26px;">还没有导入过文章 —— 点右上「＋ 导入文章」试试粘贴一段新闻。</div>

    <div v-if="today" class="section-title today-summary">今日：新词 {{ today.new }} · 复习 {{ today.review }} · 背单词对 {{ today.memorize_right }} / 错 {{ today.memorize_wrong }} · 听打首答对 {{ today.right }} / 错 {{ today.wrong }}</div>
  </div>
</template>
