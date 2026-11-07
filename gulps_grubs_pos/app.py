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

def load_html_template(name, **values):
    """Load a small HTML fragment from templates/ and safely fill placeholders."""
    from html import escape
    template_path = APP_DIR / 'templates' / name
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
            page=st.radio('Cashier navigation',['New Sale','Order Queue','Last Transaction','Sales History'],
                          horizontal=True,key='cashier_page',label_visibility='collapsed')
        else:
            page=st.radio('Inventory navigation',['Stock Overview','Restock Products'],
                          horizontal=True,key='inventory_page',label_visibility='collapsed')
st.caption('Demo mode selector only — it is not secure authentication. Add role-based login before public deployment.')

# Rebuild the AVL tree from SQLite at each run, keeping the database as source of truth.
try: product_tree=rebuild_tree()
except Exception as e:
    safe_error(e); st.stop()

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
    tab1, tab2 = st.tabs(['Add product', 'Edit / Delete'])
    
    with tab1:
        # MOVED OUTSIDE FOR INTERACTIVE REAL-TIME RENDERING
        classification = st.radio('Product Classification *', 
            ['Foods (Grubs)', 'Drinks (Gulps)', 'Others (Combo/Meal Plan)'], 
            horizontal=True
        )
        
        # We handle EVERYTHING in a single, clean workspace flow
        st.markdown("---")
        name = st.text_input('Product name *', placeholder='Enter product name', key='prod_name_input').strip()
        
        # Initialize form baseline tracking containers
        category = ""
        size_prices = {}
        price = 0.0
        
        # --- PATH 1: FOODS ---
        if classification == 'Foods (Grubs)':
            category = st.text_input('Category *', placeholder='e.g. Streetfood, Donut and Waffles').strip()
            price = st.number_input('Price (₱)', min_value=0.0, step=5.0, format='%.2f')
            
        # --- PATH 2: DRINKS (Instant Checkbox Disabling Works Perfectly Here) ---
                # --- PATH 2: DRINKS ---
        elif classification == 'Drinks (Gulps)':
            base_category = st.text_input('Category Name *', placeholder='e.g. Milkshake, Float, Milktea').strip()
            
            st.caption('Configure your cup sizes and pricing:')
            s8, s12, s16 = st.columns(3)
            
            # By embedding classification in the key, Streamlit completely unmounts and resets 
            # the checkboxes to their default values the moment you click a different classification radio!
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

            # Pack active sizes matching structural parameters
            if use8: size_prices[8] = cents_from_peso(price8)
            if use12: size_prices[12] = cents_from_peso(price12)
            if use16: size_prices[16] = cents_from_peso(price16)
            
            # Map custom size details into classification string
            if use_custom and custom_label:
                size_prices[99] = cents_from_peso(custom_price)
                category = f"{base_category} | Custom:{custom_label}"
            else:
                category = base_category
                
            # Base price fallback selection
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

                    # UNIFIED FORM: One save button captures name, category, standard sizes, and custom sizes together!
                    with st.form(f'unified_edit_form_{p["id"]}'):
                        st.markdown("#### Core Product Details")
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
                            
                            # If no sizes are configured yet, default open 12 and 16 oz as baselines
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
                            
                            # Build submission tracking layout dict
                            updated_sizes = {sz: cents_from_peso(pr) for sz, pr in size_inputs.items()}
                            if has_custom and edit_custom_label:
                                updated_sizes[99] = cents_from_peso(edit_custom_price)
                                
                            # Baseline single price fallback calculation
                            new_base_price_cents = next(iter(updated_sizes.values()), p['price_cents'])
                        else:
                            # Standard Food Processing Workflow Paths
                            new_cat = st.text_input('Category', value=p['category']).strip()
                            new_price_val = st.number_input('Price (₱)', min_value=0.0, value=float(p['price_cents']/100), step=5.0, format='%.2f')
                            new_base_price_cents = cents_from_peso(new_price_val)
                            updated_sizes = None

                        st.divider()
                        new_threshold = st.number_input('Low-stock alert at', min_value=0, max_value=1000000, value=int(p['low_stock_threshold']), step=1)
                        
                        # Form Action Triggers
                        save_changes = st.form_submit_button('Save All Product Details', type='primary')
                        
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
                                
                    # Independent Deactivation Button (Outside the save form context)
                    st.warning('Products are deactivated instead of deleted so historical sales remain intact.')
                    if st.button('Deactivate selected product', key=f"deact_action_btn_{p['id']}"):
                        try:
                            # Safe Deletion checking method loop routing
                            success, return_msg = db.delete_product(p['id'])
                            db.log_activity('Admin', 'Product deactivation processed', f"{p['code']} · {p['name']}")
                            st.info(return_msg)
                            st.rerun()
                        except Exception as e: safe_error(e)
                else: 
                    st.info('This product is inactive and cannot be sold. Its historic transaction details are preserved.')
                    if st.button('Reactivate product profile', key=f"reactivate_action_{p['id']}", type='secondary'):
                        try:
                            with db.connection() as _conn:
                                _conn.execute('UPDATE products SET active = 1 WHERE id = ?', (p['id'],))
                            db.log_activity('Admin', 'Product reactivated', f"{p['code']} · {p['name']}")
                            st.success('Product profile reactivated successfully!')
                            st.rerun()
                        except Exception as e: safe_error(e)

        # Global Catalog Search Inventory Matrix View Frames
        st.markdown("---")
        search = st.text_input('Search by code or product name', key='product_search')
        shown_items = [prod for prod in all_products if search.casefold() in (prod['code']+' '+prod['name']).casefold()]
        if shown_items:
            st.dataframe(pd.DataFrame([
                {
                    'Code': prod['code'],
                    'Product': prod['name'],
                    'Category': prod['category'],
                    'Price': (' · '.join(f"{size if size != 99 else 'Custom'} oz {money(price)}" for size, price in db.get_product_sizes(prod['id']).items()) if db.get_product_sizes(prod['id']) else money(prod['price_cents'])),
                    'Stock': prod['stock'],
                    'Low-stock threshold': prod['low_stock_threshold'],
                    'Status': 'Active' if prod['active'] else 'Inactive'
                } for prod in shown_items
            ]), use_container_width=True, hide_index=True)
        else: 
            st.info('No products match your search.')

        # Tab 3 Configuration with Safe Automated Deletion Logic
    with tab3:
        st.subheader("Archived & Deactivated Products")
        st.markdown(
            "Manage archived menu item blueprints here. Active item records can be permanently deleted "
            "or securely deactivated depending on past checkout historical constraints."
        )
        
        # Load absolute checklist inventory matrix
        all_items = db.list_products(active_only=False)
        inactive_items = [p for p in all_items if not p['active']]
        
        if not inactive_items:
            st.success("🎉 No archived products found! Your active menu catalog is clean.")
        else:
            search_archived = st.text_input('Search archived profiles by code or name', key='archive_search_bar')
            filtered_archive = [
                p for p in inactive_items 
                if search_archived.casefold() in (p['code'] + ' ' + p['name']).casefold()
            ]
            
            if not filtered_archive:
                st.info("No archived items match your search term.")
            else:
                for item in filtered_archive:
                    with st.container(border=True):
                        col_details, col_restore, col_purge = st.columns([3.5, 1, 1], vertical_alignment="center")
                        
                        with col_details:
                            st.markdown(f"### {item['name']}")
                            display_category = item['category'].split(" | Custom:", 1)[0] if " | Custom:" in item['category'] else item['category']
                            st.markdown(f"**Code:** `{item['code']}`  |  **Category:** *{display_category}*")
                        
                        # 1. Action Button 1: Reactivate Product Profile
                        with col_restore:
                            if st.button("Reactivate", key=f"rest_btn_{item['id']}", use_container_width=True):
                                try:
                                    with db.connection() as _conn:
                                        _conn.execute('UPDATE products SET active = 1 WHERE id = ?', (item['id'],))
                                    db.log_activity('Admin', 'Product reactivated', f"{item['code']} · {item['name']}")
                                    st.success(f"Restored '{item['name']}'!")
                                    st.rerun()
                                except Exception as e: safe_error(e)
                                
                        # 2. Action Button 2: Delete Row From Database
                        with col_purge:
                            if st.button("Delete", key=f"purge_btn_{item['id']}", type="primary", use_container_width=True):
                                try:
                                    # Call your dual delete verification method inside database.py
                                    success, return_msg = db.delete_product(item['id'])
                                    db.log_activity('Admin', 'Product delete action processed', f"{item['code']} · {item['name']}")
                                    
                                    if success:
                                        st.success(return_msg)
                                    else:
                                        st.error(return_msg)
                                    st.rerun()
                                except Exception as e: safe_error(e)


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

