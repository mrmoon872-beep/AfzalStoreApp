import streamlit as st
import sqlite3
import pandas as pd
import difflib
from datetime import datetime


def generate_bill_no():
    now = datetime.now()
    return f"BILL-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}"


ALL_UNITS = ["KG", "Gram", "Piece", "Dozen", "Liter", "ML", "Pack"]


@st.cache_data(ttl=15, show_spinner=False)
def cached_item_catalog():
    """PERF FIX: item list ab 15-sec cache hoti hai (5000+ items pe bhi search
    turant chalega, har keystroke pe DB dobara query nahi hoti). Aata (Chakki)
    ko bhi ek normal item ki tarah isi list mein shamil kiya gaya hai."""
    try:
        conn = sqlite3.connect("afzal_store.db", timeout=10)
        c = conn.cursor()
        c.execute("PRAGMA table_info(items)")
        columns = [col[1] for col in c.fetchall()]
        has_unit_col = 'default_unit' in columns

        if has_unit_col:
            c.execute("SELECT name, COALESCE(sale_price, price, default_rate, 0), COALESCE(default_unit, 'Piece'), COALESCE(price, 0) FROM items WHERE name IS NOT NULL AND name != '' ORDER BY name")
        else:
            c.execute("SELECT name, COALESCE(sale_price, price, default_rate, 0), 'Piece', COALESCE(price, 0) FROM items WHERE name IS NOT NULL AND name != '' ORDER BY name")
        rows = c.fetchall()
        conn.close()

        catalog = [{"name": r[0], "rate": float(r[1] or 0), "unit": r[2] or "Piece", "cost": float(r[3] or 0), "source": "item"} for r in rows]
    except sqlite3.Error as e:
        st.error(f"⚠️ Items list load nahi ho saki: {e}")
        catalog = []

    # Aata (Chakki Management) ko bhi ek virtual item ki tarah add karo
    try:
        from chaki_management import get_current_stock, get_config_rate
        _, aata_stock = get_current_stock()
        aata_rate = get_config_rate()
        catalog.append({"name": "Aata (Chakki)", "rate": float(aata_rate), "unit": "KG", "cost": 0.0, "source": "aata", "stock": aata_stock})
    except Exception:
        pass  # Chaki module na milay to bhi Nayi Sale chalti rahegi, sirf Aata list mein nahi aayega

    return catalog


def fuzzy_filter_items(catalog, search_text, limit=30):
    """Smart Search: pehle simple substring match (jo "C" type karte hi turant
    C se shuru hone wale items dikhata hai), phir agar kam results milein to
    fuzzy/typo-tolerant match bhi try karta hai (jaise "Cheni" -> "Cheeni").
    Python ki built-in difflib use ki hai - koi extra install nahi chahiye."""
    if not search_text:
        return catalog[:limit]

    search_lower = search_text.strip().lower()
    substring_matches = [it for it in catalog if search_lower in it["name"].lower()]

    if len(substring_matches) >= 3:
        return substring_matches[:limit]

    # Fuzzy fallback - kharab spelling ke liye
    all_names = [it["name"] for it in catalog]
    close = difflib.get_close_matches(search_text, all_names, n=limit, cutoff=0.5)
    fuzzy_matches = [it for it in catalog if it["name"] in close]

    # Substring aur fuzzy dono ko combine karo (duplicate hataate hue)
    combined = {it["name"]: it for it in (substring_matches + fuzzy_matches)}
    return list(combined.values())[:limit] if combined else catalog[:limit]


def _format_item_label(it):
    return f"{it['name']} - Rs.{it['rate']:.0f}/{it['unit']}"


def _cust_options(c):
    try:
        c.execute("SELECT id, name FROM customers WHERE status = 'Active' OR status IS NULL ORDER BY name")
        rows = c.fetchall()
    except sqlite3.Error:
        rows = []
    options = {"Cash Customer": 0}
    for cust in rows:
        options[cust[1]] = cust[0]
    return options


