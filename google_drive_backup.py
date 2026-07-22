"""
Google Drive Backup Module - AfzalStore
=========================================
Yeh module client_secret.json (jo aapne project folder mein rakhi hai) use karke
Google Drive par backup upload/download/list karta hai.

ZAROORI (Ek Baar Install Karna Hoga):
    pip install google-auth-oauthlib google-api-python-client google-auth-httplib2

Agar app PyInstaller se .exe banati hai, to build karte waqt in packages ko bhi
hidden-imports mein shamil karna hoga, warna .exe mein Drive backup kaam nahi karega:
    pyinstaller --hidden-import=googleapiclient --hidden-import=google_auth_oauthlib ... app.py

Har function is module mein defensively likha gaya hai - agar internet na ho, Google
libraries install na hon, ya token expire ho jaye, to yeh app ko kabhi crash nahi
karega - sirf ek friendly False/None return karega jise calling code handle karta hai.
"""

import os
import json
from datetime import datetime

CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "drive_token.json"
SETTINGS_FILE = "drive_backup_settings.json"
DRIVE_FOLDER_NAME = "AfzalStore_Backups"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]  # sirf app ki apni files - poori Drive nahi


def _resolve_path(filename):
    """`filename` ko kai mumkin jagah dhoondta hai - is module (_internal/) ke
    andar, is se ek folder upar (root - jahan README_FINAL.txt ke mutabiq
    client_secret.json rakhne ko kaha gaya tha), aur current working
    directory mein (jahan se `streamlit run` chalaya gaya ho). Isi wajah se
    'file project folder mein nahi mili' wala error ab nahi aata chahe app
    kahin se bhi chalayi jaye. Pehli jagah jahan file mil jaye, wahi return
    hoti hai; kahin na mile to bare filename hi wapas milta hai (taake purana
    error-message behavior barqarar rahe)."""
    here = os.path.dirname(os.path.abspath(__file__))   # .../_internal
    parent = os.path.dirname(here)                        # .../ (root, _internal ke bahar)
    candidates = [
        filename,                        # current working directory
        os.path.join(here, filename),    # _internal/filename
        os.path.join(parent, filename),  # root/filename
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return filename


def get_client_secret_path():
    return _resolve_path(CLIENT_SECRET_FILE)

# Google libraries optional hain - agar install nahi hain to poori app phir bhi chalti rahegi,
# sirf Drive backup ka option "unavailable" dikhega (local backup pe koi asar nahi).
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload, MediaIoBaseUpload
    import io
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False


def _has_cloud_token():
    """Streamlit Cloud par client_secret.json file nahi hoti - agar Secrets mein
    pehle se ek valid token maujood hai, to Drive available maan lo (Connect
    flow Cloud par chalti hi nahi, sirf local PC par ek-baara chalti hai)."""
    try:
        import streamlit as st
        return hasattr(st, "secrets") and "gdrive_token" in st.secrets
    except Exception:
        return False


def is_available():
    """Google Drive backup tabhi available hai jab libraries installed hon AUR
    (a) client_secret.json local file maujood ho (Desktop mode), YA
    (b) Streamlit Secrets mein pehle se token maujood ho (Cloud mode)."""
    return GOOGLE_LIBS_AVAILABLE and (os.path.exists(get_client_secret_path()) or _has_cloud_token())


def load_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    return {"auto_drive_backup_enabled": False, "last_drive_backup_date": None}


def save_settings(settings_dict):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings_dict, f)
        return True
    except OSError:
        return False


def is_connected():
    """Kya humare paas already ek valid (ya refreshable) token hai - matlab
    dobara consent screen dikhaye bagair Drive use ho sakti hai."""
    if not GOOGLE_LIBS_AVAILABLE:
        return False
    if _has_cloud_token():
        return _get_credentials() is not None
    if not os.path.exists(TOKEN_FILE):
        return False
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        return creds is not None and (creds.valid or creds.refresh_token is not None)
    except Exception:
        return False


