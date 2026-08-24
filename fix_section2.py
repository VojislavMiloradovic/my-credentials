with open("update_linkedin.py", "rb") as f:
    content = f.read()

# The problematic section - use encoded strings
old_str = """    except Exception as e:
        logger.warning(f"⚠️ Could not persist full data: {e}")

    # 4. Generate L1 baseline fingerprints for cross-artifact validation
    if execute_content_loss_guard:
            try:
                execute_content_loss_guard(
                    new_records=certs,
                    platform="linkedin-certifications",
                    id_field="license",\r                fail_on_warn=False,  # Baseline generation should not fail the pipeline
                )
                logger.info(
                   "✅ L1 baseline fingerprints generated for cross-artifact validation"
                )
            except PipelineDataLossAnomaly as anomaly_err:
                logger.warning(
                    f"⚠️ Baseline generation anomaly (non-fatal): {anomaly_err}"
                )
            except Exception as e:
                logger.warning(f"⚠️ Baseline generation failed (non-fatal): {e}")
        else:
            logger.warning(
                "⚠️ Content-aware loss guard unavailable, skipping baseline generation"
            )

        total_certs = len(certs)

        # 2. Sort: reverse original order first, then reverse issued date (ties broken by position in CSV)"""

new_str = """    except Exception as e:
        logger.warning(f"⚠️ Could not persist full data: {e}")

    # 4. Generate L1 baseline fingerprints for cross-artifact validation
    if execute_content_loss_guard:
        try:
            execute_content_loss_guard(
                new_records=certs,
                platform="linkedin-certifications",
                id_field="license",
                fail_on_warn=False,  # Baseline generation should not fail the pipeline
            )
            logger.info(
                "✅ L1 baseline fingerprints generated for cross-artifact validation"
            )
        except PipelineDataLossAnomaly as anomaly_err:
            logger.warning(
                f"⚠️ Baseline generation anomaly (non-fatal): {anomaly_err}"
            )
        except Exception as e:
            logger.warning(f"⚠️ Baseline generation failed (non-fatal): {e}")
    else:
        logger.warning(
            "⚠️ Content-aware loss guard unavailable, skipping baseline generation"
        )

    total_certs = len(certs)

    # 2. Sort: reverse original order first, then reverse issued date (ties broken by position in CSV)"""

old_bytes = old_str.encode("utf-8")
new_bytes = new_str.encode("utf-8")

content = content.replace(old_bytes, new_bytes)

with open("update_linkedin.py", "wb") as f:
    f.write(content)
print("Fixed")
