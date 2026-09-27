import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SEE = ROOT / "tiktok-see" / "tiktok_see.sh"
AUDIT = ROOT / "video-audit" / "video_audit.sh"


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TIKTOK_SEE_TRANSCRIBE": "0"}
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=False)


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
    assert (see_output / "soft_cuts.txt").is_file()
    assert (see_output / "exact.tsv").is_file()
    assert list((see_output / "exact").glob("*.png"))

    clip_list = tmp_path / "clips.txt"
    clip_list.write_text(f"{color_bars_video}\n{color_bars_video}\n")
    pre_result = run("bash", str(AUDIT), "pre", str(clip_list), cwd=ROOT)
    assert pre_result.returncode == 0, pre_result.stderr
    assert "1 repeated reference" in pre_result.stdout

    audit_output = tmp_path / "audit-output"
    post_result = run("bash", str(AUDIT), "post", str(color_bars_video), str(audit_output), cwd=ROOT)
    assert post_result.returncode == 0, post_result.stderr
    assert (audit_output / "contact.png").is_file()


def test_deep_video_workflow(color_bars_video: Path, tmp_path: Path) -> None:
    output = tmp_path / "deep-output"
    result = run("bash", str(SEE), str(color_bars_video), str(output),
                 "--depth", "deep", "--window", "0-1.2", cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert (output / "shots.tsv").is_file()
    assert list(output.glob("filmstrip-*.png"))
    assert (output / "waveform.png").is_file()


def test_transcript_output_with_local_recognizer(color_bars_video: Path, tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    recognizer = fake_bin / "mlx_whisper"
    recognizer.write_text(
        "#!" + sys.executable + "\n"
        "import pathlib, sys\n"
        "args = sys.argv\n"
        "out = pathlib.Path(args[args.index('--output-dir') + 1])\n"
        "(out / 'transcript.txt').write_text('sample speech')\n"
        "(out / 'transcript.srt').write_text('1\\n00:00:00,000 --> 00:00:01,000\\nsample speech\\n')\n"
        "(out / 'transcript.json').write_text('{\"segments\": []}')\n"
    )
    recognizer.chmod(0o755)
    output = tmp_path / "transcript-output"
    env = {**os.environ, "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
           "TIKTOK_SEE_TRANSCRIBE": "1"}
    result = subprocess.run(["bash", str(SEE), str(color_bars_video), str(output),
                             "--depth", "quick"], cwd=ROOT, env=env, text=True,
                            capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert (output / "transcript.txt").read_text() == "sample speech"
    assert (output / "transcript.srt").is_file()
    assert (output / "transcript.json").is_file()


@pytest.mark.parametrize(
    ("inputs", "filter_graph", "expected_kind"),
    [
        (["-f", "lavfi", "-i", "color=c=white:s=160x90:r=30:d=3"],
         "fade=t=out:st=1:d=0.8,format=yuv420p", "fade-out"),
        (["-f", "lavfi", "-i", "color=c=red:s=160x90:r=30:d=2",
          "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=30:d=2"],
         "xfade=transition=fade:duration=0.8:offset=1.2,format=yuv420p", "gradual"),
    ],
)
def test_gradual_transition_detection(
    tmp_path: Path, inputs: list[str], filter_graph: str, expected_kind: str
) -> None:
    video = tmp_path / "transition.mp4"
    option = "-filter_complex" if filter_graph.startswith("xfade=") else "-vf"
    created = run("ffmpeg", "-v", "error", "-y", *inputs, option, filter_graph,
                  str(video), cwd=tmp_path)
    assert created.returncode == 0, created.stderr
    (tmp_path / "cuts.txt").write_text("")
    detected = run(sys.executable, str(ROOT / "tiktok-see" / "see.py"),
                   "soft", str(video), str(tmp_path), cwd=ROOT)
    assert detected.returncode == 0, detected.stderr
    assert expected_kind in (tmp_path / "soft_cuts.txt").read_text()
