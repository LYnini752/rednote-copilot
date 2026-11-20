"""Validate and package a curated source-only alpha snapshot (no Git operations)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "app.py",
    "copilot.py",
    "provider.py",
    "workflows.py",
    "README.md",
    "README.en.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "SECURITY.md",
    ".gitignore",
    "requirements.txt",
    "requirements-dev.txt",
    "constraints.txt",
    "pyproject.toml",
    "config.example.json",
    "config.real.example.json",
    "example-metrics.csv",
    ".github/workflows/ci.yml",
)
PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
)


def source_files(root=ROOT):
    files = [root / name for name in REQUIRED]
    files += sorted((root / "tests").glob("*.py"))
    files += sorted((root / "docs").glob("*.md"))
    files += sorted((root / "tools").glob("*.py"))
    return sorted(set(files))


def validate(root=ROOT):
    files = source_files(root)
    manifest = {}
    for file in files:
        if file.is_symlink() or not file.is_file():
            raise ValueError("发布源文件不存在或是符号链接：" + str(file.relative_to(root)))
        data = file.read_bytes()
        text = data.decode("utf-8")
        if any(pattern.search(text) for pattern in PATTERNS):
            raise ValueError(
                "源文件疑似含凭据，请先人工核对（不输出内容）：" + str(file.relative_to(root))
            )
        manifest[file.relative_to(root).as_posix()] = hashlib.sha256(data).hexdigest()
    for filename in ("config.example.json", "config.real.example.json"):
        spec = json.loads((root / filename).read_text(encoding="utf-8"))
        if any(
            key.lower() in {"api_key", "cookie", "authorization", "password", "token"}
            for key in spec
        ):
            raise ValueError("配置样例含禁止的凭据字段")
    if not any(name.startswith("tests/") for name in manifest):
        raise ValueError("未找到测试文件")

    existing = root / "SOURCE_MANIFEST.json"
    if existing.exists():
        try:
            published = json.loads(existing.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError, OSError):
            raise ValueError("SOURCE_MANIFEST.json 无法读取或不是有效 JSON") from None
        if published != manifest:
            raise ValueError(
                "SOURCE_MANIFEST.json 与当前源文件不一致；请重新生成或用同步工具更新后再发布"
            )

    return manifest


def package(destination, root=ROOT):
    manifest = validate(root)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in manifest:
            archive.write(root / name, arcname="rednote-copilot/" + name)
        archive.writestr(
            "rednote-copilot/SOURCE_MANIFEST.json", json.dumps(manifest, indent=2) + "\n"
        )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--zip",
        type=Path,
        help="Write a curated source archive (never includes venv, outputs or credentials)",
    )
    args = parser.parse_args()
    manifest = package(args.zip) if args.zip else validate()
    print(
        json.dumps(
            {
                "status": "source-check-passed",
                "file_count": len(manifest),
                "limitations": "Pattern check is not a full secret/security audit; real model quality requires separate validation.",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
