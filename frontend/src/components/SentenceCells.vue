<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({ tokens: { type: Object, required: true }, submitted: Boolean,
  feedback: Boolean, practiceMode: { type: String, default: "assisted" } });
const scur = ref(0);
const charPos = ref(0);   // 当前词内的字符光标（0..已输入长度），点击词格/方向键定位
const input = ref([]);
const box = ref(null);
const flash = ref([]);
const mark = ref([]);
const extras = ref([]);
// 与 WordCells 同口径：纯听写模式下提交判分后（有标色）也亮出词序，方便对照错处
const showSequence = computed(() => props.practiceMode !== "pure" || props.feedback || mark.value.some(Boolean));

// 词核字符：字母/数字/下划线/撇号/连字符；其余视为前后标点（pre/suf）。
// 内部含 . , / & : 等字符的缩写词（B.C.、a.m.、2,400、Why/Why）整体保留在 core 中由用户输入。
const words = computed(() =>
  props.tokens.text.split(/\s+/).map((w) => {
    const pre = (w.match(/^[^\w-]+/) || [""])[0];
    const suf = (w.match(/[^\w-]+$/) || [""])[0];
    let core = w.slice(pre.length, suf ? w.length - suf.length : w.length);
    core = core.replace(/_/g, "");  // 下划线可忽略：不要求输入，判定时忽略
    // 纯标点 token（独立的 —、… 等）：渲染为标点、不参与输入与判分。
    // 不参与判分是硬约束——它的 norm(core) 为空，要求作答则永远判不对
    if (!core) return { pre: "", core: w, suf: "", punctOnly: true };
    return { pre, core, suf };
  }));

// 纯标点词槽（归一化后为空）不需作答
function isPunctOnly(i) { return !norm(words.value[i]?.core); }
function firstTypable() {
  let j = 0;
  while (j < words.value.length - 1 && isPunctOnly(j)) j++;
  return j;
}

watch(() => `${props.tokens.id}:${props.tokens.text}`, () => { scur.value = firstTypable(); charPos.value = 0; input.value = []; flash.value = []; mark.value = []; extras.value = []; });

