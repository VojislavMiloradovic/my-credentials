with open("update_linkedin.py", "rb") as f:
    content = f.read()

# Find the problematic section
idx = content.find(
    b"# 4. Generate L1 baseline fingerprints for cross-artifact validation"
)
if idx >= 0:
    print(f"Found at position {idx}")
    print(content[idx : idx + 2000].decode("utf-8", errors="replace"))
else:
    print("Not found")

# Also find the total_certs line
idx2 = content.find(b"total_certs = len(certs)")
if idx2 >= 0:
    print(f"total_certs at position {idx2}")
    print(content[idx2 - 200 : idx2 + 200].decode("utf-8", errors="replace"))
