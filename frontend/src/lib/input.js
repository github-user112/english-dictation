// 移动端 IME 安全的「隐藏输入框」处理。
//
// 关键：部分手机 IME 对纯英文提交，compositionend 之后不触发 input 事件，
// 导致组字结果无法投递、value 不清空（越积越多）。
// 对策：在 compositionend 时直接投递 + 清空 value，并标记跳过紧随其后的 input 事件，
// 防止中文（compEnd + input 都触发）时双投。

import { kbdLog } from "./kbdlog";

// 回声标记：compEnd 已投递的文本。紧随的 input 事件若内容相同即为中文 IME 的回声，跳过防双投；
// 英文 IME 提交后常常没有回声 input——所以只按内容精确跳过，绝不盲跳下一个事件（会吞掉真实输入）。
let skipEcho = "";

export function onCompStart(ev, el) {
  kbdLog("compStart", { data: ev.data, val: el?.value ?? "" });
}

export function onCompEnd(ev, el, typeChar, ok) {
  const ch = ev.data || el?.value || "";
  el && (el.value = "");   // 立即清空，防止旧文本累积到下一次组字
  kbdLog("compEnd", { ch });
  skipEcho = ch;
  if (ch && ok()) {
    typeChar(ch);
    kbdLog("delivered", { ch, from: "compEnd" });
  }
}

export function onCharInput(ev, typeChar, ok, onDelete) {
  if (ev.isComposing) {
    kbdLog("input:composing", { val: ev.target?.value ?? "" });
    return;
  }
  // 退格永远最先处理：不被回声跳过拦截（组字提交后的第一次退格是真实操作）。
  // 移动端退格：多数软键盘不发 Backspace keydown，只发 delete* input 事件（data 为 null）。
  // deleteWordBackward 也只退一格——逐格删除语义一致，够用。
  if (ev.inputType && ev.inputType.startsWith("delete")) {
    skipEcho = "";
    ev.target.value = "";
    kbdLog("input:delete", { inputType: ev.inputType });
    if (ok()) onDelete?.();
    return;
  }
  const ch = ev.data || ev.target.value;
  if (ch && ch === skipEcho) {   // compEnd 的回声：跳过
    skipEcho = "";
    ev.target.value = "";
    return;
  }
  skipEcho = "";
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

/* 全局兜底：软键盘弹起会把格子区（.cells-section/.cells-wrap）顶出可视区——
   焦点在 1px 的隐藏输入框 #catch 上，浏览器自动滚动对它无意义。
   visualViewport 明显收缩（≥150px，排除地址栏伸缩）且焦点在 #catch 时，
   把格子区滚到可视视口中央。四个打字页（Practice/Memorize/Boss/Sprint）共用此模块，免逐页接线。
   ponytail: 模块级副作用；scrollIntoView 无法对准 visualViewport，故手动算滚动量 */
if (typeof window !== "undefined" && window.visualViewport) {
  const vv = window.visualViewport;
  let maxH = vv.height;
  let timer = null;
  vv.addEventListener("resize", () => {
    if (vv.height > maxH) maxH = vv.height;
    if (maxH - vv.height < 150 || document.activeElement?.id !== "catch") return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      const el = document.querySelector(".cells-section,.cells-wrap");
      if (!el) return;
      const r = el.getBoundingClientRect();   // 相对布局视口；换算进可视视口后居中
      const delta = (r.top - vv.offsetTop) - (vv.height - r.height) / 2;
      window.scrollBy({ top: delta, behavior: "smooth" });
    }, 250);   // 等键盘动画落定
  });
}
