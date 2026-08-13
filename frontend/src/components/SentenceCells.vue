<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({ tokens: { type: Object, required: true }, submitted: Boolean });
const scur = ref(0);
const input = ref([]);
const box = ref(null);
const flash = ref([]);
const mark = ref([]);

const words = computed(() =>
  props.tokens.text.split(/\s+/).map((w) => {
    const m = w.match(/^([^\w]*)([\w'-]*)([^\w]*)$/) || ["", "", w, ""];
    return { pre: m[1], core: m[2] || m[1] || w, suf: m[3] };
  }));

watch(() => props.tokens.text, () => { scur.value = 0; input.value = []; flash.value = []; mark.value = []; });

function typeWordChar(ch) {
  if (ch === " ") {
    if (!(input.value[scur.value] || "")) return;
    if (scur.value + 1 >= words.value.length) return;
    scur.value++;
    return;
  }
  if (!/[a-zA-Z']/.test(ch)) return;
  const i = scur.value;
  const w = input.value[i] || "";
  if (w.length >= 30) return;
  input.value[i] = w + ch;
  const target = (words.value[i]?.core || "").toLowerCase();
  const wrong = target && !target.startsWith((w + ch).toLowerCase());
  mark.value[i] = wrong ? "wrong" : "";
  return wrong;
}
function refreshMark(i) {
  const typed = (input.value[i] || "").toLowerCase();
  const target = (words.value[i]?.core || "").toLowerCase();
  mark.value[i] = typed && !target.startsWith(typed) ? "wrong" : "";
}
function backspace() {
  const w = input.value[scur.value] || "";
  if (w.length) {
    input.value[scur.value] = w.slice(0, -1);
    refreshMark(scur.value);
    return;
  }
  if (scur.value > 0) {
    scur.value--;
    input.value[scur.value] = (input.value[scur.value] || "").slice(0, -1);
    refreshMark(scur.value);
  }
}
function cell(i) { return box.value?.querySelector("#sc" + i); }
function paint() {
  const t = words.value.map((w) => w.core.toLowerCase());
  mark.value = t.map((w, i) => (input.value[i] || "").toLowerCase() === w ? "right" : "wrong");
}
function markWrong() {
  const t = words.value.map((w) => w.core.toLowerCase());
  mark.value = t.map((w, i) => {
    const mine = (input.value[i] || "").toLowerCase();
    if (mine === w) return "right";
    return mine ? "wrong" : "miss";
  });
}
function reset() {
  scur.value = 0;
  input.value = [];
  flash.value = [];
  mark.value = [];
  box.value?.querySelectorAll(".cell").forEach((el) => el.classList.remove("right", "wrong", "miss"));
}
function isCorrect() {
  const t = words.value.map((w) => w.core.toLowerCase());
  return t.every((w, i) => (input.value[i] || "").toLowerCase() === w);
}
function lineChars(i) {
  return Math.max(3, words.value[i]?.core.length || 0, (input.value[i] || "").length);
}
defineExpose({ typeWordChar, backspace, paint, markWrong, reset, isCorrect });
</script>

<template>
  <div ref="box" class="cells-wrap" style="margin:0;">
    <template v-for="(w, i) in words" :key="i">
      <span v-if="w.pre" class="punct">{{ w.pre }}</span>
      <span :id="'sc' + i" class="cell word-line"
            :class="[mark[i] || '', !submitted && i === scur ? 'current' : '']"
            :style="{ '--chars': lineChars(i) }">{{ input[i] }}</span>
      <span v-if="w.suf" class="punct">{{ w.suf }}</span>
    </template>
  </div>
</template>
