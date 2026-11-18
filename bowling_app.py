import os
import re
import tempfile
from collections import deque

import numpy as np
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from github import Github, GithubException
from io import StringIO

try:  # 영상 분석용 (requirements.txt 에 opencv-python-headless 필요)
    import cv2
except Exception:
    cv2 = None

st.set_page_config(page_title="볼링 에버리지 트래커", page_icon="🎳", layout="wide")
st.markdown("<h1 style='font-size: 24px;'>🎳 김형용 - 볼링 에버리지 기록 & 분석</h1>", unsafe_allow_html=True)

DATA_FILE = "bowling_records.csv"
LESSON_FILE = "bowling_lessons.csv"
THEORY_FILE = "bowling_theory.csv"
BALL_FILE = "bowling_balls.csv"
DEFAULT_ALLEY = "덕우스핀볼링장"
NO_BALL = "(선택 안 함)"
SPEED_FILE = "bowling_speed.csv"
SPEED_COLS = ['Date', 'Ball', 'Time_s', 'Distance_m', 'Speed_kmh', 'Method', 'Memo']
LANE_LENGTH_M = 18.288  # 파울라인 ~ 1번 핀 중심 (60피트)

BALL_COLS = ['제조사', '품명', '코어', '커버스톡', 'TYPE', '마감', 'RG', 'DIFF', 'ASY', '메모']
BALL_NUM_COLS = ['RG', 'DIFF', 'ASY']


# ───────────────────────── 공통 유틸 ─────────────────────────
def stretch(func, *args, **kwargs):
    """최신 Streamlit은 width="stretch", 구버전은 use_container_width=True 를 사용."""
    try:
        return func(*args, width="stretch", **kwargs)
    except Exception:
        return func(*args, use_container_width=True, **kwargs)


def flash(msg, icon="✅"):
    """st.rerun() 이후에도 보이도록 토스트 메시지를 예약."""
    st.session_state["_flash"] = (msg, icon)


if "_flash" in st.session_state:
    _msg, _icon = st.session_state.pop("_flash")
    st.toast(_msg, icon=_icon)


# ───────────────────────── GitHub 입출력 ─────────────────────────
@st.cache_resource
def get_github_repo():
    g = Github(st.secrets["GITHUB_TOKEN"])
    return g.get_repo(st.secrets["REPO_NAME"])


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_csv(filename):
    """파일 내용과 sha 반환. 파일이 없으면 (None, None). 그 외 오류는 예외 발생(캐시되지 않음)."""
    repo = get_github_repo()
    try:
        fc = repo.get_contents(filename)
    except GithubException as e:
        if e.status == 404:
            return None, None
        raise
    return fc.decoded_content.decode("utf-8"), fc.sha


def load_csv(filename, default_columns):
    try:
        text, sha = _fetch_csv(filename)
    except GithubException as e:
        st.error(f"GitHub에서 {filename} 을(를) 불러오지 못했습니다 (오류 {e.status}). 잠시 후 사이드바의 '새로고침'을 눌러 주세요.")
        st.stop()
    except Exception as e:
        st.error(f"GitHub 연결 설정(secrets)이나 네트워크를 확인해 주세요: {e}")
        st.stop()

    if not text or not text.strip():
        return pd.DataFrame(columns=default_columns), sha

    df = pd.read_csv(StringIO(text))
    for col in default_columns:
        if col not in df.columns:
            df[col] = ""
    return df, sha


def save_csv_to_github(df, filename, sha, commit_msg="데이터 업데이트"):
    """저장 성공 여부를 반환. 충돌/오류 시 메시지를 띄우고 False."""
    out = df.copy()
    for col in ('Date', '날짜'):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors='coerce').dt.strftime('%Y-%m-%d')
    csv_content = out.to_csv(index=False)
    try:
        repo = get_github_repo()
        if sha:
            repo.update_file(filename, commit_msg, csv_content, sha)
        else:
            repo.create_file(filename, f"{filename} 첫 생성", csv_content)
    except GithubException as e:
        st.cache_data.clear()
        if e.status in (409, 422):
            st.error("⚠️ 다른 기기/탭에서 먼저 수정된 데이터가 있습니다. 화면을 새로고침한 뒤 다시 시도해 주세요.")
        else:
            st.error(f"GitHub 저장 실패 (오류 {e.status}). 잠시 후 다시 시도해 주세요.")
        return False
    st.cache_data.clear()
    return True


def add_row(df, row, prepend=False):
    new = pd.DataFrame([row])
    if df.empty:
        return new
    return pd.concat([new, df] if prepend else [df, new], ignore_index=True)


def is_valid_score(token):
    return token.isascii() and token.isdigit() and 0 <= int(token) <= 300


def summarize(frame, key, sort=False):
    out = frame.groupby(key, sort=sort).agg(
        게임수=('Score', 'count'),
        에버리지=('Score', 'mean'),
        최고점수=('Score', 'max'),
        최저점수=('Score', 'min'),
        표준편차=('Score', 'std'),
        **{'200+비율(%)': ('Score', lambda s: (s >= 200).mean() * 100)}
    ).reset_index()
    for c in ['에버리지', '표준편차', '200+비율(%)']:
        out[c] = out[c].round(1)
    return out


# ───────────────────────── 데이터 로드/정리 ─────────────────────────
base_df, file_sha = load_csv(DATA_FILE, ['Date', 'Alley', 'Score', 'Ball'])
if not base_df.empty:
    base_df['Date'] = pd.to_datetime(base_df['Date'], errors='coerce')
    base_df['Score'] = pd.to_numeric(base_df['Score'], errors='coerce')
    base_df = base_df.dropna(subset=['Date', 'Score']).copy()
    base_df['Score'] = base_df['Score'].astype(int)
    base_df['Alley'] = base_df['Alley'].fillna('').astype(str)
    base_df['Ball'] = base_df['Ball'].fillna('').astype(str)
    base_df = base_df.sort_values(by='Date', kind='stable').reset_index(drop=True)
base_df = base_df[['Date', 'Alley', 'Score', 'Ball']]

lesson_df, lesson_sha = load_csv(LESSON_FILE, ['날짜', '주제', '내용'])
lesson_df['날짜'] = pd.to_datetime(lesson_df['날짜'], errors='coerce')
lesson_df = lesson_df.sort_values('날짜', ascending=False, kind='stable', na_position='last').reset_index(drop=True)
lesson_df['날짜'] = lesson_df['날짜'].apply(lambda x: x.date() if pd.notna(x) else None)
for c in ['주제', '내용']:
    lesson_df[c] = lesson_df[c].fillna('').astype(str)

theory_df, theory_sha = load_csv(THEORY_FILE, ['분류/용어', '내용'])
for c in ['분류/용어', '내용']:
    theory_df[c] = theory_df[c].fillna('').astype(str)

ball_df, ball_sha = load_csv(BALL_FILE, BALL_COLS)
for c in BALL_COLS:
    if c in BALL_NUM_COLS:
        ball_df[c] = pd.to_numeric(ball_df[c], errors='coerce')
    else:
        ball_df[c] = ball_df[c].fillna('').astype(str)
ball_names = list(dict.fromkeys(n for n in ball_df['품명'] if n.strip()))

speed_df, speed_sha = load_csv(SPEED_FILE, SPEED_COLS)
speed_df['Date'] = pd.to_datetime(speed_df['Date'], errors='coerce')
for c in ['Time_s', 'Distance_m', 'Speed_kmh']:
    speed_df[c] = pd.to_numeric(speed_df[c], errors='coerce')
for c in ['Ball', 'Method', 'Memo']:
    speed_df[c] = speed_df[c].fillna('').astype(str)
speed_df = speed_df.dropna(subset=['Date']).sort_values('Date', kind='stable').reset_index(drop=True)
speed_df = speed_df[SPEED_COLS]

