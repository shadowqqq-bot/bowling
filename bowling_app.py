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
LESSON_FILE = "bowling_lessons.csv"
THEORY_FILE = "bowling_theory.csv"
BALL_FILE = "bowling_balls.csv"

def get_github_repo():
    token = st.secrets["GITHUB_TOKEN"]
    repo_name = st.secrets["REPO_NAME"]
    g = Github(token)
    return g.get_repo(repo_name)

# 범용 깃허브 CSV 불러오기 함수
def load_csv_from_github(filename, default_columns):
    try:
        repo = get_github_repo()
        file_content = repo.get_contents(filename)
        csv_str = file_content.decoded_content.decode("utf-8")
        df = pd.read_csv(StringIO(csv_str))
        for col in default_columns:
            if col not in df.columns:
                df[col] = ""
        return df, file_content.sha
    except Exception:
        return pd.DataFrame(columns=default_columns), None

# 범용 깃허브 CSV 저장 함수
def save_csv_to_github(df, filename, sha, commit_msg="데이터 업데이트"):
    repo = get_github_repo()
    df_to_save = df.copy()
    if 'Date' in df_to_save.columns and not df_to_save.empty:
        df_to_save['Date'] = pd.to_datetime(df_to_save['Date']).dt.strftime('%Y-%m-%d')
    csv_content = df_to_save.to_csv(index=False)
    if sha:
        repo.update_file(filename, commit_msg, csv_content, sha)
    else:
        repo.create_file(filename, f"{filename} 첫 생성", csv_content)

# 데이터 로드
df, file_sha = load_csv_from_github(DATA_FILE, ['Date', 'Alley', 'Score'])
if not df.empty:
    df['Date'] = pd.to_datetime(df['Date'])

lesson_df, lesson_sha = load_csv_from_github(LESSON_FILE, ['날짜', '주제', '내용'])
theory_df, theory_sha = load_csv_from_github(THEORY_FILE, ['분류/용어', '내용'])
ball_cols = ['제조사', '품명', '코어', '커버스톡', 'TYPE', '마감', 'RG', 'DIFF', 'ASY', '메모']
ball_df, ball_sha = load_csv_from_github(BALL_FILE, ball_cols)

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
                save_csv_to_github(df, DATA_FILE, file_sha, "새 볼링 점수 추가")
                st.success(f"{len(scores)}게임 저장 완료!")
                st.rerun()

# 상단 요약 지표 및 집계 기준 (점수 데이터가 있을 때 표시)
if not df.empty:
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
else:
    st.info("아직 등록된 볼링 점수 기록이 없습니다. 왼쪽 상단 `[>]` 메뉴를 열어 첫 점수를 입력해 보세요!")

# 6개 탭 구성
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📈 그래프",
    "📋 기록 조회 및 수정",
    "🏢 볼링장별",
    "📝 레슨 후기",
    "📚 볼링 이론/용어",
    "🎳 볼링공 정보"
])

# 탭 1: 그래프
with tab1:
    if not df.empty:
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
            title="전 게임 점수 및 누적 에버리지",
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
        fig_cum.update_layout(
            showlegend=False,
            margin=dict(l=20, r=10, t=50, b=20),
            yaxis=dict(title="점수", range=[0, 310]),
            hovermode="x unified"
        )
        st.plotly_chart(fig_cum, use_container_width=True)
    else:
        st.write("점수 기록을 추가하면 그래프가 표시됩니다.")

# 탭 2: 기록 조회 및 수정
with tab2:
    if not df.empty:
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

        if st.button("💾 변경사항 저장하기", type="primary", key="save_scores"):
            cleaned_df = edited_df.dropna(subset=['Date', 'Alley', 'Score']).copy()
            cleaned_df['Date'] = pd.to_datetime(cleaned_df['Date'])
            cleaned_df['Score'] = cleaned_df['Score'].astype(int)
            cleaned_df = cleaned_df.sort_values(by='Date').reset_index(drop=True)
            save_csv_to_github(cleaned_df, DATA_FILE, file_sha, "볼링 기록 수정/삭제 반영")
            st.success("✅ 수정된 기록이 성공적으로 저장되었습니다!")
            st.rerun()
    else:
        st.write("조회할 기록이 없습니다.")

