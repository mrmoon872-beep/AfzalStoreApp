import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta

DB_FILE = 'afzal_store.db'


def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10)
    return conn


def safe_read_sql(query, conn, params=None, friendly_name="report"):
    """Har SQL query is se guzarti hai - agar table/column missing ho ya DB locked ho,
    poora page crash hone ke bajaye khali table dikha kar aage chalta rahega."""
    try:
        return pd.read_sql_query(query, conn, params=params)
    except Exception as e:
        st.warning(f"⚠️ {friendly_name} abhi load nahi ho saka ({e}). Baaki report chalti rahegi.")
        return pd.DataFrame()


# ==================== 🔥 CACHED DATA FETCHERS (LIFETIME FAST SPEED) 🔥 ====================
# PERF FIX: pehle har report tab pe har button-click / rerun pe seedha pd.read_sql chal
# jaata tha - 10 lakh records pe yeh har dabaane pe kaafi seconds lagata. Ab @st.cache_data
# se same date-range ka result 60 second tak yaad rehta hai, dobara DB hit nahi hoti.
# NOTE: conn object cache mein pass nahi karte (wo hashable nahi hota) - is liye yeh
# functions apna connection khud kholte hain, sirf tareekhein (strings) parameter lete hain.

@st.cache_data(ttl=60, show_spinner="Hisaab load ho raha hai...")
def cached_mahine_ka_hisaab(start_date, end_date):
    conn = get_db()
    try:
        cash_df = safe_read_sql(
            "SELECT SUM(total) as total_cash FROM sales WHERE DATE(date) BETWEEN ? AND ? AND sale_type='cash'",
            conn, (str(start_date), str(end_date)), "Cash Sale")
        cash_total = cash_df['total_cash'][0] if not cash_df.empty and cash_df['total_cash'][0] else 0

        udhaar_stock_df = safe_read_sql("""
            SELECT SUM(sh.qty * i.sale_price) as total_udhaar_stock
            FROM stock_history sh JOIN items i ON sh.item_name = i.name
            WHERE sh.type = 'sale' AND DATE(sh.date) BETWEEN ? AND ?
        """, conn, (str(start_date), str(end_date)), "Udhaar Stock Sale")
        udhaar_stock_total = udhaar_stock_df['total_udhaar_stock'][0] if not udhaar_stock_df.empty and udhaar_stock_df['total_udhaar_stock'][0] else 0

        jama_df = safe_read_sql(
            "SELECT SUM(amount) as total_jama FROM udhaar WHERE DATE(date) BETWEEN ? AND ? AND type='jama'",
            conn, (str(start_date), str(end_date)), "Recovery")
        jama_total = jama_df['total_jama'][0] if not jama_df.empty and jama_df['total_jama'][0] else 0

        daily_sale_df = safe_read_sql("""
            SELECT date, SUM(total) as sale FROM (
                SELECT DATE(date) as date, total FROM sales
                WHERE DATE(date) BETWEEN ? AND ? AND LOWER(TRIM(sale_type)) = 'cash'
                UNION ALL
                SELECT DATE(sh.date) as date, (sh.qty * i.sale_price) as total
                FROM stock_history sh JOIN items i ON sh.item_name = i.name
                WHERE sh.type = 'sale' AND DATE(sh.date) BETWEEN ? AND ?
            ) as combined GROUP BY date ORDER BY date
        """, conn, (str(start_date), str(end_date), str(start_date), str(end_date)), "Daily Sale Chart")

        bills_df = safe_read_sql(
            "SELECT bill_no, date, total, sale_type FROM sales WHERE DATE(date) = ?",
            conn, (str(datetime.now().date()),), "Today's Bills")

        return cash_total, udhaar_stock_total, jama_total, daily_sale_df, bills_df
    finally:
        conn.close()


