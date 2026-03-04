# -*- coding: utf-8 -*-
"""
아이템 검색 + 날짜 구간(시작일~종료일) 평균구매금액(1개당)
- 사이드바: 엑셀 업로드, 검색(부분 일치), 날짜 구간 슬라이더
- 단일 모드: 1개 아이템
- 비교 모드: 다중 아이템(최대 8개) + 지수화(첫날=100) 옵션
- 업로드 파일이 없으면 기본 파일(Data_sample.xlsx) 사용
필수 컬럼: 일자, 아이템명, 평균구매금액(1개당)
"""
from pathlib import Path
from typing import List

import pandas as pd
import streamlit as st
import plotly.express as px

# -------------------- 페이지 설정 --------------------
st.set_page_config(
    page_title="아이템 검색 · 날짜 구간 평균구매금액(1개당)",
    page_icon="🔎",
    layout="wide",
)

DATA_PATH_DEFAULT = Path("Data_sample.xlsx")

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
    df["아이템명_순수"] = (
        name_series.str.replace(r"\(\d+\)$", "", regex=True).str.strip()
    )
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

# -------------------- UI --------------------
st.title("🔎 아이템 검색 · 날짜 구간 평균구매금액(1개당)")
st.caption("검색 → (단일 또는 비교) 선택 → 날짜 구간 그래프 확인. 사이드바에서 시작일~종료일을 슬라이더로 조절하세요.")

with st.sidebar:
    st.header("데이터")
    uploaded = st.file_uploader(
        "엑셀 업로드 (.xlsx)",
        type=["xlsx"],
        help="필수 컬럼: 일자, 아이템명, 평균구매금액(1개당)",
    )
    if uploaded:
        xlsx_path = Path("_uploaded.xlsx")
        with open(xlsx_path, "wb") as f:
            f.write(uploaded.read())
        st.success("업로드된 파일을 사용합니다.")
    else:
        xlsx_path = DATA_PATH_DEFAULT
        st.info(f"기본 파일 사용: {xlsx_path}")

# 데이터 로드 & 검색/기간 UI
try:
    df = load_data(xlsx_path)
    idx = build_index(df)
except Exception as e:
    st.error(f"데이터를 불러오는 중 오류 발생: {e}")
    st.stop()

with st.sidebar:
    st.header("검색")
    q = st.text_input("검색어 (이름/코드 부분 일치)", value="", placeholder="예) 아스마르, 1990007109, 큐브 …")
    top_n = st.slider("최대 결과 수", 10, 200, 50, step=10)

# 날짜 구간 슬라이더 (데이터 로드 후에 생성)
min_date = pd.to_datetime(df["일자"].min()).date()
max_date = pd.to_datetime(df["일자"].max()).date()
# 기본값: 최신일 기준 최근 14일 범위
_default_start = (pd.to_datetime(max_date) - pd.Timedelta(days=13)).date()
if _default_start < min_date:
    _default_start = min_date

with st.sidebar:
    st.header("기간")
    start_date, end_date = st.slider(
        "표시 기간(날짜)",
        min_value=min_date,
        max_value=max_date,
        value=(_default_start, max_date),
        format="YYYY-MM-DD",
    )

# 검색 결과
res = contains_filter(idx, q, top_n=top_n)
res_show = res.rename(
    columns={"item_name": "아이템명", "item_code": "아이템코드", "days": "관측일수"}
)[["아이템명", "아이템코드", "관측일수", "first_date", "last_date"]]

st.subheader("검색 결과")
st.dataframe(res_show, use_container_width=True, height=360)

if res.empty:
    st.info("검색 결과가 없습니다. 검색어를 바꿔보세요.")
    st.stop()

# 후보 준비
names = res["item_name"].tolist()
codes = res["item_code"].fillna("").tolist()
labels = [f"{n} ({c})" if c else n for n, c in zip(names, codes)]
name_by_label = {lbl: nm for lbl, nm in zip(labels, names)}  # 멀티 선택용

# -------------------- 모드 선택 --------------------
compare_mode = st.checkbox("🔀 멀티 아이템 비교 모드로 보기", value=False)

if not compare_mode:
    # -------- 단일 모드 --------
    col_sel1, col_sel2 = st.columns([2, 1])
    with col_sel1:
        sel_label = st.selectbox("그래프로 볼 항목을 선택하세요", labels, index=0)
    with col_sel2:
        by_code = st.toggle("아이템코드로 선택", value=False, help="체크 시 코드 기준으로 선택합니다.")

    sel_idx = labels.index(sel_label)
    sel_name = names[sel_idx]
    sel_code = codes[sel_idx] or None

    by = "code" if by_code and sel_code else "name"
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
    k3.metric(f"증감", f"{int(chg):,}" if chg is not None else "-", delta=None if chg is None else f"{int(chg):,}")

    # 그래프
    pretty_title = f"{sel_name} ({sel_code})" if by == "code" and sel_code else sel_name
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
            default=labels[:2] if len(labels) >= 2 else labels,
            max_selections=min(8, len(labels)),
        )
    with right:
        norm_mode = st.selectbox("값 표시 방식", ["실제 가격", "지수화(첫날=100)"], index=0)

    sel_names = [name_by_label[lbl] for lbl in sel_labels]
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

# 도움말
with st.expander("동작 원리/주의사항 보기"):
    st.markdown(
        f"""
- **표시 기간**: 사이드바에서 선택한 **{start_date} ~ {end_date}** 범위를 '포함'하여 집계합니다.  
- 같은 날 데이터가 여러 건이면 **일자 평균**으로 계산합니다.  
- **비교 모드**는 선택한 아이템에 대해 동일한 날짜 구간을 적용합니다.  
- '지수화(첫날=100)'는 각 아이템의 기간 내 **첫 유효값을 100으로 정규화**하여 상대 변화를 비교합니다.  
- 필수 컬럼: **일자, 아이템명, 평균구매금액(1개당)**  
- 업로드 파일이 없으면 같은 폴더의 **Data_sample.xlsx**를 사용합니다.
"""
    )