<script setup>
import { ref } from "vue";
import { Settings } from "../lib/core";

const s = ref(Settings.get());

function set(key, val) {
  Settings.set({ [key]: val });
  s.value = Settings.get();
}
function copyLink() {
  navigator.clipboard.writeText(location.href).then(
    () => alert("链接已复制"),
    () => alert("复制失败"));
}
</script>

<template>
  <div>
    <div class="section-title">听写显示</div>
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
    <div class="setting-row">
      <div><div class="lab">单词跟打</div><div class="desc">格子下方显示原文，照着打（跟打模式）</div></div>
      <label class="switch"><input type="checkbox" :checked="s.showWord"
        @change="set('showWord', $event.target.checked)"><span class="slider"></span></label>
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
    <div class="section-title">我的</div>
    <div class="setting-row">
      <div><div class="lab">我的学习链接</div><div class="desc" style="word-break:break-all;">当前地址已含你的 uuid，分享这个链接即可同步你的进度</div></div>
      <button class="btn ghost" @click="copyLink">复制</button>
    </div>
  </div>
</template>