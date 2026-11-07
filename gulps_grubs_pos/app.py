from datetime import date, datetime, time, timedelta
from pathlib import Path
import logging
import sqlite3
import streamlit as st
import pandas as pd
from data_structures import LinkedListCart, AVLTree, MinHeap, HeapEntry
import database as db


APP_DIR=Path(__file__).resolve().parent
LOG_PATH=APP_DIR/'pos.log'
logging.basicConfig(filename=LOG_PATH, level=logging.ERROR, format='%(asctime)s %(levelname)s %(message)s')

st.set_page_config(page_title='Gulps & Grubs | POS', page_icon='🥤', layout='wide', initial_sidebar_state='collapsed')

def money(cents): return f"₱{int(cents)/100:,.2f}"
def safe_error(exc):
    logging.exception('Application operation failed')
    if isinstance(exc,(ValueError,sqlite3.IntegrityError)): st.error(str(exc))
    else: st.error('Something went wrong while saving your changes. No incomplete transaction was committed. Check pos.log for technical details.')
def cents_from_peso(value): return int(round(float(value)*100))

def load_html_template(_filename, **values):
    """Load a small HTML fragment from templates/ and safely fill placeholders."""
    from html import escape
    # Fixed typo: uses _filename which will never collide with product properties
    template_path = APP_DIR / 'templates' / _filename
    content = template_path.read_text(encoding='utf-8')
    for key, value in values.items():
        content = content.replace('{{ ' + key + ' }}', escape(str(value)))
    return content

def rebuild_tree():
    tree=AVLTree()
    for p in db.list_products(active_only=True): tree.insert(p['code'],p)
    tree.validate()
    return tree

def rebuild_heap():
    heap=MinHeap()
    for o in db.list_orders(pending_only=True):
        heap.push(HeapEntry(int(o['priority']),int(o['sequence_no']),int(o['id']),o))
    return heap

st.markdown(f'<style>{(APP_DIR / "style.css").read_text(encoding="utf-8")}</style>', unsafe_allow_html=True)

try:
    db.init_db()
except Exception as e:
    st.error('Could not initialize the database. Check folder permissions and the application log.')
    logging.exception('Database initialization failed')
    st.stop()

if 'cart' not in st.session_state: st.session_state.cart=LinkedListCart()
if 'last_sale' not in st.session_state: st.session_state.last_sale=None
if 'mode' not in st.session_state: st.session_state.mode='Admin'

st.markdown(load_html_template('brand_banner.html'), unsafe_allow_html=True)

# Branded horizontal header inspired by the supplied storefront navigation reference.
# The logo, workspace switcher, and page links share one orange header bar.
with st.container(key='site_header'):
    logo_col, brand_col, mode_col, page_col = st.columns([1.05, 1.8, 1.55, 5.2], vertical_alignment='center', gap='small')
    with logo_col:
        st.image(str(APP_DIR / 'brand_logo.jpg'), width=118)
    with brand_col:
        st.markdown(load_html_template('site_brand.html'), unsafe_allow_html=True)
    with mode_col:
        st.markdown(load_html_template('nav_label.html', label='WORKSPACE'), unsafe_allow_html=True)
        mode=st.radio('Workspace',['Admin','Cashier','Inventory Manager'],index=['Admin','Cashier','Inventory Manager'].index(st.session_state.get('mode_choice','Admin')) if st.session_state.get('mode_choice','Admin') in ['Admin','Cashier','Inventory Manager'] else 0,
                      horizontal=True,key='mode_choice',label_visibility='collapsed')
    st.session_state.mode=mode
    with page_col:
        st.markdown(load_html_template('nav_label.html', label='NAVIGATION'), unsafe_allow_html=True)
        if mode=='Admin':
            page=st.radio('Admin navigation',['Dashboard','Product Management','Sales History','Activity History'],
                          horizontal=True,key='admin_page',label_visibility='collapsed')
        elif mode=='Cashier':
            page=st.radio('Cashier navigation',['New Sale','Pickup Queue Priority','Last Transaction','Sales History'],
                          horizontal=True,key='cashier_page',label_visibility='collapsed')
        else:
            page=st.radio('Inventory navigation',['Dashboard','Stock Overview','Restock Products'],
                          horizontal=True,key='inventory_page',label_visibility='collapsed')
st.caption('Demo mode selector only — it is not secure authentication.')

# Rebuild the AVL tree from SQLite at each run, keeping the database as source of truth.
try: product_tree=rebuild_tree()
except Exception as e:
    safe_error(e); st.stop()
