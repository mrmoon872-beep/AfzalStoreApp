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

    st.success(
        "✅ Auto-Sync Active - aapka data hamesha khud-ba-khud mahfooz ho raha hai. "
        "Yeh page kholna bhi zaroori nahi - sirf app istemal karte rahein."
    )

    # ==================== LOCAL BACKUP (safe: sirf CREATE karta hai) ====================
    st.markdown("### 💻 Local Backup (Computer)")
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

    st.divider()

    # ==================== GOOGLE DRIVE BACKUP ====================
    st.markdown("### ☁️ Google Drive Backup")
    st.caption("Agar computer chori ho jaye, kharab ho jaye ya crash ho jaye, tab bhi aapka data Google Drive se wapas mil sakta hai.")

    # PERF/BUG FIX: pehle yahan seedha os.path.exists(client_secret.json)
    # check hota tha - is se Streamlit Cloud par hamesha "file nahi mili"
    # warning aati thi, chahe Secrets mein valid 'gdrive_token' kyun na ho.
    # is_available() already dono cases handle karta hai (local file YA
    # cloud token) - isi liye ab sirf isi ko istemal kar rahe hain.
    is_cloud_token = gdrive._has_cloud_token()

    if not gdrive.GOOGLE_LIBS_AVAILABLE:
        st.warning(
            "⚠️ Google Drive backup abhi available nahi hai kyunke zaroori packages install nahi hain.\n\n"
            "Terminal/CMD mein yeh chalayein, phir app restart karein:\n\n"
            "`pip install google-auth-oauthlib google-api-python-client google-auth-httplib2`"
        )
        return
    elif not gdrive.is_available():
        st.warning(
            f"⚠️ '{gdrive.CLIENT_SECRET_FILE}' file root ya _internal, kisi folder mein bhi nahi mili, "
            "aur Streamlit Secrets mein bhi koi 'gdrive_token' nahi mila. In mein se koi ek tareeqa apnayein."
        )
        return

    connected = gdrive.is_connected()

    if connected:
        st.success("✅ Google Drive Connected Hai")
    elif is_cloud_token:
        # Cloud par 'gdrive_token' Secret maujood hai lekin invalid/expire
        # ho chuka hai. Yahan HARGIZ localhost-based "Connect Karo" flow
        # nahi dikhana - woh sirf local PC par kaam karta hai.
        st.error(
            "❌ Streamlit Secrets mein 'gdrive_token' maujood hai lekin ab valid/refreshable nahi hai.\n\n"
            "Apne PC (local) par ek baar dobara 'Connect Google Drive' karein, phir jo nayi "
            "drive_token.json banegi uska poora content Streamlit Cloud ke Secrets mein "
            "'gdrive_token' ke naam se update kar dein."
        )
        with st.expander("🔍 Diagnostic Info (dikhata hai masla kahan hai, secret khud kabhi nahi dikhata)"):
            diag = gdrive.cloud_token_diagnostics()
            st.write(f"Secret mila: {'✅ Haan' if diag['secret_mila'] else '❌ Nahi'}")
            st.write(f"JSON theek se parse hui: {'✅ Haan' if diag['json_theek_hai'] else '❌ Nahi'}")
            st.write(f"Credentials valid hain: {'✅ Haan' if diag['credentials_valid'] else '❌ Nahi'}")
            if diag["error"]:
                st.code(diag["error"])
        return
    else:
        st.info("🔌 Google Drive abhi connect nahi hai.")

        if not st.session_state.get("_gdrive_connecting"):
            if st.button("🔗 Google Drive Connect Karo", type="primary"):
                auth_url, err = gdrive.start_drive_connect()
                if err:
                    st.error(err)
                else:
                    st.session_state["_gdrive_connecting"] = True
                    st.session_state["_gdrive_auth_url"] = auth_url
                    st.rerun()
        else:
            st.link_button(
                "👉 Pehle Yahan Click Kar Ke Allow Karein",
                st.session_state.get("_gdrive_auth_url", ""),
                type="primary",
            )
            st.caption(
                "Allow karne ke baad Google aapko ek 'localhost' wale page par le jayega jo "
                "shayad 'this site can't be reached' dikhaye - **yeh bilkul normal hai, ignore "
                "karein.** Us page ke URL/address bar mein poora link maujood hai - wahi copy "
                "kar ke neeche paste karein."
            )
            pasted = st.text_input(
                "Yahan wo poora URL (ya sirf uska 'code=' wala hissa) paste karein:",
                key="_gdrive_pasted_code",
            )
            col_confirm, col_cancel = st.columns(2)
            with col_confirm:
                if st.button("✅ Connect Complete Karo", type="primary"):
                    success, message = gdrive.complete_drive_connect(pasted)
                    if success:
                        st.session_state["_gdrive_connecting"] = False
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)
            with col_cancel:
                if st.button("❌ Cancel"):
                    st.session_state["_gdrive_connecting"] = False
                    st.rerun()
        return

    # ==================== Sab kuch neeche sirf tab dikhta hai jab Drive CONNECTED ho ====================
    st.divider()
    settings = gdrive.load_settings()

    # NOTE: yeh toggle sirf DIKHANE/PREFERENCE ke liye hai - asal sync
    # (offline<->online MAIN.db mirror + rozana dated backup) data-safety
    # ki wajah se HAMESHA background mein chalta hai, chahe yeh toggle
    # kisi bhi position par ho. Isi liye yahan kabhi koi "OFF/warning"
    # state nahi dikhayi jati - user ko kabhi lagna nahi chahiye ke uska
    # data ab mahfooz nahi ho raha.
    auto_on = st.toggle(
        "📅 Roz Khud-Ba-Khud Drive Par Backup Karo (Full Auto-Sync)",
        value=settings.get("auto_drive_backup_enabled", True),
    )
    if auto_on != settings.get("auto_drive_backup_enabled", True):
        settings["auto_drive_backup_enabled"] = auto_on
        gdrive.save_settings(settings)

    st.success(
        "✅ Full Auto-Sync Active - ab kabhi kuch click karne ki zaroorat nahi:\n\n"
        "- Mobile par jo bhi save karein, background mein khud Drive par chala jayega.\n"
        "- PC (offline) khulte hi khud check hota hai - mobile wala nayi data khud aa jata hai.\n"
        "- PC par jo save karein, internet aate hi khud Drive par chala jata hai.\n"
        "- Roz ek dated backup bhi (Local + Drive) khud ban jati hai - 90 din tak mahfooz."
    )

    last_date = settings.get("last_drive_backup_date")
    if last_date:
        st.caption(f"📅 Aakhri automatic Drive backup: {last_date}")

    st.divider()

    # ==================== SIRF EK RESTORE BUTTON - DOUBLE CONFIRM ====================
    st.markdown("### 🚨 PC Crash / Chori / Format Ho Jaye To")
    st.caption(
        "Yeh EK button seedha Drive ki MAIN database (afzal_store_MAIN.db) - jo hamesha "
        "sab se latest aur complete data rakhti hai (sab customers, items, udhaar, sab kuch) - "
        "wapas is computer par utaar deta hai. Kisi list mein se date chunne ki zaroorat nahi."
    )

    if not st.session_state.get("_confirm_main_restore"):
        if st.button("🚨 MAIN Backup Se Poora Data Wapas Lao (One-Click Restore)", type="primary"):
            st.session_state["_confirm_main_restore"] = True
            st.rerun()
    else:
        st.warning("⚠️ Kya aap waqai MAIN backup se restore karna chahte hain? Aapka maujooda data replace ho jayega.")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("✅ Haan, Restore Karein", type="primary", key="_main_restore_yes"):
                with st.spinner("Google Drive se poora data wapas laya ja raha hai..."):
                    success, message = gdrive.restore_main_db_from_drive(DB_FILE)
                st.session_state["_confirm_main_restore"] = False
                if success:
                    st.cache_resource.clear()
                    st.success(message + " App restart ho rahi hai...")
                    st.rerun()
                else:
                    st.error(message)
        with col_no:
            if st.button("❌ Cancel", key="_main_restore_no"):
                st.session_state["_confirm_main_restore"] = False
                st.rerun()

    # ==================== ADVANCED (chhupa hua, expert-only, khatarnak) ====================
    with st.expander("🛠️ Advanced - Purani History (Expert Only)", expanded=False):
        st.warning(
            "⚠️ Yeh section sirf experts ke liye hai. Yahan se kisi purani tareekh ki backup "
            "restore karna khatarnak ho sakta hai - **AAJ KA DATA us purani tareekh ke data se "
            "REPLACE ho jayega** aur wapas nahi aa sakega. Sirf tab istemal karein jab bilkul "
            "yaqeen ho ke aapko kya chahiye."
        )

        st.markdown("#### ☁️ Google Drive - Purani Dated Backups")
        # PERF FIX: list_drive_backups() (jo Drive API call karta hai) ab
        # SIRF is Advanced expander ke andar chalta hai - normal page load
        # par kabhi nahi, isi liye Backup & Restore page bhi fast khulta hai.
        drive_backups = gdrive.list_drive_backups()
        if not drive_backups:
            st.info("Abhi Drive par koi dated backup nahi hai.")
        else:
            backup_labels = {f"{f['name']}": f["id"] for f in drive_backups}
            selected_label = st.selectbox(
                "Kisi Purani Tareekh Se Restore Karne Ke Liye Chuno",
                list(backup_labels.keys()), key="drive_restore_select",
            )
            if not st.session_state.get("_confirm_dated_restore"):
                if st.button("♻️ Is Tareekh Se Restore Karo", key="_dated_restore_btn"):
                    st.session_state["_confirm_dated_restore"] = True
                    st.rerun()
            else:
                st.error("⚠️ PAKKA? Yeh AAJ KA data mita kar purani tareekh ka data la dega. Wapis nahi ho sakta.")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Haan, Purani Tareekh Se Restore Karo", type="primary", key="_dated_restore_yes"):
                        selected_id = backup_labels[selected_label]
                        with st.spinner("Google Drive se download ho raha hai..."):
                            success, message = gdrive.download_backup_from_drive(selected_id, DB_FILE)
                        st.session_state["_confirm_dated_restore"] = False
                        if success:
                            st.cache_resource.clear()
                            st.success(message + " App restart ho rahi hai...")
                            st.rerun()
                        else:
                            st.error(message)
                with c2:
                    if st.button("❌ Cancel", key="_dated_restore_no"):
                        st.session_state["_confirm_dated_restore"] = False
                        st.rerun()

        st.divider()
        st.markdown("#### 💻 Local - Purani Backups")
        try:
            local_backups = os.listdir(BACKUP_FOLDER) if os.path.exists(BACKUP_FOLDER) else []
        except OSError:
            local_backups = []

        if not local_backups:
            st.info("Koi local backup nahi mila")
        else:
            selected_local = st.selectbox("Local Backup Chuno", sorted(local_backups, reverse=True), key="local_restore_select")
            if not st.session_state.get("_confirm_local_restore"):
                if st.button("Restore Karo (Local)", key="_local_restore_btn"):
                    st.session_state["_confirm_local_restore"] = True
                    st.rerun()
            else:
                st.error("⚠️ PAKKA? AAJ KA data mit kar is purani local file ka data aa jayega.")
                lc1, lc2 = st.columns(2)
                with lc1:
                    if st.button("✅ Haan, Local Se Restore Karo", type="primary", key="_local_restore_yes"):
                        try:
                            shutil.copy(os.path.join(BACKUP_FOLDER, selected_local), DB_FILE)
                            st.session_state["_confirm_local_restore"] = False
                            st.cache_resource.clear()
                            st.success("Restore ho gaya! App restart ho rahi hai...")
                            st.rerun()
                        except OSError as e:
                            st.error(f"Restore karne mein masla aaya: {e}")
                with lc2:
                    if st.button("❌ Cancel", key="_local_restore_no"):
                        st.session_state["_confirm_local_restore"] = False
                        st.rerun()
