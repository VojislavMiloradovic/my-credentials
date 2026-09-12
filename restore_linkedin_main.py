with open(
    r"C:\Users\Toughbook\OneDrive\Documents\GitHub\my-credentials\update_linkedin.py",
    "r",
    encoding="utf-8",
) as f:
    content = f.read()

# Find the main function
idx = content.find("def main():")
if idx >= 0:
    # Find the end of main (next def or end of file)
    next_def = content.find("\ndef ", idx + 10)
    if next_def >= 0:
        main_content = content[idx:next_def]
    else:
        main_content = content[idx:]

    print("Current main function:")
    print(main_content[:2000])
    print("...")
    print(main_content[-2000:] if len(main_content) > 2000 else main_content)
else:
    print("main not found")
