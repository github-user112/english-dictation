<script setup>
import { computed, onMounted, ref } from "vue";
import { api } from "../lib/core";

const stats = ref(null);

onMounted(async () => { stats.value = await api("/stats"); });

const last14 = computed(() => {
  if (!stats.value) return [];
  const days = new Map((stats.value.days || []).map((d) => [d.day, d]));
  const out = [];
  for (let i = 13; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
    const row = days.get(d);
    out.push({ day: d.slice(5), total: row ? row.right + row.wrong : 0 });
  }
  return out;
});
const maxDay = computed(() => Math.max(1, ...last14.value.map((d) => d.total)));
</script>

<template>
  <div v-if="!stats" class="empty">加载中…</div>
  <div v-else>
    <div class="stat-cards">
      <div class="stat-card"><div class="num">{{ stats.streak }}</div><div class="lab">连续打卡(天)</div></div>
      <div class="stat-card"><div class="num">{{ stats.total_right }}</div><div class="lab">累计答对</div></div>
      <div class="stat-card"><div class="num">{{ stats.total_wrong }}</div><div class="lab">累计答错</div></div>
      <div class="stat-card"><div class="num">{{ stats.wrong_words }}</div><div class="lab">错词本</div></div>
    </div>
    <div class="section-title">最近 14 天</div>
    <div class="stat-card" style="padding:14px 10px 26px;">
      <div class="bars">
        <div v-for="d in last14" :key="d.day" class="bar">
          <div class="fill" :style="{height: (d.total / maxDay * 100) + '%'}"></div>
          <div class="day">{{ d.day }}</div>
        </div>
      </div>
    </div>
  </div>
</template>