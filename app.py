
# ARS Canvas v3 (JP UI)
import streamlit as st
import sqlite3, re
import pandas as pd
from datetime import datetime, timedelta
from dateutil import tz
import random, uuid
from contextlib import contextmanager
import qrcode
from streamlit_autorefresh import st_autorefresh
import os
DEFAULT_BASE_URL = os.getenv("ARS_BASE_URL", "https://arsystem.streamlit.app")
from io import BytesIO

# ---------- Theme & Styles (Focus: readability + friendly spacing) ----------
PAGE_CSS = """
<style>
:root{
  --radius:18px;
  --pad-comfy:18px;
  --pad-cozy:14px;
  --pad-compact:10px;
  --fg:#0f172a;
  --bg:#ffffff;
  --sub:#64748b;
  --hi:#111827;
  --border:#e5e7eb;
}
.block-container{padding-top:0.5rem; padding-bottom:2rem; max-width:1200px;}
header[data-testid="stHeader"]{backdrop-filter: blur(4px);}
/* Sticky tools */
.sticky-tools{ position: sticky; top: 0; z-index: 50; padding: .5rem 0 .75rem;
  background: linear-gradient(180deg, rgba(255,255,255,.95), rgba(255,255,255,.85)); border-bottom:1px solid #eef0f3;}
/* Card */
.ars-card{ border-radius:var(--radius); border:1px solid var(--border);
  background:linear-gradient(180deg,#fff,#fafbfc); box-shadow:0 0 0 1px rgba(0,0,0,0.01), 0 18px 28px -24px rgba(2,6,23,.35);
  padding: var(--pad);}
.ars-meta{ color: var(--sub); font-size:.85rem }
.ars-chip{ display:inline-block; padding:.25rem .6rem; border-radius:999px; border:1px solid var(--border); background:#fff; margin-right:.35rem; font-size:.8rem;}
/* Buttons (bigger hit area) */
button[kind="secondary"], button[kind="primary"]{ padding:.6rem .9rem; border-radius:14px; }
/* Focus */
.ars-focus{ font-size: clamp(34px, 7.5vw, 72px); line-height:1.18; font-weight:800; letter-spacing:.2px; }
/* Line clamp for long comments */
.clamp-4{ display:-webkit-box; -webkit-line-clamp:4; -webkit-box-orient:vertical; overflow:hidden; }
/* High contrast */
.high-contrast .ars-card{ background:#000; color:#fff; border-color:#222;}
.high-contrast .ars-meta{ color:#cbd5e1; }
.high-contrast .stMarkdown, .high-contrast h1,h2,h3,h4{ color:#fff !important;}
/* Grid container */
.grid{ display:grid; grid-template-columns: repeat(var(--cols), 1fr); gap: 12px; }
</style>
"""

# ---------- DB Helpers ----------
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "ars.sqlite")

def _dict_factory(cursor, row):
    return { col[0]: row[idx] for idx, col in enumerate(cursor.description) }

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = _dict_factory
    try:
        yield conn
    finally:
        conn.commit(); conn.close()

