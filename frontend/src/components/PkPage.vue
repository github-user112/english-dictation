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
    <div v-if="!roomParam" class="empty">
      <div class="page-heading compact">
        <span class="eyebrow">REALTIME BATTLE</span>
        <h1>实时 PK 对战</h1>
        <p>开个房间，把链接发给好友，同一份词流比谁听得准、写得快。</p>
      </div>
      <div v-if="errored" class="account-message error" role="alert" style="margin-bottom:14px;">{{ errored }}</div>
      <div class="pk-lobby">
        <div class="pk-lobby-card">
          <div class="pk-lobby-title">创建房间</div>
          <label class="pk-list-label">词库
            <select v-model="createList" class="daily-list-select" aria-label="选择词库">
              <option v-for="l in lobbyLists" :key="l.key" :value="l.key">{{ l.title }}</option>
            </select>
          </label>
          <button class="btn primary big" :disabled="creating" @click="createRoom">
            {{ creating ? "生成中…" : "创建并进入" }}
          </button>
        </div>
        <div class="pk-lobby-card">
          <div class="pk-lobby-title">加入房间</div>
          <p class="pk-hint-sm">已有 6 位房间口令？</p>
          <input v-model="joinCode" class="pk-code-input" maxlength="6" placeholder="输入口令"
                 @keyup.enter="joinRoom" style="text-transform:uppercase;">
          <button class="btn ghost big" :disabled="!joinCode.trim()" @click="joinRoom">加入</button>
        </div>
      </div>
    </div>

    <!-- 连接 / 错误 -->
    <div v-else-if="errored" class="empty" role="alert">
      <p>{{ errored }}</p>
      <div class="controls" style="margin-top:16px;">
        <button class="btn primary" @click="connect(roomParam)">重试</button>
        <button class="btn ghost" @click="playAgain">返回</button>
      </div>
    </div>
    <div v-else-if="!snap" class="empty">连接中…</div>

    <!-- 等待大厅 -->
    <div v-else-if="snap.phase === 'waiting'" class="empty">
      <div class="pk-code">{{ code }}</div>
      <p class="pk-code-cap">房间口令 · 把链接发给好友即可同桌</p>
      <div class="controls" style="margin-top:8px;">
        <button class="btn ghost sm" @click="copyInvite">复制邀请链接</button>
      </div>
      <div class="pk-seats">
        <div v-for="s in seatsView" :key="s.seat" class="pk-seat" :class="{ empty: !s.joined }">
          <span class="pk-seat-tag">{{ SEAT_LABEL[s.seat] }}</span>
          <b>{{ s.name }}</b>
          <span v-if="!s.joined" class="pk-waiting">等待对手…</span>
        </div>
      </div>
      <button v-if="snap.role !== 'spectator'" class="btn primary big" style="margin-top:18px;" @click="startGame">开始对战</button>
      <p v-else class="pk-hint-sm">你正在旁观，对战开始后即可看到实时比分。</p>
    </div>

    <!-- 对战中 -->
    <div v-else-if="snap.phase === 'playing'" class="pk-play">
      <div class="pk-hud">
        <div v-for="p in displayPlayers" :key="p.seat" class="pk-hud-col" :class="{ me: snap.role !== 'spectator' && p.seat === snap.role }">
          <span class="pk-hud-name">{{ p.name }}<small>{{ SEAT_LABEL[p.seat] }}</small></span>
          <b class="pk-hud-score">{{ p.score }}</b>
          <span class="pk-hud-combo">连击 ×{{ p.combo }}</span>
        </div>
        <div class="pk-timer" :class="{ urgent: remain <= 10 }" role="timer" :aria-label="`剩余 ${remain} 秒`">
          <b>{{ remain }}<small>s</small></b>
        </div>
      </div>
      <div v-if="localDone" class="pk-done-note">你已交卷，等待对手完成…</div>
      <div v-else class="pk-board">
        <div class="pk-progress">第 {{ Math.min(idx + 1, total) }} / {{ total }} 词</div>
        <button class="btn ghost pk-play-btn" aria-label="重播发音" @click="playCurrent">🔊</button>
        <input ref="inputEl" v-model="input" class="pk-catch" :disabled="localDone"
               autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false"
               placeholder="听音打词，回车提交" @keyup.enter="submitWord">
        <div v-if="revealed" class="pk-warn" role="alert">✗ 拼错了，再试一次</div>
        <div class="controls" style="margin-top:10px;">
          <button class="btn ghost sm" :disabled="localDone" @click="skipWord">跳过</button>
          <button class="btn primary sm" :disabled="localDone" @click="submitWord">提交</button>
        </div>
      </div>
    </div>

    <!-- 结算 -->
    <div v-else class="empty">
      <div class="pk-verdict" :class="{ win: snap.winner === snap.me, draw: snap.winner === 'draw', lose: snap.role !== 'spectator' && snap.winner && snap.winner !== snap.me }">
        {{ verdictText() }}
      </div>
      <div class="pk-result-rows">
        <div v-for="p in displayPlayers" :key="p.seat" class="pk-result-row">
          <span class="pk-rr-name">{{ p.user === snap.me ? "🙋 " : "" }}{{ p.name }}<small>{{ SEAT_LABEL[p.seat] }}</small></span>
          <b class="pk-rr-score">{{ p.score }}</b>
          <span v-if="snap.winner && snap.winner === p.user" class="pk-crown">👑</span>
        </div>
      </div>
      <div class="controls" style="margin-top:16px;">
        <button class="btn primary" @click="shareOpen = true">分享战报</button>
        <button class="btn ghost" @click="playAgain">再来一局</button>
      </div>
    </div>

    <ShareCard :open="shareOpen" kind="pk" :payload="sharePayload()" @close="shareOpen = false" />
  </div>
