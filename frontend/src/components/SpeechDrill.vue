<script setup>
import { computed, onUnmounted, ref, watch } from "vue";
import { bestAlternativeScore, listenOnce, preferServerRecognition, speechErrorMessage,
         speechStateLabel, speechSupported } from "../lib/speech";

const props = defineProps({ text: { type: String, required: true } });

const state = ref("idle");       // idle | listening | result | error
const result = ref(null);        // { score, hit }
const errorMsg = ref("");
const serverMode = ref(preferServerRecognition()); // 移动端默认录音上传
const stage = ref("");           // requesting | recording | encoding | uploading | recognizing
const recordingUrl = ref("");    // 本词录音 blob URL，失败也可回放
const recordingAudio = ref(null);
let rec = null;
let session = 0;                 // 会话令牌：换词/取消后旧回调作废

const visible = speechSupported();

const verdict = computed(() => {
  if (!result.value) return null;
  const s = result.value.score;
  if (s >= 85) return { cls: "good", label: "发音很棒！" };
  if (s >= 60) return { cls: "close", label: "接近了，再来一次" };
  return { cls: "bad", label: "再试一次" };
});

function revokeRecording() {
  recordingAudio.value?.pause();
  if (recordingUrl.value) {
    URL.revokeObjectURL(recordingUrl.value);
    recordingUrl.value = "";
  }
}

/* 用户点「跟读」发起（保留麦克风权限手势）；处理中禁重入 */
function start() {
  if (state.value === "listening" || !visible) return;
  session++;
  const my = session;
  try { rec && rec.abort(); } catch { /* 已结束 */ }
  revokeRecording();
  result.value = null;
  errorMsg.value = "";
  state.value = "listening";
  stage.value = "requesting";
  serverMode.value = preferServerRecognition();
  rec = listenOnce({
    onFallback: () => { if (my === session) serverMode.value = true; },   // 原生识别空壳，自动切服务端
    onState: (st) => { if (my === session) stage.value = st; },
    onRecording: (blob) => {
      if (my !== session || !blob) return;
      revokeRecording();
      recordingUrl.value = URL.createObjectURL(blob);
    },
    onResult: (alts) => {
      if (my !== session) return;
      result.value = bestAlternativeScore(props.text, alts);
      state.value = "result";
      stage.value = "";
    },
    onError: (err) => {
      if (err === "aborted" || my !== session) return;   // 主动取消/换词不算失败
      result.value = null;                               // 失败清空结果，不计分
      errorMsg.value = speechErrorMessage(err);
      state.value = "error";
      stage.value = "";
    },
    onEnd: () => {
      if (my !== session) return;
      stage.value = "";
      if (state.value === "listening") state.value = "idle";  // 无结果自动结束
    },
  });
  if (!rec && state.value === "listening") {
    result.value = null;
    stage.value = "";
    errorMsg.value = speechErrorMessage("start-failed");
    state.value = "error";
  } else if (rec?.mode === "server") {
    serverMode.value = true;
  }
}

function finishRecording() {
  if (state.value !== "listening" || stage.value !== "recording") return;
  stage.value = serverMode.value ? "encoding" : "recognizing";
  rec?.finish();
}

function cancel() {
  session++;
  try { rec && rec.abort(); } catch { /* 已结束 */ }
  rec = null;
  stage.value = "";
  state.value = "idle";
}

/* 换词即作废旧会话、释放录音，旧回调不能把上一词的分数带到新词 */
watch(() => props.text, () => {
  session++;
  try { rec && rec.abort(); } catch { /* 已结束 */ }
  rec = null;
  revokeRecording();
  result.value = null;
  errorMsg.value = "";
  stage.value = "";
  state.value = "idle";
}, { flush: "sync" });

onUnmounted(() => {
  session++;
  try { rec && rec.abort(); } catch { /* 已结束 */ }
  revokeRecording();
});
</script>

<template>
  <div v-if="visible" class="speech-drill" aria-live="polite" :class="{
    'rec-on': state === 'listening' && stage === 'recording',
    good: verdict && verdict.cls === 'good',
    close: verdict && verdict.cls === 'close',
    bad: state === 'error' || (verdict && verdict.cls === 'bad'),
  }">
    <template v-if="state === 'listening'">
      <button v-if="serverMode && stage === 'recording'" class="btn primary sm recording" aria-label="说完了，开始识别" @click="finishRecording">
        🎤 说完了，开始识别
      </button>
      <button class="btn ghost sm" aria-label="取消本次跟读" @click="cancel">
        <span v-if="stage === 'recording'" class="mic-dot" aria-hidden="true"></span>
        {{ speechStateLabel(stage) }} · 点击取消
      </button>
    </template>
    <template v-else>
      <button class="btn ghost sm" aria-label="跟读这个单词" @click="start">{{ state === 'error' ? '🎤 重试跟读' : '🎤 跟读' }}</button>
      <span v-if="state === 'result' && verdict" class="speech-verdict" :class="verdict.cls">
        {{ verdict.label }} <b>{{ result.score }}分</b>
        <small v-if="result.hit && result.score < 85">（听到的是「{{ result.hit }}」）</small>
      </span>
      <span v-if="state === 'error'" class="speech-verdict bad">{{ errorMsg }}</span>
      <span v-if="state === 'idle'" class="sd-idle">跟读一下，练练发音 👄</span>
    </template>
    <audio v-if="recordingUrl" ref="recordingAudio" class="sd-replay" :src="recordingUrl" controls preload="none"
           aria-label="回放自己的录音"></audio>
  </div>
</template>
