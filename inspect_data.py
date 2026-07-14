import os
import json

def inspect_json():
    # Find any JSON file in the data folder
    data_dir = "data"
    json_files = [f for f in os.listdir(data_dir) if f.endswith('.json')]
    
    if not json_files:
        print("No JSON file found in the 'data' folder!")
        return
        
    file_path = os.path.join(data_dir, json_files[0])
    print(f"Reading {file_path}...")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    summary = []
    summary.append(f"File Name: {json_files[0]}")
    summary.append(f"Data Type: {type(data).__name__}\n")
    
    if isinstance(data, dict):
        summary.append("=== TOP LEVEL KEYS ===")
        for key, val in data.items():
            val_type = type(val).__name__
            length_info = f" (Length: {len(val)})" if hasattr(val, '__len__') and not isinstance(val, str) else ""
            summary.append(f"- {key}: {val_type}{length_info}")
            
            # If it's a list, let's inspect the first item
            if isinstance(val, list) and len(val) > 0:
                first_item = val[0]
                summary.append(f"  * Sample item type: {type(first_item).__name__}")
                if isinstance(first_item, dict):
                    summary.append(f"  * Sample keys: {list(first_item.keys())}")
                    # Give a tiny preview of string values (truncated)
                    preview = {k: (str(v)[:100] + '...' if len(str(v)) > 100 else v) for k, v in first_item.items()}
                    summary.append(f"  * Sample data preview: {json.dumps(preview, indent=4)}")
                summary.append("") # Spacer
                
    elif isinstance(data, list):
        summary.append(f"Root is a List of {len(data)} items.")
        if len(data) > 0:
            first_item = data[0]
            summary.append(f"Sample item keys: {list(first_item.keys()) if isinstance(first_item, dict) else type(first_item).__name__}")

    # Write summary to a file
    output_path = os.path.join(data_dir, "structure_summary.txt")
    with open(output_path, 'w', encoding='utf-8') as out:
        out.write("\n".join(summary))
    print(f"Summary written to {output_path}")

if __name__ == "__main__":
    inspect_json()
