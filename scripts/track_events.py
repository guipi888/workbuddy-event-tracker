#!/usr/bin/env python3
"""
赛事活动追踪脚本 v2.0
功能：
  1. 从配置的信息源抓取赛事信息
  2. 与历史记录比对，找出新增/变更赛事
  3. 新赛事自动提交到 OPC 公共赛事池（需要 API Key）
  4. 输出摘要 + 更新本地记录

数据文件：
  - user_config.json  : API Key 配置
  - sources.json      : 信息源列表
  - events_history.json : 历史记录
"""

import json
import re
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse

# ============================================================
# 路径配置
# 所有数据文件存放在脚本同级目录下的 data/ 中
# 技能安装后路径示例：~/.workbuddy/skills/赛事活动追踪/scripts/
# ============================================================
SCRIPT_DIR = Path(__file__).parent
USER_CONFIG_FILE = SCRIPT_DIR / "user_config.json"
SOURCES_FILE = SCRIPT_DIR / "sources.json"
HISTORY_FILE = SCRIPT_DIR / "events_history.json"
DATA_DIR = SCRIPT_DIR / "data"
RECORD_MD = DATA_DIR / "赛事记录.md"

# ============================================================
# 工具函数
# ============================================================

def load_json(filepath):
    if not filepath.exists():
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(filepath, data):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_url(url, timeout=30):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except (URLError, HTTPError) as e:
        print(f"  [!] 抓取失败: {url} -> {e}")
        return None


def extract_text(html, max_len=50000):
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def make_id(source_id, event_name):
    raw = f"{source_id}:{event_name}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def to_iso(dt_str, default_tz="+08:00"):
    """将各种日期字符串转为 ISO 8601"""
    if not dt_str:
        return None
    # 如果已经是 ISO 格式
    if "T" in dt_str:
        return dt_str if "+" in dt_str or "Z" in dt_str else f"{dt_str}{default_tz}"
    # 纯日期格式 2026-07-21 → 2026-07-21T00:00:00+08:00
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", dt_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}T00:00:00{default_tz}"
    return None


def infer_type(text):
    """从文本推断赛事 type"""
    t = text.lower()
    if any(k in t for k in ["黑客松", "hackathon", "编程马拉松", "marathon"]):
        return "hackathon"
    if any(k in t for k in ["创业", "路演", "business plan", "startup"]):
        return "startup"
    if any(k in t for k in ["设计", "ui/ux", "品牌", "visual"]):
        return "design"
    if any(k in t for k in ["数学", "建模", "学术", "acm", "科研"]):
        return "academic"
    if any(k in t for k in ["峰会", "summit", "conference", "大会"]):
        return "summit"
    return "hackathon"


def infer_region(text):
    """从文本推断赛事 region"""
    t = text
    if any(k in t for k in ["线上", "online", "远程"]):
        return "online"
    if "北京" in t:
        return "beijing"
    if "上海" in t:
        return "shanghai"
    if "杭州" in t:
        return "hangzhou"
    if "深圳" in t:
        return "shenzhen"
    if any(k in t for k in ["全国", "中国"]):
        return "national"
    if any(k in t for k in ["海外", "国外", "overseas"]):
        return "overseas"
    return "online"


def extract_tags(text, max_tags=8):
    """从文本提取标签关键词"""
    tag_map = {
        "AI": ["ai", "人工智能", "大模型", "机器学习", "深度学习", "llm", "gpt", "智能体"],
        "Web3": ["web3", "区块链", "crypto", "nft", "defi", "智能合约"],
        "编程挑战": ["编程", "coding", "代码", "算法", "数据结构"],
        "开源": ["开源", "open source", "github"],
        "学生赛": ["学生", "大学生", "高校", "校园"],
        "多模态": ["多模态", "multimodal"],
        "Agent": ["agent", "智能体"],
        "独立开发": ["独立开发", "独立开发者", "indie hacker", "indie"],
        "创业": ["创业", "startup", "创始人"],
        "产品": ["产品", "product", "pm"],
    }
    tags = []
    t_lower = text.lower()
    for tag_name, keywords in tag_map.items():
        if any(kw in t_lower for kw in keywords):
            tags.append(tag_name)
            if len(tags) >= max_tags:
                break
    return tags


# ============================================================
# OPC API 提交
# ============================================================

