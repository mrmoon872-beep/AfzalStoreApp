"""
Sync Manager - AfzalStore
===========================
Google Drive ko "asal" (source of truth) database rakhne ke liye 2-way sync.

STREAMLIT CLOUD FIX (is round ki FINAL FIX):
- Streamlit Cloud jaisi ephemeral-storage hosting par agar user save karne ke
  FAURAN baad tab band kar de, to purana 5-second-debounced background upload
  kabhi chal hi nahi pata tha (container turant ruk jata tha) - is se woh save
  hamesha kho jata tha. Ab har save ke turant baad (isi rerun mein, BLOCKING)
  Drive upload hota hai - chahe usse thoda ruk kar page dikhe, data mahfooz
  rehta hai. Chota st.toast dikhta hai taake user ko pata chale sync ho raha
  hai aur wo thora ruk kar hi tab band kare.
- Cross-device "kya kisi doosri device se nayi data aayi hai" wala download
  check ab bhi background thread mein (throttled) hota hai kyunke woh urgent
  nahi hota aur page load dheema nahi karna chahiye.
- Roz ki dated backup bhi isi background thread mein, chup-chaap.
"""

import os
import time
import threading
from datetime import datetime
import streamlit as st

SYNC_THROTTLE_SECONDS = 30      # is se zyada baar-baar Drive check nahi hota
UPLOAD_DEBOUNCE_SECONDS = 5     # background safety-net upload ke liye (blocking path se alag)

_sync_lock = threading.Lock()
_sync_in_progress = False
_last_known_upload_mtime = 0.0
_upload_lock = threading.Lock()


def _fmt_size(num_bytes):
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / 1024:.0f} KB"


def blocking_upload_if_changed(local_db_path="afzal_store.db", show_status=True):
    """REQUIREMENT #1 FIX: har save ke FAURAN baad, isi rerun mein (blocking,
    background thread nahi) call karna - agar local file pichli successful
    upload ke baad se badal chuki hai (yani kuch naya save hua hai), to
    Drive par TURANT upload karta hai, bina 5-second wait ke. Isi tarah agar
    user save karne ke 1-2 second baad hi tab band kar de, tab tak upload
    already ho chuka hota hai. show_status=True hone par chota st.toast bhi
    dikhata hai (pehle sab kuch chup-chaap tha - ab user ko jaan-boojh kar
    dikhaya jata hai taake wo sync khatam hone tak ek pal ruk sake)."""
    global _last_known_upload_mtime
    try:
        if not os.path.exists(local_db_path):
            return False
        local_mtime = os.path.getmtime(local_db_path)
        if local_mtime <= _last_known_upload_mtime:
            return False  # kuch naya save nahi hua - upload ki zaroorat nahi

        import google_drive_backup as gdrive
        if not gdrive.is_available() or not gdrive.is_connected():
            return False

        with _upload_lock:
            # dobara check - kisi doosre rerun/thread ne isi beech upload na kar di ho
            if local_mtime <= _last_known_upload_mtime:
                return False

            if show_status:
                try:
                    st.toast("☁️ Google Drive par save ho raha hai...")
                except Exception:
                    pass

            success, message = gdrive.upload_main_db_to_drive(local_db_path)

            if success:
                _last_known_upload_mtime = local_mtime
                now_str = datetime.now().strftime("%I:%M:%S %p")
                try:
                    size_str = _fmt_size(os.path.getsize(local_db_path))
                except OSError:
                    size_str = "?"
                st.session_state["_last_drive_sync_time"] = now_str
                st.session_state["_last_drive_sync_size"] = size_str
                if show_status:
                    try:
                        st.toast(f"✅ Synced {now_str}")
                    except Exception:
                        pass
                return True
            else:
                if show_status:
                    try:
                        st.toast(f"⚠️ Drive sync abhi nahi ho saka - dobara koshish hogi.")
                    except Exception:
                        pass
                return False
    except Exception:
        return False


def blocking_startup_recovery(local_db_path="afzal_store.db"):
    """REQUIREMENT #2 FIX: app bilkul shuru hote hi (kisi CREATE TABLE ya page
    render se pehle) call karna. Agar local database khali/naya-bana hua lag
    raha hai (jaise Streamlit Cloud par ephemeral restart ke baad - disk khud
    khali ho chuki, sirf abhi CREATE TABLE se stub bana hai) aur Drive par
    isse bari (waqai data wali) MAIN backup maujood hai, to turant - BLOCKING,
    background thread nahi - woh asal data download kar leta hai, taake user
    ko kabhi khaali Dashboard/0 customers na dikhein. Kabhi crash nahi karta:
    Drive na ho ya internet na ho to bas chup-chaap return ho jata hai (page
    aage apne aap normal empty-state handle kar lega)."""
    try:
        import google_drive_backup as gdrive
        if not gdrive.is_available() or not gdrive.is_connected():
            return False

        local_size = gdrive._local_db_size(local_db_path)
        local_rows = gdrive._local_db_row_count(local_db_path)

        looks_empty_enough = gdrive._looks_empty(local_size) or local_rows < 5
        if not looks_empty_enough:
            return False  # local mein pehle se theek-thaak data hai, chhedne ki zaroorat nahi

        downloaded, _msg = gdrive.download_main_db_if_newer(local_db_path, force=True)
        return downloaded
    except Exception:
        return False


