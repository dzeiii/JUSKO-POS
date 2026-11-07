"""SQLite persistence and atomic business operations for the POS MVP."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
import re

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'pos.db'

@contextmanager
def connection(db_path=DB_PATH):
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 10000')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db(db_path=DB_PATH):
    with connection(db_path) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS products (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT NOT NULL COLLATE NOCASE UNIQUE,
          name TEXT NOT NULL COLLATE NOCASE,
          category TEXT NOT NULL,
          price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
          stock INTEGER NOT NULL CHECK(stock >= 0),
          low_stock_threshold INTEGER NOT NULL DEFAULT 5 CHECK(low_stock_threshold >= 0),
          high_stock_threshold INTEGER NOT NULL DEFAULT 50 CHECK(high_stock_threshold >= 0), -- Added column
          active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
          created_at TEXT NOT NULL,
          cashier_label TEXT NOT NULL DEFAULT 'Cashier'
        );
        CREATE TABLE IF NOT EXISTS product_sizes (
          product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          size_oz INTEGER NOT NULL CHECK(size_oz IN (8,12,16)),
          price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
          PRIMARY KEY(product_id, size_oz)
        );
        CREATE TABLE IF NOT EXISTS transaction_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          transaction_id INTEGER NOT NULL REFERENCES transactions(id),
          product_id INTEGER REFERENCES products(id),
          product_code TEXT NOT NULL,
          product_name TEXT NOT NULL,
          unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0),
          quantity INTEGER NOT NULL CHECK(quantity > 0),
          subtotal_cents INTEGER NOT NULL CHECK(subtotal_cents >= 0),
          size_oz INTEGER CHECK(size_oz IN (8,12,16) OR size_oz IS NULL),
          customizations TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS inventory_movements (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          product_id INTEGER NOT NULL REFERENCES products(id),
          quantity_change INTEGER NOT NULL,
          reason TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS activity_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          actor_mode TEXT NOT NULL CHECK(actor_mode IN ('Admin','Cashier','Kitchen','System')),
          action TEXT NOT NULL,
          details TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pending_orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_name TEXT NOT NULL,
          details TEXT NOT NULL,
          order_type TEXT NOT NULL DEFAULT 'Food' CHECK(order_type IN ('Food','Drink','Pickup')),
          priority INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 5),
          sequence_no INTEGER NOT NULL UNIQUE,
          status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Completed','Cancelled')),
          created_at TEXT NOT NULL,
          completed_at TEXT
        );
        ''')
        
        # --- Migration: Safely inject high_stock_threshold into existing database ---
        product_columns = {r['name'] for r in c.execute('PRAGMA table_info(products)').fetchall()}
        if 'high_stock_threshold' not in product_columns:
            c.execute("ALTER TABLE products ADD COLUMN high_stock_threshold INTEGER NOT NULL DEFAULT 50 CHECK(high_stock_threshold >= 0)")

        order_columns = {r['name'] for r in c.execute('PRAGMA table_info(pending_orders)').fetchall()}
        if 'order_type' not in order_columns:
            c.execute("ALTER TABLE pending_orders ADD COLUMN order_type TEXT NOT NULL DEFAULT 'Food'")
        columns = {r['name'] for r in c.execute('PRAGMA table_info(transaction_items)').fetchall()}
        if 'size_oz' not in columns:
            c.execute('ALTER TABLE transaction_items ADD COLUMN size_oz INTEGER')
        if 'customizations' not in columns:
            c.execute("ALTER TABLE transaction_items ADD COLUMN customizations TEXT NOT NULL DEFAULT ''")
            
        c.execute('''INSERT OR IGNORE INTO product_sizes(product_id,size_oz,price_cents)
                     SELECT id,8,price_cents FROM products WHERE lower(category)='beverage' ''')
        c.execute('''INSERT OR IGNORE INTO product_sizes(product_id,size_oz,price_cents)
                     SELECT id,12,price_cents FROM products WHERE lower(category)='beverage' ''')
        c.execute('''INSERT OR IGNORE INTO product_sizes(product_id,size_oz,price_cents)
                     SELECT id,16,price_cents FROM products WHERE lower(category)='beverage' ''')
        c.executescript('''
        CREATE INDEX IF NOT EXISTS idx_products_active_name ON products(active, name);
        CREATE INDEX IF NOT EXISTS idx_transactions_created ON transactions(created_at);
        CREATE INDEX IF NOT EXISTS idx_items_transaction ON transaction_items(transaction_id);
        CREATE INDEX IF NOT EXISTS idx_movements_product_date ON inventory_movements(product_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_orders_status_priority ON pending_orders(status, priority, sequence_no);
        CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_history(created_at);
        ''')

def rowdict(row): return dict(row) if row is not None else None

def list_products(db_path=DB_PATH, active_only=False):
    with connection(db_path) as c:
        sql = 'SELECT * FROM products' + (' WHERE active=1' if active_only else '') + ' ORDER BY name COLLATE NOCASE'
        return [dict(r) for r in c.execute(sql).fetchall()]

def get_product(product_id, db_path=DB_PATH):
    with connection(db_path) as c: return rowdict(c.execute('SELECT * FROM products WHERE id=?', (product_id,)).fetchone())

def generate_product_code(db_path=DB_PATH):
    """Generate the next unused GG-#### code, including codes of inactive products."""
    pattern = re.compile(r"^GG-(\d+)$", re.IGNORECASE)
    with connection(db_path) as c:
        existing_codes = [r['code'] for r in c.execute('SELECT code FROM products').fetchall()]
    used_numbers = []
    for existing_code in existing_codes:
        match = pattern.fullmatch(existing_code.strip())
        if match:
            used_numbers.append(int(match.group(1)))
    next_number = max(used_numbers, default=0) + 1
    candidate = f"GG-{next_number:04d}"
    # Also avoid a collision if a product already uses this code in another format.
    existing_upper = {code.upper() for code in existing_codes}
    while candidate.upper() in existing_upper:
        next_number += 1
        candidate = f"GG-{next_number:04d}"
    return candidate

