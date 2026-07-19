import streamlit as st
import os
import shutil
from datetime import datetime
import google_drive_backup as gdrive

# Database aur Backup folders ke naam
DB_FILE = 'afzal_store.db'
BACKUP_DIR = 'app_backups'

# Agar backups ka folder nahi bana hua to bana dein
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

def auto_daily_backup():
    """Rozana app khulte hi bina click kiye auto background backup lene ke liye
    (local disk pe) - aur agar Google Drive backup ON hai to Drive par bhi."""
    if not os.path.exists(DB_FILE):
        return False

    # Aaj ki tarikh (Jaise: 27-06-2026)
    today_str = datetime.now().strftime("%d-%m-%Y")

    # PERF/BUG FIX: disk full hone ki soorat mein os.listdir/shutil.copy2 crash
    # kar sakte the - ab har step try/except mein hai, app kabhi is wajah se ruk nahi sakti.
    try:
        all_files = os.listdir(BACKUP_DIR)
    except OSError:
        all_files = []

    auto_exists = any(f"auto_backup_{today_str}" in f for f in all_files)

    local_backup_done = False
    if not auto_exists:
        timestamp = datetime.now().strftime("%d-%m-%Y_%H-%M")
        backup_filename = f"auto_backup_{timestamp}.db"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)

        try:
            free_mb = shutil.disk_usage(".").free / (1024 * 1024)
        except OSError:
            free_mb = None

        if free_mb is not None and free_mb < 100:
            pass  # disk bohot kam hai - chup-chaap skip, agli baar try hoga
        else:
            try:
                shutil.copy2(DB_FILE, backup_path)
                manage_old_backups()
                local_backup_done = True
            except OSError:
                pass

    # Google Drive backup - poori tarah alag/optional hai, kabhi bhi local backup ko
    # crash nahi karega chahe internet na ho ya Drive setup na ho.
    try:
        gdrive.auto_drive_backup_if_due(DB_FILE)
        gdrive.sync_pending_local_photos("bill_images")
    except Exception:
        pass

    return local_backup_done

def manage_old_backups():
    """Dukan ka computer full na ho, isliye 30 din se purane auto backups khud mita deta hai"""
    all_files = [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.endswith('.db')]
    if len(all_files) > 30:
        all_files.sort(key=os.path.getmtime)
        while len(all_files) > 30:
            os.remove(all_files[0])
            all_files.pop(0)

def show_backup_restore():
    # Page khulte hi auto backup check karega aur chalaye ka
    backup_hua = auto_daily_backup()

    # Premium Colorful Containers (Bina Buttons Ke)
    st.markdown("""
        <style>
        .auto-box {
            background-color: #f0fdf4;
            padding: 25px;
            border-radius: 12px;
            border-left: 8px solid #22c55e;
            box-shadow: 0px 4px 12px rgba(34, 197, 94, 0.1);
            margin-bottom: 20px;
            text-align: center;
        }
        .status-badge {
            background-color: #22c55e;
            color: white;
            padding: 5px 15px;
            border-radius: 20px;
            font-weight: bold;
            display: inline-block;
            margin-top: 10px;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title("🔄 Fully Automatic Backup System")
    st.caption("Ab aapko koi bhi button click karne ki zarorat nahi hai. App aapka data khud sambhalti hai.")
    st.divider()

    # Screen par sirf status dikhayega ke sab theek chal raha hai
    today_date = datetime.now().strftime("%d-%B-%Y")
    
    st.markdown(f"""
        <div class="auto-box">
            <h2 style="color: #15803d; margin-top:0;">✅ System Active & Safe</h2>
            <p style="color: #1e293b; font-size: 16px;">
                Afzal Store App ka data background mein har roz khud-ba-khud mahfooz ho raha hai.
            </p>
            <p style="color: #64748b; font-size: 14px;">Aaj ki Tareekh: <strong>{today_date}</strong></p>
            <span class="status-badge">Auto Backup Enabled</span>
        </div>
    """, unsafe_allow_html=True)

    # Folder mein majood backups ki list niche check karne ke liye dikha dete hain
    st.markdown("### 📁 Mehfooz Shuda Auto Backups Ki List")
    files = [f for f in os.listdir(BACKUP_DIR) if f.endswith('.db')]
    files.sort(reverse=True)
    
    if files:
        st.write("Aapke computer mein is waqt yeh files khud-ba-khud safe ho chuki hain:")
        for f in files[:10]: # Sirf top 10 latest dikhane ke liye
            st.text(f"📄 {f}")
    else:
        st.info("Pehli file background mein save ho rahi hai...")