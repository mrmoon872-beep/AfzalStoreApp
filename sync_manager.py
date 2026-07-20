"""
Sync Manager - AfzalStore
===========================
Google Drive ko "asal" (source of truth) database rakhne ke liye 2-way sync.

PERF FIX (is round mein): Pehle throttle ek local JSON "marker file" se hota
tha - Streamlit Cloud par disk I/O thoda unpredictable ho sakta hai, aur agar
throttle kabhi fail hota to Drive check HAR rerun par chalta (bohot dheema).
Ab `st.cache_resource(ttl=...)` use karte hain - yeh Streamlit ka apna,
server-side, memory-based cache hai: guarantee hai ke andar wala function
sirf ek dafa TTL window mein chalega, chahe kitni bhi baar/kisi bhi session
se call ho. Koi disk I/O nahi, koi race condition nahi.
"""

import os
import time
import threading
import streamlit as st

SYNC_THROTTLE_SECONDS = 30  # is se zyada baar-baar Drive API call nahi hoti
_upload_lock = threading.Lock()
_upload_in_progress = False
_last_known_upload_mtime = 0.0


def _background_upload(local_db_path):
    """Alag thread mein chalta hai - koi bhi st.* call nahi karta (Streamlit
    ka background-thread context issue se bachne ke liye), sirf file I/O aur
    Google API calls karta hai."""
    global _upload_in_progress, _last_known_upload_mtime
    try:
        import google_drive_backup as gdrive
        gdrive.upload_main_db_to_drive(local_db_path)
        _last_known_upload_mtime = time.time()
    except Exception:
        pass  # background thread mein exception UI tak kabhi nahi jani chahiye
    finally:
        with _upload_lock:
            _upload_in_progress = False


@st.cache_resource(ttl=SYNC_THROTTLE_SECONDS, show_spinner=False)
def _throttled_sync_check(_local_db_path, _cache_bust):
    """PERF FIX: st.cache_resource ki wajah se yeh function ka poora andar
    ka code sirf HAR 30-SECOND mein EK DAFA chalta hai - chahe app par
    kitni bhi baar click ho, kitne bhi log ek sath use kar rahe hon. Baaki
    saari calls (jo TTL window ke andar hon) bina Drive tak pahonchay
    turant cached result wapas paati hain - is liye ab sync kabhi bhi UI
    ko dheema nahi karta."""
    global _upload_in_progress

    status_msg = None
    try:
        import google_drive_backup as gdrive
        if not gdrive.is_available() or not gdrive.is_connected():
            return None
    except Exception:
        return None

    try:
        downloaded, msg = gdrive.download_main_db_if_newer(_local_db_path)
        if downloaded:
            status_msg = "🔄 " + msg
    except Exception:
        pass

    try:
        if os.path.exists(_local_db_path):
            local_mtime = os.path.getmtime(_local_db_path)
            if local_mtime > _last_known_upload_mtime:
                with _upload_lock:
                    already_running = _upload_in_progress
                    if not already_running:
                        _upload_in_progress = True
                if not already_running:
                    t = threading.Thread(target=_background_upload, args=(_local_db_path,), daemon=True)
                    t.start()
    except Exception:
        pass

    return status_msg


def run_full_sync(local_db_path="afzal_store.db"):
    """App.py se har rerun par call karna safe hai - andar `st.cache_resource`
    khud throttle karta hai, is liye is function ko baar-baar call karna
    (near-)FREE hai. Returns a status string for optional display, or None."""
    try:
        return _throttled_sync_check(local_db_path, 0)
    except Exception:
        return None