# Inside database.py - Put this exact function structure back
def add_product(code, name, category, price_cents, stock, threshold, db_path=DB_PATH, size_prices=None):
    code, name, category = code.strip().upper(), name.strip(), category.strip()
    if not code or len(code)>30: raise ValueError('Product code is required and must be at most 30 characters.')
    if not name or len(name)>100: raise ValueError('Product name is required and must be at most 100 characters.')
    if not category or len(category)>50: raise ValueError('Choose a valid category (maximum 50 characters).')
    if isinstance(price_cents, bool) or not isinstance(price_cents, int) or price_cents < 0: raise ValueError('Price must be a non-negative amount.')
    if isinstance(stock, bool) or not isinstance(stock, int) or stock < 0: raise ValueError('Stock must be a non-negative whole number.')
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0: raise ValueError('Low-stock threshold must be a non-negative whole number.')
    
    now = datetime.now().isoformat()
    
    with connection(db_path) as c:
        res = c.execute('''
            INSERT INTO products (code, name, category, price_cents, stock, low_stock_threshold, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        ''', (code, name, category, price_cents, stock, threshold, now, now))
        
        product_id = res.lastrowid
        
        if size_prices:
            for size_oz, pr_cents in size_prices.items():
                c.execute('''
                    INSERT INTO product_sizes (product_id, size_oz, price_cents)
                    VALUES (?, ?, ?)
                ''', (product_id, int(size_oz), pr_cents))
                
        return product_id
    except sqlite3.IntegrityError as e:
        if 'products.code' in str(e).lower(): raise ValueError('That product code already exists.') from e
        raise

def _validate_size_prices(size_prices, allow_subset=False):
    valid = isinstance(size_prices, dict) and bool(size_prices) and set(size_prices).issubset({8, 12, 16})
    if not valid or (not allow_subset and set(size_prices) != {8, 12, 16}):
        raise ValueError('Set valid prices for the available drink sizes (8 oz, 12 oz, and/or 16 oz).')
    for size, price in size_prices.items():
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            raise ValueError(f'The {size} oz price must be a non-negative whole number of centavos.')


