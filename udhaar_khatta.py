import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import base64
import streamlit.components.v1 as components
import camera_ocr
import google_drive_backup as gdrive
import image_compression
import sync_manager


def format_quantity(kg_value):
    grams = kg_value * 1000
    if kg_value >= 1:
        kg_part = int(kg_value)
        gram_part = int(grams % 1000)
        if gram_part == 0:
            return f"{kg_part} KG"
        return f"{kg_part} KG {gram_part} gram"
    else:
        if grams == 500: return "500 gram"
        elif grams == 250: return "250 gram"
        elif grams == 125: return "125 gram"
        else: return f"{int(grams)} gram"


def update_qty_callback():
    unit = st.session_state.get("khata_unit", "KG")
    rate = st.session_state.get("khata_rate", 0.0)
    amt = st.session_state.get("khata_amt_entry", 0.0)

    factor = {"Pao": 0.25, "Ada Pao": 0.125, "Ada Kilo": 0.5, "Gram": 0.001}.get(unit, 1.0)

    if amt > 0 and rate > 0:
        kg_val = amt / (rate * factor)
        st.session_state["khata_qty"] = round(kg_val, 3)
        st.session_state["formatted_display"] = format_quantity(kg_val)
        st.session_state["khata_amt_entry"] = 0.0


