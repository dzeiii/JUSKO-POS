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
# 🔔 GLOBAL TRANSACTIONS NOTIFICATION HUB (Pure Browser CSS Async Animation)
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
    logo_col, brand_col, mode_col, page_col = st.columns([1.05, 1.8, 1.55, 5.2], vertical_alignment='center', gap='small')
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
            page = st.radio('Inventory navigation', ['Dashboard', 'Stock Overview', 'Restock Products'], horizontal=True, key='inventory_page', label_visibility='collapsed')
st.caption('Demo mode selector only — it is not secure authentication.')

try: product_tree = rebuild_tree()
except Exception as e:
    safe_error(e); st.stop()

# =========================================================================
# 👑 ADMIN WORKSPACE MODULES
# =========================================================================
if mode == 'Admin' and page == 'Dashboard':
    from datetime import datetime, time, timedelta
    today = ph_today()
    start_time = datetime.combine(today, time.min).isoformat()
    end_time = datetime.combine(today + timedelta(days=1), time.min).isoformat()
    
    st.subheader('Business overview')
    summary = db.sales_summary(start_time, end_time)
    all_products = db.list_products(active_only=True)
    low = [p for p in all_products if p['stock'] <= p['low_stock_threshold']]
    high = [p for p in all_products if p['stock'] >= p['high_stock_threshold']]
    
    a, b, c, d, e = st.columns(5)
    a.metric('Today’s revenue', money(summary['revenue_cents']))
    b.metric('Completed sales', summary['transactions'])
    c.metric('Active products', len(all_products))
    d.metric('Low-stock alerts', len(low), delta='Needs attention' if low else 'Stock looks good', delta_color='inverse' if low else 'normal')
    e.metric('High-stock alerts', len(high), delta='Overstocked' if high else 'Stock looks good', delta_color='off' if high else 'normal', help='Products at or above their Admin-defined high-stock threshold.')

    st.caption('Revenue is the total value of recorded sales, not profit. Product costs and operating expenses are not tracked.')
    
    left, right = st.columns([1.15, 1])
    with left:
        st.markdown('#### Low-stock watch')
        if low:
            st.dataframe(pd.DataFrame([{'Code': p['code'], 'Product': p['name'], 'Stock': p['stock'], 'Alert at': p['low_stock_threshold']} for p in low]), use_container_width=True, hide_index=True)
        else: st.success('No active products are at or below their low-stock threshold.')

        st.markdown('#### High-stock watch')
        if high:
            st.dataframe(pd.DataFrame([{'Code': p['code'], 'Product': p['name'], 'Stock': p['stock'], 'Limit': p.get('high_stock_threshold', 0)} for p in high]), use_container_width=True, hide_index=True)
        else: st.success('No active products are at or above their high-stock threshold.')
    
    with right:
        st.markdown('#### Recent transactions')
        recent = db.transaction_history()[:6]
        if recent: st.dataframe(pd.DataFrame([{'Sale #': r['id'], 'Date': r['created_at'].replace('T', ' ')[:16], 'Total': money(r['total_cents'])} for r in recent]), use_container_width=True, hide_index=True)
        else: st.info('Completed sales will appear here.')
        
    st.markdown('#### Sales over the last 7 days')
    daily = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        s = datetime.combine(day, time.min).isoformat()
        e = datetime.combine(day + timedelta(days=1), time.min).isoformat()
        sm = db.sales_summary(s, e)
        daily.append({'Date': day.strftime('%b %d'), 'Revenue (₱)': sm['revenue_cents'] / 100})
    st.bar_chart(pd.DataFrame(daily).set_index('Date'))

