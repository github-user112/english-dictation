/* onCharInput 删除事件测试：移动端软键盘退格只发 delete* input 事件（data 为 null），
   必须投递给 onDelete，而不是被当作空输入丢弃 */
import { describe, it, expect, vi } from "vitest";
import { onCharInput, onCompEnd } from "./input";

function makeEv(over = {}) {
  return { isComposing: false, data: null, inputType: "deleteContentBackward",
    target: { value: "" }, ...over };
}

describe("onCharInput delete handling", () => {
  it("deleteContentBackward should call onDelete, not typeChar", () => {
    const typeChar = vi.fn(), onDelete = vi.fn();
    onCharInput(makeEv(), typeChar, () => true, onDelete);
    expect(onDelete).toHaveBeenCalledOnce();
    expect(typeChar).not.toHaveBeenCalled();
  });

  it("deleteWordBackward should also map to one backspace", () => {
    const onDelete = vi.fn();
    onCharInput(makeEv({ inputType: "deleteWordBackward" }), vi.fn(), () => true, onDelete);
    expect(onDelete).toHaveBeenCalledOnce();
  });

  it("delete should respect ok() gate", () => {
    const onDelete = vi.fn();
    onCharInput(makeEv(), vi.fn(), () => false, onDelete);
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("missing onDelete should not break insert path", () => {
    const typeChar = vi.fn();
    onCharInput(makeEv({ inputType: "insertText", data: "a" }), typeChar, () => true);
    expect(typeChar).toHaveBeenCalledWith("a");
  });

  it("compEnd echo with same text should be skipped, different text delivered", () => {
    const typeChar = vi.fn();
    onCompEnd({ data: "你好" }, { value: "你好" }, typeChar, () => true);
    expect(typeChar).toHaveBeenCalledWith("你好");
    onCharInput(makeEv({ inputType: "insertCompositionText", data: "你好" }), typeChar, () => true);
    expect(typeChar).toHaveBeenCalledTimes(1);   // 回声被跳过
    onCharInput(makeEv({ inputType: "insertText", data: "a" }), typeChar, () => true);
    expect(typeChar).toHaveBeenCalledTimes(2);   // 真实输入不受影响
  });

  it("delete right after compEnd (no echo) must NOT be swallowed", () => {
    const typeChar = vi.fn(), onDelete = vi.fn();
    onCompEnd({ data: "hello" }, { value: "" }, typeChar, () => true);   // 英文 IME：无回声 input
    onCharInput(makeEv(), typeChar, () => true, onDelete);
    expect(onDelete).toHaveBeenCalledOnce();   // 退格穿透 skipEcho
  });
});