def get_product_sizes(product_id, db_path=DB_PATH):
    with connection(db_path) as c:
        rows = c.execute('SELECT size_oz,price_cents FROM product_sizes WHERE product_id=? ORDER BY size_oz', (product_id,)).fetchall()
        return {int(r['size_oz']): int(r['price_cents']) for r in rows}


def set_product_sizes(product_id, size_prices, db_path=DB_PATH):
    _validate_size_prices(size_prices, allow_subset=True)
    with connection(db_path) as c:
        product = c.execute("SELECT id FROM products WHERE id=? AND active=1", (product_id,)).fetchone()
        if not product:
            raise ValueError('Product not found or inactive.')
        for size in (8, 12, 16):
            if size in size_prices:
                c.execute('''INSERT INTO product_sizes(product_id,size_oz,price_cents) VALUES(?,?,?)
                             ON CONFLICT(product_id,size_oz) DO UPDATE SET price_cents=excluded.price_cents''',
                          (product_id,size,int(size_prices[size])))
            else:
                c.execute('DELETE FROM product_sizes WHERE product_id=? AND size_oz=?', (product_id,size))
        # Use 12 oz as the standard price when available, otherwise the first available size.
        standard_price=int(size_prices.get(12, next(iter(size_prices.values()))))
        c.execute('UPDATE products SET price_cents=?,updated_at=? WHERE id=?',
                  (standard_price,datetime.now().isoformat(timespec='seconds'),product_id))


def update_product(product_id, code, name, category, price_cents, threshold, db_path=DB_PATH):
    code, name, category = code.strip().upper(), name.strip(), category.strip()
    if not code or len(code)>30 or not name or len(name)>100 or not category or len(category)>50: raise ValueError('Code, name, and category are required and must fit the field limits.')
    if isinstance(price_cents,bool) or not isinstance(price_cents,int) or price_cents<0: raise ValueError('Price must be non-negative.')
    if isinstance(threshold,bool) or not isinstance(threshold,int) or threshold<0: raise ValueError('Threshold must be a non-negative whole number.')
    now = datetime.now().isoformat(timespec='seconds')
    try:
        with connection(db_path) as c:
            cur=c.execute('UPDATE products SET code=?,name=?,category=?,price_cents=?,low_stock_threshold=?,updated_at=? WHERE id=? AND active=1', (code,name,category,price_cents,threshold,now,product_id))
            if cur.rowcount != 1: raise ValueError('Product not found or already inactive.')
    except sqlite3.IntegrityError as e:
        if 'products.code' in str(e).lower(): raise ValueError('That product code already exists.') from e
        raise

def deactivate_product(product_id, db_path=DB_PATH):
    with connection(db_path) as c:
        cur=c.execute('UPDATE products SET active=0,updated_at=? WHERE id=? AND active=1', (datetime.now().isoformat(timespec='seconds'),product_id))
        if cur.rowcount != 1: raise ValueError('Product not found or already inactive.')

def restock_product(product_id, quantity, db_path=DB_PATH):
    if isinstance(quantity,bool) or not isinstance(quantity,int) or quantity<1: raise ValueError('Restock quantity must be a positive whole number.')
    now=datetime.now().isoformat(timespec='seconds')
    with connection(db_path) as c:
        cur=c.execute('UPDATE products SET stock=stock+?,updated_at=? WHERE id=? AND active=1', (quantity,now,product_id))
        if cur.rowcount != 1: raise ValueError('Product not found or inactive.')
        c.execute('INSERT INTO inventory_movements(product_id,quantity_change,reason,created_at) VALUES(?,?,?,?)', (product_id,quantity,'Restock',now))

