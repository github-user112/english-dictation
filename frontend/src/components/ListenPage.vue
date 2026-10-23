<script setup>
/* 按课听录音：整课原声连续播放 + 逐句高亮，只听不判分、不记学习记录。
   file 模式播整课原声（按时间轴高亮/跳转）；sentences 模式逐句串播（口语900句等无时间轴素材）。 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { api, audioEl, audioPlaying, ensureAudio, Settings, stopAudio } from "../lib/core";

const props = defineProps({ params: { type: Object, default: null } });

const OPTS_KEY = "dict_listen_opts";
const CHAIN_KEY = "dict_listen_chain";   // 跨页跳课连播的 sessionStorage 令牌

const lists = ref([]);           // 有课次的句子素材
const list = ref("");
const lessons = ref([]);
const lesson = ref(null);
const items = ref([]);
const mode = ref("file");
const fileUrl = ref("");
const segStart = ref(0);
const segEnd = ref(0);
const loading = ref(true);
const pageError = ref("");
const activeIdx = ref(-1);
const sentIdx = ref(0);          // sentences 模式当前句
const now = ref(0);               // audioEl.currentTime 镜像，驱动进度条
const speed = ref(Settings.get().speed);
const opts = loadOpts();
const showEn = ref(opts.showEn);
const showZh = ref(opts.showZh);
const loopOne = ref(opts.loopOne);
const loopLesson = ref(opts.loopLesson);
const autoNext = ref(opts.autoNext);
if (loopLesson.value) { loopOne.value = false; autoNext.value = false; }   // 旧配置里的互斥归一
const listEl = ref(null);
let mounted = true;
let loadedSrc = "";               // 当前 audioEl 已装载的 src（避免重复 load）
let playSeq = 0;                  // 播放令牌：整课/换句操作用来作废还在加载的单句音频

function loadOpts() {
  try { return { showEn: true, showZh: true, loopOne: false, loopLesson: false, autoNext: false,
                ...JSON.parse(localStorage.getItem(OPTS_KEY) || "{}") }; }
  catch { return { showEn: true, showZh: true, loopOne: false, loopLesson: false, autoNext: false }; }
}
function saveOpts() {
  localStorage.setItem(OPTS_KEY, JSON.stringify({
    showEn: showEn.value, showZh: showZh.value,
    loopOne: loopOne.value, loopLesson: loopLesson.value, autoNext: autoNext.value,
  }));
}
function toggleLoopOne() {
  loopOne.value = !loopOne.value;
  if (loopOne.value) loopLesson.value = false;   // 单句循环与整课循环互斥
  saveOpts();
}
function toggleLoopLesson() {
  loopLesson.value = !loopLesson.value;
  if (loopLesson.value) { loopOne.value = false; autoNext.value = false; }
  saveOpts();
}
function toggleAutoNext() {
  autoNext.value = !autoNext.value;
  if (autoNext.value) loopLesson.value = false;
  saveOpts();
}

const playing = computed(() => audioPlaying.value);
const lessonPos = computed(() => lessons.value.findIndex((x) => x.lesson === lesson.value));
const prevLessonNo = computed(() => lessonPos.value > 0 ? lessons.value[lessonPos.value - 1].lesson : null);
const nextLessonNo = computed(() => lessonPos.value >= 0 && lessonPos.value < lessons.value.length - 1
  ? lessons.value[lessonPos.value + 1].lesson : null);
const speedLabel = computed(() => speed.value.toFixed(2).replace(/0$/, "").replace(/\.0$/, "") + "x");
const pct = computed(() => {
  if (mode.value !== "file" || segEnd.value <= segStart.value) return 0;
  return Math.min(100, Math.max(0, (now.value - segStart.value) / (segEnd.value - segStart.value) * 100));
});
const sentProg = computed(() => items.value.length
  ? Math.min(100, (sentIdx.value + 1) / items.value.length * 100) : 0);

function fmt(t) {
  t = Math.max(0, Math.floor(t));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}
const curTime = computed(() => fmt(Math.max(0, now.value - segStart.value)));
const totTime = computed(() => fmt(segEnd.value - segStart.value));

onMounted(async () => {
  audioEl.ontimeupdate = onTime;
  audioEl.onended = onEnded;
  audioEl.addEventListener("loadedmetadata", onLoadedMetadata);
  try {
    const d = await api("/lists");
    if (!mounted) return;
    lists.value = (d.lists || []).filter((l) => l.type === "sentences" && l.lesson_count);
    if (!lists.value.length) throw new Error("没有可按课听录音的素材");
    const want = props.params?.get("list") || localStorage.getItem("dict_listen_list");
    list.value = lists.value.some((l) => l.key === want) ? want : lists.value[0].key;
    await loadLessons();
    if (!mounted) return;
    const wantLesson = Number(props.params?.get("lesson") || localStorage.getItem("dict_listen_lesson"));
    lesson.value = lessons.value.some((x) => x.lesson === wantLesson) ? wantLesson : lessons.value[0].lesson;
    await loadLesson();
    if (!mounted) return;
    // 上一课播完自动跳来时延续连播；标记带课号，避免遗留标记让别的课误自动播放
    if (sessionStorage.getItem(CHAIN_KEY) === String(lesson.value)) {
      sessionStorage.removeItem(CHAIN_KEY);
      play();
    }
  } catch (err) {
    if (mounted) pageError.value = err.message || "加载失败";
  } finally {
    if (mounted) loading.value = false;
  }
});

onUnmounted(() => {
  mounted = false;
  audioEl.ontimeupdate = null;
  audioEl.onended = null;
  audioEl.removeEventListener("loadedmetadata", onLoadedMetadata);
  stopAudio();
});

async function loadLessons() {
  const d = await api(`/lessons?list=${encodeURIComponent(list.value)}`);
  if (!mounted) return;
  lessons.value = d.lessons || [];
}

async function loadLesson() {
  if (!mounted) return;
  stopPlayback();
  const d = await api(`/listen/session?list=${encodeURIComponent(list.value)}&lesson=${lesson.value}`);
  if (!mounted) return;
  items.value = d.items || [];
  mode.value = d.mode || "sentences";
  fileUrl.value = d.file || "";
  segStart.value = d.start || 0;
  segEnd.value = d.end || 0;
  now.value = segStart.value;
  activeIdx.value = -1;
  sentIdx.value = 0;
  localStorage.setItem("dict_listen_list", list.value);
  localStorage.setItem("dict_listen_lesson", String(lesson.value));
}

function stopPlayback() {
  playSeq++;                       // 作废还在等 TTS/HEAD 的单句加载
  audioEl.pause();
  audioEl.removeAttribute?.("src");
  audioEl.load?.();
  loadedSrc = "";
  pendingSeek = null;
}

/* 整课原声需要先装载再 seek；同页连续操作不重复 load */
function ensureFile() {
  if (loadedSrc !== fileUrl.value) {
    audioEl.src = fileUrl.value;
    audioEl.load();
    loadedSrc = fileUrl.value;
  }
}

