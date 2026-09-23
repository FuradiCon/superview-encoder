import os, threading, time, types
import pytest
import engine
import jobs


def wait_until(pred, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    raise AssertionError("timed out")


def fake_engine(convert_impl=None, info=None):
    def probe(fp, path):
        if path.endswith(".txt"):
            return None
        return info or engine.ProbeInfo(2688, 2016, 100_000_000, "yuv420p10le", 10.0, False)

    def convert(ff, job, enc, on_progress=None, cancel=None):
        if convert_impl:
            return convert_impl(job, on_progress, cancel)
        on_progress(0.5, 2.0)
        open(job.dst, "wb").close()

    return types.SimpleNamespace(VIDEO_EXTS=engine.VIDEO_EXTS, probe=probe, plan_job=engine.plan_job,
                                 convert=convert, Cancelled=engine.Cancelled, ConvertError=engine.ConvertError)


ENC = engine.Encoder("hevc_nvenc", "NVIDIA HEVC", True, True)


@pytest.fixture
def make(tmp_path):
    ctls = []
    def _make(**kw):
        eng = kw.pop("eng", fake_engine())
        c = jobs.Controller("ff", "fp", ENC, settings_path=str(tmp_path / "s" / "settings.json"), eng=eng, **kw)
        c.set_output_dir(str(tmp_path / "out"))
        ctls.append(c)
        return c
    yield _make
    for c in ctls:
        c.shutdown()


def src(tmp_path, name):
    p = tmp_path / "in" / name
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(b"v")
    return str(p)


def status(c):
    return [i["status"] for i in c.snapshot()["items"]]


def test_converts_in_order(make, tmp_path):
    c = make()
    c.add_paths([src(tmp_path, "a.mp4"), src(tmp_path, "b.MOV")])
    c.start()
    wait_until(lambda: status(c) == ["done", "done"])
    assert os.path.exists(tmp_path / "out" / "superview_a.mp4")
    assert os.path.exists(tmp_path / "out" / "superview_b.mp4")


def test_folder_expands_top_level_videos_only(make, tmp_path):
    src(tmp_path, "a.mp4"); src(tmp_path, "notes.txt")
    (tmp_path / "in" / "sub").mkdir()
    (tmp_path / "in" / "sub" / "deep.mp4").write_bytes(b"v")
    c = make()
    assert c.add_paths([str(tmp_path / "in")]) == 1
    assert [i["name"] for i in c.snapshot()["items"]] == ["a.mp4"]


def test_non_video_file_is_skipped(make, tmp_path):
    c = make()
    c.add_paths([src(tmp_path, "notes.txt")])
    c.start()
    wait_until(lambda: status(c) == ["skipped"])
    assert c.snapshot()["items"][0]["detail"] == "not a video"


def test_duplicate_ignored_while_queued(make, tmp_path):
    c = make()
    p = src(tmp_path, "a.mp4")
    assert c.add_paths([p]) == 1
    assert c.add_paths([p]) == 0


def test_already_converted_skipped(make, tmp_path):
    c = make()
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / "out" / "superview_a.mp4").write_bytes(b"x")
    c.add_paths([src(tmp_path, "a.mp4")])
    c.start()
    wait_until(lambda: status(c) == ["skipped"])
    assert c.snapshot()["items"][0]["detail"] == "already converted"


def test_failure_keeps_queue_going(make, tmp_path):
    def conv(job, prog, cancel):
        if "bad" in job.src:
            raise engine.ConvertError("moov atom not found")
        open(job.dst, "wb").close()
    c = make(eng=fake_engine(conv))
    c.add_paths([src(tmp_path, "bad.mp4"), src(tmp_path, "good.mp4")])
    c.start()
    wait_until(lambda: status(c) == ["failed", "done"])
    assert c.snapshot()["items"][0]["error"] == "moov atom not found"


def test_cancel_current(make, tmp_path):
    started = threading.Event()
    def conv(job, prog, cancel):
        started.set()
        cancel.wait(5)
        raise engine.Cancelled()
    c = make(eng=fake_engine(conv))
    c.add_paths([src(tmp_path, "a.mp4"), src(tmp_path, "b.mp4")])
    c.start()
    started.wait(5)
    assert c.is_busy()
    c.cancel_current()
    wait_until(lambda: status(c)[0] == "cancelled")


def test_remove_only_waiting_and_clear_finished(make, tmp_path):
    c = make()
    c.add_paths([src(tmp_path, "a.mp4"), src(tmp_path, "b.mp4")])
    ids = [i["id"] for i in c.snapshot()["items"]]
    c.remove(ids[1])
    assert len(c.snapshot()["items"]) == 1
    c.start()
    wait_until(lambda: status(c) == ["done"])
    c.clear_finished()
    assert c.snapshot()["items"] == []


def test_output_dir_persists(make, tmp_path):
    c = make()
    c.set_output_dir(str(tmp_path / "elsewhere"))
    c2 = jobs.Controller("ff", "fp", ENC, settings_path=str(tmp_path / "s" / "settings.json"), eng=fake_engine())
    assert c2.snapshot()["output_dir"] == str(tmp_path / "elsewhere")


def test_unwritable_output_pauses_with_error(make, tmp_path):
    blocker = tmp_path / "file_not_dir"
    blocker.write_bytes(b"x")
    c = make()
    c.set_output_dir(str(blocker / "out"))       # parent is a file -> can't create
    c.add_paths([src(tmp_path, "a.mp4")])
    c.start()
    wait_until(lambda: c.snapshot()["error"])
    assert status(c) == ["waiting"]
    c.set_output_dir(str(tmp_path / "ok"))
    wait_until(lambda: status(c) == ["done"])
    assert c.snapshot()["error"] is None


def test_snapshot_meta_and_current(make, tmp_path):
    gate = threading.Event()
    def conv(job, prog, cancel):
        prog(0.25, 2.0)
        gate.wait(5)
        open(job.dst, "wb").close()
    c = make(eng=fake_engine(conv))
    c.add_paths([src(tmp_path, "a.mp4"), src(tmp_path, "b.mp4")])
    c.start()
    wait_until(lambda: c.snapshot()["items"][0]["pct"] == 25.0)
    s = c.snapshot()
    assert s["current"] == {"index": 1, "total": 2}
    assert s["items"][0]["meta"] == "2688×2016 → 3584×2016 · 100 Mbps · 10-bit"
    assert s["items"][0]["speed"] == 2.0
    assert s["encoder"] == {"label": "NVIDIA HEVC", "gpu": True}
    gate.set()
