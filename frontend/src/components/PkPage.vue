<script setup>
/* 实时 PK 对战页：游客也能玩。
 * 时序：有 room 参数时先 GET 快照（让服务端种下游客身份 Cookie）再开 WebSocket；
 * 断线指数退避重连，重连前同样先 GET 快照。收到 state 帧即整帧替换本地状态。 */
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { api, playWord, stopAudio } from "../lib/core";
import ShareCard from "./ShareCard.vue";

const props = defineProps({ params: { type: Object, default: null } });

const LIST_TITLES = {
  cet4: "CET-4 词汇", cet6: "CET-6 词汇", kaoyan: "考研词汇", tuofu: "托福词汇",
};
const wordLists = ref([]);       // 词库选项来自素材目录，与每日挑战同一来源
api("/lists").then((d) => {
  wordLists.value = (d.lists || []).filter((l) => l.type === "words");
}).catch(() => { /* 目录拉取失败时退回内置四项 */ });
function listTitle(key) {
  const hit = wordLists.value.find((l) => l.key === key);
  return hit?.title || LIST_TITLES[key] || key;
}
const lobbyLists = computed(() =>
  wordLists.value.length ? wordLists.value
    : Object.entries(LIST_TITLES).map(([key, title]) => ({ key, title })));
const SEAT_LABEL = { creator: "房主", opponent: "挑战者" };

const roomParam = props.params?.get("room") || "";
const listParam = ref(props.params?.get("list") || "cet4");

const snap = ref(null);          // 最近一帧 state
const connecting = ref(false);
const errored = ref("");

/* 初始屏（无 room 参数） */
const joinCode = ref("");
const createList = ref("cet4");
const creating = ref(false);

/* 对战本地状态 */
const idx = ref(0);
const input = ref("");
const revealed = ref(false);     // 答错提示
const myScore = ref(0);
const myCombo = ref(0);
const myAnswered = ref(0);
const localDone = ref(false);    // 是否已交卷（本地停笔）
const localInit = ref(false);    // 本局本地计数是否已用服务端校准
const pending = ref(false);      // 已提交待服务端 verdict；判权在服务端，本地不再自判
const pendingSkip = ref(false);  // 本次 pending 是跳过（verdict 必然 wrong，但要前进）
const remain = ref(0);
const shareOpen = ref(false);

let mounted = true;
let intentionalClose = false;
let reconnectAttempts = 0;
let offset = 0;                  // Date.now() - server_now (ms)
let countdownTimer = null;
let reconnectTimer = null;
const ws = ref(null);
const inputEl = ref(null);
const answerLog = new Map();   // index → text：断线重连后整体重放补账

const code = computed(() => snap.value?.code || roomParam || joinCode.value.toUpperCase());
const phase = computed(() => snap.value?.phase || (connecting.value ? "connecting" : "lobby"));
const total = computed(() => snap.value?.items?.length || 0);
const item = computed(() => {
  const s = snap.value;
  if (!s || s.phase !== "playing") return null;
  return s.items[idx.value] || null;
});

/* HUD：我方（本地即时）与对方（服务端）合并渲染；旁观者纯服务端。
 * 结算屏除外——结算要显示服务端盖章后的权威分数，本地计数可能落后一帧。 */
const displayPlayers = computed(() => {
  const s = snap.value;
  if (!s) return [];
  if (s.role !== "spectator" && s.phase !== "finished") {
    return s.players.map((p) => (p.seat === s.role
      ? { ...p, score: myScore.value, combo: myCombo.value, answered: myAnswered.value }
      : p));
  }
  return s.players;
});
const seatsView = computed(() => {
  const s = snap.value;
  if (!s) return [];
  const map = new Map(s.players.map((p) => [p.seat, p]));
  return ["creator", "opponent"].map((seat) => ({
    seat,
    name: map.get(seat)?.name || (seat === "opponent" ? "等待对手…" : "房主"),
    joined: Boolean(map.get(seat)),
  }));
});

onMounted(() => {
  if (roomParam) connect(roomParam);
});

onUnmounted(() => {
  mounted = false;
  intentionalClose = true;
  stopCountdown();
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  try { ws.value?.close(); } catch { /* 已关闭 */ }
  stopAudio();
});

async function connect(room) {
  connecting.value = true;
  errored.value = "";
  try {
    const s = await api(`/pk/room/${encodeURIComponent(room)}`);
    if (!mounted) return;
    snap.value = s;
    if (s.server_now) offset = Date.now() - new Date(s.server_now).getTime();
  } catch (err) {
    if (!mounted) return;
    errored.value = err.message || "无法加入房间";
    connecting.value = false;
    return;
  }
  openWs(room);
}

