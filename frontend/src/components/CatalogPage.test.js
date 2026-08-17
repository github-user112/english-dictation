/* CatalogPage 组件测试 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import CatalogPage from "../components/CatalogPage.vue";

let activeSessions = [];
let failLists = false;

/* mock 后端：/lists 返回带 lesson_count 的句子素材；oral900 的 /lessons 模拟失败 */
vi.mock("../lib/core", () => ({
  api: vi.fn(async (path) => {
    if (path.startsWith("/lists")) {
      if (failLists) throw new Error("素材库不可用");
      return {
        today: null,
        active_sessions: activeSessions,
        lists: [
          { key: "nc1", type: "sentences", lesson_count: 2, total: 40, known: 3, new: 37, title: "NCE1", audio_done: 40 },
          { key: "oral900", type: "sentences", lesson_count: 9, total: 100, known: 0, new: 100, title: "口语900", audio_done: 100 },
        ],
      };
    }
    const key = new URLSearchParams(path.split("?")[1]).get("list");
    if (key === "oral900") throw new Error("oral900 lessons 加载失败");
    return {
      lessons: [
        { lesson: 1, total: 20, known: 3, learning: 2, unseen: 15 },
        { lesson: 2, total: 20, known: 0, learning: 0, unseen: 20 },
      ],
    };
  }),
  Settings: { get: () => ({ practiceMode: "assisted" }) },
}));

describe("CatalogPage", () => {
  beforeEach(() => {
    localStorage.clear();
    activeSessions = [];
    failLists = false;
  });

  it("should render lesson options with labels without TDZ error", async () => {
    const wrapper = mount(CatalogPage);
    await flushPromises();
    const opts = wrapper.findAll("option");
    expect(opts.length).toBe(2);
    expect(opts[0].text()).toContain("第 1 课");
    expect(opts[0].text()).toContain("打过 5");       // known 3 + learning 2
    expect(opts[1].text()).toContain("未开始");
  });

  it("should still render cards when one material's lessons request fails", async () => {
    const wrapper = mount(CatalogPage);
    await flushPromises();
    // oral900 /lessons 失败不应阻塞页面：两张句子卡片都要渲染出来
    expect(wrapper.text()).toContain("口语900");
    expect(wrapper.text()).toContain("NCE1");
    // 失败的素材显示错误且不能进入伪按课模式，正常素材仍可用
    expect(wrapper.findAll("option").length).toBe(2);
    expect(wrapper.text()).toContain("课程加载失败，请刷新重试");
    const cards = wrapper.findAll(".card");
    const oralCard = cards.find((card) => card.text().includes("口语900"));
    const ncCard = cards.find((card) => card.text().includes("NCE1"));
    expect(oralCard.find("select").exists()).toBe(false);
    expect(oralCard.find("button").attributes("disabled")).toBeDefined();
    expect(ncCard.find("button").attributes("disabled")).toBeUndefined();
  });

  it("should only label sessions in the current practice mode as resumable", async () => {
    activeSessions = [
      { id: "pure-1", list: "nc1", lesson: 1, mode: "pure", scope: "all", total: 20, pending: 10 },
      { id: "assisted-2", list: "nc1", lesson: 2, mode: "assisted", scope: "all", total: 20, pending: 10 },
    ];
    const wrapper = mount(CatalogPage);
    await flushPromises();
    const options = wrapper.findAll("option");
    expect(options[0].text()).not.toContain("继续");
    expect(options[1].text()).toContain("继续");
  });

  it("should show a retryable error when the catalog request fails", async () => {
    failLists = true;
    const wrapper = mount(CatalogPage);
    await flushPromises();
    expect(wrapper.text()).toContain("素材库不可用");
    expect(wrapper.find("button").text()).toBe("重试");
  });
});
