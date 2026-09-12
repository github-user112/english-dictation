/* 背单词页自测：答错后亮答案、Enter 清空重打、打对才过（不误判重、不换题） */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import MemorizePage from "../components/MemorizePage.vue";

const cellsStub = vi.hoisted(() => ({ correct: false, full: true, resets: 0 }));
const posts = vi.hoisted(() => []);

vi.mock("../lib/core", async () => {
  const { ref } = await import("vue");
  return {
    api: vi.fn(async (path, opts) => {
      if (path.startsWith("/memorize/session")) {
        return { items: [{ id: "1", text: "apple", meaning: "苹果", phonetic: "", kind: "word", audio: "" }], total: 1 };
      }
      if (path === "/memorize") {
        const body = JSON.parse(opts.body);
        posts.push(body);
        return { ok: true, duplicate: false, memorized: body.right, memorize_count: body.right ? 2 : 0 };
      }
      return { ok: true };
    }),
    audioEl: { pause: vi.fn(), play: vi.fn() },
    ensureAudio: vi.fn(async () => ""),
    playUrl: vi.fn(), preloadAudio: vi.fn(), playWord: vi.fn(), preloadWord: vi.fn(),
    sndRight: vi.fn(), sndWrong: vi.fn(),
    audioPlaying: ref(false),
  };
});

vi.mock("./WordCells.vue", () => ({
  default: {
    name: "WordCells",
    props: ["tokens", "submitted"],
    template: "<div class='word-cells-stub'></div>",
    setup(_, { expose }) {
      expose({
        typeLetter: () => {}, backspace: () => {}, paint: () => {}, markWrong: () => {},
        reset: () => { cellsStub.resets++; },
        isCorrect: () => cellsStub.correct, isFull: () => cellsStub.full,
        serialize: () => null, restore: () => {}, answerText: () => "",
      });
      return {};
    },
  },
}));

function enter() {
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", cancelable: true }));
}

describe("MemorizePage 自测答错重打", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    posts.length = 0;
    cellsStub.correct = false; cellsStub.full = true; cellsStub.resets = 0;
    sessionStorage.clear();
  });
  afterEach(() => { vi.useRealTimers(); });

  it("答错 → 亮答案 → Enter 重打 → 打对才过，纠正用新 attempt_id 保存", async () => {
    const wrapper = mount(MemorizePage, {
      props: { params: new URLSearchParams("list=test_words&lesson=1") },
    });
    await flushPromises();
    // 学习态 → 跳过学习直接自测
    await wrapper.find(".card .btn.ghost").trigger("click");   // 跳过学习，直接自测
    await flushPromises();

    // 答错提交
    enter();
    await flushPromises();
    expect(posts).toHaveLength(1);
    expect(posts[0].right).toBe(false);
    expect(wrapper.text()).toContain("按 Enter 重输");

    // Enter 清空重打（不换题、清空格子）
    enter();
    await flushPromises();
    expect(cellsStub.resets).toBe(1);
    expect(wrapper.text()).toContain("照答案重打");

    // 重打打对：用新 attempt_id 保存 right=true，计时不跳过
    cellsStub.correct = true;
    enter();
    await flushPromises();
    expect(posts).toHaveLength(2);
    expect(posts[1].right).toBe(true);
    expect(posts[1].attempt_id).not.toBe(posts[0].attempt_id);

    // 已背 → 900ms 后队列空 → 完成页
    await vi.advanceTimersByTimeAsync(1000);
    await flushPromises();
    expect(wrapper.text()).toContain("本轮完成");
    wrapper.unmount();
  });
});
