/* 按课听录音页测试：整课原声模式的时间轴高亮/课末停止/点句跳转，以及逐句串播模式 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import ListenPage from "../components/ListenPage.vue";
import { ensureAudio } from "../lib/core";

const filePayload = {
  list: "test", lesson: 1, mode: "file", total: 3,
  file: "/audio/test/lesson.mp3", start: 0, end: 30,
  items: [
    { id: "1", text: "One", zh: "一", start: 0, end: 10, audio: "/audio/test/1.mp3" },
    { id: "2", text: "Two", zh: "二", start: 10, end: 20, audio: "/audio/test/2.mp3" },
    { id: "3", text: "Three", zh: "三", start: 20, end: 30, audio: "/audio/test/3.mp3" },
    { id: "4", text: "Unmapped", zh: "无时间轴", start: null, end: null, audio: "/audio/test/4.mp3" },
  ],
};
const sentPayload = {
  list: "test", lesson: 1, mode: "sentences", total: 2,
  items: [
    { id: "1", text: "One", zh: "一", start: null, end: null, audio: "/audio/test/1.mp3" },
    { id: "2", text: "Two", zh: "二", start: null, end: null, audio: "/audio/test/2.mp3" },
  ],
};
let sessionPayload = filePayload;

const { audioEl, emit } = vi.hoisted(() => {
  const listeners = {};
  const el = {
    currentTime: 0, src: "", paused: true, playbackRate: 1, readyState: 1,
    play: vi.fn(() => Promise.resolve()), pause: vi.fn(), load: vi.fn(),
    removeAttribute: vi.fn(),
    addEventListener: (ev, fn) => { (listeners[ev] ||= []).push(fn); },
    removeEventListener: vi.fn(),
    ontimeupdate: null, onended: null,
  };
  return { audioEl: el, emit: (ev) => (listeners[ev] || []).forEach((fn) => fn()) };
});

vi.mock("../lib/core", () => ({
  api: vi.fn(async (path) => {
    if (path === "/lists") {
      return { lists: [{ key: "test", type: "sentences", title: "T", lesson_count: 2 }] };
    }
    if (path.startsWith("/lessons")) return { lessons: [{ lesson: 1 }, { lesson: 2 }] };
    if (path.startsWith("/listen/session")) return sessionPayload;
    return {};
  }),
  audioEl,
  audioPlaying: { value: false },
  ensureAudio: vi.fn(async (it) => it.audio),   // 测试里音频都视为已存在
  Settings: { get: () => ({ speed: 1 }), set: vi.fn() },
  stopAudio: vi.fn(),
}));

Element.prototype.scrollIntoView = vi.fn();

async function mountPage(hash = "list=test&lesson=1") {
  const wrapper = mount(ListenPage, {
    props: { params: new URLSearchParams(hash) },
  });
  await flushPromises();
  return wrapper;
}

describe("ListenPage", () => {
  beforeEach(() => {
    sessionPayload = filePayload;
    localStorage.clear();
    sessionStorage.clear();
    audioEl.currentTime = 0;
    audioEl.src = "";
    audioEl.paused = true;
    audioEl.ontimeupdate = null;
    audioEl.onended = null;
    vi.clearAllMocks();
  });

  it("file 模式：渲染句子列表，时间轴推进时高亮当前句", async () => {
    const wrapper = await mountPage();
    expect(wrapper.findAll(".sent-row")).toHaveLength(4);
    expect(wrapper.find(".track-fill").attributes("style")).toContain("width: 0%");

    await wrapper.find(".play-btn").trigger("click");   // 装载整课音频后才开始播放
    audioEl.currentTime = 15;   // 落在第 2 句 [10,20)
    audioEl.ontimeupdate();
    await flushPromises();
    const rows = wrapper.findAll(".sent-row");
    expect(rows[1].classes()).toContain("active");
    expect(rows[0].classes()).not.toContain("active");
  });

  it("file 模式：越过课末时间轴自动暂停，点句跳转到该句起点", async () => {
    const wrapper = await mountPage();
    await wrapper.find(".play-btn").trigger("click");   // 先装载整课音频
    audioEl.pause.mockClear();                            // 排除 loadLesson 里那次暂停的干扰
    audioEl.currentTime = 31;   // 超过 end=30
    audioEl.ontimeupdate();
    expect(audioEl.pause).toHaveBeenCalled();

    vi.clearAllMocks();
    await wrapper.findAll(".sent-row")[2].trigger("click");
    expect(audioEl.src).toBe("/audio/test/lesson.mp3");
    expect(audioEl.currentTime).toBe(20);
    expect(audioEl.play).toHaveBeenCalled();
  });

  it("file 模式：开启自动连播时课末跳下一课，最后一课不跳", async () => {
    localStorage.setItem("dict_listen_opts", JSON.stringify({ autoNext: true }));
    location.hash = "";
    const wrapper = await mountPage("list=test&lesson=1");
    await wrapper.find(".play-btn").trigger("click");
    audioEl.currentTime = 31;
    audioEl.ontimeupdate();
    expect(location.hash).toContain("lesson=2");

    location.hash = "";
    const last = await mountPage("list=test&lesson=2");
    await last.find(".play-btn").trigger("click");
    audioEl.currentTime = 31;
    audioEl.ontimeupdate();
    expect(location.hash).toBe("");   // 没有下一课，停在课末
  });

  it("file 模式：本课循环开启时课末回到本课开头继续播", async () => {
    sessionPayload = { ...filePayload, start: 5 };   // 本课从 5s 开始
    const wrapper = await mountPage();
    const chip = wrapper.findAll(".lp-chip").find((b) => b.text().includes("本课循环"));
    await chip.trigger("click");
    expect(chip.attributes("aria-pressed")).toBe("true");
    expect(JSON.parse(localStorage.getItem("dict_listen_opts")).loopLesson).toBe(true);

    await wrapper.find(".play-btn").trigger("click");
    audioEl.pause.mockClear();
    audioEl.currentTime = 31;             // 越过 end=30
    audioEl.ontimeupdate();
    await flushPromises();
    expect(audioEl.pause).not.toHaveBeenCalled();
    expect(audioEl.currentTime).toBe(5);  // 回到本课起点，不是文件 0s
    expect(wrapper.find(".track-fill").attributes("style")).toContain("width: 0%");
    expect(wrapper.findAll(".sent-row")[0].classes()).toContain("active");
    expect(location.hash).not.toContain("lesson=2");   // 不能误切下一课
  });

  it("file 模式：无时间轴句子播单句音频，播完不触发自动连播", async () => {
    localStorage.setItem("dict_listen_opts", JSON.stringify({ autoNext: true }));
    const wrapper = await mountPage();

    await wrapper.findAll(".sent-row")[3].trigger("click");   // 第 4 句无 start/end
    expect(audioEl.src).toBe("/audio/test/4.mp3");
    expect(audioEl.play).toHaveBeenCalled();

    const before = location.hash;
    audioEl.onended();
    await flushPromises();
    expect(location.hash).toBe(before);   // 单句播完只是停，不能当成课末去跳下一课
  });

  it("file 模式：播过无时间轴句子后再按播放，换回整课原声并接着听", async () => {
    const wrapper = await mountPage();
    await wrapper.find(".play-btn").trigger("click");
    audioEl.currentTime = 15;               // 整课已听到第 15 秒
    audioEl.ontimeupdate();

    await wrapper.findAll(".sent-row")[3].trigger("click");   // 播单句音频
    expect(audioEl.src).toBe("/audio/test/4.mp3");

    audioEl.paused = true;
    audioEl.play.mockClear();
    await wrapper.find(".play-btn").trigger("click");
    expect(audioEl.src).toBe("/audio/test/lesson.mp3");      // 不能把单句当成整课续播
    expect(audioEl.currentTime).toBe(15);
    expect(audioEl.play).toHaveBeenCalled();
  });

  it("file 模式：首次装载后跳句要等元数据就绪才定位", async () => {
    const wrapper = await mountPage();
    audioEl.readyState = 0;               // 模拟刚换 src，元数据未就绪
    await wrapper.findAll(".sent-row")[2].trigger("click");
    expect(audioEl.src).toBe("/audio/test/lesson.mp3");
    expect(audioEl.currentTime).toBe(0);  // 元数据没好之前定位会被浏览器丢弃
    audioEl.readyState = 1;
    emit("loadedmetadata");
    expect(audioEl.currentTime).toBe(20); // 就绪后再补上目标位置
  });

  it("file 模式：整课定位还没生效就切去单句，单句不能继承整课的时间点", async () => {
    sessionPayload = { ...filePayload, start: 5 };
    const wrapper = await mountPage();

    audioEl.readyState = 0;
    await wrapper.find(".play-btn").trigger("click");        // pendingSeek = 5
    await wrapper.findAll(".sent-row")[3].trigger("click");  // 无时间轴单句
    expect(audioEl.src).toBe("/audio/test/4.mp3");

    audioEl.readyState = 1;
    emit("loadedmetadata");
    expect(audioEl.currentTime).toBe(0);   // 不能跳到整课的 5 秒处（单句早播完了）
  });

  it("sentences 模式：按句串播，播完自动下一句", async () => {
    sessionPayload = sentPayload;
    const wrapper = await mountPage();
    expect(wrapper.text()).toContain("第 1 / 2 句");

    audioEl.paused = true;
    await wrapper.find(".play-btn").trigger("click");
    expect(audioEl.src).toBe("/audio/test/1.mp3");
    expect(audioEl.play).toHaveBeenCalled();

    audioEl.onended();   // 第 1 句播完
    await flushPromises();
    expect(audioEl.src).toBe("/audio/test/2.mp3");
    expect(wrapper.text()).toContain("第 2 / 2 句");
  });

  it("sentences 模式：本课循环开启时最后一句播完回到第 1 句", async () => {
    sessionPayload = sentPayload;
    localStorage.setItem("dict_listen_opts", JSON.stringify({ loopLesson: true }));
    const wrapper = await mountPage();

    audioEl.paused = true;
    await wrapper.find(".play-btn").trigger("click");
    audioEl.onended();   // 第 1 句 → 第 2 句
    await flushPromises();
    expect(audioEl.src).toBe("/audio/test/2.mp3");

    audioEl.onended();   // 最后一句 → 回第 1 句
    await flushPromises();
    expect(audioEl.src).toBe("/audio/test/1.mp3");
    expect(wrapper.text()).toContain("第 1 / 2 句");
  });

  it("本课循环与单句循环、自动下一课互斥", async () => {
    localStorage.setItem("dict_listen_opts", JSON.stringify({ autoNext: true }));
    const wrapper = await mountPage();
    const byText = (text) => wrapper.findAll(".lp-chip").find((b) => b.text().includes(text));

    await byText("本课循环").trigger("click");
    expect(byText("本课循环").attributes("aria-pressed")).toBe("true");
    expect(byText("自动下一课").attributes("aria-pressed")).toBe("false");
    expect(JSON.parse(localStorage.getItem("dict_listen_opts")))
      .toMatchObject({ loopLesson: true, loopOne: false, autoNext: false });

    await byText("单句循环").trigger("click");
    expect(byText("单句循环").attributes("aria-pressed")).toBe("true");
    expect(byText("本课循环").attributes("aria-pressed")).toBe("false");

    await byText("本课循环").trigger("click");   // 再开课循环，单句关掉
    expect(byText("单句循环").attributes("aria-pressed")).toBe("false");
    await byText("自动下一课").trigger("click"); // 开自动下一课，课循环关掉
    expect(byText("本课循环").attributes("aria-pressed")).toBe("false");
    expect(byText("自动下一课").attributes("aria-pressed")).toBe("true");
  });

  it("file 模式：单句音频还在加载时按播放，加载完成后不能抢回整课播放", async () => {
    let resolveAudio;
    ensureAudio.mockImplementationOnce(() => new Promise((res) => { resolveAudio = res; }));
    const wrapper = await mountPage();

    await wrapper.findAll(".sent-row")[3].trigger("click");   // 单句加载挂起
    audioEl.paused = true;
    await wrapper.find(".play-btn").trigger("click");         // 用户改听整课
    expect(audioEl.src).toBe("/audio/test/lesson.mp3");

    resolveAudio("/audio/test/4.mp3");
    await flushPromises();
    expect(audioEl.src).toBe("/audio/test/lesson.mp3");       // 不能被迟到的单句覆盖
    expect(audioEl.play).toHaveBeenCalled();
  });

  it("sentences 模式：离开页面后，未完成的单句加载不再开始播放", async () => {
    sessionPayload = sentPayload;
    let resolveAudio;
    ensureAudio.mockImplementationOnce(() => new Promise((res) => { resolveAudio = res; }));
    const wrapper = await mountPage();

    await wrapper.find(".play-btn").trigger("click");   // 挂在 ensureAudio 上
    expect(resolveAudio).toBeTypeOf("function");

    wrapper.unmount();
    audioEl.play.mockClear();
    resolveAudio("/audio/test/1.mp3");
    await flushPromises();
    expect(audioEl.src).toBe("");
    expect(audioEl.play).not.toHaveBeenCalled();        // 不能在别的页面突然出声
  });
});
