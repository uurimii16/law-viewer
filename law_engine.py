#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""law_engine.py — 법제처 OPEN API 호출 + 인용(법/영/규칙 제N조) 해석 엔진.

D:\\노션재푸시\\push_guides.py 에서 '노션과 무관한' 부분만 뽑아 재사용.
노션/스트림릿 의존성 0 — 순수 표준 라이브러리(urllib/re/json)만 쓴다.

CLI(회귀 확인용):
    python law_engine.py --dry "도시·군관리계획수립지침"
    → push_guides.py --dry 와 같은 인용 해석 결과가 나오는지 대조.
"""
import os, re, sys, json, time, urllib.request, urllib.parse

OC   = "uurimii16"                       # 법제처 공동활용 인증(OC=이메일 아이디)
DRF  = "https://www.law.go.kr/DRF"

HERE   = os.path.dirname(os.path.abspath(__file__))
MCACHE = os.path.join(HERE, "out", "mother_cache.json")   # 모법(법/영/규칙) 조문 캐시

# 지침/규칙 → 모법 매핑 (push_guides.py의 GUIDES 그대로).
# (검색어, 종류 law|admrul, 모법명)
GUIDES = [
    ("도시·군관리계획수립지침",                              "admrul", "국토의 계획 및 이용에 관한 법률"),
    ("도시ㆍ군계획시설의 결정ㆍ구조 및 설치기준에 관한 규칙", "law",    "국토의 계획 및 이용에 관한 법률"),
    ("지역·지구등의 지형도면 작성에 관한 지침",              "admrul", "토지이용규제 기본법"),
    ("도시·주거환경정비기본계획 수립 지침",                  "admrul", "도시 및 주거환경정비법"),
]

# 고정으로 항상 띄우는 4개 모법(법률).
CORE_LAWS = [
    "국토의 계획 및 이용에 관한 법률",
    "토지이용규제 기본법",
    "도시 및 주거환경정비법",
    "도시재생 활성화 및 지원에 관한 특별법",
]

_BOX = "─━│┃┌┐└┘├┤┬┴┼┏┓┗┛┠┣┫┯┷╋═║"
def is_box(t): return any(c in t for c in _BOX)

# ── 법제처 ────────────────────────────────────────────────────────────────
def drf(ep, **p):
    p = {"OC": OC, "type": "JSON", **p}
    u = f"{DRF}/{ep}?" + urllib.parse.urlencode(p)
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    for i in range(3):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=40).read().decode("utf-8"))
        except Exception:
            if i == 2: raise
            time.sleep(1.0 * (i + 1))

def as_list(x): return [] if x is None else (x if isinstance(x, list) else [x])
def norm(s): return (s or "").replace(" ", "").replace("ㆍ", "·")

def _s(x):
    if x is None: return ""
    if isinstance(x, list): return "\n".join(_s(i) for i in x)
    return str(x)

CIRC = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
def _circ(c):  c = _s(c).strip(); return CIRC.index(c[0]) + 1 if c and c[0] in CIRC else None
def _honum(s): d = re.sub(r"\D", "", _s(s)); return int(d) if d else None

def fmt_date(s):
    s = _s(s)
    return f"{s[:4]}.{s[4:6]}.{s[6:]}" if len(s) == 8 else s

# 본문 속 <img id="..."> → 법제처 이미지 URL
IMG_RE = re.compile(r'<img[^>]*?id="(\d+)"[^>]*?>(?:\s*</img>)?')
def img_url(iid): return f"https://www.law.go.kr/LSW/flDownload.do?flSeq={iid}"
def strip_tags(s): return re.sub(r"<[^>]+>", "", _s(s)).strip()

# ── 검색 / 본문 가져오기 ─────────────────────────────────────────────────────
def search_law(query, display=20):
    """법령명 검색 → [{name, mst, date}]."""
    d = drf("lawSearch.do", target="law", query=query, display=str(display))
    return [{"name": it.get("법령명한글"), "mst": it.get("법령일련번호"),
             "date": str(it.get("시행일자", ""))}
            for it in as_list(d.get("LawSearch", {}).get("law"))]

def search_admrul(query, display=20):
    d = drf("lawSearch.do", target="admrul", query=query, display=str(display))
    return [{"name": it.get("행정규칙명"), "id": it.get("행정규칙일련번호"),
             "date": str(it.get("시행일자", ""))}
            for it in as_list(d.get("AdmRulSearch", {}).get("admrul"))]

def fetch_admrul(name):
    d = drf("lawSearch.do", target="admrul", query=name, display="10")
    items = as_list(d.get("AdmRulSearch", {}).get("admrul"))
    hit = next((it for it in items if norm(it.get("행정규칙명")) == norm(name)), None) or (items[0] if items else None)
    if not hit: return None
    root = drf("lawService.do", target="admrul", ID=hit["행정규칙일련번호"]).get("AdmRulService", {})
    info = root.get("행정규칙기본정보", {})
    body = _s(root.get("조문내용", "")) or ""
    return {"name": info.get("행정규칙명", name), "date": _s(info.get("시행일자", "")),
            "kind": info.get("행정규칙종류", "행정규칙"), "body": body}

def fetch_law_units(name):
    """법령명(법률/시행령/시행규칙/규칙) → {name, date, kind, units[]}."""
    d = drf("lawSearch.do", target="law", query=name, display="20")
    items = as_list(d.get("LawSearch", {}).get("law"))
    hit = next((it for it in items if norm(it.get("법령명한글")) == norm(name)),
               items[0] if items else None)
    if not hit: return None
    root = drf("lawService.do", target="law", MST=hit["법령일련번호"]).get("법령", {})
    basic = root.get("기본정보", {})
    kind = basic.get("법종구분")
    kind = kind.get("content", "") if isinstance(kind, dict) else _s(kind)
    units = as_list(root.get("조문", {}).get("조문단위"))
    return {"name": basic.get("법령명_한글") or hit.get("법령명한글", name),
            "date": _s(basic.get("시행일자", "")), "kind": kind or "법령", "units": units}

# 검색결과 로딩용: 모법 인덱스 빌드에도 재사용
def fetch_units(law_name):
    doc = fetch_law_units(law_name)
    return doc["units"] if doc else []

# ── 모법 인용 인덱스 ─────────────────────────────────────────────────────────
def _build_role_index(units):
    """조문단위 → {(조int,가지int): {title, head, full[], 항{M:{text,호{K},lines[]}}, 호_flat{K}}}."""
    idx = {}
    for u in as_list(units):
        if u.get("조문여부") == "전문": continue
        jo = _honum(u.get("조문번호"))
        if not jo: continue
        gaji = _honum(u.get("조문가지번호")) or 0
        head = _s(u.get("조문내용")).strip()
        parts = [head] if head else []
        hang_map, ho_flat, order = {}, {}, 0
        for h in as_list(u.get("항")):
            order += 1
            M = _circ(h.get("항번호")) or order
            htxt = _s(h.get("항내용")).strip()
            holines = []
            hos = {}
            for ho in as_list(h.get("호")):
                K = _honum(ho.get("호번호")); txt = _s(ho.get("호내용")).strip()
                if K: hos[K] = txt; ho_flat[K] = txt
                if txt: holines.append("  " + txt)
                for mok in as_list(ho.get("목")):
                    mt = _s(mok.get("목내용")).strip()
                    if mt: holines.append("    " + mt)
            hang_map[M] = {"text": htxt, "호": hos,
                           "lines": ([htxt] if htxt else []) + holines}
            if htxt: parts.append(htxt)
            parts += holines
        idx[(jo, gaji)] = {"title": _s(u.get("조문제목")), "head": head,
                           "full": [p for p in parts if p], "항": hang_map, "호_flat": ho_flat}
    return idx

_MC = None
def _units_cached(law_name, role, mother):
    global _MC
    if _MC is None:
        try:    _MC = json.load(open(MCACHE, encoding="utf-8"))
        except Exception: _MC = {}
    key = f"{mother}|{role}"
    if key not in _MC:
        _MC[key] = fetch_units(law_name)
        try:
            os.makedirs(os.path.dirname(MCACHE), exist_ok=True)
            json.dump(_MC, open(MCACHE, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception: pass
    return _MC[key]

_IDX = {}
def get_index(mother):
    """모법명 → {role('법'/'영'/'규칙'): role_index}. 메모이즈 + 캐시."""
    if mother in _IDX: return _IDX[mother]
    roles = {"법": mother, "영": mother + " 시행령", "규칙": mother + " 시행규칙"}
    built = {}
    for role, lawname in roles.items():
        try:    built[role] = _build_role_index(_units_cached(lawname, role, mother))
        except Exception: built[role] = {}
    _IDX[mother] = built
    return built

# ── 인용 탐지·전개 ───────────────────────────────────────────────────────────
CITE_CFG = {
    "국토의 계획 및 이용에 관한 법률": r"(?:같은\s*법|법)",
    "토지이용규제 기본법":            r"(?:같은\s*법|기본법|법)",
    "도시 및 주거환경정비법":          r"(?:같은\s*법|법)",
    "도시재생 활성화 및 지원에 관한 특별법": r"(?:같은\s*법|법)",
}
_SEG = r'제\s*\d+\s*조(?:\s*의\s*\d+)?|제\s*\d+\s*항|제\s*\d+\s*호|부터|까지'
_SEP = r'(?:\s*(?:및|과|와|또는|이상|[,ㆍ·])\s*|\s+)'

def make_cite(mother):
    law = CITE_CFG.get(mother, r"(?:같은\s*법|법)")
    return re.compile(
        r'(?<![가-힣])(?:'
        r'(?P<law>' + law + r')\s*(?P<sub>시행령|시행규칙)?'
        r'|(?P<bare>시행규칙|시행령|규칙|영)'
        r')\s*'
        r'(?P<body>제\s*\d+\s*조(?:\s*의\s*\d+)?(?:' + _SEP + r'?(?:' + _SEG + r'))*)')

TOK = re.compile(r'제\s*(\d+)\s*조(?:\s*의\s*(\d+))?|제\s*(\d+)\s*항|제\s*(\d+)\s*호|(부터)|(까지)')

def parse_targets(body):
    toks = []
    for m in TOK.finditer(body or ""):
        if   m.group(1): toks.append(("JO", int(m.group(1)), int(m.group(2)) if m.group(2) else 0))
        elif m.group(3): toks.append(("HANG", int(m.group(3))))
        elif m.group(4): toks.append(("HO", int(m.group(4))))
        elif m.group(5): toks.append(("BUTEO",))
        elif m.group(6): toks.append(("KKAJI",))
    out = []
    cur_jo = cur_gaji = cur_hang = None
    pend_jo = pend_hang = False
    def _rng(a, b): return [a, b] if b - a > 20 else list(range(a, b + 1))
    def _eat_kkaji(i): return i + 1 if i < len(toks) and toks[i][0] == "KKAJI" else i
    def close_hang():
        nonlocal pend_hang
        if pend_hang: out.append((cur_jo, cur_gaji, cur_hang, None))
        pend_hang = False
    def close_jo():
        nonlocal pend_jo
        if pend_jo and cur_jo is not None: out.append((cur_jo, cur_gaji, None, None))
        pend_jo = False
    i = 0
    while i < len(toks):
        t = toks[i]
        if t[0] in ("BUTEO", "KKAJI"): i += 1; continue
        rng = (i + 2 < len(toks) and toks[i + 1][0] == "BUTEO" and toks[i + 2][0] == t[0])
        if t[0] == "JO":
            close_hang(); close_jo()
            if rng:
                for j in _rng(t[1], toks[i + 2][1]): out.append((j, 0, None, None))
                cur_jo, cur_gaji, cur_hang = toks[i + 2][1], toks[i + 2][2], None
                i = _eat_kkaji(i + 3); continue
            cur_jo, cur_gaji, cur_hang = t[1], t[2], None; pend_jo = True; i += 1; continue
        if t[0] == "HANG":
            pend_jo = False; close_hang()
            if rng:
                for h in _rng(t[1], toks[i + 2][1]): out.append((cur_jo, cur_gaji, h, None))
                cur_hang = toks[i + 2][1]; i = _eat_kkaji(i + 3); continue
            cur_hang = t[1]; pend_hang = True; i += 1; continue
        if t[0] == "HO":
            pend_jo = pend_hang = False
            if rng:
                for k in _rng(t[1], toks[i + 2][1]): out.append((cur_jo, cur_gaji, cur_hang, k))
                i = _eat_kkaji(i + 3); continue
            out.append((cur_jo, cur_gaji, cur_hang, t[1])); i += 1; continue
        i += 1
    close_hang(); close_jo()
    seen, res = set(), []
    for tg in out:
        if tg[0] is None or tg in seen: continue
        seen.add(tg); res.append(tg)
    return res

_CITE = {}
def get_cite(mother):
    if mother not in _CITE: _CITE[mother] = make_cite(mother)
    return _CITE[mother]

def _role_of(m):
    b = m.group("bare")
    if b: return "규칙" if "규칙" in b else "영"
    sub = m.group("sub")
    if sub == "시행규칙": return "규칙"
    if sub == "시행령":  return "영"
    return "법"

def _label(role, jo, gaji, hang, ho):
    s = f"{role} 제{jo}조"
    if gaji: s += f"의{gaji}"
    if hang: s += f"제{hang}항"
    if ho:   s += f"제{ho}호"
    return s

def resolve(idx, role, jo, gaji, hang, ho):
    """(label, [본문 줄들]) — 못 찾으면 안내문."""
    label = _label(role, jo, gaji, hang, ho)
    art = (idx.get(role) or {}).get((jo, gaji))
    if not art:
        return label, ["(해당 조문 없음 — 법제처 원문 참조)"]
    if hang:
        hg = art["항"].get(hang)
        if hg:
            if ho and ho in hg["호"]:
                return label, [x for x in ([hg["text"]] if hg["text"] else []) + [hg["호"][ho]] if x]
            return label, hg["lines"] or art["full"]
        return label, art["full"]
    if ho:
        if ho in art["호_flat"]:
            return label, [x for x in ([art["head"]] if art["head"] else []) + [art["호_flat"][ho]] if x]
        return label, art["full"]
    return label, art["full"]

def line_cites(text, idx, cite):
    """한 줄 text → [(label, [본문 줄들])]. UI에서 st.expander로 펼칠 인용 목록."""
    out = []
    if not idx or not cite or not text: return out
    for m in cite.finditer(text):
        role = _role_of(m)
        for (jo, gaji, hang, ho) in parse_targets(m.group("body")):
            out.append(resolve(idx, role, jo, gaji, hang, ho))
    return out

# ── 전문 → 읽기 좋은 줄 (push_guides.py 그대로) ──────────────────────────────
_HNEG = r"(?!\s*(?:참조|준용|」|\)))"
def split_guide(s):
    if not s: return []
    s = _s(s).replace("\r", "")
    s = re.sub(r"(?<!「)\s*(제\s*\d+\s*편)" + _HNEG, r"\n\n§편 \1", s)
    s = re.sub(r"(?<!「)\s*(제\s*\d+\s*장)" + _HNEG, r"\n\n§장 \1", s)
    s = re.sub(r"(?<!「)\s*(제\s*\d+\s*절)" + _HNEG, r"\n§절 \1", s)
    s = re.sub(r"(?<!「)\s*(제\s*\d+\s*관)" + _HNEG, r"\n§절 \1", s)
    s = re.sub(r"\s*((?:\d+-){1,}\d+\.)", r"\n\1 ", s)
    s = re.sub(r"\s*(\(\d+\))\s+(?=[가-힣「])", r"\n\1 ", s)
    s = re.sub(r"(?<![ㆍ·])([①-⑳])\s+(?=[^\sㆍ·및또])", r"\n\1 ", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return [ln.rstrip() for ln in s.split("\n")]

def split_article(txt):
    if not txt: return []
    s = re.sub(r"\s*<개정[^>]*>", "", _s(txt))
    s = re.sub(r"(?<![ㆍ·])([①-⑳])\s+(?=[^\sㆍ·및또])", r"\n\1 ", s)
    s = re.sub(r"(?<![0-9의])(\d+)\.\s+", r"\n\1. ", s)
    s = re.sub(r"(?<![가-힣])([가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허])\.\s", r"\n  \1. ", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return [ln.rstrip() for ln in s.split("\n") if ln.strip()]

# ── 법령(조문단위) → 화면용 순서 있는 조문 리스트 (호·목까지 포함: 옛 누락버그 회피) ──
def render_units(units):
    """units → [(조 헤더, [본문 줄들])]. 순서 보존, 항/호/목 모두 포함."""
    arts = []
    for u in as_list(units):
        if u.get("조문여부") == "전문":
            t = strip_tags(u.get("조문내용"))
            if t: arts.append(("§ " + t[:200], []))
            continue
        jo = _honum(u.get("조문번호"))
        if not jo: continue
        gaji = _honum(u.get("조문가지번호")) or 0
        title = _s(u.get("조문제목"))
        header = f"제{jo}조" + (f"의{gaji}" if gaji else "") + (f"({title})" if title else "")
        lines = []
        head = re.sub(r"^\s*제\s*\d+\s*조(?:의\d+)?\s*(\([^)]*\))?\s*", "", _s(u.get("조문내용")).strip())
        if head: lines.append(head)
        def _emit_ho(ho, indent="  "):
            k = _s(ho.get("호내용")).strip()
            if k: lines.append(indent + k)
            for mok in as_list(ho.get("목")):
                mt = _s(mok.get("목내용")).strip()
                if mt: lines.append(indent + "  " + mt)
        for hh in as_list(u.get("항")):
            ht = _s(hh.get("항내용")).strip()
            if ht: lines.append(ht)
            for ho in as_list(hh.get("호")): _emit_ho(ho)
        for ho in as_list(u.get("호")): _emit_ho(ho)   # 조 직속 호
        arts.append((header, lines))
    return arts

# ── 내보내기용 문서 모델 / 3단 ───────────────────────────────────────────────
def doc_sections(name, kind, mother, include_cites=True):
    """법령/지침 → {title, date, kind, articles:[{header, lines:[{text, cites}]}]}.
    cites = [(label, [본문줄]) …] (include_cites=False면 빈 리스트)."""
    doc = fetch_admrul(name) if kind == "admrul" else fetch_law_units(name)
    if not doc: return None
    idx = get_index(mother) if (include_cites and mother) else None
    cite = get_cite(mother) if (include_cites and mother) else None
    arts = []
    if "units" in doc:
        for header, lines in render_units(doc["units"]):
            if header.startswith("§ "):
                arts.append({"header": header[2:], "lines": []}); continue
            arts.append({"header": header,
                         "lines": [{"text": ln, "cites": line_cites(ln, idx, cite)} for ln in lines]})
    else:
        cur = {"header": None, "lines": []}
        arts = [cur]
        for ln in split_guide(doc["body"]):
            if not ln: continue
            if ln.startswith(("§편 ", "§장 ", "§절 ")):
                cur = {"header": strip_tags(ln[3:]), "lines": []}; arts.append(cur)
            else:
                t = strip_tags(ln)
                cur["lines"].append({"text": t, "cites": line_cites(t, idx, cite)})
    return {"title": doc["name"], "date": doc.get("date", ""), "kind": doc.get("kind", ""), "articles": arts}

def three_column(name):
    """법 이름 → {name, has{법,영,규칙}, rows:[{jo, 법:(헤더,줄들), 영:…, 규칙:…}]}.
    ⚠️ 조번호 기준 나란히(참고용) — 법/영/규칙 조번호가 의미상 1:1 대응은 아님."""
    def byjo(doc):
        m = {}
        if not doc: return m
        for header, lines in render_units(doc["units"]):
            mm = re.match(r"제(\d+)조(?:의(\d+))?", header)
            if not mm: continue
            m[(int(mm.group(1)), int(mm.group(2) or 0))] = (header, lines)
        return m
    law   = fetch_law_units(name)
    yeong = fetch_law_units(name + " 시행령")
    rule  = fetch_law_units(name + " 시행규칙")
    L, Y, R = byjo(law), byjo(yeong), byjo(rule)
    keys = sorted(set(L) | set(Y) | set(R))
    rows = []
    for k in keys:
        rows.append({"jo": f"제{k[0]}조" + (f"의{k[1]}" if k[1] else ""),
                     "법": L.get(k), "영": Y.get(k), "규칙": R.get(k)})
    return {"name": (law or {}).get("name", name),
            "has": {"법": bool(L), "영": bool(Y), "규칙": bool(R)}, "rows": rows}

# ── CLI: 인용 해석 오프라인 확인 (--dry) ─────────────────────────────────────
def _dry(name):
    entry = next((g for g in GUIDES if name in g[0]), None)
    if entry:
        _, kind, mother = entry
    else:
        kind, mother = "law", name        # 임의 법: 자기 자신이 모법
    print(f"■ {name}  (모법: {mother})")
    doc = fetch_admrul(name) if kind == "admrul" else fetch_law_units(name)
    if not doc: print("  !! 법제처에서 못 찾음", file=sys.stderr); return
    idx = get_index(mother); cite = get_cite(mother)
    if "units" in doc:
        text = "\n".join(_s(u.get("조문내용")) + "\n" +
                         "\n".join(_s(h.get("항내용")) for h in as_list(u.get("항")))
                         for u in doc["units"])
    else:
        text = doc.get("body") or ""
    seen = 0
    for (label, lines) in line_cites(text, idx, cite):
        print(f"   {label:20s} → {(lines[0] if lines else '')[:70]}")
        seen += 1
    print(f"   (인용 {seen}건)")

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry"]
    if not args:
        print("사용법: python law_engine.py --dry \"법령/지침 이름\"")
    else:
        _dry(args[0])
