import streamlit as st
import pandas as pd
import random
from datetime import date, timedelta
import io
import os
import json
import matplotlib.pyplot as plt
from matplotlib import font_manager
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="バンド練習シフト管理", layout="centered")

DAYS = ["月曜", "火曜", "水曜", "木曜", "金曜", "土曜"]
SHORT_DAYS = ["月", "火", "水", "木", "金", "土"]
PERIODS = ["1限", "2限", "昼休み", "3限", "4限", "5限", "放課後"]
ALL_SLOTS = [f"{day} {period}" for day in DAYS for period in PERIODS]
MAX_SLOTS_PER_BAND = 3

SHEET_NAMES = ["settings", "bands", "votes", "schedule"]


@st.cache_resource
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    if "gcp_service_account" in st.secrets:
        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]), scopes=scopes
        )
    else:
        secret_path = os.path.expanduser("~/Desktop/band_app/secrets.json")
        with open(secret_path, "r") as f:
            info = json.load(f)
        creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)


def get_spreadsheet_url():
    if "SPREADSHEET_URL" in st.secrets:
        return st.secrets["SPREADSHEET_URL"]
    base_dir = os.path.expanduser("~/Desktop/band_app")
    import sys
    if base_dir not in sys.path:
        sys.path.append(base_dir)
    import config
    return config.SPREADSHEET_URL


@st.cache_resource
def get_worksheets():
    gc = get_gspread_client()
    sh = gc.open_by_url(get_spreadsheet_url())
    existing = {ws.title: ws for ws in sh.worksheets()}
    result = {}
    for name in SHEET_NAMES:
        if name in existing:
            ws = existing[name]
        else:
            ws = sh.add_worksheet(title=name, rows=500, cols=20)
        result[name] = ws
    return result


def _parse_date(val, fallback):
    if not val:
        return fallback
    try:
        return date.fromisoformat(str(val).strip()[:10])
    except Exception:
        return fallback


@st.cache_data(ttl=15)
def load_all_data():
    ws_map = get_worksheets()

    # 1. settings
    s_rows = ws_map["settings"].get_all_values()
    today = date.today()
    default_monday = today - timedelta(days=today.weekday())
    settings_dict = {
        "event_name": "未設定イベント",
        "event_start": default_monday.isoformat(),
        "event_end": (default_monday + timedelta(days=59)).isoformat(),
        "week_start": default_monday.isoformat(),
        "round_num": "1",
        "admin_password": "",
    }
    if len(s_rows) >= 2:
        for row in s_rows[1:]:
            if len(row) >= 2 and row[0].strip():
                settings_dict[row[0].strip()] = row[1]

    # 2. bands
    b_rows = ws_map["bands"].get_all_values()
    bands = {}
    total_stats = {}
    if len(b_rows) >= 2:
        for row in b_rows[1:]:
            if not row or not row[0].strip():
                continue
            b_name = row[0].strip()
            try:
                m_cnt = int(row[1]) if len(row) > 1 and str(row[1]).strip() else 4
            except Exception:
                m_cnt = 4
            try:
                t_stat = int(row[2]) if len(row) > 2 and str(row[2]).strip() else 0
            except Exception:
                t_stat = 0
            bands[b_name] = max(1, m_cnt)
            total_stats[b_name] = max(0, t_stat)

    # 3. votes
    v_rows = ws_map["votes"].get_all_values()
    member_votes = {b: {} for b in bands}
    if len(v_rows) >= 2:
        for row in v_rows[1:]:
            if len(row) < 2:
                continue
            b_name = row[0].strip()
            m_name = row[1].strip()
            if not b_name or not m_name:
                continue
            if b_name not in bands:
                continue
            raw_slots = row[2] if len(row) > 2 else ""
            slots = [s.strip() for s in str(raw_slots).split(",") if s.strip()]
            member_votes.setdefault(b_name, {})[m_name] = slots

    # 4. schedule
    sc_rows = ws_map["schedule"].get_all_values()
    schedule_records = []
    if len(sc_rows) >= 2:
        for row in sc_rows[1:]:
            if len(row) >= 3 and row[0].strip() and row[1].strip():
                schedule_records.append({
                    "曜日": row[0].strip(),
                    "コマ": row[1].strip(),
                    "担当バンド": row[2].strip(),
                })

    return {
        "event_name": settings_dict["event_name"].strip() or "未設定イベント",
        "event_start": _parse_date(settings_dict["event_start"], default_monday),
        "event_end": _parse_date(settings_dict["event_end"], default_monday + timedelta(days=59)),
        "week_start": _parse_date(settings_dict["week_start"], default_monday),
        "round_num": max(1, int(settings_dict["round_num"] or 1)),
        "admin_password": str(settings_dict["admin_password"] or ""),
        "bands": bands,
        "total_stats": total_stats,
        "member_votes": member_votes,
        "schedule_records": schedule_records,
    }


