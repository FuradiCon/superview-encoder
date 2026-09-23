"""
engine.py -- Superview Encoder's conversion logic. No UI code in here.

Stretches 4:3 video to 16:9 the way GoPro SuperView does: the center stays
natural and the edges take the stretch. The stretch maps are byte-identical to
Niek's superview v0.2; the ffmpeg call fixes v0.2's stream-mapping bug (DJI
files carry a preview video that v0.2 fed into the filter by mistake).
"""

import glob
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass

VIDEO_EXTS = (".mp4", ".mov")
CREATE_NO_WINDOW = 0x08000000  # keep ffmpeg from flashing console windows


def _run(args):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", stdin=subprocess.DEVNULL,
                          creationflags=CREATE_NO_WINDOW)


# ------------------------------------------------------------------ tools

def _candidate_dirs():
    here = os.path.dirname(os.path.abspath(__file__))
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(os.path.join(sys._MEIPASS, "ffmpeg"))
    dirs.append(os.path.join(here, "ffmpeg"))
    dirs += sorted(glob.glob(os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages",
        "Gyan.FFmpeg*", "ffmpeg-*", "bin")), reverse=True)
    return dirs


def find_tools():
    """(ffmpeg, ffprobe) paths, or (None, None). Skips System32, which on this
    machine holds a 2019 ffmpeg too old for current NVIDIA drivers."""
    for d in _candidate_dirs():
        f, p = os.path.join(d, "ffmpeg.exe"), os.path.join(d, "ffprobe.exe")
        if os.path.isfile(f) and os.path.isfile(p):
            return f, p
    f, p = shutil.which("ffmpeg"), shutil.which("ffprobe")
    sys32 = os.path.normcase(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"))
    if f and p and os.path.normcase(os.path.dirname(f)) != sys32:
        return f, p
    return None, None


# ------------------------------------------------------------------ probe / plan

@dataclass
class ProbeInfo:
    width: int
    height: int
    bitrate: int
    pix_fmt: str
    duration: float
    has_audio: bool


def probe(ffprobe, path):
    r = _run([ffprobe, "-v", "error", "-show_entries",
              "stream=codec_type,width,height,bit_rate,pix_fmt:format=bit_rate,duration",
              "-of", "json", path])
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return None
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("width")), None)
    if video is None:
        return None
    fmt = data.get("format", {})
    bitrate = int(video.get("bit_rate") or fmt.get("bit_rate") or 0) or 50_000_000
    return ProbeInfo(int(video["width"]), int(video["height"]), bitrate,
                     video.get("pix_fmt", ""), float(fmt.get("duration") or 0),
                     any(s.get("codec_type") == "audio" for s in streams))


@dataclass
class Job:
    src: str
    dst: str
    in_w: int
    in_h: int
    out_w: int
    out_h: int
    bitrate: int
    ten_bit: bool
    duration: float
    has_audio: bool


def output_size(w, h):
    out_w = int(h * 16 / 9)
    out_w += out_w % 2  # encoders need even dimensions
    return out_w, h


def output_path(src, out_dir):
    stem = os.path.splitext(os.path.basename(src))[0]
    return os.path.join(out_dir, "superview_" + stem + ".mp4")


def plan_job(info, src, out_dir):
    if info is None:
        return None, "not a video"
    if info.width * 9 >= info.height * 16:
        return None, "already 16:9"
    dst = output_path(src, out_dir)
    if os.path.exists(dst):
        return None, "already converted"
    out_w, out_h = output_size(info.width, info.height)
    return Job(src, dst, info.width, info.height, out_w, out_h, info.bitrate,
               "10" in info.pix_fmt, info.duration, info.has_audio), None


# ------------------------------------------------------------------ stretch maps

def write_maps(in_w, out_w, out_h, xpath, ypath):
    """16-bit binary PGM remap files. Same formula as superview v0.2: output
    column x samples input column (x - dx) - sign(tx) * tx^2 * dx."""
    dx = (out_w - in_w) / 2.0
    row = []
    for x in range(out_w):
        tx = (x / out_w - 0.5) * 2.0
        offset = tx * tx * dx
        if tx < 0:
            offset = -offset
        row.append(int((x - dx) - offset))
    header = b"P5 %d %d 65535\n" % (out_w, out_h)
    xrow = struct.pack(">%dH" % out_w, *row)
    with open(xpath, "wb") as f:
        f.write(header)
        f.write(xrow * out_h)
    with open(ypath, "wb") as f:
        f.write(header)
        for y in range(out_h):
            f.write(struct.pack(">H", y) * out_w)


# ------------------------------------------------------------------ encoders

@dataclass
class Encoder:
    name: str
    label: str
    gpu: bool
    ten_bit: bool


