import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta


def create_vc_tables(conn):
    """VC (Committee) system ke 4 tables - agar pehle se hain to kuch nahi hota
    (CREATE TABLE IF NOT EXISTS), history data kabhi delete nahi hota."""
    c = conn.cursor()
    try:
        c.execute('''CREATE TABLE IF NOT EXISTS vc_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vc_name TEXT NOT NULL,
            vc_type TEXT NOT NULL,
            total_members INTEGER NOT NULL,
            qist_amount REAL NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT,
            status TEXT DEFAULT 'Active',
            completed_date TEXT,
            created_date TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS vc_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vc_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            phone TEXT,
            address TEXT,
            is_owner INTEGER DEFAULT 0,
            added_date TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS vc_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vc_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            period_label TEXT NOT NULL,
            amount REAL NOT NULL,
            date TEXT NOT NULL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS vc_payouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vc_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            period_label TEXT NOT NULL,
            amount REAL NOT NULL,
            position_number INTEGER NOT NULL,
            date TEXT NOT NULL
        )''')
        # PERF FIX: 2-3 VCs chalti rahengi lambe arse tak, sath kai members aur
        # payments - indexes taake yeh page hamesha tez rahe, chahe saal purani ho
        c.execute("CREATE INDEX IF NOT EXISTS idx_vc_members_vc_id ON vc_members (vc_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_vc_payments_vc_id ON vc_payments (vc_id, member_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_vc_payouts_vc_id ON vc_payouts (vc_id, member_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_vc_list_status ON vc_list (status)")
        conn.commit()
    except sqlite3.Error as e:
        st.error(f"⚠️ VC tables set karne mein masla aaya: {e}")


def calc_end_date(start_date, vc_type, total_members):
    try:
        if vc_type == "Daily":
            return (start_date + timedelta(days=total_members - 1)).strftime("%Y-%m-%d")
        elif vc_type == "Weekly":
            return (start_date + timedelta(weeks=total_members - 1)).strftime("%Y-%m-%d")
        else:  # Monthly
            month = start_date.month - 1 + (total_members - 1)
            year = start_date.year + month // 12
            month = month % 12 + 1
            day = min(start_date.day, 28)
            return datetime(year, month, day).strftime("%Y-%m-%d")
    except Exception:
        return start_date.strftime("%Y-%m-%d")


def position_label(position, total_members):
    """Position number se 'Pehle/Beech/Akhir' badge decide karta hai."""
    if position <= 2:
        return "🔵 Pehle Nikli", "#e3f2fd", "#1565C0"
    elif position >= total_members - 1:
        return "🔴 Akhir Me Nikli", "#ffebee", "#C62828"
    else:
        return "🟡 Beech Me Nikli", "#fff8e1", "#F57C00"


def safe_vc_execute(c, query, params=(), friendly_action="VC record save"):
    try:
        c.execute(query, params)
        return True
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        if "disk" in msg or "full" in msg:
            st.error("❌ Disk space kam hai! Jagah khali karein.")
        elif "locked" in msg:
            st.error("❌ Database is waqt busy hai. Dobara try karein.")
        else:
            st.error(f"❌ {friendly_action} nahi ho saka: {e}")
        return False
    except sqlite3.Error as e:
        st.error(f"❌ {friendly_action} nahi ho saka: {e}")
        return False


def check_and_complete_vc(conn, vc_id, total_members):
    """Agar sab members ko payout mil chuka hai, VC ko khud-ba-khud 'Completed'
    kar deta hai aur History mein move ho jati hai. Yeh HAMESHA payout count
    check karta hai (5000+ payments ho tab bhi ek chhoti COUNT query hai, tez)."""
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(DISTINCT member_id) FROM vc_payouts WHERE vc_id=?", (vc_id,))
        paid_out_count = c.fetchone()[0] or 0
        if paid_out_count >= total_members:
            c.execute("UPDATE vc_list SET status='Completed', completed_date=? WHERE id=? AND status='Active'",
                      (datetime.now().strftime("%Y-%m-%d"), vc_id))
            conn.commit()
            return True
    except sqlite3.Error:
        pass
    return False


