<script setup>
import { onMounted, ref } from "vue";
import { api, Settings } from "../lib/core";
import { Account } from "../lib/account";

const s = ref(Settings.get());

const pushSupported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const pushOn = ref(false);
const pushBusy = ref(false);

onMounted(async () => {
  if (!pushSupported) return;
  try {
    const reg = await navigator.serviceWorker.getRegistration("/sw.js");
    pushOn.value = Boolean(reg && await reg.pushManager.getSubscription());
  } catch { /* 读取失败按未开启展示 */ }
});

function b64ToU8(b64) {
  const pad = "=".repeat((4 - b64.length % 4) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

async function togglePush() {
  if (pushBusy.value) return;
  pushBusy.value = true;
  try {
    if (pushOn.value) {
      const reg = await navigator.serviceWorker.getRegistration("/sw.js");
      const sub = reg && await reg.pushManager.getSubscription();
      if (sub) {
        await api("/push/subscribe", { method: "DELETE", body: JSON.stringify({ endpoint: sub.endpoint }) });
        await sub.unsubscribe();
      }
      pushOn.value = false;
      return;
    }
    const perm = await Notification.requestPermission();
    if (perm !== "granted") { alert("通知权限被拒绝，请在浏览器设置里允许通知"); return; }
    const { public_key } = await api("/push/key");
    const reg = await navigator.serviceWorker.register("/sw.js");
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToU8(public_key) });
    await api("/push/subscribe", { method: "POST", body: JSON.stringify(sub.toJSON()) });
    pushOn.value = true;
  } catch (err) {
    alert(err.message || "设置失败");
  } finally {
    pushBusy.value = false;
  }
}

function set(key, val) {
  // L1: 数值设置钳制（HTML min/max 不限制输入内容）
  if (key === "newPerDay") val = Math.max(5, Math.min(50, val)) || 10;
  if (key === "replayInterval") val = Math.max(1, Math.min(30, val)) || 5;
  if (key === "replayTimes") val = Math.max(0, Math.min(5, val)) || 0;
  Settings.set({ [key]: val });
  s.value = Settings.get();
}
</script>