elif mode == 'Admin' and page == 'Product Management':

    st.subheader('Product Catalog Management')
    tab1, tab2, tab3 = st.tabs(['Add product','Edit / Delete','View Catalog'])
       
    with tab1:
        classification = st.radio('Product Classification *', ['Foods (Grubs)', 'Drinks (Gulps)', 'Others (Combo/Meal Plan)'], horizontal=True)
        st.markdown("---")

        # Dynamically pull pre-saved category lists
        try:
            db_products = db.list_products(active_only=False)
            drink_keywords = ['milktea', 'milkshake', 'shake', 'lemonade', 'slushie', 'slush', 'coffee', 'float', 'frappe', 'drink', 'beverage', 'juice', 'tea', 'brew', 'gulp']
            
            food_cats, drink_cats, combo_cats = set(), set(), set()
            for p in db_products:
                if not p['category']: continue
                clean_cat = p['category'].split(" | Custom:", 1)[0].strip()
                clean_cat_lower = clean_cat.lower()
                
                is_drink_cat = any(dk in clean_cat_lower for dk in drink_keywords)
                is_combo_cat = any(ck in clean_cat_lower for ck in ['combo', 'promo', 'bundle'])
                
                if is_drink_cat: drink_cats.add(clean_cat)
                elif is_combo_cat: combo_cats.add(clean_cat)
                else: food_cats.add(clean_cat)
            
            if classification == 'Drinks (Gulps)': existing_saved_cats = sorted(list(drink_cats))
            elif classification == 'Others (Combo/Meal Plan)': existing_saved_cats = sorted(list(combo_cats))
            else: existing_saved_cats = sorted(list(food_cats))
        except Exception:
            existing_saved_cats = []

        def parse_and_format_price(raw_text):
            if not raw_text: return 0.0
            clean_digits = raw_text.replace('₱', '').strip()
            try: 
                return float(clean_digits)
            except ValueError: 
                return 0.0
                
        # AUTOMATIC PRODUCT FORM RESET
        if "clear_product_form" not in st.session_state:
            st.session_state.clear_product_form = False

        if st.session_state.clear_product_form:

            # Clear product information
            st.session_state[f'f_name_{classification}'] = ""
            st.session_state[f'f_cat_text_input_lane_{classification}'] = ""

            # Clear food/combo pricing
            st.session_state[f'f_price_{classification}'] = ""

            # Clear drink pricing
            st.session_state['drink_val_8_text_final'] = ""
            st.session_state['drink_val_12_text_final'] = ""
            st.session_state['drink_val_16_text_final'] = ""
            st.session_state['drink_lbl_custom_reactive_field'] = ""
            st.session_state['drink_val_custom_text_reactive'] = ""

            # Reset drink checkboxes
            st.session_state['drink_use_8_final'] = False
            st.session_state['drink_use_12_final'] = True
            st.session_state['drink_use_16_final'] = True
            st.session_state['drink_use_custom_reactive_layer'] = False

            # Reset initial stock
            st.session_state[f'starting_stock_{classification}'] = 0

            st.session_state.clear_product_form = False
        # STEP 1: PRODUCT INFORMATION
        size_prices = {}
        price = 0.0
        drink_category_suffix = ""
        drink_config_error = None
        st.markdown("#### 📝 Product Information")
        name = st.text_input('Product name *',placeholder='Enter product name',key=f'f_name_{classification}').strip()
        category = st.text_input('Category *',placeholder="Type your category name here (e.g., Waffle, Streetfood)...",key=f'f_cat_text_input_lane_{classification}').strip()

        st.divider()
        
        # STEP 2: DRINK SIZE AND PRICING CONFIGURATION
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
        if classification == 'Drinks (Gulps)':
            st.markdown("##### 🥤 Cup Size & Base Pricing Options")
            st.caption('Ticking checkboxes will automatically expose size pricing input fields below:')

            price8 = 0.00
            price12 = 0.00
            price16 = 0.00
            # Render options inside a clean horizontal 3-column sub-grid matrix
            col8, col12, col16 = st.columns(3)    
            with col8:
                use8 = st.checkbox('Offer 8 oz', value=False, key='drink_use_8_final')
                price8_input = ""
                if use8:
                    price8_input = st.text_input('8 oz Price (₱) *', placeholder='0.00', key='drink_val_8_text_final', ).strip()
                    price8 = parse_and_format_price(price8_input) if use8 else 0.00
                        
            with col12:
                use12 = st.checkbox('Offer 12 oz', value=True, key='drink_use_12_final')
                price12_input = ""
                if use12:
                    price12_input = st.text_input('12 oz Price (₱) *', placeholder='0.00', key='drink_val_12_text_final' ).strip()
                    price12 = parse_and_format_price(price12_input) if use12 else 0.00
                        
            with col16:
                use16 = st.checkbox('Offer 16 oz', value=True, key='drink_use_16_final')
                price16_input = ""
                if use16:
                    price16_input = st.text_input('16 oz Price (₱) *', placeholder='0.00', key='drink_val_16_text_final').strip()
                    price16 = parse_and_format_price(price16_input) if use16 else 0.00

            st.divider()
            st.markdown("##### 🥤 Other / Custom Sizing Configuration")

            if "custom_sizes_count" not in st.session_state:
                st.session_state.custom_sizes_count = 1

            custom_size_inputs_list = []
            
            for i in range(st.session_state.custom_sizes_count):
                if st.session_state.custom_sizes_count > 1:
                    st.markdown(f"**Custom Size Option #{i + 1}**")
                
                c_size_col, c_price_col = st.columns(2)
                with c_size_col:
                    lbl_val = st.text_input('Custom Size Description Label', placeholder='e.g., 22oz, 1-Liter', key=f'drink_lbl_custom_reactive_field_{i}').strip()
                with c_price_col:
                    prc_val = st.text_input('Custom Size Price (₱) *', placeholder='0.00', key=f'drink_val_custom_text_reactive_{i}').strip()
                
                custom_size_inputs_list.append({"label": lbl_val, "price_raw": prc_val})

            if st.button("➕ Add another custom size", key="add_another_custom_size_btn"):
                st.session_state.custom_sizes_count += 1
                st.rerun()
    
            try:    
                if use8:
                    price8 = read_drink_price(price8_input, "8 oz")
                    size_prices[8] = cents_from_peso(price8)
        
                if use12:
                    price12 = read_drink_price(price12_input, "12 oz")
                    size_prices[12] = cents_from_peso(price12)
        
                if use16:
                    price16 = read_drink_price(price16_input, "16 oz")
                    size_prices[16] = cents_from_peso(price16)
        
                custom_labels_compiled = []
                custom_database_key_id = 99  
                
                for idx, entry in enumerate(custom_size_inputs_list):
                    c_label = entry["label"]
                    c_price_raw = entry["price_raw"]
                    
                    if c_label or c_price_raw:
                        if not c_label:
                            raise ValueError(f"Please enter a description label for Custom Size #{idx + 1}.")
                        
                        parsed_c_price = read_drink_price(c_price_raw, f"custom size '{c_label}'")
                        
                        size_prices[custom_database_key_id] = cents_from_peso(parsed_c_price)
                        custom_labels_compiled.append(c_label)
                        
                        custom_database_key_id += 1  
                
                if custom_labels_compiled:
                    drink_category_suffix = f" | Custom:{', '.join(custom_labels_compiled)}"
                    
            except ValueError as exc:
                drink_config_error = str(exc)

            st.divider()

        # STEP 3: FOOD AND COMBO PRICING
        if classification in ['Foods (Grubs)','Others (Combo/Meal Plan)']:
            st.markdown("#### 💰 Product Pricing")
            price_input = st.text_input('Product Price (₱) *',placeholder='0.00',key=f'f_price_{classification}').strip()
            price = parse_and_format_price(price_input)
        
        # STEP 4: INVENTORY ALERT SETTINGS
        st.markdown("#### 📦 Inventory Settings")
        low_stock_threshold = st.number_input('Low-stock alert boundary count',min_value=0,value=5,step=1)
        high_stock_threshold = st.number_input('High-stock alert boundary count',min_value=0,value=50,step=1)
        st.divider()
        
        # STEP 5: SUBMIT PRODUCT
        submit_form_btn = st.button('Add product to Catalog',type='primary',use_container_width=True,key=f'add_product_button_{classification}')

        # --- OUTSIDE FORM CONTAINER: Form data routing checks execute safely downstream ---
        if submit_form_btn:
            def to_sentence_case(text):
                """Automatically converts any text input into clean sentence case words."""
                if not text: return ""
                # Split text by spaces, capitalize each word cleanly, and join them back
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
                if not words: return False
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

            # --- STEP 3: RUN THE SELECTION TREE WITH VALIDATED INITIALIZATIONS ---
            if clean_name and name_audit in existing_product_names: 
                st.error(f"🔴 Catalog Conflict: A product named '{clean_name}' already exists in your store inventory!")
            elif not clean_name: 
                st.error("Product name is required.")
            elif not clean_category: 
                st.error("Category structure specification is required.")
            elif is_spam_text or is_nonsense_word: 
                st.error("🔴 Invalid Entry: Input contains keyboard spam or gibberish text patterns.")
            elif contains_junk: 
                st.error("🔴 Context Validation Alert: Junk classifications (person, human, object) are strictly blocked.")
            elif not is_valid_context:
                st.error(f"🔴 Context/Classification Mismatch: {mismatch_error} Please allocate your item correctly.")
            elif classification in ['Foods (Grubs)', 'Others (Combo/Meal Plan)'] and price <= 0.0: 
                st.error("🔴 Validation Error: Price field is required and must be greater than ₱0.00.")
            elif classification == 'Drinks (Gulps)' and drink_config_error:
                st.error(f"🔴 Drink Configuration Error: {drink_config_error}")
            elif classification == 'Drinks (Gulps)' and not size_prices:
                st.error("🔴 Validation Error: Enable and configure at least one drink size.")
            else:
                try:
                    price_cents = cents_from_peso(price) if classification != 'Drinks (Gulps)' else 0
                    starting_stock = 0
                    all_existing_products = db.list_products(active_only=False)
                    prefix = "GLP" if classification == 'Drinks (Gulps)' else "GRB"
                    existing_numbers = []
                    for prod in all_existing_products:
                        code_str = prod.get('code', '')
                        if code_str.startswith(f"{prefix}-"):
                            try:
                                num_part = int(code_str.split("-")[1])
                                existing_numbers.append(num_part)
                            except (IndexError, ValueError):
                                continue

                    if existing_numbers:
                        next_code_number = max(existing_numbers) + 1
                    else:
                        next_code_number = 1001 

                    while True:
                        generated_code = f"{prefix}-{next_code_number}"
                        
                        with db.connection() as conn:
                            collision_check = conn.execute("SELECT 1 FROM products WHERE code = ?", (generated_code,)).fetchone()
                        
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
                    
                    formatted_display_price = f"₱{price:,.2f}" if classification != 'Drinks (Gulps)' else "Configured Sizes Array"
                    audit_msg = f"Menu product item '{clean_name}' successfully added to store catalog database! Assigned code: '{generated_code}' under active category grouping: '{final_save_category}'."
                    
                    st.session_state.global_toast = {
                        "msg": f"🟢 SUCCESS: Product '{clean_name}' successfully added to catalog as unique code '{generated_code}'!",
                        "bg": "#2e7d32",  
                        "icon": "🟢"
                    }
                    
                    db.log_activity('Admin', 'Product Created', f"{generated_code} · {clean_name}")
                    logging.info(f"TRANSACTION SUCCESS [ADMIN]: {audit_msg}")

                    # Clean out form UI memory
                    st.session_state.clear_product_form = True
                    st.session_state.custom_sizes_count = 1
                    st.rerun()
                except Exception as e: 
                    safe_error(e)

    # EDIT / DELETE TAB
    with tab2:
        st.subheader("Edit or Delete Product")
        all_products = db.list_products(active_only=False)
        if not all_products:
            st.info("No active products available to edit.")
        else:
            labels = {(f"{prod['code']} — {prod['name']} {'(Inactive)' if not prod['active'] else ''}"): prod for prod in all_products}
            selected_label = st.selectbox('Select product to modify',list(labels.keys()),key='edit_select')
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
                st.markdown("#### Product Details")
                ec1, ec2 = st.columns(2)
                ec1.text_input('Product code (automatically assigned)',value=p['code'],disabled=True)
                new_name = ec2.text_input('Product name',value=p['name']).strip()
                is_a_drink = is_custom_drink or any(
                    d in base_cat_name.lower()
                    for d in ['milkshake', 'float', 'milktea', 'drink', 'coffee', 'juice', 'beverage']
                )
                size_inputs = {}
                if is_a_drink:
                    new_base_cat = st.text_input('Category Name *',value=base_cat_name).strip()
                    st.markdown('Available drink size pricing')
                    all_possible_sizes = [8, 12, 16]
                    size_cols = st.columns(len(all_possible_sizes))
                    
                    for size_idx, size in enumerate(all_possible_sizes):
                        existing_price_cents = current_sizes.get(size, 0)
                        if not current_sizes and size in (12, 16):
                            existing_price_cents = p.get('price_cents', 0)  
                        initial_value = float(existing_price_cents) / 100.0
                        size_inputs[size] = size_cols[size_idx].number_input(
                            f'{size} oz price (₱)',
                            min_value=0.0,
                            value=initial_value,
                            step=1.0,
                            format="%.2f",
                            key=f"edit_price_{p['code']}_{size}" # Added unique key to prevent streamlit render conflicts
                        )

                    st.divider()
                    st.markdown('🥤 Other / Custom Size Configuration')
                    has_custom = st.checkbox("Enable a different custom size profile for this product",value=is_custom_drink,key=f"form_has_cust_{p['id']}")
                    c_col1, c_col2 = st.columns(2)
                    edit_custom_label = c_col1.text_input("Custom Size Description Label",value=custom_sz_label,placeholder="e.g., 22oz, 1-Liter",disabled=not has_custom,key=f"form_lbl_cust_{p['id']}").strip()
                    edit_custom_price = c_col2.number_input("Custom Size Price (₱)",min_value=0.0,value=float(current_sizes.get(99, 0.0) / 100),step=5.0,format='%.2f',disabled=not has_custom,key=f"form_val_cust_{p['id']}")
                    updated_sizes = {}
                    for sz_key, cents_val in current_sizes.items():
                        updated_sizes[int(sz_key)] = int(cents_val)
                    for sz, pr_val in size_inputs.items():
                        if float(pr_val) > 0.0:
                            updated_sizes[int(sz)] = cents_from_peso(pr_val)
                    if has_custom and edit_custom_label:
                        if float(edit_custom_price) > 0.0:
                            updated_sizes[99] = cents_from_peso(edit_custom_price)
                        elif 99 in current_sizes:
                            updated_sizes[99] = int(current_sizes[99])
                        else:
                            updated_sizes[99] = 0
                        new_cat = (f"{new_base_cat} | Custom:{edit_custom_label}")
                    else:
                        new_cat = new_base_cat
                        if 99 in updated_sizes:
                            del updated_sizes[99]
                    if updated_sizes:
                        new_base_price_cents = next(iter(updated_sizes.values()))
                    else:
                        new_base_price_cents = p['price_cents']
                else:
                    new_cat = st.text_input('Category',value=p['category'],key=f"edit_cat_food_{p['id']}").strip()
                    new_price_val = st.number_input('Price (₱)',min_value=0.0,value=float(p['price_cents'] / 100),step=5.0,format='%.2f',key=f"edit_price_food_{p['id']}")
                    new_base_price_cents = cents_from_peso(new_price_val)
                    updated_sizes = None
                st.divider()
                new_threshold = st.number_input('Low-stock alert at',min_value=0,max_value=1000000,value=int(p['low_stock_threshold']),step=1)
                save_changes = st.button('Save All Product Details', type='primary', key=f"unified_save_btn_{p['id']}")
                if save_changes:
                    if not new_name or not new_cat: 
                        st.error("Product name and category definitions cannot be left blank.")
                    else:
                        try: 
                            db.update_product(p['id'], p['code'], new_name, new_cat, int(new_base_price_cents), int(new_threshold))
                            
                            if is_a_drink:
                                updated_sizes = {}
                                for size_key, input_val in size_inputs.items():
                                    cents_val = int(round(input_val * 100))
                                    if cents_val > 0:
                                        updated_sizes[size_key] = cents_val

                                if updated_sizes:
                                    db.set_product_sizes(p['id'], updated_sizes)
                                else:
                                    with db.connection() as clean_conn:
                                        clean_conn.execute("DELETE FROM product_sizes WHERE product_id = ?", (p['id'],))
                            else:
                                with db.connection() as clean_conn:
                                    clean_conn.execute("DELETE FROM product_sizes WHERE product_id = ?", (p['id'],))
                            
                            audit_msg = f"Product '{p['code']}' details updated successfully (New Name: '{new_name}', New Category: '{new_cat}')."
                            
                            st.session_state.global_toast = {
                                "msg": f"⚙️ UPDATE SUCCESS: Product details for '{p['code']}' have been cleanly updated!",
                                "bg": "#1565c0",  
                                "icon": "⚙️"
                            }
                            db.log_activity('Admin', 'Product Updated', f"{p['code']} · {new_name}")
                            logging.info(f"SUCCESS [ADMIN]: {audit_msg}")
                            st.rerun()
                        except Exception as e: 
                            safe_error(e)

                st.divider()
                st.error('### 🚨 DANGER ZONE: PERMANENT PURGE')
                st.markdown("Clicking delete below will execute a HARD DELETE. This completely wipes the item profile row from the database catalog and cannot be undone.", 
                            unsafe_allow_html=True)
                with st.container(key="danger_zone_box"):
                    check_step1 = st.checkbox("Confirm: I want to permanently delete this product profile, not deactivate it.", key=f"force_del_c1_{p['id']}")
                    check_step2 = st.checkbox("Confirm: I understand this action completely removes it from all search logs.", key=f"force_del_c2_{p['id']}")
                    if st.button('Permanently Delete From Database', key=f"hard_purge_action_{p['id']}", type='primary', disabled=not (check_step1 and check_step2)):
                        try:
                            success, msg = db.delete_product(p['id'])
                            if success:
                                audit_msg = f"Product '{p['code']} — {p['name']}' was permanently removed from the master database catalog files."
                                st.session_state.global_toast = {
                                    "msg": f"🚨 PURGE REMOVAL: Product '{p['code']}' has been permanently wiped from the store catalog!",
                                    "bg": "#c62828", 
                                    "icon": "🚨"
                                }
                                
                                db.log_activity('Admin', 'Product Deleted', f"{p['code']} · {p['name']}")
                                logging.info(f"SUCCESS [ADMIN]: {audit_msg}")
                                st.rerun()
                            else: 
                                st.error(msg)
                        except Exception as e: 
                            safe_error(e)

    # VIEW CATALOG TAB
    with tab3:
        st.markdown("---")
        st.markdown("#### 🔍 Filter & Sort Product Catalog")
        search_col, category_col, sort_col = st.columns([2, 1.2, 1.2])
        with search_col:
            search = st.text_input('Search by code or product name',key='product_search_input')
        with category_col:
            raw_categories = {prod['category'].split(" | Custom:", 1)[0].strip()for prod in all_products}
            category_options = (["All Categories"] + sorted(list(raw_categories)))
            selected_search_category = st.selectbox("Filter by Category",category_options,key='product_category_filter')
        with sort_col:
            sort_option = st.selectbox("Arrange Products By",[
                    "Product Name (A-Z)",
                    "Product Name (Z-A)",
                    "Product Code (Ascending)",
                    "Highest Price First",
                    "Lowest Price First",
                    "Lowest Stock Level First",
                    "Highest Stock Level First"
                ],key='catalog_sort_selector')
        filtered_items = []
        for prod in all_products:
            matches_keyword = search.casefold() in (prod['code'] + ' ' + prod['name']).casefold()
            clean_item_category = prod['category'].split(" | Custom:", 1)[0].strip()
            matches_category = (selected_search_category == "All Categories"or clean_item_category == selected_search_category)
            if matches_keyword and matches_category:
                filtered_items.append(prod)
        if sort_option == "Product Name (A-Z)":
            filtered_items.sort(key=lambda x: x['name'].lower())
        elif sort_option == "Product Name (Z-A)":
            filtered_items.sort(key=lambda x: x['name'].lower(),reverse=True)
        elif sort_option == "Product Code (Ascending)":
            filtered_items.sort(key=lambda x: x['code'].lower())
        elif sort_option == "Highest Price First":
            filtered_items.sort(key=lambda x: x['price_cents'],reverse=True)
        elif sort_option == "Lowest Price First":
            filtered_items.sort(key=lambda x: x['price_cents'])
        elif sort_option == "Lowest Stock Level First":
            filtered_items.sort(key=lambda x: x['stock'])
        elif sort_option == "Highest Stock Level First":
            filtered_items.sort(key=lambda x: x['stock'],reverse=True)
        if filtered_items:
            st.dataframe(
                pd.DataFrame([{
                        'Code': prod['code'],
                        'Product': prod['name'],
                        'Category': prod['category'].split(" | Custom:", 1)[0],
                        'Price': (' · '.join(f"{size if size != 99 else 'Custom'} oz {money(price)}" for size, price in db.get_product_sizes(prod['id']).items())
                                if db.get_product_sizes(prod['id'])
                                else money(prod['price_cents'])),
                                'Stock': prod['stock'],
                                'Low-stock threshold': prod['low_stock_threshold'],
                                'Status': (
                                    'Active' if prod['active'] else 'Inactive')}
                                    for prod in filtered_items
                                    ]),use_container_width=True, hide_index=True)
        else:
            st.info('No catalog products match your search keyword or selected category filter.')