</template>

<style scoped>
.pk-lobby { display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; margin-top: 8px; }
.pk-lobby-card {
  background: var(--panel); border: 1px solid var(--border); border-radius: 16px;
  padding: 18px 16px; width: min(320px, 86vw); display: flex; flex-direction: column; gap: 12px; align-items: stretch;
}
.pk-lobby-title { font-weight: 750; font-size: 15px; }
.pk-list-label { font-size: 12px; color: var(--dim); display: flex; flex-direction: column; gap: 6px; }
.pk-hint-sm { color: var(--dim); font-size: 12px; margin: 0; }
.pk-code-input {
  text-align: center; letter-spacing: .25em; font-size: 20px; font-weight: 700;
  padding: 10px; border-radius: 12px; border: 1px solid var(--border); background: var(--panel2); color: var(--text);
}
.pk-code {
  font-family: "Avenir Next", monospace; font-size: 44px; font-weight: 800; letter-spacing: .18em;
  color: var(--accent-strong); margin-top: 6px;
}
.pk-code-cap { color: var(--dim); font-size: 13px; margin: 4px 0 0; }
.pk-seats { display: flex; gap: 14px; margin: 18px auto 0; flex-wrap: wrap; justify-content: center; }
.pk-seat {
  min-width: 160px; padding: 14px 18px; border-radius: 14px; border: 1px solid var(--border);
  background: var(--panel); display: flex; flex-direction: column; gap: 4px; align-items: flex-start;
}
.pk-seat.empty { opacity: .7; border-style: dashed; }
.pk-seat-tag { font-size: 11px; color: var(--accent); font-weight: 700; }
.pk-waiting { color: var(--dim); font-size: 12px; }
.pk-play { max-width: 520px; margin: 0 auto; }
.pk-hud { display: flex; align-items: center; gap: 10px; justify-content: center; margin-bottom: 14px; }
.pk-hud-col {
  flex: 1; padding: 12px; border-radius: 14px; border: 1px solid var(--border); background: var(--panel);
  display: flex; flex-direction: column; gap: 2px; text-align: center;
}
.pk-hud-col.me { border-color: var(--accent); box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent); }
.pk-hud-name { font-size: 13px; font-weight: 700; }
.pk-hud-name small { color: var(--dim); font-weight: 400; margin-left: 6px; }
.pk-hud-score { font-size: 34px; line-height: 1; }
.pk-hud-combo { font-size: 12px; color: var(--dim); }
.pk-timer {
  min-width: 64px; padding: 12px; border-radius: 14px; background: var(--panel3); text-align: center;
}
.pk-timer.urgent b { color: var(--red); }
.pk-timer b { font-size: 28px; }
.pk-timer small { font-size: 12px; color: var(--dim); }
.pk-board { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 18px; text-align: center; }
.pk-progress { color: var(--dim); font-size: 13px; margin-bottom: 10px; }
.pk-play-btn { font-size: 20px; }
.pk-catch {
  width: 100%; margin-top: 10px; padding: 12px 14px; font-size: 17px; text-align: center;
  border-radius: 12px; border: 1px solid var(--border); background: var(--panel2); color: var(--text);
}
.pk-catch:disabled { opacity: .5; }
.pk-warn { color: var(--red); font-size: 13px; margin-top: 8px; }
.pk-done-note { text-align: center; color: var(--yellow); font-size: 14px; margin: 10px 0; }
.pk-verdict { font-size: 26px; font-weight: 800; margin: 6px 0 14px; }
.pk-verdict.win { color: var(--green); }
.pk-verdict.draw { color: var(--accent); }
.pk-result-rows { max-width: 340px; margin: 0 auto; }
.pk-result-row {
  display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-radius: 12px;
  border: 1px solid var(--border); background: var(--panel); margin-bottom: 10px;
}
.pk-rr-name { flex: 1; text-align: left; font-weight: 700; }
.pk-rr-name small { color: var(--dim); font-weight: 400; margin-left: 6px; }
.pk-rr-score { font-size: 22px; }
.pk-crown { font-size: 20px; }
</style>
