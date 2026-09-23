import json, os, struct
import pytest
import engine

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def info(w=2688, h=2016, pix="yuv420p10le", audio=False):
    return engine.ProbeInfo(w, h, 100_000_000, pix, 254.1, audio)


def test_output_size_rounds_width_to_even():
    assert engine.output_size(2688, 2016) == (3584, 2016)
    assert engine.output_size(4000, 3000) == (5334, 3000)   # 5333.33 -> 5333 -> even 5334
    assert engine.output_size(1920, 1440) == (2560, 1440)


def test_output_path(tmp_path):
    assert engine.output_path(r"D:\clips\DJI_1.MP4", str(tmp_path)) == os.path.join(str(tmp_path), "superview_DJI_1.mp4")


def test_plan_job_ok(tmp_path):
    job, reason = engine.plan_job(info(audio=True), r"D:\x\a.mp4", str(tmp_path))
    assert reason is None
    assert (job.in_w, job.in_h, job.out_w, job.out_h) == (2688, 2016, 3584, 2016)
    assert job.ten_bit is True and job.has_audio is True and job.bitrate == 100_000_000


def test_plan_job_skips(tmp_path):
    assert engine.plan_job(None, "a.mp4", str(tmp_path)) == (None, "not a video")
    assert engine.plan_job(info(3840, 2160), "a.mp4", str(tmp_path)) == (None, "already 16:9")
    (tmp_path / "superview_a.mp4").write_bytes(b"x")
    assert engine.plan_job(info(), "a.mp4", str(tmp_path)) == (None, "already converted")


def test_maps_match_superview_v02(tmp_path):
    ref = json.load(open(os.path.join(FIX, "sv02_xrow_2688.json")))
    xp, yp = tmp_path / "x.pgm", tmp_path / "y.pgm"
    engine.write_maps(ref["in_w"], ref["out_w"], ref["out_h"], str(xp), str(yp))
    header, body = xp.read_bytes().split(b"\n", 1)
    assert header == b"P5 3584 2016 65535"
    w = ref["out_w"]
    first = list(struct.unpack(">%dH" % w, body[: w * 2]))
    last = list(struct.unpack(">%dH" % w, body[-w * 2:]))
    assert first == ref["row"] and last == ref["row"]
    yh, ybody = yp.read_bytes().split(b"\n", 1)
    assert yh == header
    assert struct.unpack(">H", ybody[:2])[0] == 0
    assert struct.unpack(">H", ybody[-2:])[0] == 2015


def test_detect_encoder_order(monkeypatch):
    works = {("hevc_amf", "nv12")}
    monkeypatch.setattr(engine, "_test_encode", lambda ff, name, pix: (name, pix) in works)
    enc = engine.detect_encoder("ffmpeg")
    assert (enc.name, enc.gpu, enc.ten_bit) == ("hevc_amf", True, False)


def test_detect_encoder_prefers_nvenc_10bit(monkeypatch):
    monkeypatch.setattr(engine, "_test_encode", lambda ff, name, pix: True)
    enc = engine.detect_encoder("ffmpeg")
    assert (enc.name, enc.label, enc.ten_bit) == ("hevc_nvenc", "NVIDIA HEVC", True)


def test_detect_encoder_none(monkeypatch):
    monkeypatch.setattr(engine, "_test_encode", lambda ff, name, pix: False)
    assert engine.detect_encoder("ffmpeg") is None


def test_pix_fmt_for():
    gpu10 = engine.Encoder("hevc_nvenc", "NVIDIA HEVC", True, True)
    gpu8 = engine.Encoder("hevc_amf", "AMD HEVC", True, False)
    cpu = engine.Encoder("libx265", "CPU HEVC", False, True)
    assert engine.pix_fmt_for(gpu10, True) == "p010le"
    assert engine.pix_fmt_for(gpu10, False) == "nv12"
    assert engine.pix_fmt_for(gpu8, True) == "nv12"
    assert engine.pix_fmt_for(cpu, True) == "yuv420p10le"
    assert engine.pix_fmt_for(cpu, False) == "yuv420p"


def test_build_command_maps_streams_explicitly(tmp_path):
    job, _ = engine.plan_job(info(audio=True), "in.mp4", str(tmp_path))
    enc = engine.Encoder("hevc_nvenc", "NVIDIA HEVC", True, True)
    cmd = engine.build_command("ffmpeg", job, enc, "x.pgm", "y.pgm", "out.part.mp4")
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert fc == "[0:v:0][1:v][2:v]remap,format=p010le[v]"   # the DJI preview-stream fix
    assert cmd[cmd.index("-map") + 1] == "[v]"
    assert "0:a:0" in cmd and "-progress" in cmd and cmd[-1] == "out.part.mp4"
    assert cmd[cmd.index("-b:v") + 1] == "100000000"


def test_build_command_no_audio(tmp_path):
    job, _ = engine.plan_job(info(audio=False), "in.mp4", str(tmp_path))
    enc = engine.Encoder("libx265", "CPU HEVC", False, True)
    cmd = engine.build_command("ffmpeg", job, enc, "x.pgm", "y.pgm", "o.mp4")
    assert "0:a:0" not in cmd and "libx265" in cmd