def _background_full_sync(local_db_path):
    """Cross-device download-check + rozana dated backup - background thread
    mein hota hai (urgent nahi, page load dheema nahi karna). Upload wala
    hissa yahan bhi ek SAFETY NET ke taur par maujood hai (agar kabhi
    blocking_upload_if_changed() na chal paya ho), lekin normal flow mein
    zyada tar kaam blocking_upload_if_changed() khud kar chuka hota hai."""
    global _sync_in_progress, _last_known_upload_mtime
    try:
        import google_drive_backup as gdrive
        if not gdrive.is_available() or not gdrive.is_connected():
            return

        try:
            gdrive.download_main_db_if_newer(local_db_path)
        except Exception:
            pass

        try:
            if os.path.exists(local_db_path):
                local_mtime = os.path.getmtime(local_db_path)
                if local_mtime > _last_known_upload_mtime:
                    time.sleep(UPLOAD_DEBOUNCE_SECONDS)
                    with _upload_lock:
                        if local_mtime > _last_known_upload_mtime:
                            success, _msg = gdrive.upload_main_db_to_drive(local_db_path)
                            if success:
                                _last_known_upload_mtime = local_mtime
        except Exception:
            pass

        try:
            gdrive.auto_drive_backup_if_due(local_db_path)
        except Exception:
            pass
    except Exception:
        pass
    finally:
        with _sync_lock:
            _sync_in_progress = False


@st.cache_resource(ttl=SYNC_THROTTLE_SECONDS, show_spinner=False)
def _throttled_sync_trigger(_local_db_path, _cache_bust):
    """PERF FIX: `st.cache_resource` ki wajah se yeh sirf HAR 30-SECOND mein
    EK DAFA background thread START karta hai - khud kabhi Drive tak
    (blocking) nahi jata, is liye turant return hota hai aur app/page load
    kabhi is ki wajah se dheema nahi hota."""
    global _sync_in_progress
    with _sync_lock:
        if _sync_in_progress:
            return
        _sync_in_progress = True
    t = threading.Thread(target=_background_full_sync, args=(_local_db_path,), daemon=True)
    t.start()


def run_full_sync(local_db_path="afzal_store.db"):
    """App.py se har rerun par call karna safe hai - khud kabhi block nahi
    karta. Cross-device download-check aur dated backup background mein
    chalte hain. NOTE: turant/blocking save-upload ab is function ka hissa
    NAHI hai - iske liye alag se blocking_upload_if_changed() use karein
    (jo app.py top par khud call karta hai, is liye har save ke baad khud
    ho jata hai bina kisi feature-file mein alag se hook lagaye)."""
    try:
        _throttled_sync_trigger(local_db_path, 0)
    except Exception:
        pass


def _background_photo_upload(photo_bytes, filename, subfolder):
    """Alag thread mein chalta hai - koi bhi st.* call nahi karta. Isi wajah
    se agar internet slow ho ya Drive tak pahonchne mein 10-20 second bhi lag
    jayen, app ka baaki hissa (form save, list refresh) turant chalta rehta
    hai - kabhi 'hang' nahi hota."""
    try:
        import google_drive_backup as gdrive
        gdrive.upload_photo_to_drive(photo_bytes, filename, subfolder=subfolder)
    except Exception:
        pass  # background thread se UI tak koi error kabhi nahi jani chahiye


def upload_photo_to_drive_background(photo_bytes, filename, subfolder="Photos"):
    """PERF FIX: pehle item/customer photo save hone ke turant baad, isi
    request ke andar (blocking) Google Drive par upload hoti thi - agar us
    waqt internet slow hota to poora form submit "hang" jaisa lagta tha
    (kai second tak UI response hi nahi karta tha), jabke local photo already
    save ho chuki hoti thi. Ab yeh upload ek background thread mein hoti hai:
    local save turant complete hota hai, Drive upload chup-chaap peeche
    (kuch second baad) khud ho jati hai. Kabhi exception raise nahi karta."""
    try:
        t = threading.Thread(
            target=_background_photo_upload,
            args=(photo_bytes, filename, subfolder),
            daemon=True,
        )
        t.start()
    except Exception:
        pass
