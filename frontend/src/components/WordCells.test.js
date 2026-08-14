/* WordCells 组件测试 */
import { describe, it, expect, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";
import WordCells from "../components/WordCells.vue";

function makeWord(text, opts = {}) {
  return { id: text, text, phonetic: "/test/", meaning: "测试", kind: "word", ...opts };
}

describe("WordCells", () => {
  it("should render letter cells for each letter in the word", () => {
    const wrapper = mount(WordCells, {
      props: { tokens: makeWord("hello"), submitted: false, feedback: false },
    });
    // "hello" has 5 letters, pure mode showSequence=false renders a single line
    // Default practiceMode is "assisted", so showSequence is true
    const cells = wrapper.findAll(".cell.letter-line");
    expect(cells.length).toBe(5);
  });

  it("should render punctuation as punct spans", () => {
    const wrapper = mount(WordCells, {
      props: { tokens: makeWord("it's"), submitted: false, feedback: false },
    });
    const puncts = wrapper.findAll(".punct");
    expect(puncts.length).toBe(1);
    expect(puncts[0].text()).toBe("'");
  });

  it("should not render any input in pure mode initially", () => {
    const wrapper = mount(WordCells, {
      props: { tokens: makeWord("hello"), submitted: false, feedback: false, practiceMode: "pure" },
    });
    // In pure mode with showSequence=false, renders a single pure-line
    const pureLine = wrapper.find(".pure-line");
    expect(pureLine.exists()).toBe(true);
  });

  it("typeLetter should fill characters", () => {
    const wrapper = mount(WordCells, {
      props: { tokens: makeWord("cat"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeLetter("c");
    vm.typeLetter("a");
    vm.typeLetter("t");
    expect(vm.isFull()).toBe(true);
    expect(vm.isCorrect()).toBe(true);
  });

  it("typeLetter should detect wrong character", () => {
    const wrapper = mount(WordCells, {
      props: { tokens: makeWord("cat"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    const wrong = vm.typeLetter("x");
    expect(wrong).toBe(true);
  });

  it("isCorrect should return false for wrong input", () => {
    const wrapper = mount(WordCells, {
      props: { tokens: makeWord("cat"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeLetter("d");
    vm.typeLetter("o");
    vm.typeLetter("g");
    expect(vm.isCorrect()).toBe(false);
  });

  it("backspace should remove last character", () => {
    const wrapper = mount(WordCells, {
      props: { tokens: makeWord("ab"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeLetter("a");
    vm.typeLetter("b");
    expect(vm.isFull()).toBe(true);
    vm.backspace();
    expect(vm.isFull()).toBe(false);
  });

  it("reset should clear all input", () => {
    const wrapper = mount(WordCells, {
      props: { tokens: makeWord("test"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeLetter("t");
    vm.typeLetter("e");
    vm.reset();
    expect(vm.isCorrect()).toBe(false);
  });

  it("paint should mark all cells as right", async () => {
    const wrapper = mount(WordCells, {
      props: { tokens: makeWord("hi"), submitted: false, feedback: true, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeLetter("h");
    vm.typeLetter("i");
    vm.paint();
    await wrapper.vm.$nextTick();
    const cells = wrapper.findAll(".cell.letter-line");
    expect(cells.length).toBe(2);
    expect(cells[0].classes()).toContain("right");
    expect(cells[1].classes()).toContain("right");
  });

  it("markWrong should mark missing and wrong cells", async () => {
    const wrapper = mount(WordCells, {
      props: { tokens: makeWord("dog"), submitted: false, feedback: true, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeLetter("d");
    vm.typeLetter("e");
    vm.markWrong();
    await wrapper.vm.$nextTick();
    const cells = wrapper.findAll(".cell.letter-line");
    expect(cells[0].classes()).toContain("right");  // d matches
    expect(cells[1].classes()).toContain("wrong");  // e != o
    expect(cells[2].classes()).toContain("miss");   // not typed
  });

  it("serialize and restore should round-trip state", () => {
    const wrapper = mount(WordCells, {
      props: { tokens: makeWord("hello"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    const vm = wrapper.vm;
    vm.typeLetter("h");
    vm.typeLetter("e");
    const state = vm.serialize();
    expect(state.input).toBeDefined();
    expect(state.cursor).toBe(2);

    // Restore to a new instance
    const wrapper2 = mount(WordCells, {
      props: { tokens: makeWord("hello"), submitted: false, feedback: false, practiceMode: "assisted" },
    });
    wrapper2.vm.restore(state);
    expect(wrapper2.vm.isCorrect()).toBe(false);
    wrapper2.vm.typeLetter("l");
    wrapper2.vm.typeLetter("l");
    wrapper2.vm.typeLetter("o");
    expect(wrapper2.vm.isCorrect()).toBe(true);
  });
});