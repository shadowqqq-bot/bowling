import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from github import Github
from io import StringIO

st.set_page_config(page_title="볼링 에버리지 트래커", page_icon="🎳", layout="wide")
st.title("🎳 볼링 에버리지 기록 & 분석기")

DATA_FILE = "bowling_records.csv"

# 깃허브 연동 설정 (Streamlit Secrets 활용)
def get_github_repo():
    token = st.secrets["GITHUB_TOKEN"]
    repo_name = st.secrets["REPO_NAME"]
    g = Github(token)
    return g.get_repo(repo_name)

# 1. 깃허브에서 데이터 불러오기
def load_data():
    try:
        repo = get_github_repo()
        file_content = repo.get_contents(DATA_FILE)
        csv_str = file_content.decoded_content.decode("utf-8")
        df = pd.read_csv(StringIO(csv_str))
        df['Date'] = pd.to_datetime(df['Date'])
        return df, file_content.sha
    except Exception:
        return pd.DataFrame(columns=['Date', 'Alley', 'Score']), None

# 2. 깃허브에 데이터 자동 저장(Commit)하기
def save_data(df, sha, commit_msg="볼링 점수 업데이트"):
    repo = get_github_repo()
    df_to_save = df.copy()
    if not df_to_save.empty:
        df_to_save['Date'] = pd.to_datetime(df_to_save['Date']).dt.strftime('%Y-%m-%d')
    csv_content = df_to_save.to_csv(index=False)
    
    if sha:
        repo.update_file(DATA_FILE, commit_msg, csv_content, sha)
    else:
        repo.create_file(DATA_FILE, "첫 볼링 점수 기록 생성", csv_content)

df, file_sha = load_data()

# 3. 사이드바: 점수 입력 폼
with st.sidebar:
    st.header("📝 새 게임 기록 추가")
    with st.form("record_form", clear_on_submit=True):
        input_date = st.date_input("날짜", datetime.today())
        # 기본값으로 '덕우스핀볼링장' 고정 (다른 곳일 때만 수정)
        input_alley = st.text_input("볼링장 이름", value="덕우스핀볼링장")
        input_scores = st.text_input("점수 (여러 게임은 쉼표로 구분)", placeholder="예: 180, 205, 190")
        
        submitted = st.form_submit_button("기록 저장")
        
        if submitted:
            scores = [int(s.strip()) for s in input_scores.split(",") if s.strip().isdigit() and 0 <= int(s.strip()) <= 300]
            if not scores:
                st.error("0~300 사이의 올바른 점수를 입력해 주세요.")
            else:
                alley_name = input_alley.strip() if input_alley.strip() != "" else "덕우스핀볼링장"
                new_rows = pd.DataFrame({
                    'Date': [pd.to_datetime(input_date)] * len(scores),
                    'Alley': [alley_name] * len(scores),
                    'Score': scores
                })
                if df.empty:
                    df = new_rows
                else:
                    df = pd.concat([df, new_rows], ignore_index=True)
                
                save_data(df, file_sha, "새 볼링 점수 추가")
                st.success(f"{len(scores)}게임 저장 완료!")
                st.rerun()

# 4. 메인 화면: 통계 및 그래프
if df.empty:
    st.info("아직 등록된 볼링 기록이 없습니다. 왼쪽 상단 `[>]` 메뉴를 열어 첫 점수를 입력해 보세요!")
else:
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values(by='Date').reset_index(drop=True)
    df['Game_Number'] = df.index + 1
    df['Cumulative_Avg'] = df['Score'].expanding().mean().round(1)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("총 게임 수", f"{len(df)} 게임")
    col2.metric("전체 에버리지", f"{df['Score'].mean():.1f} 점")
    col3.metric("최고 점수 (High)", f"{df['Score'].max()} 점")
    col4.metric("최저 점수 (Low)", f"{df['Score'].min()} 점")

    st.divider()

    period_option = st.radio("집계 기준:", ["날짜별", "주별", "월별", "연도별"], horizontal=True)

    df_period = df.copy()
    if period_option == "날짜별":
        df_period['Period'] = df_period['Date'].dt.strftime('%Y-%m-%d')
    elif period_option == "주별":
        df_period['Period'] = df_period['Date'].dt.to_period('W').apply(lambda r: r.start_time.strftime('%Y-%m-%d(주)'))
    elif period_option == "월별":
        df_period['Period'] = df_period['Date'].dt.strftime('%Y-%m')
    elif period_option == "연도별":
        df_period['Period'] = df_period['Date'].dt.strftime('%Y년')

    stats_df = df_period.groupby('Period').agg(
        게임수=('Score', 'count'),
        에버리지=('Score', 'mean'),
        최고점수=('Score', 'max'),
        최저점수=('Score', 'min')
    ).reset_index()
    stats_df['에버리지'] = stats_df['에버리지'].round(1)

    tab1, tab2, tab3 = st.tabs(["📈 그래프", "📋 기록 조회 및 수정", "🏢 볼링장별"])

    with tab1:
        fig_period = go.Figure()
        fig_period.add_trace(go.Scatter(
            x=stats_df['Period'], y=stats_df['에버리지'],
            mode='lines+markers+text', name='기간 평균',
            text=stats_df['에버리지'], textposition='top center',
            line=dict(color='#1f77b4', width=3)
        ))
        fig_period.add_trace(go.Bar(
            x=stats_df['Period'], y=stats_df['게임수'],
            name='게임 수', yaxis='y2', opacity=0.2, marker_color='gray'
        ))
        fig_period.update_layout(
            title=f"{period_option} 에버리지 추이",
            yaxis=dict(title="에버리지", range=[0, 310]),
            yaxis