@st.cache_data(ttl=60, show_spinner="Item-wise sale nikal rahe hain...")
def cached_item_wise_sale(start_date, end_date):
    conn = get_db()
    try:
        return safe_read_sql("""
            SELECT Item, Category, SUM(Total_Qty) as Total_Qty,
                   SUM(Total_Sale) as Total_Sale, SUM(Times_Sold) as Times_Sold,
                   ROUND(SUM(Total_Sale) / NULLIF(SUM(Total_Qty), 0), 2) as Avg_Rate
            FROM (
                SELECT i.name as Item, i.category as Category,
                       s.qty as Total_Qty, s.total as Total_Sale, 1 as Times_Sold
                FROM sales s JOIN items i ON s.item_id = i.id
                WHERE DATE(s.date) BETWEEN ? AND ?
                UNION ALL
                SELECT i.name as Item, i.category as Category,
                       sh.qty as Total_Qty, (sh.qty * i.sale_price) as Total_Sale, 1 as Times_Sold
                FROM stock_history sh JOIN items i ON sh.item_name = i.name
                WHERE sh.type = 'sale' AND DATE(sh.date) BETWEEN ? AND ?
            ) as combined_sales GROUP BY Item, Category ORDER BY Total_Sale DESC
        """, conn, (str(start_date), str(end_date), str(start_date), str(end_date)), "Item-Wise Sale")
    finally:
        conn.close()


@st.cache_data(ttl=60, show_spinner="Udhaar list nikal rahe hain...")
def cached_customer_udhaar():
    conn = get_db()
    try:
        return safe_read_sql("""
            SELECT c.name as Customer, c.phone as Phone,
                   IFNULL(SUM(CASE WHEN u.type='udhaar' THEN u.amount ELSE -u.amount END), 0) as Baaki,
                   MAX(CASE WHEN u.type='jama' THEN u.date ELSE NULL END) as Last_Payment
            FROM customers c LEFT JOIN udhaar u ON c.id = u.customer_id
            GROUP BY c.id, c.name, c.phone HAVING Baaki > 0.01 ORDER BY Baaki DESC
        """, conn, None, "Customer-Wise Udhaar")
    finally:
        conn.close()


@st.cache_data(ttl=60, show_spinner="Bill list nikal rahe hain...")
def cached_bill_summary(start_date, end_date):
    conn = get_db()
    try:
        return safe_read_sql("""
            SELECT COUNT(DISTINCT id) as total_bills, COALESCE(SUM(final_total), 0) as total_sale,
                   COALESCE(SUM(paid_amount), 0) as total_paid, COALESCE(SUM(balance), 0) as total_udhaar
            FROM sales_bills WHERE date BETWEEN ? AND ?
        """, conn, (str(start_date), str(end_date)), "Bill Summary")
    finally:
        conn.close()


@st.cache_data(ttl=60, show_spinner="Bills load ho rahe hain...")
def cached_bill_page(start_date, end_date, search_text, page, page_size):
    """PERF FIX: pehle is period ke SAARE bills ek saath fetch ho kar dropdown mein daal
    diye jaate the - 10 lakh records pe yeh dropdown khud hi app ko atka deta. Ab sirf
    ek page (default 50 bills) fetch hoti hai, LIMIT/OFFSET ke saath, plus bill-no search."""
    conn = get_db()
    try:
        base_where = "WHERE date BETWEEN ? AND ?"
        params = [str(start_date), str(end_date)]
        if search_text:
            base_where += " AND bill_no LIKE ?"
            params.append(f"%{search_text}%")

        total_count_df = safe_read_sql(
            f"SELECT COUNT(*) as cnt FROM sales_bills {base_where}", conn, tuple(params), "Bill Count")
        total_count = int(total_count_df['cnt'][0]) if not total_count_df.empty else 0

        page_query = f"""
            SELECT bill_no as 'Bill No', customer_name as 'Customer', date as 'Date',
                   time as 'Time', final_total as 'Total', paid_amount as 'Paid',
                   balance as 'Balance', type as 'Type'
            FROM sales_bills {base_where}
            ORDER BY date DESC, time DESC LIMIT ? OFFSET ?
        """
        page_params = tuple(params) + (page_size, page * page_size)
        bills_df = safe_read_sql(page_query, conn, page_params, "Bill List")
        return bills_df, total_count
    finally:
        conn.close()


