<script setup>
/* 社交分享弹层：统一 pk 战报 / badge 徽章的预览、PNG 下载与文案复制入口；
 * 绘制与文案全部来自 lib/cards.js。本组件负责开合、画布挂载、操作反馈。 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { PALETTES, currentTheme } from "../lib/poster";
import {
  badgeShareText, paintBadgeCard, paintPkCard, paintWeeklyCard,
  pkShareText, weeklyShareText,
} from "../lib/cards";

const props = defineProps({
  open: { type: Boolean, default: false },
  kind: { type: String, required: true },       // pk | badge | weekly
  payload: { type: Object, required: true },
});

const emit = defineEmits(["close"]);

const PAINTER = { pk: paintPkCard, badge: paintBadgeCard, weekly: paintWeeklyCard };
const TEXT = { pk: pkShareText, badge: badgeShareText, weekly: weeklyShareText };
const FILENAME = { pk: "对战战报", badge: "成就徽章", weekly: "学习周报" };

const poster = ref(null);
const copied = ref(false);
const box = ref(null);
const lastFocused = ref(null);
const shareText = computed(() => (TEXT[props.kind] || (() => ""))(props.payload));

/* ponytail: L3 — watcher 以 payload 对象身份为键会随父组件重渲反复触发；
 * 改为字符串化稳定值，payload 内容不变时不重画。 */
const stableKey = computed(() => props.open ? `${props.kind}:${JSON.stringify(props.payload)}` : "");

watch(
  () => stableKey.value,
  async () => {
    if (!props.open) return;
    await nextTick();
    drawPreview();
  },
  { immediate: false },
);

onMounted(() => {
  window.addEventListener("keydown", onKey);
});
onUnmounted(() => {
  window.removeEventListener("keydown", onKey);
});

function onKey(e) {
  if (e.key === "Escape" && props.open) {
    e.preventDefault();
    emit("close");
    lastFocused.value?.focus?.();
  }
}

function openDialog() {
  if (!props.open) return;
  lastFocused.value = document.activeElement;
  // ponytail: M3 焦点陷阱的最小实现——只把焦点圈在 modal-box 内，
  // 复杂 Tab 轮转对 canvas 分享卡无实际意义（用户只点按钮）。
  document.addEventListener("focusin", trapFocus);
}
function closeDialog() {
  if (props.open) return;
  document.removeEventListener("focusin", trapFocus);
  lastFocused.value?.focus?.();
}
function trapFocus(e) {
  if (box.value && !box.value.contains(e.target)) {
    e.preventDefault();
    box.value.focus({ preventScroll: true });
  }
}

watch(
  () => props.open,
  (o) => o ? nextTick(openDialog) : closeDialog(),
);

function drawPreview() {
  const cv = poster.value;
  const painter = PAINTER[props.kind];
  if (!cv || !painter) return;
  painter(cv, props.payload, 1, PALETTES[currentTheme()]);
}

async function savePng() {
  const painter = PAINTER[props.kind];
  if (!painter) return;
  const off = document.createElement("canvas");
  painter(off, props.payload, 2, PALETTES[currentTheme()]);   // 离屏 dpr=2 全分辨率导出
  if (!off.width) return;
  const a = document.createElement("a");
  a.download = `${FILENAME[props.kind]}-${new Date().toISOString().slice(0, 10)}.png`;
  a.href = off.toDataURL("image/png");
  a.click();
}

async function copyText() {
  try {
    await navigator.clipboard.writeText(shareText.value);
    copied.value = true;
    setTimeout(() => { copied.value = false; }, 2000);
  } catch { /* 剪贴板不可用时文案块始终可见，可手动复制 */ }
}
</script>

<template>
  <div v-if="open" class="modal share-modal" role="dialog" aria-modal="true"
       aria-label="分享卡片" @click.self="emit('close')">
    <div ref="box" class="modal-box share-box" tabindex="-1">
      <h3 class="share-title">{{ FILENAME[kind] }}</h3>
      <canvas ref="poster" class="share-canvas" aria-label="分享卡片预览"></canvas>
      <pre class="share-text" aria-label="分享文本">{{ shareText }}</pre>
      <div class="share-ops">
        <button type="button" class="btn primary" @click="savePng">保存 PNG</button>
        <button type="button" class="btn" @click="copyText">
          {{ copied ? "已复制 ✓" : "复制文案" }}
        </button>
        <button type="button" class="btn ghost" @click="emit('close')">关闭</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.share-box { width: min(94%, 430px); max-height: 92vh; overflow-y: auto; }
.share-title { margin: 0 0 12px; font-size: 18px; }
.share-canvas { width: 100%; border-radius: 14px; display: block; }
.share-text {
  margin-top: 12px; padding: 12px; white-space: pre-wrap; word-break: break-all;
  text-align: left; font-size: 13px; line-height: 1.6;
  background: color-mix(in srgb, var(--bg) 75%, transparent); border-radius: 10px;
}
.share-ops { display: flex; gap: 9px; justify-content: center; flex-wrap: wrap; margin-top: 4px; }
</style>
