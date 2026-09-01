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
    <div class="page-heading"><span class="eyebrow">PERSONALIZE</span><h1>按你的节奏学习</h1><p>调整提示、主题和每日练习量。</p></div>
    <div class="section-title">听写显示</div>
    <div class="setting-row">
      <div><div class="lab">默认练习模式</div><div class="desc">纯听写不显示提示；辅助听写即时纠错；跟打显示原文且不计入掌握</div></div>
      <div class="mode-options">
        <button v-for="m in [{k:'pure',n:'纯听写'},{k:'assisted',n:'辅助'},{k:'follow',n:'跟打'}]" :key="m.k"
          class="btn ghost sm" :class="{primary:s.practiceMode===m.k}" @click="set('practiceMode',m.k)">{{ m.n }}</button>
      </div>
    </div>
    <div class="setting-row">
      <div><div class="lab">显示中文释义</div><div class="desc">在题卡上方显示汉语意思，答错后也会显示</div></div>
      <label class="switch"><input type="checkbox" :checked="s.showMeaning"
        @change="set('showMeaning', $event.target.checked)"><span class="slider"></span></label>
    </div>
    <div class="setting-row">
      <div><div class="lab">显示音标</div><div class="desc">单词模式下显示国际音标</div></div>
      <label class="switch"><input type="checkbox" :checked="s.showPhonetic"
        @change="set('showPhonetic', $event.target.checked)"><span class="slider"></span></label>
    </div>
    <div class="section-title">外观</div>
    <div class="setting-row">
      <div><div class="lab">界面主题</div><div class="desc">亮色 / 暗色切换</div></div>
      <div style="display:flex;gap:8px;">
        <button class="btn ghost" :class="{primary: s.theme === 'light'}" @click="set('theme', 'light')">亮色</button>
        <button class="btn ghost" :class="{primary: s.theme === 'dark'}" @click="set('theme', 'dark')">暗色</button>
      </div>
    </div>
    <div class="section-title">练习节奏</div>
    <div class="setting-row">
      <div><div class="lab">每日新词数</div><div class="desc">每天学习的新词/新句数量，复习词自动追加</div></div>
      <input type="number" min="5" max="50" style="width:70px;"
        :value="s.newPerDay" @change="set('newPerDay', Number($event.target.value))">
    </div>
    <div class="setting-row">
      <div><div class="lab">自动重播间隔（秒）</div><div class="desc">读完后隔几秒自动重播一次</div></div>
      <input type="number" min="1" max="60" style="width:70px;"
        :value="s.replayInterval" @change="set('replayInterval', Number($event.target.value))">
    </div>
    <div class="setting-row">
      <div><div class="lab">自动重播次数</div><div class="desc">第一次播放后再重播几次，0 表示只播一遍</div></div>
      <input type="number" min="0" max="10" style="width:70px;"
        :value="s.replayTimes" @change="set('replayTimes', Number($event.target.value))">
    </div>
    <div class="section-title">提醒</div>
    <div class="setting-row">
      <div><div class="lab">每日目标提醒</div><div class="desc">设定了学习计划后，当天没背完时傍晚推送提醒（需浏览器允许通知）</div></div>
      <button v-if="pushSupported" class="btn ghost" :class="{primary: pushOn}" :disabled="pushBusy" @click="togglePush">
        {{ pushOn ? '已开启 ✓' : '开启提醒' }}
      </button>
      <span v-else class="desc">当前浏览器不支持推送</span>
    </div>
    <div class="section-title">账户</div>
    <div class="setting-row">
      <div v-if="Account.authenticated"><div class="lab">已登录：{{ Account.username }}</div><div class="desc">学习进度已受到账号保护，可在账户页修改密码。</div></div>
      <div v-else><div class="lab">游客模式</div><div class="desc">注册后可保护当前学习进度，并在其他设备继续学习。</div></div>
      <a class="btn ghost" href="#/account">{{ Account.authenticated ? '管理账户' : '登录 / 注册' }}</a>
    </div>
  </div>
</template>
