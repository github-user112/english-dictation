# 英语听打系统 — 代码审查 Bug 报告

> **审查来源**：
> - 后端子代理（`c62b2d30`）独立审查，返回 15 项（3 High / 2 Medium / 6 Low / 4 备注）；
> - 前端子代理（`58d57348`）与数据/测试子代理（`e0fda4e0`）在返回前均超时失败（消息为空），**前端与数据部分的发现均为审查者本人通读源码与数据文件所得**；
> - 本报告按**真实可复现性**重新定级，不直接照搬后端子代理原始严重度（有 2 项降为 Medium）。
>
> 总合并后约 30 项：5 High / 9 Medium / 11 Low / 5 Info。

---

## 一、严重度图例
- **H** High — 功能错误 / 数据污染 / 安全，建议立即修
- **M** Medium — 异常行为 / 体验问题，建议尽快修
- **L** Low — 健壮性 / 一致性 / 代码质量，可排期修
- **Info** — 仅供记录，不必修

---

## 二、按真实严重度排列的合并清单

### 【H1】SentenceCells 对带连字符词（如 `well-known`）分词错误
- **位置**：`frontend/src/components/SentenceCells.vue:14-17`
- **描述**：正则 `/^([^\w]*)([\w'-]*)([^\w]*)$/` 把 `-` 放进 `[\w'-]`，导致 `well-known` 被当成一个词。用户在 `well-` 后按空格会触发"错误"即时报错（`target.startsWith` 判定），且 `isCorrect` 用空格数判词数会误判。
- **影响**：任何含连字符的句子（新闻、口语 900 句高频）都无法正常完成练习。
- **修复**：把 `-` 移出字符类，或把它视为单词边界；`isCorrect` 改用词数组比对。
- **来源**：审查者本人（前端通读）

### 【H2】WordCells `typeLetter` 只吃 a-zA-Z，非字母字符静默丢弃
- **位置**：`frontend/src/components/WordCells.vue:24-36`；调用链 `PracticePage.vue:148-152`、`MemorizePage.vue:213-217`
- **描述**：`if (!/[a-zA-Z]/.test(ch)) return` 直接丢弃非字母字符。`onInput` 会把输入法候选上屏、粘贴整词等一次性传入 `ch`，其中非字母部分无声丢失，用户无感知。
- **影响**：粘贴、IME 上屏、含数字单词（如 `a1`、`3D`）丢字，用户体验差且难排查。
- **修复**：`typeChar` 在传入前按 `[a-zA-Z]` 过滤，或对丢弃字符给出提示。
- **来源**：审查者本人（前端通读）

### 【H3】WordCells `typeLetter` 游标越界时无 return，导致 `|| wrong` 累计漏判
- **位置**：`frontend/src/components/WordCells.vue:24-36` + `PracticePage.vue:160-181`
- **描述**：`typeLetter` 在"游标已满 + 非 pure 模式"分支无 `return`，隐式返回 `undefined`（falsy）。`PracticePage.typeChar` 用 `wrong = cells.typeLetter(c) || wrong` 累计，最后一笔越界字符会被**漏判为"非错"**，可能在超长/夹杂 punct 输入下误判为"正确"。
- **影响**：边界输入可能误判正确提交成功。
- **修复**：该分支显式 `return true`。
- **来源**：审查者本人（前端通读）

### 【H4】MemorizePage 答错时不保留答案高亮，用户看不到自己打错在哪
- **位置**：`frontend/src/components/MemorizePage.vue:251-256` + 模板 334-339 行
- **描述**：答错分支把 `lastNote` 设为"再背一次，明天还会见到它"，模板走 `!lastRight` 分支显示答案；但**用户当前已打内容在 `markWrong` 后没有与答案对照呈现**——用户看不到"我打错的是哪个字母"。背单词的核心价值（看自己打错处）受损。
- **影响**：学习效果打折扣。
- **修复**：答错时保留/高亮错误字母对照（`markWrong` 已做），但 `lastNote` 应同时包含答案，或答错时也显示 `cur.text`。
- **来源**：审查者本人（前端通读）

### 【H5】`memorize.py` 重置时未清空 `last_memorize`（子代理原 High，降为 M）
- **位置**：`backend/memorize.py:80-82`
- **描述**：答错重置 `memorize_count=0`、`memorized=0` 时**未清空 `last_memorize`**。
- **影响（降为 M）**：review 查询要求 `memorized=1`，重置期间 `last_memorize` 不参与过滤，危害有限；但用户重新背到 memorized=1 后，若其他逻辑依赖该字段会产生不一致。
- **修复**：第 81-82 行加 `sr["last_memorize"] = None`。
- **来源**：后端子代理 Bug #1

