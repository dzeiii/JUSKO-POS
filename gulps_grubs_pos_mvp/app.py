from pathlib import Path
import base64
import streamlit as st
from modules.database import *
from modules.dsa import AVLTree, LinkedListCart, MinHeap
from modules.services import *

st.set_page_config(page_title="Gulps & Grubs POS", page_icon="🥤", layout="wide")
init_db()

st.markdown("""
<style>
:root { --orange:#ef7d22; --deep:#4b160f; --cream:#fff2d2; --gold:#ffc43d; }
.stApp { background:#fff9ed; color:#32150f; }
[data-testid="stHeader"] { background:transparent; }
.block-container { max-width:1200px; padding-top:1rem; padding-bottom:2rem; }
.gg-header { background:linear-gradient(115deg,#f07820,#f6a12c); border:3px solid #f8c849;
 border-radius:16px; padding:14px 20px; display:flex; align-items:center; gap:18px; margin-bottom:18px; }
.gg-header img { width:110px; height:110px; object-fit:cover; border:3px solid #fff1c5; border-radius:12px; }
.gg-header h1 { color:#4b160f; margin:0; font-size:1.8rem; }
.gg-header p { color:#4b160f; margin:3px 0 0; }
h1,h2,h3 { color:#5b2114; }
div[data-testid="stMetric"] { background:#fff; border:1px solid #f3d7a1; border-radius:12px; padding:12px; }
.stButton>button { background:#ef7d22; color:white; border:0; border-radius:9px; font-weight:600; }
.stButton>button:hover { background:#d96716; color:white; }
[data-testid="stTabs"] button[aria-selected="true"] { color:#a64212; }
div[data-testid="stForm"] { background:#fff; border:1px solid #f3d7a1; padding:14px; border-radius:12px; }
</style>
""", unsafe_allow_html=True)

logo = Path(__file__).resolve().parent / "assets" / "gulps_grubs_logo.jpg"
st.markdown(f"""
<div class="gg-header">
<img src="data:image/jpeg;base64,{base64.b64encode(logo.read_bytes()).decode()}">
<div><h1>Gulps & Grubs at the Garage</h1>
<p>Simple point-of-sale • Order priority • Stock management</p></div>
</div>
""", unsafe_allow_html=True)

mode = st.radio("Choose workspace", ["Cashier", "Admin", "Inventory Manager"], horizontal=True)
products = get_products()
tree = AVLTree()
for p in products:
    tree.insert(p["name"].lower(), p)

def product_label(p):
    return f'{p["code"]} · {p["name"]} · {p["size"]} · ₱{p["price"]:.2f}'

def show_products(rows):
    if not rows:
        st.info("No matching menu products.")
        return
    st.dataframe([{"Code":p["code"],"Product":p["name"],"Category":p["category"],
                   "Size":p["size"],"Price":f'₱{p["price"]:.2f}',"Stock":p["stock"],
                   "Availability":p["availability"]} for p in rows],
                 use_container_width=True, hide_index=True)

if mode == "Cashier":
    st.subheader("Cashier · Take an order")
    left,right = st.columns([1.15, .85])
    if "cart" not in st.session_state: st.session_state.cart = LinkedListCart()
    cart = st.session_state.cart
    with left:
        if not products:
            st.info("Your menu is empty. Ask the Admin to add products manually in Admin → Menu products.")
        search = st.text_input("Search menu", placeholder="Type a product or flavor name")
        matches = tree.search_prefix(search.lower()) if search.strip() else products
        matches = [p for p in matches if p["availability"] == "Available" and p["stock"] > 0]
        show_products(matches)
        if matches:
            chosen = st.selectbox("Select menu item", matches, format_func=product_label)
            qty = st.number_input("Quantity", min_value=1, max_value=max(1, int(chosen["stock"])), value=1)
            if st.button("Add to cart"):
                cart.add(chosen["id"], chosen["name"] + " (" + chosen["size"] + ")", chosen["price"], int(qty),
                         chosen["size"], chosen["code"])
                st.success("Added to cart.")
    with right:
        st.markdown("#### Current cart")
        for item in cart.to_list():
            a,b = st.columns([3,1])
            a.write(f'**{item["name"]}** × {item["quantity"]}  \n₱{item["subtotal"]:.2f}')
            if b.button("Remove", key=f'remove_{item["product_id"]}'):
                cart.remove(item["product_id"]); st.rerun()
        st.markdown(f"### Total: ₱{cart.total():.2f}")
        if cart.to_list():
            priority = st.selectbox("Order priority", ["Normal","High","Urgent"])
            if st.button("Submit order", type="primary", use_container_width=True):
                try:
                    oid = create_order(cart.to_list(), cart.total(), priority)
                    cart.clear()
                    st.success(f"Order #{oid} submitted. Stock and shared packaging were updated.")
                    st.rerun()
                except ValueError as e: st.error(str(e))
            if st.button("Clear cart"): cart.clear(); st.rerun()
    st.divider()
    st.markdown("#### Pending order queue")
    heap = MinHeap()
    for o in get_orders(["Pending","Preparing"]): heap.push(o["priority_rank"], o["created_at"], o)
    queued=[]
    while len(heap): queued.append(heap.pop()[2])
    if queued:
        st.dataframe([{"Order":o["id"],"Priority":o["priority"],"Total":f'₱{o["total"]:.2f}',"Status":o["status"]} for o in queued],
                     use_container_width=True, hide_index=True)
    else: st.caption("There are no pending orders.")

