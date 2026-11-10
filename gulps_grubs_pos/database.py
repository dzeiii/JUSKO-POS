"""SQLite persistence and atomic business operations for the POS MVP."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import re
from datetime import datetime, timedelta

def get_ph_iso_timestamp():
    """Generates a reliable string timestamp calibrated to Philippine Standard Time (UTC+8)."""
    return (datetime.utcnow() + timedelta(hours=8)).isoformat()


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
          high_stock_threshold INTEGER NOT NULL DEFAULT 50 CHECK(high_stock_threshold >= 0),
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
          size_oz INTEGER NOT NULL CHECK(size_oz IN (8,12,16,99)), 
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
          size_oz INTEGER CHECK(size_oz IN (8,12,16,99) OR size_oz IS NULL),
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
          actor_mode TEXT NOT NULL CHECK(actor_mode IN ('Admin','Cashier','Inventory Manager','System')),
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
        try:
            c.execute("SAVEPOINT tx_items_check;")
            c.execute('''
                INSERT INTO transaction_items (transaction_id, product_id, product_code, product_name, unit_price_cents, quantity, subtotal_cents, size_oz, customizations)
                VALUES (0, 0, 'MIG_TEST', 'Migration Test', 0, 1, 0, 99, '');
            ''')
            c.execute("ROLLBACK TO tx_items_check;")
            c.execute("RELEASE tx_items_check;")
        except sqlite3.IntegrityError:
            c.execute("ROLLBACK TO tx_items_check;")
            c.execute("RELEASE tx_items_check;")
            
            old_items = c.execute("SELECT id, transaction_id, product_id, product_code, product_name, unit_price_cents, quantity, subtotal_cents, size_oz, customizations FROM transaction_items").fetchall()
            
            c.execute("DROP TABLE transaction_items")
            c.execute('''
                CREATE TABLE transaction_items (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  transaction_id INTEGER NOT NULL REFERENCES transactions(id),
                  product_id INTEGER REFERENCES products(id),
                  product_code TEXT NOT NULL,
                  product_name TEXT NOT NULL,
                  unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0),
                  quantity INTEGER NOT NULL CHECK(quantity > 0),
                  subtotal_cents INTEGER NOT NULL CHECK(subtotal_cents >= 0),
                  size_oz INTEGER CHECK(size_oz IN (8,12,16,99) OR size_oz IS NULL),
                  customizations TEXT NOT NULL DEFAULT ''
                );
            ''')
            
            for r in old_items:
                c.execute('''
                    INSERT INTO transaction_items (id, transaction_id, product_id, product_code, product_name, unit_price_cents, quantity, subtotal_cents, size_oz, customizations)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (r['id'], r['transaction_id'], r['product_id'], r['product_code'], r['product_name'], r['unit_price_cents'], r['quantity'], r['subtotal_cents'], r['size_oz'], r['customizations']))

def rowdict(row): return dict(row) if row is not None else None

def list_products(db_path=DB_PATH, active_only=False):
    with connection(db_path) as c:
        sql = 'SELECT * FROM products' + (' WHERE active=1' if active_only else '') + ' ORDER BY name COLLATE NOCASE'
        return [dict(r) for r in c.execute(sql).fetchall()]

def get_product(product_id, db_path=DB_PATH):
    with connection(db_path) as c: return rowdict(c.execute('SELECT * FROM products WHERE id=?', (product_id,)).fetchone())

def generate_product_code(classification, db_path=DB_PATH):
    """Generates a gap-filling product code by finding the lowest available sequential number."""
    prefix_map = {
        'Foods (Grubs)': 'GRB',
        'Drinks (Gulps)': 'GLP',
        'Others (Combo/Meal Plan)': 'CMB'
    }
    prefix = prefix_map.get(classification, 'PRD')
    
    with connection(db_path) as c:
        # 1. Pull ALL active codes for this specific prefix from the live table columns
        rows = c.execute(
            "SELECT code FROM products WHERE code LIKE ?", 
            (f"{prefix}-%",)
        ).fetchall()
        
        # 2. Extract the numeric suffix integers into a lookup set array
        active_numbers = set()
        for r in rows:
            try:
                num_part = int(r['code'].split('-')[1])
                active_numbers.add(num_part)
            except (ValueError, IndexError):
                continue
        
        # 3. GAP FINDER: Start at 1001 and look for the very first number that is NOT currently on your screen
        candidate_number = 1001
        while candidate_number in active_numbers:
            candidate_number += 1
            
        # Returns the lowest available empty slot (e.g., if 1002 is missing, it returns 1002)
        return f"{prefix}-{candidate_number:04d}"


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
        while True:
            collision_check = c.execute('SELECT 1 FROM products WHERE code = ?', (code,)).fetchone()
            if not collision_check:
                break
            try:
                prefix, num_part = code.split("-")
                code = f"{prefix}-{int(num_part) + 1}"
            except (ValueError, IndexError):
                code = f"{code}_1"
        try:
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
            raise ValueError(f"The product code '{code}' is already taken.")

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

def set_product_sizes(product_id, sizes_dict, db_path=DB_PATH):
    # --- FIND AND FIX THIS EXACT VALIDATION CHECK IN DATABASE.PY ---
    # Ensure it allows key 99 (custom size) alongside 8, 12, and 16
    valid_sizes = {8, 12, 16, 99}
    
    # Check if ANY of the keys provided are valid
    if not sizes_dict or not any(int(sz) in valid_sizes for sz in sizes_dict.keys()):
        raise ValueError("Set valid prices for the available drink sizes (8 oz, 12 oz, and/or 16 oz).")

    # The rest of your function code continues exactly the same below...
    with connection(db_path) as c:
        c.execute('DELETE FROM product_sizes WHERE product_id = ?', (product_id,))
        for size_oz, price_cents in sizes_dict.items():
            c.execute('''
                INSERT INTO product_sizes (product_id, size_oz, price_cents)
                VALUES (?, ?, ?)
            ''', (product_id, int(size_oz), int(price_cents)))

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

def delete_product(product_id, db_path=DB_PATH):
    """Forced cascade delete to completely purge a product and its history line item logs."""
    with connection(db_path) as c:
        c.execute("DELETE FROM transaction_items WHERE product_id = ?", (product_id,))
        c.execute("DELETE FROM product_sizes WHERE product_id = ?", (product_id,))
        c.execute("DELETE FROM inventory_movements WHERE product_id = ?", (product_id,))
        c.execute("DELETE FROM products WHERE id = ?", (product_id,))
        
    return True, "Product and all its transaction history lines successfully purged."

def restock_product(product_id, quantity, db_path=DB_PATH):
    if isinstance(quantity,bool) or not isinstance(quantity,int) or quantity<1: raise ValueError('Restock quantity must be a positive whole number.')
    now=datetime.now().isoformat(timespec='seconds')
    with connection(db_path) as c:
        cur=c.execute('UPDATE products SET stock=stock+?,updated_at=? WHERE id=? AND active=1', (quantity,now,product_id))
        if cur.rowcount != 1: raise ValueError('Product not found or inactive.')
        c.execute('INSERT INTO inventory_movements(product_id,quantity_change,reason,created_at) VALUES(?,?,?,?)', (product_id,quantity,'Restock',now))

def checkout(items, cashier_label='Cashier', db_path=DB_PATH):
    """Safely processes and persists sales transactions into table records."""
    if not items:
        raise ValueError("Cannot checkout an empty shopping cart configuration.")
        
    current_time = get_ph_iso_timestamp()
    
    with connection(db_path) as c:
        total_cents = sum(item['subtotal_cents'] for item in items)
        
        # ✨ FIXED: Save the execution statement result into a cursor variable
        cursor = c.execute(
            'INSERT INTO transactions (total_cents, created_at, cashier_label) VALUES (?, ?, ?)',
            (total_cents, current_time, cashier_label.strip() or 'Cashier')
        )
        transaction_id = cursor.lastrowid # ✨ FIXED: Read from cursor instead of c
        
        for item in items:
            p_id = item.get('id') if item.get('id') is not None else item.get('product_id')
            qty = item['quantity']
            if p_id is None:
                raise ValueError("Could not find a valid product ID reference inside the cart payload.")
    
            prod = c.execute('SELECT * FROM products WHERE id=?', (p_id,)).fetchone()
            if not prod:
                raise ValueError(f"Product reference ID {p_id} could not be found.")
                
            if prod['stock'] < qty:
                raise ValueError(f"Insufficient stock for '{prod['name']}'. Only {prod['stock']} units remain.")
                
            new_stock = prod['stock'] - qty
            c.execute('UPDATE products SET stock=?, updated_at=? WHERE id=?', (new_stock, current_time, p_id))
            
            c.execute(
                'INSERT INTO inventory_movements (product_id, quantity_change, reason, created_at) VALUES (?, ?, ?, ?)',
                (p_id, -qty, f"Sale Checkout #{transaction_id}", current_time)
            )
            
            size_oz = item.get('size_oz')
            customizations = item.get('customizations', '')
            item_name = item.get('name', prod['name'])
            
            c.execute('''
                INSERT INTO transaction_items (
                    transaction_id, product_id, product_code, product_name, 
                    unit_price_cents, quantity, subtotal_cents, size_oz, customizations
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_id, p_id, prod['code'], item_name,
                item['unit_price_cents'], qty, item['subtotal_cents'],
                size_oz if size_oz is not None else None, customizations
            ))
            
        return {
            'transaction_id': transaction_id,
            'total_cents': total_cents,
            'created_at': current_time,
            'cashier_label': cashier_label
        }

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

def add_order(customer_name, details, priority, order_type='Drink', db_path=DB_PATH):
    """Safely adds a checkout transaction ticket into the kitchen priority pending queue table."""
    current_time = get_ph_iso_timestamp()
    
    with connection(db_path) as c:
        max_seq_row = c.execute('SELECT MAX(sequence_no) as max_seq FROM pending_orders').fetchone()
        next_sequence_no = (max_seq_row['max_seq'] + 1) if (max_seq_row and max_seq_row['max_seq'] is not None) else 1
        
        # ✨ FIXED: Save the execution statement result into a cursor variable
        cursor = c.execute('''
            INSERT INTO pending_orders (
                customer_name, details, order_type, priority, sequence_no, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'Pending', ?)
        ''', (
            customer_name.strip(), 
            details.strip(), 
            order_type, 
            int(priority), 
            next_sequence_no, 
            current_time
        ))
        
        return cursor.lastrowid 
        
def update_order_status(order_id, status):
    from datetime import datetime, timedelta
    
    with connection() as conn:
        conn.execute("UPDATE pending_orders SET status = ? WHERE id = ?", (status, order_id))
    
        ph_now = datetime.utcnow() + timedelta(hours=8)
        current_ph_time = ph_now.strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            INSERT INTO activity_history (created_at, actor_mode, action, details) 
            VALUES (?, ?, ?, ?)
        """, (current_ph_time, "Cashier", "Queue Action", f"Order #{order_id} marked {status}"))


