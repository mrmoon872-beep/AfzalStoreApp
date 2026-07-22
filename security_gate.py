"""
Security Gate - AfzalStore
=============================
3 layers:
1. Master Key (?key=afzal786) - basic gate, hides app from randomly-found URLs
2. Device Lock - localStorage token, checked against Drive's allowed_devices.json
3. Admin Panel (?admin=true) - block/unblock devices from anywhere

⚠️ HONEST LIMITS (please read):
- Master Key is NOT strong security - it's a static string visible in the URL.
  Anyone who sees the URL once (screenshot, browser history, shared link) has
  it forever. It stops casual/accidental discovery, not a determined person.
- Device Lock uses browser localStorage, NOT hardware fingerprinting. Clearing
  browser data, incognito mode, or a new browser = new device_id = needs
  re-approval. This is expected behaviour, not a bug.
- If Google Drive is not connected/available, the device-lock check is SKIPPED
  (only the master key applies) so a Drive outage can never lock the owner out
  of their own shop. This is a deliberate trade-off.
"""

import os
import json
import time
import streamlit as st
import streamlit.components.v1 as components

ALLOWED_DEVICES_FILE_NAME = "allowed_devices.json"
DEFAULT_MASTER_KEY = "afzal786"
_CACHE_TTL = 20  # seconds - kill-switch changes on Drive take effect within this window


def _get_master_key():
    try:
        if hasattr(st, "secrets") and "MASTER_KEY" in st.secrets:
            return str(st.secrets["MASTER_KEY"])
    except Exception:
        pass
    return DEFAULT_MASTER_KEY


def _access_denied_screen(title, message):
    st.markdown(f"""
        <div style="display:flex; align-items:center; justify-content:center; min-height:70vh;">
            <div style="text-align:center; background:#fff3f3; border:2px solid #dc3545; border-radius:16px; padding:40px 30px; max-width:420px;">
                <h1 style="color:#dc3545; margin:0;">🔒</h1>
                <h2 style="color:#dc3545; margin:10px 0;">{title}</h2>
                <p style="color:#555; font-size:15px;">{message}</p>
            </div>
        </div>
    """, unsafe_allow_html=True)
    # Blocked/stolen device ki soorat mein local cache/localStorage bhi saaf kar dete hain
    components.html("""
        <script>
        try { localStorage.removeItem('afzal_device_id'); } catch(e) {}
        </script>
    """, height=0)
    st.stop()


def _ensure_device_id_in_url():
    """URL mein 'device_id' na ho to, JS se localStorage check/generate kar ke
    URL mein add karta hai (page ek dafa reload hogi). Yeh dependency-free
    tareeqa hai - koi extra Streamlit component install karne ki zaroorat nahi."""
    st.markdown("""
        <div style="display:flex; align-items:center; justify-content:center; min-height:60vh;">
            <div style="text-align:center;">
                <h3>🔐 Verifying Device...</h3>
                <p style="color:#888;">Ek second rukiye...</p>
            </div>
        </div>
    """, unsafe_allow_html=True)
    components.html("""
        <script>
        (function() {
            try {
                let deviceId = localStorage.getItem('afzal_device_id');
                if (!deviceId) {
                    deviceId = 'dev-' + crypto.randomUUID();
                    localStorage.setItem('afzal_device_id', deviceId);
                }
                const url = new URL(window.parent.location.href);
                url.searchParams.set('device_id', deviceId);
                window.parent.location.replace(url.toString());
            } catch (e) {
                document.body.innerHTML = '<p style="color:red;">Device check failed: ' + e + '</p>';
            }
        })();
        </script>
    """, height=0)
    st.stop()


