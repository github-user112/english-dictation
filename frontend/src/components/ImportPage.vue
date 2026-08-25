<script setup>
import { computed, ref } from "vue";
import { api } from "../lib/core";

const title = ref("");
const text = ref("");
const saving = ref(false);
const error = ref("");
const ok = ref(null);

/* 与后端 custom.split_sentences 同规则：分段 → 句末标点切 → 超长软切 → 封顶 */
const previewCount = computed(() => {
  const t = text.value.replace(/\r\n/g, "\n").trim();
  if (!t) return 0;
  const pieces = [];
  for (const para of t.split(/\n{1,}/)) {
    const p = para.trim();
    if (p) pieces.push(...p.split(/(?<=[.!?…。；;])\s+/));
  }
  const out = [];
  for (let p of pieces) {
    p = p.trim();
    if (!p) continue;
    if (p.length > 280) {   // MAX_SENTENCE_LEN
      for (let q of p.split(/(?<=[,，:：—-])\s+/)) {
        q = q.trim();
        if (q.length >= 2) out.push(q);   // MIN_SENTENCE_LEN
      }
    } else if (p.length >= 2) {
      out.push(p);
    }
  }
  return Math.min(out.length, 300);   // MAX_SENTENCES
});

async function submit() {
  if (saving.value) return;
  error.value = "";
  saving.value = true;
  try {
    const d = await api("/materials/custom", {
      method: "POST",
      body: JSON.stringify({ title: title.value, text: text.value }),
    });
    ok.value = d;
    setTimeout(() => { location.hash = "#/catalog"; }, 900);
  } catch (err) {
    error.value = err.message || "导入失败";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="page-heading compact">
    <span class="eyebrow">CUSTOM MATERIAL</span>
    <h1>把任意文章，<em style="font-style:normal;color:var(--accent-strong)">变成听写素材。</em></h1>
    <p>粘贴英文文本（新闻 / 课文 / 歌词），自动分句后进入句子听写流程；发音按需生成。</p>
  </div>

  <div class="import-page">
    <label class="imp-label" for="imp-title">标题（可选）</label>
    <input id="imp-title" v-model="title" class="imp-input" maxlength="60"
           placeholder="例：经济学人 · The age of average" />

    <label class="imp-label" for="imp-text">英文原文</label>
    <textarea id="imp-text" v-model="text" class="imp-textarea" rows="14"
              placeholder="Paste any English text here…&#10;支持直接换行分段；按 . ! ? 等句末标点自动分句。" spellcheck="false"></textarea>

    <div class="imp-foot">
      <span class="sub">{{ previewCount ? `预计切分 ${previewCount} 句` : "等待粘贴…" }}</span>
      <span class="sub" style="color:var(--dim2)">上限 20,000 字符 · 300 句</span>
      <button class="btn primary big" :disabled="saving || previewCount < 3" @click="submit">
        {{ saving ? "切分中…" : "切分并保存" }}
      </button>
    </div>
    <p v-if="error" class="account-message error" role="alert">{{ error }}</p>
    <p v-if="ok" class="account-message success">已保存《{{ ok.title }}》（{{ ok.count }} 句），正在前往素材库…</p>

    <div class="hint" style="margin-top:22px;">保存后在素材库「我的文章」里点「开始听写」即可练习；删除不会影响学习统计。</div>
  </div>
</template>

<style scoped>
.import-page { max-width: 760px; margin: 0 auto; display: grid; gap: 10px; }
.imp-label { color: var(--dim); font-size: 12px; font-weight: 700; margin-top: 8px; }
.imp-input, .imp-textarea {
  width: 100%; padding: 12px 14px; color: var(--text);
  background: var(--panel2); border: 1px solid var(--border); border-radius: 12px;
  outline: none; font: inherit; transition: border-color .12s, box-shadow .12s;
}
.imp-input:focus, .imp-textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent), transparent 86%); }
.imp-textarea { resize: vertical; min-height: 220px; line-height: 1.7; font-size: 14px; }
.imp-foot { display: flex; align-items: center; gap: 16px; margin-top: 6px; }
.imp-foot .btn { margin-left: auto; }
</style>