@st.cache_data(ttl=60, show_spinner=False)
def cached_bill_items(bill_no):
    conn = get_db()
    try:
        return safe_read_sql("""
            SELECT sbi.item_name as 'Item', sbi.qty as 'Qty', sbi.unit as 'Unit',
                   sbi.rate as 'Rate', sbi.total as 'Total'
            FROM sales_bill_items sbi JOIN sales_bills sb ON sbi.bill_id = sb.id
            WHERE sb.bill_no = ?
        """, conn, (bill_no,), "Bill Items")
    finally:
        conn.close()


def show_reports():
    st.header("📈 Reports - Hisaab Kitaab")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["📅 Mahine Ka Hisaab", "📦 Item-Wise Sale", "👥 Customer-Wise Udhaar", "💰 Galle Ka Cash Flow", "🧾 Bill Record"])

    with tab1:
        st.subheader("Mahine Ka Hisaab")
        col1, col2 = st.columns(2)
        start_date = col1.date_input("Shuru Ki Tarikh", datetime.now() - timedelta(days=30))
        end_date = col2.date_input("Aakhri Tarikh", datetime.now())

        if start_date > end_date:
            st.error("⚠️ Shuru ki tarikh, aakhri tarikh se pehle honi chahiye.")
        elif st.button("Hisaab Dekho", type="primary"):
            show_mahine_ka_hisaab(start_date, end_date)
        else:
            default_start = datetime.now().replace(day=1).date()
            default_end = datetime.now().date()
            st.info(f"👇 Default Report: {default_start} se {default_end} tak - Is Mahine")
            show_mahine_ka_hisaab(default_start, default_end)

    with tab2:
        st.subheader("Item-Wise Sale")
        col1, col2 = st.columns(2)
        start_date_item = col1.date_input("Shuru Ki Tarikh", datetime.now() - timedelta(days=30), key="item_start")
        end_date_item = col2.date_input("Aakhri Tarikh", datetime.now(), key="item_end")

        if start_date_item > end_date_item:
            st.error("⚠️ Shuru ki tarikh, aakhri tarikh se pehle honi chahiye.")
        elif st.button("Item-Wise Hisaab Dekho", type="primary", key="item_btn"):
            item_sale_df = cached_item_wise_sale(start_date_item, end_date_item)
            if not item_sale_df.empty:
                st.dataframe(item_sale_df, width='stretch')
                col1, col2 = st.columns(2)
                top_item = item_sale_df.iloc[0]
                col1.metric("Sabse Zyada Bikne Wala", f"{top_item['Item']}")
                col1.caption(f"Rs. {top_item['Total_Sale']:,.0f} ki sale")
                col2.metric("Total Bills", f"{item_sale_df['Times_Sold'].sum()} bills")
            else:
                st.info("Is date range mein koi sale nahi hui")

    with tab3:
        st.subheader("Customer-Wise Udhaar Baaki")
        cust_udhaar_df = cached_customer_udhaar()
        if not cust_udhaar_df.empty:
            st.dataframe(cust_udhaar_df, width='stretch')
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Customers", f"{len(cust_udhaar_df)}")
            col2.metric("Total Udhaar", f"Rs. {cust_udhaar_df['Baaki'].sum():,.0f}")
            col3.metric("Sabse Zyada", f"{cust_udhaar_df.iloc[0]['Customer']}")
            col3.caption(f"Rs. {cust_udhaar_df.iloc[0]['Baaki']:,.0f}")
        else:
            st.success("Sab customers clear hain - Koi udhaar baaki nahi")

    with tab4:
        show_galla_cash_flow()

    with tab5:
        show_bill_record()


