import os
import json

def inspect_json():
    data_dir = "data"
    json_files = [f for f in os.listdir(data_dir) if f.endswith('.json')]
    
    if not json_files:
        print("No JSON file found in the 'data' folder!")
        return
        
    file_path = os.path.join(data_dir, json_files[0])
    print(f"Reading {file_path}...")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            print("Success! JSON parsed perfectly.")
    except json.JSONDecodeError as e:
        print(f"\n❌ JSON Syntax Error detected: {e}")
        print(f"Error is on Line {e.lineno}, Column {e.colno}\n")
        
        # Pull context lines around the error to show us exactly what broke
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            start_line = max(0, e.lineno - 10)
            end_line = min(len(lines), e.lineno + 10)
            
            print("--- CONTEXT LINES (Look for the 👉) ---")
            for i in range(start_line, end_line):
                line_num = i + 1
                prefix = "👉 " if line_num == e.lineno else "   "
                print(f"{prefix}{line_num:4d}: {lines[i].rstrip()}")
            print("--------------------------------------")
        except Exception as read_err:
            print(f"Could not read file context: {read_err}")
        
        # Keep the error raised so the Action registers the failure but yields our print logs
        raise e

if __name__ == "__main__":
    inspect_json()
