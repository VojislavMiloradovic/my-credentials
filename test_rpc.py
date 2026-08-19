import json
import re

# Test the RPC fixture format
rpc = '0["gQeJTc","[[[\\\"110772055890077594470\\\",[[\\"/awards/pathways/cloud-architecture\\",1705312800000],[\\"/awards/pathways/data-engineering\\",1705399200000]]]]]"]'

for line in rpc.splitlines():
    if 'gQeJTc' in line or 'RwSpuf' in line:
        clean_line = re.sub(r'^\d+', '', line).strip()
        print('Clean line:', clean_line)
        try:
            outer_data = json.loads(clean_line)
            print('outer_data:', outer_data)
            for chunk in outer_data:
                print('  chunk:', chunk, type(chunk))
                if isinstance(chunk, list):
                    for element in chunk:
                        print('    element:', element, type(element))
                        if isinstance(element, str) and element.startswith(('[', '{')):
                            print('      parsing as JSON...')
                            badge_matrix = json.loads(element)
                            print('      badge_matrix:', badge_matrix)
        except Exception as e:
            print('Error:', e)