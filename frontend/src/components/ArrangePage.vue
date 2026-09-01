<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, playUrl, sndRight, sndWrong, stopAudio } from "../lib/core";

const phase = ref("start");    // start | play | done
const sentLists = ref([]);
const list = ref("nc1");
const lesson = ref("");   // 目录页带 ?lesson= 进来时聚焦那一课
const questions = ref([]);
const idx = ref(0);
const placed = ref([]);        // 已排入答案区的词块下标（display 数组的下标）
const feedback = ref(null);    // { right, text }
const score = ref(0);
const loadError = ref("");
const submitting = ref(false);
let mounted = true;
let advanceTimer = null;

const q = computed(() => questions.value[idx.value] || null);
const remaining = computed(() => {
  if (!q.value) return [];
  return q.value.chunks.map((text, i) => ({ text, i })).filter((c) => !placed.value.includes(c.i));
});
const complete = computed(() => q.value && placed.value.length === q.value.chunks.length);

const props = defineProps({ params: { type: Object, default: null } });

onMounted(async () => {
  list.value = props.params?.get("list") || list.value;
  lesson.value = props.params?.get("lesson") || "";
  try {
    const d = await api("/lists");
    if (!mounted) return;
    sentLists.value = (d.lists || []).filter((l) => l.type === "sentences");
    if (!sentLists.value.some((l) => l.key === list.value)) {
      list.value = sentLists.value[0]?.key || "nc1";
    }
  } catch { /* 开始时再试 */ }
});

onUnmounted(() => {
  mounted = false;
  stopAudio();
  if (advanceTimer) clearTimeout(advanceTimer);
});

async function start() {
  loadError.value = "";
  try {
    const qs = new URLSearchParams({ list: list.value, n: 6 });
    if (lesson.value) qs.set("lesson", lesson.value);
    const d = await api(`/arrange/session?${qs}`);
    questions.value = d.questions || [];
    if (!questions.value.length) return;
    idx.value = 0; score.value = 0;
    phase.value = "play";
    replay();
  } catch (err) {
    loadError.value = err.message || "出题失败";
  }
}

function resetLine() {
  placed.value = [];
  feedback.value = null;
  submitting.value = false;
}

function replay() {
  if (q.value) playUrl(q.value.audio);
}

function pick(i) {
  if (feedback.value || placed.value.includes(i)) return;
  placed.value = [...placed.value, i];
}

function unpick(pos) {
  if (feedback.value) return;
  placed.value = placed.value.filter((_, p) => p !== pos);
}

async function submit() {
  if (!complete.value || feedback.value || submitting.value) return;
  submitting.value = true;
  const attemptId = (() => {
    const uuid = globalThis.crypto?.randomUUID?.();
    return uuid ? uuid.replaceAll("-", "") : `${Date.now()}${Math.random().toString(36).slice(2)}`;
  })();
  try {
    const d = await api("/arrange/answer", {
      method: "POST",
      body: JSON.stringify({ list: list.value, id: q.value.id, order: placed.value, attempt_id: attemptId }),
    });
    feedback.value = d;
    if (d.right) {
      score.value++;
      sndRight();
      advanceTimer = setTimeout(next, 1100);   // 答对稍作停留自动下一句
    } else {
      sndWrong();
    }
  } catch (err) {
    loadError.value = err.message || "提交失败，请重试";
    submitting.value = false;
  }
}

function next() {
  if (advanceTimer) { clearTimeout(advanceTimer); advanceTimer = null; }
  if (idx.value + 1 >= questions.value.length) {
    stopAudio();
    phase.value = "done";
    window.dispatchEvent(new CustomEvent("profile-changed"));
    return;
  }
  idx.value++;
  resetLine();
  replay();
}

function goCatalog() { location.hash = "#/catalog"; }
</script>

