<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({ tokens: { type: Object, required: true }, submitted: Boolean,
  feedback: Boolean, practiceMode: { type: String, default: "assisted" } });
const scur = ref(0);
const input = ref([]);
const box = ref(null);
const flash = ref([]);
const mark = ref([]);
const extras = ref([]);
const showSequence = computed(() => props.practiceMode !== "pure" || props.feedback);

// 词核字符：字母/数字/下划线/撇号/连字符；其余视为前后标点（pre/suf）。
// 内部含 . , / & : 等字符的缩写词（B.C.、a.m.、2,400、Why/Why）整体保留在 core 中由用户输入。
const words = computed(() =>
  props.tokens.text.split(/\s+/).map((w) => {
    const pre = (w.match(/^[^\w-]+/) || [""])[0];
    const suf = (w.match(/[^\w-]+$/) || [""])[0];
    let core = w.slice(pre.length, suf ? w.length - suf.length : w.length);
    core = core.replace(/_/g, "");  // 下划线可忽略：不要求输入，判定时忽略
    if (!core) return { pre: "", core: w, suf: "" };  // 纯标点 token
    return { pre, core, suf };
  }));

watch(() => `${props.tokens.id}:${props.tokens.text}`, () => { scur.value = 0; input.value = []; flash.value = []; mark.value = []; extras.value = []; });

function typeWordChar(ch) {
  if (ch === " ") {
    const typed = (input.value[scur.value] || "").toLowerCase();
    const target = (words.value[scur.value]?.core || "").toLowerCase();
    if (!typed) {
      if (scur.value < words.value.length - 1) scur.value++;
      return false;
    }
    if (typed === target) {
      if (scur.value < words.value.length - 1) scur.value++;
      return false;
    }
    if (props.practiceMode !== "pure") mark.value[scur.value] = "wrong";
    return true;
  }
  if (ch === "_") return;   // 下划线可忽略：输入时跳过，判定时词核已去除下划线
  if (!/^[a-zA-Z0-9_\'\-.,/&:]+$/.test(ch)) return;
  const i = scur.value;
  const w = input.value[i] || "";
  if (w.length >= 30) return;
  input.value[i] = w + ch;
  const target = (words.value[i]?.core || "").toLowerCase();
  const wrong = target && !target.startsWith((w + ch).toLowerCase());
  if (props.practiceMode !== "pure") mark.value[i] = wrong ? "wrong" : "";
  return props.practiceMode !== "pure" && wrong;
}
function refreshMark(i) {
  if (props.practiceMode === "pure" && !props.submitted) {
    mark.value[i] = "";
    return;
  }
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
function focusWord(i) {
  if (props.submitted || props.feedback) return;
  scur.value = i;
}
function paint() {
  const t = words.value.map((w) => w.core.toLowerCase());
  mark.value = t.map((w, i) => (input.value[i] || "").toLowerCase() === w ? "right" : "wrong");
}
function markWrong() {
  // 逐词按位比对，错误的词留在原位标红，不移动到其他横线
  const target = words.value.map((w) => w.core.toLowerCase());
  const marks = target.map((w, i) => {
    const typed = (input.value[i] || "").toLowerCase();
    if (!typed) return "miss";
    return typed === w ? "right" : "wrong";
  });
  const extra = [];
  for (let i = target.length; i < input.value.length; i++) {
    if (input.value[i]) extra.push({ word: input.value[i], at: target.length });
  }
  mark.value = marks;
  extras.value = extra;
}
function reset() {
  scur.value = 0;
  input.value = [];
  flash.value = [];
  mark.value = [];
  extras.value = [];
  box.value?.querySelectorAll(".cell").forEach((el) => el.classList.remove("right", "wrong", "miss"));
}
function isCorrect() {
  const t = words.value.map((w) => w.core.toLowerCase());
  return input.value.filter(Boolean).length === t.length &&
    t.every((w, i) => (input.value[i] || "").toLowerCase() === w);
}
function lineChars(i) {
  if (props.practiceMode === "pure") return Math.max(3, (input.value[i] || "").length);
  return Math.max(3, words.value[i]?.core.length || 0, (input.value[i] || "").length);
}
const displayWords = computed(() => {
  const count = mark.value.some(Boolean) || extras.value.length
    ? words.value.length : Math.max(words.value.length, input.value.length, scur.value + 1);
  return Array.from({ length: count }, (_, i) => words.value[i] || { pre: "", core: "", suf: "" });
});
function answerText() {
  return input.value.filter(Boolean).join(" ");
}
function extraAt(i) { return extras.value.filter((e) => e.at === i); }
function serialize() {
  return { input: [...input.value], cursor: scur.value, mark: [...mark.value], extras: [...extras.value] };
}
function restore(s) {
  if (!s) return;
  input.value = [...(s.input || [])];
  scur.value = Number(s.cursor) || 0;
  mark.value = [];    // 恢复快照不还原上次的判错标色，进入时保持干净界面
  extras.value = [];
}
defineExpose({ typeWordChar, backspace, paint, markWrong, reset, isCorrect, serialize, restore, answerText });
</script>

<template>
  <div ref="box" class="cells-wrap" style="margin:0;">
    <span v-if="!showSequence" class="cell word-line pure-line" :class="{ current: !submitted }"
          :style="{ '--chars': Math.max(10, answerText().length) }">{{ answerText() }}</span>
    <template v-for="(w, i) in displayWords" v-else :key="i">
      <span v-for="(e, k) in extraAt(i)" :key="'extra-' + i + '-' + k" class="cell word-line wrong"
            :style="{ '--chars': Math.max(3, e.word.length) }">{{ e.word }}</span>
      <span v-if="w.pre" class="punct">{{ w.pre }}</span>
      <span :id="'sc' + i" class="cell word-line"
            :class="[mark[i] || '', !submitted && i === scur ? 'current' : '']"
            :style="{ '--chars': lineChars(i), cursor: 'text' }" @click="focusWord(i)">{{ input[i] }}</span>
      <span v-if="w.suf" class="punct">{{ w.suf }}</span>
    </template>
    <span v-for="(e, i) in extraAt(displayWords.length)" :key="'extra-end-' + i" class="cell word-line wrong"
          :style="{ '--chars': Math.max(3, e.word.length) }">{{ e.word }}</span>
  </div>
</template>
