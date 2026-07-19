import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

def get_db():
    conn = sqlite3.connect('afzal_store.db', check_same_thread=False, timeout=10)
    return conn

# Naye Khareji Defaulters ke liye table setup
def create_khareji_tables():
    conn = get_db()
    c = conn.cursor()
    # Main Entries Table
    c.execute('''CREATE TABLE IF NOT EXISTS khareji_defaulters
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, total_amount REAL, 
                  remaining_amount REAL, status TEXT, date_added TEXT)''')
    # Payments Logs Table
    c.execute('''CREATE TABLE IF NOT EXISTS khareji_payments
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, defaulter_id INTEGER, 
                  amount_paid REAL, date_paid TEXT, current_remaining REAL)''')
    conn.commit()
    conn.close()

create_khareji_tables()

def show_defaulter():
    # Premium Custom CSS for Defaulter Section
    st.markdown("""
        <style>
        div.stButton > button[kind="primary"] {
            background-color: #e74c3c !important;
            color: white !important;
            border-radius: 8px !important;
            border: 2px solid #c0392b !important;
            font-weight: bold !important;
            box-shadow: 0px 4px 6px rgba(0,0,0,0.1) !important;
        }
        div.stButton > button[kind="secondary"] {
            background-color: #2ecc71 !important;
            color: white !important;
            border-radius: 8px !important;
            border: 2px solid #27ae60 !important;
            font-weight: bold !important;
        }
        label[data-testid="stWidgetLabel"] {
            color: #2c3e50 !important;
            font-weight: bold !important;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title("🚫 Defaulter List - Manual + Auto")

    if not os.path.exists('defaulter_photos'):
        os.makedirs('defaulter_photos')

    conn = get_db()

    # Tabs Management
    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Defaulter List & History", 
        "➕ Manual Add Karo", 
        "💰 Payment Jama Karo",
        "📁 Alag Khareji List (Saalo Puraane)"
    ])

    # ================= TAB 1: DEFAULTER LIST DIKHAO =================
    with tab1:
        st.markdown("""
            <div style='background-color:#fce4d6; padding:12px; border-radius:8px; border-left:6px solid #e67e22; margin-bottom:15px;'>
                <p style='margin:0; font-weight:bold; color:#d35400;'>⚠️ Alert: Jin logon ne 6 mahine se payment nahi ki ya jinhe manually add kiya gaya hai:</p>
            </div>
        """, unsafe_allow_html=True)

        six_months_ago = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

        defaulters_df = pd.read_sql(f'''
            SELECT
                c.name as Customer,
                MAX(c.phone) as Phone,
                SUM(CASE WHEN u.type='udhaar' THEN u.amount ELSE -u.amount END) as Baaki,
                MAX(CASE WHEN u.type='jama' THEN u.date ELSE NULL END) as Last_Payment
            FROM customers c
            JOIN udhaar u ON c.id = u.customer_id
            GROUP BY c.name
            HAVING Baaki > 0.01 AND (Last_Payment IS NULL OR Last_Payment < '{six_months_ago}')

            UNION

            SELECT
                customer_name as Customer,
                phone as Phone,
                remaining_baaki as Baaki,
                MAX(jama_date) as Last_Payment
            FROM defaulter_payments
            WHERE remaining_baaki > 0.01
            GROUP BY customer_name
            ORDER BY Baaki DESC
        ''', conn)

        if not defaulters_df.empty:
            st.dataframe(defaulters_df, use_container_width=True, hide_index=True)
            col1, col2 = st.columns(2)
            with col1: st.metric("Total Defaulters", f"{len(defaulters_df)}")
            with col2: st.metric("Total Baaki Raqam", f"Rs. {defaulters_df['Baaki'].sum():,.2f}")
        else:
            st.success("✅ Mubarak Ho! Koi defaulter nahi hai is waqt.")

        st.divider()
        st.markdown("### 🔍 Kisi Defaulter Ki Payment History Dekhein")
        cust_list = defaulters_df['Customer'].tolist() if not defaulters_df.empty else []
        selected_cust = st.selectbox("👤 Customer Ka Name Chunein", cust_list, key="def_hist_select")
        
        if selected_cust:
            history_df = pd.read_sql('''
                SELECT jama_date as Date, jama_amount as Jama_Kiya,
                       remaining_baaki as Baaki_Reh_Gaya, remark as Remark, photo_path as Photo
                FROM defaulter_payments WHERE customer_name =? ORDER BY jama_date DESC
            ''', conn, params=(selected_cust,))
            if not history_df.empty:
                st.dataframe(history_df[['Date', 'Jama_Kiya', 'Baaki_Reh_Gaya', 'Remark']], use_container_width=True, hide_index=True)
                st.markdown("#### 📸 Jama Shuda Payment Raseed / Photos:")
                img_cols = st.columns(4)
                col_idx = 0
                for idx, row in history_df.iterrows():
                    if row['Photo'] and os.path.exists(row['Photo']):
                        with img_cols[col_idx % 4]:
                            st.image(row['Photo'], caption=f"🗓️ {row['Date']}\n💵 Rs.{row['Jama_Kiya']:,.0f}", use_container_width=True)
                        col_idx += 1
                if col_idx == 0: st.info("Is customer ki koi tasveer record mein nahi hai.")
            else:
                st.info("Is customer ki abhi tak koi payment history record mein nahi hai.")

    # ================= TAB 2: MANUAL ADD KARO =================
    with tab2:
        st.markdown("<h3 style='color: #c0392b;'>➕ Naya Defaulter Manually Shamil Karen</h3>", unsafe_allow_html=True)
        with st.form("manual_defaulter", clear_on_submit=True):
            name = st.text_input("👤 Customer Ka Naam*")
            phone = st.text_input("📞 Phone Number (Optional)")
            total_baaki = st.number_input("💰 Total Baaki Amount (Rs.)*", min_value=0.0, step=100.0)
            remark = st.text_area("🗒️ Remark / Wajah", value="Manual entry")
            photo = st.file_uploader("📸 Koi Photo Ya Parchii Upload Karo", type=['jpg', 'png', 'jpeg'])

            submit = st.form_submit_button("🔴 Defaulter List Mein Shamil Karo", type="primary")
            if submit:
                if name.strip() and total_baaki > 0:
                    photo_path = None
                    if photo:
                        photo_path = f"defaulter_photos/{name.strip()}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
                        with open(photo_path, "wb") as f: f.write(photo.getbuffer())

                    c = conn.cursor()
                    c.execute('''
                        INSERT INTO defaulter_payments
                        (customer_name, phone, total_baaki, jama_amount, remaining_baaki, jama_date, photo_path, remark)
                        VALUES (?,?,?, 0,?,?,?,?)
                    ''', (name.strip(), phone, total_baaki, total_baaki, datetime.now().strftime("%Y-%m-%d"), photo_path, remark))
                    conn.commit()
                    st.success(f"✔️ {name.strip()} ko defaulter list mein kamiyabi se add kar diya gaya!")
                    st.rerun()
                else:
                    st.error("❌ Galti: Customer ka naam aur Baaki raqam likhna lazmi hai!")

    # ================= TAB 3: PAYMENT JAMA KARO =================
    with tab3:
        st.markdown("<h3 style='color: #27ae60;'>💵 Defaulter Se Baaki Payment Vasool Karen</h3>", unsafe_allow_html=True)
        
        all_defaulters_df = pd.read_sql('''
            SELECT DISTINCT customer_name as name FROM defaulter_payments WHERE remaining_baaki > 0.01
            UNION
            SELECT name FROM customers WHERE id IN (
                SELECT customer_id FROM udhaar u GROUP BY customer_id
                HAVING SUM(CASE WHEN u.type='udhaar' THEN u.amount ELSE -u.amount END) > 0.01
            )
        ''', conn)
        all_defaulters = all_defaulters_df['name'].tolist() if not all_defaulters_df.empty else []

        if all_defaulters:
            cust = st.selectbox("👤 Kis Defaulter Se Payment Mili?*", all_defaulters, key="pay_jama_cust_select")
            curr_baaki_df = pd.read_sql('''
                SELECT remaining_baaki FROM defaulter_payments WHERE customer_name =? ORDER BY id DESC LIMIT 1
            ''', conn, params=(cust,))
            
            if curr_baaki_df.empty:
                curr_baaki_df = pd.read_sql('''
                    SELECT SUM(CASE WHEN u.type='udhaar' THEN u.amount ELSE -u.amount END) as remaining_baaki
                    FROM udhaar u 
                    JOIN customers c ON u.customer_id = c.id 
                    WHERE c.name =?
                ''', conn, params=(cust,))

            current_baaki = curr_baaki_df['remaining_baaki'].iloc[0] if not curr_baaki_df.empty else 0.0
            st.markdown(f"<div style='background-color:#e8f8f5; padding:10px; border-radius:5px; border-left:5px solid #2ecc71;'>Iska Total Baaki Udhaar: <strong style='color:#27ae60; font-size:18px;'>Rs. {current_baaki:,.2f}</strong></div>", unsafe_allow_html=True)
            st.divider()

            with st.form("jama_payment", clear_on_submit=True):
                jama_amount = st.number_input("💵 Kitni Raqam Jama Kar Raha Hai?*", min_value=1.0, max_value=float(current_baaki), step=50.0)
                jama_date = st.date_input("📅 Kis Tareekh Ko Jama Kiye*", value=datetime.now())
                photo = st.file_uploader("📸 Raseed / Payment Ki Photo Upload Karen", type=['jpg', 'png', 'jpeg'])
                remark = st.text_input("🗒️ Short Note / Remark", value="Partial payment")

                submit_payment = st.form_submit_button("🟢 Vasool Shuda Record Save Karo", type="secondary")
                if submit_payment:
                    remaining = current_baaki - jama_amount
                    photo_path = None
                    if photo:
                        photo_path = f"defaulter_photos/{cust}_payment_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
                        with open(photo_path, "wb") as f: f.write(photo.getbuffer())

                    c = conn.cursor()
                    c.execute('''
                        INSERT INTO defaulter_payments
                        (customer_name, phone, total_baaki, jama_amount, remaining_baaki, jama_date, photo_path, remark)
                        VALUES (?,?,?,?,?,?,?,?)
                    ''', (cust, "", current_baaki, jama_amount, remaining, jama_date.strftime("%Y-%m-%d"), photo_path, remark))
                    conn.commit()
                    st.success(f"✔️ Rs. {jama_amount:,.2f} Jama ho gaye! Ab baqi udhaar Rs. {remaining:,.2f} reh gaya.")
                    st.rerun()
        else: st.info("Mubarak ho! Is waqt koi bhi customer defaulter list mein nahi hai.")

    # ================= TAB 4: ALAG KHAREJI LIST (UPDATED FOR TOTAL DISPLAY) =================
    with tab4:
        st.markdown("<h3 style='color: #8e44ad;'>📁 Saalo Puraane Udhaar / Khareji Defaulters List</h3>", unsafe_allow_html=True)
        st.caption("Ais list ka app ke baki data ya kiryana/chakki system se koi taluq nahi hai. Ye aapka apna personal record hai.")

        # Database se live sub ka total pehle calculate kar lete hain
        totals_df = pd.read_sql("SELECT SUM(total_amount) as total_p, SUM(remaining_amount) as total_r FROM khareji_defaulters", conn)
        total_pehle_ka = totals_df['total_p'].iloc[0] if totals_df['total_p'].iloc[0] else 0.0
        total_mojuda_bakaya = totals_df['total_r'].iloc[0] if totals_df['total_r'].iloc[0] else 0.0

        # Barabar barabar show karne ke liye columns banaye hain
        col_radio, col_totals = st.columns([3, 2])

        with col_radio:
            khareji_mode = st.radio("Mano Chunein:", ["📋 List Dekho Aur Payments", "➕ Naya Banda Add Karo", "⚙️ Edit / Delete Entries"], horizontal=True)

        with col_totals:
            # Edit option ke bilkul barabar mein live metric total boxes dikhenge
            st.markdown(
                f"""
                <div style="display: flex; gap: 10px; margin-top: 5px; justify-content: flex-end;">
                    <div style="background-color: #f1f2f6; padding: 6px 12px; border-radius: 6px; border: 1px solid #ced6e0; text-align: center;">
                        <span style="font-size: 11px; color: #57606f; font-weight: bold; display: block;">KUL BAAKI</span>
                        <strong style="font-size: 14px; color: #2f3542;">Rs. {total_pehle_ka:,.0f}</strong>
                    </div>
                    <div style="background-color: #ffeaa7; padding: 6px 12px; border-radius: 6px; border: 1px solid #eccc68; text-align: center;">
                        <span style="font-size: 11px; color: #b7791f; font-weight: bold; display: block;">MOJUDA BAKAYA</span>
                        <strong style="font-size: 14px; color: #d35400;">Rs. {total_mojuda_bakaya:,.0f}</strong>
                    </div>
                </div>
                """, 
                unsafe_allow_html=True
            )

        c = conn.cursor()
        
        # 1. ADD NEW BANDA
        if khareji_mode == "➕ Naya Banda Add Karo":
            st.markdown("#### 👤 Nayi Personal Entry Likhein")
            with st.form("add_khareji_form", clear_on_submit=True):
                k_name = st.text_input("Nam Likhein*")
                k_amount = st.number_input("Kul Kitne Paise Baaki Hain (Rs.)*", min_value=1.0, step=500.0)
                k_date = st.date_input("Udhaar Ki Date / Sal", value=datetime.now())
                
                k_submit = st.form_submit_button("💾 List Mein Save Karo", type="secondary")
                if k_submit and k_name.strip():
                    c.execute("INSERT INTO khareji_defaulters (name, total_amount, remaining_amount, status, date_added) VALUES (?, ?, ?, 'Pending', ?)",
                              (k_name.strip().title(), k_amount, k_amount, k_date.strftime("%Y-%m-%d")))
                    conn.commit()
                    st.success(f"✔️ {k_name} kamiyabi se alag list mein shamil ho gaya!")
                    st.rerun()

        # 2. LIST VIEW AND PAYMENT MANAGEMENT
        elif khareji_mode == "📋 List Dekho Aur Payments":
            df_khareji = pd.read_sql("SELECT id, name as 'Customer Name', total_amount as 'Pehle Ka Kul Baaki', remaining_amount as 'Mojuda Bakaya', status as 'Status', date_added as 'Shuru Ki Date' FROM khareji_defaulters ORDER BY id DESC", conn)
            
            if df_khareji.empty:
                st.info("Abhi tak is list mein koi naam save nahi kiya gaya.")
            else:
                def style_status(val):
                    color = '#27ae60' if val == 'Complete' else '#e74c3c'
                    return f'color: {color}; font-weight: bold;'
                
                st.markdown("#### 📑 Mukammal Khareji List")
                st.dataframe(df_khareji.style.map(style_status, subset=['Status']), use_container_width=True, hide_index=True)

                st.divider()
                st.markdown("#### 💰 Khareji Bande Ki Raqam Jama Karo (Partial/Installment)")
                
                active_khareji = pd.read_sql("SELECT id, name, remaining_amount FROM khareji_defaulters WHERE remaining_amount > 0", conn)
                if not active_khareji.empty:
                    khareji_options = [f"{row['name']} (Rem: Rs. {row['remaining_amount']:,.0f}) | ID:{row['id']}" for _, row in active_khareji.iterrows()]
                    selected_k = st.selectbox("Banda Chunein", khareji_options)
                    
                    k_id = int(selected_k.split("| ID:")[1])
                    k_rem = float(selected_k.split("(Rem: Rs. ")[1].split(")")[0].replace(',', ''))
                    
                    col_p1, col_p2 = st.columns(2)
                    with col_p1:
                        p_amount = st.number_input("Kitne Paise Jama Kar Diye?", min_value=1.0, max_value=k_rem, step=100.0)
                    with col_p2:
                        p_date = st.date_input("Jama Karne Ki Tarikh", value=datetime.now(), key="kh_p_date")
                    
                    if st.button("🟢 Payment Entry Save Karo", type="primary"):
                        new_rem = k_rem - p_amount
                        new_status = "Complete" if new_rem <= 0 else "Pending"
                        
                        c.execute("INSERT INTO khareji_payments (defaulter_id, amount_paid, date_paid, current_remaining) VALUES (?, ?, ?, ?)",
                                  (k_id, p_amount, p_date.strftime("%Y-%m-%d"), new_rem))
                        c.execute("UPDATE khareji_defaulters SET remaining_amount=?, status=? WHERE id=?", (new_rem, new_status, k_id))
                        conn.commit()
                        st.success(f"✔️ Rs. {p_amount} jama ho gaye! Naya bakaya: Rs. {new_rem}. Status: {new_status}")
                        st.rerun()
                else:
                    st.success("Sab ki payments complete hain!")

                st.divider()
                st.markdown("#### 🗓️ Puraani Vasooli Ka Record (Payment History Logs)")
                df_logs = pd.read_sql('''SELECT kd.name as 'Name', kp.amount_paid as 'Jama Kiye', 
                                         kp.date_paid as 'Kis Din Diye', kp.current_remaining as 'Us Din Ka Baqi' 
                                         FROM khareji_payments kp 
                                         JOIN khareji_defaulters kd ON kp.defaulter_id = kd.id 
                                         ORDER BY kp.id DESC''', conn)
                if not df_logs.empty:
                    st.dataframe(df_logs, use_container_width=True, hide_index=True)

        # 3. EDIT & DELETE SYSTEM
        elif khareji_mode == "⚙️ Edit / Delete Entries":
            df_manage = pd.read_sql("SELECT id, name, total_amount, remaining_amount FROM khareji_defaulters", conn)
            if df_manage.empty:
                st.info("Koi entries majood nahi hain.")
            else:
                manage_list = [f"{r['name']} (ID:{r['id']})" for _, r in df_manage.iterrows()]
                selected_manage = st.selectbox("Kisi Entry Ko Chunein (Edit/Delete Ke Liye)", manage_list)
                m_id = int(selected_manage.split("(ID:")[1].replace(")", ""))
                
                c.execute("SELECT name, total_amount, remaining_amount FROM khareji_defaulters WHERE id=?", (m_id,))
                row_details = c.fetchone()
                
                st.markdown("---")
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    new_edit_name = st.text_input("Naam Change Karein", value=row_details[0])
                    new_edit_total = st.number_input("Pehle Ka Kul Baaki Change Karein", value=float(row_details[1]))
                with col_e2:
                    new_edit_rem = st.number_input("Mojuda Bakaya Change Karein", value=float(row_details[2]))
                
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("📝 Tabdeeli (Edit) Save Karo", use_container_width=True):
                        e_status = "Complete" if new_edit_rem <= 0 else "Pending"
                        c.execute("UPDATE khareji_defaulters SET name=?, total_amount=?, remaining_amount=?, status=? WHERE id=?",
                                  (new_edit_name.strip(), new_edit_total, new_edit_rem, e_status, m_id))
                        conn.commit()
                        st.success("✔️ Entry kamiyabi se update ho gayi!")
                        st.rerun()
                with col_b2:
                    if st.button("❌ Yeh Record Hamesha K Liye Delete Karo", type="primary", use_container_width=True):
                        c.execute("DELETE FROM khareji_defaulters WHERE id=?", (m_id,))
                        c.execute("DELETE FROM khareji_payments WHERE defaulter_id=?", (m_id,))
                        conn.commit()
                        st.warning("🗑️ Record ko database se mita diya gaya.")
                        st.rerun()

    conn.close()