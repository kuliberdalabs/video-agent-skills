import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SEE = ROOT / "tiktok-see" / "tiktok_see.sh"
AUDIT = ROOT / "video-audit" / "video_audit.sh"


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)


@pytest.fixture()
def color_bars_video(tmp_path: Path) -> Path:
    video = tmp_path / "color-bars.mp4"
    result = run(
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "smptebars=size=320x568:rate=24",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000",
        "-t",
        "1.5",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(video),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    return video


def test_help_and_shell_syntax() -> None:
    for script in (SEE, AUDIT):
        syntax = run("bash", "-n", str(script), cwd=ROOT)
        assert syntax.returncode == 0, syntax.stderr
        help_result = run("bash", str(script), "--help", cwd=ROOT)
        assert help_result.returncode == 0, help_result.stderr
        assert "usage:" in help_result.stdout


def test_local_video_workflow(color_bars_video: Path, tmp_path: Path) -> None:
    see_output = tmp_path / "see-output"
    see_result = run("bash", str(SEE), str(color_bars_video), str(see_output), cwd=ROOT)
    assert see_result.returncode == 0, see_result.stderr
    assert (see_output / "contact.png").is_file()
    assert (see_output / "cuts.txt").is_file()

    clip_list = tmp_path / "clips.txt"
    clip_list.write_text(f"{color_bars_video}\n{color_bars_video}\n")
    pre_result = run("bash", str(AUDIT), "pre", str(clip_list), cwd=ROOT)
    assert pre_result.returncode == 0, pre_result.stderr
    assert "1 repeated reference" in pre_result.stdout

    audit_output = tmp_path / "audit-output"
    post_result = run("bash", str(AUDIT), "post", str(color_bars_video), str(audit_output), cwd=ROOT)
    assert post_result.returncode == 0, post_result.stderr
    assert (audit_output / "contact.png").is_file()
