import streamlit as st
import os
from PIL import Image
import json
import base64
import image_compression

LOGO_FILE = 'logo.png'
DRAGON_BG_FILE = 'dragon_bg.png'
SIDEBAR_BG_IMG_FILE = 'sidebar_bg_img.png'
LOGO_SHAPE_FILE = 'logo_shape.txt'
THEME_COLOR_FILE = 'theme_colors.txt'
SIDEBAR_SETTINGS_FILE = 'sidebar_settings.txt'
SIDEBAR_TYPE_FILE = 'sidebar_type.txt'
BANNER_SETTINGS_FILE = 'banner_settings.txt'
GOLDEN_TEXT_FILE = 'golden_text_setting.txt'
SHOW_AMOUNTS_FILE = 'show_amounts.txt' # <-- NAYI LINE ADD KI

# PERF FIX: these used to re-read + re-base64-encode the logo/banner/sidebar images
# (~1.9MB combined) from disk on every single Streamlit rerun, i.e. every click anywhere
# in the app. Caching on (path, mtime) means the expensive read+encode only happens again
# when the file actually changes - uploading a new image changes its mtime and busts the
# cache automatically, no manual invalidation needed.
@st.cache_data(show_spinner=False)
def _read_file_base64(path, mtime):
    with open(path, 'rb') as f:
        return base64.b64encode(f.read()).decode()

def get_base64_logo():
    if os.path.exists(LOGO_FILE):
        return _read_file_base64(LOGO_FILE, os.path.getmtime(LOGO_FILE))
    return None

def get_base64_image(image_path):
    if os.path.exists(image_path):
        return _read_file_base64(image_path, os.path.getmtime(image_path))
    return None

def get_logo_shape():
    if os.path.exists(LOGO_SHAPE_FILE):
        with open(LOGO_SHAPE_FILE, 'r') as f:
            return f.read().strip()
    return "Chokor"

def save_logo_shape(shape):
    with open(LOGO_SHAPE_FILE, 'w') as f:
        f.write(shape)

def get_theme_colors():
    default_colors = {
        'items_card': 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
        'customers_card': 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
        'sidebar_bg': '#111e14',
        'total_customers_card': 'linear-gradient(135deg, #a8edea 0%, #fed6e3 100%)',
        'dashboard_cash_card': 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        'dashboard_udhaar_card': 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
        'item_list_bg_even': '#f8f9fa',
        'item_list_bg_odd': '#e9ecef',
        'item_list_border': '#667eea',
        'customer_card_border_clear': '#43e97b',
        'customer_card_border_udhaar': '#f5576c',
        'text_primary': '#2c3e50',
        'text_secondary': '#7f8c8d',
        'button_primary': '#667eea',
        'success_color': '#43e97b',
        'danger_color': '#f5576c',
        'custom_colors': {}
    }
    if os.path.exists(THEME_COLOR_FILE):
        with open(THEME_COLOR_FILE, 'r') as f:
            try:
                saved = json.load(f)
                return {**default_colors, **saved}
            except:
                return default_colors
    return default_colors

def save_theme_colors(colors):
    with open(THEME_COLOR_FILE, 'w') as f:
        json.dump(colors, f)

def get_banner_settings():
    default_settings = {'fit': 'cover', 'height': 150, 'position': 'center'}
    if os.path.exists(BANNER_SETTINGS_FILE):
        with open(BANNER_SETTINGS_FILE, 'r') as f:
            try:
                saved = json.load(f)
                return {**default_settings, **saved}
            except:
                return default_settings
    return default_settings

def save_banner_settings(settings):
    with open(BANNER_SETTINGS_FILE, 'w') as f:
        json.dump(settings, f)