@st.cache_data(ttl=_CACHE_TTL, show_spinner=False)
def _cached_allowed_devices():
    """Drive se allowed_devices.json load karta hai. Kabhi crash nahi karta -
    fail ho to khali dict deta hai (jis se device-lock check khud-ba-khud
    'skip' ho jata hai, owner kabhi lock-out nahi hota)."""
    try:
        import google_drive_backup as gdrive
        if not gdrive.is_available() or not gdrive.is_connected():
            return None  # Drive available nahi - caller isay 'skip check' ki tarah treat karega

        service = gdrive._get_drive_service()
        if service is None:
            return None
        folder_id = gdrive._get_or_create_folder_path(service, ["AfzalStore", "Security"])
        if not folder_id:
            return None

        results = service.files().list(
            q=f"name='{ALLOWED_DEVICES_FILE_NAME}' and '{folder_id}' in parents and trashed=false",
            spaces="drive", fields="files(id)").execute()
        files = results.get("files", [])

        if not files:
            return {"_file_id": None, "_folder_id": folder_id, "devices": {}}

        import io
        from googleapiclient.http import MediaIoBaseDownload
        request = service.files().get_media(fileId=files[0]["id"])
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        data = json.loads(fh.getvalue().decode("utf-8"))
        data["_file_id"] = files[0]["id"]
        data["_folder_id"] = folder_id
        return data
    except Exception:
        return None


def _save_allowed_devices(data):
    """allowed_devices.json ko Drive par save/update karta hai. Admin panel
    (block/unblock/add) isay use karta hai."""
    try:
        import google_drive_backup as gdrive
        service = gdrive._get_drive_service()
        if service is None:
            return False

        file_id = data.pop("_file_id", None)
        folder_id = data.pop("_folder_id", None)
        payload = json.dumps({"devices": data.get("devices", {})}).encode("utf-8")

        import io
        from googleapiclient.http import MediaIoBaseUpload
        media = MediaIoBaseUpload(io.BytesIO(payload), mimetype="application/json")

        if file_id:
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            service.files().create(body={"name": ALLOWED_DEVICES_FILE_NAME, "parents": [folder_id]}, media_body=media, fields="id").execute()

        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"⚠️ Devices list Drive par save nahi ho saki: {e}")
        return False


def _gate_enforced_here():
    """Localhost par gate hamesha bypass hota hai - koi key/device_id kabhi
    nahi maanga jayega. Sirf Streamlit Cloud (ya jahan bhi aap chahen) par
    isay ON karne ke liye, us deployment ke Secrets mein yeh line add
    karein:
        ENFORCE_KEY = "true"
    Kuch na add karein to gate hamesha OFF rehta hai (app hamesha seedha
    khulta hai) - yeh reliable hai kyunke yeh URL/host detect karne ki
    koshish nahi karta (jo alag-alag Streamlit versions/proxies par
    consistent nahi hota) - balke aap khud seedha decide karte hain."""
    try:
        return hasattr(st, "secrets") and str(st.secrets.get("ENFORCE_KEY", "")).strip().lower() in ("1", "true", "yes")
    except Exception:
        return False


def enforce_security_gate():
    """App ke bilkul shuru mein call karo (kisi bhi page content se pehle).
    Returns True agar aage barhna safe hai. False/st.stop() agar block ho.
    Admin mode hai to True return karta hai lekin caller ko admin panel
    dikhana chahiye (is_admin_request() se check karein)."""

    if not _gate_enforced_here():
        # Local PC (ya koi bhi jagah jahan ENFORCE_KEY secret set nahi hai) -
        # hamesha seedha khulta hai, koi key/device_id/"Checking Access..."
        # kabhi nahi dikhta.
        return True

    # ---- LAYER 1: MASTER KEY ----
    url_key = st.query_params.get("key", "")
    expected_key = _get_master_key()
    if url_key != expected_key:
        _access_denied_screen(
            "Private Store - Access Denied",
            "Yeh app private hai. Sahi link/key ke bagair access nahi ho sakti."
        )
        return False

    # ---- LAYER 2: DEVICE LOCK ----
    device_id = st.query_params.get("device_id", "")
    if not device_id:
        _ensure_device_id_in_url()
        return False  # (unreachable - st.stop() already called above)

    allowed_data = _cached_allowed_devices()

    if allowed_data is None:
        # Drive available nahi hai - device-lock SKIP karte hain (sirf master key
        # kaafi hai) taake Drive down hone se owner khud lock-out na ho jaye.
        st.session_state["_device_id"] = device_id
        st.session_state["_device_lock_active"] = False
        return True

    st.session_state["_device_lock_active"] = True
    st.session_state["_device_id"] = device_id
    st.session_state["_allowed_devices_data"] = allowed_data

    devices = allowed_data.get("devices", {})

    # BOOTSTRAP: agar Drive par list bilkul khali hai (pehli baar setup ho raha
    # hai), pehli connect hone wali device ko khud-ba-khud owner maan kar
    # approve kar dete hain - warna koi bhi device kabhi approve nahi ho sakegi
    # (chicken-and-egg problem, admin panel khud bhi ek allowed device maangta hai).
    if not devices:
        devices[device_id] = {"label": "Owner (Auto-Approved First Device)", "added_date": time.strftime("%Y-%m-%d"), "blocked": False}
        allowed_data["devices"] = devices
        _save_allowed_devices(dict(allowed_data))
        st.session_state["_allowed_devices_data"] = _cached_allowed_devices() or allowed_data
        return True

    device_info = devices.get(device_id)
    if device_info is None:
        _access_denied_screen(
            "Device Not Registered",
            f"Yeh device abhi tak allow nahi hai. Owner ko yeh Device ID bhejein taake wo approve kar sakein:<br><br>"
            f"<code style='background:#eee; padding:4px 8px; border-radius:4px; font-size:12px;'>{device_id}</code>"
        )
        return False

    if device_info.get("blocked"):
        _access_denied_screen(
            "This Device is Blocked",
            "Yeh device owner ne block kar di hai. Agar yeh ghalti se hua hai to owner se raabta karein."
        )
        return False

    return True