def connect_to_drive():
    """Ek-baara OAuth consent flow chalata hai - browser tab khulega, aap apna
    Google account select/allow karenge, phir token.json save ho jayegi taake
    dobara har baar login na karna paray. Returns (success: bool, message: str).

    ⚠️ YEH FLOW SIRF APNE PC (Desktop) PAR CHALTI HAI - is ke liye ek local
    browser chahiye jo consent screen khol sake. Streamlit Cloud (ya kisi bhi
    remote/headless server) par yeh kaam NAHI karegi, kyunke wahan koi browser
    nahi hota. Cloud ke liye: pehle apne PC par yeh 'Connect' ek baar karein,
    phir jo 'drive_token.json' file banegi uska poora content Streamlit Cloud
    ke Secrets mein 'gdrive_token' ke naam se paste kar dein (README_CLOUD_SETUP.txt
    mein exact steps hain)."""
    if not GOOGLE_LIBS_AVAILABLE:
        return False, "❌ Google Drive libraries install nahi hain. Terminal mein yeh chalayein:\npip install google-auth-oauthlib google-api-python-client google-auth-httplib2"
    secret_path = get_client_secret_path()
    if not os.path.exists(secret_path):
        return False, f"❌ '{CLIENT_SECRET_FILE}' file root ya _internal folder, kisi mein bhi nahi mili. Pehle yeh file wahan rakhein. (Cloud par yeh flow chalti hi nahi - README_CLOUD_SETUP.txt dekhein.)"

    try:
        flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
        return True, "✅ Google Drive kamyabi se connect ho gayi!"
    except Exception as e:
        return False, (f"❌ Google Drive connect nahi ho saki: {e}\n\nAgar aap Streamlit Cloud par hain, "
                        f"yeh flow yahan kaam nahi karegi - README_CLOUD_SETUP.txt mein Cloud ka tareeqa dekhein.")


def _get_credentials():
    """Saved token load karta hai, expire ho to chup-chaap refresh kar deta hai.
    Kabhi bhi consent screen dobara nahi dikhata jab tak refresh token invalid na ho jaye.

    CLOUD SUPPORT: Streamlit Cloud par koi permanent local file nahi hoti aur na hi
    browser jahan OAuth consent screen khul sake - is liye Cloud par token Streamlit
    Secrets se (st.secrets['gdrive_token']) load hota hai, jo aapne apne PC par
    ek-baara 'Connect Google Drive' kar ke banayi gayi drive_token.json se copy ki
    thi. Local desktop par pehle jaisa hi file-based tareeqa chalta hai."""
    if not GOOGLE_LIBS_AVAILABLE:
        return None

    try:
        import streamlit as st
        if hasattr(st, "secrets") and "gdrive_token" in st.secrets:
            token_json = st.secrets["gdrive_token"]
            if isinstance(token_json, str):
                creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
            else:
                creds = Credentials.from_authorized_user_info(dict(token_json), SCOPES)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            return creds if creds and creds.valid else None
    except Exception:
        pass  # Secrets mein nahi mila ya ghalat format - local file try karo

    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w") as token:
                token.write(creds.to_json())
        return creds if creds and creds.valid else None
    except Exception:
        return None


def _get_drive_service():
    creds = _get_credentials()
    if not creds:
        return None
    try:
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception:
        return None


def _get_or_create_backup_folder(service):
    """AfzalStore_Backups naam ka folder Drive par dhoondta hai, na mile to bana deta hai."""
    try:
        results = service.files().list(
            q=f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces="drive", fields="files(id, name)").execute()
        folders = results.get("files", [])
        if folders:
            return folders[0]["id"]

        folder_metadata = {"name": DRIVE_FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}
        folder = service.files().create(body=folder_metadata, fields="id").execute()
        return folder.get("id")
    except Exception:
        return None