def checkout(cart_items, cashier_label='Cashier', db_path=DB_PATH, fail_after_items=None):
    """Atomic checkout. Validates size availability and preserves item customizations."""
    if not cart_items: raise ValueError('Your cart is empty.')
    now=datetime.now().isoformat(timespec='seconds')
    normalized=[]; keys=[]
    for item in cart_items:
        q=item.get('quantity'); pid=int(item['product_id']); size=item.get('size_oz')
        customizations=str(item.get('customizations','') or '')
        if isinstance(q, bool) or not isinstance(q, int) or q < 1: raise ValueError('Every item quantity must be a positive whole number.')
        if size is not None and (isinstance(size,bool) or size not in (8,12,16)): raise ValueError('Drink size must be 8 oz, 12 oz, or 16 oz.')
        key=(pid,size,customizations)
        if key in keys: raise ValueError('Cart contains duplicate product/size/options entries; update the quantities and retry.')
        keys.append(key); normalized.append((pid,q,size,customizations))
    with connection(db_path) as c:
        current=[]; total=0
        for pid,q,size,customizations in normalized:
            p=c.execute('SELECT * FROM products WHERE id=? AND active=1', (pid,)).fetchone()
            if not p: raise ValueError('A cart product is missing or inactive. Refresh the cart and try again.')
            if q > p['stock']: raise ValueError(f"Insufficient stock for {p['name']}: available {p['stock']}, requested {q}.")
            size_rows=c.execute('SELECT size_oz,price_cents FROM product_sizes WHERE product_id=?',(pid,)).fetchall()
            if size is not None:
                size_row=next((r for r in size_rows if int(r['size_oz'])==int(size)),None)
                if not size_row: raise ValueError(f'The {size} oz size is not available for {p["name"]}.')
                unit_price=int(size_row['price_cents'])
            else:
                if size_rows: raise ValueError(f'Choose a size for {p["name"]} before checkout.')
                unit_price=int(p['price_cents'])
            subtotal=unit_price*q; total+=subtotal
            current.append((p,q,size,unit_price,subtotal,customizations))
        cur=c.execute('INSERT INTO transactions(total_cents,created_at,cashier_label) VALUES(?,?,?)',(total,now,cashier_label))
        tid=cur.lastrowid
        c.execute('INSERT INTO activity_history(actor_mode,action,details,created_at) VALUES(?,?,?,?)',('Cashier','Sale completed',f'Sale #{tid} · {cashier_label} · Total ₱{total/100:.2f}',now))
        for index,(p,q,size,unit_price,subtotal,customizations) in enumerate(current,start=1):
            c.execute("INSERT INTO transaction_items(transaction_id,product_id,product_code,product_name,unit_price_cents,quantity,subtotal_cents,size_oz,customizations) VALUES(?,?,?,?,?,?,?,?,?)",(tid,p['id'],p['code'],p['name'],unit_price,q,subtotal,size,customizations))
            cur=c.execute('UPDATE products SET stock=stock-?,updated_at=? WHERE id=? AND active=1 AND stock>=?',(q,now,p['id'],q))
            if cur.rowcount != 1: raise ValueError(f'Stock changed for {p["name"]}; refresh and try again.')
            c.execute('INSERT INTO inventory_movements(product_id,quantity_change,reason,created_at) VALUES(?,?,?,?)',(p['id'],-q,f'Sale #{tid}',now))
            if fail_after_items is not None and index >= fail_after_items: raise RuntimeError('Injected failure for rollback test.')
        return {'transaction_id':tid,'total_cents':total,'created_at':now,'items':[{'code':p['code'],'name':p['name'],'size_oz':size,'quantity':q,'unit_price_cents':unit_price,'subtotal_cents':subtotal,'customizations':customizations} for p,q,size,unit_price,subtotal,customizations in current]}

def sales_summary(start_iso, end_iso, db_path=DB_PATH):
    with connection(db_path) as c:
        row=c.execute('SELECT COALESCE(SUM(total_cents),0) total, COUNT(*) count FROM transactions WHERE created_at>=? AND created_at<?', (start_iso,end_iso)).fetchone()
        return {'revenue_cents':int(row['total']),'transactions':int(row['count'])}

def transaction_history(start_iso=None, end_iso=None, db_path=DB_PATH):
    sql='SELECT * FROM transactions WHERE 1=1'; params=[]
    if start_iso: sql+=' AND created_at>=?'; params.append(start_iso)
    if end_iso: sql+=' AND created_at<?'; params.append(end_iso)
    sql+=' ORDER BY id DESC'
    with connection(db_path) as c: return [dict(r) for r in c.execute(sql,params).fetchall()]

