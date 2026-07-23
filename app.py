import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
import os
import base64

# Purani files import
from items_add import show_items_add
from udhaar_khatta import show_udhaar_khatta
from daily_sale import show_daily_sale # <-- Sirf ye 1 line ab
from agencies import show_agencies
from defaulter import show_defaulter
from reports import show_reports
from logo_setting import show_logo_setting, get_logo_shape, get_theme_colors, save_theme_colors, get_base64_logo, get_base64_image, DRAGON_BG_FILE
from nayi_sale import show_nayi_sale
from backup_setting import show_backup_restore
from chaki_management import show_chakki_management
from expenses import show_expenses
from roz_ka_roll_nama import show_roll_nama
from backup_restore import auto_daily_backup
import pwa_setup
import security_gate
import sync_manager

# Database Setup
# PATH FIX: pehle 'afzal_store.db' hamesha current working directory ke
# hisaab se dhoondhi jati thi - agar app _internal/ ke bahar se chalayi
# jaye (ya iske bar-aks) to file 'nahi milti'. Ab dono mumkin jagah check
# hoti hain - jahan asal file maujood ho wahi istemal hoti hai.
def _resolve_db_file():
    candidates = [
        'afzal_store.db',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'afzal_store.db'),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]  # koi bhi na mile to yahin nayi database ban jayegi


DB_FILE = _resolve_db_file()
BACKUP_FOLDER = 'Backup'
LOGO_FILE = 'logo.png'
GOLDEN_TEXT_FILE = 'golden_text_setting.txt'

os.makedirs(BACKUP_FOLDER, exist_ok=True)

# Database me missing columns add karo - 1 baar chalega
def add_missing_columns():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE items ADD COLUMN default_unit TEXT DEFAULT 'Piece'")
        print("✅ default_unit column add ho gaya")
    except:
        pass  # Pehle se hai to error ignore karo
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

# PERF FIX: auto_daily_backup() and the whole schema-migration block below used to run
# unconditionally on EVERY Streamlit rerun (every click/keystroke anywhere in the app) -
# ~40 schema probe queries plus a backup-folder scan, every single time, since Streamlit
# re-executes this whole script top-to-bottom on each interaction. Wrapping one-time setup
# in @st.cache_resource makes it run at most once every few minutes (as a safety net)
# instead of on every rerun. backup_setting.py calls st.cache_resource.clear() right after
# a restore so a restored (possibly older-schema) database gets re-migrated immediately.
# ttl=180 (3 min) so that after Nayi Sale / Udhaar Entry ke saves, aaj ki dated
# Local+Drive backup bhi reasonably jaldi refresh ho jati hai - bina har click par
# chalne ke (jo dheema kar deta).
@st.cache_resource(ttl=180, show_spinner=False)
def run_auto_backup_check():
    auto_daily_backup()

