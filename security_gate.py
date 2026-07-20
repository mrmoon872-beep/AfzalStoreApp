"""
Security Gate - AfzalStore (Owner-Approval Device System)
=============================================================
NO shared password/key. Flow:

1. Naya mobile/browser link kholta hai -> "Request Access" button dikhta hai
2. Woh dabata hai -> request Google Drive par save hoti hai (status: pending)
3. Owner apne Admin Panel mein dekh kar Approve/Reject karta hai
4. Approve hone ke baad, WOHI browser hamesha ke liye andar aata rahega
   (localStorage mein device ka apna token save rehta hai)
5. Owner khud pehli baar app kholay to khud-ba-khud "Owner" ban jata hai
   (bootstrap - warna koi bhi kabhi approve nahi ho sakta)

⚠️ HONEST LIMITS (please read):
- Device Lock browser ki localStorage par based hai, hardware fingerprinting
  nahi. Browser cache clear karna, incognito, ya naya browser = nayi
  request banani paregi. Yeh design ka hissa hai, bug nahi.
- Agar Google Drive disconnect/down ho jaye, device-check SKIP ho jata hai
  (app phir bhi khulti hai) - taake Drive down hone se owner khud lock-out
  na ho jaye. Is halat mein app "open" rehti hai jab tak Drive wapas na aaye.
- Yeh ek chhoti dukan ke liye "kaafi acha" security hai, bank-grade nahi.
"""

import time
import streamlit as st
import streamlit.components.v1 as components

ALLOWED_DEVICES_FILE_NAME = "allowed_devices.json"
_CACHE_TTL = 15  # seconds - Drive se list kitni jaldi refresh hoti hai


# ==================== STEP 1: BROWSER-VERIFIED DEVICE ID ====================

def _force_localstorage_redirect():
    """Har NAYI session ke pehle hi run mein yeh chalta hai - JS se is
    browser ki apni localStorage padhta hai aur URL ko HAMESHA usi se
    match karwata hai (chahe URL mein pehle se koi device_id ho ya na ho).

    SECURITY FIX: Pehle sirf tab check hota tha jab URL mein device_id
    BILKUL na ho - is se ek gap tha: agar koi kisi approved device ka
    poora URL (jisme uska device_id already tha) copy kar ke apne alag
    browser mein khol leta, purana code us ID ko seedha trust kar leta
    tha. Ab har naye session mein URL ka device_id hamesha is BROWSER ki
    apni localStorage se overwrite hota hai - kisi doosre browser ka ID
    copy karne se koi fayda nahi hota, foran uska apna asal ID le liya
    jata hai."""
    st.markdown("""
        <div style="display:flex; align-items:center; justify-content:center; min-height:60vh;">
            <div style="text-align:center;">
                <h3>Checking Access...</h3>
                <p style="color:#888;">Ek second rukiye...</p>
            </div>
        </div>
    """, unsafe_allow_html=True)
    components.html("""
        <script>
        (function() {
            try {
                let localId = localStorage.getItem('afzal_device_id');
                if (!localId) {
                    localId = 'dev-' + crypto.randomUUID();
                    localStorage.setItem('afzal_device_id', localId);
                }
                const url = new URL(window.parent.location.href);
                url.searchParams.set('device_id', localId);
                window.parent.location.replace(url.toString());
            } catch (e) {
                document.body.innerHTML = '<p style="color:red;">Browser check failed: ' + e + '</p>';
            }
        })();
        </script>
    """, height=0)
    st.stop()


def _get_verified_device_id():
    """Is poore browser-session ke liye SIRF EK BAAR JS-verify hota hai (pehla
    run). Uske baad session_state se hi trust hota hai - URL se dobara nahi
    (taake beech mein URL manually edit kar ke koi doosra device_id na daal
    sake)."""
    if st.session_state.get("_device_verified"):
        return st.session_state.get("_device_id_confirmed")

    incoming = st.query_params.get("device_id", "")
    already_redirected = st.session_state.get("_redirect_attempted", False)

    if not already_redirected:
        st.session_state["_redirect_attempted"] = True
        _force_localstorage_redirect()
        return None  # unreachable - st.stop() upar ho chuka

    st.session_state["_device_verified"] = True
    st.session_state["_device_id_confirmed"] = incoming
    return incoming