elif mode == 'Admin' and page == 'Sales History':
    st.subheader('📜 Sales Transaction History')
    ph_today_date = ph_today()
    c1, c2 = st.columns(2)
    start_date = c1.date_input('From date',value=ph_today_date - timedelta(days=30))
    end_date = c2.date_input('To date',value=ph_today_date)
    if start_date > end_date:
        st.error('The start date must not be after the end date.')
    else:
        start = datetime.combine(start_date,time.min).isoformat()
        end = datetime.combine(end_date + timedelta(days=1),time.min).isoformat()
        rows = db.transaction_history(start, end)
        st.metric('Revenue in selected period',money(sum(r['total_cents'] for r in rows)))
        if rows:
            st.dataframe(
                pd.DataFrame([
                    {'Sale #': r['id'],
                    'Date/time': r['created_at'].replace('T', ' ')[:16],
                    'Cashier': r['cashier_label'],
                    'Total': money(r['total_cents'])
                    }
                    for r in rows
                ]),use_container_width=True,hide_index=True)
            chosen = st.selectbox('View sale details',[r['id'] for r in rows],format_func=lambda x: f"Sale #{x}")
            details = db.transaction_items(chosen)
            st.dataframe(
                pd.DataFrame([
                    {'Code': x['product_code'],'Product': x['product_name'],'Size': (f"{x.get('size_oz')} oz" if x.get('size_oz') else '—'),'Options': x.get('customizations', ''),
                    'Qty': x['quantity'],'Unit price': money(x['unit_price_cents']),'Subtotal': money(x['subtotal_cents'])
                    }
                    for x in details]), use_container_width=True, hide_index=True
            )
            st.download_button('Download filtered sales CSV',
                pd.DataFrame([
                    {
                        'sale_id': r['id'],
                        'created_at': r['created_at'],
                        'cashier': r['cashier_label'],
                        'total_php': r['total_cents'] / 100
                    }
                    for r in rows
                ]).to_csv(index=False).encode('utf-8'),'sales_history.csv','text/csv'
            )
        else:
            st.info('No transactions were found for the selected dates.')