def _save_stock_and_side_effects(c, conn, item_name, qty, unit, rate, total_amt, cust_id, cust_name, bill_no, status, is_aata):
    """Ek item sell hone ke SAARE side-effects ek jagah - stock cut, roll_nama
    entry (Roz Ka Roll Nama + Reports mein dikhne ke liye), aur Aata ho to
    chakki_atta_sale mein bhi. Har step try/except mein - koi ek fail ho to
    bhi baaki try hote hain, poora bill save fail nahi hota."""
    warnings = []

    if is_aata:
        try:
            c.execute("""INSERT INTO chakki_atta_sale (date, customer_name, aata_kg, rate_per_kg, total, sale_type, paid, remaining_balance, source)
                         VALUES (?,?,?,?,?,?,?,?,?)""",
                      (datetime.now().strftime("%Y-%m-%d"), cust_name, qty, rate, total_amt,
                       "Cash Sale" if status == "cash" else "Udhar Par Diya",
                       total_amt if status == "cash" else 0.0,
                       0.0 if status == "cash" else total_amt, f"Nayi Sale Bill: {bill_no}"))
        except sqlite3.Error as e:
            warnings.append(f"Chakki stock update nahi ho saka: {e}")
    else:
        try:
            c.execute("SELECT stock FROM items WHERE name=?", (item_name,))
            result = c.fetchone()
            if result and result[0] is not None:
                old_stock = result[0]
                new_stock = old_stock - qty
                c.execute("UPDATE items SET stock=? WHERE name=?", (new_stock, item_name))
                c.execute("""INSERT INTO stock_history (item_name, date, type, qty, unit, old_stock, new_stock, note)
                            VALUES (?,?,?,?,?,?,?,?)""",
                          (item_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'sale', qty, unit, old_stock, new_stock, f"Bill: {bill_no} - {cust_name}"))
        except sqlite3.Error as e:
            warnings.append(f"Stock update nahi ho saka ({item_name}): {e}")

    # Roz Ka Roll Nama + Reports mein dikhne ke liye - yeh pehle MISSING tha
    try:
        c.execute("""INSERT INTO roll_nama (date, customer, customer_name, item, qty, amount, paid, status, bachat)
                     VALUES (?,?,?,?,?,?,?,?,?)""",
                  (datetime.now().strftime("%Y-%m-%d"), cust_name, cust_name, item_name, qty, total_amt,
                   total_amt if status == "cash" else 0.0,
                   "Cash" if status == "cash" else "Udhaar", 0.0))
    except sqlite3.Error as e:
        warnings.append(f"Roz Ka Roll Nama mein add nahi ho saka: {e}")

    return warnings


