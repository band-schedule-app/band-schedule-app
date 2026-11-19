import streamlit as st
import pandas as pd
import random
import io
import os
import json
from datetime import date, timedelta
import gspread
from google.oauth2.service_account import Credentials
import matplotlib.pyplot as plt
from matplotlib import font_manager

for font_name in ["Hiragino Sans", "Hiragino Kaku Gothic ProN", "Yu Gothic", "Noto Sans CJK JP", "IPAexGothic"]:
    if any(font_name in f.name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = font_name
        break

st.set_page_config(page_title="バンド練習シフト管理", layout="centered")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

@st.cache_resource
def get_spreadsheet():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    secrets_path = os.path.join(base_dir, "secrets.json")
    if os.path.exists(secrets_path):
        import config
        creds = Credentials.from_service_account_file(secrets_path, scopes=SCOPES)
        sheet_url = config.SPREADSHEET_URL
    else:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        sheet_url = st.secrets["SPREADSHEET_URL"]
    client = gspread.authorize(creds)
    return client.open_by_url(sheet_url)

@st.cache_data(ttl=60)
def load_all_data():
    sh = get_spreadsheet()
    today = date.today()
    next_mon = today + timedelta(days=(7 - today.weekday()) % 7)
    default_settings = {
        "event_name": "未設定イベント",
        "event_start": next_mon.isoformat(),
        "event_end": (next_mon + timedelta(days=60)).isoformat(),
        "week_start": next_mon.isoformat(),
        "round_num": "1",
        "admin_password": ""
    }
    ws_set = sh.worksheet("settings")
    rows_set = ws_set.get_all_values()
    settings = default_settings.copy()
    if len(rows_set) <= 1:
        ws_set.clear()
        ws_set.append_row(["key", "value"])
        for k, v in settings.items():
            ws_set.append_row([k, str(v)])
    else:
        for r in rows_set[1:]:
            if len(r) >= 2 and r[0] in settings:
                settings[r[0]] = r[1]

    ws_bands = sh.worksheet("bands")
    rows_bands = ws_bands.get_all_values()
    bands, total_stats = {}, {}
    if len(rows_bands) <= 1:
        ws_bands.clear()
        ws_bands.append_row(["band_name", "member_count", "total_slots"])
    else:
        for r in rows_bands[1:]:
            if len(r) >= 3 and r[0]:
                bands[r[0]] = int(r[1])
                total_stats[r[0]] = int(r[2])

    ws_votes = sh.worksheet("votes")
    rows_votes = ws_votes.get_all_values()
    member_votes = {b: {} for b in bands}
    if len(rows_votes) <= 1:
        ws_votes.clear()
        ws_votes.append_row(["band_name", "member_name", "slots_json"])
    else:
        for r in rows_votes[1:]:
            if len(r) >= 3 and r[0] in member_votes and r[1]:
                member_votes[r[0]][r[1]] = json.loads(r[2])

    ws_sched = sh.worksheet("schedule")
    rows_sched = ws_sched.get_all_values()
    schedule_df, counts = None, {}
    if len(rows_sched) <= 1:
        ws_sched.clear()
        ws_sched.append_row(["day", "period", "assigned_band"])
    else:
        sched_list = [{"曜日": r[0], "コマ": r[1], "担当バンド": r[2]} for r in rows_sched[1:] if len(r) >= 3]
        if sched_list:
            schedule_df = pd.DataFrame(sched_list)
            counts = {b: 0 for b in bands}
            for item in sched_list:
                ab = item["担当バンド"].replace("(過半数)", "")
                if ab in counts:
                    counts[ab] += 1

    return settings, bands, total_stats, member_votes, schedule_df, counts

def save_settings_to_sheet(settings):
    ws = get_spreadsheet().worksheet("settings")
    ws.clear()
    ws.append_row(["key", "value"])
    for k, v in settings.items():
        ws.append_row([k, str(v)])

def save_bands_to_sheet(bands, total_stats):
    ws = get_spreadsheet().worksheet("bands")
    ws.clear()
    ws.append_row(["band_name", "member_count", "total_slots"])
    for b, cnt in bands.items():
        ws.append_row([b, cnt, total_stats.get(b, 0)])

def save_votes_to_sheet(member_votes):
    ws = get_spreadsheet().worksheet("votes")
    ws.clear()
    ws.append_row(["band_name", "member_name", "slots_json"])
    for b, m_dict in member_votes.items():
        for m, slots in m_dict.items():
            ws.append_row([b, m, json.dumps(slots, ensure_ascii=False)])

def save_schedule_to_sheet(schedule_df):
    ws = get_spreadsheet().worksheet("schedule")
    ws.clear()
    ws.append_row(["day", "period", "assigned_band"])
    if schedule_df is not None:
        for _, row in schedule_df.iterrows():
            ws.append_row([row["曜日"], row["コマ"], row["担当バンド"]])

def create_schedule_image(cal_df, title_text):
    fig, ax = plt.subplots(figsize=(9.5, 5.0), dpi=200)
    ax.axis("off")
    ax.set_title(title_text, fontsize=14, fontweight="bold", pad=14)
    table = ax.table(cellText=cal_df.values, rowLabels=cal_df.index, colLabels=cal_df.columns, loc="center", cellLoc="center", rowLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9.5)
    table.scale(1.0, 1.8)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#CCCCCC")
        if row == 0:
            cell.set_facecolor("#2C3E50")
            cell.get_text().set_color("white")
            cell.get_text().set_weight("bold")
        elif col == -1:
            cell.set_facecolor("#ECF0F1")
            cell.get_text().set_weight("bold")
        else:
            txt = cell.get_text().get_text()
            if txt == "ー":
                cell.set_facecolor("#FAFAFA")
                cell.get_text().set_color("#AAAAAA")
            elif "(過半数)" in txt:
                cell.set_facecolor("#FFF9E6")
            else:
                cell.set_facecolor("#EBF5FB")
                cell.get_text().set_weight("bold")
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    buf.seek(0)
    return buf

settings, bands_dict, total_stats, member_votes, schedule_df, counts = load_all_data()

if "name_input_key" not in st.session_state:
    st.session_state["name_input_key"] = 0
if "last_vote_msg" not in st.session_state:
    st.session_state["last_vote_msg"] = ""
if "admin_unlocked" not in st.session_state:
    st.session_state["admin_unlocked"] = False

st.title("バンド練習スケジュール")
if st.button("🔄 最新データに更新（他の人の投票を反映）", use_container_width=True):
    load_all_data.clear()
    st.rerun()

DAYS = ["月曜", "火曜", "水曜", "木曜", "金曜", "土曜"]
SHORT_DAYS = ["月", "火", "水", "木", "金", "土"]
PERIODS = ["1限", "2限", "昼休み", "3限", "4限", "5限", "放課後"]
MAX_SLOTS_PER_BAND = 3

ev_start = date.fromisoformat(settings["event_start"])
ev_end = date.fromisoformat(settings["event_end"])
raw_start = date.fromisoformat(settings["week_start"])
round_num = int(settings["round_num"])

w_start = raw_start - timedelta(days=raw_start.weekday())
w_end = w_start + timedelta(days=5)
effective_start = ev_start if (w_start < ev_start <= w_end) else w_start
start_idx = effective_start.weekday()
ACTIVE_DAYS = DAYS[start_idx:]
ACTIVE_SLOTS = [f"{day} {period}" for day in ACTIVE_DAYS for period in PERIODS]
DAY_LABELS = {DAYS[i]: f"{(w_start + timedelta(days=i)).strftime('%-m/%-d')}({SHORT_DAYS[i]})" for i in range(6)}
WEEK_RANGE_STR = f"{effective_start.strftime('%-m/%-d')}〜{w_end.strftime('%-m/%-d')}"
EVENT_RANGE_STR = f"{ev_start.strftime('%-m/%-d')}〜{ev_end.strftime('%-m/%-d')}"

st.caption(f"🎪 イベント：**{settings['event_name']}** ｜ 🗓️ コマ取り期間：{EVENT_RANGE_STR} ｜ 対象週：**{WEEK_RANGE_STR}**（第{round_num}回）")

tab1, tab2, tab3, tab4 = st.tabs(["📅 シフト作成", "🗳️ 個人投票", "🎸 バンド管理", "⚙️ 管理者"])

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

with tab1:
    st.subheader(f"練習スケジュール（{WEEK_RANGE_STR}）")
    st.caption(f"※最大{MAX_SLOTS_PER_BAND}コマ上限 ／ 連続コマ優先 ／ 全員＞過半数 ／ 累計が少ないバンド優先")
    band_names = list(bands_dict.keys())
    if not band_names:
        st.info("まずは「🎸 バンド管理」タブからバンド名と人数を追加してください。")
    else:
        if st.button("🔄 条件を考慮して自動割り振り", use_container_width=True):
            band_status = evaluate_band_slots(bands_dict, member_votes)
            new_counts = {b: 0 for b in band_names}
            assigned_band_map = {}
            slot_results = {}
            sorted_slots = sorted(ACTIVE_SLOTS, key=lambda s: (
                sum(1 for b in band_names if band_status[b][s] == "full") == 0,
                sum(1 for b in band_names if band_status[b][s] == "full"),
                sum(1 for b in band_names if band_status[b][s] == "majority")
            ))
            for slot in sorted_slots:
                day, period = slot.split(" ")
                p_idx = PERIODS.index(period)
                full_bands = [b for b in band_names if band_status[b][slot] == "full" and new_counts[b] < MAX_SLOTS_PER_BAND]
                maj_bands = [b for b in band_names if band_status[b][slot] == "majority" and new_counts[b] < MAX_SLOTS_PER_BAND]
                target_bands, suffix = (full_bands, "") if full_bands else ((maj_bands, "(過半数)") if maj_bands else ([], ""))
                if target_bands:
                    consec_bands = [b for b in target_bands if is_consecutive_for_band(b, day, p_idx, assigned_band_map, band_status)]
                    pool = consec_bands if consec_bands else target_bands
                    min_score = min((new_counts[b], total_stats.get(b, 0)) for b in pool)
                    candidates = [b for b in pool if (new_counts[b], total_stats.get(b, 0)) == min_score]
                    chosen = random.choice(candidates)
                    new_counts[chosen] += 1
                    assigned_band_map[slot] = chosen
                    slot_results[slot] = f"{chosen}{suffix}"
                else:
                    slot_results[slot] = "ー"
            new_sched_df = pd.DataFrame([{"曜日": s.split(" ")[0], "コマ": s.split(" ")[1], "担当バンド": slot_results[s]} for s in ACTIVE_SLOTS])
            save_schedule_to_sheet(new_sched_df)
            st.rerun()

        if schedule_df is not None and not schedule_df.empty:
            with st.expander("📊 今回の当選コマ数を見る（上限3コマ）"):
                st.dataframe(pd.DataFrame(list(counts.items()), columns=["バンド名", "今回当選数"]), use_container_width=True, hide_index=True)
            filter_band = st.selectbox("バンドでハイライト表示", ["すべて表示"] + band_names)
            df = schedule_df.copy()
            df["表示用"] = df["担当バンド"].apply(lambda x: f"★ {x}" if (x == filter_band or x == f"{filter_band}(過半数)") else ("・" if x != "ー" else "ー")) if filter_band != "すべて表示" else df["担当バンド"]
            cal_df = df.pivot(index="コマ", columns="曜日", values="表示用").reindex(index=PERIODS, columns=ACTIVE_DAYS).rename(columns=DAY_LABELS)
            st.dataframe(cal_df, use_container_width=True)
            st.download_button(label="🖼️ このスケジュール表を画像（PNG）で保存", data=create_schedule_image(cal_df, f"バンド練習スケジュール（{WEEK_RANGE_STR}）"), file_name=f"band_schedule_{effective_start.strftime('%m%d')}.png", mime="image/png", use_container_width=True)

with tab2:
    st.subheader(f"個人スケジュール投票（{WEEK_RANGE_STR}）")
    band_names = list(bands_dict.keys())
    if st.session_state["last_vote_msg"]:
        st.success(st.session_state["last_vote_msg"])
        st.session_state["last_vote_msg"] = ""
    if not band_names:
        st.info("先に「🎸 バンド管理」タブからバンドを追加してください。")
    else:
        PLACEHOLDER = "ーー バンドを選択してください ーー"
        selected_band = st.selectbox("1. 自分のバンドを選択", [PLACEHOLDER] + band_names, index=0)
        if selected_band == PLACEHOLDER:
            st.warning("👆 まず自分のバンドを選択してください。")
        else:
            total_members = bands_dict[selected_band]
            b_votes = member_votes.setdefault(selected_band, {})
            voted_members = list(b_votes.keys())
            st.info(f"📊 **【{selected_band}】の投票状況：{len(voted_members)} / {total_members}人 完了**\n\n投票済み：{', '.join(voted_members) if voted_members else 'まだいません'}")
            member_name = st.text_input("2. 自分の名前を入力（例：田中）", key=f"member_name_input_{st.session_state['name_input_key']}")
            clean_member = member_name.strip()
            if clean_member:
                existing_slots = b_votes.get(clean_member, [])
                with st.form("member_vote_form"):
                    st.write(f"**3. {clean_member}さんが参加できるコマにチェック**")
                    selected_slots = []
                    for day in ACTIVE_DAYS:
                        with st.expander(f"📌 {DAY_LABELS[day]} の参加可能コマ", expanded=(day == ACTIVE_DAYS[0])):
                            for period in PERIODS:
                                slot_name = f"{day} {period}"
                                if st.checkbox(period, value=(slot_name in existing_slots), key=f"{selected_band}_{clean_member}_{slot_name}"):
                                    selected_slots.append(slot_name)
                    if st.form_submit_button("🗳️ この内容で投票を送信する", use_container_width=True):
                        member_votes[selected_band][clean_member] = selected_slots
                        save_votes_to_sheet(member_votes)
                        st.session_state["last_vote_msg"] = f"【{selected_band}】{clean_member}さんの予定（計{len(selected_slots)}コマ）を登録しました！"
                        st.session_state["name_input_key"] += 1
                        st.rerun()

with tab3:
    st.subheader("バンドの追加・人数設定")
    with st.form("add_band_form", clear_on_submit=True):
        new_band_name = st.text_input("バンド名", placeholder="例：〇〇バンド")
        member_count = st.number_input("メンバー人数（人）", min_value=1, max_value=20, value=4, step=1)
        if st.form_submit_button("➕ バンドを登録する", use_container_width=True):
            clean_name = new_band_name.strip()
            if not clean_name:
                st.error("バンド名を入力してください。")
            elif clean_name in bands_dict:
                st.warning(f"「{clean_name}」はすでに登録されています。")
            else:
                bands_dict[clean_name] = int(member_count)
                total_stats[clean_name] = 0
                save_bands_to_sheet(bands_dict, total_stats)
                st.success(f"「{clean_name}」（{int(member_count)}人）を登録しました！")
                st.rerun()
    st.divider()
    st.write(f"**現在登録されているバンド（計 {len(bands_dict)} バンド）**")
    for b, cnt in list(bands_dict.items()):
        voted_cnt = len(member_votes.get(b, {}))
        col_name, col_del = st.columns([3, 1])
        col_name.write(f"・ **{b}**（{cnt}人編成 / 投票済：{voted_cnt}人）")
        if col_del.button("削除", key=f"del_{b}", use_container_width=True):
            bands_dict.pop(b, None)
            total_stats.pop(b, None)
            member_votes.pop(b, None)
            save_bands_to_sheet(bands_dict, total_stats)
            save_votes_to_sheet(member_votes)
            st.rerun()

with tab4:
    st.subheader("⚙️ 管理者")
    saved_pw = settings["admin_password"]
    is_locked = bool(saved_pw) and not st.session_state["admin_unlocked"]
    if is_locked:
        st.warning("🔒 このページはパスワードで保護されています。")
        with st.form("unlock_admin_form"):
            input_pw = st.text_input("パスワードを入力してください", type="password")
            if st.form_submit_button("🔓 ロックを解除する", use_container_width=True):
                if input_pw == saved_pw:
                    st.session_state["admin_unlocked"] = True
                    st.rerun()
                else:
                    st.error("パスワードが違います。")
    else:
        st.write("**🎪 イベント名 ＆ コマ取り期間の設定**")
        st.caption("※イベント名を変更して保存すると、バンド登録・投票・累計統計がすべてリセットされ、新しいイベントを1から開始できます。")
        with st.form("date_setting_form"):
            in_event_name = st.text_input("イベント名", value=settings["event_name"], placeholder="例：〇〇ライブ")
            col_s, col_e = st.columns(2)
            with col_s:
                in_event_start = st.date_input("コマ取り開始日", value=ev_start)
            with col_e:
                in_event_end = st.date_input("コマ取り終了日", value=ev_end)
            in_week_start = st.date_input("現在のシフト対象週（月曜日の日付）", value=w_start)
            if st.form_submit_button("💾 イベント・コマ取り期間を保存", use_container_width=True):
                clean_ev = in_event_name.strip() or "未設定イベント"
                is_new_event = (clean_ev != settings["event_name"])
                if is_new_event:
                    save_bands_to_sheet({}, {})
                    save_votes_to_sheet({})
                    save_schedule_to_sheet(None)
                    settings["round_num"] = "1"
                    target_d = in_event_start
                else:
                    target_d = in_event_start if (in_event_start != ev_start and in_week_start == w_start) else in_week_start
                aligned_w = target_d - timedelta(days=target_d.weekday())
                settings["event_name"] = clean_ev
                settings["event_start"] = in_event_start.isoformat()
                settings["event_end"] = in_event_end.isoformat()
                settings["week_start"] = aligned_w.isoformat()
                save_settings_to_sheet(settings)
                st.rerun()

        st.divider()
        st.write("**📊 各バンドの累計練習コマ数**")
        if not bands_dict:
            st.info("バンドが登録されていません。")
        else:
            stats_list = [{"バンド名": b, "これまでの累計": total_stats.get(b, 0), "今回(未確定)": counts.get(b, 0), "確定後の合計": total_stats.get(b, 0) + counts.get(b, 0)} for b in bands_dict]
            st.dataframe(pd.DataFrame(stats_list), use_container_width=True, hide_index=True)
            st.divider()
            st.write("**🔄 今回のシフトを確定し、次の週へ進む**")
            confirm_reset = st.checkbox("シフト画像を保存済みで、投票データをリセットしてよいことを確認しました")
            if st.button("確定して累計に加算 ＆ 翌週へリセット", type="primary", disabled=not confirm_reset, use_container_width=True):
                for b in bands_dict:
                    total_stats[b] = total_stats.get(b, 0) + counts.get(b, 0)
                save_bands_to_sheet(bands_dict, total_stats)
                save_votes_to_sheet({})
                save_schedule_to_sheet(None)
                settings["round_num"] = str(round_num + 1)
                settings["week_start"] = (w_start + timedelta(days=7)).isoformat()
                save_settings_to_sheet(settings)
                st.rerun()

        st.divider()
        with st.expander("🔐 このタブのパスワード設定・変更"):
            with st.form("set_admin_pw_form"):
                new_pw = st.text_input("新しいパスワード（未設定にする場合は空欄）", value=saved_pw, type="password")
                if st.form_submit_button("💾 パスワード設定を保存", use_container_width=True):
                    settings["admin_password"] = new_pw.strip()
                    save_settings_to_sheet(settings)
                    st.session_state["admin_unlocked"] = True
                    st.rerun()
            if saved_pw and st.button("🔒 今すぐロックする", use_container_width=True):
                st.session_state["admin_unlocked"] = False
                st.rerun()
