import engine, jobs


def test_tool_name():
    assert engine.tool_name("ffmpeg", "win32") == "ffmpeg.exe"
    assert engine.tool_name("ffmpeg", "darwin") == "ffmpeg"


def test_candidates_mac_prefers_videotoolbox():
    names = [c[0] for c in engine.candidates_for("darwin")]
    assert names == ["hevc_videotoolbox", "libx265"]


def test_candidates_windows_unchanged():
    names = [c[0] for c in engine.candidates_for("win32")]
    assert names == ["hevc_nvenc", "hevc_qsv", "hevc_amf", "libx265"]


def test_videotoolbox_args():
    enc = engine.Encoder("hevc_videotoolbox", "Apple HEVC", True, True)
    args = engine.encoder_args(enc, 100_000_000)
    assert args[:2] == ["-c:v", "hevc_videotoolbox"]
    assert args[args.index("-b:v") + 1] == "100000000"
    assert engine.pix_fmt_for(enc, True) == "p010le"


def test_clear_quarantine_noop_off_mac(monkeypatch):
    calls = []
    monkeypatch.setattr(engine, "IS_MAC", False)
    monkeypatch.setattr(engine.subprocess, "run", lambda *a, **k: calls.append(a))
    engine.clear_quarantine(["/x/ffmpeg"])
    assert calls == []


def test_clear_quarantine_on_mac(monkeypatch):
    calls = []
    monkeypatch.setattr(engine, "IS_MAC", True)
    monkeypatch.setattr(engine.subprocess, "run", lambda args, **k: calls.append(args))
    engine.clear_quarantine(["/x/ffmpeg", None])
    assert calls == [["xattr", "-d", "com.apple.quarantine", "/x/ffmpeg"]]


def test_default_paths_mac():
    out, settings = jobs.default_paths("darwin", home="/Users/a", appdata=None)
    assert out.replace("\\", "/") == "/Users/a/Movies/Superview"
    assert settings.replace("\\", "/") == "/Users/a/Library/Application Support/Superview Encoder/settings.json"


def test_default_paths_windows():
    out, settings = jobs.default_paths("win32", home=r"C:\Users\a", appdata=r"C:\Users\a\AppData\Roaming")
    assert out.replace("\\", "/") == "C:/Users/a/Videos/Superview"
    assert settings.replace("\\", "/") == "C:/Users/a/AppData/Roaming/Superview Encoder/settings.json"