def upload_backup_to_drive(local_db_path="afzal_store.db"):
    """Live database file seedha Google Drive par upload karta hai (koi extra local
    copy banaye bagair, taake disk space kam na ho). Returns (success: bool, message: str)."""
    if not is_available():
        return False, "Google Drive setup mukammal nahi hai."
    if not os.path.exists(local_db_path):
        return False, f"❌ '{local_db_path}' file nahi mili - kuch bhi upload karne ko nahi hai."

    service = _get_drive_service()
    if service is None:
        return False, "❌ Google Drive se connection nahi hai. Pehle 'Connect Google Drive' dabayein."

    try:
        folder_id = _get_or_create_backup_folder(service)
        if not folder_id:
            return False, "❌ Drive par backup folder nahi ban saka."

        timestamp = datetime.now().strftime("%d-%m-%Y_%H-%M")
        drive_filename = f"afzal_store_backup_{timestamp}.db"

        file_metadata = {"name": drive_filename, "parents": [folder_id]}
        media = MediaFileUpload(local_db_path, mimetype="application/octet-stream", resumable=True)
        service.files().create(body=file_metadata, media_body=media, fields="id").execute()

        _cleanup_old_drive_backups(service, folder_id, keep_latest=20)
        return True, f"✅ Google Drive par backup ho gaya: {drive_filename}"
    except Exception as e:
        msg = str(e).lower()
        if "quota" in msg or "storage" in msg:
            return False, "❌ Aapki Google Drive storage full hai. Purani files delete karein ya storage bharain."
        elif "network" in msg or "connection" in msg or "timeout" in msg:
            return False, "❌ Internet connection nahi mila. Backup baad mein dobara try hoga."
        return False, f"❌ Drive upload nahi ho saka: {e}"


def _cleanup_old_drive_backups(service, folder_id, keep_latest=30):
    """Computer ki tarah Drive par bhi space bachane ke liye, sirf latest N backups
    rakhta hai, baaki purani khud mita deta hai."""
    try:
        results = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            spaces="drive", fields="files(id, name, createdTime)",
            orderBy="createdTime desc").execute()
        files = results.get("files", [])
        for old_file in files[keep_latest:]:
            try:
                service.files().delete(fileId=old_file["id"]).execute()
            except Exception:
                pass
    except Exception:
        pass


def _get_or_create_folder_path(service, folder_names):
    """Nested folder path banata/dhoondta hai, jaise ['AfzalStore', 'Photos'].
    Har level pe agar folder na ho to bana deta hai. Returns final folder id ya None."""
    parent_id = "root"
    try:
        for name in folder_names:
            results = service.files().list(
                q=f"name='{name}' and mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false",
                spaces="drive", fields="files(id, name)").execute()
            folders = results.get("files", [])
            if folders:
                parent_id = folders[0]["id"]
            else:
                metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
                folder = service.files().create(body=metadata, fields="id").execute()
                parent_id = folder.get("id")
        return parent_id
    except Exception:
        return None


def upload_photo_to_drive(photo_bytes, filename, subfolder="Photos"):
    """Customer/Item photo ko seedha Google Drive ke 'AfzalStore/Photos' folder
    mein upload karta hai. Returns (success: bool, message_or_file_id: str).
    Agar Drive connect na ho ya koi bhi masla aaye, defensively False deta hai -
    calling code local copy rakhne ka fallback use karta hai."""
    if not is_available():
        return False, "Google Drive setup mukammal nahi hai."

    service = _get_drive_service()
    if service is None:
        return False, "❌ Google Drive se connection nahi hai."

    try:
        folder_id = _get_or_create_folder_path(service, ["AfzalStore", subfolder])
        if not folder_id:
            return False, "❌ Drive par 'AfzalStore/Photos' folder nahi ban saka."

        file_metadata = {"name": filename, "parents": [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(photo_bytes), mimetype="image/jpeg", resumable=True)
        uploaded = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        return True, uploaded.get("id", "")
    except Exception as e:
        msg = str(e).lower()
        if "quota" in msg or "storage" in msg:
            return False, "❌ Google Drive storage full hai."
        elif "network" in msg or "connection" in msg or "timeout" in msg:
            return False, "❌ Internet connection nahi mila - photo baad mein Drive par upload hogi."
        return False, f"❌ Photo upload nahi ho saki: {e}"


def sync_pending_local_photos(local_folder="bill_images"):
    """Roz ke auto-backup ke sath chalta hai - agar Drive us waqt available nahi
    thi jab koi photo li gayi thi (local mein save ho gayi), to yeh function
    baad mein chup-chaap unhe Drive par bhi upload kar deta hai. Kabhi crash
    nahi karta, kisi bhi wajah se fail ho to bas skip kar deta hai."""
    if not is_connected() or not os.path.isdir(local_folder):
        return 0

    marker_file = os.path.join(local_folder, ".synced_to_drive.json")
    try:
        synced = set(json.load(open(marker_file))) if os.path.exists(marker_file) else set()
    except (json.JSONDecodeError, OSError):
        synced = set()

    uploaded_count = 0
    try:
        for fname in os.listdir(local_folder):
            if fname in synced or fname.startswith("."):
                continue
            full_path = os.path.join(local_folder, fname)
            if not os.path.isfile(full_path):
                continue
            try:
                with open(full_path, "rb") as f:
                    photo_bytes = f.read()
                success, _ = upload_photo_to_drive(photo_bytes, fname)
                if success:
                    synced.add(fname)
                    uploaded_count += 1
            except OSError:
                continue

        try:
            with open(marker_file, "w") as f:
                json.dump(list(synced), f)
        except OSError:
            pass
    except OSError:
        pass

    return uploaded_count
    """Drive par maujood backups ki list deta hai (naya se purana). Kabhi crash nahi
    karta - error ki soorat mein khali list wapas deta hai."""
    if not is_available():
        return []
    service = _get_drive_service()
    if service is None:
        return []
    try:
        folder_id = _get_or_create_backup_folder(service)
        if not folder_id:
            return []
        results = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            spaces="drive", fields="files(id, name, createdTime, size)",
            orderBy="createdTime desc").execute()
        return results.get("files", [])
    except Exception:
        return []