#==================
### ADMIN MODE 
#==================
if mode=='Admin' and page=='Dashboard':
    st.subheader('Business overview')
    today=date.today(); start=datetime.combine(today,time.min).isoformat(); end=datetime.combine(today+timedelta(days=1),time.min).isoformat()
    summary=db.sales_summary(start,end)
    all_products=db.list_products(active_only=True)
    low=[p for p in all_products if p['stock']<=p['low_stock_threshold']]
    high = [p for p in all_products if p['stock'] >= p['high_stock_threshold']]
    a,b,c,d,e=st.columns(5)
    a.metric('Today’s revenue',money(summary['revenue_cents']))
    b.metric('Completed sales',summary['transactions'])
    c.metric('Active products',len(all_products))
    d.metric('Low-stock alerts',len(low),delta='Needs attention' if low else 'Stock looks good',delta_color='inverse' if low else 'normal')
    e.metric('High-stock alerts',len(high),delta='Overstocked' if high else 'Stock looks good', delta_color='off' if high else 'normal',help='Products at or above their Admin-defined high-stock threshold.'
)

    st.caption('Revenue is the total value of recorded sales, not profit. Product costs and operating expenses are not tracked.')
    
    left,right=st.columns([1.15,1])
    with left:
        st.markdown('#### Low-stock watch')
        if low:
            st.dataframe(pd.DataFrame([{'Code':p['code'],'Product':p['name'],'Stock':p['stock'],'Alert at':p['low_stock_threshold']} for p in low]),use_container_width=True,hide_index=True)
        else: st.success('No active products are at or below their low-stock threshold.')

        st.markdown('#### High-stock watch')
        if high:
            st.dataframe(pd.DataFrame([{'Code':p['code'],'Product':p['name'],'Stock':p['stock'],'Limit':p.get('high_stock_threshold', 0)} for p in high]),use_container_width=True,hide_index=True)
        else: st.success('No active products are at or above their high-stock threshold.')
    
    with right:
        st.markdown('#### Recent transactions')
        recent=db.transaction_history()[:6]
        if recent: st.dataframe(pd.DataFrame([{'Sale #':r['id'],'Date':r['created_at'].replace('T',' '),'Total':money(r['total_cents'])} for r in recent]),use_container_width=True,hide_index=True)
        else: st.info('Completed sales will appear here.')
    st.markdown('#### Sales over the last 7 days')
    daily=[]
    for i in range(6,-1,-1):
        day=today-timedelta(days=i); s=datetime.combine(day,time.min).isoformat(); e=datetime.combine(day+timedelta(days=1),time.min).isoformat(); sm=db.sales_summary(s,e)
        daily.append({'Date':day.strftime('%b %d'),'Revenue (₱)':sm['revenue_cents']/100})
    st.bar_chart(pd.DataFrame(daily).set_index('Date'))

