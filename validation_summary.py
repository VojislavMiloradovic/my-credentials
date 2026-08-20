import json

with open("validation_reports/cross_artifact_report.json") as f:
    data = json.load(f)

print("Timestamp: " + str(data["timestamp"]))
print("Total checks: " + str(data["summary"]["total"]))
print("Passed: " + str(data["summary"]["passed"]))
print("Failed (errors): " + str(data["summary"]["failed"]))
print("Warnings: " + str(data["summary"]["warnings"]))
print()
print("Failed checks:")
for r in data["results"]:
    if not r["passed"] and r["severity"] == "error":
        platform = r["platform"] or "global"
        print(
            "  [FAIL] ["
            + str(platform)
            + "] "
            + str(r["check"])
            + ": "
            + str(r["message"])
        )
print()
print("Warnings:")
for r in data["results"]:
    if not r["passed"] and r["severity"] == "warning":
        platform = r["platform"] or "global"
        print(
            "  [WARN] ["
            + str(platform)
            + "] "
            + str(r["check"])
            + ": "
            + str(r["message"])
        )