# ───────────────────────── 사이드바 ─────────────────────────
with st.sidebar:
    if st.button("🔄 GitHub 새로고침"):
        st.cache_data.clear()
        st.rerun()

    target_avg = st.number_input("🎯 목표 에버리지 (0이면 숨김)", min_value=0, max_value=300, value=0, step=5)

    st.header("📝 새 게임 기록 추가")
    with st.form("record_form", clear_on_submit=True):
        input_date = st.date_input("날짜", datetime.today())
        input_alley = st.text_input("볼링장 이름", value=DEFAULT_ALLEY)
        input_ball = st.selectbox("사용한 볼", [NO_BALL] + ball_names)
        input_scores = st.text_input("점수 (쉼표/공백으로 구분)", placeholder="예: 180, 205, 190")
        submitted = st.form_submit_button("기록 저장")

        if submitted:
            tokens = [t for t in re.split(r"[,\s]+", input_scores.strip()) if t]
            scores = [int(t) for t in tokens if is_valid_score(t)]
            rejected = [t for t in tokens if not is_valid_score(t)]
            if not scores:
                st.error("0~300 사이의 올바른 점수를 입력해 주세요." + (f" (제외된 값: {', '.join(rejected)})" if rejected else ""))
            else:
                alley_name = input_alley.strip() or DEFAULT_ALLEY
                new_rows = pd.DataFrame({
                    'Date': [pd.to_datetime(input_date)] * len(scores),
                    'Alley': [alley_name] * len(scores),
                    'Score': scores,
                    'Ball': [("" if input_ball == NO_BALL else input_ball)] * len(scores),
                })
                merged = new_rows if base_df.empty else pd.concat([base_df, new_rows], ignore_index=True)
                merged = merged.sort_values(by='Date', kind='stable').reset_index(drop=True)
                if save_csv_to_github(merged, DATA_FILE, file_sha, "새 볼링 점수 추가"):
                    msg = f"{len(scores)}게임 저장 완료!"
                    if rejected:
                        msg += f" (제외된 값: {', '.join(rejected)})"
                    flash(msg, "⚠️" if rejected else "✅")
                    st.rerun()

# ───────────────────────── 집계 ─────────────────────────
if not base_df.empty:
    df = base_df.copy()
    df['Game_Number'] = df.index + 1
    df['Cumulative_Avg'] = df['Score'].expanding().mean().round(1)

    overall = df['Score'].mean()
    r1 = st.columns(4)
    r1[0].metric("총 게임 수", f"{len(df)} 게임")
    r1[1].metric("전체 에버리지", f"{overall:.1f} 점")
    r1[2].metric("최고 점수 (High)", f"{df['Score'].max()} 점")
    r1[3].metric("최저 점수 (Low)", f"{df['Score'].min()} 점")

    recent10 = df['Score'].tail(10).mean()
    recent30 = df['Score'].tail(30).mean()
    std = df['Score'].std()
    r2 = st.columns(4)
    r2[0].metric("최근 10게임 평균", f"{recent10:.1f} 점", delta=f"{recent10 - overall:+.1f}")
    r2[1].metric("최근 30게임 평균", f"{recent30:.1f} 점", delta=f"{recent30 - overall:+.1f}")
    r2[2].metric("200점 이상 비율", f"{(df['Score'] >= 200).mean() * 100:.1f} %")
    r2[3].metric("표준편차 (기복)", f"{std:.1f}" if pd.notna(std) else "-")

    st.divider()
    period_option = st.radio("집계 기준:", ["날짜별", "주별", "월별", "연도별"], horizontal=True)

    df_p = df.copy()
    if period_option == "날짜별":
        df_p['Period'] = df_p['Date'].dt.strftime('%Y년 %m월 %d일')
    elif period_option == "주별":
        week_start = df_p['Date'] - pd.to_timedelta(df_p['Date'].dt.weekday, unit='D')
        df_p['Period'] = week_start.dt.strftime('%Y년 %m월 %d일(주간)')
    elif period_option == "월별":
        df_p['Period'] = df_p['Date'].dt.strftime('%Y년 %m월')
    else:
        df_p['Period'] = df_p['Date'].dt.strftime('%Y년')

    stats_df = summarize(df_p, 'Period', sort=False)
else:
    df = base_df.copy()
    st.info("아직 등록된 볼링 점수 기록이 없습니다. 왼쪽 상단 `[>]` 메뉴를 열어 첫 점수를 입력해 보세요!")

# ───────────────────────── 탭 ─────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📈 그래프",
    "📋 기록 조회 및 수정",
    "🏢 볼링장별",
    "📝 레슨 후기",
    "📚 볼링 이론/용어",
    "🎳 볼링공 정보",
    "🚀 구속 측정"
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
        if target_avg > 0:
            fig_p.add_hline(y=target_avg, line_dash="dash", line_color="green",
                            annotation_text=f"목표 {target_avg}", annotation_position="top left")
        fig_p.update_layout(
            title=f"{period_option} 에버리지 추이",
            xaxis=dict(title="기간", type='category'),
            yaxis=dict(title="에버리지", range=[0, 310]),
            yaxis2=dict(title="게임 수", overlaying='y', side='right', showgrid=False),
            hovermode="x unified"
        )
        stretch(st.plotly_chart, fig_p)

        st.divider()

        col_a, col_b, col_c = st.columns([1, 1, 2])
        with col_a:
            score_color = st.color_picker("🎨 '점수' 선 색상", "#83C9FF")
        with col_b:
            avg_color = st.color_picker("🎨 '에버리지 변화' 선 색상", "#FF4B4B")
        with col_c:
            ma_window = st.slider("📐 이동평균 게임 수", min_value=3, max_value=50, value=10)

        ma_label = f"이동평균({ma_window}게임)"
        df_cum_plot = df.copy()
        df_cum_plot[ma_label] = df_cum_plot['Score'].rolling(ma_window, min_periods=1).mean().round(1)
        df_cum_plot = df_cum_plot.rename(columns={'Score': '점수', 'Cumulative_Avg': '에버리지 변화'})

        fig_cum = px.line(
            df_cum_plot,
            x='Game_Number',
            y=['점수', '에버리지 변화', ma_label],
            title="전 게임 점수 · 누적 에버리지 · 이동평균",
            markers=True,
            labels={'Game_Number': '누적 게임 순서', 'value': '점수', 'variable': '구분'},
            color_discrete_map={'점수': score_color, '에버리지 변화': avg_color, ma_label: '#FFA500'}
        )
        if target_avg > 0:
            fig_cum.add_hline(y=target_avg, line_dash="dash", line_color="green",
                              annotation_text=f"목표 {target_avg}", annotation_position="top left")
        fig_cum.update_layout(
            legend_title_text="",
            margin=dict(l=20, r=10, t=50, b=20),
            yaxis=dict(title="점수", range=[0, 310]),
            hovermode="x unified"
        )
        stretch(st.plotly_chart, fig_cum)

        st.divider()

        fig_h = px.histogram(df, x='Score', title="점수 분포", labels={'Score': '점수'})
        fig_h.update_traces(xbins=dict(start=0, end=310, size=10))
        fig_h.add_vline(x=overall, line_dash="dash", annotation_text=f"평균 {overall:.1f}")
        fig_h.update_layout(bargap=0.05, xaxis=dict(range=[0, 310]), yaxis_title="게임 수")
        stretch(st.plotly_chart, fig_h)
    else:
        st.write("점수 기록을 추가하면 그래프가 표시됩니다.")

# 탭 2: 기록 조회 및 수정
with tab2:
    if not df.empty:
        st.subheader(f"📊 {period_option} 요약 통계")
        stretch(st.dataframe, stats_df.iloc[::-1], hide_index=True)

        st.divider()
        st.subheader("✏️ 전체 기록 수정 및 삭제")
        st.caption("💡 표의 날짜, 볼링장, 점수, 사용 볼을 클릭해 수정하거나, 맨 왼쪽 체크박스를 선택해 행을 삭제한 뒤 아래 **'변경사항 저장하기'** 버튼을 눌러주세요.")

        edit_df = base_df.sort_values(by='Date', ascending=False, kind='stable').reset_index(drop=True)
        edit_df['Date'] = edit_df['Date'].dt.date

        used_balls = set(edit_df['Ball']) - {''}
        ball_options = [""] + sorted(set(ball_names) | used_balls)

        col_cfg = {
            "Date": st.column_config.DateColumn("날짜", format="YYYY-MM-DD", required=True),
            "Alley": st.column_config.TextColumn("볼링장", default=DEFAULT_ALLEY, required=True),
            "Score": st.column_config.NumberColumn("점수", min_value=0, max_value=300, step=1, required=True),
            "Ball": st.column_config.SelectboxColumn("사용 볼", options=ball_options, required=False),
        }
        edited_df = stretch(st.data_editor, edit_df, num_rows="dynamic", column_config=col_cfg, key="editor")

        if st.button("💾 변경사항 저장하기", type="primary", key="save_scores"):
            cleaned = edited_df.dropna(subset=['Date', 'Alley', 'Score']).copy()
            cleaned['Date'] = pd.to_datetime(cleaned['Date'])
            cleaned['Score'] = cleaned['Score'].astype(int)
            cleaned['Ball'] = cleaned['Ball'].fillna('').astype(str)
            cleaned = cleaned.sort_values(by='Date', kind='stable').reset_index(drop=True)
            if save_csv_to_github(cleaned, DATA_FILE, file_sha, "볼링 기록 수정/삭제 반영"):
                flash("수정된 기록이 저장되었습니다!")
                st.rerun()
    else:
        st.write("조회할 기록이 없습니다.")

