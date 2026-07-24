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
    # 🕐 LIVE CLOCK (Asia/Karachi) + HIJRI DATE WIDGET
    # ========================================================================
    # BUG FIX: dashboard pehle server/container ka UTC time dikhata tha (jaise
    # 07:53:34 AM jabke Karachi mein us waqt asal mein 12:53:34 PM tha, kyunke
    # PKT = UTC+5). Ab hamesha Asia/Karachi time use hota hai, chahe server
    # kahin bhi (kisi bhi UTC/other-timezone machine par) host ho.
    # Karachi (PKT) = fixed UTC+5, Pakistan DST follow nahi karta - is liye
    # pytz ki zaroorat nahi, sirf ek lightweight fixed-offset calc kaafi hai.
    # (pytz import + tz lookup slow tha aur sirf initial/first-paint value
    # ke liye lagta tha - JS side ticking pehle se hi apna UTC+5 offset use
    # kar raha tha, ab Python side bhi wahi lightweight tareeqa use karta hai.)
    from datetime import timezone, timedelta
    now = datetime.now(timezone.utc) + timedelta(hours=5)

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
        # ULTRA-LIGHT CLOCK (fix for speed regression after live clock added):
        # Purana components.html() version har rerun par ek naya <iframe>
        # banata tha (heavy overhead) - isi wajah se Dashboard load 0.1s se
        # 1.1s ho gaya tha aur page navigation par bhi ~1s lag aata tha.
        # Ab st.markdown(unsafe_allow_html=True) use ho raha hai - yeh sirf
        # inline <div>/<script> string ko seedha page ke DOM mein daalta hai,
        # koi iframe nahi banta. Python sirf ek dafa (pehle paint ke liye)
        # Karachi time compute karta hai; uske baad ka har second ka tick
        # 100% client-side JS (setInterval) se hota hai jo sirf do DOM
        # elements (#pk-time, #pk-date) update karta hai - koi st.rerun,
        # koi Streamlit backend round-trip nahi. Isi liye har rerun/navigation
        # par iska overhead ~0 hai aur 0.1 sec target wapas aa jaata hai.
        initial_time = now.strftime("%I:%M:%S %p")
        initial_date = now.strftime("%A, %d %b %Y")
        st.markdown(f'''
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        padding: 12px 20px; border-radius: 12px; text-align: center;
                        box-shadow: 0 4px 15px rgba(0,0,0,0.2); font-family: 'Source Sans Pro', sans-serif;">
                <p style="margin:0; font-size:14px; color:#fff; font-weight:bold;">
                    🕐 <b id="pk-time">{initial_time}</b>
                </p>
                <p style="margin:5px 0 0 0; font-size:11px; color:#E8EAF6;">
                    <small id="pk-date">{initial_date}</small>{hijri_line}
                </p>
            </div>
            <script>
            (function() {{
                if (window.__pkClockRunning) return;
                window.__pkClockRunning = true;
                var days = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
                var months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
                setInterval(function() {{
                    var d = new Date();
                    var utc = d.getTime() + (d.getTimezoneOffset() * 60000);
                    var pkt = new Date(utc + (5 * 3600000));
                    var te = document.getElementById('pk-time');
                    var de = document.getElementById('pk-date');
                    if (te) {{
                        te.innerText = pkt.toLocaleTimeString('en-US', {{hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:true}});
                    }}
                    if (de) {{
                        de.innerText = days[pkt.getDay()] + ", " + String(pkt.getDate()).padStart(2,'0') + " " + months[pkt.getMonth()] + " " + pkt.getFullYear();
                    }}
                }}, 1000);
            }})();
            </script>
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

    # Card grid styling (Streamlit's own st.columns already stacks to 1 column
    # on narrow/mobile screens automatically, so no extra media-query hack needed).
    st.markdown('''
        <style>
        .udhaar-card-wrap {
            border-radius: 12px;
            padding: 12px 14px;
            margin-bottom: 10px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.18);
        }
        </style>
    ''', unsafe_allow_html=True)

    search_udhaar = st.text_input("🔍 Customer Ka Naam Search Karein (galat spelling bhi chalegi)...", placeholder="Customer ka naam likhein...", key="udhaar_search")

    st.markdown("<br>", unsafe_allow_html=True)

    # BUG FIX: pehle query sirf "total_udhaar > 0" wale customers laati thi -
    # is wajah se agar filhaal koi customer ka net balance 0 ho (ya calculation
    # mismatch ho), poora section khali dikhta tha "Koi udhaar wala customer
    # nahi mila" - chahe customers/udhaar entries maujood hon. Ab: pehle dues
    # (>0) wale customers try karo; agar koi na milay to recent 10 customers
    # (0 balance sahi hai) dikha do, taake yeh section kabhi bilkul khali na lage.
    #
    # PERF: pool ek dafa cache hota hai (15 sec) - search/pagination ke waqt
    # dobara DB hit nahi hoti, sirf isi cached pool par fuzzy filter chalta hai.
    @st.cache_data(ttl=15, show_spinner=False)
    def _cached_udhaar_pool():
        try:
            df_dues = pd.read_sql_query("""
                SELECT c.id, c.name, c.phone, c.photo,
                    IFNULL(SUM(CASE WHEN u.type='udhaar' THEN u.amount ELSE -u.amount END), 0) as total_udhaar
                FROM customers c LEFT JOIN udhaar u ON c.id = u.customer_id
                GROUP BY c.id, c.name, c.phone, c.photo
                HAVING total_udhaar > 0
                ORDER BY total_udhaar DESC LIMIT 100
            """, conn)
            print(f"[Dashboard Debug] Udhaar Top10 query -> customers with dues found: {len(df_dues)}")
            if not df_dues.empty:
                return df_dues

            # Koi bhi customer ka dues > 0 nahi mila - recent 10 customers
            # dikhao (0 balance) taake section kabhi khali na lage.
            df_recent = pd.read_sql_query("""
                SELECT c.id, c.name, c.phone, c.photo,
                    IFNULL(SUM(CASE WHEN u.type='udhaar' THEN u.amount ELSE -u.amount END), 0) as total_udhaar
                FROM customers c LEFT JOIN udhaar u ON c.id = u.customer_id
                GROUP BY c.id, c.name, c.phone, c.photo
                ORDER BY c.id DESC LIMIT 10
            """, conn)
            print(f"[Dashboard Debug] Udhaar Top10 query -> no dues, showing recent customers: {len(df_recent)}")
            return df_recent
        except Exception as e:
            st.error(f"❌ Udhaar data load karne mein error: {e}")
            return pd.DataFrame()

    df_udhaar_pool = _cached_udhaar_pool()

    if not df_udhaar_pool.empty and search_udhaar:
        search_lower = search_udhaar.strip().lower()
        names_lower = df_udhaar_pool['name'].astype(str).str.lower()
        starts_with_mask = names_lower.str.startswith(search_lower)
        contains_mask = names_lower.str.contains(search_lower, na=False, regex=False)
        substring_matches = df_udhaar_pool[starts_with_mask | contains_mask]

        if len(substring_matches) >= 1:
            df_udhaar_pool = substring_matches
        else:
            all_names = df_udhaar_pool['name'].astype(str).tolist()
            close = difflib.get_close_matches(search_udhaar, all_names, n=25, cutoff=0.5)
            df_udhaar_pool = df_udhaar_pool[df_udhaar_pool['name'].astype(str).isin(close)]

    # PAGINATION: 10 se shuru hoti hai, "Aur Dikhao" dabane se +10 (poora pool
    # ek sath load nahi hota - dashboard 0.1 sec jaisa tez rehta hai).
    if 'dashboard_udhaar_limit' not in st.session_state:
        st.session_state.dashboard_udhaar_limit = 10
    if st.session_state.get('_last_udhaar_search') != search_udhaar:
        # Search badalte hi limit wapas 10 par - naye results shuru se dikhein.
        st.session_state.dashboard_udhaar_limit = 10
        st.session_state['_last_udhaar_search'] = search_udhaar

    udhaar_limit = st.session_state.dashboard_udhaar_limit
    df_udhaar = df_udhaar_pool.head(udhaar_limit)

    if not df_udhaar.empty:
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8',
                  '#F7DC6F', '#BB8FCE', '#85C1E2', '#F8C471', '#82E0AA']

        # GRID: 2 columns on desktop, Streamlit auto-stacks to 1 column on mobile.
        card_cols = st.columns(2)
        for grid_idx, (_, row) in enumerate(df_udhaar.iterrows()):
            color = colors[grid_idx % len(colors)]
            customer_name = row['name']
            customer_id = row['id']
            total_amount = float(row['total_udhaar'])
            photo_data = row['photo']
            initial = str(customer_name)[0].upper() if customer_name else "?"
            avatar_fallback = f'<div style="width:80px; height:80px; border-radius:50%; background:rgba(255,255,255,0.35); display:flex; align-items:center; justify-content:center; font-size:32px; font-weight:bold; color:#fff; flex-shrink:0;">{initial}</div>'

            if photo_data and len(photo_data) > 0:
                try:
                    img_base64 = base64.b64encode(photo_data).decode()
                    photo_html = f'<img src="data:image/png;base64,{img_base64}" style="width:80px; height:80px; border-radius:50%; object-fit:cover; border:3px solid white; flex-shrink:0;">'
                except Exception:
                    photo_html = avatar_fallback
            else:
                photo_html = avatar_fallback

            display_amount = f"Rs. {total_amount:,.2f}" if show_amounts else "••••••"

            with card_cols[grid_idx % 2]:
                st.markdown(f'''
                    <div class="udhaar-card-wrap" style="background:{color};">
                        <div style="display:flex; align-items:center; gap:12px;">
                            {photo_html}
                            <div>
                                <p style="margin:0; font-size:16px; font-weight:bold; color:#fff; text-shadow:1px 1px 2px rgba(0,0,0,0.25);">{customer_name}</p>
                                <p style="margin:4px 0 0 0; font-size:12px; color:#fff; opacity:0.85;">Total Udhaar</p>
                                <p style="margin:2px 0 0 0; font-size:20px; font-weight:bold; color:#fff; text-shadow:1px 1px 2px rgba(0,0,0,0.25);">{display_amount}</p>
                            </div>
                        </div>
                    </div>
                ''', unsafe_allow_html=True)

                # SHORTCUT: seedha Udhaar Khatta page par isi customer ka khata khol deta hai.
                if st.button("📖 Khata Kholo", key=f"khata_shortcut_{customer_id}", use_container_width=True):
                    st.session_state['selected_customer_id'] = customer_id
                    st.session_state.force_open_khata = True
                    # BUG FIX: seedha "st.session_state.menu = ..." set karna crash deta
                    # tha (StreamlitAPIException) kyunke menu ek widget se bound hai.
                    # Ab safe '_pending_menu' flag use hota hai jo app.py sidebar render
                    # hone se PEHLE apply karta hai.
                    st.session_state['_pending_menu'] = "📒 Udhaar Khatta"
                    st.rerun()

        if len(df_udhaar_pool) > udhaar_limit:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("⬇️ Aur Dikhao (Load More 10)", key="udhaar_load_more", use_container_width=True):
                st.session_state.dashboard_udhaar_limit += 10
                st.rerun()
    else:
        st.info("🔍 Koi udhaar wala customer nahi mila")

    conn.close()