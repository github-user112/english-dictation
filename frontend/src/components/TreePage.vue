<script setup>
import { onMounted, ref } from "vue";
import { api } from "../lib/core";
import { refreshProfile } from "../lib/profile";

/* 阶段阶梯与 backend/profile.py 的 TREE_ICONS/TREE_LABELS 保持一致 */
const STAGES = [
  { icon: "🌰", label: "种子" }, { icon: "🌱", label: "发芽" },
  { icon: "🌿", label: "幼苗" }, { icon: "🪴", label: "成株" },
  { icon: "🌳", label: "小树" }, { icon: "🌳", label: "繁茂" },
  { icon: "🌸", label: "开花" }, { icon: "🍎", label: "硕果" },
];
const SEEN_KEY = "dict_tree_stage_v1";

const p = ref(null);
const error = ref("");
const grew = ref(false);   // 本次进来比上次记录的阶段更高：播长大动画

async function load() {
  error.value = "";
  try {
    const d = await api("/profile");
    p.value = d;
    const seen = Number(localStorage.getItem(SEEN_KEY) || "0");
    if (d.tree_stage > seen && seen > 0) grew.value = true;   // 首访静默落库
    localStorage.setItem(SEEN_KEY, String(Math.max(seen, d.tree_stage)));
    refreshProfile(true);
  } catch (err) {
    error.value = err.message || "加载失败";
  }
}

onMounted(load);

function statusLine(d) {
  if (d.tree_wilted) return "小树渴坏了——今天练一点，它就会醒过来。";
  if (d.tree_needs_water) return "今天还没浇水：听几个词、完成每日挑战都算浇水。";
  if (d.today_done) return "今天已经浇过水啦，小树很滋润。";
  return "开始今天的第一次练习吧。";
}
</script>

<template>
  <div v-if="error" class="empty" role="alert"><p>{{ error }}</p><button class="btn primary" @click="load">重试</button></div>
  <div v-else-if="!p" class="empty">加载中…</div>

  <div v-else class="tree-page">
    <div class="page-heading compact">
      <span class="eyebrow">WORD TREE</span>
      <h1>你的单词树<em style="font-style:normal;color:var(--accent-strong)">· {{ p.tree_label }}</em></h1>
      <p>每一次练习都是浇水；连续保持，它就会一路长到硕果累累。</p>
    </div>

    <div class="practice-card tree-card">
      <div class="tree-stage" :class="{ wilted: p.tree_wilted, grow: grew }"
           role="img" :aria-label="`单词树阶段：${p.tree_label}`">
        <span class="tree-icon">{{ p.tree_icon }}</span>
        <transition name="combo-pop"><span v-if="grew" class="tree-grew">长大了！</span></transition>
      </div>
      <p class="hint">{{ statusLine(p) }}</p>

      <!-- 七日活跃点阵（周一起） -->
      <div class="tree-week" aria-label="近七天活跃情况">
        <span v-for="(w, i) in p.week" :key="w.day" class="week-dot"
              :class="{ on: w.active }" :title="w.day">
          <i>{{ '一二三四五六日'[i] }}</i>
        </span>
      </div>

      <div class="stat-cards tree-stats">
        <div class="stat-card"><div class="num">{{ p.streak }}<small> 天</small></div><div class="lab">连续活跃</div></div>
        <div class="stat-card"><div class="num">{{ p.total_active_days }}<small> 天</small></div><div class="lab">累计浇水</div></div>
        <div class="stat-card"><div class="num">{{ p.daily_streak }}<small> 天</small></div><div class="lab">每日挑战连击</div></div>
      </div>
    </div>

    <!-- 阶段阶梯 -->
    <div class="tree-ladder" aria-hidden="true">
      <span v-for="(s, i) in STAGES" :key="s.label" class="ladder-node"
            :class="{ reached: i <= p.tree_stage, current: i === p.tree_stage }">
        <b>{{ s.icon }}</b><small>{{ s.label }}</small>
      </span>
    </div>

    <div class="controls" style="margin-top:18px;">
      <a class="btn primary big" href="#/catalog">去练习浇水</a>
      <a class="btn ghost big" href="#/daily">今日挑战</a>
    </div>
  </div>
</template>
