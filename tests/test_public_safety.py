import os
import subprocess
from pathlib import Path

import pytest


IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv"}


def repository_files(root: Path) -> list[Path]:
    if (root / ".git").is_dir():
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        return [root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item
                and (root / item.decode("utf-8")).is_file()]

    files = []
    for path in root.rglob("*"):
        if not path.is_file() or IGNORED_PARTS.intersection(path.parts):
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        files.append(path)
    return files


def test_new_skill_files_are_scanned_and_public_fetch_is_isolated() -> None:
    root = Path(__file__).resolve().parents[1]
    files = repository_files(root)
    required = {Path("tiktok-see/SKILL.md"), Path("tiktok-see/see.py"),
                Path("tiktok-see/tiktok_see.sh")}
    assert required <= {path.relative_to(root) for path in files}

    contents = {path.relative_to(root): path.read_text().casefold()
                for path in files if path.suffix in {".md", ".py", ".sh"}}
    fetch = contents[Path("tiktok-see/tiktok_see.sh")]
    assert "--ignore-config" in fetch
    forbidden_options = (
        "--" + "cookies" + "-from-" + "browser",
        "--" + "cookies",
        "tiktok_see_" + "cookies" + "_from_" + "browser",
    )
    for text in contents.values():
        assert not any(option in text for option in forbidden_options)
        assert "~" + "/" not in text
        assert "/" + "users" + "/" not in text


def test_repository_matches_external_policy() -> None:
    policy_file = os.environ.get("OSS_PRIVATE_DENYLIST_FILE")
    if not policy_file:
        pytest.skip("OSS_PRIVATE_DENYLIST_FILE is not set")

    policy_path = Path(policy_file)
    assert policy_path.is_file(), f"policy file is unavailable: {policy_path}"
    patterns = [line.strip().casefold() for line in policy_path.read_text().splitlines() if line.strip()]
    root = Path(__file__).resolve().parents[1]
    findings = []

    for path in repository_files(root):
        relative_path = path.relative_to(root)
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        candidate = f"{relative_path}\n{text}".casefold()
        for pattern in patterns:
            if pattern in candidate:
                findings.append(f"{relative_path}: {pattern}")

    assert not findings, "external policy matches found:\n" + "\n".join(findings)