def save_settings(data):
    ws = get_worksheets()["settings"]
    rows = [
        ["key", "value"],
        ["event_name", data["event_name"]],
        ["event_start", data["event_start"].isoformat()],
        ["event_end", data["event_end"].isoformat()],
        ["week_start", data["week_start"].isoformat()],
        ["round_num", str(data["round_num"])],
        ["admin_password", data["admin_password"]],
    ]
    ws.clear()
    ws.update(rows, value_input_option="USER_ENTERED")
    load_all_data.clear()


def save_bands_and_stats(bands, total_stats):
    ws = get_worksheets()["bands"]
    rows = [["band_name", "member_count", "total_stats"]]
    for b_name, m_cnt in bands.items():
        rows.append([b_name, int(m_cnt), int(total_stats.get(b_name, 0))])
    ws.clear()
    ws.update(rows, value_input_option="USER_ENTERED")
    load_all_data.clear()


def save_votes(member_votes):
    ws = get_worksheets()["votes"]
    rows = [["band_name", "member_name", "slots"]]
    for b_name, m_dict in member_votes.items():
        for m_name, slots in m_dict.items():
            rows.append([b_name, m_name, ",".join(slots)])
    ws.clear()
    ws.update(rows, value_input_option="USER_ENTERED")
    load_all_data.clear()


def save_schedule(schedule_records):
    ws = get_worksheets()["schedule"]
    rows = [["曜日", "コマ", "担当バンド"]]
    for rec in schedule_records:
        rows.append([rec["曜日"], rec["コマ"], rec["担当バンド"]])
    ws.clear()
    ws.update(rows, value_input_option="USER_ENTERED")
    load_all_data.clear()


def get_japanese_font():
    candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return font_manager.FontProperties(fname=path)
    return None


def create_schedule_image(cal_df, title_text):
    jp_font = get_japanese_font()
    rows, cols = cal_df.shape
    fig_w = max(7.5, cols * 1.45 + 1.5)
    fig_h = max(4.2, rows * 0.65 + 1.4)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=150)
    ax.axis("off")

    if title_text:
        if jp_font:
            ax.set_title(title_text, fontproperties=jp_font, fontsize=13, fontweight="bold", pad=12)
        else:
            ax.set_title(title_text, fontsize=13, fontweight="bold", pad=12)

    cell_text = [[str(val) for val in row] for row in cal_df.values]
    col_labels = [str(c) for c in cal_df.columns]
    row_labels = [str(r) for r in cal_df.index]

    table = ax.table(
        cellText=cell_text,
        colLabels=col_labels,
        rowLabels=row_labels,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9.5)
    table.scale(1.0, 1.65)

    for (r, c), cell in table.get_celld().items():
        if jp_font:
            cell.get_text().set_fontproperties(jp_font)
        if r == 0:
            cell.set_facecolor("#2B4C7E")
            cell.get_text().set_color("white")
            cell.get_text().set_weight("bold")
        elif c == -1:
            cell.set_facecolor("#EBF1F8")
            cell.get_text().set_weight("bold")
        else:
            txt = cell.get_text().get_text()
            if txt in ("ー", "・", ""):
                cell.set_facecolor("#F9FAFB")
                cell.get_text().set_color("#888888")
            elif "(過半数)" in txt:
                cell.set_facecolor("#FFF8E1")
                cell.get_text().set_color("#7A5200")
            else:
                cell.set_facecolor("#E8F5E9")
                cell.get_text().set_color("#1B5E20")
                cell.get_text().set_weight("bold")

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


if "name_input_key" not in st.session_state:
    st.session_state["name_input_key"] = 0
if "last_vote_msg" not in st.session_state:
    st.session_state["last_vote_msg"] = ""
if "admin_unlocked" not in st.session_state:
    st.session_state["admin_unlocked"] = False

try:
    db = load_all_data()
except Exception as e:
    st.error("Googleスプレッドシートとの接続中にエラーが発生しました。")
    st.code(str(e))
    if st.button("🔄 再接続する", use_container_width=True):
        load_all_data.clear()
        st.rerun()
    st.stop()