function openWs(room) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let sock;
  try {
    sock = new WebSocket(`${proto}://${location.host}/ws/pk/${encodeURIComponent(room)}`);
  } catch (err) {
    scheduleReconnect(room);
    return;
  }
  ws.value = sock;
  sock.onopen = () => {
    if (!mounted) { sock.close(); return; }
    connecting.value = false;
    reconnectAttempts = 0;
    pending.value = false;   // 断线窗口丢掉的 verdict 靠 replay 重发答案后重新等判定
    sock.send(JSON.stringify({ type: "join" }));
    replay();
  };
  sock.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    handleMsg(msg);
  };
  sock.onclose = () => {
    if (intentionalClose || !mounted) return;
    scheduleReconnect(room);
  };
  sock.onerror = () => { try { sock.close(); } catch { /* close 触发重连 */ } };
}

function handleMsg(msg) {
  if (msg.type === "state") {
    snap.value = msg;
    if (msg.server_now) offset = Date.now() - new Date(msg.server_now).getTime();
    if (msg.phase === "playing") {
      if (!localInit.value) initLocal(msg);
      startCountdown(msg);
    } else {
      localInit.value = false;
      stopCountdown();
      if (msg.phase === "finished") closeWhenSettled();
    }
  } else if (msg.type === "verdict") {
    onVerdict(msg);
  } else if (msg.type === "gone") {
    errored.value = "房间已被清理或已过期";
    stopCountdown();
    intentionalClose = true;
    try { ws.value?.close(); } catch { /* 已关闭 */ }
  }
  // ping 忽略
}

function initLocal(msg) {
  localInit.value = true;
  localDone.value = false;
  pending.value = false;
  pendingSkip.value = false;
  answerLog.clear();      // 新局换词流，旧局的重放账本已失效
  idx.value = 0;
  input.value = "";
  const meP = msg.players.find((p) => p.seat === msg.role);
  if (meP) {
    myScore.value = meP.score;
    myCombo.value = meP.combo;
    myAnswered.value = meP.answered;
    idx.value = Math.min(meP.answered, (msg.items?.length || 1) - 1);
  } else {
    myScore.value = 0; myCombo.value = 0; myAnswered.value = 0;
  }
  focusInput();
  playCurrent();
}

function scheduleReconnect(room) {
  if (reconnectAttempts >= 5) {
    errored.value = "连接已断开，请刷新页面重试";
    return;
  }
  const delay = Math.min(8000, 500 * 2 ** reconnectAttempts);
  reconnectAttempts++;
  reconnectTimer = setTimeout(() => { if (mounted) connect(room); }, delay);
}

function send(obj) {
  const s = ws.value;
  if (s && s.readyState === WebSocket.OPEN) {
    try { s.send(JSON.stringify(obj)); } catch { /* 发送失败：answer 帧靠重连后的 replay() 补账 */ }
  }
}
function sendAnswer(index, text) {
  answerLog.set(index, text);
  send({ type: "answer", index, text });
}
/* 断线窗口内丢掉的 answer 帧在此补账：服务端按 index 幂等去重，重放零成本。 */
function replay() {
  for (const [index, text] of answerLog) send({ type: "answer", index, text });
  if (localDone.value) send({ type: "finish" });
}

function startGame() { send({ type: "start" }); }

function playCurrent() { if (item.value) playWord(item.value); }
function focusInput() {
  nextTick(() => { try { inputEl.value?.focus({ preventScroll: true }); } catch { /* 聚焦失败忽略 */ } });
}

/* 判权在服务端：提交后等 verdict 帧再推进。pending 期间锁定输入防连点。 */
function submitWord() {
  const it = item.value;
  if (!it || snap.value?.phase !== "playing" || localDone.value || pending.value) return;
  const guess = input.value.trim().toLowerCase();
  if (!guess) return;
  revealed.value = false;
  pending.value = true;
  pendingSkip.value = false;
  sendAnswer(idx.value, guess);
}

function skipWord() {
  if (snap.value?.phase !== "playing" || localDone.value || pending.value) return;
  revealed.value = false;
  pending.value = true;
  pendingSkip.value = true;
  sendAnswer(idx.value, "");
}

