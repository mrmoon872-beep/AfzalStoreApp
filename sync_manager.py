"""
Sync Manager - AfzalStore
===========================
Google Drive ko "asal" (source of truth) database rakhne ke liye 2-way sync.

100% SILENT + NON-BLOCKING (is round ki FINAL FIX):
- Pehle download-check seedha (blocking) request thread mein chalta tha -
  agar internet slow ho to poora page load bhi dheema ho jata tha. Ab
  DOWNLOAD aur UPLOAD dono EK HI background thread mein hote hain - jo
  function Streamlit se call hota hai (`run_full_sync`) khud sirf thread
  START kar ke FOREN turant return ho jata hai. App/page kabhi is wajah se
  nahi rukta, chahe Drive kitni bhi slow kyun na ho.
- Koi st.toast / st.success / st.info / st.warning KAHIN nahi hai is file
  mein - background thread se Streamlit UI calls karna waise bhi safe nahi
  hota, aur user ko yeh sync bilkul dikhna hi nahi chahiye. Poora sync
  chup-chaap peeche chalta rehta hai.
- Upload se pehle 5-second debounce hai - taake ek hi save ke turant baad
  baar baar upload na ho, thoda ruk kar ek hi baar latest file jaye.
"""

import os
import time
import threading
import streamlit as st

SYNC_THROTTLE_SECONDS = 30      # is se zyada baar-baar Drive check nahi hota
UPLOAD_DEBOUNCE_SECONDS = 5     # save hone ke turant baad itna ruk kar hi upload hota hai

_sync_lock = threading.Lock()
_sync_in_progress = False
_last_known_upload_mtime = 0.0


def _background_full_sync(local_db_path):
    """POORA sync (download-if-newer + upload-if-changed + daily dated
    backup) isi EK background thread ke andar hota hai - koi bhi st.* call
    nahi (na hi koi print/message), sirf file I/O aur Google Drive API
    calls. Kabhi bhi exception UI tak nahi jati - chup-chaap skip ho jata
    hai, agli baar phir try hoga."""
    global _sync_in_progress, _last_known_upload_mtime
    try:
        import google_drive_backup as gdrive
        if not gdrive.is_available() or not gdrive.is_connected():
            return

        # 1) STARTUP/ONGOING CHECK: Drive ka MAIN.db agar local se nayi hai
        #    (kisi doosri device se aaya naya data), to chup-chaap download
        #    kar ke local file replace kar deta hai. Koi popup/message nahi.
        try:
            gdrive.download_main_db_if_newer(local_db_path)
        except Exception:
            pass

        # 2) SAVE PAR AUTO-UPLOAD: agar local file is se pehle jitni baar
        #    upload hui usse nayi hai (matlab kuch naya save hua hai), to
        #    thoda (5 sec) ruk kar - taake lagataar saves ek hi upload mein
        #    samet jayen - Drive par upload kar deta hai. MAIN.db hamesha
        #    'latest timestamp jeetay' rule follow karta hai.
        try:
            if os.path.exists(local_db_path):
                local_mtime = os.path.getmtime(local_db_path)
                if local_mtime > _last_known_upload_mtime:
                    time.sleep(UPLOAD_DEBOUNCE_SECONDS)
                    gdrive.upload_main_db_to_drive(local_db_path)
                    _last_known_upload_mtime = time.time()
        except Exception:
            pass

        # 3) Rozana dated backup (Local+Drive history, 90-din retention) -
        #    yeh bhi isi background thread mein, chup-chaap.
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
    """App.py se har rerun (aur is liye har save ke baad bhi, kyunke
    Streamlit save ke baad khud rerun karta hai) par call karna safe hai -
    khud kabhi block nahi karta, kabhi koi UI message nahi dikhata. Poora
    OFFLINE<->ONLINE sync isi ek call se chup-chaap chalta rehta hai -
    kisi toggle/setting se gated nahi hai (data safety ke liye hamesha ON),
    Backup & Restore page khole bagair bhi."""
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