def show_udhaar_khatta(get_db):
    filtered_cust = []

    conn = get_db()
    c = conn.cursor()

    def safe_execute(query, params=(), friendly_action="Record save"):
        """Har INSERT/UPDATE/DELETE is se guzarta hai - koi bhi DB error aaye to app
        crash hone ke bajaye saaf error dikhayega aur data safe rahega."""
        try:
            c.execute(query, params)
            return True
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "disk" in msg or "full" in msg:
                st.error("❌ Disk space kam hai! Jagah khali karein, phir dobara try karein.")
            elif "locked" in msg:
                st.error("❌ Database is waqt busy hai. Dobara button dabayein.")
            else:
                st.error(f"❌ {friendly_action} nahi ho saka: {e}")
            return False
        except sqlite3.Error as e:
            st.error(f"❌ {friendly_action} nahi ho saka: {e}")
            return False

    try:
        c.execute('''CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, address TEXT, manual_status TEXT, customer_type TEXT, photo BLOB)''')
        c.execute('''CREATE TABLE IF NOT EXISTS udhaar (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, date TEXT, type TEXT, amount REAL, item TEXT, qty REAL, rate REAL, detail TEXT, time TEXT, unit TEXT, pehle_baaki REAL, baad_baaki REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rate REAL, stock REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS stock_history (id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT, qty REAL, action TEXT, date TEXT, time TEXT, user TEXT)''')

        try:
            c.execute("ALTER TABLE customers ADD COLUMN khata_no INTEGER")
        except sqlite3.OperationalError:
            pass

        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_udhaar_customer_id2 ON udhaar (customer_id, date)")
        except sqlite3.OperationalError:
            pass

        conn.commit()
    except sqlite3.Error as e:
        st.error(f"⚠️ Udhaar Khatta tables set karne mein masla aaya: {e}")

    if 'selected_customer_id' not in st.session_state:
        st.session_state['selected_customer_id'] = None
    if 'editing_entry_id' not in st.session_state:
        st.session_state['editing_entry_id'] = None
    if 'editing_item_id' not in st.session_state:
        st.session_state['editing_item_id'] = None
    if 'show_total_baaki' not in st.session_state:
        st.session_state['show_total_baaki'] = False

    st.markdown("""
    <style>
    @keyframes smooth-blink {
        0% { opacity: 1; }
        50% { opacity: 0.4; }
        100% { opacity: 1; }
    }
    @keyframes fast-blink {
        0% { opacity: 1; }
        50% { opacity: 0.1; }
        100% { opacity: 1; }
    }
    .dot-green { height: 18px; width: 18px; background-color: #28a745; border-radius: 50%; display: inline-block; animation: smooth-blink 3s infinite; margin-top: 22px; }
    .dot-orange { height: 18px; width: 18px; background-color: #fd7e14; border-radius: 50%; display: inline-block; animation: smooth-blink 1.5s infinite; margin-top: 22px; }
    .dot-red { height: 18px; width: 18px; background-color: #dc3545; border-radius: 50%; display: inline-block; animation: fast-blink 0.8s infinite; margin-top: 22px; }
    .whatsapp-avatar {
        width: 60px!important; height: 60px!important; border-radius: 50%!important;
        object-fit: cover!important; object-position: center!important;
        display: inline-block!important; border: 1px solid #ccc!important;
    }
    div[data-baseweb="tab-list"] button {
        border-radius: 12px!important; padding: 6px 16px!important;
        margin-right: 8px!important; border: none!important;
        transition: all 0.2s ease-in-out;
    }
    /* 1. Baaki Dekho - Soft Red/Orange */
    div[data-baseweb="tab-list"] button:nth-of-type(1) { background: linear-gradient(135deg, #ff9a76, #ff6a5c)!important; }
    div[data-baseweb="tab-list"] button:nth-of-type(1) p { color: white!important; font-weight: bold!important; font-size: 15px!important; }
    /* 2. Sab Customers Ki List - Soft Blue */
    div[data-baseweb="tab-list"] button:nth-of-type(2) { background: linear-gradient(135deg, #74b9ff, #4e8ef7)!important; }
    div[data-baseweb="tab-list"] button:nth-of-type(2) p { color: white!important; font-weight: bold!important; font-size: 15px!important; }
    /* 3. Jama Karo - Soft Green */
    div[data-baseweb="tab-list"] button:nth-of-type(3) { background: linear-gradient(135deg, #6fdc8c, #34c759)!important; }
    div[data-baseweb="tab-list"] button:nth-of-type(3) p { color: white!important; font-weight: bold!important; font-size: 15px!important; }
    /* 4. Naya Udhaar - Soft Purple */
    div[data-baseweb="tab-list"] button:nth-of-type(4) { background: linear-gradient(135deg, #b28dff, #8c6bff)!important; }
    div[data-baseweb="tab-list"] button:nth-of-type(4) p { color: white!important; font-weight: bold!important; font-size: 15px!important; }
    /* 5. Udhaar Book Scan - Soft Teal */
    div[data-baseweb="tab-list"] button:nth-of-type(5) { background: linear-gradient(135deg, #5fd9d0, #2bb3a3)!important; }
    div[data-baseweb="tab-list"] button:nth-of-type(5) p { color: white!important; font-weight: bold!important; font-size: 15px!important; }
    /* 6. Customer Setting - Soft Grey/Black */
    div[data-baseweb="tab-list"] button:nth-of-type(6) { background: linear-gradient(135deg, #6c757d, #495057)!important; }
    div[data-baseweb="tab-list"] button:nth-of-type(6) p { color: white!important; font-weight: bold!important; font-size: 15px!important; }

    /* Print Bill - Red | WhatsApp - Green (distinct action buttons) */
    button[aria-label="🖨️ Print Bill"] {
        background: linear-gradient(135deg, #ff6b6b, #e63946)!important;
        color: white!important; font-weight: bold!important; border: none!important; border-radius: 10px!important;
    }
    button[aria-label="📱 WhatsApp Message Banao"] {
        background: linear-gradient(135deg, #25D366, #128C7E)!important;
        color: white!important; font-weight: bold!important; border: none!important; border-radius: 10px!important;
    }
    </style>
    """, unsafe_allow_html=True)

    def get_customer_status(cust_id):
        try:
            c.execute("SELECT manual_status FROM customers WHERE id=?", (cust_id,))
            res = c.fetchone()
            manual = res[0] if res and res[0] else 'Auto'
            if manual != 'Auto':
                return manual.lower(), 0
            c.execute("SELECT date FROM udhaar WHERE customer_id=? AND type='jama' ORDER BY date DESC LIMIT 1", (cust_id,))
            last_jama = c.fetchone()
            if not last_jama:
                c.execute("SELECT SUM(amount) FROM udhaar WHERE customer_id=? AND type='udhaar'", (cust_id,))
                has_udhaar = (c.fetchone()[0] or 0) > 0
                return ('red', 999) if has_udhaar else ('green', 0)
            try:
                days_diff = (datetime.now() - datetime.strptime(last_jama[0], "%Y-%m-%d")).days
            except Exception:
                days_diff = 0
            if days_diff < 60:
                return 'green', days_diff
            elif days_diff < 90:
                return 'orange', days_diff
            return 'red', days_diff
        except sqlite3.Error:
            return 'green', 0  # DB error - safe default, page kabhi crash nahi hogi is wajah se

    def get_baaki(cust_id):
        try:
            c.execute("SELECT IFNULL(SUM(CASE WHEN type='udhaar' THEN amount ELSE 0 END), 0) - IFNULL(SUM(CASE WHEN type='jama' THEN amount ELSE 0 END), 0) FROM udhaar WHERE customer_id =?", (cust_id,))
            res = c.fetchone()
            return res[0] if res and res[0] else 0
        except sqlite3.Error:
            return 0

    def get_all_items():
        try:
            c.execute("PRAGMA table_info(items);")
            columns = [col[1].lower() for col in c.fetchall()]
            if 'sale_price' in columns:
                c.execute("SELECT name, sale_price FROM items ORDER BY name")
            elif 'price' in columns:
                c.execute("SELECT name, price FROM items ORDER BY name")
            elif 'default_rate' in columns:
                c.execute("SELECT name, default_rate FROM items ORDER BY name")
            else:
                c.execute("SELECT name FROM items ORDER BY name")
            return c.fetchall()
        except Exception:
            return []

    def update_main_stock(item_name, qty_to_reduce, unit, customer_name):
        try:
            c.execute("SELECT stock FROM items WHERE name=?", (item_name,))
            result = c.fetchone()
            if not result:
                return False
            old_stock = result[0] or 0
            new_stock = old_stock - qty_to_reduce
            ok1 = safe_execute("UPDATE items SET stock=? WHERE name=?", (new_stock, item_name), "Stock update")
            ok2 = safe_execute("""INSERT INTO stock_history (item_name, date, action, qty, time, user) VALUES (?,?,?,?,?,?)""",
                (item_name, datetime.now().strftime("%Y-%m-%d"), 'sale', qty_to_reduce, datetime.now().strftime("%H:%M:%S"), f"Udhaar diya - {customer_name} (Udhaar Khatta)"),
                "Stock history")
            if ok1 and ok2:
                conn.commit()
                return True
            conn.rollback()
            return False
        except sqlite3.Error as e:
            st.error(f"Stock update error: {e}")
            return False

    def render_html_photo(photo_bytes):
        if photo_bytes:
            base64_photo = base64.b64encode(photo_bytes).decode()
            return f'<img src="data:image/jpeg;base64,{base64_photo}" class="whatsapp-avatar" style="width:60px; height:60px; border-radius:50%; object-fit:cover; object-position:center;" />'
        return '<div class="whatsapp-default-avatar">👤</div>'

    st.subheader("📒 Udhaar Khatta - Khata Dar")

    # PERF FIX: yeh list ab 15-second cache karta hai. Customer list badalne (naya
    # customer, entry, payment) ke baad st.cache_data.clear() se turant fresh ho jaata hai.
    @st.cache_data(ttl=15, show_spinner="Customers load ho rahe hain...")
    def cached_customer_list():
        try:
            return pd.read_sql_query("""
                SELECT c.id, c.name, c.phone, c.photo,
                       IFNULL(SUM(CASE WHEN u.type='udhaar' THEN u.amount ELSE 0 END), 0) - IFNULL(SUM(CASE WHEN u.type='jama' THEN u.amount ELSE 0 END), 0) as baaki,
                       c.address, c.manual_status, c.customer_type, c.khata_no
                FROM customers c
                LEFT JOIN udhaar u ON c.id = u.customer_id
                GROUP BY c.id
                ORDER BY IFNULL(c.khata_no, 999) ASC, c.name ASC
            """, conn).values.tolist()
        except Exception as e:
            st.error(f"⚠️ Customers list load nahi ho saki: {e}")
            return []

    customers = cached_customer_list()

    # PERF FIX: monthly totals/clear-status ALWAYS aik SQL aggregate query se aate
    # hain (poori history se, chahe customer ki 5000+ entries hon) - is se yeh
    # kabhi bhi sirf "displayed" (capped) entries se ghalat calculate nahi hote,
    # aur SQL GROUP BY hone ki wajah se yeh hamesha tez rehta hai.
    @st.cache_data(ttl=15, show_spinner=False)
    def cached_monthly_summary(customer_id):
        try:
            df = pd.read_sql_query("""
                SELECT strftime('%Y-%m', date) as ym,
                       SUM(CASE WHEN type='udhaar' THEN amount ELSE 0 END) as udhaar_total,
                       SUM(CASE WHEN type='jama' THEN amount ELSE 0 END) as jama_total
                FROM udhaar WHERE customer_id = ? AND date IS NOT NULL
                GROUP BY ym ORDER BY ym DESC
            """, conn, params=(customer_id,))
            return df
        except Exception as e:
            st.warning(f"⚠️ Monthly summary load nahi ho saka: {e}")
            return pd.DataFrame(columns=["ym", "udhaar_total", "jama_total"])


    if not customers:
        st.warning("Please add a customer first from 'Roz Ka Roll Nama'")

    tab1, tab_list, tab3, tab2, tab_scan, tab4 = st.tabs([
        "📊 Baaki Dekho", "📋 Sab Customers Ki List", "💰 Jama Karo",
        "💸 Naya Udhaar", "📷 Udhaar Book Scan", "⚙ Customer Setting"
    ])

    # ==================== TAB 1: BAAKI DEKHO ====================
    with tab1:
        st.markdown("### Sab Customers Ka Hisab")
        total_cust = len(customers)
        total_baaki_all = sum([cust[4] for cust in customers]) if customers else 0

        col_sum1, col_sum2, col_sum3 = st.columns(3)
        col_sum1.metric("**Total Customers**", f"{total_cust}")

        if st.session_state.get('show_total_baaki', False):
            col_sum2.metric("**Sab Ka Total Baaki**", f"Rs. {total_baaki_all:,.0f}")
        else:
            col_sum2.metric("**Sab Ka Total Baaki**", "••••••")

        with col_sum3:
            if customers:
                cust_options = {}
                for idx, cust in enumerate(customers, 1):
                    numbered_name = f"{idx}. {cust[1]} ({cust[7]})"
                    cust_options[numbered_name] = cust[0]

                default_index = None
                if st.session_state['selected_customer_id']:
                    current_cust_name = next((cust[1] for cust in customers if cust[0] == st.session_state['selected_customer_id']), None)
                    if current_cust_name:
                        matching_key = next((k for k in cust_options.keys() if current_cust_name in k), None)
                        if matching_key:
                            default_index = list(cust_options.keys()).index(matching_key)

                selected_name = st.selectbox(
                    "**Customer Select Karo**",
                    options=[""] + list(cust_options.keys()),
                    key="main_cust_select",
                    index=default_index + 1 if default_index is not None else 0,
                    placeholder="Customer Chuno..."
                )

                if selected_name:
                    st.session_state['selected_customer_id'] = cust_options.get(selected_name)
                elif selected_name == "":
                    st.session_state['selected_customer_id'] = None

        st.markdown("---")

        if st.session_state['selected_customer_id']:
            active_id = st.session_state['selected_customer_id']
            cust_row = next((cust for cust in customers if cust[0] == active_id), None)
            if cust_row:
                cust_id, name, phone, photo, baaki, _, _, cust_type, _ = cust_row
                dot_status, days_passed = get_customer_status(cust_id)

                col_head1, col_head2, col_head3, col_head4 = st.columns([1, 3, 2, 2])
                with col_head1:
                    st.markdown(render_html_photo(photo), unsafe_allow_html=True)
                with col_head2:
                    if dot_status == 'red' and days_passed >= 90:
                        st.subheader(f"📖 {name} Ka Khata 🚫 (Blacklisted)")
                    else:
                        st.subheader(f"📖 {name} Ka Khata - {cust_type}")
                with col_head3:
                    st.info(f"📞 {phone or 'N/A'}")
                with col_head4:
                    st.error(f"**Baaki: Rs. {baaki:,.0f}**") if baaki > 0 else st.success("**Hisab Clear**")

                with st.expander("➕ Naya Udhaar/Jama Add Karo", expanded=False):
                    entry_type = st.radio("Type", ["Udhaar", "Jama"], horizontal=True, key="khata_type")
                    col_d1, col_d2 = st.columns(2)
                    with col_d1:
                        entry_date = st.date_input("Date Chuno", value=datetime.now().date(), key="khata_date")
                    with col_d2:
                        entry_time = st.time_input("Time Chuno", value=datetime.now().time(), key="khata_time")

                    item_mode = None
                    if entry_type == "Udhaar":
                        all_items = get_all_items()
                        item_display_list = [f"{i[0]} - Rs. {i[1]:g}" for i in all_items]
                        item_rates = {i[0]: i[1] for i in all_items}
                        item_name_map = {f"{i[0]} - Rs. {i[1]:g}": i[0] for i in all_items}

                        item_mode = st.radio("Entry Type", ["📋 List Se Chuno", "✏ Naya Likho", "💵 Cash Udhaar"], horizontal=True, key="khata_item_mode")

                        if item_mode == "📋 List Se Chuno":
                            selected_display = st.selectbox("Item", options=[""] + item_display_list, key="khata_item_select")
                            item = item_name_map.get(selected_display, "")
                            if item and st.session_state.get('last_selected_item') != item:
                                st.session_state['khata_rate'] = item_rates.get(item, 0.0)
                                st.session_state['last_selected_item'] = item
                                st.rerun()
                        elif item_mode == "✏ Naya Likho":
                            item = st.text_input("Naya Item Likho", key="khata_item_text")
                        else:
                            item = "Cash Udhaar"
                            st.info("💵 Customer ko cash udhaar diya gaya - Sirf amount likho")

                        if item_mode == "💵 Cash Udhaar":
                            amount = st.number_input("Cash Amount*", min_value=0.0, value=1000.0, step=100.0, key="khata_cash_amt")
                            qty = 1
                            rate = amount
                            unit = "Cash"
                            formatted_qty = "Cash"
                            st.success(f"**Total Amount: Rs. {amount:,.0f}**")
                        else:
                            col_a1, col_a2, col_a3, col_a4 = st.columns(4)
                            with col_a1:
                                unit = st.selectbox("Unit", ["KG", "Gram", "Pao", "Ada Pao", "Ada Kilo", "Dozen", "Adad"], key="khata_unit")
                            with col_a2:
                                qty = st.number_input("Qty", min_value=0.0, step=0.25, key="khata_qty")
                            with col_a3:
                                rate = st.number_input("Rate", min_value=0.0, step=10.0, key="khata_rate")
                            with col_a4:
                                st.write("**OR**")
                                total_amount_entry = st.number_input("Total Amount (Rs.)", min_value=0.0, step=10.0, key="khata_amt_entry", on_change=update_qty_callback)

                            factor = {"Pao": 0.25, "Ada Pao": 0.125, "Ada Kilo": 0.5, "Gram": 0.001}.get(unit, 1.0)
                            actual_qty = qty * factor
                            amount = actual_qty * rate

                            formatted_qty = st.session_state.get("formatted_display", f"{qty} {unit}")
                            st.info(f"**Total: {formatted_qty} | Amount: Rs. {amount:,.0f}**")

                        detail = st.text_input("Extra Detail", key="khata_detail", value="Cash udhaar diya" if item_mode == "💵 Cash Udhaar" else "")
                        pehle_baaki, baad_baaki = None, None
                    else:
                        pehle_baaki = get_baaki(cust_id)
                        amount = st.number_input("Jama Raqam", min_value=0.0, step=100.0, key="khata_jama_amt")
                        baad_baaki = pehle_baaki - amount
                        st.warning(f"**Pehle Baaki: Rs. {pehle_baaki:,.0f}** | **Ab Baaki: Rs. {baad_baaki:,.0f}**")
                        detail = st.text_input("Detail", value="Cash Jama", key="khata_jama_detail")
                        item, qty, rate, unit = None, None, None, None

                    if st.button("Save Karo", type="primary", use_container_width=True, key="save_entry_btn"):
                        if entry_type == "Udhaar" and item_mode != "💵 Cash Udhaar" and not item:
                            st.error("Item name likho ya select karo!")
                        elif amount is None or amount <= 0:
                            st.error("Amount 0 se zyada hona chahiye!")
                        else:
                            ok = safe_execute(
                                "INSERT INTO udhaar (customer_id, date, type, amount, item, qty, rate, detail, time, unit, pehle_baaki, baad_baaki) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                (cust_id, entry_date.strftime("%Y-%m-%d"), entry_type.lower(), amount, item, qty, rate, detail, entry_time.strftime("%I:%M %p"), unit, pehle_baaki, baad_baaki),
                                "Khata entry")
                            if ok:
                                conn.commit()
                                st.cache_data.clear()
                                st.success("Entry Saved successfully!")
                                for key in ['khata_qty', 'khata_rate', 'khata_amt_entry', 'last_selected_item', 'khata_cash_amt']:
                                    if key in st.session_state:
                                        del st.session_state[key]
                                st.rerun()
                st.markdown("---")
                st.markdown("""
                    <div style="background: linear-gradient(135deg, #fff3cd, #ffe08a); padding:12px 18px; border-radius:10px; border-left:6px solid #f0a500; margin:10px 0;">
                        <h3 style="margin:0; color:#7a5b00;">📜 Poora Khata - Action Panel</h3>
                    </div>
                """, unsafe_allow_html=True)

                if 'whatsapp_msg' not in st.session_state:
                    st.session_state['whatsapp_msg'] = ""

                col1, col2 = st.columns(2)

                with col1:
                    if st.button("📱 WhatsApp Message Banao", type="secondary", use_container_width=True):
                        selected_ids = [k.split("_")[1] for k, v in st.session_state.items() if k.startswith("chk_") and v]
                        if selected_ids:
                            try:
                                c.execute(f"SELECT item, qty, unit, amount FROM udhaar WHERE id IN ({','.join(['?']*len(selected_ids))}) AND type='udhaar'", selected_ids)
                                selected_entries = c.fetchall()
                            except sqlite3.Error as e:
                                st.error(f"⚠️ Message nahi ban saka: {e}")
                                selected_entries = []

                            current_date = datetime.now().strftime("%Y-%m-%d")
                            msg = f"*AFZAL KRIYANA STORE*\n*Customer: {name}*\n*Date: {current_date}*\n─────────────────\n"
                            tot = 0
                            for idx, (it, qt, un, am) in enumerate(selected_entries, 1):
                                qt_disp = qt if qt is not None else 0
                                msg += f"{idx}. {it or 'Item'} | {qt_disp:g} {un or 'KG'} = *Rs. {(am or 0):,.0f}*\n"
                                tot += (am or 0)
                            msg += f"─────────────────\n*Total: Rs. {tot:,.0f}*"
                            st.session_state['whatsapp_msg'] = msg
                        else:
                            st.warning("Pehle transactions select karein side waale Checkbox se!")

                with col2:
                    if st.button("🖨️ Print Bill", type="primary", use_container_width=True):
                        selected_ids = [k.split("_")[1] for k, v in st.session_state.items() if k.startswith("chk_") and v]
                        if selected_ids:
                            components.html("<script>window.print();</script>", height=0)
                        else:
                            st.warning("Pehle print karne ke liye transactions select karein!")

                if st.session_state.get('whatsapp_msg'):
                    st.text_area("📋 WhatsApp Text Copy Karo:", st.session_state['whatsapp_msg'], height=150)
                    if st.button("Clear Msg"):
                        st.session_state['whatsapp_msg'] = ""
                        st.rerun()

                # PERF FIX: pehle is customer ki SAARI history (saalon ka data ho sakta hai)
                # ek saath load hoti thi - ab default sirf latest 300 entries, aur agar
                # zyada hain to "Purani History Dekho" checkbox se poori dikhti hai.
                show_full_khata_history = st.checkbox("📜 Purani History Bhi Dekho (dheema ho sakta hai)", key="khata_full_history")
                khata_limit = 5000 if show_full_khata_history else 300
                try:
                    c.execute("""SELECT id, date, time, type, amount, item, qty, rate, detail, unit, pehle_baaki, baad_baaki
                                 FROM udhaar WHERE customer_id =? ORDER BY date DESC, id DESC LIMIT ?""", (cust_id, khata_limit))
                    entries = c.fetchall()
                except sqlite3.Error as e:
                    st.error(f"⚠️ Khata entries load nahi ho sakin: {e}")
                    entries = []

                if len(entries) >= khata_limit and not show_full_khata_history:
                    st.caption(f"ℹ️ Sirf latest {khata_limit} entries dikhayi ja rahi hain. Purani history ke liye upar wala checkbox lagayein.")

                # MONTHLY GROUPING - is CUSTOMER (cust_id, jo bhi select ho) ke liye dynamic
                monthly_summary_df = cached_monthly_summary(cust_id)
                available_months = monthly_summary_df["ym"].tolist() if not monthly_summary_df.empty else []

                def _month_label(ym_str):
                    try:
                        return datetime.strptime(ym_str, "%Y-%m").strftime("%B %Y")
                    except Exception:
                        return ym_str

                if available_months:
                    st.markdown("**📅 Month Se Filter Karein:**")
                    filter_cols = st.columns(min(len(available_months) + 1, 6))
                    if "khata_month_filter" not in st.session_state:
                        st.session_state["khata_month_filter"] = "All"

                    with filter_cols[0]:
                        if st.button("Sab Mahine", key="month_filter_all", type="primary" if st.session_state["khata_month_filter"] == "All" else "secondary", use_container_width=True):
                            st.session_state["khata_month_filter"] = "All"
                            st.rerun()

                    for i, ym in enumerate(available_months[:5]):
                        with filter_cols[(i + 1) % 6]:
                            if st.button(_month_label(ym), key=f"month_filter_{ym}",
                                         type="primary" if st.session_state["khata_month_filter"] == ym else "secondary",
                                         use_container_width=True):
                                st.session_state["khata_month_filter"] = ym
                                st.rerun()

                active_month_filter = st.session_state.get("khata_month_filter", "All")

                # Detail entries ko month ke hisab se group karo (sirf jo already fetch ho chuki hain)
                entries_by_month = {}
                for e in entries:
                    try:
                        ym = e[1][:7]  # "YYYY-MM-DD" se "YYYY-MM"
                    except Exception:
                        ym = "Unknown"
                    entries_by_month.setdefault(ym, []).append(e)

                months_to_show = [m for m in entries_by_month.keys() if active_month_filter == "All" or m == active_month_filter]
                months_to_show = sorted(months_to_show, reverse=True)

                if not months_to_show:
                    st.info("Is filter ke liye koi entry nahi mili.")

                for ym in months_to_show:
                    month_entries = entries_by_month[ym]
                    month_label = _month_label(ym)

                    # Monthly totals HAMESHA full SQL aggregate se (khata_limit se independent) -
                    # taake purane mahino ke totals bhi sahi rahein chahe list capped ho
                    row = monthly_summary_df[monthly_summary_df["ym"] == ym]
                    if not row.empty:
                        month_udhaar = float(row.iloc[0]["udhaar_total"])
                        month_jama = float(row.iloc[0]["jama_total"])
                    else:
                        month_udhaar = sum(e[4] for e in month_entries if e[3] == 'udhaar')
                        month_jama = sum(e[4] for e in month_entries if e[3] == 'jama')
                    month_baaki = month_udhaar - month_jama

                    with st.expander(f"📅 {month_label}", expanded=(active_month_filter != "All" or ym == months_to_show[0])):
                        distinct_dates = sorted(list(set([e[1] for e in month_entries])), reverse=True)

                        for target_date in distinct_dates:
                            try:
                                date_obj = datetime.strptime(target_date, "%Y-%m-%d")
                                formatted_date_header = date_obj.strftime("📅 %Y-%m-%d (%A)")
                            except Exception:
                                formatted_date_header = f"📅 {target_date}"

                            with st.expander(formatted_date_header, expanded=True):
                                date_entries = [e for e in month_entries if e[1] == target_date]
                                for entry_id, e_date, e_time, e_type, e_amount, e_item, e_qty, e_rate, e_detail, e_unit, e_pehle_baaki, e_baad_baaki in date_entries:
                                    col_chk, col_e1, col_btn1, col_btn2 = st.columns([0.5, 7.5, 1, 1])
                                    with col_chk:
                                        st.checkbox("", key=f"chk_{entry_id}")
                                    with col_e1:
                                        # BUG FIX: pehle yahan "{e_qty:g if e_qty is not None else 0}"
                                        # likha tha - yeh invalid format-spec syntax hai aur jab bhi
                                        # koi entry bina qty ke hoti thi (jaise "Initial Balance" wala
                                        # naya-customer udhaar), poora page TypeError se crash ho jata
                                        # tha. Ab har value None-safe hai, kabhi crash nahi hoga.
                                        if e_type == 'udhaar':
                                            safe_qty = e_qty if e_qty is not None else 0
                                            safe_rate = e_rate if e_rate is not None else 0
                                            safe_item = e_item if e_item else "Udhaar"
                                            safe_unit = e_unit or 'KG'
                                            st.error(f"**{safe_item}** | {safe_qty:g} {safe_unit} x {safe_rate:g} = **Rs. {(e_amount or 0):,.0f}** ({e_time}) {f'[{e_detail}]' if e_detail else ''}")
                                        else:
                                            safe_pehle = e_pehle_baaki if e_pehle_baaki is not None else 0
                                            safe_baad = e_baad_baaki if e_baad_baaki is not None else 0
                                            st.success(f"**{e_detail or 'Cash Jama'}** | Pehle: Rs. {safe_pehle:,.0f} | Jama: **Rs. {(e_amount or 0):,.0f}** | Baaki: Rs. {safe_baad:,.0f} ({e_time})")
                                    with col_btn1:
                                        if st.button("✏️", key=f"edit_trigger_{entry_id}"):
                                            if st.session_state['editing_entry_id'] == entry_id:
                                                st.session_state['editing_entry_id'] = None
                                            else:
                                                st.session_state['editing_entry_id'] = entry_id
                                            st.rerun()
                                    with col_btn2:
                                        if st.button("🗑️", key=f"del_{entry_id}"):
                                            if safe_execute("DELETE FROM udhaar WHERE id=?", (entry_id,), "Entry delete"):
                                                conn.commit()
                                                st.cache_data.clear()
                                                st.rerun()

                                    if st.session_state['editing_entry_id'] == entry_id:
                                        with st.container():
                                            st.markdown("##### 📝 Entry Edit Karo")
                                            if e_type == 'udhaar':
                                                col_edit_it, col_edit_un, col_edit_qt, col_edit_rt = st.columns([3, 2, 2, 2])
                                                with col_edit_it:
                                                    new_item = st.text_input("Item Name", value=e_item or "", key=f"edit_it_val_{entry_id}")
                                                with col_edit_un:
                                                    units_list = ["KG", "Pao", "Ada Pao", "Ada Kilo", "Dozen", "Adad"]
                                                    u_idx = units_list.index(e_unit) if e_unit in units_list else 0
                                                    new_unit = st.selectbox("Unit", units_list, index=u_idx, key=f"edit_un_val_{entry_id}")
                                                with col_edit_qt:
                                                    new_qty = st.number_input("Qty", min_value=0.0, step=0.25, value=float(e_qty or 0), key=f"edit_qt_val_{entry_id}")
                                                with col_edit_rt:
                                                    new_rate = st.number_input("Rate", min_value=0.0, step=10.0, value=float(e_rate or 0), key=f"edit_rt_val_{entry_id}")
                                                new_detail = st.text_input("Detail", value=e_detail or "", key=f"edit_det_val_{entry_id}")

                                                if new_unit == "Pao":
                                                    actual_edit_qty = new_qty * 0.25
                                                elif new_unit == "Ada Pao":
                                                    actual_edit_qty = new_qty * 0.125
                                                elif new_unit == "Ada Kilo":
                                                    actual_edit_qty = new_qty * 0.5
                                                else:
                                                    actual_edit_qty = new_qty
                                                new_amount = actual_edit_qty * new_rate
                                            else:
                                                new_amount = st.number_input("Jama Raqam", min_value=0.0, step=100.0, value=float(e_amount or 0), key=f"edit_amt_val_{entry_id}")
                                                new_detail = st.text_input("Detail", value=e_detail or "Cash Jama", key=f"edit_det_val_{entry_id}")
                                                new_item, new_qty, new_rate, new_unit = None, None, None, None

                                            col_edit_actions = st.columns(2)
                                            with col_edit_actions[0]:
                                                if st.button("✔️ Update Entry", type="primary", key=f"update_submit_{entry_id}"):
                                                    if e_type == 'udhaar':
                                                        ok = safe_execute("""UPDATE udhaar SET item=?, qty=?, rate=?, unit=?, amount=?, detail=? WHERE id=?""",
                                                            (new_item, new_qty, new_rate, new_unit, new_amount, new_detail, entry_id), "Entry update")
                                                    else:
                                                        new_baad = (e_pehle_baaki or 0) - new_amount
                                                        ok = safe_execute("""UPDATE udhaar SET amount=?, detail=?, baad_baaki=? WHERE id=?""",
                                                            (new_amount, new_detail, new_baad, entry_id), "Entry update")
                                                    if ok:
                                                        conn.commit()
                                                        st.cache_data.clear()
                                                        st.session_state['editing_entry_id'] = None
                                                        st.success("Entry updated successfully!")
                                                        st.rerun()
                                            with col_edit_actions[1]:
                                                if st.button("❌ Cancel", key=f"update_cancel_{entry_id}"):
                                                    st.session_state['editing_entry_id'] = None
                                                    st.rerun()

                        # MONTHLY FOOTER - is mahine (ym) ke liye Udhaar/Jama/Baaki total,
                        # HAMESHA full SQL aggregate (monthly_summary_df) se - kabhi bhi
                        # sirf displayed/capped entries se calculate nahi hota
                        st.markdown("---")
                        if month_baaki <= 0:
                            st.markdown(f"""
                                <div style="background-color:#d4edda; padding:14px; border-radius:8px; border-left:6px solid #28a745; margin-top:8px;">
                                    <p style="margin:0; color:#155724;">📊 <b>{month_label} Ka Total Udhaar:</b> Rs. {month_udhaar:,.0f} | <b>Total Jama:</b> Rs. {month_jama:,.0f} | <b>Baaki:</b> Rs. {month_baaki:,.0f}</p>
                                    <h4 style="margin:6px 0 0 0; color:#155724;">✅ {month_label.upper()} - BILL CLEAR / HISAB CLEAR - Paid</h4>
                                </div>
                            """, unsafe_allow_html=True)
                        else:
                            st.markdown(f"""
                                <div style="background-color:#f8d7da; padding:14px; border-radius:8px; border-left:6px solid #dc3545; margin-top:8px;">
                                    <p style="margin:0; color:#721c24;">📊 <b>{month_label} Ka Total Udhaar:</b> Rs. {month_udhaar:,.0f} | <b>Total Jama:</b> Rs. {month_jama:,.0f}</p>
                                    <h4 style="margin:6px 0 0 0; color:#721c24;">❌ {month_label.upper()} - Baaki Reh Gaya: Rs. {month_baaki:,.0f}</h4>
                                </div>
                            """, unsafe_allow_html=True)

                st.markdown("---")
                if st.button("❌ Khata Band Karo", use_container_width=True):
                    st.session_state['selected_customer_id'] = None
                    st.rerun()
        else:
            st.info("Saare Customers dekhne aur unka khata kholne ke liye barabar waale tab **'📋 Sab Customers Ki List'** par jayein.")

    # ==================== TAB 2: SAB CUSTOMERS KI LIST ====================
    with tab_list:
        st.markdown("### 📋 Saare Customers Ka Poora Record")
        if not customers:
            st.info("Koi customer saved nahi hai.")
        else:
            only_blacklist = st.checkbox("🚫 Sirf Blacklisted (Red Dot) Customers Dekho", key="filter_blacklist_toggle")
            st.divider()
            displayed_count = 0

            for idx, (cust_id, name, phone, photo, baaki, address, manual_status, cust_type, khata_no) in enumerate(customers, 1):
                status, days_p = get_customer_status(cust_id)
                if only_blacklist and status != 'red':
                    continue
                displayed_count += 1

                col0, col1, col2, col3, col5 = st.columns([0.5, 1.2, 3.5, 2.5, 2])
                with col0:
                    st.markdown(f'<span class="dot-{status}"></span>', unsafe_allow_html=True)
                with col1:
                    st.markdown(render_html_photo(photo), unsafe_allow_html=True)
                with col2:
                    if status == 'red' and days_p >= 90:
                        st.write(f"**{name} 🚫 (Blacklisted)**")
                    else:
                        st.write(f"**{name}** - {cust_type}")
                    if phone:
                        st.caption(f"📞 {phone}")
                with col3:
                    st.error(f"Rs. {baaki:,.0f}") if baaki > 0 else st.success("Clear")
                with col5:
                    if st.button("Khata Kholain", key=f"main_list_khata_{cust_id}", use_container_width=True):
                        st.session_state['selected_customer_id'] = cust_id
                        st.toast(f"✔️ {name} Ka Khata Select Ho Gaya!")
                        st.rerun()
                st.divider()

            if only_blacklist and displayed_count == 0:
                st.success("Mubarak ho! Is waqt koi bhi customer Blacklist yaani Red Dot par nahi hai. 🎉")

    # ==================== TAB 3: JAMA KARO ====================
    with tab3:
        st.markdown("### Udhaar Jama Karo")
        if not customers:
            st.warning("Pehle Customer add karein.")
        else:
            cust_dict = {f"{idx}. {cust_row[1]} ({cust_row[7]})": cust_row[0] for idx, cust_row in enumerate(customers, 1)}

            if not cust_dict:
                st.info("Koi customer nahi mila.")
            else:
                sel_name = st.selectbox("Customer Select Chuno", list(cust_dict.keys()), key="jama_tab_select")
                sel_id = cust_dict.get(sel_name)

                if sel_id is None:
                    st.error("Pehle customer select karein.")
                else:
                    p_b = get_baaki(sel_id)
                    st.info(f"**{sel_name}** Current Balance: **Rs. {p_b:,.0f}**")
                    j_amt = st.number_input("Jama Ki Raqam Add Karein", min_value=0.0, step=100.0)
                    j_det = st.text_input("Raqam Detail", value="Cash Jama")

                    if st.button("Jama Raqam Save", type="primary", use_container_width=True):
                        if j_amt > 0:
                            ok = safe_execute("INSERT INTO udhaar (customer_id, date, type, amount, detail, time, pehle_baaki, baad_baaki) VALUES (?,?,?,?,?,?,?,?)",
                                (sel_id, datetime.now().strftime("%Y-%m-%d"), 'jama', j_amt, j_det, datetime.now().strftime("%I:%M %p"), p_b, p_b - j_amt), "Jama entry")
                            if ok:
                                conn.commit()
                                st.cache_data.clear()
                                st.success("Jama entries finalized!")
                                st.session_state['selected_customer_id'] = sel_id
                                st.rerun()
                        else:
                            st.error("Amount 0 se zyada hona chahiye!")

    # ==================== TAB 4: NAYA UDHAAR ====================
    with tab2:
        st.markdown("### Naya Udhaar Likho")
        if not customers:
            st.warning("Koi customer majood nahi hai.")
        else:
            type_filter = st.selectbox("Customer Type Filter", ["All", "Customer", "Worker", "Ghar Ka Kharcha"], key="udhaar_type_filter")
            if type_filter != "All":
                filtered_cust = [cust_row for cust_row in customers if cust_row[7] == type_filter]
            else:
                filtered_cust = customers

            cust_dict = {}
            for cust_row in filtered_cust:
                k_num = cust_row[8] if (len(cust_row) > 8 and cust_row[8] is not None) else cust_row[0]
                label = f"{k_num}. {cust_row[1]} ({cust_row[7]})"
                cust_dict[label] = cust_row[0]

            if not cust_dict:
                st.info("Is filter ke liye koi customer nahi mila. Neeche se 'Naya Customer' add karein ya filter badlein.")
            else:
                sel_name = st.selectbox("Customer Select Chuno", list(cust_dict.keys()), key="udhaar_tab")
                sel_id = cust_dict.get(sel_name)

                all_items = get_all_items()
                item_display_list = [f"{i[0]} - Rs. {i[1]:g}" for i in all_items]
                item_rates = {i[0]: i[1] for i in all_items}
                item_name_map = {f"{i[0]} - Rs. {i[1]:g}": i[0] for i in all_items}

                it_mode = st.radio("Item Selection Mode", ["List Se", "Naya Type Karein"], horizontal=True)
                if it_mode == "List Se":
                    selected_display = st.selectbox("Item", options=[""] + item_display_list)
                    item = item_name_map.get(selected_display, "")
                else:
                    item = st.text_input("Naya Item Likho")

                col_q, col_u, col_r = st.columns(3)
                with col_q:
                    qty = st.number_input("Quantity", min_value=0.0, step=1.0, key="u_qty")
                with col_u:
                    unit = st.selectbox("Unit Type", ["KG", "Pao", "Ada Pao", "Ada Kilo", "Dozen", "Adad"])
                with col_r:
                    rate = st.number_input("Rate Amount", min_value=0.0, step=10.0, value=item_rates.get(item, 0.0) if item else 0.0, key="u_rate")

                if unit == "Pao":
                    a_qty = qty * 0.25
                elif unit == "Ada Pao":
                    a_qty = qty * 0.125
                elif unit == "Ada Kilo":
                    a_qty = qty * 0.5
                else:
                    a_qty = qty

                amount = a_qty * rate
                st.info(f"**Total Bill Price: Rs. {amount:,.0f}**")
                u_det = st.text_input("Remarks / Extra Detail")

                if st.button("Udhaar Bill Save", type="primary", use_container_width=True):
                    if sel_id is None:
                        st.error("Pehle customer select karein.")
                    elif not (amount > 0 and item):
                        st.error("Item name aur amount zaroori hai!")
                    else:
                        ok = safe_execute("INSERT INTO udhaar (customer_id, date, type, amount, item, qty, rate, detail, time, unit) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (sel_id, datetime.now().strftime("%Y-%m-%d"), 'udhaar', amount, item, qty, rate, u_det, datetime.now().strftime("%I:%M %p"), unit), "Udhaar bill")

                        if ok:
                            conn.commit()
                            st.cache_data.clear()

                            if it_mode == "List Se":
                                customer_name = sel_name.split('. ', 1)[1].split(' (')[0] if '. ' in sel_name else sel_name
                                stock_updated = update_main_stock(item, a_qty, unit, customer_name)
                                if stock_updated:
                                    st.success(f"Udhaar finalized! Stock mein {a_qty:g} {unit} kam ho gaya.")
                                else:
                                    st.success("Udhaar finalized!")
                            else:
                                st.success("Udhaar finalized!")

                            st.session_state['selected_customer_id'] = sel_id
                            st.rerun()

    # ==================== TAB: UDHAAR BOOK SCAN (OCR) ====================
    with tab_scan:
        st.markdown("### 📷 Purani Udhaar Book Ka Page Scan Karein")
        st.caption("Customer ki purani kitab ka ek page ki photo khinchein - Naam, Date, Item, Raqam nikal kar Preview mein dikhaye jayenge. Aap check/edit kar ke hi save kar sakte hain.")

        scan_mode = st.radio("Photo", ["📤 Upload", "📷 Camera Se Khinchein"], horizontal=True, key="book_scan_mode")
        if scan_mode == "📷 Camera Se Khinchein":
            book_img = st.camera_input("Udhaar Book Ka Page Khinchein", key="book_scan_cam")
        else:
            book_img = st.file_uploader("Udhaar Book Ka Page Upload Karein", type=["jpg", "jpeg", "png"], key="book_scan_upload")

        if book_img is not None and st.button("🔍 Book Scan Karo (OCR)", key="book_scan_btn"):
            img_bytes = book_img.getvalue()
            with st.spinner("Book scan ho raha hai..."):
                raw_text, err = camera_ocr.extract_raw_text(img_bytes)
            if err:
                st.warning(err + " Neeche khali table mein khud likh sakte hain.")
                st.session_state["book_scan_rows"] = [{"date": "", "customer": "", "item": "", "amount": 0.0}]
            else:
                guessed = camera_ocr.guess_udhaar_entries(raw_text)
                if not guessed:
                    st.info("ℹ️ OCR ko page mein saaf entries nahi mili. Neeche khud likh sakte hain.")
                    guessed = [{"date": "", "customer": "", "item": "", "amount": 0.0}]
                st.session_state["book_scan_rows"] = guessed

        if "book_scan_rows" in st.session_state:
            st.warning("⚠️ **Preview & Confirm:** OCR (khaas kar kharab handwriting/Sindhi likhai par) 100% sahi nahi hota. Har row dhyan se check/edit karein - Customer Name theek se likhein (yeh maujooda customer se match hoga), phir 'Confirm & Save' dabayein.")

            edited_df = st.data_editor(
                pd.DataFrame(st.session_state["book_scan_rows"]),
                num_rows="dynamic", key="book_scan_editor", width='stretch',
                column_config={
                    "date": st.column_config.TextColumn("Date (YYYY-MM-DD)"),
                    "customer": st.column_config.TextColumn("Customer Name*"),
                    "item": st.column_config.TextColumn("Item"),
                    "amount": st.column_config.NumberColumn("Amount (Rs.)*", min_value=0.0),
                })

            if st.button("✅ Confirm & Save Sab Entries", type="primary", key="book_scan_confirm"):
                saved_count = 0
                skipped_count = 0
                for _, row in edited_df.iterrows():
                    cust_name = str(row.get("customer", "")).strip()
                    amount = float(row.get("amount", 0) or 0)
                    if not cust_name or amount <= 0:
                        skipped_count += 1
                        continue

                    try:
                        parsed_date = pd.to_datetime(row.get("date", ""), dayfirst=True, errors="coerce")
                        date_str = parsed_date.strftime("%Y-%m-%d") if not pd.isna(parsed_date) else datetime.now().strftime("%Y-%m-%d")
                    except Exception:
                        date_str = datetime.now().strftime("%Y-%m-%d")

                    try:
                        c.execute("SELECT id FROM customers WHERE LOWER(TRIM(name)) = LOWER(?)", (cust_name,))
                        existing = c.fetchone()
                        if existing:
                            cust_id = existing[0]
                        else:
                            c.execute("INSERT INTO customers (name, customer_type) VALUES (?, 'Customer')", (cust_name,))
                            cust_id = c.lastrowid

                        ok = safe_execute(
                            "INSERT INTO udhaar (customer_id, date, type, amount, item, detail, time) VALUES (?,?,?,?,?,?,?)",
                            (cust_id, date_str, 'udhaar', amount, str(row.get("item", "")).strip() or "Udhaar Book Scan",
                             "Udhaar Book Scan se add hua", datetime.now().strftime("%I:%M %p")),
                            "Book scan entry")
                        if ok:
                            saved_count += 1
                        else:
                            skipped_count += 1
                    except sqlite3.Error:
                        skipped_count += 1

                conn.commit()
                st.cache_data.clear()
                del st.session_state["book_scan_rows"]

                # Book photo bhi Drive par bhej dete hain (record ke liye)
                try:
                    sync_manager.upload_photo_to_drive_background(
                        img_bytes if 'img_bytes' in dir() else book_img.getvalue(),
                        f"udhaar_book_scan_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg")
                except Exception:
                    pass

                if saved_count:
                    st.success(f"✔️ {saved_count} entries save ho gayi!" + (f" ({skipped_count} skip hui - naam ya amount khali tha)" if skipped_count else ""))
                else:
                    st.error("❌ Koi bhi entry save nahi ho saki - Customer Name aur Amount zaroori hain.")
                st.rerun()

    # ==================== TAB 5: CUSTOMER SETTING ====================
    with tab4:
        st.markdown("### ⚙ Management Settings")

        st.markdown("#### 🔒 Privacy Settings")
        toggle_col1, toggle_col2 = st.columns([1, 3])
        with toggle_col1:
            old_value = st.session_state.get('show_total_baaki', False)
            new_value = st.toggle(
                "Total Baaki Dikhao",
                value=old_value,
                key="total_baaki_toggle"
            )
            if new_value != old_value:
                st.session_state['show_total_baaki'] = new_value
                st.rerun()

        with toggle_col2:
            if st.session_state.get('show_total_baaki', False):
                st.success("✅ Total Baaki sab ko nazar aa raha hai")
            else:
                st.warning("🔒 Total Baaki chupaya hua hai")

        st.divider()

        sub_t1, sub_t2, sub_t3 = st.tabs(["👥 Naya Customer Banayein", "✏ Saved Customer Edit Karein", "📦 Items Stock Rate"])

        # SUB-TAB 1: CREATE CUSTOMER
        with sub_t1:
            with st.form("new_customer_form"):
                n_name = st.text_input("New Customer Name*")
                n_phone = st.text_input("Mobile Number")
                n_addr = st.text_area("Home Address")
                n_status = st.selectbox("Dot Manual Override", ["Auto", "Green", "Orange", "Red"])
                n_type = st.selectbox("Customer Type*", ["Customer", "Worker", "Ghar Ka Kharcha"])

                booked_numbers = set()
                try:
                    temp_cursor = conn.cursor()
                    temp_cursor.execute("SELECT khata_no FROM customers")
                    booked_numbers = {int(row[0]) for row in temp_cursor.fetchall() if row[0] is not None and str(row[0]).isdigit()}
                except Exception:
                    pass

                khata_options = []
                khata_map = {}

                for num in range(1, 101):
                    if num in booked_numbers:
                        label = f"{num} ✅ (Pehle Se Saved Hai)"
                    else:
                        label = f"{num} ❌ (Khali Hai)"
                    khata_options.append(label)
                    khata_map[label] = num

                selected_khata_label = st.selectbox("Khata Number Chunein (1 se 100)*", khata_options)
                n_khata_no = khata_map.get(selected_khata_label)

                n_initial_balance = st.number_input(
                    "Initial Balance (Agar pehle se udhaar hai)",
                    min_value=0.0, step=100.0
                )

                photo_mode = st.radio("Customer Photo (Optional)", ["📤 Upload", "📷 Camera"], horizontal=True, key="new_cust_photo_mode")
                if photo_mode == "📷 Camera":
                    uploaded_photo = st.camera_input("Customer Ki Photo Khinchein")
                else:
                    uploaded_photo = st.file_uploader("Customer Photo Upload Karein (Optional)", type=["jpg", "jpeg", "png"])

                if st.form_submit_button("Save Customer"):
                    if not n_name:
                        st.error("Naam likhna zaroori hai.")
                    else:
                        try:
                            if uploaded_photo is not None:
                                # PERF FIX: customer photos BLOB mein DB ke andar save hoti
                                # hain - agar 5000+ customers full-size photo upload karein
                                # to database file khud kai GB ki ho sakti hai (slow
                                # backup/restore/queries). Ab compress ho kar ~500KB tak.
                                with st.spinner("Photo compress ho rahi hai..."):
                                    photo_bytes, compress_msg = image_compression.compress_image(uploaded_photo)
                                if compress_msg:
                                    st.caption(compress_msg)
                            else:
                                photo_bytes = None

                            if photo_bytes:
                                try:
                                    sync_manager.upload_photo_to_drive_background(
                                        photo_bytes, f"customer_{n_name.strip()}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg")
                                except Exception:
                                    pass
                        except Exception:
                            photo_bytes = None
                            st.warning("⚠️ Photo read nahi ho saki, bagair photo ke save ho raha hai.")

                        try:
                            save_cursor = conn.cursor()
                            save_cursor.execute("""
                                INSERT INTO customers (name, phone, address, manual_status, customer_type, photo, khata_no)
                                VALUES (?,?,?,?,?,?,?)
                            """, (n_name, n_phone, n_addr, n_status, n_type, photo_bytes, n_khata_no))

                            new_customer_id = save_cursor.lastrowid

                            if n_initial_balance and n_initial_balance > 0:
                                # BUG FIX: pehle is INSERT mein qty/item/rate/unit columns
                                # bilkul chhoṛe jaate the (NULL ban jaate the), jo baad mein
                                # "Poora Khata" tab khulte hi crash kar deta tha (upar dekhein).
                                # Ab explicit 'Cash Udhaar' item + qty=1 dete hain, taake yeh
                                # entry baaki normal udhaar entries jaisi hi safe rahe.
                                save_cursor.execute(
                                    "INSERT INTO udhaar (customer_id, date, type, amount, item, qty, rate, unit, detail, time) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                    (new_customer_id, datetime.now().strftime("%Y-%m-%d"), "udhaar", n_initial_balance,
                                     "Initial Balance", 1, n_initial_balance, "Cash", "Initial Balance", datetime.now().strftime("%I:%M %p"))
                                )

                            conn.commit()
                            st.cache_data.clear()
                            st.success(f"New Client saved at Khata No: {n_khata_no}!")
                            st.rerun()
                        except sqlite3.Error as e:
                            st.error(f"Save karte waqt error aaya: {e}")

        # SUB-TAB 2: EDIT EXISTING CUSTOMERS
        with sub_t2:
            st.markdown("#### Purane Customer Ki Details Sahi Karein")

            if not customers:
                st.info("Koi customer available nahi hai.")
            else:
                edit_dict = {}
                for c_row in customers:
                    try:
                        if len(c_row) > 1:
                            khata_display = c_row[8] if len(c_row) > 8 and c_row[8] is not None else "No Khata"
                            edit_dict[f"{c_row[1]} ({c_row[2] or 'No Phone'}) - Khata No: {khata_display}"] = c_row
                    except Exception:
                        if len(c_row) > 2:
                            edit_dict[f"{c_row[1]} ({c_row[2] or 'No Phone'})"] = c_row

                if not edit_dict:
                    st.info("Customers ka data load ho raha hai...")
                else:
                    selected_edit_label = st.selectbox("Kounse Customer Ki Detail Change Karni Hai?", list(edit_dict.keys()))

                    if selected_edit_label:
                        edit_row = edit_dict.get(selected_edit_label)

                        if edit_row and len(edit_row) >= 9:
                            e_id, e_name, e_phone, e_photo, _, e_addr, e_manual, e_type, e_khata = edit_row[:9]
                        elif edit_row and len(edit_row) == 8:
                            e_id, e_name, e_phone, e_photo, _, e_addr, e_manual, e_type = edit_row[:8]
                            e_khata = None
                        elif edit_row:
                            e_id, e_name, e_phone = edit_row[0], edit_row[1], edit_row[2]
                            e_photo, e_addr, e_manual, e_type, e_khata = None, "", "Auto", "Customer", None
                        else:
                            e_id = None

                        if e_id is not None:
                            with st.form(f"edit_customer_form_{e_id}"):
                                if e_photo:
                                    st.markdown("**Current Photo:**")
                                    st.markdown(render_html_photo(e_photo), unsafe_allow_html=True)

                                up_name = st.text_input("Customer Name", value=e_name)
                                up_phone = st.text_input("Mobile Number", value=e_phone or "")
                                up_addr = st.text_area("Home Address", value=e_addr or "")

                                status_list = ["Auto", "Green", "Orange", "Red"]
                                s_idx = status_list.index(e_manual) if e_manual in status_list else 0
                                up_status = st.selectbox("Dot Manual Override", status_list, index=s_idx)

                                type_list = ["Customer", "Worker", "Ghar Ka Kharcha"]
                                t_idx = type_list.index(e_type) if e_type in type_list else 0
                                up_type = st.selectbox("Customer Type*", type_list, index=t_idx)

                                khata_list = list(range(1, 101))
                                k_idx = khata_list.index(int(e_khata)) if e_khata is not None and str(e_khata).isdigit() and int(e_khata) in khata_list else 0
                                up_khata = st.selectbox("Khata Number Badlein (Optional)", khata_list, index=k_idx)

                                edit_photo_mode = st.radio("Photo Badlein (Optional)", ["📤 Upload", "📷 Camera"], horizontal=True, key=f"edit_photo_mode_{e_id}")
                                if edit_photo_mode == "📷 Camera":
                                    new_uploaded_photo = st.camera_input("Nayi Photo Khinchein", key=f"edit_photo_cam_{e_id}")
                                else:
                                    new_uploaded_photo = st.file_uploader("Nayi photo upload karein ya khali chor dein", type=["jpg", "jpeg", "png"], key=f"edit_photo_{e_id}")

                                if st.form_submit_button("Update Customer Details"):
                                    try:
                                        if new_uploaded_photo is not None:
                                            with st.spinner("Photo compress ho rahi hai..."):
                                                final_photo, compress_msg = image_compression.compress_image(new_uploaded_photo)
                                            if compress_msg:
                                                st.caption(compress_msg)
                                            if final_photo is None:
                                                final_photo = e_photo
                                        else:
                                            final_photo = e_photo

                                        if new_uploaded_photo is not None and final_photo:
                                            try:
                                                sync_manager.upload_photo_to_drive_background(
                                                    final_photo, f"customer_{up_name.strip()}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg")
                                            except Exception:
                                                pass

                                        edit_cursor = conn.cursor()
                                        edit_cursor.execute("""
                                            UPDATE customers
                                            SET name=?, phone=?, address=?, manual_status=?, customer_type=?, khata_no=?, photo=?
                                            WHERE id=?
                                        """, (up_name, up_phone, up_addr, up_status, up_type, up_khata, final_photo, e_id))
                                        conn.commit()
                                        st.cache_data.clear()
                                        st.success("Customer details + Photo updated successfully!")
                                        st.rerun()
                                    except sqlite3.Error as e:
                                        st.error(f"Update karte waqt error aaya: {e}")

        # SUB-TAB 3: ITEMS STOCK RATE
        with sub_t3:
            st.markdown("#### 📦 Items Stock & Rate Management")
            st.info("Yahan item ka rate aur stock manage karein")

    conn.close()
