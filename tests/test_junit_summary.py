from tools.junit_summary import summarize


def test_summarize_testsuite_root(tmp_path):
    xml = tmp_path / "suite.xml"
    xml.write_text(
        """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<testsuite name=\"pytest\" tests=\"3\" failures=\"0\" errors=\"0\" skipped=\"0\" time=\"1.25\" timestamp=\"2026-11-20T10:00:00\">
  <testcase classname=\"a\" name=\"t1\" time=\"0.1\" />
  <testcase classname=\"a\" name=\"t2\" time=\"0.2\" />
  <testcase classname=\"b\" name=\"t3\" time=\"0.95\" />
</testsuite>\n""",
        encoding="utf-8",
    )
    summary = summarize(xml)
    assert summary["tests"] == 3
    assert summary["failures"] == 0
    assert summary["errors"] == 0
    assert summary["skipped"] == 0
    assert summary["timestamp"].startswith("2026-11-20")


def test_summarize_testsuites_root(tmp_path):
    xml = tmp_path / "suites.xml"
    xml.write_text(
        """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<testsuites>
  <testsuite name=\"one\" tests=\"2\" failures=\"1\" errors=\"0\" skipped=\"0\" time=\"0.2\" timestamp=\"2026-11-20T10:00:00\">
    <testcase classname=\"a\" name=\"t1\" />
  </testsuite>
  <testsuite name=\"two\" tests=\"1\" failures=\"0\" errors=\"0\" skipped=\"1\" time=\"0.3\" timestamp=\"2026-11-20T10:00:01\" />
</testsuites>\n""",
        encoding="utf-8",
    )
    summary = summarize(xml)
    assert summary["tests"] == 3
    assert summary["failures"] == 1
    assert summary["skipped"] == 1
    assert summary["duration_seconds"] == 0.5


def test_reject_unknown_root(tmp_path):
    xml = tmp_path / "bad.xml"
    xml.write_text("<bad></bad>", encoding="utf-8")
    try:
        summarize(xml)
    except ValueError as exc:
        assert "Unsupported" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
