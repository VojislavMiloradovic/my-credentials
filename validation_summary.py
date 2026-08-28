import json
import os
import sys


def main():
    """Print validation summary from cross_artifact_report.json."""
    report_path = "validation_reports/cross_artifact_report.json"

    if not os.path.exists(report_path):
        print(f"Report not found: {report_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in report: {e}", file=sys.stderr)
        sys.exit(1)

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


if __name__ == "__main__":
    main()
