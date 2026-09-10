/* 站点图标跟随主题 */
import { describe, it, expect, beforeEach } from "vitest";
import { applyFavicon, currentTheme } from "./favicon";

function svgLink() {
  return document.querySelector("link[rel='icon'][type='image/svg+xml']");
}

describe("favicon", () => {
  beforeEach(() => {
    document.head.innerHTML = "";
    document.documentElement.removeAttribute("data-theme");
  });

  it("injects a green icon for the light theme and a dark one for dark", () => {
    document.documentElement.setAttribute("data-theme", "light");
    const light = applyFavicon();
    expect(light).toContain("data:image/svg+xml");
    expect(decodeURIComponent(light)).toContain("#58cc02");   // 多邻国绿渐变中段
    expect(decodeURIComponent(light)).toContain("#ffffff");   // 白字 E

    const dark = applyFavicon("dark");
    expect(decodeURIComponent(dark)).toContain("#1e1e1e");    // 深灰底
    expect(decodeURIComponent(dark)).toContain("#58cc02");    // 绿字 E
    expect(svgLink()).not.toBeNull();
  });

  it("falls back to dark palette when data-theme is absent", () => {
    expect(currentTheme()).toBe("dark");
    const href = applyFavicon();
    expect(decodeURIComponent(href)).toContain("#1e1e1e");
  });

  it("reuses the same link element across switches", () => {
    applyFavicon("light");
    const first = svgLink();
    applyFavicon("dark");
    expect(svgLink()).toBe(first);
  });
});
