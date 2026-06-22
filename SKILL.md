---
name: OPC赛事活动追踪
slug: opc-event-tracker
displayName: OPC赛事活动追踪
version: "2.1.0"
description: 追踪 OPC/AI/独立开发者相关赛事活动。从信息源抓取 → 提取结构化信息 → 提交到 OPC 公共赛事池。安装时引导用户获取 API Key。触发词：赛事、比赛、hackathon、活动、OPC赛事、AI比赛、独立开发者大赛、收录赛事、加到OPC
agent_created: true
triggers:
  - 赛事
  - 比赛
  - hackathon
  - 活动
  - OPC赛事
  - AI比赛
  - 独立开发者大赛
  - 收录赛事
  - 加到OPC
  - 推到OPC
xiaping_trigger:
  - 赛事
  - 比赛
  - hackathon
  - 活动
  - OPC
  - AI比赛
  - 收录赛事
xiaping_category:
  - 效率工具
  - 信息聚合
xiaping_tags:
  - 赛事追踪
  - OPC
  - 黑客松
  - AI
  - 创业大赛
  - 独立开发者
---

# 赛事活动追踪

## 首次安装引导（必须执行）

安装本技能后，**必须先引导用户设置 API Key**，否则无法提交到 OPC 公共赛事池。

### 引导流程

1. 输出以下引导文案：

```
🔑 OPC 赛事收录 — API Key 设置

本技能可以将赛事提交到 OPC（一人公司工具站）的公共赛事池。
你需要一个 API Key 才能提交。

📋 获取方式：
  1. 打开 https://mrkjai.com
  2. 登录/注册账号
  3. 进入「我的 → 个人集成（API Key）」页面
  4. 复制你的 Key（格式：opc_user_xxx...）
  5. 回到这里，把 Key 发给我

💡 没有 Key 的话，本技能只能本地追踪赛事，无法提交到公共池。
```

2. 用户提供 Key 后，写入配置文件：`scripts/user_config.json`
3. 确认设置成功，告知用户：「✅ API Key 已保存，现在可以收录赛事了」

### user_config.json 结构

```json
{
  "api_key": "opc_user_xxx...",
  "api_base": "https://mrkjai.com",
  "configured_at": "2026-06-22T17:00:00+08:00"
}
```

---

## 触发方式

- 用户提供赛事链接 + 说"收录"/"加到OPC"/"推到OPC" → **提取+提交到 OPC**
- 用户主动问"有什么赛事" → 展示本地追踪记录
- 定时任务自动执行（每周一） → 抓取信息源 + 提交到 OPC
- 用户说"新增信息源" → 追加到 sources.json

---

## 核心流程

### 流程A：用户提供链接 → 收录到 OPC

1. 用 WebFetch 抓取链接内容
2. 从页面中提取结构化字段（见下方字段映射表）
3. 展示确认清单，等用户确认
4. 调用 OPC API 提交
5. 同时写入本地 events_history.json

### 流程B：定时追踪 → 自动抓取+提交

1. 读取 `scripts/sources.json`，获取所有已启用的信息源
2. 逐个信息源抓取页面内容
3. 调用对应解析器提取结构化字段
4. 与 `scripts/events_history.json` 比对
5. 新赛事 → 调用 OPC API 提交（使用用户的 API Key）
6. 更新本地历史 JSON + Markdown 记录
7. 输出摘要

---

## OPC API 接口规范

### 接口信息

| 项目 | 值 |
|------|-----|
| 方法 | POST |
| 路径 | `/api/events/ingest` |
| 域名 | 从 user_config.json 读取 `api_base`，默认 `https://mrkjai.com` |
| Content-Type | application/json; charset=utf-8 |
| 鉴权 | Header `X-API-Key: {api_key}` |

### 必填字段

| 字段 | 类型 | 限制 | 说明 |
|------|------|------|------|
| `title` | string | 1-120 字符 | 赛事名称 |
| `summary` | string | 1-300 字符 | 一句话描述 |
| `type` | enum | 见下方 | 赛事类型 |
| `region` | enum | 见下方 | 地区 |
| `organizer` | string | 1-100 字符 | 主办方 |
| `publishedAt` | string | ISO 8601 | 赛事发布/开始时间 |
| `deadlineAt` | string | ISO 8601 | 报名截止时间，必须晚于 publishedAt |
| `externalUrl` | string | 合法 URL | 赛事详情页 URL，去重键 |

### 选填字段

| 字段 | 类型 | 限制 |
|------|------|------|
| `tags` | string[] | 最多 8 个 |

### 枚举值

**type**：`startup`(创业大赛) / `hackathon`(黑客松) / `design`(设计比赛) / `academic`(学术竞赛) / `summit`(行业峰会)

**region**：`online`(线上) / `beijing` / `shanghai` / `hangzhou` / `shenzhen` / `national`(全国) / `overseas`(海外)

### 返回码

| code | 含义 |
|------|------|
| `created` | 成功收录 |
| `exists` | externalUrl 已存在（幂等） |
| `unauthenticated` | 缺 X-API-Key |
| `invalid_key` | Key 无效 |
| `key_revoked` | Key 已撤销 |
| `validation_error` | 字段校验失败 |
| `internal_error` | 服务器异常 |

---

## 字段提取规则