def show_nayi_sale(get_db):
    conn = get_db()
    c = conn.cursor()

    tab1, tab2, tab3 = st.tabs(["🛒 Nayi Sale", "🛍 Multi-Item Cart (Fast Bill)", "↩️ Item Return / Wapsi"])
    catalog = cached_item_catalog()

    # ==================== TAB 1: NAYI SALE (Single Item, Fast) ====================
    with tab1:
        st.subheader("🛒 Nayi Sale")

        if not catalog:
            st.warning("Items table me koi item nahi hai. Pehle items add karein.")
        else:
            cust_options = _cust_options(c)
            selected_cust_name = st.selectbox("Customer Khatta Chuno", list(cust_options.keys()), key="ns_cust")
            cust_id = cust_options[selected_cust_name]

            search_text = st.text_input("🔍 Item Dhoondo (jaise 'C' likhein to Chini, Chawal sab dikhenge)", key="ns_search")
            filtered = fuzzy_filter_items(catalog, search_text)

            if not filtered:
                st.info("Koi item nahi mila is naam se.")
            else:
                labels = [_format_item_label(it) for it in filtered]
                selected_label = st.selectbox("Item Chuno", labels, key="ns_item_select")
                selected_item = filtered[labels.index(selected_label)]
                is_aata = selected_item["source"] == "aata"
                default_unit = selected_item["unit"]
                default_rate = selected_item["rate"]

                col1, col2, col3 = st.columns([1.3, 1, 1.3])
                with col2:
                    unit = st.selectbox("Unit", ALL_UNITS, index=ALL_UNITS.index(default_unit) if default_unit in ALL_UNITS else 0, key="ns_unit", disabled=is_aata)
                with col3:
                    rate = st.number_input(f"Rate per {unit}", min_value=0.0, step=1.0, value=float(default_rate), format="%.2f", key="ns_rate")

                # PRICE <-> QTY BIDIRECTIONAL AUTO-CALCULATION
                def _ns_qty_changed():
                    r = st.session_state.get("ns_rate", 0)
                    if r > 0:
                        st.session_state["ns_amount"] = round(st.session_state["ns_qty"] * r, 2)

                def _ns_amount_changed():
                    r = st.session_state.get("ns_rate", 0)
                    if r > 0:
                        st.session_state["ns_qty"] = round(st.session_state["ns_amount"] / r, 3)

                with col1:
                    qty = st.number_input("Quantity", min_value=0.0, step=0.1, value=st.session_state.get("ns_qty", 1.0), format="%.3f", key="ns_qty", on_change=_ns_qty_changed)

                amount_col1, amount_col2 = st.columns(2)
                with amount_col1:
                    st.number_input(f"Ya Amount Rs. Likhein (Qty khud calculate hogi)", min_value=0.0, step=10.0,
                                     value=st.session_state.get("ns_amount", round(qty * rate, 2)), key="ns_amount", on_change=_ns_amount_changed)

                total_amount = qty * rate
                with amount_col2:
                    st.metric("Total Amount", f"Rs. {total_amount:,.0f}")

                note = st.text_input("Note (Optional)", key="ns_note")

                if st.button("💾 Save Sale", type="primary", use_container_width=True, key="ns_save_btn"):
                    if qty <= 0 or total_amount <= 0:
                        st.error("❌ Quantity aur Amount 0 se zyada hone chahiye!")
                    else:
                        try:
                            current_time = datetime.now()
                            bill_no = generate_bill_no()
                            status = "cash" if cust_id == 0 else "udhaar"

                            c.execute("""INSERT INTO sales_bills
                                (bill_no, customer_id, customer_name, date, time, subtotal, discount, final_total, paid_amount, balance, type)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                                (bill_no, cust_id, selected_cust_name, current_time.strftime("%Y-%m-%d"),
                                 current_time.strftime("%I:%M %p"), total_amount, 0, total_amount,
                                 total_amount if status == "cash" else 0.0,
                                 0.0 if status == "cash" else total_amount, 'Single Item'))
                            bill_id = c.lastrowid

                            c.execute("""INSERT INTO sales_bill_items (bill_id, item_name, qty, unit, rate, total)
                                        VALUES (?,?,?,?,?,?)""", (bill_id, selected_item["name"], qty, unit, rate, total_amount))

                            # Sirf real (Udhaar Khatta) customer ho tabhi udhaar table mein likho -
                            # BUG FIX: pehle "Cash Customer" (id=0) ke liye bhi udhaar row ban sakti
                            # thi agar balance>0 ho jata, jo ek "ghost" entry ban jati thi.
                            if cust_id != 0:
                                c.execute("INSERT INTO udhaar (customer_id, date, type, amount, item, qty, rate, detail, time, unit) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                          (cust_id, current_time.strftime("%Y-%m-%d"),
                                           'udhaar' if status == 'udhaar' else 'jama',
                                           total_amount, selected_item["name"], qty, rate, f"Bill: {bill_no}", current_time.strftime("%I:%M %p"), unit))

                            warnings = _save_stock_and_side_effects(c, conn, selected_item["name"], qty, unit, rate, total_amount,
                                                                     cust_id, selected_cust_name, bill_no, status, is_aata)

                            conn.commit()
                            st.cache_data.clear()
                            for w in warnings:
                                st.warning(f"⚠️ {w}")
                            st.success(f"✅ Sale saved! Bill No: {bill_no}")
                            st.balloons()
                            for k in ["ns_qty", "ns_amount"]:
                                st.session_state.pop(k, None)
                            st.rerun()
                        except sqlite3.Error as e:
                            conn.rollback()
                            st.error(f"❌ Sale save nahi ho saki: {e}")

    # ==================== TAB 2: MULTI-ITEM CART (Fast Bill) ====================
    with tab2:
        st.subheader("🛍 Multi-Item Cart - Fast Bill")

        if 'multi_item_sale_cart' not in st.session_state:
            st.session_state.multi_item_sale_cart = []

        cust_map = _cust_options(c)
        selected_cust_cart = st.selectbox("Customer Chuno (Cart)", list(cust_map.keys()), key="cart_cust")
        cust_id = cust_map[selected_cust_cart]

        with st.expander("➕ Add Item to Cart", expanded=True):
            search_col, mode_col = st.columns([3, 1])
            with search_col:
                cart_search = st.text_input("🔍 Item Dhoondo (Smart Search - galat spelling bhi chalegi)", key="cart_search")
            filtered_cart_items = fuzzy_filter_items(catalog, cart_search)

            if not filtered_cart_items:
                st.warning("Koi item nahi mila. Spelling check karein ya naya item Add karein.")
            else:
                add_mode = mode_col.radio("Add Mode", ["🎯 Ek Item (Precise)", "⚡ Bulk (Kai Ek Saath)"], key="cart_add_mode", label_visibility="visible")

                if add_mode == "⚡ Bulk (Kai Ek Saath)":
                    # REQUIREMENT 1: Multi-Item Fast Selection - ek saath kai items cart mein
                    bulk_labels = [_format_item_label(it) for it in filtered_cart_items]
                    picked_labels = st.multiselect("Items Chuno (kai ek saath select kar sakte hain)", bulk_labels, key="cart_bulk_pick")
                    bulk_qty = st.number_input("Har Item Ki Default Qty", min_value=0.01, value=1.0, step=0.5, key="cart_bulk_qty")

                    if st.button("⚡ Sab Cart Mein Dalo", type="primary", use_container_width=True, key="cart_bulk_add_btn"):
                        added = 0
                        for lbl in picked_labels:
                            it = filtered_cart_items[bulk_labels.index(lbl)]
                            found = False
                            for existing in st.session_state.multi_item_sale_cart:
                                if existing['item'] == it['name'] and existing['unit'] == it['unit']:
                                    existing['qty'] += bulk_qty
                                    existing['total'] = existing['qty'] * existing['rate']
                                    found = True
                                    break
                            if not found:
                                st.session_state.multi_item_sale_cart.append({
                                    "item": it['name'], "qty": bulk_qty, "unit": it['unit'],
                                    "rate": it['rate'], "total": bulk_qty * it['rate'], "is_aata": it['source'] == 'aata'
                                })
                            added += 1
                        if added:
                            st.toast(f"✔️ {added} items cart mein add ho gaye!")
                            st.rerun()

                else:
                    # Precise single-item add with bidirectional Qty<->Amount
                    labels = [_format_item_label(it) for it in filtered_cart_items]
                    col1, col2, col3, col4 = st.columns([2.5, 1, 1.2, 1.2])
                    with col1:
                        selected_display = st.selectbox("Item Chuno", labels, key="cart_item_select")
                        selected_data = filtered_cart_items[labels.index(selected_display)]
                        cart_item = selected_data["name"]
                        default_rate = selected_data["rate"]
                        default_unit = selected_data["unit"]
                        is_aata_item = selected_data["source"] == "aata"

                    with col2:
                        unit = st.selectbox("Unit", ALL_UNITS, index=ALL_UNITS.index(default_unit) if default_unit in ALL_UNITS else 2, key="cart_unit", disabled=is_aata_item)
                    with col3:
                        cart_rate = st.number_input("Rate", value=float(default_rate), format="%.2f", key="cart_rate")

                    def _cart_qty_changed():
                        r = st.session_state.get("cart_rate", 0)
                        if r > 0:
                            st.session_state["cart_amount"] = round(st.session_state["cart_qty"] * r, 2)

                    def _cart_amount_changed():
                        r = st.session_state.get("cart_rate", 0)
                        if r > 0:
                            st.session_state["cart_qty"] = round(st.session_state["cart_amount"] / r, 3)

                    with col4:
                        cart_qty = st.number_input("Qty", min_value=0.0, step=0.1, value=st.session_state.get("cart_qty", 1.0), format="%.3f", key="cart_qty", on_change=_cart_qty_changed)

                    amt_col1, amt_col2 = st.columns(2)
                    with amt_col1:
                        # REQUIREMENT 3: Amount likho to Qty khud badle, Qty likho to Amount khud badle
                        st.number_input("Ya Amount Rs. (Qty khud calculate hogi)", min_value=0.0, step=10.0,
                                         value=st.session_state.get("cart_amount", round(cart_qty * cart_rate, 2)),
                                         key="cart_amount", on_change=_cart_amount_changed)
                    with amt_col2:
                        st.metric("Is Item Ka Total", f"Rs. {(cart_qty * cart_rate):,.0f}")

                    if st.button("➕ Add to Cart", use_container_width=True, key="cart_add_single_btn"):
                        if cart_qty > 0:
                            found = False
                            for existing in st.session_state.multi_item_sale_cart:
                                if existing['item'] == cart_item and existing['unit'] == unit:
                                    existing['qty'] += cart_qty
                                    existing['rate'] = cart_rate
                                    existing['total'] = existing['qty'] * cart_rate
                                    found = True
                                    st.toast(f"{cart_item} ki qty update ho gayi")
                                    break
                            if not found:
                                st.session_state.multi_item_sale_cart.append({
                                    "item": cart_item, "qty": cart_qty, "unit": unit,
                                    "rate": cart_rate, "total": cart_qty * cart_rate, "is_aata": is_aata_item
                                })
                            for k in ["cart_qty", "cart_amount"]:
                                st.session_state.pop(k, None)
                            st.rerun()
                        else:
                            st.error("❌ Qty 0 se zyada honi chahiye!")

        if st.session_state.multi_item_sale_cart:
            st.divider()
            st.write("**Current Cart:**")

            for idx, item in enumerate(st.session_state.multi_item_sale_cart):
                col1, col2, col3, col4, col5, col6 = st.columns([3, 1.2, 1, 1.2, 1.5, 0.8])
                with col1:
                    st.write(f"**{item['item']}**" + (" 🌾" if item.get('is_aata') else ""))
                with col2:
                    new_qty = st.number_input("Qty", value=float(item['qty']), key=f"qty_{idx}", label_visibility="collapsed", format="%.3f", min_value=0.0)
                with col3:
                    st.write(item['unit'])
                with col4:
                    new_rate = st.number_input("Rate", value=float(item['rate']), key=f"rate_{idx}", label_visibility="collapsed", format="%.2f", min_value=0.0)
                with col5:
                    st.write(f"**Rs. {new_qty * new_rate:.0f}**")
                with col6:
                    if st.button("🗑", key=f"del_{idx}", help="Delete item"):
                        st.session_state.multi_item_sale_cart.pop(idx)
                        st.rerun()

                if new_qty != item['qty'] or new_rate != item['rate']:
                    st.session_state.multi_item_sale_cart[idx]['qty'] = new_qty
                    st.session_state.multi_item_sale_cart[idx]['rate'] = new_rate
                    st.session_state.multi_item_sale_cart[idx]['total'] = new_qty * new_rate
                    st.rerun()

            st.divider()
            cart_subtotal = sum(i['total'] for i in st.session_state.multi_item_sale_cart)

            col1, col2 = st.columns(2)
            with col1:
                discount_type = st.selectbox("Discount Type", ["None", "Percentage %", "Flat Amount"], key="disc_type")
                if discount_type == "Percentage %":
                    discount_val = st.number_input("Discount %", min_value=0.0, max_value=100.0, value=0.0, key="disc_perc")
                    discount_amt = cart_subtotal * (discount_val / 100)
                elif discount_type == "Flat Amount":
                    discount_amt = st.number_input("Discount Rs.", min_value=0.0, value=0.0, key="disc_flat")
                else:
                    discount_amt = 0.0

            with col2:
                paid_amount = st.number_input("Paid Amount Rs.", min_value=0.0, value=float(max(cart_subtotal - discount_amt, 0)), key="paid_amt")

            final_total = cart_subtotal - discount_amt
            balance = final_total - paid_amount

            st.write(f"### Subtotal: Rs. {cart_subtotal:,.0f}")
            if discount_amt > 0:
                st.write(f"### Discount: -Rs. {discount_amt:,.0f}")
            st.write(f"### **Final Total: Rs. {final_total:,.0f}**")
            st.write(f"### Paid: Rs. {paid_amount:,.0f} | **Balance/Udhaar: Rs. {balance:,.0f}**")

            if balance > 0 and cust_id == 0:
                st.warning("⚠️ Cash Customer par baaki (udhaar) chhodna theek nahi - agar udhaar dena hai to upar 'Customer Chuno' mein asal customer select karein, warna yeh baaki kisi ke khatte mein nahi jayega.")

            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("🖨 Print Bill", use_container_width=True, key="cart_print_btn"):
                    now = datetime.now().strftime("%d-%m-%Y %I:%M %p")
                    items_html = "".join([
                        f"<tr><td>{i['item']}</td><td>{i['qty']:.3f} {i['unit']}</td><td>{i['rate']:.0f}</td><td>{i['total']:.0f}</td></tr>"
                        for i in st.session_state.multi_item_sale_cart
                    ])
                    html = f"""
                    <div style="font-family: Arial; width: 300px; margin: auto;">
                        <h2 style="text-align:center; margin:0;">Afzal Kiryana Store</h2>
                        <hr>
                        <p style="font-size:12px;">Date: {now}<br>Customer: {selected_cust_cart}</p>
                        <table style="width:100%; font-size:13px; border-collapse: collapse;">
                            <tr style="border-bottom:1px solid #000;"><th>Item</th><th>Qty</th><th>Rate</th><th>Total</th></tr>
                            {items_html}
                        </table>
                        <hr>
                        <p style="text-align:right; margin:2px;">Subtotal: Rs. {cart_subtotal:.0f}</p>
                        {"<p style='text-align:right; margin:2px;'>Discount: -Rs. " + f"{discount_amt:.0f}</p>" if discount_amt > 0 else ""}
                        <h3 style="text-align:right; margin:5px;">Total: Rs. {final_total:.0f}</h3>
                        <p style="text-align:right; margin:2px;">Paid: Rs. {paid_amount:.0f}</p>
                        <h3 style="text-align:right; margin:5px;">Balance: Rs. {balance:.0f}</h3>
                        <hr><p style="text-align:center; font-size:12px;">Shukriya! Dubara Tashreef Layein</p>
                    </div><script>window.print();</script>
                    """
                    st.components.v1.html(html, height=0)

            with col2:
                if st.button("💾 Final Bill Save", use_container_width=True, type="primary", key="cart_save_btn"):
                    try:
                        current_time = datetime.now()
                        bill_no = generate_bill_no()
                        status = "cash" if cust_id == 0 else ("udhaar" if balance > 0 else "cash")

                        c.execute("""INSERT INTO sales_bills
                            (bill_no, customer_id, customer_name, date, time, subtotal, discount, final_total, paid_amount, balance, type)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                            (bill_no, cust_id, selected_cust_cart, current_time.strftime("%Y-%m-%d"),
                             current_time.strftime("%I:%M %p"), cart_subtotal, discount_amt, final_total, paid_amount, balance, 'Multi-Item'))
                        bill_id = c.lastrowid

                        all_warnings = []
                        for item in st.session_state.multi_item_sale_cart:
                            c.execute("""INSERT INTO sales_bill_items (bill_id, item_name, qty, unit, rate, total)
                                        VALUES (?,?,?,?,?,?)""", (bill_id, item['item'], item['qty'], item['unit'], item['rate'], item['total']))

                            # BUG FIX: sirf real customer (cust_id != 0) ke liye udhaar table mein likhna -
                            # "Cash Customer" ke naam se ghost udhaar entries pehle ban sakti thin
                            if cust_id != 0:
                                c.execute("""INSERT INTO udhaar
                                    (customer_id, date, type, amount, item, qty, rate, detail, time, unit)
                                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                                    (cust_id, current_time.strftime("%Y-%m-%d"),
                                     'udhaar' if balance > 0 else 'jama',
                                     item['total'], item['item'], item['qty'], item['rate'],
                                     f"Bill: {bill_no}", current_time.strftime("%I:%M %p"), item['unit']))

                            w = _save_stock_and_side_effects(c, conn, item['item'], item['qty'], item['unit'], item['rate'], item['total'],
                                                              cust_id, selected_cust_cart, bill_no, status, item.get('is_aata', False))
                            all_warnings.extend(w)

                        conn.commit()
                        st.cache_data.clear()
                        st.session_state.multi_item_sale_cart = []
                        for w in set(all_warnings):
                            st.warning(f"⚠️ {w}")
                        st.success(f"✅ Bill saved! Bill No: {bill_no}")
                        st.balloons()
                        st.rerun()
                    except sqlite3.Error as e:
                        conn.rollback()
                        st.error(f"❌ Bill save nahi ho saka: {e}")

            with col3:
                if st.button("🗑 Cart Khali Karo", use_container_width=True, key="cart_clear_btn"):
                    st.session_state.multi_item_sale_cart = []
                    st.rerun()
        else:
            st.info("Cart khali hai. Upar se items add karein.")

    # ==================== TAB 3: ITEM RETURN / WAPSI ====================
    with tab3:
        st.subheader("↩️ Item Return / Wapsi")
        st.caption("Customer ne 1-2 din pehle jo bill liya tha, us mein se koi item wapas kar raha hai - stock wapas add hoga aur uska balance adjust hoga.")

        search_bill = st.text_input("🔍 Bill Number Dhoondo", key="return_bill_search")
        try:
            if search_bill.strip():
                c.execute("SELECT id, bill_no, customer_name, customer_id, date, final_total, balance, type FROM sales_bills WHERE bill_no LIKE ? ORDER BY id DESC LIMIT 30", (f"%{search_bill.strip()}%",))
            else:
                c.execute("SELECT id, bill_no, customer_name, customer_id, date, final_total, balance, type FROM sales_bills ORDER BY id DESC LIMIT 30")
            matching_bills = c.fetchall()
        except sqlite3.Error as e:
            st.error(f"⚠️ Bills load nahi ho sakay: {e}")
            matching_bills = []

        if not matching_bills:
            st.info("Koi bill nahi mila.")
        else:
            bill_labels = [f"{b[1]} | {b[2]} | {b[4]} | Rs.{b[5]:,.0f}" for b in matching_bills]
            selected_bill_label = st.selectbox("Bill Chuno", bill_labels, key="return_bill_select")
            selected_bill = matching_bills[bill_labels.index(selected_bill_label)]
            bill_id, bill_no, cust_name, r_cust_id, bill_date, bill_total, bill_balance, bill_type = selected_bill

            try:
                c.execute("SELECT id, item_name, qty, unit, rate, total FROM sales_bill_items WHERE bill_id=?", (bill_id,))
                bill_items = c.fetchall()
            except sqlite3.Error as e:
                st.error(f"⚠️ Bill items load nahi ho sakay: {e}")
                bill_items = []

            if not bill_items:
                st.warning("Is bill mein koi item record nahi mila.")
            else:
                st.markdown(f"**Bill: {bill_no}** | Customer: {cust_name} | Date: {bill_date}")
                return_item_labels = [f"{it[1]} (Becha: {it[2]:g} {it[3]}, Rate Rs.{it[4]:.0f})" for it in bill_items]
                selected_return_label = st.selectbox("Kaunsa Item Wapas Ho Raha Hai?", return_item_labels, key="return_item_select")
                selected_return_item = bill_items[return_item_labels.index(selected_return_label)]
                _, ret_item_name, ret_orig_qty, ret_unit, ret_rate, ret_orig_total = selected_return_item

                return_qty = st.number_input(f"Kitni Qty Wapas Ho Rahi Hai? (Max: {ret_orig_qty:g} {ret_unit})",
                                              min_value=0.0, max_value=float(ret_orig_qty), value=float(ret_orig_qty), step=0.1, key="return_qty")
                refund_amount = return_qty * ret_rate
                st.info(f"💰 **Refund/Adjustment Amount: Rs. {refund_amount:,.0f}**")

                if r_cust_id and r_cust_id != 0:
                    st.caption("Yeh customer ka udhaar hai - refund uske balance se KAM ho jayega (jama entry ban jayegi).")
                else:
                    st.caption("Yeh cash sale thi - refund cash mein wapas karna hoga (yeh sirf record ke liye save hoga).")

                if st.button("✅ Return/Wapsi Confirm Karo", type="primary", use_container_width=True, key="return_confirm_btn"):
                    if return_qty <= 0:
                        st.error("❌ Return qty 0 se zyada honi chahiye!")
                    else:
                        try:
                            # 1. Stock wapas barhao
                            c.execute("SELECT stock FROM items WHERE name=?", (ret_item_name,))
                            stock_row = c.fetchone()
                            if stock_row and stock_row[0] is not None:
                                old_stock = stock_row[0]
                                new_stock = old_stock + return_qty
                                c.execute("UPDATE items SET stock=? WHERE name=?", (new_stock, ret_item_name))
                                c.execute("""INSERT INTO stock_history (item_name, date, type, qty, unit, old_stock, new_stock, note)
                                            VALUES (?,?,?,?,?,?,?,?)""",
                                          (ret_item_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'return', return_qty, ret_unit,
                                           old_stock, new_stock, f"Return from Bill: {bill_no}"))

                            # 2. Roll Nama mein negative entry (record ke liye)
                            c.execute("""INSERT INTO roll_nama (date, customer, customer_name, item, qty, amount, paid, status, bachat)
                                         VALUES (?,?,?,?,?,?,?,?,?)""",
                                      (datetime.now().strftime("%Y-%m-%d"), cust_name, cust_name, f"RETURN: {ret_item_name}",
                                       return_qty, -refund_amount, -refund_amount, "Return", 0.0))

                            # 3. Agar udhaar customer tha, uska balance kam karo (jama jaisi entry)
                            if r_cust_id and r_cust_id != 0:
                                c.execute("""INSERT INTO udhaar (customer_id, date, type, amount, item, detail, time)
                                             VALUES (?,?,?,?,?,?,?)""",
                                          (r_cust_id, datetime.now().strftime("%Y-%m-%d"), 'jama', refund_amount,
                                           f"Return: {ret_item_name}", f"Item Return - Bill {bill_no}", datetime.now().strftime("%I:%M %p")))

                            conn.commit()
                            st.cache_data.clear()
                            st.success(f"✔️ Return mukammal! Stock mein {return_qty:g} {ret_unit} wapas aa gaya" +
                                       (f" aur customer ka Rs. {refund_amount:,.0f} balance kam ho gaya." if r_cust_id and r_cust_id != 0 else "."))
                            st.rerun()
                        except sqlite3.Error as e:
                            conn.rollback()
                            st.error(f"❌ Return save nahi ho saka: {e}")

    conn.close()
