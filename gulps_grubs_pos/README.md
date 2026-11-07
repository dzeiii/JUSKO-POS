# Gulps & Grubs POS — Streamlit MVP

A beginner-friendly point-of-sale application for a small food and beverage business. It uses Streamlit for the interface, SQLite as the persistent source of truth, and manually implemented Linked List, AVL Tree, and Min-Heap structures.

## Features

- **Admin mode:** dashboard, daily revenue and sales count, low-stock alerts, add/edit/deactivate products, restocking, date-filtered sales history, CSV export, and scheduled pickup priority queue.
- **Cashier mode:** browse by menu category, search products, choose only the configured 8 oz / 12 oz / 16 oz sizes, select menu modifiers such as sinkers and fries flavors, and use a linked-list cart with distinct size/option variants. Checkout saves the selected options, deducts inventory, and shows completed-sale details.
- **SQLite:** products, configurable per-product drink sizes, transactions with historical size/price/customization snapshots, transaction line items with saved customizations, inventory movements, and pending orders. Foreign keys and indexes are enabled. Checkout writes the transaction, historical line items, inventory deductions, and movement records in one database transaction.
- **Validation:** duplicate product codes, invalid prices/quantities, missing or inactive products, insufficient stock, invalid order priority, and duplicate cart IDs are rejected.
- **Warm brand styling:** cream, terracotta, orange, and burgundy, with optional `brand_logo.jpg`.

> This is an educational MVP. The sidebar mode selector is a workflow selector, not secure authentication. Do not expose a public deployment containing business data until role authentication and a durable production database are configured. SQLite on ephemeral cloud storage may not persist reliably across redeploys/restarts.

## Folder structure

```text
pos_mvp/
├── app.py                 # Streamlit UI and mode-level permission checks
├── database.py            # Schema, validation, CRUD, atomic checkout, reports
├── data_structures.py     # Manual singly linked list, AVL tree, binary min-heap
├── tests/
│   └── test_pos.py        # Automated unit/integration tests
├── requirements.txt       # Lightweight third-party dependencies
├── brand_logo.jpg         # Optional business logo
├── .gitignore             # Keeps database/log/secrets out of Git
└── README.md
```

## Requirements

- Python 3.10 or newer
- Windows, macOS, or Linux
- Internet access only for initial package installation

## Run on Windows

1. Extract the project ZIP.
2. Open Command Prompt or PowerShell in the extracted `pos_mvp` folder.
3. Create and activate a virtual environment (recommended):

```powershell
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r requirements.txt
```

4. Start the app:

```powershell
py -m streamlit run app.py
```

5. Open the local URL Streamlit prints (usually `http://localhost:8501`).
6. On first run, `pos.db` is created automatically and starts with no sample menu or inventory records. Admin manually enters each product name, category, price, and optional drink sizes.

The menu is part of the existing Python/Streamlit POS application, not a separate app or programming language. Imported products use the prices you supplied; starting stock is entered during import, and the default is zero so you do not accidentally create imaginary inventory.

## Run tests

From the project root:

```powershell
py -m unittest discover -s tests -v
```

The tests use temporary SQLite files and do not modify the application's `pos.db`.

## Demonstration workflow

1. Open **Admin → Products & Inventory → Add product** and manually enter the product name, category, price, and optional drink sizes. Then use Inventory Manager to restock.
2. Menu items show only the sizes and prices you specified. For example, milkshakes show 12 oz at ₱35 and 16 oz at ₱45; floats show only their listed sizes. Edit size prices in **Edit / deactivate** if needed.
3. Open **Cashier → New Sale**. Filter by category, select a product, choose its available cup size, and set options such as sinkers or fries flavor where shown.
4. Confirm the sale. The transaction saves the selected cup size and actual size price; each drink counts as one serving from inventory.
5. Return to **Admin → Dashboard** and **Sales History** to review the sale and revenue.
6. Restock the product and confirm that the inventory movement is recorded.
7. Open **Admin → Pickup Queue**, add two orders with priorities 4 and 1, and process the next order. Priority 1 is first; equal priorities are FIFO by sequence number.
8. Stop and restart Streamlit. Product, size prices, stock, sales, and order records remain in the local SQLite file.

## Data structure roles and complexity

