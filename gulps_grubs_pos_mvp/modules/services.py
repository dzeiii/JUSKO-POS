from modules.database import connect
RANK={"Urgent":1,"High":2,"Normal":3}
def gen_code(category):
    prefix={"Milkshake":"MIL","Milktea":"MT","Float":"FLT","Snack":"SNK"}.get(category,"OTH")
    with connect() as c:n=c.execute("SELECT COUNT(*) FROM products WHERE code LIKE ?",(prefix+"-%",)).fetchone()[0]+1
    return f"{prefix}-{n:03d}"
def save_product(code,name,category,size,price,stock,low):
    code=code or gen_code(category)
    with connect() as c:c.execute("""INSERT INTO products(code,name,category,size,price,stock,low_stock)
    VALUES(?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name,category=excluded.category,
    size=excluded.size,price=excluded.price,stock=excluded.stock,low_stock=excluded.low_stock""",
    (code,name,category,size,price,stock,low))
def delete_product(code):
    with connect() as c:c.execute("DELETE FROM products WHERE code=?",(code,))
def adjust_stock(code,delta):
    with connect() as c:
        r=c.execute("SELECT stock FROM products WHERE code=?",(code,)).fetchone()
        if not r or r[0]+delta<0:raise ValueError("Product not found or stock cannot become negative.")
        c.execute("UPDATE products SET stock=stock+? WHERE code=?",(delta,code))
def add_inventory_item(name,kind,unit,qty,reorder):
    prefix="PKG" if kind=="Packaging" else "RAW"
    with connect() as c:
        n=c.execute("SELECT COUNT(*) FROM inventory WHERE code LIKE ?",(prefix+"-%",)).fetchone()[0]+1
        c.execute("INSERT INTO inventory(code,name,kind,unit,quantity,reorder_level) VALUES(?,?,?,?,?,?)",
                  (f"{prefix}-{n:03d}",name,kind,unit,qty,reorder))
def restock_inventory(code,qty):
    with connect() as c:
        c.execute("UPDATE inventory SET quantity=quantity+? WHERE code=?",(qty,code))
        c.execute("INSERT INTO inventory_movements(inventory_code,movement,quantity) VALUES(?,?,?)",(code,"RESTOCK",qty))
def delete_inventory_item(code):
    with connect() as c:c.execute("DELETE FROM inventory WHERE code=?",(code,))
def create_order(items,total,priority):
    with connect() as c:
        for item in items:
            p=c.execute("SELECT stock,size FROM products WHERE id=?",(item["product_id"],)).fetchone()
            if not p or p["stock"]<item["quantity"]:raise ValueError(f'Insufficient menu stock for {item["name"]}.')
            if p["size"] in ("8oz","12 oz","16 oz"):
                cup=c.execute("SELECT id,quantity FROM inventory WHERE kind='Packaging' AND lower(name)=lower(?)",
                              (p["size"]+" cups",)).fetchone()
                if not cup or cup["quantity"]<item["quantity"]:raise ValueError(f'Not enough {p["size"]} cups in shared supplies.')
            straw=c.execute("SELECT id,quantity FROM inventory WHERE kind='Packaging' AND lower(name)='straws'").fetchone()
            if straw and straw["quantity"]<item["quantity"]:raise ValueError("Not enough straws in shared supplies.")
        cur=c.execute("INSERT INTO orders(total,priority,priority_rank) VALUES(?,?,?)",(total,priority,RANK[priority]))
        oid=cur.lastrowid
        for item in items:
            p=c.execute("SELECT size FROM products WHERE id=?",(item["product_id"],)).fetchone()
            c.execute("INSERT INTO order_items(order_id,product_id,product_name,price,quantity,subtotal) VALUES(?,?,?,?,?,?)",
                      (oid,item["product_id"],item["name"],item["price"],item["quantity"],item["subtotal"]))
            c.execute("UPDATE products SET stock=stock-? WHERE id=?",(item["quantity"],item["product_id"]))
            if p["size"] in ("8oz","12 oz","16 oz"):
                c.execute("UPDATE inventory SET quantity=quantity-? WHERE kind='Packaging' AND lower(name)=lower(?)",
                          (item["quantity"],p["size"]+" cups"))
            c.execute("UPDATE inventory SET quantity=quantity-? WHERE kind='Packaging' AND lower(name)='straws'",(item["quantity"],))
        return oid
def update_order_status(oid,status):
    with connect() as c:c.execute("UPDATE orders SET status=? WHERE id=?",(status,oid))
