/* 错词 Boss 战页组件测试 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import BossPage from "../components/BossPage.vue";

const mkItem = (id, text, wc) => ({
  id, list: "test_words", text, phonetic: "", meaning: "", audio: "/audio/lazy/x.mp3", wrong_count: wc,
});
const session = { items: [mkItem("hello", "hello", 9), mkItem("world", "world", 4)], total: 2 };
const resultResp = {
  score: 2, total: 2, cleared: 2, wrong_remaining: 0,
  profile: { xp: 20, level: 1, title: "词童" },
};

const bossPosts = [];
let sessionOverride = null;

vi.mock("../lib/core", () => ({
  api: vi.fn(async (path, opts) => {
    if (path === "/boss/result") {
      bossPosts.push(JSON.parse(opts.body));
      return resultResp;
    }
    if (path === "/boss/session") return sessionOverride || session;
    return { ok: true };
  }),
  playWord: vi.fn(),
  sndCombo: vi.fn(),
  sndWrong: vi.fn(),
  stopAudio: vi.fn(),
}));

async function typeText(wrapper, text) {
  const inp = wrapper.find("#catch");
  for (const ch of text) {
    inp.element.value = ch;
    await inp.trigger("input");   // 组件读取 ev.target.value 后自行清空
  }
}

function startBtn(wrapper) {
  return wrapper.findAll("button").find((b) => b.text().includes("开始讨伐"));
}

describe("BossPage", () => {
  beforeEach(() => {
    bossPosts.length = 0;
    sessionOverride = null;
    localStorage.clear();
  });
  afterEach(() => { vi.useRealTimers(); });

  it("assembles the most-wrong army on the start screen", async () => {
    const wrapper = mount(BossPage);
    await flushPromises();
    expect(wrapper.text()).toContain("你有 3 颗心");
    const chips = wrapper.findAll(".army-chip");
    expect(chips).toHaveLength(2);
    expect(chips[0].text()).toContain("hello");
    expect(chips[0].text()).toContain("×9");   // 最痛的词排头
  });

  it("shows the empty-book screen when no wrong words remain", async () => {
    sessionOverride = { items: [], total: 0 };
    const wrapper = mount(BossPage);
    await flushPromises();
    expect(wrapper.text()).toContain("错词本已清空");
    expect(startBtn(wrapper)).toBeUndefined();
  });

  it("drains HP per hit and submits once with unique ids on victory", async () => {
    vi.useFakeTimers();
    const spy = vi.spyOn(window, "dispatchEvent");
    const wrapper = mount(BossPage);
    await flushPromises();
    await startBtn(wrapper).trigger("click");

    expect(wrapper.find(".boss-hp-num").text()).toBe("2 / 2");
    await typeText(wrapper, "hello");   // 第一刀命中
    expect(wrapper.find(".boss-hp-num").text()).toBe("1 / 2");
    await vi.advanceTimersByTimeAsync(400);   // 答对锁过后自动切词
    await flushPromises();

    await typeText(wrapper, "world");   // 最后一刀：Boss 血量归零
    await vi.advanceTimersByTimeAsync(700);
    await flushPromises();

    expect(bossPosts).toHaveLength(1);
    expect(bossPosts[0].answers).toStrictEqual([
      { id: "hello", right: true }, { id: "world", right: true },
    ]);
    expect(spy.mock.calls.some((c) => c[0].type === "profile-changed")).toBe(true);
    expect(wrapper.find(".boss-verdict.win").exists()).toBe(true);
    expect(wrapper.text()).toContain("Boss 击破");
    expect(wrapper.text()).toContain("错词本全清");
    spy.mockRestore();
  });

  it("loses after burning all three hearts and reports every miss", async () => {
    sessionOverride = {
      items: [mkItem("a", "cat", 5), mkItem("b", "dog", 3), mkItem("c", "fox", 1)],
      total: 3,
    };
    vi.useFakeTimers();
    const wrapper = mount(BossPage);
    await flushPromises();
    await startBtn(wrapper).trigger("click");

    for (const word of ["zzzzz", "zzzzz", "zzzz"]) {
      await typeText(wrapper, word);   // 全打错
      await vi.advanceTimersByTimeAsync(1000);
      await flushPromises();
    }
    expect(bossPosts).toHaveLength(1);
    expect(bossPosts[0].answers.every((a) => a.right === false)).toBe(true);
    expect(bossPosts[0].answers.map((a) => a.id)).toStrictEqual(["a", "b", "c"]);
    expect(wrapper.find(".boss-verdict.lose").exists()).toBe(true);
    expect(wrapper.text()).toContain("心力耗尽");
  });

  it("retreats without submitting when no answer was given", async () => {
    vi.useFakeTimers();
    const wrapper = mount(BossPage);
    await flushPromises();
    await startBtn(wrapper).trigger("click");
    await wrapper.findAll("button").find((b) => b.text().includes("撤退")).trigger("click");
    await flushPromises();
    expect(bossPosts).toHaveLength(0);   // 不战而退：没有可记账的答案
    expect(wrapper.text()).toContain("鸣金收兵");
  });
});
