from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import logging
import sqlite3
import streamlit as st
import pandas as pd
from data_structures import LinkedListCart, AVLTree, MinHeap, HeapEntry
import database as db

# Official Philippine timezone
PH_TZ = ZoneInfo("Asia/Manila")

def ph_now():
    return datetime.now(PH_TZ)

def ph_today():
    return ph_now().date()

def ph_datetime_string():
    return ph_now().replace(tzinfo=None).isoformat(timespec="seconds")

APP_DIR = Path(__file__).resolve().parent
LOG_PATH = APP_DIR / 'pos.log'
logging.basicConfig(filename=LOG_PATH, level=logging.ERROR, format='%(asctime)s %(levelname)s %(message)s')

st.set_page_config(page_title='Gulps & Grubs | POS', page_icon='🥤', layout='wide', initial_sidebar_state='collapsed')

def money(cents): return f"₱{int(cents)/100:,.2f}"
def safe_error(exc):
    logging.exception('Application operation failed')
    if isinstance(exc, (ValueError, sqlite3.IntegrityError)): st.error(str(exc))
    else: st.error('Something went wrong while saving your changes. No incomplete transaction was committed. Check pos.log for technical details.')
def cents_from_peso(value): return int(round(float(value)*100))

def load_html_template(_filename, **values):
    """Load a small HTML fragment from templates/ and safely fill placeholders."""
    from html import escape
    template_path = APP_DIR / 'templates' / _filename
    content = template_path.read_text(encoding='utf-8')
    for key, value in values.items():
        content = content.replace('{{ ' + key + ' }}', escape(str(value)))
    return content

def rebuild_tree():
    tree = AVLTree()
    for p in db.list_products(active_only=True): tree.insert(p['code'], p)
    tree.validate()
    return tree

def rebuild_heap():
    heap = MinHeap()
    for o in db.list_orders(pending_only=True):
        heap.push(HeapEntry(int(o['priority']), int(o['sequence_no']), int(o['id']), o))
    return heap

st.markdown(f'<style>{(APP_DIR / "style.css").read_text(encoding="utf-8")}</style>', unsafe_allow_html=True)

try:
    db.init_db()
except Exception as e:
    st.error('Could not initialize the database. Check folder permissions and the application log.')
    logging.exception('Database initialization failed')
    st.stop()

if 'cart' not in st.session_state: st.session_state.cart = LinkedListCart()
if 'last_sale' not in st.session_state: st.session_state.last_sale = None
if 'mode' not in st.session_state: st.session_state.mode = 'Admin'

st.markdown(load_html_template('brand_banner.html'), unsafe_allow_html=True)

# =========================================================================
#  GLOBAL TRANSACTIONS NOTIFICATION HUB (Pure Browser CSS Async Animation)
# =========================================================================
if 'global_toast' in st.session_state and st.session_state.global_toast:
    toast_data = st.session_state.global_toast
    
    st.markdown(
        f"""
        <style>
            @keyframes slideDismiss {{
                0% {{ opacity: 1; transform: translateY(0); max-height: 120px; margin-bottom: 25px; padding: 16px; }}
                80% {{ opacity: 1; transform: translateY(0); max-height: 120px; margin-bottom: 25px; padding: 16px; }}
                100% {{ opacity: 0; transform: translateY(-20px); max-height: 0px; margin-bottom: 0px; padding: 0px; overflow: hidden; visibility: hidden; }}
            }}
            .async-alert-banner {{
                background-color: {toast_data['bg']}; 
                color: white; 
                border-radius: 8px; 
                font-size: 15px; 
                font-weight: bold;
                box-shadow: 0 4px 6px rgba(0,0,0,0.12);
                display: flex;
                align-items: center;
                animation: slideDismiss 3.5s forwards cubic-bezier(0.4, 0, 0.2, 1);
                pointer-events: none; /* Prevents container from trapping pointer focal clicks */
            }}
        </style>
        <div class="async-alert-banner">
            <span style="font-size: 22px; margin-right: 12px; padding-left: 16px; padding-top: 12px; padding-bottom: 12px;">{toast_data['icon']}</span>
            <div style="padding-right: 16px; padding-top: 12px; padding-bottom: 12px;">{toast_data['msg']}</div>
        </div>
        """, 
        unsafe_allow_html=True
    )
    # Safely clear the data bucket completely behind the scenes
    st.session_state.global_toast = None
    
with st.container(key='site_header'):
    logo_col, brand_col, mode_col, page_col = st.columns([0.85, 1.65, 2.35, 4.75], vertical_alignment='center', gap='small')
    with logo_col:
        st.image(str(APP_DIR / 'brand_logo.jpg'), width=118)
    with brand_col:
        st.markdown(load_html_template('site_brand.html'), unsafe_allow_html=True)
    with mode_col:
        st.markdown(load_html_template('nav_label.html', label='WORKSPACE'), unsafe_allow_html=True)
        mode = st.radio('Workspace', ['Admin', 'Cashier', 'Inventory Manager'], index=['Admin', 'Cashier', 'Inventory Manager'].index(st.session_state.get('mode_choice', 'Admin')) if st.session_state.get('mode_choice', 'Admin') in ['Admin', 'Cashier', 'Inventory Manager'] else 0, horizontal=True, key='mode_choice', label_visibility='collapsed')
    st.session_state.mode = mode
    with page_col:
        st.markdown(load_html_template('nav_label.html', label='NAVIGATION'), unsafe_allow_html=True)
        if mode == 'Admin':
            page = st.radio('Admin navigation', ['Dashboard', 'Product Management', 'Sales History', 'Activity History'], horizontal=True, key='admin_page', label_visibility='collapsed')
        elif mode == 'Cashier':
            cashier_options = ['Dashboard', 'New Sale', 'Pickup Queue Priority', 'Sales History']
            current_selection = st.session_state.get('cashier_page', 'Dashboard')
            if current_selection not in cashier_options:
                current_selection = 'Dashboard'
            page = st.radio('Cashier navigation', cashier_options, index=cashier_options.index(current_selection), horizontal=True, key='cashier_page', label_visibility='collapsed')
        else:
            page = st.radio('Inventory navigation', ['Dashboard', 'Stock History'], horizontal=True, key='inventory_page', label_visibility='collapsed')
st.caption('Demo mode selector only — it is not secure authentication.')

try: product_tree = rebuild_tree()
except Exception as e:
    safe_error(e); st.stop()

# =========================================================================
# 👑 ADMIN WORKSPACE MODULES
# =========================================================================
if mode == 'Admin' and page == 'Dashboard':
    today = ph_today()
    start_time = datetime.combine(today, time.min).isoformat()
    end_time = datetime.combine(today + timedelta(days=1), time.min).isoformat()

    st.markdown("### Business Overview")
    summary = db.sales_summary(start_time, end_time)
    all_products = db.list_products(active_only=True)
    low = [p for p in all_products if p['stock'] <= p['low_stock_threshold']]
    high = [p for p in all_products if p['stock'] >= p['high_stock_threshold']]

    # ROW 1: 5 Compact KPI Cards
    a, b, c, d, e = st.columns(5, gap="small")
    a.metric('Today’s revenue', money(summary['revenue_cents']), help='Total value of recorded sales, not profit.')
    b.metric('Completed sales', summary['transactions'])
    c.metric('Active products', len(all_products))
    d.metric('Low-stock alerts', len(low), delta='Needs attention' if low else 'Stock looks good', delta_color='inverse' if low else 'normal')
    e.metric('High-stock alerts', len(high), delta='Overstocked' if high else 'Stock looks good', delta_color='off' if high else 'normal', help='Products at or above their high-stock threshold.')

    # ROW 2: 3-Column Bento Grid (50% | 25% | 25%)
    col_chart, col_recent, col_stock = st.columns([2, 1, 1], gap="small")

    with col_chart:
        with st.container(key='bento_chart_card'):
            st.markdown('**Sales over the last 7 days**')
            daily = []
            for i in range(6, -1, -1):
                day = today - timedelta(days=i)
                s = datetime.combine(day, time.min).isoformat()
                e = datetime.combine(day + timedelta(days=1), time.min).isoformat()
                sm = db.sales_summary(s, e)
                daily.append({'Date': day.strftime('%b %d'), 'Revenue (₱)': sm['revenue_cents'] / 100})
            st.bar_chart(pd.DataFrame(daily).set_index('Date'), height=245)

    with col_recent:
        with st.container(key='bento_recent_card'):
            st.markdown('**Recent transactions**')
            recent = db.transaction_history()[:6]
            if recent:
                st.dataframe(
                    pd.DataFrame([{'Sale #': r['id'], 'Date': r['created_at'].replace('T', ' ')[:16], 'Total': money(r['total_cents'])} for r in recent]),
                    use_container_width=True, hide_index=True, height=245
                )
            else:
                st.info('Completed sales will appear here.')

    with col_stock:
        with st.container(key='bento_stock_card'):
            st.markdown('**Stock watch**')
            tab_low, tab_high = st.tabs([f"Low Stock ({len(low)})", f"High Stock ({len(high)})"])
            with tab_low:
                if low:
                    st.dataframe(
                        pd.DataFrame([{'Code': p['code'], 'Product': p['name'], 'Stock': p['stock'], 'Min': p['low_stock_threshold']} for p in low]),
                        use_container_width=True, hide_index=True, height=195
                    )
                else:
                    st.success('No products at or below low-stock threshold.')
            with tab_high:
                if high:
                    st.dataframe(
                        pd.DataFrame([{'Code': p['code'], 'Product': p['name'], 'Stock': p['stock'], 'Max': p.get('high_stock_threshold', 0)} for p in high]),
                        use_container_width=True, hide_index=True, height=195
                    )
                else:
                    st.success('No products at or above high-stock threshold.')