elif mode == "Admin":
    st.subheader("Admin · Menu and business overview")
    summary = get_sales_summary()
    a,b,c = st.columns(3)
    a.metric("Completed sales", f'₱{summary["sales"]:.2f}')
    b.metric("Completed orders", summary["transactions"])
    c.metric("Menu variants", len(products))
    ptab, rtab, qtab = st.tabs(["Menu products", "Reports", "Order queue"])
    with ptab:
        st.markdown("#### Add or update a menu item")
        st.caption("Your menu starts empty. Enter each product manually below; saved products will appear in the Cashier menu.")
        with st.form("product_form"):
            code = st.text_input("Product code (blank = automatic)")
            name = st.text_input("Product / flavor name")
            category = st.selectbox("Category", ["Milkshake","Milktea","Float","Snack","Other"])
            size = st.selectbox("Size", ["8oz","12 oz","16 oz","N/A"])
            price = st.number_input("Selling price (₱)", min_value=0.0, value=45.0, step=1.0)
            stock = st.number_input("Opening menu stock", min_value=0, value=0, step=1)
            threshold = st.number_input("Low-stock threshold", min_value=0, value=5, step=1)
            if st.form_submit_button("Save menu item"):
                if not name.strip() or price <= 0: st.error("Enter a product name and a price above zero.")
                else:
                    try:
                        save_product(code.strip() or None,name.strip(),category,size,price,int(stock),int(threshold))
                        st.success("Menu item saved."); st.rerun()
                    except Exception as e: st.error(str(e))
        st.markdown("#### Search and delete")
        q = st.text_input("Search menu products", key="admin_search").lower()
        filtered=[p for p in products if q in p["name"].lower() or q in p["code"].lower()]
        show_products(filtered)
        if products:
            target=st.selectbox("Choose item to delete",[product_label(p) for p in products])
            if st.button("Delete selected menu item"):
                delete_product(target.split(" · ")[0]); st.success("Deleted."); st.rerun()
        st.caption("To edit an item, save it again using its existing product code.")
    with rtab:
        low=get_low_stock()
        st.markdown("#### Low-stock menu alerts")
        show_products(low)
        st.markdown("#### Shared supply overview")
        supplies=get_inventory()
        if supplies:
            st.dataframe([{"Supply":x["name"],"Type":x["kind"],"On hand":f'{x["quantity"]:g} {x["unit"]}',
                           "Reorder level":x["reorder_level"]} for x in supplies],use_container_width=True,hide_index=True)
        orders=get_orders(["Completed"])
        st.markdown("#### Completed sales")
        if orders:
            st.dataframe([{"Order":o["id"],"Total":f'₱{o["total"]:.2f}',"Date":o["created_at"]} for o in orders],
                         use_container_width=True,hide_index=True)
        else: st.caption("No completed sales yet.")
    with qtab:
        orders=get_orders(["Pending","Preparing"])
        if not orders: st.info("Queue is empty.")
        for o in sorted(orders,key=lambda x:(x["priority_rank"],x["created_at"])):
            x,y,z=st.columns([3,1,1])
            x.write(f'**Order #{o["id"]}** · {o["priority"]} · ₱{o["total"]:.2f} · {o["status"]}')
            if y.button("Preparing",key=f'prep{o["id"]}'): update_order_status(o["id"],"Preparing"); st.rerun()
            if z.button("Complete",key=f'complete{o["id"]}'): update_order_status(o["id"],"Completed"); st.rerun()

else:
    st.subheader("Inventory Manager · Stock and supplies")
    menu_tab, supply_tab = st.tabs(["Menu stock", "Shared supplies"])
    with menu_tab:
        st.markdown("#### Finished menu-product stock")
        show_products(products)
        if products:
            target=st.selectbox("Select menu item",[product_label(p) for p in products])
            code=target.split(" · ")[0]
            delta=st.number_input("Stock adjustment (+ add / - deduct)",value=0,step=1)
            if st.button("Update menu stock"):
                try: adjust_stock(code,int(delta)); st.success("Menu stock updated."); st.rerun()
                except ValueError as e: st.error(str(e))
    with supply_tab:
        st.markdown("#### Shared supplies")
        supplies=get_inventory()
        if supplies:
            st.dataframe([{"Code":x["code"],"Supply":x["name"],"Type":x["kind"],"Quantity":f'{x["quantity"]:g} {x["unit"]}',
                           "Reorder level":x["reorder_level"],"Status":"LOW" if x["quantity"]<=x["reorder_level"] else "OK"} for x in supplies],
                         use_container_width=True,hide_index=True)
        with st.form("supply_form"):
            st.markdown("#### Add a supply")
            nm=st.text_input("Supply name")
            kind=st.selectbox("Supply type",["Packaging","Ingredient","Other"])
            unit=st.text_input("Unit",value="pcs")
            qty=st.number_input("Opening quantity",min_value=0.0,value=0.0)
            reorder=st.number_input("Reorder level",min_value=0.0,value=5.0)
            if st.form_submit_button("Add supply"):
                if nm.strip(): add_inventory_item(nm.strip(),kind,unit.strip(),qty,reorder); st.success("Supply added."); st.rerun()
                else: st.error("Supply name is required.")
        if supplies:
            chosen=st.selectbox("Supply to restock", [f'{x["code"]} · {x["name"]}' for x in supplies])
            amount=st.number_input("Restock quantity",min_value=0.01,value=1.0)
            if st.button("Record restock"):
                restock_inventory(chosen.split(" · ")[0],amount); st.success("Restock recorded."); st.rerun()
            delete=st.selectbox("Supply to delete",[f'{x["code"]} · {x["name"]}' for x in supplies],key="del_supply")
            if st.button("Delete selected supply"): delete_inventory_item(delete.split(" · ")[0]); st.rerun()
        st.caption("Packaging (such as cups and straws) is deducted automatically on each sale. Ingredients are tracked here and adjusted manually.")
