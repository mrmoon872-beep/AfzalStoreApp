"""
Sync Manager - AfzalStore
===========================
Google Drive ko "asal" (source of truth) database rakhne ke liye 2-way sync.

SPEED FIX (is round ki FINAL FIX):
- Pichli baar har save ke baad SYNCHRONOUSLY (blocking) Drive upload hoti thi -
  is se HAR click/navigation par Streamlit ka poora page 3-5 second tak
  "atak" jata tha, kyunke Streamlit har interaction par pura script dobara
  chalata hai aur woh blocking call bhi har baar chal rahi thi.
- Ab upload hamesha ek background thread mein, FAURAN (bina kisi wait ke)
  start hoti hai - jo function isse trigger karta hai
  (`trigger_immediate_background_upload`) khud FAURAN (0.01 sec) return ho
  jata hai, thread ke khatam hone ka intezar kiye bagair. Save = turant,
  Drive sync peeche-peeche khud ho jata hai.
- SIRF EK jagah ab bhi (jaan-boojh kar) blocking hai: app restart hote hi,
  agar local database khali/naya-bana lage (Streamlit Cloud jaisi ephemeral
  storage par restart ke baad), to ek dafa (1-2 second) rukk kar asal data
  Drive se le aata hai - warna user ko khaali Dashboard dikhta. Yeh sirf
  PEHLI baar (process ki poori zindagi mein ek hi dafa, st.cache_resource ki
  madad se) chalta hai, har click par nahi.
- Background thread se seedha st.session_state/st.toast use karna safe nahi
  hota (Streamlit ka script-context sirf main thread mein hota hai) - is
  liye thread apna result ek simple, thread-safe module-level dict mein
  likhta hai; app.py har rerun par (bilkul sasta, koi Drive call nahi) yeh
  dict check kar ke session_state/toast update kar deta hai.
"""

import os
import time
import threading
from datetime import datetime
import streamlit as st

_last_known_upload_mtime = 0.0
_upload_lock = threading.Lock()
_upload_in_progress = False

# Background thread yahan apna result likhta hai - sirf plain Python dict
# (koi st.* call nahi), is liye kisi bhi thread se likhna safe hai.
_status_lock = threading.Lock()
_sync_status = {
    "syncing": False,       # abhi upload chal rahi hai kya
    "last_success_ts": 0.0, # aakhri kaamyab upload ka time.time()
    "last_size_str": None,  # aakhri kaamyab upload ke waqt file ka size
    "shown_ts": 0.0,         # yeh success app.py ko "toast" ke zariye dikha diya gaya
}


def _fmt_size(num_bytes):
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / 1024:.0f} KB"


def _background_upload_worker(local_db_path, local_mtime):
    """SIRF background thread ke andar chalta hai - koi bhi st.* call nahi
    karta (thread-safe nahi hota), sirf file I/O + Google Drive API + apna
    plain _sync_status dict update karta hai."""
    global _last_known_upload_mtime, _upload_in_progress
    try:
        with _status_lock:
            _sync_status["syncing"] = True
        import google_drive_backup as gdrive
        success, _msg = gdrive.upload_main_db_to_drive(local_db_path)
        if success:
            _last_known_upload_mtime = local_mtime
            with _status_lock:
                _sync_status["last_success_ts"] = time.time()
                try:
                    _sync_status["last_size_str"] = _fmt_size(os.path.getsize(local_db_path))
                except OSError:
                    _sync_status["last_size_str"] = None
    except Exception:
        pass
    finally:
        with _status_lock:
            _sync_status["syncing"] = False
        _upload_in_progress = False


def trigger_immediate_background_upload(local_db_path="afzal_store.db"):
    """REQUIREMENT: har save ke turant baad (conn.commit() ke theek baad) yeh
    call karna - KHUD KABHI BLOCK NAHI HOTA (0.01 sec mein return ho jata
    hai). Agar db pichli upload ke baad se badal chuki hai, to Drive upload
    turant ek background thread start karta hai - koi toast/popup nahi
    dikhata (INVISIBLE SYNC), sirf sidebar ka 'Last Drive Sync' caption
    khud-ba-khud update ho jata hai jab upload poori ho jati hai (via
    refresh_sync_indicator_in_session())."""
    global _upload_in_progress
    try:
        if not os.path.exists(local_db_path):
            return
        local_mtime = os.path.getmtime(local_db_path)
        if local_mtime <= _last_known_upload_mtime:
            return  # kuch naya save nahi hua

        with _upload_lock:
            if _upload_in_progress:
                return  # pehle se ek upload chal rahi hai, dobara shuru na karo
            _upload_in_progress = True

        t = threading.Thread(
            target=_background_upload_worker,
            args=(local_db_path, local_mtime),
            daemon=True,
        )
        t.start()
    except Exception:
        _upload_in_progress = False


