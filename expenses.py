import streamlit as st
import pandas as pd
from datetime import datetime
import os
import sqlite3
from vc_management import show_vc_module

def show_expenses(get_db):
    # --- 🛠️ FOOLPROOF BUG FIX (Database Columns Check) ---
    try:
        conn = get_db()
        c = conn.cursor()
        try:
            c.execute("SELECT current_balance FROM customers LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE customers ADD COLUMN current_balance REAL DEFAULT 0.0")
            conn.commit()
        try:
            c.execute("SELECT image_path FROM expenses LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE expenses ADD COLUMN image_path TEXT DEFAULT ''")
            conn.commit()
        conn.close()
    except Exception:
        pass

    # --- STYLING (Purple Tabs) ---
    st.markdown("""
    <style>
        button[data-baseweb="tab"], .stTabs button, [role="tab"] {
            background-color: #f1f5f9 !important;
            color: #475569 !important;
            border-radius: 8px 8px 0px 0px !important;
            padding: 10px 24px !important;
            font-weight: 600 !important;
            border: 1px solid #e2e8f0 !important;
        }
        button[data-baseweb="tab"][aria-selected="true"], .stTabs button[aria-selected="true"] {
            background: linear-gradient(135deg, #667eea, #764ba2) !important;
            color: white !important;
            box-shadow: 0px 4px 12px rgba(102, 126, 234, 0.4) !important;
        }
        .expense-row {
            background-color: #f8fafc;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 10px;
            border-left: 5px solid #667eea;
        }
    </style>
    """, unsafe_allow_html=True)

    if not os.path.exists("bill_images"):
        os.makedirs("bill_images")

    st.header("⚡ Expenses & Personal Cash Management")
    tab1, tab2, tab3 = st.tabs(["Naya Record Darj Karein", "Kharchon Aur Cash Ki Report", "🤝 VC (Committee)"])
    
    with tab1:
        st.subheader("Nayi Entry Add Karo")
        
        expense_type = st.selectbox("Kism Chunyein", [
            "Dukan: Worker ki Dihadi / Salary 👥", 
            "Dukan: Bijli ka Bill ⚡", 
            "Dukan: Gas ka Bill 🔥", 
            "Dukan: Chaki Maintenance 🔧", 
            "Dukan: Salary Se Investment 💰",          
            "Dukan: Personal Use Ke Liye Nikale 💸",    
            "Ghar: Bachon ki School Fees 📚",
            "Ghar: Petrol (Bike/Gari) ⛽",
            "Ghar: Khane Peene ka Saaman / Raashan 🍏",
            "Mutafariq / Doosre Kharche 🏪"
        ])
        
        conn = get_db()
        worker_settlement = False
        selected_worker_name = ""
        purana_udhaar = 0.0
        
        if "Worker ki Dihadi" in expense_type:
            st.info("🔄 Worker ki Salary aur Udhaar Khatte ko aapas me jorne ka system active hai.")
            try:
                workers_df = pd.read_sql("SELECT name, current_balance FROM customers ORDER BY name ASC", conn)
            except Exception:
                workers_df = pd.DataFrame(columns=['name', 'current_balance'])
            
            if not workers_df.empty:
                selected_worker_name = st.selectbox("Udhaar Khatta se Worker ka naam chuno:", ["-- Worker Select Karein --"] + list(workers_df['name']))
                if selected_worker_name != "-- Worker Select Karein --":
                    worker_settlement = st.checkbox("⚠️ Kya is salary me se worker ka purana udhaar/saaman/advance kaatna (saaf karna) hai?", value=True)
                    purana_udhaar = float(workers_df[workers_df['name'] == selected_worker_name]['current_balance'].values[0] or 0)
                    st.warning(f"📋 {selected_worker_name} ka Udhaar Khatta me abhi kul Rs. {purana_udhaar:,.0f} baaki hai.")
        
        amount = st.number_input("Raqam / Total Amount (Rs.)", min_value=0.0, step=100.0)
        detail = st.text_area("Mazeed Detail (Tafseel)", placeholder="Jaise: Asif ki June mahine ki total salary...")
        
        uploaded_file = None
        if "Bijli ka Bill" in expense_type or "Gas ka Bill" in expense_type:
            uploaded_file = st.file_uploader(f"📸 Tasveer Upload Karein", type=["jpg", "jpeg", "png"])
            
        if st.button("Record Save Karo", type="primary"):
            c = conn.cursor()
            date_str = datetime.now().strftime("%Y-%m-%d")
            
            final_detail = detail
            if "Worker ki Dihadi" in expense_type and selected_worker_name != "-- Worker Select Karein --":
                final_detail = f"Worker: {selected_worker_name} | Total Salary Fixed: Rs. {amount}. " + detail
                if worker_settlement:
                    final_detail += f" [Udhaar Khatta se Rs. {purana_udhaar} settle kiye]."
            
            saved_image_path = ""
            if uploaded_file is not None:
                saved_image_path = f"bill_images/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_file.name}"
                with open(saved_image_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                    
            try:
                c.execute("INSERT INTO expenses (expense_type, amount, detail, date, image_path) VALUES (?, ?, ?, ?, ?)",
                          (expense_type, amount, final_detail, date_str, saved_image_path))
                if "Worker ki Dihadi" in expense_type and worker_settlement and selected_worker_name != "-- Worker Select Karein --":
                    c.execute("UPDATE customers SET current_balance = 0.0 WHERE name = ?", (selected_worker_name,))
                conn.commit()
                st.success("Record aur Udhaar Khatta kamyabi se update ho gaya!")
                st.rerun()
            except Exception as e:
                st.error(f"Error saving data: {e}")
            finally:
                conn.close()
                
    with tab2:
        st.subheader("📊 Report & Analytics")
        conn = get_db()
        try:
            df = pd.read_sql("SELECT * FROM expenses ORDER BY id DESC", conn)
        except:
            df = pd.DataFrame()
        
        if not df.empty:
            # --- 🚀 NEW SYNC FEATURE: Smart Calculation Engine ---
            df['is_investment'] = df['expense_type'].apply(lambda x: "Investment" in str(x))
            
            total_ghar = df[df['expense_type'].str.contains('Ghar:', na=False)]['amount'].sum()
            total_dukan_exp = df[df['expense_type'].str.contains('Dukan:', na=False) & ~df['expense_type'].str.contains('Investment', na=False) & ~df['expense_type'].str.contains('Personal Use', na=False)]['amount'].sum()
            total_investment = df[df['is_investment'] == True]['amount'].sum()
            total_drawings = df[df['expense_type'].str.contains('Personal Use', na=False)]['amount'].sum()
            total_net_exp = (total_ghar + total_dukan_exp) - total_investment + total_drawings

            st.markdown(f"""
            <div style="display: flex; gap: 10px; margin-bottom: 25px; flex-wrap: wrap;">
                <div style="flex: 1; min-width: 180px; background: linear-gradient(135deg, #667eea, #764ba2); padding: 15px; border-radius: 12px; color: white;">
                    <p style="margin: 0; font-size: 13px; opacity: 0.8;">Net Kharcha Effect</p>
                    <h3 style="margin: 5px 0 0 0; font-size: 20px;">Rs. {total_net_exp:,.0f}</h3>
                </div>
                <div style="flex: 1; min-width: 180px; background: linear-gradient(135deg, #43e97b, #38f9d7); padding: 15px; border-radius: 12px; color: #1e293b;">
                    <p style="margin: 0; font-size: 13px; font-weight: bold; opacity: 0.8;">👥 Total Worker & Dukan Expense</p>
                    <h3 style="margin: 5px 0 0 0; font-size: 20px; font-weight: bold;">Rs. {total_dukan_exp:,.0f}</h3>
                </div>
                <div style="flex: 1; min-width: 180px; background: linear-gradient(135deg, #f6d365, #fda085); padding: 15px; border-radius: 12px; color: #1e293b;">
                    <p style="margin: 0; font-size: 13px; font-weight: bold; opacity: 0.8;">💼 Salary Investment</p>
                    <h3 style="margin: 5px 0 0 0; font-size: 20px; font-weight: bold;">Rs. {total_investment:,.0f}</h3>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            for idx, row in df.iterrows():
                is_worker = "Worker" in str(row['expense_type'])
                border_color = "#43e97b" if is_worker else "#667eea"
                img_html = "<br><span style='color:#764ba2; font-size:12px;'>📸 Tasveer Uploaded</span>" if row.get('image_path') and os.path.exists(str(row['image_path'])) else ""
                
                st.markdown(f"""
                <div class="expense-row" style="border-left: 5px solid {border_color};">
                    <table style="width:100%; border:none;">
                        <tr>
                            <td style="width:35%;"><b>{row['expense_type']}</b>{img_html}<br><small style='color:gray;'>📅 {row['date']}</small></td>
                            <td style="width:20%; color:#764ba2; font-size:16px;"><b>Rs. {row['amount']:,.0f}</b></td>
                            <td style="width:45%; color:#475569;">ℹ️ {row['detail']}</td>
                        </tr>
                    </table>
                </div>
                """, unsafe_allow_html=True)
                
                if row.get('image_path') and os.path.exists(str(row['image_path'])):
                    with st.expander("👁️ Tasveer Dekhein"):
                        st.image(str(row['image_path']), use_container_width=True)
        else:
            st.info("Koi record nahi mila.")
        conn.close()

    with tab3:
        show_vc_module(get_db)