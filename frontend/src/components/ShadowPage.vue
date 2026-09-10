<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, audioEl, audioPlaying, playUrl, preloadAudio, sndRight, sndWrong, stopAudio } from "../lib/core";
import { bestSentenceScore, listenOnce, speechSupported } from "../lib/speech";

const props = defineProps({ params: { type: Object, default: null } });

const PASS = 85;                 // >=85 判优秀，可跳下一句
const supported = speechSupported();

const list = ref("nc1");
const lesson = ref(null);
const lessons = ref([]);         // 课次表（切换课/算下一课）
const items = ref([]);
const idx = ref(0);
const phase = ref("intro");      // intro | play | idle | listen | result | done
const result = ref(null);        // { score, hit }
const errorMsg = ref("");
const loading = ref(true);
const pageError = ref("");
const showText = ref(localStorage.getItem("dict_shadow_text") !== "0");
const attempts = ref(0);         // 本句已跟读次数
const passCount = ref(0);
const playToken = ref(0);
let rec = null;
let mounted = true;

const cur = computed(() => items.value[idx.value] || null);
const passed = computed(() => Boolean(result.value) && result.value.score >= PASS);
const revealed = computed(() => showText.value || phase.value === "result");
const nextLessonNo = computed(() => {
  const i = lessons.value.findIndex((x) => x.lesson === lesson.value);
  return i >= 0 ? (lessons.value[i + 1]?.lesson ?? null) : null;
});
const verdict = computed(() => {
  if (!result.value) return null;
  const s = result.value.score;
  if (s >= PASS) return { cls: "good", label: "优秀！" };
  if (s >= 60) return { cls: "close", label: "接近了，再读一遍" };
  return { cls: "bad", label: "再听一遍，跟着读" };
});

onMounted(async () => {
  list.value = props.params?.get("list") || "nc1";
  lesson.value = Number(props.params?.get("lesson")) || null;
  try {
    const qs = new URLSearchParams({ list: list.value });
    if (lesson.value) qs.set("lesson", lesson.value);
    const d = await api(`/shadow/session?${qs}`);
    if (!mounted) return;
    items.value = d.items || [];
    api(`/lessons?list=${list.value}`)
      .then((r) => { if (mounted) lessons.value = r.lessons || []; })
      .catch(() => { /* 课次表只用于切换，失败不阻塞 */ });
    loading.value = false;
  } catch (err) {
    pageError.value = err.message || "课程加载失败";
    loading.value = false;
  }
});

onUnmounted(() => {
  mounted = false;
  playToken.value++;
  abortRec();
  stopAudio();
});

function abortRec() {
  try { rec && rec.abort(); } catch { /* 已结束 */ }
  rec = null;
}

function toggleText() {
  showText.value = !showText.value;
  localStorage.setItem("dict_shadow_text", showText.value ? "1" : "0");
}

function start() {
  idx.value = 0;
  passCount.value = 0;
  startItem();
}

function startItem() {
  attempts.value = 0;
  result.value = null;
  errorMsg.value = "";
  play(true);
}

/* 播放当前句；thenListen 时播完自动开麦跟读 */
function play(thenListen) {
  const item = cur.value;
  if (!item) return;
  const token = ++playToken.value;
  abortRec();
  result.value = null;
  errorMsg.value = "";
  phase.value = "play";
  const nxt = items.value[idx.value + 1];
  if (nxt) preloadAudio(nxt.audio);
  audioEl.onended = () => {
    if (!mounted || token !== playToken.value) return;
    if (thenListen) beginListen(item);
    else if (phase.value === "play") phase.value = "idle";
  };
  playUrl(item.audio);
}

function beginListen(item) {
  if (!supported) { phase.value = "idle"; return; }
  abortRec();
  phase.value = "listen";
  rec = listenOnce({
    onResult: (alts) => {
      if (!mounted || cur.value !== item) return;
      const r = bestSentenceScore(item.text, alts);
      result.value = r;
      attempts.value++;
      if (r.score >= PASS) { passCount.value++; sndRight(); } else sndWrong();
      phase.value = "result";
    },
    onError: (err) => {
      if (err === "aborted") return;   // 主动取消/重播，不算失败
      if (!mounted || cur.value !== item) return;
      errorMsg.value = err === "not-allowed" ? "需要麦克风权限"
        : err === "no-speech" ? "没听到声音，靠近点再试"
        : "识别失败，请重试";
      phase.value = "idle";
    },
    onEnd: () => {
      if (phase.value === "listen") phase.value = "idle";  // 无结果自动结束
    },
  });
  if (!rec) phase.value = "idle";
}

function next() {
  playToken.value++;
  abortRec();
  if (idx.value >= items.value.length - 1) {
    stopAudio();
    phase.value = "done";
    return;
  }
  idx.value++;
  startItem();
}

function replay() { play(true); }       // 再听一遍，播完自动开麦
function retry() { beginListen(cur.value); }  // 不重听，直接再读
function switchLesson() {
  const p = new URLSearchParams({ list: list.value });
  if (lesson.value) p.set("lesson", lesson.value);
  location.hash = `#/shadow?${p}`;
}
function goCatalog() { location.hash = "#/catalog"; }
</script>

