<script setup>
import { computed, onUnmounted, ref } from "vue";
import { bestAlternativeScore, listenOnce, speechSupported } from "../lib/speech";

const props = defineProps({ text: { type: String, required: true } });

const state = ref("idle");   // idle | listening | result | error
const result = ref(null);    // { score, hit }
const errorMsg = ref("");
let rec = null;

const visible = speechSupported();

const verdict = computed(() => {
  if (!result.value) return null;
  const s = result.value.score;
  if (s >= 85) return { cls: "good", label: "发音很棒！" };
  if (s >= 60) return { cls: "close", label: "接近了，再来一次" };
  return { cls: "bad", label: "再试一次" };
});

function start() {
  if (state.value === "listening") return;
  result.value = null;
  errorMsg.value = "";
  state.value = "listening";
  rec = listenOnce({
    onResult: (alts) => {
      result.value = bestAlternativeScore(props.text, alts);
      state.value = "result";
    },
    onError: (err) => {
      errorMsg.value = err === "not-allowed" ? "需要麦克风权限"
        : err === "no-speech" ? "没听到声音，靠近点再试"
        : err === "unsupported" ? "当前浏览器不支持语音识别"
        : "识别失败，请重试";
      state.value = "error";
    },
    onEnd: () => {
      if (state.value === "listening") state.value = "idle";  // 无结果自动结束
    },
  });
  if (!rec) state.value = "error";
}

function cancel() {
  try { rec && rec.abort(); } catch { /* 已结束 */ }
  state.value = "idle";
}

onUnmounted(() => { try { rec && rec.abort(); } catch { /* 已结束 */ } });
</script>

<template>
  <div v-if="visible" class="speech-drill" aria-live="polite">
    <template v-if="state === 'listening'">
      <button class="btn ghost sm listening" aria-label="正在聆听，点击取消" @click="cancel">
        <span class="mic-dot"></span> 正在听…点击取消
      </button>
    </template>
    <template v-else>
      <button class="btn ghost sm" aria-label="跟读这个单词" @click="start">🎤 跟读</button>
      <span v-if="state === 'result' && verdict" class="speech-verdict" :class="verdict.cls">
        {{ verdict.label }} <b>{{ result.score }}分</b>
        <small v-if="result.hit && result.score < 85">（听到的是「{{ result.hit }}」）</small>
      </span>
      <span v-if="state === 'error'" class="speech-verdict bad">{{ errorMsg }}</span>
    </template>
  </div>
</template>
