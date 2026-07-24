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
import re
import json
import threading
import urllib.parse
from datetime import datetime, timedelta

CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "drive_token.json"
SETTINGS_FILE = "drive_backup_settings.json"
DRIVE_FOLDER_NAME = "AfzalStore_Backups"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]  # sirf app ki apni files - poori Drive nahi
MAIN_DB_DRIVE_NAME = "afzal_store_MAIN.db"

# ---------------------------------------------------------------------
# DATED BACKUP RETENTION (History list ke liye - 1 din = 1 file)
# ---------------------------------------------------------------------
BACKUP_RETENTION_DAYS = 90  # 3 mahine - is se purani dated backup rolling delete hoti hai
_BACKUP_DATE_RE = re.compile(r"(\d{2}-\d{2}-\d{4})")

# ---------------------------------------------------------------------
# EMPTY-DB PROTECTION (data-loss bug fix)
# ---------------------------------------------------------------------
# BUG FIX: pehle sirf modifiedTime/mtime compare karte the ke "kaun nayi hai"
# - lekin agar app ek fresh/ephemeral container mein restart hoti hai (jahan
# local disk persist nahi karti), to sqlite3.connect() + CREATE TABLE se
# ek bilkul KHALI local afzal_store.db abhi-abhi ban jati hai - jis ka mtime
# "abhi" (sab se NAYA) ho jata hai, chahe usme data ka naam-o-nishaan na ho.
# Sirf mtime dekhne se yeh khali file "sab se nayi" lagti thi, is liye:
#   1) asal (bhari-bharkam) Drive data download hi nahi hota tha, aur
#   2) 5-second baad yehi khali file Drive par UPLOAD ho kar asal MAIN
#      backup ko bhi khali file se REPLACE kar deti thi.
# Ab timestamp ke sath-sath file "size" bhi dekha jata hai: agar koi file
# (local ya Drive) khatarnak tarah se choti hai jabke doosri taraf wali
# file khaasi badi hai, to us "choti" file par kabhi bharosa nahi kiya
# jata - chahe uska mtime/timestamp kitna hi "naya" kyun na ho.
EMPTY_DB_SIZE_THRESHOLD = 12 * 1024       # is se choti file "khali/stub" mani jati hai
                                           # (khali CREATE TABLE schema ~8KB hoti hai)
POPULATED_DB_SIZE_THRESHOLD = 20 * 1024   # is se badi file "waqai data wali" ho sakti hai
                                           # (chhota naya shop bhi jaldi is se aage nikal jata hai)
                                           # - asal faisla row-count se hota hai, yeh sirf
                                           # Drive side ke liye ek sasta pre-filter hai (Drive
                                           # file download kiye baghair uske andar rows nahi
                                           # gin sakte, is liye sirf size dekha jata hai).


def _local_db_size(local_db_path):
    try:
        return os.path.getsize(local_db_path) if os.path.exists(local_db_path) else 0
    except OSError:
        return 0


def _looks_empty(size_bytes):
    return size_bytes < EMPTY_DB_SIZE_THRESHOLD


def _looks_populated(size_bytes):
    return size_bytes > POPULATED_DB_SIZE_THRESHOLD


def _local_db_row_count(local_db_path):
    """Local DB mein kitni 'asal' rows hain (items+sales+khata jama), sirf
    size ke ilawa ek extra content-based check ke liye. Kabhi crash nahi
    karta - table na ho ya file locked ho to bas 0 wapas karta hai."""
    if not os.path.exists(local_db_path):
        return 0
    total = 0
    try:
        import sqlite3
        conn = sqlite3.connect(local_db_path, timeout=3)
        for table in ("items", "sales", "khata", "customers"):
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
                total += cur.fetchone()[0] or 0
            except Exception:
                pass
        conn.close()
    except Exception:
        pass
    return total


def is_running_on_cloud():
    """Streamlit Cloud (ya kisi bhi ephemeral-storage hosting) par chal rahi
    hai ya user ke apne PC/localhost par - is ka andaza lagata hai taake UI
    mein sirf wahi options dikhayein jo us jagah kaam karte hain (jaise
    'Local Backup (Computer)' localhost par hi maayne rakhta hai, Cloud par
    disk restart par mit jati hai is liye wahan dikhana hi ghalat-fehmi
    paida karta hai). Kabhi crash nahi karta - pata na chale to False
    (yani 'local/offline' maan leta hai, jo zyada permissive/safe hai)."""
    try:
        if os.getenv("STREAMLIT_RUNTIME"):
            return True
        # Streamlit Community Cloud apps hamesha isi tarah ke path se chalti hain
        if os.path.exists("/mount/src") or os.getcwd().startswith("/mount/src"):
            return True
        # 'gdrive_token' Streamlit Secrets mein ho (na ke local drive_token.json
        # file) - yeh bhi hosted/cloud deployment ka strong signal hai.
        if _has_cloud_token():
            return True
    except Exception:
        pass
    return False


