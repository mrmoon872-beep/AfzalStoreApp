"""
PWA Setup Module - AfzalStore
==============================
Yeh module app ko "installable" banata hai taake mobile ke home screen par
AfzalStore ka icon aa sake (Add to Home Screen).

ZAROORI:
1. .streamlit/config.toml mein yeh line honi chahiye (agar nahi hai to yeh
   module khud add kar deta hai):
       [server]
       enableStaticServing = true
2. Icon aapke maujooda logo.png se khud generate hota hai. Agar logo.png
   nahi milti to ek plain default icon ban jata hai.
3. PWA sirf HTTPS (ya localhost) par kaam karti hai - is liye HTTPS setup
   (mkcert) bhi zaroori hai, jiski instructions "HTTPS_SETUP_INSTRUCTIONS.txt"
   mein hain.
"""

import os
import json
import streamlit as st

STATIC_DIR = "static"
LOGO_FILE = "logo.png"
CONFIG_TOML_PATH = os.path.join(".streamlit", "config.toml")


def _ensure_static_serving_enabled():
    """config.toml mein enableStaticServing=true aur maxUploadSize=15 (MB) set karta
    hai agar pehle se nahi hai. maxUploadSize is liye chhota rakha hai taake koi
    galti se 200MB ki photo select na kar le - compression to hoti hi hai, lekin
    yeh ek extra safety net hai taake upload khud bhi jaldi ho."""
    try:
        os.makedirs(".streamlit", exist_ok=True)
        existing = ""
        if os.path.exists(CONFIG_TOML_PATH):
            with open(CONFIG_TOML_PATH, "r") as f:
                existing = f.read()

        updated = existing
        if "[server]" not in updated:
            updated += "\n[server]\n"
        if "enableStaticServing" not in updated:
            updated = updated.replace("[server]", "[server]\nenableStaticServing = true", 1)
        if "maxUploadSize" not in updated:
            updated = updated.replace("[server]", "[server]\nmaxUploadSize = 15", 1)

        if updated != existing:
            with open(CONFIG_TOML_PATH, "w") as f:
                f.write(updated)
    except OSError:
        pass  # config likhne mein masla - PWA icon kaam nahi karega, lekin app crash nahi hogi


def _generate_icons():
    """logo.png se 192x192 aur 512x512 PWA icons banata hai. Agar logo.png
    nahi hai to ek simple placeholder icon banata hai (app kabhi crash nahi
    hogi is wajah se)."""
    os.makedirs(STATIC_DIR, exist_ok=True)
    icon_192 = os.path.join(STATIC_DIR, "icon-192.png")
    icon_512 = os.path.join(STATIC_DIR, "icon-512.png")

    # Agar icons pehle se ban chuke hain aur logo.png us se purani nahi hui, to dobara mat banao
    if os.path.exists(icon_192) and os.path.exists(icon_512):
        if not os.path.exists(LOGO_FILE) or os.path.getmtime(icon_192) >= os.path.getmtime(LOGO_FILE):
            return

    try:
        from PIL import Image, ImageDraw

        if os.path.exists(LOGO_FILE):
            base_img = Image.open(LOGO_FILE).convert("RGBA")
        else:
            # Placeholder icon agar logo.png abhi tak nahi bani - "AS" letters wala circle
            base_img = Image.new("RGBA", (512, 512), (46, 125, 50, 255))
            draw = ImageDraw.Draw(base_img)
            draw.ellipse((30, 30, 482, 482), fill=(255, 255, 255, 255))
            draw.text((150, 200), "AS", fill=(46, 125, 50, 255))

        for size, path in [(192, icon_192), (512, icon_512)]:
            square = Image.new("RGBA", (size, size), (255, 255, 255, 255))
            resized = base_img.copy()
            resized.thumbnail((size, size))
            offset = ((size - resized.width) // 2, (size - resized.height) // 2)
            square.paste(resized, offset, resized if resized.mode == "RGBA" else None)
            square.save(path, "PNG")
    except Exception:
        pass  # icon generate nahi ho saka - PWA install prompt shayad na aaye, lekin app chalti rahegi


def _generate_manifest():
    manifest = {
        "name": "Afzal Kiryana Store",
        "short_name": "AfzalStore",
        "start_url": ".",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#2e7d32",
        "orientation": "portrait",
        "icons": [
            {"src": "app/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "app/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    try:
        os.makedirs(STATIC_DIR, exist_ok=True)
        with open(os.path.join(STATIC_DIR, "manifest.json"), "w") as f:
            json.dump(manifest, f)
    except OSError:
        pass


def _generate_service_worker():
    """Minimal service worker - "Add to Home Screen" install prompt ke liye
    zaroori hai (Chrome/Android requirement). Yeh koi bhari offline caching
    nahi karta - bas app ko "installable" banata hai."""
    sw_code = """
self.addEventListener('install', (event) => { self.skipWaiting(); });
self.addEventListener('activate', (event) => { event.waitUntil(clients.claim()); });
self.addEventListener('fetch', (event) => {
    event.respondWith(fetch(event.request).catch(() => new Response('Offline - PC se dobara connect karein.')));
});
"""
    try:
        os.makedirs(STATIC_DIR, exist_ok=True)
        with open(os.path.join(STATIC_DIR, "service-worker.js"), "w") as f:
            f.write(sw_code)
    except OSError:
        pass


def setup_pwa():
    """App shuru hote hi ek dafa call karo (app.py mein) - manifest, icons,
    aur service worker generate/refresh karta hai. Har cheez try/except mein
    hai, is function ki wajah se app kabhi crash nahi hogi."""
    _ensure_static_serving_enabled()
    _generate_icons()
    _generate_manifest()
    _generate_service_worker()


def inject_pwa_tags():
    """Page mein manifest link, theme-color meta, aur service-worker registration
    JS inject karta hai. app.py mein har rerun par call karna safe hai (halka sa
    HTML/JS hai, koi bhaari kaam nahi)."""
    st.markdown("""
        <link rel="manifest" href="./app/static/manifest.json">
        <meta name="theme-color" content="#2e7d32">
        <link rel="apple-touch-icon" href="./app/static/icon-192.png">
        <script>
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('./app/static/service-worker.js')
                .catch(function(err) { console.log('SW registration skipped:', err); });
        }
        </script>
    """, unsafe_allow_html=True)