def refresh_sync_indicator_in_session():
    """App.py se HAR rerun par call karna safe hai - Drive/network ko
    KABHI touch nahi karta, sirf ek plain in-memory dict padhta hai, is liye
    0.01 sec se bhi kam lagta hai. INVISIBLE SYNC: koi toast/popup nahi -
    sirf sidebar ke 'Last Drive Sync' caption ke liye session_state chup-chaap
    update kar deta hai jab bhi koi background upload kaamyabi se poori hoti
    hai."""
    with _status_lock:
        last_success_ts = _sync_status["last_success_ts"]
        last_size_str = _sync_status["last_size_str"]

    if last_success_ts:
        now_str = datetime.fromtimestamp(last_success_ts).strftime("%I:%M:%S %p")
        st.session_state["_last_drive_sync_time"] = now_str
        st.session_state["_last_drive_sync_size"] = last_size_str or ""


@st.cache_resource(show_spinner=False)
def _run_startup_recovery_once(_local_db_path):
    """PERF FIX: yeh (aur is ke andar ka Drive check) guaranteed sirf EK
    DAFA chalta hai poore process ki zindagi mein - `st.cache_resource`
    (bina ttl ke) ki wajah se. Is liye har rerun/click par yeh dobara nahi
    chalta - sirf app ke bilkul pehle load par, jab tak process zinda hai."""
    try:
        import google_drive_backup as gdrive
        if not gdrive.is_available() or not gdrive.is_connected():
            return False

        local_size = gdrive._local_db_size(_local_db_path)
        local_rows = gdrive._local_db_row_count(_local_db_path)

        looks_empty_enough = gdrive._looks_empty(local_size) or local_rows < 5
        if not looks_empty_enough:
            return False  # local mein pehle se theek-thaak data hai

        downloaded, _msg = gdrive.download_main_db_if_newer(_local_db_path, force=True)
        return downloaded
    except Exception:
        return False


def blocking_startup_recovery(local_db_path="afzal_store.db"):
    """REQUIREMENT #2/#3: app bilkul shuru hote hi (kisi CREATE TABLE se
    pehle) call karna. Sirf process ki PEHLI hi baar (st.cache_resource ki
    wajah se) agar local database khali/naya-bana hua lage (Streamlit Cloud
    par ephemeral restart ke baad), to BLOCKING (1-2 second) Drive se asal
    data le aata hai. Baaki tamam reruns par yeh function khud instant
    return hota hai (cached result), koi extra lag nahi."""
    try:
        return _run_startup_recovery_once(local_db_path)
    except Exception:
        return False


def _background_full_sync(local_db_path):
    """Cross-device download-check (kya kisi doosri device se nayi data aayi
    hai) + rozana dated backup - background thread mein, throttled (har 30
    second mein ek dafa). Upload yahan nahi hoti - woh ab
    trigger_immediate_background_upload() ke zariye save ke turant baad
    alag se hoti hai."""
    global _sync_in_progress
    try:
        import google_drive_backup as gdrive
        if not gdrive.is_available() or not gdrive.is_connected():
            return
        try:
            gdrive.download_main_db_if_newer(local_db_path)
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


SYNC_THROTTLE_SECONDS = 30
_sync_lock = threading.Lock()
_sync_in_progress = False


@st.cache_resource(ttl=SYNC_THROTTLE_SECONDS, show_spinner=False)
def _throttled_sync_trigger(_local_db_path, _cache_bust):
    global _sync_in_progress
    with _sync_lock:
        if _sync_in_progress:
            return
        _sync_in_progress = True
    t = threading.Thread(target=_background_full_sync, args=(_local_db_path,), daemon=True)
    t.start()


def run_full_sync(local_db_path="afzal_store.db"):
    """App.py se har rerun par call karna safe hai - khud kabhi block nahi
    karta (thread sirf har 30 second mein ek dafa start hoti hai, khud yeh
    function turant return hota hai). Cross-device download-check aur dated
    backup background mein chalte hain."""
    try:
        _throttled_sync_trigger(local_db_path, 0)
    except Exception:
        pass


def _background_photo_upload(photo_bytes, filename, subfolder):
    """Alag thread mein chalta hai - koi bhi st.* call nahi karta."""
    try:
        import google_drive_backup as gdrive
        gdrive.upload_photo_to_drive(photo_bytes, filename, subfolder=subfolder)
    except Exception:
        pass


def upload_photo_to_drive_background(photo_bytes, filename, subfolder="Photos"):
    """Photo upload background thread mein - form submit turant complete
    hota hai, Drive upload chup-chaap peeche khud ho jati hai."""
    try:
        t = threading.Thread(
            target=_background_photo_upload,
            args=(photo_bytes, filename, subfolder),
            daemon=True,
        )
        t.start()
    except Exception:
        pass
