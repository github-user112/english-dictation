<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, playUrl, sndRight, sndWrong, stopAudio, todayNextStep, goTodayStep } from "../lib/core";

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
const fromToday = ref(false);   // 今日动线入口带 from=today：自动开跑，结算页给"下一关"
const nextLoading = ref(false);
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
  fromToday.value = props.params?.get("from") === "today";
  try {
    const d = await api("/lists");
    if (!mounted) return;
    sentLists.value = (d.lists || []).filter((l) => l.type === "sentences");
    if (!sentLists.value.some((l) => l.key === list.value)) {
      list.value = sentLists.value[0]?.key || "nc1";
    }
  } catch { /* 开始时再试 */ }
  if (fromToday.value) start();   // 动线串联：参数已带齐，跳过开始页
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
  if (complete.value) submit();   // 词块放满即判对错，不用再点提交
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
function goLists() { location.hash = "#/lists"; }
async function goNextStep() {
  if (nextLoading.value) return;
  nextLoading.value = true;
  const s = await todayNextStep("arrange");
  if (mounted) goTodayStep(s);
}
</script>

<template>
  <div class="arrange-page">

    <!-- ============ 开始页 ============ -->
    <div v-if="phase === 'start'" class="arrange-start">
      <div class="start-card">
        <div class="arena-bar"></div>
        <div class="start-inner">
          <div class="start-head">
            <span class="start-ic" aria-hidden="true">🧩</span>
            <div class="start-copy">
              <h1 class="start-title">听音排句</h1>
              <p class="start-sub">听一句英文，把打乱的词块点回正确语序</p>
            </div>
          </div>

          <p class="start-desc">练的是<b>语序耳感</b>：先听清句子的停顿与语调节奏，再按顺序点词块拼回去。每句一次机会——拼对得满额经验，拼错看一眼原句再进下一题。</p>

          <div class="start-rules">
            <div class="rule-item">
              <span class="rule-ic" aria-hidden="true">🔊</span>
              <div class="rule-body"><b>点播放听句子</b><small>绿色大圆按钮可反复重播</small></div>
            </div>
            <div class="rule-item">
              <span class="rule-ic" aria-hidden="true">🧩</span>
              <div class="rule-body"><b>按语序点词块</b><small>点答案区里的词块可以取回</small></div>
            </div>
            <div class="rule-item">
              <span class="rule-ic" aria-hidden="true">✅</span>
              <div class="rule-body"><b>放满自动判对错</b><small>拼对进下一句，拼错看原句</small></div>
            </div>
          </div>

          <div class="match-setup">
            <label class="match-label" for="arrange-list">句子素材</label>
            <select id="arrange-list" v-model="list" class="match-select form-select"
                    aria-label="选择句子素材">
              <option v-for="l in sentLists" :key="l.key" :value="l.key">{{ l.title }}</option>
            </select>
          </div>

          <p v-if="loadError" role="alert" class="start-error">{{ loadError }}</p>

          <div class="controls start-controls">
            <button class="btn primary big" @click="start">🧩 开始排句</button>
            <button class="btn ghost big" @click="goLists">返回素材库</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ============ 答题中 ============ -->
    <template v-else-if="phase === 'play' && q">

      <!-- 顶部进度条 -->
      <div class="arrange-strip">
        <div class="as-qcount"><span class="num">{{ idx + 1 }}</span>/{{ questions.length }}</div>
        <div class="as-progress" role="progressbar" aria-label="排句进度"
             :aria-valuenow="idx" :aria-valuemin="0" :aria-valuemax="questions.length">
          <div v-for="n in questions.length" :key="n" class="as-seg"
               :class="{ done: n <= idx, current: n === idx + 1 }"></div>
        </div>
        <div class="as-score">
          <span class="badge-soft green">✓ 答对 {{ score }} 句</span>
        </div>
      </div>

      <div class="arrange-grid">

        <!-- 主区 -->
        <div class="arena">
          <div class="arena-bar"></div>
          <div class="arena-inner">

            <div class="arena-head">
              <div class="ah-left">
                <div class="qnum"><span class="ic" aria-hidden="true">🎯</span> 第 {{ idx + 1 }}/{{ questions.length }} 句</div>
                <div class="badge-soft blue"><span aria-hidden="true">🔀</span> 听音排句</div>
              </div>
              <div class="badge-soft gold"><span aria-hidden="true">🧩</span> {{ q.chunks.length }} 个词块</div>
            </div>

            <p v-if="q.zh" class="arrange-zh" aria-label="中文提示">
              <span class="zh-ic" aria-hidden="true">💬</span>
              <span class="zh-text">{{ q.zh }}</span>
            </p>

            <div class="audio-player">
              <button class="audio-play" aria-label="重播句子" @click="replay">
                <span class="ap-ic" aria-hidden="true">▶</span>
              </button>
              <div class="audio-body">
                <div class="audio-title"><span aria-hidden="true">🎧</span> 点击播放，听清语序</div>
                <div class="audio-meta">
                  <span>🔊 英文朗读</span><i class="dot"></i><span>可反复播放</span>
                </div>
              </div>
              <div class="audio-wave" aria-hidden="true">
                <i></i><i></i><i></i><i></i><i></i><i></i><i></i>
              </div>
            </div>

            <!-- 答案区：点已放的词块取回 -->
            <div class="answer-zone">
              <div class="answer-zone-label">
                <span aria-hidden="true">📝</span> 你的答案
                <span class="az-hint">点下方词块，按听到的顺序排入</span>
              </div>
              <div class="slot-line"
                   :class="{ filled: placed.length, right: feedback?.right, wrong: Boolean(feedback) && !feedback?.right }"
                   aria-label="答案区"
                   :aria-description="`已放 ${placed.length}/${q.chunks.length} 个词块`">
                <template v-if="placed.length">
                  <button v-for="(pi, pos) in placed" :key="`${pi}-${pos}`" class="chunk in-slot"
                          :aria-label="`取回词块 ${q.chunks[pi]}`" @click="unpick(pos)">
                    <span class="chunk-num">{{ pos + 1 }}</span>
                    <span class="chunk-text">{{ q.chunks[pi] }}</span>
                    <span class="chunk-x" aria-hidden="true">×</span>
                  </button>
                </template>
                <small v-else>👆 点击下方词块，按听到的顺序排到这里</small>
              </div>
            </div>

            <!-- 词块池 -->
            <div class="wordbank-zone">
              <div class="bank-label">
                <span class="ic" aria-hidden="true">🧩</span> 词块库
                <span class="remaining">剩余 {{ remaining.length }} / {{ q.chunks.length }}</span>
              </div>
              <div class="chunk-pool" aria-label="词块区">
                <button v-for="c in remaining" :key="c.i" class="chunk"
                        :aria-label="`选择词块 ${c.text}`" @click="pick(c.i)">{{ c.text }}</button>
              </div>
            </div>

            <div id="answer-line" aria-live="polite"
                 :class="{ right: feedback?.right, wrong: Boolean(feedback) && !feedback?.right }">
              <span v-if="feedback?.right" style="color:var(--green);">✅ 拼对了！自动进入下一句…</span>
              <span v-else-if="feedback" style="color:var(--red);">
                ❌ 正确语序：<b class="show-word">{{ feedback.text }}</b></span>
            </div>

            <div class="controls action-row">
              <button class="btn ghost" :disabled="!placed.length || Boolean(feedback)"
                      aria-label="清空重排" @click="placed = []">🔄 清空重排</button>
              <button class="btn ghost" :disabled="Boolean(feedback)"
                      aria-label="重播句子" @click="replay">🔊 重播</button>
              <span class="spacer"></span>
              <button v-if="feedback && !feedback.right" class="btn green" @click="next">下一句 →</button>
              <button class="btn primary" :disabled="!complete || Boolean(feedback)"
                      aria-label="提交这句" @click="submit">✓ 提交这句</button>
            </div>

            <div class="hint">🔊 随时可重播 · 点答案区里的词块可以取回 · 词块放满自动判对错，拼对自动下一句</div>
          </div>
        </div>

        <!-- 右栏 -->
        <div class="side-col">
          <div class="ring-card">
            <div class="ring-wrap">
              <svg viewBox="0 0 100 100" aria-hidden="true">
                <circle class="ring-bg" cx="50" cy="50" r="42" stroke-width="10"/>
                <circle class="ring-fg" cx="50" cy="50" r="42" stroke-width="10"
                        stroke-dasharray="263.9"
                        :style="{ strokeDashoffset: 263.9 * (1 - score / Math.max(questions.length, 1)) }"/>
              </svg>
              <div class="ring-center">
                <div class="pct">{{ Math.round(score / Math.max(questions.length, 1) * 100) }}%</div>
                <div class="sub">答对率</div>
              </div>
            </div>
            <div class="ring-info">
              <div class="ri-title"><span aria-hidden="true">📊</span> 本轮表现</div>
              <div class="ri-sub">已完成 <b>{{ idx }}</b> 题 · 剩余 <b>{{ Math.max(questions.length - idx, 0) }}</b> 题</div>
              <div class="ring-stats">
                <div class="rs"><div class="v green">{{ score }}</div><div class="l">✓ 答对</div></div>
                <div class="rs"><div class="v red">{{ Math.max(idx - score, 0) }}</div><div class="l">✗ 答错</div></div>
              </div>
            </div>
          </div>

          <div class="stats-grid">
            <div class="stat-mini">
              <div class="sm-emoji" aria-hidden="true">🏆</div>
              <div class="sm-val green">{{ score }}</div>
              <div class="sm-lbl">答对句数</div>
            </div>
            <div class="stat-mini">
              <div class="sm-emoji" aria-hidden="true">📝</div>
              <div class="sm-val blue">{{ questions.length }}</div>
              <div class="sm-lbl">本轮总题</div>
            </div>
            <div class="stat-mini">
              <div class="sm-emoji" aria-hidden="true">⏭️</div>
              <div class="sm-val orange">{{ Math.max(questions.length - idx, 0) }}</div>
              <div class="sm-lbl">剩余句数</div>
            </div>
            <div class="stat-mini">
              <div class="sm-emoji" aria-hidden="true">🧩</div>
              <div class="sm-val purple">{{ q.chunks.length }}</div>
              <div class="sm-lbl">本题词块</div>
            </div>
          </div>

          <div class="tip-card">
            <div class="tc-head"><span class="ic" aria-hidden="true">💡</span> 解题小技巧</div>
            <p><b>先找主语和谓语</b>，再补宾语与修饰语。注意<b>冠词 (the/a)</b>通常紧跟名词，<b>介词 (on/under)</b>多出现在短语末尾。多听几遍，抓住<b>语调节奏</b>！</p>
          </div>
        </div>

      </div>

      <p v-if="loadError" role="alert" class="page-error">{{ loadError }}</p>
    </template>

    <!-- ============ 结算 ============ -->
    <div v-else class="arrange-done">
      <div class="done-card">
        <div class="done-emoji" aria-hidden="true">{{ score === questions.length ? '🎉' : '🧩' }}</div>
        <h3 class="done-title">{{ score === questions.length ? '全部拼对！' : '排句完成' }}</h3>
        <p class="done-desc">拼对 {{ score }} / {{ questions.length }} 句</p>

        <div class="done-stats">
          <div class="stat-mini">
            <div class="sm-emoji" aria-hidden="true">🏆</div>
            <div class="sm-val green">{{ score }}</div>
            <div class="sm-lbl">答对</div>
          </div>
          <div class="stat-mini">
            <div class="sm-emoji" aria-hidden="true">❌</div>
            <div class="sm-val red">{{ Math.max(questions.length - score, 0) }}</div>
            <div class="sm-lbl">答错</div>
          </div>
          <div class="stat-mini">
            <div class="sm-emoji" aria-hidden="true">📈</div>
            <div class="sm-val blue">{{ Math.round(score / Math.max(questions.length, 1) * 100) }}%</div>
            <div class="sm-lbl">正确率</div>
          </div>
        </div>

        <div class="controls done-controls">
          <template v-if="fromToday">
            <button class="btn primary big" :disabled="nextLoading" @click="goNextStep">下一关 →</button>
            <button class="btn ghost big" @click="goCatalog">返回今日动线</button>
          </template>
          <template v-else>
            <button class="btn primary big" @click="start">🔁 再来一组</button>
            <button class="btn ghost big" @click="goLists">返回素材库</button>
          </template>
        </div>
      </div>
    </div>

  </div>
</template>