# 탭 3: 볼링장별 통계
with tab3:
    if not df.empty:
        alley_stats = summarize(df, 'Alley').sort_values('게임수', ascending=False).reset_index(drop=True)
        fig_a = px.bar(
            alley_stats, x='Alley', y='에버리지', text='에버리지',
            hover_data=['게임수', '최고점수'], title="볼링장별 에버리지"
        )
        fig_a.update_layout(xaxis_title="볼링장", yaxis=dict(title="에버리지", range=[0, 310]))
        stretch(st.plotly_chart, fig_a)
        stretch(st.dataframe, alley_stats, hide_index=True)
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
                new_df = add_row(lesson_df, {
                    '날짜': lesson_date,
                    '주제': lesson_title.strip(),
                    '내용': lesson_content.strip()
                }, prepend=True)
                if save_csv_to_github(new_df, LESSON_FILE, lesson_sha, "레슨 후기 추가"):
                    flash("레슨 후기가 저장되었습니다!")
                    st.rerun()

    st.divider()
    st.caption("💡 아래 표에서 내용을 더블클릭하여 직접 수정하거나 행을 삭제한 뒤 **'레슨 후기 변경사항 저장'**을 누르세요.")
    edited_lesson_df = stretch(
        st.data_editor,
        lesson_df,
        num_rows="dynamic",
        column_config={
            "날짜": st.column_config.DateColumn("날짜", format="YYYY-MM-DD", width="small"),
            "주제": st.column_config.TextColumn("핵심 주제", width="medium"),
            "내용": st.column_config.TextColumn("상세 내용 및 후기", width="large")
        },
        key="lesson_editor"
    )
    if st.button("💾 레슨 후기 변경사항 저장", key="save_lessons"):
        cleaned_lesson = edited_lesson_df.dropna(how='all').reset_index(drop=True)
        if save_csv_to_github(cleaned_lesson, LESSON_FILE, lesson_sha, "레슨 후기 수정"):
            flash("레슨 후기 변경사항이 저장되었습니다!")
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
                new_df = add_row(theory_df, {
                    '분류/용어': theory_term.strip(),
                    '내용': theory_desc.strip()
                }, prepend=True)
                if save_csv_to_github(new_df, THEORY_FILE, theory_sha, "볼링 이론/용어 추가"):
                    flash("볼링 이론/용어가 저장되었습니다!")
                    st.rerun()

    st.divider()
    st.caption("💡 아래 표에서 내용을 더블클릭하여 수정하거나 행을 삭제한 뒤 **'이론/용어 변경사항 저장'**을 누르세요.")
    edited_theory_df = stretch(
        st.data_editor,
        theory_df,
        num_rows="dynamic",
        column_config={
            "분류/용어": st.column_config.TextColumn("용어 / 이론 제목", width="medium"),
            "내용": st.column_config.TextColumn("상세 설명", width="large")
        },
        key="theory_editor"
    )
    if st.button("💾 이론/용어 변경사항 저장", key="save_theory"):
        cleaned_theory = edited_theory_df.dropna(how='all').reset_index(drop=True)
        if save_csv_to_github(cleaned_theory, THEORY_FILE, theory_sha, "볼링 이론/용어 수정"):
            flash("이론/용어 변경사항이 저장되었습니다!")
            st.rerun()

# 탭 6: 볼링공 정보
with tab6:
    st.subheader("🎳 볼링공 제원(Spec) 관리")
    with st.form("ball_form", clear_on_submit=True):
        b_col1, b_col2, b_col3 = st.columns(3)
        with b_col1:
            b_maker = st.text_input("제조사", placeholder="예: 스톰(Storm), 트랙(Track)")
            b_cover = st.text_input("커버스톡", placeholder="예: R2S, QR-11, HK22")
            b_rg = st.number_input("RG", value=None, min_value=0.0, max_value=5.0, step=0.001, format="%.3f", placeholder="예: 2.48")
        with b_col2:
            b_name = st.text_input("품명", placeholder="예: 넥스트 팩터, 파라곤 레드")
            b_type = st.text_input("TYPE", placeholder="예: Hybrid, Pearl, Solid, Urethane")
            b_diff = st.number_input("DIFF", value=None, min_value=0.0, max_value=1.0, step=0.001, format="%.3f", placeholder="예: 0.052")
        with b_col3:
            b_core = st.text_input("코어", placeholder="예: 비대칭(Asym) / 대칭(Sym)")
            b_finish = st.text_input("마감 (Surface)", placeholder="예: 1500-grit Polished, 2000 Abralon")
            b_asy = st.number_input("ASY (Mass Bias)", value=None, min_value=0.0, max_value=1.0, step=0.001, format="%.3f", placeholder="예: 0.017 (대칭은 비워 두기)")

        b_memo = st.text_area("특징 및 메모 (레이아웃, 볼 모션, 사용 후기 등 여러 줄 입력 가능)", height=90, placeholder="예: 50 x 4.5 x 40 지공, 백엔드에서 날카롭게 꺾임")

        if st.form_submit_button("볼링공 정보 등록"):
            if b_name.strip() == "":
                st.warning("볼링공 품명을 입력해 주세요.")
            else:
                new_df = add_row(ball_df, {
                    '제조사': b_maker.strip(),
                    '품명': b_name.strip(),
                    '코어': b_core.strip(),
                    '커버스톡': b_cover.strip(),
                    'TYPE': b_type.strip(),
                    '마감': b_finish.strip(),
                    'RG': b_rg,
                    'DIFF': b_diff,
                    'ASY': b_asy,
                    '메모': b_memo.strip()
                })
                if save_csv_to_github(new_df, BALL_FILE, ball_sha, "볼링공 정보 추가"):
                    flash(f"'{b_name}' 볼링공 정보가 등록되었습니다!")
                    st.rerun()

    st.divider()
    st.subheader("📊 볼별 사용 통계")
    used = df[df['Ball'] != ''] if not df.empty else df
    if not used.empty:
        ball_stats = summarize(used, 'Ball').sort_values('게임수', ascending=False).reset_index(drop=True)
        fig_b = px.bar(ball_stats, x='Ball', y='에버리지', text='에버리지',
                       hover_data=['게임수', '최고점수'], title="볼별 에버리지")
        fig_b.update_layout(xaxis_title="볼", yaxis=dict(title="에버리지", range=[0, 310]))
        stretch(st.plotly_chart, fig_b)
        stretch(st.dataframe, ball_stats, hide_index=True)
    else:
        st.caption("점수 기록 입력 시 '사용한 볼'을 선택하면 볼별 에버리지가 표시됩니다.")

    st.divider()
    st.caption("💡 표의 셀을 클릭해 제원을 직접 수정하거나 왼쪽 체크박스로 행을 삭제한 뒤 **'볼링공 정보 변경사항 저장'**을 누르세요. (볼 이름을 바꾸면 기존 기록의 볼 이름과 달라질 수 있어요.)")
    edited_ball_df = stretch(
        st.data_editor,
        ball_df,
        num_rows="dynamic",
        column_config={
            "RG": st.column_config.NumberColumn("RG", format="%.3f", step=0.001),
            "DIFF": st.column_config.NumberColumn("DIFF", format="%.3f", step=0.001),
            "ASY": st.column_config.NumberColumn("ASY", format="%.3f", step=0.001),
        },
        key="ball_editor"
    )
    if st.button("💾 볼링공 정보 변경사항 저장", key="save_balls"):
        cleaned_balls = edited_ball_df.dropna(how='all').reset_index(drop=True)
        if save_csv_to_github(cleaned_balls, BALL_FILE, ball_sha, "볼링공 정보 수정"):
            flash("볼링공 정보 변경사항이 저장되었습니다!")
            st.rerun()
# ───────────────────────── 구속 측정 헬퍼 ─────────────────────────
MODE_MANUAL = "✋ 수동 (영상 보며 지정)"
MODE_TRACK = "🎯 자동 (공 추적)"
MODE_AUTO = "🤖 자동 (영역 변화 감지)"
MODE_DIRECT = "⌨️ 시간 직접 입력"
VIDEO_TYPES = ["mp4", "mov", "avi", "m4v", "mkv"]
END_MOTION = "💥 핀이 움직이기 시작하는 순간 (추천)"
END_LINE = "📏 1번 핀 높이 선 통과"


def spd_store_video(uploaded):
    """업로드된 영상을 임시 파일로 저장(같은 파일이면 재사용)하고 경로를 반환."""
    key = f"{uploaded.name}_{uploaded.size}"
    if st.session_state.get("spd_vid_key") != key:
        old = st.session_state.get("spd_vid_path")
        if old and os.path.exists(old):
            try:
                os.remove(old)
            except OSError:
                pass
        suffix = os.path.splitext(uploaded.name)[1] or ".mp4"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(uploaded.getbuffer())
        tmp.close()
        st.session_state.update(spd_vid_key=key, spd_vid_path=tmp.name,
                                spd_frame=0, spd_t_start=0.0, spd_t_end=0.0)
        st.session_state.pop("spd_series", None)
        st.session_state.pop("trk_res", None)
    return st.session_state["spd_vid_path"]