### 【H6】`catalog.py` 配额响应字段命名不一致（子代理原 High，降为 M）
- **位置**：`backend/catalog.py:264-266`
- **描述**：新会话返回 `quota.allocated_today`，但 DB 列名为 `allocated_new`；续会话时 `serialize_session` 直接透传 `dict(plan)` 原始行（含 `allocated_new`），两处字段名不统一。前端若依赖 `allocated_today`，续会话时取不到。
- **说明**：后端子代理称此 bug 为"用 plan['new_quota'] 而非 plan['allocated_new'] 计算"——经源码核对**不成立**，第 265 行实际为 `plan["allocated_new"] + len(fresh)`，计算正确；真正的问题是**字段命名不一致**。
- **影响**：续会话时"今日已分配"显示 undefined。
- **修复**：`serialize_session` 中把 `allocated_new` 映射为 `allocated_today`。
- **来源**：后端子代理 Bug #2（经源码更正）

### 【H7】`daily_practice_log` 与 `daily_log` 统计口径不一致（子代理原 Medium）
- **位置**：`backend/catalog.py:379-416`（daily_log） vs `429-448`（daily_practice_log）
- **描述**：attempt 分支在 `daily_practice_log` 写入时 `final_right=None`（转 0），completed 分支用 `final_right` 实值，两处对同一会话的 right/wrong 计数可能**对不上**。
- **影响**：StatsPage 展示两套不一致数据。
- **修复**：统一两个日志表在 attempt/completed 的写入语义。
- **来源**：后端子代理 Bug #3

### 【H8】WordCells `markWrong` 用 `input[i]` 而非 `input.value[letterIdxs()[...]]`，语义错位
- **位置**：`frontend/src/components/WordCells.vue:73-76`
- **描述**：`markWrong` 用 `refTokens.value.map((t, i) => ...)` 遍历所有 token（含 punct），但 `input.value[i]` 是按 token 总索引写入。当前**碰巧工作**是因为 `input` 按 token 索引预留，但语义不清且 refactor 即错。
- **影响**：当前无功能 bug，维护风险高。
- **修复**：改为按 `letterIdxs()` 映射访问 `input`。
- **来源**：审查者本人（前端通读）

### 【H9】`PracticePage.onDocDown` 对非 touch 点击一律 preventDefault，误伤右键/拖拽
- **位置**：`frontend/src/components/PracticePage.vue:103-114`
- **描述**：对非 button/link/input 的点击调用 `ev.preventDefault()` 以捕获焦点，同时**阻断右键菜单、拖拽、选择文本**等默认行为。
- **影响**：用户无法在练习页复制/粘贴/右键。
- **修复**：仅在 `ev.button === 0`（左键）时 preventDefault。
- **来源**：审查者本人（前端通读）

### 【H10】`SentenceCells.focusWord` 判读 `submitted.value`（不存在的 local ref），应为 `props.submitted`
- **位置**：`frontend/src/components/SentenceCells.vue:70-72`
- **描述**：`focusWord(i)` 判 `submitted.value`，但 `submitted` 是 prop 而非 local ref；提交后仍可能 focus 到其他词。
- **修复**：改为 `props.submitted`。
- **来源**：审查者本人（前端通读）

### 【H11】`WrongPage.remove` 调用 `location.reload()` 整页刷新
- **位置**：`frontend/src/components/WrongPage.vue:21`
- **描述**：删除错词后整页刷新，白屏闪烁。
- **修复**：改为重新 `await api("/wrong")` 拉取列表。
- **来源**：审查者本人（前端通读）

### 【H12】`StatsPage.last14` 前端用 UTC 日期，后端 `date.today()` 用服务器本地时区，跨日对不上
- **位置**：`frontend/src/components/StatsPage.vue:9-19` vs `backend/catalog.py:46`
- **描述**：前端 `new Date(Date.now() - i*86400000).toISOString()` 用 UTC，后端用服务器时区。跨日/跨时区时"最近 14 天"与后端对齐失败，某几天数据对不上。
- **影响**：统计图表与后端计数不一致。
- **修复**：前端改用与后端相同时区逻辑，或后端传"截至日期"。
- **来源**：审查者本人（前后端对比）

### 【H13】`catalog.api_wrong` SQL 字符串拼接
- **位置**：`backend/misc.py:20-21`
- **描述**：`cond = "WHERE user=? AND wrong_count > 0" + (" AND list=?" if list_key else "")`。当前参数化绑定正确，但 SQL 拼接模式脆弱。
- **修复**：改为条件性参数绑定。
- **来源**：审查者本人（后端通读）

