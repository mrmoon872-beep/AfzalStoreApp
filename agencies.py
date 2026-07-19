def show_agencies(get_db):
    import streamlit as st
    import sqlite3
    from datetime import datetime
    import base64
    import camera_ocr
    import google_drive_backup as gdrive

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
                st.error("❌ Computer ki disk space kam hai! Jagah khali karein, phir dobara try karein.")
            elif "locked" in msg:
                st.error("❌ Database is waqt busy hai. Dobara button dabayein.")
            else:
                st.error(f"❌ {friendly_action} nahi ho saka: {e}")
            return False
        except sqlite3.Error as e:
            st.error(f"❌ {friendly_action} nahi ho saka: {e}")
            return False

    try:
        # Database Tables Structure
        c.execute('''CREATE TABLE IF NOT EXISTS agencies (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        phone TEXT,
                        address TEXT,
                        commission REAL DEFAULT 0.0)''')

        c.execute('''CREATE TABLE IF NOT EXISTS agency_v2_bills (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        agency_id INTEGER,
                        bill_number TEXT,
                        date TEXT,
                        total_amount REAL,
                        paid_amount REAL DEFAULT 0.0,
                        detail TEXT,
                        bill_photo BLOB,
                        status TEXT DEFAULT 'Pending',
                        FOREIGN KEY(agency_id) REFERENCES agencies(id))''')

        c.execute('''CREATE TABLE IF NOT EXISTS agency_v2_payments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        bill_id INTEGER,
                        date TEXT,
                        amount REAL,
                        detail TEXT,
                        payment_mode TEXT DEFAULT 'Cash',
                        FOREIGN KEY(bill_id) REFERENCES agency_v2_bills(id))''')

        try:
            c.execute("SELECT payment_mode FROM agency_v2_payments LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE agency_v2_payments ADD COLUMN payment_mode TEXT DEFAULT 'Cash'")

        conn.commit()
    except sqlite3.Error as e:
        st.error(f"⚠️ Agency tables set karne mein masla aaya: {e}")
        conn.close()
        return

    def render_photo(photo_bytes):
        if photo_bytes:
            base64_photo = base64.b64encode(photo_bytes).decode()
            return f'<img src="data:image/jpeg;base64,{base64_photo}" style="max-width:150px; border-radius:8px; border:1px solid #ccc;" />'
        return '<span style="color:gray;">No Photo</span>'

    st.subheader("🏢 Agencies - Maal Khareedna")

    sub_tab1, sub_tab2, sub_tab3, sub_tab4, sub_tab5 = st.tabs([
        "➕ Agency Add Karo",
        "📋 Agencies List",
        "💰 Kist Jama Karo",
        "📜 Purana Record (Archive)",
        "📊 Kul Udhaar Dashboard"
    ])

    # ==================== SUB-TAB 1: NAYI AGENCY ADD KARO ====================
    with sub_tab1:
        st.markdown("### Nayi Agency Add Karo")
        with st.form("nayi_agency_form", clear_on_submit=True):
            col_a1, col_a2 = st.columns(2)
            with col_a1:
                agency_name = st.text_input("Agency Ka Naam*")
                phone_num = st.text_input("Phone Number")
            with col_a2:
                address = st.text_input("Address")
                commission = st.number_input("Commission %", min_value=0.0, max_value=100.0, value=0.0, step=0.1)

            submit_agency = st.form_submit_button("Agency Save Karo", type="primary", use_container_width=True)
            if submit_agency:
                if agency_name and agency_name.strip():
                    if safe_execute("INSERT INTO agencies (name, phone, address, commission) VALUES (?,?,?,?)",
                              (agency_name.strip(), phone_num, address, commission), "Agency"):
                        conn.commit()
                        st.success(f"✔️ {agency_name} kamyabi se save ho gayi!")
                        st.rerun()
                else:
                    st.error("Agency ka naam likhna lazmi hai!")

    # ==================== SUB-TAB 2: AGENCIES LIST & ACTIVE BILLS ====================
    with sub_tab2:
        st.markdown("### 📋 Sab Agencies Aur Unke Active Bills")

        try:
            c.execute("SELECT id, name, phone, address, commission FROM agencies ORDER BY name")
            all_agencies = c.fetchall()
        except sqlite3.Error as e:
            st.error(f"⚠️ Agencies list load nahi ho saki: {e}")
            all_agencies = []

        if not all_agencies:
            st.info("Abhi koi agency saved nahi hai.")
        else:
            for ag_id, ag_name, ag_phone, ag_address, ag_comm in all_agencies:

                with st.expander(f"🏢 {ag_name} (Phone: {ag_phone or 'N/A'})"):

                    # --- SECTION 1: ADD NEW BILL WITH PHOTO + OCR BILL SCAN ---
                    st.markdown("#### 📑 Is Agency Ka Naya Bill Add Karo")

                    photo_mode = st.radio("Bill Ki Photo", ["📤 Upload Karein", "📷 Camera Se Khinchein"],
                                           horizontal=True, key=f"photo_mode_{ag_id}")
                    if photo_mode == "📷 Camera Se Khinchein":
                        b_img = st.camera_input("Bill Ki Photo Khinchein", key=f"b_cam_{ag_id}")
                    else:
                        b_img = st.file_uploader("Bill Ki Photo Upload Karein", type=["jpg", "png", "jpeg"], key=f"b_img_{ag_id}")

                    ocr_rows_key = f"ocr_rows_{ag_id}"

                    if b_img is not None:
                        if st.button("🔍 Bill Scan Karo (OCR)", key=f"scan_btn_{ag_id}"):
                            try:
                                img_bytes = b_img.getvalue()
                            except Exception:
                                img_bytes = None

                            if img_bytes:
                                with st.spinner("Bill scan ho raha hai..."):
                                    raw_text, err = camera_ocr.extract_raw_text(img_bytes)
                                if err:
                                    st.warning(err + " Neeche khali table mein khud likh sakte hain.")
                                    st.session_state[ocr_rows_key] = [{"item": "", "qty": 1.0, "rate": 0.0, "total": 0.0}]
                                else:
                                    guessed = camera_ocr.guess_bill_rows(raw_text)
                                    if not guessed:
                                        st.info("ℹ️ OCR ko bill mein saaf numbers nahi mile. Neeche khud likh sakte hain.")
                                        guessed = [{"item": "", "qty": 1.0, "rate": 0.0, "total": 0.0}]
                                    st.session_state[ocr_rows_key] = guessed

                    if ocr_rows_key in st.session_state:
                        st.warning("⚠️ **Preview & Confirm:** OCR (khaas kar kharab handwriting/Sindhi likhai par) 100% sahi nahi hota. Neeche har row dhyan se check/edit kar ke tabhi save karein.")
                        import pandas as _pd
                        edited_df = st.data_editor(
                            _pd.DataFrame(st.session_state[ocr_rows_key]),
                            num_rows="dynamic", key=f"editor_{ag_id}", width='stretch',
                            column_config={
                                "item": st.column_config.TextColumn("Item Name"),
                                "qty": st.column_config.NumberColumn("Qty", min_value=0.0),
                                "rate": st.column_config.NumberColumn("Rate", min_value=0.0),
                                "total": st.column_config.NumberColumn("Total (Rs.)", min_value=0.0),
                            })

                        suggested_total = float(edited_df["total"].sum()) if not edited_df.empty else 0.0
                        suggested_detail = "; ".join(
                            f"{r['item']} x{r['qty']:g} = Rs.{r['total']:,.0f}"
                            for _, r in edited_df.iterrows() if str(r.get('item', '')).strip()
                        )
                    else:
                        suggested_total = 0.0
                        suggested_detail = ""

                    with st.form(f"new_bill_form_{ag_id}", clear_on_submit=True):
                        col_b1, col_b2 = st.columns(2)
                        with col_b1:
                            b_num = st.text_input("Bill Number / Invoice No*", key=f"b_num_{ag_id}")
                            b_amt = st.number_input("Bill Ki Total Raqam (Rs.)", min_value=0.0, step=500.0,
                                                     value=suggested_total, key=f"b_amt_{ag_id}")
                        with col_b2:
                            b_det = st.text_input("Detail (e.g., Maal Detail)", value=suggested_detail, key=f"b_det_{ag_id}")
                            st.caption("📷 Photo upar wale section se ली जाएगी" if b_img is not None else "Photo abhi tak nahi li gayi (optional)")

                        if st.form_submit_button("💾 Bill Save Karo (Confirm)", use_container_width=True):
                            if b_num and b_num.strip() and b_amt > 0:
                                try:
                                    img_bytes = b_img.getvalue() if b_img is not None else None
                                except Exception:
                                    img_bytes = None
                                    st.warning("⚠️ Photo read nahi ho saki, bill photo ke bagair save ho raha hai.")

                                t_date = datetime.now().strftime("%Y-%m-%d %I:%M %p")
                                if safe_execute("INSERT INTO agency_v2_bills (agency_id, bill_number, date, total_amount, detail, bill_photo) VALUES (?,?,?,?,?,?)",
                                          (ag_id, b_num.strip(), t_date, b_amt, b_det, img_bytes), "Agency bill"):
                                    conn.commit()

                                    # Photo Google Drive ke AfzalStore/Photos folder mein bhi bhej dete hain
                                    # (agar connect hai) - fail ho to koi asar nahi, sirf local hi save rehta hai.
                                    if img_bytes:
                                        try:
                                            drive_filename = f"agency_bill_{ag_name}_{b_num.strip()}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
                                            gdrive.upload_photo_to_drive(img_bytes, drive_filename)
                                        except Exception:
                                            pass

                                    if ocr_rows_key in st.session_state:
                                        del st.session_state[ocr_rows_key]
                                    st.success(f"Bill No {b_num} kamyabi se save ho gaya!")
                                    st.rerun()
                            else:
                                st.error("❌ Bill Number aur Amount (0 se zyada) lazmi hain!")

                    # --- SECTION 2: LIVE / PENDING BILLS WITH PAYMENTS HISTORY ---
                    st.markdown("#### ⏳ Active Bills (Jo Rehte Hain)")
                    try:
                        # PERF FIX: latest 100 pending bills per agency - agar isse zyada
                        # pending bills hon (bohot bade dataset mein) to bhi page atkega nahi.
                        c.execute("SELECT id, bill_number, date, total_amount, paid_amount, detail, bill_photo FROM agency_v2_bills WHERE agency_id=? AND status='Pending' ORDER BY id DESC LIMIT 100", (ag_id,))
                        pending_bills = c.fetchall()
                    except sqlite3.Error as e:
                        st.warning(f"⚠️ Pending bills load nahi ho sakay: {e}")
                        pending_bills = []

                    if not pending_bills:
                        st.caption("Koi pending bill nahi hai.")
                    else:
                        for b_id, b_no, b_date, t_am, p_am, det, photo in pending_bills:
                            rem = t_am - p_am
                            col_p1, col_p2, col_p3 = st.columns([4, 3, 3])
                            with col_p1:
                                st.error(f"📄 **Bill No: {b_no}** | Date: {b_date}\n\nTotal: Rs. {t_am:,.0f} | Baaki: **Rs. {rem:,.0f}**")
                                st.caption(f"Detail: {det or 'N/A'}")
                            with col_p2:
                                st.markdown(render_photo(photo), unsafe_allow_html=True)
                            with col_p3:
                                if st.button("🗑️ Bill Delete", key=f"del_b_{b_id}"):
                                    ok1 = safe_execute("DELETE FROM agency_v2_payments WHERE bill_id=?", (b_id,), "Bill delete")
                                    ok2 = safe_execute("DELETE FROM agency_v2_bills WHERE id=?", (b_id,), "Bill delete")
                                    if ok1 and ok2:
                                        conn.commit()
                                        st.rerun()
                                    else:
                                        conn.rollback()

                            try:
                                c.execute("SELECT date, amount, detail, payment_mode FROM agency_v2_payments WHERE bill_id=? ORDER BY id DESC", (b_id,))
                                pay_history = c.fetchall()
                            except sqlite3.Error:
                                pay_history = []
                            if pay_history:
                                with st.expander(f"📜 Is Bill Ki Purani Kistien ({len(pay_history)})"):
                                    for p_date, p_amt, p_det, p_mode in pay_history:
                                        st.write(f"📅 **{p_date}** -> Rs. {p_amt:,.0f} via *{p_mode}* ({p_det})")
                            st.divider()

                    # --- SECTION 3: LIVE STOCK FROM ITEMS TABLE ---
                    st.markdown("#### 📦 Is Agency Ke Items Aur Live Stock")
                    try:
                        c.execute("SELECT name, stock FROM items WHERE agency_name = ?", (ag_name,))
                        ag_items = c.fetchall()
                    except sqlite3.Error:
                        ag_items = []

                    if not ag_items:
                        st.caption("Is agency ke naam par abhi koi item saved nahi hai.")
                    else:
                        for name, stock in ag_items:
                            if stock is not None and stock <= 0:
                                st.warning(f"❌ **{name}**: **Khatam (0 Stock)** ⚠️")
                            else:
                                st.info(f"✔️ **{name}**: Stock = {stock if stock is not None else 0:g}")

                    st.markdown("---")
                    if st.button("🗑️ Poori Agency Delete", key=f"del_full_ag_{ag_id}"):
                        ok1 = safe_execute("DELETE FROM agency_v2_bills WHERE agency_id=?", (ag_id,), "Agency delete")
                        ok2 = safe_execute("DELETE FROM agencies WHERE id=?", (ag_id,), "Agency delete")
                        if ok1 and ok2:
                            conn.commit()
                            st.rerun()
                        else:
                            conn.rollback()

    # ==================== SUB-TAB 3: KIST JAMA KARO ====================
    with sub_tab3:
        st.markdown("### 💰 Bill Chunker - Kist Jama Karo")

        try:
            c.execute("SELECT id, name FROM agencies ORDER BY name")
            ag_list = c.fetchall()
        except sqlite3.Error as e:
            st.error(f"⚠️ Agencies list load nahi ho saki: {e}")
            ag_list = []

        if not ag_list:
            st.warning("Pehle koi agency banayein.")
        else:
            ag_options = {f"{ag[1]}": ag[0] for ag in ag_list}
            selected_ag = st.selectbox("Agency Select Karein", list(ag_options.keys()))
            selected_ag_id = ag_options[selected_ag]

            try:
                c.execute("SELECT id, bill_number, total_amount, paid_amount FROM agency_v2_bills WHERE agency_id=? AND status='Pending' ORDER BY id DESC LIMIT 200", (selected_ag_id,))
                active_bills = c.fetchall()
            except sqlite3.Error as e:
                st.error(f"⚠️ Active bills load nahi ho sakay: {e}")
                active_bills = []

            if not active_bills:
                st.success("🎉 Is Agency ke saare bills pehle hi mukammal (Complete) hain!")
            else:
                bill_options = {f"Bill No: {b[1]} (Total: {b[2]} | Rehta Hai: {b[2]-b[3]})": b for b in active_bills}
                selected_bill_lbl = st.selectbox("🎯 Chuno Kis Bill Mein Paise Jama Karne Hain?", list(bill_options.keys()))

                selected_bill_row = bill_options[selected_bill_lbl]
                b_id, b_no, total_amt, paid_amt = selected_bill_row
                rem_amt = max(total_amt - max(paid_amt, 0.0), 0.0)

                with st.form("kist_submission_form"):
                    col_k1, col_k2 = st.columns(2)
                    with col_k1:
                        k_amt = st.number_input("Kitne Paise Jama Karne Hain? (Rs.)", min_value=0.0, max_value=float(rem_amt) if rem_amt > 0 else 0.0, step=500.0)
                        k_det = st.text_input("Detail / Remarks", value="Paid")
                    with col_k2:
                        k_mode = st.selectbox("💸 Kis Tareeqe Se Paise Diye?", ["Cash", "JazzCash", "EasyPaisa", "Bank Transfer"])

                    if st.form_submit_button("💰 Payment Save Karo", type="primary", use_container_width=True):
                        if k_amt > 0:
                            new_paid = paid_amt + k_amt
                            status_now = 'Completed' if new_paid >= total_amt else 'Pending'

                            current_datetime = datetime.now().strftime("%Y-%m-%d %I:%M %p")
                            current_date_only = datetime.now().strftime("%Y-%m-%d")

                            ok1 = safe_execute("INSERT INTO agency_v2_payments (bill_id, date, amount, detail, payment_mode) VALUES (?,?,?,?,?)",
                                      (b_id, current_datetime, k_amt, k_det, k_mode), "Payment")
                            ok2 = safe_execute("UPDATE agency_v2_bills SET paid_amount=?, status=? WHERE id=?", (new_paid, status_now, b_id), "Bill update")

                            ok3 = True
                            if k_mode == "Cash":
                                expense_msg = f"Agency Payment: {selected_ag} (Bill: {b_no})"
                                ok3 = safe_execute("INSERT INTO expenses (date, expense_type, amount, detail) VALUES (?, ?, ?, ?)",
                                          (current_date_only, "Agency Cash Paid", k_amt, expense_msg), "Expense entry")

                            if ok1 and ok2 and ok3:
                                conn.commit()
                                st.success(f"Rs. {k_amt:,.0f} ({k_mode}) Bill No {b_no} mein jama ho gaye!")
                                st.rerun()
                            else:
                                conn.rollback()
                                st.error("❌ Payment save nahi ho saka - kuch bhi save nahi hua (safety ke liye). Dobara try karein.")

    # ==================== SUB-TAB 4: 📜 PURANA RECORD (ARCHIVE) ====================
    with sub_tab4:
        st.markdown("### 📜 Clear Bills Aur Unka Mukammal Record")
        show_all_archive = st.checkbox("📜 Sab Purana Record Dikhao (dheema ho sakta hai)", key="ag_archive_all")
        archive_limit = 2000 if show_all_archive else 20

        try:
            c.execute("SELECT id, name FROM agencies ORDER BY name")
            ag_list_archive = c.fetchall()
        except sqlite3.Error as e:
            st.error(f"⚠️ Agencies list load nahi ho saki: {e}")
            ag_list_archive = []

        if not ag_list_archive:
            st.info("Abhi koi data majood nahi hai.")
        else:
            for ag_id, ag_name in ag_list_archive:
                try:
                    # PERF FIX: pehle YEH SAARI completed bills har agency ke liye load hoti
                    # thin (kai saal ka data ho to bohot heavy) - ab default sirf latest 20.
                    c.execute("SELECT id, bill_number, date, total_amount, detail, bill_photo FROM agency_v2_bills WHERE agency_id=? AND status='Completed' ORDER BY id DESC LIMIT ?", (ag_id, archive_limit))
                    comp_bills = c.fetchall()
                except sqlite3.Error:
                    comp_bills = []

                if comp_bills:
                    with st.expander(f"🏢 {ag_name} (Dikha Rahe: {len(comp_bills)})"):
                        for b_id, b_no, b_date, t_am, det, photo in comp_bills:
                            col_c1, col_c2 = st.columns([7, 3])
                            with col_c1:
                                st.success(f"🎉 **Bill No: {b_no} ( Mukammal Paid )**")
                                st.write(f"**Total Bill Raqam:** Rs. {t_am:,.0f} | **Bill Ki Date:** {b_date}")
                                block_det = det or 'N/A'
                                st.caption(f"**Detail:** {block_det}")

                                try:
                                    c.execute("SELECT date, amount, detail, payment_mode FROM agency_v2_payments WHERE bill_id=? ORDER BY id ASC", (b_id,))
                                    archived_payments = c.fetchall()
                                except sqlite3.Error:
                                    archived_payments = []
                                if archived_payments:
                                    st.markdown("**💰 Jama Shuda Kistion Ka Record:**")
                                    for p_date, p_amt, p_det, p_mode in archived_payments:
                                        st.caption(f"📅 **{p_date}** -> Rs. {p_amt:,.0f} via *{p_mode}* ({p_det})")
                            with col_c2:
                                st.markdown(render_photo(photo), unsafe_allow_html=True)
                            st.divider()

    # ==================== SUB-TAB 5: 📊 KUL UDHAAR DASHBOARD ====================
    with sub_tab5:
        st.markdown("### 📊 Tamam Agencies Ka Kul Udhaar Hisab")

        try:
            c.execute("SELECT SUM(total_amount), SUM(paid_amount) FROM agency_v2_bills WHERE status='Pending'")
            summary_row = c.fetchone()
            grand_total = summary_row[0] or 0.0
            grand_paid = summary_row[1] or 0.0
        except sqlite3.Error as e:
            st.error(f"⚠️ Dashboard load nahi ho saka: {e}")
            grand_total = grand_paid = 0.0
        grand_remaining = grand_total - grand_paid

        st.markdown(f"""
        <div style="background-color:#f8f9fa; border-left:5px solid #ff4b4b; padding:20px; border-radius:8px; margin-top:10px;">
            <table style="width:100%; border-collapse:collapse;">
                <tr>
                    <td style="font-size:16px; color:#555; padding: 8px 0;"><b>📦 Kul Active Bills Amount:</b></td>
                    <td style="font-size:18px; text-align:right; color:#333; padding: 8px 0;">Rs. {grand_total:,.0f}</td>
                </tr>
                <tr>
                    <td style="font-size:16px; color:#28a745; padding: 8px 0;"><b>✅ Kul Jama Shuda Raqam:</b></td>
                    <td style="font-size:18px; text-align:right; color:#28a745; padding: 8px 0;">Rs. {grand_paid:,.0f}</td>
                </tr>
                <tr style="border-top:2px solid #ddd;">
                    <td style="font-size:18px; color:#ff4b4b; padding-top:12px;"><b>🚨 Kul Baaki Raqam (Payable):</b></td>
                    <td style="font-size:22px; text-align:right; color:#ff4b4b; padding-top:12px;"><b>Rs. {grand_remaining:,.0f}</b></td>
                </tr>
            </table>
        </div>
        """, unsafe_allow_html=True)

    conn.close()