// 判分归一化：忽略大小写与标点，只比字母数字（"Chinese," 与 "Chinese"、"too." 与 "too" 同算对）
const norm = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
scur.value = firstTypable();   // 挂载时句首若是纯标点 token，光标直接落在第一个可输入词（须在 norm 定义后）
function typeWordChar(ch) {
  if (/\s/.test(ch)) {   // 任何空白都算跳格：空格/NBSP/全角空格（IME 组字里常见后两者）
    const typed = norm(input.value[scur.value]);
    const target = norm(words.value[scur.value]?.core);
    if (!typed) {
      jumpTo(scur.value + 1);
      return false;
    }
    if (typed === target) {
      jumpTo(scur.value + 1);
      return false;
    }
    if (props.practiceMode !== "pure") mark.value[scur.value] = "wrong";
    // 整句灌入（IME 组字提交）：错词标红留在原格但照常跳格，不堵后面的词
    if (bulk) jumpTo(scur.value + 1);
    return true;
  }
  if (ch === "_") return;   // 下划线可忽略：输入时跳过，判定时词核已去除下划线
  if (!/^[a-zA-Z0-9_\'\-.,/&:]+$/.test(ch)) return;
  const i = scur.value;
  const w = input.value[i] || "";
  // IME 组字常把句尾标点随词一起提交（"Robert."）：词核已输完且光标在词尾、该字符正是后缀标点 →
  // 当作空格跳词，不进输入，否则词格会被标点撑长（光标在词中间时是在改词，标点照常插入）
  const wd = words.value[i];
  if (wd && charPos.value === w.length && norm(w) === norm(wd.core) && wd.suf.startsWith(ch)) {
    jumpTo(i + 1);
    return false;
  }
  if (w.length >= 30) return;
  const nw = w.slice(0, charPos.value) + ch + w.slice(charPos.value);
  input.value[i] = nw;
  charPos.value++;
  const target = norm(words.value[i]?.core);
  const wrong = target && !target.startsWith(norm(nw));
  if (props.practiceMode !== "pure") mark.value[i] = wrong ? "wrong" : "";
  return props.practiceMode !== "pure" && wrong;
}
// 跳到指定词（越界则停在末词），光标落到该词已输入文本末尾；纯标点词槽不参与输入，自动跳过
function jumpTo(i) {
  let j = Math.min(i, words.value.length - 1);
  while (j < words.value.length - 1 && isPunctOnly(j)) j++;
  while (j > 0 && isPunctOnly(j)) j--;   // 目标及之后全是标点：退回最近的可输入词
  scur.value = j;
  charPos.value = (input.value[scur.value] || "").length;
}
// 整句灌入模式标记：IME 组字/粘贴一次交付整句时，空格跳格不再要求当前词完全正确
let bulk = false;
function typeText(s) {
  bulk = true;
  let wrong = false;
  for (const c of s) wrong = typeWordChar(c) || wrong;
  bulk = false;
  return wrong;
}
function refreshMark(i) {
  if (props.practiceMode === "pure" && !props.submitted) {
    mark.value[i] = "";
    return;
  }
  const typed = norm(input.value[i]);
  const target = norm(words.value[i]?.core);
  mark.value[i] = typed && !target.startsWith(typed) ? "wrong" : "";
}
function backspace() {
  const w = input.value[scur.value] || "";
  if (charPos.value > 0) {   // 删光标前一个字符（光标在词尾时等价于旧的删末尾）
    input.value[scur.value] = w.slice(0, charPos.value - 1) + w.slice(charPos.value);
    charPos.value--;
    refreshMark(scur.value);
    return;
  }
  if (scur.value > 0) {   // 光标在词首：退回上一可输入词并删其尾字符（跳过纯标点槽，沿用旧行为）
    let j = scur.value - 1;
    while (j > 0 && isPunctOnly(j)) j--;
    if (isPunctOnly(j)) return;
    scur.value = j;
    input.value[scur.value] = (input.value[scur.value] || "").slice(0, -1);
    charPos.value = (input.value[scur.value] || "").length;
    refreshMark(scur.value);
  }
}
function cell(i) { return box.value?.querySelector("#sc" + i); }
function focusWord(i, ev) {
  if (props.submitted || props.feedback) return;
  scur.value = i;
  charPos.value = clickOffset(ev, i);
}
// 由点击坐标算词内字符偏移：优先 caretRangeFromPoint（Chrome/Safari），
// Firefox 用 caretPositionFromPoint，都不支持或点在词外则落到词首/词尾
function clickOffset(ev, i) {
  const w = input.value[i] || "";
  if (!ev || !w) return w.length;
  const el = cell(i);
  if (!el) return w.length;
  const doc = el.ownerDocument;
  let container, offset;
  if (doc.caretRangeFromPoint) {
    const r = doc.caretRangeFromPoint(ev.clientX, ev.clientY);
    if (!r) return w.length;
    container = r.startContainer; offset = r.startOffset;
  } else if (doc.caretPositionFromPoint) {
    const p = doc.caretPositionFromPoint(ev.clientX, ev.clientY);
    if (!p) return w.length;
    container = p.offsetNode; offset = p.offset;
  } else return w.length;
  if (container.nodeType === 3) {   // 文本节点：整词文本，或当前词拆分后的 .cb/.ca 片段
    const parent = container.parentNode;
    if (parent !== el && parent.classList?.contains("ca")) {
      return Math.min((el.querySelector(".cb")?.textContent.length || 0) + offset, w.length);
    }
    return Math.min(offset, w.length);   // .cb 或未拆分的整词，offset 即词内偏移
  }
  // 点在元素上（字符缝隙/包装元素）：按水平位置归到最近的词首/词尾/拆分缝
  if (container === el) {
    const cb = el.querySelector(".cb");
    if (cb) return offset === 0 ? 0 : offset === 1 ? cb.textContent.length : w.length;
    return offset === 0 ? 0 : w.length;
  }
  if (container.classList?.contains("ca")) return w.length;
  if (container.classList?.contains("cb")) return offset ? container.textContent.length : 0;
  return w.length;   // 其余情况（落在装饰元素上）：光标落到词尾
}
function moveCursor(d) {
  if (props.submitted || props.feedback) return;
  const len = (input.value[scur.value] || "").length;
  const p = charPos.value + d;
  if (p < 0) {
    if (scur.value > 0) jumpTo(scur.value - 1);
    return;
  }
  if (p > len) {
    if (scur.value < words.value.length - 1) {   // 移到下一可输入词（跳过纯标点槽）
      let j = scur.value + 1;
      while (j < words.value.length - 1 && isPunctOnly(j)) j++;
      if (!isPunctOnly(j)) { scur.value = j; charPos.value = 0; }
    }
    return;
  }
  charPos.value = p;
}
function paint() {
  const t = words.value.map((w) => norm(w.core));
  mark.value = t.map((w, i) => norm(input.value[i]) === w ? "right" : "wrong");
}
function markWrong() {
  // 逐词按位比对，错误的词留在原位标红，不移动到其他横线
  const target = words.value.map((w) => norm(w.core));
  const marks = target.map((w, i) => {
    const typed = norm(input.value[i]);
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
  scur.value = firstTypable();
  charPos.value = 0;
  input.value = [];
  flash.value = [];
  mark.value = [];
  extras.value = [];
  box.value?.querySelectorAll(".cell").forEach((el) => el.classList.remove("right", "wrong", "miss"));
}
function isCorrect() {
  const t = words.value.map((w) => norm(w.core));
  // 纯标点槽（target 为空）不需作答：只数非空 target，作答里纯标点槽的输入（若有）也不算占用
  return input.value.filter((v, i) => v && t[i] !== "").length === t.filter(Boolean).length &&
    t.every((w, i) => !w || norm(input.value[i]) === w);
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
  return { input: [...input.value], cursor: scur.value, charPos: charPos.value, mark: [...mark.value], extras: [...extras.value] };
}
function restore(s) {
  if (!s) return;
  input.value = [...(s.input || [])];
  scur.value = Number(s.cursor) || 0;
  if (isPunctOnly(scur.value)) scur.value = firstTypable();   // 老快照可能指在纯标点槽上
  // 老快照没有 charPos 字段：落到词尾，与旧版行为一致
  const len = (input.value[scur.value] || "").length;
  charPos.value = s.charPos === undefined ? len : Math.min(Number(s.charPos) || 0, len);
  mark.value = [];    // 恢复快照不还原上次的判错标色，进入时保持干净界面
  extras.value = [];
}
defineExpose({ typeWordChar, typeText, backspace, paint, markWrong, reset, isCorrect, serialize, restore, answerText, focusWord, moveCursor });
</script>

<template>
  <div ref="box" class="cells-wrap" :class="{ err: feedback }" style="margin:0;">
    <span v-if="!showSequence" class="cell word-line pure-line" :class="{ current: !submitted && !feedback }"
          :style="{ '--chars': Math.max(10, answerText().length) }">{{ answerText() }}</span>
    <template v-for="(w, i) in displayWords" v-else :key="i">
      <span v-for="(e, k) in extraAt(i)" :key="'extra-' + i + '-' + k" class="cell word-line wrong"
            :style="{ '--chars': Math.max(3, e.word.length) }">{{ e.word }}</span>
      <span v-if="w.pre" class="punct">{{ w.pre }}</span>
      <span v-if="w.punctOnly" class="punct">{{ w.core }}</span>
      <span v-else :id="'sc' + i" class="cell word-line"
            :class="[mark[i] || '', !submitted && !feedback && i === scur ? 'current has-midcaret' : '']"
            :style="{ '--chars': lineChars(i), cursor: 'text' }" @click="focusWord(i, $event)"><template v-if="!submitted && !feedback && i === scur"><span class="cb">{{ (input[i] || "").slice(0, charPos) }}</span><i class="midcaret" aria-hidden="true"></i><span class="ca">{{ (input[i] || "").slice(charPos) }}</span></template><template v-else>{{ input[i] }}</template></span>
      <span v-if="w.suf" class="punct">{{ w.suf }}</span>
    </template>
    <span v-for="(e, i) in extraAt(displayWords.length)" :key="'extra-end-' + i" class="cell word-line wrong"
          :style="{ '--chars': Math.max(3, e.word.length) }">{{ e.word }}</span>
  </div>
</template>