<template>
  <div class="settings-page">

    <!-- ====== 页头 ====== -->
    <div class="page-heading">
      <span class="eyebrow">PERSONALIZE</span>
      <h1><span class="h-emoji">🎛️</span> 按你的节奏学习</h1>
      <p>调整提示、主题和每日练习量。</p>
    </div>

    <!-- ====== 调音台 Hero ====== -->
    <div class="studio-hero">
      <div class="grid-bg"></div>
      <div class="sh-body">
        <!-- 均衡器 -->
        <div class="eq-wrap">
          <div class="eq">
            <span></span><span></span><span></span><span></span>
            <span></span><span></span><span></span>
          </div>
          <div class="eq-tag">NOW MIXING</div>
        </div>
        <!-- 读数区 -->
        <div class="sh-mid">
          <div class="sh-title-row">
            <span class="sh-badge">🎛️ STUDIO</span>
            <span class="sh-title">当前练习配置</span>
          </div>
          <div class="sh-voice">
            <div class="sh-voice-ic">🎧</div>
            <div>
              <div class="sh-voice-name">{{ s.practiceMode === 'pure' ? '纯听写模式' : s.practiceMode === 'assisted' ? '辅助模式' : '跟打模式' }}</div>
              <div class="sh-voice-meta">{{ s.theme === 'light' ? '亮色主题' : '暗色主题' }} · 每日 {{ s.newPerDay }} 词</div>
            </div>
          </div>
          <div class="sh-readout">
            <div class="rd"><span class="k">新词/日</span><span class="v">{{ s.newPerDay }}</span></div>
            <div class="rd"><span class="k">重播间隔</span><span class="v">{{ s.replayInterval }}s</span></div>
            <div class="rd"><span class="k">重播次数</span><span class="v">{{ s.replayTimes }}</span></div>
            <div class="rd"><span class="k">通知</span><span class="v">{{ pushOn ? 'ON' : 'OFF' }}</span></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ====== 设置卡片网格 ====== -->
    <div class="main-grid">

      <!-- ──── 听写显示 ──── -->
      <div class="section-card">
        <div class="sc-head">
          <div class="sc-title"><span class="sc-ic">🎧</span> 听写显示</div>
          <div class="sc-sub">题目呈现方式</div>
        </div>
        <div class="setting-list">
          <div class="step-item">
            <div class="step-icon">🎯</div>
            <div class="step-body">
              <b>默认练习模式</b>
              <small>纯听写不显示提示；辅助听写即时纠错；跟打显示原文且不计入掌握</small>
            </div>
            <div class="seg">
              <button v-for="m in [{k:'pure',n:'纯听写'},{k:'assisted',n:'辅助'},{k:'follow',n:'跟打'}]" :key="m.k"
                :class="{on: s.practiceMode===m.k}" @click="set('practiceMode',m.k)">{{ m.n }}</button>
            </div>
          </div>
          <div class="step-item">
            <div class="step-icon">🈶</div>
            <div class="step-body">
              <b>显示中文释义</b>
              <small>在题卡上方显示汉语意思，答错后也会显示</small>
            </div>
            <label class="switch"><input type="checkbox" :checked="s.showMeaning"
              @change="set('showMeaning', $event.target.checked)"><span class="slider"></span></label>
          </div>
          <div class="step-item">
            <div class="step-icon">🔤</div>
            <div class="step-body">
              <b>显示音标</b>
              <small>单词模式下显示国际音标</small>
            </div>
            <label class="switch"><input type="checkbox" :checked="s.showPhonetic"
              @change="set('showPhonetic', $event.target.checked)"><span class="slider"></span></label>
          </div>
        </div>
      </div>

      <!-- ──── 练习节奏 ──── -->
      <div class="section-card">
        <div class="sc-head">
          <div class="sc-title"><span class="sc-ic">⏱️</span> 练习节奏</div>
          <div class="sc-sub">每日量与重播</div>
        </div>
        <div class="setting-list">
          <div class="step-item">
            <div class="step-icon">📅</div>
            <div class="step-body">
              <b>每日新词数</b>
              <small>每天学习的新词/新句数量，复习词自动追加</small>
            </div>
            <div class="num-wrap">
              <input type="number" class="num-input" min="5" max="50"
                :value="s.newPerDay" @change="set('newPerDay', Number($event.target.value))">
              <span class="num-unit">词</span>
            </div>
          </div>
          <div class="step-item">
            <div class="step-icon">⏸️</div>
            <div class="step-body">
              <b>自动重播间隔（秒）</b>
              <small>读完后隔几秒自动重播一次</small>
            </div>
            <div class="num-wrap">
              <input type="number" class="num-input" min="1" max="30"
                :value="s.replayInterval" @change="set('replayInterval', Number($event.target.value))">
              <span class="num-unit">秒</span>
            </div>
          </div>
          <div class="step-item">
            <div class="step-icon">🔁</div>
            <div class="step-body">
              <b>自动重播次数</b>
              <small>第一次播放后再重播几次，0 表示只播一遍</small>
            </div>
            <div class="num-wrap">
              <input type="number" class="num-input" min="0" max="5"
                :value="s.replayTimes" @change="set('replayTimes', Number($event.target.value))">
              <span class="num-unit">次</span>
            </div>
          </div>
        </div>
      </div>

      <!-- ──── 界面主题（跨两列）──── -->
      <div class="section-card span-2">
        <div class="sc-head">
          <div class="sc-title"><span class="sc-ic">🎨</span> 界面主题</div>
          <div class="sc-sub">亮色 / 暗色切换</div>
        </div>
        <div class="theme-grid">
          <div class="theme-card" :class="{active: s.theme === 'light'}">
            <div class="tc-preview light">
              <div class="ln g" style="width:56%"></div>
              <div class="ln" style="width:78%"></div>
              <div class="ln" style="width:40%"></div>
            </div>
            <div class="tc-name-row">
              <b>☀️ 亮色</b>
              <span v-if="s.theme === 'light'" class="tc-check">✓</span>
            </div>
            <div class="tc-desc">明亮清爽，白天学习首选</div>
            <button class="btn sm full mt-10" :class="{primary: s.theme === 'light', ghost: s.theme !== 'light'}" @click="set('theme', 'light')">
              {{ s.theme === 'light' ? '✓ 当前使用' : '切换到亮色' }}
            </button>
          </div>
          <div class="theme-card" :class="{active: s.theme === 'dark'}">
            <div class="tc-preview dark">
              <div class="ln g" style="width:56%"></div>
              <div class="ln" style="width:78%"></div>
              <div class="ln" style="width:40%"></div>
            </div>
            <div class="tc-name-row">
              <b>🌙 暗色</b>
              <span v-if="s.theme === 'dark'" class="tc-check">✓</span>
            </div>
            <div class="tc-desc">夜间护眼，减少屏幕刺激</div>
            <button class="btn sm full mt-10" :class="{primary: s.theme === 'dark', ghost: s.theme !== 'dark'}" @click="set('theme', 'dark')">
              {{ s.theme === 'dark' ? '✓ 当前使用' : '切换到暗色' }}
            </button>
          </div>
        </div>
      </div>

      <!-- ──── 提醒与通知 ──── -->
      <div class="section-card">
        <div class="sc-head">
          <div class="sc-title"><span class="sc-ic">🔔</span> 每日目标提醒</div>
          <div class="sc-sub">不错过每一次打卡</div>
        </div>
        <div class="setting-list">
          <div class="step-item">
            <div class="step-icon">📬</div>
            <div class="step-body">
              <b>Web Push 推送</b>
              <small>设定了学习计划后，当天没背完时傍晚推送提醒（需浏览器允许通知）</small>
            </div>
            <button v-if="pushSupported" class="btn sm" :class="{primary: pushOn, ghost: !pushOn}" :disabled="pushBusy" @click="togglePush">
              {{ pushOn ? '已开启 ✓' : '开启提醒' }}
            </button>
            <span v-else class="desc">当前浏览器不支持推送</span>
          </div>
        </div>
      </div>

      <!-- ──── 账户 ──── -->
      <div class="section-card">
        <div class="sc-head">
          <div class="sc-title"><span class="sc-ic">👤</span> 账户</div>
          <div class="sc-sub">同步学习进度</div>
        </div>
        <div class="setting-list">
          <div class="step-item">
            <div class="step-icon">{{ Account.authenticated ? '✅' : '👋' }}</div>
            <div class="step-body">
              <div v-if="Account.authenticated">
                <b>已登录：{{ Account.username }}</b>
                <small>学习进度已受到账号保护，可在账户页修改密码。</small>
              </div>
              <div v-else>
                <b>游客模式</b>
                <small>注册后可保护当前学习进度，并在其他设备继续学习。</small>
              </div>
            </div>
            <a class="btn sm primary" href="#/account">{{ Account.authenticated ? '管理账户' : '登录 / 注册' }}</a>
          </div>
        </div>
      </div>

    </div>

    <!-- ====== 底部信息条 ====== -->
    <div class="save-bar">
      <div class="save-info">
        <span class="si-ic">💡</span>
        <span>所有更改将立即生效并同步到你的其他设备</span>
      </div>
    </div>

  </div>
</template>
