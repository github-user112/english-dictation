<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, audioEl, audioPlaying, playUrl, preloadAudio, sndRight, sndWrong, stopAudio,
         todayNextStep, goTodayStep } from "../lib/core";
import { bestSentenceScore, listenOnce, preferServerRecognition, speechErrorMessage, speechStateLabel,
         speechSupported } from "../lib/speech";

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
const fromToday = ref(false);    // 今日动线入口带 from=today：结束页给"下一关"
const nextLoading = ref(false);
const serverMode = ref(preferServerRecognition()); // 移动端默认服务端识别；桌面原生可用
const speechStage = ref("");     // requesting | recording | encoding | uploading | recognizing
const recordingAudio = ref(null);
const recordingUrl = ref("");    // 本句录音 blob URL（HTML audio 回放，换句/重录/unmount 释放）
const session = ref(0);          // 会话令牌：取消/换题后过期回调不得覆盖当前结果
const passedIds = new Set();     // 已优秀的句 id：重复通过同一句不重复计数
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
  fromToday.value = props.params?.get("from") === "today";
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
  revokeRecording();
  stopAudio();
});

function abortRec() {
  session.value++;               // 令牌失效：旧会话的一切回调到此作废
  try { rec && rec.abort(); } catch { /* 已结束 */ }
  rec = null;
  speechStage.value = "";
}

/* 录音 blob URL 只服务当前句；换句/重录/卸载时释放 */
function revokeRecording() {
  recordingAudio.value?.pause();
  if (recordingUrl.value) {
    URL.revokeObjectURL(recordingUrl.value);
    recordingUrl.value = "";
  }
}

function toggleText() {
  showText.value = !showText.value;
  localStorage.setItem("dict_shadow_text", showText.value ? "1" : "0");
}

function start() {
  idx.value = 0;
  passCount.value = 0;
  passedIds.clear();
  startItem();
}

function startItem() {
  attempts.value = 0;
  result.value = null;
  errorMsg.value = "";
  revokeRecording();
  play();
}

/* 播放当前句（播完不再自动开麦，由用户点「跟读」发起） */
function play() {
  const item = cur.value;
  if (!item) return;
  const token = ++playToken.value;
  abortRec();
  errorMsg.value = "";
  phase.value = "play";
  const nxt = items.value[idx.value + 1];
  if (nxt) preloadAudio(nxt.audio);
  audioEl.onended = () => {
    if (!mounted || token !== playToken.value) return;
    if (phase.value === "play") phase.value = "idle";
  };
  playUrl(item.audio);
}

/* 用户点「跟读」时才申请麦克风权限；处理中禁重入，可取消 */
function beginListen(item) {
  if (!item || !supported || phase.value === "listen") return;
  playToken.value++;
  stopAudio();
  abortRec();
  revokeRecording();
  serverMode.value = preferServerRecognition();
  result.value = null;
  errorMsg.value = "";
  const my = ++session.value;
  phase.value = "listen";
  speechStage.value = "requesting";
  rec = listenOnce({
    onFallback: () => { if (my === session.value) serverMode.value = true; },   // 原生识别空壳，自动切服务端（手动停止）
    onState: (st) => {
      if (my !== session.value || !mounted) return;
      speechStage.value = st;
    },
    onRecording: (blob) => {
      if (my !== session.value || !mounted || !blob) return;
      revokeRecording();
      recordingUrl.value = URL.createObjectURL(blob);   // 失败也可回放自己的录音
    },
    onResult: (alts) => {
      if (!mounted || my !== session.value || cur.value !== item) return;
      const r = bestSentenceScore(item.text, alts);
      result.value = r;
      attempts.value++;
      if (r.score >= PASS) {
        if (!passedIds.has(item.id)) { passedIds.add(item.id); passCount.value++; }
        sndRight();
      } else sndWrong();
      phase.value = "result";
      speechStage.value = "";
    },
    onError: (err) => {
      if (err === "aborted") return;   // 主动取消/重播，不算失败
      if (!mounted || my !== session.value || cur.value !== item) return;
      result.value = null;             // 失败清空结果，不计分
      errorMsg.value = speechErrorMessage(err);
      phase.value = "idle";
      speechStage.value = "";
    },
    onEnd: () => {
      if (my !== session.value || !mounted) return;
      speechStage.value = "";
      if (phase.value === "listen") phase.value = "idle";  // 无结果自动结束
    },
  });
  if (!rec) { phase.value = "idle"; speechStage.value = ""; }
  else if (rec.mode === "server") serverMode.value = true;   // 无原生识别，直接走服务端
}

