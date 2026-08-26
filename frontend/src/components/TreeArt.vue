<script setup>
/* 单词树手绘 SVG：8 个生长阶段连续演变（与 backend tree_stage 对齐），
   部件按登场阈值依次弹出；枯萎时整树去饱和、花果落尽、树冠低垂。
   颜色全部走主题 token，明暗主题自动成立。 */
const props = defineProps({
  stage: { type: Number, default: 0 },   // 0-7
  wilted: { type: Boolean, default: false },
  size: { type: Number, default: 120 },
});
const s = props.stage;
</script>

<template>
  <svg class="tree-art" :class="{ wilted }" :width="size" :height="size"
       viewBox="0 0 120 120" fill="none" role="img"
       :aria-label="`单词树生长阶段 ${Math.min(Math.max(s, 0), 7) + 1} / 8`">
    <!-- 土壤 -->
    <ellipse cx="60" cy="103" rx="30" ry="6" class="soil"></ellipse>
    <path d="M40 101 q2.5 -5 5 0" class="grass" :class="{ on: s >= 2 }" style="--d:.05s"></path>
    <path d="M76 101 q2.5 -5 5 0" class="grass" :class="{ on: s >= 3 }" style="--d:.1s"></path>

    <!-- 阶段 0：土里的种子（破土后淡出） -->
    <g class="gp seed" :class="{ on: s < 1 }">
      <ellipse cx="60" cy="96" rx="6.5" ry="8.5" transform="rotate(-18 60 96)" fill="#c9914f"></ellipse>
      <path d="M56.5 92.5 q3.5 -2.5 7 -.5" stroke="#a9702f" stroke-width="1.4" stroke-linecap="round"></path>
    </g>

    <!-- 幼苗期（1-3 阶段），长成小树后让位给树干 -->
    <g class="seedling">
      <path d="M60 101 C59 96 59 93 60 89" class="stem gp" :class="{ on: s >= 1 && s < 4 }"></path>
      <ellipse cx="55.6" cy="88.2" rx="4.6" ry="2.7" transform="rotate(-36 55.6 88.2)"
               class="leaf gp" :class="{ on: s >= 1 && s < 4 }" style="--d:.08s"></ellipse>
      <ellipse cx="64.4" cy="88.2" rx="4.6" ry="2.7" transform="rotate(36 64.4 88.2)"
               class="leaf gp" :class="{ on: s >= 1 && s < 4 }" style="--d:.16s"></ellipse>
      <path d="M60 90 C60 84 60 79 60 72" class="stem gp" :class="{ on: s >= 2 && s < 4 }" style="--d:.1s"></path>
      <ellipse cx="53.6" cy="83.6" rx="6.2" ry="3.1" transform="rotate(-32 53.6 83.6)"
               class="leaf gp" :class="{ on: s >= 2 && s < 4 }" style="--d:.2s"></ellipse>
      <ellipse cx="66.4" cy="83.6" rx="6.2" ry="3.1" transform="rotate(32 66.4 83.6)"
               class="leaf gp" :class="{ on: s >= 2 && s < 4 }" style="--d:.28s"></ellipse>
      <path d="M60 73 C60 68 60 64 60 60" class="stem gp" :class="{ on: s >= 3 && s < 4 }" style="--d:.15s"></path>
      <ellipse cx="53" cy="75.5" rx="6.6" ry="3.4" transform="rotate(-28 53 75.5)"
               class="leaf gp" :class="{ on: s >= 3 && s < 4 }" style="--d:.26s"></ellipse>
      <ellipse cx="67" cy="75.5" rx="6.6" ry="3.4" transform="rotate(28 67 75.5)"
               class="leaf gp" :class="{ on: s >= 3 && s < 4 }" style="--d:.34s"></ellipse>
      <ellipse cx="60" cy="63.5" rx="3" ry="5" class="leaf gp" :class="{ on: s >= 3 && s < 4 }" style="--d:.44s"></ellipse>
    </g>

    <!-- 树干与树枝（4 阶段起） -->
    <path d="M57.2 102 C58.2 88 58.5 74 59.3 60 L60.7 60 C61.5 74 61.8 88 62.8 102 Z"
          class="trunk gp" :class="{ on: s >= 4 }" style="--d:.05s"></path>
    <path d="M60 68 C54.5 64 50.5 60.5 47.5 56.5" class="branch gp" :class="{ on: s >= 5 }" style="--d:.12s"></path>
    <path d="M60 68 C65.5 64 69.5 60.5 72.5 56.5" class="branch gp" :class="{ on: s >= 5 }" style="--d:.18s"></path>

    <!-- 树冠：4 阶段主团，5 阶段铺满，随风轻摆 -->
    <g class="canopy" :class="{ on: s >= 4 }">
      <circle cx="60" cy="48" r="15" class="c-main gp" :class="{ on: s >= 4 }" style="--d:.12s"></circle>
      <ellipse cx="46.5" cy="55" rx="9.5" ry="9" class="c-main gp" :class="{ on: s >= 5 }" style="--d:.2s"></ellipse>
      <ellipse cx="73.5" cy="55" rx="9.5" ry="9" class="c-main gp" :class="{ on: s >= 5 }" style="--d:.28s"></ellipse>
      <ellipse cx="60" cy="36.5" rx="10.5" ry="10" class="c-main gp" :class="{ on: s >= 5 }" style="--d:.36s"></ellipse>
      <circle cx="52.5" cy="42" r="6" class="c-light gp" :class="{ on: s >= 5 }" style="--d:.42s"></circle>
    </g>

    <!-- 6 阶段开花（枯萎时落尽） -->
    <g v-for="(f, i) in [[49, 45], [70.5, 41.5], [60, 57], [76, 52], [45, 55.5]]" :key="`f${i}`"
       class="flower gp" :class="{ on: s >= 6 && !wilted }" :style="{ '--d': `${.3 + i * .07}s` }">
      <circle :cx="f[0]" :cy="f[1]" r="2.7" class="petal"></circle>
      <circle :cx="f[0]" :cy="f[1]" r="1" class="heart"></circle>
    </g>

    <!-- 7 阶段结果 -->
    <g v-for="(a, i) in [[52.5, 49.5], [69, 45.5], [60.5, 64], [75.5, 58.5]]" :key="`a${i}`"
       class="fruit gp" :class="{ on: s >= 7 && !wilted }" :style="{ '--d': `${.35 + i * .08}s` }">
      <circle :cx="a[0]" :cy="a[1]" r="3.3" class="apple"></circle>
      <circle :cx="a[0] - 1" :cy="a[1] - 1" r=".9" class="shine"></circle>
      <ellipse :cx="a[0] + 2" :cy="a[1] - 3.4" rx="1.8" ry=".9"
               :transform="`rotate(-30 ${a[0] + 2} ${a[1] - 3.4})`" fill="var(--green)"></ellipse>
    </g>
  </svg>
