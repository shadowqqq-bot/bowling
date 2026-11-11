import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from github import Github
from io import StringIO

st.set_page_config(page_title="볼링 에버리지 트래커", page_icon="🎳", layout="wide")
st.markdown("<h1 style='font-size: 24px;'>🎳 김형용 - 볼링 에버리지 기록 & 분석</h1>", unsafe_allow_html=True)
DATA_FILE = "bowling_records.csv"

def get_github_repo():
    token = st.secrets["GITHUB_TOKEN"]
    repo_name = st.secrets["REPO_NAME"]
    g = Github(token)
    return g.get_repo(repo_name)

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

# 사이드바: 점수 입력 폼
with st.sidebar:
    st.header("📝 새 게임 기록 추가")
    with st.form("record_form", clear_on_submit=True):
        input_date = st.date_input("날짜", datetime.today())
        input_alley = st.text_input("볼링장 이름", value="덕우스핀볼링장")
        input_scores = st.text_input("점수 (쉼표로 구분)", placeholder="예: 180, 205, 190")
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
                df = new_rows if df.empty else pd.concat([df, new_rows], ignore_index=True)
                save_data(df, file_sha, "새 볼링 점수 추가")
                st.success(f"{len(scores)}게임 저장 완료!")
                st.rerun()

# 메인 화면
if df.empty:
    st.info("아직 등록된 볼링 기록이 없습니다. 왼쪽 상단 `[>]` 메뉴를 열어 첫 점수를 입력해 보세요!")
else:
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values(by='Date').reset_index(drop=True)
    df['Game_Number'] = df.index + 1
    df['Cumulative_Avg'] = df['Score'].expanding().mean().round(1)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("총 게임 수", f"{len(df)} 게임")
    c2.metric("전체 에버리지", f"{df['Score'].mean():.1f} 점")
    c3.metric("최고 점수 (High)", f"{df['Score'].max()} 점")
    c4.metric("최저 점수 (Low)", f"{df['Score'].min()} 점")

    st.divider()
    period_option = st.radio("집계 기준:", ["날짜별", "주별", "월별", "연도별"], horizontal=True)

    df_p = df.copy()
    if period_option == "날짜별":
        df_p['Period'] = df_p['Date'].dt.strftime('%Y년 %m월 %d일')
    elif period_option == "주별":
        df_p['Period'] = df_p['Date'].dt.to_period('W').apply(lambda r: r.start_time.strftime('%Y년 %m월 %d일(주간)'))
    elif period_option == "월별":
        df_p['Period'] = df_p['Date'].dt.strftime('%Y년 %m월')
    else:
        df_p['Period'] = df_p['Date'].dt.strftime('%Y년')

    stats_df = df_p.groupby('Period', sort=False).agg(
        게임수=('Score', 'count'),
        에버리지=('Score', 'mean'),
        최고점수=('Score', 'max'),
        최저점수=('Score', 'min')
    ).reset_index()
    stats_df['에버리지'] = stats_df['에버리지'].round(1)

    tab1, tab2, tab3 = st.tabs(["📈 그래프", "📋 기록 조회 및 수정", "🏢 볼링장별"])

    with tab1:
        # 1. 기간별 에버리지 추이 그래프
        fig_p = go.Figure()
        fig_p.add_trace(go.Scatter(
            x=stats_df['Period'], y=stats_df['에버리지'],
            mode='lines+markers+text', name='기간 평균',
            text=stats_df['에버리지'], textposition='top center',
            line=dict(color='#1f77b4', width=3)
        ))
        fig_p.add_trace(go.Bar(
            x=stats_df['Period'], y=stats_df['게임수'],
            name='게임 수', yaxis='y2', opacity=0.2, marker_color='gray'
        ))
        fig_p.update_layout(
            title=f"{period_option} 에버리지 추이",
            xaxis=dict(title="기간", type='category'),
            yaxis=dict(title="에버리지", range=[0, 310]),
            yaxis2=dict(title="게임 수", overlaying='y', side='right', showgrid=False),
            hovermode="x unified"
        )
        st.plotly_chart(fig_p, use_container_width=True)

        st.divider()

        # 2. 전 게임 점수 및 누적 에버리지 그래프 (선 색상 선택 기능 포함)
        col_color1, col_color2, _ = st.columns([1, 1, 4])
        with col_color1:
            score_color = st.color_picker("🎨 '점수' 선 색상 선택", "#83C9FF")
        with col_color2:
            avg_color = st.color_picker("🎨 '에버리지 변화' 선 색상 선택", "#FF4B4B")

        df_cum_plot = df.rename(columns={
            'Score': '점수',
            'Cumulative_Avg': '에버리지 변화'
        })

        fig_cum = px.line(
            df_cum_plot,
            x='Game_Number',
            y=['점수', '에버리지 변화'],
            title="게임 점수 및 누적 에버리지",
            markers=True,
            labels={
                'Game_Number': '누적 게임 순서',
                'value': '점수',
                'variable': '구분'
            },
            color_discrete_map={
                '점수': score_color,
                '에버리지 변화': avg_color
            }
        )
        # showlegend=False 로 우측 범례를 제거하고 우측 여백(r=10)을 줄여 X축 폭 최대화
        fig_cum.update_layout(
            showlegend=False,
            margin=dict(l=20, r=10, t=50, b=20),
            yaxis=dict(title="점수", range=[0, 310]),
            hovermode="x unified"
        )
        st.plotly_chart(fig_cum, use_container_width=True)

    with tab2:
        st.subheader(f"📊 {period_option} 요약 통계")
        st.dataframe(stats_df.iloc[::-1], use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("✏️ 전체 기록 수정 및 삭제")
        st.caption("💡 표의 날짜, 볼링장, 점수를 클릭해 수정하거나, 맨 왼쪽 체크박스를 선택해 행을 삭제한 뒤 아래 **'변경사항 저장하기'** 버튼을 눌러주세요.")

        edit_df = df[['Date', 'Alley', 'Score']].sort_values(by='Date', ascending=False).reset_index(drop=True)
        edit_df['Date'] = edit_df['Date'].dt.date

        col_cfg = {
            "Date": st.column_config.DateColumn("날짜", format="YYYY-MM-DD", required=True),
            "Alley": st.column_config.TextColumn("볼링장", default="덕우스핀볼링장", required=True),
            "Score": st.column_config.NumberColumn("점수", min_value=0, max_value=300, step=1, required=True)
        }
        edited_df = st.data_editor(edit_df, num_rows="dynamic", use_container_width=True, column_config=col_cfg, key="editor")

        if st.button("💾 변경사항 저장하기", type="primary"):
            cleaned_df = edited_df.dropna(subset=['Date', 'Alley', 'Score']).copy()
            cleaned_df['Date'] = pd.to_datetime(cleaned_df['Date'])
            cleaned_df['Score'] = cleaned_df['Score'].astype(int)
            cleaned_df = cleaned_df.sort_values(by='Date').reset_index(drop=True)
            save_data(cleaned_df, file_sha, "볼링 기록 수정/삭제 반영")
            st.success("✅ 수정된 기록이 성공적으로 저장되었습니다!")
            st.rerun()

    with tab3:
        alley_stats = df.groupby('Alley').agg(게임수=('Score', 'count'), 에버리지=('Score', 'mean'), 최고점수=('Score', 'max')).reset_index()
        alley_stats['에버리지'] = alley_stats['에버리지'].round(1)
        st.dataframe(alley_stats, use_container_width=True, hide_index=True)
# --- 코드 끝 ---