# --- TABLES CREATE ---
@st.cache_resource(ttl=3600, show_spinner=False)
def ensure_database_schema():
    add_missing_columns()
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY)''')

    # Bill Record Tables - NAYA ADD KARO
    c.execute('''CREATE TABLE IF NOT EXISTS sales_bills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_no TEXT,
        customer_id INTEGER,
        customer_name TEXT,
        date TEXT,
        time TEXT,
        subtotal REAL,
        discount REAL,
        final_total REAL,
        paid_amount REAL,
        balance REAL,
        type TEXT DEFAULT 'Multi-Item'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS sales_bill_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id INTEGER,
        item_name TEXT,
        qty REAL,
        unit TEXT,
        rate REAL,
        total REAL,
        FOREIGN KEY (bill_id) REFERENCES sales_bills(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS khata (id INTEGER PRIMARY KEY, customer_name TEXT, amount REAL, type TEXT, note TEXT, date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_notes (id INTEGER PRIMARY KEY, note_text TEXT, full_datetime TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS customer_status (customer_name TEXT PRIMARY KEY, status TEXT, remark TEXT, updated_on TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT, address TEXT, photo BLOB, status TEXT DEFAULT 'Active', manual_status TEXT DEFAULT 'Auto')''')
    c.execute('''CREATE TABLE IF NOT EXISTS udhaar (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, date TEXT, type TEXT, amount REAL, item TEXT, qty REAL, rate REAL, detail TEXT, time TEXT, unit TEXT, pehle_baaki REAL, baad_baaki REAL, FOREIGN KEY(customer_id) REFERENCES customers(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS defaulter_payments (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL, phone TEXT, total_baaki REAL, jama_amount REAL, remaining_baaki REAL, jama_date TEXT, photo_path TEXT, remark TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS agencies (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, phone TEXT, address TEXT, commission REAL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS agency_bills (id INTEGER PRIMARY KEY AUTOINCREMENT, agency_id INTEGER, bill_no TEXT, total_amount REAL, paid_amount REAL DEFAULT 0, remaining REAL, status TEXT DEFAULT 'Active', start_date TEXT, complete_date TEXT, FOREIGN KEY(agency_id) REFERENCES agencies(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS agency_payments (id INTEGER PRIMARY KEY AUTOINCREMENT, bill_id INTEGER, agency_id INTEGER, amount REAL, payment_date TEXT, payment_time TEXT, remark TEXT, FOREIGN KEY(bill_id) REFERENCES agency_bills(id), FOREIGN KEY(agency_id) REFERENCES agencies(id))''')

    # --- CHAKI & EXPENSE TABLES ---
    c.execute('''CREATE TABLE IF NOT EXISTS chaki_records (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT, type TEXT, weight REAL, rate REAL, total_amount REAL, paid_amount REAL, date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, expense_type TEXT, amount REAL, detail TEXT, date TEXT)''')

    def add_column_if_not_exists(table_name, column_name, column_type):
        try:
            c.execute(f"SELECT {column_name} FROM {table_name} LIMIT 1")
        except sqlite3.OperationalError:
            c.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    conn.commit()
    add_column_if_not_exists('items', 'name', 'TEXT')
    add_column_if_not_exists('items', 'price', 'REAL')
    add_column_if_not_exists('items', 'stock', 'INTEGER')
    add_column_if_not_exists('items', 'category', 'TEXT')
    add_column_if_not_exists('items', 'sale_price', 'REAL')
    add_column_if_not_exists('items', 'base_unit', 'TEXT')
    add_column_if_not_exists('sales', 'item_id', 'INTEGER')
    add_column_if_not_exists('sales', 'qty', 'INTEGER')
    add_column_if_not_exists('sales', 'total', 'REAL')
    add_column_if_not_exists('sales', 'date', 'TEXT')
    add_column_if_not_exists('sales', 'customer_name', 'TEXT')
    add_column_if_not_exists('sales', 'payment_type', 'TEXT')
    add_column_if_not_exists('sales', 'sale_type', 'TEXT')
    add_column_if_not_exists('sales', 'bill_no', 'TEXT')
    add_column_if_not_exists('sales', 'time', 'TEXT')
    add_column_if_not_exists('sales', 'rate', 'REAL')
    add_column_if_not_exists('sales', 'munafa', 'REAL DEFAULT 0')
    add_column_if_not_exists('sales', 'unit', "TEXT DEFAULT 'Pcs'")
    add_column_if_not_exists('sales', 'note', 'TEXT')
    add_column_if_not_exists('sales', 'item_name', 'TEXT')
    # BUG FIX: items_add.py's Quick-Sale "Return" flow inserts a customer_id value into the
    # sales table, but nothing ever created this column - so processing any return used to
    # crash with "sqlite3.OperationalError: table sales has no column named customer_id".
    add_column_if_not_exists('sales', 'customer_id', 'INTEGER')
    add_column_if_not_exists('khata', 'item_name', 'TEXT')
    add_column_if_not_exists('khata', 'qty', 'REAL')
    add_column_if_not_exists('khata', 'rate', 'REAL')
    add_column_if_not_exists('khata', 'full_datetime', 'TEXT')
    add_column_if_not_exists('customer_status', 'photo', 'BLOB')
    add_column_if_not_exists('customer_status', 'phone', 'TEXT')
    add_column_if_not_exists('customer_status', 'address', 'TEXT')
    add_column_if_not_exists('customers', 'manual_status', 'TEXT')
    add_column_if_not_exists('udhaar', 'item', 'TEXT')
    add_column_if_not_exists('udhaar', 'qty', 'REAL')
    add_column_if_not_exists('udhaar', 'rate', 'REAL')
    add_column_if_not_exists('udhaar', 'time', 'TEXT')
    add_column_if_not_exists('udhaar', 'unit', 'TEXT')
    add_column_if_not_exists('udhaar', 'pehle_baaki', 'REAL')
    add_column_if_not_exists('udhaar', 'baad_baaki', 'REAL')
    add_column_if_not_exists('agencies', 'phone', 'TEXT')
    add_column_if_not_exists('agencies', 'address', 'TEXT')
    add_column_if_not_exists('agencies', 'commission', 'REAL')
    add_column_if_not_exists('customers', 'customer_type', "TEXT DEFAULT 'Customer'")

    # BUG FIX: expenses.py lets the user attach a photo to an expense (e.g. bijli/gas bill),
    # but no 'image_path' column ever existed - so EVERY expense save used to fail with
    # "Error saving data: table expenses has no column named image_path" and nothing got saved.
    add_column_if_not_exists('expenses', 'image_path', 'TEXT')
    add_column_if_not_exists('expenses', 'category', 'TEXT')
    add_column_if_not_exists('expenses', 'description', 'TEXT')
    add_column_if_not_exists('expenses', 'time', 'TEXT')

    # BUG FIX: items_add.py's Quick-Sale return flow inserts item_id into sales_bill_items,
    # but the table (as created in app.py) never had that column - crashed on any return.
    add_column_if_not_exists('sales_bill_items', 'item_id', 'INTEGER')

    # BUG FIX: items_add.py's Quick-Sale bill save inserts a customer_name value into the
    # udhaar table, but that column never existed - so saving ANY Quick Sale bill used to
    # crash with "sqlite3.OperationalError: table udhaar has no column named customer_name".
    add_column_if_not_exists('udhaar', 'customer_name', 'TEXT')

    # --- BUG FIX: shared tables were being created with DIFFERENT/CONFLICTING column
    # sets in different files (items_add.py / nayi_sale.py / udhaar_khatta.py / daily_sale.py /
    # roz_ka_roll_nama.py / agencies.py all touch the SAME table names but expected different
    # columns). Whichever page ran first "won" and later pages crashed with
    # "sqlite3.OperationalError: table X has no column named Y". Fixing this centrally here,
    # since this file always runs first, guarantees every column every page needs actually
    # exists - no matter which menu the user opens first.

    # stock_history (used by items_add.py, nayi_sale.py, udhaar_khatta.py, roz_ka_roll_nama.py, reports.py)
    c.execute('''CREATE TABLE IF NOT EXISTS stock_history (id INTEGER PRIMARY KEY AUTOINCREMENT)''')
    add_column_if_not_exists('stock_history', 'item_id', 'INTEGER')
    add_column_if_not_exists('stock_history', 'item_name', 'TEXT')
    add_column_if_not_exists('stock_history', 'type', 'TEXT')
    add_column_if_not_exists('stock_history', 'action', 'TEXT')
    add_column_if_not_exists('stock_history', 'qty', 'REAL')
    add_column_if_not_exists('stock_history', 'unit', 'TEXT')
    add_column_if_not_exists('stock_history', 'old_stock', 'REAL')
    add_column_if_not_exists('stock_history', 'new_stock', 'REAL')
    add_column_if_not_exists('stock_history', 'note', 'TEXT')
    add_column_if_not_exists('stock_history', 'date', 'TEXT')
    add_column_if_not_exists('stock_history', 'time', 'TEXT')
    add_column_if_not_exists('stock_history', 'user', 'TEXT')

    # roll_nama (used by daily_sale.py dashboard + roz_ka_roll_nama.py page)
    c.execute('''CREATE TABLE IF NOT EXISTS roll_nama (id INTEGER PRIMARY KEY AUTOINCREMENT)''')
    add_column_if_not_exists('roll_nama', 'date', 'TEXT')
    add_column_if_not_exists('roll_nama', 'customer_name', 'TEXT')
    add_column_if_not_exists('roll_nama', 'customer', 'TEXT')
    add_column_if_not_exists('roll_nama', 'item', 'TEXT')
    add_column_if_not_exists('roll_nama', 'qty', 'REAL DEFAULT 1.0')
    add_column_if_not_exists('roll_nama', 'amount', 'REAL')
    add_column_if_not_exists('roll_nama', 'paid', 'REAL')
    add_column_if_not_exists('roll_nama', 'status', 'TEXT')
    add_column_if_not_exists('roll_nama', 'bachat', 'REAL DEFAULT 0')

    # agency_v2_bills / agency_v2_payments (used by agencies.py + daily_sale.py + reports.py)
    c.execute('''CREATE TABLE IF NOT EXISTS agency_v2_bills (id INTEGER PRIMARY KEY AUTOINCREMENT)''')
    add_column_if_not_exists('agency_v2_bills', 'agency_id', 'INTEGER')
    add_column_if_not_exists('agency_v2_bills', 'bill_number', 'TEXT')
    add_column_if_not_exists('agency_v2_bills', 'date', 'TEXT')
    add_column_if_not_exists('agency_v2_bills', 'total_amount', 'REAL')
    add_column_if_not_exists('agency_v2_bills', 'paid_amount', 'REAL DEFAULT 0.0')
    add_column_if_not_exists('agency_v2_bills', 'detail', 'TEXT')
    add_column_if_not_exists('agency_v2_bills', 'bill_photo', 'BLOB')
    add_column_if_not_exists('agency_v2_bills', 'status', "TEXT DEFAULT 'Pending'")

    c.execute('''CREATE TABLE IF NOT EXISTS agency_v2_payments (id INTEGER PRIMARY KEY AUTOINCREMENT)''')
    add_column_if_not_exists('agency_v2_payments', 'bill_id', 'INTEGER')
    add_column_if_not_exists('agency_v2_payments', 'date', 'TEXT')
    add_column_if_not_exists('agency_v2_payments', 'agency_name', 'TEXT')
    add_column_if_not_exists('agency_v2_payments', 'amount', 'REAL')
    add_column_if_not_exists('agency_v2_payments', 'detail', 'TEXT')
    add_column_if_not_exists('agency_v2_payments', 'payment_type', 'TEXT')
    add_column_if_not_exists('agency_v2_payments', 'payment_mode', "TEXT DEFAULT 'Cash'")

    # PERF FIX (lifetime speed / 10-lakh-record readiness): every report/list page filters by
    # date and/or joins on these foreign keys. Without indexes, SQLite does a full table scan
    # on every query - fine at 500 rows, painfully slow at 10 lakh. CREATE INDEX IF NOT EXISTS
    # is safe to run every launch (near-instant no-op if the index already exists), and each
    # is wrapped individually so one failure (e.g. a table/column missing on an older DB) can
    # never block the rest of the app from starting.
    def add_index_if_not_exists(index_name, table_name, columns):
        try:
            c.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns})")
        except sqlite3.OperationalError:
            pass  # table/column not present yet on this DB - safe to skip, retried next launch

    add_index_if_not_exists('idx_sales_date', 'sales', 'date')
    add_index_if_not_exists('idx_sales_item_id', 'sales', 'item_id')
    add_index_if_not_exists('idx_sales_sale_type', 'sales', 'sale_type')
    add_index_if_not_exists('idx_sales_bills_date', 'sales_bills', 'date')
    add_index_if_not_exists('idx_sales_bills_bill_no', 'sales_bills', 'bill_no')
    add_index_if_not_exists('idx_sales_bill_items_bill_id', 'sales_bill_items', 'bill_id')
    add_index_if_not_exists('idx_udhaar_customer_id', 'udhaar', 'customer_id')
    add_index_if_not_exists('idx_udhaar_date', 'udhaar', 'date')
    add_index_if_not_exists('idx_khata_customer_name', 'khata', 'customer_name')
    add_index_if_not_exists('idx_agency_bills_agency_id', 'agency_bills', 'agency_id')
    add_index_if_not_exists('idx_agency_payments_bill_id', 'agency_payments', 'bill_id')
    add_index_if_not_exists('idx_agency_v2_bills_agency_name', 'agency_v2_bills', 'agency_name')
    add_index_if_not_exists('idx_agency_v2_payments_bill_id', 'agency_v2_payments', 'bill_id')
    add_index_if_not_exists('idx_customers_name', 'customers', 'name')
    add_index_if_not_exists('idx_chakki_pisai_date', 'chakki_pisai', 'date')
    add_index_if_not_exists('idx_chakki_atta_sale_date', 'chakki_atta_sale', 'date')
    add_index_if_not_exists('idx_chaki_records_date', 'chaki_records', 'date')
    add_index_if_not_exists('idx_expenses_date', 'expenses', 'date')
    add_index_if_not_exists('idx_defaulter_customer_name', 'defaulter_payments', 'customer_name')

    conn.commit()
    conn.close()

run_auto_backup_check()
ensure_database_schema()

# BUG FIX (no such column: kharid_price): upar wala ensure_database_schema()
# 'items' table sirf (id, name) ke sath banata hai agar table pehle se na ho
# (jaise fresh/ephemeral restart ke baad). Poori items schema (kharid_price,
# sale_price, category, waghera) ab tak sirf items_add.py ke ensure_items_schema()
# mein thi, jo tab tak nahi chalta jab tak user khud "Items Add" tab na khole -
# is beech agar koi aur page (Roll Nama, Dashboard, waghera) items.kharid_price
# query kare to crash ho jata tha. Ab yeh startup par hi (Items Add khole
# bagair bhi) guaranteed chal jata hai - khud cached hai (1hr) is liye sasta hai.
try:
    from items_add import ensure_items_schema as _ensure_items_schema
    _ensure_items_schema()
except Exception:
    pass

# PERF FIX: this used to run unconditionally on every rerun too - a full khata table scan
# plus a per-row write with 3 correlated subqueries each. Cached the same way so it
# recomputes at most once an hour per server process instead of on every click.
@st.cache_resource(ttl=3600, show_spinner=False)
def auto_update_blacklist():
    conn = get_db()
    c = conn.cursor()
    six_months_ago = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d %H:%M:%S")
    defaulters = pd.read_sql(f'''
    SELECT k.customer_name, SUM(CASE WHEN k.type='Udhaar' THEN k.amount ELSE -k.amount END) as baaki,
    MAX(CASE WHEN k.type='Jama' THEN k.full_datetime ELSE NULL END) as last_payment
    FROM khata k
    GROUP BY k.customer_name
    HAVING baaki > 0.01 AND (last_payment IS NULL OR last_payment < '{six_months_ago}')
    ''', conn)
    for idx, row in defaulters.iterrows():
        updated_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        remark = f"Auto Blacklist: 6 mahine se payment nahi. Last: {row['last_payment'] if row['last_payment'] else 'Kabhi nahi'}"
        c.execute("""
        INSERT OR REPLACE INTO customer_status (customer_name, status, remark, updated_on, photo, phone, address)
        VALUES (?, 'Red',?,?,
        COALESCE((SELECT photo FROM customer_status WHERE customer_name=?), NULL),
        COALESCE((SELECT phone FROM customer_status WHERE customer_name=?), ''),
        COALESCE((SELECT address FROM customer_status WHERE customer_name=?), ''))""",
                  (row['customer_name'], remark, updated_on, row['customer_name'], row['customer_name'], row['customer_name']))
    conn.commit()
    conn.close()

auto_update_blacklist()

if 'goto_customer' not in st.session_state:
    st.session_state.goto_customer = None
if 'menu' not in st.session_state:
    st.session_state.menu = "📊 Dashboard"
if 'force_open_khata' not in st.session_state:
    st.session_state.force_open_khata = False

# BUG FIX: "st.session_state.menu" is bound to the sidebar radio widget (key="menu"
# below) - Streamlit does NOT allow setting a widget-bound session_state key directly
# once that widget has already rendered in the same run (raises StreamlitAPIException
# and breaks the page). The Dashboard "shortcut click" (Udhaar Khatta ka khata seedha
# kholna) needs to change pages programmatically, so it now sets a SEPARATE flag
# ('_pending_menu') instead. Here, BEFORE the sidebar widget renders, we apply that
# pending change safely - this is the one place in the whole app allowed to touch
# st.session_state.menu directly.
if st.session_state.get('_pending_menu') is not None:
    st.session_state.menu = st.session_state.pop('_pending_menu')

st.set_page_config(page_title="Afzal Store", layout="wide")

# ==================== SECURITY GATE (Master Key + Device Lock) ====================
# Yeh SABSE PEHLE chalna zaroori hai - kisi bhi page ka content render hone se
# pehle. Agar block ho jaye to enforce_security_gate() khud st.stop() kar deta
# hai, is se aage ka koi bhi code (DB, sidebar, pages) kabhi nahi chalta.
if not security_gate.enforce_security_gate():
    st.stop()

if security_gate.is_admin_request():
    security_gate.show_admin_panel()
    st.stop()

# ==================== GOOGLE DRIVE 2-WAY SYNC (100% SILENT) ====================
# Har rerun par call karna safe hai - khud kabhi block nahi karta (poora kaam
# ek background thread mein hota hai) aur KABHI koi popup/toast/message nahi
# dikhata - user ko Dashboard, Nayi Sale, Udhaar Khatta waghera istemal karte
# waqt is ka bilkul pata nahi chalega. Backup & Restore page khole bagair bhi
# offline<->online data khud-ba-khud sync hota rehta hai.
try:
    sync_manager.run_full_sync(DB_FILE)
except Exception:
    pass  # sync mein koi bhi masla aaye, app kabhi is wajah se na ruke

# PERF FIX: setup_pwa() disk par icons/manifest likhta hai - is se sirf ek dafa
# (cache_resource se) chalta hai, har rerun par nahi. inject_pwa_tags() halka
# HTML/JS hai, har rerun par chalna safe hai.
@st.cache_resource(show_spinner=False)
def _run_pwa_setup_once():
    try:
        pwa_setup.setup_pwa()
    except Exception:
        pass  # PWA icon/manifest na bhi bane to poori app chalti rahegi
    return True

_run_pwa_setup_once()
pwa_setup.inject_pwa_tags()

theme_colors = get_theme_colors()

sidebar_color = theme_colors.get('sidebar_bg', '#111e14')
sidebar_bg_img_base64 = get_base64_image('sidebar_bg_img.png')
sb_size = "cover"
sb_repeat = "no-repeat"
if os.path.exists('sidebar_settings.txt'):
    with open('sidebar_settings.txt', 'r') as f:
        data = f.read().split('|')
        if len(data) >= 2:
            sb_size = "contain" if data[0] == "Contain (Fit)" else "cover"
            sb_repeat = "repeat" if data[1] == "Repeat (Tile)" else "no-repeat"

if sidebar_bg_img_base64:
    sidebar_style = f"""
    background-color: {sidebar_color}!important;
    background-image: linear-gradient(180deg, rgba(8, 12, 9, 0.75) 0%, rgba(8, 12, 9, 0.75) 100%), url("data:image/png;base64,{sidebar_bg_img_base64}")!important;
    background-size: {sb_size}!important;
    background-repeat: {sb_repeat}!important;
    background-position: center!important;
    """
else:
    sidebar_style = f"background: {sidebar_color}!important;"

st.markdown(f"""
<style>
[data-testid="stSidebar"] {{ {sidebar_style} }}
div[data-testid="stSidebarUserContent"] div[role="radiogroup"] label {{ background: transparent!important; border: none!important; border-left: 3px solid transparent!important; padding: 10px 20px!important; border-radius: 0px!important; margin-bottom: 2px!important; transition: all 0.2s ease!important; }}
div[data-testid="stSidebarUserContent"] div[role="radiogroup"] label:hover {{ background: rgba(255, 255, 255, 0.1)!important; border-left: 3px solid rgba(255, 255, 255, 0.5)!important; }}
div[data-testid="stSidebarUserContent"] div[role="radiogroup"] [data-checked="true"] {{ background: rgba(255, 255, 255, 0.15)!important; border-left: 3px solid #00ff66!important; }}
div[data-testid="stSidebarUserContent"] div[role="radiogroup"] label div[data-testid="stMarkdownContainer"] p {{ font-size: 15px!important; font-weight: 500!important; color: #ffffff!important; }}
</style>
""", unsafe_allow_html=True)

if os.path.exists(GOLDEN_TEXT_FILE):
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] h3 {
    background: linear-gradient(135deg, #FFD700 0%, #FFA500 50%, #FFD700 100%)!important;
    -webkit-background-clip: text!important;
    -webkit-text-fill-color: transparent!important;
    background-clip: text!important;
    font-weight: 800!important;
    text-shadow: 0px 0px 15px rgba(255, 215, 0, 0.4)!important;
    }
    </style>
    """, unsafe_allow_html=True)

def show_logo(width=50, height=60, sidebar=False):
    logo_shape = get_logo_shape()
    logo_base64 = get_base64_logo()
    if sidebar:
        width, height = 40, 50
    if logo_base64:
        border_radius = "50%" if logo_shape == "Gol" else "8px"
        if logo_shape == "Gol":
            height = width
        return f'<div style="width:{width}px; height:{height}px; border-radius:{border_radius}; border:2px solid #00c850; overflow:hidden; display:flex; align-items:center; justify-content:center; background-image:url(\'data:image/png;base64,{logo_base64}\'); background-size:cover; background-position:center;"></div>'
    return f"<div style='font-size:{width}px; text-align:center;'>🛒</div>"

with st.sidebar:
    col1, col2 = st.columns([1, 3])
    with col1:
        st.markdown(show_logo(sidebar=True), unsafe_allow_html=True)
    with col2:
        st.markdown("<h3 style='margin-top:15px; margin-bottom:0px; color:#00c850!important; font-family: sans-serif;'>Afzal Store</h3>", unsafe_allow_html=True)
    st.divider()
    menu_options = [
        "📊 Dashboard",
        "📋 Roz Ka Roll Nama",
        "📒 Udhaar Khatta",
        "🛒 Nayi Sale",
        "📦 Items Add",
        "🌾 Chaki Management",
        "⚡ Expenses & Bill",
        "📝 Roz Ka Note",
        "🏢 Agencies",
        "🚫 Defaulter",
        "📈 Reports",
        "💾 Backup & Restore",
        "⚙️ Logo Setting"
    ]
    # BUG FIX: index was being recomputed from st.session_state.menu on every rerun, and
    # that same session_state entry was then overwritten with the widget's return value -
    # but with no key= binding the widget to it, a click's new value and the freshly
    # recomputed `index` disagreed for one rerun. The click would visually "take" for a
    # moment then snap back, and only a second click on the same option would stick.
    # Binding directly via key="menu" lets Streamlit own st.session_state.menu itself and
    # removes the desync - st.session_state.menu is already initialized above (line 270).
    st.radio("Menu Chuno", menu_options, key="menu", label_visibility="collapsed")

dragon_bg_base64 = get_base64_image(DRAGON_BG_FILE)
if dragon_bg_base64:
    st.markdown(f"""
    <style>
   .dragon-banner {{ background-image: url("data:image/png;base64,{dragon_bg_base64}"); background-size: cover; background-position: center; padding: 45px 30px; border-radius: 12px; text-align: center; margin-top: -30px; margin-bottom: 25px; box-shadow: 0px 4px 15px rgba(0,0,0,0.15); }}
   .dragon-title {{ color: #1a1a1a!important; font-size: 52px!important; font-weight: 900!important; margin: 0px!important; text-shadow: 2px 2px 10px rgba(255, 255, 255, 0.9); }}
    </style>
    <div class="dragon-banner"><h1 class="dragon-title">Afzal Kiryana Store</h1></div>
    """, unsafe_allow_html=True)
else:
    col1, col2 = st.columns([1, 10])
    with col1:
        st.markdown(show_logo(width=50, height=60), unsafe_allow_html=True)
    with col2:
        st.markdown("<h1 style='padding-top:15px'>Afzal Store</h1>", unsafe_allow_html=True)

# --- NAVIGATION ---
if st.session_state.menu == "📊 Dashboard":
    show_daily_sale(get_db) # <-- YE THEK HO GAYA
elif st.session_state.menu == "📋 Roz Ka Roll Nama":
    show_roll_nama(get_db)
elif st.session_state.menu == "📒 Udhaar Khatta":
    show_udhaar_khatta(get_db)
elif st.session_state.menu == "🛒 Nayi Sale":
    show_nayi_sale(get_db)
elif st.session_state.menu == "📦 Items Add":
    show_items_add()
elif st.session_state.menu == "🌾 Chaki Management":
    show_chakki_management(get_db)
elif st.session_state.menu == "⚡ Expenses & Bill":
    show_expenses(get_db)
elif st.session_state.menu == "📝 Roz Ka Note":
    st.header("📝 Roz Ka Note")
    conn = get_db()
    c = conn.cursor()
    note_text = st.text_area("Aaj ka note likho")
    if st.button("Note Save Karo"):
        if note_text:
            c.execute("INSERT INTO daily_notes (note_text, full_datetime) VALUES (?,?)", (note_text, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            st.rerun()
    notes_df = pd.read_sql("SELECT * FROM daily_notes ORDER BY id DESC", conn)
    st.dataframe(notes_df, use_container_width=True)
    conn.close()
elif st.session_state.menu == "🏢 Agencies":
    show_agencies(get_db)
elif st.session_state.menu == "🚫 Defaulter":
    show_defaulter()
elif st.session_state.menu == "📈 Reports":
    show_reports()
elif st.session_state.menu == "💾 Backup & Restore":
    show_backup_restore()
elif st.session_state.menu == "⚙️ Logo Setting":
    show_logo_setting(show_logo)