def init_db():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS rooms(
            code TEXT PRIMARY KEY,
            title TEXT,
            created_at TEXT,
            focus_comment_id INTEGER,
            admin_pin TEXT,
            is_closed INTEGER DEFAULT 0
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS comments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_code TEXT,
            author TEXT,
            content TEXT,
            votes INTEGER DEFAULT 0,
            tags TEXT DEFAULT '',
            hidden INTEGER DEFAULT 0,
            created_at TEXT
        )""")
        # migrations: ensure hidden column exists
        cols = [r["name"] for r in c.execute("PRAGMA table_info(comments)").fetchall()]
        if "hidden" not in cols:
            c.execute("ALTER TABLE comments ADD COLUMN hidden INTEGER DEFAULT 0")

def is_valid_code(code:str)->bool:
    return bool(re.fullmatch(r"\d{6}", code or ""))

def ensure_room_by_code(code):
    with get_db() as conn:
        return conn.cursor().execute("SELECT * FROM rooms WHERE code=?", (code,)).fetchone()

def create_room(title, admin_pin=None, code=None):
    if code and not is_valid_code(code): raise ValueError("ルームIDは6桁の数字です。")
    code = code or ''.join(random.choices('0123456789', k=6))
    with get_db() as conn:
        c = conn.cursor()
        if ensure_room_by_code(code): raise ValueError("そのルームIDは使用中です。")
        c.execute("INSERT INTO rooms(code,title,created_at,admin_pin) VALUES(?,?,?,?)",
                  (code, title or "Session", datetime.utcnow().isoformat(), admin_pin or ""))
    return code

def add_comment(room_code, author, content):
    if not content or not content.strip(): return
    with get_db() as conn:
        c = conn.cursor()
        r = c.execute("SELECT is_closed FROM rooms WHERE code=?", (room_code,)).fetchone()
        if not r or int(r["is_closed"])==1: return
        c.execute("""INSERT INTO comments(room_code, author, content, created_at)
                     VALUES(?,?,?,?)""", (room_code, author or "", content.strip(), datetime.utcnow().isoformat()))

def vote_comment(comment_id, delta=1):
    with get_db() as conn:
        conn.cursor().execute("UPDATE comments SET votes = COALESCE(votes,0)+? WHERE id=?", (delta, comment_id))

def set_focus(room_code, comment_id):
    with get_db() as conn:
        conn.cursor().execute("UPDATE rooms SET focus_comment_id=? WHERE code=?", (comment_id, room_code))

def tag_comment(comment_id, tag):
    with get_db() as conn:
        c = conn.cursor()
        row = c.execute("SELECT tags FROM comments WHERE id=?", (comment_id,)).fetchone()
        if not row: return
        tags = [t for t in (row["tags"] or "").split(",") if t]
        if tag and tag not in tags: tags.append(tag)
        c.execute("UPDATE comments SET tags=? WHERE id=?", (",".join(tags), comment_id))

def hide_comment(comment_id, hide=True):
    with get_db() as conn:
        conn.cursor().execute("UPDATE comments SET hidden=? WHERE id=?", (1 if hide else 0, comment_id))

def get_comments(room_code, keyword=None, include_hidden=False):
    with get_db() as conn:
        c = conn.cursor()
        sql = "SELECT * FROM comments WHERE room_code=?"
        args = [room_code]
        if not include_hidden: sql += " AND hidden=0"
        if keyword:
            sql += " AND content LIKE ?"; args.append(f"%{keyword}%")
        sql += " ORDER BY votes DESC, created_at DESC"
        return c.execute(sql, tuple(args)).fetchall()

def get_room(room_code):
    with get_db() as conn:
        return conn.cursor().execute("SELECT * FROM rooms WHERE code=?", (room_code,)).fetchone()

def set_room_closed(room_code, closed:bool):
    with get_db() as conn:
        conn.cursor().execute("UPDATE rooms SET is_closed=? WHERE code=?", (1 if closed else 0, room_code))

# ---------- App ----------
st.set_page_config(page_title="ARS Canvas v3", page_icon="💬", layout="wide")
init_db()
st.markdown(PAGE_CSS, unsafe_allow_html=True)

if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = datetime.utcnow().isoformat()

# Role & global UI
st.sidebar.header("ARS Canvas v3")
mode = st.sidebar.radio("ロール", ["参加者", "司会者", "プロジェクター"], horizontal=True)

hc = st.sidebar.toggle("高コントラスト（プロジェクター向け）", value=False)
font_scale = st.sidebar.slider("文字サイズ", 0.9, 1.7, 1.15, 0.05)
density = st.sidebar.selectbox("表示密度", ["Comfy","Cozy","Compact"], index=1)
pad = {"Comfy":"var(--pad-comfy)","Cozy":"var(--pad-cozy)","Compact":"var(--pad-compact)"}[density]
cols = st.sidebar.slider("グリッド列（参加者のグリッド表示）", 1, 3, 2)

st.markdown(f'<div class="{"high-contrast" if hc else ""}" style="font-size:{font_scale}rem; --pad:{pad}; --cols:{cols};">',
            unsafe_allow_html=True)

# Room selection (6-digit)
qp = st.query_params
if "room" in qp and "room_code" not in st.session_state:
    code_from_url = qp.get("room")
    if isinstance(code_from_url, (list, tuple)):
        code_from_url = code_from_url[0] if code_from_url else ""
    if is_valid_code(code_from_url) and ensure_room_by_code(code_from_url):
        st.session_state["room_code"] = code_from_url

with st.sidebar.expander("ルーム作成（6桁）", expanded=False):
    new_title = st.text_input("タイトル", value="Session")
    desired = st.text_input("カスタムID（6桁数字）", placeholder="例: 128947")
    admin_pin = st.text_input("司会者PIN（任意）", type="password")
    if st.button("作成", use_container_width=True):
        try:
            code = create_room(new_title, admin_pin=admin_pin, code=desired or None)
            st.session_state["room_code"] = code
            st.success(f"作成しました: {code}")
            st.query_params.update(room=code)
        except Exception as e:
            st.error(str(e))

join_code = st.sidebar.text_input("参加ID（6桁）", value=st.session_state.get("room_code","")).strip()
if st.sidebar.button("参加", use_container_width=True):
    if is_valid_code(join_code) and ensure_room_by_code(join_code):
        st.session_state["room_code"] = join_code
        st.query_params.update(room=join_code)
    else:
        st.sidebar.error("ルームが見つかりません。")

room_code = st.session_state.get("room_code")
if not room_code:
    st.info("ルームを作成または参加してください。")
    st.stop()

room = get_room(room_code)
if not room:
    st.error("そのルームは存在しません。"); st.stop()

# Sticky header
with st.container():
    st.markdown('<div class="sticky-tools">', unsafe_allow_html=True)
    top_left, top_mid, top_right = st.columns([2,4,2])
    with top_left:
        st.subheader(f"Room: {room_code}")
        st.caption(room.get("title",""))
    with top_mid:
        sort = st.segmented_control("ソート", options=["人気順","新着"], default="人気順")
    with top_right:
        refresh_ms = st.slider("自動更新(ms)", 1000, 5000, 2000, 250, help="会場では 2000ms 推奨")
    st.markdown('</div>', unsafe_allow_html=True)

# QR absolute link builder
with st.expander("参加用URLとQR"):
    # 固定のベースURLを使用（?room=CODE を付与）
    join_link = f"{DEFAULT_BASE_URL}/?room={room_code}"
    st.text_input("参加URL（配布用）", value=join_link, disabled=True)
    st.caption("このURLをスマホで開けば、そのままルームに参加できます。")

    # QRコード
    buf = BytesIO()
    qrcode.make(join_link).save(buf, format="PNG"); buf.seek(0)
    st.image(buf, caption="スマホで読み取り（URLを開くだけで参加）", width=180)

    # 参加案内（スクリーンに表示する想定）
    st.markdown("""
