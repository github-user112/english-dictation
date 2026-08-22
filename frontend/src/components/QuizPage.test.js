/* 听音选词页组件测试 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import QuizPage from "../components/QuizPage.vue";

const questions = [
  { id: "apple", audio: "/audio/lazy/apple.mp3", options: [
    { id: "apple", text: "apple", phonetic: "/ˈæp.əl/", meaning: "苹果" },
    { id: "pear", text: "pear", phonetic: "", meaning: "梨" },
    { id: "banana", text: "banana", phonetic: "", meaning: "香蕉" },
    { id: "cat", text: "cat", phonetic: "", meaning: "猫" },
  ] },
  { id: "dog", audio: "/audio/lazy/dog.mp3", options: [
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

function findOption(wrapper, text) {
  return wrapper.findAll(".quiz-option").find((b) => b.text().includes(text));
}

describe("QuizPage", () => {
  beforeEach(() => { resultPosts.length = 0; });

  it("should grade a correct pick and advance through all questions", async () => {
    const wrapper = mount(QuizPage);
    await flushPromises();
    expect(wrapper.text()).toContain("1 / 2");

    findOption(wrapper, "apple").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("答对了");
    expect(wrapper.text()).toContain("得分 1");
    expect(resultPosts[0]).toMatchObject({ id: "apple", right: true, mode: "quiz" });

    await wrapper.findAll("button").find((b) => b.text().includes("下一题")).trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("2 / 2");
  });

  it("should reveal the answer on a wrong pick and reach the summary", async () => {
    const wrapper = mount(QuizPage);
    await flushPromises();
    findOption(wrapper, "apple").trigger("click");   // 第 1 题答对
    await flushPromises();
    await wrapper.findAll("button").find((b) => b.text().includes("下一题")).trigger("click");
    await flushPromises();

    findOption(wrapper, "fox").trigger("click");     // 第 2 题答错
    await flushPromises();
    expect(wrapper.text()).toContain("正确答案");
    expect(wrapper.text()).toContain("dog");
    expect(resultPosts[1]).toMatchObject({ id: "dog", right: false });

    await wrapper.findAll("button").find((b) => b.text().includes("查看结果")).trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("本轮完成");
    expect(wrapper.text()).toContain("答对 1 / 2");
  });
});