elif mode == 'Admin' and page == 'Activity History':
    st.subheader('Admin and staff activity history')
    st.caption('Persistent audit trail for sales, queue actions, product changes, and inventory updates.')
    f1, f2 = st.columns([1, 2])
    role_filter = f1.selectbox('Mode',['All', 'Admin', 'Cashier', 'Inventory Manager', 'System'])
    activity_search = f2.text_input('Search activity history',placeholder='Search product, order number, sale number, action...')
    rows = db.activity_history(role_filter,activity_search,limit=1000)
    
    if rows:
        from datetime import datetime, timedelta
        formatted_rows = []
        for r in rows:
            raw_time = r['created_at'].replace('T', ' ')[:16]
            
            try:
                dt_obj = datetime.strptime(raw_time, "%Y-%m-%d %H:%M")
                if "15:" in raw_time:
                    dt_obj += timedelta(hours=8)
                display_time = dt_obj.strftime("%Y-%m-%d %H:%M")
            except Exception:
                display_time = raw_time

            formatted_rows.append({
                'Date/time': display_time,
                'Mode': r['actor_mode'],
                'Action': r['action'],
                'Details': r['details']
            })

        st.dataframe(pd.DataFrame(formatted_rows), use_container_width=True, hide_index=True)
        st.download_button('Download activity history CSV', pd.DataFrame(rows).to_csv(index=False).encode('utf-8'), 'activity_history.csv', 'text/csv')
    else:
        st.info('No activity matches this search yet.')