@st.cache_data(show_spinner=False)
def spd_video_info(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    info = dict(
        fps=float(cap.get(cv2.CAP_PROP_FPS) or 0.0),
        n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
        w=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
        h=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
    )
    cap.release()
    return info


@st.cache_data(show_spinner=False, max_entries=128)
def spd_read_frame(path, idx):
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    h, w = frame.shape[:2]
    if w > 960:
        frame = cv2.resize(frame, (960, int(h * 960 / w)), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def spd_draw_rois(frame_rgb, rois):
    img = frame_rgb.copy()
    h, w = img.shape[:2]
    for name, (x1, x2), (y1, y2), color in rois:
        p1 = (int(w * x1 / 100), int(h * y1 / 100))
        p2 = (int(w * x2 / 100), int(h * y2 / 100))
        cv2.rectangle(img, p1, p2, color, max(2, w // 300))
        cv2.putText(img, name, (p1[0] + 4, p1[1] + int(h * 0.05)),
                    cv2.FONT_HERSHEY_SIMPLEX, max(0.6, w / 1200), color, 2)
    return img


@st.cache_data(show_spinner=False, max_entries=8)
def spd_motion(path, roi_a, roi_b, pix_thr, f_lo, f_hi, step):
    """두 감시 영역(A: 파울라인, B: 핀)의 프레임 간 변화량(%)을 구한다."""
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(f_lo))
    idxs, ma, mb = [], [], []
    hist_a, hist_b = deque(maxlen=step + 1), deque(maxlen=step + 1)

    def crop(gray, roi):
        (x1, x2), (y1, y2) = roi
        h, w = gray.shape
        ya, yb = int(h * y1 / 100), int(h * y2 / 100)
        xa, xb = int(w * x1 / 100), int(w * x2 / 100)
        return gray[ya:max(yb, ya + 1), xa:max(xb, xa + 1)]

    i = int(f_lo)
    while i <= int(f_hi):
        ok, frame = cap.read()
        if not ok:
            break
        w0 = frame.shape[1]
        if w0 > 480:
            frame = cv2.resize(frame, None, fx=480.0 / w0, fy=480.0 / w0, interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        hist_a.append(crop(gray, roi_a))
        hist_b.append(crop(gray, roi_b))
        if len(hist_a) == step + 1:
            ma.append(float((cv2.absdiff(hist_a[-1], hist_a[0]) > pix_thr).mean() * 100))
            mb.append(float((cv2.absdiff(hist_b[-1], hist_b[0]) > pix_thr).mean() * 100))
        else:
            ma.append(0.0)
            mb.append(0.0)
        idxs.append(i)
        i += 1
    cap.release()
    return np.array(idxs), np.array(ma), np.array(mb)


def spd_detect(idxs, ma, mb, thr_a, thr_b):
    """A영역이 처음 기준을 넘는 프레임 = 파울라인 통과, 그 이후 B영역이 처음 기준을 넘는 프레임 = 핀 타격."""
    if len(idxs) == 0:
        return None, None
    hit_a = np.where(ma >= thr_a)[0]
    if hit_a.size == 0:
        return None, None
    a = int(hit_a[0])
    hit_b = np.where((mb >= thr_b) & (np.arange(len(mb)) > a))[0]
    b = int(hit_b[0]) if hit_b.size else None
    return int(idxs[a]), (int(idxs[b]) if b is not None else None)


def spd_draw_lines(frame_rgb, y_foul, y_pin, lane_x, chain=None, marker=None, pin_box=None):
    """기준선(파울라인/1번 핀 또는 핀 영역 상자), 레인 범위, (선택) 추적된 공 궤적과 색 따오기 위치를 그린다."""
    img = frame_rgb.copy()
    h, w = img.shape[:2]
    th = max(2, w // 300)
    blue, orange = (30, 144, 255), (255, 140, 0)
    yy = int(h * y_foul / 100)
    cv2.line(img, (0, yy), (w, yy), blue, th)
    if pin_box is None:
        yy = int(h * y_pin / 100)
        cv2.line(img, (0, yy), (w, yy), orange, th)
    else:
        (bx1, bx2), (by1, by2) = pin_box
        cv2.rectangle(img, (int(w * bx1 / 100), int(h * by1 / 100)),
                      (int(w * bx2 / 100), int(h * by2 / 100)), orange, th)
    for x in lane_x:
        xx = int(w * x / 100)
        cv2.line(img, (xx, 0), (xx, h), (60, 200, 60), th)
    if chain:
        pts = [(int(w * c[1] / 100), int(h * c[2] / 100)) for c in chain]
        for p, q in zip(pts[:-1], pts[1:]):
            cv2.line(img, p, q, (255, 0, 0), max(1, th // 2))
        for p in pts:
            cv2.circle(img, p, max(3, w // 160), (255, 0, 0), -1)
    if marker:
        mx, my = int(w * marker[0] / 100), int(h * marker[1] / 100)
        r = max(8, w // 50)
        cv2.circle(img, (mx, my), r, (255, 255, 0), th)
        cv2.line(img, (mx - r, my), (mx + r, my), (255, 255, 0), 1)
        cv2.line(img, (mx, my - r), (mx, my + r), (255, 255, 0), 1)
    return img


def spd_crop(img, x_rng, y_center, half=5.0, out_w=900):
    """레인 가로 범위 × (y_center ± half)% 영역을 잘라 확대한다 (기준선을 정밀하게 맞출 때 사용)."""
    h, w = img.shape[:2]
    x0, x1 = int(w * max(x_rng[0] - 3, 0) / 100), int(w * min(x_rng[1] + 3, 100) / 100)
    y0, y1 = int(h * max(y_center - half, 0) / 100), int(h * min(y_center + half, 100) / 100)
    crop = img[y0:max(y1, y0 + 2), x0:max(x1, x0 + 2)]
    s = out_w / crop.shape[1]
    return cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)


def spd_color_params(hex_color, tol):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    h, s, v = cv2.cvtColor(np.uint8([[[r, g, b]]]), cv2.COLOR_RGB2HSV)[0, 0]
    return (int(h), int(s), int(v), int(tol))


def spd_color_mask(hsv, color):
    """HSV 이미지에서 지정한 색(색조 ± 허용 오차)에 해당하는 픽셀을 255로 표시."""
    h, s, v, tol = color
    dh = np.abs(hsv[..., 0].astype(np.int16) - h)
    dh = np.minimum(dh, 180 - dh)
    s_min, v_min = max(40, int(s * 0.5)), max(30, int(v * 0.4))
    return ((dh <= tol) & (hsv[..., 1] >= s_min) & (hsv[..., 2] >= v_min)).astype(np.uint8) * 255


def spd_color_preview(frame_rgb, color):
    img = frame_rgb.copy()
    mask = spd_color_mask(cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV), color)
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    img[mask > 0] = (0, 255, 0)
    return img


def spd_pick_color():
    """미리보기 프레임의 지정 위치(주변 중앙값)에서 공 색을 따온다."""
    path = st.session_state.get("spd_vid_path")
    img = spd_read_frame(path, st.session_state.get("trk_ref", 0)) if path else None
    if img is None:
        return
    h, w = img.shape[:2]
    cx = int(w * st.session_state.get("trk_sx", 50.0) / 100)
    cy = int(h * st.session_state.get("trk_sy", 50.0) / 100)
    r = max(2, w // 250)
    patch = img[max(cy - r, 0):cy + r + 1, max(cx - r, 0):cx + r + 1].reshape(-1, 3)
    rgb = np.median(patch, axis=0).astype(int)
    st.session_state["trk_color"] = "#%02x%02x%02x" % tuple(int(c) for c in rgb)


@st.cache_data(show_spinner=False, max_entries=8)
def spd_track(path, lane_x, y_foul, y_pin, d_rng, var_thr, f_lo, f_hi, color=None):
    """공 후보 (프레임, x%, y%)를 모은다. color가 없으면 배경 제거(움직임)로, 있으면 공 색상으로 찾는다."""
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(f_lo))
    sub = (cv2.createBackgroundSubtractorMOG2(history=150, varThreshold=float(var_thr), detectShadows=False)
           if color is None else None)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    y_lo, y_hi = sorted((y_foul, y_pin))
    m_foul = min(6.0, 0.35 * abs(y_foul - y_pin))  # 파울라인 바깥쪽은 보간 정확도를 위해 조금 더 포함
    m_pin = 0.5  # 핀 쪽은 핀 위쪽의 빨간 표시등 같은 잡음을 막기 위해 거의 포함하지 않음
    m_lo, m_hi = (m_pin, m_foul) if y_pin < y_foul else (m_foul, m_pin)
    cands = []
    i = int(f_lo)
    while i <= int(f_hi):
        ok, frame = cap.read()
        if not ok:
            break
        w0 = frame.shape[1]
        if w0 > 480:
            frame = cv2.resize(frame, None, fx=480.0 / w0, fy=480.0 / w0, interpolation=cv2.INTER_AREA)
        h, w = frame.shape[:2]
        if color is None:
            gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
            mask = sub.apply(gray)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.dilate(mask, kernel, iterations=1)
        else:
            hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (3, 3), 0), cv2.COLOR_BGR2HSV)
            mask = cv2.morphologyEx(spd_color_mask(hsv, color), cv2.MORPH_CLOSE, kernel)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        a_min = np.pi / 4 * (d_rng[0] / 100 * w) ** 2
        a_max = np.pi / 4 * (d_rng[1] / 100 * w) ** 2
        found = []
        for c in cnts:
            area = cv2.contourArea(c)
            if area < a_min or area > a_max:
                continue
            per = cv2.arcLength(c, True)
            if per <= 0:
                continue
            circ = 4 * np.pi * area / (per * per)
            _, _, bw, bh = cv2.boundingRect(c)
            if circ < 0.3 or max(bw, bh) / max(1, min(bw, bh)) > 3.0:
                continue
            m = cv2.moments(c)
            if m["m00"] == 0:
                continue
            cx, cy = m["m10"] / m["m00"] / w * 100, m["m01"] / m["m00"] / h * 100
            if not (lane_x[0] <= cx <= lane_x[1] and y_lo - m_lo <= cy <= y_hi + m_hi):
                continue
            found.append((circ, i, cx, cy))
        found.sort(reverse=True)
        cands.extend((f, cx, cy) for _, f, cx, cy in found[:3])
        i += 1
    cap.release()
    return cands


def spd_chain(cands, y_foul, y_pin, gap_max=4):
    """후보들 중 핀 방향으로 꾸준히 전진하는 가장 긴 궤적(공)을 찾는다.
    공이 튀면서 생기는 작은 되돌림(0.6%까지)은 허용하고, 제자리의 잡음은 순 전진량이 없어 탈락한다."""
    if len(cands) < 4:
        return []
    direction = 1.0 if y_pin > y_foul else -1.0
    pts = sorted(cands)
    n = len(pts)
    score = [0.0] * n
    prev = [-1] * n
    for j in range(n):
        fj, xj, yj = pts[j]
        for i in range(j - 1, -1, -1):
            fi, xi, yi = pts[i]
            gap = fj - fi
            if gap > gap_max:
                break
            if gap < 1:
                continue
            dy = (yj - yi) * direction
            if dy < -0.6 or dy > 8.0 * gap or abs(xj - xi) > 6.0 * gap:
                continue
            s = score[i] + dy + 0.001
            if s > score[j]:
                score[j] = s
                prev[j] = i
    j = int(np.argmax(score))
    chain = []
    while j != -1:
        chain.append(pts[j])
        j = prev[j]
    return chain[::-1]


def spd_cross(chain, y_foul, y_pin, fps):
    """궤적이 두 기준선을 지나는 시각을 프레임 사이까지 보간한다.
    기준선을 지나는 구간 주변 몇 점만 직선으로 맞추고, 궤적이 기준선까지 가지 않았으면 끝부분을 연장(추정)한다."""
    arr = np.array(chain, dtype=float)
    t = arr[:, 0] / fps
    y = arr[:, 2]
    out = []
    for yl in (y_foul, y_pin):
        k = next((i for i in range(len(y) - 1) if (y[i] - yl) * (y[i + 1] - yl) <= 0 and y[i] != y[i + 1]), None)
        if k is not None:
            lo, hi = max(0, k - 2), min(len(y), k + 4)
            c = np.polyfit(y[lo:hi], t[lo:hi], 1)
            out.append((float(np.polyval(c, yl)), False))
        else:
            near = np.argsort(np.abs(y - yl))[:8]
            c = np.polyfit(y[near], t[near], 1)
            out.append((float(np.polyval(c, yl)), True))
    return out


def spd_pin_impact(idxs, mb, thr, after_frame):
    """after_frame 이후 핀 영역의 변화가 처음 thr(%) 이상이 되는 프레임. 다음 프레임도 thr/2 이상이면 확정."""
    for k in range(len(idxs)):
        if idxs[k] <= after_frame:
            continue
        if mb[k] >= thr and (k + 1 >= len(mb) or mb[k + 1] >= thr * 0.5):
            return int(idxs[k])
    return None


def spd_step(delta):
    n = st.session_state.get("spd_nframes", 1)
    st.session_state["spd_frame"] = int(min(max(st.session_state.get("spd_frame", 0) + delta, 0), n - 1))


def spd_mark(key):
    fps = st.session_state.get("spd_fps", 30.0) or 30.0
    st.session_state[key] = round(st.session_state.get("spd_frame", 0) / fps, 3)


def spd_goto(key):
    fps = st.session_state.get("spd_fps", 30.0) or 30.0
    n = st.session_state.get("spd_nframes", 1)
    st.session_state["spd_frame"] = int(min(max(round(st.session_state.get(key, 0.0) * fps), 0), n - 1))


def spd_send_manual(t_start, t_end, fps):
    st.session_state["spd_t_start"] = round(float(t_start), 3)
    st.session_state["spd_t_end"] = round(float(t_end), 3)
    st.session_state["spd_frame"] = int(round(t_start * fps))
    st.session_state["spd_mode"] = MODE_MANUAL


# 탭 7: 구속 측정
with tab7:
    st.subheader("🚀 볼링공 구속 측정")
    st.caption("구속(km/h) = 레인 길이(m) ÷ 파울라인~핀 도달 시간(초) × 3.6 · 릴리스 속도가 아니라 파울라인~핀 구간의 **평균 속도**입니다.")

    # 다른 측정 방식으로 옮겨 다녀도 값이 유지되도록 매 실행마다 다시 저장
    for _k, _d in (("spd_frame", 0), ("spd_t_start", 0.0), ("spd_t_end", 0.0)):
        st.session_state[_k] = st.session_state.get(_k, _d)

    cs1, cs2 = st.columns(2)
    with cs1:
        lane_len = st.number_input(
            "레인 길이 (파울라인 ~ 1번 핀, m)", min_value=1.0, max_value=30.0,
            value=LANE_LENGTH_M, step=0.001, format="%.3f", key="spd_lane",
            help="규정상 파울라인에서 1번 핀 중심까지 60피트 = 18.288 m 입니다.")
    with cs2:
        slow_factor = st.number_input(
            "슬로모션 배율 (일반 영상은 1)", min_value=1.0, max_value=32.0,
            value=1.0, step=1.0, key="spd_slow",
            help="240fps 슬로모션을 30fps로 저장한 영상처럼 실제보다 N배 느리게 재생되는 영상이면 N을 입력하세요. 실제 시간 = 영상 시간 ÷ 배율")

    mode = st.radio("측정 방식", [MODE_TRACK, MODE_MANUAL, MODE_AUTO, MODE_DIRECT], horizontal=True, key="spd_mode")

    video_ok, video_path, up, info = False, None, None, None
    fps = 0.0
    if mode != MODE_DIRECT:
        if cv2 is None:
            st.error("영상 분석 라이브러리(OpenCV)가 없습니다. requirements.txt 에 `opencv-python-headless` 를 추가해 주세요. "
                     "(지금은 '시간 직접 입력' 방식만 쓸 수 있어요.)")
        else:
            up = st.file_uploader("🎬 투구 영상 업로드", type=VIDEO_TYPES, key="spd_upload",
                                  help="삼각대로 고정해 촬영한 영상이 가장 좋습니다. 투구 전후 10~20초로 짧게 자르면 분석이 빨라요.")
            if up is not None:
                video_path = spd_store_video(up)
                info = spd_video_info(video_path)
                if not info or info["n"] < 2 or info["fps"] <= 0:
                    st.error("영상 정보를 읽지 못했습니다. mp4(H.264) 형식으로 변환해서 다시 올려 주세요.")
                else:
                    video_ok = True
                    fps = info["fps"]
                    st.session_state["spd_fps"] = fps
                    st.session_state["spd_nframes"] = info["n"]
                    st.caption(f"{info['w']}×{info['h']} · {fps:.2f} fps · {info['n']} 프레임 · {info['n'] / fps:.1f} 초 "
                               f"(프레임 1칸 = {1000 / fps:.1f} ms)")
            else:
                st.info("영상을 올리면 시작할 수 있어요. 영상 없이 스톱워치로 잰 시간만 있다면 '시간 직접 입력'을 선택하세요.")

    elapsed = None          # 영상(또는 입력) 기준 걸린 시간(초)
    method_label = ""

    # ── 수동 ──
    if mode == MODE_MANUAL and video_ok:
        method_label = "수동"
        n = info["n"]
        with st.expander("▶ 원본 영상 재생 (대략적인 위치 확인용)", expanded=True):
            st.video(up)
        st.markdown("**① 프레임을 넘겨 보며 정확한 순간을 찾으세요**")
        nav = st.columns(4)
        nav[0].button("⏪ -10", on_click=spd_step, args=(-10,), key="spd_m10")
        nav[1].button("◀ -1", on_click=spd_step, args=(-1,), key="spd_m1")
        nav[2].button("+1 ▶", on_click=spd_step, args=(1,), key="spd_p1")
        nav[3].button("+10 ⏩", on_click=spd_step, args=(10,), key="spd_p10")
        st.slider("프레임 번호", 0, n - 1, key="spd_frame")
        fi = st.session_state["spd_frame"]
        img = spd_read_frame(video_path, fi)
        if img is not None:
            st.image(img, caption=f"프레임 {fi} / {n - 1}  ·  {fi / fps:.3f} 초")
        mk1, mk2 = st.columns(2)
        mk1.button("📍 이 프레임 = 파울라인 통과", on_click=spd_mark, args=("spd_t_start",),
                   type="primary", key="spd_mark_s")
        mk2.button("💥 이 프레임 = 핀 타격", on_click=spd_mark, args=("spd_t_end",),
                   type="primary", key="spd_mark_e")

        st.markdown("**② 지정된 시각 (숫자를 직접 고쳐도 됩니다)**")
        tc1, tc2 = st.columns(2)
        t_start = tc1.number_input("파울라인 통과 시각 (초)", min_value=0.0, step=0.001, format="%.3f", key="spd_t_start")
        t_end = tc2.number_input("핀 타격 시각 (초)", min_value=0.0, step=0.001, format="%.3f", key="spd_t_end")
        gc1, gc2 = st.columns(2)
        gc1.button("↩ 파울라인 시각 프레임으로 이동", on_click=spd_goto, args=("spd_t_start",), key="spd_go_s")
        gc2.button("↩ 핀 타격 시각 프레임으로 이동", on_click=spd_goto, args=("spd_t_end",), key="spd_go_e")

        if t_end > 0:
            th1, th2 = st.columns(2)
            im_s = spd_read_frame(video_path, min(int(round(t_start * fps)), n - 1))
            im_e = spd_read_frame(video_path, min(int(round(t_end * fps)), n - 1))
            if im_s is not None:
                th1.image(im_s, caption=f"파울라인 통과 ({t_start:.3f} 초)")
            if im_e is not None:
                th2.image(im_e, caption=f"핀 타격 ({t_end:.3f} 초)")
        elapsed = t_end - t_start

    # ── 자동 (공 추적) ──
    elif mode == MODE_TRACK and video_ok:
        method_label = "자동(추적)"
        n = info["n"]
        duration = n / fps
        st.markdown("**① 기준선과 영역 지정** — 🟦 파란 선: 파울라인(공이 손을 떠나 레인에 닿는 높이) · 🟩 초록 세로선: 공이 지나가는 레인 범위 · "
                    "🟧 주황 선/상자: 핀 쪽 기준. 카메라는 고정되어 있어야 하고, 비스듬히 찍어 레인이 납작하게 보여도 괜찮아요.")
        tl1, tl2 = st.columns(2)
        with tl1:
            y_foul = st.slider("파울라인 높이 (%, 화면 맨 위 = 0)", 0.0, 100.0, 88.0, 0.1, key="trk_yf")
            end_mode = st.radio("핀 도달 판정 방식", [END_MOTION, END_LINE], key="trk_end",
                                help="레인이 화면에서 납작하게 보이면 핀 근처에서 공이 거의 안 움직여 높이 선으로는 시각이 크게 흔들립니다. "
                                     "'핀이 움직이기 시작하는 순간'이 훨씬 정확해요.")
        with tl2:
            lane_x = st.slider("레인 가로 범위 (%)", 0.0, 100.0, (25.0, 75.0), 0.5, key="trk_x")
            d_rng = st.slider("공 지름 범위 (화면 가로 대비 %)", 0.3, 12.0, (0.8, 6.0), 0.1, key="trk_d",
                              help="가까울 때 가장 크고 핀 쪽으로 갈수록 작아지니, 두 경우를 모두 포함하도록 넓게 잡으세요.")
        if end_mode == END_LINE:
            y_pin = st.slider("1번 핀 높이 (%)", 0.0, 100.0, 18.0, 0.1, key="trk_yp")
            pin_x = pin_y = pin_thr = None
        else:
            pc1, pc2, pc3 = st.columns(3)
            pin_x = pc1.slider("핀 영역 가로 (%)", 0.0, 100.0, (40.0, 60.0), 0.5, key="trk_px")
            pin_y = pc2.slider("핀 영역 세로 (%)", 0.0, 100.0, (8.0, 20.0), 0.1, key="trk_py",
                               help="서 있는 핀들이 들어가는 상자입니다. 공이 핀에 닿기 직전의 높이가 상자 아래쪽 끝 근처가 되게 맞추세요.")
            pin_thr = pc3.slider("핀 움직임 감지 기준 (% 변화)", 0.05, 20.0, 0.2, 0.05, key="trk_pthr",
                                 help="작을수록 민감합니다. 아래 그래프에서 핀이 맞기 전 평평한 구간보다 높게 잡으세요.")
            y_pin = pin_y[1]
        trk_ref = st.slider("미리보기 프레임 (공이 보이는 장면으로)", 0, n - 1, 0, key="trk_ref")
        ref_img = spd_read_frame(video_path, trk_ref)

        use_color = st.checkbox("🎨 공 색상으로 추적 — 카메라를 손으로 들었거나 배경이 복잡할 때 추천 (검정·흰색·회색 공은 색 구분이 어려워 비추천)",
                                value=True, key="trk_color_on")
        color, marker = None, None
        if use_color:
            st.session_state.setdefault("trk_color", "#c8102e")
            cc1, cc2 = st.columns([1, 2])
            cc1.color_picker("공 색상", key="trk_color")
            tol = cc2.slider("색상 허용 오차", 3, 40, 12, key="trk_tol",
                             help="공이 일부만 초록색으로 표시되면 올리고, 바닥 등 다른 곳까지 표시되면 내리세요.")
            sp1, sp2, sp3 = st.columns([2, 2, 2])
            sp1.slider("색 따오기 위치 X (%)", 0.0, 100.0, 50.0, 0.1, key="trk_sx")
            sp2.slider("색 따오기 위치 Y (%)", 0.0, 100.0, 50.0, 0.1, key="trk_sy")
            sp3.button("📍 노란 원 위치의 색을 공 색으로", on_click=spd_pick_color, key="trk_pick",
                       help="미리보기에서 공이 보이는 프레임을 고르고, X/Y로 노란 원을 공 위에 올린 뒤 누르세요.")
            color = spd_color_params(st.session_state["trk_color"], tol)
            marker = (st.session_state["trk_sx"], st.session_state["trk_sy"])
        pin_box = (tuple(pin_x), tuple(pin_y)) if end_mode == END_MOTION else None
        if ref_img is not None:
            pv1, pv2 = st.columns(2)
            lines_img = spd_draw_lines(ref_img, y_foul, y_pin, lane_x, marker=marker, pin_box=pin_box)
            pv1.image(lines_img, caption="기준선 미리보기")
            if color is not None:
                pv2.image(spd_color_preview(ref_img, color),
                          caption="색 인식 미리보기 (초록 = 공 색으로 인식된 부분)")
            with st.expander("🔍 기준선 확대 보기 (정밀하게 맞출 때)"):
                z1, z2 = st.columns(2)
                z1.image(spd_crop(lines_img, lane_x, y_foul), caption="파울라인 부근")
                z2.image(spd_crop(lines_img, lane_x, y_pin), caption="핀 부근")

        st.markdown("**② 분석 설정**")
        t_lo, t_hi = st.slider("분석 구간 (초) — 투구 직전부터 핀에 닿은 직후까지", 0.0, float(duration),
                               (0.0, float(duration)), step=0.1, key="trk_range")
        var_thr = 20
        if not use_color:
            with st.expander("고급 설정 (공이 안 잡힐 때 조정)"):
                var_thr = st.slider("움직임 감지 민감도 (작을수록 민감)", 4, 60, 20, key="trk_var")

        valid_geo = abs(y_foul - y_pin) >= 3 and lane_x[0] < lane_x[1]
        if not valid_geo:
            st.warning("파울라인과 핀 쪽 기준은 3% 이상 떨어져 있어야 하고, 레인 가로 범위의 시작값이 끝값보다 작아야 합니다.")
        params = (float(y_foul), end_mode, float(y_pin), tuple(lane_x), tuple(d_rng), int(var_thr),
                  float(t_lo), float(t_hi), color, pin_box, pin_thr)
        if st.button("🎯 공 추적 실행", type="primary", key="trk_run", disabled=not valid_geo):
            f_lo, f_hi = int(t_lo * fps), min(int(t_hi * fps), n - 1)
            with st.spinner("공을 추적하는 중..."):
                cands = spd_track(video_path, tuple(lane_x), float(y_foul), float(y_pin), tuple(d_rng),
                                  int(var_thr), f_lo, f_hi, color)
                pin_series = None
                if pin_box is not None:
                    pin_series = spd_motion(video_path, pin_box, pin_box, 25, f_lo, f_hi,
                                            max(1, int(round(fps / 30))))
            st.session_state["trk_res"] = {"path": video_path, "cands": cands, "pin": pin_series, "params": params}

        res = st.session_state.get("trk_res")
        if res and res["path"] == video_path:
            if res["params"] != params:
                st.info("설정이 바뀌었습니다. 다시 **공 추적 실행**을 눌러 주세요.")
            else:
                chain = spd_chain(res["cands"], y_foul, y_pin)
                span = abs(y_foul - y_pin)
                progress = abs(chain[-1][2] - chain[0][2]) if chain else 0.0
                if len(chain) < 6 or progress < 0.4 * span:
                    st.warning(
                        f"공의 궤적을 충분히 찾지 못했습니다 (후보 {len(res['cands'])}개). "
                        "분석 구간을 투구 시점으로 좁히거나, 공 지름 범위·레인 가로 범위를 조정해 보세요. "
                        "색상 추적이면 '색 인식 미리보기'에서 공이 초록색으로 보이는지 확인하고 색/허용 오차를 맞추세요. "
                        "움직임 추적이면 민감도를 낮추거나 색상 추적을 써 보세요. 계속 안 되면 '수동' 방식을 쓰세요.")
                else:
                    (ta, est_a), (tb, est_b) = spd_cross(chain, y_foul, y_pin, fps)
                    pin_fig = None
                    if end_mode == END_MOTION:
                        pidx, _, pmb = res["pin"]
                        impact = spd_pin_impact(pidx, pmb, pin_thr, chain[0][0])
                        tb, est_b = (None, False) if impact is None else ((impact - 0.5) / fps, False)
                        pin_fig = go.Figure(go.Scatter(x=pidx / fps, y=pmb, mode="lines", name="핀 영역 변화",
                                                       line=dict(color="#ff8c00")))
                        pin_fig.add_hline(y=pin_thr, line_dash="dot", line_color="#888", annotation_text="감지 기준")
                        if tb is not None:
                            pin_fig.add_vline(x=tb, line_dash="dash", line_color="#ff8c00", annotation_text="핀 타격")
                        pin_fig.update_layout(title="핀 영역의 움직임 (프레임 간 변화 %)", xaxis_title="영상 시간 (초)",
                                              yaxis_title="변화 %", height=260, margin=dict(l=20, r=10, t=50, b=20))

                    mid_img = spd_read_frame(video_path, int(chain[len(chain) // 2][0]))
                    if mid_img is not None:
                        st.image(spd_draw_lines(mid_img, y_foul, y_pin, lane_x, chain, pin_box=pin_box),
                                 caption=f"추적된 공 궤적 (빨간 점 {len(chain)}개)")

                    fig_t = go.Figure(go.Scatter(x=[c[0] / fps for c in chain], y=[c[2] for c in chain],
                                                 mode="markers+lines", name="공 위치", line=dict(color="#d62728")))
                    fig_t.add_hline(y=y_foul, line_dash="dot", line_color="#1e90ff", annotation_text="파울라인")
                    if end_mode == END_LINE:
                        fig_t.add_hline(y=y_pin, line_dash="dot", line_color="#ff8c00", annotation_text="1번 핀")
                    fig_t.add_vline(x=ta, line_dash="dash", line_color="#1e90ff")
                    if tb is not None:
                        fig_t.add_vline(x=tb, line_dash="dash", line_color="#ff8c00")
                    fig_t.update_layout(title="시간에 따른 공의 화면 높이", xaxis_title="영상 시간 (초)",
                                        yaxis=dict(title="화면 높이 (%)", autorange="reversed"),
                                        height=320, margin=dict(l=20, r=10, t=50, b=20))
                    stretch(st.plotly_chart, fig_t)
                    if pin_fig is not None:
                        stretch(st.plotly_chart, pin_fig)

                    if tb is None:
                        st.warning("핀이 움직이는 순간을 찾지 못했습니다. 핀 영역 상자를 핀에 맞추거나 감지 기준을 낮춰 보세요.")
                    else:
                        how = "핀 움직임 감지" if end_mode == END_MOTION else "1번 핀 높이 선 통과"
                        st.success(f"파울라인 통과 {ta:.3f} 초 → 핀 도달 {tb:.3f} 초 ({how})")
                        if est_a or est_b:
                            st.caption("⚠️ 공이 기준선까지 찍히지 않아 일부 시각은 궤적을 연장해 추정한 값입니다. 결과가 이상하면 수동으로 확인하세요.")
                        # 기준선이 조금 어긋났을 때 결과가 얼마나 흔들리는지
                        dlt, speeds = 0.3, []
                        for dyf in (-dlt, 0.0, dlt):
                            for dyp in ((-dlt, 0.0, dlt) if end_mode == END_LINE else (0.0,)):
                                (ta2, _), (tb2, _) = spd_cross(chain, y_foul + dyf, y_pin + dyp, fps)
                                tb2 = tb2 if end_mode == END_LINE else tb
                                if tb2 - ta2 > 0.2:
                                    speeds.append(lane_len / ((tb2 - ta2) / slow_factor) * 3.6)
                        if speeds:
                            st.caption(f"📐 기준선 높이가 화면 높이의 ±{dlt}% 어긋나면 구속이 약 {min(speeds):.1f} ~ {max(speeds):.1f} km/h 로 달라집니다.")
                        st.button("✋ 이 값을 수동 모드로 가져가 확인/미세 조정", on_click=spd_send_manual,
                                  args=(max(ta, 0.0), max(tb, 0.0), fps), key="trk_to_manual")
                        elapsed = tb - ta
        else:
            st.info("기준선을 맞춘 뒤 **공 추적 실행**을 눌러 주세요.")

    # ── 자동 (영역 변화 감지) ──
    elif mode == MODE_AUTO and video_ok:
        method_label = "자동"
        n = info["n"]
        duration = n / fps
        st.markdown("**① 감시 영역 지정** — 카메라는 고정되어 있어야 합니다. 파란 영역(A)은 파울라인 바로 앞 레인, 주황 영역(B)은 핀 데크에 맞추세요.")
        ra, rb = st.columns(2)
        with ra:
            st.markdown("🟦 **A: 파울라인 영역**")
            fx = st.slider("A 가로 범위 (%)", 0, 100, (25, 75), key="spd_fx")
            fy = st.slider("A 세로 범위 (%)", 0, 100, (75, 95), key="spd_fy")
        with rb:
            st.markdown("🟧 **B: 핀 영역**")
            pnx = st.slider("B 가로 범위 (%)", 0, 100, (40, 60), key="spd_px")
            pny = st.slider("B 세로 범위 (%)", 0, 100, (5, 25), key="spd_py")
        ref_idx = st.slider("미리보기 프레임", 0, n - 1, 0, key="spd_ref")
        ref_img = spd_read_frame(video_path, ref_idx)
        if ref_img is not None:
            st.image(spd_draw_rois(ref_img, [("A", fx, fy, (30, 144, 255)), ("B", pnx, pny, (255, 140, 0))]),
                     caption="감시 영역 미리보기")

        st.markdown("**② 분석 설정**")
        t_lo, t_hi = st.slider("분석 구간 (초) — 투구 직전부터 핀이 쓰러진 직후까지만", 0.0, float(duration),
                               (0.0, float(duration)), step=0.1, key="spd_range")
        with st.expander("고급 설정 (감지가 잘 안 될 때 조정)"):
            pix_thr = st.slider("픽셀 변화 민감도 (작을수록 민감)", 5, 80, 25, key="spd_pix")

        region_ok = fx[0] < fx[1] and fy[0] < fy[1] and pnx[0] < pnx[1] and pny[0] < pny[1]
        if not region_ok:
            st.warning("감시 영역의 범위가 올바르지 않습니다. 시작값이 끝값보다 작아야 합니다.")
        if st.button("🔍 영상 분석 실행", type="primary", key="spd_run", disabled=not region_ok):
            step = max(1, int(round(fps / 30)))
            with st.spinner("영상을 분석하는 중..."):
                series = spd_motion(video_path, (fx, fy), (pnx, pny), int(pix_thr),
                                    int(t_lo * fps), min(int(t_hi * fps), n - 1), step)
            st.session_state["spd_series"] = {"path": video_path, "data": series}

        ser = st.session_state.get("spd_series")
        if ser and ser["path"] == video_path:
            idxs, ma, mb = ser["data"]
            if len(idxs) == 0:
                st.error("분석할 프레임을 읽지 못했습니다. 분석 구간을 확인해 주세요.")
            else:
                st.markdown("**③ 감지 기준** — 그래프를 보고 기준선(점선)을 조정하세요.")
                dc1, dc2 = st.columns(2)
                thr_a = dc1.slider("A(파울라인) 감지 기준 (% 변화)", 0.1, 50.0, 1.0, 0.1, key="spd_thr_a")
                thr_b = dc2.slider("B(핀) 감지 기준 (% 변화)", 0.5, 80.0, 8.0, 0.5, key="spd_thr_b")
                fa, fb = spd_detect(idxs, ma, mb, thr_a, thr_b)

                tt = idxs / fps
                fig_m = go.Figure()
                fig_m.add_trace(go.Scatter(x=tt, y=ma, mode="lines", name="A 파울라인 영역", line=dict(color="#1e90ff")))
                fig_m.add_trace(go.Scatter(x=tt, y=mb, mode="lines", name="B 핀 영역", line=dict(color="#ff8c00")))
                fig_m.add_hline(y=thr_a, line_dash="dot", line_color="#1e90ff")
                fig_m.add_hline(y=thr_b, line_dash="dot", line_color="#ff8c00")
                if fa is not None:
                    fig_m.add_vline(x=fa / fps, line_dash="dash", line_color="#1e90ff", annotation_text="파울라인")
                if fb is not None:
                    fig_m.add_vline(x=fb / fps, line_dash="dash", line_color="#ff8c00", annotation_text="핀 타격")
                fig_m.update_layout(title="영역별 움직임 (프레임 간 변화 %)", xaxis_title="영상 시간 (초)",
                                    yaxis_title="변화 %", height=320, margin=dict(l=20, r=10, t=50, b=20))
                stretch(st.plotly_chart, fig_m)

                if fa is None:
                    st.warning("파울라인 통과를 감지하지 못했습니다. A 기준을 낮추거나 A 영역을 공이 지나는 레인 쪽으로 좁혀 보세요.")
                elif fb is None:
                    st.warning("핀 타격을 감지하지 못했습니다. B 기준을 낮추거나 B 영역을 핀 전체가 들어오게 조정해 보세요.")
                else:
                    ta, tb = fa / fps, fb / fps
                    st.success(f"파울라인 통과 {ta:.3f} 초 (프레임 {fa}) → 핀 타격 {tb:.3f} 초 (프레임 {fb})")
                    sa, sb = st.columns(2)
                    ia, ib = spd_read_frame(video_path, fa), spd_read_frame(video_path, fb)
                    if ia is not None:
                        sa.image(ia, caption="감지된 파울라인 통과 프레임")
                    if ib is not None:
                        sb.image(ib, caption="감지된 핀 타격 프레임")
                    st.button("✋ 이 값을 수동 모드로 가져가 미세 조정", on_click=spd_send_manual,
                              args=(ta, tb, fps), key="spd_to_manual")
                    elapsed = tb - ta
        else:
            st.info("감시 영역을 맞춘 뒤 **영상 분석 실행**을 눌러 주세요.")

    # ── 직접 입력 ──
    elif mode == MODE_DIRECT:
        method_label = "직접입력"
        elapsed = st.number_input("파울라인 → 핀까지 걸린 시간 (초)", min_value=0.1, max_value=20.0,
                                  value=2.5, step=0.01, format="%.3f", key="spd_direct")

    # ── 결과 ──
    st.divider()
    if elapsed is not None and elapsed <= 0:
        st.warning("핀 타격 시각이 파울라인 통과 시각보다 늦어야 합니다.")
    elif elapsed is not None:
        real_t = elapsed / slow_factor
        ms = lane_len / real_t
        kmh = ms * 3.6
        mph = kmh / 1.609344

        rc = st.columns(4)
        rc[0].metric("🚀 구속", f"{kmh:.1f} km/h")
        rc[1].metric("mph", f"{mph:.1f}")
        rc[2].metric("실제 걸린 시간", f"{real_t:.3f} 초")
        rc[3].metric("초속", f"{ms:.2f} m/s")

        if video_ok and mode != MODE_DIRECT:
            err = 1.0 / fps / slow_factor
            if real_t - err > 0:
                st.caption(f"±1프레임({err * 1000:.0f} ms) 오차 범위: "
                           f"{lane_len / (real_t + err) * 3.6:.1f} ~ {lane_len / (real_t - err) * 3.6:.1f} km/h")
        if kmh < 10 or kmh > 45:
            st.warning("일반적인 구속(대략 20~35 km/h)과 차이가 큽니다. 시각, 슬로모션 배율, 레인 길이를 다시 확인해 보세요.")

        with st.form("speed_form"):
            sf1, sf2, sf3 = st.columns([1, 1, 2])
            s_date = sf1.date_input("측정 날짜", datetime.today())
            s_ball = sf2.selectbox("사용한 볼", [NO_BALL] + ball_names)
            s_memo = sf3.text_input("메모", placeholder="예: 3번 레인, 훅 많이 줌")
            if st.form_submit_button("💾 구속 기록 저장"):
                row = {
                    'Date': pd.to_datetime(s_date),
                    'Ball': "" if s_ball == NO_BALL else s_ball,
                    'Time_s': round(real_t, 3),
                    'Distance_m': round(lane_len, 3),
                    'Speed_kmh': round(kmh, 2),
                    'Method': method_label,
                    'Memo': s_memo.strip(),
                }
                new_df = add_row(speed_df, row).sort_values('Date', kind='stable').reset_index(drop=True)
                if save_csv_to_github(new_df, SPEED_FILE, speed_sha, "구속 기록 추가"):
                    flash(f"{kmh:.1f} km/h 기록이 저장되었습니다!")
                    st.rerun()

    # ── 기록 ──
    st.divider()
    st.subheader("📊 구속 기록")
    if speed_df.empty:
        st.caption("저장된 구속 기록이 없습니다. 위에서 측정한 뒤 '구속 기록 저장'을 눌러 보세요.")
    else:
        sp = speed_df.copy()
        sc = st.columns(3)
        sc[0].metric("측정 횟수", f"{len(sp)} 회")
        sc[1].metric("평균 구속", f"{sp['Speed_kmh'].mean():.1f} km/h")
        sc[2].metric("최고 구속", f"{sp['Speed_kmh'].max():.1f} km/h")

        fig_sp = px.line(sp, x='Date', y='Speed_kmh', markers=True, hover_data=['Ball', 'Method', 'Memo'],
                         title="구속 추이", labels={'Date': '날짜', 'Speed_kmh': '구속 (km/h)'})
        stretch(st.plotly_chart, fig_sp)

        by_ball = sp.assign(Ball=sp['Ball'].replace('', '(미지정)')).groupby('Ball').agg(
            측정횟수=('Speed_kmh', 'count'), 평균구속=('Speed_kmh', 'mean'), 최고구속=('Speed_kmh', 'max')
        ).reset_index()
        by_ball['평균구속'] = by_ball['평균구속'].round(1)
        by_ball['최고구속'] = by_ball['최고구속'].round(1)
        stretch(st.dataframe, by_ball.rename(columns={'Ball': '볼'}), hide_index=True)

        st.caption("💡 표에서 메모를 고치거나 행을 삭제한 뒤 **'구속 기록 변경사항 저장'**을 누르세요.")
        edit_sp = sp.sort_values('Date', ascending=False, kind='stable').reset_index(drop=True)
        edit_sp['Date'] = edit_sp['Date'].dt.date
        edited_sp = stretch(
            st.data_editor, edit_sp, num_rows="dynamic", key="speed_editor",
            column_config={
                "Date": st.column_config.DateColumn("날짜", format="YYYY-MM-DD", required=True),
                "Ball": st.column_config.TextColumn("볼"),
                "Time_s": st.column_config.NumberColumn("시간(초)", format="%.3f"),
                "Distance_m": st.column_config.NumberColumn("거리(m)", format="%.3f"),
                "Speed_kmh": st.column_config.NumberColumn("구속(km/h)", format="%.2f", required=True),
                "Method": st.column_config.TextColumn("방식"),
                "Memo": st.column_config.TextColumn("메모"),
            })
        if st.button("💾 구속 기록 변경사항 저장", key="save_speed"):
            cleaned_sp = edited_sp.dropna(subset=['Date', 'Speed_kmh']).copy()
            cleaned_sp['Date'] = pd.to_datetime(cleaned_sp['Date'])
            cleaned_sp = cleaned_sp.sort_values('Date', kind='stable').reset_index(drop=True)
            if save_csv_to_github(cleaned_sp, SPEED_FILE, speed_sha, "구속 기록 수정"):
                flash("구속 기록 변경사항이 저장되었습니다!")
                st.rerun()
# --- 코드 끝 ---