<template>
  <div v-if="pageError" class="empty" role="alert"><p>{{ pageError }}</p><button class="btn primary" @click="goCatalog">返回素材库</button></div>
  <div v-else-if="loading" class="empty loading"><span class="spin" aria-hidden="true"></span><span class="load-text">加载中…</span></div>

  <!-- 开始页：音频自动播放与麦克风都需要一次用户手势 -->
  <div v-else-if="phase === 'intro'" class="practice-card shadow-intro">
    <h2>听读模式</h2>
    <p>每句流程：先听一遍原声 → 跟着读 → 系统打分（{{ PASS }} 分优秀）</p>
    <p class="hint">共 {{ items.length }} 句{{ lesson ? ` · 第 ${lesson} 课` : "" }}</p>
    <p v-if="!supported" class="speech-verdict bad" role="alert">当前浏览器不支持语音识别（推荐 Chrome），只能听不能打分</p>
    <div class="controls" style="margin-top:16px;">
      <button class="btn primary big" @click="start">▶ 开始</button>
    </div>
  </div>

  <!-- 结束 -->
  <div v-else-if="phase === 'done'" class="empty">
    <div style="font-size:20px;font-weight:700;margin-bottom:10px;">本课完成 🎉</div>
    <p>优秀 {{ passCount }} / {{ items.length }} 句</p>
    <div class="controls" style="margin-top:16px;">
      <button class="btn primary big" @click="start">再读一遍</button>
      <button v-if="nextLessonNo != null" class="btn primary" @click="lesson = nextLessonNo; switchLesson()">下一课（第 {{ nextLessonNo }} 课）→</button>
      <button class="btn ghost" @click="goCatalog">返回素材库</button>
    </div>
  </div>

  <div v-else class="shadow-page">
    <div class="practice-top">
      <span class="progress-line">{{ lesson ? `第 ${lesson} 课 · ` : "" }}{{ idx + 1 }} / {{ items.length }} · 优秀 {{ passCount }}</span>
      <span class="shadow-top-right">
        <select v-if="lessons.length" v-model.number="lesson" class="lesson-select" aria-label="切换课程" @change="switchLesson">
          <option v-for="x in lessons" :key="x.lesson" :value="x.lesson">第 {{ x.lesson }} 课</option>
        </select>
        <button class="btn ghost sm" :aria-pressed="showText" @click="toggleText">{{ showText ? "隐藏句子" : "显示句子" }}</button>
      </span>
    </div>
    <div class="practice-card">
      <div class="shadow-sentence" aria-live="polite">
        <template v-if="revealed">
          <div class="shadow-en">{{ cur.text }}</div>
          <div v-if="cur.zh" class="shadow-zh">{{ cur.zh }}</div>
        </template>
        <div v-else class="shadow-hidden">句子已隐藏 · 听音后跟读</div>
      </div>

      <div class="speech-drill" aria-live="polite">
        <span v-if="phase === 'play'" class="speech-verdict">🔊 正在播放…</span>
        <span v-else-if="phase === 'listen'" class="speech-verdict good"><span class="mic-dot"></span> 正在听，请跟读…</span>
        <span v-else-if="phase === 'result' && verdict" class="speech-verdict" :class="verdict.cls">
          {{ verdict.label }} <b>{{ result.score }}分</b>
          <small v-if="!passed && result.hit">（听到的是「{{ result.hit }}」）</small>
        </span>
        <span v-else-if="errorMsg" class="speech-verdict bad">{{ errorMsg }}</span>
        <span v-else class="speech-verdict">准备好了</span>
      </div>

      <div class="controls">
        <template v-if="phase === 'result'">
          <button v-if="passed" class="btn primary big" @click="next">{{ idx >= items.length - 1 ? '完成本课 →' : '下一句 →' }}</button>
          <template v-else>
            <button class="btn ghost" :class="{ playing: audioPlaying }" @click="replay">🔊 再听一遍</button>
            <button class="btn primary big" @click="retry">🎤 再读一次</button>
            <button class="btn ghost" aria-label="跳过这句" @click="next">跳过 →</button>
          </template>
        </template>
        <template v-else>
          <button v-if="phase === 'listen'" class="btn ghost sm listening" aria-label="取消本次跟读" @click="abortRec(); phase = 'idle'">取消</button>
          <button class="btn ghost" :class="{ playing: audioPlaying && phase === 'play' }" :disabled="phase === 'play'" @click="replay">🔊 重播</button>
          <button v-if="supported" class="btn ghost" :disabled="phase === 'play'" @click="retry">🎤 跟读</button>
          <button class="btn ghost" aria-label="跳过这句" @click="next">跳过 →</button>
        </template>
      </div>
      <div class="hint">听一遍 → 自动开麦跟读 → {{ PASS }} 分优秀可跳下一句{{ showText ? "" : " · 句子已隐藏，打分后显示" }}</div>
    </div>
  </div>
</template>