# =========================================================================
# CASHIER WORKSPACE MODULES
# =========================================================================
elif mode == 'Cashier' and page == 'Dashboard':
    st.subheader('📊 Cashier Shift Workspace Dashboard')
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
    c_metric1.metric(label="My Today's Sales 💰",value=money(shift_summary['revenue_cents']),delta=f"{shift_summary['transactions']} Receipts printed today")
    c_metric2.metric(label="Active Kitchen Queue ⏳",value=f"{pending_count} Orders",delta=("Queue heavy - Focus on speed" if pending_count > 5 else "Queue light / clear"),
                    delta_color="inverse" if pending_count > 5 else "normal")
    c_metric3.metric(label="Current Work Station",value="Cashier Desk #1",delta="System Connected & Online")
    st.divider()
    st.markdown("#### 📜 Recent Shift Receipts")
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
    st.subheader('New Sale')
    # LOAD ACTIVE PRODUCTS
    all_products = db.list_products(active_only=True)
    inventory_categories = ['powder','drinking cups','food cups','square plates','takeout boxes big','takeout boxes small','lids flat','lids dome']

    # Case-insensitive inventory category filtering
    products = [p for p in all_products if str(p['category']).split(" | Custom:", 1)[0].strip().casefold() not in inventory_categories]
    left, right = st.columns([1.35, 1], gap='large')
    
    # LEFT COLUMN: AVAILABLE PRODUCTS
    with left:
        st.markdown('#### Available products')
        selected_catalog_tab = st.radio(
            "Filter Department Menu Context",
            ["✨ All Catalog", "🍔 Foods (Grubs)", "🥤 Drinks (Gulps)"],
            horizontal=True,
            label_visibility="collapsed",
            key="cashier_department_filter_tabs"
        )
        st.write("")

        query = st.text_input('Find a product', placeholder='Search product name or code')
        # Apply filter modifications based on active selection loops
        if query.strip():
            match = product_tree.search(query.strip())
            if match and match['category'] not in inventory_categories:
                base_shown = [match]
            else:
                base_shown = [p for p in products if query.casefold() in (p['name'] + ' ' + p['code']).casefold()]
        else:
            base_shown = products
            
        # Added 'int(p['stock']) > 0' to hide any items with 0 stock automatically
        if selected_catalog_tab == "🍔 Foods (Grubs)":
            shown = [p for p in base_shown if not db.get_product_sizes(p['id']) and int(p['stock']) > 0]
        elif selected_catalog_tab == "🥤 Drinks (Gulps)":
            shown = [p for p in base_shown if bool(db.get_product_sizes(p['id'])) and int(p['stock']) > 0]
        else:
            shown = [p for p in base_shown if int(p['stock']) > 0]

        if not shown:
            st.info('No matching active products with available stock found.')
            
        # PRODUCT DISPLAY
        for start_idx in range(0, len(shown), 2):
            cols = st.columns(2)
            for col, p in zip(cols, shown[start_idx:start_idx + 2]):
                with col:
                    # LOAD PRODUCT SIZES
                    sizes = db.get_product_sizes(p['id'])
                    is_drink = bool(sizes)
                    # CLEAN CATEGORY AND CUSTOM SIZE LABEL
                    if " | Custom:" in p['category']:
                        cat_parts = p['category'].split(" | Custom:", 1)
                        display_cat_clean = str(cat_parts[0]).strip()
                        custom_size_text = str(cat_parts[1]).strip()
                    else:
                        display_cat_clean = str(p['category']).strip()
                        custom_size_text = ""
                    
                    # DISPLAY PRODUCT PRICE
                    if is_drink:
                        price_parts = []
                        for size, price in sizes.items():
                            if int(size) == 99 and custom_size_text:
                                price_parts.append(f"{custom_size_text} {money(price)}")
                            elif int(size) == 99:
                                price_parts.append(f"Custom Size {money(price)}")
                            else:
                                price_parts.append(f"{size} oz {money(price)}")
                        price_line = ' · '.join(price_parts)
                    else:
                        price_line = money(p['price_cents'])
                    
                    # CASHIER PRODUCT CARD
                    card_html = load_html_template('product_card.html', name=str(p['name']), product_name=str(p['name']),
                        code=str(p['code']), category=str(display_cat_clean), price=str(price_line), price_line=str(price_line), stock=str(int(p['stock'])))
                    st.markdown(card_html,unsafe_allow_html=True)
                    
                    # ADD TO CART FORM
                    with st.form(f"add_cart_{p['id']}"):
                        size_oz = None
                        unit_price = p['price_cents']
                        chosen_customizations = []
                        addon_premium = 0
                        
                        # Set up the text variables safely
                        prod_name_lower = p['name'].lower()
                        cat_lower = display_cat_clean.lower()
                        is_milktea = 'milktea' in cat_lower or 'milktea' in prod_name_lower
                        is_milkshake = 'milkshake' in cat_lower or 'milkshake' in prod_name_lower
                        is_lemonade_slushie = 'slushie' in cat_lower or 'slushie' in prod_name_lower
                        is_lemonade = ('lemonade' in cat_lower or 'lemonade' in prod_name_lower) and not is_lemonade_slushie
                        is_coffee = 'coffee' in cat_lower or 'coffee' in prod_name_lower
                        is_float_or_juice = 'float' in cat_lower or 'float' in prod_name_lower or 'juice' in cat_lower or 'juice' in prod_name_lower

                        with st.popover(" Customize", use_container_width=True, disabled=p['stock'] < 1):
                            if is_drink:
                                st.markdown("##### 🥤 Sizing Configuration")
                                available_sizes = list(sizes.keys())
                                def size_label_formatter(z):
                                    if int(z) == 99 and custom_size_text: return custom_size_text
                                    return f"{z} oz"
                                size_oz = st.radio('Choose Size:', available_sizes, format_func=size_label_formatter, horizontal=True, key=f"size_{p['id']}")
                                unit_price = sizes[size_oz]
                                st.caption(f"Base Size Price: {money(unit_price)}")
                                
                                # Sinker logic inside popover window
                                if not is_float_or_juice:
                                    st.markdown("##### Sinker Options")
                                    if is_milktea:
                                        mt_sinker = st.radio("Sinkers:", ["Pearls", "None"], horizontal=True, key=f"radio_sink_{p['id']}")
                                        if mt_sinker == "None": chosen_customizations.append("❌ NO PEARLS")
                                    elif is_milkshake:
                                        ms_sinker = st.radio("Sinkers:", ["Pearls", "Nata", "None"], horizontal=True, key=f"radio_sink_{p['id']}")
                                        if ms_sinker == "None": chosen_customizations.append("❌ NO SINKERS")
                                    elif is_lemonade:
                                        lem_sinker = st.radio("Sinkers:", ["Rainbow Jelly", "None"], horizontal=True, key=f"radio_sink_{p['id']}")
                                        if lem_sinker == "None": chosen_customizations.append("❌ NO RAINBOW JELLY")
                                    elif is_lemonade_slushie:
                                        sl_sinker = st.radio("Sinkers:", ["Nata", "None"], horizontal=True, key=f"radio_sink_{p['id']}")
                                        if sl_sinker == "None": chosen_customizations.append("❌ NO NATA")
                                    elif is_coffee:
                                        cf_sinker = st.radio("Sinkers:", ["Coffee Jelly", "None"], horizontal=True, key=f"radio_sink_{p['id']}")
                                        if cf_sinker == "None": chosen_customizations.append("❌ NO COFFEE JELLY")

                                # Add-ons options inside popover window
                                st.markdown("##### Topping Add-ons (+₱5)")
                                sk_c1, sk_c2 = st.columns(2)
                                with sk_c1: add_extra_pearl = st.checkbox("Extra Pearls", key=f"add_p_{p['id']}")
                                with sk_c2: add_extra_nata = st.checkbox("Extra Nata", key=f"add_n_{p['id']}")
                                with sk_c1: add_extra_jelly = st.checkbox("Extra Jelly", key=f"add_j_{p['id']}")
                                with sk_c2: add_extra_coffee_jelly = st.checkbox("Extra C.Jelly", key=f"add_c_{p['id']}")
                                
                                if add_extra_pearl: chosen_customizations.append("➕ Extra Pearls"); addon_premium += 500
                                if add_extra_nata: chosen_customizations.append("➕ Extra Nata"); addon_premium += 500
                                if add_extra_jelly: chosen_customizations.append("➕ Extra Jelly"); addon_premium += 500
                                if add_extra_coffee_jelly: chosen_customizations.append("➕ Extra Coffee Jelly"); addon_premium += 500
                                unit_price += addon_premium

                            st.markdown("##### To Note:")
                            if is_drink: note_hint = "e.g., 50% Sugar, Less Ice"
                            elif "fries" in display_cat_clean.lower() or "snack" in display_cat_clean.lower(): note_hint = "e.g., BBQ, Cheese"
                            else: note_hint = "e.g., Syrup, Whipped Cream..."

                            custom_note = st.text_input('Special Notes', placeholder=note_hint, key=f"note_input_{p['id']}").strip()
                            qty = st.number_input('Quantity to Order', min_value=1, max_value=max(1, int(p['stock'])), value=1, step=1, key=f"qty_{p['id']}", disabled=p['stock'] < 1)
                            
                            st.write("")
                            add = st.form_submit_button('🛒 Add to cart', use_container_width=True, disabled=p['stock'] < 1)
                    # PROCESS ADD TO CART
                    if add:
                        try:
                            if qty > p['stock']: 
                                raise ValueError(f"Only {p['stock']} unit(s) are in stock.")
                            
                            # 1. Check size variables on-the-fly
                            if size_oz and int(size_oz) == 99 and custom_size_text: 
                                size_display_name = custom_size_text
                            elif size_oz: 
                                size_display_name = f"{size_oz} oz"
                            else: 
                                size_display_name = ''
                            checkout_product_payload = p.copy()
                           
                            if size_oz and int(size_oz) == 99 and custom_size_text:
                                checkout_product_payload['name'] = f"{p['name']} ({custom_size_text})"
                                
                            final_notes_list = chosen_customizations.copy()
                            if custom_note: 
                                final_notes_list.append(custom_note)
                            combined_customizations = '; '.join(final_notes_list)
                                
                            st.session_state.cart.add(
                                checkout_product_payload, 
                                int(qty), 
                                size_oz=size_oz, 
                                unit_price_cents=unit_price, 
                                customizations=combined_customizations
                            )
                            st.rerun()
                        except Exception as e: safe_error(e)

    # SHOPPING CART
    with right:
        st.markdown('#### Shopping cart')
        cart = st.session_state.cart
        items = cart.items()
        if not items:
            st.info('Your cart is empty. Add a product to begin.')
        else:
            for item in items:
                with st.container(border=True):
                    size_val = item.get('size_oz')
                    size_lbl = ""
                    
                    if size_val is not None:
                        if int(size_val) == 99:
                            try:
                                master_product_row = db.get_product_by_id(item['id']) if hasattr(db, 'get_product_by_id') else item
                                master_category_str = str(master_product_row.get('category', item.get('category', '')))
                                if " | Custom:" in master_category_str:
                                    size_lbl = master_category_str.split(" | Custom:", 1)[1].strip()
                                else:
                                    size_lbl = "Custom"
                            except Exception:
                                size_lbl = "Custom"
                        else:
                            size_lbl = f"{size_val} oz"
                        
                    display_title = f"**{item['name']} ({size_lbl})**" if size_lbl else f"**{item['name']}**"
                    options_label = f"\n\n<small style='color:gray;'>{item['customizations']}</small>" if item.get('customizations') else ""
                    
                    c1, c2 = st.columns(2)
                    c1.markdown(f"{display_title}{options_label}\n\n{money(item['unit_price_cents'])} each", unsafe_allow_html=True)
                    c2.markdown(f"**{money(item['subtotal_cents'])}**")

                    qcol, rmcol = st.columns([2, 1])
                    new_q = qcol.number_input('Quantity',min_value=1,max_value=1000000,value=int(item['quantity']),step=1,
                        key=(f"cart_q_{item['product_id']} {item.get('size_oz') or 'std'} {abs(hash(str(item.get('customizations', ''))))}"))
                    if qcol.button('Update',key=(f"update_{item['product_id']} {item.get('size_oz') or 'std'} {abs(hash(str(item.get('customizations',''))))}")):
                        try:
                            p = db.get_product(item['product_id'])
                            if not p or not p['active']:
                                raise ValueError('This product is no longer available. Remove it from the cart.')
                            if int(new_q) > p['stock']:
                                raise ValueError(f"Only {p['stock']} unit(s) are in stock.")
                            cart.set_quantity(item['product_id'],int(new_q),item.get('size_oz'),item.get('customizations', ''))
                            st.rerun()
                        except Exception as e:
                            safe_error(e)
                    if rmcol.button('Remove',
                        key=(f"remove_{item['product_id']} {item.get('size_oz') or 'std'} {abs(hash(str(item.get('customizations',''))))}")):
                        cart.remove(item['product_id'],item.get('size_oz'),item.get('customizations', ''))
                        st.rerun()
        st.divider()
        st.markdown(f"### Total: {money(cart.total_cents())}")
        with st.form('checkout_form'):
            customer_name = st.text_input('Customer name *',placeholder='e.g. John Doe')
            priority_level = st.select_slider('Priority level',
                options=[1, 2, 3],
                value=3,
                format_func=lambda x: {
                    1: '1 · Urgent',
                    2: '2 · High',
                    3: '3 · Normal'
                }[x]
            )

            cashier_label = st.text_input('Cashier name (optional)',value='Cashier')
            confirm = st.form_submit_button('Confirm sale',type='primary',use_container_width=True)
            if confirm:
                try:
                    if not customer_name.strip(): 
                        raise ValueError("Please enter the customer name.")
                    
                    if hasattr(st.session_state.cart, '_items'):
                        raw_cart_values = list(st.session_state.cart._items.values())
                    else:
                        raw_cart_values = list(st.session_state.cart.items())
                    
                    if not raw_cart_values:
                        raise ValueError("Your checkout shopping basket is completely empty.")
                    
                    determined_cashier = cashier_label.strip() if cashier_label else "Cashier"
                        
                    sale = db.checkout(raw_cart_values, cashier_label=determined_cashier)
                    st.session_state.last_sale = sale

                    order_details_list = []
                    for item in raw_cart_values:
                        size_val = item.get('size_oz')
                        size_suffix = ""
                        if size_val is not None:
                            if int(size_val) == 99:
                                size_suffix = " (Custom Size)"
                            else:
                                size_suffix = f" ({size_val} oz)"
                                
                        order_details_list.append(f"{item['quantity']}x {item.get('name', 'Product')}{size_suffix}")
                    order_details_str = ", ".join(order_details_list)
                    
                    db.add_order(
                        customer_name=customer_name.strip(), 
                        details=order_details_str, 
                        priority=int(priority_level)
                    )

                    # Clear shopping cart basket 
                    st.session_state.cart.clear()
                    st.session_state.global_toast = {
                        "msg": f"🏁 TRANSACTION SUCCESSFUL: Sale checkout processed for '{customer_name.strip()}'! Total Paid: {money(sale['total_cents'])}.",
                        "bg": "#2e7d32",  
                        "icon": "💰"
                    }
                    st.rerun()
                except Exception as e:
                    st.error(f"🔍 INTERNAL SYSTEM ERROR DETECTED: {str(e)}")


