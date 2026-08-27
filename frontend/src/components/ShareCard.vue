<script setup>
/* 社交分享弹层：统一三张卡片（sprint 成绩 / pk 战报 / badge 徽章）的
 * 预览、PNG 下载与文案复制入口；绘制与文案全部来自 lib/cards.js，
 * 本组件只负责开合状态、画布挂载和操作反馈。 */
import { computed, nextTick, ref, watch } from "vue";
import { PALETTES, currentTheme } from "../lib/poster";
import {
  badgeShareText, paintBadgeCard, paintPkCard, paintSprintCard,
  pkShareText, sprintShareText,
} from "../lib/cards";

const props = defineProps({
  open: { type: Boolean, default: false },
  kind: { type: String, required: true },       // sprint | pk | badge
  payload: { type: Object, required: true },    // 与 cards.js 各 painter 的 m 一致（含 link）
});

const emit = defineEmits(["close"]);

const PAINTER = {
  sprint: paintSprintCard,
  pk: paintPkCard,
  badge: paintBadgeCard,
};
const TEXT = {
  sprint: sprintShareText,
  pk: pkShareText,
  badge: badgeShareText,
};
const FILENAME = { sprint: "冲刺成绩卡", pk: "对战战报", badge: "成就徽章" };

const poster = ref(null);
const copied = ref(false);
const shareText = computed(() => (TEXT[props.kind] || (() => ""))(props.payload));

watch(
  () => [props.open, props.kind, props.payload],
  async () => {
    if (!props.open) return;
    await nextTick();                       // 等 <canvas> 挂回 DOM 再预览
    drawPreview();
  },
  { immediate: false },
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
  <div v-if="open" class="modal share-modal" role="dialog" aria-label="分享卡片"
       @click.self="emit('close')">
    <div class="modal-box share-box">
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