def submit_to_opc(event, user_config):
    """
    将赛事提交到 OPC 公共赛事池
    返回：(success, code, data)
    """
    api_key = user_config.get("api_key")
    if not api_key:
        print("    ⚠️  未配置 API Key，跳过提交")
        return False, "no_key", None

    api_base = user_config.get("api_base", "https://mrkjai.com")
    url = f"{api_base}/api/events/ingest"

    # 组装 payload
    published_at = to_iso(event.get("publish_date")) or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT00:00:00+08:00")
    deadline_at = to_iso(event.get("deadline"))

    if not deadline_at:
        # 兜底：publishedAt + 30 天
        from datetime import datetime as dt
        pub_dt = dt.fromisoformat(published_at)
        deadline_dt = pub_dt + timedelta(days=30)
        deadline_at = deadline_dt.strftime("%Y-%m-%dT23:59:59+08:00")

    full_text = event.get("raw_snippet", "") + " " + event.get("name", "")
    event_type = infer_type(full_text)
    event_region = infer_region(full_text)

    payload = {
        "title": event.get("name", "")[:120],
        "summary": event.get("summary", event.get("name", ""))[:300],
        "type": event.get("api_type", event_type),
        "region": event.get("api_region", event_region),
        "organizer": event.get("organizer", "")[:100],
        "publishedAt": published_at,
        "deadlineAt": deadline_at,
        "externalUrl": event.get("url", ""),
    }

    tags = extract_tags(full_text)
    if tags:
        payload["tags"] = tags[:8]

    # 校验必填
    for field in ["title", "summary", "organizer", "externalUrl"]:
        if not payload[field]:
            print(f"    ⚠️  必填字段 {field} 为空，跳过提交")
            return False, "missing_field", None

    payload_json = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    try:
        req = Request(
            url,
            data=payload_json,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-API-Key": api_key,
            },
            method="POST",
        )
        with urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            code = body.get("code", "unknown")
            ok = body.get("ok", False)

            if ok and code in ("created", "exists"):
                data = body.get("data", {})
                return True, code, data
            else:
                print(f"    ❌ OPC 返回错误: code={code}, field={body.get('field','')}, error={body.get('error','')}")
                return False, code, body

    except HTTPError as e:
        print(f"    ❌ HTTP {e.code}: {e.reason}")
        return False, f"http_{e.code}", None
    except URLError as e:
        print(f"    ❌ 网络错误: {e}")
        return False, "network_error", None
    except Exception as e:
        print(f"    ❌ 提交异常: {e}")
        return False, "exception", None


# ============================================================
# 信息源解析器
# ============================================================