elif mode=='Admin' and page=='Product Management':
    st.subheader('Product Catalog Management')
    tab1, tab2, tab3 = st.tabs(['Add product', 'Edit / Delete', 'View Catalog'])
    
    with tab1:
        classification = st.radio('Product Classification *', 
            ['Foods (Grubs)', 'Drinks (Gulps)', 'Others (Combo/Meal Plan)'], 
            horizontal=True
        )
        st.markdown("---")
        name = st.text_input('Product name *', placeholder='Enter product name', key='prod_name_input').strip()
        category = ""
        size_prices = {}
        price = 0.0
        
        # --- PATH 1: FOODS ---
        if classification == 'Foods (Grubs)':
            category = st.text_input('Category *', placeholder='e.g. Streetfood, Donut and Waffles').strip()
            price = st.number_input('Price (₱)', min_value=0.0, step=5.0, format='%.2f')
            
        # --- PATH 2: DRINKS ---
        elif classification == 'Drinks (Gulps)':
            base_category = st.text_input('Category Name *', placeholder='e.g. Milkshake, Float, Milktea').strip()
            
            st.caption('Configure your cup sizes and pricing:')
            s8, s12, s16 = st.columns(3)
            
            with s8:
                use8 = st.checkbox('Offer 8 oz', value=False, key=f'{classification}_use_8')
                price8 = st.number_input('8 oz price (₱)', min_value=0.0, step=5.0, format='%.2f', disabled=not use8, key=f'{classification}_val_8')
            with s12:
                use12 = st.checkbox('Offer 12 oz', value=True, key=f'{classification}_use_12')
                price12 = st.number_input('12 oz price (₱)', min_value=0.0, step=5.0, format='%.2f', disabled=not use12, key=f'{classification}_val_12')
            with s16:
                use16 = st.checkbox('Offer 16 oz', value=True, key=f'{classification}_use_16')
                price16 = st.number_input('16 oz price (₱)', min_value=0.0, step=5.0, format='%.2f', disabled=not use16, key=f'{classification}_val_16')
            
            st.divider()
            st.markdown("##### 🥤 Other / Custom Size Profile")
            use_custom = st.checkbox('Offer a different custom size', value=False, key=f'{classification}_use_custom')
            
            c_size_col, c_price_col = st.columns(2)
            with c_size_col:
                custom_label = st.text_input('Custom Size Description Label', placeholder='e.g., 22oz, 1-Liter', disabled=not use_custom, key=f'{classification}_lbl_custom').strip()
            with c_price_col:
                custom_price = st.number_input('Custom Size Price (₱)', min_value=0.0, step=5.0, format='%.2f', disabled=not use_custom, key=f'{classification}_val_custom')

            if use8: size_prices[8] = cents_from_peso(price8)
            if use12: size_prices[12] = cents_from_peso(price12)
            if use16: size_prices[16] = cents_from_peso(price16)

            if use_custom and custom_label:
                size_prices[99] = cents_from_peso(custom_price)
                category = f"{base_category} | Custom:{custom_label}"
            else:
                category = base_category
        
            if size_prices:
                price = next(iter(size_prices.values())) / 100
                
        # --- PATH 3: OTHERS ---
        elif classification == 'Others (Combo/Meal Plan)':
            category = st.text_input('Category *', placeholder='e.g. Combo Meal, Promo Bundle').strip()
            price = st.number_input('Price (₱)', min_value=0.0, step=5.0, format='%.2f')

        # System Administration Settings & Threshold Counts
        st.divider()
        low_stock_threshold = st.number_input('Low-stock alert boundary count', min_value=0, value=5, step=1)
        high_stock_threshold = st.number_input('High-stock alert boundary count', min_value=0, value=50, step=1)
        
        # Submit Button Action Block
        if st.button('Add product to Catalog', type='primary'):
            if not name:
                st.error("Product name is required.")
            elif not category:
                st.error("Category structure specification is required.")
            elif classification == 'Drinks (Gulps)' and not size_prices:
                st.error("Please enable at least one size configuration option for drink catalog items.")
            else:
                try:
                    price_cents = cents_from_peso(price)
                    generated_code = db.generate_product_code()
                    starting_stock = 0 # Default to 0, Managed via Inventory Manager Workspace
                    
                    db.add_product(
                        code=generated_code,
                        name=name, 
                        category=category, 
                        price_cents=price_cents, 
                        stock=starting_stock,
                        threshold=low_stock_threshold,
                        size_prices=size_prices if classification == 'Drinks (Gulps)' else None
                    )
                    st.success(f"Successfully registered '{name}' under '{category}' (Code: {generated_code})!")
                    st.rerun()
                except Exception as e:
                    safe_error(e)

        with tab2:
            st.subheader("Edit or Delete Product")
            
            # Load all products using your uniform list call
            all_products = db.list_products(active_only=False)
            if not all_products:
                st.info("No active products available to edit.")
            else:
                labels = {f"{prod['code']} — {prod['name']} {'(Inactive)' if not prod['active'] else ''}": prod for prod in all_products}
                selected_label = st.selectbox('Select product to modify', list(labels.keys()), key='edit_select')
                p = labels[selected_label]
                
                if p['active']:
                    # Pull saved size details up front
                    current_sizes = db.get_product_sizes(p['id'])
                    
                    # Parse custom descriptions out of the category string
                    orig_category = p['category']
                    is_custom_drink = " | Custom:" in orig_category
                    if is_custom_drink:
                        base_cat_name, custom_sz_label = orig_category.split(" | Custom:", 1)
                    else:
                        base_cat_name = orig_category
                        custom_sz_label = ""

                    st.markdown("#### Product Details")
                    ec1, ec2 = st.columns(2)
                    ec1.text_input('Product code (automatically assigned)', value=p['code'], disabled=True)
                    new_name = ec2.text_input('Product name', value=p['name']).strip()
                    
                    # Identify if item structural layout tracks as a drink type
                    is_a_drink = is_custom_drink or any(d in base_cat_name.lower() for d in ['milkshake', 'float', 'milktea', 'drink', 'coffee', 'juice', 'beverage'])
                    
                    size_inputs = {}
                    if is_a_drink:
                        new_base_cat = st.text_input('Category Name *', value=base_cat_name).strip()
                        
                        st.markdown('**Available drink size pricing**')
                        standard_sizes = {k: v for k, v in current_sizes.items() if k in (8, 12, 16)}
                        
                        if not standard_sizes:
                            standard_sizes = {12: p['price_cents'], 16: p['price_cents']}
                            
                        size_cols = st.columns(len(standard_sizes))
                        for size_idx, size in enumerate(sorted(standard_sizes.keys())):
                            size_inputs[size] = size_cols[size_idx].number_input(
                                f'{size} oz price (₱)', 
                                min_value=0.0, 
                                value=float(standard_sizes[size]/100), 
                                step=5.0, 
                                format='%.2f', 
                                key=f'form_price_{p["id"]}_{size}'
                            )
                            
                        st.divider()
                        st.markdown('**🥤 Other / Custom Size Configuration**')
                        has_custom = st.checkbox("Enable a different custom size profile for this product", value=is_custom_drink, key=f"form_has_cust_{p['id']}")
                        
                        c_col1, c_col2 = st.columns(2)
                        edit_custom_label = c_col1.text_input("Custom Size Description Label", value=custom_sz_label, placeholder="e.g., 22oz, 1-Liter", disabled=not has_custom, key=f"form_lbl_cust_{p['id']}").strip()
                        edit_custom_price = c_col2.number_input("Custom Size Price (₱)", min_value=0.0, value=float(current_sizes.get(99, 0.0) / 100), step=5.0, format='%.2f', disabled=not has_custom, key=f"form_val_cust_{p['id']}")
                        
                        new_cat = f"{new_base_cat} | Custom:{edit_custom_label}" if (has_custom and edit_custom_label) else new_base_cat
                        
                        # FIX: Read baseline sizes directly as raw cents integers from the DB without multiplying again
                        updated_sizes = {int(sz): int(cents) for sz, cents in current_sizes.items()}
                        
                        # Update standard sizes ONLY if they match what's on the screen layout
                        for sz, pr_val in size_inputs.items():
                            updated_sizes[int(sz)] = cents_from_peso(pr_val)
                        
                        # Add or update the custom size (99) profile independently
                        if has_custom and edit_custom_label:
                            updated_sizes[99] = cents_from_peso(edit_custom_price)
                        elif 99 in updated_sizes:
                            del updated_sizes[99]
                        
                        new_base_price_cents = next(iter(updated_sizes.values()), p['price_cents'])
                    else:
                        # Standard Food Processing Workflow Paths
                        new_cat = st.text_input('Category', value=p['category']).strip()
                        new_price_val = st.number_input('Price (₱)', min_value=0.0, value=float(p['price_cents']/100), step=5.0, format='%.2f')
                        new_base_price_cents = cents_from_peso(new_price_val)
                        updated_sizes = None

                    st.divider()
                    new_threshold = st.number_input('Low-stock alert at', min_value=0, max_value=1000000, value=int(p['low_stock_threshold']), step=1)
                    
                    save_changes = st.button('Save All Product Details', type='primary', key=f"unified_save_btn_{p['id']}")

                    if save_changes:
                        if not new_name or not new_cat:
                            st.error("Product name and category definitions cannot be left blank.")
                        else:
                            try: 
                                # 1. Update Core Blueprint Specifications
                                db.update_product(p['id'], p['code'], new_name, new_cat, int(new_base_price_cents), int(new_threshold))
                                
                                # 2. Update Multi-size Arrays if mapping drink layout structures
                                if is_a_drink and updated_sizes:
                                    db.set_product_sizes(p['id'], updated_sizes)
                                    
                                db.log_activity('Admin', 'Product updated', f"{p['code']} · {new_name}")
                                st.success('Product and all matching sizing configurations saved successfully!')
                                st.rerun()
                            except Exception as e: 
                                safe_error(e)

                   # --- Permanent Force Hard-Delete Interface Module ---
                    st.divider()
                    st.error('### 🚨 DANGER ZONE: PERMANENT PURGE')
                    
                    # HTML and Bold styling fixed to render properly together
                    st.markdown(
                        "<span style='font-size: 20px;'>Clicking delete below will execute a <b style='color: #c92a2a;'>HARD DELETE</b>. "
                        "This completely wipes the item profile row from the database catalog and cannot be undone.</span>", 
                        unsafe_allow_html=True
                    )
                
                    # FIXED: Indentation aligned correctly inside your active product block
                    with st.container(key="danger_zone_box"):    
                        check_step1 = st.checkbox("Confirm: I want to permanently delete this product profile, not deactivate it.", key=f"force_del_c1_{p['id']}")
                        check_step2 = st.checkbox("Confirm: I understand this action completely removes it from all search logs.", key=f"force_del_c2_{p['id']}")
                        # Button lights up ONLY when both safety checks are explicitly marked
                        if st.button('Permanently Delete From Database', key=f"hard_purge_action_{p['id']}", type='primary', disabled=not (check_step1 and check_step2)):
                            try:
                                # Triggers the forced hard delete execution function method
                                success, msg = db.delete_product(p['id'])
                                db.log_activity('Admin', 'Forced hard delete executed', f"{p['code']} · {p['name']}")
                                
                                if success:
                                    st.success(msg)
                                    st.rerun()
                                else:
                                    st.error(msg)
                            except Exception as e:
                                safe_error(e)

    with tab3:
        # Global Catalog Search Inventory Matrix View Frames
        st.markdown("---")
        st.markdown("#### 🔍 Filter & Sort Product Catalog")
        
        # Split sorting filters into 3 clean, balanced columns
        search_col, category_col, sort_col = st.columns([2, 1.2, 1.2])
        
        with search_col:
            search = st.text_input('Search by code or product name', key='product_search_input')
            
        with category_col:
            raw_categories = {prod['category'].split(" | Custom:", 1)[0].strip() for prod in all_products}
            category_options = ["All Categories"] + sorted(list(raw_categories))
            selected_search_category = st.selectbox("Filter by Category", category_options, key='product_category_filter')
            
        with sort_col:
            # 1. Provide arrangement sorting choices
            sort_option = st.selectbox(
                "Arrange Products By",
                [
                    "Product Name (A-Z)", 
                    "Product Name (Z-A)", 
                    "Product Code (Ascending)", 
                    "Highest Price First", 
                    "Lowest Price First",
                    "Lowest Stock Level First",
                    "Highest Stock Level First"
                ],
                key='catalog_sort_selector'
            )

        # 2. Filter list by BOTH keyword search AND category selection simultaneously
        filtered_items = []
        for prod in all_products:
            matches_keyword = search.casefold() in (prod['code'] + ' ' + prod['name']).casefold()
            clean_item_category = prod['category'].split(" | Custom:", 1)[0].strip()
            matches_category = (selected_search_category == "All Categories") or (clean_item_category == selected_search_category)
            
            if matches_keyword and matches_category:
                filtered_items.append(prod)

        # 3. Dynamic Sorting Execution Logic
        if sort_option == "Product Name (A-Z)":
            filtered_items.sort(key=lambda x: x['name'].lower())
        elif sort_option == "Product Name (Z-A)":
            filtered_items.sort(key=lambda x: x['name'].lower(), reverse=True)
        elif sort_option == "Product Code (Ascending)":
            filtered_items.sort(key=lambda x: x['code'].lower())
        elif sort_option == "Highest Price First":
            filtered_items.sort(key=lambda x: x['price_cents'], reverse=True)
        elif sort_option == "Lowest Price First":
            filtered_items.sort(key=lambda x: x['price_cents'])
        elif sort_option == "Lowest Stock Level First":
            filtered_items.sort(key=lambda x: x['stock'])
        elif sort_option == "Highest Stock Level First":
            filtered_items.sort(key=lambda x: x['stock'], reverse=True)

        # 4. Render Sorted Dataframe Results Matrix
        if filtered_items:
            st.dataframe(pd.DataFrame([
                {
                    'Code': prod['code'],
                    'Product': prod['name'],
                    'Category': prod['category'].split(" | Custom:", 1)[0], # Display clean category name
                    'Price': (' · '.join(f"{size if size != 99 else 'Custom'} oz {money(price)}" for size, price in db.get_product_sizes(prod['id']).items()) if db.get_product_sizes(prod['id']) else money(prod['price_cents'])),
                    'Stock': prod['stock'],
                    'Low-stock threshold': prod['low_stock_threshold'],
                    'Status': 'Active' if prod['active'] else 'Inactive'
                } for prod in filtered_items
            ]), use_container_width=True, hide_index=True)
        else: 
            st.info('No catalog products match your search keyword or selected category filter.')

