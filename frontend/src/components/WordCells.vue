<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({ tokens: { type: Object, required: true }, submitted: Boolean });
const wcur = ref(0);
const input = ref([]);
const box = ref(null);
const flash = ref([]);
const mark = ref([]);

const refTokens = computed(() =>
  [...props.tokens.text].map((c) => ({ type: /[a-zA-Z]/.test(c) ? "letter" : "punct", text: c })));

watch(() => props.tokens.text, () => { wcur.value = 0; input.value = []; flash.value = []; mark.value = []; });

function letterIdxs() {
  const out = [];
  refTokens.value.forEach((t, i) => { if (t.type === "letter") out.push(i); });
  return out;
}
function typeLetter(ch) {
  if (!/[a-zA-Z]/.test(ch)) return;
  const ids = letterIdxs();
  if (wcur.value >= ids.length) return;
  const idx = ids[wcur.value];
  input.value[idx] = ch;
  wcur.value++;
  const wrong = ch.toLowerCase() !== refTokens.value[idx].text.toLowerCase();
  mark.value[idx] = wrong ? "wrong" : "";
  return wrong;
}
function isFull() {
  return wcur.value >= letterIdxs().length;
}
function backspace() {
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
  box.value?.querySelectorAll(".cell").forEach((el) => el.classList.remove("right", "wrong", "miss"));
}
function isCorrect() {
  return refTokens.value.every((t, i) => t.type === "punct" ||
    (input.value[i] || "").toLowerCase() === t.text.toLowerCase());
}
defineExpose({ typeLetter, backspace, paint, markWrong, reset, isCorrect, isFull });
</script>

<template>
  <div ref="box" class="cells-wrap" style="margin:0;">
    <span v-for="(t, i) in refTokens" :key="i" class="cell"
          :class="[t.type === 'punct' ? 'fixed' : '', flash.includes(i) ? 'bad' : '', mark[i] || '']">{{ t.type === 'punct' ? t.text : input[i] }}</span>
  </div>
</template>
