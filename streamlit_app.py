#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""streamlit_app.py — 법제처 API 기반 '필요법 조합 뷰어'.

- 최대 3개까지 법 선택(고정 4법+지침4 + 검색으로 아무 법 추가).
- 한 법만 고르면 '3단(법·시행령·시행규칙) 비교' 보기 가능.
- 인용 표기/색상/배치 옵션을 골라 PDF·HTML로 추출하거나, 각자 자기 노션으로 푸시.
- ⚠️ 이 앱은 AI를 안 씀 → AI 토큰 소모 0. 노션 토큰은 이용자 각자의 것.
"""
import re
import streamlit as st
import law_engine as E
import notion_sink as N
import exporters as X

st.set_page_config(page_title="법령 조합 뷰어", page_icon="⚖️", layout="wide")
MAX_PICK = 3

# ── 캐시 래퍼 ────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=6 * 3600)
def c_law(name):      return E.fetch_law_units(name)
@st.cache_data(show_spinner=False, ttl=6 * 3600)
def c_admrul(name):   return E.fetch_admrul(name)
@st.cache_data(show_spinner=False, ttl=6 * 3600)
def c_search(q):      return E.search_law(q)
@st.cache_data(show_spinner=False, ttl=6 * 3600)
def c_index(mother):  return E.get_index(mother)
@st.cache_data(show_spinner=False, ttl=6 * 3600)
def c_3dan(name):     return E.three_column(name)
@st.cache_data(show_spinner=False, ttl=6 * 3600)
def c_deleg(mother):  return E.build_delegation(mother)
@st.cache_data(show_spinner=False, ttl=6 * 3600)
def c_ext(lawname, body):  return E.resolve_external(lawname, body)
@st.cache_data(show_spinner=False, ttl=6 * 3600)
def c_sections(name, kind, mother, inc):  return E.doc_sections(name, kind, mother, inc)

def mother_of(name):
    for gname, kind, mo in E.GUIDES:
        if E.norm(gname) == E.norm(name): return mo, kind
    return name, "law"

@st.cache_data(show_spinner=False)
def _secs(names, inc):
    out = []
    for nm in names:
        mo, kd = mother_of(nm)
        out.append(E.doc_sections(nm, kd, (mo if mo != nm else nm), inc))
    return out

@st.cache_data(show_spinner=False)
def _html_bytes(names, inc, color, layout):
    return X.build_html(_secs(names, inc),
                        {"include_cites": inc, "color": color, "layout": layout}).encode("utf-8")

# ── 세션 상태 ────────────────────────────────────────────────────────────────
if "picked" not in st.session_state:
    st.session_state.picked = list(E.CORE_LAWS[:1])

def toggle_pick(nm):
    p = st.session_state.picked
    if nm in p: p.remove(nm)
    elif len(p) < MAX_PICK: p.append(nm)
    else: st.session_state._warn = True

# ── 사이드바 ─────────────────────────────────────────────────────────────────
st.sidebar.title("⚖️ 법령 조합")
st.sidebar.caption(f"법제처 OPEN API 실시간 · 최대 {MAX_PICK}개")
if st.session_state.pop("_warn", False):
    st.sidebar.warning(f"최대 {MAX_PICK}개까지만 선택할 수 있어요.")

st.sidebar.subheader("기본 법령")
for nm in E.CORE_LAWS + [g[0] for g in E.GUIDES]:
    st.sidebar.checkbox(nm, value=(nm in st.session_state.picked),
                        key="chk_" + nm, on_change=toggle_pick, args=(nm,))

st.sidebar.divider()
st.sidebar.subheader("🔎 다른 법 검색·추가")
q = st.sidebar.text_input("법령명 검색", placeholder="예: 건축법")
if q:
    try:
        for r in c_search(q)[:10]:
            st.sidebar.button(f"➕ {r['name']}", key="add_" + str(r["mst"]),
                              on_click=toggle_pick, args=(r["name"],))
    except Exception as e:
        st.sidebar.error(f"검색 실패: {e}")

st.sidebar.divider()
if st.sidebar.button("🔄 최신으로 새로고침"):
    st.cache_data.clear(); E._IDX.clear(); E._MC = None
    st.rerun()

picked = st.session_state.picked

# ── 보기 방식 / 표시 옵션 ────────────────────────────────────────────────────
st.sidebar.divider()
st.sidebar.subheader("🖥️ 보기 방식")
MODES = ["탭 보기 (여러 법)", "3단 비교 (조번호 기준)",
         "위임 3단 (법↔시행령·규칙)", "호 단위 관련조문"]
mode = st.sidebar.radio("모드", MODES, index=0,
                        help="아래 3개는 법을 1개만 선택했을 때 동작합니다(그 법의 법·시행령·시행규칙 세트).")

st.sidebar.subheader("⚙️ 표시·추출 옵션")
show_cites = st.sidebar.checkbox("자기 법령 인용 펼침(📎)", value=True,
                                 help="본문 속 '법/영/규칙 제N조'를 그 자리에서 펼쳐 봅니다.")
show_ext = st.sidebar.checkbox("타법 인용 펼침(📖·느림)", value=False,
                               help="「산지관리법」 제6조… 처럼 다른 법 인용을 법제처에서 가져와 아래에 붙입니다.")
COLORS = {"파랑": "#2E5AAC", "먹색": "#222222", "진회색": "#444B54", "고동": "#7A3B2E", "숲색": "#2F6B4F"}
color = COLORS[st.sidebar.selectbox("제목 색상", list(COLORS), index=0)]
layout = st.sidebar.radio("배치", ["기본", "조밀"], horizontal=True)

kw = st.text_input("본문 검색(키워드)", placeholder="조문 안 단어로 필터 · 비우면 전체")
options = {"include_cites": show_cites, "color": color, "layout": layout}

# ── 렌더 헬퍼 ────────────────────────────────────────────────────────────────
def render_lines(lines, mother):
    idx = c_index(mother) if (show_cites and mother) else None
    cite = E.get_cite(mother) if (show_cites and mother) else None
    for ln in lines:
        if not ln.strip(): continue
        if kw and kw not in ln: continue
        st.markdown(f"<div style='margin:.1em 0'>{ln.replace('<','&lt;')}</div>", unsafe_allow_html=True)
        if show_cites:
            for label, body in E.line_cites(ln, idx, cite):
                with st.expander("📎 " + label):
                    for x in body: st.write(x)
        if show_ext:
            for lname, body in E.external_cites_in_line(ln):
                try:
                    for label, blines in c_ext(lname, body):
                        with st.expander("📖 " + label):
                            for x in blines: st.write(x)
                except Exception:
                    pass

def render_related(cell):
    """위임/호 단위에서 붙는 시행령·규칙 조문을 접이식으로."""
    if not cell:
        st.caption("— (관련 시행령·규칙 없음)"); return
    for role, mark in (("영", "📗 시행령"), ("규칙", "📙 시행규칙")):
        for header, lines in cell.get(role, []):
            with st.expander(f"{mark} · {header}", expanded=False):
                for ln in lines:
                    if ln.strip():
                        st.markdown(ln.replace("<", "&lt;"))

# ── 메인 ─────────────────────────────────────────────────────────────────────
st.markdown(f"### 선택한 법령 ({len(picked)}/{MAX_PICK})")
single = (len(picked) == 1)

def view_tabs():
    tabs = st.tabs(picked)
    for tab, name in zip(tabs, picked):
        with tab:
            mother, kind = mother_of(name)
            with st.spinner(f"{name} 불러오는 중…"):
                doc = c_admrul(name) if kind == "admrul" else c_law(name)
            if not doc:
                st.error("법제처에서 못 찾았습니다."); continue
            st.subheader(doc["name"])
            st.caption(f"시행 {E.fmt_date(doc.get('date',''))} · {doc.get('kind','')}"
                       + (f" · 인용 모법: {mother}" if mother != name else ""))
            if "units" in doc:
                for header, lines in E.render_units(doc["units"]):
                    if header.startswith("§ "):
                        st.markdown(f"### {header[2:]}"); continue
                    st.markdown(f"**{header}**")
                    render_lines(lines, mother)
            else:
                render_lines(E.split_guide(doc["body"]), mother)

def view_3dan_jono(name):
    mother, _ = mother_of(name)
    with st.spinner(f"{name} 3단 구성 중…"):
        t = c_3dan(name)
    st.subheader(f"{t['name']} — 3단 비교 (조번호 기준)")
    st.caption("법·시행령·시행규칙을 조번호로 나란히(대응은 참고용). 없는 단은 '—'.")
    c1, c2, c3 = st.columns(3)
    for c, m in ((c1, "**📘 법률**"), (c2, "**📗 시행령**"), (c3, "**📙 시행규칙**")): c.markdown(m)
    for row in t["rows"]:
        if kw and not any(kw in (E._s(c[1]) if (c := row[r]) else "") for r in ("법", "영", "규칙")):
            continue
        cols = st.columns(3)
        for col, r in zip(cols, ("법", "영", "규칙")):
            with col:
                cell = row[r]
                if cell:
                    st.markdown(f"**{cell[0]}**"); render_lines(cell[1], mother)
                else:
                    st.caption("—")
        st.divider()

def view_delegation(name):
    mother, _ = mother_of(name)
    with st.spinner(f"{name} 위임관계 분석 중…"):
        d = c_deleg(mother)
    st.subheader(f"{d['law']['name']} — 위임 3단")
    st.caption("각 법 조문 옆에, 그 조를 '법 제N조…에 따라' 위임받은 시행령·시행규칙을 붙였습니다.")
    for header, lines in E.render_units(d["law"]["units"]):
        if header.startswith("§ "):
            st.markdown(f"### {header[2:]}"); continue
        mm = re.match(r"제(\d+)조(?:의(\d+))?", header)
        key = (int(mm.group(1)), int(mm.group(2) or 0)) if mm else None
        if kw and kw not in header and not any(kw in x for x in lines):
            cell0 = d["by_jo"].get(key, {})
            if not any(kw in h for role in ("영", "규칙") for h, _ in cell0.get(role, [])):
                continue
        cL, cR = st.columns([3, 2])
        with cL:
            st.markdown(f"**{header}**"); render_lines(lines, mother)
        with cR:
            render_related(d["by_jo"].get(key, {}))
        st.divider()

def view_ho(name):
    mother, _ = mother_of(name)
    with st.spinner(f"{name} 호 단위 분석 중…"):
        d = c_deleg(mother)
    st.subheader(f"{d['law']['name']} — 호 단위 관련조문")
    st.caption("각 호(예: 13. 공공시설) 아래에 그 호를 구체화한 시행령·규칙을 붙였습니다.")
    struct = E.law_units_structured(d["law"]["units"])
    for s in struct:
        if kw and kw not in s["header"] and kw not in s["head"] \
           and not any(kw in ho["text"] for h in s["항"] for ho in h["호"]) \
           and not any(kw in ho["text"] for ho in s["호"]):
            continue
        esc = lambda t: (t or "").replace("<", "&lt;")
        st.markdown(f"**{s['header']}**")
        if s["head"]: st.markdown(esc(s["head"]))
        def show_ho(hang_M, ho):
            if not ho.get("K"): return
            st.markdown(f"&nbsp;&nbsp;**{ho['K']}.** {esc(ho['text'])}", unsafe_allow_html=True)
            cell = d["by_ho"].get((s["jo"], s["gaji"], hang_M, ho["K"])) \
                or d["by_ho"].get((s["jo"], s["gaji"], None, ho["K"]))
            if cell: render_related(cell)
        for hang in s["항"]:
            if hang["text"]: st.markdown(esc(hang["text"]))
            for ho in hang["호"]: show_ho(hang["M"], ho)
        for ho in s["호"]:
            show_ho(None, ho)
        st.divider()

if not picked:
    st.info("왼쪽에서 볼 법령을 선택하세요 (최대 3개).")
elif mode == MODES[0]:
    view_tabs()
elif not single:
    st.warning("이 보기는 법을 **1개만** 선택했을 때 동작해요. 지금은 '탭 보기'로 보여드릴게요.")
    view_tabs()
elif mode == MODES[1]:
    view_3dan_jono(picked[0])
elif mode == MODES[2]:
    view_delegation(picked[0])
else:
    view_ho(picked[0])

# ── 사이드바: 내보내기 / 노션 (항상 보이게) ──────────────────────────────────
st.sidebar.divider()
st.sidebar.subheader("📥 내보내기 · 노션 푸시")
if not picked:
    st.sidebar.caption("먼저 볼 법을 선택하세요.")
else:
    fname = "법령조합_" + "_".join(E.norm(p)[:8] for p in picked)
    st.sidebar.download_button(
        "📄 HTML 내려받기",
        data=_html_bytes(tuple(picked), show_cites, color, layout),
        file_name=fname + ".html", mime="text/html", use_container_width=True)
    st.sidebar.caption("HTML은 한글(HWP)·Word로도 열려요. 브라우저 '인쇄 → PDF 저장'도 가능.")

    if st.sidebar.button("📕 PDF 만들기", use_container_width=True):
        try:
            with st.spinner("PDF 생성 중… (양이 많으면 조금 걸려요)"):
                st.session_state._pdf = X.build_pdf(
                    _secs(tuple(picked), show_cites),
                    {"include_cites": show_cites, "color": color, "layout": layout})
                st.session_state._pdfname = fname + ".pdf"
        except Exception as e:
            st.session_state._pdf = None
            st.sidebar.error(f"PDF 생성 실패: {e}")
    if st.session_state.get("_pdf"):
        st.sidebar.download_button(
            "⬇️ PDF 저장", data=st.session_state._pdf,
            file_name=st.session_state.get("_pdfname", "법령.pdf"),
            mime="application/pdf", use_container_width=True)

    with st.sidebar.expander("📤 내 노션으로 푸시"):
        st.markdown(
            "1. 노션 [Integration](https://www.notion.so/my-integrations) 만들고 토큰(`ntn_...`) 발급\n"
            "2. 푸시할 **부모 페이지** → `...` → **연결 추가**로 그 Integration 연결\n"
            "3. 아래에 토큰·페이지 주소 붙여넣기")
        tok = st.text_input("노션 토큰", type="password", placeholder="ntn_...")
        parent = st.text_input("부모 페이지 URL 또는 ID", placeholder="https://www.notion.so/....")
        st.caption("⚠️ 토큰은 저장 안 함(이 요청에만). 각자 자기 노션에만 씁니다.")
        if st.button("내 노션으로 푸시", type="primary", disabled=not (tok and parent)):
            logbox = st.empty(); logs = []
            def log(m): logs.append(m); logbox.code("\n".join(logs))
            ok = 0
            for name in picked:
                mo, kd = mother_of(name)
                try:
                    if N.push_one(tok, name, kd, parent, (mo if mo != name else name), log=log):
                        ok += 1
                except Exception as e:
                    log(f"  !! 실패({name}): {e}")
            (st.success if ok else st.error)(f"완료: {ok}/{len(picked)}건 푸시")
