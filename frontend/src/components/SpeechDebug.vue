<script setup>
/* 语音调试页（#/dbg）：一次性收集手机端语音识别环境信息，用户截图发回即可定位 */
import { onMounted, ref } from "vue";
import { listenServerOnce } from "../lib/speech";

const lines = ref([]);
const testing = ref(false);
const serverRecording = ref(false);
let serverRec = null;

function log(label, value) {
  lines.value.push(`${label}: ${value}`);
}

onMounted(async () => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  log("浏览器 UA", navigator.userAgent);
  log("协议", `${location.protocol}（isSecureContext=${window.isSecureContext}）`);
  log("SpeechRecognition", SR ? "存在" : "不存在");
  log("mediaDevices.getUserMedia", navigator.mediaDevices?.getUserMedia ? "存在" : "不存在");
  try {
    const p = await navigator.permissions.query({ name: "microphone" });
    log("麦克风权限(permissions API)", p.state);   // granted | denied | prompt
  } catch (e) {
    log("麦克风权限(permissions API)", `查询失败 ${e.name}`);
  }
});

/* 测试1：getUserMedia —— 只测系统/浏览器麦克风权限，与语音识别服务无关 */
async function testMic() {
  log("—— getUserMedia 测试 ——", "");
  try {
    const s = await navigator.mediaDevices.getUserMedia({ audio: true });
    s.getTracks().forEach((t) => t.stop());
    log("getUserMedia", "✅ 成功（麦克风权限没问题）");
  } catch (e) {
    log("getUserMedia", `❌ ${e.name} / ${e.message}`);
  }
}

/* 测试2：真实调一次语音识别，拿到原始错误码 */
function testSR() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  log("—— SpeechRecognition 测试 ——", "");
  if (!SR) { log("SpeechRecognition", "❌ 浏览器没有此 API"); return; }
  testing.value = true;
  const rec = new SR();
  rec.lang = "en-US";
  rec.interimResults = false;
  rec.onresult = (e) => { log("识别结果", `✅ 听到「${e.results[0][0].transcript}」`); testing.value = false; };
  rec.onerror = (e) => { log("识别错误码", `❌ ${e.error}${e.message ? " / " + e.message : ""}`); testing.value = false; };
  rec.onend = () => { testing.value = false; };
  try { rec.start(); log("start()", "已调用，请对着手机说句话…"); }
  catch (e) { log("start() 抛异常", `❌ ${e.name} / ${e.message}`); testing.value = false; }
}

/* 测试3：服务端识别（/api/asr Whisper 兜底路径），点「结束并识别」手动停止上传 */
function testServer() {
  log("—— 服务端识别测试 ——", "");
  testing.value = true;
  serverRecording.value = true;
  log("提示", "录音已开始，请对着手机说句话，然后点「🎤 说完了，开始识别」…");
  serverRec = listenServerOnce({
    onResult: (alts) => { log("服务端识别", `✅ 听到「${alts[0]}」`); testing.value = false; serverRecording.value = false; },
    onError: (e) => { log("服务端识别", `❌ ${e}`); testing.value = false; serverRecording.value = false; },
    onEnd: () => { testing.value = false; serverRecording.value = false; },
  });
}
</script>

<template>
  <div class="practice-card" style="max-width:640px;margin:0 auto;">
    <h2>🎤 语音环境调试</h2>
    <p class="hint">点下面两个按钮各测一次，然后整页截图发回来。</p>
    <div class="controls" style="margin:12px 0;">
      <button class="btn primary" @click="testMic">① 测麦克风权限</button>
      <button class="btn primary" :disabled="testing" @click="testSR">② 测语音识别(原生)</button>
      <button class="btn primary" :disabled="testing" @click="testServer">③ 测语音识别(服务端)</button>
      <button v-if="serverRecording" class="btn primary recording" @click="serverRec && serverRec.finish()">🎤 说完了，开始识别</button>
    </div>
    <pre style="white-space:pre-wrap;word-break:break-all;font-size:12px;background:var(--card2,#f5f5f5);padding:12px;border-radius:8px;">{{ lines.join("\n") }}</pre>
  </div>
</template>