<template>
  <div class="arrange-page">
    <!-- 开始页 -->
    <div v-if="phase === 'start'" class="empty">
      <div style="font-size:44px;" aria-hidden="true">🧩</div>
      <div style="font-size:20px;font-weight:700;margin-bottom:10px;">听音排句</div>
      <p>听一句英文，把打乱的词块点回正确顺序——练的是语序耳感。</p>
      <p>每句一次机会：拼对得满额经验，拼错看一眼原句再进下一题。</p>
      <div class="match-setup">
        <select v-model="list" class="match-select" aria-label="选择句子素材">
          <option v-for="l in sentLists" :key="l.key" :value="l.key">{{ l.title }}</option>
        </select>
      </div>
      <p v-if="loadError" role="alert" style="color:var(--red);">{{ loadError }}</p>
      <div class="controls" style="margin-top:16px;">
        <button class="btn primary big" @click="start">🧩 开始排句</button>
        <button class="btn ghost" @click="goCatalog">返回素材库</button>
      </div>
    </div>

    <!-- 答题中 -->
    <template v-else-if="phase === 'play' && q">
      <div class="practice-top">
        <span class="progress-line">第 {{ idx + 1 }}/{{ questions.length }} 句 · 得分 {{ score }}</span>
        <button class="btn ghost sm" aria-label="重播句子" @click="replay">🔊 重播</button>
      </div>
      <div class="practice-card arrange-card">
        <p v-if="q.zh" class="arrange-zh" aria-label="中文提示">{{ q.zh }}</p>
        <!-- 答案区：点已放的词块取回 -->
        <div class="slot-line" :class="{ filled: placed.length }" aria-label="答案区"
             :aria-description="`已放 ${placed.length}/${q.chunks.length} 个词块`">
          <template v-if="placed.length">
            <button v-for="(pi, pos) in placed" :key="`${pi}-${pos}`" class="chunk in-slot"
                    :aria-label="`取回词块 ${q.chunks[pi]}`" @click="unpick(pos)">
              {{ q.chunks[pi] }}
            </button>
          </template>
          <small v-else>点击下方词块，按听到的顺序排到这里</small>
        </div>
        <!-- 词块池 -->
        <div class="chunk-pool" aria-label="词块区">
          <button v-for="c in remaining" :key="c.i" class="chunk"
                  :aria-label="`选择词块 ${c.text}`" @click="pick(c.i)">{{ c.text }}</button>
        </div>
        <div id="answer-line" aria-live="polite">
          <span v-if="feedback?.right" style="color:var(--green);">✔ 拼对了！</span>
          <span v-else-if="feedback" style="color:var(--red);">
            ✗ 正确语序：<b class="show-word">{{ feedback.text }}</b></span>
        </div>
        <div class="controls">
          <button class="btn primary" :disabled="!complete || Boolean(feedback)"
                  aria-label="提交这句" @click="submit">提交这句</button>
          <button class="btn ghost" :disabled="!placed.length || Boolean(feedback)"
                  aria-label="清空重排" @click="placed = []">清空重排</button>
          <button v-if="feedback && !feedback.right" class="btn primary" @click="next">下一句 →</button>
        </div>
        <div class="hint">🔊 随时可重播 · 点答案区里的词块可以取回 · 拼对自动下一句</div>
      </div>
      <p v-if="loadError" role="alert" style="color:var(--red);text-align:center;">{{ loadError }}</p>
    </template>

    <!-- 结算 -->
    <div v-else class="empty">
      <div style="font-size:40px;" aria-hidden="true">{{ score === questions.length ? '🎉' : '🧩' }}</div>
      <div style="font-size:20px;font-weight:700;margin-bottom:10px;">
        {{ score === questions.length ? '全部拼对！' : '排句完成' }}</div>
      <p>拼对 {{ score }} / {{ questions.length }} 句</p>
      <div class="controls" style="margin-top:16px;">
        <button class="btn primary big" @click="start">再来一组</button>
        <button class="btn ghost big" @click="goCatalog">返回素材库</button>
      </div>
    </div>
  </div>
</template>
