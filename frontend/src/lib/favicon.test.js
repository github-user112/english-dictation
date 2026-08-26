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

  it("injects an amber icon for the light theme and a navy one for dark", () => {
    document.documentElement.setAttribute("data-theme", "light");
    const light = applyFavicon();
    expect(light).toContain("data:image/svg+xml");
    expect(decodeURIComponent(light)).toContain("#ffd37a");   // 琥珀渐变起点
    expect(decodeURIComponent(light)).toContain("#241703");   // 深棕 E

    const dark = applyFavicon("dark");
    expect(decodeURIComponent(dark)).toContain("#161d33");    // 墨蓝底
    expect(decodeURIComponent(dark)).toContain("#ffd37a");    // 琥珀 E
    expect(svgLink()).not.toBeNull();
  });

  it("falls back to dark palette when data-theme is absent", () => {
    expect(currentTheme()).toBe("dark");
    const href = applyFavicon();
    expect(decodeURIComponent(href)).toContain("#161d33");
  });

  it("reuses the same link element across switches", () => {
    applyFavicon("light");
    const first = svgLink();
    applyFavicon("dark");
    expect(svgLink()).toBe(first);
  });
});
