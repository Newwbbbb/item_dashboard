# -*- coding: utf-8 -*-
"""
아이템 검색 · 날짜 구간(시작일~종료일) 평균구매금액(1개당)
- 사이드바 제거, 데이터 업로드 기능 삭제
- 상단 컨트롤: 최대 결과 수, 날짜 구간 슬라이더
- 그 아래: 아이템 검색 입력창
- 검색 결과(아이템명/아이템코드만 표시)에서 '선택' 클릭 → 그래프 항목 자동 반영
- 단일 모드 & 멀티 비교(지수화 옵션) 지원
- 기본 데이터 파일: market_item_data.xlsx
필수 컬럼: 일자, 아이템명, 평균구매금액(1개당)
"""
from pathlib import Path
from typing import List, Optional

import pandas as pd
import streamlit as st
import plotly.express as px

# -------------------- 페이지 설정 --------------------
st.set_page_config(
    page_title="아이템 검색 · 날짜 구간 평균구매금액(1개당)",
    page_icon="🔎",
    layout="wide",
)

# ✅ 기본 데이터 파일명을 market_item_data.xlsx 로 고정
DATA_PATH_DEFAULT = Path("market_item_data.xlsx")

# -------------------- 유틸 --------------------
def _set_selection(name: str, code: Optional[str]):
    """검색 결과에서 클릭 시, 선택 상태를 세션에 저장."""
    label = f"{name} ({code})" if (code and str(code).strip()) else name
    st.session_state["selected_name"] = name
    st.session_state["selected_code"] = code if code else ""
    st.session_state["selected_label"] = label

# -------------------- 데이터 유틸 --------------------
@st.cache_data(show_spinner=False)
def load_data(xlsx_path: Path) -> pd.DataFrame:
    """엑셀 로드 + 전처리 (일자/아이템명/아이템코드 정리)."""
    df = pd.read_excel(xlsx_path, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]

    required = {"일자", "아이템명", "평균구매금액(1개당)"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"필수 컬럼 누락: {missing}")

    # 타입/파생 컬럼
    df["일자"] = pd.to_datetime(df["일자"], errors="coerce")
    name_series = df["아이템명"].astype(str)
    df["아이템명_순수"] = name_series.str.replace(r"\(\d+\)$", "", regex=True).str.strip()
    df["아이템코드"] = name_series.str.extract(r"\((\d+)\)$")[0]
    return df


@st.cache_data(show_spinner=False)
def build_index(df: pd.DataFrame) -> pd.DataFrame:
    """아이템 요약 색인 (최근일/관측일수 기준 정렬)."""
    grp = df.groupby(["아이템명_순수", "아이템코드"], dropna=False)
    idx = grp["일자"].agg(days="nunique", first_date="min", last_date="max").reset_index()
    idx = idx.rename(columns={"아이템명_순수": "item_name", "아이템코드": "item_code"})
    idx = idx.sort_values(["last_date", "days", "item_name"], ascending=[False, False, True])
    return idx


def contains_filter(idx: pd.DataFrame, q: str, top_n: int = 100) -> pd.DataFrame:
    """부분 일치 검색(아이템명/코드). 이름 시작 일치 우선 정렬."""
    if not q:
        return idx.head(top_n)
    mask = (
        idx["item_name"].str.contains(q, case=False, na=False)
        | idx["item_code"].fillna("").str.contains(q, case=False, na=False)
    )
    res = idx[mask].copy()
    starts = res["item_name"].str.startswith(q, na=False)
    res = res.assign(_starts=starts.astype(int))
    res = res.sort_values(["_starts", "last_date", "days"], ascending=[False, False, False])
    return res.drop(columns=["_starts"]).head(top_n)


