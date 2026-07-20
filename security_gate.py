"""
Security Gate - AfzalStore
============================
Owner-approval device lock. Ek device ek baar approve ho jaye to hamesha
ke liye yaad rehta hai - refresh, app band-khol, PWA "home screen" icon,
Streamlit Cloud reboot, sab ke baad bhi.

DO YEH CHEEZEIN JO PEHLE HANG KI WAJAH BANI THEEN, INHEIN YAHAN NAHI HAI:
1. Koi "components.html se JS value wapas Python mein padhna" wala
   two-way round-trip nahi hai (yehi cheez pehle "Checking Access..."
   par hamesha ke liye atka deti thi). JS sirf ek-tarfa kaam karta hai:
   browser ko navigate karna. Python kabhi kisi JS jawab ka intezar
   nahi karta - har run apne aap poora (complete) hota hai.
2. Koi time.sleep() ya while-loop nahi hai.

DEVICE ID DO JagahOn PAR YAAD RAKHA JATA HAI (dono chalu):
  a) URL query param (?d_id=...) - yehi Python ka source of truth hai.
  b) Browser localStorage - taake PWA "Add to Home Screen" icon dobara
     khulne par (jo URL ko ?d_id ke bagair reset kar deta hai) bhi wahi
     purana device_id khud URL mein wapas aa jaye.

APPROVED/PENDING/OWNER LIST PERSISTENCE:
  Local file (device_access.json) hamesha kaam karta hai, lekin
  Streamlit Cloud reboot/redeploy par local files wipe ho jati hain.
  Is liye - agar Google Drive connect hai (jo app mein already available
  hai, backup ke liye) - to yeh file automatically Drive par bhi save
  hoti hai aur reboot ke baad wahan se wapas load ho jati hai. Agar
  Drive connect nahi hai to sab kuch local par hi chalta rahega (bas
  reboot ke baad list reset ho jayegi).
"""

import streamlit as st
import streamlit.components.v1 as components
import json
import os
import uuid

DEVICES_FILE = "device_access.json"
DRIVE_FILENAME = "device_access.json"
_DEFAULT = {"owner": None, "approved": [], "pending": []}


# ---------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------
def _load_local():
    if not os.path.exists(DEVICES_FILE):
        return dict(_DEFAULT)
    try:
        with open(DEVICES_FILE, "r") as f:
            data = json.load(f)
        data.setdefault("owner", None)
        data.setdefault("approved", [])
        data.setdefault("pending", [])
        return data
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT)


def _save_local(data):
    with open(DEVICES_FILE, "w") as f:
        json.dump(data, f, indent=2)


@st.cache_resource(ttl=30, show_spinner=False)
def _pull_from_drive_throttled(_cache_bust):
    """Har 30 second mein zyada se zyada EK baar Drive check karta hai
    (st.cache_resource is se guarantee karta hai) - kitni bhi baar call ho,
    (near-)FREE hai. Kabhi bhi UI ko dheema nahi karta, kabhi crash nahi
    karta - Drive na ho to chup-chaap kuch nahi karta."""
    try:
        import google_drive_backup as gdrive
        if not gdrive.is_available() or not gdrive.is_connected():
            return
        gdrive.download_json_file_if_newer(DEVICES_FILE, DRIVE_FILENAME)
    except Exception:
        pass


def _push_to_drive_best_effort():
    """Chhoti JSON file hai (chandh KB) is liye seedha, synchronously upload
    karna bhi tez hai - lekin phir bhi kabhi bhi app ko crash ya slow
    nahi karega, sirf try karta hai."""
    try:
        import google_drive_backup as gdrive
        if gdrive.is_available() and gdrive.is_connected():
            gdrive.upload_json_file_to_drive(DEVICES_FILE, DRIVE_FILENAME)
    except Exception:
        pass


def _load():
    _pull_from_drive_throttled(0)
    return _load_local()


def _save(data):
    _save_local(data)
    _push_to_drive_best_effort()


# ---------------------------------------------------------------------
# Browser-side device id memory (localStorage) - ONE-WAY only, never
# blocks Python. See module docstring.
# ---------------------------------------------------------------------
def _try_restore_id_from_browser():
    """Agar is browser mein pehle se koi device_id save hai (localStorage),
    to isay URL mein daal kar page navigate kar deta hai. Agar kuch save
    nahi hai, ya JS block hai, kuch nahi hota - Python neeche apna normal
    kaam (naya pending device banana) turant jaari rakhta hai, kabhi
    ruk kar wait nahi karta."""
    components.html(
        """
        <script>
        try {
            var saved = window.localStorage.getItem('afzal_device_id');
            if (saved) {
                var url = new URL(window.top.location.href);
                if (url.searchParams.get('d_id') !== saved) {
                    url.searchParams.set('d_id', saved);
                    window.top.location.replace(url.toString());
                }
            }
        } catch (e) {}
        </script>
        """,
        height=0,
    )


def _remember_id_in_browser(device_id):
    """Naye/kisi bhi device_id ko browser ki localStorage mein save kar
    deta hai taake agli baar (refresh, PWA relaunch, app band-khol) yehi
    id khud-ba-khud wapas mil jaye. Fire-and-forget - Python is se kabhi
    kuch wapas nahi manga."""
    components.html(
        f"""
        <script>
        try {{ window.localStorage.setItem('afzal_device_id', '{device_id}'); }}
        catch (e) {{}}
        </script>
        """,
        height=0,
    )