def show_galla_cash_flow():
    st.subheader("💰 Galle Ka Cash Flow - Poori Tafseel")

    col_f1, col_f2 = st.columns(2)
    flow_start = col_f1.date_input("Shuru Ki Tarikh", datetime.now(), key="flow_start")
    flow_end = col_f2.date_input("Aakhri Tarikh", datetime.now(), key="flow_end")

    if flow_start > flow_end:
        st.error("⚠️ Shuru ki tarikh, aakhri tarikh se pehle honi chahiye.")
        return

    if not st.button("Cash Flow Details Dekho", type="primary", key="flow_btn"):
        return

    st.markdown("---")
    conn = get_db()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(expenses)")
            cols = [row[1] for row in cursor.fetchall()]
        except sqlite3.Error:
            cols = []

        exp_col = "category"
        if cols:
            if "category" in cols:
                exp_col = "category"
            elif "type" in cols:
                exp_col = "type"
            elif "description" in cols:
                exp_col = "description"
            elif "title" in cols:
                exp_col = "title"
            else:
                exp_col = cols[1] if len(cols) > 1 else "date"

        st.markdown("### 📥 1. Cash Inflow (Paise Kahan Se Aaye)")
        fs, fe = str(flow_start), str(flow_end)
        inflow_queries = [
            ("""SELECT DATE(date) as 'Tareeq', 'Nayi Sale (Dukan Bill)' as 'Tafseel', total as 'Raqam (Rs.)'
                FROM sales WHERE DATE(date) BETWEEN ? AND ? AND LOWER(TRIM(sale_type)) = 'cash'""", [fs, fe]),
            ("""SELECT DATE(date) as 'Tareeq', 'Roznama / Roll Nama Entry' as 'Tafseel', amount as 'Raqam (Rs.)'
                FROM roll_nama WHERE DATE(date) BETWEEN ? AND ? AND LOWER(TRIM(status)) = 'cash'""", [fs, fe]),
        ]
        inflow_frames = []
        for q, p in inflow_queries:
            inflow_frames.append(safe_read_sql(q, conn, tuple(p), "Cash Inflow"))
        if cols and exp_col in cols:
            inflow_frames.append(safe_read_sql(f"""
                SELECT DATE(date) as 'Tareeq', 'Expenses & Bill (Income/Jama)' as 'Tafseel', amount as 'Raqam (Rs.)'
                FROM expenses WHERE DATE(date) BETWEEN ? AND ?
                AND (LOWER(TRIM({exp_col})) LIKE '%jama%' OR LOWER(TRIM({exp_col})) LIKE '%received%' OR LOWER(TRIM({exp_col})) LIKE '%in%')
            """, conn, (fs, fe), "Expenses Inflow"))
        inflow_df = pd.concat([d for d in inflow_frames if not d.empty], ignore_index=True) if any(not d.empty for d in inflow_frames) else pd.DataFrame()

        if not inflow_df.empty:
            st.dataframe(inflow_df, width='stretch')
            total_inflow = inflow_df['Raqam (Rs.)'].sum()
            st.success(f"**Total Aane Wala Cash: Rs. {total_inflow:,.0f}**")
        else:
            total_inflow = 0
            st.info("Is dauran koi cash inflow nahi hua.")

        st.markdown("---")
        st.markdown("### 📤 2. Cash Outflow (Paise Kahan Gaye)")

        agency_df = safe_read_sql("""
            SELECT DATE(p.date) as 'Tareeq',
                   'Agency Paid: ' || IFNULL(a.name, 'Unknown Agency') || ' (Bill ID: ' || p.bill_id || ')' as 'Tafseel',
                   p.amount as 'Raqam (Rs.)'
            FROM agency_v2_payments p
            LEFT JOIN agency_v2_bills b ON p.bill_id = b.id
            LEFT JOIN agencies a ON b.agency_id = a.id
            WHERE DATE(p.date) BETWEEN ? AND ? AND LOWER(TRIM(p.payment_mode)) = 'cash'
        """, conn, (fs, fe), "Agency Cash Outflow")

        if cols and exp_col in cols:
            expenses_out_df = safe_read_sql(f"""
                SELECT DATE(date) as 'Tareeq', 'Dukan Kharcha (' || {exp_col} || ')' as 'Tafseel', amount as 'Raqam (Rs.)'
                FROM expenses WHERE DATE(date) BETWEEN ? AND ?
                AND NOT (LOWER(TRIM({exp_col})) LIKE '%jama%' OR LOWER(TRIM({exp_col})) LIKE '%received%' OR LOWER(TRIM({exp_col})) LIKE '%in%')
            """, conn, (fs, fe), "Expense Outflow")
        else:
            expenses_out_df = pd.DataFrame(columns=['Tareeq', 'Tafseel', 'Raqam (Rs.)'])

        frames = [d for d in (agency_df, expenses_out_df) if not d.empty]
        outflow_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=['Tareeq', 'Tafseel', 'Raqam (Rs.)'])

        if not outflow_df.empty:
            st.dataframe(outflow_df, width='stretch')
            total_outflow = outflow_df['Raqam (Rs.)'].sum()
            st.error(f"**Total Jane Wala Cash: Rs. {total_outflow:,.0f}**")
        else:
            total_outflow = 0
            st.info("Is dauran koi cash outflow ya kharcha nahi hua.")

        st.markdown("---")
        net_cash = total_inflow - total_outflow
        st.markdown("### 📋 3. Galle Ka Khulasa (Summary)")
        col_s1, col_s2, col_s3 = st.columns(3)
        col_s1.metric("Kul Aaya Cash (In)", f"Rs. {total_inflow:,.0f}")
        col_s2.metric("Kul Gaya Cash (Out)", f"Rs. {total_outflow:,.0f}")
        col_s3.metric("Galle Mein Maujood Cash", f"Rs. {net_cash:,.0f}")
    finally:
        conn.close()


