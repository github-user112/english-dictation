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
  <!-- ═══════ Hero ═══════ -->
  <div class="imp-hero">
    <span class="imp-sparkles">✨📥✨</span>
    <div class="imp-hero-icon">📥</div>
    <div class="imp-hero-text">
      <h1>把任意文章，<em>变成听写素材。</em></h1>
      <div class="sub">粘贴英文文本（新闻 / 课文 / 歌词），自动分句后进入句子听写流程</div>
      <div class="sub2">TXT / CSV / JSON · 自动识别格式 · 智能去重清洗</div>
    </div>
    <div class="imp-hero-stats">
      <div class="ihs">
        <div class="hv">{{ previewCount }}</div>
        <div class="hl">已识别句</div>
      </div>
      <div class="ihs">
        <div class="hv">{{ text.length }}</div>
        <div class="hl">字符数</div>
      </div>
      <div class="ihs">
        <div class="hv">300</div>
        <div class="hl">上限</div>
      </div>
    </div>
  </div>

  <!-- ═══════ Pipeline ═══════ -->
  <div class="imp-pipeline-card">
    <div class="imp-pipeline">
      <div class="imp-pipe-step done">
        <span class="ips-emoji">📋</span>
        <span class="ips-title">粘贴</span>
        <span class="ips-desc">输入文本</span>
      </div>
      <div class="imp-pipe-arrow">→</div>
      <div class="imp-pipe-step done">
        <span class="ips-emoji">✂️</span>
        <span class="ips-title">分句</span>
        <span class="ips-desc">自动切分</span>
      </div>
      <div class="imp-pipe-arrow">→</div>
      <div class="imp-pipe-step" :class="previewCount >= 3 ? 'active' : 'pending'">
        <span class="ips-emoji">💾</span>
        <span class="ips-title">保存</span>
        <span class="ips-desc">保存到素材库</span>
      </div>
      <div class="imp-pipe-arrow">→</div>
      <div class="imp-pipe-step pending">
        <span class="ips-emoji">🎯</span>
        <span class="ips-title">练习</span>
        <span class="ips-desc">开始听写</span>
      </div>
    </div>
  </div>

  <!-- ═══════ Main Grid ═══════ -->
  <div class="imp-main-grid">

    <!-- ─── Left Column ─── -->
    <div class="imp-left">

      <!-- Method Tabs -->
      <div class="imp-method-tabs">
        <div class="imp-method-tab active">
          <span class="imt-check">✓</span>
          <span class="imt-badge">当前</span>
          <span class="imt-emoji">📋</span>
          <span class="imt-title">粘贴文本</span>
          <span class="imt-desc">从任意来源复制内容</span>
        </div>
        <div class="imp-method-tab">
          <span class="imt-emoji">📤</span>
          <span class="imt-title">上传文件</span>
          <span class="imt-desc">TXT / CSV / JSON</span>
        </div>
      </div>

      <!-- Content Type -->
      <div class="imp-ctype-row">
        <span class="imp-ctype-label">导入类型：</span>
        <div class="imp-ctype-opt">📚 词库</div>
        <div class="imp-ctype-opt active">💬 句库</div>
      </div>

      <!-- Title Input -->
      <div class="imp-form-group">
        <label class="imp-form-label" for="imp-title">标题（可选）</label>
        <input id="imp-title" v-model="title" class="imp-form-input" maxlength="60"
               placeholder="例：经济学人 · The age of average" />
      </div>

      <!-- Paste Zone -->
      <div class="imp-paste-zone">
        <div class="imp-paste-header">
          <div class="imp-paste-badge">
            <span class="imp-pb-dot"></span>
            📋 粘贴英文原文
          </div>
          <div class="imp-paste-count">
            ✨ {{ previewCount ? `已识别 ${previewCount} 句` : '等待粘贴…' }}
          </div>
        </div>
        <textarea id="imp-text" v-model="text" class="imp-paste-textarea" rows="14"
                  placeholder="Paste any English text here…&#10;支持直接换行分段；按 . ! ? 等句末标点自动分句。" spellcheck="false"></textarea>
        <div class="imp-paste-footer">
          <span>📝 每行一条 · # 注释行自动忽略</span>
          <span>📤 或拖拽文件到此处</span>
        </div>
      </div>

      <!-- Options -->
      <div class="imp-options-card">
        <div class="imp-oc-title"><span>⚙️</span> 导入选项</div>
        <div class="imp-option-row">
          <div class="imp-or-body">
            <b>🔊 自动生成发音</b>
            <small>使用 TTS 为每句生成标准发音音频</small>
          </div>
          <div class="imp-toggle on"></div>
        </div>
        <div class="imp-option-row">
          <div class="imp-or-body">
            <b>🧹 去重合并</b>
            <small>与现有句库重复的词汇将自动合并</small>
          </div>
          <div class="imp-toggle on"></div>
        </div>
        <div class="imp-option-row">
          <div class="imp-or-body">
            <b>🔤 按字母排序</b>
            <small>导入后按 A-Z 字母顺序排列</small>
          </div>
          <div class="imp-toggle"></div>
        </div>
      </div>

    </div>

    <!-- ─── Right Column ─── -->
    <div class="imp-right">

      <!-- Format Spec -->
      <div class="imp-format-card">
        <div class="imp-fc-title"><span>📐</span> 格式规范</div>
        <div class="imp-fc-tabs">
          <div class="imp-fc-tab active">TXT</div>
          <div class="imp-fc-tab">CSV</div>
          <div class="imp-fc-tab">JSON</div>
        </div>
        <div class="imp-fc-code">
          <div class="imp-fcc-line"><span class="imp-fcc-comment"># 每行一段 · 按 . ! ? 自动分句</span></div>
          <div class="imp-fcc-line"><span class="imp-fcc-text">The weather is beautiful today.</span></div>
          <div class="imp-fcc-line"><span class="imp-fcc-text">I love learning English.</span></div>
          <div class="imp-fcc-line"><span class="imp-fcc-comment"># 支持直接换行分段</span></div>
          <div class="imp-fcc-line"><span class="imp-fcc-text">Practice makes perfect!</span></div>
        </div>
        <div class="imp-fc-hint">💡 也可省略标点，系统会自动分句</div>
      </div>

      <!-- Tips -->
      <div class="imp-tips">
        <span class="imp-tb-emoji">💡</span>
        <div class="imp-tb-body">
          <b>导入小贴士</b>
          <p>单个文本最多 300 句。导入后自动进入素材库，可用于句子听写、听读跟读等所有练习模式。</p>
        </div>
      </div>

    </div>

  </div>

  <!-- ═══════ Action Bar ═══════ -->
  <div class="imp-action-bar">
    <div class="imp-ab-info">
      <span class="imp-ai-dot"></span>
      <span v-if="previewCount >= 3">准备就绪 · {{ previewCount }} 条待导入</span>
      <span v-else>还需至少 3 句才能导入</span>
    </div>
    <button class="btn primary big" :disabled="saving || previewCount < 3" @click="submit">
      {{ saving ? "切分中…" : "切分并保存" }}
    </button>
  </div>

  <!-- ═══════ Messages ═══════ -->
  <p v-if="error" class="account-message error" role="alert">{{ error }}</p>
  <p v-if="ok" class="account-message success">已保存《{{ ok.title }}》（{{ ok.count }} 句），正在前往素材库…</p>

  <!-- ═══════ Footer ═══════ -->
  <div class="imp-footer">
    🦉 英语听打 · 导入句库<br>
    导入内容自动进入素材库，可用于所有练习模式 🚀
  </div>
</template>

<style scoped>
/* 所有页面级样式在 17-import.css；此处仅放 scoped 组件级微调 */
.imp-form-group { margin-bottom: 14px; }
.imp-form-label { display: block; font-size: 13px; font-weight: 800; margin-bottom: 6px; color: var(--text); }
.imp-form-input {
  width: 100%; padding: 12px 15px;
  border: 2px solid var(--border); border-radius: var(--r-btn);
  font-family: inherit; font-size: 14px; font-weight: 600;
  background: var(--panel); color: var(--text);
  transition: border-color .15s;
}
.imp-form-input:focus { outline: none; border-color: var(--green); }
</style>