**参加のしかた**
1. スマホで **上記URL** を開く（またはQRを読み取り）  
2. 画面上部のロールを **「参加者」** にする  
3. そのまま投稿・👍投票ができます  
   ※ もしトップ画面に来た場合は、サイドバーの **「参加ID」** に **{room_code}** を入力してください。
""")

# Auto refresh & last refresh tracking
st_autorefresh(interval=refresh_ms, key="refresh")
last_seen = pd.to_datetime(st.session_state.last_refresh)
# Admin PIN helper
def is_admin_ok():
    if not room.get("admin_pin"): return True
    if st.session_state.get("pin_ok", False): return True
    pin = st.sidebar.text_input("司会者PINを入力", type="password", key="pin_input")
    if st.sidebar.button("ロック解除", key="unlock_btn"):
        if pin == room.get("admin_pin"):
            st.session_state["pin_ok"] = True; st.sidebar.success("解除しました")
        else:
            st.sidebar.error("PINが違います")
    return st.session_state.get("pin_ok", False)

# ---------- PARTICIPANT ----------
if mode == "参加者":
    if room.get("is_closed")==1:
        st.warning("投稿はクローズされています（司会者が再開できます）。")
    left, right = st.columns([2,1])
    with left:
        kw = st.text_input("キーワード絞り込み", placeholder="例: マイク, 事例, 照明 など")
        rows = get_comments(room_code, keyword=kw)
        if sort == "新着":
            rows = sorted(rows, key=lambda x: x["created_at"], reverse=True)

        # List or Grid
        use_grid = st.toggle("グリッド表示", value=(cols>1))
        new_badge = lambda created: " 🆕" if pd.to_datetime(created) > last_seen else ""
        if use_grid and cols>1:
            st.markdown('<div class="grid">', unsafe_allow_html=True)
            for r in rows[:300]:
                st.markdown(f'<div class="ars-card">', unsafe_allow_html=True)
                st.markdown(f'**{r["content"]}**{new_badge(r["created_at"])}')
                meta = f'👍 {r["votes"]} ・ {pd.to_datetime(r["created_at"]).strftime("%H:%M")}'
                st.markdown(f'<div class="ars-meta">{meta}</div>', unsafe_allow_html=True)
                if r["tags"]:
                    for t in r["tags"].split(","):
                        st.markdown(f'<span class="ars-chip">#{t}</span>', unsafe_allow_html=True)
                if st.button(f'👍 {r["votes"]}', key=f"up_{r['id']}"):
                    vote_comment(r["id"], 1); st.experimental_rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            for r in rows[:300]:
                st.markdown(f'<div class="ars-card">', unsafe_allow_html=True)
                st.markdown(f'**{r["content"]}**{new_badge(r["created_at"])}')
                meta = f'👍 {r["votes"]} ・ {pd.to_datetime(r["created_at"]).strftime("%H:%M")}'
                st.markdown(f'<div class="ars-meta">{meta}</div>', unsafe_allow_html=True)
                if r["tags"]:
                    for t in r["tags"].split(","):
                        st.markdown(f'<span class="ars-chip">#{t}</span>', unsafe_allow_html=True)
                if st.button(f'👍 {r["votes"]}', key=f"up_{r['id']}"):
                    vote_comment(r["id"], 1); st.experimental_rerun()
                st.markdown('</div>', unsafe_allow_html=True)

    with right:
        st.markdown("### 投稿")
        with st.form("compose"):
            author = st.text_input("名前（任意）", placeholder="匿名可")
            content = st.text_area("発言・質問", height=140, placeholder="シンプルに1メッセージ1アイデアで")
            submitted = st.form_submit_button("送信（Ctrl/Cmd+Enterでも可）", type="primary", use_container_width=True)
            if submitted:
                add_comment(room_code, author, content)
                st.success("送信しました")
                st.session_state.last_refresh = datetime.utcnow().isoformat()
                st.experimental_rerun()

# ---------- ORGANIZER ----------
elif mode == "司会者":
    if not is_admin_ok(): st.stop()

    tabs = st.tabs(["キュー", "クラスタ", "ルーム設定"])

    with tabs[0]:
        kw = st.text_input("フィルタ", placeholder="キーワードで絞り込み")
        rows = get_comments(room_code, keyword=kw, include_hidden=True)
        if sort == "新着":
            rows = sorted(rows, key=lambda x: x["created_at"], reverse=True)

        for r in rows[:400]:
            st.markdown(f'<div class="ars-card">', unsafe_allow_html=True)
            c1, c2, c3, c4, c5 = st.columns([8,1,1,2,2])
            with c1:
                hidden_mark = "（非表示）" if r["hidden"]==1 else ""
                st.markdown(f'**{r["content"]}** {hidden_mark}')
                if r["tags"]:
                    for t in r["tags"].split(","):
                        st.markdown(f'<span class="ars-chip">#{t}</span>', unsafe_allow_html=True)
                st.caption(f'👍 {r["votes"]} ・ {pd.to_datetime(r["created_at"]).strftime("%H:%M")} ・ ID {r["id"]}')
            with c2:
                if st.button("Focus", key=f"fc_{r['id']}"):
                    set_focus(room_code, r["id"]); st.toast("フォーカスしました")
            with c3:
                if st.button(f"👍 {r['votes']}", key=f"up_org_{r['id']}"):
                    vote_comment(r["id"], 1); st.experimental_rerun()
            with c4:
                tag = st.text_input("タグ", key=f"tg_{r['id']}", label_visibility="collapsed", placeholder="タグ追加")
                if st.button("＋", key=f"tg_btn_{r['id']}"):
                    if tag.strip(): tag_comment(r["id"], tag.strip()); st.experimental_rerun()
            with c5:
                toggle = st.toggle("非表示", value=(r["hidden"]==1), key=f"hd_{r['id']}")
                if toggle != (r["hidden"]==1):
                    hide_comment(r["id"], toggle); st.experimental_rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    with tabs[1]:
        st.caption("TF-IDF + KMeans でテーマを把握（最大6クラスタ）")
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.cluster import KMeans
            df = pd.DataFrame(get_comments(room_code, include_hidden=False))
            if df.empty:
                st.info("まだコメントがありません。")
            else:
                vec = TfidfVectorizer(max_features=5000, stop_words=None)
                X = vec.fit_transform(df["content"].tolist())
                k = min(6, max(2, int(len(df)/4)))
                model = KMeans(n_clusters=k, n_init=10, random_state=42)
                df["cluster"] = model.fit_predict(X)
                for cid in sorted(df["cluster"].unique()):
                    st.markdown(f"#### クラスタ {cid}")
                    sub = df[df["cluster"]==cid].sort_values("votes", ascending=False).head(6)
                    for _, r in sub.iterrows():
                        st.markdown(f'<div class="ars-card">{r["content"]} <span class="ars-chip">👍 {int(r["votes"])}</span></div>', unsafe_allow_html=True)
        except Exception as e:
            st.warning(f"クラスタリングは現在利用できません: {e}")

    with tabs[2]:
        c1, c2, c3 = st.columns(3)
        with c1:
            closed = bool(room.get("is_closed")==1)
            new_closed = st.toggle("投稿をクローズ", value=closed)
            if new_closed != closed:
                set_room_closed(room_code, new_closed); st.experimental_rerun()
        with c2:
            if st.button("フォーカス解除"):
                set_focus(room_code, None); st.success("フォーカスを解除しました")
        with c3:
            st.caption("共有は ?room=CODE のURLを配布してください")

# ---------- PROJECTOR ----------
elif mode == "プロジェクター":
    r = get_room(room_code)
    colL, colR = st.columns([4,1])
    with colL:
        focus_id = r.get("focus_comment_id")
        if focus_id:
            with get_db() as conn:
                row = conn.cursor().execute("SELECT * FROM comments WHERE id=?", (focus_id,)).fetchone()
            if row and row["hidden"]==0:
                st.markdown('<div class="ars-card ars-focus">', unsafe_allow_html=True)
                st.markdown(row["content"])
                st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.info("フォーカス中の発言が見つかりません（非表示の可能性）。")
        else:
            st.info("司会者がフォーカスを設定するとここに表示されます。")
    with colR:
        st.markdown("### ローテーション")
        auto = st.toggle("人気順を自動表示（8秒ごと）", value=False)
        if auto:
            # cycle top 20 comments, excluding hidden
            rows = get_comments(room_code)
            if rows:
                idx = int(datetime.utcnow().timestamp() // 8) % min(20, len(rows))
                set_focus(room_code, rows[idx]["id"])

# Update last_refresh timestamp at end of render
st.session_state.last_refresh = datetime.utcnow().isoformat()

st.markdown("</div>", unsafe_allow_html=True)