def show_mahine_ka_hisaab(start_date, end_date):
    cash_total, udhaar_stock_total, jama_total, daily_sale_df, bills_df = cached_mahine_ka_hisaab(start_date, end_date)
    total_sale = cash_total + udhaar_stock_total

    st.markdown("### 📝 Hisaab Ka Khulasa")
    st.success(f"""
    **📅 {start_date} se {end_date} tak:**

    💵 **Cash Sale:** Rs. {cash_total:,.0f}
    📋 **Udhaar Sale:** Rs. {udhaar_stock_total:,.0f}
    💰 **Recovery (Jama):** Rs. {jama_total:,.0f}
    📊 **Total Sale:** Rs. {total_sale:,.0f}

    **🗓️ Aaj Ki Date:** {datetime.now().strftime('%d-%m-%Y')}
    """)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Cash Sale", f"Rs. {cash_total:,.0f}")
    col2.metric("Udhaar Sale", f"Rs. {udhaar_stock_total:,.0f}")
    col3.metric("Recovery", f"Rs. {jama_total:,.0f}")
    col4.metric("Total Sale", f"Rs. {total_sale:,.0f}")

    st.divider()

    st.subheader("📊 Roz Ki Sale - Chart")
    if not daily_sale_df.empty:
        col_chart1, col_chart2 = st.columns(2)
        with col_chart1:
            st.bar_chart(daily_sale_df.set_index('date'), color="#FF4B4B")
        with col_chart2:
            st.line_chart(daily_sale_df.set_index('date'), color="#00CC96")

        max_day = daily_sale_df.loc[daily_sale_df['sale'].idxmax()]
        min_day = daily_sale_df.loc[daily_sale_df['sale'].idxmin()]
        st.success(f"📈 **Sabse Zyada Sale:** {max_day['date']} - Rs. {max_day['sale']:,.0f}")
        st.warning(f"📉 **Sabse Kam Sale:** {min_day['date']} - Rs. {min_day['sale']:,.0f}")
    else:
        st.info("Is date range mein koi sale nahi")

    st.subheader("🧾 Today's Bills")
    if not bills_df.empty:
        bills_df = bills_df.copy()
        bills_df['Payment_Type'] = bills_df['sale_type'].apply(lambda x: 'Udhaar' if x == 'credit' else 'Cash')
        st.dataframe(bills_df, width='stretch')
    else:
        st.info("Aaj koi bill nahi")


