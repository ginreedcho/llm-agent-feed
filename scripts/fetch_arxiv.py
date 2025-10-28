#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_arxiv.py（最终版 - 仅合并昨日新增）
- 使用 arXiv Atom API 拉取符合 QUERIES 的论文
- 解析并产出条目格式： id, title, date(YYYY-MM-DD), tags, authors, institution, link, abstract, fetched_at
- 仅保留“昨日（UTC）”发布的条目作为新增，合并入已有 history（data/papers.json）
- 合并去重后按 date/fetched_at 降序保存（保留最近 KEEP_MAX 条）
"""
from __future__ import annotations
import os
import sys
import time
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

# ----------------- 配置 -----------------
ARXIV_API = "http://export.arxiv.org/api/query"
ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA_DIR = os.path.join(ROOT, "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "papers.json")
MAX_RESULTS_PER_QUERY = 50
KEEP_MAX = 600

# 请把 email 改为你的联系邮箱（遵守 arXiv 建议）
HEADERS = {"User-Agent": "llm-agent-feed/1.0 (mailto:your-email@example.com)"}

# 查询（已修正优先级和括号）
QUERIES = [
    '(all:"large language model" OR all:"LLM" OR all:"language model") AND all:agent',
    'all:agent AND (all:"reinforcement learning" OR all:planning OR all:tool-use OR all:"memory" OR all:"grounding")',
    '(ti:"agent" OR abs:"agent") AND (ti:"LLM" OR abs:"LLM" OR ti:"language model" OR abs:"language model")',
    'cat:cs.AI OR cat:cs.CL OR cat:cs.LG'
    ]

# ----------------- 辅助函数 -----------------
def arxiv_query(search_query: str, start=0, max_results=50) -> str:
    params = {
        "search_query": search_query,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    }
    resp = requests.get(ARXIV_API, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text

def safe_text(elem):
    return (elem.text or "").strip() if elem is not None else ""

def parse_atom(atom_xml: str) -> List[Dict[str, Any]]:
    ns = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}
    root = ET.fromstring(atom_xml)
    entries: List[Dict[str, Any]] = []
    for entry in root.findall('atom:entry', ns):
        try:
            raw_id = safe_text(entry.find('atom:id', ns))
            arxiv_id = raw_id.rsplit('/', 1)[-1] if raw_id else None
            title = safe_text(entry.find('atom:title', ns)).replace('\n', ' ').strip()
            summary = safe_text(entry.find('atom:summary', ns)).replace('\n', ' ').strip()
            published = safe_text(entry.find('atom:published', ns))  # e.g. 2025-10-27T12:34:56Z

            # parse authors + affiliations (if present)
            authors = []
            affiliations = set()
            for author in entry.findall('atom:author', ns):
                name = safe_text(author.find('atom:name', ns))
                if name:
                    authors.append(name)
                aff = author.find('arxiv:affiliation', ns)
                if aff is not None and aff.text and aff.text.strip():
                    affiliations.add(aff.text.strip())

            # categories -> tags
            cats = [c.attrib.get('term') for c in entry.findall('atom:category', ns) if c.attrib.get('term')]

            # try to find pdf link
            pdf_link = None
            for link in entry.findall('atom:link', ns):
                t = link.attrib.get('type', '')
                href = link.attrib.get('href', '')
                if t == 'application/pdf' and href:
                    pdf_link = href
                    break
            if not pdf_link and arxiv_id:
                pdf_link = f"https://arxiv.org/pdf/{arxiv_id}"

            # build institution (from affiliations if present; otherwise simple fallback)
            institution = ", ".join(sorted(affiliations)) if affiliations else ""
            if not institution:
                fallback_orgs = ['Google', 'DeepMind', 'Microsoft', 'Meta', 'OpenAI', 'CMU', 'MIT', 'Stanford', 'Huawei', 'HiSilicon', 'ETH Zurich', 'EPFL']
                found = []
                st = (title + " " + summary).lower()
                for org in fallback_orgs:
                    if org.lower() in st:
                        found.append(org)
                institution = ", ".join(found)

            # tags: include categories and their suffix
            tags: List[str] = []
            for c in cats:
                if c:
                    tags.append(c)
                    if '.' in c:
                        tags.append(c.split('.')[-1])

            # dedupe tags preserving order
            seen = set()
            tags_clean = []
            for t in tags:
                tt = t.strip()
                if tt and tt not in seen:
                    seen.add(tt)
                    tags_clean.append(tt)

            # date as YYYY-MM-DD (from published)
            date = ""
            if published:
                try:
                    date = datetime.fromisoformat(published.replace('Z', '+00:00')).date().isoformat()
                except Exception:
                    date = published.split('T')[0] if 'T' in published else published

            entry_obj = {
                "id": arxiv_id,
                "title": title,
                "date": date,
                "tags": tags_clean,
                "authors": authors,
                "institution": institution,
                "link": pdf_link,
                "abstract": summary,
                "fetched_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            }
            entries.append(entry_obj)
        except Exception as e:
            print("parse entry error:", e, file=sys.stderr)
    return entries

def load_existing() -> List[Dict[str, Any]]:
    if not os.path.exists(OUTPUT_FILE):
        return []
    try:
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_entries(entries: List[Dict[str, Any]]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

def merge_and_dedupe(old: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # by id, prefer newer fetched_at from new entries
    by_id: Dict[str, Dict[str, Any]] = {e['id']: e for e in old if e.get('id')}
    for e in new:
        if not e.get('id'):
            continue
        if e['id'] in by_id:
            # if new is newer, replace
            try:
                if e.get('fetched_at', '') > by_id[e['id']].get('fetched_at', ''):
                    by_id[e['id']] = e
            except Exception:
                by_id[e['id']] = e
        else:
            by_id[e['id']] = e
    merged = list(by_id.values())
    # sort by date desc then fetched_at desc
    def sort_key(x: Dict[str, Any]):
        return (x.get('date', ''), x.get('fetched_at', ''))
    merged.sort(key=sort_key, reverse=True)
    return merged[:KEEP_MAX]

# ----------------- 主流程 -----------------
def main():
    all_new = []
    for q in QUERIES:
        try:
            xml = arxiv_query(q, start=0, max_results=MAX_RESULTS_PER_QUERY)
            ents = parse_atom(xml)
            all_new.extend(ents)
            time.sleep(1.0)
        except Exception as e:
            print("query error:", e, file=sys.stderr)

    # dedupe within this run by id (keep first seen)
    uniq: Dict[str, Dict[str, Any]] = {}
    for e in all_new:
        if e.get('id') and e['id'] not in uniq:
            uniq[e['id']] = e
    new_list = list(uniq.values())

    # calculate yesterday (UTC)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    # filter new_list to only keep those with published date == yesterday
    new_list_filtered: List[Dict[str, Any]] = []
    for e in new_list:
        pub_str = e.get("date", "")
        if not pub_str:
            continue
        try:
            pub_date = datetime.fromisoformat(pub_str).date()
        except Exception:
            # fallback try fetched_at
            try:
                pub_date = datetime.fromisoformat(e.get("fetched_at", "").replace('Z', '+00:00')).date()
            except Exception:
                continue
        if pub_date == yesterday:
            new_list_filtered.append(e)

    existing = load_existing()
    merged = merge_and_dedupe(existing, new_list_filtered)
    save_entries(merged)

    print(f"Found {len(new_list)} unique results this run; {len(new_list_filtered)} are from yesterday ({yesterday.isoformat()}).")
    print(f"Saved {len(merged)} total entries to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