CANDIDATES = [
    ("hevc_nvenc", "NVIDIA HEVC", True),
    ("hevc_qsv", "Intel HEVC", True),
    ("hevc_amf", "AMD HEVC", True),
    ("libx265", "CPU HEVC", False),
]


def _test_encode(ffmpeg, name, pix_fmt):
    r = _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
              "-i", "color=black:s=256x256:d=0.1", "-vf", "format=" + pix_fmt,
              "-c:v", name, "-f", "null", "-"])
    return r.returncode == 0


def detect_encoder(ffmpeg, candidates=CANDIDATES):
    for name, label, gpu in candidates:
        if _test_encode(ffmpeg, name, "p010le" if gpu else "yuv420p10le"):
            return Encoder(name, label, gpu, True)
        if _test_encode(ffmpeg, name, "nv12" if gpu else "yuv420p"):
            return Encoder(name, label, gpu, False)
    return None


def pix_fmt_for(enc, ten_bit_src):
    ten = ten_bit_src and enc.ten_bit
    if enc.gpu:
        return "p010le" if ten else "nv12"
    return "yuv420p10le" if ten else "yuv420p"


def encoder_args(enc, bitrate):
    b, peak = str(bitrate), str(int(bitrate * 1.5))
    if enc.name == "hevc_nvenc":
        return ["-c:v", "hevc_nvenc", "-preset", "p5", "-rc", "vbr",
                "-b:v", b, "-maxrate", peak, "-bufsize", str(bitrate * 2)]
    if enc.name == "hevc_qsv":
        return ["-c:v", "hevc_qsv", "-preset", "medium", "-b:v", b, "-maxrate", peak]
    if enc.name == "hevc_amf":
        return ["-c:v", "hevc_amf", "-quality", "quality", "-rc", "vbr_peak",
                "-b:v", b, "-maxrate", peak]
    return ["-c:v", "libx265", "-preset", "medium", "-b:v", b, "-x265-params", "log-level=error"]


def build_command(ffmpeg, job, enc, xmap, ymap, part):
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
           "-progress", "pipe:1", "-nostats",
           "-i", job.src, "-i", xmap, "-i", ymap,
           # explicit labels: DJI files carry a 2nd (preview) video stream that
           # unlabeled inputs would feed into remap as a "map"
           "-filter_complex", "[0:v:0][1:v][2:v]remap,format=%s[v]" % pix_fmt_for(enc, job.ten_bit),
           "-map", "[v]"]
    if job.has_audio:
        cmd += ["-map", "0:a:0", "-c:a", "copy"]
    cmd += encoder_args(enc, job.bitrate)
    cmd += ["-tag:v", "hvc1", "-map_metadata", "0", "-movflags", "+faststart", part]
    return cmd


# ------------------------------------------------------------------ convert

class Cancelled(Exception):
    pass


class ConvertError(Exception):
    pass


def convert(ffmpeg, job, enc, on_progress=None, cancel=None):
    """Run one conversion. Blocks. Raises Cancelled or ConvertError; never
    leaves a partial output behind."""
    os.makedirs(os.path.dirname(job.dst), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="superview_")
    xmap, ymap = os.path.join(tmp, "x.pgm"), os.path.join(tmp, "y.pgm")
    part = job.dst[:-4] + ".part.mp4"
    proc = None
    try:
        write_maps(job.in_w, job.out_w, job.out_h, xmap, ymap)
        proc = subprocess.Popen(build_command(ffmpeg, job, enc, xmap, ymap, part),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                                errors="replace", creationflags=CREATE_NO_WINDOW)
        err_lines = []
        reader = threading.Thread(target=lambda: err_lines.extend(proc.stderr), daemon=True)
        reader.start()
        if cancel is not None:
            def watch():
                while proc.poll() is None:
                    if cancel.wait(0.2):
                        proc.kill()
                        return
            threading.Thread(target=watch, daemon=True).start()

        frac, speed = 0.0, None
        for line in proc.stdout:
            key, _, val = line.strip().partition("=")
            if key == "out_time_us" and val.isdigit() and job.duration > 0:
                frac = min(int(val) / 1e6 / job.duration, 1.0)
            elif key == "speed" and val.endswith("x"):
                try:
                    speed = float(val[:-1])
                except ValueError:
                    pass
            elif key == "progress" and on_progress:
                on_progress(1.0 if val == "end" else frac, speed)
        proc.wait()
        reader.join(timeout=5)

        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if proc.returncode != 0:
            msg = "".join(err_lines[-20:]).strip()
            raise ConvertError(msg or "ffmpeg exited with code %d" % proc.returncode)
        os.replace(part, job.dst)
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        if os.path.exists(part):
            os.remove(part)
        shutil.rmtree(tmp, ignore_errors=True)