def _backup_filename_for_today():
    """Aaj ki tareekh wala dated-backup naam - is naam ki file din mein
    kitni bhi baar banayi jaye, hamesha WAHI EK file overwrite hoti hai."""
    return f"afzal_store_backup_{datetime.now().strftime('%d-%m-%Y')}.db"


def _parse_backup_date(filename):
    """Filename mein se DD-MM-YYYY nikal kar date() deta hai. Na mile ya
    invalid ho to None (aisi files retention/list dono se chup-chaap
    ignore ho jati hain, kabhi delete nahi hoti)."""
    m = _BACKUP_DATE_RE.search(filename or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d-%m-%Y").date()
    except ValueError:
        return None


def _is_dated_backup_name(name):
    """MAIN.db (master file) is check se KABHI match nahi hoti - sirf
    'afzal_store_backup_...db' jaisi dated history files match hoti hain.
    Isi function ki wajah se retention/cleanup logic MAIN.db ko kabhi
    haath tak nahi laga sakta."""
    if not name or name == MAIN_DB_DRIVE_NAME:
        return False
    lname = name.lower()
    return "backup" in lname and lname.endswith(".db")


# ---------------------------------------------------------------------
# CLOUD BOOTSTRAP: Streamlit Cloud par client_secret.json file GitHub par
# daalna theek nahi (yeh secret hoti hai), is liye is ke bajaye poora JSON
# Streamlit Secrets mein [gdrive] client_secret_json ke naam se rakha jata
# hai. Yeh function module load hote hi (sab se pehle) chal kar us secret
# se ek ASAL client_secret.json file bana deta hai - taake neeche wala
# purana code (jo hamesha se ek physical file dhoondta hai) bina kisi
# tabdeeli ke chalta rahe, chahe Local PC ho ya Cloud.
# ---------------------------------------------------------------------
def _bootstrap_client_secret_from_secrets():
    """Streamlit Secrets mein [gdrive] client_secret_json (dict ya JSON-string,
    dono chalte hain) dhoondta hai aur agar milay to us se client_secret.json
    file 4 mumkin jagah par bana deta hai:
        client_secret.json
        internal/client_secret.json
        _internal/client_secret.json
        internal/_internal/client_secret.json
    (root aur is script ki apni location - dono se relative, taake app kahin
    se bhi chalayi jaye, file mil jaye.)

    - Agar file kisi jagah pehle se maujood hai, use overwrite nahi karta.
    - Agar Streamlit hi installed nahi, Secrets available nahi, ya secret
      ka format ghalat hai - chup-chaap kuch nahi karta, KABHI crash nahi
      karta (Local PC par yeh function bilkul koi asar nahi dalta)."""
    try:
        import streamlit as st
    except Exception:
        return  # Streamlit installed hi nahi - plain local/script context

    try:
        if not hasattr(st, "secrets") or "gdrive" not in st.secrets:
            return
        raw = st.secrets["gdrive"].get("client_secret_json")
        if not raw:
            return

        # Dono format handle karo: dict (TOML table) ya string (triple-quoted JSON)
        if isinstance(raw, str):
            secret_dict = json.loads(raw)
        else:
            secret_dict = dict(raw)

        here = os.path.dirname(os.path.abspath(__file__))     # jahan yeh script hai
        parent = os.path.dirname(here)                          # is se ek folder upar
        bases = {os.getcwd(), here, parent}                     # sab mumkin "root" jagah

        relative_targets = [
            "client_secret.json",
            os.path.join("internal", "client_secret.json"),
            os.path.join("_internal", "client_secret.json"),
            os.path.join("internal", "_internal", "client_secret.json"),
        ]

        written_any = False
        for base in bases:
            for rel in relative_targets:
                target = os.path.join(base, rel)
                try:
                    if os.path.exists(target):
                        continue  # pehle se hai - dobara na likho
                    target_dir = os.path.dirname(target)
                    if target_dir:
                        os.makedirs(target_dir, exist_ok=True)
                    with open(target, "w") as f:
                        json.dump(secret_dict, f)
                    written_any = True
                except OSError:
                    continue  # is jagah likhne ki ijazat nahi - agli jagah try karo
        return written_any
    except Exception:
        return False  # kisi bhi wajah se secret na parh saka - app crash na ho


# App import hote hi ek baar chal jata hai - is ke baad se poora purana
# file-based code (get_client_secret_path, is_available, connect_to_drive
# waghera) bilkul pehle jaisa hi kaam karta hai, chahe Cloud ho ya Local.
_bootstrap_client_secret_from_secrets()


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


def _get_cloud_token_raw():
    """st.secrets mein 'gdrive_token' dhoondta hai - top-level par (jaisa
    documentation mein bataya gaya) YA agar kisi ne galti se [gdrive] section
    ke andar daal diya ho, wahan bhi check karta hai. Kuch na mile to None."""
    try:
        import streamlit as st
        if not hasattr(st, "secrets"):
            return None
        if "gdrive_token" in st.secrets:
            return st.secrets["gdrive_token"]
        if "gdrive" in st.secrets:
            section = st.secrets["gdrive"]
            try:
                if "gdrive_token" in section:
                    return section["gdrive_token"]
            except Exception:
                pass
    except Exception:
        pass
    return None


def _has_cloud_token():
    """Streamlit Cloud par client_secret.json file nahi hoti - agar Secrets mein
    pehle se ek valid token maujood hai, to Drive available maan lo (Connect
    flow Cloud par chalti hi nahi, sirf local PC par ek-baara chalti hai)."""
    return _get_cloud_token_raw() is not None


def cloud_token_diagnostics():
    """Secret ki VALUE kabhi bhi wapas nahi karta - sirf yeh batata hai ke
    kis stage tak cheezein sahi hain, taake 'connect nahi ho raha' jaisi
    khamoshh (silent) nakami ki bajaye asal wajah pata chal sake."""
    info = {"secret_mila": False, "json_theek_hai": False, "credentials_valid": False, "error": None}
    raw = _get_cloud_token_raw()
    if raw is None:
        return info
    info["secret_mila"] = True
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
        info["json_theek_hai"] = True
        creds = Credentials.from_authorized_user_info(data, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        info["credentials_valid"] = bool(creds and creds.valid)
    except Exception as e:
        info["error"] = str(e)[:200]
    return info


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
    return {"auto_drive_backup_enabled": True, "last_drive_backup_date": None}


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


_connect_state = {"flow": None}


def start_drive_connect():
    """Ek authorization URL banata hai jo seedha Streamlit UI mein dikhayi ja
    sakti hai. PEHLE yeh ek local server (localhost:8765) chalata tha jo
    Google ke redirect ka intezar karta - lekin Streamlit CLOUD par yeh
    KABHI kaam nahi kar sakta: jab user apne browser mein 'Allow' dabata
    hai, Google us USER KE APNE browser ko localhost par bhejta hai - aur
    'localhost' hamesha user ki apni machine hoti hai, Cloud server nahi.
    Is liye us mode mein "localhost refused to connect" hamesha aata,
    chahe code kuch bhi ho.
    NAYA TAREEQA (local aur Cloud dono par barabar kaam karta hai): user ko
    sirf link di jati hai; Allow karne ke baad jo (chahe error) page khule
    us ke URL bar se poora link copy kar ke wapas app mein paste karna hota
    hai - hum us se sirf 'code' nikal lete hain, kisi listening server ki
    zaroorat nahi. Returns (auth_url, error_message)."""
    if not GOOGLE_LIBS_AVAILABLE:
        return None, "❌ Google Drive libraries install nahi hain. Terminal mein yeh chalayein:\npip install google-auth-oauthlib google-api-python-client google-auth-httplib2"
    secret_path = get_client_secret_path()
    if not os.path.exists(secret_path):
        return None, f"❌ '{CLIENT_SECRET_FILE}' file root ya _internal folder, kisi mein bhi nahi mili."

    try:
        flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
        # 'http://localhost/' istemal kar rahe hain sirf taake Google ka
        # "Desktop app" client type ise valid maane (yeh kisi bhi localhost
        # redirect ko automatically allow karta hai) - hum is par kabhi
        # actually listen nahi karte, is liye yeh Cloud par bhi chalega.
        flow.redirect_uri = "http://localhost/"
        auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
        _connect_state["flow"] = flow
        return auth_url, None
    except Exception as e:
        return None, f"❌ {e}"


def complete_drive_connect(pasted_text):
    """User jo bhi paste kare - poora redirect URL (jisme 'localhost refused
    to connect' dikha ho) YA sirf 'code' - usme se authorization code nikal
    kar token banata hai aur save kar deta hai. Kaam karta hai chahe
    'connection refused' page dikha ho, kyunke code hamesha URL ke andar
    hota hai, page load hone se koi farq nahi padta.
    Returns (success: bool, message: str)."""
    flow = _connect_state.get("flow")
    if not flow:
        return False, "Pehle 'Google Drive Connect Karo' button dabayein."

    text = (pasted_text or "").strip()
    if not text:
        return False, "Pehle upar wale box mein URL ya code paste karein."

    code = None
    if "code=" in text:
        try:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(text).query)
            if "code" in qs:
                code = qs["code"][0]
        except Exception:
            code = None
    if not code:
        code = text  # shayad sirf bare code hi paste kiya ho

    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
        _connect_state["flow"] = None
        return True, "✅ Google Drive kamyabi se connect ho gayi!"
    except Exception as e:
        return False, f"❌ Code sahi nahi tha ya expire ho gaya: {e}\n\nDobara 'Connect Karo' se shuru karein."


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
        # BUG FIX: pehle flow.run_local_server(port=0) khud webbrowser.open()
        # try karta tha - agar PC par default-browser association kharab ho
        # (ya koi bhi wajah se Python browser auto-launch na kar sake) to
        # yeh "could not locate runnable browser" wala exception deta tha
        # aur poori Connect flow fail ho jati thi. Ab open_browser=False se
        # yeh auto-launch bilkul try hi nahi karta - is ke bajaye ek link
        # TERMINAL/CMD window mein print hoti hai (jahan se `streamlit run
        # app.py` chalaya tha) jise aap khud copy kar ke kisi bhi browser
        # mein paste kar sakte hain. Isi wajah se yeh error class ab kabhi
        # nahi aa sakta.
        creds = flow.run_local_server(
            port=0,
            open_browser=False,
            authorization_prompt_message=(
                "\n👉 Apna CMD/Terminal window dekhein - wahan ek link print hui hai.\n"
                "Us link ko copy kar ke apne kisi bhi browser mein paste karein,\n"
                "apna Google account select/allow karein, phir yahan wapas aa jayein.\n"
            ),
        )
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
        token_json = _get_cloud_token_raw()
        if token_json is not None:
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
    """Live database file ko 'AAJ KI TAREEKH' wali dated backup ke taur par
    Google Drive par upload karta hai. Din mein yeh function kitni bhi baar
    chale (auto-daily-check, dobara rerun, ya manual button), NAYI file
    KABHI nahi banti - agar aaj ki tareekh wali file Drive par pehle se hai
    to usi ko UPDATE (overwrite) kar diya jata hai. Isi wajah se Drive ki
    history list mein hamesha zyada se zyada EK file per din hi rehti hai.
    Returns (success: bool, message: str)."""
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

        drive_filename = _backup_filename_for_today()

        # Aaj ki tareekh wali file Drive par pehle se maujood hai kya?
        existing_id = None
        try:
            results = service.files().list(
                q=f"name='{drive_filename}' and '{folder_id}' in parents and trashed=false",
                spaces="drive", fields="files(id)").execute()
            found = results.get("files", [])
            existing_id = found[0]["id"] if found else None
        except Exception:
            existing_id = None

        media = MediaFileUpload(local_db_path, mimetype="application/octet-stream", resumable=True)
        if existing_id:
            service.files().update(fileId=existing_id, media_body=media).execute()
        else:
            service.files().create(body={"name": drive_filename, "parents": [folder_id]},
                                    media_body=media, fields="id").execute()

        _apply_drive_retention(service, folder_id)
        return True, f"✅ Google Drive par backup ho gaya: {drive_filename}"
    except Exception as e:
        msg = str(e).lower()
        if "quota" in msg or "storage" in msg:
            return False, "❌ Aapki Google Drive storage full hai. Purani files delete karein ya storage bharain."
        elif "network" in msg or "connection" in msg or "timeout" in msg:
            return False, "❌ Internet connection nahi mila. Backup baad mein dobara try hoga."
        return False, f"❌ Drive upload nahi ho saka: {e}"


def _apply_drive_retention(service, folder_id):
    """Drive Backups folder par 2 kaam karta hai (MAIN.db ko kabhi chhoo
    nahi ta - sirf dated 'afzal_store_backup_*.db' files par asar hota hai):

    (a) Agar kisi bhi EK din ki 1 se zyada dated files mil jayen (purani
        history se, jab pehle time-wale naam bante the), sirf sab se NAYI
        rakhta hai, baaki usi din ki extra files mita deta hai - isi se
        list turant 'ek din = ek file' ban jati hai.
    (b) 90 din (3 mahine) se purani koi bhi dated backup khud rolling
        delete ho jati hai - pehle 90 din mein KUCH bhi delete nahi hota,
        us ke baad rozana bilkul 1 purani file (90 din wali) hatt jati hai."""
    try:
        results = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            spaces="drive", fields="files(id, name, createdTime)").execute()
        files = results.get("files", [])
    except Exception:
        return

    by_date = {}
    for f in files:
        if not _is_dated_backup_name(f.get("name", "")):
            continue  # MAIN.db ya koi aur file - kabhi mat chuo
        day = _parse_backup_date(f["name"])
        if day is None:
            continue
        by_date.setdefault(day, []).append(f)

    cutoff = datetime.now().date() - timedelta(days=BACKUP_RETENTION_DAYS)

    for day, group in by_date.items():
        # (a) Isi din ki duplicate files mein se sirf nayi rakho
        if len(group) > 1:
            group.sort(key=lambda f: f.get("createdTime", ""), reverse=True)
            for extra in group[1:]:
                try:
                    service.files().delete(fileId=extra["id"]).execute()
                except Exception:
                    pass
            group = group[:1]
        # (b) 90 din se purani - rolling delete
        if day < cutoff:
            for f in group:
                try:
                    service.files().delete(fileId=f["id"]).execute()
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


