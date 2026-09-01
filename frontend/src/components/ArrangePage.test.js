/* 听音排句页组件测试 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import ArrangePage from "../components/ArrangePage.vue";

/* 词块池顺序固定；text 是原句，判分按提交下标重拼与原句比对（同服务端口径） */
const questions = [
  { id: "2", zh: "这是一个测试", audio: "/audio/lazy/a.mp3", text: "This is a test",
    chunks: ["This", "is", "a", "test"] },
];

const answers = [];
let sessionOverride = null;

vi.mock("../lib/core", () => ({
  api: vi.fn(async (path, opts) => {
    if (path === "/arrange/answer") {
      const body = JSON.parse(opts.body);
      answers.push(body);
      const bank = sessionOverride?.questions || questions;
      const q = bank.find((x) => String(x.id) === String(body.id));
      const built = body.order.map((i) => q.chunks[i]).join(" ");
      const right = built === q.text;
      return { right, score: right ? 1 : 0, text: q.text,
        profile: { xp: right ? 10 : 2 } };
    }
    if (path.startsWith("/arrange/session")) return sessionOverride || {
      list: "test_sents", questions, total: questions.length };
    if (path === "/lists") {
      return { lists: [{ key: "test_words", type: "words", title: "Words" },
                       { key: "test_sents", type: "sentences", title: "Sents" }] };
    }
    return { ok: true };
  }),
  playUrl: vi.fn(),
  sndRight: vi.fn(),
  sndWrong: vi.fn(),
  stopAudio: vi.fn(),
}));

function chunkByText(wrapper, text) {
  return wrapper.findAll(".chunk-pool .chunk").find((b) => b.text() === text);
}

async function play(wrapper) {
  await wrapper.findAll("button").find((b) => b.text().includes("开始排句")).trigger("click");
  await flushPromises();
}

describe("ArrangePage", () => {
  beforeEach(() => { answers.length = 0; sessionOverride = null; localStorage.clear(); });
  afterEach(() => { vi.useRealTimers(); });

  it("filters to sentence lists on the start screen and deals a question", async () => {
    const wrapper = mount(ArrangePage);
    await flushPromises();
    expect(wrapper.findAll(".match-select")[0].findAll("option")).toHaveLength(1);
    await play(wrapper);
    expect(wrapper.text()).toContain("第 1/1 句");
    expect(wrapper.findAll(".chunk-pool .chunk")).toHaveLength(4);
    expect(wrapper.find("button[aria-label='提交这句']").attributes()).toHaveProperty("disabled");
  });

  it("submits the picked order, reveals the answer when wrong and advances", async () => {
    vi.useFakeTimers();
    const spy = vi.spyOn(window, "dispatchEvent");
    const wrapper = mount(ArrangePage);
    await flushPromises();
    await play(wrapper);

    // 故意拼错：test This is a
    for (const w of ["test", "This", "is", "a"]) await chunkByText(wrapper, w).trigger("click");
    expect(wrapper.findAll(".slot-line .chunk")).toHaveLength(4);
    // 点答案区取回第二块（This）再点回去：顺序变为 test is a This，仍是错的
    await wrapper.findAll(".slot-line .chunk")[1].trigger("click");
    expect(wrapper.findAll(".slot-line .chunk")).toHaveLength(3);
    await chunkByText(wrapper, "This").trigger("click");
    expect(wrapper.findAll(".slot-line .chunk")).toHaveLength(4);

    await wrapper.find("button[aria-label='提交这句']").trigger("click");
    await flushPromises();
    expect(answers).toHaveLength(1);
    expect(wrapper.text()).toContain("正确语序");
    expect(wrapper.text()).toContain("This is a test");

    await wrapper.findAll("button").find((b) => b.text().includes("下一句")).trigger("click");
    expect(spy.mock.calls.some((c) => c[0].type === "profile-changed")).toBe(true);
    expect(wrapper.text()).toContain("排句完成");
    spy.mockRestore();
  });

  it("scores a correct rebuild and auto-advances after a pause", async () => {
    sessionOverride = {
      list: "test_sents",
      questions: [
        { id: "9", zh: "", audio: "/audio/lazy/b.mp3", text: "one two three",
          chunks: ["one", "two", "three"] },
      ],
      total: 1,
    };
    vi.useFakeTimers();
    const wrapper = mount(ArrangePage);
    await flushPromises();
    await play(wrapper);
    for (const w of ["one", "two", "three"]) await chunkByText(wrapper, w).trigger("click");
    await wrapper.find("button[aria-label='提交这句']").trigger("click");
    await flushPromises();
    expect(answers).toHaveLength(1);
    // 无 ?list= 参数时回退到第一个句子素材
    expect(answers[0]).toMatchObject({ list: "test_sents", id: "9", order: [0, 1, 2] });
    expect(typeof answers[0].attempt_id).toBe("string");
    expect(wrapper.text()).toContain("拼对了");

    await vi.advanceTimersByTimeAsync(1200);   // 答对 1.1s 自动进结算
    await flushPromises();
    expect(wrapper.text()).toContain("全部拼对");
  });
});