def log_activity(actor_mode, action, details='', db_path=DB_PATH):
    """Persist an audit entry for important Admin, Cashier, and Kitchen actions."""
    if actor_mode not in ('Admin','Cashier','Inventory Manager','System'):
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

def update_product_stock_direct(product_id, new_stock, actor="Inventory Manager", db_path=DB_PATH):
    """Overwrites a product's stock count directly and logs the change."""
    now = datetime.now().isoformat()
    with connection(db_path) as c:
        # Get original stock for logging details
        orig = c.execute("SELECT name, stock FROM products WHERE id = ?", (product_id,)).fetchone()
        if not orig:
            raise ValueError("Product not found.")
            
        c.execute("UPDATE products SET stock = ?, updated_at = ? WHERE id = ?", (new_stock, now, product_id))
        
        diff = new_stock - orig['stock']
        c.execute('''
            INSERT INTO inventory_movements (product_id, quantity_change, reason, created_at)
            VALUES (?, ?, ?, ?)
        ''', (product_id, diff, f"Direct stock audit/override by {actor}", now))

def calculate_available_servings(product_id, db_path=DB_PATH):
    """Calculates the available stock volume metrics for a specific product item."""
    with connection(db_path) as c:
        row = c.execute('SELECT stock FROM products WHERE id = ?', (product_id,)).fetchone()
        return row['stock'] if row else 0


