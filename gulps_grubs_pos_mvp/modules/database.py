import os
import sqlite3
from pathlib import Path

# Streamlit Cloud can set GULPS_GRUBS_DB_PATH to a mounted persistent
# location. Otherwise, keep the database in the project's data/ directory.
PROJECT_DIR = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("GULPS_GRUBS_DB_PATH", PROJECT_DIR / "data" / "gulps_grubs.db"))


def connect():
    # SQLite creates the database file, but it cannot create missing folders.
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c
def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL,category TEXT NOT NULL,size TEXT NOT NULL,price REAL NOT NULL,stock INTEGER NOT NULL DEFAULT 0,
          low_stock INTEGER NOT NULL DEFAULT 5,availability TEXT NOT NULL DEFAULT 'Available');
        CREATE TABLE IF NOT EXISTS inventory(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL,kind TEXT NOT NULL,unit TEXT NOT NULL,quantity REAL NOT NULL DEFAULT 0,reorder_level REAL NOT NULL DEFAULT 5);
        CREATE TABLE IF NOT EXISTS inventory_movements(id INTEGER PRIMARY KEY AUTOINCREMENT,inventory_code TEXT,movement TEXT,
          quantity REAL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,total REAL NOT NULL,priority TEXT NOT NULL,
          priority_rank INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'Pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS order_items(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL,
          product_id INTEGER,product_name TEXT NOT NULL,price REAL NOT NULL,quantity INTEGER NOT NULL,subtotal REAL NOT NULL,
          FOREIGN KEY(order_id) REFERENCES orders(id));
        CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        # One-time menu reset requested by the owner. This clears the old menu
        # exactly once while preserving orders, sales history, and inventory.
        reset_key = "empty_menu_reset_2026_11_v1"
        reset_done = c.execute("SELECT value FROM app_settings WHERE key=?", (reset_key,)).fetchone()
        if not reset_done:
            c.execute("DELETE FROM products")
            c.execute("INSERT INTO app_settings(key,value) VALUES(?,?)", (reset_key, "done"))
        # Products are intentionally NOT preloaded. Add them manually in Admin.
        if c.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]==0:
            c.executemany("INSERT INTO inventory(code,name,kind,unit,quantity,reorder_level) VALUES(?,?,?,?,?,?)",[
            ("PKG-001","12 oz cups","Packaging","pcs",100,20),("PKG-002","16 oz cups","Packaging","pcs",100,20),
            ("PKG-003","Straws","Packaging","pcs",200,30),("RAW-001","Milk","Ingredient","liters",10,3),
            ("RAW-002","Sugar","Ingredient","kg",8,2),("RAW-003","Pearls / Sago","Ingredient","kg",4,1)])
def fetch(sql,args=()):
    with connect() as c:return [dict(r) for r in c.execute(sql,args).fetchall()]
def get_products():return fetch("SELECT * FROM products ORDER BY name,size")
def get_inventory():return fetch("SELECT * FROM inventory ORDER BY kind,name")
def get_orders(statuses=None):
    if statuses:
        marks=",".join("?" for _ in statuses); return fetch(f"SELECT * FROM orders WHERE status IN ({marks}) ORDER BY created_at",statuses)
    return fetch("SELECT * FROM orders ORDER BY id DESC")
def get_sales_summary():return fetch("SELECT COALESCE(SUM(total),0) sales,COUNT(*) transactions FROM orders WHERE status='Completed'")[0]
def get_low_stock():return fetch("SELECT * FROM products WHERE stock<=low_stock ORDER BY stock")