let pendingSeek = null;
/* 刚换 src 时元数据未就绪，直接赋 currentTime 会被浏览器丢弃（整课共享文件会从头播到别的课） */
function seekTo(t) {
  if (audioEl.readyState >= 1) audioEl.currentTime = t;
  else pendingSeek = t;
}
function onLoadedMetadata() {
  if (pendingSeek != null) {
    const t = pendingSeek;
    pendingSeek = null;
    audioEl.currentTime = t;
  }
}

function play() {
  if (!items.value.length) return;   // 素材未就绪（加载中/出错）
  if (mode.value !== "file") { playSentence(sentIdx.value); return; }
  playSeq++;                        // 用户要听整课：作废还没加载完的单句音频
  audioEl.playbackRate = speed.value;
  if (loadedSrc === fileUrl.value) {
    if (audioEl.currentTime < segStart.value || audioEl.currentTime >= segEnd.value - 0.05) {
      seekTo(segStart.value);
    }
  } else {
    // loadedSrc 不是整课文件：可能是刚点过无时间轴句子的单句音频，
    // 必须换回整课原声，否则按播放只会重播那句单句
    ensureFile();
    seekTo(resumePoint());
  }
  audioEl.play().catch(() => {});
}

/* 从单句音频切回整课时，尽量接着上次听到的位置；课末/未开始则从头 */
function resumePoint() {
  const t = now.value;
  return t > segStart.value && t < segEnd.value - 0.05 ? t : segStart.value;
}

/* 单句音频：换 src 后浏览器自己归零，显式归零只为覆盖"未换 src 重播"的情况 */
async function playSentence(i) {
  const it = items.value[i];
  if (!it) return;
  const seq = ++playSeq;
  sentIdx.value = i;
  activeIdx.value = i;
  const url = await ensureAudio(it);   // 文件缺失时懒生成 TTS，否则点了没声
  if (!mounted || seq !== playSeq || sentIdx.value !== i) return;   // 等待期间已离开/换整课/切句
  pendingSeek = null;                  // 丢弃整课音频尚未应用的定位，别带到单句上
  loadedSrc = url;
  audioEl.src = url;
  audioEl.playbackRate = speed.value;
  if (audioEl.readyState >= 1) audioEl.currentTime = 0;
  audioEl.play().catch(() => {});
}

function toggle() { audioEl.paused ? play() : audioEl.pause(); }

