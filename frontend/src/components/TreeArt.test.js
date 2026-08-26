/* 单词树 SVG 组件：阶段部件按阈值生长 */
import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import TreeArt from "../components/TreeArt.vue";

const onCount = (wrapper) => wrapper.findAll(".gp.on").length;

describe("TreeArt", () => {
  it("grows parts stage by stage", () => {
    const seed = mount(TreeArt, { props: { stage: 0 } });
    expect(seed.find(".seed").classes()).toContain("on");
    expect(onCount(seed)).toBe(1);

    const sprout = mount(TreeArt, { props: { stage: 1 } });
    expect(sprout.find(".seed").classes()).not.toContain("on");   // 种子入土
    expect(sprout.findAll(".leaf.on").length).toBe(2);            // 子叶展开

    const tree = mount(TreeArt, { props: { stage: 4 } });
    expect(tree.find(".trunk").classes()).toContain("on");
    expect(tree.find(".canopy").classes()).toContain("on");
    expect(tree.findAll(".seedling .gp.on").length).toBe(0);      // 幼苗让位给树干

    const full = mount(TreeArt, { props: { stage: 7 } });
    expect(full.findAll(".flower.on").length).toBe(5);
    expect(full.findAll(".fruit.on").length).toBe(4);
  });

  it("drops blossoms and fruit when wilted", () => {
    const w = mount(TreeArt, { props: { stage: 7, wilted: true } });
    expect(w.find(".tree-art").classes()).toContain("wilted");
    expect(w.findAll(".flower.on").length).toBe(0);
    expect(w.findAll(".fruit.on").length).toBe(0);
    expect(w.attributes("aria-label")).toContain("8 / 8");
  });
});
