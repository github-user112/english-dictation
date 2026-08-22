/* 听音选词页组件测试 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import QuizPage from "../components/QuizPage.vue";

const questions = [
  { id: "apple", text: "apple", audio: "/audio/lazy/apple.mp3", options: [
    { id: "apple", text: "apple", phonetic: "/ˈæp.əl/", meaning: "苹果" },
    { id: "pear", text: "pear", phonetic: "", meaning: "梨" },
    { id: "banana", text: "banana", phonetic: "", meaning: "香蕉" },
    { id: "cat", text: "cat", phonetic: "", meaning: "猫" },
  ] },
  { id: "dog", text: "dog", audio: "/audio/lazy/dog.mp3", options: [
    { id: "dog", text: "dog", phonetic: "", meaning: "狗" },
    { id: "fox", text: "fox", phonetic: "", meaning: "狐狸" },
    { id: "bird", text: "bird", phonetic: "", meaning: "鸟" },
    { id: "fish", text: "fish", phonetic: "", meaning: "鱼" },
  ] },
];

const resultPosts = [];
vi.mock("../lib/core", () => ({
  api: vi.fn(async (path, opts) => {
    if (path.startsWith("/quiz/session")) return { questions, total: questions.length };
    if (path === "/result") resultPosts.push(JSON.parse(opts.body));
    return { ok: true };
  }),
  playWord: vi.fn(),
  sndRight: vi.fn(),
  sndWrong: vi.fn(),
}));

import { playWord } from "../lib/core";

function findOption(wrapper, text) {
  return wrapper.findAll(".quiz-option").find((b) => b.text().includes(text));
}

describe("QuizPage", () => {
  beforeEach(() => {
    resultPosts.length = 0;
    playWord.mockClear();
  });
  afterEach(() => { vi.useRealTimers(); });

  it("should grade a correct pick and auto-advance after 1s", async () => {
    vi.useFakeTimers();
    const wrapper = mount(QuizPage);
    await flushPromises();
    expect(wrapper.text()).toContain("1 / 2");
    // 回归：playWord 必须拿到带 text 的题目，否则会去播 audio=undefined
    expect(playWord).toHaveBeenCalledWith(expect.objectContaining({ id: "apple", text: "apple" }));

    findOption(wrapper, "apple").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("答对了");
    expect(wrapper.text()).toContain("得分 1");
    expect(resultPosts[0]).toMatchObject({ id: "apple", right: true, mode: "quiz" });
    // 选对后没有手动按钮，等 1 秒自动跳
    expect(wrapper.findAll("button").find((b) => b.text().includes("下一题"))).toBeUndefined();

    await vi.advanceTimersByTimeAsync(1000);
    await flushPromises();
    expect(wrapper.text()).toContain("2 / 2");

    // 最后一题答对后自动进入结算页
    findOption(wrapper, "dog").trigger("click");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(1000);
    await flushPromises();
    expect(wrapper.text()).toContain("本轮完成");
    expect(wrapper.text()).toContain("答对 2 / 2");
  });

  it("should reveal the answer on a wrong pick and wait for manual next", async () => {
    vi.useFakeTimers();
    const wrapper = mount(QuizPage);
    await flushPromises();
    findOption(wrapper, "apple").trigger("click");   // 第 1 题答对（自动跳）
    await flushPromises();
    await vi.advanceTimersByTimeAsync(1000);
    await flushPromises();
    expect(wrapper.text()).toContain("2 / 2");

    findOption(wrapper, "fox").trigger("click");     // 第 2 题答错
    await flushPromises();
    expect(wrapper.text()).toContain("正确答案");
    expect(wrapper.text()).toContain("dog");
    expect(resultPosts[1]).toMatchObject({ id: "dog", right: false });
    // 答错不自动跳：手动按钮保持可见
    const nextBtn = wrapper.findAll("button").find((b) => b.text().includes("查看结果"));
    expect(nextBtn).toBeDefined();
    await nextBtn.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("本轮完成");
    expect(wrapper.text()).toContain("答对 1 / 2");
  });
});