function onVerdict(msg) {
  if (localDone.value) { pending.value = false; return; }
  // 只认当前题且在等的 verdict：断线重放/迟到帧不重复计数
  if (msg.index !== idx.value || !pending.value) return;
  const wasSkip = pendingSkip.value;
  pending.value = false;
  pendingSkip.value = false;
  myAnswered.value++;
  input.value = "";
  if (msg.right) {
    myScore.value++; myCombo.value++;
    advance();
  } else if (wasSkip) {
    advance();
  } else {
    myCombo.value = 0;
    revealed.value = true;
    playCurrent();
    focusInput();
  }
}

function advance() {
  if (idx.value + 1 >= total.value) finishLocal();
  else { idx.value++; playCurrent(); focusInput(); }
}

function finishLocal() {
  if (localDone.value) return;
  localDone.value = true;
  send({ type: "finish" });
  // 等待服务端 state 推进到 finished；若对手仍在打，HUD 继续直播对手进度
}

function startCountdown(msg) {
  stopCountdown();
  updateRemain();
  countdownTimer = setInterval(updateRemain, 250);
}
function stopCountdown() {
  if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
}
function updateRemain() {
  const s = snap.value;
  if (!s || s.phase !== "playing" || !s.deadline_at) { remain.value = 0; return; }
  const current = Date.now() - offset;
  const left = Math.max(0, Math.ceil((new Date(s.deadline_at).getTime() - current) / 1000));
  remain.value = left;
  if (left <= 0 && !localDone.value) finishLocal();   // 倒计时归零，本地停笔发 finish
}

function closeWhenSettled() {
  // 服务端收尾后会挂约 20s 再断连接，前端主动 close 释放资源
  setTimeout(() => {
    if (!mounted) return;
    intentionalClose = true;
    try { ws.value?.close(); } catch { /* 已关闭 */ }
  }, 1500);
}

/* 初始屏：创建 / 加入 */
async function createRoom() {
  if (creating.value) return;
  creating.value = true;
  errored.value = "";
  try {
    const d = await api(`/pk/room?list=${encodeURIComponent(createList.value)}`, { method: "POST" });
    location.hash = `#/pk?room=${d.code}&list=${createList.value}`;
  } catch (err) {
    errored.value = err.message || "创建房间失败";
  } finally {
    creating.value = false;
  }
}
function joinRoom() {
  const c = joinCode.value.trim().toUpperCase();
  if (!c) return;
  location.hash = `#/pk?room=${c}`;
}

/* 结算分享 */
function verdictText() {
  const s = snap.value;
  if (!s) return "";
  if (s.winner === "draw") return "平局！";
  if (!s.winner || s.role === "spectator") return "对战结束";
  if (s.winner === s.me) return "你赢了！🏆";
  return "惜败…";
}
function sharePayload() {
  const s = snap.value;
  if (!s) return { code: "", listTitle: "", verdict: "", rows: [] };
  return {
    code: s.code,
    listTitle: listTitle(s.list),
    verdict: verdictText(),
    rows: displayPlayers.value.map((p) => ({
      name: p.name, score: p.score, crown: Boolean(s.winner) && s.winner === p.user, finished: p.finished,
    })),
  };
}
function inviteLink() { return `${location.origin}/#/pk?room=${code.value}`; }
async function copyInvite() {
  try { await navigator.clipboard.writeText(inviteLink()); } catch { /* 剪贴板不可用忽略 */ }
}
function playAgain() { location.hash = "#/pk"; }
</script>

