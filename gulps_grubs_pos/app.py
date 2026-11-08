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
            cashier_options = ['Dashboard', 'New Sale', 'Pickup Queue Priority', 'Last Transaction', 'Sales History']
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
        classification = st.radio('Product Classification *',['Foods (Grubs)','Drinks (Gulps)','Others (Combo/Meal Plan)'],horizontal=True)
        st.markdown("---")
        try:
            db_products = db.list_products(active_only=False)
            drink_keywords = ['milktea', 'milkshake', 'shake', 'lemonade','slushie', 'slush', 'coffee', 'float', 'frappe','drink', 'beverage', 'juice', 'tea', 'brew', 'gulp']
            food_cats = set()
            drink_cats = set()
            combo_cats = set()

            for p in db_products:
                if not p['category']:
                    continue
                clean_cat = p['category'].split(" | Custom:", 1)[0].strip()
                clean_cat_lower = clean_cat.lower()
                is_drink_cat = any(dk in clean_cat_lower for dk in drink_keywords)
                is_combo_cat = ('combo' in clean_cat_lower or 'promo' in clean_cat_lower or 'bundle' in clean_cat_lower)
                if is_drink_cat:
                    drink_cats.add(clean_cat)
                elif is_combo_cat:
                    combo_cats.add(clean_cat)
                else:
                    food_cats.add(clean_cat)

            if classification == 'Drinks (Gulps)':
                existing_saved_cats = sorted(list(drink_cats))

            elif classification == 'Others (Combo/Meal Plan)':
                existing_saved_cats = sorted(list(combo_cats))

            else:
                existing_saved_cats = sorted(list(food_cats))
        except Exception:
            existing_saved_cats = []

        # Setup real-time string pool memory mapping
        text_state_key = f"raw_typing_buffer_{classification}"
        if text_state_key not in st.session_state:
            st.session_state[text_state_key] = ""
        options_pool = existing_saved_cats.copy()
        user_typing = st.session_state[text_state_key].strip()
        if user_typing and user_typing not in options_pool:
            options_pool.insert(0, user_typing)

        # MAIN FORM BLOCK CONTAINER
        with st.form( key=f'add_product_submit_form_{classification}',clear_on_submit=True):
            name = st.text_input('Product name *',placeholder='Enter product name',key=f'f_name_{classification}').strip()
            category = ""
            size_prices = {}
            price = 0.0
            
            category = st.text_input(
                'Category *', 
                placeholder="Type your category name here (e.g., Waffle, Streetfood)...", 
                key=f'f_cat_text_input_lane_{classification}').strip()
                
            def parse_and_format_price(raw_text):
                if not raw_text:
                    return 0.0
                clean_digits = raw_text.replace('₱', '').strip()
                try:
                    return float(clean_digits)
                except ValueError:
                    return 0.0
            # PATH 1: FOODS
            if classification == 'Foods (Grubs)':
                price_input = st.text_input('Price (₱) *',placeholder='0.00',key=f'f_price_{classification}').strip()
                price = parse_and_format_price(price_input)

            # PATH 2: DRINKS
            elif classification == 'Drinks (Gulps)':
                st.caption('Configure your cup sizes and pricing:')
                use8 = st.checkbox('Offer 8 oz',value=False,key=f'{classification}_use_8')
                price8 = 0.0
                if use8:
                    price8 = st.number_input('8 oz price (₱)',min_value=1.0,step=5.0,format='%.2f',key=f'{classification}_val_8')
                
                use12 = st.checkbox('Offer 12 oz',value=True,key=f'{classification}_use_12')
                price12 = 0.0
                if use12:
                    price12 = st.number_input('12 oz price (₱)',min_value=1.0,step=5.0,format='%.2f',key=f'{classification}_val_12')

                use16 = st.checkbox('Offer 16 oz',value=True,key=f'{classification}_use_16')
                price16 = 0.0
                if use16:
                    price16 = st.number_input('16 oz price (₱)',min_value=1.0,step=5.0,format='%.2f',key=f'{classification}_val_16')
                
                st.divider()
                st.markdown("##### 🥤 Other / Custom Size Profile")
                use_custom = st.checkbox('Offer a different custom size',value=False,key=f'{classification}_use_custom')
                custom_label = ""
                custom_price = 0.0

                if use_custom:
                    c_size_col, c_price_col = st.columns(2)
                    with c_size_col:
                        custom_label = st.text_input('Custom Size Description Label',placeholder='e.g., 22oz, 1-Liter',key=f'{classification}_lbl_custom').strip()

                    with c_price_col:
                        custom_price = st.number_input('Custom Size Price (₱)',min_value=1.0,step=5.0,format='%.2f',key=f'{classification}_val_custom')
                        
                if use8 and price8 > 0:
                    size_prices[8] = cents_from_peso(price8)

                if use12 and price12 > 0:
                    size_prices[12] = cents_from_peso(price12)

                if use16 and price16 > 0:
                    size_prices[16] = cents_from_peso(price16)

                if use_custom and custom_label and custom_price > 0:
                    size_prices[99] = cents_from_peso(custom_price)
                    category = f"{category} | Custom:{custom_label}"

            # PATH 3: OTHERS
            elif classification == 'Others (Combo/Meal Plan)':

                price_input = st.text_input('Price (₱) *',placeholder='0.00',key=f'f_price_{classification}').strip()
                price = parse_and_format_price(price_input)

            st.divider()
            low_stock_threshold = st.number_input('Low-stock alert boundary count',min_value=0,value=5,step=1)
            high_stock_threshold = st.number_input('High-stock alert boundary count',min_value=0,value=50,step=1)

            submit_form_btn = st.form_submit_button('Add product to Catalog',type='primary',use_container_width=True)

        # SUBMIT BUTTON
        if submit_form_btn:
            clean_name = name.strip()
            clean_category = category.strip()
            
            # Isolate strings for high-precision field-level checks
            name_audit = clean_name.lower()
            category_audit = clean_category.lower()
            combined_audit = f"{name_audit} {category_audit}"

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
                'milkshake', 'slushie', 'macchiato', 'espresso', 'capuccino', 'lemonade', 'soda', 'pop'
            ]

            prohibited_keywords = ['person', 'human', 'people', 'teacher', 'student', 'animal', 'object', 'thing']

            try:
                existing_product_names = [str(item['name']).lower().strip() for item in db.list_products(active_only=True)]
            except Exception: existing_product_names = []

            is_spam_text = has_consecutive_repetitions(combined_audit, max_allowed=3)
            is_nonsense_word = looks_like_gibberish(combined_audit)
            contains_junk = any(junk in combined_audit for junk in prohibited_keywords)

            # --- ✨ FIXED: STRICTOR FIELD-LEVEL CONTEXT OVERLAP ENFORCEMENT ---
            if classification == 'Drinks (Gulps)':
                # Enforce that the category field itself must represent a liquid asset layout row
                is_valid_context = any(word in category_audit for word in drink_dictionary)
                mismatch_error = f"Selected 'Drinks (Gulps)' but entered a non-beverage category '{clean_category}'."
            elif classification == 'Foods (Grubs)':
                # Enforce that a drink keyword cannot occupy a food category description lane
                has_drink_trigger_in_food = any(word in category_audit for word in drink_dictionary) or any(word in name_audit for word in drink_dictionary)
                is_valid_context = any(word in category_audit for word in food_dictionary) and not has_drink_trigger_in_food
                mismatch_error = f"Selected 'Foods (Grubs)' but entered a drink or non-food asset configuration layer."
            else:
                is_valid_context = any(word in combined_audit for word in food_dictionary + drink_dictionary)
                mismatch_error = "Entered an invalid combo meal category context description."

            # Master execution gatekeeping path tree
            if not clean_name: st.error("Product name is required.")
            elif not clean_category: st.error("Category structure specification is required.")
            elif clean_name.lower() in existing_product_names: st.error(f"🔴 Catalog Conflict: A product named '{clean_name}' already exists!")
            elif is_spam_text or is_nonsense_word: st.error("🔴 Invalid Entry: Input contains keyboard spam or gibberish text patterns.")
            elif contains_junk: st.error("🔴 Context Validation Alert: Junk classifications (person, human, object) are strictly blocked.")
            
            # --- ✨ EVALUATES DYNAMICALLY FILTERED SEPARATIONS ---
            elif not is_valid_context:
                st.error(f"🔴 Context/Classification Mismatch: {mismatch_error} Please allocate your item correctly.")
                
            elif classification in ['Foods (Grubs)', 'Others (Combo/Meal Plan)'] and price <= 0.0: st.error("🔴 Validation Error: Price field is required and must be greater than ₱0.00.")
            elif classification == 'Drinks (Gulps)' and not size_prices: st.error("🔴 Validation Error: Sizing prices are required. Enable and price at least one size option.")
            else:
                try:
                    price_cents = cents_from_peso(price)
                    generated_code = db.generate_product_code(classification)
                    starting_stock = 0
                    db.add_product(
                        code=generated_code, name=clean_name, category=clean_category, price_cents=price_cents, 
                        stock=starting_stock, threshold=low_stock_threshold,
                        size_prices=size_prices if classification == 'Drinks (Gulps)' else None)    
                
                    # ✨ SUCCESS TRANSACTION PRINT RECORD
                    display_price = f"₱{price:,.2f}" if classification != 'Drinks (Gulps)' else "Sizing Profile Configured"
                    success_msg = f"🟢 SUCCESS [ADMIN]: Product '{clean_name}' successfully added to catalog under category '{clean_category}' at {display_price} (Assigned Code: {generated_code})."
                    st.success(success_msg)
                    db.log_activity('Admin', 'Product Created', f"{generated_code} · {clean_name}")
                    logging.info(success_msg)
                    st.rerun()
                except Exception as e: safe_error(e)
                    
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
                    standard_sizes = {k: v for k, v in current_sizes.items() if k in (8, 12, 16)}
                    if not standard_sizes:
                        standard_sizes = {12: p['price_cents'],16: p['price_cents']}
                    size_cols = st.columns(len(standard_sizes))
                    for size_idx, size in enumerate(sorted(standard_sizes.keys())):
                        size_inputs[size] = size_cols[size_idx].number_input(f'{size} oz price (₱)',min_value=0.0,value=float(standard_sizes[size] / 100),step=5.0,format='%.2f',key=f'form_price_{p["id"]}_{size}')
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
                save_changes = st.button('Save All Product Details',type='primary',key=f"unified_save_btn_{p['id']}")
                if save_changes:
                    if not new_name or not new_cat: st.error("Product name and category definitions cannot be left blank.")
                    else:
                        try: 
                            db.update_product(p['id'], p['code'], new_name, new_cat, int(new_base_price_cents), int(new_threshold))
                            if is_a_drink and updated_sizes is not None:
                                db.set_product_sizes(p['id'], updated_sizes)
                            else:
                                with db.connection() as clean_conn:
                                    clean_conn.execute("DELETE FROM product_sizes WHERE product_id = ?", (p['id'],))
                            
                            # ✨ SUCCESS TRANSACTION PRINT RECORD
                            success_msg = f"📝 SUCCESS [ADMIN]: Product '{p['code']}' details updated successfully (New Name: '{new_name}', New Category: '{new_cat}')."
                            st.success(success_msg)
                            db.log_activity('Admin', 'Product Updated', f"{p['code']} · {new_name}")
                            logging.info(success_msg)
                            st.rerun()
                        except Exception as e: safe_error(e)
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
                                # ✨ SUCCESS TRANSACTION PRINT RECORD
                                success_msg = f"🗑️ SUCCESS [ADMIN]: Product '{p['code']} — {p['name']}' was permanently removed from the master database catalog files."
                                st.success(success_msg)
                                db.log_activity('Admin', 'Product Deleted', f"{p['code']} · {p['name']}")
                                logging.info(success_msg)
                                st.rerun()
                            else: st.error(msg)
                        except Exception as e: safe_error(e)
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
                                    'Active' if prod['active'] else 'Inactive'
                                    )
                                    }
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
        st.dataframe(
            pd.DataFrame([
                {
                    'Date/time': r['created_at'].replace('T', ' ')[:16],
                    'Mode': r['actor_mode'],
                    'Action': r['action'],
                    'Details': r['details']
                }
                for r in rows
            ]),use_container_width=True,hide_index=True)
        st.download_button('Download activity history CSV',pd.DataFrame(rows).to_csv(index=False).encode('utf-8'),'activity_history.csv','text/csv')
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
    all_products = db.list_products(active_only=True)
    inventory_categories = [
        'powder','drinking cups','food cups','square plates','takeout boxes big',
        'takeout boxes small','lids flat','lids dome']
    products = [p for p in all_products if p['category'] not in inventory_categories]
    left, right = st.columns([1.35, 1], gap='large')
    with left:
        st.markdown('#### Available products')
        query = st.text_input('Find a product',placeholder='Search product name or code')
        if query.strip():
            match = product_tree.search(query.strip())
            if match and match['category'] not in inventory_categories:
                shown = [match]
            else:
                shown = [p for p in products if query.casefold() in (p['name'] + ' ' + p['code']).casefold()]
        else:
            shown = products
        if not shown:
            st.info('No matching active products.')
        for start_idx in range(0, len(shown), 2):
            cols = st.columns(2)
            for col, p in zip(cols, shown[start_idx:start_idx + 2]):
                with col:
                    sizes = db.get_product_sizes(p['id'])
                    is_drink = bool(sizes)
                    if " | Custom:" in p['category']:
                        cat_parts = p['category'].split(" | Custom:", 1)
                        display_cat_clean = str(cat_parts[0]).strip()
                        custom_size_text = str(cat_parts[1]).strip()
                    else:
                        display_cat_clean = str(p['category']).strip()
                        custom_size_text = ""
                    if is_drink:
                        price_parts = []
                        for size, price in sizes.items():
                            if int(size) == 99 and custom_size_text:
                                price_parts.append(f"{custom_size_text} {money(price)}")
                            else:
                                price_parts.append(f"{size} oz {money(price)}")
                        price_line = ' · '.join(price_parts)
                    else:
                        price_line = money(p['price_cents'])
                    card_html = load_html_template('product_card.html',name=str(p['name']),product_name=str(p['name']),code=str(p['code']),
                        category=str(display_cat_clean),price=str(price_line),price_line=str(price_line),stock=str(int(p['stock'])))
                    st.markdown(card_html,unsafe_allow_html=True)
                    with st.form(f"add_cart_{p['id']}"):
                        size_oz = None, 
                        unit_price = p['price_cents']
                    if is_drink:
                        available_sizes = list(sizes.keys())
                        def size_label_formatter(z):
                            if int(z) == 99 and custom_size_text:
                                return custom_size_text
                            return f"{z} oz"
                        size_oz = st.radio(
                            'Choose cup size',available_sizes,format_func=size_label_formatter,horizontal=True,key=f"size_{p['id']}")
                        unit_price = sizes[size_oz]
                        st.caption(f"Selected size price: {money(unit_price)}")
                        
                        chosen_customizations = []
                        addon_premium = 0
                        prod_name_lower = p['name'].lower()
                        cat_lower = display_cat_clean.lower()
                        is_milktea = ('milktea' in cat_lower or 'milktea' in prod_name_lower)
                        is_milkshake = ('milkshake' in cat_lower or 'milkshake' in prod_name_lower)
                        is_lemonade_slushie = ('slushie' in cat_lower or 'slushie' in prod_name_lower)
                        is_lemonade = (
                            ('lemonade' in cat_lower or 'lemonade' in prod_name_lower)
                            and not is_lemonade_slushie
                        )
                        is_coffee = ('coffee' in cat_lower or 'coffee' in prod_name_lower)
                        if is_drink:
                            st.markdown("### Sinker Selection")
                            if is_milktea:
                                mt_sinker = st.radio("Included Sinker Options",
                                    ["Include Pearls (Default)","No Sinkers (None)"],horizontal=True,key=f"radio_sink_{p['id']}")
                                if mt_sinker == "No Sinkers (None)":
                                    chosen_customizations.append("❌ NO PEARLS")
                            elif is_milkshake:
                                ms_sinker = st.radio("Included Sinker Options",
                                    ["Include Pearls & Nata (Default)","No Sinkers (None)"],horizontal=True,key=f"radio_sink_{p['id']}")
                                if ms_sinker == "No Sinkers (None)":
                                    chosen_customizations.append("❌ NO SINKERS")
                            elif is_lemonade:
                                lem_sinker = st.radio("Included Sinker Options",
                                    ["Include Rainbow Jelly (Default)","No Sinkers (None)"],horizontal=True,key=f"radio_sink_{p['id']}")
                                if lem_sinker == "No Sinkers (None)":
                                    chosen_customizations.append("❌ NO RAINBOW JELLY")
                            elif is_lemonade_slushie:
                                sl_sinker = st.radio("Included Sinker Options",
                                    ["Include Nata (Default)","No Sinkers (None)"],horizontal=True,key=f"radio_sink_{p['id']}")
                                if sl_sinker == "No Sinkers (None)":
                                    chosen_customizations.append("❌ NO NATA")                                
                            elif is_coffee:
                                cf_sinker = st.radio("Included Sinker Options",
                                    ["Include Coffee Jelly (Default)","No Sinkers (None)"],horizontal=True,key=f"radio_sink_{p['id']}")
                                if cf_sinker == "No Sinkers (None)":
                                    chosen_customizations.append("❌ NO COFFEE JELLY")
                            st.markdown("### Add-ons")
                            sk1, sk2, sk3, sk4 = st.columns(4)
                            add_extra_pearl = sk1.checkbox("Extra Pearls (+₱5)",key=f"add_p_{p['id']}")
                            add_extra_nata = sk2.checkbox("Extra Nata (+₱5)",key=f"add_n_{p['id']}")
                            add_extra_jelly = sk3.checkbox("Extra Jelly (+₱5)",key=f"add_j_{p['id']}")
                            add_extra_coffee_jelly = sk4.checkbox("Extra Coffee Jelly (+₱5)",key=f"add_c_{p['id']}")

                            if add_extra_pearl:
                                chosen_customizations.append("➕ Extra Pearls")
                                addon_premium += 500

                            if add_extra_nata:
                                chosen_customizations.append("➕ Extra Nata")
                                addon_premium += 500

                            if add_extra_jelly:
                                chosen_customizations.append("➕ Extra Jelly")
                                addon_premium += 500

                            if add_extra_coffee_jelly:
                                chosen_customizations.append("➕ Extra Coffee Jelly")
                                addon_premium += 500
                            unit_price += addon_premium
                        if is_drink:
                            note_hint = ("e.g., 50% Sugar, Less Ice, Severe Lactose Allergy")
                        elif ("fries" in display_cat_clean.lower() or "snack" in display_cat_clean.lower()):
                            note_hint = ("e.g., Barbecue, Cheese, Sour Cream, No Salt")
                        elif ("donut" in display_cat_clean.lower()or "waffle" in display_cat_clean.lower() or "dessert" in display_cat_clean.lower()):
                            note_hint = ("e.g., Chocolate Syrup, Maple,Whipped Cream")
                        else:
                            note_hint = ("e.g., Add notes, flavors, combos, or allergy alerts here...")

                        custom_note = st.text_input('Special Notes / Customization',placeholder=note_hint,key=f"note_input_{p['id']}").strip()
                        qty = st.number_input('Qty',min_value=1,max_value=max(1, int(p['stock'])),value=1,step=1,key=f"qty_{p['id']}",disabled=p['stock'] < 1)
                        add = st.form_submit_button('Add to cart',use_container_width=True,disabled=p['stock'] < 1)
                        if add:
                            try:
                                if qty > p['stock']:
                                    raise ValueError(f"Only {p['stock']} unit(s) are in stock.")
                                if size_oz and int(size_oz) == 99 and custom_size_text:
                                    size_display_name = custom_size_text
                                elif size_oz:
                                    size_display_name = f"{size_oz} oz"
                                else:
                                    size_display_name = ''
                                final_notes_list = chosen_customizations.copy()
                                if custom_note:
                                    final_notes_list.append(custom_note)
                                combined_customizations = '; '.join(
                                    final_notes_list
                                )
                                st.session_state.cart.add(p,int(qty),size_oz=size_oz,unit_price_cents=unit_price,customizations=combined_customizations)
                                size_label = (f" ({size_display_name})" if size_oz else '')
                                option_label = (f" · Options: '{combined_customizations}'" if combined_customizations else '')
                                st.success(f"Added {qty} × {p['name']} {size_label}{option_label}.")
                                st.rerun()
                            except Exception as e:
                                safe_error(e)
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
                    if item.get('size_oz'):
                        size_lbl = ("22 oz" if int(item['size_oz']) == 99 else f"{item['size_oz']} oz")
                    else:
                        size_lbl = ""
                    display_title = (f"{item['name']} ({size_lbl})" if size_lbl else f"{item['name']}")
                    options_label = (f"\n\n{item['customizations']}" if item.get('customizations') else "")
                    c1, c2 = st.columns([2, 1])
                    c1.markdown(f"{display_title}{options_label}\n\n"f"{money(item['unit_price_cents'])} each",unsafe_allow_html=True)
                    c2.markdown(f"{money(item['subtotal_cents'])}")
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

            cashier_name = st.text_input('Cashier name (optional)',value='Cashier')
            confirm = st.form_submit_button('Confirm sale',type='primary',use_container_width=True)
            if confirm:
                try:
                    if not customer_name.strip(): raise ValueError("Please enter the customer name.")
                    sale = db.checkout(cart.items(), cashier_label.strip() or 'Cashier')
                    st.session_state.last_sale = sale
            
                    order_details_str = ", ".join([f"{item['quantity']}x {item['name']}" for item in cart.items()])
                    db.add_order(customer_name.strip(), order_details_str, int(priority_level))
                    cart.clear()
                    
                    # ✨ SUCCESS TRANSACTION PRINT RECORD
                    success_msg = f"💰 SUCCESS [CASHIER]: Sale Checkout #{sale['transaction_id']} processed successfully! Bill Total: {money(sale['total_cents'])} received. Ticket dispatched to kitchen pickup queue."
                    st.success(success_msg)
                    db.log_activity('Cashier', 'Sale Completed', f"Receipt #{sale['transaction_id']} · Total: {money(sale['total_cents'])}")
                    logging.info(success_msg)
                    st.rerun()
                except Exception as e: safe_error(e)

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
                
                # ✨ SUCCESS TRANSACTION PRINT RECORD
                success_msg = f"🔔 SUCCESS [KITCHEN/CASHIER]: Pickup Order #{next_order.order_id} for customer '{next_order.payload['customer_name']}' successfully marked as COMPLETED and cleared from active lane."
                st.success(success_msg)
                db.log_activity('Cashier', 'Queue Cleared', f"Order #{next_order.order_id} marked complete")
                logging.info(success_msg)
                st.rerun()
            except Exception as e: safe_error(e)
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

