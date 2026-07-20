import streamlit as st
import json
import os
import uuid

OWNER_FILE = "owner.json"
APPROVED_FILE = "approved_devices.json"
PENDING_FILE = "pending_devices.json"


# ---------------------------------------------------------------------
# Low-level JSON helpers
# ---------------------------------------------------------------------
def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _load_owner():
    return _load_json(OWNER_FILE, {})  # {"device_id": "xxxx"}


def _save_owner(device_id):
    _save_json(OWNER_FILE, {"device_id": device_id})


def _load_approved():
    return _load_json(APPROVED_FILE, [])  # list of device_ids


def _save_approved(ids):
    _save_json(APPROVED_FILE, ids)


def _load_pending():
    return _load_json(PENDING_FILE, [])  # list of device_ids


def _save_pending(ids):
    _save_json(PENDING_FILE, ids)


# ---------------------------------------------------------------------
# Main gate — call at top of app.py
# ---------------------------------------------------------------------
def check_device_access():
    """
    Returns True if this device is allowed to use the app.
    Returns False (and has already rendered a waiting/blocked screen)
    if it should not proceed. Caller should st.stop() when False.
    Never loops - at most one st.rerun() the very first time a device
    is seen, to attach ?d_id to the URL.
    """
    d_id = st.query_params.get("d_id")

    owner = _load_owner()

    # No device id in URL yet -> assign one
    if not d_id:
        new_id = uuid.uuid4().hex[:8]

        # First device ever -> becomes owner
        if not owner:
            _save_owner(new_id)
        else:
            pending = _load_pending()
            approved = _load_approved()
            if new_id not in pending and new_id not in approved:
                pending.append(new_id)
                _save_pending(pending)

        st.query_params["d_id"] = new_id
        st.rerun()
        return False  # unreachable, rerun happens above

    # Owner
    if owner.get("device_id") == d_id:
        st.session_state["is_owner"] = True
        return True

    approved = _load_approved()
    pending = _load_pending()

    # Approved device
    if d_id in approved:
        st.session_state["is_owner"] = False
        return True

    # Pending device
    if d_id in pending:
        st.session_state["is_owner"] = False
        st.markdown("## ⏳ Waiting for Owner Approval")
        st.write("Aapki request owner ko bhej di gayi hai. Approval ka intezar karein.")
        st.code(d_id, language=None)
        st.caption("Yeh aapki Device ID hai.")
        if st.button("🔄 Check Again"):
            st.rerun()
        return False

    # Unknown device (e.g. was revoked/blocked, or files were reset)
    if owner:
        pending.append(d_id)
        _save_pending(pending)
        st.markdown("## ⏳ Request Sent to Owner")
        st.write("Aapki request owner ko bhej di gayi hai. Approval ka intezar karein.")
        st.code(d_id, language=None)
        if st.button("🔄 Check Again"):
            st.rerun()
        return False

    # No owner exists yet and somehow d_id is set (edge case) -> become owner
    _save_owner(d_id)
    st.session_state["is_owner"] = True
    return True


def is_owner():
    return st.session_state.get("is_owner", False)


# ---------------------------------------------------------------------
# Admin panel — call when ?admin=true is in the URL
# ---------------------------------------------------------------------
def show_admin_panel():
    d_id = st.query_params.get("d_id")
    owner = _load_owner()

    if not d_id or owner.get("device_id") != d_id:
        st.error("Sirf Owner hi Admin Panel dekh sakta hai.")
        st.stop()

    st.markdown("## 🛠️ Admin Panel — Device Access Control")

    pending = _load_pending()
    approved = _load_approved()

    st.subheader(f"⏳ Pending Requests ({len(pending)})")
    if not pending:
        st.caption("Koi pending request nahi hai.")
    for dev in list(pending):
        col1, col2, col3 = st.columns([3, 1, 1])
        col1.code(dev, language=None)
        if col2.button("✅ Approve", key=f"approve_{dev}"):
            pending.remove(dev)
            _save_pending(pending)
            approved.append(dev)
            _save_approved(approved)
            st.rerun()
        if col3.button("❌ Reject", key=f"reject_{dev}"):
            pending.remove(dev)
            _save_pending(pending)
            st.rerun()

    st.subheader(f"✅ Approved Devices ({len(approved)})")
    if not approved:
        st.caption("Koi approved device nahi hai.")
    for dev in list(approved):
        col1, col2 = st.columns([4, 1])
        col1.code(dev, language=None)
        if col2.button("🚫 Revoke / Block", key=f"revoke_{dev}"):
            approved.remove(dev)
            _save_approved(approved)
            st.rerun()

    st.divider()
    st.caption(
        "Mobile chori hone par: uska Device ID upar 'Approved Devices' list mein "
        "dhoondh kar 'Revoke / Block' dabayein — uska access turant band ho jayega."
    )
