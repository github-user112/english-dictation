<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({ tokens: { type: Object, required: true }, submitted: Boolean });
const wcur = ref(0);
const input = ref([]);
const box = ref(null);

const refTokens = computed(() =>
  [...props.tokens.text].map((c) => ({ type: /[a-zA-Z]/.test(c) ? "letter" : "punct", text: c })));

watch(() => props.tokens.text, () => { wcur.value = 0; input.value = []; });

function letterIdxs() {
  const out = [];
  refTokens.value.forEach((t, i) => { if (t.type === "letter") out.push(i); });
  return out;
}
function typeLetter(ch) {
  if (!/[a-zA-Z]/.test(ch)) return;
  const ids = letterIdxs();
  if (wcur.value >= ids.length) return;
  input.value[ids[wcur.value]] = ch;
  wcur.value++;
}
function backspace() {
  if (wcur.value <= 0) return;
  wcur.value--;
  input.value[letterIdxs()[wcur.value]] = "";
}
function paint() {
  refTokens.value.forEach((t, i) => {
    if (t.type !== "letter") return;
    const el = box.value.children[i];
    if (!el) return;
    const mine = (input.value[i] || "").toLowerCase();
    const ok = mine === t.text.toLowerCase();
    el.classList.add(ok ? "right" : "wrong");
    if (!ok) el.textContent = t.text;
  });
}
function isCorrect() {
  return refTokens.value.every((t, i) => t.type === "punct" ||
    (input.value[i] || "").toLowerCase() === t.text.toLowerCase());
}
defineExpose({ typeLetter, backspace, paint, isCorrect });
</script>

<template>
  <div ref="box" class="cells-wrap" style="margin:0;">
    <span v-for="(t, i) in refTokens" :key="i" class="cell"
          :class="t.type === 'punct' ? 'fixed' : ''">{{ t.type === 'punct' ? t.text : input[i] }}</span>
  </div>
</template>