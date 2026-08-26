/* 每日挑战页组件测试 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import DailyPage from "../components/DailyPage.vue";

const questions = [
  { id: "apple", text: "apple", kind: "audio_en", audio: "/audio/lazy/apple.mp3", options: [
    { id: "apple", text: "apple", phonetic: "/ˈæp.əl/", meaning: "苹果" },
    { id: "pear", text: "pear", phonetic: "", meaning: "梨" },
    { id: "banana", text: "banana", phonetic: "", meaning: "香蕉" },
    { id: "cat", text: "cat", phonetic: "", meaning: "猫" },
  ] },
  { id: "dog", text: "dog", kind: "zh_en", audio: "/audio/lazy/dog.mp3", options: [
    { id: "dog", text: "dog", phonetic: "", meaning: "狗" },
    { id: "fox", text: "fox", phonetic: "", meaning: "狐狸" },
    { id: "bird", text: "bird", phonetic: "", meaning: "鸟" },
    { id: "fish", text: "fish", phonetic: "", meaning: "鱼" },
  ] },
];

/* 练习局（带 r= 轮次）：服务端出的另一批词 */
const practiceQuestions = [
  { id: "moon", text: "moon", kind: "audio_en", audio: "/audio/lazy/moon.mp3", options: [
    { id: "moon", text: "moon", phonetic: "", meaning: "月亮" },
    { id: "star", text: "star", phonetic: "", meaning: "星星" },
    { id: "sky", text: "sky", phonetic: "", meaning: "天空" },
    { id: "sea", text: "sea", phonetic: "", meaning: "海" },
  ] },
  { id: "sun", text: "sun", kind: "en_zh", audio: "/audio/lazy/sun.mp3", options: [
    { id: "sun", text: "sun", phonetic: "", meaning: "太阳" },
    { id: "rain", text: "rain", phonetic: "", meaning: "雨" },
    { id: "wind", text: "wind", phonetic: "", meaning: "风" },
    { id: "snow", text: "snow", phonetic: "", meaning: "雪" },
  ] },
];
const practiceSession = {
  day: "2026-08-26", list: "test_words", list_title: "CET-4",
  total: 2, questions: practiceQuestions,
  practice: true, completed: false, my_result: null,
};

const session = {
  day: "2026-08-26", list: "test_words", list_title: "CET-4",
  total: 2, questions, completed: false, my_result: null,
};
const resultResp = {
  duplicate: false, day: "2026-08-26", score: 1, total: 2,
  detail: [{ id: "apple", kind: "audio_en", right: true }, { id: "dog", kind: "zh_en", right: false }],
  profile: { xp: 12, level: 1, title: "词童", daily_streak: 1 },
};

const dailyPosts = [];
let sessionOverride = null;
let practiceRequested = "";

vi.mock("../lib/core", () => ({
  api: vi.fn(async (path, opts) => {
    if (path.startsWith("/daily/result")) {
      dailyPosts.push(JSON.parse(opts.body));
      return resultResp;
    }
    if (path.startsWith("/daily")) {
      const m = path.match(/[?&]r=(\d+)/);
      if (m) { practiceRequested = m[1]; return practiceSession; }
      return sessionOverride || session;
    }
    if (path === "/lists") return { lists: [{ key: "test_words", type: "words", title: "CET-4" }] };
    if (path === "/profile") return { level: 3, title: "词木", daily_streak: 0 };
    return { ok: true };
  }),
  playWord: vi.fn(),
  sndRight: vi.fn(),
  sndWrong: vi.fn(),
}));

function findOption(wrapper, text) {
  return wrapper.findAll(".quiz-option").find((b) => b.text().includes(text));
}

async function answerAllCorrectly(wrapper) {
  await findOption(wrapper, "apple").trigger("click");
  await vi.advanceTimersByTimeAsync(1000);   // 答对 1s 自动进下一题
  await flushPromises();
  // 第 2 题是看义选词：目标 dog，点 fox（错误）走手动翻页路径
  await findOption(wrapper, "fox").trigger("click");
  const btn = wrapper.findAll("button").find((b) => b.text().includes("查看结果"));
  await btn.trigger("click");
  await flushPromises();
}