elif mode == 'Admin' and page == 'Product Management':
    # Sleek smaller heading + Tabs with wider padding
    st.markdown('### Product Catalog Management')
    tab1, tab2, tab3 = st.tabs(['   Add product   ', '   Edit / Delete   ','   View Catalog   '
    ])

    with tab1:
        # Put Product Classification label & radio pills inline on a single compact row
        cls_lbl, cls_radio = st.columns([0.85, 3.5], vertical_alignment='center', gap='small')
        with cls_lbl:
            st.markdown('#### Product Classification')
        with cls_radio:
            classification = st.radio(
                'Product Classification *',
                ['Foods (Grubs)', 'Drinks (Gulps)', 'Others (Combo/Meal Plan)'],
                horizontal=True,
                label_visibility='collapsed'
            )

        # Dynamically pull pre-saved category lists
        try:
            db_products = db.list_products(active_only=False)
            drink_keywords = ['milktea', 'milkshake', 'shake', 'lemonade', 'slushie', 'slush', 'coffee', 'float', 'frappe', 'drink', 'beverage', 'juice', 'tea', 'brew', 'gulp']
            food_cats, drink_cats, combo_cats = set(), set(), set()
            for p in db_products:
                if not p['category']: continue
                _, _, custom_part = p['category'].partition(" | Custom:")
                clean_cat = p['category'].partition(" | Custom:").strip()
                clean_cat_lower = clean_cat.lower()
                if any(dk in clean_cat_lower for dk in drink_keywords): drink_cats.add(clean_cat)
                elif any(ck in clean_cat_lower for ck in ['combo', 'promo', 'bundle']): combo_cats.add(clean_cat)
                else: food_cats.add(clean_cat)
            if classification == 'Drinks (Gulps)': existing_saved_cats = sorted(list(drink_cats))
            elif classification == 'Others (Combo/Meal Plan)': existing_saved_cats = sorted(list(combo_cats))
            else: existing_saved_cats = sorted(list(food_cats))
        except Exception:
            existing_saved_cats = []

        def parse_and_format_price(raw_text):
            if not raw_text: return 0.0
            try: return float(raw_text.replace('₱', '').strip())
            except ValueError: return 0.0

        # AUTOMATIC PRODUCT FORM RESET
        if "clear_product_form" not in st.session_state:
            st.session_state.clear_product_form = False

        if st.session_state.clear_product_form:
            st.session_state[f'f_name_{classification}'] = ""
            st.session_state[f'f_cat_text_input_lane_{classification}'] = ""
            st.session_state[f'f_price_{classification}'] = ""
            st.session_state['drink_val_8_text_final'] = ""
            st.session_state['drink_val_12_text_final'] = ""
            st.session_state['drink_val_16_text_final'] = ""
            st.session_state['drink_use_8_final'] = False
            st.session_state['drink_use_12_final'] = True
            st.session_state['drink_use_16_final'] = True
            st.session_state[f'starting_stock_{classification}'] = 0
            st.session_state.clear_product_form = False

        size_prices = {}
        price = 0.0
        drink_category_suffix = ""
        drink_config_error = None

        def read_drink_price(raw_value, size_label):
            if not raw_value:
                raise ValueError(f"Please enter the price for {size_label}.")
            try:
                parsed_value = float(raw_value.replace('₱', '').replace(',', '').strip())
            except ValueError:
                raise ValueError(f"Invalid price for {size_label}. Enter a valid numerical amount.")
            if parsed_value <= 0:
                raise ValueError(f"The price for {size_label} must be greater than ₱0.00.")
            return parsed_value

        # --- BALANCED 2-COLUMN BENTO CARDS ---
        add_left, add_right = st.columns([1, 1.15], gap="medium")

        with add_left:
            with st.container(key='bento_form_left'):
                st.markdown("**1. Product Information**")
                name = st.text_input('Product name *', placeholder='Enter product name', key=f'f_name_{classification}').strip()
                category = st.text_input('Category *', placeholder="e.g., Waffle, Streetfood, Milktea...", key=f'f_cat_text_input_lane_{classification}').strip()

                st.markdown("**2. Inventory Settings**")
                inv_c1, inv_c2 = st.columns(2, gap="small")
                with inv_c1:
                    low_stock_threshold = st.number_input('Low-stock alert at', min_value=0, value=5, step=1)
                with inv_c2:
                    high_stock_threshold = st.number_input('High-stock alert at', min_value=0, value=50, step=1)

        with add_right:
            with st.container(key='bento_form_right'):
                if classification in ['Foods (Grubs)', 'Others (Combo/Meal Plan)']:
                    st.markdown("**3. Product Pricing**")
                    price_input = st.text_input('Product Price (₱) *', placeholder='0.00', key=f'f_price_{classification}').strip()
                    price = parse_and_format_price(price_input)
                    st.caption("Flat unit price for food items, snacks, or combo meals.")

                elif classification == 'Drinks (Gulps)':
                    st.markdown("**3. Cup Size & Base Pricing**")
                    price8 = price12 = price16 = 0.00
                    col8, col12, col16 = st.columns(3, gap="small")
                    with col8:
                        use8 = st.checkbox('Offer 8 oz', value=False, key='drink_use_8_final')
                        price8_input = st.text_input('8 oz (₱) *', placeholder='0.00', key='drink_val_8_text_final').strip() if use8 else ""
                        price8 = parse_and_format_price(price8_input) if use8 else 0.00
                    with col12:
                        use12 = st.checkbox('Offer 12 oz', value=True, key='drink_use_12_final')
                        price12_input = st.text_input('12 oz (₱) *', placeholder='0.00', key='drink_val_12_text_final').strip() if use12 else ""
                        price12 = parse_and_format_price(price12_input) if use12 else 0.00
                    with col16:
                        use16 = st.checkbox('Offer 16 oz', value=True, key='drink_use_16_final')
                        price16_input = st.text_input('16 oz (₱) *', placeholder='0.00', key='drink_val_16_text_final').strip() if use16 else ""
                        price16 = parse_and_format_price(price16_input) if use16 else 0.00

                    # Inline header + "+ Add size" button on the same row to save vertical space
                    cs_hdr, cs_btn = st.columns([2, 1], vertical_alignment='center', gap='small')
                    with cs_hdr:
                        st.markdown("**Custom Sizing (Optional)**")
                    with cs_btn:
                        if st.button("+ Add size", key="add_another_custom_size_btn", use_container_width=True):
                            st.session_state.custom_sizes_count = st.session_state.get("custom_sizes_count", 1) + 1
                            st.rerun()

                    if "custom_sizes_count" not in st.session_state:
                        st.session_state.custom_sizes_count = 1

                    custom_size_inputs_list = []
                    # Internal fixed-height scroll container (height=92) so adding 3+ sizes NEVER scrolls the page
                    with st.container(height=92, border=False):
                        for i in range(st.session_state.custom_sizes_count):
                            c_size_col, c_price_col = st.columns([1.4, 1], gap="small")
                            with c_size_col:
                                lbl_val = st.text_input(f'Label #{i+1}', placeholder='e.g., 22oz, 1-Liter', key=f'drink_lbl_custom_reactive_field_{i}', label_visibility="collapsed").strip()
                            with c_price_col:
                                prc_val = st.text_input(f'Price #{i+1}', placeholder='Price (₱)', key=f'drink_val_custom_text_reactive_{i}', label_visibility="collapsed").strip()
                            custom_size_inputs_list.append({"label": lbl_val, "price_raw": prc_val})

                    try:
                        size_prices = {}
                        if use8:
                            price8 = read_drink_price(price8_input, "8 oz")
                            size_prices.update({8: cents_from_peso(price8)})
                        if use12:
                            price12 = read_drink_price(price12_input, "12 oz")
                            size_prices.update({12: cents_from_peso(price12)})
                        if use16:
                            price16 = read_drink_price(price16_input, "16 oz")
                            size_prices.update({16: cents_from_peso(price16)})

                        custom_labels_compiled = []
                        custom_database_key_id = 99
                        for idx, entry in enumerate(custom_size_inputs_list):
                            c_label = entry["label"]
                            c_price_raw = entry["price_raw"]
                            if c_label or c_price_raw:
                                if not c_label:
                                    raise ValueError(f"Please enter a description label for Custom Size #{idx + 1}.")
                                parsed_c_price = read_drink_price(c_price_raw, f"custom size '{c_label}'")
                                size_prices.update({custom_database_key_id: cents_from_peso(parsed_c_price)})
                                custom_labels_compiled.append(c_label)
                                custom_database_key_id += 1
                        if custom_labels_compiled:
                            drink_category_suffix = f" | Custom:{', '.join(custom_labels_compiled)}"

                    except ValueError as exc:
                        drink_config_error = str(exc)

        submit_form_btn = st.button('Add product to Catalog', type='primary', use_container_width=True, key=f'add_product_button_{classification}')

        if submit_form_btn:
            def to_sentence_case(text):
                if not text: return ""
                words = [word.strip().capitalize() for word in text.split() if word.strip()]
                return " ".join(words)

            def has_consecutive_repetitions(text, max_allowed=3):
                if not text: return False
                count = 1
                for i in range(1, len(text)):
                    if text[i] == text[i-1] and text[i].isalnum():
                        count += 1
                        if count > max_allowed: return True
                    else: count = 1
                return False

            def looks_like_gibberish(text):
                words = [w for w in text.split() if w.isalpha()]
                if not words:
                    return False
                vowels = set("aeiou")
                for word in words:
                    if len(word) >= 5 and not any(char in vowels for char in word): return True
                return False

            clean_name = to_sentence_case(name)
            clean_category = to_sentence_case(category)
            final_save_category = f"{clean_category}{drink_category_suffix}" if classification == 'Drinks (Gulps)' else clean_category

            name_audit = clean_name.lower()
            category_audit = clean_category.lower()
            combined_audit = f"{name_audit} {category_audit}"

            food_dictionary = [
                'food', 'snack', 'grub', 'fry', 'fries', 'potato', 'burger', 'sandwich', 'bun', 'bread',
                'waffle', 'donut', 'doughnut', 'cake', 'pastry', 'cookie', 'pie', 'sweet', 'dessert',
                'crepe', 'rice', 'meal', 'combo', 'box', 'platter', 'bucket', 'chicken', 'wings', 'pork',
                'beef', 'meat', 'fish', 'seafood', 'sauce', 'dip', 'bbq', 'cheese', 'street', 'grill',
                'bacon', 'egg', 'noodles', 'soup', 'pasta', 'salad', 'kikiam', 'lumpia', 'siomai', 'balls'
            ]
            drink_dictionary = [
                'tea', 'milk', 'coffee', 'juice', 'shake', 'smoothie', 'soda', 'cola', 'drink', 'beverage',
                'gulp', 'water', 'brew', 'ice', 'syrup', 'slush', 'frappe', 'float', 'latte', 'milktea',
                'milkshake', 'slushie', 'macchiato', 'espresso', 'capuccino', 'lemonade', 'soda', 'pop', 'fruit tea',
            ]
            prohibited_keywords = ['person', 'human', 'people', 'teacher', 'student', 'animal', 'object', 'thing']

            try:
                existing_product_names = [str(item['name']).lower().strip() for item in db.list_products(active_only=True)]
            except Exception:
                existing_product_names = []

            is_spam_text = has_consecutive_repetitions(combined_audit, max_allowed=3)
            is_nonsense_word = looks_like_gibberish(combined_audit)
            contains_junk = any(junk in combined_audit for junk in prohibited_keywords)

            if classification == 'Drinks (Gulps)':
                is_valid_context = any(word in category_audit for word in drink_dictionary)
                mismatch_error = f"Selected 'Drinks (Gulps)' but entered a non-beverage category '{category}'."
            elif classification == 'Foods (Grubs)':
                has_drink_trigger_in_food = any(word in category_audit for word in drink_dictionary) or any(word in name_audit for word in drink_dictionary)
                is_valid_context = any(word in category_audit for word in food_dictionary) and not has_drink_trigger_in_food
                mismatch_error = f"Selected 'Foods (Grubs)' but entered a drink or non-food layout configuration."
            else:
                is_valid_context = any(word in combined_audit for word in food_dictionary + drink_dictionary)
                mismatch_error = "Entered an invalid combo meal category context description."

            if clean_name and name_audit in existing_product_names:
                st.error(f"Catalog Conflict: A product named '{clean_name}' already exists in your store inventory.")
            elif not clean_name:
                st.error("Product name is required.")
            elif not clean_category:
                st.error("Category structure specification is required.")
            elif is_spam_text or is_nonsense_word:
                st.error("Invalid Entry: Input contains keyboard spam or gibberish text patterns.")
            elif contains_junk:
                st.error("Context Validation Alert: Junk classifications (person, human, object) are strictly blocked.")
            elif not is_valid_context:
                st.error(f"Context/Classification Mismatch: {mismatch_error} Please allocate your item correctly.")
            elif classification in ['Foods (Grubs)', 'Others (Combo/Meal Plan)'] and price <= 0.0:
                st.error("Validation Error: Price field is required and must be greater than ₱0.00.")
            elif classification == 'Drinks (Gulps)' and drink_config_error:
                st.error(f"Validation Error: {drink_config_error}")
            elif classification == 'Drinks (Gulps)' and not size_prices:
                st.error("Validation Error: Enable and configure at least one drink size.")
            else:
                try:
                    price_cents = cents_from_peso(price) if classification != 'Drinks (Gulps)' else 0
                    starting_stock = 0

                    all_existing_products = db.list_products(active_only=False)
                    if classification == 'Drinks (Gulps)':
                        prefix = "GLP"
                    elif classification == 'Others (Combo/Meal Plan)':
                        prefix = "CMB"
                    else:
                        prefix = "GRB"

                    existing_numbers = []
                    for prod in all_existing_products:
                        code_str = str(prod.get('code', ''))
                        if code_str.startswith(f"{prefix}-"):
                            suffix = code_str.removeprefix(f"{prefix}-")
                            if suffix.isdigit():
                                existing_numbers.append(int(suffix))

                    next_code_number = max(existing_numbers) + 1 if existing_numbers else 1001

                    while True:
                        generated_code = f"{prefix}-{next_code_number}"
                        with db.connection() as conn:
                            conn.row_factory = sqlite3.Row
                            collision_check = conn.execute("SELECT 1 FROM products WHERE UPPER(code) = UPPER(?)", (generated_code,)).fetchone()
                        if not collision_check:
                            break
                        next_code_number += 1

                    db.add_product(
                        code=generated_code,
                        name=clean_name,
                        category=final_save_category,
                        price_cents=price_cents,
                        stock=starting_stock,
                        threshold=low_stock_threshold,
                        size_prices=size_prices if classification == 'Drinks (Gulps)' else None
                    )
                    audit_msg = f"Menu product item '{clean_name}' successfully added to store catalog database! Assigned code: '{generated_code}' under active category grouping: '{final_save_category}'."
                    st.session_state.global_toast = {
                        "msg": f"SUCCESS: Product '{clean_name}' added to catalog as code '{generated_code}'.",
                        "bg": "#2e7d32",
                        "icon": "[OK]"
                    }
                    db.log_activity('Admin', 'Product Created', f"{generated_code} · {clean_name}")
                    logging.info(f"TRANSACTION SUCCESS [ADMIN]: {audit_msg}")

                    st.session_state.clear_product_form = True
                    st.session_state.custom_sizes_count = 1
                    st.rerun()
                except Exception as e:
                    safe_error(e)

    # EDIT / DELETE TAB (2-Column Bento Layout + Collapsible Danger Zone)
    with tab2:
        all_products = db.list_products(active_only=False)
        if not all_products:
            st.info("No active products available to edit.")
        else:
            labels = {(f"{prod['code']} — {prod['name']} {'(Inactive)' if not prod['active'] else ''}"): prod for prod in all_products}
            selected_label = st.selectbox('Select product to modify', list(labels.keys()), key='edit_select', label_visibility="collapsed")
            p = labels[selected_label]
            if p['active']:
                current_sizes = db.get_product_sizes(p['id'])
                orig_category = p['category']
                is_custom_drink = " | Custom:" in orig_category
                if is_custom_drink:
                    base_cat_name, custom_sz_label = orig_category.split(" | Custom:", 1)
                else:
                    base_cat_name = orig_category
                    custom_sz_label = ""
                is_a_drink = is_custom_drink or any(
                    d in base_cat_name.lower()
                    for d in ['milkshake', 'float', 'milktea', 'drink', 'coffee', 'juice', 'beverage', 'tea', 'gulp', 'fruit tea']
                )
                edit_left, edit_right = st.columns([1, 1.15], gap="medium")
                # LEFT CARD: Product Details & Threshold
                with edit_left:
                    with st.container(key='bento_edit_left'):
                        st.markdown("**1. Product Details**")
                        ec1, ec2 = st.columns((1, 1.6), gap="small")
                        ec1.text_input('Code', value=p['code'], disabled=True)
                        new_name = ec2.text_input('Product name', value=p['name'], key=f"edit_name_field_{p['id']}").strip()

                        cat_col, low_col, high_col = st.columns((1.4, 1, 1), gap="small")
                        with cat_col:
                            if is_a_drink:
                                new_base_cat = st.text_input('Category Name *', value=base_cat_name, key=f"edit_base_cat_field_{p['id']}").strip()
                            else:
                                new_base_cat = st.text_input('Category Name *', value=p['category'], key=f"edit_cat_food_{p['id']}").strip()
                        with low_col:
                            new_threshold = st.number_input('Low-stock alert', min_value=0, max_value=1000000, value=int(p.get('low_stock_threshold', 5)), step=1, key=f"edit_thresh_{p['id']}")
                        with high_col:
                            new_high_threshold = st.number_input('High-stock alert', min_value=0, max_value=1000000, value=int(p.get('high_stock_threshold', 50)), step=1, key=f"edit_high_thresh_{p['id']}")

                        # Save Button & Danger Zone moved inside Left Card
                        save_changes = st.button('Save All Product Details', type='primary', use_container_width=True, key=f"unified_save_btn_{p['id']}")
                        
                        with st.expander("Danger Zone (Permanent Delete)"):
                            dz_c1, dz_c2 = st.columns(2, gap="small")
                            with dz_c1:
                                check_step1 = st.checkbox("Confirm delete", key=f"force_del_c1_{p['id']}")
                            with dz_c2:
                                check_step2 = st.checkbox("Remove from logs", key=f"force_del_c2_{p['id']}")
                            if st.button('Permanently Delete', key=f"hard_purge_action_{p['id']}", type='primary', use_container_width=True, disabled=not (check_step1 and check_step2)):
                                try:
                                    success, msg = db.delete_product(p['id'])
                                    if success:
                                        st.session_state.global_toast = {
                                            "msg": f"PURGE REMOVAL: Product '{p['code']}' has been permanently deleted from the catalog.",
                                            "bg": "#c62828",
                                            "icon": "[!]"
                                        }
                                        db.log_activity('Admin', 'Product Deleted', f"{p['code']} · {p['name']}")
                                        st.rerun()
                                    else:
                                        st.error(msg)
                                except Exception as e:
                                    safe_error(e)

                # RIGHT CARD: Pricing & Sizes
                with edit_right:
                    with st.container(key='bento_edit_right'):
                        st.markdown("**2. Pricing & Sizing**")
                        size_inputs = {}
                        if is_a_drink:
                            all_possible_sizes = [8, 12, 16]
                            size_cols = st.columns(len(all_possible_sizes), gap="small")
                            for size_idx, size in enumerate(all_possible_sizes):
                                existing_price_cents = current_sizes.get(size, 0)
                                if not current_sizes and size in (12, 16):
                                    existing_price_cents = p.get('price_cents', 0)
                                initial_value = float(existing_price_cents) / 100.0
                                size_inputs[size] = size_cols[size_idx].number_input(
                                    f'{size} oz (₱)',
                                    min_value=0.0,
                                    value=initial_value,
                                    step=1.0,
                                    format="%.2f",
                                    key=f"edit_price_{p['code']}_{size}"
                                )
                            custom_sizes_in_db = {sz: cents for sz, cents in current_sizes.items() if int(sz) >= 99}
                            custom_labels_array = [lbl.strip() for lbl in orig_category.split(" | Custom:", 1)[1].split(",")] if " | Custom:" in orig_category else []
                            total_slots_to_render = max(len(custom_labels_array), len(custom_sizes_in_db))
                            if f"edit_custom_count_{p['id']}" in st.session_state:
                                total_slots_to_render = max(total_slots_to_render, st.session_state[f"edit_custom_count_{p['id']}"])
                            else:
                                st.session_state[f"edit_custom_count_{p['id']}"] = total_slots_to_render
                            edit_custom_inputs = []
                            has_any_active_data = False
                            for i in range(st.session_state[f"edit_custom_count_{p['id']}"]):
                                associated_db_key = 99 + i
                                if not st.session_state.get(f"delete_custom_{p['id']}_{associated_db_key}", False):
                                    saved_lbl = custom_labels_array[i] if i < len(custom_labels_array) else ""
                                    if saved_lbl or st.session_state.get(f"edit_lbl_cust_dbkey_{p['id']}_{associated_db_key}"):
                                        has_any_active_data = True
                                        break
                            if not has_any_active_data and len(custom_sizes_in_db) == 0:
                                st.session_state[f"edit_custom_count_{p['id']}"] = 1
                            for i in range(st.session_state[f"edit_custom_count_{p['id']}"]):
                                associated_db_key = 99 + i
                                if st.session_state.get(f"delete_custom_{p['id']}_{associated_db_key}", False):
                                    continue

                                default_label = custom_labels_array[i] if i < len(custom_labels_array) else ""
                                default_price = float(custom_sizes_in_db.get(associated_db_key, 0.0)) / 100.0
                                ec_col1, ec_col2, ec_col3 = st.columns([2, 1.5, 1], gap="small")
                                with ec_col1:
                                    lbl_val = ec_col1.text_input("Label", value=default_label, placeholder="e.g., 22oz", key=f"edit_lbl_cust_dbkey_{p['id']}_{associated_db_key}", label_visibility="collapsed").strip()
                                with ec_col2:
                                    prc_val = ec_col2.number_input("Price", min_value=0.0, value=default_price, step=1.0, format='%.2f', key=f"edit_val_cust_dbkey_{p['id']}_{associated_db_key}", label_visibility="collapsed")
                                with ec_col3:
                                    if ec_col3.button("Remove", key=f"remove_custom_size_row_dbkey_{p['id']}_{associated_db_key}", use_container_width=True):
                                        st.session_state[f"delete_custom_{p['id']}_{associated_db_key}"] = True
                                        if f"edit_lbl_cust_dbkey_{p['id']}_{associated_db_key}" in st.session_state:
                                            del st.session_state[f"edit_lbl_cust_dbkey_{p['id']}_{associated_db_key}"]
                                        st.rerun()
                                if lbl_val or prc_val > 0:
                                    edit_custom_inputs.append({"label": lbl_val, "price": prc_val})
                            if st.button("+ Add custom size", key=f"edit_add_more_sizes_btn_{p['id']}"):
                                st.session_state[f"edit_custom_count_{p['id']}"] += 1
                                st.rerun()
                            updated_sizes = {int(sz): cents_from_peso(pr_val) for sz, pr_val in size_inputs.items() if float(pr_val) > 0.0}
                            compiled_edit_labels = []
                            edit_db_key_id = 99
                            for entry in edit_custom_inputs:
                                if entry["label"] and entry["price"] > 0:
                                    updated_sizes[edit_db_key_id] = cents_from_peso(entry["price"])
                                    compiled_edit_labels.append(entry["label"])
                                    edit_db_key_id += 1
                            new_cat = f"{new_base_cat} | Custom:{', '.join(compiled_edit_labels)}" if compiled_edit_labels else new_base_cat
                            new_base_price_cents = next(iter(updated_sizes.values())) if updated_sizes else p['price_cents']
                        else:
                            new_cat = new_base_cat
                            new_price_val = st.number_input('Price (₱)', min_value=0.0, value=float(p['price_cents'] / 100), step=5.0, format='%.2f', key=f"edit_price_food_{p['id']}")
                            new_base_price_cents = cents_from_peso(new_price_val)
                            updated_sizes = None

                if save_changes:
                    if not new_name or not new_cat:
                        st.error("Product name and category definitions cannot be left blank.")
                    else:
                        success_trigger = False
                        try:
                            with db.connection() as save_conn:
                                save_conn.execute("""
                                    UPDATE products
                                    SET name = ?, category = ?, price_cents = ?, low_stock_threshold = ?, updated_at = ?
                                    WHERE id = ?
                                """, (new_name, new_cat, int(new_base_price_cents), int(new_threshold), datetime.now().isoformat(), p['id']))
                            if is_a_drink:
                                with db.connection() as clear_conn:
                                    clear_conn.execute("DELETE FROM product_sizes WHERE product_id = ?", (p['id'],))
                                    if updated_sizes:
                                        for size_key, cents_val in updated_sizes.items():
                                            clear_conn.execute("INSERT INTO product_sizes (product_id, size_oz, price_cents) VALUES (?, ?, ?)", (p['id'], int(size_key), int(cents_val)))
                            else:
                                with db.connection() as clean_conn:
                                    clean_conn.execute("DELETE FROM product_sizes WHERE product_id = ?", (p['id'],))
                            st.session_state.global_toast = {
                                "msg": f"UPDATE SUCCESS: Product details for '{p['code']}' have been updated.",
                                "bg": "#1565c0",
                                "icon": "[UPDATED]"
                            }
                            db.log_activity('Admin', 'Product Updated', f"{p['code']} · {new_name}")
                            success_trigger = True
                        except Exception as e:
                            safe_error(e)
                        if success_trigger:
                            st.rerun()

    # VIEW CATALOG TAB
    with tab3:
        with st.container(key='bento_catalog_card'):
            all_products = db.list_products(active_only=False)
            if not all_products:
                st.info("No products found in the catalog.")
            else:
                # Single clean filter toolbar row (no extra subheader or divider)
                f_search, f_cat, f_sort = st.columns([2, 1.2, 1.2], gap="small")
                with f_search:
                    search_q = st.text_input(
                        'Search',
                        placeholder='Search by code or product name...',
                        key='cat_search_input',
                        label_visibility='collapsed'
                    ).strip().lower()

                categories = sorted(list({
                    p['category'].partition(" | Custom:")[0].strip()
                    for p in all_products if p.get('category')
                }))
                with f_cat:
                    selected_cat = st.selectbox(
                        'Category',
                        ['All Categories'] + categories,
                        key='cat_filter_select',
                        label_visibility='collapsed'
                    )

                with f_sort:
                    sort_option = st.selectbox(
                        'Sort By',
                        ['Product Name (A-Z)', 'Product Name (Z-A)', 'Stock (Low to High)', 'Stock (High to Low)', 'Code'],
                        key='cat_sort_select',
                        label_visibility='collapsed'
                    )

                # Filter & Sort Logic
                filtered = []
                for p in all_products:
                    clean_cat = p['category'].partition(" | Custom:")[0].strip() if p.get('category') else ""
                    if selected_cat != 'All Categories' and clean_cat != selected_cat:
                        continue
                    if search_q and (search_q not in p['name'].lower() and search_q not in p['code'].lower()):
                        continue

                    # Format multi-size prices cleanly without truncation
                    sizes = db.get_product_sizes(p['id'])
                    if sizes:
                        custom_lbls = [lbl.strip() for lbl in p['category'].partition(" | Custom:")[2].split(",")] if " | Custom:" in p['category'] else []
                        price_parts = []
                        for sz_key in sorted(sizes.keys()):
                            if int(sz_key) < 99:
                                price_parts.append(f"{sz_key}oz: {money(sizes[sz_key])}")
                            else:
                                idx = int(sz_key) - 99
                                lbl = custom_lbls[idx] if idx < len(custom_lbls) and custom_lbls[idx] else "Custom"
                                price_parts.append(f"{lbl}: {money(sizes[sz_key])}")
                        price_display = "  |  ".join(price_parts)
                    else:
                        price_display = money(p['price_cents'])

                    filtered.append({
                        'Code': p['code'],
                        'Product': p['name'],
                        'Category': clean_cat,
                        'Price': price_display,
                        'Stock': int(p['stock']),
                        'Min Alert': int(p.get('low_stock_threshold', 5)),
                        'Status': 'Active' if p['active'] else 'Inactive'
                    })

                if sort_option == 'Product Name (A-Z)':
                    filtered.sort(key=lambda x: x['Product'].lower())
                elif sort_option == 'Product Name (Z-A)':
                    filtered.sort(key=lambda x: x['Product'].lower(), reverse=True)
                elif sort_option == 'Stock (Low to High)':
                    filtered.sort(key=lambda x: x['Stock'])
                elif sort_option == 'Stock (High to Low)':
                    filtered.sort(key=lambda x: x['Stock'], reverse=True)
                elif sort_option == 'Code':
                    filtered.sort(key=lambda x: x['Code'])

                if filtered:
                    st.dataframe(
                        pd.DataFrame(filtered),
                        use_container_width=True,
                        hide_index=True,
                        height=340,
                        column_config={
                            "Code": st.column_config.TextColumn("Code", width="small"),
                            "Product": st.column_config.TextColumn("Product", width="medium"),
                            "Category": st.column_config.TextColumn("Category", width="small"),
                            "Price": st.column_config.TextColumn("Price", width="large"),
                            "Stock": st.column_config.NumberColumn("Stock", width="small", format="%d"),
                            "Min Alert": st.column_config.NumberColumn("Min Alert", width="small", format="%d"),
                            "Status": st.column_config.TextColumn("Status", width="small"),
                        }
                    )
                else:
                    st.info("No products match your current filter.")

