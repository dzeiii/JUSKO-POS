"""Required data structures, implemented manually for the POS MVP."""
from dataclasses import dataclass
from typing import Any, Optional

from dataclasses import dataclass
from typing import Optional, List, Dict, Any

@dataclass
class CartNode:
    product_id: int
    code: str
    name: str
    unit_price_cents: int
    quantity: int
    size_oz: Optional[int] = None
    customizations: str = ''
    category: str = '' # 🟢 Added to store product grouping text safely
    next: Optional['CartNode'] = None


class LinkedListCart:
    """Singly linked cart; drink variants are distinct nodes keyed by product ID + size."""
    def __init__(self):
        self.head: Optional[CartNode] = None

    def find(self, product_id: int, size_oz: Optional[int] = None, customizations: str = '') -> Optional[CartNode]:
        node = self.head
        while node:
            if node.product_id == product_id and node.size_oz == size_oz and node.customizations == customizations:
                return node
            node = node.next
        return None

    def add(self, product_payload, quantity, size_oz=None, unit_price_cents=0, customizations=""):
        target_size = int(size_oz) if size_oz is not None else None
        
        current = self.head
        while current:
            current_size = int(current.size_oz) if current.size_oz is not None else None
            
            if current.product_id == product_payload['id'] and current_size == target_size and current.customizations == customizations:
                current.quantity += int(quantity)
                return
            current = current.next

        # 🟢 FIX: Map dictionary payload fields correctly to match dataclass fields exactly!
        new_node = CartNode(
            product_id=int(product_payload['id']),
            code=str(product_payload['code']),
            name=str(product_payload['name']),
            unit_price_cents=int(unit_price_cents),
            quantity=int(quantity),
            size_oz=target_size,
            customizations=customizations,
            category=str(product_payload.get('category', ''))
        )
        
        if not self.head:
            self.head = new_node
        else:
            current = self.head
            while current.next:
                current = current.next
            current.next = new_node

    def set_quantity(self, product_id: int, quantity: int, size_oz: Optional[int] = None, customizations: str = '') -> bool:
        node = self.find(product_id, size_oz, customizations)
        if not node: return False
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ValueError('Quantity must be a positive whole number.')
        node.quantity = quantity
        return True

    def remove(self, product_id: int, size_oz: Optional[int] = None, customizations: str = '') -> bool:
        previous, node = None, self.head
        while node:
            if node.product_id == product_id and node.size_oz == size_oz and node.customizations == customizations:
                if previous is None: self.head = node.next
                else: previous.next = node.next
                return True
            previous, node = node, node.next
        return False

    def clear(self): self.head = None

    def items(self):
        item_list = []
        current = self.head
        while current:
            # 🟢 FIX: Read explicit parameters straight from node variables securely
            node_data = {
                'id': current.product_id,
                'product_id': current.product_id,
                'code': current.code,
                'name': current.name,
                'quantity': current.quantity,
                'size_oz': current.size_oz,
                'unit_price_cents': current.unit_price_cents,
                'subtotal_cents': current.unit_price_cents * current.quantity,
                'customizations': current.customizations,
                'category': current.category
            }
            item_list.append(node_data)
            current = current.next
        return item_list

    def total_cents(self) -> int:
        total, node = 0, self.head
        while node:
            total += node.unit_price_cents * node.quantity
            node = node.next
        return total

    def __len__(self):
        count, node = 0, self.head
        while node: count += 1; node = node.next
        return count



@dataclass
class AVLNode:
    key: str
    value: dict
    left: Optional['AVLNode'] = None
    right: Optional['AVLNode'] = None
    height: int = 1


