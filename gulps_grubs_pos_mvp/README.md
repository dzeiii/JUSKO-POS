# Gulps & Grubs at the Garage POS

## Run
1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Run `pip install -r requirements.txt`.
4. Run `streamlit run app.py`.

The app creates the `data/` directory and `data/gulps_grubs.db` automatically.
The uploaded logo is in `assets/`.

**Streamlit Community Cloud note:** the default SQLite file is stored on the app
instance's local filesystem and may be lost when the app is redeployed or its
instance is replaced. For live business use, configure `GULPS_GRUBS_DB_PATH` to
a genuinely persistent mounted volume (if your hosting plan provides one), or
migrate the database to a managed service such as PostgreSQL/Supabase. Keep
regular backups; do not commit a live customer database to a public GitHub repo.

## Three modes
- Cashier: search menu items, manage a linked-list cart, choose priority, submit orders, and view the queue.
- Admin: create/update/delete menu variants, manage prices, view sales and low-stock reports, and update order statuses.
- Inventory Manager: update finished menu stock, add/delete shared supplies, restock supplies, and monitor packaging/ingredient levels.

## Shared supplies behavior
Packaging is shared across all drinks. Each sold menu item automatically deducts one matching size cup (8oz/12 oz/16 oz) and one straw per quantity. Ingredients such as milk, sugar, and pearls are tracked separately and adjusted manually. Add packaging inventory with exact names such as `12 oz cups`, `16 oz cups`, and `Straws` for the automatic deduction rules to work.

## DSA
- Linked List: cashier cart insertion, deletion, traversal, and total.
- AVL Tree: product-name index for cashier prefix search.
- Min-Heap: order queue, where Urgent=1, High=2, Normal=3; earlier timestamp breaks ties.

## MVP limitations
The three modes are workspace selectors, not secure login roles. Add authentication and permissions before real deployment. This MVP deducts menu stock and standardized packaging only; it does not calculate ingredient recipes. Sales totals include orders marked Completed.


## Empty menu / manual product setup
The menu is intentionally initialized empty. On the first run of this updated version, the app clears existing menu products one time and records a reset marker in the database. It preserves order history, completed sales, and shared inventory. Products are not automatically seeded. Add products manually from **Admin → Menu products → Add or update a menu item**. The saved products then appear in the Cashier workspace.