# 탭 3: 볼링장별 통계
with tab3:
    if not df.empty:
        alley_stats = df.groupby('Alley').agg(게임수=('Score', 'count'), 에버리지=('Score', 'mean'), 최고점수=('Score', 'max')).reset_index()
        alley_stats['에버리지'] = alley_stats['에버리지'].round(1)
        st.dataframe(alley_stats, use_container_width=True, hide_index=True)
    else:
        st.write("조회할 기록이 없습니다.")

# 탭 4: 레슨 후기
with tab4:
    st.subheader("📝 레슨 후기 및 연습 일지")
    with st.form("lesson_form", clear_on_submit=True):
        col_l1, col_l2 = st.columns([1, 3])
        with col_l1:
            lesson_date = st.date_input("레슨/연습 날짜", datetime.today())
        with col_l2:
            lesson_title = st.text_input("핵심 주제", placeholder="예: 푸시 타이밍 교정, 릴리스 시 손목 각도 유지")
        lesson_content = st.text_area("레슨 내용 및 후기 (자유롭게 여러 줄 입력)", height=130, placeholder="레슨에서 배운 내용이나 연습 시 느낀 점을 자유롭게 적어보세요.")
        
        if st.form_submit_button("레슨 후기 등록"):
            if lesson_content.strip() == "" and lesson_title.strip() == "":
                st.warning("주제나 내용을 입력해 주세요.")
            else:
                new_lesson = pd.DataFrame({
                    '날짜': [lesson_date.strftime('%Y-%m-%d')],
                    '주제': [lesson_title.strip()],
                    '내용': [lesson_content.strip()]
                })
                lesson_df = new_lesson if lesson_df.empty else pd.concat([new_lesson, lesson_df], ignore_index=True)
                save_csv_to_github(lesson_df, LESSON_FILE, lesson_sha, "레슨 후기 추가")
                st.success("✅ 레슨 후기가 저장되었습니다!")
                st.rerun()

    st.divider()
    st.caption("💡 아래 표에서 내용을 더블클릭하여 직접 수정하거나 행을 삭제한 뒤 **'레슨 후기 변경사항 저장'**을 누르세요.")
    edited_lesson_df = st.data_editor(
        lesson_df.fillna(""),
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "날짜": st.column_config.TextColumn("날짜", width="small"),
            "주제": st.column_config.TextColumn("핵심 주제", width="medium"),
            "내용": st.column_config.TextColumn("상세 내용 및 후기", width="large")
        },
        key="lesson_editor"
    )
    if st.button("💾 레슨 후기 변경사항 저장", key="save_lessons"):
        cleaned_lesson = edited_lesson_df.dropna(how='all').reset_index(drop=True)
        save_csv_to_github(cleaned_lesson, LESSON_FILE, lesson_sha, "레슨 후기 수정")
        st.success("✅ 레슨 후기 변경사항이 저장되었습니다!")
        st.rerun()

# 탭 5: 볼링 이론/용어
with tab5:
    st.subheader("📚 볼링 이론 및 용어 노트")
    with st.form("theory_form", clear_on_submit=True):
        theory_term = st.text_input("용어 / 이론 제목", placeholder="예: PAP (Positive Axis Point), 듀얼 앵글 레이아웃, 축 회전(Axis Rotation)")
        theory_desc = st.text_area("상세 설명 (자유롭게 여러 줄 입력)", height=130, placeholder="이론이나 용어에 대한 설명, 레인 공략법 등을 자유롭게 정리해 보세요.")
        
        if st.form_submit_button("이론/용어 등록"):
            if theory_term.strip() == "" and theory_desc.strip() == "":
                st.warning("용어나 설명을 입력해 주세요.")
            else:
                new_theory = pd.DataFrame({
                    '분류/용어': [theory_term.strip()],
                    '내용': [theory_desc.strip()]
                })
                theory_df = new_theory if theory_df.empty else pd.concat([new_theory, theory_df], ignore_index=True)
                save_csv_to_github(theory_df, THEORY_FILE, theory_sha, "볼링 이론/용어 추가")
                st.success("✅ 볼링 이론/용어가 저장되었습니다!")
                st.rerun()

    st.divider()
    st.caption("💡 아래 표에서 내용을 더블클릭하여 수정하거나 행을 삭제한 뒤 **'이론/용어 변경사항 저장'**을 누르세요.")
    edited_theory_df = st.data_editor(
        theory_df.fillna(""),
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "분류/용어": st.column_config.TextColumn("용어 / 이론 제목", width="medium"),
            "내용": st.column_config.TextColumn("상세 설명", width="large")
        },
        key="theory_editor"
    )
    if st.button("💾 이론/용어 변경사항 저장", key="save_theory"):
        cleaned_theory = edited_theory_df.dropna(how='all').reset_index(drop=True)
        save_csv_to_github(cleaned_theory, THEORY_FILE, theory_sha, "볼링 이론/용어 수정")
        st.success("✅ 이론/용어 변경사항이 저장되었습니다!")
        st.rerun()

