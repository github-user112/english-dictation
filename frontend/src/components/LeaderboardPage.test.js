/* LeaderboardPage 组件测试 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import LeaderboardPage from "../components/LeaderboardPage.vue";

const meUser = "test-user";

function makeLbResponse(scope, period) {
  return {
    total_players: 42,
    me_rank: 3,
    rows: [
      { rank: 1, user: "alice", name: "Alice", value: 100, combo: 5, total: 10, level_title: "词霸" },
      { rank: 2, user: "bob", name: "Bob", value: 80, combo: 3, total: 10, level_title: "词痴" },
      { rank: 3, user: meUser, name: "Me", value: 70, combo: 2, total: 10, level_title: "词童" },
    ],
  };
}

const mockApi = vi.fn(async (path) => {
  if (path === "/auth/me") return { user: meUser };
  if (path.startsWith("/leaderboard")) {
    const u = new URLSearchParams(path.split("?")[1]);
    return makeLbResponse(u.get("scope"), u.get("period"));
  }
  return {};
});

vi.mock("../lib/core", () => ({ api: (...a) => mockApi(...a) }));
vi.mock("../lib/account", () => ({
  Account: { loading: false, authenticated: true },
  refreshAccount: vi.fn().mockResolvedValue(),
}));

function mountPage(hash = "#/leaderboard?scope=sprint&period=all") {
  const url = new URL(hash.slice(1), "http://localhost");
  const params = url.searchParams;
  return mount(LeaderboardPage, { props: { params } });
}

describe("LeaderboardPage", () => {
  beforeEach(() => {
    mockApi.mockClear();
  });

  it("calls api with correct scope and period", async () => {
    mountPage("#/leaderboard?scope=daily&period=weekly");
    await flushPromises();
    expect(mockApi).toHaveBeenCalledWith("/auth/me");
    expect(mockApi).toHaveBeenCalledWith(expect.stringContaining("/leaderboard?"));
    const lbCall = mockApi.mock.calls.find((c) => c[0].startsWith("/leaderboard"));
    const qs = new URLSearchParams(lbCall[0].split("?")[1]);
    expect(qs.get("scope")).toBe("daily");
    expect(qs.get("period")).toBe("weekly");
  });

  it("does not render period selector for sprint scope", async () => {
    const w = mountPage("#/leaderboard?scope=sprint");
    await flushPromises();
    expect(w.find(".period-group").exists()).toBe(false);
  });

  it("does not render period selector for streak scope", async () => {
    const w = mountPage("#/leaderboard?scope=streak");
    await flushPromises();
    expect(w.find(".period-group").exists()).toBe(false);
  });

  it("renders period selector for daily scope", async () => {
    const w = mountPage("#/leaderboard?scope=daily");
    await flushPromises();
    expect(w.find(".period-group").exists()).toBe(true);
  });

  it("highlights me row", async () => {
    const w = mountPage("#/leaderboard?scope=sprint");
    await flushPromises();
    const meRow = w.findAll(".lb-row").find((r) => r.text().includes("Me"));
    expect(meRow).toBeTruthy();
    expect(meRow.classes()).toContain("me");
  });

  it("does not highlight other rows", async () => {
    const w = mountPage("#/leaderboard?scope=sprint");
    await flushPromises();
    const aliceRow = w.findAll(".lb-row").find((r) => r.text().includes("Alice"));
    expect(aliceRow.classes()).not.toContain("me");
  });
});
