import streamlit as st
import os
import shutil
from datetime import datetime
import google_drive_backup as gdrive

DB_FILE = 'afzal_store.db'
BACKUP_FOLDER = 'Backup'


def _free_space_mb(path="."):
    try:
        return shutil.disk_usage(path).free / (1024 * 1024)
    except OSError:
        return None


def show_backup_restore():
    st.header("💾 Backup & Restore")
    os.makedirs(BACKUP_FOLDER, exist_ok=True)

    tab_local, tab_drive = st.tabs(["💻 Local Backup (Computer)", "☁️ Google Drive Backup"])

    # ==================== LOCAL BACKUP (existing feature) ====================
    with tab_local:
        col1, col2 = st.columns(2)

        with col1:
            if st.button("Backup Banao", type="primary"):
                free_mb = _free_space_mb()
                if free_mb is not None and free_mb < 100:
                    st.error(f"❌ Computer ki disk space bohot kam hai ({free_mb:.0f} MB baaki)! Pehle jagah khali karein, phir backup banayein.")
                else:
                    backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                    try:
                        shutil.copy(DB_FILE, os.path.join(BACKUP_FOLDER, backup_name))
                        st.success(f"Backup ban gaya: {backup_name}")
                    except OSError as e:
                        if "space" in str(e).lower() or "disk" in str(e).lower():
                            st.error("❌ Disk space kam hai, backup nahi ban saka. Jagah khali karein.")
                        else:
                            st.error(f"Backup banane mein masla aaya: {e}")

        with col2:
            try:
                backups = os.listdir(BACKUP_FOLDER) if os.path.exists(BACKUP_FOLDER) else []
            except OSError:
                backups = []
            if backups:
                selected_backup = st.selectbox("Backup Chuno", sorted(backups, reverse=True))
                if st.button("Restore Karo", type="secondary"):
                    try:
                        shutil.copy(os.path.join(BACKUP_FOLDER, selected_backup), DB_FILE)
                        st.cache_resource.clear()
                        st.success("Restore ho gaya! App restart ho rahi hai...")
                        st.rerun()
                    except OSError as e:
                        st.error(f"Restore karne mein masla aaya: {e}")
            else:
                st.info("Koi backup nahi mila")

    # ==================== GOOGLE DRIVE BACKUP (naya) ====================
    with tab_drive:
        st.markdown("### ☁️ Google Drive Par Auto Backup")
        st.caption("Agar computer chori ho jaye, kharab ho jaye ya crash ho jaye, tab bhi aapka data Google Drive se wapas mil sakta hai.")

        if not gdrive.GOOGLE_LIBS_AVAILABLE:
            st.warning(
                "⚠️ Google Drive backup abhi available nahi hai kyunke zaroori packages install nahi hain.\n\n"
                "Terminal/CMD mein yeh chalayein, phir app restart karein:\n\n"
                "`pip install google-auth-oauthlib google-api-python-client google-auth-httplib2`"
            )
        elif not os.path.exists(gdrive.CLIENT_SECRET_FILE):
            st.warning(f"⚠️ '{gdrive.CLIENT_SECRET_FILE}' file project folder mein nahi mili. Pehle yeh file yahan (afzal_store.db ke sath) rakhein.")
        else:
            connected = gdrive.is_connected()

            if connected:
                st.success("✅ Google Drive Connected Hai")
            else:
                st.info("🔌 Google Drive abhi connect nahi hai.")
                if st.button("🔗 Google Drive Connect Karo", type="primary"):
                    with st.spinner("Browser mein Google login khul raha hai... Wahan apna account allow karein."):
                        success, message = gdrive.connect_to_drive()
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

            if connected:
                st.divider()
                settings = gdrive.load_settings()

                col_a, col_b = st.columns(2)
                with col_a:
                    auto_on = st.toggle("📅 Roz Khud-Ba-Khud Drive Par Backup Karo", value=settings.get("auto_drive_backup_enabled", False))
                    if auto_on != settings.get("auto_drive_backup_enabled", False):
                        settings["auto_drive_backup_enabled"] = auto_on
                        gdrive.save_settings(settings)
                        st.rerun()
                with col_b:
                    if st.button("☁️ Abhi Turant Drive Par Backup Karo", type="primary"):
                        with st.spinner("Google Drive par upload ho raha hai..."):
                            success, message = gdrive.upload_backup_to_drive(DB_FILE)
                        if success:
                            st.success(message)
                        else:
                            st.error(message)

                last_date = settings.get("last_drive_backup_date")
                if last_date:
                    st.caption(f"📅 Aakhri automatic Drive backup: {last_date}")

                st.divider()
                st.markdown("### 📜 Drive Par Maujood Backups")
                drive_backups = gdrive.list_drive_backups()

                if not drive_backups:
                    st.info("Abhi Drive par koi backup nahi hai. Upar wala button dabayein.")
                else:
                    backup_labels = {f"{f['name']}": f["id"] for f in drive_backups}
                    selected_label = st.selectbox("Restore Karne Ke Liye Backup Chuno", list(backup_labels.keys()), key="drive_restore_select")

                    st.warning("⚠️ Restore karne se aapki MAUJOODA app ka data is backup se REPLACE ho jayega. Pehle apna current data ka bhi local backup bana lein (upar wale tab se).")
                    if st.button("♻️ Is Backup Se Restore Karo (Google Drive)", type="secondary"):
                        selected_id = backup_labels[selected_label]
                        with st.spinner("Google Drive se download ho raha hai..."):
                            success, message = gdrive.download_backup_from_drive(selected_id, DB_FILE)
                        if success:
                            st.cache_resource.clear()
                            st.success(message + " App restart ho rahi hai...")
                            st.rerun()
                        else:
                            st.error(message)
