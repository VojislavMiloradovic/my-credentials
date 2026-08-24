with open("update_linkedin.py", "r") as f:
    content = f.read()

# Fix the indentation issue
old = """    try:
            with open(validation_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.info(
                f"💾 Full data persisted: '{validation_file}' ({len(certs)} certifications)"
            )
        except Exception as e:
            logger.warning(f"⚠️ Could not persist full data: {e}")

        # 4. Generate L1 baseline fingerprints for cross-artifact validation
        if execute_content_loss_guard:"""

new = """    try:
        with open(validation_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info(
            f"💾 Full data persisted: '{validation_file}' ({len(certs)} certifications)"
        )
    except Exception as e:
        logger.warning(f"⚠️ Could not persist full data: {e}")

    # 4. Generate L1 baseline fingerprints for cross-artifact validation
    if execute_content_loss_guard:"""

content = content.replace(old, new)

with open("update_linkedin.py", "w") as f:
    f.write(content)
print("Fixed")
