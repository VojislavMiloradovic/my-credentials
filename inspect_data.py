import os
import json

def deep_inspect_remaining():
    data_dir = "data"
    json_files = [f for f in os.listdir(data_dir) if f.endswith('.json')]
    
    if not json_files:
        print("No JSON file found!")
        return
        
    file_path = os.path.join(data_dir, json_files[0])
    print(f"Reading {file_path} for deep inspection of remaining sections...")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    summary = []
    summary.append("=== DEEP INSPECTION - PHASE 2 ===\n")
    
    keys_to_inspect = ["Progress", "LearnCompanion", "XP", "SkillAssessment"]
    
    for root_key in keys_to_inspect:
        summary.append("========================================")
        summary.append(f"ROOT KEY: {root_key}")
        summary.append("========================================")
        
        val = data.get(root_key)
        if val is None:
            summary.append(f"{root_key} is None or missing.\n")
            continue
            
        summary.append(f"Type: {type(val).__name__}")
        if isinstance(val, dict):
            summary.append(f"Keys inside {root_key}: {list(val.keys())}\n")
            for sub_key, sub_val in val.items():
                val_type = type(sub_val).__name__
                length_info = f" (Length: {len(sub_val)})" if hasattr(sub_val, '__len__') and not isinstance(sub_val, str) else ""
                summary.append(f"  - Sub-key '{sub_key}': {val_type}{length_info}")
                
                # Sample lists
                if isinstance(sub_val, list) and len(sub_val) > 0:
                    summary.append("    * Sample first item in list:")
                    item_str = json.dumps(sub_val[0], indent=4)
                    if len(item_str) > 1000:
                        item_str = item_str[:1000] + "\n    ... [TRUNCATED] ..."
                    summary.append(item_str)
                # Sample dictionaries
                elif isinstance(sub_val, dict) and len(sub_val) > 0:
                    first_k = list(sub_val.keys())[0]
                    item_str = json.dumps(sub_val[first_k], indent=4)
                    if len(item_str) > 1000:
                        item_str = item_str[:1000] + "\n    ... [TRUNCATED] ..."
                    summary.append(f"    * Sample of sub-key '{first_k}':\n{item_str}")
                summary.append("") # spacing
        elif isinstance(val, list):
            summary.append(f"Length of list: {len(val)}")
            if len(val) > 0:
                item_str = json.dumps(val[0], indent=4)
                if len(item_str) > 1000:
                    item_str = item_str[:1000] + "\n... [TRUNCATED] ..."
                summary.append(f"Sample first item:\n{item_str}")
        else:
            summary.append(f"Value: {val}")
        summary.append("\n")
            
    # Write to structure_summary.txt
    output_path = os.path.join(data_dir, "structure_summary.txt")
    with open(output_path, 'w', encoding='utf-8') as out:
        out.write("\n".join(summary))
    print(f"Phase 2 summary written to {output_path}")

if __name__ == "__main__":
    deep_inspect_remaining()
