import os
import json

def repair_and_inspect():
    data_dir = "data"
    json_files = [f for f in os.listdir(data_dir) if f.endswith('.json')]
    
    if not json_files:
        print("No JSON file found in the 'data' folder!")
        return
        
    file_path = os.path.join(data_dir, json_files[0])
    print(f"Reading {file_path}...")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # 1. Automatically escape the unescaped REDACTED double quotes
    repaired = False
    if 'AccountKey="REDACTED"' in content:
        print("🔧 Found unescaped 'AccountKey=\"REDACTED\"'. Auto-repairing...")
        # We replace it with properly escaped quotes so it doesn't break the JSON string
        content = content.replace('AccountKey="REDACTED"', 'AccountKey=\\"REDACTED\\"')
        repaired = True
        
    # 2. If repaired, write the cleaned JSON back to the repository
    if repaired:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print("✅ Cleaned JSON file saved back to the directory!")

    # 3. Try to parse and generate the structure summary
    try:
        data = json.loads(content)
        print("🎉 Success! JSON parsed perfectly.")
        
        summary = []
        summary.append(f"File Name: {json_files[0]}")
        summary.append(f"Data Type: {type(data).__name__}\n")
        
        if isinstance(data, dict):
            summary.append("=== TOP LEVEL KEYS ===")
            for key, val in data.items():
                val_type = type(val).__name__
                length_info = f" (Length: {len(val)})" if hasattr(val, '__len__') and not isinstance(val, str) else ""
                summary.append(f"- {key}: {val_type}{length_info}")
                
                if isinstance(val, list) and len(val) > 0:
                    first_item = val[0]
                    summary.append(f"  * Sample item type: {type(first_item).__name__}")
                    if isinstance(first_item, dict):
                        summary.append(f"  * Sample keys: {list(first_item.keys())}")
                    summary.append("") # Spacer
                    
        # Write summary
        output_path = os.path.join(data_dir, "structure_summary.txt")
        with open(output_path, 'w', encoding='utf-8') as out:
            out.write("\n".join(summary))
        print(f"Summary written to {output_path}")
        
    except json.JSONDecodeError as e:
        print(f"❌ Another syntax error detected: {e}")
        raise e

if __name__ == "__main__":
    repair_and_inspect()