def transaction_items(transaction_id, db_path=DB_PATH):
    with connection(db_path) as c: return [dict(r) for r in c.execute('SELECT * FROM transaction_items WHERE transaction_id=? ORDER BY id',(transaction_id,)).fetchall()]

def list_orders(pending_only=False, db_path=DB_PATH, order_type=None):
    clauses=[]; params=[]
    if pending_only: clauses.append("status='Pending'")
    if order_type: clauses.append('order_type=?'); params.append(order_type)
    sql='SELECT * FROM pending_orders'+((' WHERE '+' AND '.join(clauses)) if clauses else '')+' ORDER BY priority ASC, sequence_no ASC'
    with connection(db_path) as c: return [dict(r) for r in c.execute(sql,params).fetchall()]

def add_order(customer_name, details, priority, db_path=DB_PATH, order_type='Food'):
    customer_name,details=customer_name.strip(),details.strip()
    if not customer_name or len(customer_name)>100: raise ValueError('Customer name is required (maximum 100 characters).')
    if not details or len(details)>500: raise ValueError('Order details are required (maximum 500 characters).')
    if order_type not in ('Food','Drink','Pickup'): raise ValueError('Order type must be Food, Drink, or Pickup.')
    if isinstance(priority,bool) or not isinstance(priority,int) or priority not in range(1,6): raise ValueError('Priority must be from 1 (most urgent) to 5 (least urgent).')
    now=datetime.now().isoformat(timespec='seconds')
    with connection(db_path) as c:
        cur=c.execute('INSERT INTO pending_orders(customer_name,details,order_type,priority,sequence_no,created_at) VALUES(?,?,?,?,?,?)',(customer_name,details,order_type,priority,0,now))
        oid=cur.lastrowid
        c.execute('UPDATE pending_orders SET sequence_no=? WHERE id=?',(oid,oid))
        c.execute('INSERT INTO activity_history(actor_mode,action,details,created_at) VALUES(?,?,?,?)',('Cashier','Order queued',f'Order #{oid} · {order_type} · {customer_name} · Priority {priority} · {details}',now))
        return oid

def update_order_status(order_id, status, db_path=DB_PATH):
    if status not in ('Completed','Cancelled'): raise ValueError('Invalid order status.')
    with connection(db_path) as c:
        cur=c.execute("UPDATE pending_orders SET status=?,completed_at=? WHERE id=? AND status='Pending'",(status,datetime.now().isoformat(timespec='seconds'),order_id))
        if cur.rowcount != 1: raise ValueError('Pending order not found; it may already be processed.')
        c.execute('INSERT INTO activity_history(actor_mode,action,details,created_at) VALUES(?,?,?,?)',('Kitchen' if status=='Completed' else 'Cashier',f'Order {status.lower()}',f'Order #{order_id}',datetime.now().isoformat(timespec='seconds')))

def log_activity(actor_mode, action, details='', db_path=DB_PATH):
    """Persist an audit entry for important Admin, Cashier, and Kitchen actions."""
    if actor_mode not in ('Admin','Cashier','Kitchen','System'):
        raise ValueError('Invalid activity role.')
    action = str(action).strip()[:100]
    details = str(details).strip()[:1000]
    if not action:
        raise ValueError('Activity action is required.')
    with connection(db_path) as c:
        c.execute('INSERT INTO activity_history(actor_mode,action,details,created_at) VALUES(?,?,?,?)',
                  (actor_mode, action, details, datetime.now().isoformat(timespec='seconds')))


def activity_history(actor_mode=None, search_text='', limit=500, db_path=DB_PATH):
    sql='SELECT * FROM activity_history WHERE 1=1'; params=[]
    if actor_mode and actor_mode != 'All':
        sql += ' AND actor_mode=?'; params.append(actor_mode)
    if search_text.strip():
        sql += ' AND (action LIKE ? OR details LIKE ?)'; term=f'%{search_text.strip()}%'; params.extend([term,term])
    sql += ' ORDER BY id DESC LIMIT ?'; params.append(max(1,min(int(limit),5000)))
    with connection(db_path) as c:
        return [dict(r) for r in c.execute(sql,params).fetchall()]
