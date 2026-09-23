import os, subprocess, threading
import pytest
import engine

pytestmark = pytest.mark.slow
FF, FP = engine.find_tools()


def make_clip(path, w, h, secs, ten_bit, with_preview):
    """Synthetic 4:3 clip. with_preview adds a 2nd MJPEG video stream like DJI files."""
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:d={secs}:r=30"]
    if with_preview:
        cmd += ["-f", "lavfi", "-i", f"testsrc2=s=960x720:d={secs}:r=30", "-map", "0:v", "-map", "1:v",
                "-c:v:1", "mjpeg", "-pix_fmt:v:1", "yuvj420p"]
    cmd += ["-c:v:0", "libx265", "-preset", "ultrafast", "-pix_fmt:v:0", "yuv420p10le" if ten_bit else "yuv420p",
            "-x265-params", "log-level=error", "-b:v:0", "20M", str(path)]
    subprocess.run(cmd, check=True)


@pytest.fixture(scope="module")
def encoder():
    assert FF, "ffmpeg not found"
    return engine.detect_encoder(FF)


@pytest.mark.parametrize("ten_bit", [True, False])
def test_convert_dji_like_clip(tmp_path, encoder, ten_bit):
    src = tmp_path / "DJI_TEST.MP4"
    make_clip(src, 2688, 2016, 2, ten_bit, with_preview=True)
    info = engine.probe(FP, str(src))
    job, reason = engine.plan_job(info, str(src), str(tmp_path / "out"))
    assert reason is None
    seen = []
    engine.convert(FF, job, encoder, lambda f, s: seen.append(f))
    out = engine.probe(FP, job.dst)
    assert (out.width, out.height) == (3584, 2016)
    assert ("10" in out.pix_fmt) == (ten_bit and encoder.ten_bit)
    assert seen and max(seen) > 0.9
    assert not os.path.exists(job.dst[:-4] + ".part.mp4")


def test_cancel_removes_partial(tmp_path, encoder):
    src = tmp_path / "long.mp4"
    make_clip(src, 1920, 1440, 20, False, with_preview=False)
    job, _ = engine.plan_job(engine.probe(FP, str(src)), str(src), str(tmp_path / "out"))
    cancel = threading.Event()
    def prog(f, s):
        if f > 0.05:
            cancel.set()
    with pytest.raises(engine.Cancelled):
        engine.convert(FF, job, encoder, prog, cancel)
    assert os.listdir(tmp_path / "out") == []


def test_failure_reports_ffmpeg_error(tmp_path, encoder):
    src = tmp_path / "broken.mp4"
    src.write_bytes(b"\x00" * 4096)
    job = engine.Job(str(src), str(tmp_path / "out" / "superview_broken.mp4"),
                     1920, 1440, 2560, 1440, 1_000_000, False, 1.0, False)
    with pytest.raises(engine.ConvertError) as e:
        engine.convert(FF, job, encoder)
    assert str(e.value).strip()
    assert os.listdir(tmp_path / "out") == []
