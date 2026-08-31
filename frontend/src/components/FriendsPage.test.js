/* FriendsPage 组件测试 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import FriendsPage from "../components/FriendsPage.vue";

let authState = { loading: false, authenticated: false };

const mockApi = vi.fn(async (path, opts) => {
  if (path === "/auth/me") return { user: "me123" };
  if (path === "/friends") return {
    friends: [
      { user_id: "f1", username: "Alice", level: 3, level_title: "词痴", streak: 5, today_done: true, last_active_at: "2026-08-27T10:00:00Z" },
      { user_id: "f2", username: "Bob", level: 1, level_title: "词童", streak: 0, today_done: false, last_active_at: "2026-08-20T08:00:00Z" },
    ],
    requests: { incoming: [{ user_id: "r1", username: "Charlie" }], outgoing: [{ user_id: "r2", username: "Dave" }] },
    max: 50,
  };
  if (path === "/friends/activity") return { events: [{ kind: "sprint_record", name: "Alice", score: 95, created_at: "2026-08-27T09:00:00Z" }] };
  if (path === "/friends/add") return { ok: true };
  if (path === "/friends/accept") return { ok: true };
  if (path === "/friends/reject") return { ok: true };
  return {};
});

vi.mock("../lib/core", () => ({ api: (...a) => mockApi(...a) }));
vi.mock("../lib/account", () => ({
  get Account() { return authState; },
  refreshAccount: vi.fn().mockImplementation(() => {
    authState.loading = false;
    return Promise.resolve();
  }),
}));

describe("FriendsPage", () => {
  beforeEach(() => {
    mockApi.mockClear();
    authState = { loading: false, authenticated: true };
  });

  it("does not call api when not authenticated", async () => {
    authState = { loading: false, authenticated: false };
    mount(FriendsPage);
    await flushPromises();
    expect(mockApi).not.toHaveBeenCalled();
  });

  it("renders login gate when not authenticated", async () => {
    authState = { loading: false, authenticated: false };
    const w = mount(FriendsPage);
    await flushPromises();
    expect(w.find(".login-gate").exists()).toBe(true);
    expect(w.find(".login-gate").text()).toContain("好友与动态需要登录");
  });

  it("renders friends when authenticated", async () => {
    const w = mount(FriendsPage);
    await flushPromises();
    expect(w.text()).toContain("Alice");
    expect(w.text()).toContain("Bob");
  });

  it("renders incoming requests", async () => {
    const w = mount(FriendsPage);
    await flushPromises();
    expect(w.text()).toContain("Charlie");
  });

  it("renders outgoing requests", async () => {
    const w = mount(FriendsPage);
    await flushPromises();
    expect(w.text()).toContain("Dave");
  });

  it("reloads friends after addFriend", async () => {
    // 保存原实现，测试后恢复，避免影响后续测试
    const originalImpl = mockApi.getMockImplementation();
    // 搜索 mock：返回一个可添加的用户
    mockApi.mockImplementation(async (path, opts) => {
      if (path === "/auth/me") return { user: "me123" };
      if (path.startsWith("/friends/search")) return {
        users: [{ user_id: "new1", username: "Eve", relation: "none" }],
      };
      if (path === "/friends") return {
        friends: [], requests: { incoming: [], outgoing: [] }, max: 50,
      };
      if (path === "/friends/activity") return { events: [] };
      if (path === "/friends/add") return { ok: true };
      return {};
    });
    const w = mount(FriendsPage);
    await flushPromises();
    const friendsCallsBefore = mockApi.mock.calls.filter((c) => c[0] === "/friends").length;

    // 模拟搜索输入
    const searchInput = w.find("input[placeholder*='搜索']").exists()
      ? w.find("input[placeholder*='搜索']")
      : w.find("input");
    await searchInput.setValue("Eve");
    // 等待 350ms debounce
    await new Promise((r) => setTimeout(r, 400));
    await flushPromises();

    // 点击搜索结果中的添加按钮
    const addBtn = w.findAll("button").find((b) =>
      b.text().includes("加好友") || b.text().includes("添加"));
    expect(addBtn).toBeTruthy();
    await addBtn.trigger("click");
    await flushPromises();

    // addFriend 成功后应调用 reloadFriends → 重新拉取 /friends 和 /friends/activity
    const friendsCallsAfter = mockApi.mock.calls.filter((c) => c[0] === "/friends").length;
    expect(friendsCallsAfter).toBeGreaterThan(friendsCallsBefore);
    expect(mockApi.mock.calls.some((c) => c[0] === "/friends/add")).toBe(true);
    // 恢复原实现
    mockApi.mockImplementation(originalImpl);
  });

  it("renders activity events", async () => {
    const w = mount(FriendsPage);
    await flushPromises();
    expect(w.text()).toContain("冲刺新纪录");
  });
});
