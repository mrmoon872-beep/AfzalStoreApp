"""
Image Compression Module - AfzalStore
========================================
Har jagah jahan photo upload hoti hai (Logo Setting, Items Add, Udhaar Khatta
customer photos waghera), yeh module use karke photo ko save karne se PEHLE
chhota kar dete hain. Isi wajah se:

1. Upload karte waqt app hang nahi hoti (bara, uncompressed file disk par
   seedha save nahi hoti)
2. Baad mein jab yeh photo dikhani ho (base64 encode karke ya display), woh
   bhi tez rehti hai kyunke file already chhoti hai
3. 5000+ photos ho jayen tab bhi total disk/memory use manageable rehta hai
   (500 KB x 5000 = ~2.5 GB max, bajaye 200 MB x 5000 = 1 TB ke)
"""

import io

try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


MAX_DIMENSION = 1024      # is se zyada lambi/chaudi photo resize ho jayegi
TARGET_SIZE_KB = 500      # is se choti banane ki koshish hogi
MIN_QUALITY = 30          # is se kam quality nahi jayegi (bilkul kharab na ho)


def compress_image(file_obj, max_dimension=MAX_DIMENSION, target_kb=TARGET_SIZE_KB):
    """Kisi bhi uploaded file (st.file_uploader ya st.camera_input se) ko
    resize + compress kar ke chhoti JPEG bytes mein wapas deta hai.

    Returns: (compressed_bytes, info_message) - agar kuch ghalat ho (corrupt
    photo, PIL na ho), to original bytes hi wapas kar deta hai (kabhi crash
    nahi karta, kabhi khali/None nahi deta jab tak input hi na ho).
    """
    if file_obj is None:
        return None, None

    try:
        raw_bytes = file_obj.getvalue()
    except AttributeError:
        try:
            raw_bytes = file_obj.read()
        except Exception:
            return None, "⚠️ Photo read nahi ho saki."

    if not raw_bytes:
        return None, "⚠️ Photo khali hai."

    if not PIL_AVAILABLE:
        return raw_bytes, "⚠️ Image compression library (Pillow) nahi mili - photo bina compress kiye save ho rahi hai."

    original_kb = len(raw_bytes) / 1024

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img = ImageOps.exif_transpose(img)  # mobile photos rotate ho jati hain, seedhi karo

        # Transparency (PNG logos) preserve karna zaroori hai, warna background kaala ho jata hai
        has_transparency = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        if not has_transparency and img.mode != "RGB":
            img = img.convert("RGB")

        # Bari photo ko chhota karo (aspect ratio maintain hoti hai)
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

        output_format = "PNG" if has_transparency else "JPEG"
        quality = 85

        while True:
            buffer = io.BytesIO()
            if output_format == "JPEG":
                img.save(buffer, format="JPEG", quality=quality, optimize=True)
            else:
                img.save(buffer, format="PNG", optimize=True)

            size_kb = buffer.tell() / 1024
            if size_kb <= target_kb or quality <= MIN_QUALITY or output_format == "PNG":
                break
            quality -= 15  # thoda aur compress karo agar abhi bhi bari hai

        compressed_bytes = buffer.getvalue()
        final_kb = len(compressed_bytes) / 1024

        if final_kb < original_kb:
            msg = f"✅ Photo compress ho gayi: {original_kb:.0f} KB → {final_kb:.0f} KB"
        else:
            msg = None  # pehle se hi chhoti thi, kuch batane ki zaroorat nahi

        return compressed_bytes, msg
    except Exception as e:
        # Kharab/corrupt photo ho sakti hai - original hi save kar do, crash mat karo
        return raw_bytes, f"⚠️ Photo compress nahi ho saki ({e}) - original size mein save ho rahi hai."
