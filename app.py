# -*- coding: utf-8 -*-
"""
아이템 검색 · 날짜 구간(시작일~종료일) 평균구매금액(1개당)
- 사이드바/업로드 제거: 기본 데이터(market_item_data.xlsx)만 사용
- 상단 한 줄: '아이템 검색' + (우측) '최대 결과 수' / '표시 기간'
- 검색 결과: 아이템명/아이템코드만 표시, 테두리 + 고정 높이(5행) + 스크롤
- 결과 '선택' 클릭 → '그래프로 볼 항목' 즉시 반영(세션 + st.rerun)
- '아이템 코드로 선택' 기능 제거(항상 이름 기준)
- '그래프로 볼 항목' 및 멀티 비교의 옵션은 '전체 아이템 목록(마스터)' 기반
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

# ✅ 기본 데이터 파일(리포 루트)
DATA_PATH_DEFAULT = Path("market_item_data.xlsx")

# -------------------- 유틸 --------------------
def _set_selection(name: str, code: Optional[str]):
    """검색 결과에서 선택 시 세션에 저장 → '그래프로 볼 항목' 기본값으로 반영."""
    label = f"{name} ({code})" if (code and str(code).strip()) else name
    st.session_state["selected_name"] = name
    st.session_state["selected_code"] = code if code else ""
    st.session_state["selected_label"] = label

@st.cache_data(show_spinner=False)
def load_data(xlsx_path: Path) -> pd.DataFrame:
    """엑셀 로드 + 전처리."""
    if not xlsx_path.exists():
        raise FileNotFoundError(
            f"기본 데이터 파일을 찾을 수 없습니다: {xlsx_path.resolve()}\n"
            f"리포 루트에 '{xlsx_path.name}' 을 업로드해 주세요."
        )
    df = pd.read_excel(xlsx_path, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]

    required = {"일자", "아이템명", "평균구매금액(1개당)"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"필수 컬럼 누락: {missing}")

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
    df: pd.DataFrame, *, key: str, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> pd.DataFrame:
    """선택된 아이템의 '날짜 구간' 평균구매금액(1개당) 시계열 (이름 기준만 사용)."""
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
    all_days = pd.date_range(start=s, end=e, freq="D")
    ts = ts.set_index("일자").reindex(all_days)
    ts.index.name = "일자"
    return ts.reset_index()

def get_multi_series_by_daterange(
    df: pd.DataFrame, *, names: List[str], start_date: pd.Timestamp, end_date: pd.Timestamp,
    normalize: str = "none"  # "none" | "index100"
) -> pd.DataFrame:
    """멀티 아이템 '날짜 구간' 시계열(롱 포맷)."""
    if not names:
        return pd.DataFrame(columns=["일자", "값", "아이템"])
    s = pd.to_datetime(start_date)
    e = pd.to_datetime(end_date)
    all_days = pd.date_range(start=s, end=e, freq="D")

    out = []
    for nm in names:
        dsel = df[(df["아이템명_순수"] == nm) & (df["일자"] >= s) & (df["일자"] <= e)]
        if dsel.empty:
            continue
        ts = (dsel.groupby("일자", as_index=False)["평균구매금액(1개당)"]
                  .mean().sort_values("일자").set_index("일자").reindex(all_days))
        ts.columns = ["값"]; ts.index.name = "일자"
        if normalize == "index100":
            base = ts["값"].dropna().head(1)
            if not base.empty and base.iloc[0] != 0:
                ts["값"] = (ts["값"] / base.iloc[0]) * 100
        ts = ts.reset_index(); ts["아이템"] = nm
        out.append(ts)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["일자","값","아이템"])

# -------------------- 데이터 로드 --------------------
st.markdown("## 🔎 아이템 검색 · 날짜 구간 평균구매금액(1개당)")
st.caption("검색과 컨트롤을 한 줄에 배치하고, 결과 박스는 5행 기준 테두리/스크롤이 적용됩니다. 기본 데이터(market_item_data.xlsx) 사용.")

try:
    df = load_data(DATA_PATH_DEFAULT)
    idx = build_index(df)
except Exception as e:
    st.error(f"데이터를 불러오는 중 오류 발생: {e}")
    st.stop()

# 날짜 기본값
min_date = pd.to_datetime(df["일자"].min()).date()
max_date = pd.to_datetime(df["일자"].max()).date()
_default_start = (pd.to_datetime(max_date) - pd.Timedelta(days=13)).date()
if _default_start < min_date:
    _default_start = min_date

# -------------------- 상단 가로 배치: 검색 + (최대 결과 수 / 기간) --------------------
# 비율: 검색(6) | 최대(1.2) | 기간(2.2)
col_search, col_topn, col_dates = st.columns([6, 1.2, 2.2], vertical_alignment="bottom")

with col_search:
    q_main = st.text_input(
        "아이템 검색",
        value=st.session_state.get("q_main", ""),
        placeholder="아이템명 또는 아이템코드로 검색…",
    )
with col_topn:
    top_n = st.number_input("최대 결과 수", min_value=10, max_value=500, value=50, step=10)
with col_dates:
    start_date, end_date = st.date_input(
        "표시 기간",
        value=(_default_start, max_date),
        min_value=min_date,
        max_value=max_date,
        format="YYYY-MM-DD",
    )

# -------------------- 마스터 옵션(전체 아이템) --------------------
# ⬅️ '그래프로 볼 항목'은 항상 전체 아이템 목록에서 고르도록 해서, 검색 결과와 무관하게 선택값이 보장되도록 함
master_names = idx["item_name"].tolist()
master_codes = idx["item_code"].fillna("").tolist()
master_labels = [f"{n} ({c})" if c else n for n, c in zip(master_names, master_codes)]

# -------------------- 검색 & 결과(5행 스크롤 + 테두리) --------------------
res = contains_filter(idx, q_main, top_n=int(top_n))
res_min = res.rename(columns={"item_name": "아이템명", "item_code": "아이템코드"})[["아이템명", "아이템코드"]]

st.markdown("### 검색 결과")

# 컨테이너 높이/테두리 → 내부 컴포넌트(버튼/컬럼 포함)에 스크롤이 적용
ROW_H = 42            # 행 하나의 대략적인 높이
VISIBLE_ROWS = 5      # ✅ 요청: 5개 이상일 때 스크롤
box_h = 16 + ROW_H * (VISIBLE_ROWS + 1)   # +헤더

box = st.container(height=box_h, border=True)
with box:
    # 헤더
    h1, h2, h3 = st.columns([0.55, 0.35, 0.10])
    h1.markdown("**아이템명**")
    h2.markdown("**아이템코드**")
    h3.markdown("**선택**")

    if res_min.empty:
        st.info("검색 결과가 없습니다. 다른 키워드로 시도해 보세요.")
    else:
        # top_n까지는 모두 렌더링하되, 컨테이너 높이로 스크롤 발생
        for i, row in res_min.iterrows():
            c1, c2, c3 = st.columns([0.55, 0.35, 0.10])
            c1.write(row["아이템명"])
            c2.write("" if pd.isna(row["아이템코드"]) else str(row["아이템코드"]))
            if c3.button("선택", key=f"pick_{i}"):
                _set_selection(row["아이템명"], None if pd.isna(row["아이템코드"]) else str(row["아이템코드"]))
                # 즉시 반영: rerun으로 selectbox 기본값 갱신
                st.rerun()

# -------------------- 모드 선택: 단일 / 멀티 비교 --------------------
compare_mode = st.checkbox("🔀 멀티 아이템 비교 모드로 보기", value=False)

# 최근 클릭 선택값을 select/multiselect 기본값에 반영
pre_label = st.session_state.get("selected_label")

if not compare_mode:
    # -------- 단일 모드: '그래프로 볼 항목'은 마스터 옵션 기반 --------
    default_index = master_labels.index(pre_label) if pre_label in master_labels else 0 if master_labels else 0
    sel_label = st.selectbox("그래프로 볼 항목", master_labels, index=default_index, key="sel_label")
    # 라벨 → 이름 복원
    if " (" in sel_label and sel_label.endswith(")"):
        sel_name = sel_label[: sel_label.rfind(" (")]
    else:
        sel_name = sel_label

    series = get_series_by_daterange(df, key=sel_name, start_date=start_date, end_date=end_date)
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
    fig = px.line(
        series, x="일자", y="평균구매금액(1개당)",
        title=f"{start_date} ~ {end_date} 평균구매금액(1개당) — {sel_name}",
        markers=True,
    )
    fig.update_layout(
        yaxis=dict(tickformat=",d"),
        font=dict(family="Nanum Gothic, Malgun Gothic, Apple SD Gothic Neo, Noto Sans CJK KR, Segoe UI, Arial", size=14),
        margin=dict(l=10, r=10, t=50, b=10),
        legend_title_text="",
    )
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")

    # 다운로드
    csv_bytes = series.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 시계열 CSV 다운로드",
        data=csv_bytes,
        file_name=f"{start_date}_{end_date}_{sel_name}.csv",
        mime="text/csv",
    )

else:
    # -------- 비교 모드: 멀티 옵션도 마스터 기반 --------
    default_multi = [pre_label] if (pre_label in master_labels) else (master_labels[:2] if len(master_labels) >= 2 else master_labels)
    sel_labels = st.multiselect(
        "비교할 항목을 선택하세요 (최대 8개 권장)",
        master_labels,
        default=default_multi,
        max_selections=min(8, len(master_labels)),
        key="compare_labels",
    )

    norm_mode = st.selectbox("값 표시 방식", ["실제 가격", "지수화(첫날=100)"], index=0)

    sel_names = []
    for lbl in sel_labels:
        if " (" in lbl and lbl.endswith(")"):
            nm = lbl[: lbl.rfind(" (")]
        else:
            nm = lbl
        sel_names.append(nm)

    if len(sel_names) == 0:
        st.info("비교할 항목을 1개 이상 선택해 주세요.")
        st.stop()

    series_multi = get_multi_series_by_daterange(
        df, names=sel_names, start_date=start_date, end_date=end_date,
        normalize="index100" if norm_mode.startswith("지수화") else "none",
    )
    if series_multi.empty:
        st.warning("선택한 항목의 비교 데이터가 없습니다.")
        st.stop()

    y_label = "지수(첫날=100)" if norm_mode.startswith("지수화") else "평균구매금액(1개당)"
    title_suffix = "(지수화)" if norm_mode.startswith("지수화") else "(실제)"
    fig = px.line(
        series_multi, x="일자", y="값", color="아이템", markers=True,
        title=f"{start_date} ~ {end_date} 멀티 아이템 비교 {title_suffix}",
    )
    fig.update_layout(
        yaxis=dict(tickformat=",.0f"),
        yaxis_title=y_label,
        font=dict(family="Nanum Gothic, Malgun Gothic, Apple SD Gothic Neo, Noto Sans CJK KR, Segoe UI, Arial", size=14),
        margin=dict(l=10, r=10, t=50, b=10),
        legend_title_text="아이템",
    )
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")

    with st.expander("📊 비교 요약 (기간 내 시작값/최신값/증감)"):
        summary = []
        for nm, sub in series_multi.groupby("아이템"):
            sub_valid = sub.dropna(subset=["값"]).sort_values("일자")
            if sub_valid.empty:
                continue
            start_v = float(sub_valid["값"].iloc[0]); end_v = float(sub_valid["값"].iloc[-1])
            diff = end_v - start_v; pct = (diff / start_v * 100.0) if start_v != 0 else None
            summary.append({"아이템": nm, "시작값": round(start_v, 2), "최신값": round(end_v, 2),
                            "증감": round(diff, 2), "증감(%)": None if pct is None else round(pct, 2)})
        if summary:
            st.dataframe(pd.DataFrame(summary), use_container_width=True)
        else:
            st.info("요약을 계산할 수 있는 데이터가 부족합니다.")