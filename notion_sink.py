#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notion_sink.py — 조합한 법령을 '이용자 각자의' 노션으로 푸시.

push_guides.py의 노션 푸시 로직을 재사용하되, NOTION_TOKEN·부모페이지를 함수 인자로 받아
웹앱 이용자가 자기 토큰/자기 페이지로 푸시할 수 있게 한다(계정 하드코딩 없음).

핵심: push_one(token, name, kind, parent, mother) — 한 문서를 parent 페이지 아래
자식 페이지로 생성하고, 본문 속 인용은 그 자리 📎 토글로 붙인다.
"""
import re, json, time, urllib.request, urllib.error
import law_engine as E

NAPI = "https://api.notion.com/v1"

# ── 노션 API ─────────────────────────────────────────────────────────────
def napi(token, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(NAPI + path, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"})
    for i in range(6):
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                out = json.loads(resp.read().decode("utf-8"))
                time.sleep(0.34)
                return out
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            if e.code == 429 and i < 5: time.sleep(2 * (i + 1)); continue
            if e.code in (502, 503, 504) and i < 3: time.sleep(2 * (i + 1)); continue
            raise RuntimeError(f"[노션 {e.code}] {method} {path}\n{msg}")

# ── 블록 빌더 ─────────────────────────────────────────────────────────────
def rt(s):
    s = s if s else " "
    return [{"type": "text", "text": {"content": s[i:i+1900]}} for i in range(0, len(s), 1900)]
def para(s):  return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt(s)}}
def h2(s):    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": rt(s)}}
def h3(s):    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": rt(s)}}
def boldp(s): return {"object": "block", "type": "paragraph",
                      "paragraph": {"rich_text": [{"type": "text", "text": {"content": s},
                                                   "annotations": {"bold": True}}]}}
def code(s):  return {"object": "block", "type": "code", "code": {"rich_text": rt(s), "language": "plain text"}}
def callout(s): return {"object": "block", "type": "callout",
                        "callout": {"rich_text": rt(s), "icon": {"emoji": "📘"}}}
def toggle(s):  return {"object": "block", "type": "toggle", "toggle": {"rich_text": rt(s)}}
def img_block(iid):
    return {"object": "block", "type": "image",
            "image": {"type": "external", "external": {"url": E.img_url(iid)}}}

def emit_text(out, s):
    idx = 0
    for m in E.IMG_RE.finditer(s):
        pre = E.strip_tags(s[idx:m.start()])
        if pre: out.append(para(pre))
        out.append(img_block(m.group(1)))
        idx = m.end()
    tail = E.strip_tags(s[idx:])
    if tail: out.append(para(tail))

# ── 문서 → 블록 (인용 📎 토글 부착) ──────────────────────────────────────────
def blocks_for(doc, idx, cite):
    blk = [callout(f"{doc.get('kind','')} · 시행 {E.fmt_date(doc.get('date',''))} · 전문(단독) · 인용은 📎 토글 · 자동 생성")]
    bodies = []
    def emit_body(s):
        if "<img" in s:
            emit_text(blk, s); return
        if E.is_box(s):
            blk.append(code(s)); return
        text = E.strip_tags(s)
        if not idx or not cite:
            if text: blk.append(para(text))
            return
        last, matched = 0, False
        for m in cite.finditer(text):
            matched = True
            seg = text[last:m.end()]
            if seg.strip(): blk.append(para(seg))
            last = m.end()
            role = E._role_of(m)
            for (jo, gaji, hang, ho) in E.parse_targets(m.group("body")):
                label, lines = E.resolve(idx, role, jo, gaji, hang, ho)
                blk.append(toggle("📎 " + label))
                bodies.append([para(x) for x in lines] or [para("(원문 참조)")])
        if not matched:
            if text: blk.append(para(text))
        else:
            tail = text[last:]
            if tail.strip(): blk.append(para(tail))
    if "units" in doc:                       # 법령(조문단위) — 호·목 포함(render_units 기준)
        for header, lines in E.render_units(doc["units"]):
            if header.startswith("§ "):
                blk.append(h3(header[2:])); continue
            blk.append(h3(header))
            for ln in lines:
                if ln.strip(): emit_body(ln)
    else:                                    # 행정규칙(조문내용 문자열)
        ref = lambda t: any(r in t for r in ("참조", "준용", "」", "의 규정", "에 따라", "를 준용"))
        for ln in E.split_guide(doc["body"]):
            if not ln: continue
            if   ln.startswith("§편 "): t = E.strip_tags(ln[3:]); blk.append(para(t) if ref(t) else h2(t))
            elif ln.startswith("§장 "): t = E.strip_tags(ln[3:]); blk.append(para(t) if ref(t) else h3(t))
            elif ln.startswith("§절 "): t = E.strip_tags(ln[3:]); blk.append(para(t) if ref(t) else boldp(t))
            else:                       emit_body(ln)
    return blk, bodies

def children(token, bid):
    out, cur = [], None
    while True:
        d = napi(token, "GET", f"/blocks/{bid}/children?page_size=100" + (f"&start_cursor={cur}" if cur else ""))
        out += d.get("results", [])
        if not d.get("has_more"): break
        cur = d["next_cursor"]
    return out

def append(token, bid, blocks):
    out = []
    for i in range(0, len(blocks), 100):
        r = napi(token, "PATCH", f"/blocks/{bid}/children", {"children": blocks[i:i+100]})
        if r: out += r.get("results", [])
    return out

def archive_same(token, parent, title):
    for ch in children(token, parent):
        if ch.get("type") == "child_page" and ch["child_page"]["title"] == title:
            napi(token, "PATCH", f"/pages/{ch['id']}", {"archived": True})

def normalize_parent_id(s):
    """노션 페이지 URL 또는 32자리 id → 대시 포함 UUID."""
    s = (s or "").strip()
    m = re.search(r"([0-9a-fA-F]{32})", s.replace("-", ""))
    if not m: raise ValueError("노션 페이지 URL 또는 ID를 확인하세요.")
    h = m.group(1).lower()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

def push_one(token, name, kind, parent, mother, log=print):
    """한 문서를 parent 아래 새 페이지로 푸시. mother=인용 해석 기준 모법."""
    parent = normalize_parent_id(parent)
    log(f"■ {name} 수집…")
    doc = E.fetch_admrul(name) if kind == "admrul" else E.fetch_law_units(name)
    if not doc:
        log(f"  !! 법제처에서 못 찾음: {name}"); return None
    idx = E.get_index(mother) if mother else None
    cite = E.get_cite(mother) if mother else None
    title = doc["name"]
    archive_same(token, parent, title)
    page = napi(token, "POST", "/pages", {"parent": {"page_id": parent},
                                          "properties": {"title": [{"text": {"content": title}}]}})
    blocks, bodies = blocks_for(doc, idx, cite)
    made = append(token, page["id"], blocks)
    toggles = [b for b in made if b.get("type") == "toggle"]
    for tg, body in zip(toggles, bodies):
        if body: append(token, tg["id"], body)
    url = "https://www.notion.so/" + page["id"].replace("-", "")
    log(f"  완료({len(blocks)}블록, 인용 {len(toggles)}건) → {url}")
    return url
