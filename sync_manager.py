"""
Sync Manager - AfzalStore
===========================
Google Drive ko "asal" (source of truth) database rakhne ke liye 2-way sync:

1. STARTUP/PERIODIC DOWNLOAD: agar Drive par local se NAYI database hai (kisi
   doosri device - mobile/PC - se aayi ho), to local copy khud-ba-khud
   update ho jati hai.
2. BACKGROUND UPLOAD: agar local database mein change hua hai (koi bhi sale,
   udhaar entry, waghera), to woh background thread mein Drive par upload
   ho jata hai - UI kabhi block nahi hoti.

Har cheez defensively likhi hai - internet na ho, Drive setup na ho, ya
koi bhi error aaye, is se poori app kabhi crash ya slow nahi hoti - sync
bas chup-chaap skip ho jata hai aur agli baar phir try hota hai.
"""

import os
import json
import time
import threading

SYNC_MARKER_FILE = "drive_sync_marker.json"
SYNC_THROTTLE_SECONDS = 25  # is se zyada baar-baar Drive API call nahi hoti
_upload_lock = threading.Lock()
_upload_in_progress = False


def _load_marker():
    try:
        if os.path.exists(SYNC_MARKER_FILE):
            with open(SYNC_MARKER_FILE, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    return {"last_check": 0, "last_upload": 0}


def _save_marker(marker):
    try:
        with open(SYNC_MARKER_FILE, "w") as f:
            json.dump(marker, f)
    except OSError:
        pass


def _background_upload(local_db_path):
    """Alag thread mein chalta hai - koi bhi st.* call nahi karta (Streamlit
    ka background-thread context issue se bachne ke liye), sirf file I/O aur
    Google API calls karta hai."""
    global _upload_in_progress
    try:
        import google_drive_backup as gdrive
        gdrive.upload_main_db_to_drive(local_db_path)
        marker = _load_marker()
        marker["last_upload"] = time.time()
        _save_marker(marker)
    except Exception:
        pass  # background thread mein exception UI tak kabhi nahi jani chahiye
    finally:
        with _upload_lock:
            _upload_in_progress = False


def run_full_sync(local_db_path="afzal_store.db"):
    """Har app rerun par call karna safe hai - andar khud hi throttle check
    karta hai, is liye zyada tar calls turant (bina Drive tak pahonche) return
    ho jati hain. Returns a status string for optional display, or None."""
    marker = _load_marker()
    now = time.time()

    if now - marker.get("last_check", 0) < SYNC_THROTTLE_SECONDS:
        return None  # abhi thodi der pehle hi check hua tha - skip

    marker["last_check"] = now
    _save_marker(marker)

    try:
        import google_drive_backup as gdrive
        if not gdrive.is_available() or not gdrive.is_connected():
            return None  # Drive setup nahi hai - chup-chaap skip, local app phir bhi chalti hai
    except Exception:
        return None

    status_msg = None

    # 1) Pehle DOWNLOAD check - agar Drive par (kisi doosri device se) nayi
    #    database hai, to yahan mil jayegi
    try:
        downloaded, msg = gdrive.download_main_db_if_newer(local_db_path)
        if downloaded:
            status_msg = "🔄 " + msg
    except Exception:
        pass

    # 2) Phir UPLOAD check - agar local mein naya data hai (last upload ke
    #    baad), background thread mein Drive par bhej do (UI block nahi hogi)
    global _upload_in_progress
    try:
        if os.path.exists(local_db_path):
            local_mtime = os.path.getmtime(local_db_path)
            if local_mtime > marker.get("last_upload", 0):
                with _upload_lock:
                    already_running = _upload_in_progress
                    if not already_running:
                        _upload_in_progress = True
                if not already_running:
                    t = threading.Thread(target=_background_upload, args=(local_db_path,), daemon=True)
                    t.start()
    except Exception:
        pass

    return status_msg