def get_series_by_daterange(
    df: pd.DataFrame, *, key: str, by: str = "name",
    start_date: pd.Timestamp, end_date: pd.Timestamp
) -> pd.DataFrame:
    """선택된 아이템의 '날짜 구간' 평균구매금액(1개당) 시계열."""
    if by == "code":
        dsel = df[df["아이템코드"] == key].copy()
    else:
        dsel = df[df["아이템명_순수"] == key].copy()

    if dsel.empty:
        return pd.DataFrame(columns=["일자", "평균구매금액(1개당)"])

    s = pd.to_datetime(start_date)
    e = pd.to_datetime(end_date)
    dN = dsel[(dsel["일자"] >= s) & (dsel["일자"] <= e)].copy()

    ts = (
        dN.groupby("일자", as_index=False)["평균구매금액(1개당)"]
          .mean()
          .sort_values("일자")
    )

    # 누락 일자 보이도록 전체 날짜 인덱스
    all_days = pd.date_range(start=s, end=e, freq="D")
    ts = ts.set_index("일자").reindex(all_days)
    ts.index.name = "일자"
    return ts.reset_index()


def get_multi_series_by_daterange(
    df: pd.DataFrame,
    *, names: List[str],
    start_date: pd.Timestamp, end_date: pd.Timestamp,
    normalize: str = "none"  # "none" | "index100"
) -> pd.DataFrame:
    """
    멀티 아이템의 '날짜 구간' 시계열(롱 포맷).
    반환 컬럼: [일자, 값, 아이템]
    """
    if not names:
        return pd.DataFrame(columns=["일자", "값", "아이템"])

    s = pd.to_datetime(start_date)
    e = pd.to_datetime(end_date)
    all_days = pd.date_range(start=s, end=e, freq="D")

    out_list = []
    for nm in names:
        dsel = df[(df["아이템명_순수"] == nm) & (df["일자"] >= s) & (df["일자"] <= e)]
        if dsel.empty:
            continue
        ts = (
            dsel.groupby("일자", as_index=False)["평균구매금액(1개당)"]
                .mean()
                .sort_values("일자")
                .set_index("일자")
                .reindex(all_days)
        )
        ts.columns = ["값"]
        ts.index.name = "일자"

        if normalize == "index100":
            base = ts["값"].dropna().head(1)
            if not base.empty and base.iloc[0] != 0:
                ts["값"] = (ts["값"] / base.iloc[0]) * 100

        ts = ts.reset_index()
        ts["아이템"] = nm
        out_list.append(ts)

    if not out_list:
        return pd.DataFrame(columns=["일자", "값", "아이템"])

    return pd.concat(out_list, ignore_index=True)

# -------------------- 본문 레이아웃 --------------------
st.markdown("## 🔎 아이템 검색 · 날짜 구간 평균구매금액(1개당)")
st.caption("상단 컨트롤(최대 결과 수/기간) → 검색 → 결과에서 '선택' 클릭 → 그래프 확인. 기본 데이터(market_item_data.xlsx)를 사용합니다.")

# 데이터 로드
try:
    df = load_data(DATA_PATH_DEFAULT)
    idx = build_index(df)
except Exception as e:
    st.error(f"데이터를 불러오는 중 오류 발생: {e}")
    st.stop()

# 날짜 범위 기본값 계산
min_date = pd.to_datetime(df["일자"].min()).date()
max_date = pd.to_datetime(df["일자"].max()).date()
_default_start = (pd.to_datetime(max_date) - pd.Timedelta(days=13)).date()
if _default_start < min_date:
    _default_start = min_date

# ---------- 상단 컨트롤(최대 결과 수 + 날짜 구간) ----------
ctl1, ctl2 = st.columns([1, 4])
with ctl1:
    top_n = st.number_input("최대 결과 수", min_value=10, max_value=500, value=50, step=10)
with ctl2:
    start_date, end_date = st.slider(
        "표시 기간(날짜)",
        min_value=min_date,
        max_value=max_date,
        value=(_default_start, max_date),
        format="YYYY-MM-DD",
    )