@st.cache_data(ttl=15, show_spinner=False)
def cached_vc_list(status):
    """PERF FIX: Active/Completed VC list cache hoti hai - dashboard-jaisi baar
    baar dikhne wali list ke liye DB hit har rerun pe nahi hoti."""
    try:
        conn = sqlite3.connect("afzal_store.db", timeout=10)
        df = pd.read_sql_query("SELECT * FROM vc_list WHERE status=? ORDER BY id DESC", conn, params=(status,))
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=15, show_spinner=False)
def cached_vc_members(vc_id):
    try:
        conn = sqlite3.connect("afzal_store.db", timeout=10)
        df = pd.read_sql_query("SELECT * FROM vc_members WHERE vc_id=? ORDER BY id ASC", conn, params=(vc_id,))
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def owner_summary(conn, vc_id, owner_member_id):
    """Shopkeeper (owner) ka apna hisaab: kitni di, kitni mili, balance."""
    try:
        c = conn.cursor()
        c.execute("SELECT COALESCE(SUM(amount),0) FROM vc_payments WHERE vc_id=? AND member_id=?", (vc_id, owner_member_id))
        given = c.fetchone()[0] or 0.0
        c.execute("SELECT COALESCE(SUM(amount),0), MIN(position_number) FROM vc_payouts WHERE vc_id=? AND member_id=?", (vc_id, owner_member_id))
        row = c.fetchone()
        received = row[0] or 0.0
        my_position = row[1]
        return given, received, my_position
    except sqlite3.Error:
        return 0.0, 0.0, None


def render_vc_summary_card(conn, vc_row, members_df):
    """Ek VC ka poora colorful summary card - Active aur History dono jagah use hota hai."""
    vc_id = vc_row['id']
    total_members = vc_row['total_members']

    owner_row = members_df[members_df['is_owner'] == 1]
    owner_member_id = int(owner_row.iloc[0]['id']) if not owner_row.empty else None

    st.markdown(f"""
        <div style="background: linear-gradient(135deg, #f5f7fa, #e4ebf5); padding:16px 20px; border-radius:12px; border-left:6px solid #667eea; margin-bottom:10px;">
            <h4 style="margin:0; color:#2d3748;">🤝 {vc_row['vc_name']} <span style="font-size:13px; font-weight:normal; color:#718096;">({vc_row['vc_type']})</span></h4>
            <p style="margin:4px 0 0 0; color:#4a5568; font-size:13px;">👥 {total_members} Members | 💵 Qist: Rs. {vc_row['qist_amount']:,.0f} | 📅 {vc_row['start_date']} se {vc_row['end_date']}</p>
        </div>
    """, unsafe_allow_html=True)

    if owner_member_id is not None:
        given, received, my_position = owner_summary(conn, vc_id, owner_member_id)
        balance = received - given

        col1, col2, col3 = st.columns(3)
        col1.metric("💸 Maine Kitni Qist Di", f"Rs. {given:,.0f}")
        col2.metric("💰 Mujhe Kitni Mili", f"Rs. {received:,.0f}")

        if balance >= 0:
            col3.markdown(f"""
                <div style="background:#d4edda; padding:10px; border-radius:8px; text-align:center;">
                    <p style="margin:0; color:#155724; font-size:13px;">Mera Balance</p>
                    <h4 style="margin:2px 0 0 0; color:#155724;">✅ Faiday Me: +Rs. {balance:,.0f}</h4>
                </div>
            """, unsafe_allow_html=True)
        else:
            col3.markdown(f"""
                <div style="background:#f8d7da; padding:10px; border-radius:8px; text-align:center;">
                    <p style="margin:0; color:#721c24; font-size:13px;">Mera Balance</p>
                    <h4 style="margin:2px 0 0 0; color:#721c24;">❌ Zyada Diya: -Rs. {abs(balance):,.0f}</h4>
                </div>
            """, unsafe_allow_html=True)

        if my_position:
            label, bg, fg = position_label(int(my_position), total_members)
            st.markdown(f"""
                <div style="background:{bg}; padding:8px 14px; border-radius:8px; margin-top:8px; display:inline-block;">
                    <span style="color:{fg}; font-weight:bold;">Meri VC Kab Nikli? {label} - Number {int(my_position)}/{total_members}</span>
                </div>
            """, unsafe_allow_html=True)
        else:
            st.caption("ℹ️ Aapki VC abhi tak nahi nikli.")
    else:
        st.caption("ℹ️ Is VC mein 'Mein' (owner) member set nahi hai - Member Add karte waqt 'Yeh Mein Hoon' checkbox lagayein.")