<template>
  <div class="pk-page">
    <!-- 初始屏：创建 / 加入 -->
    <div v-if="!roomParam" class="pk-lobby-page">
      <div class="page-heading compact">
        <span class="eyebrow">REALTIME BATTLE</span>
        <h1>⚔️ 实时 PK 对战</h1>
        <p>开个房间，把链接发给好友，同一份词流比谁听得准、写得快。</p>
      </div>
      <div v-if="errored" class="account-message error" role="alert" style="margin-bottom:14px;">{{ errored }}</div>
      <div class="pk-lobby">
        <div class="card pk-lobby-card">
          <div class="card-title"><span class="card-icon">🎮</span> 创建房间</div>
          <div class="form-group">
            <label class="form-label">词库</label>
            <select v-model="createList" class="form-select" aria-label="选择词库">
              <option v-for="l in lobbyLists" :key="l.key" :value="l.key">{{ l.title }}</option>
            </select>
          </div>
          <button class="btn primary big full" :disabled="creating" @click="createRoom">
            {{ creating ? "⏳ 生成中…" : "🎮 创建并进入" }}
          </button>
        </div>
        <div class="card pk-lobby-card">
          <div class="card-title"><span class="card-icon">🚪</span> 加入房间</div>
          <p class="form-hint">已有 6 位房间口令？</p>
          <input v-model="joinCode" class="form-input pk-code-input" maxlength="6" placeholder="输入口令"
                 @keyup.enter="joinRoom" style="text-transform:uppercase;">
          <button class="btn ghost big full" :disabled="!joinCode.trim()" @click="joinRoom">加入</button>
        </div>
      </div>
    </div>

    <!-- 连接 / 错误 -->
    <div v-else-if="errored" class="empty" role="alert">
      <span class="emoji">⚠️</span>
      <h3>连接失败</h3>
      <p>{{ errored }}</p>
      <div class="controls" style="margin-top:16px;">
        <button class="btn primary" @click="connect(roomParam)">重试</button>
        <button class="btn ghost" @click="playAgain">返回</button>
      </div>
    </div>
    <div v-else-if="!snap" class="empty loading">
      <span class="spin"></span>
      <span class="load-text">连接中…</span>
    </div>

    <!-- 等待大厅 -->
    <div v-else-if="snap.phase === 'waiting'" class="pk-waiting">
      <div class="card pk-wait-card">
        <div class="card-title"><span class="card-icon">⏳</span> 等待对手加入</div>
        <div class="card-desc">把房间口令分享给好友，对方加入后即可开始对战</div>
        <div class="pk-code-chip">{{ code }}</div>
        <p class="pk-code-cap">房间口令 · 把链接发给好友即可同桌</p>
        <div class="controls" style="margin-top:8px;">
          <button class="btn ghost sm" @click="copyInvite">📋 复制邀请链接</button>
        </div>
      </div>
      <div class="pk-seats">
        <div v-for="s in seatsView" :key="s.seat" class="card pk-seat" :class="{ empty: !s.joined }">
          <span class="pk-seat-tag">{{ SEAT_LABEL[s.seat] }}</span>
          <b>{{ s.name }}</b>
          <span v-if="!s.joined" class="pk-waiting-text">等待对手…</span>
        </div>
      </div>
      <button v-if="snap.role !== 'spectator'" class="btn primary big full" style="margin-top:18px;" @click="startGame">🚀 开始对战</button>
      <p v-else class="pk-hint-sm">👁️ 你正在旁观，对战开始后即可看到实时比分。</p>
    </div>

    <!-- 对战中 -->
    <div v-else-if="snap.phase === 'playing'" class="pk-play">
      <!-- Arena Hero -->
      <div class="arena-hero">
        <div class="arena-glow"></div>
        <div class="arena-row">
          <div class="player-side" :class="snap.role === 'spectator' ? 'left' : (displayPlayers[0] && displayPlayers[0].seat === snap.role ? 'left' : 'right')">
            <div class="p-avatar-wrap">
              <div class="p-avatar-ring">
                <div class="p-avatar-inner">{{ displayPlayers[0] && displayPlayers[0].seat === snap.role ? '🦉' : '🐯' }}</div>
              </div>
              <div class="p-live-dot">LIVE</div>
            </div>
            <div class="p-name">{{ displayPlayers[0]?.name }}</div>
            <div class="p-meta">
              <span class="m-item">{{ SEAT_LABEL[displayPlayers[0]?.seat] }}</span>
              <span class="m-item">⚡ ×{{ displayPlayers[0]?.combo || 0 }}</span>
            </div>
            <div class="p-score">{{ displayPlayers[0]?.score || 0 }}</div>
            <div class="p-score-lbl">当前得分</div>
          </div>
          <div class="vs-center">
            <div class="vs-badge">VS</div>
            <div class="vs-round">第 {{ Math.min(idx + 1, total) }} / {{ total }} 词</div>
            <div class="vs-timer timer-pill" :class="{ urgent: remain <= 10 }" role="timer" :aria-label="`剩余 ${remain} 秒`">
              ⏱️ {{ remain }}s
            </div>
          </div>
          <div class="player-side" :class="snap.role === 'spectator' ? 'right' : (displayPlayers[1] && displayPlayers[1].seat === snap.role ? 'left' : 'right')">
            <div class="p-avatar-wrap">
              <div class="p-avatar-ring">
                <div class="p-avatar-inner">{{ displayPlayers[1] && displayPlayers[1].seat === snap.role ? '🦉' : '🐯' }}</div>
              </div>
              <div class="p-live-dot">LIVE</div>
            </div>
            <div class="p-name">{{ displayPlayers[1]?.name }}</div>
            <div class="p-meta">
              <span class="m-item">{{ SEAT_LABEL[displayPlayers[1]?.seat] }}</span>
              <span class="m-item">⚡ ×{{ displayPlayers[1]?.combo || 0 }}</span>
            </div>
            <div class="p-score">{{ displayPlayers[1]?.score || 0 }}</div>
            <div class="p-score-lbl">当前得分</div>
          </div>
        </div>
      </div>

      <!-- Live Card -->
      <div class="live-card">
        <div class="live-card-top"></div>
        <div class="live-inner">
          <div class="live-head">
            <div class="l">
              <span class="live-ic">🎯</span>
              <b>实时对战<small>第 {{ Math.min(idx + 1, total) }} / {{ total }} 词</small></b>
            </div>
            <button class="btn blue sm pk-tts-btn" aria-label="播放音频" @click="playCurrent">🔊 播放</button>
          </div>

          <div class="dual-bars">
            <div v-for="p in displayPlayers" :key="'bar-' + p.seat" class="db-row">
              <div class="db-avatar" :class="snap.role !== 'spectator' && p.seat === snap.role ? 'me' : 'op'">
                {{ snap.role !== 'spectator' && p.seat === snap.role ? '🦉' : '🐯' }}
              </div>
              <div class="db-info">
                <div class="db-info-top">
                  <div class="db-name">{{ p.name }}<span v-if="snap.role !== 'spectator' && p.seat === snap.role" class="me-tag">我</span></div>
                  <div class="db-score" :class="snap.role !== 'spectator' && p.seat === snap.role ? 'me' : 'op'">{{ p.score }}<small>分</small></div>
                </div>
                <div class="progress-bar">
                  <div class="progress-fill" :class="snap.role !== 'spectator' && p.seat === snap.role ? 'green' : 'blue'" :style="{ width: (total > 0 ? Math.min((p.answered / total) * 100, 100) : 0) + '%' }"></div>
                </div>
              </div>
              <div class="db-status">
                <span class="s-dot" :class="p.finished ? '' : 'go'"></span> {{ p.finished ? '已完成' : '进行中' }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="localDone" class="pk-done-note">✅ 你已交卷，等待对手完成…</div>
      <div v-else class="pk-board">
        <div class="word-display">
          <div class="word-label">本轮单词</div>
          <input ref="inputEl" v-model="input" class="pk-catch" :disabled="localDone"
                 autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false"
                 placeholder="听音打词，回车提交" @keyup.enter="submitWord">
          <div v-if="revealed" class="pk-warn" role="alert">✗ 拼错了，再试一次</div>
          <div v-else class="word-hint">🎧 听音后输入英文拼写 · 回车提交</div>
        </div>
        <div class="controls" style="margin-top:10px;">
          <button class="btn ghost sm" :disabled="localDone" @click="skipWord">跳过</button>
          <button class="btn primary sm" :disabled="localDone" @click="submitWord">提交</button>
        </div>
      </div>
    </div>

    <!-- 结算 -->
    <div v-else class="pk-finished">
      <div class="hero-card pk-verdict-card" :class="{ win: snap.winner === snap.me, draw: snap.winner === 'draw', lose: snap.role !== 'spectator' && snap.winner && snap.winner !== snap.me }">
        <div class="pk-verdict-emoji">{{ snap.winner === 'draw' ? '🤝' : snap.winner === snap.me ? '🏆' : '💔' }}</div>
        <div class="pk-verdict">{{ verdictText() }}</div>
      </div>
      <div class="pk-result-rows">
        <div v-for="p in displayPlayers" :key="p.seat" class="card pk-result-row" :class="{ win: snap.winner && snap.winner === p.user }">
          <span class="pk-rr-name">{{ p.user === snap.me ? "🙋 " : "" }}{{ p.name }}<small>{{ SEAT_LABEL[p.seat] }}</small></span>
          <b class="pk-rr-score">{{ p.score }}</b>
          <span v-if="snap.winner && snap.winner === p.user" class="pk-crown">👑</span>
        </div>
      </div>
      <div class="controls" style="margin-top:16px;">
        <button class="btn primary" @click="shareOpen = true">📤 分享战报</button>
        <button class="btn ghost" @click="playAgain">🔄 再来一局</button>
      </div>
    </div>

    <ShareCard :open="shareOpen" kind="pk" :payload="sharePayload()" @close="shareOpen = false" />
  </div>
</template>

<style scoped>
/* 所有页面专属样式已移至 styles/pages/21-pk.css */
</style>
