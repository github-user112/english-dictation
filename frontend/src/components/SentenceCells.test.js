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
});