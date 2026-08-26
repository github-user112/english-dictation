/* 英中配对消消乐页组件测试 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import MatchPage from "../components/MatchPage.vue";

const items = [
  { id: "apple", list: "test_words", text: "apple", phonetic: "/ˈæp.əl/", meaning: "苹果", audio: "/audio/lazy/apple.mp3" },
  { id: "dog", list: "test_words", text: "dog", phonetic: "", meaning: "狗", audio: "/audio/lazy/dog.mp3" },
  { id: "cat", list: "test_words", text: "cat", phonetic: "", meaning: "猫", audio: "/audio/lazy/cat.mp3" },
];

const matchPosts = [];
let sessionOverride = null;

vi.mock("../lib/core", () => ({
  api: vi.fn(async (path, opts) => {
    if (path === "/match/result") {
      const body = JSON.parse(opts.body);
      matchPosts.push(body);
      const perfect = body.answers.filter((a) => a.right).length;
      return { total: body.answers.length, perfect,
        profile: { xp: 10 * perfect + 2 * (body.answers.length - perfect) } };
    }
    if (path.startsWith("/match/session")) return sessionOverride || { list: "test_words", items, total: items.length };
    if (path === "/lists") {
      return { lists: [{ key: "test_words", type: "words", title: "Test Words" },
                       { key: "test_sents", type: "sentences", title: "Sents" }] };
    }
    return { ok: true };
  }),
  playWord: vi.fn(),
  stopAudio: vi.fn(),
}));

function tileByText(wrapper, text) {
  return wrapper.findAll(".pair-tile").find((t) => t.text().includes(text));
}

describe("MatchPage", () => {
  beforeEach(() => { matchPosts.length = 0; sessionOverride = null; localStorage.clear(); });
  afterEach(() => { vi.useRealTimers(); });

  it("renders start screen with word lists only and deals shuffled tiles", async () => {
    const wrapper = mount(MatchPage);
    await flushPromises();
    const options = wrapper.findAll(".match-select")[0].findAll("option");
    expect(options).toHaveLength(1);   // 句子库被过滤掉
    await wrapper.findAll("button").find((b) => b.text().includes("开始配对")).trigger("click");
    await flushPromises();
    // 3 对词 → 6 张牌：每词一个英文面一个中文面
    const tiles = wrapper.findAll(".pair-tile");
    expect(tiles).toHaveLength(6);
    expect(wrapper.findAll(".pair-tile.en")).toHaveLength(3);
    expect(wrapper.findAll(".pair-tile.zh")).toHaveLength(3);
    expect(wrapper.text()).toContain("已消 0/3");
  });

  it("eliminates matched pairs, shakes mismatches and submits once on win", async () => {
    vi.useFakeTimers();
    const spy = vi.spyOn(window, "dispatchEvent");
    const wrapper = mount(MatchPage);
    await flushPromises();
    await wrapper.findAll("button").find((b) => b.text().includes("开始配对")).trigger("click");
    await flushPromises();

    // 先配错一次：apple 配 狗
    await tileByText(wrapper, "apple").trigger("click");
    await tileByText(wrapper, "狗").trigger("click");
    expect(wrapper.text()).toContain("步数 1 · 失误 1");
    expect(wrapper.findAll(".pair-tile.shaking")).toHaveLength(2);

    // 再正确配对 apple ↔ 苹果
    await vi.advanceTimersByTimeAsync(700);   // 等抖动结束
    await tileByText(wrapper, "apple").trigger("click");
    await tileByText(wrapper, "苹果").trigger("click");
    expect(wrapper.findAll(".pair-tile.gone")).toHaveLength(2);   // 双牌消散
    expect(wrapper.text()).toContain("已消 1/3");

    // 配完剩余两对
    for (const [en, zh] of [["dog", "狗"], ["cat", "猫"]]) {
      await tileByText(wrapper, en).trigger("click");
      await tileByText(wrapper, zh).trigger("click");
    }
    await flushPromises();

    expect(matchPosts).toHaveLength(1);
    // 配错涉及双方：apple 与 狗(dog) 都失去"首配即中"，只有 cat 满额
    expect(matchPosts[0]).toStrictEqual({ list: "test_words", answers: [
      { id: "apple", right: false }, { id: "dog", right: false }, { id: "cat", right: true },
    ] });
    expect(spy.mock.calls.some((c) => c[0].type === "profile-changed")).toBe(true);
    expect(wrapper.text()).toContain("桌面清空");
    expect(wrapper.text()).toContain("首配即中 1/3");
    spy.mockRestore();
  });

  it("shows a perfect run message when nothing was mismatched", async () => {
    sessionOverride = { list: "test_words",
      items: [items[0]], total: 1 };
    const wrapper = mount(MatchPage);
    await flushPromises();
    await wrapper.findAll("button").find((b) => b.text().includes("开始配对")).trigger("click");
    await flushPromises();
    await tileByText(wrapper, "apple").trigger("click");
    await tileByText(wrapper, "苹果").trigger("click");
    await flushPromises();
    expect(matchPosts[0].answers).toStrictEqual([{ id: "apple", right: true }]);
    expect(wrapper.text()).toContain("全部首配即中");
  });
});