# ---------- 검색 입력창 ----------
st.subheader("아이템 검색")
q_main = st.text_input(
    "아이템명 또는 아이템코드로 검색…",
    value=st.session_state.get("q_main", ""),
    placeholder="예) 아스마르, 1990007109, 큐브 …",
)

# ---------- 검색 수행 & 결과 표 (아이템명/아이템코드만) ----------
res = contains_filter(idx, q_main, top_n=int(top_n))
res_min = res.rename(columns={"item_name": "아이템명", "item_code": "아이템코드"})[["아이템명", "아이템코드"]]

st.subheader("검색 결과")
# 테이블 헤더
h1, h2, h3 = st.columns([0.55, 0.35, 0.10])
h1.markdown("**아이템명**")
h2.markdown("**아이템코드**")
h3.markdown("**선택**")

if res_min.empty:
    st.info("검색 결과가 없습니다. 다른 키워드로 시도해 보세요.")
else:
    for i, row in res_min.iterrows():
        c1, c2, c3 = st.columns([0.55, 0.35, 0.10])
        c1.write(row["아이템명"])
        c2.write("" if pd.isna(row["아이템코드"]) else str(row["아이템코드"]))
        if c3.button("선택", key=f"pick_{i}"):
            _set_selection(row["아이템명"], None if pd.isna(row["아이템코드"]) else str(row["아이템코드"]))

# -------------------- 모드 선택: 단일 / 멀티 비교 --------------------
compare_mode = st.checkbox("🔀 멀티 아이템 비교 모드로 보기", value=False)

# 후보/라벨 준비
names = res["item_name"].tolist()
codes = res["item_code"].fillna("").tolist()
labels = [f"{n} ({c})" if c else n for n, c in zip(names, codes)]

# 최근 클릭 선택값을 selectbox 기본값에 반영
pre_label = st.session_state.get("selected_label")
default_index = labels.index(pre_label) if (pre_label in labels) else (0 if labels else 0)

if not compare_mode:
    # -------- 단일 모드 --------
    sel_col1, sel_col2 = st.columns([2, 1])
    with sel_col1:
        sel_label = st.selectbox("그래프로 볼 항목", labels, index=default_index, key="sel_label")
    with sel_col2:
        by_code = st.toggle("아이템코드로 선택", value=False, help="체크 시 코드 기준으로 선택합니다.")

    # selectbox → 이름/코드 복원
    sel_idx = labels.index(sel_label) if labels else 0
    sel_name = names[sel_idx] if names else ""
    sel_code = codes[sel_idx] or None

    # 클릭 선택이 있었으면 'by_code'도 자동 설정(코드 존재 시)
    if pre_label and pre_label == sel_label:
        by_code = bool(sel_code)

    by = "code" if (by_code and sel_code) else "name"
    key = sel_code if by == "code" else sel_name

    series = get_series_by_daterange(
        df, key=key, by=by,
        start_date=start_date, end_date=end_date
    )
    if series.empty:
        st.warning("선택한 항목의 데이터가 없습니다.")
        st.stop()

    # KPI
    valid_series = series.dropna(subset=["평균구매금액(1개당)"])
    latest = valid_series.tail(1)["평균구매금액(1개당)"].values[0] if not valid_series.empty else None
    meanN = valid_series["평균구매금액(1개당)"].mean() if not valid_series.empty else None
    first = valid_series.head(1)["평균구매금액(1개당)"].values[0] if not valid_series.empty else None
    chg = (latest - first) if (latest is not None and first is not None) else None

    k1, k2, k3 = st.columns(3)
    k1.metric("최신값", f"{int(latest):,}" if latest is not None else "-")
    k2.metric(f"{start_date}~{end_date} 평균", f"{int(meanN):,}" if meanN is not None else "-")
    k3.metric("증감", f"{int(chg):,}" if chg is not None else "-", delta=None if chg is None else f"{int(chg):,}")

    # 그래프
    pretty_title = f"{sel_name} ({sel_code})" if (by == "code" and sel_code) else sel_name
    fig = px.line(
        series,
        x="일자",
        y="평균구매금액(1개당)",
        title=f"{start_date} ~ {end_date} 평균구매금액(1개당) — {pretty_title}",
    )
    fig.update_traces(mode="lines+markers")
    fig.update_layout(
        yaxis=dict(tickformat=",d"),
        font=dict(
            family="Nanum Gothic, Malgun Gothic, Apple SD Gothic Neo, Noto Sans CJK KR, Segoe UI, Arial",
            size=14,
        ),
        margin=dict(l=10, r=10, t=50, b=10),
        legend_title_text="",
    )
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")

    # 다운로드
    csv_bytes = series.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 시계열 CSV 다운로드",
        data=csv_bytes,
        file_name=f"{start_date}_{end_date}_{pretty_title}.csv",
        mime="text/csv",
    )

