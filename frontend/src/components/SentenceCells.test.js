/* SentenceCells 组件测试 */
import { describe, it, expect, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";
import SentenceCells from "../components/SentenceCells.vue";

function makeSentence(text, opts = {}) {
  return { id: "1", text, phonetic: "", meaning: "测试", kind: "sentence", ...opts };
}

describe("SentenceCells", () => {
  it("should render a word cell for each word in the sentence", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("Hello world"), submitted: false, feedback: false },
    });
    const cells = wrapper.findAll(".cell.word-line");
    expect(cells.length).toBe(2);
  });

  it("should handle punctuation at word boundaries", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("Hello, world!"), submitted: false, feedback: false },
    });
    const puncts = wrapper.findAll(".punct");
    expect(puncts.length).toBe(2);
  });

  it("typeWordChar should type characters into current word", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("hi"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeWordChar("h");
    vm.typeWordChar("i");
    expect(vm.isCorrect()).toBe(true);
  });

  it("isCorrect should return false for wrong words", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("hello"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeWordChar("w");
    vm.typeWordChar("r");
    vm.typeWordChar("o");
    vm.typeWordChar("n");
    vm.typeWordChar("g");
    expect(vm.isCorrect()).toBe(false);
  });

  it("space should advance to next word", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("a b"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeWordChar("a");
    vm.typeWordChar(" ");  // advance to next word
    expect(vm.isCorrect()).toBe(false);  // second word not typed yet
    vm.typeWordChar("b");
    expect(vm.isCorrect()).toBe(true);
  });

  it("backspace should remove last character or go to previous word", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("a b"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeWordChar("a");
    vm.typeWordChar(" ");
    vm.typeWordChar("b");
    vm.backspace();  // remove 'b'
    vm.backspace();  // go back to first word
    expect(vm.isCorrect()).toBe(false);
  });

  it("paint should mark all words as right or wrong", async () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("good day"), submitted: false, feedback: true, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeWordChar("g");
    vm.typeWordChar("o");
    vm.typeWordChar("o");
    vm.typeWordChar("d");
    vm.typeWordChar(" ");
    vm.typeWordChar("d");
    vm.typeWordChar("a");
    vm.typeWordChar("y");
    vm.paint();
    await wrapper.vm.$nextTick();
    const cells = wrapper.findAll(".cell.word-line");
    expect(cells[0].classes()).toContain("right");
    expect(cells[1].classes()).toContain("right");
  });

  it("serialize and restore should round-trip state", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("hello world"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeWordChar("h");
    vm.typeWordChar("e");
    const state = vm.serialize();
    expect(state.input).toBeDefined();
    expect(state.cursor).toBe(0);

    const wrapper2 = mount(SentenceCells, {
      props: { tokens: makeSentence("hello world"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    wrapper2.vm.restore(state);
    wrapper2.vm.typeWordChar("l");
    wrapper2.vm.typeWordChar("l");
    wrapper2.vm.typeWordChar("o");
    wrapper2.vm.typeWordChar(" ");
    wrapper2.vm.typeWordChar("w");
    wrapper2.vm.typeWordChar("o");
    wrapper2.vm.typeWordChar("r");
    wrapper2.vm.typeWordChar("l");
    wrapper2.vm.typeWordChar("d");
    expect(wrapper2.vm.isCorrect()).toBe(true);
  });

  it("should let hyphenated words be typed with the hyphen", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("forty-one."), submitted: false, feedback: true, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    const cells = wrapper.findAll(".cell.word-line");
    expect(cells.length).toBe(1);          // 一个词核 cells，句号是独立标点
    expect(wrapper.findAll(".punct").length).toBe(1);
    for (const ch of "forty-one") vm.typeWordChar(ch);
    expect(vm.isCorrect()).toBe(true);
  });

  it("should accept digits inside words (e.g. 000-volt)", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("000-volt"), submitted: false, feedback: true, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    for (const ch of "000-volt") vm.typeWordChar(ch);
    expect(vm.isCorrect()).toBe(true);
  });

  it("should accept abbrevations with inner periods (e.g. B.C.)", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("B.C."), submitted: false, feedback: true, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    for (const ch of "B.C") vm.typeWordChar(ch);
    expect(vm.isCorrect()).toBe(true);
  });

  it("should accept numbers with commas (e.g. 2,400)", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("2,400"), submitted: false, feedback: true, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    for (const ch of "2,400") vm.typeWordChar(ch);
    expect(vm.isCorrect()).toBe(true);
  });

  it("should keep leading quotes as punctuation not part of the word", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("'No,'"), submitted: false, feedback: true, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    for (const ch of "No") vm.typeWordChar(ch);
    expect(vm.isCorrect()).toBe(true);
    expect(wrapper.findAll(".punct").length).toBe(2);  // 前导引号 + 尾随引号逗号
  });

  it("should keep regression: normal words with trailing comma still work", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("Hello, world!"), submitted: false, feedback: true, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    for (const ch of "Hello") vm.typeWordChar(ch);
    vm.typeWordChar(" ");
    for (const ch of "world") vm.typeWordChar(ch);
    expect(vm.isCorrect()).toBe(true);
  });

  it("should ignore underscores both in input and judging", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("Chang_woo"), submitted: false, feedback: true, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeWordChar("_");            // 输入下划线被忽略
    for (const ch of "Chang") vm.typeWordChar(ch);
    vm.typeWordChar("_");            // 中间的下划线也忽略
    for (const ch of "woo") vm.typeWordChar(ch);
    expect(vm.isCorrect()).toBe(true);  // 不打/打错下划线都算对
  });

  it("IME 组字带出的句尾标点应跳词而不是判错", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("My name is Robert."), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    let anyWrong = false;
    for (const ch of "My name is Robert.") anyWrong = vm.typeWordChar(ch) || anyWrong;
    expect(anyWrong).toBe(false);       // 句尾句号不判错
    expect(vm.isCorrect()).toBe(true);  // 整句判对
  });

  it("词中标点照常输入：逗号不触发跳词", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("Hello, world!"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    for (const ch of "Hello, world!") vm.typeWordChar(ch);
    expect(vm.isCorrect()).toBe(true);
  });

  it("词核未输完时后缀标点仍进输入（B.C. 的句点）", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("B.C."), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    for (const ch of "B.C") vm.typeWordChar(ch);
    expect(vm.isCorrect()).toBe(true);
    vm.typeWordChar(".");               // 词核已完整，句尾点被忽略
    expect(vm.isCorrect()).toBe(true);
  });

  it("typeText 整句灌入应按词分发进格", async () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("My name is Robert."), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const wrong = wrapper.vm.typeText("My name is Robert.");
    expect(wrong).toBe(false);
    expect(wrapper.vm.isCorrect()).toBe(true);
    await wrapper.vm.$nextTick();
    const cells = wrapper.findAll(".cell.word-line");
    expect(cells[0].text()).toBe("My");   // 各进各格，不是全堆在第一格
    expect(cells[3].text()).toBe("Robert");
  });

  it("typeText 灌入时错词标红留在原格，不堵后面的词", async () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("My name is Robert."), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const wrong = wrapper.vm.typeText("My neme is Robert.");
    expect(wrong).toBe(true);
    expect(wrapper.vm.isCorrect()).toBe(false);
    await wrapper.vm.$nextTick();
    const cells = wrapper.findAll(".cell.word-line");
    expect(cells[1].text()).toBe("neme");
    expect(cells[1].classes()).toContain("wrong");   // 错词标红
    expect(cells[2].text()).toBe("is");              // 后面的词照常进自己的格
    expect(cells[3].text()).toBe("Robert");
  });

  it("NBSP/全角空格同样切词", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("My name"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    wrapper.vm.typeText("My name");
    expect(wrapper.vm.isCorrect()).toBe(true);
    const w2 = mount(SentenceCells, {
      props: { tokens: makeSentence("My name"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    w2.vm.typeText("My　name");
    expect(w2.vm.isCorrect()).toBe(true);
  });

  it("标点不参与判分：多加的逗号句号也算对", async () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("She is Chinese too."), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const wrong = wrapper.vm.typeText("She is Chinese, too.");
    expect(wrong).toBe(false);              // 逗号不判错
    expect(wrapper.vm.isCorrect()).toBe(true);
    await wrapper.vm.$nextTick();
    const cells = wrapper.findAll(".cell.word-line");
    expect(cells[2].classes()).not.toContain("wrong");
    expect(cells[3].classes()).not.toContain("wrong");
  });

  it("省略标点也算对：don't 打成 dont 不判错", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("I don't know."), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const wrong = wrapper.vm.typeText("I dont know");
    expect(wrong).toBe(false);
    expect(wrapper.vm.isCorrect()).toBe(true);
  });

  it("focusWord 定位到词尾，配合方向键可改掉词中间的错字母", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("My name is Robert."), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeText("My neme is Robert");
    expect(vm.isCorrect()).toBe(false);
    vm.focusWord(1);            // 无坐标事件 → 光标落词尾（jsdom 无 caretRangeFromPoint）
    vm.moveCursor(-2);          // neme → ne|me
    vm.backspace();             // 删 e → nme
    vm.typeWordChar("a");       // 插入 a → name
    expect(vm.isCorrect()).toBe(true);
  });

  it("moveCursor 移进词中间后可插入修正", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("My name is Robert."), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeText("My nme is Robert");
    vm.focusWord(1);            // 光标在 "nme" 词尾
    vm.moveCursor(-2);          // 移到 n|me
    vm.typeWordChar("a");       // 插入 → name
    expect(vm.isCorrect()).toBe(true);
    expect(vm.answerText()).toBe("My name is Robert");
  });

  it("词中间 backspace 删光标前一个字符", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("hello world"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeText("hexllo world");
    vm.focusWord(0);
    vm.moveCursor(-3);          // hexllo 词尾 → hex|llo
    vm.backspace();             // 删 x → hello
    expect(vm.answerText()).toBe("hello world");
    expect(vm.isCorrect()).toBe(true);
  });

  it("moveCursor 可跨词移动", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("a b"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeText("a b");
    vm.moveCursor(-1);          // 第二词词首
    vm.moveCursor(-1);          // 跨回第一词词尾
    vm.backspace();             // 删 "a"
    expect(vm.answerText()).toBe("b");
  });

  it("serialize/restore 带 charPos 往返", () => {
    const wrapper = mount(SentenceCells, {
      props: { tokens: makeSentence("hello world"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeText("hello world");
    vm.focusWord(0);
    vm.moveCursor(-2);          // hel|lo
    const state = vm.serialize();
    expect(state.charPos).toBe(3);
    const w2 = mount(SentenceCells, {
      props: { tokens: makeSentence("hello world"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    w2.vm.restore(state);
    w2.vm.typeWordChar("X");    // 在词 0 第 3 字符后插入
    expect(w2.vm.answerText()).toBe("helXlo world");
  });
});