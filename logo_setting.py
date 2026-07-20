import streamlit as st
from PIL import Image
import io
import os

LOGO_DIR = "Logo_F"
LOGO_PATH = os.path.join(LOGO_DIR, "logo.png")
MAX_DIMENSION = 300
JPEG_QUALITY = 80


@st.cache_data(show_spinner=False)
def _compress_image_bytes(file_bytes):
    """Cached so re-running the app doesn't recompress the same upload."""
    image = Image.open(io.BytesIO(file_bytes))
    image = image.convert("RGB")
    image.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


def render():
    st.markdown("## 🖼️ Logo Setting")
    os.makedirs(LOGO_DIR, exist_ok=True)

    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, caption="Current Logo", width=150)
    else:
        st.caption("Abhi tak koi logo upload nahi hua.")

    uploaded_file = st.file_uploader(
        "Naya Logo Upload Karein", type=["png", "jpg", "jpeg"], key="logo_uploader"
    )

    if uploaded_file is not None:
        with st.spinner("Logo compress ho raha hai..."):
            try:
                file_bytes = uploaded_file.getvalue()
                compressed_bytes = _compress_image_bytes(file_bytes)
                with open(LOGO_PATH, "wb") as f:
                    f.write(compressed_bytes)
                st.success("Logo update ho gaya!")
                st.image(compressed_bytes, caption="Naya Logo", width=150)
            except Exception as e:
                st.error(f"Logo process nahi ho saka: {e}")