elif mode == 'Cashier' and page == 'Pickup Queue Priority':
    st.subheader('Cashier - Order Priority & Pickup Queue')
    st.caption('Orders are automatically added to this priority queue upon finalizing sales at checkout.')
    heap = rebuild_heap()
    next_order = heap.peek()
    if next_order:
        st.markdown("### 🔔 Next Priority Order in Queue")
        st.info(f"Order #{next_order.order_id} — {next_order.payload['customer_name']} |Priority Level: {next_order.priority} | Details: {next_order.payload['details']}")
        if st.button('Mark Next Order Completed', type='primary'):
            try:
                db.update_order_status(next_order.order_id, 'Completed')
                st.session_state.global_toast = {
                    "msg": f"🔔 QUEUE ACTION: Order #{next_order.order_id} for '{next_order.payload['customer_name']}' has been marked as COMPLETED and cleared from active lane.",
                    "bg": "#1565c0",  # Information Blue
                    "icon": "🏁"
                }
                
                db.log_activity('Cashier', 'Queue Cleared', f"Order #{next_order.order_id} marked complete")
                logging.info(f"Order #{next_order.order_id} marked complete.")
                st.rerun()
            except Exception as e: 
                st.exception(e)


    else:
        st.success('No pending pickup orders in queue.')
    st.markdown("#### All Pending Pickup Orders")
    all_orders = db.list_orders()
    if all_orders:
        st.dataframe(
            pd.DataFrame([
                {'Order #': o['id'],'Customer': o['customer_name'],'Details': o['details'],'Priority': o['priority'],'Status': o['status'],'Created': o['created_at'].replace('T', ' ')[:16]}
                for o in all_orders]),use_container_width=True,hide_index=True)
    else:
        st.info('No pickup orders found in the database.')

