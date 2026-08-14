<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({ tokens: { type: Object, required: true }, submitted: Boolean,
  feedback: Boolean, practiceMode: { type: String, default: "assisted" } });
const wcur = ref(0);
const input = ref([]);
const box = ref(null);
const flash = ref([]);
const mark = ref([]);
const extraInput = ref("");
const ignoredHint = ref("");
let ignoredTimer = null;
const showSequence = computed(() => props.practiceMode !== "pure" || props.feedback || mark.value.some(Boolean));

const refTokens = computed(() =>
  [...props.tokens.text].map((c) => ({ type: /[a-zA-Z]/.test(c) ? "letter" : "punct", text: c })));

watch(() => `${props.tokens.id}:${props.tokens.text}`, () => { wcur.value = 0; input.value = []; flash.value = []; mark.value = []; extraInput.value = ""; ignoredHint.value = ""; clearTimeout(ignoredTimer); });

function letterIdxs() {
  const out = [];
  refTokens.value.forEach((t, i) => { if (t.type === "letter") out.push(i); });
  return out;
}
function typeLetter(ch) {
  if (!/[a-zA-Z]/.test(ch)) {
    ignoredHint.value = `已忽略非字母字符「${ch}」，请输入字母`;
    clearTimeout(ignoredTimer);
    ignoredTimer = setTimeout(() => { ignoredHint.value = ""; }, 1500);
    return;
  }
  const ids = letterIdxs();
  if (wcur.value >= ids.length) {
    if (props.practiceMode === "pure") extraInput.value += ch;
    return false;
  }
  const idx = ids[wcur.value];
  input.value[idx] = ch;
  wcur.value++;
  const wrong = ch.toLowerCase() !== refTokens.value[idx].text.toLowerCase();
  if (props.practiceMode !== "pure") mark.value[idx] = wrong ? "wrong" : "";
  return props.practiceMode !== "pure" && wrong;
}
function isFull() {
  return wcur.value >= letterIdxs().length;
}
function isCurrent(i) {
  return !props.submitted && letterIdxs()[wcur.value] === i;
}
function answerText() {
  return letterIdxs().map((i) => input.value[i] || "").join("") + extraInput.value;
}
function serialize() { return { input: [...input.value], cursor: wcur.value, mark: [...mark.value], extraInput: extraInput.value }; }
function restore(s) {
  if (!s) return;
  input.value = [...(s.input || [])];
  wcur.value = Number(s.cursor) || 0;
  mark.value = props.practiceMode === "pure" && !props.feedback ? [] : [...(s.mark || [])];
  extraInput.value = s.extraInput || "";
}
function backspace() {
  if (extraInput.value) {
    extraInput.value = extraInput.value.slice(0, -1);
    return;
  }
  if (wcur.value <= 0) return;
  wcur.value--;
  const idx = letterIdxs()[wcur.value];
  input.value[idx] = "";
  mark.value[idx] = "";
}
function paint() {
  mark.value = refTokens.value.map((t) => t.type === "punct" ? "" : "right");
}
function markWrong() {
  mark.value = refTokens.value.map((t, i) => {
    if (t.type === "punct") return "";
    const mine = (input.value[i] || "").toLowerCase();
    if (mine === t.text.toLowerCase()) return "right";
    return mine ? "wrong" : "miss";
  });
}
function reset() {
  wcur.value = 0;
  input.value = [];
  flash.value = [];
  mark.value = [];
  extraInput.value = "";
  box.value?.querySelectorAll(".cell").forEach((el) => el.classList.remove("right", "wrong", "miss"));
}
function isCorrect() {
  return !extraInput.value && refTokens.value.every((t, i) => t.type === "punct" ||
    (input.value[i] || "").toLowerCase() === t.text.toLowerCase());
}
defineExpose({ typeLetter, backspace, paint, markWrong, reset, isCorrect, isFull, serialize, restore });
</script>

<template>
  <div ref="box" class="cells-wrap letter-lines" style="margin:0;">
    <span v-if="!showSequence" class="cell word-line current pure-line"
          :style="{ '--chars': Math.max(6, answerText().length) }">{{ answerText() }}</span>
    <template v-for="(t, i) in refTokens" :key="i">
      <span v-if="showSequence && t.type === 'punct'" class="punct">{{ t.text }}</span>
      <span v-else-if="showSequence" class="cell letter-line"
            :class="[mark[i] || '', isCurrent(i) ? 'current' : '']">{{ input[i] }}</span>
    </template>
    <span v-for="(c, i) in extraInput" v-if="showSequence" :key="'extra-' + i" class="cell letter-line wrong">{{ c }}</span>
    <span v-if="ignoredHint" class="ignored-hint" role="status">{{ ignoredHint }}</span>
  </div>
</template>
