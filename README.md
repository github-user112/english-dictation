# 英语听打系统 (English Dictation)

"听 → 打字 → 判分"英语练习系统。部署于 OCI ARM（Always Free），域名通过 Cloudflare 代理，nginx 静态直出 + API 反代，双份 TLS（Cloudflare 边缘 + Let's Encrypt 源站）。

## 🔗 在线体验

**https://mi2.cc.cd** — 打开即用，浏览器自动分配学习帐号（UUID 挂在 URL 后面），分享链接即可同步进度。

## 功能

- **单词听打**：听发音，逐字母填入格子，判分后显示音标与中文释义；可切换"全部 / 只看已背"
- **句子听写**：听整句，逐词填入格子，逐词标色对比（正确绿/遗漏黄/拼错红）
- **背单词**：英→中翻卡学习 + 看中文拼写自测，连续答对 2 次标记已背；听打答错的词自动退回重背
- **素材库**：CET-4 / CET-6 / 考研 / 托福 词汇 + 新概念英语 1-4 册逐句 + 口语 900 句
- **错词本**：错词自动收录，按简化间隔重复（1/3/7 天）安排复习
- **用户隔离**：每个访问者分配 UUID 挂在 URL 后面（`?u=xxx`），数据互不干扰，分享链接即同步进度
- **统计**：近期曲线、连续打卡天数、累计正确率

## 技术栈

- 后端：Flask + SQLite（API）
- 前端：Vue 3 + Vite 8（SFC 组件，`frontend/` 目录）
- TTS：edge-tts 预生成 + 按需懒生成兜底

## 目录结构

```
app.py                  Flask 入口
backend/                后端包（config/db/auth/materials + 按功能分模块路由）
frontend/               Vue 3 + Vite 8 前端（SFC 组件，构建输出到 static/）
wordlists/              GitHub 开源词库（已转换 JSON）
sentences/              句子素材（口语 900 句、新概念）
audio/                  edge-tts 预生成音频（gitignore）
scripts/build_data.py   拉取素材并转换统一格式
scripts/gen_audio.py    edge-tts 批量生成音频
static/                 构建产物（nginx 直接服务）
```

## 学习闭环

```
新词 → 背单词(英→中翻卡 + 中→英拼写×2) → 已背 → 听打(可选"只看已背") → 掌握
   ↑                                                        ↓ 答错
   └──────────── 自动退回重背 + 进错词本 ◄────────────────────┘
```

## 本地运行

```bash
pip install -r requirements.txt
python scripts/build_data.py    # 拉取词库（需网络）
python scripts/gen_audio.py     # 生成音频（可选，缺了会自动懒生成）
python app.py                   # 127.0.0.1:8200
```

前端开发（Vite 8）：

```bash
cd frontend
npm install
npm run dev      # 开发预览
npm run build    # 构建产物输出到 ../static（nginx 直接服务）
```

### API

| 接口 | 说明 |
|---|---|
| GET /api/lists | 素材列表 + 学习进度（含已背数） |
| GET /api/session?list=cet4&scope=all\|memorized | 今日任务（新词+复习，scope 只看已背） |
| POST /api/result | 答题结果记录（听打答错自动退回背诵队列） |
| GET /api/memorize/session?list= | 背单词任务（待背新词 + 到期复习） |
| POST /api/memorize | 背诵结果记录（连续答对 2 次标记已背） |
| GET /api/wrong | 错词本 |
| GET /api/stats | 统计 |
| POST /api/tts | TTS 懒生成 |

所有接口通过 `?u=uuid` 或 cookie 区分用户。

## 素材来源

- 词汇：https://github.com/vxiaozhi/vocabulary-book-by-deepseek (Apache-2.0)
- 句子：https://github.com/drizzletown/English900
- 新概念：https://github.com/iChochy/NCE（逐句中英对照 LRC 数据，脚本 `scripts/build_nce.py`）
- 发音：Microsoft Edge TTS（edge-tts 库）

## LICENSE

代码 MIT；词库/句子素材版权归各自来源。