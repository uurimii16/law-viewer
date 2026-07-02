#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""streamlit_app.py — 법제처 API 기반 '필요법 조합 뷰어'.

- 최대 3개까지 법 선택(고정 4법+지침4 + 검색으로 아무 법 추가).
- 한 법만 고르면 '3단(법·시행령·시행규칙) 비교' 보기 가능.
- 인용 표기/색상/배치 옵션을 골라 PDF·HTML로 추출하거나, 각자 자기 노션으로 푸시.
- ⚠️ 이 앱은 AI를 안 씀 → AI 토큰 소모 0. 노션 토큰은 이용자 각자의 것.
"""
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
def c_sections(name, kind, mother, inc):  return E.doc_sections(name, kind, mother, inc)

def mother_of(name):
    for gname, kind, mo in E.GUIDES:
        if E.norm(gname) == E.norm(name): return mo, kind
    return name, "law"

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

# ── 표시 옵션 ────────────────────────────────────────────────────────────────
st.sidebar.divider()
st.sidebar.subheader("⚙️ 표시·추출 옵션")
show_cites = st.sidebar.checkbox("타법·인용 조문 표기(📎)", value=True)
COLORS = {"파랑": "#2E5AAC", "먹색": "#222222", "진회색": "#444B54", "고동": "#7A3B2E", "숲색": "#2F6B4F"}
color = COLORS[st.sidebar.selectbox("제목 색상", list(COLORS), index=0)]
layout = st.sidebar.radio("배치", ["기본", "조밀"], horizontal=True)
show_3dan = False
if len(picked) == 1:
    show_3dan = st.sidebar.checkbox("3단(법·시행령·시행규칙) 비교로 보기")

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
        for label, body in E.line_cites(ln, idx, cite):
            with st.expander("📎 " + label):
                for x in body: st.write(x)

def render_col(cell, mother):
    if not cell:
        st.caption("—"); return
    header, lines = cell
    st.markdown(f"**{header}**")
    render_lines(lines, mother)

# ── 메인 ─────────────────────────────────────────────────────────────────────
st.markdown(f"### 선택한 법령 ({len(picked)}/{MAX_PICK})")
if not picked:
    st.info("왼쪽에서 볼 법령을 선택하세요 (최대 3개).")
elif show_3dan:                                  # 3단 비교 (한 법 선택 시)
    name = picked[0]
    mother, _ = mother_of(name)
    with st.spinner(f"{name} 3단 구성 중…"):
        t = c_3dan(name)
    st.subheader(f"{t['name']} — 3단 비교")
    st.caption("법 · 시행령 · 시행규칙을 조번호 기준으로 나란히(대응은 참고용). 없는 단은 '—'.")
    c1, c2, c3 = st.columns(3)
    for c, role in ((c1, "법"), (c2, "영"), (c3, "규칙")):
        c.markdown({"법": "**📘 법률**", "영": "**📗 시행령**", "규칙": "**📙 시행규칙**"}[role])
    for row in t["rows"]:
        if kw and not any(kw in (E._s(c[1]) if (c := row[r]) else "") for r in ("법", "영", "규칙")):
            continue
        c1, c2, c3 = st.columns(3)
        with c1: render_col(row["법"], mother)
        with c2: render_col(row["영"], mother)
        with c3: render_col(row["규칙"], mother)
        st.divider()
else:                                            # 탭 뷰
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

# ── 내보내기 ─────────────────────────────────────────────────────────────────
st.divider()
st.subheader("📥 내보내기 (선택한 법령 전체)")
if picked:
    @st.cache_data(show_spinner=False)
    def _sections(names, inc):
        out = []
        for nm in names:
            mo, kd = mother_of(nm)
            out.append(E.doc_sections(nm, kd, (mo if mo != nm else nm), inc))
        return out
    with st.spinner("문서 구성 중…"):
        secs = _sections(tuple(picked), show_cites)
    fname = "법령조합_" + "_".join(E.norm(p)[:8] for p in picked)
    cc1, cc2 = st.columns(2)
    with cc1:
        st.download_button("📄 HTML 내려받기", data=X.build_html(secs, options).encode("utf-8"),
                           file_name=fname + ".html", mime="text/html", use_container_width=True)
        st.caption("브라우저에서 열어 '인쇄 → PDF로 저장'도 가능")
    with cc2:
        try:
            st.download_button("📕 PDF 내려받기", data=X.build_pdf(secs, options),
                               file_name=fname + ".pdf", mime="application/pdf", use_container_width=True)
        except Exception as e:
            st.error(f"PDF 생성 실패: {e}")

# ── 노션 푸시 (이용자별) ─────────────────────────────────────────────────────
with st.expander("📤 선택한 법령을 '내 노션'으로 푸시하기"):
    st.markdown(
        "1. 노션 [Integration](https://www.notion.so/my-integrations) 만들고 토큰(`ntn_...`) 발급\n"
        "2. 푸시할 **부모 페이지** → `...` → **연결 추가**로 그 Integration 연결\n"
        "3. 아래에 토큰과 그 페이지 주소 붙여넣기")
    tok = st.text_input("노션 토큰", type="password", placeholder="ntn_...")
    parent = st.text_input("부모 페이지 URL 또는 ID", placeholder="https://www.notion.so/....")
    st.caption("⚠️ 토큰은 서버에 저장하지 않습니다(이 요청에만 사용). 각자 자기 노션에만 씁니다.")
    if st.button("이 목록을 내 노션으로 푸시", type="primary", disabled=not (tok and parent and picked)):
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
