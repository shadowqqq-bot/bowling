import re
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from github import Github, GithubException
from io import StringIO

st.set_page_config(page_title="볼링 에버리지 트래커", page_icon="🎳", layout="wide")
st.markdown("<h1 style='font-size: 24px;'>🎳 김형용 - 볼링 에버리지 기록 & 분석</h1>", unsafe_allow_html=True)

DATA_FILE = "bowling_records.csv"
LESSON_FILE = "bowling_lessons.csv"
THEORY_FILE = "bowling_theory.csv"
BALL_FILE = "bowling_balls.csv"
DEFAULT_ALLEY = "덕우스핀볼링장"
NO_BALL = "(선택 안 함)"

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
# --- 코드 끝 ---