def show_logo_setting(show_logo_func):
    st.header("⚙ Logo, Sidebar & Graphics Setting")
    st.write("Yahan se aap app ka Logo, Sidebar, Dragon Background aur Theme Colors badal sakte hain.")

    # --- LOGO SHAPE ---
    current_shape = get_logo_shape()
    st.subheader("Logo Ki Shape Chuno")
    logo_shape = st.radio("Shape:", ["Gol", "Chokor"], index=0 if current_shape=="Gol" else 1, horizontal=True, key="shape_radio")
    if logo_shape!= current_shape:
        save_logo_shape(logo_shape)
        st.success(f"Logo shape {logo_shape} save ho gayi!")
        st.rerun()
    st.divider()

    # ==================== NAYA FEATURE: GOLDEN TEXT TOGGLE ====================
    st.subheader("✨ Store Name Style")
    golden_enabled = st.checkbox("Sidebar Mein 'Afzal Store' Ko Golden Karo", value=os.path.exists(GOLDEN_TEXT_FILE))
    if golden_enabled:
        with open(GOLDEN_TEXT_FILE, 'w') as f:
            f.write('enabled')
        st.success("Golden text ON ho gaya! App refresh karo.")
    else:
        if os.path.exists(GOLDEN_TEXT_FILE):
            os.remove(GOLDEN_TEXT_FILE)
        st.info("Normal white text active hai")
    st.divider()
    # ==============================================================================

    # ==================== NAYA FEATURE: DASHBOARD AMOUNTS PRIVACY ====================
    with st.expander("🔒 Dashboard Privacy Setting", expanded=False):
        # SIMPLIFIED: pehle yahan password (1234) daal kar unlock karna parta tha,
        # phir hi toggle nazar aata tha. Ab seedha simple ON/OFF button hai - koi
        # password nahi, koi lock/unlock nahi.
        # HARDENING: explicit unique key diya (auto-generated key kabhi doosri
        # widget se clash na kare), aur try/except ab HAR tarah ki error pakड़ta
        # hai (sirf OSError nahi) taake yeh section kabhi bhi poori app ko na roke.
        try:
            show_amounts = st.toggle(
                "Dashboard Amounts Show Karo",
                value=os.path.exists(SHOW_AMOUNTS_FILE),
                help="ON: Dashboard par Aaj ki Cash Sale, Total Udhaar, Aj ki Bachat dikhegi | OFF: Sab •••••• ho jayega",
                key="dashboard_privacy_toggle"
            )

            if show_amounts:
                if not os.path.exists(SHOW_AMOUNTS_FILE):
                    with open(SHOW_AMOUNTS_FILE, 'w') as f:
                        f.write('enabled')
                st.success("✅ Amounts Dashboard par show ho rahi hain")
            else:
                if os.path.exists(SHOW_AMOUNTS_FILE):
                    os.remove(SHOW_AMOUNTS_FILE)
                st.warning("🔒 Amounts Dashboard par hide hain - Sirf •••••• dikhega")
        except Exception as e:
            st.error(f"⚠️ Privacy setting save nahi ho saki: {e}")

    st.divider()
    # ==============================================================================
    
    # YAHAN SE TUMHARE BAQI LOGO SETTING KE OPTIONS SHURU HONGE
    # Wo sab wapas aa jayenge

    # --- THEME COLORS ---
    st.subheader("🎨 Dashboard & Sidebar Unlimited Colors")
    theme_colors = get_theme_colors()
    gradient_options = {
        "Blue Gradient": "linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)",
        "Green Gradient": "linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)",
        "Purple Gradient": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
        "Orange Gradient": "linear-gradient(135deg, #fa709a 0%, #fee140 100%)",
        "Red Gradient": "linear-gradient(135deg, #f093fb 0%, #f5576c 100%)",
        "Teal Gradient": "linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)"
    }
    tab1, tab2, tab3 = st.tabs(["📊 Dashboard Cards", "📋 List & Sidebar Colors", "🎨 Custom Colors"])
    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            st.write("**Total Items Card Color:**")
            items_color_name = st.selectbox("Items Card:", list(gradient_options.keys()), index=list(gradient_options.values()).index(theme_colors['items_card']) if theme_colors['items_card'] in gradient_options.values() else 0, key="items_color")
            theme_colors['items_card'] = gradient_options[items_color_name]
            st.write("**Cash Sale Card Color:**")
            cash_color_name = st.selectbox("Cash Card:", list(gradient_options.keys()), index=list(gradient_options.values()).index(theme_colors['dashboard_cash_card']) if theme_colors['dashboard_cash_card'] in gradient_options.values() else 2, key="cash_color")
            theme_colors['dashboard_cash_card'] = gradient_options[cash_color_name]
        with col2:
            st.write("**Customer Theme Color:**")
            customers_color_name = st.selectbox("Customers Theme:", list(gradient_options.keys()), index=list(gradient_options.values()).index(theme_colors['customers_card']) if theme_colors['customers_card'] in gradient_options.values() else 1, key="customers_color")
            theme_colors['customers_card'] = gradient_options[customers_color_name]
            st.write("**Udhaar Card Color:**")
            udhaar_color_name = st.selectbox("Udhaar Card:", list(gradient_options.keys()), index=list(gradient_options.values()).index(theme_colors['dashboard_udhaar_card']) if theme_colors['dashboard_udhaar_card'] in gradient_options.values() else 4, key="udhaar_color")
            theme_colors['dashboard_udhaar_card'] = gradient_options[udhaar_color_name]

    with tab2:
        st.markdown("### 📁 Sidebar Background Setup")
        current_sb_type = "Photo (Image)" if os.path.exists(SIDEBAR_TYPE_FILE) else "Solid Color"
        if os.path.exists(SIDEBAR_TYPE_FILE):
            with open(SIDEBAR_TYPE_FILE, 'r') as f:
                current_sb_type = f.read().strip()
        sb_type_selected = st.radio("Sidebar Background Type:", ["Photo (Image)", "Solid Color"], index=0 if current_sb_type == "Photo (Image)" else 1, horizontal=True, key="sb_type_radio")
        with open(SIDEBAR_TYPE_FILE, 'w') as f:
            f.write(sb_type_selected)
        st.divider()

        col1, col2 = st.columns(2)
        with col1:
            theme_colors['item_list_bg_even'] = st.color_picker("Even Row Color", theme_colors['item_list_bg_even'], key="item_even")
            theme_colors['customer_card_border_clear'] = st.color_picker("Clear Border Color", theme_colors['customer_card_border_clear'], key="clear_border")
            st.markdown("### ➡ Sidebar Base Color")
            theme_colors['sidebar_bg'] = st.color_picker("Sidebar Solid Color Chuno (Unlimited)", theme_colors.get('sidebar_bg', '#111e14'), key="sidebar_color_picker")
        with col2:
            theme_colors['item_list_bg_odd'] = st.color_picker("Odd Row Color", theme_colors['item_list_bg_odd'], key="item_odd")
            theme_colors['customer_card_border_udhaar'] = st.color_picker("Udhaar Border Color", theme_colors['customer_card_border_udhaar'], key="udhaar_border")

    with tab3:
        st.info("Yahan koi bhi naya color add karein jo app mein use karna ho.")
        if 'custom_colors' not in theme_colors:
            theme_colors['custom_colors'] = {}
        col1, col2, col3 = st.columns([2,2,1])
        with col1:
            new_color_name = st.text_input("Color Ka Naam", placeholder="e.g., button_green")
        with col2:
            new_color_value = st.color_picker("Color Chuno", "#667eea", key="new_color")
        with col3:
            st.write("")
            if st.button("Add Karo", use_container_width=True):
                if new_color_name:
                    theme_colors['custom_colors'][new_color_name] = new_color_value
                    save_theme_colors(theme_colors)
                    st.success(f"Color '{new_color_name}' add ho gaya!")
                    st.rerun()

        if theme_colors['custom_colors']:
            st.divider()
            for name, color in theme_colors['custom_colors'].items():
                col1, col2, col3 = st.columns([3,1,1])
                with col1:
                    st.code(f"{name}: {color}")
                with col2:
                    st.markdown(f"<div style='background:{color}; width:100%; height:30px; border-radius:5px;'></div>", unsafe_allow_html=True)
                with col3:
                    if st.button("🗑", key=f"del_{name}"):
                        del theme_colors['custom_colors'][name]
                        save_theme_colors(theme_colors)
                        st.rerun()

        st.write("")
        if st.button("Sab Colors Save Karo", type="primary", use_container_width=True):
            save_theme_colors(theme_colors)
            st.success("Colors save ho gaye! Setting apply ho chuki hai.")
            st.rerun()

    st.divider()

    # --- IMAGE UPLOADS MANAGEMENT ---
    st.subheader("🖼 Graphics & Images Upload Management")
    def _save_compressed_upload(uploaded_file, dest_path, success_msg):
        """BUG FIX: pehle yahan Image.open(...).save(...) seedha FULL SIZE
        (200MB tak) file disk par save karta tha - bari photo par yeh app ko
        "hang" jaisa mehsoos karata tha (UI response nahi deti jab tak save
        na ho jaye), aur baad mein har page load par yehi bari file base64
        encode hoti thi (aur bhi dheema). Ab har photo pehle compress hoti
        hai (~500KB tak, max 1024px) - upload turant ho jata hai aur file
        hamesha chhoti rehti hai."""
        with st.spinner("Photo compress ho rahi hai..."):
            compressed_bytes, info_msg = image_compression.compress_image(uploaded_file)
        if compressed_bytes is None:
            st.error(info_msg or "❌ Photo save nahi ho saki.")
            return False
        try:
            with open(dest_path, "wb") as f:
                f.write(compressed_bytes)
        except OSError as e:
            st.error(f"❌ Photo disk par save nahi ho saki: {e}")
            return False
        if info_msg:
            st.caption(info_msg)
        st.success(success_msg)
        return True

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### 🛒 Store Logo")
        uploaded_logo = st.file_uploader("Naya Logo Upload Karein", type=['png','jpg','jpeg'], key="logo_upload_main")
        if uploaded_logo is not None:
            if _save_compressed_upload(uploaded_logo, LOGO_FILE, "Logo badal gaya!"):
                st.rerun()
        if os.path.exists(LOGO_FILE):
            st.markdown(show_logo_func(width=80, height=90), unsafe_allow_html=True)
            if st.button("Logo Delete Karo", type="secondary", key="del_logo_btn"):
                try:
                    os.remove(LOGO_FILE)
                except OSError as e:
                    st.error(f"⚠️ Delete nahi ho saka: {e}")
                st.rerun()

    with col2:
        st.markdown("### 🐉 Dragon Banner")
        uploaded_bg = st.file_uploader("Naya Dragon Banner", type=['png','jpg','jpeg'], key="dragon_upload")
        if uploaded_bg is not None:
            if _save_compressed_upload(uploaded_bg, DRAGON_BG_FILE, "Dragon Banner update ho gaya!"):
                st.rerun()
        if os.path.exists(DRAGON_BG_FILE):
            st.image(DRAGON_BG_FILE, width=120)
            if st.button("Banner Delete", type="secondary", key="del_bg_btn"):
                try:
                    os.remove(DRAGON_BG_FILE)
                except OSError as e:
                    st.error(f"⚠️ Delete nahi ho saka: {e}")
                st.rerun()

    with col3:
        st.markdown("### 📁 Sidebar Photo Management")
        current_sb_type_check = "Photo (Image)"
        if os.path.exists(SIDEBAR_TYPE_FILE):
            with open(SIDEBAR_TYPE_FILE, 'r') as f:
                current_sb_type_check = f.read().strip()
        if current_sb_type_check == "Photo (Image)":
            uploaded_sb_bg = st.file_uploader("Sidebar Ke Piche Ki Photo", type=['png','jpg','jpeg'], key="sidebar_img_upload")
            if uploaded_sb_bg is not None:
                if _save_compressed_upload(uploaded_sb_bg, SIDEBAR_BG_IMG_FILE, "Sidebar ki background photo lag gayi!"):
                    st.rerun()
            if os.path.exists(SIDEBAR_BG_IMG_FILE):
                st.image(SIDEBAR_BG_IMG_FILE, width=120)
                sb_size = st.radio("Photo Size:", ["Cover (Full)", "Contain (Fit)"], horizontal=True, key="sb_size")
                sb_repeat = st.radio("Repeat:", ["No-Repeat", "Repeat (Tile)"], horizontal=True, key="sb_repeat")
                with open(SIDEBAR_SETTINGS_FILE, 'w') as f:
                    f.write(f"{sb_size}|{sb_repeat}")
                if st.button("Photo Delete Karo", type="secondary", key="del_sb_img_btn"):
                    if os.path.exists(SIDEBAR_BG_IMG_FILE):
                        os.remove(SIDEBAR_BG_IMG_FILE)
                    if os.path.exists(SIDEBAR_SETTINGS_FILE):
                        os.remove(SIDEBAR_SETTINGS_FILE)
                    st.success("Sidebar photo hata di gayi!")
                    st.rerun()
        else:
            st.info("Aapne 'Solid Color' select kiya hua hai. Rang badalney k liye upar 'Sidebar Base Color' use karein.")
            if os.path.exists(SIDEBAR_BG_IMG_FILE) or os.path.exists(SIDEBAR_SETTINGS_FILE):
                if st.button("Purani Photo & Settings Clear Karein", type="secondary", key="clear_photo_settings"):
                    if os.path.exists(SIDEBAR_BG_IMG_FILE):
                        os.remove(SIDEBAR_BG_IMG_FILE)
                    if os.path.exists(SIDEBAR_SETTINGS_FILE):
                        os.remove(SIDEBAR_SETTINGS_FILE)
                    st.success("Sidebar image aur settings clear ho gayin!")
                    st.rerun()

    st.divider()
    st.subheader("🐉 Dragon Banner Adjust Karein")
    banner_settings = get_banner_settings()
    col1, col2, col3 = st.columns(3)
    with col1:
        banner_fit = st.selectbox(
            "Image Fit Karo",
            ["cover", "contain", "stretch"],
            index=["cover", "contain", "stretch"].index(banner_settings['fit']),
            help="Cover: Frame fill karega, cut ho sakti hai | Contain: Poori dikhegi | Stretch: Zabardasti fit karega"
        )
    with col2:
        banner_height = st.slider("Banner Height", 120, 250, banner_settings['height'], 10, help="Frame kitna bara chahiye")
    with col3:
        banner_position = st.selectbox(
            "Image Position",
            ["center", "top", "bottom"],
            index=["center", "top", "bottom"].index(banner_settings['position'])
        )
    new_settings = {
        'fit': banner_fit,
        'height': banner_height,
        'position': banner_position
    }
    if new_settings!= banner_settings:
        save_banner_settings(new_settings)
        st.success("Banner settings save ho gayin!")
        st.rerun()