else:
    # -------- 비교 모드 --------
    left, right = st.columns([2, 1])
    with left:
        sel_labels = st.multiselect(
            "비교할 항목을 선택하세요 (최대 8개 권장)",
            labels,
            default=[pre_label] if (pre_label in labels) else (labels[:2] if len(labels) >= 2 else labels),
            max_selections=min(8, len(labels)),
            key="compare_labels",
        )
    with right:
        norm_mode = st.selectbox("값 표시 방식", ["실제 가격", "지수화(첫날=100)"], index=0)

    sel_names = []
    for lbl in sel_labels:
        if " (" in lbl and lbl.endswith(")"):
            nm = lbl[: lbl.rfind(" (")]
        else:
            nm = lbl
        sel_names.append(nm)

    if len(sel_names) == 0:
        st.info("좌측에서 비교할 항목을 1개 이상 선택해 주세요.")
        st.stop()

    series_multi = get_multi_series_by_daterange(
        df,
        names=sel_names,
        start_date=start_date, end_date=end_date,
        normalize="index100" if norm_mode.startswith("지수화") else "none",
    )
    if series_multi.empty:
        st.warning("선택한 항목의 비교 데이터가 없습니다.")
        st.stop()

    # 그래프
    y_label = "지수(첫날=100)" if norm_mode.startswith("지수화") else "평균구매금액(1개당)"
    title_suffix = "(지수화)" if norm_mode.startswith("지수화") else "(실제)"
    fig = px.line(
        series_multi,
        x="일자",
        y="값",
        color="아이템",
        markers=True,
        title=f"{start_date} ~ {end_date} 멀티 아이템 비교 {title_suffix}",
    )
    fig.update_layout(
        yaxis=dict(tickformat=",.0f"),
        yaxis_title=y_label,
        font=dict(
            family="Nanum Gothic, Malgun Gothic, Apple SD Gothic Neo, Noto Sans CJK KR, Segoe UI, Arial",
            size=14,
        ),
        margin=dict(l=10, r=10, t=50, b=10),
        legend_title_text="아이템",
    )
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")

    # 간단 요약 표 (시작값/최신값/증감)
    with st.expander("📊 비교 요약 (기간 내 시작값/최신값/증감)"):
        summary = []
        for nm, sub in series_multi.groupby("아이템"):
            sub_valid = sub.dropna(subset=["값"]).sort_values("일자")
            if sub_valid.empty:
                continue
            start_v = float(sub_valid["값"].iloc[0])
            end_v = float(sub_valid["값"].iloc[-1])
            diff = end_v - start_v
            pct = (diff / start_v * 100.0) if start_v != 0 else None
            summary.append(
                {"아이템": nm, "시작값": round(start_v, 2), "최신값": round(end_v, 2),
                 "증감": round(diff, 2), "증감(%)": None if pct is None else round(pct, 2)}
            )
        if summary:
            st.dataframe(pd.DataFrame(summary), use_container_width=True)
        else:
            st.info("요약을 계산할 수 있는 데이터가 부족합니다.")