MAIN_DB_DRIVE_NAME = "afzal_store_MAIN.db"


def _get_main_db_file_id(service, folder_id):
    try:
        results = service.files().list(
            q=f"name='{MAIN_DB_DRIVE_NAME}' and '{folder_id}' in parents and trashed=false",
            spaces="drive", fields="files(id, modifiedTime)").execute()
        files = results.get("files", [])
        return files[0] if files else None
    except Exception:
        return None


def get_drive_main_db_modified_time():
    """Drive par maujood MAIN database ka last-modified time deta hai (ya None
    agar Drive par abhi tak koi nahi hai / connect nahi hai). Isay local file ke
    mtime se compare kar ke pata chalta hai kaunsi copy 'nayi' hai."""
    if not is_available():
        return None
    service = _get_drive_service()
    if service is None:
        return None
    try:
        folder_id = _get_or_create_backup_folder(service)
        if not folder_id:
            return None
        file_info = _get_main_db_file_id(service, folder_id)
        if not file_info:
            return None
        from datetime import datetime as _dt
        return _dt.strptime(file_info["modifiedTime"], "%Y-%m-%dT%H:%M:%S.%fZ")
    except Exception:
        return None


def upload_main_db_to_drive(local_db_path="afzal_store.db"):
    """MAIN database ko Drive par upload/update karta hai (ek hi file, dated
    backups se alag) - yeh woh file hai jo har device 'latest' maan kar
    download karta hai. Returns (success: bool, message: str)."""
    if not is_available():
        return False, "Google Drive setup mukammal nahi hai."
    if not os.path.exists(local_db_path):
        return False, f"❌ '{local_db_path}' nahi mili."

    service = _get_drive_service()
    if service is None:
        return False, "❌ Google Drive se connection nahi hai."

    try:
        folder_id = _get_or_create_backup_folder(service)
        if not folder_id:
            return False, "❌ Drive par folder nahi ban saka."

        existing = _get_main_db_file_id(service, folder_id)
        media = MediaFileUpload(local_db_path, mimetype="application/octet-stream", resumable=True)

        if existing:
            service.files().update(fileId=existing["id"], media_body=media).execute()
        else:
            service.files().create(body={"name": MAIN_DB_DRIVE_NAME, "parents": [folder_id]}, media_body=media, fields="id").execute()

        return True, "✅ Database Drive par sync ho gayi."
    except Exception as e:
        msg = str(e).lower()
        if "quota" in msg or "storage" in msg:
            return False, "❌ Google Drive storage full hai."
        elif "network" in msg or "connection" in msg or "timeout" in msg:
            return False, "❌ Internet nahi mila - sync baad mein dobara try hogi."
        return False, f"❌ Sync nahi ho saki: {e}"


