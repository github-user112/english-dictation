# 英语听打系统 (English Dictation)

"听 → 打字 → 判分"英语练习系统。

## 🔗 在线体验

**https://mi2.cc.cd** — 打开即用。游客可直接练习；注册用户名和密码后，可保护进度并跨设备登录。

## 功能

- **单词听打**：听发音，逐字母填入格子，判分后显示音标与中文释义；可切换"全部 / 只看已背"
- **句子听写**：听整句，逐词填入格子，逐词标色对比（正确绿/遗漏黄/拼错红）
- **背单词**：英→中翻卡学习 + 看中文拼写自测，连续答对 2 次标记已背；听打答错的词自动退回重背
- **素材库**：CET-4 / CET-6 / 考研 / 托福 词汇 + 新概念英语 1-4 册逐句 + 口语 900 句
- **错词本**：错词自动收录，按简化间隔重复（1/3/7 天）安排复习
- **账户与游客模式**：新访问者可匿名学习；注册后以安全 Cookie 会话登录，学习进度无需迁移
- **统计**：近期曲线、连续打卡天数、累计正确率
- **三种练习模式**：纯听写（无提示）、辅助听写（即时纠错）、跟打（显示原文且不推进听写掌握）
- **听音选词**：三种题型——听音选词（音→形）、听词选义（音→义）、看义选词（义→形），到期待复习词优先出题，答错自动进错词本
- **限时冲刺**：60 秒听音打词连击挑战，音调随连击上升，服务端保留个人最高分
- **跟读打分**：Web Speech API 浏览器端语音识别，识别文本与目标词比对给相似度分，无需后端
- **真实首答统计**：首答结果不可被重输覆盖，按模式分别统计首答正确率
- **每日任务恢复**：每日新题配额固定，刷新/换设备继续未完成题目和顺序
- **新概念按课学习**：1-4 册可选择课号并按课文原顺序练习
- **句子序列对齐**：漏词、多词、拼错分别定位，不再因一个漏词导致后续全部错位

## 技术栈

- 后端：Flask + SQLite（API）
- 前端：Vue 3 + Vite 8（SFC 组件，`frontend/` 目录）
- TTS：edge-tts 预生成 + 按需懒生成兜底

## 目录结构

```
app.py                  Flask 入口
backend/                后端包（config/db/auth/materials + 按功能分模块路由）
frontend/               Vue 3 + Vite 8 前端（SFC 组件，构建输出到 static/）
wordlists/              词库（由 scripts/build_data.py 拉取生成，不入库，见 NOTICE）
sentences/              句子素材（由 scripts 拉取生成，不入库，见 NOTICE）
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

## 部署

本机即生产环境：nginx 直接服务仓库 `static/`，后端由系统服务 `english-dictation.service` 运行（gunicorn 127.0.0.1:8200，WorkingDirectory 即本仓库，单元文件见 `systemd/`，与已安装版本保持一致）。

- **前端**：`cd frontend && npm run build`，产物落到 `static/`，nginx 即时生效，无需重启
- **后端**：改了 Python 代码后需重载进程：

```bash
sudo systemctl restart english-dictation     # 或无 sudo 时优雅重载（不中断监听）：
kill -HUP $(pgrep -of "gunicorn.*app:app")
```

部署后验证：`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8200/api/auth/me` 应为 200。

### API

| 接口 | 说明 |
|---|---|
| GET /api/lists | 素材列表 + 学习进度（含已背数） |
| GET /api/session?list=cet4&scope=all\|memorized | 今日任务（新词+复习，scope 只看已背） |
| POST /api/result | 答题结果记录（听打答错自动退回背诵队列） |
| GET /api/memorize/session?list= | 背单词任务（待背新词 + 到期复习） |
| POST /api/memorize | 背诵结果记录（连续答对 2 次标记已背） |
| GET /api/quiz/session?list=&n=&kind= | 选词出题（kind=audio_en\|en_zh\|zh_en，默认 audio_en） |
| GET /api/sprint/session?list=&n= | 限时冲刺随机词流（n 默认 40） |
| GET /api/sprint/best | 限时冲刺个人最佳 |
| POST /api/sprint/best | 上报冲刺成绩（仅保留历史最高分） |
| GET /api/wrong | 错词本 |
| POST /api/wrong/remove | 从错词本移除（重置为未学） |
| GET /api/lessons | 课程目录（新概念按课学习） |
| GET /api/stats | 统计 |
| GET /api/auth/me | 当前游客或账户状态 |
| POST /api/auth/register | 注册并认领当前游客进度 |
| POST /api/auth/login | 用户名密码登录 |
| POST /api/auth/logout | 退出当前账户 |
| POST /api/auth/change-password | 修改密码并撤销其他会话 |
| POST /api/tts | TTS 懒生成 |

普通学习接口通过安全 Cookie 隔离用户。未注册的旧 `?u=UUID` 链接会在首次请求后转换为游客 Cookie；已认领账户的旧链接必须登录，不能作为访问凭据。

## 素材来源

- 词汇：https://github.com/vxiaozhi/vocabulary-book-by-deepseek (Apache-2.0)
- 句子：https://github.com/drizzletown/English900
- 新概念：https://github.com/iChochy/NCE（逐句中英对照 LRC 数据，脚本 `scripts/build_nce.py`）
- 发音：Microsoft Edge TTS（edge-tts 库）

## LICENSE

- **代码**：MIT（见 [LICENSE](LICENSE)）。
- **素材**：词库/句子 JSON **不随本仓库分发**，由 `scripts/` 在本地按需拉取生成（默认被 `.gitignore` 排除）。其版权与许可限制各不相同，详见 [NOTICE](NOTICE)——新概念英语、口语 900 句等教材内容**不可再分发，仅限个人学习研究**。