- **Linked List cart:** manually implemented nodes; each size/customization combination is a distinct cart item keyed by product ID, size, and selected options. `add`/`find`/`set_quantity`/`remove` and total traversal are O(n) in the general case.
- **AVL Tree:** keyed by normalized unique product code. Search/insert/delete are O(log n) while balanced; rotations and height/balance updates maintain the invariant. The tree is rebuilt from active SQLite products on each app run, and the cashier's exact-code search uses it.
- **Min-Heap:** custom binary heap keyed by `(priority, sequence_no)`. `push` and `pop` are O(log n), `peek` is O(1). It is rebuilt from pending SQLite orders; SQLite remains authoritative, and completion is persisted to the database.

## Money and reliability notes

All monetary amounts, including 8 oz / 12 oz / 16 oz prices, are stored as integer centavos, avoiding binary floating-point rounding in totals. The beverage inventory count represents servings/cups, not separate stock pools per cup size. The UI converts pesos to centavos at input time. Checkout re-reads current active products and stock inside a single SQLite transaction, inserts the sale and immutable historical item snapshots, deducts stock conditionally, and writes inventory movements. Any exception rolls back all checkout writes. Revenue is reported; profit is not calculated because costs and expenses are not recorded.

## Current MVP limitations

- The mode selector does not authenticate users; it is suitable for a local class demonstration, not public multi-user access.
- The app is designed for local single-business use. For durable online multi-user deployment, use a persistent database service and add authentication/authorization.
- Pickup orders are a queue demonstration and are not automatically linked to a payment/sale; online ordering and customer accounts are intentionally out of scope.
- No card payment integration, refunds, tax configuration, receipt printer, or profit reporting.

## Cashier priority queue and Kitchen mode

- **Cashier → Order Queue:** cashier enters a customer/order label, chooses Food or Drink, enters order details, and assigns priority from 1 (most urgent) to 5 (least urgent).
- **Inventory Manager → Stock Overview:** kitchen staff see pending Food orders only, sorted by priority and then FIFO sequence. Staff can mark the next food order completed.
- Queue records are stored in SQLite (`pending_orders`). Existing databases are migrated to add the `order_type` column automatically.
- The queue is a manual order-ticket workflow. Completing a sale does not automatically create a kitchen ticket; the cashier sends the order to the queue from **Order Queue**.


## Three work modes and persistent history

- **Cashier Mode:** searches the menu by name/code, adds items with exact cup sizes and available customizations, checks out, assigns priority (1 is most urgent), and automatically sends food and drink items to their respective queues. Mixed orders are split between queues. The cashier can search pending orders and review cashier history.
- **Inventory Manager Mode:** displays pending food orders in priority order, with first-in-first-out handling for equal priorities, and lets kitchen staff mark the next food order completed.
- **Admin Mode:** adds, searches, edits, restocks, and deactivates products; reviews sales history and dashboard reports; and searches the activity history for admin, cashier, and kitchen actions. Products are deactivated rather than physically deleted so historical transactions remain accurate.

The SQLite database records sales, sale line items, inventory movements, queue status, and activity history. `pos.db` is created locally on first run and is intentionally excluded from Git. To populate the Cashier menu, open **Admin → Products & Inventory → Load business menu**, import the menu, then record the actual starting inventory in **Restock** (or import with a suitable starting quantity).

## Styling and HTML templates

The UI styling is stored separately in `style.css`. Small reusable HTML fragments are in `templates/` (`brand_banner.html`, `site_brand.html`, `nav_label.html`, and `product_card.html`). The Streamlit widgets and interactive navigation remain in `app.py`, because Streamlit manages those controls through Python. The SQLite database and data-structure implementation are unchanged.

To customize colors and spacing, edit `style.css`. To change static brand text or product-card markup, edit the matching file in `templates/`. Keep the `templates/` folder beside `app.py`.


## Empty-start setup and manual categories

This version does not preload menu products, categories, or sample stock. Admin types the category for every new product (for example, Milkshake, Milktea, Floats, Fries, or Siomai). For drinks, Admin checks the drink-size option and selects only the cup sizes offered, then enters each price. Inventory Manager handles stock viewing and restocking. Existing local `pos.db` files are not automatically erased; back up and delete the local database file only if you intentionally want to erase previous transactions and inventory too.