def show_vc_module(get_db):
    conn = get_db()
    create_vc_tables(conn)
    c = conn.cursor()

    st.markdown("<h3 style='color:#667eea;'>🤝 VC (Committee) Management</h3>", unsafe_allow_html=True)

    vc_tab1, vc_tab2, vc_tab3, vc_tab4, vc_tab5 = st.tabs([
        "➕ Nayi VC Banayen", "👥 Member Add Karo", "💰 Collection & Payout", "📊 Active VCs", "📜 VC History / Purani VCs"
    ])

    # ==================== NAYI VC BANAYEN ====================
    with vc_tab1:
        st.subheader("➕ Nayi VC Banayen")
        with st.form("new_vc_form", clear_on_submit=True):
            vc_name = st.text_input("VC Ka Naam*", placeholder="Jaise: Ghar Wali VC, Dukan VC...")
            col1, col2 = st.columns(2)
            with col1:
                vc_type = st.selectbox("VC Type*", ["Daily", "Weekly", "Monthly"])
                total_members = st.number_input("Total Members*", min_value=2, max_value=100, value=10, step=1)
            with col2:
                qist_amount = st.number_input("Qist Amount (Rs.)*", min_value=1.0, step=100.0, value=1000.0)
                start_date = st.date_input("Start Date*", value=datetime.now())

            preview_end = calc_end_date(datetime.combine(start_date, datetime.min.time()), vc_type, total_members)
            st.info(f"📅 **End Date (Auto-Calculate):** {preview_end}")

            if st.form_submit_button("💾 VC Save Karo", type="primary", use_container_width=True):
                if vc_name and vc_name.strip() and total_members >= 2 and qist_amount > 0:
                    end_date_str = calc_end_date(datetime.combine(start_date, datetime.min.time()), vc_type, total_members)
                    ok = safe_vc_execute(c, """INSERT INTO vc_list (vc_name, vc_type, total_members, qist_amount, start_date, end_date, status, created_date)
                                 VALUES (?,?,?,?,?,?,?,?)""",
                              (vc_name.strip(), vc_type, total_members, qist_amount, start_date.strftime("%Y-%m-%d"),
                               end_date_str, 'Active', datetime.now().strftime("%Y-%m-%d")), "Nayi VC")
                    if ok:
                        conn.commit()
                        st.cache_data.clear()
                        st.success(f"✔️ '{vc_name}' VC ban gayi! Ab 'Member Add Karo' tab se members shamil karein.")
                        st.rerun()
                else:
                    st.error("❌ VC Naam, Members (kam se kam 2) aur Qist Amount lazmi hain!")

    # ==================== MEMBER ADD KARO ====================
    with vc_tab2:
        st.subheader("👥 Member Add Karo")
        active_vcs = cached_vc_list("Active")

        if active_vcs.empty:
            st.info("Pehle koi VC banayein.")
        else:
            vc_options = {f"{row['vc_name']} ({row['vc_type']})": row['id'] for _, row in active_vcs.iterrows()}
            selected_vc_label = st.selectbox("VC Chunein", list(vc_options.keys()), key="member_vc_select")
            selected_vc_id = vc_options[selected_vc_label]
            vc_row = active_vcs[active_vcs['id'] == selected_vc_id].iloc[0]

            members_df = cached_vc_members(selected_vc_id)
            st.caption(f"👥 Ab tak {len(members_df)} / {vc_row['total_members']} members shamil hain")

            if len(members_df) >= vc_row['total_members']:
                st.warning(f"⚠️ Is VC mein already poore {vc_row['total_members']} members shamil ho chuke hain.")
            else:
                with st.form("add_member_form", clear_on_submit=True):
                    m_name = st.text_input("Member Ka Naam*")
                    col1, col2 = st.columns(2)
                    with col1:
                        m_phone = st.text_input("Phone Number")
                    with col2:
                        m_address = st.text_input("Address")
                    is_me = st.checkbox("✅ Yeh Mein Hoon (Shopkeeper/Owner)", help="Apna khud ka naam add karte waqt yeh check karein - is se 'Meri VC Kab Nikli' tracker kaam karega")

                    if st.form_submit_button("➕ Member Add Karo", type="primary", use_container_width=True):
                        if m_name and m_name.strip():
                            if is_me and (members_df['is_owner'] == 1).any():
                                st.error("❌ Is VC mein already ek 'Mein' (owner) member set hai - sirf ek hi ho sakta hai.")
                            else:
                                ok = safe_vc_execute(c, """INSERT INTO vc_members (vc_id, name, phone, address, is_owner, added_date)
                                             VALUES (?,?,?,?,?,?)""",
                                          (selected_vc_id, m_name.strip(), m_phone, m_address, 1 if is_me else 0,
                                           datetime.now().strftime("%Y-%m-%d")), "Member")
                                if ok:
                                    conn.commit()
                                    st.cache_data.clear()
                                    st.success(f"✔️ {m_name} shamil ho gaye!")
                                    st.rerun()
                        else:
                            st.error("❌ Member ka naam likhna lazmi hai!")

            if not members_df.empty:
                st.divider()
                st.markdown("**Members List:**")
                display_members = members_df[['name', 'phone', 'address', 'is_owner']].copy()
                display_members['is_owner'] = display_members['is_owner'].apply(lambda x: "✅ Mein" if x == 1 else "")
                display_members.columns = ['Naam', 'Phone', 'Address', 'Owner']
                st.dataframe(display_members, use_container_width=True, hide_index=True)

    # ==================== COLLECTION & PAYOUT ====================
    with vc_tab3:
        st.subheader("💰 Collection & Payout")
        active_vcs = cached_vc_list("Active")

        if active_vcs.empty:
            st.info("Koi active VC nahi hai.")
        else:
            vc_options = {f"{row['vc_name']} ({row['vc_type']})": row['id'] for _, row in active_vcs.iterrows()}
            selected_vc_label = st.selectbox("VC Chunein", list(vc_options.keys()), key="collect_vc_select")
            selected_vc_id = vc_options[selected_vc_label]
            vc_row = active_vcs[active_vcs['id'] == selected_vc_id].iloc[0]
            members_df = cached_vc_members(selected_vc_id)

            if members_df.empty:
                st.warning("Is VC mein abhi tak koi member nahi hai - pehle 'Member Add Karo' se members shamil karein.")
            else:
                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown("#### 📥 Qist Collection")
                    if vc_row['vc_type'] == "Daily":
                        period_date = st.date_input("Kis Din Ki Qist?", value=datetime.now(), key="collect_period_daily")
                        period_label = period_date.strftime("%Y-%m-%d")
                    elif vc_row['vc_type'] == "Weekly":
                        period_date = st.date_input("Kis Hafte Ki Qist?", value=datetime.now(), key="collect_period_weekly")
                        period_label = period_date.strftime("%Y-W%W")
                    else:
                        period_date = st.date_input("Kis Mahine Ki Qist?", value=datetime.now(), key="collect_period_monthly")
                        period_label = period_date.strftime("%Y-%m")

                    try:
                        c.execute("SELECT DISTINCT member_id FROM vc_payments WHERE vc_id=? AND period_label=?", (selected_vc_id, period_label))
                        already_paid_ids = {r[0] for r in c.fetchall()}
                    except sqlite3.Error:
                        already_paid_ids = set()

                    pending_members = members_df[~members_df['id'].isin(already_paid_ids)]
                    if pending_members.empty:
                        st.success(f"✅ Is period ({period_label}) ki qist sab members se le li gayi hai.")
                    else:
                        member_labels = [f"{row['name']}" + (" (Mein)" if row['is_owner'] == 1 else "") for _, row in pending_members.iterrows()]
                        selected_members = st.multiselect("Kin Members Ki Qist Aayi? (Kai Ek Saath Select Kar Sakte Hain)", member_labels, key="collect_members_multi")
                        collect_amount = st.number_input("Qist Amount", value=float(vc_row['qist_amount']), step=50.0, key="collect_amount")

                        if st.button("💾 Collection Save Karo", type="primary", use_container_width=True, key="collect_save_btn"):
                            if selected_members:
                                saved = 0
                                for lbl in selected_members:
                                    idx = member_labels.index(lbl)
                                    member_id = int(pending_members.iloc[idx]['id'])
                                    ok = safe_vc_execute(c, """INSERT INTO vc_payments (vc_id, member_id, period_label, amount, date)
                                                 VALUES (?,?,?,?,?)""",
                                              (selected_vc_id, member_id, period_label, collect_amount, datetime.now().strftime("%Y-%m-%d")), "Qist collection")
                                    if ok:
                                        saved += 1
                                conn.commit()
                                st.cache_data.clear()
                                st.success(f"✔️ {saved} members ki qist collect ho gayi!")
                                st.rerun()
                            else:
                                st.error("❌ Kam se kam ek member select karein!")

                with col_b:
                    st.markdown("#### 🎁 Is Baar Kisko Mila? (Payout)")
                    try:
                        c.execute("SELECT member_id FROM vc_payouts WHERE vc_id=?", (selected_vc_id,))
                        already_paidout_ids = {r[0] for r in c.fetchall()}
                    except sqlite3.Error:
                        already_paidout_ids = set()

                    remaining_members = members_df[~members_df['id'].isin(already_paidout_ids)]
                    if remaining_members.empty:
                        st.success("🎉 Sab members ko payout mil chuka hai! Yeh VC 'Completed' honi chahiye.")
                    else:
                        payout_labels = [f"{row['name']}" + (" (Mein)" if row['is_owner'] == 1 else "") for _, row in remaining_members.iterrows()]
                        selected_payout_label = st.selectbox("Konsa Member?", payout_labels, key="payout_member_select")
                        next_position = len(already_paidout_ids) + 1
                        position_number = st.number_input("Number Konsa Hai? (Position)", min_value=1, max_value=int(vc_row['total_members']), value=next_position, key="payout_position")
                        payout_amount = st.number_input("Payout Amount (Rs.)", value=float(vc_row['qist_amount']) * float(vc_row['total_members']), step=100.0, key="payout_amount")

                        if st.button("✅ Payout Confirm Karo", type="primary", use_container_width=True, key="payout_save_btn"):
                            payout_idx = payout_labels.index(selected_payout_label)
                            payout_member_id = int(remaining_members.iloc[payout_idx]['id'])
                            ok = safe_vc_execute(c, """INSERT INTO vc_payouts (vc_id, member_id, period_label, amount, position_number, date)
                                         VALUES (?,?,?,?,?,?)""",
                                      (selected_vc_id, payout_member_id, period_label, payout_amount, position_number, datetime.now().strftime("%Y-%m-%d")), "Payout")
                            if ok:
                                conn.commit()
                                st.cache_data.clear()
                                completed = check_and_complete_vc(conn, selected_vc_id, int(vc_row['total_members']))
                                st.cache_data.clear()
                                if completed:
                                    st.balloons()
                                    st.success(f"🎉 Payout confirm ho gaya! Sab {vc_row['total_members']} members ko payout mil chuka hai - yeh VC ab 'COMPLETED' hai aur History mein move ho gayi!")
                                else:
                                    st.success("✔️ Payout confirm ho gaya!")
                                st.rerun()

                st.divider()
                st.markdown("#### 📋 Is VC Ki Poori Table (Date/Month | Member | Amount | Position | Status)")
                try:
                    combined_df = pd.read_sql_query("""
                        SELECT p.date as 'Date/Month', m.name as Member, p.amount as Amount, p.position_number as Position
                        FROM vc_payouts p JOIN vc_members m ON p.member_id = m.id
                        WHERE p.vc_id = ? ORDER BY p.position_number ASC
                    """, conn, params=(selected_vc_id,))
                    if not combined_df.empty:
                        combined_df['Status'] = combined_df['Position'].apply(lambda x: position_label(int(x), int(vc_row['total_members']))[0])
                        st.dataframe(combined_df, use_container_width=True, hide_index=True)
                    else:
                        st.caption("Abhi tak koi payout nahi hua.")
                except sqlite3.Error as e:
                    st.warning(f"⚠️ Table load nahi ho saki: {e}")

    # ==================== ACTIVE VCs ====================
    with vc_tab4:
        st.subheader("📊 Active VCs")
        active_vcs = cached_vc_list("Active")

        if active_vcs.empty:
            st.info("Koi active VC nahi hai. 'Nayi VC Banayen' tab se shuru karein.")
        else:
            for _, vc_row in active_vcs.iterrows():
                with st.expander(f"🤝 {vc_row['vc_name']} ({vc_row['vc_type']}) - {vc_row['total_members']} Members", expanded=False):
                    members_df = cached_vc_members(vc_row['id'])
                    render_vc_summary_card(conn, vc_row, members_df)

    # ==================== VC HISTORY ====================
    with vc_tab5:
        st.subheader("📜 VC History / Purani VCs")
        st.caption("Yeh data permanent hai - kabhi delete nahi hota.")
        completed_vcs = cached_vc_list("Completed")

        if completed_vcs.empty:
            st.info("Abhi tak koi VC complete nahi hui.")
        else:
            for _, vc_row in completed_vcs.iterrows():
                with st.expander(f"✅ {vc_row['vc_name']} ({vc_row['vc_type']}) - Completed on {vc_row['completed_date']}", expanded=False):
                    members_df = cached_vc_members(vc_row['id'])
                    total_handled = vc_row['qist_amount'] * vc_row['total_members'] * vc_row['total_members']

                    st.markdown(f"**VC Name:** {vc_row['vc_name']} | **Type:** {vc_row['vc_type']} | **Start:** {vc_row['start_date']} | **End:** {vc_row['end_date']}")
                    st.markdown(f"**💰 Total Amount Handled:** Rs. {total_handled:,.0f}")

                    st.divider()
                    st.markdown("##### 👤 Meri Personal Summary")
                    render_vc_summary_card(conn, vc_row, members_df)

                    st.divider()
                    st.markdown("##### 📋 Poori Member-Wise Payout Order")
                    try:
                        order_df = pd.read_sql_query("""
                            SELECT p.position_number as Position, m.name as Member, p.amount as Amount, p.date as Date
                            FROM vc_payouts p JOIN vc_members m ON p.member_id = m.id
                            WHERE p.vc_id = ? ORDER BY p.position_number ASC
                        """, conn, params=(vc_row['id'],))
                        if not order_df.empty:
                            order_df['Status'] = order_df['Position'].apply(lambda x: position_label(int(x), int(vc_row['total_members']))[0])
                            st.dataframe(order_df, use_container_width=True, hide_index=True)

                            order_text = "\n".join([f"{r['Position']}. {r['Member']} ({position_label(int(r['Position']), int(vc_row['total_members']))[0]})" for _, r in order_df.iterrows()])
                            st.text_area("📋 Poori History (Copy/Print Ke Liye)", f"VC: {vc_row['vc_name']} ({vc_row['vc_type']})\n{vc_row['start_date']} se {vc_row['end_date']}\n\n{order_text}", height=200, key=f"history_text_{vc_row['id']}")
                        else:
                            st.caption("Koi payout record nahi mila.")
                    except sqlite3.Error as e:
                        st.warning(f"⚠️ History load nahi ho saki: {e}")

    conn.close()
