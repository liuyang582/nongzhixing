# -*- coding: utf-8 -*-
"""
将《农业知识RAG语料库_v1.md》解析为可直接入库的 JSONL。
用法: python build_jsonl.py
输出: agri_knowledge_v1.jsonl
"""
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE.parent / "农业知识RAG语料库_v1.md"
OUT = BASE / "agri_knowledge_v1.jsonl"

text = SRC.read_text(encoding="utf-8")

# ---------- 1. 从附录索引表取 title / 权威 / 时效 / 风险 ----------
titles = {}
for m in re.finditer(r"^\|\s*([A-G]\d{1,2}-\d{2})\s*\|\s*(.+?)\s*\|\s*([AB])\s*\|\s*(稳定|年度更新|时效性)\s*\|\s*(高|中|低)\s*\|",
                     text, re.M):
    titles[m.group(1)] = {
        "title": m.group(2),
        "authority": m.group(3),
        "stability": m.group(4),
        "risk_level": m.group(5),
    }

# ---------- 2. 切分条目 ----------
body_start = text.find("# 第二部分　语料正文")
body = text[body_start:]
blocks = re.split(r"\n(?=【条目】)", body)
blocks = [b for b in blocks if b.startswith("【条目】")]

def split_multi(val, seps=(",", ";", "、")):
    for s in seps:
        val = val.replace(s, "|")
    return [x.strip() for x in val.split("|") if x.strip()]

records, problems = [], []

for b in blocks:
    lines = b.split("\n")
    doc_id = lines[0].replace("【条目】", "").strip()

    meta = {}
    content_lines, in_content = [], False
    for ln in lines[1:]:
        if not in_content and re.match(r"^(分类|关键词|问法|来源|时效)[:：]", ln):
            for part in ln.split("|"):
                if ":" in part or "：" in part:
                    k, v = re.split(r"[:：]", part, maxsplit=1)
                    meta[k.strip()] = v.strip()
        elif ln.strip() == "---" and in_content:
            break
        elif ln.strip() == "---":
            in_content = True
        elif not in_content and ln.strip() == "":
            in_content = True
        elif in_content:
            content_lines.append(ln)

    content = "\n".join(content_lines).strip()
    content = re.sub(r"\n{3,}", "\n\n", content)

    cls = meta.get("分类", "")
    m2 = re.match(r"([A-G]\d{1,2}(?:\.\d+)?)\s*(.*)", cls)
    domain_l2 = (m2.group(2) if m2 else cls).strip()
    domain_l1 = doc_id[0]

    t = titles.get(doc_id, {})
    if not t:
        problems.append(f"{doc_id}: 附录索引表中缺少 title")

    rec = {
        "doc_id": doc_id,
        "title": t.get("title", ""),
        "domain_l1": domain_l1,
        "domain_l2": domain_l2,
        "crop": split_multi(meta.get("作物", "通用")),
        "region": split_multi(meta.get("区域", "全国")),
        "stage": split_multi(meta.get("生育期", "")),
        "operation": split_multi(meta.get("环节", "")),
        "keywords": split_multi(meta.get("关键词", "")),
        "queries": split_multi(meta.get("问法", "")),
        "content": content,
        "source": meta.get("来源", ""),
        "stability": meta.get("时效", t.get("stability", "")),
        "authority": meta.get("权威", t.get("authority", "")),
        "confidence": meta.get("置信", ""),
        "risk_level": meta.get("风险", t.get("risk_level", "")),
        "version": meta.get("版本", "v1.0"),
    }
    if "valid_from" in meta:
        rec["valid_from"] = meta["valid_from"]

    # 校验
    if not rec["source"]:
        problems.append(f"{doc_id}: 缺少 source")
    if len(rec["keywords"]) < 3:
        problems.append(f"{doc_id}: keywords 不足 3 个")
    if len(rec["queries"]) < 3:
        problems.append(f"{doc_id}: queries 不足 3 条")
    if len(rec["content"]) < 80:
        problems.append(f"{doc_id}: 正文过短({len(rec['content'])} 字符)")
    if rec["risk_level"] == "高" and not rec["source"]:
        problems.append(f"{doc_id}: 高风险条目缺少 source")

    records.append(rec)

# ---------- 3. 输出 ----------
with OUT.open("w", encoding="utf-8") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# ---------- 4. 报告 ----------
print(f"解析条目: {len(records)}")
print(f"输出文件: {OUT}")
by_l1 = {}
for r in records:
    by_l1[r["domain_l1"]] = by_l1.get(r["domain_l1"], 0) + 1
print("分类分布:", dict(sorted(by_l1.items())))
print(f"高风险条目: {sum(1 for r in records if r['risk_level'] == '高')}")
print(f"错误条目: {len(records) - len(by_l1)}")
if problems:
    print("\n--- 待修正问题 ---")
    for p in problems:
        print(" *", p)
else:
    print("\n✅ 全部条目通过校验")