def parse_trae_forum(html_text, source):
    """解析 TRAE 论坛帖"""
    text = extract_text(html_text)
    events = []

    # 批次公示
    batch_pattern = r"第\s*(\d+)\s*批[・·]?\s*截至\s*(\d+)\s*月\s*(\d+)\s*日\s*(\d+)\s*点"
    for m in re.finditer(batch_pattern, text):
        batch_num, month, day, hour = m.group(1), m.group(2), m.group(3), m.group(4)
        ctx = text[m.end():m.end() + 500]
        count_match = re.search(r"(\d[\d,]*)\s*个.*?(?:报名|通过)", ctx)
        count = count_match.group(1).replace(",", "") if count_match else "未知"

        events.append({
            "id": make_id(source["id"], f"TRAE AI 创造力大赛 - 第{batch_num}批"),
            "source_id": source["id"],
            "name": f"TRAE AI 创造力大赛 - 第{batch_num}批报名公示",
            "type": "AI赛事",
            "organizer": "TRAE（字节系）",
            "status": "报名中",
            "batch": batch_num,
            "publish_date": f"2026-{int(month):02d}-{int(day):02d}",
            "approved_count": count,
            "raw_snippet": ctx[:200],
            "url": source["url"],
            "api_type": "hackathon",
            "api_region": "online",
            "discovered_at": datetime.now().strftime("%Y-%m-%d"),
        })

    # 整体赛事
    prize = re.search(r"(\d+)\s*万元\s*现金", text)
    initial = re.search(
        r"(?:初赛[^。\n]{0,20}于\s*|于\s*)(\d{1,2})\s*月\s*(\d{1,2})\s*日[^。\n]{0,30}初赛"
        r"|初赛[^。\n]{0,10}(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        text
    )
    meta = {}
    if prize:
        meta["prize"] = f"{prize.group(1)}万元现金"
    if initial:
        g = initial.groups()
        m = next((g for g in g[::2] if g), None)
        d = next((g for g in g[1::2] if g), None)
        if m and d:
            meta["initial_result_date"] = f"2026-{int(m):02d}-{int(d):02d}"

    # 尝试提取报名截止时间
    deadline_match = re.search(r"报名.*?(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    deadline = None
    if deadline_match:
        deadline = f"2026-{int(deadline_match.group(1)):02d}-{int(deadline_match.group(2)):02d}"

    events.insert(0, {
        "id": make_id(source["id"], "TRAE AI 创造力大赛"),
        "source_id": source["id"],
        "name": "TRAE AI 创造力大赛",
        "summary": f"字节系 TRAE 主办的 AI 创造力大赛，{meta.get('prize','35万元现金')}大奖",
        "type": "AI赛事",
        "organizer": "TRAE（字节系）",
        "status": "报名中",
        "prize": meta.get("prize", "35万元现金"),
        "publish_date": "2026-06-01",
        "deadline": deadline,
        "initial_result_date": meta.get("initial_result_date", "2026-07-21"),
        "url": source["url"],
        "api_type": "hackathon",
        "api_region": "online",
        "raw_snippet": text[:500],
        "discovered_at": datetime.now().strftime("%Y-%m-%d"),
    })

    return events


def parse_workbuddy_campaign(html_text, source):
    """解析 WorkBuddy 超级个体大赛页面"""
    text = extract_text(html_text)
    title_match = re.search(r"<title>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else source["name"]

    # 奖金
    prize = None
    prize_match = re.search(r"(\d[\d,]*)\s*万", text)
    if prize_match:
        prize = f"{prize_match.group(1)}万元"

    # 时间
    deadline_match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日.*?截止", text)

    return [{
        "id": make_id(source["id"], title),
        "source_id": source["id"],
        "name": title,
        "summary": text[:300],
        "type": source.get("category", "AI赛事"),
        "organizer": source.get("organizer", ""),
        "status": "进行中",
        "prize": prize,
        "publish_date": "2026-06-01",
        "deadline": f"2026-{int(deadline_match.group(1)):02d}-{int(deadline_match.group(2)):02d}" if deadline_match else None,
        "url": source["url"],
        "api_type": "hackathon",
        "api_region": "online",
        "raw_snippet": text[:500],
        "discovered_at": datetime.now().strftime("%Y-%m-%d"),
    }]


PARSERS = {
    "trae_forum": parse_trae_forum,
    "workbuddy_super_individual": parse_workbuddy_campaign,
}


# ============================================================
# 核心逻辑
# ============================================================

def compare_with_history(new_events, history):
    new_list, changed_list = [], []
    for event in new_events:
        eid = event["id"]
        if eid not in history:
            new_list.append(event)
        else:
            old = history[eid]
            changes = []
            for key in ["status", "approved_count", "batch", "prize", "deadline"]:
                if key in event and key in old and event[key] != old[key]:
                    changes.append(f"{key}: {old[key]} -> {event[key]}")
            if changes:
                changed_list.append({"event": event, "changes": changes})
    return new_list, changed_list


def update_markdown_record(history):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# 赛事活动记录",
        f"> 最后更新：{now}",
        "",
        "## 进行中 / 即将开始",
        "| 赛事名称 | 类型 | 主办方 | 状态 | 奖品 | 关键日期 | 链接 |",
        "|---------|------|--------|------|------|---------|------|",
    ]

    active = [(eid, e) for eid, e in history.items() if e.get("status") not in ["已结束", "归档"]]
    for eid, event in sorted(active, key=lambda x: x[1].get("discovered_at", ""), reverse=True):
        name = event.get("name", "")
        etype = event.get("type", "")
        org = event.get("organizer", "")
        status = event.get("status", "")
        prize = event.get("prize", "")
        kd = event.get("initial_result_date") or event.get("deadline") or event.get("publish_date", "")
        url = event.get("url", "")
        lines.append(f"| {name} | {etype} | {org} | {status} | {prize} | {kd} | {url} |")

    lines += ["", "## 已结束（归档）", "| 赛事名称 | 类型 | 时间 | 奖品 | 链接 |", "|---------|------|------|------|------|"]

    for eid, event in history.items():
        if event.get("status") in ["已结束", "归档"]:
            name, etype, prize = event.get("name",""), event.get("type",""), event.get("prize","")
            url = event.get("url", "")
            lines.append(f"| {name} | {etype} | {event.get('publish_date','')} | {prize} | {url} |")

    lines.append("")
    with open(RECORD_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    print("=" * 60)
    print(f"赛事活动追踪脚本 v2.0")
    print(f"执行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 0. 加载用户配置
    user_config = load_json(USER_CONFIG_FILE)
    has_api_key = bool(user_config.get("api_key"))
    print(f"\n🔑 API Key: {'已配置' if has_api_key else '未配置（将跳过 OPC 提交）'}")

    # 1. 加载信息源
    sources_config = load_json(SOURCES_FILE)
    sources = sources_config.get("sources", [])
    print(f"📋 已配置 {len(sources)} 个信息源")

    # 2. 加载历史
    history = load_json(HISTORY_FILE) or {}
    print(f"📦 历史记录：{len(history)} 条")

    # 3. 逐个信息源抓取
    all_new, all_changed = [], []
    opc_results = []

    for source in sources:
        if not source.get("enabled", True):
            print(f"\n⏭️  跳过：{source['name']}")
            continue

        print(f"\n🔍 抓取：{source['name']} ({source['url']})")

        html = fetch_url(source["url"])
        if not html:
            print(f"   ❌ 抓取失败")
            continue
        print(f"   ✅ 抓取成功，{len(html)} 字符")

        parser = PARSERS.get(source["id"])
        if not parser:
            print(f"   ⚠️  无解析器，使用通用解析")
            text = extract_text(html, 5000)
            title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            title = title_match.group(1).strip() if title_match else source["name"]
            events = [{
                "id": make_id(source["id"], title),
                "source_id": source["id"],
                "name": title,
                "summary": text[:300],
                "type": source.get("category", "未知"),
                "organizer": source.get("organizer", ""),
                "status": "未知",
                "url": source["url"],
                "publish_date": datetime.now().strftime("%Y-%m-%d"),
                "raw_snippet": text[:500],
                "discovered_at": datetime.now().strftime("%Y-%m-%d"),
            }]
        else:
            events = parser(html, source)

        print(f"   📊 解析出 {len(events)} 个事件")

        new_events, changed_events = compare_with_history(events, history)
        all_new.extend(new_events)
        all_changed.extend(changed_events)

        # 提交新事件到 OPC
        for event in new_events:
            if has_api_key:
                ok, code, data = submit_to_opc(event, user_config)
                opc_results.append({"event": event["name"], "ok": ok, "code": code, "data": data})
                if ok and code == "created":
                    print(f"   ✅ OPC 收录成功: {event['name']}")
                elif ok and code == "exists":
                    print(f"   ℹ️  OPC 已存在: {event['name']}")
                else:
                    print(f"   ⚠️  OPC 提交失败({code}): {event['name']}")

        for event in events:
            history[event["id"]] = event

    # 4. 输出结果
    print("\n" + "=" * 60)
    print("📊 追踪结果")
    print("=" * 60)

    if all_new:
        print(f"\n🆕 发现 {len(all_new)} 个新事件：")
        for i, event in enumerate(all_new, 1):
            print(f"\n  {i}. {event['name']}")
            print(f"     类型：{event.get('type','')}  |  状态：{event.get('status','')}")
            if event.get("prize"):
                print(f"     奖品：{event['prize']}")
            if event.get("initial_result_date"):
                print(f"     初赛结果：{event['initial_result_date']}")
            if event.get("deadline"):
                print(f"     报名截止：{event['deadline']}")
            print(f"     链接：{event.get('url','')}")
    else:
        print("\n✅ 无新增事件")

    if all_changed:
        print(f"\n🔄 检测到 {len(all_changed)} 个事件变更：")
        for item in all_changed:
            print(f"\n  📌 {item['event']['name']}")
            for c in item["changes"]:
                print(f"     {c}")
    else:
        print("\n✅ 无事件变更")

    # 5. OPC 提交汇总
    if opc_results:
        created = sum(1 for r in opc_results if r["ok"] and r["code"] == "created")
        exists = sum(1 for r in opc_results if r["ok"] and r["code"] == "exists")
        failed = sum(1 for r in opc_results if not r["ok"])
        print(f"\n🌐 OPC 提交汇总: 收录 {created} | 已存在 {exists} | 失败 {failed}")

    # 6. 保存
    save_json(HISTORY_FILE, history)
    print(f"\n💾 历史记录已保存：{HISTORY_FILE}")
    update_markdown_record(history)
    print(f"📝 Markdown 记录已更新：{RECORD_MD}")

    summary = {
        "run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_sources": len(sources),
        "total_history": len(history),
        "new_count": len(all_new),
        "changed_count": len(all_changed),
        "new_events": all_new,
        "changed_events": all_changed,
        "opc_results": opc_results,
        "has_api_key": has_api_key,
    }
    summary_file = SCRIPT_DIR / "last_run_summary.json"
    save_json(summary_file, summary)
    print(f"📋 运行摘要已保存：{summary_file}")

    print("\n" + "=" * 60)
    print("✅ 追踪完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