### 【H14】`MemorizePage.loadState` JSON 解析失败仅静默忽略，脏缓存不清理
- **位置**：`frontend/src/components/MemorizePage.vue:46-51`
- **描述**：`JSON.parse(raw)` 失败返回 `null`，外层会重新拉取 session；但**脏的 sessionStorage 未清理**，下次刷新仍失败。
- **影响**：用户首次遇到序列化损坏后永久"恢复失败"。
- **修复**：catch 中 `sessionStorage.removeItem(SS_KEY)`。
- **来源**：审查者本人（前端通读）

### 【H15】`daily_plan` 配额可能超额，且已分配不随会话完成回滚
- **位置**：`backend/catalog.py:229-236, 260-263`
- **描述**：每日 `allocated_new` 累加无上限校验。同一天多入口学习（scope/mode 切换、刷新）时，`remaining` 变为 0 后新词分配为空，配额被"偷走"。
- **影响**：新用户首日用错模式后配额耗尽。
- **修复**：分配前校验 `remaining > 0`，或对已完成/未使用配额做回滚。
- **来源**：审查者本人（后端通读）

### 【H16】`update_word_state` 中 `.get("memorized", 0)` 对 NULL 列失效
- **位置**：`backend/catalog.py:331-334`
- **描述**：`state = dict(row)` 后，若 DB 列 `memorized` 为 `NULL`，则该键存在于字典且值为 Python `None`。`state.get("memorized", 0)` 因为**键存在**，不会使用默认值 `0`，而是返回 `None`，被写入 SQL `VALUES` 元组，导致 `memorized` 存为 `NULL` 而非 `0`。后续逻辑中任何 `if state["memorized"]:` 判断都会失败（`None` 为 falsy，看似正确，但若后续 `+1` 会抛 TypeError）。
- **影响**：旧库迁移后或新建行的初始状态可能残留 `NULL`，破坏 `memorized=1` 计数和 UI 显示。这是一个经典的 Python/SQLite 交互陷阱。
- **修复**：改为 `state.get("memorized") or 0`，或在 `dict(row)` 后对 NULL 列做 `None → 默认值` 归一化。同样适用于 `memorize_count`、`last_memorize`。
- **来源**：后端子代理 Bug #4（真 bug，审查者本人经源码验证补充）

---

## 三、Low 级发现

### 【L1】`ensureAudio` HEAD 请求失败会误判文件缺失并重复 POST `/tts`
- `frontend/src/lib/core.js:104-110`：HEAD 失败（405/403）会误判缺失并懒生成；多并发调用同一缺失音频会重复 POST。
- 修复：HEAD 失败时改用 GET；加 in-flight map 缓存。
- 来源：审查者本人（前端通读）

### 【L2】`PracticePage` retrying 状态 Space 未处理
- `frontend/src/components/PracticePage.vue:133-137`：retrying 时 Enter 清空重输，但 Space 未处理，触发默认滚动。
- 来源：审查者本人（前端通读）

### 【L3】`api()` 的 `opts.timeout || API_TIMEOUT` 在 timeout=0 时立即超时
- `frontend/src/lib/core.js:43-64`：用 `opts.timeout ?? API_TIMEOUT`。
- 来源：审查者本人（前端通读）

### 【L4】WordCells `isCorrect` 要求 `!extraInput`，pure 模式输入额外字符后永远判错
- `frontend/src/components/WordCells.vue:85-88`：用户需先退格才能提交，UI 无提示。
- 来源：审查者本人（前端通读）

### 【L5】SentenceCells 单词长度上限 30 字符硬编码
- `frontend/src/components/SentenceCells.vue:37-40`：超长单词被截断，永远判错。
- 修复：提升上限或动态按目标长度。
- 来源：审查者本人（前端通读）

### 【L6】SentenceCells `isCorrect` 用 `filter(Boolean)` 判词数，跳词时体验困惑
- `frontend/src/components/SentenceCells.vue:107-110`：非空词数匹配但位置错乱时，用户以为"我打对了"却判错。
- 来源：审查者本人（前端通读）

### 【L7】SentenceCells `alignWords` 全错/空输入的边界行为未验证
- `frontend/src/components/SentenceCells.vue:135-157`：Levenshtein DP 实现，但未覆盖 `mine=[]`、`target=[]` 等边界。
- 来源：审查者本人（前端通读）

### 【L8】`Serve_audio` `is_relative_to` 路径穿越检查逻辑正确
- `backend/misc.py:115-121`：`p = (AUDIO/subpath).resolve()` 后 `p.is_relative_to(AUDIO.resolve())`，`../` 会被拒绝。Python 3.9+ 支持，当前环境 OK。
- 来源：审查者本人（后端通读）

