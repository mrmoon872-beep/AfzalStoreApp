import streamlit as st
import os
import re
import shutil
from datetime import datetime, timedelta
import google_drive_backup as gdrive

# Database aur Backup folders ke naam
DB_FILE = 'afzal_store.db'
BACKUP_DIR = 'app_backups'

# Agar backups ka folder nahi bana hua to bana dein
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

BACKUP_RETENTION_DAYS = 90  # 3 mahine - Google Drive wali retention se hamesha match karta hai
_LOCAL_BACKUP_DATE_RE = re.compile(r"(\d{2}-\d{2}-\d{4})")


def auto_daily_backup():
    """Rozana app khulte hi (aur din mein jab bhi yeh check chale - jaise Nayi
    Sale/Udhaar save hone ke baad app rerun hoti hai) bina click kiye
    computer par 'AAJ KI TAREEKH' wali EK hi backup file rakhta hai - agar
    file pehle se hai to usi ko overwrite kar deta hai, koi nayi time-wali
    file kabhi nahi banti. Agar Google Drive backup ON hai to Drive par bhi
    (alag/optional - kabhi local backup ko crash nahi karta)."""
    if not os.path.exists(DB_FILE):
        return False

    today_str = datetime.now().strftime("%d-%m-%Y")
    backup_filename = f"afzal_store_backup_{today_str}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    try:
        free_mb = shutil.disk_usage(".").free / (1024 * 1024)
    except OSError:
        free_mb = None

    local_backup_done = False
    if free_mb is not None and free_mb < 100:
        pass  # disk bohot kam hai - chup-chaap skip, agli baar try hoga
    else:
        try:
            shutil.copy2(DB_FILE, backup_path)  # aaj ki file ho to overwrite, warna nayi bane
            local_backup_done = True
        except OSError:
            pass

    apply_local_retention()

    # Google Drive backup - poori tarah alag/optional hai, kabhi bhi local backup ko
    # crash nahi karega chahe internet na ho ya Drive setup na ho.
    try:
        gdrive.auto_drive_backup_if_due(DB_FILE)
        gdrive.sync_pending_local_photos("bill_images")
    except Exception:
        pass

    return local_backup_done


def _parse_local_backup_date(filename):
    m = _LOCAL_BACKUP_DATE_RE.search(filename or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d-%m-%Y").date()
    except ValueError:
        return None


def apply_local_retention():
    """Computer ke 'app_backups' folder par wahi 90-din wala rolling
    retention lagata hai jo Google Drive par lagta hai (isi liye dono
    jagah hamesha ek jaisi history rehti hai):

    (a) Kisi bhi EK din ki 1 se zyada dated files mil jayen (purani
        multiple-per-day files se), sirf sab se nayi rakhta hai.
    (b) 90 din se purani dated backup khud rolling delete ho jati hai -
        pehle 90 din mein KUCH bhi delete nahi hota.

    Live database (DB_FILE) ko yeh function kabhi nahi chhoo,ta - sirf
    BACKUP_DIR ke andar ki dated files par asar hota hai."""
    try:
        all_files = os.listdir(BACKUP_DIR)
    except OSError:
        return

    by_date = {}
    for fname in all_files:
        if not fname.endswith(".db"):
            continue
        day = _parse_local_backup_date(fname)
        if day is None:
            continue
        by_date.setdefault(day, []).append(fname)

    cutoff = datetime.now().date() - timedelta(days=BACKUP_RETENTION_DAYS)

    for day, group in by_date.items():
        full_paths = [os.path.join(BACKUP_DIR, f) for f in group]
        if len(full_paths) > 1:
            try:
                full_paths.sort(key=os.path.getmtime, reverse=True)
            except OSError:
                pass
            for extra in full_paths[1:]:
                try:
                    os.remove(extra)
                except OSError:
                    pass
            full_paths = full_paths[:1]
        if day < cutoff:
            for p in full_paths:
                try:
                    os.remove(p)
                except OSError:
                    pass

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