class AVLTree:
    """Self-balancing AVL tree keyed by normalized unique product code."""
    def __init__(self): self.root: Optional[AVLNode] = None
    @staticmethod
    def _height(n): return n.height if n else 0
    @classmethod
    def _update(cls, n): n.height = 1 + max(cls._height(n.left), cls._height(n.right))
    @classmethod
    def _balance(cls, n): return cls._height(n.left) - cls._height(n.right) if n else 0
    @classmethod
    def _rotate_right(cls, y):
        x, t2 = y.left, y.left.right
        x.right, y.left = y, t2
        cls._update(y); cls._update(x)
        return x
    @classmethod
    def _rotate_left(cls, x):
        y, t2 = x.right, x.right.left
        y.left, x.right = x, t2
        cls._update(x); cls._update(y)
        return y
    @classmethod
    def _rebalance(cls, n):
        cls._update(n); b = cls._balance(n)
        if b > 1:
            if cls._balance(n.left) < 0: n.left = cls._rotate_left(n.left)
            return cls._rotate_right(n)
        if b < -1:
            if cls._balance(n.right) > 0: n.right = cls._rotate_right(n.right)
            return cls._rotate_left(n)
        return n
    @staticmethod
    def _key(key): return str(key).strip().casefold()
    def insert(self, key: str, value: dict):
        key = self._key(key)
        if not key: raise ValueError('AVL keys cannot be empty.')
        self.root = self._insert(self.root, key, value)
    @classmethod
    def _insert(cls, n, key, value):
        if not n: return AVLNode(key, value)
        if key < n.key: n.left = cls._insert(n.left, key, value)
        elif key > n.key: n.right = cls._insert(n.right, key, value)
        else: n.value = value; return n
        return cls._rebalance(n)
    def search(self, key):
        key = self._key(key); n = self.root
        while n:
            if key == n.key: return n.value
            n = n.left if key < n.key else n.right
        return None
    @classmethod
    def _min_node(cls, n):
        while n.left: n = n.left
        return n
    def delete(self, key):
        self.root, deleted = self._delete(self.root, self._key(key)); return deleted
    @classmethod
    def _delete(cls, n, key):
        if not n: return None, False
        if key < n.key: n.left, deleted = cls._delete(n.left, key)
        elif key > n.key: n.right, deleted = cls._delete(n.right, key)
        else:
            deleted = True
            if not n.left: return n.right, True
            if not n.right: return n.left, True
            successor = cls._min_node(n.right)
            n.key, n.value = successor.key, successor.value
            n.right, _ = cls._delete(n.right, successor.key)
        return (cls._rebalance(n), deleted) if n else (None, deleted)
    def inorder(self):
        out = []
        def walk(n):
            if n: walk(n.left); out.append(n.value); walk(n.right)
        walk(self.root); return out
    def validate(self):
        """Return True if BST ordering, stored heights, and AVL balance are valid."""
        def check(n, low, high):
            if not n: return 0
            if (low is not None and n.key <= low) or (high is not None and n.key >= high): raise AssertionError('BST ordering broken')
            lh, rh = check(n.left, low, n.key), check(n.right, n.key, high)
            if abs(lh-rh) > 1: raise AssertionError('AVL balance broken')
            if n.height != 1 + max(lh, rh): raise AssertionError('Incorrect node height')
            return n.height
        check(self.root, None, None); return True


@dataclass
class HeapEntry:
    priority: int
    sequence: int
    order_id: int
    payload: dict


class MinHeap:
    """Manual binary min-heap. Lower priority wins; sequence breaks ties FIFO."""
    def __init__(self): self._data: list[HeapEntry] = []
    @staticmethod
    def _key(entry): return (entry.priority, entry.sequence)
    def __len__(self): return len(self._data)
    def push(self, entry: HeapEntry):
        self._data.append(entry); i = len(self._data)-1
        while i > 0:
            p = (i-1)//2
            if self._key(self._data[p]) <= self._key(self._data[i]): break
            self._data[p], self._data[i] = self._data[i], self._data[p]; i = p
    def peek(self): return self._data[0] if self._data else None
    def pop(self):
        if not self._data: return None
        if len(self._data) == 1: return self._data.pop()
        result = self._data[0]; self._data[0] = self._data.pop(); i = 0; n = len(self._data)
        while True:
            left, right, smallest = 2*i+1, 2*i+2, i
            if left < n and self._key(self._data[left]) < self._key(self._data[smallest]): smallest = left
            if right < n and self._key(self._data[right]) < self._key(self._data[smallest]): smallest = right
            if smallest == i: break
            self._data[i], self._data[smallest] = self._data[smallest], self._data[i]; i = smallest
        return result
    def ordered_entries(self):
        # Return sorted snapshot without changing the live heap.
        clone = MinHeap()
        for entry in self._data: clone.push(entry)
        out = []
        while clone: out.append(clone.pop())
        return out