elif mode=='Admin' and page=='Sales History':
    st.subheader('Sales history')
    c1,c2=st.columns(2); start_date=c1.date_input('From date',value=date.today()-timedelta(days=30)); end_date=c2.date_input('To date',value=date.today())
    if start_date>end_date: st.error('The start date must not be after the end date.')
    else:
        start=datetime.combine(start_date,time.min).isoformat(); end=datetime.combine(end_date+timedelta(days=1),time.min).isoformat()
        rows=db.transaction_history(start,end)
        st.metric('Revenue in selected period',money(sum(r['total_cents'] for r in rows)))
        if rows:
            st.dataframe(pd.DataFrame([{'Sale #':r['id'],'Date/time':r['created_at'].replace('T',' '),'Cashier':r['cashier_label'],'Total':money(r['total_cents'])} for r in rows]),use_container_width=True,hide_index=True)
            chosen=st.selectbox('View sale details',[r['id'] for r in rows],format_func=lambda x:f"Sale #{x}")
            details=db.transaction_items(chosen)
            st.dataframe(pd.DataFrame([{'Code':x['product_code'],'Product':x['product_name'],'Size':(f"{x.get('size_oz')} oz" if x.get('size_oz') else '—'),'Options':x.get('customizations',''),'Qty':x['quantity'],'Unit price':money(x['unit_price_cents']),'Subtotal':money(x['subtotal_cents'])} for x in details]),use_container_width=True,hide_index=True)
            st.download_button('Download filtered sales CSV',pd.DataFrame([{'sale_id':r['id'],'created_at':r['created_at'],'cashier':r['cashier_label'],'total_php':r['total_cents']/100} for r in rows]).to_csv(index=False).encode('utf-8'),'sales_history.csv','text/csv')
        else: st.info('No transactions were found for the selected dates.')

