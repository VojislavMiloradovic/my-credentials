with open("update_linkedin.py", "rb") as f:
    content = f.read()

# Find the problematic section
idx = content.find(
    b"# 4. Generate L1 baseline fingerprints for cross-artifact validation"
)
if idx >= 0:
    with open("section_output3.txt", "wb") as out:
        out.write(content[idx : idx + 2000])
    print(f"Found at position {idx}, written to file")
else:
    print("Not found")
