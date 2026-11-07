class CartNode:
    def __init__(self,pid,name,price,qty,size,code):
        self.product_id,self.name,self.price,self.quantity,self.size,self.code=pid,name,price,qty,size,code
        self.next=None
class LinkedListCart:
    def __init__(self): self.head=None
    def add(self,pid,name,price,qty,size="N/A",code=""):
        cur=self.head
        while cur:
            if cur.product_id==pid: cur.quantity+=qty; return
            cur=cur.next
        n=CartNode(pid,name,price,qty,size,code); n.next=self.head; self.head=n
    def remove(self,pid):
        prev,cur=None,self.head
        while cur:
            if cur.product_id==pid:
                if prev: prev.next=cur.next
                else: self.head=cur.next
                return
            prev,cur=cur,cur.next
    def to_list(self):
        out=[]; cur=self.head
        while cur:
            out.append({"product_id":cur.product_id,"name":cur.name,"price":cur.price,"quantity":cur.quantity,
                        "size":cur.size,"code":cur.code,"subtotal":cur.price*cur.quantity})
            cur=cur.next
        return out
    def total(self): return sum(x["subtotal"] for x in self.to_list())
    def clear(self): self.head=None

class AVLNode:
    def __init__(self,k,v): self.key,self.value,self.left,self.right,self.height=k,v,None,None,1
class AVLTree:
    def __init__(self): self.root=None
    def h(self,n): return n.height if n else 0
    def bal(self,n): return self.h(n.left)-self.h(n.right) if n else 0
    def rr(self,y):
        x=y.left; t=x.right; x.right=y; y.left=t
        y.height=1+max(self.h(y.left),self.h(y.right)); x.height=1+max(self.h(x.left),self.h(x.right)); return x
    def rl(self,x):
        y=x.right; t=y.left; y.left=x; x.right=t
        x.height=1+max(self.h(x.left),self.h(x.right)); y.height=1+max(self.h(y.left),self.h(y.right)); return y
    def insert(self,k,v):
        def add(n):
            if not n: return AVLNode(k,v)
            if k<n.key: n.left=add(n.left)
            elif k>n.key: n.right=add(n.right)
            else: n.value=v; return n
            n.height=1+max(self.h(n.left),self.h(n.right)); b=self.bal(n)
            if b>1 and k<n.left.key: return self.rr(n)
            if b<-1 and k>n.right.key: return self.rl(n)
            if b>1 and k>n.left.key: n.left=self.rl(n.left); return self.rr(n)
            if b<-1 and k<n.right.key: n.right=self.rr(n.right); return self.rl(n)
            return n
        self.root=add(self.root)
    def search_prefix(self,prefix):
        result=[]
        def walk(n):
            if not n:return
            walk(n.left)
            if n.key.startswith(prefix): result.append(n.value)
            walk(n.right)
        walk(self.root); return result

class MinHeap:
    def __init__(self): self.data=[]
    def __len__(self): return len(self.data)
    def push(self,rank,stamp,payload):
        self.data.append((rank,stamp,payload)); i=len(self.data)-1
        while i:
            p=(i-1)//2
            if self.data[p][:2]<=self.data[i][:2]: break
            self.data[p],self.data[i]=self.data[i],self.data[p]; i=p
    def pop(self):
        if not self.data: raise IndexError("empty heap")
        self.data[0],self.data[-1]=self.data[-1],self.data[0]; item=self.data.pop(); i=0
        while True:
            l,r=2*i+1,2*i+2; s=i
            if l<len(self.data) and self.data[l][:2]<self.data[s][:2]: s=l
            if r<len(self.data) and self.data[r][:2]<self.data[s][:2]: s=r
            if s==i: break
            self.data[i],self.data[s]=self.data[s],self.data[i]; i=s
        return item
