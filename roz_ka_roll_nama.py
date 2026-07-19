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


def show_roll_nama(get_db=None):
    import streamlit as st
    import sqlite3
    import pandas as pd
    from datetime import datetime
    import camera_ocr
    import google_drive_backup as gdrive

    DB_FILE = "afzal_store.db"

    if get_db is not None:
        conn = get_db()
    else:
        # BUG FIX: pehle yahan "data.db" (ek alag file) khulti thi jab get_db nahi milta
        # tha - is se aapka asal data (afzal_store.db) nazar hi nahi aata tha. Ab hamesha
        # wahi asal database file khulti hai, WAL mode ke sath (locked errors se bachne ke liye).
        conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")

    c = conn.cursor()

    def safe_execute(query, params=(), friendly_action="Record save"):
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

    # --- Database Setup ---
    try:
        c.execute('''CREATE TABLE IF NOT EXISTS roll_nama (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            customer TEXT,
            item TEXT,
            qty REAL,
            amount REAL,
            paid REAL,
            status TEXT,
            bachat REAL DEFAULT 0)''')
        try:
            c.execute("ALTER TABLE roll_nama ADD COLUMN qty REAL DEFAULT 1.0")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE roll_nama ADD COLUMN bachat REAL DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        # PERF FIX: date-search aur pending-udhaar lookup dono is index se fayda uthate hain
        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_roll_nama_date2 ON roll_nama (date)")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_roll_nama_pending ON roll_nama (customer, date) WHERE paid < amount")
        except sqlite3.OperationalError:
            pass

        conn.commit()
    except sqlite3.Error as e:
        st.error(f"⚠️ Roll Nama table set karne mein masla aaya: {e}")

    # ==================== 🎨 TABS KO BEAUTIFUL BOX COLORS DENA ====================
    st.markdown("""
        <style>
            div[data-testid="stTabs"] div[role="tablist"] {
                gap: 12px !important;
                padding: 5px 0px !important;
            }
            div[data-testid="stTabs"] button[role="tab"] {
                padding: 10px 20px !important;
                border-radius: 8px !important;
                font-weight: bold !important;
                border: 1px solid #e0e0e0 !important;
                background-color: #f8f9fa !important;
                box-shadow: 0px 2px 5px rgba(0,0,0,0.05) !important;
                transition: all 0.3s ease !important;
            }
            div[data-testid="stTabs"] div[role="tablist"] > button[id*="tab-0"][aria-selected="true"] {
                background-color: #2F80ED !important;
                color: white !important;
                border-color: #1b62c4 !important;
                box-shadow: 0px 4px 10px rgba(47, 128, 237, 0.3) !important;
            }
            div[data-testid="stTabs"] div[role="tablist"] > button[id*="tab-1"][aria-selected="true"] {
                background-color: #F2994A !important;
                color: white !important;
                border-color: #d67d2a !important;
                box-shadow: 0px 4px 10px rgba(242, 153, 74, 0.3) !important;
            }
            div[data-testid="stTabs"] div[data-testid="stTabs"] button[role="tab"] {
                font-size: 14px !important;
            }
            div[data-testid="stTabs"] div[data-testid="stTabs"] div[role="tablist"] > button[id*="tab-0"][aria-selected="true"] {
                background-color: #27AE60 !important;
                color: white !important;
                border-color: #219653 !important;
                box-shadow: 0px 4px 10px rgba(39, 174, 96, 0.3) !important;
            }
            div[data-testid="stTabs"] div[data-testid="stTabs"] div[role="tablist"] > button[id*="tab-1"][aria-selected="true"] {
                background-color: #9B51E0 !important;
                color: white !important;
                border-color: #7d3cbd !important;
                box-shadow: 0px 4px 10px rgba(155, 81, 224, 0.3) !important;
            }
            button[aria-label="💾 Save Karyana Entry"] {
                background-color: #2F80ED !important;
                color: white !important;
                font-weight: bold !important;
                border-radius: 8px !important;
                width: 100% !important;
                height: 45px !important;
            }
            button[aria-label="💾 Save Aata Entry"] {
                background-color: #E2445C !important;
                color: white !important;
                font-weight: bold !important;
                border-radius: 8px !important;
                width: 100% !important;
                height: 45px !important;
            }
        </style>
    """, unsafe_allow_html=True)

    st.subheader("📓 Roz Ka Khaata Book")
    tab1, tab2, tab3 = st.tabs(["✍️ Nayi Entry", "📋 Udhaar Khata (Pending)", "📊 Monthly Record"])

    items_dict = {}
    try:
        c.execute("SELECT name, sale_price, kharid_price FROM items WHERE name IS NOT NULL AND name != ''")
        rows = c.fetchall()
        for row in rows:
            item_name = str(row[0]).strip()
            sale_price = float(row[1]) if row[1] else 0.0
            kharid_price = float(row[2]) if row[2] else 0.0
            if item_name:
                display_text = f"{item_name} - Rs. {sale_price:.0f}"
                items_dict[display_text] = (item_name, sale_price, kharid_price)
    except sqlite3.Error as e:
        st.error(f"⚠️ Items list load nahi ho saki: {e}")

    item_options = ["➕ Type New / Custom Item"] + list(items_dict.keys())

    if len(items_dict) == 0:
        st.warning("⚠️ Items Add mein koi item nahi hai! Pehle Items Add mein jaake item daalo (Custom item se bhi entry ho sakti hai).")

    try:
        c.execute("SELECT id, name FROM customers ORDER BY name ASC")
        customers = c.fetchall()
    except sqlite3.Error:
        customers = []

    # ==================== TAB 1: NAYI ENTRY ====================
    with tab1:
        sub_tab_karyana, sub_tab_aata, sub_tab_scan = st.tabs(["🛒 Karyana Items Sale", "🌾 Aata/Chakki Sale", "📷 Bill Scan"])

        # ---------------- SUB TAB 1: KARYANA ITEMS ----------------
        with sub_tab_karyana:
            if 'karyana_qty' not in st.session_state:
                st.session_state.karyana_qty = 1.0
            if 'karyana_amount' not in st.session_state:
                st.session_state.karyana_amount = 0.0
            if 'prev_item' not in st.session_state:
                st.session_state.prev_item = ""

            c_status = st.radio("Payment Type", ["Cash", "Udhaar"], horizontal=True, key="payment_type")

            col1, col2 = st.columns(2)
            with col1:
                if c_status == "Udhaar":
                    if customers:
                        cust_dict_k = {f"{idx}. {cu[1]}": cu[1] for idx, cu in enumerate(customers, 1)}
                        sel_name_k = st.selectbox("👤 Udhaar Customer Chuno*", list(cust_dict_k.keys()), key="rn_karyana_cust_dropdown")
                        c_name = cust_dict_k[sel_name_k]
                    else:
                        c_name = st.text_input("Customer Name*", key="cust_name_fb", value="")
                else:
                    c_name = st.text_input("Customer Name (ya 'Cash')*", key="cust_name", value="Cash")

                selected_opt = st.selectbox("Item Chuno (Real Stock List)", item_options, key="item_select")
                custom_item = st.text_input("Ya Haath Se Item Likhein (Agar list mein nahi hai)", key="custom_item_input")

            current_rate = 0.0
            current_kharid = 0.0
            is_custom = True

            if selected_opt != "➕ Type New / Custom Item" and selected_opt in items_dict:
                current_rate = items_dict[selected_opt][1]
                current_kharid = items_dict[selected_opt][2]
                is_custom = False

                if st.session_state.prev_item != selected_opt:
                    st.session_state.karyana_qty = 1.0
                    st.session_state.karyana_amount = current_rate * st.session_state.karyana_qty
                    st.session_state.prev_item = selected_opt

            with col2:
                def update_from_qty():
                    if not is_custom and current_rate > 0:
                        st.session_state.karyana_amount = float(st.session_state.karyana_qty * current_rate)
                    elif is_custom and st.session_state.get("manual_rate_input", 0) > 0:
                        st.session_state.karyana_amount = float(st.session_state.karyana_qty * st.session_state.manual_rate_input)

                def update_from_amount():
                    if not is_custom and current_rate > 0:
                        st.session_state.karyana_qty = round(float(st.session_state.karyana_amount / current_rate), 3)
                    elif is_custom and st.session_state.get("manual_rate_input", 0) > 0:
                        st.session_state.karyana_qty = round(float(st.session_state.karyana_amount / st.session_state.manual_rate_input), 3)

                c_qty = st.number_input("Quantity (KG ya Unit)*", min_value=0.0, step=0.1, value=float(st.session_state.karyana_qty), format="%.3f", key="karyana_qty_display")
                st.session_state.karyana_qty = c_qty

                if is_custom:
                    manual_rate = st.number_input("Sale Rate per Unit*", min_value=0.0, step=1.0, value=0.0, key="manual_rate_input", on_change=update_from_qty)
                    manual_cost = st.number_input("Kharid Rate per Unit*", min_value=0.0, step=1.0, value=0.0, key="manual_cost")
                    current_rate = manual_rate
                    current_kharid = manual_cost

                current_bachat = (current_rate - current_kharid) * st.session_state.karyana_qty

                if not is_custom:
                    st.info(f"**Sale Rate: Rs. {current_rate:.0f}**")

                c_total = st.number_input("Total Amount (Rs.)*", min_value=0.0, step=1.0, key="karyana_amount", on_change=update_from_amount)

            if st.button("💾 Save Karyana Entry", type="primary", key="btn_karyana_save"):
                if c_name and c_name.strip() and c_total > 0:
                    final_item = ""
                    if custom_item.strip():
                        final_item = custom_item.strip()
                    elif selected_opt != "➕ Type New / Custom Item":
                        final_item = items_dict[selected_opt][0]

                    if not final_item:
                        st.error("Item ka naam select karein ya haath se likhein!")
                    else:
                        paid = c_total if c_status == "Cash" else 0.0
                        final_bachat = (current_rate - current_kharid) * c_qty

                        stock_ok = True
                        try:
                            c.execute("PRAGMA table_info(items)")
                            item_cols = [col[1].lower() for col in c.fetchall()]
                            if 'stock' in item_cols:
                                search_clean = final_item.strip().lower()
                                c.execute("SELECT id, name, stock, base_unit FROM items")
                                item_rows = c.fetchall()
                                for r in item_rows:
                                    db_id, db_name, db_qty, db_unit = r[0], r[1], r[2], (r[3] if len(r) > 3 else 'Pcs')
                                    if str(db_name).strip().lower() == search_clean:
                                        old_stock = db_qty if db_qty else 0.0
                                        new_qty = old_stock - c_qty
                                        stock_ok = safe_execute("UPDATE items SET stock=? WHERE id=?", (new_qty, db_id), "Stock update")
                                        if stock_ok:
                                            safe_execute('''INSERT INTO stock_history
                                                         (item_id, item_name, type, qty, unit, old_stock, new_stock, note, date, time)
                                                         VALUES (?, ?, 'OUT', ?, ?, ?, ?, ?, ?, ?)''',
                                                      (db_id, db_name, c_qty, db_unit, old_stock, new_qty,
                                                       f"Deducted via Roz Ka Roll Nama ({c_name})",
                                                       datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%H:%M:%S")),
                                                      "Stock history")
                                        break
                        except sqlite3.Error as stock_err:
                            st.warning(f"⚠️ Stock update mein choti dikkat aayi ({stock_err}) - entry phir bhi save ho rahi hai.")

                        entry_ok = safe_execute(
                            "INSERT INTO roll_nama (date, customer, item, qty, amount, paid, status, bachat) VALUES (?,?,?,?,?,?,?,?)",
                            (datetime.now().strftime("%Y-%m-%d"), c_name.strip(), final_item, c_qty, c_total, paid, c_status, final_bachat),
                            "Roll Nama entry")

                        if entry_ok and stock_ok:
                            conn.commit()
                            st.cache_data.clear()
                            st.success("🎉 Entry save!")
                            st.rerun()
                        else:
                            conn.rollback()
                            st.error("❌ Kuch save nahi ho saka (safety ke liye kuch bhi save nahi hua). Dobara try karein.")
                else:
                    st.error("Customer Name aur Total Amount likhna lazmi hai!")

        # ---------------- SUB TAB 2: AATA/CHAKKI SALE ----------------
        with sub_tab_aata:
            st.markdown("<h4 style='color: #27ae60;'>🌾 Rozana Roll Nama - Aata Sale Entry</h4>", unsafe_allow_html=True)

            try:
                from chaki_management import get_current_stock
                _, rn_aata_stock = get_current_stock()
            except Exception:
                try:
                    conn_st = sqlite3.connect(DB_FILE, timeout=10)
                    c_st = conn_st.cursor()
                    c_st.execute("SELECT SUM(qty_kg) FROM chakki_inventory WHERE item='Aata' AND type IN ('Produce', 'Manual Add')")
                    a_p = c_st.fetchone()[0] or 0.0
                    c_st.execute("SELECT SUM(aata_kg) FROM chakki_atta_sale")
                    a_s = c_st.fetchone()[0] or 0.0
                    c_st.execute("SELECT SUM(qty_kg) FROM chakki_inventory WHERE item='Aata' AND type IN ('Manual Minus')")
                    a_m = c_st.fetchone()[0] or 0.0
                    rn_aata_stock = max(a_p - (a_s + a_m), 0.0)
                    conn_st.close()
                except sqlite3.Error:
                    rn_aata_stock = 0.0

            st.info(f"📦 **Chakki Stock Status:** Current Available Aata: {rn_aata_stock:,.3f} KG")

            r_status = st.radio("Payment Type (Aata)", ["Cash", "Udhaar"], horizontal=True, key="rn_aata_pay_unique")

            if "rn_aata_rs_helper" not in st.session_state:
                st.session_state.rn_aata_rs_helper = 0.0
            if "rn_aata_qty_unique" not in st.session_state:
                st.session_state.rn_aata_qty_unique = 0.000

            def update_kg_from_rs():
                try:
                    c.execute("SELECT value FROM chakki_config WHERE key='default_aata_rate'")
                    row_cfg = c.fetchone()
                    current_rate = float(row_cfg[0]) if row_cfg else 120.0
                except sqlite3.Error:
                    current_rate = 120.0

                if st.session_state.rn_aata_rs_helper > 0 and current_rate > 0:
                    st.session_state.rn_aata_qty_unique = round(st.session_state.rn_aata_rs_helper / current_rate, 3)

            col_a1, col_a2, col_a3 = st.columns(3)
            with col_a1:
                if r_status == "Udhaar":
                    try:
                        cust_options = ["✍️ Naya Customer (Khud Naam Likhein)"]
                        cust_dict = {}
                        if customers:
                            for c_idx, row in enumerate(customers, 1):
                                display_label = f"{c_idx}. {row[1]}"
                                cust_options.append(display_label)
                                cust_dict[display_label] = str(row[1]).strip()

                        sel_name = st.selectbox("👤 Customer Select Chuno*", cust_options, key="rn_aata_cust_dropdown")

                        if sel_name == "✍️ Naya Customer (Khud Naam Likhein)":
                            r_cust_name = st.text_input("📝 Naye Customer Ka Naam Likhein:", key="rn_aata_cust_manual", value="")
                        else:
                            r_cust_name = cust_dict[sel_name]
                    except Exception:
                        r_cust_name = st.text_input("👤 Customer Name*", key="rn_aata_cust_unique", value="")
                else:
                    r_cust_name = st.text_input("👤 Customer Name (ya 'Cash')*", key="rn_aata_cust_unique", value="Cash Customer")

            with col_a2:
                try:
                    c.execute("SELECT value FROM chakki_config WHERE key='default_aata_rate'")
                    row_cfg = c.fetchone()
                    default_rate = float(row_cfg[0]) if row_cfg else 120.0
                except sqlite3.Error:
                    default_rate = 120.0

                st.number_input("💵 Kitne Rupay Ka Aata Chahiye? (Optional)", min_value=0.0, step=10.0, key="rn_aata_rs_helper", on_change=update_kg_from_rs)

            with col_a3:
                r_rate_per_kg = st.number_input("💰 Rate per KG (Rs.)", value=default_rate, step=0.1, key="rn_aata_rate_unique")

            col_b1, col_b2 = st.columns(2)
            with col_b1:
                r_aata_kg = st.number_input("⚖️ Aata Kitna Becha (KG)", min_value=0.0, step=0.001, format="%.3f", key="rn_aata_qty_unique")
            with col_b2:
                r_discount = st.number_input("🎁 Riyaat / Discount (Rs.)", min_value=0.0, step=5.0, value=0.0, key="rn_aata_discount_unique")

            PROFIT_PER_KG = 15.0

            gross_total = round(r_aata_kg * r_rate_per_kg, 2)
            r_total = max(0.0, round(gross_total - r_discount, 2))

            total_estimated_profit = round(r_aata_kg * PROFIT_PER_KG, 2)
            final_bachat = max(0.0, round(total_estimated_profit - r_discount, 2))

            if r_discount > 0:
                st.warning(f"📊 **Net Bill:** Rs. {r_total:,.2f} | 📉 **Riyaat Ki Wajah Se Bachat Kam Hui:** Rs. {final_bachat:,.2f} (Asal Bachat Rs. {total_estimated_profit:,.2f} Thi)")
            else:
                st.warning(f"📊 **Total Bill:** Rs. {r_total:,.2f} | **Is Entry Se Bachat:** Rs. {final_bachat:,.2f}")

            if r_aata_kg > rn_aata_stock:
                st.warning(f"⚠️ Stock mein sirf {rn_aata_stock:,.3f} KG Aata para hai. Phir bhi record save kia ja sakta hai.")

            if st.button("🟢 ✅ Roll Nama Se Aata Sale Save Karen", type="primary", use_container_width=True, key="rn_aata_save_btn_unique"):
                cleaned_cust_name = (r_cust_name or "").strip()

                if not cleaned_cust_name or r_aata_kg <= 0:
                    st.error("❌ Galti: Customer Name aur Aata KG likhna lazmi hai!")
                else:
                    current_time = datetime.now()
                    today_str = current_time.strftime("%Y-%m-%d")
                    time_str = current_time.strftime("%I:%M %p")

                    paid_amt = r_total if r_status == "Cash" else 0.0
                    rem_bal = 0.0 if r_status == "Cash" else r_total
                    s_type = "Cash Sale" if r_status == "Cash" else "Udhar Par Diya"

                    final_cust_id = None
                    if r_status == "Udhaar" and cleaned_cust_name:
                        try:
                            c.execute("SELECT id FROM customers WHERE LOWER(TRIM(name)) = LOWER(?)", (cleaned_cust_name,))
                            existing_user = c.fetchone()
                            if not existing_user:
                                c.execute("INSERT INTO customers (name, status) VALUES (?, 'Active')", (cleaned_cust_name,))
                                final_cust_id = c.lastrowid
                            else:
                                final_cust_id = existing_user[0]
                        except sqlite3.Error as e:
                            st.warning(f"⚠️ Customer record link nahi ho saka: {e}")

                    detail_note = "Roz Ka Roll Nama (Aata Sale)"
                    if r_discount > 0:
                        detail_note += f" - Rs. {r_discount:g} Riyaat Di"

                    ok1 = safe_execute("""
                        INSERT INTO chakki_atta_sale (date, customer_name, aata_kg, rate_per_kg, total, sale_type, paid, remaining_balance, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (today_str, cleaned_cust_name, r_aata_kg, r_rate_per_kg, r_total, s_type, paid_amt, rem_bal, detail_note), "Chakki sync")

                    ok2 = safe_execute("""
                        INSERT INTO roll_nama (date, customer, item, qty, amount, paid, status, bachat)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (today_str, cleaned_cust_name, "Aata (Chakki)" + (f" (-Rs.{r_discount:g} Riyaat)" if r_discount > 0 else ""), r_aata_kg, r_total, paid_amt, r_status, final_bachat), "Roll Nama entry")

                    ok3 = True
                    if r_status == "Udhaar" and final_cust_id is not None:
                        ok3 = safe_execute("""
                            INSERT INTO udhaar (customer_id, date, type, amount, item, qty, rate, detail, time, unit)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (final_cust_id, today_str, 'udhaar', r_total, 'Aata (Chakki)', r_aata_kg, r_rate_per_kg, detail_note, time_str, "KG"), "Udhaar khatta sync")

                    if ok1 and ok2 and ok3:
                        conn.commit()
                        st.cache_data.clear()
                        st.success("🎉 Aata Sale save ho gayi! Riyaat aapki bachat (profit) mein se kaat di gayi hai.")
                        st.rerun()
                    else:
                        conn.rollback()
                        st.error("❌ Kuch data save nahi ho saka - safety ke liye kuch bhi save nahi hua. Dobara try karein.")

        # ---------------- SUB TAB 3: BILL SCAN (OCR) ----------------
        with sub_tab_scan:
            st.markdown("<h4 style='color: #8e44ad;'>📷 Bill Scan - Photo Se Multiple Items Add Karein</h4>", unsafe_allow_html=True)
            st.caption("Kisi bhi bill/parchi ki photo khinchein - Item, Qty, Rate, Total nikal kar Preview mein dikhaye jayenge. Check/edit kar ke hi save hoga.")

            rn_scan_mode = st.radio("Photo", ["📤 Upload", "📷 Camera Se Khinchein"], horizontal=True, key="rn_scan_mode")
            if rn_scan_mode == "📷 Camera Se Khinchein":
                rn_bill_img = st.camera_input("Bill Khinchein", key="rn_scan_cam")
            else:
                rn_bill_img = st.file_uploader("Bill Upload Karein", type=["jpg", "jpeg", "png"], key="rn_scan_upload")

            rn_scan_customer = st.text_input("👤 Customer Name (ya 'Cash')", value="Cash", key="rn_scan_cust")
            rn_scan_status = st.radio("Payment Type", ["Cash", "Udhaar"], horizontal=True, key="rn_scan_status")

            if rn_bill_img is not None and st.button("🔍 Bill Scan Karo (OCR)", key="rn_scan_btn"):
                rn_img_bytes = rn_bill_img.getvalue()
                with st.spinner("Bill scan ho raha hai..."):
                    raw_text, err = camera_ocr.extract_raw_text(rn_img_bytes)
                if err:
                    st.warning(err + " Neeche khali table mein khud likh sakte hain.")
                    st.session_state["rn_scan_rows"] = [{"item": "", "qty": 1.0, "rate": 0.0, "total": 0.0}]
                else:
                    guessed = camera_ocr.guess_bill_rows(raw_text)
                    if not guessed:
                        st.info("ℹ️ OCR ko bill mein saaf numbers nahi mile. Neeche khud likh sakte hain.")
                        guessed = [{"item": "", "qty": 1.0, "rate": 0.0, "total": 0.0}]
                    st.session_state["rn_scan_rows"] = guessed

            if "rn_scan_rows" in st.session_state:
                st.warning("⚠️ **Preview & Confirm:** OCR (khaas kar kharab handwriting/Sindhi likhai par) 100% sahi nahi hota. Har row dhyan se check/edit kar ke tabhi 'Confirm & Save' dabayein.")
                rn_edited_df = st.data_editor(
                    pd.DataFrame(st.session_state["rn_scan_rows"]),
                    num_rows="dynamic", key="rn_scan_editor", width='stretch',
                    column_config={
                        "item": st.column_config.TextColumn("Item Name*"),
                        "qty": st.column_config.NumberColumn("Qty", min_value=0.0),
                        "rate": st.column_config.NumberColumn("Rate", min_value=0.0),
                        "total": st.column_config.NumberColumn("Total (Rs.)*", min_value=0.0),
                    })

                if st.button("✅ Confirm & Save Sab Items", type="primary", key="rn_scan_confirm"):
                    cust_name_clean = (rn_scan_customer or "Cash").strip() or "Cash"
                    saved_count = 0
                    for _, row in rn_edited_df.iterrows():
                        item_name = str(row.get("item", "")).strip()
                        total_amt = float(row.get("total", 0) or 0)
                        qty_amt = float(row.get("qty", 0) or 0)
                        if not item_name or total_amt <= 0:
                            continue

                        paid = total_amt if rn_scan_status == "Cash" else 0.0
                        ok = safe_execute(
                            "INSERT INTO roll_nama (date, customer, item, qty, amount, paid, status, bachat) VALUES (?,?,?,?,?,?,?,?)",
                            (datetime.now().strftime("%Y-%m-%d"), cust_name_clean, item_name, qty_amt, total_amt, paid, rn_scan_status, 0.0),
                            "Bill scan entry")
                        if ok:
                            saved_count += 1

                    conn.commit()
                    st.cache_data.clear()

                    try:
                        gdrive.upload_photo_to_drive(rn_img_bytes if 'rn_img_bytes' in dir() else rn_bill_img.getvalue(),
                                                      f"roll_nama_bill_scan_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg")
                    except Exception:
                        pass

                    del st.session_state["rn_scan_rows"]
                    if saved_count:
                        st.success(f"✔️ {saved_count} items save ho gaye!")
                        st.rerun()
                    else:
                        st.error("❌ Koi bhi item save nahi ho saka - Item Name aur Total zaroori hain.")

        # --- Aaj ka Record ---
        st.markdown("### Aaj ka Record")
        try:
            c.execute("SELECT id, date, customer, item, qty, amount, status, bachat FROM roll_nama WHERE date=? ORDER BY id DESC LIMIT 200", (datetime.now().strftime("%Y-%m-%d"),))
            data = c.fetchall()
        except sqlite3.Error as e:
            st.warning(f"⚠️ Aaj ka record load nahi ho saka: {e}")
            data = []

        for row in data:
            r_id, r_date, r_cust, r_itm, r_q, r_amt, r_stat, r_bachat = row
            if "Udhaar Wapsi" in str(r_itm):
                emoji = "💰"
            else:
                emoji = "🌾" if "Aata" in str(r_itm) else "📦"
            st.write(f"📅 {r_date} | 👤 {r_cust} | {emoji} {r_itm} (Qty: {r_q:g}) | 💰 Rs. {r_amt:,.0f} ({r_stat})")

        st.divider()

        total_sale_amount = sum([r[5] for r in data])
        aata_sale_amount = sum([r[5] for r in data if "Aata" in str(r[3])])

        col1, col2 = st.columns(2)
        with col1:
            st.metric("🛒 Aaj Ki Total Sale", f"Rs. {total_sale_amount:,.0f}")
        with col2:
            st.metric("🌾 Sirf Aata Ki Sale", f"Rs. {aata_sale_amount:,.0f}")

    # ==================== TAB 2: UDHAAR KHATA ====================
    with tab2:
        st.markdown("### 📉 Jinse Paise Lene Hain")

        # PERF FIX: pehle yeh saari pending udhaar rows Python mein group hoti thin -
        # ab grouping seedha SQL mein hoti hai (bohot tez), aur sirf top 300 customers
        # (baaki ke hisab se) dikhaye jaate hain. Search karne par seedha DB se dhoonda
        # jaata hai, poori list load kiye bagair.
        @st.cache_data(ttl=20, show_spinner="Udhaar khata load ho raha hai...")
        def cached_udhaar_summary():
            try:
                return pd.read_sql_query("""
                    SELECT customer, SUM(amount - paid) as baaki, COUNT(*) as entries
                    FROM roll_nama WHERE paid < amount
                    GROUP BY customer HAVING baaki > 0.01
                    ORDER BY baaki DESC LIMIT 300
                """, conn)
            except Exception:
                return pd.DataFrame(columns=["customer", "baaki", "entries"])

        search_query = st.text_input("🔍 Customer Ka Naam Search Karein...", value="", key="udhaar_search_box").strip()

        if search_query:
            try:
                summary_df = pd.read_sql_query("""
                    SELECT customer, SUM(amount - paid) as baaki, COUNT(*) as entries
                    FROM roll_nama WHERE paid < amount AND customer LIKE ?
                    GROUP BY customer HAVING baaki > 0.01
                    ORDER BY baaki DESC LIMIT 300
                """, conn, params=(f"%{search_query}%",))
            except sqlite3.Error as e:
                st.error(f"⚠️ Search nahi ho saka: {e}")
                summary_df = pd.DataFrame(columns=["customer", "baaki", "entries"])
        else:
            summary_df = cached_udhaar_summary()

        total_shop_udhaar = float(summary_df['baaki'].sum()) if not summary_df.empty else 0.0
        st.metric("💰 Poori Dukan Ka Kul Udhaar", f"Rs. {total_shop_udhaar:,.0f}")
        st.divider()

        if summary_df.empty:
            st.success("🎉 Koi bhi udhaar baaki nahi hai!" if not search_query else "Is naam se koi udhaar nahi mila.")

        for _, srow in summary_df.iterrows():
            cust_name = srow['customer']
            with st.expander(f"👤 {cust_name} - Kul Baaki: Rs. {srow['baaki']:,.0f}"):
                st.markdown(f"📂 **Is customer ki total {int(srow['entries'])} udhaar entries hain:**")

                try:
                    c.execute("""SELECT id, date, item, amount, paid FROM roll_nama
                                 WHERE customer=? AND paid < amount ORDER BY date DESC LIMIT 50""", (cust_name,))
                    entries = c.fetchall()
                except sqlite3.Error as e:
                    st.warning(f"⚠️ Entries load nahi ho sakin: {e}")
                    entries = []

                for r_id, r_date, r_item, r_amt, r_paid in entries:
                    baqiya = r_amt - r_paid
                    st.markdown("---")
                    st.write(f"📅 **Bill Date:** {r_date} | 📦 **Item:** {r_item}")
                    st.write(f"💵 **Bill Total:** Rs. {r_amt:,.0f} | 💸 **Pehle Paid:** Rs. {r_paid:,.0f} | 🔴 **Is Entry Ka Baaki:** Rs. {baqiya:,.0f}")

                    with st.form(f"pay_form_{r_id}"):
                        pay_amt = st.number_input("Kitne paise jama kiye?", min_value=0.0, max_value=float(baqiya) if baqiya > 0 else 0.0, key=f"pay_{r_id}")
                        if st.form_submit_button("✅ Jama Karo"):
                            if pay_amt > 0:
                                new_paid = r_paid + pay_amt
                                new_status = 'Cash' if new_paid >= r_amt else 'Udhaar'
                                ok1 = safe_execute("UPDATE roll_nama SET paid=?, status=? WHERE id=?", (new_paid, new_status, r_id), "Udhaar payment")

                                aaj_ki_tarikh = datetime.now().strftime("%Y-%m-%d")
                                wapsi_details = f"Udhaar Wapsi ({r_item})"
                                ok2 = safe_execute(
                                    "INSERT INTO roll_nama (date, customer, item, qty, amount, paid, status, bachat) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                    (aaj_ki_tarikh, cust_name, wapsi_details, 1.0, pay_amt, pay_amt, 'Cash', 0.0), "Udhaar wapsi entry")

                                if ok1 and ok2:
                                    conn.commit()
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    conn.rollback()

    # ==================== TAB 3: MONTHLY RECORD ====================
    with tab3:
        st.markdown("### 📊 Pure Mahine Ka Rozana Hisab")

        current_ym = datetime.now().strftime("%Y-%m")
        current_month_name = datetime.now().strftime("%B %Y")
        st.subheader(f"📅 Mahina: {current_month_name}")

        @st.cache_data(ttl=60, show_spinner="Monthly record load ho raha hai...")
        def cached_monthly_record(ym):
            try:
                daily_df = pd.read_sql_query(
                    "SELECT date, SUM(amount) as total FROM roll_nama WHERE date LIKE ? GROUP BY date ORDER BY date DESC",
                    conn, params=(f"{ym}-%",))
            except Exception:
                daily_df = pd.DataFrame(columns=["date", "total"])
            try:
                # PERF FIX: pehle poore mahine ke SAARE records load ho kar Python mein
                # dobara process hote the - ab yeh sirf ek dafa, cached, LIMIT ke sath hota hai
                detail_df = pd.read_sql_query(
                    "SELECT date as Date, customer as Customer, item as Item, qty as Quantity, amount as Amount FROM roll_nama WHERE date LIKE ? ORDER BY id DESC LIMIT 1000",
                    conn, params=(f"{ym}-%",))
            except Exception:
                detail_df = pd.DataFrame()
            return daily_df, detail_df

        daily_df, detail_df = cached_monthly_record(current_ym)
        total_monthly_earned = float(daily_df['total'].sum()) if not daily_df.empty else 0.0

        st.metric(f"💰 Pure {datetime.now().strftime('%B')} Ki Kul Kamai", f"Rs. {total_monthly_earned:,.0f}")
        st.divider()

        st.markdown("#### 📆 Din Ke Hisab Se Sale Detail:")
        if not daily_df.empty:
            for _, drow in daily_df.iterrows():
                st.info(f"📅 **Date: {drow['date']}** | 💵 Aaj Ki Total Sale: **Rs. {drow['total']:,.0f}**")
        else:
            st.warning("⚠️ Is mahine mein abhi tak koi sale entry nahi hui.")

        st.markdown("#### 📋 Rozana Ki Tafseeli Sale (Latest 1000):")
        if not detail_df.empty:
            df = detail_df.copy()
            try:
                df['Quantity'] = df['Quantity'].apply(format_quantity)
            except Exception:
                pass
            st.dataframe(df, use_container_width=True)
        else:
            st.write("Abhi koi tafseeli record nahi hai.")

    conn.close()