def download_main_db_if_newer(local_db_path="afzal_store.db"):
    """Agar Drive par maujood MAIN database, local copy se NAYI hai, to download
    kar ke local file replace kar deta hai. Returns (downloaded: bool, message: str).
    Kabhi bhi local file ko bina wajah overwrite nahi karta - sirf jab Drive
    version genuinely newer ho."""
    if not is_available():
        return False, "Google Drive setup mukammal nahi hai."
    service = _get_drive_service()
    if service is None:
        return False, "Google Drive se connection nahi hai."

    try:
        folder_id = _get_or_create_backup_folder(service)
        if not folder_id:
            return False, "Drive folder nahi mila."
        file_info = _get_main_db_file_id(service, folder_id)
        if not file_info:
            return False, "Drive par abhi tak koi database nahi hai (pehli baar)."

        from datetime import datetime as _dt
        drive_time = _dt.strptime(file_info["modifiedTime"], "%Y-%m-%dT%H:%M:%S.%fZ")
        local_time = _dt.utcfromtimestamp(os.path.getmtime(local_db_path)) if os.path.exists(local_db_path) else _dt.min

        if drive_time <= local_time:
            return False, "Local database already up-to-date hai."

        temp_path = local_db_path + ".drive_download_tmp"
        request = service.files().get_media(fileId=file_info["id"])
        fh = io.FileIO(temp_path, "wb")
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.close()

        # Purani file ko chhoti si safety copy rakh kar hi replace karo
        if os.path.exists(local_db_path):
            try:
                import shutil
                shutil.copy2(local_db_path, local_db_path + ".before_drive_sync.bak")
            except OSError:
                pass
        os.replace(temp_path, local_db_path)
        return True, "✅ Naya data Google Drive se mil gaya (kisi doosri device se aaya hoga)."
    except Exception as e:
        return False, f"⚠️ Drive se check nahi ho saka: {e}"


def download_backup_from_drive(file_id, dest_path):
    """Chuna hua backup Drive se download kar ke dest_path par save karta hai.
    Returns (success: bool, message: str)."""
    if not is_available():
        return False, "Google Drive setup mukammal nahi hai."
    service = _get_drive_service()
    if service is None:
        return False, "❌ Google Drive se connection nahi hai."

    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.FileIO(dest_path, "wb")
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.close()
        return True, "✅ Backup Google Drive se download ho gaya!"
    except Exception as e:
        return False, f"❌ Download nahi ho saka: {e}"


def auto_drive_backup_if_due(local_db_path="afzal_store.db"):
    """Daily local backup ki tarah, agar Drive backup ON hai aur aaj abhi tak nahi
    hua, to chup-chaap background mein Drive par bhi upload kar deta hai. Kisi bhi
    wajah se fail ho (internet na ho, token expire ho jaye) to app ko koi farak
    nahi parta - agli baar phir try hoga."""
    settings = load_settings()
    if not settings.get("auto_drive_backup_enabled"):
        return False

    today_str = datetime.now().strftime("%Y-%m-%d")
    if settings.get("last_drive_backup_date") == today_str:
        return False  # aaj ka backup ho chuka hai

    if not is_connected():
        return False  # connect nahi hai - chup-chaap skip, agli baar try hoga

    try:
        success, _ = upload_backup_to_drive(local_db_path)
        if success:
            settings["last_drive_backup_date"] = today_str
            save_settings(settings)
        return success
    except Exception:
        return False
def list_drive_backups():
    try:
        service = _get_drive_service()
        if not service:
            return []
        results = service.files().list(
            q="trashed=false", 
            pageSize=20, 
            fields="files(id, name, size, modifiedTime)"
        ).execute()
        files = results.get('files', [])
        backups = []
        for f in files:
            if 'afzal' in f['name'].lower() or 'backup' in f['name'].lower() or '.db' in f['name'].lower():
                backups.append(f)
        return backups
    except Exception as e:
        print(f"List backup error: {e}")
        return []

