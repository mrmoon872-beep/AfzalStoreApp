"""
Camera OCR Module - AfzalStore (FREE Tesseract OCR)
=====================================================
Yeh module free/offline Tesseract OCR engine use karta hai bill aur udhaar-book
photos se text nikalne ke liye.

⚠️ ZAROORI SETUP (Windows):
1. Tesseract OCR install karein (free): https://github.com/UB-Mannheim/tesseract/wiki
   (Installer chalayein, default location: C:\\Program Files\\Tesseract-OCR\\tesseract.exe)
2. Terminal mein: pip install pytesseract pillow opencv-python-headless

⚠️ HONEST BAAT: Free OCR (Tesseract) kharab handwriting aur Sindhi script par
BOHOT ghalat result de sakta hai - yeh printed/clear English/Urdu text par sab
se achha kaam karta hai. Isi liye HAR result "Preview & Confirm" screen par
dikhaya jata hai - kabhi bhi seedha save nahi hota. Aap har field check/edit
kar sakte hain save karne se pehle.
"""

import os
import re
import io

TESSERACT_PATHS_TO_TRY = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
]

try:
    import pytesseract
    from PIL import Image, ImageOps, ImageFilter

    for _path in TESSERACT_PATHS_TO_TRY:
        if os.path.exists(_path):
            pytesseract.pytesseract.tesseract_cmd = _path
            break

    OCR_LIBS_AVAILABLE = True
except ImportError:
    OCR_LIBS_AVAILABLE = False


def is_ocr_available():
    """Check karta hai ke OCR use karne ke liye sab kuch (library + Tesseract
    engine) maujood hai ya nahi. Agar nahi hai, calling code ko blank/manual-entry
    form dikhana chahiye, crash nahi hona chahiye."""
    if not OCR_LIBS_AVAILABLE:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _preprocess_image(image_bytes):
    """Photo ko OCR ke liye behtar banata hai (grayscale + contrast) - handwriting
    ke liye accuracy thori si behtar ho sakti hai, guarantee nahi."""
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)  # mobile photos rotate ho jati hain, seedhi karo
    img = img.convert("L")  # grayscale
    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def extract_raw_text(image_bytes):
    """Photo se poora raw text nikalta hai. Kabhi crash nahi karta - fail hone
    par khali string + error message deta hai."""
    if not is_ocr_available():
        return "", "⚠️ OCR available nahi hai - Tesseract install nahi hai ya path ghalat hai."
    try:
        img = _preprocess_image(image_bytes)
        text = pytesseract.image_to_string(img, lang="eng")
        return text, None
    except Exception as e:
        return "", f"⚠️ OCR text nikalte waqt masla aaya: {e}"


_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _extract_numbers(line):
    return [float(n.replace(",", "")) for n in _NUMBER_RE.findall(line)]


def guess_bill_rows(raw_text):
    """Bill ki photo ke raw OCR text se DRAFT rows guess karta hai (Item, Qty,
    Rate, Total). Yeh sirf ek ANDAZA hai - Preview & Confirm screen par user
    har row edit/delete/add kar sakta hai. Kabhi bhi is guess ko final maan
    kar seedha save nahi karna chahiye."""
    rows = []
    if not raw_text:
        return rows

    for line in raw_text.split("\n"):
        clean = line.strip()
        if not clean or len(clean) < 2:
            continue

        numbers = _extract_numbers(clean)
        if not numbers:
            continue  # koi number nahi mila is line mein - shayad heading/junk hai

        # Item name = line ka woh hissa jahan pehla number shuru hota hai, usse pehle
        first_num_match = _NUMBER_RE.search(clean)
        item_guess = clean[:first_num_match.start()].strip(" -:|.,") if first_num_match else clean
        if not item_guess:
            item_guess = "Item (naam check karein)"

        qty_guess = numbers[0] if len(numbers) >= 1 else 1.0
        rate_guess = numbers[1] if len(numbers) >= 2 else 0.0
        total_guess = numbers[-1] if len(numbers) >= 1 else 0.0

        # Agar sirf ek number mila to woh total hai, qty/rate ka andaza nahi lagate
        if len(numbers) == 1:
            qty_guess = 1.0
            rate_guess = numbers[0]
            total_guess = numbers[0]

        rows.append({
            "item": item_guess[:60],
            "qty": qty_guess,
            "rate": rate_guess,
            "total": total_guess,
        })

    return rows


_DATE_RE = re.compile(r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}")


def guess_udhaar_entries(raw_text):
    """Udhaar-book (customer ki purani kitab) ki photo se DRAFT entries guess
    karta hai (Date, Naam, Item, Raqam). Yeh bhi sirf andaza hai - Preview &
    Confirm screen mein poori tarah edit hoga."""
    rows = []
    if not raw_text:
        return rows

    for line in raw_text.split("\n"):
        clean = line.strip()
        if not clean or len(clean) < 3:
            continue

        numbers = _extract_numbers(clean)
        date_match = _DATE_RE.search(clean)
        date_guess = date_match.group(0) if date_match else ""

        remaining = clean
        if date_match:
            remaining = (clean[:date_match.start()] + " " + clean[date_match.end():]).strip()

        amount_guess = numbers[-1] if numbers else 0.0
        name_item_guess = remaining.strip(" -:|.,")

        if not numbers and not date_match:
            continue  # yeh line shayad heading/junk hai, koi useful data nahi mila

        rows.append({
            "date": date_guess,
            "customer": name_item_guess[:40] if name_item_guess else "Naam Likhein",
            "item": "",
            "amount": amount_guess,
        })

    return rows