event_name = db["event_name"]
event_start = db["event_start"]
event_end = db["event_end"]
raw_start = db["week_start"]
round_num = db["round_num"]
admin_password = db["admin_password"]
bands_dict = db["bands"]
total_stats = db["total_stats"]
member_votes = db["member_votes"]
schedule_records = db["schedule_records"]
band_names = list(bands_dict.keys())

w_start = raw_start - timedelta(days=raw_start.weekday())
w_end = w_start + timedelta(days=5)
effective_start = event_start if (w_start < event_start <= w_end) else w_start
start_idx = effective_start.weekday()
ACTIVE_DAYS = DAYS[start_idx:]
ACTIVE_SLOTS = [f"{day} {period}" for day in ACTIVE_DAYS for period in PERIODS]
DAY_LABELS = {
    DAYS[i]: f"{(w_start + timedelta(days=i)).strftime('%-m/%-d')}({SHORT_DAYS[i]})"
    for i in range(6)
}
EVENT_RANGE_STR = f"{event_start.strftime('%-m/%-d')}〜{event_end.strftime('%-m/%-d')}"
WEEK_RANGE_STR = f"{effective_start.strftime('%-m/%-d')}〜{w_end.strftime('%-m/%-d')}"

st.title("バンド練習スケジュール")
st.caption(
    f"🎪 イベント：**{event_name}** ｜ 🗓️ コマ取り期間：{EVENT_RANGE_STR} ｜ "
    f"対象週：**{WEEK_RANGE_STR}**（第{round_num}回）"
)

if st.button("🔄 最新データに更新（他の人の投票を反映）", use_container_width=True):
    load_all_data.clear()
    st.rerun()


def evaluate_band_slots(b_dict, v_dict):
    band_status = {b: {} for b in b_dict}
    for b, total_members in b_dict.items():
        b_votes = v_dict.get(b, {})
        for slot in ACTIVE_SLOTS:
            ok_count = sum(1 for member_slots in b_votes.values() if slot in member_slots)
            if ok_count >= total_members and total_members > 0:
                band_status[b][slot] = "full"
            elif ok_count > (total_members / 2):
                band_status[b][slot] = "majority"
            else:
                band_status[b][slot] = "none"
    return band_status


def is_consecutive_for_band(band, day, p_idx, assigned_map, band_status):
    adj_indices = [i for i in [p_idx - 1, p_idx + 1] if 0 <= i < len(PERIODS)]
    for adj_i in adj_indices:
        adj_slot = f"{day} {PERIODS[adj_i]}"
        if assigned_map.get(adj_slot) == band:
            return True
        if adj_slot not in assigned_map and band_status[band][adj_slot] in ("full", "majority"):
            return True
    return False


tab1, tab2, tab3, tab4 = st.tabs([
    "📅 シフト作成",
    "🗳️ 個人投票",
    "🎸 バンド管理",
    "⚙️ 管理者",
])

