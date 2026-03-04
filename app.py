# -*- coding: utf-8 -*-
"""
아이템 검색 + 최근 N일(기본 14일) 평균구매금액(1개당) 그래프
- 사이드바에서 표시 기간(days)을 7~60일 중 선택 가능 (기본 14일)
- 아이템명/아이템코드 부분 검색
- 업로드한 엑셀 또는 기본 파일(Data_sample.xlsx) 사용
필수 컬럼: 일자, 아이템명, 평균구매금액(1개당)
"""
from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.express as px

# -------------------- 페이지 설정 --------------------
st.set_page_config(
    page_title="아이템 검색 · 최근 N일 평균구매금액(1개당)",
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


def get_lastN_series(
    df: pd.DataFrame, *, key: str, by: str = "name", days: int = 14
) -> pd.DataFrame:
    """선택된 아이템의 최근 N일(오늘 포함) 평균구매금액(1개당) 시계열."""
    if by == "code":
        dsel = df[df["아이템코드"] == key].copy()
    else:
        dsel = df[df["아이템명_순수"] == key].copy()

    if dsel.empty:
        return pd.DataFrame(columns=["일자", "평균구매금액(1개당)"])

    max_date = dsel["일자"].max()
    # '오늘 포함 N일' → 시작일은 max_date - (N-1)
    start_date = max_date - pd.Timedelta(days=days - 1)

    dN = dsel[(dsel["일자"] >= start_date) & (dsel["일자"] <= max_date)].copy()

    ts = (
        dN.groupby("일자", as_index=False)["평균구매금액(1개당)"]
        .mean()
        .sort_values("일자")
    )
    # 누락 일자도 보이도록 전체 날짜 인덱스 생성
    all_days = pd.date_range(start=start_date, end=max_date, freq="D")
    ts = ts.set_index("일자").reindex(all_days)
    ts.index.name = "일자"
    return ts.reset_index()

# -------------------- UI --------------------
st.title("🔎 아이템 검색 · 최근 N일 평균구매금액(1개당)")
st.caption("검색 → 항목 선택 → 최근 N일(기본 14일) 그래프를 확인하세요. 사이드바에서 기간을 조절할 수 있습니다.")

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

    st.header("검색")
    q = st.text_input("검색어 (이름/코드 부분 일치)", value="", placeholder="예) 아스마르, 1990007109, 큐브 …")
    top_n = st.slider("최대 결과 수", 10, 200, 50, step=10)

    st.header("기간")
    # 기본값 14일(=2주)
    days = st.slider("표시 기간(일)", min_value=7, max_value=60, value=14, step=1)

# 데이터 로드
try:
    df = load_data(xlsx_path)
    idx = build_index(df)
except Exception as e:
    st.error(f"데이터를 불러오는 중 오류 발생: {e}")
    st.stop()

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

# 선택 UI
names = res["item_name"].tolist()
codes = res["item_code"].fillna("").tolist()
labels = [f"{n} ({c})" if c else n for n, c in zip(names, codes)]

col_sel1, col_sel2 = st.columns([2, 1])
with col_sel1:
    sel_label = st.selectbox("그래프로 볼 항목을 선택하세요", labels, index=0)
with col_sel2:
    by_code = st.toggle("아이템코드로 선택", value=False, help="체크 시 코드 기준으로 선택합니다.")

# 키 추출
sel_idx = labels.index(sel_label)
sel_name = names[sel_idx]
sel_code = codes[sel_idx] or None

by = "code" if by_code and sel_code else "name"
key = sel_code if by == "code" else sel_name

# 시계열 생성 (기본 14일)
series = get_lastN_series(df, key=key, by=by, days=days)
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
k2.metric(f"{days}일 평균", f"{int(meanN):,}" if meanN is not None else "-")
k3.metric(f"{days}일 증감", f"{int(chg):,}" if chg is not None else "-", delta=None if chg is None else f"{int(chg):,}")

# 그래프
pretty_title = f"{sel_name} ({sel_code})" if by == "code" and sel_code else sel_name
fig = px.line(
    series,
    x="일자",
    y="평균구매금액(1개당)",
    title=f"최근 {days}일 평균구매금액(1개당) — {pretty_title}",
)
fig.update_traces(mode="lines+markers")
fig.update_layout(
    yaxis=dict(tickformat=",d"),
    font=dict(
        family="Nanum Gothic, Malgun Gothic, Apple SD Gothic Neo, Noto Sans CJK KR, Segoe UI, Arial",
        size=14,
    ),
    margin=dict(l=10, r=10, t=50, b=10),
)
st.plotly_chart(fig, use_container_width=True, theme="streamlit")

# 다운로드
csv_bytes = series.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "📥 시계열 CSV 다운로드",
    data=csv_bytes,
    file_name=f"last{days}_{pretty_title}.csv",
    mime="text/csv",
)

# 도움말
with st.expander("동작 원리/주의사항 보기"):
    st.markdown(
        f"""
- **표시 기간**: 선택한 **최근 {days}일**을 '오늘(가장 최신 일자) 포함'으로 집계합니다.  
- 같은 날 데이터가 여러 건이면 **일자 평균**으로 계산합니다.  
- 필수 컬럼: **일자, 아이템명, 평균구매금액(1개당)**  
- 업로드 파일을 제공하지 않으면 같은 폴더의 **Data_sample.xlsx**를 사용합니다.
"""
    )