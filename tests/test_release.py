import json
import zipfile

import pytest

from tools.release_check import PATTERNS, ROOT, package, source_files, validate


def test_curated_source_snapshot_excludes_runtime_data(tmp_path):
    archive = tmp_path / "snapshot.zip"
    manifest = package(archive)
    with zipfile.ZipFile(archive) as content:
        names = content.namelist()
        saved = json.loads(content.read("rednote-copilot/SOURCE_MANIFEST.json"))
    assert saved == manifest
    assert all(".venv/" not in name and ".local/" not in name for name in names)
    assert "rednote-copilot/.github/workflows/ci.yml" in names
    assert "rednote-copilot/WORKLOG.md" not in names
    assert "rednote-copilot/HANDOFF.md" not in names
    assert "rednote-copilot/README.en.md" in names
    assert "rednote-copilot/LICENSE" in names


def test_source_validation_requires_all_files(tmp_path):
    with pytest.raises(ValueError, match="不存在"):
        validate(tmp_path)


def test_common_credential_patterns_do_not_echo_values():
    assert any(pattern.search("sk-" + "x" * 32) for pattern in PATTERNS)
    assert any(pattern.search("ghp_" + "a" * 36) for pattern in PATTERNS)
    assert any(pattern.search("-----BEGIN " + "RSA PRIVATE KEY-----") for pattern in PATTERNS)


def test_curated_sources_are_utf8_and_no_links():
    for source in source_files(ROOT):
        assert not source.is_symlink()
        source.read_text(encoding="utf-8")
