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

# 10,000-PHOTO SCALE: 'main' photo list/detail view ke liye, 'thumb' list rows
# mein dikhane ke liye. 10,000 photos x (35KB + 8KB) = ~430MB - purane tareeqe
# (500KB x 10,000 = 5GB) se karib 10x kam. Drive upload isi wajah se invisible
# rehta hai (chhoti files, background thread mein bina kisi ko pata chale).
MAIN_MAX_DIMENSION = 500
MAIN_TARGET_KB = 35
THUMB_MAX_DIMENSION = 120
THUMB_TARGET_KB = 8
DUAL_MIN_QUALITY = 40


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


def _shrink_to(img, max_dimension, target_kb, min_quality):
    """Ek hi PIL image ko diye gaye max-dimension + target size tak resize/
    compress karta hai. JPEG istemal karta hai (WEBP se zyada portable/
    compatible hai - kai purane Pillow builds mein WEBP save support nahi
    hota, is liye yahan hamesha JPEG use kiya jata hai taake kabhi crash na
    ho). Transparency (PNG logos) preserve rehti hai."""
    has_transparency = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    work_img = img.copy()
    if not has_transparency and work_img.mode != "RGB":
        work_img = work_img.convert("RGB")

    work_img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

    output_format = "PNG" if has_transparency else "JPEG"
    quality = 80
    buffer = io.BytesIO()
    while True:
        buffer = io.BytesIO()
        if output_format == "JPEG":
            work_img.save(buffer, format="JPEG", quality=quality, optimize=True)
        else:
            work_img.save(buffer, format="PNG", optimize=True)
        size_kb = buffer.tell() / 1024
        if size_kb <= target_kb or quality <= min_quality or output_format == "PNG":
            break
        quality -= 15
    return buffer.getvalue()


def compress_image_dual(file_obj):
    """10,000-PHOTO SCALE FIX: har upload se DO chhoti copies banata hai -
    ek 'main' (list mein click kar ke dekhne/detail view ke liye, ~500x500,
    ~35KB) aur ek 'thumb' (list/table rows mein seedha dikhane ke liye,
    ~120x120, ~8KB). List views ab bari 'main' photo load nahi karte - sirf
    halki thumbnail, is liye 100 items ek page par bhi turant load hote hain.

    Returns: (main_bytes, thumb_bytes, info_message). Kabhi crash nahi karta
    - Pillow na ho ya photo corrupt ho to (raw_bytes, raw_bytes, warning)
    wapas kar deta hai taake purane single-size flow ki tarah hi kaam chalta
    rahe."""
    if file_obj is None:
        return None, None, None

    try:
        raw_bytes = file_obj.getvalue()
    except AttributeError:
        try:
            raw_bytes = file_obj.read()
        except Exception:
            return None, None, "⚠️ Photo read nahi ho saki."

    if not raw_bytes:
        return None, None, "⚠️ Photo khali hai."

    if not PIL_AVAILABLE:
        return raw_bytes, raw_bytes, "⚠️ Image compression library (Pillow) nahi mili - photo bina compress kiye save ho rahi hai."

    original_kb = len(raw_bytes) / 1024

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img = ImageOps.exif_transpose(img)  # mobile photos rotate ho jati hain, seedhi karo

        main_bytes = _shrink_to(img, MAIN_MAX_DIMENSION, MAIN_TARGET_KB, DUAL_MIN_QUALITY)
        thumb_bytes = _shrink_to(img, THUMB_MAX_DIMENSION, THUMB_TARGET_KB, DUAL_MIN_QUALITY)

        final_kb = len(main_bytes) / 1024
        if final_kb < original_kb:
            msg = f"✅ Photo compress ho gayi: {original_kb:.0f} KB → {final_kb:.0f} KB (+ thumbnail)"
        else:
            msg = None

        return main_bytes, thumb_bytes, msg
    except Exception as e:
        return raw_bytes, raw_bytes, f"⚠️ Photo compress nahi ho saki ({e}) - original size mein save ho rahi hai."


def recompress_oversized_photos_background(folder="item_photos", size_threshold_kb=100):
    """STARTUP FIX: purani photos jo naye (chhote) format se pehle save hui
    thin, wo bari reh sakti hain (kai sau KB - ab se pehle ka TARGET_SIZE_KB
    500KB tha). Yeh function un sab ko DHOOND kar, EK DAFA, background daemon
    thread mein chup-chaap chhota kar deta hai - kabhi UI ko block nahi
    karta, kabhi crash nahi karta (har file alag try/except mein hai, ek
    kharab file baaki sab ko nahi rokti)."""
    import os as _os
    import threading as _threading

    def _worker():
        try:
            if not _os.path.isdir(folder):
                return
            for fname in _os.listdir(folder):
                fpath = _os.path.join(folder, fname)
                try:
                    if not _os.path.isfile(fpath):
                        continue
                    if _os.path.getsize(fpath) / 1024 <= size_threshold_kb:
                        continue
                    with open(fpath, "rb") as f:
                        raw = f.read()
                    if not PIL_AVAILABLE:
                        return  # Pillow hi nahi hai, kuch nahi ho sakta
                    img = Image.open(io.BytesIO(raw))
                    img = ImageOps.exif_transpose(img)
                    shrunk = _shrink_to(img, MAIN_MAX_DIMENSION, MAIN_TARGET_KB, DUAL_MIN_QUALITY)
                    if len(shrunk) < len(raw):
                        with open(fpath, "wb") as f:
                            f.write(shrunk)
                except Exception:
                    continue  # is ek photo mein masla, baaki chalti rahengi
        except Exception:
            pass

    try:
        t = _threading.Thread(target=_worker, daemon=True)
        t.start()
    except Exception:
        pass