# 탭 6: 볼링공 정보
with tab6:
    st.subheader("🎳 볼링공 제원(Spec) 관리")
    with st.form("ball_form", clear_on_submit=True):
        b_col1, b_col2, b_col3 = st.columns(3)
        with b_col1:
            b_maker = st.text_input("제조사", placeholder="예: 스톰(Storm), 트랙(Track)")
            b_cover = st.text_input("커버스톡", placeholder="예: R2S, QR-11, HK22")
            b_rg = st.text_input("RG", placeholder="예: 2.48")
        with b_col2:
            b_name = st.text_input("품명", placeholder="예: 넥스트 팩터, 파라곤 레드")
            b_type = st.text_input("TYPE", placeholder="예: Hybrid, Pearl, Solid, Urethane")
            b_diff = st.text_input("DIFF", placeholder="예: 0.052")
        with b_col3:
            b_core = st.text_input("코어", placeholder="예: 비대칭(Asym) / 대칭(Sym)")
            b_finish = st.text_input("마감 (Surface)", placeholder="예: 1500-grit Polished, 2000 Abralon")
            b_asy = st.text_input("ASY (Mass Bias)", placeholder="예: 0.017 (대칭은 생략 가능)")
            
        b_memo = st.text_area("특징 및 메모 (레이아웃, 볼 모션, 사용 후기 등 여러 줄 입력 가능)", height=90, placeholder="예: 50 x 4.5 x 40 지공, 백엔드에서 날카롭게 꺾임")
        
        if st.form_submit_button("볼링공 정보 등록"):
            if b_name.strip() == "":
                st.warning("볼링공 품명을 입력해 주세요.")
            else:
                new_ball = pd.DataFrame({
                    '제조사': [b_maker.strip()],
                    '품명': [b_name.strip()],
                    '코어': [b_core.strip()],
                    '커버스톡': [b_cover.strip()],
                    'TYPE': [b_type.strip()],
                    '마감': [b_finish.strip()],
                    'RG': [b_rg.strip()],
                    'DIFF': [b_diff.strip()],
                    'ASY': [b_asy.strip()],
                    '메모': [b_memo.strip()]
                })
                ball_df = new_ball if ball_df.empty else pd.concat([ball_df, new_ball], ignore_index=True)
                save_csv_to_github(ball_df, BALL_FILE, ball_sha, "볼링공 정보 추가")
                st.success(f"✅ '{b_name}' 볼링공 정보가 등록되었습니다!")
                st.rerun()

    st.divider()
    st.caption("💡 표의 셀을 클릭해 제원을 직접 수정하거나 왼쪽 체크박스로 행을 삭제한 뒤 **'볼링공 정보 변경사항 저장'**을 누르세요.")
    edited_ball_df = st.data_editor(
        ball_df.fillna(""),
        num_rows="dynamic",
        use_container_width=True,
        key="ball_editor"
    )
    if st.button("💾 볼링공 정보 변경사항 저장", key="save_balls"):
        cleaned_balls = edited_ball_df.dropna(how='all').reset_index(drop=True)
        save_csv_to_github(cleaned_balls, BALL_FILE, ball_sha, "볼링공 정보 수정")
        st.success("✅ 볼링공 정보 변경사항이 저장되었습니다!")
        st.rerun()
# --- 코드 끝 ---