### 从页面内容推断字段

| 抓取内容 | API 字段 | 推断规则 |
|----------|---------|---------|
| 页面 h1 / title | `title` | 去站点后缀、清理空白 |
| meta description / 首个 p | `summary` | 截断到 300 字符 |
| 主办方/承办方文本 | `organizer` | 截断到 100 字符 |
| 比赛开始时间 | `publishedAt` | 转 ISO 8601；找不到用当前时间 |
| 报名截止时间 | `deadlineAt` | 转 ISO 8601；找不到传 publishedAt + 30 天 |
| 详情页 URL | `externalUrl` | 原样传，用于去重 |
| 关键词/分类 | `tags` | 取前 8 个 |

### type 推断

```
含"黑客松/hackathon/编程马拉松" → hackathon
含"创业/路演/business plan/startup" → startup
含"设计/UI/UX/品牌/visual" → design
含"数学/建模/学术/ACM/科研" → academic
含"峰会/summit/conference/大会" → summit
都匹配不到 → hackathon（默认）
```

### region 推断

```
含"线上/online/远程" → online
含"北京" → beijing
含"上海" → shanghai
含"杭州" → hangzhou
含"深圳" → shenzhen
含"全国/中国" → national
含"海外/国外/overseas" → overseas
都没匹配 → online（默认）
```

### 重要规则

- deadlineAt 抓不到时传 publishedAt + 30 天，summary 里注明"长期有效"
- title 或 organizer 抓不到 → 直接告诉用户缺失，不瞎猜
- 同一 externalUrl 重复提交是幂等的（接口返回 exists）
- publishedAt 不要设为未来时间

---

## 执行命令

```bash
# 手动运行追踪（Python 3.8+ 均可，建议用系统 python3）
python3 "/<技能安装目录>/赛事活动追踪/scripts/track_events.py"

# 或显式指定 python3 路径（如 managed runtime）
# /Users/kyle/.workbuddy/binaries/python/versions/3.13.12/bin/python3 \
#   "/Users/kyle/.workbuddy/skills/赛事活动追踪/scripts/track_events.py"
```

---

## 信息源管理

配置文件：`scripts/sources.json`

用户新增信息源时，追加到 `sources` 数组：

```json
{
  "id": "唯一标识",
  "name": "显示名称",
  "url": "抓取地址",
  "type": "forum_post | official_page | rss | api | campaign_page",
  "category": "OPC赛事 | AI赛事 | 创业大赛 | 独立开发者",
  "organizer": "主办方",
  "enabled": true,
  "notes": "备注"
}
```

新增信息源后，在 `scripts/track_events.py` 的 `PARSERS` 字典注册对应解析函数。

### 已配置信息源

| ID | 名称 | URL | 类型 | 状态 |
|----|------|-----|------|------|
| trae_forum | TRAE AI 创造力大赛 | https://forum.trae.cn/t/topic/28826 | forum_post | ✅ |
| workbuddy_super_individual | WorkBuddy 超级个体大赛 | https://www.codebuddy.cn/events/super-individual | campaign_page | ✅ |

---

## 数据存储

| 文件 | 安装后路径 | 用途 |
|------|---------|------|
| user_config.json | `scripts/user_config.json` | 用户 API Key 配置（**勿提交到公开仓库**） |
| sources.json | `scripts/sources.json` | 信息源配置 |
| events_history.json | `scripts/events_history.json` | 历史赛事记录（自动生成） |
| 赛事记录.md | `scripts/data/赛事记录.md` | 人类可读记录（自动生成） |

---

## references/ 目录说明

- [sources-mgmt.md](references/sources-mgmt.md) — 信息源添加规范
- [api-spec.md](references/api-spec.md) — OPC API 完整对接文档（可复制给其他 AI）

---

## 开源发布注意事项

### ⚠️ 安全提醒

- **`scripts/user_config.json` 包含用户 API Key，切勿提交到公开仓库**
- 建议在 `.gitignore` 中添加：`scripts/user_config.json` 和 `scripts/data/`
- `scripts/events_history.json` 和 `scripts/last_run_summary.json` 是运行时产物，也不应提交

### 推荐的 `.gitignore`

```
scripts/user_config.json
scripts/events_history.json
scripts/last_run_summary.json
scripts/data/
```

### 开源适配清单

| 检查项 | 状态 |
|--------|------|
| 无硬编码绝对路径 | ✅ DATA_DIR 改为相对路径 |
| 无真实 API Key | ✅ user_config.json 已清空 |
| Python 路径通用化 | ✅ 执行命令改为 python3 |
| 勿提交运行时产物 | ✅ .gitignore 已建议 |

---

## 📝 版本迭代记录

| 版本 | 日期 | 更新内容摘要 | 操作人 |
|------|------|------------|--------|
| v1.0 | 2026-06-22 | 创建技能（WebSearch 方案） | Kyle |
| v1.1 | 2026-06-22 | 升级脚本化抓取 + JSON历史比对 | Kyle |
| v2.0 | 2026-06-22 | 重大升级：集成 OPC API 提交 + 安装引导获取 Key + 用户链路 | Kyle |
| v2.1 | 2026-06-22 | 开源适配：清空真实 Key、路径通用化、添加 .gitignore 建议 | Kyle |