</template>

<style scoped>
.tree-art { display: block; overflow: visible; }
.tree-art.wilted { filter: saturate(.3) brightness(.82); }

/* 通用生长弹入：以自身包围盒为中心缩放，--d 做部件间的错峰 */
.tree-art .gp {
  opacity: 0; transform: scale(.5);
  transform-box: fill-box; transform-origin: center;
  transition: opacity var(--dur-3) var(--ease-out), transform var(--dur-3) var(--ease-spring);
  transition-delay: var(--d, 0s);
}
.tree-art .gp.on { opacity: 1; transform: none; }

.tree-art .soil { fill: color-mix(in srgb, var(--green) 16%, var(--panel3)); }
.tree-art .grass { stroke: var(--green); stroke-width: 2; stroke-linecap: round; opacity: 0; transition: opacity var(--dur-3); }
.tree-art .grass.on { opacity: .55; }
.tree-art .stem { stroke: var(--green); stroke-width: 3; stroke-linecap: round; }
.tree-art .leaf { fill: var(--green); }
.tree-art .trunk, .tree-art .branch { fill: #8a5f3f; stroke: #8a5f3f; }
.tree-art .branch { fill: none; stroke-width: 3; stroke-linecap: round; }
.tree-art .c-main { fill: var(--green); }
.tree-art .c-light { fill: #fff; fill-opacity: .14; }   /* fill-opacity：不被 .gp.on 的 opacity 覆盖 */
.tree-art .petal { fill: var(--accent); }
.tree-art .heart { fill: var(--panel); }
.tree-art .apple { fill: var(--red); }
.tree-art .shine { fill: #fff; opacity: .55; }

/* 枯萎：花果落尽、树冠低垂、幼苗耷拉；摆动动画让位给下垂位移 */
.tree-art.wilted .canopy { animation: none; transform: translateY(3.5px); transition: transform var(--dur-4) var(--ease-out); }
.tree-art.wilted .seedling { transform: rotate(-3deg); transform-origin: 60px 101px; transition: transform var(--dur-4) var(--ease-out); }

/* 树冠随风轻摆（prefers-reduced-motion 全局规则自动覆盖） */
.tree-art .canopy { transform-box: fill-box; transform-origin: 50% 100%; animation: tree-sway 6s var(--ease-inout) infinite; }
@keyframes tree-sway { 0%, 100% { transform: rotate(0deg); } 50% { transform: rotate(1.6deg); } }
</style>