elif mode=='Cashier' and page=='New Sale':
    st.subheader('New sale')
    products=db.list_products(active_only=True)
    left,right=st.columns([1.35,1],gap='large')
    with left:
        st.markdown('#### Available products')
        menu_categories=['All categories'] + sorted({p['category'] for p in products})
        selected_category=st.selectbox('Browse category',menu_categories,key='cashier_category_filter')
        query=st.text_input('Find a product',placeholder='Search product name or code')
        category_products=products if selected_category=='All categories' else [p for p in products if p['category']==selected_category]
        # Exact-code lookup goes through the manually implemented AVL tree; category/name filtering uses SQLite-backed records.
        if query.strip():
            match=product_tree.search(query.strip())
            shown=[match] if match and match in category_products else [p for p in category_products if query.casefold() in (p['name']+' '+p['code']).casefold()]
        else: shown=category_products
        if not shown: st.info('No matching active products.')
        for start_idx in range(0,len(shown),2):
            cols=st.columns(2)
            for col,p in zip(cols,shown[start_idx:start_idx+2]):
                with col:
                    sizes=db.get_product_sizes(p['id'])
                    is_drink=bool(sizes)
                    if is_drink:
                        price_line=' · '.join(f"{size} oz {money(price)}" for size,price in sizes.items())
                    else:
                        price_line=money(p['price_cents'])
                    st.markdown(load_html_template('product_card.html', name=p['name'], code=p['code'], category=p['category'], price_line=price_line, stock=p['stock']), unsafe_allow_html=True)
                    with st.form(f"add_cart_{p['id']}"):
                        size_oz=None; unit_price=p['price_cents']; chosen_options=[]
                        if is_drink:
                            available_sizes=list(sizes.keys())
                            size_oz=st.radio('Choose cup size (oz)',available_sizes,format_func=lambda z:f"{z} oz",horizontal=True,key=f"size_{p['id']}")
                            unit_price=sizes[size_oz]
                            st.caption(f"Selected size price: {money(unit_price)}")

                        customizations='; '.join(chosen_options)
                        qty=st.number_input('Qty',min_value=1,max_value=max(1,int(p['stock'])),value=1,step=1,key=f"qty_{p['id']}",disabled=p['stock']<1)
                        add=st.form_submit_button('Add to cart',use_container_width=True,disabled=p['stock']<1)
                    if add:
                        try:
                            if qty>p['stock']: raise ValueError(f"Only {p['stock']} unit(s) are in stock.")
                            st.session_state.cart.add(p,int(qty),size_oz=size_oz,unit_price_cents=unit_price,customizations=customizations); size_label=f" ({size_oz} oz)" if size_oz else ''; option_label=f" · {customizations}" if customizations else ''; st.success(f"Added {qty} × {p['name']}{size_label}{option_label}."); st.rerun()
                        except Exception as e: safe_error(e)
    with right:
        st.markdown('#### Shopping cart')
        cart=st.session_state.cart
        items=cart.items()
        if not items: st.info('Your cart is empty. Add a product to begin.')
        else:
            for item in items:
                with st.container(border=True):
                    c1,c2=st.columns([2,1]); size_label=f" · {item['size_oz']} oz" if item.get('size_oz') else ''; option_label=f"\n\n{item['customizations']}" if item.get('customizations') else ''; c1.markdown(f"**{item['name']}{size_label}**{option_label}\n\n{money(item['unit_price_cents'])} each")
                    c2.markdown(f"**{money(item['subtotal_cents'])}**")
                    qcol,rmcol=st.columns([2,1])
                    new_q=qcol.number_input('Quantity',min_value=1,max_value=1000000,value=int(item['quantity']),step=1,key=f"cart_q_{item['product_id']}_{item.get('size_oz') or 'std'}_{abs(hash(item.get('customizations','')))}")
                    if qcol.button('Update',key=f"update_{item['product_id']}_{item.get('size_oz') or 'std'}_{abs(hash(item.get('customizations','')))}"):
                        try:
                            p=db.get_product(item['product_id'])
                            if not p or not p['active']: raise ValueError('This product is no longer available. Remove it from the cart.')
                            if int(new_q)>p['stock']: raise ValueError(f"Only {p['stock']} unit(s) are in stock.")
                            cart.set_quantity(item['product_id'],int(new_q),item.get('size_oz'),item.get('customizations','')); st.rerun()
                        except Exception as e: safe_error(e)
                    if rmcol.button('Remove',key=f"remove_{item['product_id']}_{item.get('size_oz') or 'std'}_{abs(hash(item.get('customizations','')))}"):
                        cart.remove(item['product_id'],item.get('size_oz'),item.get('customizations','')); st.rerun()
            st.divider(); st.markdown(f"### Total: {money(cart.total_cents())}")
            st.caption('Inventory is checked again at checkout. No stock is deducted until the sale commits successfully.')
            with st.form('checkout_form'):
                cashier_label=st.text_input('Cashier name / label',value='Cashier')
                order_customer=st.text_input('Customer / order label',placeholder='e.g. Walk-in #12 or pickup name')
                order_priority=st.select_slider('Order priority',options=[1,2,3,4,5],value=3,format_func=lambda x:{1:'1 · Urgent',2:'2 · High',3:'3 · Normal',4:'4 · Low',5:'5 · Flexible'}[x])
                st.caption('After checkout, food and drink items are sent to the priority queues. Mixed carts are split into both queues.')
                confirm=st.form_submit_button('Confirm sale + send to queue',type='primary',use_container_width=True)
            if confirm:
                try:
                    sale=db.checkout(cart.items(),cashier_label.strip() or 'Cashier')
                    customer_label=(order_customer.strip() or f"Sale #{sale['transaction_id']}")[:100]
                    grouped={'Food':[],'Drink':[]}
                    for line in sale['items']:
                        product=next((p for p in products if p['code']==line['code']),None)
                        category=(product or {}).get('category','').casefold()
                        name=line['name'].casefold()
                        is_drink=bool(line.get('size_oz')) or bool(db.get_product_sizes(product['id'])) if product else bool(line.get('size_oz'))
                        kind='Drink' if is_drink else 'Food'
                        size_text=f" {line['size_oz']} oz" if line.get('size_oz') else ''
                        options_text=f" ({line['customizations']})" if line.get('customizations') else ''
                        grouped[kind].append(f"{line['quantity']} × {line['name']}{size_text}{options_text}")
                    queued=[]
                    for kind,lines in grouped.items():
                        if lines:
                            oid=db.add_order(customer_label, (f"Sale #{sale['transaction_id']}: " + '; '.join(lines))[:490], int(order_priority), order_type=kind)
                            queued.append(f"{kind} queue #{oid}")
                    db.log_activity('Cashier','Sale sent to queue',f"Sale #{sale['transaction_id']} · {', '.join(queued)} · Priority {order_priority}")
                    st.session_state.last_sale=sale; cart.clear(); st.success(f"Sale #{sale['transaction_id']} completed — {money(sale['total_cents'])}. Sent to: {', '.join(queued)}."); st.rerun()
                except Exception as e: safe_error(e)
        st.markdown('---')
        st.markdown('**Cart data structure:** custom singly linked list')
        st.caption(f'{len(cart)} distinct item(s) · item lookup O(n) · cart total O(n)')

