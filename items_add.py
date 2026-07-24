import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date
import os
import urllib.parse
from logo_setting import get_theme_colors
import image_compression

# --- FUNCTION UPAR MOVE KIYA HAI TAAKI IMPORT ERROR NA AAYE ---
def get_db():
    # PERF/BUG FIX: WAL mode + timeout add kiya - pehle yahan bina timeout/WAL ke
    # connection khulta tha, jo doosre pages ke sath "database is locked" errors ki
    # bari wajah tha (Chaki, Roll Nama, Udhaar sab isi DB file ko ek waqt use karte hain).
    conn = sqlite3.connect('afzal_store.db', check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

# --- FIX FEATURE: EXTERNAL STOCK DEDUCTION WITH DYNAMIC UNIT & DOCK INTEGRATION ---
def update_stock_from_external(item_name, quantity_to_minus):
    conn = get_db()
    item = conn.execute("SELECT id, stock, base_unit FROM items WHERE LOWER(name) = LOWER(?)", (item_name.strip(),)).fetchone()
    if item:
        item_id, current_stock, base_unit = item
        new_stock = float(current_stock) - float(quantity_to_minus)
        conn.execute("UPDATE items SET stock =? WHERE id =?", (new_stock, item_id))
        conn.execute('''INSERT INTO stock_history (item_id, item_name, type, qty, unit, old_stock, new_stock, note, date, time)
                        VALUES (?,?,?,?,?,?,?,?,?,?)''',
                     (item_id, item_name, 'OUT', quantity_to_minus, base_unit, current_stock, new_stock,
                      'Deducted via Roz Ka Roll Nama', datetime.now().strftime("%Y-%m-%d"),
                      datetime.now().strftime("%H:%M:%S")))
        conn.commit()
    conn.close()
    return True

def generate_bill_no():
    return f"BILL-{datetime.now().strftime('%Y%m%d%H%M%S')}"

# PERF FIX: this whole migration block used to run in full on every single rerun of this
# page - i.e. every widget interaction on ANY of its 7 tabs, since Streamlit executes every
# st.tabs() body on each rerun regardless of which tab is visible. That meant 11
# unconditional full-table UPDATEs plus several schema probes on every click. Cached so it
# actually runs once an hour per server process instead of every rerun. backup_setting.py's
# restore flow clears this cache too (st.cache_resource.clear() is global).
@st.cache_resource(ttl=3600, show_spinner=False)
def ensure_items_schema():
    conn = get_db()

    # ===== DATABASE MIGRATION - ITEMS =====
    conn.execute('''CREATE TABLE IF NOT EXISTS items
                 (id INTEGER PRIMARY KEY, name TEXT, category TEXT, kharid_price REAL, sale_price REAL,
                 base_unit TEXT, stock REAL, min_stock INTEGER, barcode TEXT, expiry_date TEXT, photo TEXT, parent_id INTEGER)''')

    cursor = conn.execute("PRAGMA table_info(items)")
    existing_cols = [row[1] for row in cursor.fetchall()]
    new_cols = {
        'category': 'TEXT DEFAULT "Other"',
        'kharid_price': 'REAL DEFAULT 0',
        'sale_price': 'REAL DEFAULT 0',
        'base_unit': 'TEXT DEFAULT "Pcs"',
        'min_stock': 'INTEGER DEFAULT 0',
        'barcode': 'TEXT',
        'expiry_date': 'TEXT',
        'photo': 'TEXT',
        'photo_thumb': 'TEXT',
        'parent_id': 'INTEGER',
        'default_rate': 'REAL DEFAULT 0',
        'price': 'REAL DEFAULT 0',
        'agency_name': "TEXT DEFAULT 'No Agency'",
        'item_no': 'INTEGER'
    }
    for col, col_type in new_cols.items():
        if col not in existing_cols:
            try:
                conn.execute(f"ALTER TABLE items ADD COLUMN {col} {col_type}")
                conn.commit()
            except:
                pass

    conn.execute("UPDATE items SET kharid_price = 0 WHERE kharid_price IS NULL")
    conn.execute("UPDATE items SET sale_price = 0 WHERE sale_price IS NULL")
    conn.execute("UPDATE items SET base_unit = 'Pcs' WHERE base_unit IS NULL OR base_unit = ''")
    conn.execute("UPDATE items SET stock = 0 WHERE stock IS NULL")
    conn.execute("UPDATE items SET min_stock = 0 WHERE min_stock IS NULL")
    conn.execute("UPDATE items SET category = 'Other' WHERE category IS NULL OR category = ''")
    conn.execute("UPDATE items SET price = sale_price WHERE price = 0 OR price IS NULL")
    conn.commit()

    # Auto-assign item_no to existing items that have none (sequential by id)
    items_without_no = conn.execute("SELECT id FROM items WHERE item_no IS NULL ORDER BY id ASC").fetchall()
    if items_without_no:
        used_nos = set(r[0] for r in conn.execute("SELECT item_no FROM items WHERE item_no IS NOT NULL").fetchall())
        counter = 1
        for (iid,) in items_without_no:
            while counter in used_nos:
                counter += 1
            conn.execute("UPDATE items SET item_no = ? WHERE id = ?", (counter, iid))
            used_nos.add(counter)
            counter += 1
        conn.commit()

    # ===== DATABASE - SALES TABLE =====
    conn.execute('''CREATE TABLE IF NOT EXISTS sales
                 (id INTEGER PRIMARY KEY, bill_no TEXT, item_id INTEGER, item_name TEXT, qty REAL, unit TEXT,
                 rate REAL, total REAL, munafa REAL, sale_type TEXT, customer_id INTEGER, customer_name TEXT,
                 date TEXT, time TEXT, note TEXT)''')

    cursor = conn.execute("PRAGMA table_info(sales)")
    sales_cols = [row[1] for row in cursor.fetchall()]
    if 'munafa' not in sales_cols: conn.execute("ALTER TABLE sales ADD COLUMN munafa REAL DEFAULT 0")
    if 'unit' not in sales_cols: conn.execute("ALTER TABLE sales ADD COLUMN unit TEXT DEFAULT 'Pcs'")
    if 'rate' not in sales_cols: conn.execute("ALTER TABLE sales ADD COLUMN rate REAL DEFAULT 0")
    if 'note' not in sales_cols: conn.execute("ALTER TABLE sales ADD COLUMN note TEXT")
    if 'item_name' not in sales_cols: conn.execute("ALTER TABLE sales ADD COLUMN item_name TEXT")
    conn.commit()

    # ===== DATABASE - STOCK HISTORY =====
    conn.execute('''CREATE TABLE IF NOT EXISTS stock_history
                 (id INTEGER PRIMARY KEY, item_id INTEGER, item_name TEXT, type TEXT, qty REAL, unit TEXT,
                 old_stock REAL, new_stock REAL, note TEXT, date TEXT, time TEXT)''')
    conn.commit()

    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS customers
                     (id INTEGER PRIMARY KEY, name TEXT, type TEXT DEFAULT "customer")''')
        conn.commit()
    except:
        pass

    conn.close()

def show_items_add():
    # ===== ALL SESSION STATES INITIALIZATION =====
    if 'cart' not in st.session_state: st.session_state['cart'] = []

    # BUG FIX (KeyError: 'name'): "Nayi Sale > Multi-Item Cart" pehle isi
    # session_state['cart'] key ko istemal kar raha tha - agar koi customer
    # pehle Nayi Sale ka cart use karta aur phir Items Add pe aata, to yahan
    # ka code un entries ko padhne ki koshish karta jinke keys alag the
    # (jaise 'item' bajaye 'name' ke) - is se KeyError crash hota tha. Ab
    # Nayi Sale ka apna alag session key hai ('multi_item_sale_cart'), aur
    # yahan bhi extra safety ke liye har purani/malformed cart entry (jis
    # mein zaroori keys na hon) khud-ba-khud hata di jati hai - crash ki
    # jagah bas woh entry gayab ho jati hai.
    st.session_state['cart'] = [
        ci for ci in st.session_state['cart']
        if isinstance(ci, dict) and all(k in ci for k in ('name', 'item_id', 'qty', 'unit', 'rate', 'total', 'kharid_price', 'munafa'))
    ]
    if 'show_cart' not in st.session_state: st.session_state['show_cart'] = False

    st.markdown("""
    <style>
   .stTabs [data-baseweb="tab-list"] { gap: 5px; }
   .stTabs [data-baseweb="tab"] { height: auto; padding: 10px 15px; background: transparent; border-radius: 5px; }
   .stTabs [aria-selected="true"] { background: #e8f4f8; }
    </style>
    """, unsafe_allow_html=True)

    st.title("🛒 Afzal Store - Shop Management")
    ensure_items_schema()
    conn = get_db()

    CATEGORY_LIST = [
        "🌾 Rasan, Daalain & Noodles",
        "🛢️ Oil, Ghee & Masala Jaat",
        "🍅 Ketchup, Sauces & Spreads",
        "☕ Patti, Drinks & Tang",
        "🍬 Jelly & Biscuits",
        "🧼 Sabun, Shampoo & Hair Care",
        "🧴 Cosmetics & Powders",
        "🦷 Toothpaste & Oral Care",
        "👶 Baby Care & Diapers",
        "🌊 Surf, Cleaners & Maachis",
        "🦟 Insect Killer & Coils",
        "🛠️ Hardware, Glue & Cells",
        "🚬 Cigarette & Tobacco",
        "📦 Other Items"
    ]

    tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Dashboard", "➕ Add New", "📋 Items List", "💰 Quick Sale",
        "📈 Report", "📦 Stock", "⚙️ Settings"
    ])

    # ===== TAB 0: DASHBOARD =====
    with tab0:
        st.subheader("Items Dashboard")
        col1, col2 = st.columns([2, 1])
        with col1:
            search_dash = st.text_input("🔍 Search Item", placeholder="Type item name", key="dash_search")
        with col2:
            category_dash = st.selectbox("Category Filter", ["All"] + CATEGORY_LIST, key="dash_cat")

        query = "SELECT item_no, name, sale_price, base_unit, stock, category FROM items WHERE 1=1"
        params = []
        if search_dash:
            query += " AND (name LIKE? OR CAST(item_no AS TEXT) LIKE?)"
            params.extend([f"%{search_dash}%", f"%{search_dash}%"])
        if category_dash != "All":
            query += " AND category =?"
            params.append(category_dash)
        query += " ORDER BY item_no ASC"

        items_df = pd.read_sql(query, conn, params=params)
        if not items_df.empty:
            st.write(f"**Total Items: {len(items_df)}**")
            for idx, row in items_df.iterrows():
                stock_val = float(row['stock'] or 0)
                item_no_val = int(row['item_no']) if row['item_no'] is not None else "—"
                if stock_val <= 0:
                    stock_status = "🔴 Out"
                elif stock_val < 10:
                    stock_status = "🟡 Low"
                else:
                    stock_status = "🟢 OK"

                with st.container():
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**#{item_no_val}  {row['name']}**")
                        st.caption(f"Category: {row['category']} | Stock: {stock_val} {row['base_unit']}")
                    with col2:
                        st.write(f"**Rs. {row['sale_price']:.2f}**")
                        st.caption(stock_status)
                    st.divider()
        else:
            st.info("No items found")

    # ===== TAB 1: ADD NEW ITEM =====
    with tab1:
        st.subheader("Add New Item")

        # Color bar CSS for selectboxes and form sections
        st.markdown("""
        <style>
        /* Blue selectbox - Category */
        div[data-testid="stForm"] .row-widget.stSelectbox:nth-of-type(1) > div > div {
            border-left: 4px solid #1976d2 !important;
            border-radius: 4px;
        }
        /* Purple selectbox - Agency */
        div[data-testid="stForm"] .row-widget.stSelectbox:nth-of-type(2) > div > div {
            border-left: 4px solid #7b1fa2 !important;
            border-radius: 4px;
        }
        /* Green selectbox - Base Unit */
        div[data-testid="stForm"] .row-widget.stSelectbox:nth-of-type(3) > div > div {
            border-left: 4px solid #388e3c !important;
            border-radius: 4px;
        }
        /* Teal selectbox - Parent Item */
        div[data-testid="stForm"] .row-widget.stSelectbox:nth-of-type(4) > div > div {
            border-left: 4px solid #00796b !important;
            border-radius: 4px;
        }
        </style>
        """, unsafe_allow_html=True)

        with st.form("item_form", clear_on_submit=True):

            try:
                cursor = conn.execute("SELECT MAX(item_no) FROM items")
                last_no = cursor.fetchone()[0]
                suggested_no = 1 if last_no is None else last_no + 1

                cursor = conn.execute("SELECT item_no FROM items ORDER BY item_no")
                used_numbers = [row[0] for row in cursor.fetchall() if row[0] is not None]

                for i in range(1, suggested_no):
                    if i not in used_numbers:
                        suggested_no = i
                        break
            except:
                suggested_no = 1

            # ----- SECTION 1: Item Basic Info (Blue) -----
            st.markdown("""
<div style="border-left:5px solid #1976d2;background:#e3f2fd;padding:8px 14px;border-radius:5px;margin-bottom:10px">
<b style="color:#1976d2;">📋 Item Basic Info</b>
</div>""", unsafe_allow_html=True)

            col0, col1, col2 = st.columns([1, 2, 2])
            with col0:
                item_no = st.number_input(
                    "Item Number*",
                    min_value=1,
                    step=1,
                    format="%d",
                    value=suggested_no,
                    help=f"Suggested: {suggested_no}. Change kar sakte ho agar chaho"
                )
            with col1:
                name = st.text_input("Item Name*")
            with col2:
                category = st.selectbox("Category 🔵", CATEGORY_LIST)

            # ----- SECTION 2: Agency (Purple) -----
            st.markdown("""
<div style="border-left:5px solid #7b1fa2;background:#f3e5f5;padding:8px 14px;border-radius:5px;margin-bottom:10px;margin-top:6px">
<b style="color:#7b1fa2;">🏢 Agency / Supplier</b>
</div>""", unsafe_allow_html=True)

            try:
                temp_cursor = conn.cursor()
                temp_cursor.execute("SELECT DISTINCT name FROM agencies WHERE name IS NOT NULL AND name != ''")
                agencies_list = [row[0] for row in temp_cursor.fetchall()]
            except:
                agencies_list = []

            agencies_list = ["No Agency"] + agencies_list
            selected_agency = st.selectbox("Select Agency 🟣", options=agencies_list)

            # ----- SECTION 3: Pricing (Green) -----
            st.markdown("""
<div style="border-left:5px solid #388e3c;background:#e8f5e9;padding:8px 14px;border-radius:5px;margin-bottom:10px;margin-top:6px">
<b style="color:#388e3c;">💰 Pricing & Unit</b>
</div>""", unsafe_allow_html=True)

            col3, col4, col5 = st.columns(3)
            with col3:
                kharid_price = st.number_input("Purchase Price*", min_value=0.0, step=0.5, format="%.2f")
            with col4:
                sale_price = st.number_input("Sale Price*", min_value=0.0, step=0.5, format="%.2f")
            with col5:
                base_unit = st.selectbox("Base Unit* 🟢", ["Kg", "Gram", "Pcs", "Ltr", "Dozen", "Pack"])

            # ----- SECTION 4: Stock (Orange) -----
            st.markdown("""
<div style="border-left:5px solid #f57c00;background:#fff3e0;padding:8px 14px;border-radius:5px;margin-bottom:10px;margin-top:6px">
<b style="color:#f57c00;">📦 Stock Details</b>
</div>""", unsafe_allow_html=True)

            col6, col7, col8 = st.columns(3)
            with col6:
                stock = st.number_input("Stock Qty", min_value=0.0, step=0.1, format="%.2f", value=0.0)
            with col7:
                min_stock = st.number_input("Min Stock Alert", min_value=0, step=1, value=0)
            with col8:
                barcode = st.text_input("Barcode")

            # ----- SECTION 5: Extra Info (Red/Pink) -----
            st.markdown("""
<div style="border-left:5px solid #c62828;background:#ffebee;padding:8px 14px;border-radius:5px;margin-bottom:10px;margin-top:6px">
<b style="color:#c62828;">📅 Extra Info (Optional)</b>
</div>""", unsafe_allow_html=True)

            col9, col10 = st.columns(2)
            with col9:
                expiry_date = st.date_input("Expiry Date", value=None)
            with col10:
                photo_mode = st.radio("Item Photo", ["📤 Upload", "📷 Camera"], horizontal=True, key="item_photo_mode")
                if photo_mode == "📷 Camera":
                    photo = st.camera_input("Item Ki Photo Khinchein", key="item_photo_camera")
                else:
                    photo = st.file_uploader("Item Photo Upload Karein", type=['jpg', 'png', 'jpeg'], key="item_photo_upload")

            parent_items = pd.read_sql("SELECT id, name FROM items WHERE parent_id IS NULL OR parent_id = 0", conn)
            parent_list = ["None"] + parent_items['name'].tolist() if not parent_items.empty else ["None"]
            parent_select = st.selectbox("Parent Item (Variant) 🔵", parent_list)
            parent_id = None
            if parent_select != "None":
                parent_id = int(parent_items[parent_items['name'] == parent_select]['id'].iloc[0])

            # ----- SAVE BUTTON -----
            st.markdown("""
<div style="border-left:5px solid #1565c0;background:#e8eaf6;padding:8px 14px;border-radius:5px;margin-bottom:8px;margin-top:6px">
<b style="color:#1565c0;">💾 Item Save Karo</b>
</div>""", unsafe_allow_html=True)

            submit = st.form_submit_button("💾 Save Item", width='stretch', type="primary")

            if submit:
                if item_no and name and kharid_price > 0 and sale_price > 0:
                    name_check = name.strip().lower()
                    barcode_check = barcode.strip() if barcode else ""

                    cursor = conn.execute("SELECT id, name FROM items WHERE item_no =?", (item_no,))
                    duplicate_item_no = cursor.fetchone()

                    cursor = conn.execute("SELECT id, name FROM items WHERE LOWER(name) =?", (name_check,))
                    duplicate_name = cursor.fetchone()

                    duplicate_barcode = None
                    if barcode_check:
                        cursor = conn.execute("SELECT id, name FROM items WHERE barcode =? AND barcode != ''",
                                              (barcode_check,))
                        duplicate_barcode = cursor.fetchone()

                    if duplicate_item_no:
                        st.error(f"❌ Item Number {item_no} already used for '{duplicate_item_no[1]}'! Dusra number dein.")
                    elif duplicate_name:
                        st.error(f"❌ '{name}' already exists!")
                    elif duplicate_barcode:
                        st.error(f"❌ Barcode already used for '{duplicate_barcode[1]}'!")
                    else:
                        photo_path = ""
                        photo_thumb_path = ""
                        if photo:
                            os.makedirs("item_photos", exist_ok=True)
                            base_name = f"item_photos/{name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                            photo_path = f"{base_name}.jpg"
                            photo_thumb_path = f"{base_name}_thumb.jpg"
                            # 10,000-PHOTO SCALE FIX: pehle sirf ek ~500KB copy save hoti thi.
                            # Ab do chhoti copies banti hain - 'main' (~500x500, ~35KB, detail
                            # ke liye) aur 'thumb' (~120x120, ~8KB, list rows mein). List page
                            # ab sirf halki thumbnail load karta hai - 100 items ek page par
                            # bhi turant dikhte hain, aur Drive upload bhi chhota/tez hai.
                            with st.spinner("Photo compress ho rahi hai..."):
                                main_bytes, thumb_bytes, compress_msg = image_compression.compress_image_dual(photo)
                            if main_bytes:
                                with open(photo_path, "wb") as f:
                                    f.write(main_bytes)
                                if thumb_bytes:
                                    with open(photo_thumb_path, "wb") as f:
                                        f.write(thumb_bytes)
                                else:
                                    photo_thumb_path = ""
                                if compress_msg:
                                    st.caption(compress_msg)
                                try:
                                    import sync_manager
                                    sync_manager.upload_photo_to_drive_background(
                                        main_bytes, os.path.basename(photo_path))
                                    if thumb_bytes:
                                        sync_manager.upload_photo_to_drive_background(
                                            thumb_bytes, os.path.basename(photo_thumb_path))
                                except Exception:
                                    pass  # Drive na ho to koi masla nahi, local photo save ho chuki hai
                            else:
                                photo_path = ""
                                photo_thumb_path = ""
                                st.warning(compress_msg or "⚠️ Photo save nahi ho saki - item baaki detail ke sath save ho raha hai.")

                        expiry_str = expiry_date.strftime("%Y-%m-%d") if expiry_date else ""

                        conn.execute('''INSERT INTO items
                                     (item_no, name, category, kharid_price, sale_price, base_unit, stock, min_stock,
                                     barcode, expiry_date, photo, photo_thumb, parent_id, price, agency_name)
                                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                                     (item_no, name.strip(), category, kharid_price, sale_price, base_unit, stock,
                                      min_stock, barcode.strip(), expiry_str, photo_path, photo_thumb_path, parent_id, sale_price, selected_agency))

                        conn.commit()
                        cur = conn.execute("SELECT last_insert_rowid()")
                        item_id = cur.fetchone()[0]

                        conn.execute('''INSERT INTO stock_history
                                     (item_id, item_name, type, qty, unit, old_stock, new_stock, note, date, time)
                                     VALUES (?,?,?,?,?,?,?,?,?,?)''',
                                     (item_id, f"#{item_no}-{name.strip()}", 'IN', stock, base_unit, 0, stock,
                                      'New item added', datetime.now().strftime("%Y-%m-%d"),
                                      datetime.now().strftime("%H:%M:%S")))
                        conn.commit()
                        st.success(f"✅ Item #{item_no} - {name} saved successfully!")
                        st.balloons()
                        st.rerun()
                else:
                    st.error("Item Number, Name, Purchase Price and Sale Price are required!")

    # ===== TAB 2: ITEMS LIST =====
    with tab2:
        st.subheader("Items List - Edit/Delete/History")

        low_stock = pd.read_sql(
            "SELECT name, stock, min_stock, base_unit FROM items WHERE stock <= min_stock AND min_stock > 0", conn)
        thirty_days_later = (datetime.now() + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        expiry_items = pd.read_sql("SELECT name, expiry_date FROM items WHERE expiry_date != '' AND expiry_date <=?",
                                   conn, params=(thirty_days_later,))

        if not low_stock.empty or not expiry_items.empty:
            msg = f"*Afzal Store - Alert*\n\n"
            if not low_stock.empty:
                msg += f"*Low Stock Alert:*\n"
                for _, row in low_stock.iterrows():
                    msg += f"- {row['name']}: {row['stock']} {row['base_unit']} (Min: {row['min_stock']})\n"
            if not expiry_items.empty:
                msg += f"\n*Expiry Alert:*\n"
                for _, row in expiry_items.iterrows():
                    msg += f"- {row['name']}: {row['expiry_date']}\n"
            wa_url = f"https://wa.me/?text={urllib.parse.quote(msg)}"
            st.link_button("📱 Send WhatsApp Alert", wa_url, width='stretch')

        if not low_stock.empty:
            st.warning(f"⚠️ **Low Stock Alert**")
            for _, row in low_stock.iterrows():
                st.write(f"- **{row['name']}**: {row['stock']} {row['base_unit']} (Min: {row['min_stock']})")

        if not expiry_items.empty:
            st.error(f"🚨 **Expiry Alert**")
            for _, row in expiry_items.iterrows():
                # BUG FIX: malformed/legacy expiry_date values used to crash this whole tab.
                try:
                    exp_date = datetime.strptime(str(row['expiry_date']), "%Y-%m-%d").date()
                    days_left = (exp_date - datetime.now().date()).days
                    if days_left < 0:
                        st.write(f"- **{row['name']}**: Expired! ({row['expiry_date']})")
                    else:
                        st.write(f"- **{row['name']}**: {days_left} days left ({row['expiry_date']})")
                except (ValueError, TypeError):
                    st.write(f"- **{row['name']}**: {row['expiry_date']} (date format unclear)")

        col_search, col_filter = st.columns(2)
        with col_search:
            search = st.text_input("🔍 Search Item", placeholder="Name or barcode", key="list_search")
        with col_filter:
            category_filter = st.selectbox("Category Filter", ["All"] + CATEGORY_LIST, key="list_filter")

        query = "SELECT * FROM items WHERE 1=1"
        params = []
        if search:
            query += " AND (name LIKE? OR barcode LIKE? OR CAST(item_no AS TEXT) LIKE?)"
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        if category_filter != "All":
            query += " AND category =?"
            params.append(category_filter)
        query += " ORDER BY item_no ASC"

        # PERF FIX: pehle yeh SAARI matching items ek saath load hoti thin. Ab
        # sirf ek page (100 items) fetch hoti hai - bohot bade item list pe bhi tab tez rahega.
        try:
            count_df = pd.read_sql(f"SELECT COUNT(*) as cnt FROM ({query})", conn, params=params)
            total_items_count = int(count_df['cnt'][0]) if not count_df.empty else 0
        except Exception:
            total_items_count = 0

        items_per_page = 100
        total_pages_list = max(1, (total_items_count + items_per_page - 1) // items_per_page)
        if "items_list_page" not in st.session_state:
            st.session_state.items_list_page = 0
        list_filter_sig = f"{search}|{category_filter}"
        if st.session_state.get("items_list_filter_sig") != list_filter_sig:
            st.session_state.items_list_page = 0
            st.session_state.items_list_filter_sig = list_filter_sig
        st.session_state.items_list_page = min(st.session_state.items_list_page, total_pages_list - 1)

        try:
            df = pd.read_sql(query + " LIMIT ? OFFSET ?", conn,
                              params=params + [items_per_page, st.session_state.items_list_page * items_per_page])
        except Exception as e:
            st.error(f"⚠️ Items list load nahi ho saki: {e}")
            df = pd.DataFrame()

        if total_items_count > items_per_page:
            nav_col1, nav_col2, nav_col3 = st.columns([1, 1, 4])
            if nav_col1.button("⬅️ Pichla", key="items_list_prev", disabled=st.session_state.items_list_page <= 0):
                st.session_state.items_list_page -= 1
                st.rerun()
            if nav_col2.button("Agla ➡️", key="items_list_next", disabled=st.session_state.items_list_page >= total_pages_list - 1):
                st.session_state.items_list_page += 1
                st.rerun()
            nav_col3.caption(f"Page {st.session_state.items_list_page + 1} / {total_pages_list} ({total_items_count} items)")

        if not df.empty:
            for index, row in df.iterrows():
                base_unit_val = row.get('base_unit') or 'Pcs'
                kharid_val = float(row.get('kharid_price') or 0)
                sale_val = float(row.get('sale_price') or 0)
                stock_val = float(row.get('stock') or 0)
                photo_val = row.get('photo', '')
                # LAZY PHOTOS FIX (10k-photo scale): list rows ab sirf halki
                # 'thumb' (~8KB) load karte hain, bari 'main' photo (~35KB)
                # nahi - 100 rows ek page par bhi turant load hote hain.
                # Purane items jinke paas abhi thumb nahi hai (naye column se
                # pehle ke), unke liye 'photo' (main) hi fallback ke taur par
                # dikhaya jata hai.
                photo_thumb_val = row.get('photo_thumb') or photo_val
                category_val = row.get('category') or 'Other'
                parent_id = row.get('parent_id')
                item_no_val = int(row['item_no']) if row.get('item_no') is not None else "—"

                with st.container():
                    col1, col2, col3, col4, col5 = st.columns([0.5, 2.5, 2.5, 1, 1])
                    with col1:
                        if isinstance(photo_thumb_val, str) and photo_thumb_val.strip() != '' and os.path.exists(photo_thumb_val):
                            st.image(photo_thumb_val, width=50)
                        else:
                            st.markdown(f"<div style='text-align:center;font-size:11px;color:#888;font-weight:bold'>#{item_no_val}</div>", unsafe_allow_html=True)
                            st.write("📦")
                    with col2:
                        variant_text = " (Variant)" if parent_id else ""
                        st.write(f"**#{item_no_val}  {row['name']}{variant_text}**")
                        st.caption(f"{category_val} | Base: {base_unit_val}")
                        stock_color = "🔴" if stock_val <= 0 else "🟢"
                        st.caption(f"{stock_color} Stock: {stock_val} {base_unit_val}")
                    with col3:
                        st.write(f"Purchase: Rs. {kharid_val}/{base_unit_val}")
                        st.write(f"Sale: Rs. {sale_val}/{base_unit_val}")
                        munafa = sale_val - kharid_val
                        munafa_pct = (munafa / kharid_val * 100) if kharid_val > 0 else 0
                        st.caption(f"Profit: Rs. {munafa:.2f} | {munafa_pct:.1f}%")
                    with col4:
                        if st.button("📜 History", key=f"hist_{row['id']}", width='stretch'):
                            st.session_state[f'show_history_{row["id"]}'] = not st.session_state.get(
                                f'show_history_{row["id"]}', False)
                    with col5:
                        if st.button("✏️ Edit", key=f"edit_{row['id']}", width='stretch'):
                            st.session_state['edit_id'] = row['id']
                            st.session_state['show_edit_form'] = True
                            st.rerun()
                        if st.button("🗑️ Delete", key=f"del_{row['id']}", width='stretch'):
                            try:
                                conn.execute("DELETE FROM items WHERE id =?", (row['id'],))
                                conn.commit()
                                st.success("Deleted!")
                                st.rerun()
                            except sqlite3.Error as del_e:
                                st.error(f"❌ Delete nahi ho saka: {del_e}")

                    # STOCK HISTORY EXPANDER
                    if st.session_state.get(f'show_history_{row["id"]}', False):
                        with st.expander(f"📜 {row['name']} Ki Stock History", expanded=True):
                            # PERF FIX: latest 200 history entries - purani, saalon
                            # purani history ek saath load karne se yeh expander bohot
                            # dheema ho jata tha bade dataset mein.
                            try:
                                history = pd.read_sql(
                                    "SELECT * FROM stock_history WHERE item_id=? ORDER BY id DESC LIMIT 200",
                                    conn, params=(row['id'],))
                            except Exception as hist_e:
                                st.warning(f"⚠️ History load nahi ho saki: {hist_e}")
                                history = pd.DataFrame()
                            if not history.empty:
                                total_in = history[history['type'] == 'IN']['qty'].sum()
                                total_out = history[history['type'] == 'OUT']['qty'].sum()
                                col_i, col_o, col_bal = st.columns(3)
                                col_i.success(f"**✅ Total IN: {total_in:g} {row['base_unit']}**")
                                col_o.error(f"**❌ Total OUT: {total_out:g} {row['base_unit']}**")
                                col_bal.info(f"**📦 Balance: {total_in - total_out:g} {row['base_unit']}**")
                                st.divider()

                                for _, h in history.iterrows():
                                    note_str = str(h.get('note') or '')
                                    if 'Quick Sale' in note_str or 'Bill' in note_str:
                                        source = "💰 Quick Sale"
                                        bill_part = note_str.split('Bill:')[-1].strip() if 'Bill:' in note_str else ''
                                        customer_part = note_str.split('to')[-1].strip() if ' to ' in note_str else 'Cash Customer'
                                        detail = f"Bill: {bill_part} | Customer: {customer_part}" if bill_part else note_str
                                    elif 'Roll Nama' in note_str or 'Roz Ka' in note_str:
                                        source = "📋 Roz Ka Roll Nama"
                                        detail = "Deducted from daily roll"
                                    elif 'New item' in note_str or 'added' in note_str.lower():
                                        source = "➕ Item Add (Opening Stock)"
                                        detail = "Item first time add kiya gaya"
                                    elif 'Edit' in note_str or 'Updated' in note_str:
                                        source = "✏️ Item Edit"
                                        detail = "Stock/price manually update ki"
                                    elif 'Purchase' in note_str or 'Stock IN' in note_str:
                                        source = "📦 Stock Purchase"
                                        detail = note_str
                                    else:
                                        source = "🔄 Other"
                                        detail = note_str

                                    qty_val = float(h['qty'] or 0)
                                    old_s = float(h.get('old_stock') or 0)
                                    new_s = float(h.get('new_stock') or 0)

                                    if h['type'] == 'IN':
                                        st.markdown(f"""
<div style="background:#e8f5e9;border-left:4px solid #4caf50;padding:10px 14px;border-radius:6px;margin-bottom:8px">
<b>✅ STOCK IN</b> &nbsp;|&nbsp; 📅 {h['date']} &nbsp;⏰ {h['time']}<br>
<b>Item:</b> {h['item_name']} &nbsp;|&nbsp; <b>Qty:</b> +{qty_val:g} {h['unit']}<br>
<b>Source:</b> {source}<br>
<b>Detail:</b> {detail}<br>
<b>Stock:</b> {old_s:g} ➜ <b>{new_s:g} {h['unit']}</b>
</div>""", unsafe_allow_html=True)
                                    else:
                                        st.markdown(f"""
<div style="background:#ffebee;border-left:4px solid #f44336;padding:10px 14px;border-radius:6px;margin-bottom:8px">
<b>❌ STOCK OUT</b> &nbsp;|&nbsp; 📅 {h['date']} &nbsp;⏰ {h['time']}<br>
<b>Item:</b> {h['item_name']} &nbsp;|&nbsp; <b>Qty:</b> -{qty_val:g} {h['unit']}<br>
<b>Source:</b> {source}<br>
<b>Detail:</b> {detail}<br>
<b>Stock:</b> {old_s:g} ➜ <b>{new_s:g} {h['unit']}</b>
</div>""", unsafe_allow_html=True)
                            else:
                                st.info("Abhi tak koi stock movement nahi hua.")
                    st.divider()
        else:
            st.info("No items found")

    # ===== TAB 3: QUICK SALE =====
    with tab3:

        # --- Extra DB Tables for Quick Sale features ---
        conn.execute('''CREATE TABLE IF NOT EXISTS sales_bills
                     (id INTEGER PRIMARY KEY, bill_no TEXT, customer_id INTEGER, customer_name TEXT,
                     date TEXT, time TEXT, subtotal REAL, discount REAL, final_total REAL,
                     paid_amount REAL, balance REAL, type TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS sales_bill_items
                     (id INTEGER PRIMARY KEY, bill_id INTEGER, item_id INTEGER, item_name TEXT,
                     qty REAL, unit TEXT, rate REAL, total REAL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS udhaar
                     (id INTEGER PRIMARY KEY, customer_id INTEGER, customer_name TEXT, date TEXT,
                     type TEXT, amount REAL, item TEXT, qty REAL, rate REAL,
                     detail TEXT, time TEXT, unit TEXT)''')
        conn.commit()

        # Session state
        for _k, _v in [('last_bill_no', None), ('last_bill_wa', ''), ('return_mode', False)]:
            if _k not in st.session_state:
                st.session_state[_k] = _v

        qs_tab1, qs_tab2, qs_tab3, qs_tab4 = st.tabs([
            "🛒 New Sale", "📋 Bill History", "👤 Customer Ledger", "📊 Item Report"])

        # ============ NEW SALE ============
        with qs_tab1:
            st.subheader("Quick Sale")

            # WhatsApp share banner after successful save
            if st.session_state.get('last_bill_wa'):
                st.success(f"✅ Bill Save Hua! Bill No: {st.session_state['last_bill_no']}")
                wa_col, dis_col = st.columns([3, 1])
                with wa_col:
                    st.link_button("📱 WhatsApp Par Share Karo", st.session_state['last_bill_wa'], width='stretch')
                with dis_col:
                    if st.button("✖ Dismiss", key="dismiss_wa"):
                        st.session_state['last_bill_wa'] = ''
                        st.session_state['last_bill_no'] = None
                        st.rerun()
                st.divider()

            # --- 1. BARCODE SCANNER ---
            st.markdown("""
<div style="border-left:5px solid #f57c00;background:#fff3e0;padding:7px 13px;border-radius:5px;margin-bottom:8px">
<b style="color:#f57c00;">📷 Barcode Scanner — Auto Cart Add</b>
</div>""", unsafe_allow_html=True)
            barcode_scan = st.text_input("Barcode scan karo",
                                          placeholder="Barcode scan karo — item automatically cart mein jaega",
                                          key="barcode_scanner", label_visibility="collapsed")
            # Only process when value is new (avoid infinite rerun loop)
            if barcode_scan and barcode_scan != st.session_state.get('_last_barcode', ''):
                st.session_state['_last_barcode'] = barcode_scan
                bc_row = pd.read_sql("SELECT * FROM items WHERE barcode = ? LIMIT 1",
                                      conn, params=(barcode_scan.strip(),))
                if not bc_row.empty:
                    bc = bc_row.iloc[0]
                    bc_id = int(bc['id'])
                    bc_unit = str(bc.get('base_unit') or 'Pcs')
                    bc_found = False
                    for _ci in st.session_state['cart']:
                        if _ci['item_id'] == bc_id and _ci['unit'] == bc_unit:
                            _ci['qty'] += 1.0
                            _ci['total'] = _ci['qty'] * _ci['rate']
                            _ci['munafa'] = (_ci['rate'] - float(bc.get('kharid_price') or 0)) * _ci['qty']
                            bc_found = True
                            break
                    if not bc_found:
                        st.session_state['cart'].append({
                            'item_id': bc_id, 'name': bc['name'], 'qty': 1.0,
                            'unit': bc_unit, 'rate': float(bc.get('sale_price') or 0),
                            'total': float(bc.get('sale_price') or 0),
                            'kharid_price': float(bc.get('kharid_price') or 0),
                            'munafa': float(bc.get('sale_price') or 0) - float(bc.get('kharid_price') or 0)
                        })
                    st.success(f"✅ {bc['name']} cart mein add hua (barcode se)!")
                    st.rerun()
                else:
                    st.warning("❌ Is barcode ka koi item nahi mila")

            # --- 2. ITEM SEARCH (live dropdown with price) ---
            st.markdown("""
<div style="border-left:5px solid #1976d2;background:#e3f2fd;padding:7px 13px;border-radius:5px;margin-bottom:8px;margin-top:8px">
<b style="color:#1976d2;">🔍 Item Search & Add</b>
</div>""", unsafe_allow_html=True)

            srch_col, ret_col = st.columns([3, 1])
            with srch_col:
                item_search = st.text_input("Item dhundo",
                                             placeholder="Naam, barcode ya number likhein",
                                             key="sale_search", label_visibility="collapsed")
            with ret_col:
                return_mode = st.toggle("↩ Return", value=st.session_state.get('return_mode', False),
                                         key="return_toggle")
                st.session_state['return_mode'] = return_mode

            fi = None  # selected item row
            if item_search:
                # FIX 1+4: Live dropdown — search by name prefix, barcode, or item_no
                live_rows = conn.execute(
                    """SELECT id, item_no, name,
                       COALESCE(sale_price, price, default_rate, 0) as rate,
                       base_unit, stock
                       FROM items
                       WHERE name LIKE ? OR barcode = ? OR CAST(item_no AS TEXT) = ?
                       ORDER BY name LIMIT 20""",
                    (f"{item_search}%", item_search, item_search.strip())
                ).fetchall()

                # also try contains-match if prefix gave nothing
                if not live_rows:
                    live_rows = conn.execute(
                        """SELECT id, item_no, name,
                           COALESCE(sale_price, price, default_rate, 0) as rate,
                           base_unit, stock
                           FROM items
                           WHERE name LIKE ? OR barcode = ? OR CAST(item_no AS TEXT) = ?
                           ORDER BY name LIMIT 20""",
                        (f"%{item_search}%", item_search, item_search.strip())
                    ).fetchall()

                if live_rows:
                    # FIX 4: Format "Name - Rs.X/Unit - Stock: Y"
                    opts = [
                        f"{r[2]} - Rs.{r[3]:.0f}/{r[4] or 'Pcs'} - Stock: {r[5] or 0}"
                        for r in live_rows
                    ]
                    selected_opt = st.selectbox("Item chuno", opts, key="sale_dropdown",
                                                 label_visibility="collapsed")
                    # find the matching row
                    sel_idx = opts.index(selected_opt)
                    sel_row = live_rows[sel_idx]
                    fi = {
                        'id': sel_row[0], 'item_no': sel_row[1], 'name': sel_row[2],
                        'rate': float(sel_row[3]), 'base_unit': sel_row[4] or 'Pcs',
                        'stock': float(sel_row[5] or 0),
                        'kharid_price': float(conn.execute(
                            "SELECT COALESCE(kharid_price,0) FROM items WHERE id=?",
                            (sel_row[0],)).fetchone()[0])
                    }
                else:
                    st.warning("❌ Item nahi mila")

            if fi:
                fi_id   = int(fi['id'])
                fi_no   = fi['item_no'] if fi['item_no'] else "—"
                fi_unit = str(fi['base_unit'])
                fi_stk  = fi['stock']

                # FIX 2: rate from COALESCE already in fi['rate']
                if return_mode:
                    st.warning(f"↩ **Return Mode:** #{fi_no} {fi['name']} | Stock: {fi_stk} {fi_unit}")
                else:
                    if fi_stk <= 0:
                        st.warning(f"⚠️ **Out of Stock:** {fi['name']}")
                    else:
                        st.success(f"✅ **Found:** #{fi_no} {fi['name']} | Stock: {fi_stk} {fi_unit} | Rs.{fi['rate']:.2f}")

                fc1, fc2, fc3 = st.columns(3)
                with fc1:
                    if return_mode:
                        qty_min = -fi_stk if fi_stk > 0 else -999999.0
                        qty_def = max(-1.0, qty_min)   # default must satisfy min_value
                    else:
                        qty_min = 0.01
                        qty_def = 1.0
                    qty = st.number_input(f"Qty ({fi_unit})", min_value=qty_min,
                                           value=qty_def, step=0.1, key="sale_qty")
                with fc2:
                    # FIX 2: default rate from COALESCE
                    rate = st.number_input("Rate", value=fi['rate'],
                                           min_value=0.0, step=0.5, key="sale_rate")
                with fc3:
                    st.metric("Total", f"Rs. {qty * rate:.2f}")

                add_label = "↩ Return Add Karo" if return_mode else "➕ Cart Mein Dalo"
                if st.button(add_label, type="primary", width='stretch'):
                    merged = False
                    for _ci in st.session_state['cart']:
                        if _ci['item_id'] == fi_id and _ci['unit'] == fi_unit:
                            _ci['qty'] += qty
                            _ci['total'] = _ci['qty'] * _ci['rate']
                            _ci['munafa'] = (_ci['rate'] - fi['kharid_price']) * _ci['qty']
                            merged = True
                            break
                    if not merged:
                        st.session_state['cart'].append({
                            'item_id': fi_id, 'name': fi['name'], 'qty': qty,
                            'unit': fi_unit, 'rate': rate, 'total': qty * rate,
                            'kharid_price': fi['kharid_price'],
                            'munafa': (rate - fi['kharid_price']) * qty
                        })
                    st.success(f"✅ {fi['name']} {'return' if return_mode else 'cart'} mein add hua!")
                    st.rerun()

            # --- 3. CART (with live edit) ---
            if st.session_state['cart']:
                st.markdown("""
<div style="border-left:5px solid #388e3c;background:#e8f5e9;padding:7px 13px;border-radius:5px;margin-bottom:8px;margin-top:10px">
<b style="color:#388e3c;">🛒 Cart</b>
</div>""", unsafe_allow_html=True)

                for idx, cart_item in enumerate(st.session_state['cart']):
                    is_return = cart_item['qty'] < 0
                    row_bg = "#fce4ec" if is_return else "#fff8e1"
                    row_bd = "#e91e63" if is_return else "#fbc02d"
                    st.markdown(f"""
<div style="background:{row_bg};border-left:4px solid {row_bd};padding:5px 12px;border-radius:5px;margin-bottom:2px">
<b>{'↩ RETURN: ' if is_return else ''}{cart_item['name']}</b> &nbsp;<small>({cart_item['unit']})</small>
</div>""", unsafe_allow_html=True)

                    cc1, cc2, cc3, cc4 = st.columns([2, 2, 2, 1])
                    with cc1:
                        new_qty = st.number_input("Qty", value=float(cart_item['qty']),
                                                   step=0.1, key=f"cq_{idx}", label_visibility="collapsed")
                        if new_qty != cart_item['qty']:
                            st.session_state['cart'][idx]['qty'] = new_qty
                            st.session_state['cart'][idx]['total'] = new_qty * cart_item['rate']
                            st.session_state['cart'][idx]['munafa'] = (cart_item['rate'] - cart_item['kharid_price']) * new_qty
                            st.rerun()
                    with cc2:
                        new_rate = st.number_input("Rate", value=float(cart_item['rate']),
                                                    min_value=0.0, step=0.5, key=f"cr_{idx}",
                                                    label_visibility="collapsed")
                        if new_rate != cart_item['rate']:
                            st.session_state['cart'][idx]['rate'] = new_rate
                            st.session_state['cart'][idx]['total'] = cart_item['qty'] * new_rate
                            st.session_state['cart'][idx]['munafa'] = (new_rate - cart_item['kharid_price']) * cart_item['qty']
                            conn.execute("UPDATE items SET sale_price=?, price=? WHERE id=?",
                                          (new_rate, new_rate, cart_item['item_id']))
                            conn.commit()
                            st.rerun()
                    with cc3:
                        row_total = st.session_state['cart'][idx]['total']
                        st.write(f"**Rs. {row_total:.2f}**")
                    with cc4:
                        if st.button("🗑", key=f"del_cart_{idx}"):
                            st.session_state['cart'].pop(idx)
                            st.rerun()

                # FIX 5: Recalculate total cleanly from cart (returns with -qty auto-subtract)
                total_bill = sum(ci['qty'] * ci['rate'] for ci in st.session_state['cart'])
                total_munafa = sum(ci.get('munafa', 0) for ci in st.session_state['cart'])

                # --- 4. DISCOUNT ---
                st.markdown("""
<div style="border-left:5px solid #7b1fa2;background:#f3e5f5;padding:7px 13px;border-radius:5px;margin-bottom:8px;margin-top:8px">
<b style="color:#7b1fa2;">🏷️ Discount & Payment</b>
</div>""", unsafe_allow_html=True)

                disc_c1, disc_c2, disc_c3 = st.columns(3)
                with disc_c1:
                    discount_type = st.selectbox("Discount Qisam",
                                                  ["None", "Percentage %", "Flat Amount"],
                                                  key="disc_type")
                with disc_c2:
                    if discount_type != "None":
                        disc_val = st.number_input("Discount Value", min_value=0.0,
                                                    step=1.0, key="disc_val")
                    else:
                        disc_val = 0.0
                        st.write("")
                with disc_c3:
                    if discount_type == "Percentage %":
                        discount_amt = total_bill * disc_val / 100
                    elif discount_type == "Flat Amount":
                        discount_amt = min(disc_val, total_bill)
                    else:
                        discount_amt = 0.0
                    final_total = total_bill - discount_amt
                    if discount_amt > 0:
                        st.metric("After Discount", f"Rs. {final_total:.2f}",
                                   delta=f"-{discount_amt:.2f}")
                    else:
                        st.metric("Total", f"Rs. {final_total:.2f}")

                # FIX 3: Hide Munafa — only show Subtotal (munafa only in Report tab)
                st.metric("Subtotal", f"Rs. {total_bill:.2f}")

                # --- 5. SALE TYPE ---
                sale_type = st.radio("Sale Type", ["💵 Cash", "📝 Udhaar"],
                                      horizontal=True, key="qs_sale_type")
                customer_id = None
                customer_name = "Cash Customer"
                customer_ok = True
                paid_amount = final_total
                balance = 0.0

                if sale_type == "📝 Udhaar":
                    try:
                        qs_custs = pd.read_sql(
                            "SELECT id, name FROM customers WHERE type='customer' OR status='Active'", conn)
                        if not qs_custs.empty:
                            cust_dict_qs = dict(zip(qs_custs['name'], qs_custs['id']))
                            customer_name = st.selectbox("Customer Chuno",
                                                          list(cust_dict_qs.keys()), key="qs_cust")
                            customer_id = cust_dict_qs[customer_name]
                            paid_amount = st.number_input("Paid Amount (Rs.)", min_value=0.0,
                                                           value=float(final_total), step=10.0, key="qs_paid")
                            balance = final_total - paid_amount
                            if balance > 0:
                                st.error(f"💳 Baqi (Udhaar): Rs. {balance:.2f}")
                            else:
                                st.success("✅ Full Payment Ho Gaya")
                        else:
                            st.warning("⚠️ Settings mein pehle customer add karo")
                            customer_ok = False
                    except:
                        st.warning("⚠️ Customer table nahi mili")
                        customer_ok = False

                btn_c1, btn_c2, btn_c3 = st.columns(3)
                with btn_c1:
                    if st.button("✅ Bill Save Karo", type="primary", width='stretch',
                                  disabled=not customer_ok):
                        bill_no = generate_bill_no()
                        today_date = datetime.now().strftime("%Y-%m-%d")
                        today_time = datetime.now().strftime("%H:%M:%S")
                        sale_type_str = 'Cash' if sale_type == "💵 Cash" else 'Udhaar'

                        # a) sales_bills master record
                        c_ins = conn.execute(
                            '''INSERT INTO sales_bills
                               (bill_no, customer_id, customer_name, date, time,
                               subtotal, discount, final_total, paid_amount, balance, type)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                            (bill_no, customer_id, customer_name, today_date, today_time,
                             total_bill, discount_amt, final_total, paid_amount, balance, sale_type_str))
                        bill_id = c_ins.lastrowid
                        conn.commit()

                        wa_lines = [f"*Afzal Store - Bill*", f"Bill: {bill_no}",
                                    f"Date: {today_date}", f"Customer: {customer_name}",
                                    "─────────────────"]

                        has_return = any(ci['qty'] < 0 for ci in st.session_state['cart'])

                        for cart_item in st.session_state['cart']:
                            # b) sales_bill_items
                            conn.execute(
                                '''INSERT INTO sales_bill_items
                                   (bill_id, item_id, item_name, qty, unit, rate, total)
                                   VALUES (?,?,?,?,?,?,?)''',
                                (bill_id, cart_item['item_id'], cart_item['name'],
                                 cart_item['qty'], cart_item['unit'],
                                 cart_item['rate'], cart_item['total']))

                            # c) legacy sales table (backward compat)
                            conn.execute(
                                '''INSERT INTO sales
                                   (bill_no, item_id, item_name, qty, unit, rate, total, munafa,
                                   sale_type, customer_id, customer_name, date, time)
                                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                                (bill_no, cart_item['item_id'], cart_item['name'],
                                 cart_item['qty'], cart_item['unit'], cart_item['rate'],
                                 cart_item['total'], cart_item['munafa'],
                                 sale_type_str, customer_id, customer_name, today_date, today_time))

                            # d) stock update (return qty is negative → stock goes up)
                            old_stk_row = pd.read_sql("SELECT stock FROM items WHERE id=?",
                                                       conn, params=(cart_item['item_id'],))
                            old_stk = float(old_stk_row.iloc[0]['stock']) if not old_stk_row.empty else 0.0
                            new_stk = old_stk - cart_item['qty']
                            conn.execute("UPDATE items SET stock=? WHERE id=?",
                                          (new_stk, cart_item['item_id']))

                            # e) stock_history
                            h_type = 'IN' if cart_item['qty'] < 0 else 'OUT'
                            h_note = (f"Return - Bill: {bill_no}" if cart_item['qty'] < 0
                                      else f"Quick Sale - Bill: {bill_no} to {customer_name}")
                            conn.execute(
                                '''INSERT INTO stock_history
                                   (item_id, item_name, type, qty, unit, old_stock, new_stock, note, date, time)
                                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                                (cart_item['item_id'], cart_item['name'], h_type,
                                 abs(cart_item['qty']), cart_item['unit'],
                                 old_stk, new_stk, h_note, today_date, today_time))

                            sign = "↩" if cart_item['qty'] < 0 else ""
                            wa_lines.append(
                                f"{sign}{cart_item['name']}: {cart_item['qty']:g} {cart_item['unit']}"
                                f" x Rs.{cart_item['rate']:.0f} = Rs.{cart_item['total']:.0f}")

                        # f) udhaar ledger
                        udhaar_type_str = ('return' if has_return
                                           else ('udhaar' if balance > 0 else 'cash'))
                        udhaar_amt = -final_total if has_return else final_total
                        conn.execute(
                            '''INSERT INTO udhaar
                               (customer_id, customer_name, date, type, amount, detail, time)
                               VALUES (?,?,?,?,?,?,?)''',
                            (customer_id, customer_name, today_date, udhaar_type_str,
                             udhaar_amt, f"Bill: {bill_no}", today_time))
                        conn.commit()

                        wa_lines += ["─────────────────",
                                     f"Subtotal: Rs.{total_bill:.0f}",
                                     f"Discount: Rs.{discount_amt:.0f}",
                                     f"*Total: Rs.{final_total:.0f}*",
                                     f"Paid: Rs.{paid_amount:.0f}",
                                     f"Balance: Rs.{balance:.0f}",
                                     "\nShukriya! — Afzal Store"]
                        wa_msg = "\n".join(wa_lines)
                        wa_url = f"https://wa.me/?text={urllib.parse.quote(wa_msg)}"

                        st.session_state['last_bill_no'] = bill_no
                        st.session_state['last_bill_wa'] = wa_url
                        st.session_state['cart'] = []
                        st.session_state['return_mode'] = False
                        st.balloons()
                        st.rerun()

                with btn_c2:
                    # FIX 6: Bill Print button
                    if st.button("🖨️ Bill Print Karo", width='stretch'):
                        pr_items_html = "".join([
                            f"<tr><td>{ci['name']}</td>"
                            f"<td style='text-align:right'>{ci['qty']:g} {ci['unit']}</td>"
                            f"<td style='text-align:right'>Rs.{ci['rate']:.0f}</td>"
                            f"<td style='text-align:right'>Rs.{ci['qty']*ci['rate']:.0f}</td></tr>"
                            for ci in st.session_state['cart']])
                        pr_subtotal = sum(ci['qty'] * ci['rate'] for ci in st.session_state['cart'])
                        try:
                            pr_disc = discount_amt
                            pr_final = final_total
                        except NameError:
                            pr_disc = 0
                            pr_final = pr_subtotal
                        pr_html = (
                            f"<div style='width:300px;font-family:Arial;font-size:13px'>"
                            f"<h3 style='text-align:center;margin:4px'>Afzal Store</h3>"
                            f"<p style='text-align:center;margin:2px'>Date: {datetime.now().strftime('%d-%m-%Y %I:%M %p')}</p>"
                            f"<hr>"
                            f"<table style='width:100%;font-size:12px'>"
                            f"<tr><th>Item</th><th>Qty</th><th>Rate</th><th>Total</th></tr>"
                            f"{pr_items_html}</table><hr>"
                            f"<p style='margin:3px'>Subtotal: Rs.{pr_subtotal:.0f}</p>"
                            f"<p style='margin:3px'>Discount: Rs.{pr_disc:.0f}</p>"
                            f"<h4 style='margin:4px'>Total: Rs.{pr_final:.0f}</h4>"
                            f"</div><script>window.print();</script>")
                        st.components.v1.html(pr_html, height=0)

                with btn_c3:
                    if st.button("🗑️ Cart Clear", width='stretch'):
                        st.session_state['cart'] = []
                        st.rerun()

        # ============ BILL HISTORY ============
        with qs_tab2:
            st.subheader("📋 Bill History")
            bh_c1, bh_c2 = st.columns(2)
            with bh_c1:
                bh_date = st.date_input("Date Filter", value=None, key="bh_date")
            with bh_c2:
                bh_cust_srch = st.text_input("Customer Search", placeholder="Customer name", key="bh_cust")

            bh_q = "SELECT * FROM sales_bills WHERE 1=1"
            bh_p = []
            if bh_date:
                bh_q += " AND date = ?"
                bh_p.append(str(bh_date))
            if bh_cust_srch:
                bh_q += " AND customer_name LIKE ?"
                bh_p.append(f"%{bh_cust_srch}%")
            bh_q += " ORDER BY id DESC LIMIT 50"

            try:
                bills_df = pd.read_sql(bh_q, conn, params=bh_p)
            except:
                bills_df = pd.DataFrame()

            if not bills_df.empty:
                st.info(f"**{len(bills_df)} Bills | Total: Rs. {bills_df['final_total'].sum():,.0f}**")
                st.divider()
                for _, bill in bills_df.iterrows():
                    b_bg = "#e8f5e9" if bill['type'] == 'Cash' else "#fff3e0"
                    b_bd = "#43a047" if bill['type'] == 'Cash' else "#fb8c00"
                    baqi = float(bill.get('balance') or 0)
                    baqi_txt = f"&nbsp;|&nbsp; 💳 Baqi: Rs.{baqi:.0f}" if baqi > 0 else ""
                    st.markdown(f"""
<div style="background:{b_bg};border-left:4px solid {b_bd};padding:8px 14px;border-radius:6px;margin-bottom:5px">
<b>🧾 {bill['bill_no']}</b> &nbsp;|&nbsp; 📅 {bill['date']} &nbsp;⏰ {bill['time']}<br>
👤 {bill['customer_name']} &nbsp;|&nbsp; 💰 Rs.{float(bill['final_total']):.0f}
&nbsp;|&nbsp; {'💵 Cash' if bill['type']=='Cash' else '📝 Udhaar'}{baqi_txt}
</div>""", unsafe_allow_html=True)
                    if st.button(f"🖨️ Reprint", key=f"rp_{bill['id']}"):
                        try:
                            bi_df = pd.read_sql("SELECT * FROM sales_bill_items WHERE bill_id=?",
                                                 conn, params=(int(bill['id']),))
                            rows_html = "".join([
                                f"<tr><td>{r['item_name']}</td>"
                                f"<td style='text-align:right'>{r['qty']:g} {r['unit']}</td>"
                                f"<td style='text-align:right'>Rs.{r['rate']:.0f}</td>"
                                f"<td style='text-align:right'>Rs.{r['total']:.0f}</td></tr>"
                                for _, r in bi_df.iterrows()])
                            print_html = (
                                f"<html><body style='width:300px;font-family:monospace;font-size:12px'>"
                                f"<h3 style='text-align:center'>Afzal Store</h3>"
                                f"<p style='text-align:center'>Bill: {bill['bill_no']}<br>"
                                f"{bill['date']} {bill['time']}<br>Customer: {bill['customer_name']}</p><hr>"
                                f"<table width='100%'><tr><th>Item</th><th>Qty</th><th>Rate</th><th>Total</th></tr>"
                                f"{rows_html}</table><hr>"
                                f"<p>Subtotal: Rs.{float(bill['subtotal']):.0f}<br>"
                                f"Discount: Rs.{float(bill['discount']):.0f}<br>"
                                f"<b>Total: Rs.{float(bill['final_total']):.0f}</b><br>"
                                f"Paid: Rs.{float(bill['paid_amount']):.0f}<br>"
                                f"Balance: Rs.{float(bill['balance']):.0f}</p>"
                                f"<p style='text-align:center'>-- Shukriya --</p></body></html>")
                            st.components.v1.html(
                                f"<script>var w=window.open('','_blank','width=340,height=600');"
                                f"w.document.write(`{print_html}`);"
                                f"w.document.close();w.print();</script>", height=0)
                        except Exception as rp_e:
                            st.error(f"Reprint error: {rp_e}")
            else:
                st.info("Koi bill nahi mila")

        # ============ CUSTOMER LEDGER ============
        with qs_tab3:
            st.subheader("👤 Customer Ledger")
            try:
                all_custs = pd.read_sql(
                    "SELECT id, name FROM customers WHERE type='customer' OR status='Active'", conn)
                if not all_custs.empty:
                    cust_map = dict(zip(all_custs['name'], all_custs['id']))
                    sel_cust = st.selectbox("Customer Chuno", list(cust_map.keys()), key="ledger_cust")
                    sel_cust_id = cust_map[sel_cust]

                    # PERF FIX: latest 500 ledger entries - poori history load karna
                    # purane customers ke liye is tab ko dheema kar deta tha.
                    ud_df = pd.read_sql(
                        "SELECT date, type, amount, detail, time FROM udhaar "
                        "WHERE customer_id=? ORDER BY id DESC LIMIT 500",
                        conn, params=(sel_cust_id,))

                    if not ud_df.empty:
                        tot_sale = ud_df[ud_df['type'].isin(['udhaar','cash'])]['amount'].sum()
                        tot_ret  = abs(ud_df[ud_df['type']=='return']['amount'].sum())
                        tot_pay  = ud_df[ud_df['type']=='payment']['amount'].sum()
                        net_bal  = tot_sale - tot_ret - tot_pay

                        l1, l2, l3 = st.columns(3)
                        l1.metric("Kul Khareedari", f"Rs. {tot_sale:,.0f}")
                        l2.metric("Returns", f"Rs. {tot_ret:,.0f}")
                        l3.metric("💳 Baqi Balance", f"Rs. {net_bal:,.0f}")
                        st.divider()

                        for _, ud in ud_df.iterrows():
                            ut = str(ud['type'])
                            if ut in ('udhaar', 'cash'):
                                ud_bg, ud_bd, ud_ico = "#fff3e0", "#fb8c00", "🛒"
                            elif ut == 'payment':
                                ud_bg, ud_bd, ud_ico = "#e8f5e9", "#43a047", "💵"
                            elif ut == 'return':
                                ud_bg, ud_bd, ud_ico = "#fce4ec", "#e91e63", "↩"
                            else:
                                ud_bg, ud_bd, ud_ico = "#f5f5f5", "#9e9e9e", "📋"
                            st.markdown(f"""
<div style="background:{ud_bg};border-left:4px solid {ud_bd};padding:8px 14px;border-radius:6px;margin-bottom:5px">
<b>{ud_ico} {ut.upper()}</b> &nbsp;|&nbsp; 📅 {ud['date']} &nbsp;⏰ {ud.get('time','')} <br>
💰 Rs.{float(ud['amount']):.0f} &nbsp;|&nbsp; 📝 {ud.get('detail','—')}
</div>""", unsafe_allow_html=True)
                    else:
                        st.info(f"{sel_cust} ka koi ledger record nahi mila")
                else:
                    st.info("Koi customer nahi mila. Settings mein add karo.")
            except Exception as led_e:
                st.error(f"Ledger error: {led_e}")

        # ============ ITEM SALES REPORT ============
        with qs_tab4:
            st.subheader("📊 Item Sales Report")
            ir_c1, ir_c2 = st.columns(2)
            with ir_c1:
                ir_from = st.date_input("From Date", value=date.today().replace(day=1), key="ir_from")
            with ir_c2:
                ir_to = st.date_input("To Date", value=date.today(), key="ir_to")

            try:
                item_rpt = pd.read_sql(
                    """SELECT sbi.item_name AS Item,
                        SUM(sbi.qty)   AS Total_Qty,
                        SUM(sbi.total) AS Total_Amount,
                        AVG(sbi.rate)  AS Avg_Rate
                    FROM sales_bill_items sbi
                    JOIN sales_bills sb ON sbi.bill_id = sb.id
                    WHERE sb.date BETWEEN ? AND ?
                    GROUP BY sbi.item_name
                    ORDER BY Total_Amount DESC""", conn, params=(str(ir_from), str(ir_to)))

                if not item_rpt.empty:
                    ir1, ir2, ir3 = st.columns(3)
                    ir1.metric("Item Types", str(len(item_rpt)))
                    ir2.metric("Kul Qty", f"{item_rpt['Total_Qty'].sum():.1f}")
                    ir3.metric("Kul Revenue", f"Rs. {item_rpt['Total_Amount'].sum():,.0f}")
                    st.divider()
                    for _, ir_row in item_rpt.iterrows():
                        st.markdown(f"""
<div style="background:#e3f2fd;border-left:4px solid #1976d2;padding:8px 14px;border-radius:6px;margin-bottom:5px">
<b>📦 {ir_row['Item']}</b><br>
Qty: {ir_row['Total_Qty']:g} &nbsp;|&nbsp; Avg Rate: Rs.{ir_row['Avg_Rate']:.0f}
&nbsp;|&nbsp; <b>Total: Rs.{ir_row['Total_Amount']:,.0f}</b>
</div>""", unsafe_allow_html=True)
                else:
                    st.info("Is period mein koi sale nahi mili")
            except Exception as rpt_e:
                st.error(f"Report error: {rpt_e}")

    # ===== TAB 4: DAILY REPORT =====
    with tab4:
        st.subheader("Daily Report")
        conn = get_db()
        report_date = st.date_input("Date Select Karo", datetime.now(), key="daily_report_date")

        try:
            today_data = pd.read_sql("""
                SELECT 'Cash' as Sale_Type, s.bill_no as Bill_No, i.name as Item, i.category as Category,
                s.qty as Qty, i.sale_price as Rate, s.total as Amount, s.date as Time, s.sale_type as Payment_Type
                FROM sales s JOIN items i ON s.item_id = i.id WHERE DATE(s.date) = ?
                UNION ALL
                SELECT 'Udhaar' as Sale_Type, 'U-' || sh.id as Bill_No, i.name as Item, i.category as Category,
                sh.qty as Qty, i.sale_price as Rate, (sh.qty * i.sale_price) as Amount, sh.date as Time, 'Udhaar' as Payment_Type
                FROM stock_history sh JOIN items i ON sh.item_name = i.name
                WHERE sh.type = 'sale' AND DATE(sh.date) = ?
                ORDER BY Time DESC
            """, conn, params=(str(report_date), str(report_date)))
        except Exception as dr_e:
            st.error(f"⚠️ Daily report load nahi ho saka: {dr_e}")
            today_data = pd.DataFrame()

        if not today_data.empty:
            today_data['Qty'] = today_data['Qty'].round(2)
            today_data['Rate'] = today_data['Rate'].astype(int)
            today_data['Amount'] = today_data['Amount'].astype(int)

            col1, col2, col3, col4 = st.columns(4)
            total_sale = today_data['Amount'].sum()
            cash_sale = today_data[today_data['Sale_Type'] == 'Cash']['Amount'].sum()
            udhaar_sale = today_data[today_data['Sale_Type'] == 'Udhaar']['Amount'].sum()
            total_items = today_data['Qty'].sum()

            with col1:
                st.metric("Total Sale", f"Rs. {total_sale:,.0f}")
            with col2:
                st.metric("Cash Sale", f"Rs. {cash_sale:,.0f}")
            with col3:
                st.metric("Udhaar Sale", f"Rs. {udhaar_sale:,.0f}")
            with col4:
                st.metric("Items Sold", f"{total_items:,.0f}")

            st.divider()
            st.subheader("Today's Bills")

            def color_sale_type(val):
                if val == 'Udhaar':
                    return 'background-color: #FFE5E5'
                else:
                    return 'background-color: #E5FFE5'

            st.dataframe(
                today_data.style.map(color_sale_type, subset=['Sale_Type']),
                width='stretch', hide_index=True
            )

            top_items = today_data.groupby('Item')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
            if not top_items.empty:
                st.success(f"**Sabse Zyada Bika:** {top_items.iloc[0]['Item']} - {top_items.iloc[0]['Qty']} qty")
        else:
            st.info(f"{report_date} ko koi sale nahi hui")

    # ===== TAB 5: STOCK MANAGEMENT =====
    with tab5:
        st.subheader("Stock Management")
        tab_stock1, tab_stock2 = st.tabs(["📜 Stock History", "📊 Stock Value Report"])

        with tab_stock1:
            st.subheader("📜 Complete Stock History")

            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                search_hist = st.text_input("🔍 Item Search", placeholder="Item name", key="hist_search")
            with col_f2:
                type_filter = st.selectbox("Type Filter", ["All", "IN ✅", "OUT ❌"], key="hist_type")
            with col_f3:
                hist_date = st.date_input("Date Filter", value=None, key="hist_date")

            hist_query = "SELECT * FROM stock_history WHERE 1=1"
            hist_params = []
            if search_hist:
                hist_query += " AND item_name LIKE ?"
                hist_params.append(f"%{search_hist}%")
            if type_filter == "IN ✅":
                hist_query += " AND type = 'IN'"
            elif type_filter == "OUT ❌":
                hist_query += " AND type = 'OUT'"
            if hist_date:
                hist_query += " AND date = ?"
                hist_params.append(str(hist_date))
            hist_query += " ORDER BY date DESC, time DESC LIMIT 100"

            try:
                history = pd.read_sql(hist_query, conn, params=hist_params)
                history = history.fillna('')
            except Exception as sh_e:
                st.error(f"⚠️ Stock history load nahi ho saki: {sh_e}")
                history = pd.DataFrame()

            if not history.empty:
                total_in_all = history[history['type'] == 'IN']['qty'].sum()
                total_out_all = history[history['type'] == 'OUT']['qty'].sum()
                c1, c2, c3 = st.columns(3)
                c1.success(f"**✅ Total IN: {total_in_all:g}**")
                c2.error(f"**❌ Total OUT: {total_out_all:g}**")
                c3.info(f"**📋 Total Records: {len(history)}**")
                st.divider()

                for _, row in history.iterrows():
                    note_str = str(row.get('note') or '')
                    if 'Quick Sale' in note_str or 'Bill' in note_str:
                        source = "💰 Quick Sale"
                        customer_part = note_str.split('to')[-1].strip() if ' to ' in note_str else 'Cash Customer'
                        bill_part = note_str.split('Bill:')[-1].split('to')[0].strip() if 'Bill:' in note_str else ''
                        detail = f"Customer: {customer_part}" + (f" | Bill: {bill_part}" if bill_part else "")
                    elif 'Roll Nama' in note_str or 'Roz Ka' in note_str:
                        source = "📋 Roz Ka Roll Nama"
                        detail = "Daily roll se deduct hua"
                    elif 'New item' in note_str or 'added' in note_str.lower():
                        source = "➕ Add New Item (Tab)"
                        detail = "Opening stock entry"
                    elif 'Edit' in note_str or 'Updated' in note_str:
                        source = "✏️ Item Edit (Tab)"
                        detail = "Manually update kiya gaya"
                    elif 'Purchase' in note_str:
                        source = "📦 Stock Purchase"
                        detail = note_str
                    else:
                        source = "🔄 Other"
                        detail = note_str or "—"

                        def safe_float(val):
                            if val is None or val == '':
                                return 0.0
                            if isinstance(val, bytes):
                                try:
                                    val = val.decode('utf-8').strip()
                                except:
                                    return 0.0
                            try:
                                return float(val)
                            except:
                                return 0.0

                        qty_val = safe_float(row.get('qty'))
                        old_s = safe_float(row.get('old_stock'))
                        new_s = safe_float(row.get('new_stock'))
                        bg = "#e8f5e9" if row['type'] == 'IN' else "#ffebee"
                        border = "#4caf50" if row['type'] == 'IN' else "#f44336"
                        sign = "+" if row['type'] == 'IN' else "-"
                        emoji = "✅" if row['type'] == 'IN' else "❌"

                        st.markdown(f"""
<div style="background:{bg};border-left:4px solid {border};padding:10px 14px;border-radius:6px;margin-bottom:8px">
<b>{emoji} {row['type']}</b> &nbsp;|&nbsp; 📅 <b>{row['date']}</b> &nbsp;⏰ {row['time']}<br>
<b>Item:</b> {row['item_name']} &nbsp;|&nbsp; <b>Qty:</b> {sign}{qty_val:g} {row['unit']}<br>
<b>Source (Tab):</b> {source} &nbsp;|&nbsp; <b>Detail:</b> {detail}<br>
<b>Stock Change:</b> {old_s:g} ➜ <b>{new_s:g} {row['unit']}</b>
</div>""", unsafe_allow_html=True)
            else:
                st.info("Koi history nahi mili")

        with tab_stock2:
            st.subheader("Stock Value Report")
            stock_value = pd.read_sql(
                "SELECT name, stock, kharid_price, base_unit, (stock * kharid_price) as value FROM items", conn)
            if not stock_value.empty:
                st.metric("Total Stock Value", f"Rs. {stock_value['value'].sum():.2f}")
                st.dataframe(stock_value, width='stretch')
            else:
                st.info("Stock empty")

    # ===== TAB 6: SETTINGS =====
    with tab6:
        st.subheader("Settings")
        st.markdown("### 💾 Database Backup")
        if st.button("💾 Download Backup", width='stretch', type="primary"):
            with open('afzal_store.db', 'rb') as f:
                st.download_button(
                    label="📥 Download Database",
                    data=f,
                    file_name=f"afzal_store_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}.db",
                    mime="application/octet-stream"
                )

        st.markdown("### 📱 WhatsApp Alerts")
        wa_number = st.text_input("Your WhatsApp Number (92xxx)", placeholder="923001234567")
        if st.button("Test WhatsApp", width='stretch'):
            if wa_number:
                msg = f"*Afzal Store - Shop Management*\nTest message - System working!"
                wa_url = f"https://wa.me/{wa_number}?text={urllib.parse.quote(msg)}"
                st.link_button("Open WhatsApp", wa_url)
            else:
                st.error("Enter number first")

    conn.close()

    # ===== EDIT POPUP =====
    if 'edit_id' in st.session_state:
        conn2 = get_db()
        item_df = pd.read_sql("SELECT * FROM items WHERE id =?", conn2, params=(st.session_state['edit_id'],))
        if not item_df.empty:
            item = item_df.iloc[0]
            item_id = int(item['id'])
            base_unit_val = str(item.get('base_unit') or 'Pcs')
            kharid_val = float(item.get('kharid_price') or 0)
            sale_val = float(item.get('sale_price') or 0)
            stock_val = float(item.get('stock') or 0)
            min_stock_val = int(item.get('min_stock') or 0)
            category_val = str(item.get('category') or '📦 Other Items')

            CATEGORY_LIST = [
                "🌾 Rasan, Daalain & Noodles", "🛢️ Oil, Ghee & Masala Jaat",
                "🍅 Ketchup, Sauces & Spreads", "☕ Patti, Drinks & Tang",
                "🍬 Jelly & Biscuits", "🧼 Sabun, Shampoo & Hair Care",
                "🧴 Cosmetics & Powders", "🦷 Toothpaste & Oral Care",
                "👶 Baby Care & Diapers", "🌊 Surf, Cleaners & Maachis",
                "🦟 Insect Killer & Coils", "🛠️ Hardware, Glue & Cells",
                "🚬 Cigarette & Tobacco", "📦 Other Items"
            ]

            with st.form(key=f"edit_form_{item_id}"):
                st.subheader(f"✏️ Edit: {item['name']}")
                col1, col2 = st.columns(2)
                with col1:
                    edit_name = st.text_input("Item Name*", value=str(item['name']), key=f"en_{item_id}")
                with col2:
                    cat_index = CATEGORY_LIST.index(category_val) if category_val in CATEGORY_LIST else 0
                    edit_category = st.selectbox("Category", CATEGORY_LIST, index=cat_index, key=f"ec_{item_id}")

                col3, col4, col5 = st.columns(3)
                with col3:
                    edit_kharid = st.number_input("Purchase Price*", value=kharid_val, format="%.2f", min_value=0.0, key=f"ek_{item_id}")
                with col4:
                    edit_sale = st.number_input("Sale Price*", value=sale_val, format="%.2f", min_value=0.0, key=f"es_{item_id}")
                with col5:
                    unit_list = ["Kg", "Gram", "Pcs", "Ltr", "Dozen", "Pack"]
                    unit_index = unit_list.index(base_unit_val) if base_unit_val in unit_list else 2
                    edit_unit = st.selectbox("Base Unit*", unit_list, index=unit_index, key=f"eu_{item_id}")

                col6, col7, col8 = st.columns(3)
                with col6:
                    edit_stock = st.number_input("Stock Qty", value=stock_val, format="%.2f", min_value=0.0, key=f"estk_{item_id}")
                with col7:
                    edit_min_stock = st.number_input("Min Stock Alert", value=min_stock_val, min_value=0, key=f"ems_{item_id}")
                with col8:
                    edit_barcode = st.text_input("Barcode", value=str(item.get('barcode') or ''), key=f"eb_{item_id}")

                col9, col10 = st.columns(2)
                with col9:
                    expiry_val = item.get('expiry_date')
                    try:
                        expiry_default = datetime.strptime(str(expiry_val), "%Y-%m-%d").date() if expiry_val and str(expiry_val).strip() else None
                    except:
                        expiry_default = None
                    edit_expiry = st.date_input("Expiry Date", value=expiry_default, key=f"eexp_{item_id}")
                with col10:
                    edit_photo_mode = st.radio("Item Photo", ["📤 Upload", "📷 Camera"], horizontal=True, key=f"eph_mode_{item_id}")
                    if edit_photo_mode == "📷 Camera":
                        edit_photo = st.camera_input("Nayi Photo Khinchein", key=f"eph_cam_{item_id}")
                    else:
                        edit_photo = st.file_uploader("Nayi Photo Upload Karein", type=['jpg', 'png', 'jpeg'], key=f"eph_{item_id}")

                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    submit = st.form_submit_button("💾 Update", type="primary")
                with col_btn2:
                    cancel = st.form_submit_button("❌ Cancel")

            if submit:
                try:
                    photo_path = str(item.get('photo') or '')
                    photo_thumb_path = str(item.get('photo_thumb') or '')
                    if edit_photo:
                        os.makedirs("item_photos", exist_ok=True)
                        base_name = f"item_photos/{edit_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                        photo_path = f"{base_name}.jpg"
                        photo_thumb_path = f"{base_name}_thumb.jpg"
                        with st.spinner("Photo compress ho rahi hai..."):
                            main_bytes, thumb_bytes, compress_msg = image_compression.compress_image_dual(edit_photo)
                        if main_bytes:
                            with open(photo_path, "wb") as f:
                                f.write(main_bytes)
                            if thumb_bytes:
                                with open(photo_thumb_path, "wb") as f:
                                    f.write(thumb_bytes)
                            else:
                                photo_thumb_path = ""
                            if compress_msg:
                                st.caption(compress_msg)
                            try:
                                import sync_manager
                                sync_manager.upload_photo_to_drive_background(
                                    main_bytes, os.path.basename(photo_path))
                                if thumb_bytes:
                                    sync_manager.upload_photo_to_drive_background(
                                        thumb_bytes, os.path.basename(photo_thumb_path))
                            except Exception:
                                pass
                        else:
                            photo_path = str(item.get('photo') or '')
                            photo_thumb_path = str(item.get('photo_thumb') or '')
                            st.warning(compress_msg or "⚠️ Nayi photo save nahi ho saki - purani photo rehne di gayi hai.")

                    expiry_str = edit_expiry.strftime("%Y-%m-%d") if edit_expiry else ""

                    conn2.execute(
                        '''UPDATE items SET name=?, category=?, kharid_price=?, sale_price=?, price=?,
                           base_unit=?, stock=?, min_stock=?, barcode=?, expiry_date=?, photo=?, photo_thumb=? WHERE id=?''',
                        (edit_name.strip(), edit_category, edit_kharid, edit_sale, edit_sale,
                         edit_unit, edit_stock, edit_min_stock, edit_barcode.strip(),
                         expiry_str, photo_path, photo_thumb_path, item_id)
                    )
                    conn2.commit()

                    if edit_stock != stock_val:
                        move_type = 'IN' if edit_stock > stock_val else 'OUT'
                        conn2.execute(
                            '''INSERT INTO stock_history (item_id, item_name, type, qty, unit, old_stock, new_stock, note, date, time)
                               VALUES (?,?,?,?,?,?,?,?,?,?)''',
                            (item_id, edit_name.strip(), move_type, abs(edit_stock - stock_val),
                             edit_unit, stock_val, edit_stock, 'Updated via Edit',
                             datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%H:%M:%S"))
                        )
                        conn2.commit()

                    st.success(f"✅ {edit_name} successfully updated!")
                    del st.session_state['edit_id']
                    st.session_state.pop('show_edit_form', None)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Update failed: {str(e)}")

            if cancel:
                del st.session_state['edit_id']
                st.session_state.pop('show_edit_form', None)
                st.rerun()

        conn2.close()