elif mode == 'Cashier' and page == 'Last Transaction':
    st.subheader('Last Transaction')
    sale = st.session_state.last_sale
    if not sale:
        st.info('Complete a sale in New Sale to display details here.')
    else:
        st.success(f"Sale #{sale['transaction_id']} {sale['created_at'].replace('T', ' ')[:16]}")
        st.metric('Total Paid',money(sale['total_cents']))
        st.dataframe(
            pd.DataFrame([
                {
                    'Code': x['code'],
                    'Product': x['name'],
                    'Qty': x['quantity'],
                    'Unit price': money(x['unit_price_cents']),
                    'Subtotal': money(x['subtotal_cents'])
                } for x in sale['items']]),use_container_width=True,hide_index=True)

elif mode == 'Cashier' and page == 'Sales History':
    st.subheader('📜 Sales Transaction History')
    st.caption('Search completed sales and cashier actions. Records remain saved in SQLite after the app is closed.')
    h1, h2 = st.columns([1, 2])
    cashier_history_search = h1.text_input('Search sales / actions',placeholder='sale number, product, customer')
    cashier_role_filter = h2.selectbox('History type',['All cashier activity','Completed sales','Queue actions'])
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
        st.markdown('#### Completed sales')
        if sale_rows:
            st.dataframe(
                pd.DataFrame(sale_rows),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info('No sales match this search.')
    if cashier_role_filter != 'Completed sales':
        activity = db.activity_history(
            'Cashier',
            cashier_history_search,
            limit=500
        )
        st.markdown('#### Cashier actions and queue history')
        if activity:
            st.dataframe(
                pd.DataFrame([
                    {
                        'Date/time': r['created_at'].replace('T', ' ')[:16],
                        'Action': r['action'],
                        'Details': r['details']
                    }
                    for r in activity
                ]),
                use_container_width=True,
                hide_index=True
            )
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
                            
                            # ✨ SUCCESS TRANSACTION PRINT RECORD
                            success_msg = f"📦 SUCCESS [INVENTORY]: Incoming delivery logged for product '{item['name']}' ({item['code']}). Added +{int(quantity)} units. New shelf balance value: {new_total}."
                            st.success(success_msg)
                            db.log_activity('Inventory Manager', 'Stock Added', f"{item['code']} · +{int(quantity)} units")
                            logging.info(success_msg)
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
                    if selected is None: st.error("Please select a valid menu product from the dropdown box first.")
                    elif not reason: st.error("A validation reason is required to process inventory deductions.")
                    else:
                        try:
                            item = choices[selected]
                            if int(quantity) > item['stock']: st.error(f"Cannot deduct {quantity} units. Product only has {item['stock']} units currently in stock.")
                            else:
                                new_total = item['stock'] - int(quantity)
                                db.update_product_stock_direct(item['id'], new_total, actor=f"Inventory Manager ({reason})")
                                
                                # ✨ SUCCESS TRANSACTION PRINT RECORD
                                success_msg = f"📉 SUCCESS [INVENTORY]: Stock deduction processed for product '{item['name']}' ({item['code']}). Removed -{int(quantity)} units due to: '{reason}'. Current balance: {new_total}."
                                st.success(success_msg)
                                db.log_activity('Inventory Manager', 'Stock Deducted', f"{item['code']} · -{int(quantity)} units ({reason})")
                                logging.info(success_msg)
                                st.rerun()
                        except Exception as exc: safe_error(exc)
        # DIRECT STOCK AUDIT
        with itab3:
            st.markdown("#### Direct Physical Inventory Audit Override")
            st.caption("Use this only during physical inventory audits to calibrate exact database counts.")
            selected = st.selectbox('Select Product to Audit',list(choices.keys()), index=None,placeholder="Select product...",key='restock_audit_select')
            if selected:
                item = choices[selected]
                st.info(f"Current recorded database level for{item['name']} is {item['stock']} units.")
                with st.form('inventory_manager_audit'):
                    exact_stock = st.number_input('Actual physical count on shelf',min_value=0,value=int(item['stock']),step=1)
                    submit = st.form_submit_button('Overwrite Stock Balance Value',type='primary')
                    if submit:
                        try:
                            db.update_product_stock_direct(item['id'], int(exact_stock), actor="Inventory Manager Audit Override")
                            
                            # ✨ SUCCESS TRANSACTION PRINT RECORD
                            success_msg = f"✏️ SUCCESS [INVENTORY AUDIT]: Manual override executed for product '{item['name']}' ({item['code']}). Database calibrated and locked to match physical stock count value of: exactly {int(exact_stock)} units."
                            st.success(success_msg)
                            db.log_activity('Inventory Manager', 'Stock Count Audited', f"{item['code']} · Overwrote to {int(exact_stock)}")
                            logging.info(success_msg)
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
            st.markdown("#### 📉 Recent Stock Movements & Audits")
            try:
                with db.connection() as conn:
                    recent_movements = conn.execute('''SELECT m.quantity_change,m.reason, p.nameFROM inventory_movements m JOIN products p ON m.product_id = p.id ORDER BY m.created_at DESC LIMIT 6 ''').fetchall()
                if recent_movements:
                    for move in recent_movements:
                        qty = move['quantity_change']
                        st.markdown(f"{'🟢' if qty > 0 else '🔴'} {'+' if qty > 0 else ''}{qty} units — {move['name']} \n"
                            f"Reason: {move['reason']}",unsafe_allow_html=True)
                else:
                    st.info("No database movements logged yet.")
            except Exception:
                st.caption("Unable to stream live adjustment logs."
                )
    st.divider()
    st.caption('Gulps & Grubs POS · SQLite is the persistent source of truth. Prices stored as integer centavos')