elif mode == 'Cashier' and page == 'Sales History':
    st.subheader('📜 Sales Transaction History')
    
    # ⚡ PART A: DYNAMIC LAST TRANSACTION ANCHOR
    sale = st.session_state.get('last_sale')
    if sale:
        with st.expander("⚡ Just Checked Out (Last Transaction Details)", expanded=True):
            tx_id = sale.get('transaction_id')
            st.success(f"Receipt Reference: Sale #{tx_id} · Recorded at {sale['created_at'].replace('T', ' ')[:16]}")
            
            # Sub-metrics display card
            sm1, sm2 = st.columns(2)
            sm1.metric('Total Paid Amount', money(sale['total_cents']))
            sm2.markdown("<br>", unsafe_allow_html=True) # visual spacing buffer
            
            try:
                items_details = db.transaction_items(tx_id)
                if items_details:
                    st.dataframe(
                        pd.DataFrame([
                            {
                                'Code': x.get('product_code', '—'),
                                'Product': x.get('product_name', '—'),
                                'Size': f"{x['size_oz']} oz" if x.get('size_oz') else '—',
                                'Options/Notes': x.get('customizations', '—'),
                                'Qty': x.get('quantity', 1),
                                'Unit Price': money(x.get('unit_price_cents', 0)),
                                'Subtotal': money(x.get('subtotal_cents', 0))
                            } for x in items_details
                        ]), use_container_width=True, hide_index=True
                    )
            except Exception as e:
                st.caption(f"Could not render layout items: {str(e)}")
    
    st.divider()

    # 📜 PART B: RECENT SALES & HISTORY SEARCH
    st.markdown("#### 🔍Audit Search")
    st.caption('Search completed sales and cashier actions. Records remain saved in SQLite after the app is closed.')
    h1, h2 = st.columns([1, 2])
    cashier_history_search = h1.text_input('Search sales / actions', placeholder='sale number, product, customer')
    cashier_role_filter = h2.selectbox('History type', ['All cashier activity', 'Completed sales', 'Queue actions'])
    sales = db.transaction_history()
    term = cashier_history_search.casefold().strip()
    
    if cashier_role_filter != 'Queue actions':
        sale_rows = []
        for r in sales:
            details = db.transaction_items(r['id'])
            searchable = (
                f"{r['id']} {r['cashier_label']} "
                + ' '.join(
                    x['product_name'] + ' '
                    + x.get('customizations', '')
                    for x in details
                )
            )
            if not term or term in searchable.casefold():
                sale_rows.append({
                    'Sale #': r['id'],
                    'Date/time': r['created_at'].replace('T', ' ')[:16],
                    'Cashier': r['cashier_label'],
                    'Items': ', '.join(
                        f"{x['quantity']}x {x['product_name']}"
                        for x in details
                    ),
                    'Total': money(r['total_cents'])
                })
        st.markdown('##### Completed sales')
        if sale_rows:
            st.dataframe(pd.DataFrame(sale_rows), use_container_width=True, hide_index=True)
        else:
            st.info('No sales match this search.')
            
    if cashier_role_filter != 'Completed sales':
        from datetime import datetime, timedelta
        
        activity = db.activity_history('Cashier', cashier_history_search, limit=500)
        st.markdown('##### Cashier actions and queue history')
        if activity:
            formatted_activities = []
            for r in activity:
                raw_time = r['created_at'].replace('T', ' ')[:19]
            
                try:
                    dt_obj = datetime.strptime(raw_time[:16], "%Y-%m-%d %H:%M")
                    if "15:" in raw_time and r.get('action') in ['Queue Cleared', 'Queue Action']:
                        dt_obj += timedelta(hours=8)
                        
                    display_time = dt_obj.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    display_time = raw_time[:16]
                formatted_activities.append({
                    'Date/time': display_time,
                    'Action': r['action'],
                    'Details': r['details']
                })
                
            st.dataframe(pd.DataFrame(formatted_activities), use_container_width=True, hide_index=True)
        else:
            st.info('No cashier activity matches this search.')


# =========================================================================
# INVENTORY MANAGER WORKSPACE MODULES
# =========================================================================
elif mode == 'Inventory Manager' and page == 'Stock Overview':
    st.subheader('Inventory stock overview')
    products = db.list_products()
    search = st.text_input('Search products by name, code, or category')
    term = search.casefold().strip()
    shown = [p for p in products if term in (p['name'] + ' ' + p['code'] + ' ' + p['category']).casefold()]
    if shown:
        st.dataframe(
            pd.DataFrame([
                {
                    'Code': p['code'],
                    'Product': p['name'],
                    'Category': p['category'],
                    'Stock': p['stock'],
                    'Low-stock threshold': p['low_stock_threshold'],
                    'Status': (
                        'Active' if p['active'] else 'Inactive'
                    ),
                    'Stock alert': (
                        'LOW'
                        if p['stock'] <= p['low_stock_threshold']
                        else 'OK'
                    )} for p in shown]),use_container_width=True,hide_index=True)
    else:
        st.info('No product records yet. Admin must add menu products first.')
    st.caption('Inventory Manager monitors physical stock. Admin owns menu names, categories, and prices.')

