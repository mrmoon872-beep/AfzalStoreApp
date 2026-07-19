import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

DB_FILE = "afzal_store.db"


def get_db():
    """Har jagah SAME tareeqe se connection kholte hain (WAL mode + timeout) taake
    'database is locked' error kabhi na aaye, chahe ek waqt mein kai pages likh rahe hon."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# Database Tables Setting
def create_chakki_tables():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS chakki_kisht
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, gandum_kg REAL, amount_paid REAL, note TEXT)''')

        c.execute('''CREATE TABLE IF NOT EXISTS chakki_pisai
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, token_no INTEGER, customer_name TEXT,
                     safai_hui TEXT, gandum_kg REAL, katchra_kg REAL, aata_kg REAL,
                     rate_per_40kg REAL, total_pisai REAL, paid REAL, status TEXT)''')

        c.execute('''CREATE TABLE IF NOT EXISTS chakki_atta_sale
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, customer_name TEXT, aata_kg REAL,
                     rate_per_kg REAL, total REAL, sale_type TEXT, paid REAL, remaining_balance REAL DEFAULT 0.0, source TEXT DEFAULT 'Chakki App')''')

        c.execute('''CREATE TABLE IF NOT EXISTS chakki_inventory
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, type TEXT, item TEXT, qty_kg REAL, price REAL, note TEXT)''')

        c.execute('''CREATE TABLE IF NOT EXISTS chakki_simple_wapari
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, wapari_name TEXT,
                      gandum_kg REAL, bill_amount REAL, paid_amount REAL, note TEXT)''')

        # Persistent configuration table for default rates
        c.execute('''CREATE TABLE IF NOT EXISTS chakki_config
                     (key TEXT PRIMARY KEY, value REAL)''')
        c.execute("INSERT OR IGNORE INTO chakki_config (key, value) VALUES ('default_aata_rate', 110.0)")

        try:
            c.execute("ALTER TABLE chakki_atta_sale ADD COLUMN remaining_balance REAL DEFAULT 0.0")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE chakki_atta_sale ADD COLUMN source TEXT DEFAULT 'Chakki App'")
        except sqlite3.OperationalError:
            pass

        # PERF FIX (lifetime speed / 10-lakh-record readiness): these indexes make the
        # stock calculation and history log below stay fast instead of full-table-scanning.
        def add_index(name, table, cols):
            try:
                c.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})")
            except sqlite3.OperationalError:
                pass

        add_index('idx_chakki_inventory_item_type', 'chakki_inventory', 'item, type')
        add_index('idx_chakki_pisai_date_status', 'chakki_pisai', 'date, status')
        add_index('idx_chakki_atta_sale_date2', 'chakki_atta_sale', 'date')
        add_index('idx_chakki_simple_wapari_name', 'chakki_simple_wapari', 'wapari_name')

        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        # App start hote hi table creation fail na ho jaaye is se poori app band ho -
        # warning dikha kar aage badhte hain, page khulte hi dobara try ho jayega.
        st.error(f"⚠️ Chaki tables set karne mein masla aaya: {e}")


create_chakki_tables()


# Helpers for persistent rate configuration
def get_config_rate():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT value FROM chakki_config WHERE key='default_aata_rate'")
        row = c.fetchone()
        val = row[0] if row else 110.0
        conn.close()
        return float(val)
    except (sqlite3.Error, TypeError, ValueError):
        return 110.0  # safe fallback - app kabhi is wajah se na ruke


def set_config_rate(new_rate):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO chakki_config (key, value) VALUES ('default_aata_rate', ?)", (new_rate,))
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as e:
        st.error(f"⚠️ Rate save nahi ho saka: {e}")
        return False


# IMPROVED: Highly Accurate Combined Stock Calculation with Grams Precision
# PERF FIX: short (5 sec) cache - is se rapid rerun par har baar 7 SUM queries nahi
# chalti, lekin stock display ek naye entry ke baad turant bhi update ho jaata hai
# (5 sec se zyada purana kabhi nahi rehta).
@st.cache_data(ttl=5, show_spinner=False)
def get_current_stock():
    try:
        conn = get_db()
        c = conn.cursor()

        c.execute("SELECT SUM(qty_kg) FROM chakki_inventory WHERE item='Gandum' AND type IN ('Buy', 'Manual Gandum Add', 'Manual Add')")
        g_plus = c.fetchone()[0] or 0.0
        c.execute("SELECT SUM(gandum_kg) FROM chakki_simple_wapari")
        g_supp = c.fetchone()[0] or 0.0
        c.execute("SELECT SUM(gandum_kg) FROM chakki_kisht")
        g_kisht = c.fetchone()[0] or 0.0

        c.execute("SELECT SUM(qty_kg) FROM chakki_inventory WHERE item='Gandum' AND type IN ('Produced Aata (Gandum Milled)', 'Auto Milled Deduction', 'Manual Minus', 'Manual Gandum Minus')")
        g_minus = c.fetchone()[0] or 0.0

        total_gandum = (g_plus + g_supp + g_kisht) - g_minus

        c.execute("SELECT SUM(qty_kg) FROM chakki_inventory WHERE item='Aata' AND type IN ('Produce', 'Manual Add')")
        a_plus = c.fetchone()[0] or 0.0

        c.execute("SELECT SUM(aata_kg) FROM chakki_atta_sale")
        a_sold = c.fetchone()[0] or 0.0
        c.execute("SELECT SUM(qty_kg) FROM chakki_inventory WHERE item='Aata' AND type IN ('Manual Minus')")
        a_minus = c.fetchone()[0] or 0.0

        total_aata = a_plus - (a_sold + a_minus)

        conn.close()
        return round(max(total_gandum, 0.0), 3), round(max(total_aata, 0.0), 3)
    except sqlite3.Error:
        return 0.0, 0.0  # DB busy/missing - app chalti rahegi, stock 0 dikhega instead of crash


def safe_execute(cursor, query, params=(), friendly_action="Record save"):
    """Har INSERT/UPDATE is se guzarta hai - disk full, DB locked, ya koi bhi DB error aaye
    to app crash hone ke bajaye saaf Urdu/Roman error dikhayega."""
    try:
        cursor.execute(query, params)
        return True
    except sqlite3.OperationalError as e:
        if "disk" in str(e).lower() or "full" in str(e).lower():
            st.error("❌ Computer ki disk space kam hai! Kuch jagah khali karein, phir dobara try karein. Data save nahi hua.")
        elif "locked" in str(e).lower():
            st.error("❌ Database is waqt busy hai (koi aur save ho raha tha). Dubara 'Save' dabayein.")
        else:
            st.error(f"❌ {friendly_action} nahi ho saka: {e}")
        return False
    except sqlite3.Error as e:
        st.error(f"❌ {friendly_action} nahi ho saka: {e}")
        return False


@st.cache_data(ttl=30, show_spinner="Records load ho rahe hain...")
def cached_history_log(record_type, limit, start_date=None, end_date=None):
    """PERF FIX: pehle yeh chaaron history logs POORI table ek dropdown-select pe load
    kar dete the - 10 lakh rows pe yeh page ko atka deta. Ab default sirf latest N rows
    (limit) fetch hoti hain, aur optional date-range filter available hai."""
    conn = get_db()
    try:
        date_where = ""
        params = []
        if start_date and end_date:
            date_where = "WHERE date BETWEEN ? AND ?"
            params = [str(start_date), str(end_date)]

        if record_type == "Pisai Record Log":
            q = f"""SELECT id, date as Tareekh, token_no as 'Token #', customer_name as Customer,
                    gandum_kg as 'Gandum KG', aata_kg as 'Aata KG', total_pisai as 'Total Bill',
                    paid as Paid, status as Status FROM chakki_pisai {date_where}
                    ORDER BY id DESC LIMIT ?"""
        elif record_type == "Aata Sale Record Log":
            q = f"""SELECT id, date as Tareekh, customer_name as Customer, aata_kg as 'Aata KG',
                    total as 'Total Bill', sale_type as 'Type', paid as Paid,
                    remaining_balance as 'Baqi Udhaar', source as 'Source'
                    FROM chakki_atta_sale {date_where} ORDER BY id DESC LIMIT ?"""
        elif record_type == "📦 Stock Production Log":
            q = f"""SELECT id, date as Tareekh, type as 'Kism', item as 'Cheez',
                    qty_kg as 'Weight (KG)', note as 'Details' FROM chakki_inventory {date_where}
                    ORDER BY id DESC LIMIT ?"""
        else:
            q = f"""SELECT id, date as Tareekh, wapari_name as 'Wapari Name', gandum_kg as 'Gandum (KG)',
                    bill_amount as 'Bill Amount', paid_amount as 'Jama Raqam', note as 'Details'
                    FROM chakki_simple_wapari {date_where} ORDER BY id DESC LIMIT ?"""

        params.append(limit)
        return pd.read_sql_query(q, conn, params=tuple(params))
    except sqlite3.Error as e:
        st.warning(f"⚠️ History log load nahi ho saka: {e}")
        return pd.DataFrame()
    finally:
        conn.close()


def show_chakki_management(get_db_param=None):
    conn = get_db_param() if get_db_param is not None else get_db()
    c = conn.cursor()

    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        current_month_str = datetime.now().strftime("%Y-%m")
        gandum_stock, aata_stock = get_current_stock()
        saved_default_rate = get_config_rate()

        st.markdown("""
            <style>
            div[data-testid="stHeader"] { background-color: rgba(0,0,0,0); }
            div.stButton > button[kind="primary"] {
                background-color: #2ecc71 !important;
                color: white !important;
                border-radius: 8px !important;
                border: 2px solid #27ae60 !important;
                font-weight: bold !important;
                box-shadow: 0px 4px 6px rgba(0,0,0,0.1) !important;
            }
            div.stButton > button[kind="secondary"] {
                background-color: #3498db !important;
                color: white !important;
                border-radius: 8px !important;
                border: 2px solid #2980b9 !important;
                font-weight: bold !important;
            }
            label[data-testid="stWidgetLabel"] {
                color: #2c3e50 !important;
                font-weight: bold !important;
            }
            </style>
        """, unsafe_allow_html=True)

        st.title("🌾 Chaki Management System")
        st.info(f"📦 **Live Stock Position:** Current Available Gandum: `{gandum_stock:,.3f} KG` | Current Available Aata Stock: `{aata_stock:,.3f} KG`")

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "🎟️ Customer Pisai Bill",
            "🛒 Apna Aata Sale",
            "🤝 Gandum Khareed & Supplier Khata",
            "📦 Stock & Machine Production",
            "📊 Aj Ka Hisab & Records"
        ])

        # ================= TAB 1: CUSTOMER PISAI BILL =================
        with tab1:
            st.markdown("<h3 style='color: #2980b9;'>🎟️ Customer Gandum Pisai Entry</h3>", unsafe_allow_html=True)
            try:
                c.execute("SELECT token_no FROM chakki_pisai WHERE date=? AND status='Pending'", (today_str,))
                used_tokens = [r[0] for r in c.fetchall()]
            except sqlite3.Error as e:
                st.warning(f"⚠️ Token list load nahi ho saki: {e}")
                used_tokens = []
            free_tokens = [i for i in range(1, 31) if i not in used_tokens]

            if not free_tokens:
                st.error("⚠️ Aj ke saare Tokens full hain!")
            else:
                col1, col2, col3 = st.columns(3)
                with col1: token_no = st.selectbox("🎯 Token Number Chunein", free_tokens, key="pisai_tok")
                with col2: customer_name = st.text_input("✍️ Customer Ka Naam*", key="pisai_cust")
                with col3: safai_hui = st.selectbox("✨ Safai Hui?", ["Haan", "Nahi"], key="pisai_safai")

                col4, col5 = st.columns(2)
                with col4: gandum_kg = st.number_input("⚖️ Gandum Weight KG", min_value=0.0, step=0.001, format="%.3f", key="pisai_kg")
                with col5: katchra_kg = st.number_input("🗑️ Katchra KG", min_value=0.0, step=0.001, value=0.0, format="%.3f", key="pisai_kat")

                aata_kg_p = max(gandum_kg - katchra_kg, 0.0)
                rate = 250.0 if safai_hui == "Haan" else 300.0
                total_pisai = (aata_kg_p / 40.0) * rate

                st.warning(f"**📊 Hisab-Kitab:** Saaf Aata: **{aata_kg_p:.3f} KG** | Kul Pisai Bill: **Rs. {total_pisai:.2f}**")
                paid_p = st.number_input("💵 Vasool Shuda Raqam", min_value=0.0, max_value=float(total_pisai) if total_pisai > 0 else 0.0, step=10.0, value=float(total_pisai), key="pisai_paid")
                status = "Paid" if paid_p >= total_pisai else "Pending"

                if st.button("🟢 ✅ Pisai Bill Save Karo", type="primary", use_container_width=True):
                    if customer_name.strip() and gandum_kg > 0:
                        ok = safe_execute(c, """INSERT INTO chakki_pisai (date, token_no, customer_name, safai_hui, gandum_kg, katchra_kg, aata_kg, rate_per_40kg, total_pisai, paid, status)
                                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                      (today_str, token_no, customer_name.strip(), safai_hui, gandum_kg, katchra_kg, aata_kg_p, rate, total_pisai, paid_p, status),
                                      "Pisai bill")
                        if ok:
                            conn.commit()
                            st.cache_data.clear()
                            st.success("✔️ Customer Pisai Record Kamiyabi Se Save!")
                            st.rerun()
                    else:
                        st.error("❌ Galti: Customer ka naam likhein aur Gandum Weight 0 se zyada hona chahiye!")

        # ================= TAB 2: APNA AATA SALE =================
        with tab2:
            st.markdown("<h3 style='color: #27ae60;'>🛒 Apna Aata Bechna (Cash ya Udhaar)</h3>", unsafe_allow_html=True)

            with st.expander("➕ / ➖ Need to Add or Minus Stock? (Aata / Gandum Kam ya Zyada Karen)"):
                action_type = st.radio("🎯 Kya Karna Hai?", ["Stock Plus (Izafa Karen)", "Stock Minus (Galti Se Zyada Likha Gaya Tha)"], horizontal=True, key="stock_action_type")

                col_add1, col_add1_g, col_add2 = st.columns(3)
                with col_add1:
                    stock_aata_qty = st.number_input("Aata Ki Miqdar (KG)", min_value=0.0, step=0.001, format="%.3f", key="manual_aata_stock_qty")
                with col_add1_g:
                    stock_gandum_qty = st.number_input("Gandum Ki Miqdar (KG)", min_value=0.0, step=0.001, format="%.3f", key="manual_gandum_stock_qty")
                with col_add2:
                    stock_note = st.text_input("Tafseel / Note", value="Manual Adjustment", key="manual_stock_note")

                if st.button("🎯 Stock Update Karen", type="secondary"):
                    if stock_aata_qty > 0 or stock_gandum_qty > 0:
                        all_ok = True
                        if "Plus" in action_type:
                            if stock_aata_qty > 0:
                                all_ok &= safe_execute(c, "INSERT INTO chakki_inventory (date, type, item, qty_kg, price, note) VALUES (?, 'Manual Add', 'Aata', ?, 0, ?)", (today_str, stock_aata_qty, stock_note), "Stock update")
                                auto_gandum_note = f"Automatic Cut (Aata Production: {stock_aata_qty:,.3f} KG)"
                                if stock_note and stock_note != "Manual Adjustment":
                                    auto_gandum_note += f" - {stock_note}"
                                all_ok &= safe_execute(c, "INSERT INTO chakki_inventory (date, type, item, qty_kg, price, note) VALUES (?, 'Manual Minus', 'Gandum', ?, 0, ?)", (today_str, stock_aata_qty, auto_gandum_note), "Stock update")
                            if stock_gandum_qty > 0:
                                all_ok &= safe_execute(c, "INSERT INTO chakki_inventory (date, type, item, qty_kg, price, note) VALUES (?, 'Manual Gandum Add', 'Gandum', ?, 0, ?)", (today_str, stock_gandum_qty, stock_note), "Stock update")
                        else:
                            if stock_aata_qty > 0:
                                all_ok &= safe_execute(c, "INSERT INTO chakki_inventory (date, type, item, qty_kg, price, note) VALUES (?, 'Manual Minus', 'Aata', ?, 0, ?)", (today_str, stock_aata_qty, stock_note), "Stock update")
                            if stock_gandum_qty > 0:
                                all_ok &= safe_execute(c, "INSERT INTO chakki_inventory (date, type, item, qty_kg, price, note) VALUES (?, 'Manual Minus', 'Gandum', ?, 0, ?)", (today_str, stock_gandum_qty, stock_note), "Stock update")

                        if all_ok:
                            conn.commit()
                            st.cache_data.clear()
                            st.success("🎉 Stock kamiyabi se adjust ho gaya!")
                            st.rerun()

            st.divider()

            try:
                c.execute("SELECT id, name FROM customers ORDER BY name ASC")
                customer_list = [f"{r[1]} (ID: {r[0]})" for r in c.fetchall()]
            except sqlite3.Error:
                customer_list = []

            sale_type = st.radio("🔘 Bechne Ka Tareeqa Chunein", ["Cash Sale", "Udhar Par Diya"], horizontal=True, key="sale_t_rad")

            def cm_update_kg_from_rs():
                current_rate = st.session_state.sale_rate if "sale_rate" in st.session_state else saved_default_rate
                if current_rate > 0 and st.session_state.cm_aata_rs_helper > 0:
                    st.session_state.sale_aata_kg = round(st.session_state.cm_aata_rs_helper / current_rate, 3)

            col_rs, col1, col2, col3, col_cost, col_btn = st.columns([2.5, 3, 2.5, 2.5, 2.5, 1.5])

            with col_rs:
                if "cm_aata_rs_helper" not in st.session_state:
                    st.session_state.cm_aata_rs_helper = 0.0
                st.number_input("💵 Kitne Rupay Ka?", min_value=0.0, step=10.0, key="cm_aata_rs_helper", on_change=cm_update_kg_from_rs)

            with col1:
                if sale_type == "Udhar Par Diya" and customer_list:
                    selected_cust = st.selectbox("👤 Udhaar Khatta Dar Chuno*", customer_list, key="sale_ud_cust")
                    customer_name = selected_cust.split(" (ID:")[0]
                    try:
                        cust_id = int(selected_cust.split("ID: ")[1].replace(")", ""))
                    except (IndexError, ValueError):
                        cust_id = None
                else:
                    customer_name = st.text_input("👤 Customer Naam Likhein*", key="sale_cash_cust")
                    cust_id = None

            with col2:
                if "sale_aata_kg" not in st.session_state:
                    st.session_state.sale_aata_kg = 0.000
                aata_kg = st.number_input("⚖ Aata Becha (KG)", min_value=0.0, step=0.001, format="%.3f", key="sale_aata_kg")

            with col3:
                rate_per_kg = st.number_input("💰 Rate per KG", value=saved_default_rate, step=0.1, key="sale_rate")

            with col_cost:
                cost_price_per_kg = st.number_input("📉 Asal Khareed Rate", value=105.0, step=0.1, key="sale_cost_rate")

            with col_btn:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("📌 Save Rate", use_container_width=True, key="cm_save_rate_btn"):
                    if set_config_rate(rate_per_kg):
                        st.success("Saved!")

            r_discount = st.number_input("🎁 Riyaat / Discount (Rs.)", min_value=0.0, step=5.0, value=0.0, key="cm_aata_discount")

            gross_total = round(aata_kg * rate_per_kg, 2)
            total = max(0.0, round(gross_total - r_discount, 2))

            paid = st.number_input("💵 Kitne Paise Mile", min_value=0.0, value=float(total) if "Cash" in sale_type else 0.0, step=0.5, key="sale_paid")
            remaining = total - paid

            estimated_profit = round(aata_kg * (rate_per_kg - cost_price_per_kg), 2)
            final_bachat = max(0.0, round(estimated_profit - r_discount, 2))

            st.info(f"💡 **Current Available Aata Stock:** `{aata_stock:,.3f} KG` | **Current Available Gandum:** `{gandum_stock:,.3f} KG`")

            if r_discount > 0:
                st.warning(f"📊 **Gross Bill:** Rs. {gross_total:,.2f} | **Net Bill:** Rs. {total:,.2f} | 📉 **Dukan Ki Bachat:** Rs. {final_bachat:,.2f}")
            else:
                st.write(f"📊 **Total Bill:** Rs. {total:,.2f} | **Is Entry Se Bachat:** Rs. {final_bachat:,.2f}")

            if aata_kg > aata_stock:
                st.warning(f"⚠ Stock Alert: Dukandari mein sirf {aata_stock:g} KG aata para hai. Phir bhi record save kia ja sakta hai.")

            if st.button("🟢 ✅ Aata Sale Record Entry Save", type="primary", use_container_width=True):
                if customer_name.strip() and aata_kg > 0:
                    detail_note = "Chakki App Sale"
                    if r_discount > 0:
                        detail_note += f" (-Rs. {r_discount:g} Riyaat)"

                    ok1 = safe_execute(c, """
                        INSERT INTO chakki_atta_sale (date, customer_name, aata_kg, rate_per_kg, total, sale_type, paid, remaining_balance, source)
                        VALUES (?,?,?,?,?,?,?,?,?)
                    """, (today_str, customer_name.strip(), aata_kg, rate_per_kg, total, sale_type, paid, remaining, detail_note), "Aata sale")

                    ok2 = safe_execute(c, """
                        INSERT INTO roll_nama (date, customer, item, qty, amount, paid, status, bachat)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (today_str, customer_name.strip(), "Aata (Chakki App)", aata_kg, total, paid, sale_type, final_bachat), "Roll Nama entry")

                    ok3 = True
                    if "Udhar" in sale_type and cust_id is not None and remaining > 0:
                        detail_text = f"Chakki Se Aata Liya ({aata_kg:g} KG)"
                        if r_discount > 0:
                            detail_text += f" [Rs.{r_discount:g} Riyaat Di]"
                        ok3 = safe_execute(c, "INSERT INTO udhaar (customer_id, date, type, amount, item, detail, time) VALUES (?,?,?,?,?,?,?)",
                                  (cust_id, today_str, 'udhaar', remaining, 'Chakki Aata', detail_text, datetime.now().strftime("%I:%M %p")),
                                  "Udhaar khatta update")

                    if ok1 and ok2 and ok3:
                        conn.commit()
                        st.cache_data.clear()
                        st.success("✔ Aata sale record save ho gaya aur stock auto-cut!")
                        st.rerun()
                    else:
                        conn.rollback()
                        st.error("❌ Kuch data save nahi ho saka - kuch bhi save nahi hua (safety ke liye). Dobara try karein.")
                else:
                    st.error("❌ Galti: Naam aur Aata KG likhna lazmi hai!")

            st.markdown("### 📋 Aaj Ki Mukammal Aata Sale Detail")
            try:
                df_today_sales = pd.read_sql_query("""
                    SELECT date as 'Tareekh', customer_name as 'Customer Name', aata_kg as 'Aata (KG)',
                           rate_per_kg as 'Rate per KG', total as 'Total Bill (Rs.)',
                           sale_type as 'Type', remaining_balance as 'Udhaar (Rs.)', source as 'Kis Option Se Liya'
                    FROM chakki_atta_sale
                    WHERE date = ?
                    ORDER BY id DESC
                """, conn, params=(today_str,))
            except sqlite3.Error as e:
                st.warning(f"⚠️ Aaj ki sale list load nahi ho saki: {e}")
                df_today_sales = pd.DataFrame()

            if not df_today_sales.empty:
                st.dataframe(df_today_sales, use_container_width=True, hide_index=True)
                total_aaj_sale = df_today_sales['Total Bill (Rs.)'].sum()
                total_aaj_udhaar = df_today_sales['Udhaar (Rs.)'].sum()

                col_sum1, col_sum2 = st.columns(2)
                with col_sum1:
                    st.metric(label="💰 Aaj Ki Total Aata Sale (Cash + Udhaar)", value=f"Rs. {total_aaj_sale:,.2f}")
                with col_sum2:
                    st.metric(label="📈 Aaj Ka Total Aata Udhaar", value=f"Rs. {total_aaj_udhaar:,.2f}")
            else:
                st.caption("Filhal aaj koi aata sale record nahi hua.")

            st.markdown("---")
            st.markdown("<h4 style='color: #2980b9;'>📅 Is Mahine Ka Mukammal Hisab-Kitab</h4>", unsafe_allow_html=True)

            current_month_str = today_str[:7]

            try:
                c.execute("""
                    SELECT SUM(bachat) FROM roll_nama
                    WHERE date LIKE ? AND (item LIKE '%Aata%' OR item LIKE '%Chakki%')
                """, (f"{current_month_str}%",))
                monthly_profit_row = c.fetchone()
                monthly_profit = float(monthly_profit_row[0]) if monthly_profit_row and monthly_profit_row[0] is not None else 0.0

                c.execute("SELECT SUM(total) FROM chakki_atta_sale WHERE date LIKE ?", (f"{current_month_str}%",))
                monthly_sale_row = c.fetchone()
                monthly_sale = float(monthly_sale_row[0]) if monthly_sale_row and monthly_sale_row[0] is not None else 0.0

                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    st.info(f"💵 **Is Mahine Ki Total Aata Sale:** `Rs. {monthly_sale:,.2f}`")
                with col_m2:
                    st.success(f"🎉 **Is Mahine Aata Se Shudh Kamai (Net Profit):** `Rs. {monthly_profit:,.2f}`")

                st.caption("💡 *Note: Ye profit aapke input kiye gaye 'Asal Khareed Rate' ke hisab se auto-calculated hai.*")
            except (sqlite3.Error, TypeError, ValueError):
                st.caption("Monthly record calculate karne mein koi choti dikkat aayi hai.")

        # ================= TAB 3: GANDUM KHAREED & SUPPLIER KHATA =================
        with tab3:
            sub_tab1, sub_tab2 = st.tabs(["🤝 Wapari Ka Simple Khata", "💵 Direct Naqad Khareedi"])

            with sub_tab1:
                st.markdown("<h3 style='color: #d35400;'>🤝 Wapari / Aarhti Ka Simple Ledger</h3>", unsafe_allow_html=True)
                try:
                    c.execute("SELECT DISTINCT LOWER(TRIM(wapari_name)) FROM chakki_simple_wapari WHERE wapari_name IS NOT NULL AND wapari_name != ''")
                    existing_waparis = [r[0].title() for r in c.fetchall()]
                except sqlite3.Error:
                    existing_waparis = []

                col_w1, col_w2 = st.columns(2)
                with col_w1:
                    w_choice = st.radio("🔘 Wapari Dhundhein Ya Naya Banayein", ["Purana Wapari Select Karen", "Naya Wapari Likhen"], horizontal=True, key="sim_w_choice")
                with col_w2:
                    if w_choice == "Purana Wapari Select Karen" and existing_waparis:
                        w_name = st.selectbox("👤 Wapari Ka Naam Select Karen*", existing_waparis, key="sim_w_old")
                    else:
                        w_name = st.text_input("✍️ Naye Wapari Ka Naam Likhein*", key="sim_w_new")

                if w_name and w_name.strip():
                    w_name = w_name.strip().title()
                    try:
                        c.execute("SELECT SUM(bill_amount), SUM(paid_amount) FROM chakki_simple_wapari WHERE LOWER(wapari_name)=LOWER(?)", (w_name,))
                        w_totals = c.fetchone()
                        w_total_bill = w_totals[0] or 0.0
                        w_total_paid = w_totals[1] or 0.0
                    except sqlite3.Error:
                        w_total_bill = w_total_paid = 0.0
                    w_balance = w_total_bill - w_total_paid

                    st.markdown(f"""
                        <div style='background-color:#fce4d6; padding:15px; border-radius:8px; border-left:6px solid #e67e22;'>
                            <p style='margin:0; font-weight:bold; color:#d35400;'>🔴 {w_name} Ka Kul Baqi Udhaar:</p>
                            <h2 style='margin:0; color:#c0392b;'>Rs. {w_balance:,.2f}</h2>
                        </div>
                    """, unsafe_allow_html=True)
                    st.divider()

                    col_d1, col_d2 = st.columns(2)
                    with col_d1:
                        entry_date = st.date_input("📅 Tareekh Select Karen*", value=datetime.now(), key="sim_date")
                        entry_date_str = entry_date.strftime("%Y-%m-%d")
                    with col_d2:
                        s_note = st.text_input("🗒️ Tafseel / Note", key="sim_note")

                    col_e1, col_e2, col_e3 = st.columns(3)
                    with col_e1: s_gandum = st.number_input("⚖️ Kitni Gandum Khareedi (KG)", min_value=0.0, step=0.001, format="%.3f", key="sim_g_kg")
                    with col_e2: s_bill = st.number_input("➕ Bill Amount (Rs.)", min_value=0.0, step=500.0, key="sim_bill_rs")
                    with col_e3: s_paid = st.number_input("➖ Kaise/Paise Diye (Rs.)", min_value=0.0, step=500.0, key="sim_paid_rs")

                    if st.button("🟢 💾 Record Save Karo", type="primary", use_container_width=True, key="sim_save_btn"):
                        if s_gandum > 0 or s_bill > 0 or s_paid > 0:
                            ok = safe_execute(c, """INSERT INTO chakki_simple_wapari (date, wapari_name, gandum_kg, bill_amount, paid_amount, note)
                                         VALUES (?, ?, ?, ?, ?, ?)""", (entry_date_str, w_name, s_gandum, s_bill, s_paid, s_note), "Wapari record")
                            if ok:
                                conn.commit()
                                st.cache_data.clear()
                                st.success(f"✔️ {w_name} ka record mahfooz ho gaya!")
                                st.rerun()

                    st.divider()
                    try:
                        df_w = pd.read_sql_query("SELECT id, date as Tareekh, gandum_kg as 'Gandum (KG)', bill_amount as 'Bill Rs.', paid_amount as 'Jama Raqam', note as 'Note' FROM chakki_simple_wapari WHERE LOWER(wapari_name)=LOWER(?) ORDER BY id DESC LIMIT 200", conn, params=(w_name,))
                        if not df_w.empty:
                            st.dataframe(df_w, use_container_width=True, hide_index=True)
                    except sqlite3.Error as e:
                        st.warning(f"⚠️ Wapari ledger load nahi ho saka: {e}")

            with sub_tab2:
                st.markdown("<h3 style='color: #16a085;'>💵 Direct Cash Se Gandum Khareedna</h3>", unsafe_allow_html=True)
                col_c1, col_c2, col_c3 = st.columns(3)
                with col_c1: cash_g_kg = st.number_input("⚖️ Kitni Gandum Li (KG)", min_value=0.0, step=0.001, format="%.3f", key="sim_cash_g")
                with col_c2: cash_g_bill = st.number_input("💵 Kitne Paise Diye (Total Rs.)", min_value=0.0, step=500.0, key="sim_cash_bill")
                with col_c3: cash_note = st.text_input("🗒️ Note / Tafseel", value="Naqad Khareedi", key="sim_cash_note")

                if st.button("🟢 📥 Naqad Gandum Stock Mein Jama Karo", type="primary", use_container_width=True, key="sim_cash_btn"):
                    if cash_g_kg > 0:
                        ok = safe_execute(c, "INSERT INTO chakki_inventory (date, type, item, qty_kg, price, note) VALUES (?, 'Buy', 'Gandum', ?, ?, ?)", (today_str, cash_g_kg, cash_g_bill, cash_note), "Naqad khareedi")
                        if ok:
                            conn.commit()
                            st.cache_data.clear()
                            st.success(f"✔️ `{cash_g_kg:g} KG` Gandum stock mein dalti gayi!")
                            st.rerun()

        # ================= TAB 4: STOCK & MACHINE PRODUCTION =================
        with tab4:
            st.markdown("<h3 style='color: #7f8c8d;'>⚙️ Machine Production (Gandum se Aata Banana)</h3>", unsafe_allow_html=True)
            st.markdown("⚠️ *Yahan aata likhne par database se utni hi gandum khud-ba-khud kam ho jayegi.*")
            st.divider()

            aata_qty = st.number_input("⚡ Machine Se Kitna Aata Nikala (KG)*", min_value=0.0, step=0.001, format="%.3f", key="prod_a_qty")

            if aata_qty > gandum_stock:
                st.error(f"⚠️ Warning: Stock mein gandum kam hai! Aapke paas sirf {gandum_stock:g} KG gandum pari hai.")

            if st.button("🟢 ⚙️ Production Record Save Karo", type="primary", use_container_width=True):
                if aata_qty > 0:
                    ok1 = safe_execute(c, "INSERT INTO chakki_inventory (date, type, item, qty_kg, price, note) VALUES (?, 'Produce', 'Aata', ?, 0, 'Machine')", (today_str, aata_qty), "Production entry")
                    ok2 = safe_execute(c, "INSERT INTO chakki_inventory (date, type, item, qty_kg, price, note) VALUES (?, 'Produced Aata (Gandum Milled)', 'Gandum', ?, 0, 'Milling Loss Auto')", (today_str, aata_qty), "Production entry")
                    if ok1 and ok2:
                        conn.commit()
                        st.cache_data.clear()
                        st.success(f"✔️ `{aata_qty:g} KG` Aata barh gaya aur utni hi Gandum auto-minus ho gayi.")
                        st.rerun()
                    else:
                        conn.rollback()

        # ================= TAB 5: AJ KA HISAB & RECORDS =================
        with tab5:
            st.markdown("<h3 style='color: #2c3e50;'>📊 Sales Kamai Aur Monthly Records</h3>", unsafe_allow_html=True)

            try:
                c.execute("SELECT SUM(paid) FROM chakki_pisai WHERE date=?", (today_str,))
                t_pisai = c.fetchone()[0] or 0.0
                c.execute("SELECT SUM(total) FROM chakki_atta_sale WHERE date=? AND sale_type='Cash Sale'", (today_str,))
                t_acash = c.fetchone()[0] or 0.0
                c.execute("SELECT SUM(total) FROM chakki_atta_sale WHERE date=? AND sale_type='Udhar Par Diya'", (today_str,))
                t_audhar = c.fetchone()[0] or 0.0
                c.execute("SELECT SUM(aata_kg) FROM chakki_atta_sale WHERE date=?", (today_str,))
                t_akg = c.fetchone()[0] or 0.0
            except sqlite3.Error as e:
                st.warning(f"⚠️ Aaj ka hisab load nahi ho saka: {e}")
                t_pisai = t_acash = t_audhar = t_akg = 0.0

            total_cash_sales_today = t_pisai + t_acash
            total_udhar_sales_today = t_audhar
            grand_total_combined = total_cash_sales_today + total_udhar_sales_today

            col_m1, col_m2 = st.columns(2)
            with col_m1: st.metric("💰 Grand Total Sales Done", f"Rs. {grand_total_combined:,.2f}")
            with col_m2: st.metric("🌾 Aaj Kitna Aata Sale Hua", f"{t_akg:,.3f} KG")

            st.markdown("### 🧾 Automatically Divided Accounting")
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.markdown(f"""
                    <div style='background-color:#d4edda; padding:15px; border-radius:8px; border-left:6px solid #28a745;'>
                        <p style='margin:0; font-weight:bold; color:#155724;'>🟢 Aaj Ki Total Cash Sale (Aata + Pisai)</p>
                        <h3 style='margin:0; color:#28a745;'>Rs. {total_cash_sales_today:,.2f}</h3>
                    </div>
                """, unsafe_allow_html=True)
            with col_s2:
                st.markdown(f"""
                    <div style='background-color:#fff3cd; padding:15px; border-radius:8px; border-left:6px solid #ffc107;'>
                        <p style='margin:0; font-weight:bold; color:#856404;'>🟡 Aaj Ki Total Udhaar Sale</p>
                        <h3 style='margin:0; color:#d39e00;'>Rs. {total_udhar_sales_today:,.2f}</h3>
                    </div>
                """, unsafe_allow_html=True)

            st.divider()
            st.markdown("### 📆 Is Mahine Ki Kul Aata Sale (Monthly Total)")

            try:
                c.execute("SELECT SUM(aata_kg), SUM(total) FROM chakki_atta_sale WHERE strftime('%Y-%m', date) = ?", (current_month_str,))
                m_totals = c.fetchone()
                m_aata_total_kg = m_totals[0] or 0.0
                m_aata_total_cash = m_totals[1] or 0.0
            except sqlite3.Error:
                m_aata_total_kg = m_aata_total_cash = 0.0

            col_mon1, col_mon2 = st.columns(2)
            with col_mon1: st.metric("📊 Pure Month Mein Aata Sale (KG)", f"{m_aata_total_kg:,.3f} KG")
            with col_mon2: st.metric("💸 Pure Month Ki Aata Kamai (Rs.)", f"Rs. {m_aata_total_cash:,.2f}")

            st.divider()

            # PERF FIX: pehle yeh sab records EK SAATH poori table load kar deta tha.
            # Ab: default sirf latest 200 rows + optional date-range filter, aur ek
            # "Purani History Dhundo" checkbox jo bade dataset ke liye limit khud-ba-khud
            # 2000 tak bada deta hai (poori table kabhi bhi ek saath nahi khulti).
            col_h1, col_h2, col_h3 = st.columns([2, 1, 1])
            with col_h1:
                record_type = st.selectbox("📂 Kon Sa Record History Dekhni Hai?", ["Pisai Record Log", "Aata Sale Record Log", "🤝 Wapari Mukammal Ledger History", "📦 Stock Production Log"], key="history_log_sel")
            with col_h2:
                deep_search = st.checkbox("🔍 Purani History Dhundo", key="history_deep_search")
            with col_h3:
                date_filtered = st.checkbox("📅 Date Range", key="history_date_filter")

            hist_start = hist_end = None
            if date_filtered:
                dc1, dc2 = st.columns(2)
                hist_start = dc1.date_input("Start", key="hist_start")
                hist_end = dc2.date_input("End", key="hist_end")
                if hist_start > hist_end:
                    st.error("⚠️ Start date, End date se pehle honi chahiye.")
                    hist_start = hist_end = None

            record_limit = 2000 if deep_search else 200
            df = cached_history_log(record_type, record_limit, hist_start, hist_end)

            if len(df) >= record_limit:
                st.caption(f"ℹ️ Sirf latest {record_limit} records dikhaye ja rahe hain (speed ke liye). Purani history ke liye 'Purani History Dhundo' check karein ya Date Range filter lagayein.")

            st.dataframe(df, use_container_width=True, hide_index=True)
    finally:
        conn.close()