def _get_main_db_file_id(service, folder_id):
    try:
        results = service.files().list(
            q=f"name='{MAIN_DB_DRIVE_NAME}' and '{folder_id}' in parents and trashed=false",
            spaces="drive", fields="files(id, modifiedTime, size)").execute()
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

        # EMPTY-DB PROTECTION: agar local file khatarnak tarah se choti/khali hai
        # (jaise fresh container restart ke baad abhi-abhi CREATE TABLE se bani ho)
        # jabke Drive par pehle se ek 'waqai data wali' MAIN backup maujood hai, to
        # kabhi upload nahi karte - warna asal data isi khali file se overwrite ho
        # jata. Row-count bhi dekha jata hai (size ke sath) taake false-positive na ho.
        if existing:
            local_size = _local_db_size(local_db_path)
            drive_size = int(existing.get("size") or 0)
            if _looks_empty(local_size) and _looks_populated(drive_size) and _local_db_row_count(local_db_path) == 0:
                return False, (
                    "⚠️ Local database khali/naya lag raha hai jabke Drive par pehle se "
                    "data-wali backup maujood hai - safety ke liye upload skip kar diya "
                    "gaya taake asal data zaya na ho."
                )

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


def download_main_db_if_newer(local_db_path="afzal_store.db", force=False):
    """Agar Drive par maujood MAIN database, local copy se NAYI hai, to download
    kar ke local file replace kar deta hai. Returns (downloaded: bool, message: str).
    Kabhi bhi local file ko bina wajah overwrite nahi karta - sirf jab Drive
    version genuinely newer ho.

    force=True: 'newer hai ya nahi' wala mtime check bilkul skip kar ke seedha
    download karta hai (sirf empty-db protection abhi bhi lागu rehta hai) - yeh
    startup recovery ke liye hai jab local file khud khali/naya-bana hua ho
    (jaise Streamlit Cloud par ephemeral restart ke baad) aur uska mtime "nayi"
    dikhane laga ho, chahe usme koi asal data na ho."""
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

        local_size = _local_db_size(local_db_path)
        drive_size = int(file_info.get("size") or 0)

        # EMPTY-DB PROTECTION (BUG FIX): local file ka mtime "nayi" lag sakta hai
        # sirf is liye ke woh abhi-abhi (fresh restart par) khali table ke sath
        # bani hai - is tarah ki khali/stub file ko kabhi "up-to-date" maan kar
        # asal Drive data download karne se mana nahi karte. Row-count se bhi
        # confirm karte hain taake sirf size ka dhoka na ho.
        local_is_stub = (
            _looks_empty(local_size) and _looks_populated(drive_size)
            and _local_db_row_count(local_db_path) == 0
        )

        if drive_time <= local_time and not local_is_stub and not force:
            return False, "Local database already up-to-date hai."

        # ULTA protection: agar Drive wali file khud choti/khali hai jabke local
        # mein waqai data maujood hai, to us khali Drive file se local ko kabhi
        # overwrite nahi karte, chahe timestamp ya force flag kuch bhi kahe -
        # yeh protection force=True ke sath bhi hamesha lagu rehta hai.
        if _looks_empty(drive_size) and _looks_populated(local_size) and _local_db_row_count(local_db_path) > 0:
            return False, "Drive backup khali lag rahi hai - safety ke liye local data overwrite nahi kiya gaya."

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
    """Rozana - agar aaj abhi tak dated backup nahi hua, to chup-chaap
    background mein Drive par bhi bana/update kar deta hai. Data-safety ki
    wajah se yeh HAMESHA internally chalta hai (UI ka toggle sirf preference
    dikhane ke liye hai, isay band nahi kar sakta) - taake user galti se
    bhi toggle OFF kar de to bhi kabhi data sync rukay nahi. Kisi bhi wajah
    se fail ho (internet na ho, token expire ho jaye) to app ko koi farak
    nahi parta - agli baar phir try hoga."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    settings = load_settings()
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
    """'Advanced - Purani History' ke liye - sirf DATED history files
    (afzal_store_backup_DD-MM-YYYY.db) deta hai, MAIN.db ya koi aur file
    KABHI is list mein shamil nahi hoti. Ab har din ki sirf 1 hi file hoti
    hai is liye list chhoti aur saaf rehti hai. Nayi tareekh sab se upar."""
    try:
        service = _get_drive_service()
        if not service:
            return []
        folder_id = _get_or_create_backup_folder(service)
        if not folder_id:
            return []
        results = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="files(id, name, size, modifiedTime, createdTime)"
        ).execute()
        files = results.get('files', [])
        dated = [f for f in files if _is_dated_backup_name(f.get("name", ""))]
        dated.sort(key=lambda f: _parse_backup_date(f["name"]) or datetime.min.date(), reverse=True)
        return dated
    except Exception as e:
        print(f"List backup error: {e}")
        return []


def restore_main_db_from_drive(dest_path="afzal_store.db"):
    """ONE-CLICK FULL RESTORE: Drive par maujood afzal_store_MAIN.db - jo
    HAMESHA sab se latest/complete data (sab customers, items, udhaar,
    sab kuch) rakhti hai - seedha `dest_path` par utaar deta hai. Windows
    reinstall / PC crash / PC chori jaisi situation mein, kisi list mein se
    date chunne ki zaroorat nahi - bas ek click aur poora data wapas.
    Returns (success: bool, message: str)."""
    if not is_available():
        return False, "Google Drive setup mukammal nahi hai."
    service = _get_drive_service()
    if service is None:
        return False, "❌ Google Drive se connection nahi hai."

    try:
        folder_id = _get_or_create_backup_folder(service)
        if not folder_id:
            return False, "❌ Drive par backup folder nahi mila."
        file_info = _get_main_db_file_id(service, folder_id)
        if not file_info:
            return False, "❌ Drive par abhi tak MAIN database maujood nahi hai."

        # Purani local file ki safety copy pehle rakh lo, taake restore
        # galti se bhi ho jaye to purana data zaya na ho
        if os.path.exists(dest_path):
            try:
                import shutil
                safety_name = dest_path + f".before_full_restore_{datetime.now().strftime('%d-%m-%Y_%H-%M-%S')}.bak"
                shutil.copy2(dest_path, safety_name)
            except OSError:
                pass

        temp_path = dest_path + ".main_restore_tmp"
        request = service.files().get_media(fileId=file_info["id"])
        fh = io.FileIO(temp_path, "wb")
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.close()
        os.replace(temp_path, dest_path)
        return True, "✅ Poora data Google Drive (MAIN backup) se successfully wapas aa gaya!"
    except Exception as e:
        return False, f"❌ Restore nahi ho saka: {e}"

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