function next() {
  playToken.value++;
  abortRec();
  revokeRecording();
  result.value = null;
  if (idx.value >= items.value.length - 1) {
    stopAudio();
    phase.value = "done";
    reportDone();
    return;
  }
  idx.value++;
  startItem();
}

/* 完成记账：良好句数落 daily_practice_log 的 shadow 桶（零经验，喂动线跟读环）。
   失败静默——不为一笔统计打断学习流程 */
function reportDone() {
  api("/shadow/done", {
    method: "POST",
    body: JSON.stringify({
      list: list.value, lesson: lesson.value,
      good: passCount.value, total: items.value.length,
    }),
  }).catch(() => {});
}

function goCatalog() { location.hash = "#/catalog"; }
async function goNextStep() {
  if (nextLoading.value) return;
  nextLoading.value = true;
  const s = await todayNextStep("shadow");
  if (mounted) goTodayStep(s);
}

function replay() { play(); }                 // 再听一遍原声；要跟读再点「跟读」
function retry() { beginListen(cur.value); }  // 不重听，直接再读（用户手势触发，点才申请权限）
function finishRecording() {
  if (phase.value !== "listen" || speechStage.value !== "recording") return;
  speechStage.value = serverMode.value ? "encoding" : "recognizing";
  rec?.finish();
}
function switchLesson() {
  playToken.value++;
  abortRec();
  revokeRecording();
  result.value = null;
  stopAudio();
  const p = new URLSearchParams({ list: list.value });
  if (lesson.value) p.set("lesson", lesson.value);
  location.hash = `#/shadow?${p}`;
}
function goLists() { location.hash = "#/lists"; }
</script>

