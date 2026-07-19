def show_daily_sale(get_db=None):
    import streamlit as st
    import sqlite3
    import pandas as pd
    from datetime import datetime
    import os
    import base64
    import difflib
    # BUG FIX: hijri_converter is a 3rd-party package. If it's ever missing/broken,
    # the whole Dashboard (the app's default/startup page) used to crash immediately.
    # Now we fall back gracefully and just hide the Hijri date instead of crashing.
    try:
        from hijri_converter import convert
        HIJRI_AVAILABLE = True
    except Exception:
        HIJRI_AVAILABLE = False

    # --- Database Connection ---
    if get_db is not None:
        conn = get_db()
    else:
        # BUG FIX: pehle yahan "store.db"/"data.db" (galat naam wali files) khulti
        # thin agar get_db na mile - ab hamesha sahi "afzal_store.db" khulti hai,
        # WAL mode ke sath (locked errors se bachne ke liye).
        conn = sqlite3.connect("afzal_store.db", check_same_thread=False, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()
    today_str = datetime.now().strftime("%Y-%m-%d")

    # YE TABLE BANANE WALA CODE HAI - roll_nama
    c.execute("""CREATE TABLE IF NOT EXISTS roll_nama (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        customer_name TEXT,
        amount REAL,
        status TEXT
    )""")
    conn.commit()

    c.execute("""CREATE TABLE IF NOT EXISTS agency_v2_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        agency_name TEXT,
        amount REAL,
        payment_type TEXT,
        payment_mode TEXT
    )""")
    conn.commit()

    # ========================================================================
    # 🔔 NOTIFICATION SYSTEM
    # ========================================================================
    notifications = []
    
    try:
        c.execute("SELECT name, stock FROM items WHERE stock < 10 AND stock > 0")
        low_stock = c.fetchall()
        for item in low_stock:
            notifications.append({"type": "warning", "msg": f"⚠️ Low Stock: {item[0]} - Sirf {item[1]} bacha"})
        
        c.execute("SELECT name FROM items WHERE stock = 0")
        out_stock = c.fetchall()
        for item in out_stock:
            notifications.append({"type": "error", "msg": f"🚨 Out of Stock: {item[0]}"})
    except:
        pass
    
    try:
        c.execute("""
            SELECT c.name, u.date, SUM(u.amount) as total 
            FROM udhaar u 
            JOIN customers c ON u.customer_id = c.id 
            WHERE u.type='udhaar' AND julianday('now') - julianday(u.date) > 30 
            GROUP BY c.id HAVING total > 0 LIMIT 5
        """)
        defaulters = c.fetchall()
        for d in defaulters:
            notifications.append({"type": "error", "msg": f"🚨 Defaulter: {d[0]} - 30+ din se udhaar"})
    except:
        pass

    # ========================================================================
    # 🕐 LIVE CLOCK + HIJRI DATE WIDGET
    # ========================================================================
    now = datetime.now()
    hijri_line = ""
    if HIJRI_AVAILABLE:
        try:
            hijri_date = convert.Gregorian(now.year, now.month, now.day).to_hijri()
            hijri_months = ["Muharram", "Safar", "Rabi al-Awwal", "Rabi al-Thani", "Jumada al-Awwal", 
                            "Jumada al-Thani", "Rajab", "Shaban", "Ramadan", "Shawwal", 
                            "Dhu al-Qidah", "Dhu al-Hijjah"]
            hijri_line = f" | {hijri_date.day} {hijri_months[hijri_date.month-1]} {hijri_date.year} AH"
        except Exception:
            hijri_line = ""
    
    col_title, col_clock, col_notif = st.columns([3, 2, 1])
    
    with col_title:
        st.title("📊 Afzal Store - Main Dashboard")
    
    with col_clock:
        st.markdown(f'''
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                        padding: 12px 20px; border-radius: 12px; text-align: center;
                        box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                <p style="margin:0; font-size:14px; color:#fff; font-weight:bold;">
                    🕐 {now.strftime("%I:%M:%S %p")}
                </p>
                <p style="margin:5px 0 0 0; font-size:11px; color:#E8EAF6;">
                    {now.strftime("%d %b %Y")}{hijri_line}
                </p>
            </div>
        ''', unsafe_allow_html=True)
    
    with col_notif:
        notif_count = len(notifications)
        if notif_count > 0:
            if st.button(f"🔔 {notif_count}", key="notif_bell", help="Notifications dekho"):
                st.session_state.show_notif = not st.session_state.get('show_notif', False)
        else:
            st.markdown('<div style="text-align:center; padding:12px; font-size:24px;">🔔</div>', unsafe_allow_html=True)
    
    if st.session_state.get('show_notif', False) and notifications:
        with st.container():
            st.markdown('<div style="background:#fff; border-radius:10px; padding:15px; box-shadow:0 4px 15px rgba(0,0,0,0.1); margin-bottom:20px;">', unsafe_allow_html=True)
            st.markdown("### 🔔 Notifications")
            for notif in notifications[:5]:
                color = "#FFF3CD" if notif['type'] == "warning" else "#F8D7DA"
                st.markdown(f'<div style="background:{color}; padding:10px; border-radius:8px; margin-bottom:8px; font-size:13px;">{notif["msg"]}</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
    
    st.divider()

    # ========================================================================
    # 🌟 CENTRALIZED CALCULATION ENGINE
    # ========================================================================
    aaj_ki_kul_cash_sale = 0.0
    
    c.execute("SELECT SUM(total) FROM sales WHERE date =? AND LOWER(TRIM(sale_type)) = 'cash'", (today_str,))
    res_sales = c.fetchone()
    if res_sales[0]: aaj_ki_kul_cash_sale += float(res_sales[0])

    c.execute("SELECT SUM(amount) FROM roll_nama WHERE date =? AND LOWER(TRIM(status)) = 'cash'", (today_str,))
    res_roll = c.fetchone()
    if res_roll[0]: aaj_ki_kul_cash_sale += float(res_roll[0])
    
    c.execute("SELECT SUM(amount) FROM udhaar WHERE date =? AND LOWER(TRIM(type)) = 'jama'", (today_str,))
    res_jama = c.fetchone()
    if res_jama and res_jama[0]: aaj_ki_kul_cash_sale += float(res_jama[0])

    c.execute("SELECT SUM(amount) FROM agency_v2_payments WHERE date =? AND LOWER(TRIM(payment_mode)) = 'cash'", (today_str,))
    res_agency = c.fetchone()
    if res_agency[0]: aaj_ki_kul_cash_sale -= float(res_agency[0])

    c.execute("SELECT expense_type, amount FROM expenses WHERE date =?", (today_str,))
    for entry in c.fetchall():
        kism, raqam = str(entry[0]).lower(), float(entry[1])
        if "investment" in kism or "salary" in kism:
            aaj_ki_kul_cash_sale += raqam
        else:
            aaj_ki_kul_cash_sale -= raqam

    total_udhaar = 0.0
    try:
        c.execute("SELECT IFNULL(SUM(CASE WHEN u.type='udhaar' THEN u.amount ELSE -u.amount END), 0) FROM udhaar u")
        res3 = c.fetchone()
        if res3 and res3[0] is not None:
            total_udhaar = float(res3[0])
    except:
        pass

    total_items_count = 0
    try:
        c.execute("SELECT COUNT(*) FROM items")
        res4 = c.fetchone()
        if res4 and res4[0] is not None:
            total_items_count = int(res4[0])
    except:
        pass

    try:
        c.execute("SELECT SUM(bachat) FROM roll_nama WHERE DATE(date) = DATE(?)", (today_str,))
        result = c.fetchone()
        aaj_ki_bachat = float(result[0]) if result and result[0] else 0.0
    except:
        aaj_ki_bachat = 0.0

    # 9. Aata Chaki ki Sale - FIXED: chakki_atta_sale table se
    aata_chaki_sale = 0.0
    try:
        c.execute("SELECT SUM(total) FROM chakki_atta_sale WHERE date =?", (today_str,))
        res_chaki = c.fetchone()
        if res_chaki and res_chaki[0]:
            aata_chaki_sale = float(res_chaki[0])
    except:
        pass

    # ========================================================
    # 🎨 GLASS MORPHISM CARDS - 5 CARDS
    # ========================================================
    show_amounts = os.path.exists('show_amounts.txt')

    col_card1, col_card2, col_card3, col_card4, col_card5 = st.columns(5)

    glass_style = """
        background: rgba(255, 255, 255, 0.15);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.3);
        box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
        padding: 15px; border-radius: 15px; min-height: 110px;
    """

    with col_card1:
        display_value = f"Rs. {aaj_ki_kul_cash_sale:,.2f}" if show_amounts else "••••••"
        st.markdown(f'<div style="{glass_style} background: linear-gradient(135deg, rgba(46,125,50,0.7) 0%, rgba(67,160,71,0.7) 100%);"><p style="margin: 0; font-size: 13px; color: #E8F5E9; font-weight: bold;">🏪 Aj Ki Cash Sale</p><h3 style="margin: 10px 0 0 0; color: #fff; font-size: 20px;">{display_value}</h3></div>', unsafe_allow_html=True)

    with col_card2:
        display_value = f"Rs. {total_udhaar:,.2f}" if show_amounts else "••••••"
        st.markdown(f'<div style="{glass_style} background: linear-gradient(135deg, rgba(198,40,40,0.7) 0%, rgba(229,57,53,0.7) 100%);"><p style="margin: 0; font-size: 13px; color: #FFEBEE; font-weight: bold;">📉 Total Udhaar</p><h3 style="margin: 10px 0 0 0; color: #fff; font-size: 20px;">{display_value}</h3></div>', unsafe_allow_html=True)

    with col_card3:
        display_value = f"Rs. {aaj_ki_bachat:,.2f}" if show_amounts else "••••••"
        st.markdown(f'<div style="{glass_style} background: linear-gradient(135deg, rgba(255,160,0,0.7) 0%, rgba(255,179,0,0.7) 100%);"><p style="margin: 0; font-size: 13px; color: #E65100; font-weight: bold;">💰 Aj Ki Bachat</p><h3 style="margin: 10px 0 0 0; color: #fff; font-size: 20px;">{display_value}</h3></div>', unsafe_allow_html=True)

    with col_card4:
        display_value = f"Rs. {aata_chaki_sale:,.2f}" if show_amounts else "••••••"
        st.markdown(f'<div style="{glass_style} background: linear-gradient(135deg, rgba(106,27,154,0.7) 0%, rgba(142,36,170,0.7) 100%);"><p style="margin: 0; font-size: 13px; color: #F3E5F5; font-weight: bold;">🌾 Aata Chaki Sale</p><h3 style="margin: 10px 0 0 0; color: #fff; font-size: 20px;">{display_value}</h3></div>', unsafe_allow_html=True)

    with col_card5:
        st.markdown(f'<div style="{glass_style} background: linear-gradient(135deg, rgba(26,35,126,0.7) 0%, rgba(40,53,147,0.7) 100%);"><p style="margin: 0; font-size: 13px; color: #E8EAF6; font-weight: bold;">📦 Total Items</p><h3 style="margin: 10px 0 0 0; color: #fff; font-size: 20px;">{total_items_count} Items</h3></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("📦 Store Items Ki List")

    try:
        cols_df = pd.read_sql_query("PRAGMA table_info(items)", conn)
        all_cols = cols_df['name'].tolist()

        if 'name' in all_cols: name_col = 'name'
        elif 'item_name' in all_cols: name_col = 'item_name'
        elif 'product' in all_cols: name_col = 'product'
        else: name_col = all_cols[0]

        if 'stock' in all_cols: stock_col = 'stock'
        elif 'qty' in all_cols: stock_col = 'qty'
        elif 'quantity' in all_cols: stock_col = 'quantity'
        else: stock_col = all_cols[1]

        if 'sale_price' in all_cols: price_col = 'sale_price'
        elif 'price' in all_cols: price_col = 'price'
        elif 'rate' in all_cols: price_col = 'rate'
        else: price_col = all_cols[2]

        cat_col = 'category' if 'category' in all_cols else None
    except Exception as e:
        st.error(f"❌ DB Error: {e}")
        name_col = stock_col = price_col = cat_col = None

    if name_col:
        # PERF FIX: category list ek chhoti si cached query hai (real categories
        # DB se aate hain, hardcoded nahi) - 15 sec cache, 5000+ items pe bhi tez.
        @st.cache_data(ttl=15, show_spinner=False)
        def _cached_categories():
            try:
                if cat_col:
                    cdf = pd.read_sql_query(f"SELECT DISTINCT {cat_col} FROM items WHERE {cat_col} IS NOT NULL AND {cat_col} != '' ORDER BY {cat_col}", conn)
                    return cdf[cat_col].tolist()
            except Exception:
                pass
            return []

        @st.cache_data(ttl=15, show_spinner=False)
        def _cached_items_for_category(category):
            try:
                if category and category != "All Categories" and cat_col:
                    return pd.read_sql_query(f"SELECT * FROM items WHERE {cat_col} = ?", conn, params=(category,))
                return pd.read_sql_query("SELECT * FROM items", conn)
            except Exception as e:
                st.error(f"❌ DB Error: {e}")
                return pd.DataFrame()

        search_col, cat_filter_col = st.columns([2, 1])
        with search_col:
            search_query = st.text_input("🔍 Item Ka Naam Likh Kar Search Karein...", placeholder="Pehla lafz ya full name likhein (galat spelling bhi chalegi)...", key="dash_item_search")
        with cat_filter_col:
            category_options = ["All Categories"] + _cached_categories()
            selected_category = st.selectbox("Category", category_options, key="dash_item_category")

        st.markdown("<br>", unsafe_allow_html=True)

        df_items = _cached_items_for_category(selected_category)

        if not df_items.empty and search_query:
            # Smart + Fuzzy Search: pehle "starts with" (jaise "C" -> Cheeni, Chawal turant),
            # phir substring, phir galat spelling ke liye fuzzy (difflib) fallback.
            search_lower = search_query.strip().lower()
            names_lower = df_items[name_col].astype(str).str.lower()

            starts_with_mask = names_lower.str.startswith(search_lower)
            contains_mask = names_lower.str.contains(search_lower, na=False, regex=False)
            substring_matches = df_items[starts_with_mask | contains_mask]

            if len(substring_matches) >= 2:
                df_items = substring_matches
            else:
                all_names = df_items[name_col].astype(str).tolist()
                close = difflib.get_close_matches(search_query, all_names, n=25, cutoff=0.5)
                fuzzy_matches = df_items[df_items[name_col].astype(str).isin(close)]
                combined = pd.concat([substring_matches, fuzzy_matches]).drop_duplicates(subset=[name_col])
                df_items = combined if not combined.empty else df_items.iloc[0:0]

        if not df_items.empty:
            if cat_col:
                df_items = df_items.copy()
                df_items[cat_col] = df_items[cat_col].astype(str).str.strip()

            display_df = df_items.head(60)  # PERF: ek waqt mein max 60 cards - dashboard tez rehta hai
            card_cols = st.columns(2)
            for idx, (_, row) in enumerate(display_df.iterrows()):
                stock_val = int(row[stock_col] or 0)
                stock_color = "#2E7D32" if stock_val > 10 else "#F57C00" if stock_val > 0 else "#C62828"
                cat_label = f"{row[cat_col]} | " if cat_col and row[cat_col] else ""
                with card_cols[idx % 2]:
                    st.markdown(f'''
                        <div style="background: linear-gradient(135deg, #E8F5E9 0%, #C8E6C9 100%);
                            padding: 10px 14px; border-radius: 8px; margin-bottom: 8px; border-left: 4px solid #2E7D32;
                            display: flex; justify-content: space-between; align-items: center; min-height: 60px;">
                            <div>
                                <p style="margin:0; font-size:17px; font-weight:bold; color:#1B5E20; line-height:1.2;">{row[name_col]}</p>
                                <p style="margin:3px 0 0 0; font-size:14px; color:#2E7D32; line-height:1.2;">
                                    {cat_label}Stock: <b style="color:{stock_color};">{stock_val}</b>
                                </p>
                            </div>
                            <div style="text-align: right;">
                                <p style="margin:0; font-size:16px; font-weight:bold; color:#1B5E20; line-height:1.2;">Rs. {float(row[price_col] or 0):,.2f}</p>
                            </div>
                        </div>
                    ''', unsafe_allow_html=True)
            if len(df_items) > 60:
                st.caption(f"ℹ️ {len(df_items)} items milay - sirf pehle 60 dikhaye ja rahe hain. Search se aur narrow karein.")
        else:
            st.info("Koi item nahi mila. (Agar items table khali hai to pehle 'Items Add' se items shamil karein.)")

    st.markdown("<br><br>", unsafe_allow_html=True)
    st.divider()
    st.subheader("💳 Udhaar Khatta - Top 10 Customers")

    search_udhaar = st.text_input("🔍 Customer Ka Naam Search Karein (galat spelling bhi chalegi)...", placeholder="Customer ka naam likhein...", key="udhaar_search")

    st.markdown("<br>", unsafe_allow_html=True)

    # PERF FIX: pool ek dafa cache hota hai (15 sec) - search karte waqt dobara
    # DB hit nahi hoti, sirf isi pool par fuzzy filter chalta hai.
    @st.cache_data(ttl=15, show_spinner=False)
    def _cached_udhaar_pool():
        try:
            return pd.read_sql_query("""
                SELECT c.id, c.name, c.phone, c.photo,
                    IFNULL(SUM(CASE WHEN u.type='udhaar' THEN u.amount ELSE -u.amount END), 0) as total_udhaar
                FROM customers c LEFT JOIN udhaar u ON c.id = u.customer_id
                GROUP BY c.id, c.name, c.phone, c.photo
                HAVING total_udhaar > 0 ORDER BY total_udhaar DESC LIMIT 50
            """, conn)
        except Exception as e:
            st.error(f"❌ Udhaar data load karne mein error: {e}")
            return pd.DataFrame()

    df_udhaar = _cached_udhaar_pool()

    if not df_udhaar.empty and search_udhaar:
        search_lower = search_udhaar.strip().lower()
        names_lower = df_udhaar['name'].astype(str).str.lower()
        starts_with_mask = names_lower.str.startswith(search_lower)
        contains_mask = names_lower.str.contains(search_lower, na=False, regex=False)
        substring_matches = df_udhaar[starts_with_mask | contains_mask]

        if len(substring_matches) >= 1:
            df_udhaar = substring_matches
        else:
            all_names = df_udhaar['name'].astype(str).tolist()
            close = difflib.get_close_matches(search_udhaar, all_names, n=10, cutoff=0.5)
            df_udhaar = df_udhaar[df_udhaar['name'].astype(str).isin(close)]

    df_udhaar = df_udhaar.head(10)

    if not df_udhaar.empty:
        colors = [
            ("linear-gradient(135deg, #FF6B6B 0%, #FF8E53 100%)", "#FF6B6B"),
            ("linear-gradient(135deg, #4ECDC4 0%, #44A08D 100%)", "#44A08D"),
            ("linear-gradient(135deg, #667EEA 0%, #764BA2 100%)", "#764BA2"),
            ("linear-gradient(135deg, #F093FB 0%, #F5576C 100%)", "#F5576C"),
            ("linear-gradient(135deg, #FA709A 0%, #FEE140 100%)", "#FA709A"),
            ("linear-gradient(135deg, #30CFD0 0%, #330867 100%)", "#330867"),
            ("linear-gradient(135deg, #A8EDEA 0%, #FED6E3 100%)", "#5bb8b3"),
            ("linear-gradient(135deg, #FFD89B 0%, #19547B 100%)", "#19547B"),
            ("linear-gradient(135deg, #D299C2 0%, #FEF9D7 100%)", "#D299C2"),
            ("linear-gradient(135deg, #89F7FE 0%, #66A6FF 100%)", "#66A6FF"),
        ]

        for idx, row in df_udhaar.iterrows():
            color_idx = idx % len(colors)
            gradient, solid = colors[color_idx]
            customer_name = row['name']
            customer_id = row['id']
            total_amount = float(row['total_udhaar'])
            phone = row['phone'] if row['phone'] else "No Phone"
            photo_data = row['photo']

            if photo_data and len(photo_data) > 0:
                try:
                    img_base64 = base64.b64encode(photo_data).decode()
                    photo_html = f'<img src="data:image/png;base64,{img_base64}" style="width:50px; height:50px; border-radius:50%; object-fit:cover; border:3px solid white; margin-right:15px;">'
                except Exception:
                    photo_html = '<div style="width:50px; height:50px; border-radius:50%; background:#fff; display:flex; align-items:center; justify-content:center; font-size:24px; margin-right:15px;">👤</div>'
            else:
                photo_html = '<div style="width:50px; height:50px; border-radius:50%; background:#fff; display:flex; align-items:center; justify-content:center; font-size:24px; margin-right:15px;">👤</div>'

            display_amount = f"Rs. {total_amount:,.2f}" if show_amounts else "••••••"

            st.markdown(f'''
                <div style="background: {gradient};
                    padding: 15px 20px; border-radius: 12px 12px 0 0; margin-bottom: 0;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                    display: flex; align-items: center; justify-content: space-between;">
                    <div style="display: flex; align-items: center;">
                        {photo_html}
                        <div>
                            <p style="margin:0; font-size:18px; font-weight:bold; color:#fff; text-shadow: 1px 1px 2px rgba(0,0,0,0.3);">{customer_name}</p>
                            <p style="margin:3px 0 0 0; font-size:13px; color:#fff; opacity:0.9;">📞 {phone}</p>
                        </div>
                    </div>
                    <div style="text-align: right;">
                        <p style="margin:0; font-size:12px; color:#fff; opacity:0.8;">Total Udhaar</p>
                        <p style="margin:5px 0 0 0; font-size:22px; font-weight:bold; color:#fff; text-shadow: 1px 1px 2px rgba(0,0,0,0.3);">{display_amount}</p>
                    </div>
                </div>
            ''', unsafe_allow_html=True)

            # SHORTCUT CLICK: is button ko seedha card ke neeche, bina gap ke chipka
            # diya hai (CSS se) taake yeh ek hi cohesive clickable card lage. Dabate
            # hi seedha Udhaar Khatta khul kar isi customer ka khata dikhayega.
            st.markdown(f'<style>div[data-testid="stButton"] > button[kind="secondary"]#khata_shortcut_{customer_id} {{ background:{solid}!important; }}</style>', unsafe_allow_html=True)
            if st.button(f"➡️ {customer_name} Ka Khata Kholein", key=f"khata_shortcut_{customer_id}", use_container_width=True):
                st.session_state['selected_customer_id'] = customer_id
                st.session_state.force_open_khata = True
                # BUG FIX: seedha "st.session_state.menu = ..." set karna crash deta
                # tha (StreamlitAPIException) kyunke menu ek widget se bound hai.
                # Ab safe '_pending_menu' flag use hota hai jo app.py sidebar render
                # hone se PEHLE apply karta hai.
                st.session_state['_pending_menu'] = "📒 Udhaar Khatta"
                st.rerun()
            st.markdown("<div style='margin-bottom:12px;'></div>", unsafe_allow_html=True)
    else:
        st.info("🔍 Koi udhaar wala customer nahi mila")

    conn.close()