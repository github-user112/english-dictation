# english-dictation → uni-app 小程序迁移方案

> 目标：微信小程序（个人主体·工具类）+ H5 双端，后端 uniCloud 阿里云免费版，0 元起步。
> 生成日期：2026-08-21

## 一、现状盘点

### 后端（Flask, ~1600 行 Python）
| 模块 | 行数 | 功能 | 迁移难度 |
|---|---|---|---|
| auth.py / auth_routes.py | 368 | 用户名密码注册登录、session、限流 | ★ 低 — 换 uni-id 现成方案 |
| db.py | 177 | SQLite 连接/建表 | ★ 低 — 换云数据库 |
| catalog.py | 510 | 词库目录、每日计划分配 | ★★★ 中 — 核心逻辑平移 |
| materials.py | 99 | 教材材料 | ★★ 低中 |
| memorize.py | 132 | 记忆模式 | ★★ 中 |
| misc.py | 196 | 统计等杂项 | ★★ 中 |
| config.py | 60 | 配置 | ★ |

### 数据库（SQLite → 云数据库 MongoDB 风格文档库）
7 张表：account、auth_session、auth_rate_limit、word_state、daily_log、daily_plan、
study_session、study_session_item、daily_practice_log。
主键多为 (day, user) 或 (user, list, item_id) 复合键 → 文档库用联合字段 `_id` 或查询条件替代。

### 前端（Vue3 + Vite）
8 个页面组件：Catalog / Practice(听写) / Memorize / Wrong / Stats / Account / Settings + TopBar，
lib/core.js 为业务核心（可大部分复用）。

### 音频资产：927MB
nc1~nc4 共 877MB（大头）、cet4 40MB、oral900 13MB。

## 二、目标架构：一套数据，两个入口（不做双向同步）

```
微信小程序 ──┐
            ├──→ uniCloud（唯一数据源：账号 + 学习数据 + 音频）
H5 ─────────┘
```

**原则：不搞两个数据库之间的同步，直接搬家，只留一个数据源。**
同步方案（双写/冲突处理/幂等）是无底洞，坚决不走这条路。

- 小程序端：uniCloud SDK 原生调云函数，无域名白名单问题
- H5 端：uni-app 编译产物 + uniCloud SDK 走 HTTP 网关调同一批云函数
- 旧 Flask 在切换完成后只读或下线，不再写入

### H5 域名与访问配置

| 层 | 配置项 | 说明 |
|---|---|---|
| H5 页面托管 | uniCloud 前端网页托管 | 默认送免费域名，零配置零备案；也可绑自定义域名（阿里云版要求该域名已备案） |
| H5 备选 | 部署到 OCI nginx | 用现有 opencode.pjgg2023.eu.org 域名+证书，`pnpm build` 后 scp 部署脚本化 |
| 云函数调用 | 无需配域名 | uniCloud SDK 自动走 HTTP 网关 |
| 跨域 | 仅 H5 需要 | uniCloud 控制台「跨域配置」加 H5 访问域名；用送的默认域名则已内置 |
| 小程序 | 无需任何域名配置 | 内部通道 |

## 三、音频策略（关键决策点）

1. **先转码压缩**：mp3 → 32kbps 单声道 16kHz（听写场景足够），预计 927MB → ~200MB 以内
   `ffmpeg -i in.mp3 -ac 1 -ar 16000 -b:a 32k out.mp3`
2. 压缩后传 uniCloud 云存储；超免费额度部分约 ¥0.1x/GB/月，可接受
3. 小程序端 `uni.createInnerAudioContext()` 播放云存储临时 URL（可缓存 tempUrl）

## 四、分阶段实施

### 阶段 0：准备（半天）
- [ ] 注册 DCloud 账号 + 微信小程序账号（个人主体，类目：工具 > 效率）
- [ ] 开通 uniCloud 阿里云服务空间（选免费版）
- [ ] 安装 HBuilderX（uni-app 官方 IDE）