### 【L9】`load_state` 的 `quizRound` 语义混乱
- `frontend/src/components/MemorizePage.vue:200, 262`：`quizRound` 既作"当前轮次"又作 WordCells key，`startQuiz` 和 `quizNext` 都递增。
- 来源：审查者本人（前端通读）

### 【L10】`conftest.py` patch 覆盖面
- `tests/conftest.py`：当前测试依赖 patch 后的 `MATERIALS`，但 `load_material` 的 `lru_cache` 在 fixture 清除后重新加载，逻辑 OK；若未来模块在 import 时缓存了 `MATERIALS` 引用会失效。
- 来源：审查者本人（测试通读）

### 【L11】`MemorizePage` 恢复后 `cur` 未重新 align 音频缓存
- `frontend/src/components/MemorizePage.vue:69-74`：恢复后 `play()` 会调 `ensureAudio`，但 `audioCache` 是恢复前的快照，可能已失效。
- 来源：审查者本人（前端通读）

---

## 四、数据文件问题（审查者本人发现，子代理未覆盖）

### 【D1-High】cet4 词库含 56 个同值重复词
- `wordlists/cet4.json`：`bear`×2、`box`×2、`can`×2 等。`load_material` 会分配 `~2`/`~3` 后缀 id，导致：
  - `memorize_session` fresh 池只排除已背项 → 同义词反复作为"新词"出现；
  - `word_state` 存多条记录；
  - 用户看到"重复的词"困惑。
- 修复：构建阶段合并同义项（多个释义用 `;` 拼接）或标注词性。

### 【D2-Medium】`oral900` 全部 900 句缺少 `lesson` 字段
- `sentences/oral900.json`：无法按课学习，且 `materials.load_material` 的 `lesson` 为 `None`。
- 修复：`build_data.py:fetch_oral900` 中按 module 分课补 `lesson`。

### 【D3-Low】cet6/kaoyan/tuofu 词库 `phonetic` 硬编码为空
- `scripts/build_data.py:54-58`：单文件分支 `phonetic=""`，辅助/纯模式听不到音标提示。

### 【D4-Low】`build_nce.py` `parse_lrc` 对 `body.startswith("[")` 的跳过
- `scripts/build_nce.py:44-46`：当前无 bug，记录。

---

## 五、Info 级

### 【Info1】`DESIGN.md` 提到 `scripts/make_wordlist.py` 但该文件不存在
- `DESIGN.md:102-106`：文档滞后，实际为 `build_data.py`。

### 【Info2】后端子代理补充的 4 项备注（原文引用，未复现验证）
- `_material_meta_cache` / `_audio_count_cache` 的进程内缓存，跨进程重启后重建——非 bug；
- `migrate()` 对 `daily_practice_log` 新表不做迁移——新部署 OK；
- `edge_tts.Communicate` 异步调用在同步 handler 中 `asyncio.run`——单请求 OK，高并发有线程竞争风险；
- `study_session_item` 的 `ON DELETE CASCADE` 配置正确。

---

## 六、优先修复建议（按 ROI 排序）

1. **H1** SentenceCells 连字符分词（影响面最大）
2. **H3** WordCells `typeLetter` 越界返回 undefined（边界误判正确）
3. **H2** 非字母字符静默丢弃
4. **H9** `onDocDown` 误阻断右键/拖拽
5. **H12** 时区不一致导致统计对不上
6. **H5/H6** `last_memorize` 未清空、quota 字段命名不统一
7. **H14** MemorizePage 脏缓存不清理
8. **D1** cet4 词库重复词
9. **D2** oral900 缺 lesson

---

## 七、审查统计

| 来源 | 报告数 | 说明 |
|---|---|---|
| 后端子代理（`c62b2d30`） | 15 | 3 High / 2 Medium / 6 Low / 4 备注（返回完整） |
| 前端子代理（`58d57348`） | 0 | 超时失败，消息为空 |
| 数据/测试子代理（`e0fda4e0`） | 0 | 超时失败，消息为空 |
| 审查者本人（前端+数据+脚本通读） | 25 | 覆盖前端 11 文件、数据 9 文件、脚本 3 文件 |
| **合并后（重定级）** | **约 31** | **6 High / 9 Medium / 11 Low / 5 Info** |

> 注：后端子代理原始 High 中有 2 项经源码验证——`last_memorize` 降为 M；`allocated_today` 子代理对计算逻辑的指控不成立（计算实际正确），真实问题是**字段命名不一致**，降为 M。后端子代理 Bug #4（`.get` NULL gotcha）为真 bug，先前遗漏，已补充为 H16。