elif mode=='Admin' and page=='Activity History':
    st.subheader('Admin and staff activity history')
    st.caption('Persistent audit trail for sales, queue actions, product changes, and inventory updates.')
    f1,f2=st.columns([1,2])
    role_filter=f1.selectbox('Mode', ['All','Admin','Cashier','Inventory Manager','System'])
    activity_search=f2.text_input('Search activity history',placeholder='Search product, order number, sale number, action...')
    rows=db.activity_history(role_filter,activity_search,limit=1000)
    if rows:
        st.dataframe(pd.DataFrame([{'Date/time':r['created_at'].replace('T',' '),'Mode':r['actor_mode'],'Action':r['action'],'Details':r['details']} for r in rows]),use_container_width=True,hide_index=True)
        st.download_button('Download activity history CSV',pd.DataFrame(rows).to_csv(index=False).encode('utf-8'),'activity_history.csv','text/csv')
    else:
        st.info('No activity matches this search yet.')

#===================
### CASHIER MODE
#==================
elif mode == 'Cashier' and page == 'New Sale':
    st.subheader('New Sale')
    all_products = db.list_products(active_only=True)
    
    inventory_categories = [
        'powder', 'drinking cups', 'food cups', 'square plates', 
        'takeout boxes big', 'takeout boxes small', 'lids flat', 'lids dome'
    ]

    # Only show finished menu items to cashiers
    products = [p for p in all_products if p['category'] not in inventory_categories]
    
    left, right = st.columns([1.35, 1], gap='large')
    with left:
        st.markdown('#### Available products')
        query = st.text_input('Find a product', placeholder='Search product name or code')
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
            for col, p in zip(cols, shown[start_idx:start_idx+2]):
                with col:
                    # --- FIX: Ensure these two definition lines are right here at the top! ---
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

                    # Bypasses all keyword collisions completely
                    card_html = load_html_template(
                        'product_card.html',
                        name=str(p['name']),
                        product_name=str(p['name']),
                        code=str(p['code']),
                        category=str(display_cat_clean),
                        price=str(price_line),
                        price_line=str(price_line),
                        stock=str(int(p['stock']))
                    )
                    st.markdown(card_html, unsafe_allow_html=True)

                    
                    with st.form(f"add_cart_{p['id']}"):
                        size_oz = None
                        unit_price = p['price_cents']
                        
                        if is_drink:
                            available_sizes = list(sizes.keys())
                            
                            def size_label_formatter(z):
                                if int(z) == 99 and " | Custom:" in p['category']:
                                    return p['category'].split(" | Custom:", 1)[1].strip()
                                return f"{z} oz"
                                
                            size_oz = st.radio('Choose cup size', available_sizes, format_func=size_label_formatter, horizontal=True, key=f"size_{p['id']}")
                            unit_price = sizes[size_oz]
                            st.caption(f"Selected size price: {money(unit_price)}")

                        # Open customization notes box
                        custom_note = st.text_input(
                            'Special Notes / Flavors / Allergies', 
                            placeholder='e.g., No Ice, Barbecue Fries, Egg well-done',
                            key=f"note_input_{p['id']}"
                        ).strip()

                        qty = st.number_input('Qty', min_value=1, max_value=max(1, int(p['stock'])), value=1, step=1, key=f"qty_{p['id']}", disabled=p['stock'] < 1)
                        add = st.form_submit_button('Add to cart', use_container_width=True, disabled=p['stock'] < 1)
                        
                    if add:
                        try:
                            if qty > p['stock']: 
                                raise ValueError(f"Only {p['stock']} unit(s) are in stock.")
                                
                            if size_oz and int(size_oz) == 99 and " | Custom:" in p['category']:
                                size_display_name = p['category'].split(" | Custom:", 1)[1].strip()
                            elif size_oz:
                                size_display_name = f"{size_oz} oz"
                            else:
                                size_display_name = ''
                                
                            st.session_state.cart.add(p, int(qty), size_oz=size_oz, unit_price_cents=unit_price, customizations=custom_note)
                            size_label = f" ({size_display_name})" if size_oz else ''
                            option_label = f" · Note: '{custom_note}'" if custom_note else ''
                            st.success(f"Added {qty} × {p['name']}{size_label}{option_label}.")
                            st.rerun()
                        except Exception as e: 
                            safe_error(e)

    with right:
        st.markdown('#### Shopping cart')
        cart = st.session_state.cart
        items = cart.items()
        if not items: st.info('Your cart is empty. Add a product to begin.')
        else:
            for item in items:
                with st.container(border=True):
                    c1, c2 = st.columns([2, 1]); c1.markdown(f"**{item['name']}**\n\n{money(item['unit_price_cents'])} each")
                    c2.markdown(f"**{money(item['subtotal_cents'])}**")
                    qcol, rmcol = st.columns([2, 1])
                    new_q = qcol.number_input('Quantity', min_value=1, max_value=1000000, value=int(item['quantity']), step=1, key=f"cart_q_{item['product_id']}")
                    if qcol.button('Update', key=f"update_{item['product_id']}"):
                        try:
                            p = db.get_product(item['product_id'])
                            if not p or not p['active']: raise ValueError('This product is no longer available.')
                            if int(new_q) > p['stock']: raise ValueError(f"Only {p['stock']} unit(s) are in stock.")
                            cart.set_quantity(item['product_id'], int(new_q)); st.rerun()
                        except Exception as e: safe_error(e)
                    if rmcol.button('Remove', key=f"remove_{item['product_id']}"):
                        cart.remove(item['product_id']); st.rerun()
            st.divider(); st.markdown(f"### Total: {money(cart.total_cents())}")
            
            with st.form('checkout_form'):
                customer_name = st.text_input('Customer name *', placeholder='e.g. John Doe')
                priority_level = st.select_slider(
                    'Priority level', 
                    options=[1, 2, 3], 
                    value=3, 
                    format_func=lambda x: {1: '1 · Urgent', 2: '2 · High', 3: '3 · Normal'}[x]
                )
                cashier_label = st.text_input('Cashier label (optional)', value='Cashier')
                confirm = st.form_submit_button('Confirm sale', type='primary', use_container_width=True)

            if confirm:
                try:
                    if not customer_name.strip():
                        raise ValueError("Please enter the customer name.")

                    sale = db.checkout(cart.items(), cashier_label.strip() or 'Cashier')
                    st.session_state.last_sale = sale

                    order_details_str = ", ".join([f"{item['quantity']}x {item['name']}" for item in cart.items()])
                    db.add_order(customer_name.strip(), order_details_str, int(priority_level))

                    cart.clear()
                    st.success(f"Sale #{sale['transaction_id']} completed & added to pickup queue — {money(sale['total_cents'])}.")
                    st.rerun()
                except Exception as e:
                    safe_error(e)