/* 逐句串播结束：单句循环重播，否则下一句；到头按「本课循环」回首句，
   再按「自动下一课」跳课。file 模式下 loadedSrc 不是整课文件，说明播的是
   无时间轴句子的单句音频，播完直接停。 */
function onEnded() {
  if (mode.value === "file") {
    if (loadedSrc === fileUrl.value) finishLesson();
    return;
  }
  if (loopOne.value) { playSentence(sentIdx.value); return; }
  if (sentIdx.value + 1 < items.value.length) { playSentence(sentIdx.value + 1); return; }
  if (loopLesson.value) { playSentence(0); return; }
  if (autoNext.value && nextLessonNo.value != null) goLessonAuto(nextLessonNo.value);
}

function onTime() {
  if (mode.value !== "file" || loadedSrc !== fileUrl.value) return;   // 单句音频不驱动课进度
  now.value = audioEl.currentTime;
  const t = audioEl.currentTime;
  if (loopOne.value && activeIdx.value >= 0) {
    const it = items.value[activeIdx.value];
    if (it && it.end != null && t >= it.end) { seekTo(it.start); return; }
  }
  if (t >= segEnd.value) { finishLesson(); return; }
  const idx = findActive(t);
  if (idx !== activeIdx.value) activeIdx.value = idx;
}

function findActive(t) {
  let idx = -1;
  for (let i = 0; i < items.value.length; i++) {
    const s = items.value[i].start;
    if (s == null) continue;
    if (s <= t + 0.05) idx = i;
    else break;
  }
  return idx;
}

/* 课末收尾：开了本课循环就回首句继续，否则暂停（自动下一课再跳课） */
function finishLesson() {
  if (loopLesson.value) { restartLesson(); return; }
  audioEl.pause();
  if (autoNext.value && nextLessonNo.value != null) goLessonAuto(nextLessonNo.value);
}

/* 本课循环：整课原声回到本课起点继续播，进度条/高亮立即复位 */
function restartLesson() {
  playSeq++;                        // 作废还在加载的单句音频
  ensureFile();
  seekTo(segStart.value);
  now.value = segStart.value;
  activeIdx.value = findActive(segStart.value);   // 高亮立刻跳回本课第一句
  audioEl.playbackRate = speed.value;
  audioEl.play().catch(() => {});
}

function jump(i) {
  const it = items.value[i];
  if (!it) return;
  if (mode.value === "file" && it.start != null) {
    playSeq++;                       // 跳句要听整课：作废还在加载的单句音频
    ensureFile();
    seekTo(it.start);
    audioEl.playbackRate = speed.value;
    if (audioEl.paused) audioEl.play().catch(() => {});
  } else if (mode.value === "file") {
    playSentence(i);   // 个别缺时间轴的句子：用它的逐句音频单独播
  } else {
    playSentence(i);
  }
}

function seek(e) {
  const rect = e.currentTarget.getBoundingClientRect();
  const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
  if (mode.value === "file") {
    playSeq++;                       // 拖进度条回到整课：作废还在加载的单句音频
    ensureFile();
    const t = segStart.value + ratio * (segEnd.value - segStart.value);
    seekTo(t);
    now.value = t;
  } else if (items.value.length) {
    playSentence(Math.min(items.value.length - 1, Math.floor(ratio * items.value.length)));
  }
}

function cycleSpeed() {
  const next = speed.value === 0.75 ? 1.0 : speed.value === 1.0 ? 1.25 : 0.75;
  speed.value = next;
  Settings.set({ speed: next });
  audioEl.playbackRate = next;
}

function switchBook() {
  const p = new URLSearchParams({ list: list.value });
  location.hash = `#/listen?${p}`;
}
function switchLesson() {
  const p = new URLSearchParams({ list: list.value, lesson: lesson.value });
  location.hash = `#/listen?${p}`;
}
function goLesson(no) { lesson.value = no; switchLesson(); }
function goLessonAuto(no) { sessionStorage.setItem(CHAIN_KEY, String(no)); goLesson(no); }
function goLists() { location.hash = "#/lists"; }

function onKey(e) {
  if (e.target.closest?.("button, select, input, textarea")) return;
  if (e.code === "Space") { e.preventDefault(); toggle(); }
  else if (e.code === "ArrowRight") {
    const i = mode.value === "file" ? (activeIdx.value < 0 ? 0 : activeIdx.value + 1) : sentIdx.value + 1;
    if (i < items.value.length) jump(i);
  } else if (e.code === "ArrowLeft") {
    const i = mode.value === "file" ? (activeIdx.value < 0 ? 0 : activeIdx.value - 1) : sentIdx.value - 1;
    if (i >= 0) jump(i);
  }
}