# ==================== STEP 2: DRIVE-BACKED ALLOWED DEVICES LIST ====================

@st.cache_data(ttl=_CACHE_TTL, show_spinner=False)
def _cached_allowed_devices():
    """Drive se allowed_devices.json load karta hai. Fail ho (Drive down,
    connect nahi) to None deta hai - jis se poora device-check skip ho jata
    hai (owner kabhi khud lock-out nahi hota)."""
    try:
        import google_drive_backup as gdrive
        if not gdrive.is_available() or not gdrive.is_connected():
            return None

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

        import io, json
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
    try:
        import google_drive_backup as gdrive
        service = gdrive._get_drive_service()
        if service is None:
            return False

        file_id = data.pop("_file_id", None)
        folder_id = data.pop("_folder_id", None)

        import io, json
        from googleapiclient.http import MediaIoBaseUpload
        payload = json.dumps({"devices": data.get("devices", {})}).encode("utf-8")
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


# ==================== SCREENS ====================

def _blocked_screen(title, message, clear_storage=False):
    st.markdown(f"""
        <div style="display:flex; align-items:center; justify-content:center; min-height:70vh;">
            <div style="text-align:center; background:#fff3f3; border:2px solid #dc3545; border-radius:16px; padding:40px 30px; max-width:420px;">
                <h1 style="color:#dc3545; margin:0;">Locked</h1>
                <h2 style="color:#dc3545; margin:10px 0;">{title}</h2>
                <p style="color:#555; font-size:15px;">{message}</p>
            </div>
        </div>
    """, unsafe_allow_html=True)
    if clear_storage:
        components.html("<script>try { localStorage.removeItem('afzal_device_id'); } catch(e) {}</script>", height=0)
    st.stop()