elif mode == 'Cashier' and page == 'Pickup Queue Priority':
    st.subheader('Cashier - Order Priority & Pickup Queue')
    st.caption('Orders are automatically added to this priority queue upon finalizing sales at checkout.')

    heap = rebuild_heap()
    next_order = heap.peek()
    
    if next_order:
        st.markdown("### 🔔 Next Priority Order in Queue")
        st.info(f"**Order #{next_order.order_id}** — {next_order.payload['customer_name']} | **Priority Level:** {next_order.priority} | **Details:** {next_order.payload['details']}")
        if st.button('Mark Next Order Completed', type='primary'):
            try:
                db.update_order_status(next_order.order_id, 'Completed')
                st.success(f'Order #{next_order.order_id} marked as completed.')
                st.rerun()
            except Exception as e: safe_error(e)
    else:
        st.success('No pending pickup orders in queue.')

    st.markdown("#### All Pending Pickup Orders")
    all_orders = db.list_orders()
    if all_orders:
        st.dataframe(
            pd.DataFrame([
                {
                    'Order #': o['id'], 
                    'Customer': o['customer_name'], 
                    'Details': o['details'], 
                    'Priority': o['priority'], 
                    'Status': o['status'], 
                    'Created': o['created_at'].replace('T', ' ')
                } for o in all_orders
            ]), 
            use_container_width=True, 
            hide_index=True
        )
    else:
        st.info('No pickup orders found in the database.')

elif mode == 'Cashier' and page == 'Last Transaction':
    st.subheader('Last Transaction')
    sale = st.session_state.last_sale
    if not sale: st.info('Complete a sale in New Sale to display details here.')
    else:
        st.success(f"Sale #{sale['transaction_id']} · {sale['created_at'].replace('T', ' ')}")
        st.metric('Total Paid', money(sale['total_cents']))
        st.dataframe(pd.DataFrame([{'Code': x['code'], 'Product': x['name'], 'Qty': x['quantity'], 'Unit price': money(x['unit_price_cents']), 'Subtotal': money(x['subtotal_cents'])} for x in sale['items']]), use_container_width=True, hide_index=True) 

