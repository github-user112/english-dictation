# 英语听打系统 (English Dictation)

对标 Happytapper 的"听 → 打字 → 判分"英语练习系统。部署于 OCI ARM，域名通过 Cloudflare 代理。

## 功能

- **单词听打**：听发音，逐字母填入格子，判分后显示音标与中文释义
- **句子听写**：听整句，逐词填入格子，逐词标色对比（正确绿/遗漏黄/拼错红）
- **素材库**：CET-4 / CET-6 / 考研 / 托福 词汇 + 口语 900 句（GitHub 开源数据）
- **错词本**：错词自动收录，按简化间隔重复（1/3/7 天）安排复习
- **用户隔离**：每个访问者分配 UUID 挂在 URL 后面（`?u=xxx`），数据互不干扰，分享链接即同步进度
- **统计**：近期曲线、连续打卡天数、累计正确率

## 技术栈

- 后端：Flask + SQLite（API）
- 前端：Vue 3（组件化，无构建步骤）
- TTS：edge-tts 预生成 + 按需懒生成兜底
- 部署：nginx 静态直出 + API 反代，双份 TLS（Cloudflare 边缘 + Let's Encrypt 源站）

## 目录结构

```
app.py                  Flask 后端（API + 静态兜底）
wordlists/              GitHub 开源词库（已转换 JSON）
sentences/              句子素材（口语 900 句）
audio/                  edge-tts 预生成音频（gitignore）
scripts/build_data.py   拉取素材并转换统一格式
scripts/gen_audio.py    edge-tts 批量生成音频
static/                 Vue 3 前端（组件化）
```

## 本地运行

```bash
pip install -r requirements.txt
python scripts/build_data.py    # 拉取词库（需网络）
python scripts/gen_audio.py     # 生成音频（可选，缺了会自动懒生成）
python app.py                   # 127.0.0.1:8200
```

### API

| 接口 | 说明 |
|---|---|
| GET /api/lists | 素材列表 + 学习进度 |
| GET /api/session?list=cet4 | 今日任务（新词+复习） |
| POST /api/result | 答题结果记录 |
| GET /api/wrong | 错词本 |
| GET /api/stats | 统计 |
| POST /api/tts | TTS 懒生成 |

所有接口通过 `?u=uuid` 或 cookie 区分用户。

## 素材来源

- 词汇：https://github.com/vxiaozhi/vocabulary-book-by-deepseek (Apache-2.0)
- 句子：https://github.com/drizzletown/English900
- 发音：Microsoft Edge TTS（edge-tts 库）

## LICENSE

代码 MIT；词库/句子素材版权归各自来源。