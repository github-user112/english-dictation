<script setup>
import { onMounted, ref } from "vue";
import { api } from "../lib/core";
import { refreshProfile } from "../lib/profile";
import TreeArt from "./TreeArt.vue";

/* 阶段阶梯与 backend/profile.py 的 TREE_LABELS 保持一致 */
const STAGES = ["种子", "发芽", "幼苗", "成株", "小树", "繁茂", "开花", "硕果"];
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
  <div v-else-if="!p" class="empty loading"><span class="spin" aria-hidden="true"></span><span class="load-text">加载中…</span></div>

  <div v-else class="tree-page">
    <!-- Page Head -->
    <div class="tree-head">
      <div>
        <h1><span class="emoji">🌳</span> 单词树</h1>
        <p>每天浇水，你的词汇之树会长成参天大树！</p>
      </div>
      <div class="head-status">
        <span v-if="p.tree_wilted" class="badge-soft orange">🥀 小树渴坏了</span>
        <span v-else-if="p.tree_needs_water" class="badge-soft orange">💧 今天还没浇水</span>
        <span v-else class="badge green">🌿 {{ p.tree_label }}</span>
      </div>
    </div>

    <!-- Tree Hero -->
    <div class="tree-hero">
      <div class="hero-top">
        <div class="hero-stage-badge">
          <span class="em">{{ p.tree_icon }}</span>
          <span>第 {{ p.tree_stage + 1 }} 阶段 · {{ p.tree_label }}</span>
        </div>
        <div class="hero-day-pill">
          <span class="em">🔥</span>
          <span>连续 {{ p.streak }} 天</span>
        </div>
      </div>

      <!-- Tree Scene -->
      <div class="tree-scene" aria-label="单词树场景">
        <div class="watering-can" v-if="!p.tree_wilted">🚿</div>
        <div class="sun"></div>
        <div class="cloud c1"></div>
        <div class="cloud c2"></div>
        <div class="cloud c3"></div>

        <div class="drop" style="left:28%; animation-delay:0s;"></div>
        <div class="drop" style="left:38%; animation-delay:0.5s;"></div>
        <div class="drop" style="left:48%; animation-delay:1.0s;"></div>
        <div class="drop" style="left:55%; animation-delay:0.3s;"></div>
        <div class="drop" style="left:65%; animation-delay:0.8s;"></div>

        <div class="ground">
          <div class="ground-flowers" v-if="!p.tree_wilted">
            <span class="flower">🌸</span>
            <span class="flower">🌼</span>
            <span class="flower">🌷</span>
            <span class="flower">🌻</span>
            <span class="flower">🌺</span>
            <span class="flower">🌸</span>
            <span class="flower">🌼</span>
          </div>
        </div>

        <div class="tree-svg-wrap">
          <div class="tree-stage" :class="{ wilted: p.tree_wilted, grow: grew }">
            <TreeArt :stage="p.tree_stage" :wilted="p.tree_wilted" :size="200"></TreeArt>
            <transition name="combo-pop"><span v-if="grew" class="tree-grew">长大了！</span></transition>
          </div>
        </div>
      </div>

      <p class="hero-hint">{{ statusLine(p) }}</p>

      <!-- Hero Bottom -->
      <div class="hero-bottom">
        <div class="hero-stats">
          <div class="hero-stat">
            <span class="em">💧</span>
            <span class="v">{{ p.streak }}</span>
            <span class="k">连续天数</span>
          </div>
          <div class="hero-stat">
            <span class="em">📅</span>
            <span class="v">{{ p.total_active_days }}</span>
            <span class="k">累计浇水</span>
          </div>
          <div class="hero-stat">
            <span class="em">🎯</span>
            <span class="v">{{ p.daily_streak }}</span>
            <span class="k">挑战连击</span>
          </div>
          <div class="hero-stat">
            <span class="em">📈</span>
            <span class="v gold">{{ Math.round(p.tree_stage / 7 * 100) }}%</span>
            <span class="k">阶段进度</span>
          </div>
        </div>
        <div class="water-btn-wrap">
          <a href="#/catalog" class="btn big primary">💧 立即浇水</a>
          <a href="#/daily" class="btn big ghost">🎯 今日挑战</a>
        </div>
      </div>
    </div>

    <!-- Stats + Growth Timeline -->
    <div class="tree-row-stats">
      <!-- Stats -->
      <div class="card">
        <div class="card-title"><span class="card-icon">📊</span> 浇水统计</div>
        <div class="tree-stat-grid">
          <div class="stat-tile">
            <span class="em">💧</span>
            <span class="v blue">{{ p.streak }}<small> 天</small></span>
            <span class="k">连续浇水</span>
          </div>
          <div class="stat-tile">
            <span class="em">📅</span>
            <span class="v green">{{ p.total_active_days }}<small> 天</small></span>
            <span class="k">总浇水天数</span>
          </div>
          <div class="stat-tile">
            <span class="em">🎯</span>
            <span class="v orange">{{ p.daily_streak }}<small> 天</small></span>
            <span class="k">每日挑战连击</span>
          </div>
          <div class="stat-tile">
            <span class="em">🌱</span>
            <span class="v gold">{{ p.tree_stage + 1 }} / 8</span>
            <span class="k">成长阶段</span>
          </div>
        </div>
      </div>

      <!-- Growth Timeline -->
      <div class="card">
        <div class="card-title"><span class="card-icon">🌱</span> 成长路线图</div>
        <div class="card-desc">达成条件后树形会进化，每天练习推进一个阶段</div>
        <div class="stage-timeline">
          <div v-for="(label, i) in STAGES" :key="label"
               class="stage-node"
               :class="{ done: i < p.tree_stage, current: i === p.tree_stage, locked: i > p.tree_stage }">
            <div class="stage-line"></div>
            <div class="stage-emoji">
              <TreeArt :stage="i" :size="36"></TreeArt>
            </div>
            <div class="stage-name">{{ label }}</div>
            <div class="stage-info">{{ i === 0 ? 'Day 0' : i === 7 ? 'Day 7+' : 'Day ' + i }}</div>
          </div>
        </div>

        <!-- Stage Detail -->
        <div class="stage-detail-box">
          <span class="em-big">{{ p.tree_icon }}</span>
          <div class="stage-detail-info">
            <div class="title">当前：{{ p.tree_label }} · 第 {{ p.streak }} 天</div>
            <div class="desc">{{ statusLine(p) }}</div>
            <div class="next">
              <template v-if="p.tree_stage < 7">
                💧 再浇 1 天升级到 <b>{{ STAGES[p.tree_stage + 1] }}</b>
              </template>
              <template v-else>已达最高阶段！🎉</template>
            </div>
          </div>
          <a href="#/catalog" class="btn sm primary">💧 继续浇水</a>
        </div>
      </div>
    </div>

    <!-- Weekly History -->
    <div class="card">
      <div class="card-title"><span class="card-icon">📅</span> 本周浇水记录</div>
      <div class="card-desc">每天练习可获得额外 XP 和果实奖励</div>
      <div class="week-bar" aria-label="本周浇水记录">
        <div v-for="(w, i) in p.week" :key="w.day" class="week-col" :title="w.day">
          <span class="week-bar-val">{{ w.active ? '✓' : '' }}</span>
          <div class="week-bar-fill"
               :class="{ today: i === (new Date().getDay() === 0 ? 6 : new Date().getDay() - 1), on: w.active }"
               :style="{ height: w.active ? '72%' : '15%' }"></div>
          <span class="week-bar-label" :class="{ today: i === (new Date().getDay() === 0 ? 6 : new Date().getDay() - 1) }">
            {{ '一二三四五六日'[i] }}
          </span>
        </div>
      </div>
      <div class="week-summary">
        <span class="badge-soft green">{{ p.week.filter(w => w.active).length }} / 7 天活跃</span>
        <span class="badge-soft orange" v-if="p.streak > 0">🔥 连续 {{ p.streak }} 天</span>
        <span class="badge-soft red" v-if="p.tree_wilted">🥀 已枯萎</span>
      </div>
    </div>

    <!-- CTA Banner -->
    <a href="#/catalog" class="banner orange" v-if="!p.today_done">
      <span class="b-icon">🎯</span>
      <div class="b-body">
        <b>今天还没浇水！</b>
        <small>浇水一次 +5 XP，连浇 7 天有惊喜奖励</small>
      </div>
      <span class="b-go">💧 立即浇水</span>
    </a>
    <a href="#/daily" class="banner purple" v-else>
      <span class="b-icon">🎯</span>
      <div class="b-body">
        <b>今天已经浇过水啦</b>
        <small>去做每日挑战，赢取额外 XP 吧！</small>
      </div>
      <span class="b-go">🎯 每日挑战</span>
    </a>
  </div>
</template>