### 阶段 1：数据与认证（1-2 天）
- [ ] 建 uni-id 用户体系（注册/登录/改密），替代 auth.py 三件套
- [ ] 账号统一方案：
  - uni-id 为唯一账号体系，用户名+密码登录天然支持
  - account 表 password_hash 随导出迁移；若 hash 算法与 uni-id（bcrypt）不一致，做「首次登录强制重置密码」或写兼容校验函数
  - 小程序端支持「微信一键登录」后绑定已有账号，或直接用户名密码登录，两种方式通到同一账号
  - 建 old_uuid → uni-id user_id 映射表，导入各表时统一替换 user 字段
- [ ] SQLite 数据导出脚本（Python 读 learn.db → JSONL）→ 导入云数据库集合
- [ ] word_state 等 7 表建集合 + 索引方案：
  - word_state: 按 user_id+list+item_id 建唯一索引
  - daily_log/daily_plan: 复合 _id = `${day}_${uid}` 
  - study_session_item: 按 session_id+seq 索引

### 阶段 2：后端逻辑平移（3-5 天）
Flask 路由 → uniCloud **云对象**（推荐，按模块拆）：
- `catalog.obj.js` ← catalog.py（词库、每日计划分配——最重的一块）
- `practice.obj.js` ← memorize.py + misc.py 的练习/判分部分
- `stats.obj.js` ← misc.py 统计
- `materials.obj.js` ← materials.py
- 词库 JSON（cet4/cet6/kaoyan/tuofu.json）放云数据库或直接打包进前端静态资源（更简单，推荐后者）

### 阶段 3：前端重写（5-8 天，工作量最大）
按页面迁移，core.js 业务逻辑基本照搬：
- [ ] 项目骨架（pages.json、tabBar：词库/听写/统计/我的）
- [ ] CatalogPage → 词库选择+计划设置
- [ ] PracticePage → 听写核心页（录音播放、判分、进度）— 最复杂
- [ ] MemorizePage / WrongPage / StatsPage / AccountPage / SettingsPage
- [ ] 音频播放封装（innerAudioContext + 云存储 URL 缓存）
- [ ] 条件编译处理小程序/H5 差异（登录态、音频）

### 阶段 4：上线与数据切换（1-2 天）
- [ ] 小程序体验版真机测试（重点：音频播放、后台切页、登录）
- [ ] 提审（工具类个人主体，注意截图里别出现"测试"字样和二维码）
- [ ] H5 版部署（uniCloud 网页托管 或 OCI nginx，见「二」域名表）
- [ ] **数据切换（避免双写，一次性搬家）**：
  1. 选低峰时刻，备份 learn.db
  2. 导出脚本全量导出 → 建 user_id 映射 → 导入 uniCloud
  3. 抽样核对（word_state 数量、daily_log 最近 7 天）
  4. 旧 Flask 改为只读（可看历史统计）或直接下线，不再写入
  5. 观察一周，稳定后收工

## 五、风险与对策

| 风险 | 对策 |
|---|---|
| 免费额度超限（云函数调用/流量） | 个人使用量级远低于额度；监控 uniCloud 控制台用量 |
| 音频加载慢 | 先压缩；小程序端预下载下一题音频 |
| uniCloud 阿里云版免费政策变动 | 数据可导出，最坏迁腾讯云版或 CloudBase |
| 小程序审核被拒（教育类敏感） | 类目选「工具>效率」，描述写"英语学习辅助工具"，避免"课程/教学"字样 |
| 旧数据迁移丢失 | 导出前备份 learn.db；导入后抽样核对 word_state 数量 |
| 双写导致数据不一致 | 坚持单一数据源原则，切换后旧 Flask 只读/下线，绝不同时写两边 |
| H5 跨域问题 | uniCloud 控制台跨域白名单加 H5 域名（默认域名已内置） |

## 六、总工期与成本

- 工期：**约 10-15 天**（业余时间折算）
- 成本：**0 元起步**（音频压缩后大概率全在免费额度内）
- 旧系统保留：OCI 上 Flask 继续跑到切换日；切换后改只读（可查历史统计），小程序稳定后再下线

## 七、下一步动作清单

1. 你去注册：DCloud 账号、微信小程序账号（需要邮箱+身份证+手机号）
2. 我来做：写 SQLite→JSON 导出脚本、搭 uni-app 项目骨架、转码音频