describe("DailyPage", () => {
  beforeEach(() => {
    dailyPosts.length = 0;
    sessionOverride = null;
    practiceRequested = "";
    localStorage.clear();
  });
  afterEach(() => { vi.useRealTimers(); });

  it("records picks, submits once on finish and shows the grid", async () => {
    vi.useFakeTimers();
    const spy = vi.spyOn(window, "dispatchEvent");
    const wrapper = mount(DailyPage);
    await flushPromises();
    expect(localStorage.getItem("dict_daily_list")).toBe("cet4");   // 无参数时记住默认词库

    await answerAllCorrectly(wrapper);

    expect(dailyPosts).toHaveLength(1);
    expect(dailyPosts[0]).toStrictEqual({ list: "cet4", answers: [
      { id: "apple", picked: "apple" }, { id: "dog", picked: "fox" }] });
    // 结算页：得分、网格、等级行、分享文本
    expect(wrapper.text()).toContain("答对 1 / 2");
    expect(wrapper.findAll(".grid-cell.right")).toHaveLength(1);
    expect(wrapper.findAll(".grid-cell.wrong")).toHaveLength(1);
    expect(wrapper.text()).toContain("词童");
    expect(wrapper.find(".share-box").text()).toContain("英语听打 · 每日挑战 08-26 CET-4");
    expect(spy.mock.calls.some((c) => c[0].type === "profile-changed")).toBe(true);
    spy.mockRestore();
  });

  it("lands on the done screen when counted; replay deals fresh words and never submits", async () => {
    sessionOverride = {
      ...session, completed: true,
      my_result: { list: "test_words", score: 2, total: 2,
        detail: [{ id: "apple", kind: "audio_en", right: true }, { id: "dog", kind: "zh_en", right: true }] },
    };
    vi.useFakeTimers();
    const wrapper = mount(DailyPage);
    await flushPromises();
    expect(wrapper.text()).toContain("今日挑战完成");
    expect(dailyPosts).toHaveLength(0);   // 已计分：不再提交

    // 再玩一次：带轮次拉新词练习局
    await wrapper.findAll("button").find((b) => b.text().includes("再玩一次")).trigger("click");
    await flushPromises();
    expect(practiceRequested).toBe("1");
    expect(wrapper.find(".quiz-option").text()).toContain("moon");   // 不是上午那批词

    // 练习局作答：moon 对 → 自动跳；sun 听词选义点"太阳"对 → 1s 后自动进结算
    await wrapper.findAll(".quiz-option")[0].trigger("click");
    await vi.advanceTimersByTimeAsync(1100);
    await flushPromises();
    await findOption(wrapper, "太阳").trigger("click");
    await vi.advanceTimersByTimeAsync(1100);
    await flushPromises();

    expect(dailyPosts).toHaveLength(0);   // 练习局从不提交判分
    expect(wrapper.text()).toContain("练习局完成");
    expect(wrapper.text()).toContain("换一批词练手");
    expect(wrapper.text()).toContain("答对 2 / 2");
    expect(wrapper.find(".share-box").exists()).toBe(false);   // 非正式成绩不给分享物

    // 再玩一次继续换批：轮次递进
    practiceRequested = "";
    await wrapper.findAll("button").find((b) => b.text().includes("再玩一次")).trigger("click");
    await flushPromises();
    expect(practiceRequested).toBe("2");
  });

  it("keeps the share box usable when clipboard is unavailable", async () => {
    sessionOverride = {
      ...session, completed: true,
      my_result: { list: "test_words", score: 2, total: 2,
        detail: [{ id: "apple", kind: "audio_en", right: true }, { id: "dog", kind: "zh_en", right: false }] },
    };
    vi.useFakeTimers();
    const wrapper = mount(DailyPage);
    await flushPromises();
    // jsdom 没有 clipboard：点击复制不应抛错，文本块始终可见可手动复制
    await wrapper.findAll("button").find((b) => b.text().includes("复制文本")).trigger("click");
    await flushPromises();
    expect(wrapper.find(".share-box").text()).toContain("🟩🟥");
  });
});