elif mode=='Cashier' and page=='Sales History':
    st.subheader('Cashier history')
    st.caption('Search completed sales and cashier actions. Records remain saved in SQLite after the app is closed.')
    h1,h2=st.columns([1,2])
    cashier_history_search=h1.text_input('Search sales / actions',placeholder='sale number, product, customer')
    cashier_role_filter=h2.selectbox('History type',['All cashier activity','Completed sales','Queue actions'])
    sales=db.transaction_history()
    term=cashier_history_search.casefold().strip()
    if cashier_role_filter!='Queue actions':
        sale_rows=[]
        for r in sales:
            details=db.transaction_items(r['id'])
            searchable=f"{r['id']} {r['cashier_label']} "+' '.join(x['product_name']+' '+x.get('customizations','') for x in details)
            if not term or term in searchable.casefold():
                sale_rows.append({'Sale #':r['id'],'Date/time':r['created_at'].replace('T',' '),'Cashier':r['cashier_label'],'Items':', '.join(f"{x['quantity']}x {x['product_name']}" for x in details),'Total':money(r['total_cents'])})
        st.markdown('#### Completed sales')
        if sale_rows: st.dataframe(pd.DataFrame(sale_rows),use_container_width=True,hide_index=True)
        else: st.info('No sales match this search.')
    if cashier_role_filter!='Completed sales':
        activity=db.activity_history('Cashier',cashier_history_search,limit=500)
        st.markdown('#### Cashier actions and queue history')
        if activity: st.dataframe(pd.DataFrame([{'Date/time':r['created_at'].replace('T',' '),'Action':r['action'],'Details':r['details']} for r in activity]),use_container_width=True,hide_index=True)
        else: st.info('No cashier activity matches this search.')
#=====================
### INVENTORY MANAGER
#=====================
elif mode=='Inventory Manager' and page=='Stock Overview':
    st.subheader('Inventory stock overview')
    products=db.list_products()
    search=st.text_input('Search products by name, code, or category')
    term=search.casefold().strip()
    shown=[p for p in products if term in (p['name']+' '+p['code']+' '+p['category']).casefold()]
    if shown:
        st.dataframe(pd.DataFrame([{'Code':p['code'],'Product':p['name'],'Category':p['category'],'Stock':p['stock'],'Low-stock threshold':p['low_stock_threshold'],'Status':'Active' if p['active'] else 'Inactive','Stock alert':'LOW' if p['stock']<=p['low_stock_threshold'] else 'OK'} for p in shown]),use_container_width=True,hide_index=True)
    else:
        st.info('No product records yet. Admin must add menu products first.')
    st.caption('Inventory Manager monitors physical stock. Admin owns menu names, categories, and prices.')

elif mode=='Inventory Manager' and page=='Restock Products':
    st.subheader('Inventory Stock Adjustments')
    active_products = db.list_products(active_only=True)
    
    if not active_products:
        st.info('There are no active menu products to manage. Admin must add products first.')
    else:
        # Build the product choices dictionary mapping
        choices = {f"{p['code']} — {p['name']} (current stock: {p['stock']})": p for p in active_products}
        
        # Split features into 3 clean, operational tabs
        itab1, itab2, itab3 = st.tabs(["➕ Add Stock (Restock)", "➖ Deduct Stock (Waste/Spoilage)", "✏️ Direct Edit (Stock Audit)"])
        
        # --- TAB 1: ADD STOCK (RESTOCK) ---
        with itab1:
            st.markdown("#### Record Incoming Deliveries")
            with st.form('inventory_manager_restock', clear_on_submit=True):
                selected = st.selectbox('Product to Restock', list(choices.keys()), index=None, placeholder="Select product...", key='restock_add_select')
                quantity = st.number_input('Quantity received (+)', min_value=1, value=1, step=1, key='restock_add_qty')
                submit = st.form_submit_button('Save Restock Entry', type='primary')
                
            if submit:
                if selected is None: 
                    st.error("Please select a valid menu product from the dropdown box first.")
                else:
                    try:
                        item = choices[selected]
                        new_total = item['stock'] + int(quantity)
                        db.update_product_stock_direct(item['id'], new_total, actor="Inventory Manager")
                        db.log_activity('Inventory Manager', 'Stock Added', f"{item['code']} · +{int(quantity)} units")
                        st.success(f"Successfully added {quantity} units to '{item['name']}'! New balance: {new_total}")
                        st.rerun()
                    except Exception as exc: 
                        safe_error(exc)

        # --- TAB 2: DEDUCT STOCK (WASTE/SPOILAGE) ---
        with itab2:
            st.markdown("#### Record Spoilage, Damage, or Waste")
            with st.form('inventory_manager_deduct', clear_on_submit=True):
                selected = st.selectbox('Product to Deduct From', list(choices.keys()), index=None, placeholder="Select product...", key='restock_sub_select')
                quantity = st.number_input('Quantity lost / damaged (-)', min_value=1, value=1, step=1, key='restock_sub_qty')
                reason = st.text_input('Reason for Deduction *', placeholder='e.g., Expired ingredients, Spilled drink, Counter error').strip()
                submit = st.form_submit_button('Confirm Stock Deduction', type='primary')
                
            if submit:
                if selected is None: 
                    st.error("Please select a valid menu product from the dropdown box first.")
                elif not reason: 
                    st.error("A validation reason is required to process inventory deductions.")
                else:
                    try:
                        item = choices[selected]
                        if int(quantity) > item['stock']:
                            st.error(f"Cannot deduct {quantity} units. Product only has {item['stock']} units currently in stock.")
                        else:
                            new_total = item['stock'] - int(quantity)
                            db.update_product_stock_direct(item['id'], new_total, actor=f"Inventory Manager ({reason})")
                            db.log_activity('Inventory Manager', 'Stock Deducted', f"{item['code']} · -{int(quantity)} units ({reason})")
                            st.success(f"Successfully deducted {quantity} units from '{item['name']}'. New balance: {new_total}")
                            st.rerun()
                    except Exception as exc: 
                        safe_error(exc)

        # --- TAB 3: DIRECT EDIT (STOCK AUDIT) ---
        with itab3:
            st.markdown("#### Direct Physical Inventory Audit Override")
            st.caption("Use this only during physical inventory audits to calibrate exact database counts.")
            
            selected = st.selectbox('Select Product to Audit', list(choices.keys()), index=None, placeholder="Select product...", key='restock_audit_select')
            
            if selected:
                item = choices[selected]
                st.info(f"Current recorded database level for **{item['name']}** is **{item['stock']}** units.")
                
                with st.form('inventory_manager_audit'):
                    exact_stock = st.number_input('Actual physical count on shelf', min_value=0, value=int(item['stock']), step=1)
                    submit = st.form_submit_button('Overwrite Stock Balance Value', type='primary')
                    
                if submit:
                    try:
                        db.update_product_stock_direct(item['id'], int(exact_stock), actor="Inventory Manager Audit Override")
                        db.log_activity('Inventory Manager', 'Stock Count Audited', f"{item['code']} · Overwrote to {int(exact_stock)}")
                        st.success(f"Inventory database successfully calibrated to exactly {exact_stock} units.")
                        st.rerun()
                    except Exception as exc: 
                        safe_error(exc)