# ---------------------------------------------------------------------
# EXACT-NAMED WRAPPERS (auto_sync_from_drive / upload_backup)
# app.py inhi 2 naamon se call karta hai. Yeh naye code nahi likhtay -
# upar wale already-tested functions (download_main_db_if_newer,
# upload_backup_to_drive) ko hi dobara istemal karte hain, taake
# working logic dobara na likhna paray.
# ---------------------------------------------------------------------
import threading as _threading

_DB_CANDIDATE_NAMES = ["afzal_store.db"]
_last_upload_thread = {"running": False}


def _resolve_db_path(local_db_path="afzal_store.db"):
    """User ne bataya ke DB kabhi root mein hoti hai, kabhi _internal/ mein -
    dono jagah check karta hai, jahan file waqai maujood ho wahi istemal
    karta hai."""
    if os.path.exists(local_db_path):
        return local_db_path
    return _resolve_path(local_db_path)


def auto_sync_from_drive(local_db_path="afzal_store.db", min_diff_minutes=2):
    """App start hote hi call karne ke liye. Drive par maujood MAIN database
    ka waqt local file se compare karta hai - agar Drive wali file
    `min_diff_minutes` se zyada nayi hai, to download kar ke local file
    replace kar deta hai. Chota farq (clock skew waghera) ignore hota hai
    taake har rerun par fuzool download na ho. Returns (downloaded: bool,
    message: str) - kabhi crash nahi karta, Drive na ho to chup-chaap
    (False, message) deta hai."""
    resolved_path = _resolve_db_path(local_db_path)

    if not is_available():
        return False, "Google Drive setup mukammal nahi hai."
    service = _get_drive_service()
    if service is None:
        return False, "Google Drive se connection nahi hai."

    try:
        folder_id = _get_or_create_backup_folder(service)
        if not folder_id:
            return False, "Drive folder nahi mila."
        file_info = _get_main_db_file_id(service, folder_id)
        if not file_info:
            return False, "Drive par abhi tak koi database nahi hai (pehli baar)."

        from datetime import datetime as _dt, timedelta as _td
        drive_time = _dt.strptime(file_info["modifiedTime"], "%Y-%m-%dT%H:%M:%S.%fZ")
        local_time = (_dt.utcfromtimestamp(os.path.getmtime(resolved_path))
                      if os.path.exists(resolved_path) else _dt.min)

        if drive_time <= local_time + _td(minutes=min_diff_minutes):
            return False, "Local database already up-to-date hai (ya farq bohot chota hai)."

        temp_path = resolved_path + ".drive_download_tmp"
        request = service.files().get_media(fileId=file_info["id"])
        fh = io.FileIO(temp_path, "wb")
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.close()

        if os.path.exists(resolved_path):
            try:
                import shutil
                shutil.copy2(resolved_path, resolved_path + ".before_drive_sync.bak")
            except OSError:
                pass
        os.replace(temp_path, resolved_path)
        return True, "✅ Naya data Google Drive se mil gaya (kisi doosri device se aaya hoga)."
    except Exception as e:
        return False, f"⚠️ Drive se check nahi ho saka: {e}"


def _background_upload_backup(local_db_path):
    """Alag thread mein chalta hai - koi st.* call nahi karta, is liye
    kabhi UI freeze nahi karta chahe internet kitna hi slow kyun na ho."""
    try:
        upload_backup_to_drive(local_db_path)
    except Exception:
        pass
    finally:
        _last_upload_thread["running"] = False


def upload_backup(local_db_path="afzal_store.db"):
    """Har data-save ke baad (Nayi Sale, Udhaar, Items Add, waghera) call
    karne ke liye. Turant return hota hai - asal upload background thread
    mein hoti hai, is liye form submit/save button kabhi 'hang' nahi hota.
    Sirf akhri 20 backups Drive par rakhta hai (purani khud delete)."""
    resolved_path = _resolve_db_path(local_db_path)
    if _last_upload_thread["running"]:
        return  # pehle se ek upload chal rahi hai - dobara shuru na karo
    _last_upload_thread["running"] = True
    t = _threading.Thread(target=_background_upload_backup, args=(resolved_path,), daemon=True)
    t.start()