<template>
  <div v-if="pageError" class="empty shadow-error" role="alert">
    <span class="emoji" aria-hidden="true">📚</span>
    <h3>课程加载失败</h3>
    <p>{{ pageError }}</p>
    <button class="btn primary" @click="goLists">返回素材库</button>
  </div>
  <div v-else-if="loading" class="empty loading"><span class="spin" aria-hidden="true"></span><span class="load-text">加载中…</span></div>

  <!-- 开始页：音频自动播放与麦克风都需要一次用户手势 -->
  <div v-else-if="phase === 'intro'" class="practice-card shadow-intro">
    <div class="si-head">
      <span class="si-emoji" aria-hidden="true">🎤</span>
      <h2>听读模式</h2>
      <p>每句流程：先听一遍原声 → 跟着读 → 系统打分（{{ PASS }} 分优秀）</p>
    </div>
    <div class="si-steps">
      <div class="si-step">
        <span class="si-icon" aria-hidden="true">🔊</span>
        <b>听原声</b>
        <small>先听一遍示范</small>
      </div>
      <div class="si-step">
        <span class="si-icon" aria-hidden="true">🎙️</span>
        <b>跟读</b>
        <small>点「跟读」开麦</small>
      </div>
      <div class="si-step">
        <span class="si-icon" aria-hidden="true">⭐</span>
        <b>打分</b>
        <small>{{ PASS }} 分即优秀</small>
      </div>
    </div>
    <p class="hint">共 {{ items.length }} 句{{ lesson ? ` · 第 ${lesson} 课` : "" }}</p>
    <p v-if="!supported" class="speech-verdict bad" role="alert">当前浏览器不支持语音识别（推荐 Chrome），只能听不能打分</p>
    <div class="controls" style="margin-top:16px;">
      <button class="btn primary big" @click="start">▶ 开始</button>
    </div>
  </div>

  <!-- 结束 -->
  <div v-else-if="phase === 'done'" class="empty shadow-done">
    <span class="emoji" aria-hidden="true">🎉</span>
    <h3>本课完成</h3>
    <p>优秀 {{ passCount }} / {{ items.length }} 句</p>
    <div class="controls" style="margin-top:16px;">
      <template v-if="fromToday">
        <button class="btn primary big" :disabled="nextLoading" @click="goNextStep">下一关 →</button>
        <button class="btn ghost big" @click="goCatalog">返回今日动线</button>
      </template>
      <template v-else>
        <button class="btn primary big" @click="start">再读一遍</button>
        <button v-if="nextLessonNo != null" class="btn primary" @click="lesson = nextLessonNo; switchLesson()">下一课（第 {{ nextLessonNo }} 课）→</button>
        <button class="btn ghost" @click="goLists">返回素材库</button>
      </template>
    </div>
  </div>

  <div v-else class="shadow-page">
    <div class="practice-top">
      <span class="progress-line">{{ lesson ? `第 ${lesson} 课 · ` : "" }}{{ idx + 1 }} / {{ items.length }} · 优秀 {{ passCount }}
        <span class="lp-track" aria-hidden="true"><span class="lp-fill" :style="{ width: items.length ? (idx + 1) / items.length * 100 + '%' : '0%' }"></span></span>
      </span>
      <span class="shadow-top-right">
        <select v-if="lessons.length" v-model.number="lesson" class="lesson-select" aria-label="切换课程" @change="switchLesson">
          <option v-for="x in lessons" :key="x.lesson" :value="x.lesson">第 {{ x.lesson }} 课</option>
        </select>
        <button class="btn ghost sm" :aria-pressed="showText" @click="toggleText">{{ showText ? "隐藏句子" : "显示句子" }}</button>
      </span>
    </div>

    <div class="sh-grid">
      <!-- 竞技场 -->
      <div class="practice-card arena">
        <div class="arena-topbar" aria-hidden="true"></div>
        <div class="arena-inner">
          <div class="arena-head">
            <div class="left">
              <span class="qnum"><span class="ic" aria-hidden="true">🎤</span> 第 {{ idx + 1 }} / {{ items.length }} 句</span>
              <span class="badge-soft blue"><span class="ic" aria-hidden="true">🎯</span> 语音跟读</span>
            </div>
            <span class="badge-soft orange"><span class="ic" aria-hidden="true">⭐</span> 优秀 {{ passCount }} 句</span>
          </div>

          <div class="shadow-sentence" aria-live="polite">
            <template v-if="revealed">
              <div class="sentence-card">
                <div class="sentence-label"><span class="ic" aria-hidden="true">🔊</span> 请跟读下面的句子</div>
                <div class="sentence-text shadow-en" :class="{ playing: phase === 'play' }">
                  <span class="sr-only" aria-hidden="true">{{ cur.text }}</span>
                  <span v-for="(w, i) in (cur && cur.text) ? cur.text.match(/[^\s]+/g) || [] : []" :key="i"
                        class="word" :style="{ '--i': i }"
                        :class="result && result.hit
                          ? (' ' + result.hit.toLowerCase().replace(/[^a-z0-9'-]+/g, ' ') + ' ').includes(' ' + w.toLowerCase().replace(/[^a-z0-9']/g, '') + ' ') ? 'correct' : 'wrong'
                          : ''">{{ w }}</span>
                </div>
                <div v-if="cur.zh" class="shadow-zh">{{ cur.zh }}</div>
              </div>
            </template>
            <div v-else class="sentence-card">
              <div class="sentence-label"><span class="ic" aria-hidden="true">🙈</span> 句子已隐藏</div>
              <div class="shadow-hidden">句子已隐藏 · 听音后跟读</div>
            </div>
          </div>

          <div class="speech-drill" aria-live="polite" :class="{
            on: phase === 'listen' && speechStage === 'recording',
            playing: phase === 'play',
            good: verdict && verdict.cls === 'good',
            close: verdict && verdict.cls === 'close',
            bad: !!errorMsg || (verdict && verdict.cls === 'bad'),
          }">
            <span v-if="phase === 'play'" class="speech-verdict">🔊 正在播放…</span>
            <span v-else-if="phase === 'listen'" class="speech-verdict"><span v-if="speechStage === 'recording'" class="mic-dot"></span> {{ speechStateLabel(speechStage) }}<small v-if="speechStage === 'recording'">{{ serverMode ? ' · 说完点「说完了」' : ' · 请跟读，说完自动识别' }}</small></span>
            <span v-else-if="phase === 'result' && verdict" class="speech-verdict" :class="verdict.cls">
              {{ verdict.label }} <b>{{ result.score }}分</b>
              <small v-if="!passed && result.hit">（听到的是「{{ result.hit }}」）</small>
            </span>
            <span v-else-if="errorMsg" class="speech-verdict bad">{{ errorMsg }}</span>
            <span v-else class="speech-verdict">准备好了</span>
          </div>

          <div class="controls arena-controls">
            <template v-if="phase === 'result'">
              <button v-if="passed" class="btn primary big full" @click="next">{{ idx >= items.length - 1 ? '完成本课 →' : '下一句 →' }}</button>
              <template v-else>
                <div class="record-zone">
                  <button class="btn white" :class="{ playing: audioPlaying }" @click="replay">🔊 再听一遍</button>
                  <button class="btn primary big" @click="retry">🎤 再读一次</button>
                </div>
                <button class="btn ghost" aria-label="跳过这句" @click="next">跳过 →</button>
              </template>
            </template>
            <template v-else>
              <div class="record-zone">
                <template v-if="phase === 'listen'">
                  <button v-if="serverMode && speechStage === 'recording'" class="btn primary recording" @click="finishRecording">🎤 说完了，开始识别</button>
                  <button class="btn ghost sm listening" aria-label="取消本次跟读" @click="abortRec(); phase = 'idle'">取消</button>
                </template>
                <button class="btn white" :class="{ playing: audioPlaying && phase === 'play' }" :disabled="phase === 'play' || phase === 'listen'" @click="replay">🔊 重播</button>
                <button v-if="supported" class="btn primary" :disabled="phase === 'listen'" @click="retry">{{ errorMsg ? '🎤 重试跟读' : '🎤 跟读' }}</button>
                <button class="btn ghost" aria-label="跳过这句" @click="next">跳过 →</button>
              </div>
            </template>
            <div v-if="recordingUrl" class="recording-playback">
              <span>我的录音（仅当前句可回放）</span>
              <audio ref="recordingAudio" :src="recordingUrl" controls preload="metadata" aria-label="回放我的录音"></audio>
            </div>
            <div class="hint">听一遍 → 点「跟读」开麦 → 识别打分 · {{ PASS }} 分优秀可跳下一句{{ showText ? "" : " · 句子已隐藏，打分后显示" }}</div>
          </div>
        </div>
      </div>

      <!-- 得分卡 -->
      <aside v-if="result" class="score-card">
        <div class="score-hero" :class="{ ok: passed, mid: !passed && result.score >= 60, low: !passed && result.score < 60 }">
          <div class="ring-wrap">
            <svg width="140" height="140" viewBox="0 0 140 140" aria-hidden="true">
              <circle class="ring-bg" cx="70" cy="70" r="57" stroke-width="13"></circle>
              <circle class="ring-fg" cx="70" cy="70" r="57" stroke-width="13" stroke-dasharray="358"
                      :style="{ strokeDashoffset: 358 * (1 - result.score / 100) }"></circle>
            </svg>
            <div class="ring-center">
              <span class="pct">{{ result.score }}</span>
              <span class="sub">/ 100</span>
            </div>
          </div>
          <div class="score-label">{{ verdict ? verdict.label : "本句得分" }}</div>
        </div>
        <div class="score-meta">
          <div class="stat-box">
            <div class="val green">{{ passCount }}</div>
            <div class="lbl">优秀句数</div>
          </div>
          <div class="stat-box">
            <div class="val orange">{{ items.length }}</div>
            <div class="lbl">本课总句数</div>
          </div>
        </div>
        <div v-if="result.hit && !passed" class="hit-line">
          <span class="lbl">听到的</span>
          <code>{{ result.hit }}</code>
        </div>
      </aside>
    </div>
  </div>
</template>