elif mode=='Inventory Manager' and page== 'Dashboard':
    st.subheader('📦 Inventory Operations Dashboard')
        # Load running baseline metrics from your central database
    all_products = db.list_products(active_only=True)
    
    if not all_products:
        st.info("No active catalog items found. Dashboard analytics will populate once items are added.")
    else:
        # 1. Calculate operational thresholds using your alert boundaries
        out_of_stock = [p for p in all_products if p['stock'] == 0]
        low_stock = [p for p in all_products if 0 < p['stock'] <= p['low_stock_threshold']]
        overstocked = [p for p in all_products if p['stock'] >= p.get('high_stock_threshold', 50)]
        healthy_stock = len(all_products) - len(out_of_stock) - len(low_stock) - len(overstocked)
        
        # 2. Render High-Visibility Operational Gauges
        st.markdown("##### 🚨 Stock Urgency Indicators")
        g1, g2, g3, g4 = st.columns(4)
        
        g1.metric("Total Items Managed", len(all_products))
        
        g2.metric(
            "Out of Stock 🛑", 
            len(out_of_stock), 
            delta=f"CRITICAL FIX" if out_of_stock else "All Available",
            delta_color="inverse" if out_of_stock else "normal"
        )
        
        g3.metric(
            "Low-Stock Warning ⚠️", 
            len(low_stock), 
            delta=f"Needs Restock" if low_stock else "Levels Safe",
            delta_color="inverse" if low_stock else "normal"
        )
        
        g4.metric(
            "Overstocked Rows 📦", 
            len(overstocked), 
            delta=f"Freeze Orders" if overstocked else "Within Limits",
            delta_color="off" if overstocked else "normal"
        )
        
        st.divider()
        
        # 3. Two-Column Analytical Breakdown Layout
        left_dash, right_dash = st.columns(2)
        
        with left_dash:
            st.markdown("#### 🚨 Fast Action Restock Checklist")
            st.caption("Items sorted by lowest current stock count to show what needs immediate loading.")
            
            # Combine items needing attention and sort them by lowest stock level first
            urgency_list = sorted(out_of_stock + low_stock, key=lambda x: x['stock'])
            
            if not urgency_list:
                st.success("🎉 Excellent! All inventory shelf counts match healthy threshold levels.")
            else:
                checklist_data = []
                for item in urgency_list:
                    status = "🔴 OUT OF STOCK" if item['stock'] == 0 else "⚠️ LOW STOCK"
                    checklist_data.append({
                        "Code": item['code'],
                        "Product Name": item['name'],
                        "Current Stock": item['stock'],
                        "Alert Threshold": item['low_stock_threshold'],
                        "Urgency": status
                    })
                st.dataframe(pd.DataFrame(checklist_data), use_container_width=True, hide_index=True)
                
        with right_dash:
            st.markdown("#### 📉 Recent Stock Movements & Audits")
            st.caption("Live timeline logging additions, wastage data, and physical overrides.")
            
            try:
                with db.connection() as conn:
                    recent_movements = conn.execute('''
                        SELECT m.quantity_change, m.reason, p.name 
                        FROM inventory_movements m
                        JOIN products p ON m.product_id = p.id
                        ORDER BY m.created_at DESC LIMIT 6
                    ''').fetchall()
                
                if recent_movements:
                    for move in recent_movements:
                        qty = move['quantity_change']
                        icon = "🟢" if qty > 0 else "🔴"
                        sign = "+" if qty > 0 else ""
                        st.markdown(f"{icon} **{sign}{qty} units** — {move['name']} <br><small style='color:gray;'>Reason: {move['reason']}</small>", unsafe_allow_html=True)
                else:
                    st.info("No database movements logged yet.")
            except Exception:
                st.caption("Unable to stream live adjustment logs.")
st.divider()
st.caption('Gulps & Grubs POS · SQLite is the persistent source of truth · Prices stored as integer centavos')
