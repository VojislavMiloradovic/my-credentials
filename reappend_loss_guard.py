with open(r'C:\Users\Toughbook\OneDrive\Documents\GitHub\my-credentials\loss_guard.py', 'r', encoding='utf-8') as f:
    old = f.read()

with open(r'C:\Users\Toughbook\OneDrive\Documents\GitHub\my-credentials\loss_guard_additions.py', 'r', encoding='utf-8') as f:
    add = f.read()

new = old + "\n\n" + add

with open(r'C:\Users\Toughbook\OneDrive\Documents\GitHub\my-credentials\loss_guard.py', 'w', encoding='utf-8') as f:
    f.write(new)

print("Appended successfully")