elif mode == 'Inventory Manager' and page == 'Restock Products':
    st.subheader('Inventory Stock Adjustments')
    active_products = db.list_products(active_only=True)
    if not active_products:
        st.info('There are no active menu products to manage. Admin must add products first.')
    else:
        choices = {(f"{p['code']} — {p['name']} (current stock: {p['stock']})"): p for p in active_products}
        itab1, itab2, itab3 = st.tabs(["➕ Add Stock (Restock)","➖ Deduct Stock (Waste/Spoilage)","✏️ Direct Edit (Stock Audit)"])
        # ADD STOCK
        with itab1:
            st.markdown("#### Record Incoming Deliveries")
            with st.form('inventory_manager_restock',clear_on_submit=True):
                selected = st.selectbox('Product to Restock',list(choices.keys()),index=None,placeholder="Select product...",key='restock_add_select')
                quantity = st.number_input('Quantity received (+)',min_value=1,value=1,step=1,key='restock_add_qty')
                submit = st.form_submit_button('Save Restock Entry',type='primary')
                if submit:  
                    if selected is None: st.error("Please select a valid menu product from the dropdown box first.")
                    else:
                        try:
                            item = choices[selected]
                            new_total = item['stock'] + int(quantity)
                            db.update_product_stock_direct(item['id'], new_total, actor="Inventory Manager")
                            
                            st.session_state.global_toast = {
                                "msg": f"📈 STOCK INCREASED: Added +{int(quantity)} units to '{item['name']}'. New Balance: {new_total} units.",
                                "bg": "#2e7d32",  
                                "icon": "➕"
                            }
                            db.log_activity('Inventory Manager', 'Stock Added', f"{item['code']} · +{int(quantity)} units")
                            st.rerun()
                        except Exception as exc: safe_error(exc)

      # DEDUCT STOCK
        with itab2:
            st.markdown("#### Record Spoilage, Damage, or Waste")
            with st.form('inventory_manager_deduct',clear_on_submit=True):
                selected = st.selectbox('Product to Deduct From',list(choices.keys()),index=None,placeholder="Select product...",key='restock_sub_select')
                quantity = st.number_input('Quantity lost / damaged (-)',min_value=1,value=1,step=1,key='restock_sub_qty')
                reason = st.text_input('Reason for Deduction *',placeholder=('e.g., Expired ingredients, ''Spilled drink, Counter error')).strip()
                submit = st.form_submit_button('Confirm Stock Deduction',type='primary')
                if submit:
                    if selected is None: 
                        st.error("Please select a valid menu product from the dropdown box first.")
                    else:
                        item = choices[selected]
                        # 🟢 FIX: Block deductions immediately if the product is already out of stock
                        if int(item['stock']) <= 0:
                            st.error(f"🔴 Inventory Conflict: Cannot deduct stock from '{item['name']}' because current stock is already 0 units.")
                        elif not reason: 
                            st.error("A validation reason is required to process inventory deductions.")
                        elif int(quantity) > item['stock']: 
                            st.error(f"Cannot deduct {quantity} units. Product only has {item['stock']} units currently in stock.")
                        else:
                            try:
                                new_total = item['stock'] - int(quantity)
                                db.update_product_stock_direct(item['id'], new_total, actor=f"Inventory Manager ({reason})")
                                
                                st.session_state.global_toast = {
                                    "msg": f"📉 STOCK DEDUCTED: Removed -{int(quantity)} units from '{item['name']}' due to '{reason}'. New Balance: {new_total} units.",
                                    "bg": "#ef6c00",  
                                    "icon": "⚠️"
                                }
                                
                                db.log_activity('Inventory Manager', 'Stock Deducted', f"{item['code']} · -{int(quantity)} units ({reason})")
                                st.rerun()
                            except Exception as exc: safe_error(exc)

        # DIRECT STOCK AUDIT
        with itab3:
            st.markdown("#### Direct Physical Inventory Audit Override")
            st.caption("Use this only during physical inventory audits to calibrate exact database counts.")
            selected = st.selectbox('Select Product to Audit',list(choices.keys()), index=None,placeholder="Select product...",key='restock_audit_select')
            if selected:
                item = choices[selected]
                st.info(f"Current recorded database level for {item['name']} is {item['stock']} units.")
                with st.form('inventory_manager_audit'):
                    exact_stock = st.number_input('Actual physical count on shelf',min_value=0,value=int(item['stock']),step=1)
                    submit = st.form_submit_button('Overwrite Stock Balance Value',type='primary')
                    if submit:
                        try:
                            db.update_product_stock_direct(item['id'], int(exact_stock), actor="Inventory Manager Audit Override")
                            st.session_state.global_toast = {
                                "msg": f"📐 COUNTS CALIBRATED: Overwrote '{item['name']}' stock balance level to exactly {int(exact_stock)} units.",
                                "bg": "#1565c0",  
                                "icon": "✏️"
                            }
                            db.log_activity('Inventory Manager', 'Stock Count Audited', f"{item['code']} · Overwrote to {int(exact_stock)}")
                            logging.info(f"SUCCESS [INVENTORY AUDIT]: Override executed for '{item['name']}' to {int(exact_stock)}.")
                            st.rerun()
                        except Exception as exc: safe_error(exc)

elif mode == 'Inventory Manager' and page == 'Dashboard':
    st.subheader('📦 Inventory Operations Dashboard')
    all_products = db.list_products(active_only=True)
    if not all_products:
        st.info("No active catalog items found.Dashboard analytics will populate once items are added.")
    else:
        out_of_stock = [p for p in all_products if p['stock'] == 0]
        low_stock = [p for p in all_products if 0 < p['stock'] <= p['low_stock_threshold']]
        overstocked = [p for p in all_products if p['stock'] >= p.get('high_stock_threshold', 50) ]
        st.markdown("##### 🚨 Stock Urgency Indicators")
        g1, g2, g3, g4 = st.columns(4)
        g1.metric("Total Items Managed",len(all_products))
        g2.metric("Out of Stock 🛑",len(out_of_stock), delta="CRITICAL FIX" if out_of_stock else "All Available",delta_color="inverse" if out_of_stock else "normal")
        g3.metric("Low-Stock Warning ⚠️",len(low_stock),delta="Needs Restock" if low_stock else "Levels Safe",delta_color="inverse" if low_stock else "normal")
        g4.metric("Overstocked Rows 📦",len(overstocked),delta="Freeze Orders" if overstocked else "Within Limits",delta_color="off" if overstocked else "normal")
        st.divider()
        left_dash, right_dash = st.columns(2)
        with left_dash:
            st.markdown("#### 🚨 Fast Action Restock Checklist")
            urgency_list = sorted(out_of_stock + low_stock,key=lambda x: x['stock'])
            if not urgency_list:
                st.success("🎉 Excellent! All inventory shelf counts match healthy threshold levels.")
            else:
                checklist_data = []
                for item in urgency_list:
                    status = ("🔴 OUT OF STOCK" if item['stock'] == 0 else "⚠️ LOW STOCK"
                    )
                    checklist_data.append({
                        "Code": item['code'],
                        "Product Name": item['name'],
                        "Current Stock": item['stock'],
                        "Alert Threshold": item['low_stock_threshold'],
                        "Urgency": status
                    })
                st.dataframe(
                    pd.DataFrame(checklist_data),
                    use_container_width=True,
                    hide_index=True
                )
        with right_dash:
            st.markdown("#### 📦 Excess Inventory Trackers")
            if not overstocked:
                st.success("🎉 Healthy! No catalog rows exceed maximum high-stock parameters.")
            else:
                # Creates a clean dropdown drawer inside the right column summary tree
                with st.expander("🔍 View Overstocked Product Details", expanded=True):
                    st.markdown("<b style='color:#b05000; font-size:13px;'>The following menu products exceed high-stock limits:</b>", unsafe_allow_html=True)
                    st.write("")
                    for item in overstocked:
                        st.error(
                            f"📦 **{item['code']}** · {item['name']}  \n"
                            f"↳ *Current Stock:* `{item['stock']} units` (High threshold limit: `{item.get('high_stock_threshold', 50)}`)"
                        )
            st.divider()
            st.markdown("#### 📉 Recent Stock Movements & Audits")
            try:
                with db.connection() as conn:
                    recent_movements = conn.execute('''SELECT m.quantity_change, m.reason, p.name FROM inventory_movements m JOIN products p ON m.product_id = p.id ORDER BY m.created_at DESC LIMIT 6 ''').fetchall()
                if recent_movements:
                    for move in recent_movements:
                        qty = move['quantity_change']
                        st.markdown(f"{'🟢' if qty > 0 else '🔴'} {'+' if qty > 0 else ''}{qty} units — {move['name']} \n"
                            f"Reason: {move['reason']}", unsafe_allow_html=True)
                else:
                    st.info("No database movements logged yet.")
            except Exception:
                st.caption("Unable to stream live adjustment logs.")

st.divider()
st.caption('Gulps & Grubs POS · SQLite is the persistent source of truth. Prices stored as integer centavos')
