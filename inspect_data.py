import os
import json

def deep_inspect():
    data_dir = "data"
    json_files = [f for f in os.listdir(data_dir) if f.endswith('.json')]
    
    if not json_files:
        print("No JSON file found in the 'data' folder!")
        return
        
    file_path = os.path.join(data_dir, json_files[0])
    print(f"Reading {file_path} for deep inspection...")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    summary = []
    summary.append("=== DEEP INSPECTION SUMMARY ===\n")
    
    # 1. Inspect VerifiableCredentials
    summary.append("--- VERIFIABLE CREDENTIALS ---")
    vc = data.get("VerifiableCredentials", {})
    if isinstance(vc, dict):
        summary.append(f"Keys in VerifiableCredentials: {list(vc.keys())}")
        for k, v in vc.items():
            summary.append(f"Key '{k}' is of type {type(v).__name__}")
            if isinstance(v, list) and len(v) > 0:
                summary.append(f"  - Number of items: {len(v)}")
                summary.append("  - Sample of first item:")
                # Let's get a clean, indented preview of the first credential
                first_item_str = json.dumps(v[0], indent=2)
                # Truncate if it's too long, but keep enough to see keys
                if len(first_item_str) > 1500:
                    first_item_str = first_item_str[:1500] + "\n... [TRUNCATED] ..."
                summary.append(first_item_str)
            elif isinstance(v, dict):
                summary.append(f"  - Sub-keys: {list(v.keys())}")
                # Print a small sample of a sub-key
                for sub_k in list(v.keys())[:2]:
                    summary.append(f"  - Preview of subkey '{sub_k}': {str(v[sub_k])[:300]}...")
    else:
        summary.append("VerifiableCredentials is not a dictionary.")
    summary.append("\n" + "="*40 + "\n")
    
    # 2. Inspect TechProfile (since it has 26 keys, let's list them all and sample)
    summary.append("--- TECH PROFILE KEYS ---")
    tp = data.get("TechProfile", {})
    if isinstance(tp, dict):
        summary.append(f"All 26 TechProfile keys: {list(tp.keys())}\n")
        
        # We will look specifically for keys that sound like achievements
        targets = ["achievements", "badges", "trophies", "certifications", "completedModules", "modules", "learningPaths"]
        found_targets = [t for t in targets if t in tp]
        
        summary.append(f"Target keys found in TechProfile: {found_targets}")
        for target in found_targets:
            val = tp[target]
            summary.append(f"\nTarget Key: '{target}' (Type: {type(val).__name__})")
            if isinstance(val, list):
                summary.append(f"  - Length: {len(val)}")
                if len(val) > 0:
                    summary.append(f"  - Sample first item: {json.dumps(val[0], indent=2)}")
            elif isinstance(val, dict):
                summary.append(f"  - Keys: {list(val.keys())}")
                if len(val.keys()) > 0:
                    first_key = list(val.keys())[0]
                    summary.append(f"  - Sample first item under '{first_key}': {json.dumps(val[first_key], indent=2)[:500]}...")
    else:
        summary.append("TechProfile is not a dictionary.")
        
    # Write the deep inspection to our text file
    output_path = os.path.join(data_dir, "structure_summary.txt")
    with open(output_path, 'w', encoding='utf-8') as out:
        out.write("\n".join(summary))
    print(f"Deep inspection summary written to {output_path}")

if __name__ == "__main__":
    deep_inspect()
