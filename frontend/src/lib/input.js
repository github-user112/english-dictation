// 移动端 IME 安全的「隐藏输入框」处理。
//
// 关键：部分手机 IME 对纯英文提交，compositionend 之后不触发 input 事件，
// 导致组字结果无法投递、value 不清空（越积越多）。
// 对策：在 compositionend 时直接投递 + 清空 value，并标记跳过紧随其后的 input 事件，
// 防止中文（compEnd + input 都触发）时双投。

import { kbdLog } from "./kbdlog";

let skipNext = false;   // 上一次 compEnd 已投递，跳过紧随其后的 input 事件

export function onCompStart(ev, el) {
  kbdLog("compStart", { data: ev.data, val: el?.value ?? "" });
}

export function onCompEnd(ev, el, typeChar, ok) {
  const ch = ev.data || el?.value || "";
  el && (el.value = "");   // 立即清空，防止旧文本累积到下一次组字
  kbdLog("compEnd", { ch });
  skipNext = !!ch;
  if (ch && ok()) {
    typeChar(ch);
    kbdLog("delivered", { ch, from: "compEnd" });
  }
}

export function onCharInput(ev, typeChar, ok) {
  if (ev.isComposing) {
    kbdLog("input:composing", { val: ev.target?.value ?? "" });
    return;
  }
  if (skipNext) { skipNext = false; return; }
  const ch = ev.data || ev.target.value;
  if (!ch || !ok()) return;
  ev.target.value = "";
  kbdLog("input", { ch });
  typeChar(ch);
}

export function onBlurCatch(el, refocus) {
  kbdLog("blur");
  el && el.setAttribute("readonly", "");
  if (refocus) setTimeout(() => refocus(), 60);
}

/* 页面级点击守卫：点非交互区域时阻止默认焦点转移 + 收回焦点——
   软键盘只有用户主动收起（键盘自身的收起键）才收，点页面任何位置都不收。
   按钮/链接/输入框/可点卡片(role=button)等交互元素跳过，各自的 handler 照常工作。
   注：pointerdown 的 preventDefault 不影响触屏滚动（滚动由 touch-action/触摸链路决定），
   但会抑制兼容鼠标事件（mousedown/click），非交互区域本来就没有 click 行为，安全。 */
export function makeTapGuard(focusCatch, ok) {
  return function (ev) {
    if (ok && !ok()) return;
    const t = ev.target;
    if (!t || !t.closest) return;
    if (t.closest("button, a, input, select, textarea, .btn, [role=button], [tabindex]")) return;
    if (ev.pointerType === "mouse" && ev.button !== 0) return;
    ev.preventDefault();
    focusCatch();
  };
}