def show_bill_record():
    st.subheader("🧾 Bill Record - Poora Hisaab")

    col1, col2, col3 = st.columns(3)
    with col1:
        filter_type = st.selectbox("Period Chuno",
            ["Aaj", "Kal", "Pichle 7 Din", "Is Mahine", "Pichle Mahine", "Custom Date"])

    today = datetime.now().date()
    if filter_type == "Aaj":
        start_date = end_date = today
    elif filter_type == "Kal":
        start_date = end_date = today - timedelta(days=1)
    elif filter_type == "Pichle 7 Din":
        start_date = today - timedelta(days=7)
        end_date = today
    elif filter_type == "Is Mahine":
        start_date = today.replace(day=1)
        end_date = today
    elif filter_type == "Pichle Mahine":
        first_day_this_month = today.replace(day=1)
        end_date = first_day_this_month - timedelta(days=1)
        start_date = end_date.replace(day=1)
    else:
        with col2:
            start_date = st.date_input("Start Date", today, key="bill_start")
        with col3:
            end_date = st.date_input("End Date", today, key="bill_end")

    if start_date > end_date:
        st.error("⚠️ Start Date, End Date se pehle honi chahiye.")
        return

    st.divider()

    summary = cached_bill_summary(start_date, end_date)
    col1, col2, col3, col4 = st.columns(4)
    if not summary.empty:
        with col1:
            st.metric("Total Bills", f"{summary['total_bills'][0]:.0f}")
        with col2:
            st.metric("Total Sale", f"Rs. {summary['total_sale'][0]:,.0f}")
        with col3:
            st.metric("Cash Received", f"Rs. {summary['total_paid'][0]:,.0f}")
        with col4:
            st.metric("Udhaar", f"Rs. {summary['total_udhaar'][0]:,.0f}")
    else:
        st.info("Is period ka summary abhi available nahi.")

    st.divider()

    # PERF FIX: search + pagination so this stays instant even with 10 lakh bills
    st.subheader("Bill List")
    search_col, page_col = st.columns([3, 1])
    search_text = search_col.text_input("🔍 Bill No Search (khaali chhoro sab dikhane ke liye)", key="bill_search")
    page_size = 50

    if "bill_record_page" not in st.session_state:
        st.session_state.bill_record_page = 0
    # Naya search/date range aaye to page 0 pe reset karo
    filter_signature = f"{start_date}|{end_date}|{search_text}"
    if st.session_state.get("bill_record_filter_sig") != filter_signature:
        st.session_state.bill_record_page = 0
        st.session_state.bill_record_filter_sig = filter_signature

    bills_df, total_count = cached_bill_page(start_date, end_date, search_text, st.session_state.bill_record_page, page_size)

    if total_count == 0:
        st.info("Is period me koi bill nahi mila. Pehle Nayi Sale se bill banao.")
        return

    total_pages = max(1, (total_count + page_size - 1) // page_size)
    with page_col:
        st.caption(f"Page {st.session_state.bill_record_page + 1} / {total_pages} ({total_count} bills)")

    nav1, nav2, nav3 = st.columns([1, 1, 4])
    if nav1.button("⬅️ Pichla", disabled=st.session_state.bill_record_page <= 0):
        st.session_state.bill_record_page -= 1
        st.rerun()
    if nav2.button("Agla ➡️", disabled=st.session_state.bill_record_page >= total_pages - 1):
        st.session_state.bill_record_page += 1
        st.rerun()

    if not bills_df.empty:
        selected_bill = st.selectbox("Bill Detail Dekho", bills_df['Bill No'].tolist(), key="bill_select")

        if selected_bill:
            items_df = cached_bill_items(selected_bill)
            bill_rows = bills_df[bills_df['Bill No'] == selected_bill]
            if not bill_rows.empty:
                bill_info = bill_rows.iloc[0]
                st.write(f"**Customer:** {bill_info['Customer']} | **Date:** {bill_info['Date']} {bill_info['Time']} | **Type:** {bill_info['Type']}")
                st.dataframe(items_df, width='stretch', hide_index=True)
                st.write(f"**Total: Rs. {bill_info['Total']:,.0f}** | **Paid: Rs. {bill_info['Paid']:,.0f}** | **Balance: Rs. {bill_info['Balance']:,.0f}**")

        st.divider()
        st.dataframe(bills_df, width='stretch', hide_index=True)