elif mode=='Cashier' and page=='Order Queue':
    st.subheader('Cashier order queue')
    st.caption('Cashier assigns priority when sending an order. Priority 1 is most urgent; priority 5 is least urgent. Equal priorities are handled first-in, first-out.')
    queue_search=st.text_input('Search orders by order number, customer, or details',placeholder='e.g. #12, milkshake, French fries')
    with st.form('cashier_queue_form', clear_on_submit=True):
        customer=st.text_input('Customer / order number', placeholder='e.g. Walk-in #12')
        order_type=st.radio('Send order to', ['Food','Drink'], horizontal=True, help='Food and drink orders are recorded separately in the priority queue.')
        details=st.text_area('Order details', placeholder='e.g. 2 French fries (cheese), 1 siomai; no onions', max_chars=500)
        priority=st.select_slider('Priority', options=[1,2,3,4,5], value=3, format_func=lambda x:{1:'1 · Urgent',2:'2 · High',3:'3 · Normal',4:'4 · Low',5:'5 · Flexible'}[x])
        submit_order=st.form_submit_button('Add to queue', type='primary', use_container_width=True)
    if submit_order:
        try:
            oid=db.add_order(customer,details,int(priority),order_type=order_type)
            st.success(f'{order_type} order #{oid} added to the queue.')
            st.rerun()
        except Exception as e: safe_error(e)
    orders=db.list_orders(pending_only=True)
    if queue_search.strip():
        term=queue_search.casefold()
        orders=[o for o in orders if term in (str(o['id'])+' '+o['customer_name']+' '+o['details']+' '+o.get('order_type','')).casefold()]
    if orders:
        st.markdown('#### Pending orders — priority order')
        st.dataframe(pd.DataFrame([{'Queue #':o['id'],'Type':o.get('order_type','Food'),'Customer':o['customer_name'],'Order details':o['details'],'Priority':o['priority'],'Queued at':o['created_at'].replace('T',' ')} for o in orders]), use_container_width=True, hide_index=True)
    else:
        st.info('No pending orders. Add a food or drink order above.')

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
    st.subheader('Restock menu products')
    active_products=db.list_products(active_only=True)
    if active_products:
        choices={f"{p['code']} — {p['name']} (current stock: {p['stock']})":p for p in active_products}
        with st.form('inventory_manager_restock',clear_on_submit=True):
            selected=st.selectbox('Product',list(choices))
            quantity=st.number_input('Quantity received',min_value=1,max_value=1000000,value=1,step=1)
            submit=st.form_submit_button('Save restock',type='primary')
        if submit:
            try:
                item=choices[selected]
                db.restock_product(item['id'],int(quantity))
                db.log_activity('Inventory Manager','Product restocked',f"{item['code']} · +{int(quantity)}")
                st.success('Stock quantity updated.')
                st.rerun()
            except Exception as exc: safe_error(exc)
    else:
        st.info('There are no active menu products to restock. Admin must add products first.')

elif mode=='Cashier' and page=='Last Transaction':
    st.subheader('Last transaction')
    sale=st.session_state.last_sale
    if not sale: st.info('Complete a sale in New Sale to display its details here. For historical records, ask the admin to open Sales History.')
    else:
        st.success(f"Sale #{sale['transaction_id']} · {sale['created_at'].replace('T',' ')}")
        st.metric('Total paid',money(sale['total_cents']))
        st.dataframe(pd.DataFrame([{'Code':x['code'],'Product':x['name'],'Size':(f"{x.get('size_oz')} oz" if x.get('size_oz') else '—'),'Options':x.get('customizations',''),'Qty':x['quantity'],'Unit price':money(x['unit_price_cents']),'Subtotal':money(x['subtotal_cents'])} for x in sale['items']]),use_container_width=True,hide_index=True)
        st.caption('The database transaction has committed successfully; inventory and transaction history have been updated.')

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

st.divider()
st.caption('Gulps & Grubs POS · SQLite is the persistent source of truth · Prices stored as integer centavos')