# ---------------------------------------------------------------------
# Main gate — call at top of app.py
# ---------------------------------------------------------------------
def check_device_access():
    """
    Returns True agar yeh device app use kar sakta hai.
    False return karta hai (aur pehle hi ek waiting/blocked screen dikha
    chuka hota hai) agar allow nahi hai - caller ko turant st.stop()
    karna chahiye.
    """
    d_id = st.query_params.get("d_id")
    data = _load()

    # URL mein abhi tak koi d_id nahi - pehle browser se purani id restore
    # karne ki koshish karo (one-way, non-blocking - dekho docstring).
    if not d_id:
        _try_restore_id_from_browser()

        new_id = uuid.uuid4().hex[:8]

        if not data["owner"]:
            # Sabse pehla device jo kabhi is app par aaya - Owner ban jayega.
            data["owner"] = new_id
            _save(data)
            _remember_id_in_browser(new_id)
            st.query_params["d_id"] = new_id
            st.rerun()

        if new_id not in data["pending"] and new_id not in data["approved"]:
            data["pending"].append(new_id)
            _save(data)

        _remember_id_in_browser(new_id)
        st.query_params["d_id"] = new_id
        st.rerun()
        return False  # unreachable - rerun ho chuka hai

    # --- Ab d_id URL mein maujood hai ---
    if data["owner"] == d_id:
        st.session_state["is_owner"] = True
        return True

    if d_id in data["approved"]:
        st.session_state["is_owner"] = False
        return True

    if d_id in data["pending"]:
        st.session_state["is_owner"] = False
        st.markdown("## ⏳ Waiting for Owner Approval")
        st.write("Aapki request owner ko bhej di gayi hai. Approval ka intezar karein.")
        st.code(d_id, language=None)
        st.caption("Yeh aapki Device ID hai.")
        if st.button("🔄 Check Again"):
            st.rerun()
        return False

    # d_id set hai lekin kisi list mein nahi (revoke ho chuka tha, ya files
    # kabhi reset hui thi) - naye sire se pending mein daal do.
    if data["owner"]:
        data["pending"].append(d_id)
        _save(data)
        st.markdown("## ⏳ Request Sent to Owner")
        st.write("Aapki request owner ko bhej di gayi hai. Approval ka intezar karein.")
        st.code(d_id, language=None)
        if st.button("🔄 Check Again"):
            st.rerun()
        return False

    # Koi owner hi nahi hai aur d_id already set hai (rare edge case) -
    # is device ko owner bana do.
    data["owner"] = d_id
    _save(data)
    st.session_state["is_owner"] = True
    return True


def is_owner():
    return st.session_state.get("is_owner", False)


# ---------------------------------------------------------------------
# Admin panel — call when ?admin=true is in the URL
# ---------------------------------------------------------------------
def show_admin_panel():
    d_id = st.query_params.get("d_id")
    data = _load()

    if not data["owner"]:
        st.info("Pehle app ko normal tarike se kholein taake Owner set ho jaye, phir yahan aayein.")
        st.stop()

    if d_id != data["owner"]:
        st.error("Sirf Owner hi Admin Panel dekh sakta hai.")
        st.stop()

    st.markdown("## 🛠️ Admin Panel — Device Access Control")

    pending = data["pending"]
    approved = data["approved"]

    st.subheader(f"⏳ Pending Requests ({len(pending)})")
    if not pending:
        st.caption("Koi pending request nahi hai.")
    for dev in list(pending):
        col1, col2, col3 = st.columns([3, 1, 1])
        col1.code(dev, language=None)
        if col2.button("✅ Approve", key=f"approve_{dev}"):
            data["pending"].remove(dev)
            if dev not in data["approved"]:
                data["approved"].append(dev)
            _save(data)
            st.rerun()
        if col3.button("❌ Reject", key=f"reject_{dev}"):
            data["pending"].remove(dev)
            _save(data)
            st.rerun()

    st.subheader(f"✅ Approved Devices ({len(approved)})")
    if not approved:
        st.caption("Koi approved device nahi hai.")
    for dev in list(approved):
        col1, col2 = st.columns([4, 1])
        col1.code(dev, language=None)
        if col2.button("🚫 Block", key=f"revoke_{dev}"):
            data["approved"].remove(dev)
            _save(data)
            st.rerun()

    st.divider()
    try:
        import google_drive_backup as gdrive
        if gdrive.is_available() and gdrive.is_connected():
            st.caption("☁️ Yeh list Google Drive par bhi save ho rahi hai - Streamlit Cloud reboot ke baad bhi safe rahegi.")
        else:
            st.warning(
                "⚠️ Google Drive connect nahi hai - yeh list Streamlit Cloud reboot/redeploy "
                "par reset ho sakti hai. 'Backup Setting' page se Google Drive connect karein "
                "taake yeh hamesha ke liye mehfooz rahe."
            )
    except Exception:
        pass

    st.caption("Mobile chori hone par: Approved Devices list mein uska Device ID dhoond kar '🚫 Block' dabayein.")