def is_admin_request():
    return st.query_params.get("admin", "").lower() == "true"


def show_admin_panel():
    """Hidden admin page - ?key=...&admin=true se accessible. Allowed devices
    ki list dikhata hai, har ek ke saath Block/Unblock button."""
    st.title("🛡️ Admin Panel - Device Management")
    st.caption("Yahan se aap kisi bhi device ko allow/block kar sakte hain - tabdeeli turant Google Drive par save hoti hai.")

    if not st.session_state.get("_device_lock_active"):
        st.warning("⚠️ Google Drive connect nahi hai - Admin Panel sirf Drive connected hone par kaam karta hai.")
        return

    allowed_data = st.session_state.get("_allowed_devices_data") or _cached_allowed_devices()
    if allowed_data is None:
        st.error("Devices list load nahi ho saki.")
        return

    devices = allowed_data.get("devices", {})
    current_device = st.session_state.get("_device_id", "")

    st.info(f"📱 Yeh device (jo abhi admin panel dekh raha hai): `{current_device}`")
    st.divider()

    if not devices:
        st.info("Koi devices abhi tak register nahi hain.")
    else:
        for dev_id, info in list(devices.items()):
            col1, col2, col3 = st.columns([3, 1.5, 1.5])
            with col1:
                label = info.get("label", "Unnamed Device")
                is_current = " 👈 (Yeh Device)" if dev_id == current_device else ""
                st.write(f"**{label}**{is_current}")
                st.caption(f"`{dev_id}` | Added: {info.get('added_date', '?')}")
            with col2:
                status = "🔴 Blocked" if info.get("blocked") else "🟢 Allowed"
                st.write(status)
            with col3:
                if info.get("blocked"):
                    if st.button("✅ Unblock", key=f"unblock_{dev_id}", use_container_width=True):
                        devices[dev_id]["blocked"] = False
                        if _save_allowed_devices(dict(allowed_data)):
                            st.success("Unblocked!")
                            st.rerun()
                else:
                    if st.button("🚫 Block", key=f"block_{dev_id}", use_container_width=True, type="secondary"):
                        devices[dev_id]["blocked"] = True
                        if _save_allowed_devices(dict(allowed_data)):
                            st.success("Blocked! Agli baar yeh device khulte hi block ho jayegi.")
                            st.rerun()
            st.divider()

    st.markdown("#### ➕ Naya Device Manually Add Karo")
    st.caption("Agar koi device 'Not Registered' dikha raha hai, uska Device ID yahan paste kar ke add karein.")
    with st.form("add_device_form", clear_on_submit=True):
        new_id = st.text_input("Device ID (jaise dev-xxxxxxxx-xxxx-...)")
        new_label = st.text_input("Label (jaise 'Mera Mobile', 'Dukan PC')")
        if st.form_submit_button("➕ Add Karo", type="primary"):
            if new_id.strip():
                devices[new_id.strip()] = {"label": new_label.strip() or "Unnamed Device", "added_date": time.strftime("%Y-%m-%d"), "blocked": False}
                if _save_allowed_devices(dict(allowed_data)):
                    st.success("Device add ho gayi!")
                    st.rerun()
            else:
                st.error("Device ID likhna zaroori hai.")