def _request_access_screen(device_id, allowed_data):
    st.markdown("""
        <div style="display:flex; align-items:center; justify-content:center; min-height:50vh;">
            <div style="text-align:center; max-width:420px;">
                <h2>Private Store</h2>
                <p style="color:#555;">Yeh app private hai. Access ke liye owner ki approval chahiye.</p>
            </div>
        </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("Request Access", type="primary", use_container_width=True):
            devices = allowed_data.get("devices", {})
            devices[device_id] = {
                "label": "New Request",
                "requested_date": time.strftime("%Y-%m-%d %H:%M"),
                "status": "pending",
                "is_owner": False,
            }
            allowed_data["devices"] = devices
            if _save_allowed_devices(dict(allowed_data)):
                st.rerun()
    st.stop()


def _pending_screen():
    st.markdown("""
        <div style="display:flex; align-items:center; justify-content:center; min-height:70vh;">
            <div style="text-align:center; background:#fff8e1; border:2px solid #f0a500; border-radius:16px; padding:40px 30px; max-width:420px;">
                <h2 style="color:#7a5b00; margin:10px 0;">Waiting for Owner Approval</h2>
                <p style="color:#555; font-size:15px;">Aapki request bhej di gayi hai. Owner approve karega to yeh page khud khul jayega - dobara try karte rahein.</p>
            </div>
        </div>
    """, unsafe_allow_html=True)
    st.stop()


# ==================== MAIN GATE ====================

def enforce_security_gate():
    """App ke bilkul shuru mein call karo. Returns True agar aage barhna
    safe hai. False/st.stop() agar block/pending/request-screen dikhi ho."""
    device_id = _get_verified_device_id()
    if not device_id:
        return False  # (unreachable in practice - st.stop() already fired)

    allowed_data = _cached_allowed_devices()

    if allowed_data is None:
        st.session_state["_device_lock_active"] = False
        return True

    st.session_state["_device_lock_active"] = True
    st.session_state["_device_id"] = device_id
    st.session_state["_allowed_devices_data"] = allowed_data
    devices = allowed_data.get("devices", {})

    if not devices:
        devices[device_id] = {
            "label": "Owner", "added_date": time.strftime("%Y-%m-%d"),
            "status": "approved", "is_owner": True,
        }
        allowed_data["devices"] = devices
        _save_allowed_devices(dict(allowed_data))
        st.session_state["_allowed_devices_data"] = _cached_allowed_devices() or allowed_data
        return True

    info = devices.get(device_id)

    if info is None:
        _request_access_screen(device_id, allowed_data)
        return False

    status = info.get("status", "pending")
    if status == "blocked":
        _blocked_screen("This Device is Blocked", "Owner ne is device ko block kar diya hai. Ghalti lage to owner se raabta karein.", clear_storage=True)
        return False
    if status == "pending":
        _pending_screen()
        return False
    if status == "approved":
        return True

    _blocked_screen("Access Denied", "Kuch masla hai - owner se raabta karein.")
    return False


def is_owner_device():
    data = st.session_state.get("_allowed_devices_data") or {}
    device_id = st.session_state.get("_device_id", "")
    info = data.get("devices", {}).get(device_id, {})
    return bool(info.get("is_owner")) and info.get("status") == "approved"


def is_admin_request():
    return st.query_params.get("admin", "").lower() == "true"


def show_admin_panel():
    st.title("Admin Panel - Device Requests & Management")

    if not st.session_state.get("_device_lock_active"):
        st.warning("⚠️ Google Drive connect nahi hai - Admin Panel sirf Drive connected hone par kaam karta hai.")
        return

    if not is_owner_device():
        st.error("Not Authorized - sirf Owner ki device is panel ko dekh sakti hai.")
        st.stop()

    allowed_data = st.session_state.get("_allowed_devices_data") or _cached_allowed_devices()
    if allowed_data is None:
        st.error("Devices list load nahi ho saki.")
        return

    devices = allowed_data.get("devices", {})
    current_device = st.session_state.get("_device_id", "")

    pending = {k: v for k, v in devices.items() if v.get("status") == "pending"}
    approved = {k: v for k, v in devices.items() if v.get("status") == "approved"}
    blocked = {k: v for k, v in devices.items() if v.get("status") == "blocked"}

    if pending:
        st.markdown("### Pending Requests")
        for dev_id, info in list(pending.items()):
            col1, col2, col3 = st.columns([3, 1.3, 1.3])
            with col1:
                st.write("**Naya Device Request**")
                st.caption(f"`{dev_id}` | {info.get('requested_date', '?')}")
            with col2:
                if st.button("Approve", key=f"approve_{dev_id}", use_container_width=True, type="primary"):
                    devices[dev_id]["status"] = "approved"
                    devices[dev_id]["label"] = "Approved Device"
                    if _save_allowed_devices(dict(allowed_data)):
                        st.rerun()
            with col3:
                if st.button("Reject", key=f"reject_{dev_id}", use_container_width=True):
                    del devices[dev_id]
                    if _save_allowed_devices(dict(allowed_data)):
                        st.rerun()
        st.divider()

    st.markdown("### Approved Devices")
    if not approved:
        st.caption("Koi approved device nahi.")
    for dev_id, info in list(approved.items()):
        col1, col2, col3 = st.columns([3, 1.3, 1.3])
        with col1:
            owner_tag = " (Owner)" if info.get("is_owner") else ""
            you_tag = " <- (Yeh Device)" if dev_id == current_device else ""
            st.write(f"**{info.get('label', 'Device')}**{owner_tag}{you_tag}")
            st.caption(f"`{dev_id}`")
        with col2:
            st.write("Allowed")
        with col3:
            if not info.get("is_owner"):
                if st.button("Block", key=f"block_{dev_id}", use_container_width=True):
                    devices[dev_id]["status"] = "blocked"
                    if _save_allowed_devices(dict(allowed_data)):
                        st.rerun()
        st.divider()

    if blocked:
        st.markdown("### Blocked Devices")
        for dev_id, info in list(blocked.items()):
            col1, col2, col3 = st.columns([3, 1.3, 1.3])
            with col1:
                st.write(f"**{info.get('label', 'Device')}**")
                st.caption(f"`{dev_id}`")
            with col2:
                st.write("Blocked")
            with col3:
                if st.button("Unblock", key=f"unblock_{dev_id}", use_container_width=True):
                    devices[dev_id]["status"] = "approved"
                    if _save_allowed_devices(dict(allowed_data)):
                        st.rerun()
            st.divider()
