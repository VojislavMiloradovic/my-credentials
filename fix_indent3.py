with open("update_linkedin.py", "rb") as f:
    content = f.read()

# Fix the nested if block indentation (12 -> 8 spaces)
old = b"""    # 4. Generate L1 baseline fingerprints for cross-artifact validation\r\n    if execute_content_loss_guard:\r\n            try:\r\n                execute_content_loss_guard(\r\n                    new_records=certs,\r\n                    platform="linkedin-certifications",\r\n                    id_field="license",\r\n                    fail_on_warn=False,  # Baseline generation should not fail the pipeline\r\n                )\r\n                logger.info(\r\n                   """

new = b"""    # 4. Generate L1 baseline fingerprints for cross-artifact validation\r\n    if execute_content_loss_guard:\r\n        try:\r\n            execute_content_loss_guard(\r\n                new_records=certs,\r\n                platform="linkedin-certifications",\r                id_field="license",\r\n                fail_on_warn=False,  # Baseline generation should not fail the pipeline\r\n            )\r\n            logger.info(\r\n               """

content = content.replace(old, new)

with open("update_linkedin.py", "wb") as f:
    f.write(content)
print("Fixed")