watch(activeIdx, async () => {
  await nextTick();
  listEl.value?.querySelector(".sent-row.active")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
});

document.addEventListener("keydown", onKey);
onUnmounted(() => document.removeEventListener("keydown", onKey));
</script>

<template>
  <div v-if="loading" class="empty loading"><span class="spin" aria-hidden="true"></span><span class="load-text">加载中…</span></div>
  <div v-else-if="pageError" class="empty" role="alert">
    <span class="emoji" aria-hidden="true">🎧</span>
    <h3>{{ pageError }}</h3>
    <button class="btn primary" @click="goLists">返回素材库</button>
  </div>
  <div v-else class="listen-page">
    <div class="listen-top">
      <select v-model="list" class="lp-select" aria-label="选择教材" @change="switchBook">
        <option v-for="l in lists" :key="l.key" :value="l.key">{{ l.title }}</option>
      </select>
      <div class="lp-lesson-nav">
        <button class="btn ghost sm" :disabled="prevLessonNo == null"
                :aria-label="'上一课，第 ' + prevLessonNo + ' 课'" @click="goLesson(prevLessonNo)">‹</button>
        <select v-model.number="lesson" class="lp-select" aria-label="选择课程" @change="switchLesson">
          <option v-for="x in lessons" :key="x.lesson" :value="x.lesson">第 {{ x.lesson }} 课</option>
        </select>
        <button class="btn ghost sm" :disabled="nextLessonNo == null"
                :aria-label="'下一课，第 ' + nextLessonNo + ' 课'" @click="goLesson(nextLessonNo)">›</button>
      </div>
    </div>

    <div class="player-card">
      <div class="player-bar" aria-hidden="true"></div>
      <div class="player-main">
        <button class="play-btn" :aria-label="playing ? '暂停' : '播放'" @click="toggle">
          <span v-if="playing" class="ic" aria-hidden="true">⏸</span>
          <span v-else class="ic" aria-hidden="true">▶</span>
        </button>
        <div class="player-mid">
          <div v-if="mode === 'file'" class="track" role="progressbar"
               :aria-valuenow="Math.round(pct)" aria-valuemin="0" aria-valuemax="100"
               aria-label="'课程进度，已播放 ' + Math.round(pct) + '%，点击可跳转'" @click="seek">
            <div class="track-fill" :style="{ width: pct + '%' }"></div>
          </div>
          <div v-else class="track" role="progressbar" :aria-valuenow="Math.round(sentProg)"
               aria-valuemin="0" aria-valuemax="100" aria-label="句子进度，点击可跳转" @click="seek">
            <div class="track-fill" :style="{ width: sentProg + '%' }"></div>
          </div>
          <div class="times">
            <span v-if="mode === 'file'">{{ curTime }} / {{ totTime }}</span>
            <span v-else>第 {{ sentIdx + 1 }} / {{ items.length }} 句</span>
            <button class="speed-btn" aria-label="调节播放速度" @click="cycleSpeed">🎚️ {{ speedLabel }}</button>
          </div>
        </div>
      </div>
      <div class="player-opts">
        <button class="lp-chip" :class="{ on: loopOne }" :aria-pressed="loopOne"
                @click="toggleLoopOne">🔂 单句循环</button>
        <button class="lp-chip" :class="{ on: loopLesson }" :aria-pressed="loopLesson"
                @click="toggleLoopLesson">🔁 本课循环</button>
        <button class="lp-chip" :class="{ on: autoNext }" :aria-pressed="autoNext"
                @click="toggleAutoNext">⏭️ 自动下一课</button>
        <button class="lp-chip" :class="{ on: !showEn }" :aria-pressed="!showEn"
                @click="showEn = !showEn; saveOpts()">{{ showEn ? "隐藏英文" : "显示英文" }}</button>
        <button class="lp-chip" :class="{ on: !showZh }" :aria-pressed="!showZh"
                @click="showZh = !showZh; saveOpts()">{{ showZh ? "隐藏中文" : "显示中文" }}</button>
      </div>
    </div>

    <div class="sent-list" ref="listEl">
      <button v-for="(it, i) in items" :key="it.id"
              class="sent-row" :class="{ active: i === activeIdx, dim: mode === 'file' && it.start == null }"
              :aria-label="'第 ' + (i + 1) + ' 句' + (i === activeIdx ? '（正在播放）' : '')"
              @click="jump(i)">
        <span class="sent-no">{{ i + 1 }}</span>
        <span class="sent-body">
          <span class="sent-en">{{ showEn ? it.text : "· · · · ·" }}</span>
          <span v-if="showZh && it.zh" class="sent-zh">{{ it.zh }}</span>
        </span>
      </button>
    </div>
  </div>
</template>
