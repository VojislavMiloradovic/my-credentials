with open(
    r"C:\Users\Toughbook\OneDrive\Documents\GitHub\my-credentials\tests\conftest.py",
    "r",
    encoding="utf-8",
) as f:
    content = f.read()

# Fix the mock_loss_guard fixture
old_fixture = '''def mock_loss_guard(monkeypatch):
    """Mock loss_guard module to avoid baseline file I/O."""
    mock_execute = MagicMock()
    mock_anomaly = type("PipelineDataLossAnomaly", (Exception,), {})
    monkeypatch.setattr("loss_guard.execute_content_loss_guard", mock_execute)
    monkeypatch.setattr("loss_guard.PipelineDataLossAnomaly", mock_execute)
    # Also patch in modules that import it directly
    monkeypatch.setattr("update_credly_badges.execute_content_loss_guard", mock_execute)
    monkeypatch.setattr("update_google_skills.execute_content_loss_guard", mock_execute)
    monkeypatch.setattr("update_aws_skills.execute_content_loss_guard", mock_execute)
    monkeypatch.setattr("update_linkedin.execute_content_loss_guard", mock_execute)
    monkeypatch.setattr(
        "update_google_developer.execute_content_loss_guard", mock_execute
    )
    # Only patch PipelineDataLossAnomaly in modules that still define it
    monkeypatch.setattr("update_credly_badges.PipelineDataLossAnomaly", mock_anomaly)
    
    monkeypatch.setattr("update_linkedin.PipelineDataLossAnomaly", mock_anomaly)
    monkeypatch.setattr("update_google_developer.PipelineDataLossAnomaly", mock_anomaly)
    # Note: update_ms_learn, update_aws_skills, update_google_skills no longer define PipelineDataLossAnomaly
    return mock_execute'''

new_fixture = '''def mock_loss_guard(monkeypatch):
    """Mock loss_guard module to avoid baseline file I/O."""
    mock_execute = MagicMock()
    mock_anomaly = type("PipelineDataLossAnomaly", (Exception,), {})
    monkeypatch.setattr("loss_guard.execute_content_loss_guard", mock_execute)
    monkeypatch.setattr("loss_guard.PipelineDataLossAnomaly", mock_anomaly)
    # Also patch in modules that import it directly
    monkeypatch.setattr("update_linkedin.execute_content_loss_guard", mock_execute)
    monkeypatch.setattr(
        "update_google_developer.execute_content_loss_guard", mock_execute
    )
    # Only patch PipelineDataLossAnomaly in modules that still define it
    monkeypatch.setattr("update_linkedin.PipelineDataLossAnomaly", mock_anomaly)
    monkeypatch.setattr("update_google_developer.PipelineDataLossAnomaly", mock_anomaly)
    # Note: update_credly_badges, update_ms_learn, update_aws_skills, update_google_skills no longer define PipelineDataLossAnomaly
    return mock_execute'''

with open(
    r"C:\Users\Toughbook\OneDrive\Documents\GitHub\my-credentials\tests\conftest.py",
    "r",
    encoding="utf-8",
) as f:
    content = f.read()

if old_fixture in content:
    content = content.replace(old_fixture, new_fixture)
    print("[OK] conftest.py fixture updated")
else:
    print("[FAIL] Old fixture not found")

with open(
    r"C:\Users\Toughbook\OneDrive\Documents\GitHub\my-credentials\tests\conftest.py",
    "w",
    encoding="utf-8",
) as f:
    f.write(content)

print("Done!")
