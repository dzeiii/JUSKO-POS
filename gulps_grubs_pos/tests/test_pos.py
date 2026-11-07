import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database as db
from data_structures import LinkedListCart, AVLTree, MinHeap, HeapEntry

class DataStructureTests(unittest.TestCase):
    def test_linked_list_cart_operations(self):
        cart=LinkedListCart(); p={'id':1,'code':'A','name':'Tea','price_cents':500}
        cart.add(p,2); cart.add(p,1)
        self.assertEqual(cart.find(1).quantity,3); self.assertEqual(cart.total_cents(),1500)
        self.assertTrue(cart.set_quantity(1,2)); self.assertEqual(cart.total_cents(),1000)
        self.assertTrue(cart.remove(1)); self.assertEqual(len(cart),0)
        cart.add(p,1,size_oz=12,customizations='Sinkers: Nata')
        cart.add(p,1,size_oz=12,customizations='Sinkers: None')
        self.assertEqual(len(cart),2)
        self.assertEqual({x['customizations'] for x in cart.items()},{'Sinkers: Nata','Sinkers: None'})
        with self.assertRaises(ValueError): cart.add(p,0)

    def test_avl_rotations_search_delete_balance(self):
        tree=AVLTree()
        for key in ['C','B','A','D','E','F','G','H','I']:
            tree.insert(key,{'code':key}); self.assertTrue(tree.validate())
        self.assertEqual(tree.search('e')['code'],'E')
        self.assertTrue(tree.delete('D')); self.assertIsNone(tree.search('D')); self.assertTrue(tree.validate())
        self.assertEqual([x['code'] for x in tree.inorder()],sorted(['A','B','C','E','F','G','H','I']))

    def test_min_heap_priority_and_fifo_ties(self):
        heap=MinHeap()
        heap.push(HeapEntry(3,1,1,{})); heap.push(HeapEntry(1,5,2,{})); heap.push(HeapEntry(1,2,3,{}))
        self.assertEqual(heap.peek().order_id,3)
        self.assertEqual([heap.pop().order_id for _ in range(3)],[3,2,1])
        self.assertIsNone(heap.pop())

class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/'test.db'; db.init_db(self.path)
        self.pid=db.add_product('DRK-1','Iced Coffee','Beverage',7500,5,2,self.path)
    def tearDown(self): self.tmp.cleanup()
    def test_auto_product_codes_skip_used_codes_and_inactive_products(self):
        self.assertEqual(db.generate_product_code(self.path), 'GG-0001')
        auto_pid = db.add_product(db.generate_product_code(self.path), 'Brown Sugar Latte', 'Beverage', 5000, 0, 5, self.path)
        self.assertEqual(db.get_product(auto_pid, self.path)['code'], 'GG-0001')
        self.assertEqual(db.generate_product_code(self.path), 'GG-0002')
        db.deactivate_product(auto_pid, self.path)
        self.assertEqual(db.generate_product_code(self.path), 'GG-0002')

    def test_add_update_deactivate_and_duplicate(self):
        with self.assertRaises(ValueError): db.add_product('DRK-1','Duplicate','Beverage',100,1,1,self.path)
        db.update_product(self.pid,'DRK-1','Iced Coffee XL','Beverage',8500,2,self.path)
        self.assertEqual(db.get_product(self.pid,self.path)['price_cents'],8500)
        db.deactivate_product(self.pid,self.path); self.assertEqual(db.get_product(self.pid,self.path)['active'],0)
    def test_checkout_inventory_history_and_restock(self):
        sale=db.checkout([{'product_id':self.pid,'quantity':2,'size_oz':12}],'Test cashier',self.path)
        self.assertEqual(sale['total_cents'],15000); self.assertEqual(db.get_product(self.pid,self.path)['stock'],3)
        hist=db.transaction_history(db_path=self.path); self.assertEqual(len(hist),1)
        items=db.transaction_items(sale['transaction_id'],self.path); self.assertEqual(items[0]['product_name'],'Iced Coffee')
        db.restock_product(self.pid,4,self.path); self.assertEqual(db.get_product(self.pid,self.path)['stock'],7)
    def test_insufficient_stock_rejected_without_transaction(self):
        with self.assertRaises(ValueError): db.checkout([{'product_id':self.pid,'quantity':6,'size_oz':12}],'Cashier',self.path)
        self.assertEqual(db.get_product(self.pid,self.path)['stock'],5)
        self.assertEqual(db.transaction_history(db_path=self.path),[])
    def test_database_rollback_on_failure(self):
        with self.assertRaises(RuntimeError): db.checkout([{'product_id':self.pid,'quantity':2,'size_oz':12}],'Cashier',self.path,fail_after_items=1)
        self.assertEqual(db.get_product(self.pid,self.path)['stock'],5)
        self.assertEqual(db.transaction_history(db_path=self.path),[])
        with db.connection(self.path) as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM inventory_movements').fetchone()[0],1)
    def test_drink_size_prices_and_historical_size(self):
        db.set_product_sizes(self.pid,{8:4000,12:5000,16:6500},self.path)
        sale=db.checkout([{'product_id':self.pid,'quantity':2,'size_oz':16}],'Test cashier',self.path)
        self.assertEqual(sale['total_cents'],13000)
        self.assertEqual(sale['items'][0]['size_oz'],16)
        detail=db.transaction_items(sale['transaction_id'],self.path)
        self.assertEqual(detail[0]['size_oz'],16)
        self.assertEqual(detail[0]['unit_price_cents'],6500)

    def test_manual_drink_sizes_and_customizations_are_preserved(self):
        pid=db.add_product('GG-DRINK-1','Custom Milkshake','Milkshake',3500,4,1,self.path,size_prices={12:3500,16:4500})
        self.assertEqual(db.get_product_sizes(pid,self.path),{12:3500,16:4500})
        sale=db.checkout([{'product_id':pid,'quantity':1,'size_oz':12,'customizations':'Sinkers: Nata'}],'Cashier',self.path)
        detail=db.transaction_items(sale['transaction_id'],self.path)[0]
        self.assertEqual(detail['customizations'],'Sinkers: Nata')
        self.assertEqual(detail['unit_price_cents'],3500)

    def test_order_priority_and_status(self):
        a=db.add_order('Pat','1 latte',4,self.path); b=db.add_order('Sam','2 teas',1,self.path)
        heap=MinHeap()
        for o in db.list_orders(True,self.path): heap.push(HeapEntry(o['priority'],o['sequence_no'],o['id'],o))
        self.assertEqual(heap.pop().order_id,b); self.assertEqual(heap.pop().order_id,a)
        db.update_order_status(b,'Completed',self.path)
        self.assertEqual([o['id'] for o in db.list_orders(True,self.path)],[a])

if __name__=='__main__': unittest.main(verbosity=2)