elif mode == 'Admin' and page == 'Sales History':
    st.markdown ('### Sales History')
    today = ph_today()
    t_dates, t_kpi, t_export = st.columns([2.1, 1.35, 0.32], vertical_alignment='center', gap='small')

    with t_dates:
        with st.container(key='bento_sales_dates'):
            d1, d2 = st.columns(2, gap='small')
            with d1:
                start_d = st.date_input('From date', value=today - timedelta(days=30), key='admin_sales_from')
            with d2:
                end_d = st.date_input('To date', value=today, key='admin_sales_to')

    start_iso = datetime.combine(start_d, time.min).isoformat()
    end_iso = datetime.combine(end_d + timedelta(days=1), time.min).isoformat()

    all_tx = db.transaction_history()
    filtered_tx = [tx for tx in all_tx if start_iso <= tx['created_at'] < end_iso]
    total_rev_cents = sum(tx['total_cents'] for tx in filtered_tx)

    with t_kpi:
        with st.container(key='bento_sales_kpi'):
            st.metric(f"Period Revenue ({len(filtered_tx)} sales)", money(total_rev_cents))

    with t_export:
        with st.container(key='bento_sales_dl'):
            if filtered_tx:
                csv_df = pd.DataFrame([
                    {
                        'Sale #': r['id'],
                        'Date/time': r['created_at'].replace('T', ' ')[:16],
                        'Cashier': r.get('cashier', 'Cashier'),
                        'Total (PHP)': r['total_cents'] / 100.0
                    }
                    for r in filtered_tx
                ])
                st.download_button(
                    "",
                    icon=":material/download:",
                    help="Download filtered sales CSV",
                    data=csv_df.to_csv(index=False).encode('utf-8'),
                    file_name=f"gulps_grubs_sales_{start_d}_to_{end_d}.csv",
                    mime='text/csv',
                    type='primary'
                )
            else:
                st.button("", icon=":material/download:", help="No sales to export", disabled=True)

    if not filtered_tx:
        st.info('No sales recorded in this date range.')
    else:
        # ROW 2: 2-Column Master-Detail Bento Grid (Left: Sales Transactions | Right: Inspect Receipt)
        left_tx, right_detail = st.columns([1, 1.15], gap='medium')

        with left_tx:
            with st.container(key='bento_sales_list'):
                st.markdown('**Sales Transactions**')
                tx_rows = [
                    {
                        'Sale #': f"Sale #{r['id']}",
                        'Date/time': r['created_at'].replace('T', ' ')[:16],
                        'Cashier': r.get('cashier', 'Cashier'),
                        'Total': money(r['total_cents'])
                    }
                    for r in filtered_tx
                ]
                st.dataframe(
                    pd.DataFrame(tx_rows),
                    use_container_width=True,
                    hide_index=True,
                    height=315,
                    column_config={
                        "Sale #": st.column_config.TextColumn("Sale #", width="small"),
                        "Date/time": st.column_config.TextColumn("Date/time", width="medium"),
                        "Cashier": st.column_config.TextColumn("Cashier", width="small"),
                        "Total": st.column_config.TextColumn("Total", width="small"),
                    }
                )

        with right_detail:
            with st.container(key='bento_sales_detail', border=True):
                st.markdown('**Inspect receipt**')
                sale_options = {
                    f"Sale #{r['id']}  —  {r['created_at'].replace('T', ' ')[:16]}  ({money(r['total_cents'])})": r
                    for r in filtered_tx
                }
                selected_sale_lbl = st.selectbox(
                    'Inspect receipt',
                    list(sale_options.keys()),
                    key='admin_sales_detail_select',
                    label_visibility='collapsed'
                )
                chosen_tx = sale_options[selected_sale_lbl]

                with db.connection() as conn:
                    conn.row_factory = sqlite3.Row
                    tables = [r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                    items_table = next((t for t in tables if 'item' in t.lower()), 'sale_items')
                    fk_col = 'transaction_id' if 'transaction' in items_table.lower() else 'sale_id'

                    items = conn.execute(f"""
                        SELECT si.*, p.code, p.name AS product_name, p.category
                        FROM {items_table} si
                        LEFT JOIN products p ON si.product_id = p.id
                        WHERE si.{fk_col} = ?
                    """, (chosen_tx['id'],)).fetchall()

                detail_rows = []
                for raw_item in items:
                    item = dict(raw_item)
                    sz = item.get('size_oz')
                    cat_str = item.get('category') or ''
                    if sz and int(sz) >= 99:
                        _, _, custom_part = cat_str.partition(" | Custom:")
                        custom_lbls = [l.strip() for l in custom_part.split(",")] if custom_part else []
                        idx = int(sz) - 99
                        size_display = next((lbl for i, lbl in enumerate(custom_lbls) if i == idx and lbl), "Custom")
                    elif sz and int(sz) > 0:
                        size_display = f"{sz} oz"
                    else:
                        size_display = "—"

                    qty_val = item.get('qty') if item.get('qty') is not None else item.get('quantity', 1)
                    unit_cents = item.get('unit_price_cents') if item.get('unit_price_cents') is not None else item.get('price_cents', 0)
                    sub_cents = item.get('subtotal_cents') if item.get('subtotal_cents') is not None else (int(qty_val) * int(unit_cents))

                    detail_rows.append({
                        'Code': item.get('code') or '—',
                        'Product': item.get('product_name') or item.get('name') or 'Item',
                        'Size': size_display,
                        'Qty': int(qty_val),
                        'Subtotal': money(sub_cents)
                    })

                st.dataframe(
                    pd.DataFrame(detail_rows),
                    use_container_width=True,
                    hide_index=True,
                    height=242,
                    column_config={
                        "Code": st.column_config.TextColumn("Code", width="small"),
                        "Product": st.column_config.TextColumn("Product", width="medium"),
                        "Size": st.column_config.TextColumn("Size", width="small"),
                        "Qty": st.column_config.NumberColumn("Qty", width="small", format="%d"),
                        "Subtotal": st.column_config.TextColumn("Subtotal", width="small"),
                    }
                )
                st.caption(f"Receipt Total: **{money(chosen_tx['total_cents'])}**  ·  Processed by **{chosen_tx.get('cashier', 'Cashier')}**")

elif mode == 'Admin' and page == 'Activity History':
    with st.container(key='bento_activity_card'):
        # Single clean top row: Title | Mode Filter | Search | Circular Download Icon
        hdr_c, mode_c, search_c, dl_c = st.columns((1.1, 0.9, 1.8, 0.3), vertical_alignment='center', gap='small')
        with hdr_c:
            st.markdown('##### Activity History')
        with mode_c:
            mode_filter = st.selectbox(
                'Mode',
                ('All', 'Admin', 'Cashier', 'Inventory Manager'),
                key='act_mode_filter',
                label_visibility='collapsed'
            )
        with search_c:
            act_search = st.text_input(
                'Search',
                placeholder='Search product, order #, sale #, action...',
                key='act_search_input',
                label_visibility='collapsed'
            ).strip().lower()

        logs = db.activity_history() if hasattr(db, 'activity_history') else []
        filtered_logs = []
        for row in logs:
            r = dict(row)
            # Automatically find whichever column holds the role/mode ('Admin', 'Cashier', 'Inventory Manager')
            r_mode = next(
                (
                    str(v) for k, v in r.items()
                    if k not in ('id', 'created_at', 'timestamp', 'action', 'details')
                    and v in ('Admin', 'Cashier', 'Inventory Manager')
                ),
                next((str(v) for k, v in r.items() if k not in ('id', 'created_at', 'timestamp', 'action', 'details') and v), '')
            )
            r_action = r.get('action') or ''
            r_details = r.get('details') or ''
            r_time = str(r.get('created_at') or r.get('timestamp') or '').replace('T', ' ')[:16]

            if mode_filter != 'All' and r_mode != mode_filter:
                continue
            if act_search and act_search not in f"{r_mode} {r_action} {r_details}".lower():
                continue

            filtered_logs.append({
                'Date/time': r_time,
                'Mode': r_mode,
                'Action': r_action,
                'Details': r_details
            })


        with dl_c:
            with st.container(key='bento_sales_dl'):
                if filtered_logs:
                    csv_data = pd.DataFrame(filtered_logs).to_csv(index=False).encode('utf-8')
                    st.download_button(
                        "",
                        icon=":material/download:",
                        help="Download activity history CSV",
                        data=csv_data,
                        file_name="gulps_grubs_activity_history.csv",
                        mime="text/csv",
                        type="primary"
                    )
                else:
                    st.button("", icon=":material/download:", help="No logs to export", disabled=True)

        if filtered_logs:
            st.dataframe(
                pd.DataFrame(filtered_logs),
                use_container_width=True,
                hide_index=True,
                height=365,
                column_config={
                    "Date/time": st.column_config.TextColumn("Date/time", width="small"),
                    "Mode": st.column_config.TextColumn("Mode", width="small"),
                    "Action": st.column_config.TextColumn("Action", width="small"),
                    "Details": st.column_config.TextColumn("Details", width="large"),
                }
            )
        else:
            st.info("No activity logs match your filter.")

# =========================================================================
# CASHIER WORKSPACE MODULES
# =========================================================================
elif mode == 'Cashier' and page == 'Dashboard':
    st.subheader('Cashier Shift Workspace Dashboard')
    today = ph_today()
    start = datetime.combine(today,time.min).isoformat()
    end = datetime.combine(today + timedelta(days=1),time.min).isoformat()
    shift_summary = db.sales_summary(start, end)
    recent_sales = db.transaction_history(start, end)[:5]
    try:
        with db.connection() as conn:
            pending_count_row = conn.execute("""SELECT COUNT(*) as total FROM pending_orders WHERE status = 'Pending'""").fetchone()
            pending_count = (pending_count_row['total'] if pending_count_row else 0)
    except Exception:
        pending_count = 0
    c_metric1, c_metric2, c_metric3 = st.columns(3)
    c_metric1.metric(label="My Today's Sales ",value=money(shift_summary['revenue_cents']),delta=f"{shift_summary['transactions']} Receipts printed today")
    c_metric2.metric(label="Active Kitchen Queue ",value=f"{pending_count} Orders",delta=("Queue heavy - Focus on speed" if pending_count > 5 else "Queue light / clear"),
                    delta_color="inverse" if pending_count > 5 else "normal")
    c_metric3.metric(label="Current Work Station",value="Cashier Desk #1",delta="System Connected & Online")
    st.markdown("####  Recent Shift Receipts")
    st.caption("A quick-reference scroll log of your last few completed checkouts:")
    if not recent_sales:
        st.info("No customer transactions have been recorded during your active shift window yet.")
    else:
        receipt_ledger = []
        for r in recent_sales:
            short_time = r['created_at'].replace('T', ' ')[:16]
            receipt_ledger.append({
                "Receipt #": f"TX-{r['id']}",
                "Timestamp": short_time,
                "Cashier Desk": r['cashier_label'],
                "Total Bill": money(r['total_cents'])
            })

        st.dataframe(pd.DataFrame(receipt_ledger),use_container_width=True,hide_index=True)


elif mode == 'Cashier' and page == 'New Sale':
    if 'cart' not in st.session_state or not isinstance(st.session_state.cart, list):
        st.session_state.cart = []

    all_products = [dict(p) for p in db.list_products(active_only=True)]

    # Standard Drink Sinkers / Add-ons (₱10.00 each)
    SINKER_OPTIONS = {
        "Pearls (₱10)": 1000,
        "Nata de Coco (₱10)": 1000,
        "Coffee Jelly (₱10)": 1000,
        "Cream Cheese (₱15)": 1500,
        "Oreo Crumbles (₱15)": 1500,
    }

    # 2-COLUMN BENTO POS WORKSPACE (Left: Available Products | Right: Shopping Cart & Checkout)
    pos_left, pos_right = st.columns((1.35, 1), gap='medium')

    # =========================================================
    # LEFT BENTO CARD: AVAILABLE PRODUCTS + SINKERS / CUSTOMIZE
    # =========================================================
    with pos_left:
        with st.container(key='bento_pos_menu', border=True):
            hdr_m, cat_m, search_m = st.columns((1.05, 1.45, 1.3), vertical_alignment='center', gap='small')
            with hdr_m:
                st.markdown("**Available Products**")
            with cat_m:
                cat_filter = st.segmented_control(
                    "Filter",
                    options=("All", "Foods", "Drinks", "Combos"),
                    default="All",
                    selection_mode="single",
                    label_visibility="collapsed",
                    width="stretch",
                    key="pos_cat_pills"
                )
                if not cat_filter:
                    cat_filter = "All"
            with search_m:
                pos_search = st.text_input(
                    "Search",
                    placeholder="Search name or code...",
                    key="pos_search_input",
                    label_visibility="collapsed"
                ).strip().lower()

            visible_products = []
            for p in all_products:
                code_upper = str(p.get('code', '')).upper()
                if cat_filter == "Foods" and not code_upper.startswith("GRB-"):
                    continue
                if cat_filter == "Drinks" and not code_upper.startswith("GLP-"):
                    continue
                if cat_filter == "Combos" and not code_upper.startswith("CMB-"):
                    continue
                if pos_search and (pos_search not in p['name'].lower() and pos_search not in code_upper.lower()):
                    continue
                visible_products.append(p)

            # Fixed-height internal scroll container (height=365) so page NEVER scrolls
            with st.container(height=365, border=False):
                if not visible_products:
                    st.info("No matching products found.")
                else:
                    cols_grid = st.columns(2, gap='small')
                    for idx, prod in enumerate(visible_products):
                        with cols_grid[idx % 2]:
                            with st.container(key=f"pos_item_card_{prod['id']}", border=True):
                                stk = int(prod.get('stock', 0))
                                sizes = db.get_product_sizes(prod['id'])
                                cat_str = prod.get('category') or ''
                                clean_cat, _, custom_part = cat_str.partition(" | Custom:")
                                clean_cat = clean_cat.strip()
                                is_drink_item = bool(sizes) or str(prod.get('code', '')).upper().startswith("GLP-")

                                st.markdown(f"**{prod['name']}**")
                                st.caption(f"{prod['code']} · {clean_cat} · Stock: {stk}")

                                if is_drink_item and sizes:
                                    custom_lbls = [l.strip() for l in custom_part.split(",")] if custom_part else []
                                    size_options = {}
                                    for sz_key in sorted(sizes.keys()):
                                        if int(sz_key) < 99:
                                            lbl = f"{sz_key} oz — {money(sizes[sz_key])}"
                                        else:
                                            c_idx = int(sz_key) - 99
                                            c_name = custom_lbls[c_idx] if c_idx < len(custom_lbls) and custom_lbls[c_idx] else "Custom"
                                            lbl = f"{c_name} — {money(sizes[sz_key])}"
                                        size_options[lbl] = (int(sz_key), int(sizes[sz_key]))

                                    s_col, b_col = st.columns((1.5, 1), vertical_alignment='center', gap='small')
                                    with s_col:
                                        chosen_sz_lbl = st.selectbox(
                                            "Size",
                                            list(size_options.keys()),
                                            key=f"pos_sz_sel_{prod['id']}",
                                            label_visibility="collapsed"
                                        )
                                    sz_id, base_unit_cents = size_options[chosen_sz_lbl]

                                    # Compact Customize Popover for Sinkers & Ice/Sugar Note
                                    with st.popover("Customize (Sinkers)", use_container_width=True):
                                        picked_sinkers = st.multiselect(
                                            "Add Sinkers / Toppings",
                                            options=list(SINKER_OPTIONS.keys()),
                                            key=f"pos_sinkers_{prod['id']}"
                                        )
                                        drink_note = st.text_input(
                                            "Ice / Sugar / Note",
                                            placeholder="e.g., Less ice, 50% sugar",
                                            key=f"pos_note_{prod['id']}"
                                        ).strip()

                                    sinkers_extra_cents = sum(SINKER_OPTIONS[s] for s in picked_sinkers)
                                    final_unit_cents = base_unit_cents + sinkers_extra_cents
                                    custom_parts = [s.split(" (") for s in picked_sinkers]
                                    if drink_note:
                                        custom_parts.append(drink_note)
                                    custom_summary = ", ".join(custom_parts)

                                    with b_col:
                                        if st.button("+ Add", key=f"pos_add_btn_{prod['id']}", type="primary", use_container_width=True, disabled=(stk <= 0)):
                                            existing = next(
                                                (
                                                    c for c in st.session_state.cart
                                                    if c['product_id'] == prod['id']
                                                    and c.get('size_oz') == sz_id
                                                    and c.get('customizations', '') == custom_summary
                                                ),
                                                None
                                            )
                                            if existing:
                                                if existing['quantity'] < stk:
                                                    existing['quantity'] += 1
                                                else:
                                                    st.warning(f"Only {stk} in stock.")
                                            else:
                                                sz_tag, _, _ = chosen_sz_lbl.partition(" — ")
                                                st.session_state.cart.append({
                                                    'product_id': prod['id'],
                                                    'code': prod['code'],
                                                    'name': prod['name'],
                                                    'size_oz': sz_id,
                                                    'size_label': sz_tag,
                                                    'customizations': custom_summary,
                                                    'unit_price_cents': final_unit_cents,
                                                    'quantity': 1
                                                })
                                            st.rerun()

                                else:
                                    unit_cents = int(prod.get('price_cents', 0))
                                    p_col, b_col = st.columns((1.5, 1), vertical_alignment='center', gap='small')
                                    with p_col:
                                        st.markdown(f"**{money(unit_cents)}**")

                                    with st.popover("Customize (Note)", use_container_width=True):
                                        food_note = st.text_input(
                                            "Special Request / Flavor",
                                            placeholder="e.g., Extra cheese, spicy, no mayo",
                                            key=f"pos_food_note_{prod['id']}"
                                        ).strip()

                                    with b_col:
                                        if st.button("+ Add", key=f"pos_add_btn_{prod['id']}", type="primary", use_container_width=True, disabled=(stk <= 0)):
                                            existing = next(
                                                (
                                                    c for c in st.session_state.cart 
                                                    if c['product_id'] == prod['id']
                                                    and not c.get('size_oz')
                                                    and c.get('customizations', '') == food_note
                                                ),
                                                None
                                            )
                                            if existing:
                                                if existing['quantity'] < stk:
                                                    existing['quantity'] += 1
                                                else:
                                                    st.warning(f"Only {stk} in stock.")
                                            else:
                                                st.session_state.cart.append({
                                                    'product_id': prod['id'],
                                                    'code': prod['code'],
                                                    'name': prod['name'],
                                                    'size_oz': None,
                                                    'size_label': '',
                                                    'customizations': food_note,
                                                    'unit_price_cents': unit_cents,
                                                    'quantity': 1
                                                })
                                            st.rerun()

    # =========================================================
    # RIGHT BENTO CARD: COMPACT SHOPPING CART & CHECKOUT
    # =========================================================
    with pos_right:
        with st.container(key='bento_pos_cart', border=True):
            c_hdr, c_clr = st.columns((2, 1), vertical_alignment='center', gap='small')
            with c_hdr:
                cart_items = st.session_state.cart if isinstance(st.session_state.cart, list) else []
                total_items = sum(int(i.get('quantity', 1)) for i in cart_items if isinstance(i, dict))
                st.markdown(f"**Shopping Cart ({total_items})**")
            with c_clr:
                if st.button("Clear", key="pos_clear_cart", use_container_width=True, disabled=(len(st.session_state.cart) == 0)):
                    st.session_state.cart.clear()
                    st.rerun()

            with st.container(height=185, border=False):
                if not st.session_state.cart:
                    st.info("Cart is empty. Click '+ Add' on a product to begin.")
                else:
                    for idx, item in enumerate(list(st.session_state.cart)):
                        sz_txt = f" ({item['size_label']})" if item.get('size_label') else ""
                        cust_txt = f" · _{item['customizations']}_" if item.get('customizations') else ""
                        line_sub = int(item['unit_price_cents']) * int(item['quantity'])
                        stock_limit = next((int(p['stock']) for p in all_products if p['id'] == item['product_id']), 999)

                        r_name, r_minus, r_qty, r_plus, r_price, r_del = st.columns((2.1, 0.45, 0.45, 0.45, 1.0, 0.45), vertical_alignment='center', gap='small')
                        with r_name:
                            st.markdown(f"**{item['name']}**{sz_txt}{cust_txt}")
                        with r_minus:
                            if st.button("-", key=f"cart_dec_{idx}", use_container_width=True):
                                if item['quantity'] > 1:
                                    item['quantity'] -= 1
                                else:
                                    st.session_state.cart.pop(idx)
                                st.rerun()
                        with r_qty:
                            st.markdown(f"<div style='text-align:center;font-weight:700;'>{item['quantity']}</div>", unsafe_allow_html=True)
                        with r_plus:
                            if st.button("+", key=f"cart_inc_{idx}", use_container_width=True, disabled=(item['quantity'] >= stock_limit)):
                                item['quantity'] += 1
                                st.rerun()
                        with r_price:
                            st.markdown(f"<div style='text-align:right;font-weight:700;'>{money(line_sub)}</div>", unsafe_allow_html=True)
                        with r_del:
                            if st.button("x", key=f"cart_rem_{idx}", use_container_width=True):
                                st.session_state.cart.pop(idx)
                                st.rerun()

            # Compact 3-Column Customer, Priority & Cashier Strip
            in1, in2, in3 = st.columns((1.3, 1.0, 1.0), gap='small')
            with in1:
                if st.session_state.pop("clear_pos_cust_name", False):
                    st.session_state["pos_cust_name"] = ""
                customer_name = st.text_input("Customer name *", placeholder="e.g. Juan", key="pos_cust_name")

            with in2:
                priority_level = st.selectbox(
                    "Priority",
                    options=(3, 2, 1),
                    format_func=lambda x: {1: "1 - Urgent", 2: "2 - High", 3: "3 - Normal"}[x],
                    key="pos_priority_sel"
                )
            with in3:
                cashier_name = st.text_input("Cashier", value="Cashier", key="pos_cashier_name")

            total_cents = sum(int(i['unit_price_cents']) * int(i['quantity']) for i in st.session_state.cart)

            # Total Bar + Confirm Sale Button pinned cleanly inside the card
            tot_c, btn_c = st.columns((1.1, 1.3), vertical_alignment='center', gap='small')
            with tot_c:
                st.markdown(
                    f"""
                    <div style="background:#f8f3eb; border:1px solid #e2d4c3; border-radius:10px; padding:6px 12px;">
                        <div style="font-size:0.72rem; color:#6b5255; font-weight:600;">Total Due</div>
                        <div style="font-size:1.15rem; font-weight:800; color:#4b1117;">{money(total_cents)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with btn_c:
                confirm_btn = st.button(
                    "Confirm Sale",
                    type="primary",
                    use_container_width=True,
                    disabled=(len(st.session_state.cart) == 0),
                    key="pos_confirm_sale_btn"
                )

            if confirm_btn:
                if not customer_name or not customer_name.strip():
                    st.warning("Customer name is required before confirming sale.")
                else:
                    try:
                        c_label = cashier_name.strip() or "Cashier"

                        # Build exact item payload expected by db.checkout()
                        checkout_payload = []
                        for item in st.session_state.cart:
                            qty = int(item['quantity'])
                            u_cents = int(item['unit_price_cents'])
                            checkout_payload.append({
                                'product_id': int(item['product_id']),
                                'name': item['name'],
                                'unit_price_cents': u_cents,
                                'quantity': qty,
                                'subtotal_cents': u_cents * qty,
                                'size_oz': int(item['size_oz']) if item.get('size_oz') is not None else None,
                                'customizations': item.get('customizations', '')
                            })

                        sale = db.checkout(items=checkout_payload, cashier_label=c_label)
                        st.session_state.last_sale = sale

                        order_details_list = []
                        for item in st.session_state.cart:
                            sz_suffix = f" ({item['size_label']})" if item.get('size_label') else ""
                            cust_suffix = f" [{item['customizations']}]" if item.get('customizations') else ""
                            order_details_list.append(f"{item['quantity']}x {item['name']}{sz_suffix}{cust_suffix}")

                        db.add_order(
                            customer_name=customer_name.strip(),
                            details=", ".join(order_details_list),
                            priority=int(priority_level)
                        )

                        sale_ref = sale.get('transaction_id', '')
                        sale_label = f"Sale #{sale_ref} · " if sale_ref else ""
                        db.log_activity('Cashier', 'Sale Completed', f"{sale_label}{customer_name.strip()} · {money(total_cents)}")

                        st.session_state.cart.clear()
                        st.session_state["clear_pos_cust_name"] = True
                        st.session_state.global_toast = {
                            "msg": f"SALE CONFIRMED: Order for '{customer_name.strip()}' recorded ({money(total_cents)}).",
                            "bg": "#2e7d32",
                            "icon": "[OK]"
                        }
                        st.rerun()
                    except Exception as e:
                        st.warning(str(e))


elif mode == 'Cashier' and page == 'Pickup Queue Priority':
    heap = rebuild_heap()
    next_order = heap.peek()
    pending_orders = db.list_orders(pending_only=True)

    q_left, q_right = st.columns((1, 1.45), gap='medium')

    # =========================================================
    # LEFT BENTO CARD: NEXT PRIORITY ORDER TO SERVE
    # =========================================================
    with q_left:
        with st.container(key='bento_queue_next', border=True):
            st.markdown("##### Next Priority Order")
            st.caption("Highest-priority ticket in the active pickup lane.")

            if next_order:
                p_map = {1: "1 - Urgent", 2: "2 - High", 3: "3 - Normal", 4: "4 - Low", 5: "5 - Lowest"}
                prio_label = p_map.get(int(next_order.priority), f"Level {next_order.priority}")

                st.markdown(
                    f"""
                    <div style="background:#fffcf7; border:1.5px solid #e2d4c3; border-left:5px solid #f58220; border-radius:12px; padding:14px 16px; margin:8px 0 14px 0;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                            <span style="font-size:1.1rem; font-weight:800; color:#4b1117;">Order #{next_order.order_id} — {next_order.payload['customer_name']}</span>
                            <span style="background:#f58220; color:#fff; font-size:0.75rem; font-weight:700; padding:3px 10px; border-radius:999px;">{prio_label}</span>
                        </div>
                        <div style="font-size:0.95rem; color:#3d2427; font-weight:600;">{next_order.payload['details']}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                if st.button('Mark Next Order Completed', type='primary', use_container_width=True, key='btn_complete_next_order'):
                    try:
                        db.update_order_status(next_order.order_id, 'Completed')
                        st.session_state.global_toast = {
                            "msg": f"QUEUE ACTION: Order #{next_order.order_id} for '{next_order.payload['customer_name']}' marked COMPLETED.",
                            "bg": "#1565c0",
                            "icon": "[OK]"
                        }
                        logging.info(f"Order #{next_order.order_id} marked complete.")
                        st.rerun()
                    except Exception as e:
                        st.warning(str(e))
            else:
                st.info("All caught up! No pending orders in the pickup queue.")

    # =========================================================
    # RIGHT BENTO CARD: ACTIVE PENDING PICKUP QUEUE
    # =========================================================
    with q_right:
        with st.container(key='bento_queue_list', border=True):
            hdr_q, cnt_q = st.columns((2.5, 1), vertical_alignment='center')
            with hdr_q:
                st.markdown("##### All Pending Pickup Orders")
            with cnt_q:
                st.markdown(
                    f"<div style='text-align:right; font-weight:700; color:#4b1117;'>{len(pending_orders)} Waiting</div>",
                    unsafe_allow_html=True
                )

            if pending_orders:
                queue_rows = [
                    {
                        "Order #": int(o['id']),
                        "Customer": o['customer_name'],
                        "Details": o['details'],
                        "Priority": int(o['priority']),
                        "Status": o['status'],
                        "Created": str(o['created_at']).replace('T', ' ')[:16]
                    }
                    for o in pending_orders
                ]
                st.dataframe(
                    pd.DataFrame(queue_rows),
                    use_container_width=True,
                    hide_index=True,
                    height=330,
                    column_config={
                        "Order #": st.column_config.NumberColumn("Order #", width="small", format="%d"),
                        "Customer": st.column_config.TextColumn("Customer", width="small"),
                        "Details": st.column_config.TextColumn("Details", width="large"),
                        "Priority": st.column_config.NumberColumn("Priority", width="small", format="%d"),
                        "Status": st.column_config.TextColumn("Status", width="small"),
                        "Created": st.column_config.TextColumn("Created", width="small"),
                    }
                )
            else:
                st.info("No pending pickup orders right now.")

elif mode == 'Cashier' and page == 'Sales History':
    # Single compact top toolbar: Heading | Search | History Type Filter
    hdr_c, search_c, type_c = st.columns((1.1, 1.5, 1.1), vertical_alignment='center', gap='small')
    with hdr_c:
        st.markdown("##### Sales & Activity History")
    with search_c:
        cashier_q = st.text_input(
            "Search",
            placeholder="Search sale #, product, customer...",
            key="cashier_hist_search",
            label_visibility="collapsed"
        ).strip().lower()
    with type_c:
        hist_type = st.selectbox(
            "Filter",
            ("All cashier activity", "Completed sales only", "Queue & pickup actions"),
            key="cashier_hist_type",
            label_visibility="collapsed"
        )

    left_sales, right_panel = st.columns((1.35, 1), gap='medium')

    # =========================================================
    # LEFT BENTO CARD: COMPLETED SALES TABLE
    # =========================================================
    with left_sales:
        with st.container(key='bento_cashier_sales', border=True):
            st.markdown("**Completed Sales**")
            if hist_type == "Queue & pickup actions":
                st.info("Switch filter to 'All cashier activity' or 'Completed sales only' to view sales.")
            else:
                tx_list = db.transaction_history()
                sales_rows = []
                for tx in tx_list:
                    tx_id = int(tx['id'])
                    items = db.transaction_items(tx_id)
                    items_summary = ", ".join(
                        f"{i['quantity']}x {i['product_name']}" + (f" ({i['size_oz']}oz)" if i.get('size_oz') and int(i['size_oz']) < 99 else "")
                        for i in items
                    )
                    row_text = f"{tx_id} {tx.get('cashier_label', '')} {items_summary}".lower()
                    if cashier_q and cashier_q not in row_text:
                        continue

                    sales_rows.append({
                        "Sale #": tx_id,
                        "Date/time": str(tx['created_at']).replace('T', ' ')[:16],
                        "Cashier": tx.get('cashier_label', 'Cashier'),
                        "Items": items_summary,
                        "Total": money(int(tx['total_cents']))
                    })

                if sales_rows:
                    st.dataframe(
                        pd.DataFrame(sales_rows),
                        use_container_width=True,
                        hide_index=True,
                        height=355,
                        column_config={
                            "Sale #": st.column_config.NumberColumn("Sale #", width="small", format="%d"),
                            "Date/time": st.column_config.TextColumn("Date/time", width="small"),
                            "Cashier": st.column_config.TextColumn("Cashier", width="small"),
                            "Items": st.column_config.TextColumn("Items", width="large"),
                            "Total": st.column_config.TextColumn("Total", width="small"),
                        }
                    )
                else:
                    st.info("No completed sales match your search.")

    # =========================================================
    # RIGHT BENTO COLUMN: LAST CHECKOUT RECEIPT + CASHIER LOGS
    # =========================================================
    with right_panel:
        # Top Right Card: Compact Last Checkout Receipt (Collapsed by default or sleek mini-card)
        with st.container(key='bento_cashier_receipt', border=True):
            last_tx = st.session_state.get('last_sale')
            if last_tx and isinstance(last_tx, dict) and last_tx.get('transaction_id'):
                l_id = int(last_tx['transaction_id'])
                l_time = str(last_tx.get('created_at', '')).replace('T', ' ')[:16]
                l_tot = money(int(last_tx.get('total_cents', 0)))

                r_hdr, r_tot = st.columns((1.6, 1), vertical_alignment='center')
                with r_hdr:
                    st.markdown(f"**Last Receipt: Sale #{l_id}**")
                    st.caption(f"Recorded {l_time}")
                with r_tot:
                    st.markdown(
                        f"<div style='background:#f8f3eb; border:1px solid #e2d4c3; border-radius:8px; padding:4px 10px; text-align:right; font-weight:800; color:#4b1117;'>{l_tot}</div>",
                        unsafe_allow_html=True
                    )

                l_items = db.transaction_items(l_id)
                if l_items:
                    mini_rows = [
                        {
                            "Item": f"{i['quantity']}x {i['product_name']}" + (f" ({i['size_oz']}oz)" if i.get('size_oz') and int(i['size_oz']) < 99 else ""),
                            "Notes": i.get('customizations') or "—",
                            "Subtotal": money(int(i['subtotal_cents']))
                        }
                        for i in l_items
                    ]
                    st.dataframe(pd.DataFrame(mini_rows), use_container_width=True, hide_index=True, height=105)
            else:
                st.markdown("**Last Checkout Receipt**")
                st.caption("Complete a checkout in 'New Sale' to preview the receipt here.")

        # Bottom Right Card: Cashier Actions & Queue History
        with st.container(key='bento_cashier_logs', border=True):
            st.markdown("**Cashier Actions & Queue History**")
            if hist_type == "Completed sales only":
                st.info("Switch filter to view queue & pickup actions.")
            else:
                c_logs = db.activity_history(actor_mode='Cashier', search_text=cashier_q, limit=200)
                if c_logs:
                    log_rows = [
                        {
                            "Time": str(r['created_at']).replace('T', ' ')[5:16],
                            "Action": r['action'],
                            "Details": r['details']
                        }
                        for r in c_logs
                    ]
                    st.dataframe(
                        pd.DataFrame(log_rows),
                        use_container_width=True,
                        hide_index=True,
                        height=175,
                        column_config={
                            "Time": st.column_config.TextColumn("Time", width="small"),
                            "Action": st.column_config.TextColumn("Action", width="small"),
                            "Details": st.column_config.TextColumn("Details", width="medium"),
                        }
                    )
                else:
                    st.info("No cashier actions recorded yet.")



# =========================================================================
# INVENTORY MANAGER WORKSPACE MODULES
# =========================================================================
elif mode == 'Inventory Manager' and page == 'Stock History':
    with st.container(key='bento_stock_history_card', border=True):
        # Single clean top row: Title | Movement Type Filter | Search | Circular CSV Download
        hdr_c, act_c, search_c, dl_c = st.columns((1.1, 1.0, 1.7, 0.3), vertical_alignment='center', gap='small')
        with hdr_c:
            st.markdown('##### Stock Movement History')
        with act_c:
            action_filter = st.selectbox(
                'Action',
                ('All Stock Movements', 'Stock Added', 'Stock Deducted', 'Stock Set'),
                key='inv_hist_action_filter',
                label_visibility='collapsed'
            )
        with search_c:
            hist_search = st.text_input(
                'Search',
                placeholder='Search product code, units, or note...',
                key='inv_hist_search_input',
                label_visibility='collapsed'
            ).strip().lower()

        logs = db.activity_history() if hasattr(db, 'activity_history') else []
        stock_actions = {'Stock Added', 'Stock Deducted', 'Stock Set', 'Stock Adjusted'}

        filtered_stock_logs = []
        for row in logs:
            r = dict(row)
            r_action = r.get('action') or ''
            if r_action not in stock_actions:
                continue
            if action_filter != 'All Stock Movements' and r_action != action_filter:
                continue

            r_mode = next(
                (
                    str(v) for k, v in r.items()
                    if k not in ('id', 'created_at', 'timestamp', 'action', 'details')
                    and v in ('Admin', 'Cashier', 'Inventory Manager')
                ),
                'Inventory Manager'
            )
            r_details = r.get('details') or ''
            r_time = str(r.get('created_at') or r.get('timestamp') or '').replace('T', ' ')[:16]

            if hist_search and hist_search not in f"{r_action} {r_details} {r_mode}".lower():
                continue

            filtered_stock_logs.append({
                'Date/time': r_time,
                'Updated By': r_mode,
                'Movement': r_action,
                'Details': r_details
            })

        with dl_c:
            with st.container(key='bento_sales_dl'):
                if filtered_stock_logs:
                    csv_data = pd.DataFrame(filtered_stock_logs).to_csv(index=False).encode('utf-8')
                    st.download_button(
                        "",
                        icon=":material/download:",
                        help="Download stock history CSV",
                        data=csv_data,
                        file_name="gulps_grubs_stock_history.csv",
                        mime="text/csv",
                        type="primary"
                    )
                else:
                    st.button("", icon=":material/download:", help="No stock logs to export", disabled=True)

        if filtered_stock_logs:
            st.dataframe(
                pd.DataFrame(filtered_stock_logs),
                use_container_width=True,
                hide_index=True,
                height=365,
                column_config={
                    "Date/time": st.column_config.TextColumn("Date/time", width="small"),
                    "Updated By": st.column_config.TextColumn("Updated By", width="small"),
                    "Movement": st.column_config.TextColumn("Movement", width="small"),
                    "Details": st.column_config.TextColumn("Details", width="large"),
                }
            )
        else:
            st.info("No stock movements recorded yet. Restock or adjust an item on the Dashboard to see it logged here.")


elif mode == 'Inventory Manager' and page == 'Dashboard':
    all_products = [dict(p) for p in db.list_products(active_only=True)]

    # Compute KPI counts matching your existing Stock Urgency Indicators
    total_skus = len(all_products)
    out_of_stock = [p for p in all_products if int(p.get('stock', 0)) <= 0]
    low_stock = [
        p for p in all_products
        if 0 < int(p.get('stock', 0)) <= int(p.get('low_stock_threshold', 5))
    ]
    overstocked = [
        p for p in all_products
        if int(p.get('high_stock_threshold', 50)) > 0
        and int(p.get('stock', 0)) >= int(p.get('high_stock_threshold', 50))
    ]

    # ROW 1: Retained Stock Urgency Indicators (with equal-height delta alignment)
    st.markdown("##### Stock Urgency Indicators")
    k1, k2, k3, k4 = st.columns(4, gap='small')
    with k1:
        st.metric(
            "Total Items Managed",
            f"{total_skus}",
            delta="Active Catalog",
            delta_color="off"
        )
    with k2:
        st.metric(
            "Out of Stock",
            f"{len(out_of_stock)}",
            delta="All Available" if len(out_of_stock) == 0 else "Action Needed",
            delta_color="normal" if len(out_of_stock) == 0 else "inverse"
        )
    with k3:
        st.metric(
            "Low-Stock Warning",
            f"{len(low_stock)}",
            delta="All Healthy" if len(low_stock) == 0 else "Needs Restock",
            delta_color="normal" if len(low_stock) == 0 else "inverse"
        )
    with k4:
        st.metric(
            "Overstocked Rows",
            f"{len(overstocked)}",
            delta="Within Limits" if len(overstocked) == 0 else "High Volume",
            delta_color="normal" if len(overstocked) == 0 else "off"
        )

    if not all_products:
        st.info("No active products in catalog. Add products under Admin -> Product Management first.")
    else:
        # ROW 2: 2-Column Bento Grid (Left: Live Stock Levels | Right: Quick Stock Adjustment)
        inv_left, inv_right = st.columns((1.35, 1), gap='medium')

        with inv_left:
            with st.container(key='bento_inv_table', border=True):
                hdr_l, f_search, f_status = st.columns((1.1, 1.4, 1.1), vertical_alignment='center', gap='small')
                with hdr_l:
                    st.markdown("**Live Stock Levels**")
                with f_search:
                    inv_q = st.text_input(
                        "Search stock",
                        placeholder="Search code or name...",
                        key="inv_dash_search",
                        label_visibility="collapsed"
                    ).strip().lower()
                with f_status:
                    status_filter = st.selectbox(
                        "Status",
                        ("All Items", "Low Stock", "Out of Stock", "Overstocked", "Healthy"),
                        key="inv_dash_status",
                        label_visibility="collapsed"
                    )

                sorted_prods = sorted(all_products, key=lambda x: (int(x.get('stock', 0)), x.get('name', '').lower()))

                table_rows = []
                for p in sorted_prods:
                    stk = int(p.get('stock', 0))
                    low_t = int(p.get('low_stock_threshold', 5))
                    high_t = int(p.get('high_stock_threshold', 50))

                    if stk <= 0:
                        status_lbl = "Out of Stock"
                    elif stk <= low_t:
                        status_lbl = "Low Stock"
                    elif high_t > 0 and stk >= high_t:
                        status_lbl = "Overstocked"
                    else:
                        status_lbl = "Healthy"

                    if status_filter == "Low Stock" and status_lbl != "Low Stock":
                        continue
                    if status_filter == "Out of Stock" and status_lbl != "Out of Stock":
                        continue
                    if status_filter == "Overstocked" and status_lbl != "Overstocked":
                        continue
                    if status_filter == "Healthy" and status_lbl != "Healthy":
                        continue
                    if inv_q and (inv_q not in p['name'].lower() and inv_q not in p['code'].lower()):
                        continue

                    table_rows.append({
                        "Code": p['code'],
                        "Product": p['name'],
                        "Stock": stk,
                        "Min Alert": low_t,
                        "Status": status_lbl
                    })

                if table_rows:
                    st.dataframe(
                        pd.DataFrame(table_rows),
                        use_container_width=True,
                        hide_index=True,
                        height=265,
                        column_config={
                            "Code": st.column_config.TextColumn("Code", width="small"),
                            "Product": st.column_config.TextColumn("Product", width="medium"),
                            "Stock": st.column_config.NumberColumn("Stock", width="small", format="%d"),
                            "Min Alert": st.column_config.NumberColumn("Min Alert", width="small", format="%d"),
                            "Status": st.column_config.TextColumn("Status", width="small"),
                        }
                    )
                else:
                    st.info("No products match your current filter.")

                st.caption(f"Showing {len(table_rows)} of {total_skus} active products · Sorted by lowest stock first")

        with inv_right:
            with st.container(key='bento_inv_adjust', border=True):
                st.markdown("**Quick Stock Adjustment**")

                prod_map = {
                    f"{p['code']} — {p['name']} ({int(p.get('stock', 0))} in stock)": p
                    for p in sorted(all_products, key=lambda x: x['code'])
                }
                chosen_lbl = st.selectbox(
                    "Select Product",
                    list(prod_map.keys()),
                    key="inv_adjust_product_select"
                )
                target_p = prod_map[chosen_lbl]
                current_stk = int(target_p.get('stock', 0))

                adj_mode = st.segmented_control(
                    "Adjustment Action",
                    options=("+ Restock", "- Deduct", "Set Exact"),
                    default="+ Restock",
                    selection_mode="single",
                    width="stretch",
                    key="inv_adj_mode_pills"
                )
                if not adj_mode:
                    adj_mode = "+ Restock"

                q_col, prev_col = st.columns((1.2, 1), vertical_alignment='bottom', gap='small')
                with q_col:
                    min_val = 0 if adj_mode == "Set Exact" else 1
                    default_val = current_stk if adj_mode == "Set Exact" else 10
                    qty_input = st.number_input(
                        "Quantity",
                        min_value=min_val,
                        max_value=100000,
                        value=default_val,
                        step=1,
                        key=f"inv_qty_val_{target_p['id']}_{adj_mode}"
                    )

                if adj_mode == "+ Restock":
                    projected_stk = current_stk + int(qty_input)
                    delta_units = int(qty_input)
                    action_title = "Stock Added"
                    detail_note = f"{target_p['code']} · +{delta_units} units"
                elif adj_mode == "- Deduct":
                    projected_stk = max(0, current_stk - int(qty_input))
                    delta_units = projected_stk - current_stk
                    action_title = "Stock Deducted"
                    detail_note = f"{target_p['code']} · {delta_units} units"
                else:
                    projected_stk = int(qty_input)
                    delta_units = projected_stk - current_stk
                    action_title = "Stock Set"
                    detail_note = f"{target_p['code']} · Set to {projected_stk} units"

                with prev_col:
                    st.markdown(
                        f"""
                        <div style="background:#f8f3eb; border:1px solid #e2d4c3; border-radius:10px; padding:6px 10px; text-align:center;">
                            <div style="font-size:0.72rem; color:#6b5255; font-weight:600;">New Stock</div>
                            <div style="font-size:1.05rem; font-weight:800; color:#4b1117;">{projected_stk} units</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                adj_reason = st.text_input(
                    "Reason / Note (Optional)",
                    placeholder="e.g., Morning delivery, spoilage, count correction...",
                    key=f"inv_reason_{target_p['id']}"
                ).strip()

                update_stk_btn = st.button(
                    "Update Stock",
                    type="primary",
                    use_container_width=True,
                    key=f"inv_submit_btn_{target_p['id']}"
                )

                if update_stk_btn:
                    if adj_mode == "- Deduct" and int(qty_input) > current_stk:
                        st.error(f"Cannot deduct {int(qty_input)} units — only {current_stk} currently in stock.")
                    elif projected_stk == current_stk:
                        st.warning("Stock level is unchanged.")
                    else:
                        try:
                            with db.connection() as conn:
                                conn.execute(
                                    "UPDATE products SET stock = ?, updated_at = ? WHERE id = ?",
                                    (int(projected_stk), datetime.now().isoformat(), target_p['id'])
                                )
                            full_detail = f"{detail_note} ({adj_reason})" if adj_reason else detail_note
                            db.log_activity('Inventory Manager', action_title, full_detail)
                            st.session_state.global_toast = {
                                "msg": f"STOCK UPDATED: {target_p['name']} ({target_p['code']}) is now at {projected_stk} units.",
                                "bg": "#2e7d32",
                                "icon": "[OK]"
                            }
                            st.rerun()
                        except Exception as e:
                            safe_error(e)