# ==========================================
# タブ1：シフト確認・均等割り振り
# ==========================================
with tab1:
    st.subheader(f"第{round_num}回 練習スケジュール（{WEEK_RANGE_STR}）")
    st.caption(
        f"※最大{MAX_SLOTS_PER_BAND}コマ上限 ／ 連続コマ優先 ／ 全員＞過半数 ／ 累計が少ないバンド優先"
    )

    if not band_names:
        st.info("まずは「🎸 バンド管理」タブからバンド名と人数を追加してください。")
    else:
        if st.button("🔄 条件を考慮して自動割り振り", use_container_width=True):
            band_status = evaluate_band_slots(bands_dict, member_votes)
            counts = {b: 0 for b in band_names}
            assigned_band_map = {}
            slot_results = {}

            sorted_slots = sorted(
                ACTIVE_SLOTS,
                key=lambda s: (
                    sum(1 for b in band_names if band_status[b][s] == "full") == 0,
                    sum(1 for b in band_names if band_status[b][s] == "full"),
                    sum(1 for b in band_names if band_status[b][s] == "majority"),
                ),
            )

            for slot in sorted_slots:
                day, period = slot.split(" ")
                p_idx = PERIODS.index(period)
                full_bands = [
                    b for b in band_names
                    if band_status[b][slot] == "full" and counts[b] < MAX_SLOTS_PER_BAND
                ]
                maj_bands = [
                    b for b in band_names
                    if band_status[b][slot] == "majority" and counts[b] < MAX_SLOTS_PER_BAND
                ]
                if full_bands:
                    target_bands, suffix = full_bands, ""
                elif maj_bands:
                    target_bands, suffix = maj_bands, "(過半数)"
                else:
                    target_bands, suffix = [], ""

                if target_bands:
                    consec_bands = [
                        b for b in target_bands
                        if is_consecutive_for_band(b, day, p_idx, assigned_band_map, band_status)
                    ]
                    pool = consec_bands if consec_bands else target_bands
                    min_score = min(
                        (counts[b], total_stats.get(b, 0)) for b in pool
                    )
                    candidates = [
                        b for b in pool
                        if (counts[b], total_stats.get(b, 0)) == min_score
                    ]
                    chosen = random.choice(candidates)
                    counts[chosen] += 1
                    assigned_band_map[slot] = chosen
                    slot_results[slot] = f"{chosen}{suffix}"
                else:
                    slot_results[slot] = "ー"

            new_records = [
                {
                    "曜日": s.split(" ")[0],
                    "コマ": s.split(" ")[1],
                    "担当バンド": slot_results[s],
                }
                for s in ACTIVE_SLOTS
            ]
            save_schedule(new_records)
            st.session_state.pop("sched_img_bytes", None)
            st.success("累計練習数と希望条件を考慮して割り振り、スプレッドシートに保存しました！")
            st.rerun()

        if schedule_records:
            df = pd.DataFrame(schedule_records)
            df = df.drop_duplicates(subset=["曜日", "コマ"], keep="last")
            df = df[df["曜日"].isin(ACTIVE_DAYS)]

            week_counts = {b: 0 for b in band_names}
            for _, row in df.iterrows():
                val = str(row["担当バンド"])
                base_b = val[:-4] if val.endswith("(過半数)") else val
                if base_b in week_counts:
                    week_counts[base_b] += 1

            with st.expander("📊 今回の当選コマ数を見る（上限3コマ）"):
                st.dataframe(
                    pd.DataFrame(
                        list(week_counts.items()),
                        columns=["バンド名", "今回当選数"],
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

            filter_band = st.selectbox("バンドでハイライト表示", ["すべて表示"] + band_names)
            disp_df = df.copy()
            if filter_band != "すべて表示":
                disp_df["表示用"] = disp_df["担当バンド"].apply(
                    lambda x: f"★ {x}"
                    if (x == filter_band or x == f"{filter_band}(過半数)")
                    else ("・" if x != "ー" else "ー")
                )
            else:
                disp_df["表示用"] = disp_df["担当バンド"]

            cal_df = disp_df.pivot(index="コマ", columns="曜日", values="表示用").reindex(
                index=PERIODS, columns=ACTIVE_DAYS
            )
            labeled_cal_df = cal_df.rename(columns=DAY_LABELS)
            st.dataframe(labeled_cal_df, use_container_width=True)

            img_title = f"{event_name} 第{round_num}回（{WEEK_RANGE_STR}）"
            if st.button("🖼️ 保存用の画像を作成する", use_container_width=True):
                st.session_state["sched_img_bytes"] = create_schedule_image(labeled_cal_df, img_title)

            if "sched_img_bytes" in st.session_state:
                st.download_button(
                    label="📥 作成した画像をスマホに保存（PNG）",
                    data=st.session_state["sched_img_bytes"],
                    file_name=f"band_schedule_round{round_num}.png",
                    mime="image/png",
                    use_container_width=True,
                )

# ==========================================
# タブ2：個人投票
# ==========================================
with tab2:
    st.subheader("個人スケジュール投票")
    st.caption(f"対象週：**{WEEK_RANGE_STR}**（第{round_num}回）")

    if st.session_state["last_vote_msg"]:
        st.success(st.session_state["last_vote_msg"])
        st.session_state["last_vote_msg"] = ""

    if not band_names:
        st.info("先に「🎸 バンド管理」タブからバンドを追加してください。")
    else:
        PLACEHOLDER = "ーー バンドを選択してください ーー"
        selected_band = st.selectbox(
            "1. 自分のバンドを選択", [PLACEHOLDER] + band_names, index=0
        )
        if selected_band == PLACEHOLDER:
            st.warning("👆 まず自分のバンドを選択してください。")
        else:
            total_members = bands_dict[selected_band]
            b_votes = member_votes.get(selected_band, {})
            voted_members = list(b_votes.keys())
            st.info(
                f"📊 **【{selected_band}】の投票状況：{len(voted_members)} / {total_members}人 完了**\n\n"
                f"投票済み：{', '.join(voted_members) if voted_members else 'まだいません'}"
            )

            member_name = st.text_input(
                "2. 自分の名前を入力（例：田中）",
                key=f"member_name_input_{st.session_state['name_input_key']}",
            )
            clean_member = member_name.strip()

            if clean_member:
                existing_slots = b_votes.get(clean_member, [])
                with st.form("member_vote_form"):
                    st.write(f"**3. {clean_member}さんが参加できるコマにチェック**")
                    selected_slots = []
                    for day in ACTIVE_DAYS:
                        with st.expander(
                            f"📌 {DAY_LABELS[day]}の参加可能コマ",
                            expanded=(day == ACTIVE_DAYS[0]),
                        ):
                            for period in PERIODS:
                                slot_name = f"{day} {period}"
                                if st.checkbox(
                                    period,
                                    value=(slot_name in existing_slots),
                                    key=f"{selected_band}_{clean_member}_{slot_name}",
                                ):
                                    selected_slots.append(slot_name)

                    if st.form_submit_button("🗳️ この内容で投票を送信する", use_container_width=True):
                        updated_votes = {k: dict(v) for k, v in member_votes.items()}
                        updated_votes.setdefault(selected_band, {})[clean_member] = selected_slots
                        save_votes(updated_votes)
                        st.session_state["last_vote_msg"] = (
                            f"【{selected_band}】{clean_member}さんの予定（計{len(selected_slots)}コマ）を登録しました！"
                        )
                        st.session_state["name_input_key"] += 1
                        st.rerun()

# ==========================================
# タブ3：バンド管理
# ==========================================
with tab3:
    st.subheader("バンドの追加・人数設定")
    with st.form("add_band_form", clear_on_submit=True):
        new_band_name = st.text_input("バンド名", placeholder="例：〇〇バンド")
        member_count = st.number_input(
            "メンバー人数（人）", min_value=1, max_value=20, value=4, step=1
        )
        if st.form_submit_button("➕ バンドを登録する", use_container_width=True):
            clean_name = new_band_name.strip()
            if not clean_name:
                st.error("バンド名を入力してください。")
            elif clean_name in bands_dict:
                st.warning(f"「{clean_name}」はすでに登録されています。")
            else:
                new_bands = dict(bands_dict)
                new_bands[clean_name] = int(member_count)
                new_stats = dict(total_stats)
                new_stats[clean_name] = 0
                new_votes = {k: dict(v) for k, v in member_votes.items()}
                new_votes[clean_name] = {}

                save_bands_and_stats(new_bands, new_stats)
                save_votes(new_votes)
                st.success(f"「{clean_name}」（{int(member_count)}人）を登録しました！")
                st.rerun()

    st.divider()
    st.write(f"**現在登録されているバンド（計 {len(bands_dict)} バンド）**")
    if not bands_dict:
        st.caption("まだバンドが登録されていません。上の入力欄から追加してください。")
    else:
        for b, cnt in list(bands_dict.items()):
            voted_cnt = len(member_votes.get(b, {}))
            col_name, col_del = st.columns([3, 1])
            col_name.write(f"・ **{b}**（{cnt}人編成 / 投票済：{voted_cnt}人）")
            if col_del.button("削除", key=f"del_{b}", use_container_width=True):
                new_bands = {k: v for k, v in bands_dict.items() if k != b}
                new_stats = {k: v for k, v in total_stats.items() if k != b}
                new_votes = {k: dict(v) for k, v in member_votes.items() if k != b}
                save_bands_and_stats(new_bands, new_stats)
                save_votes(new_votes)
                st.rerun()

# ==========================================
# タブ4：管理者
# ==========================================
with tab4:
    st.subheader("⚙️ 管理者")

    is_locked = bool(admin_password) and not st.session_state["admin_unlocked"]
    if is_locked:
        st.warning("🔒 管理者パスワードが設定されています。パスワードを入力してロックを解除してください。")
        with st.form("unlock_admin_form"):
            pw_input = st.text_input("管理者パスワード", type="password")
            if st.form_submit_button("🔓 ロックを解除する", use_container_width=True):
                if pw_input == admin_password:
                    st.session_state["admin_unlocked"] = True
                    st.rerun()
                else:
                    st.error("パスワードが違います。")
    else:
        if admin_password:
            if st.button("🔒 管理者タブを再度ロックする", use_container_width=True):
                st.session_state["admin_unlocked"] = False
                st.rerun()

        st.write("**📊 累計練習コマ数統計**")
        if not band_names:
            st.info("バンドが登録されていません。")
        else:
            stat_rows = [
                {"バンド名": b, "累計練習コマ数": total_stats.get(b, 0)}
                for b in band_names
            ]
            stat_df = pd.DataFrame(stat_rows)
            st.dataframe(stat_df, use_container_width=True, hide_index=True)
            st.bar_chart(stat_df.set_index("バンド名")["累計練習コマ数"])

        st.divider()
        st.write("**🔄 今回のシフトを確定して累計に加算 ＆ 投票データをリセット**")
        st.caption(
            "ボタンを押すと、現在表示されているシフトの当選コマ数が各バンドの累計に加算され、"
            "投票データとシフト表がリセットされて次の回（＋7日）に進みます（バンド名・人数・累計統計は保持されます）。"
        )
        confirm_reset = st.checkbox("上記の処理を実行することを確認しました")
        if st.button(
            "✅ 確定して累計に加算 ＆ 次の回の投票へリセット",
            use_container_width=True,
            disabled=not confirm_reset,
        ):
            updated_stats = dict(total_stats)
            for rec in schedule_records:
                val = str(rec.get("担当バンド", ""))
                base_b = val[:-4] if val.endswith("(過半数)") else val
                if base_b in updated_stats:
                    updated_stats[base_b] += 1

            next_round = round_num + 1
            next_week_start = w_start + timedelta(days=7)

            save_bands_and_stats(bands_dict, updated_stats)
            save_votes({b: {} for b in bands_dict})
            save_schedule([])
            save_settings({
                "event_name": event_name,
                "event_start": event_start,
                "event_end": event_end,
                "week_start": next_week_start,
                "round_num": next_round,
                "admin_password": admin_password,
            })
            st.session_state.pop("sched_img_bytes", None)
            st.success(f"第{round_num}回の結果を累計に加算し、第{next_round}回（{next_week_start.strftime('%-m/%-d')}週）へ進めました！")
            st.rerun()

        st.divider()
        st.write("**🎪 イベント名 ＆ コマ取り期間の設定**")
        st.caption(
            "※イベント名を変更して保存すると、バンド登録・投票・累計統計がすべてリセットされ、"
            "新しいイベントを1から開始できます。"
        )
        with st.form("date_setting_form"):
            in_event_name = st.text_input(
                "イベント名", value=event_name, placeholder="例：〇〇ライブ"
            )
            col_s, col_e = st.columns(2)
            with col_s:
                in_event_start = st.date_input("コマ取り開始日", value=event_start)
            with col_e:
                in_event_end = st.date_input("コマ取り終了日", value=event_end)
            in_week_start = st.date_input(
                "現在のシフト対象週（月曜日の日付）", value=w_start
            )
            if st.form_submit_button("💾 イベント・コマ取り期間を保存", use_container_width=True):
                clean_ev = in_event_name.strip() or "未設定イベント"
                is_new_event = clean_ev != event_name
                if is_new_event:
                    save_bands_and_stats({}, {})
                    save_votes({})
                    save_schedule([])
                    new_round = 1
                    target_d = in_event_start
                else:
                    new_round = round_num
                    if in_event_start != event_start and in_week_start == w_start:
                        target_d = in_event_start
                    else:
                        target_d = in_week_start

                new_w_start = target_d - timedelta(days=target_d.weekday())
                save_settings({
                    "event_name": clean_ev,
                    "event_start": in_event_start,
                    "event_end": in_event_end,
                    "week_start": new_w_start,
                    "round_num": new_round,
                    "admin_password": admin_password,
                })
                st.session_state.pop("sched_img_bytes", None)
                st.success("設定を保存しました！")
                st.rerun()

        st.divider()
        st.write("**🔐 管理者タブのパスワード設定・変更**")
        st.caption("空欄のまま保存するとパスワードなし（誰でも開ける状態）になります。")
        with st.form("admin_pw_form"):
            new_pw = st.text_input(
                "新しいパスワード",
                value=admin_password,
                type="password",
                placeholder="例：1234",
            )
            if st.form_submit_button("🔑 パスワードを保存", use_container_width=True):
                save_settings({
                    "event_name": event_name,
                    "event_start": event_start,
                    "event_end": event_end,
                    "week_start": w_start,
                    "round_num": round_num,
                    "admin_password": new_pw.strip(),
                })
                st.session_state["admin_unlocked"] = True
                st.success("パスワード設定を更新しました（全端末に反映されます）。")
                st.rerun()
