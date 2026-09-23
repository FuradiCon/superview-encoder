"""
jobs.py -- Superview Encoder's queue: one worker thread, one conversion at a
time, files can be added while it runs. No UI code; app.py wires this to the
window and pushes snapshot() to the page whenever on_change fires.
"""

import itertools
import json
import os
import sys
import tempfile
import threading
import time

import engine


def default_paths(platform, home, appdata):
    """(default output folder, settings.json path) for this OS."""
    if platform == "darwin":
        return (os.path.join(home, "Movies", "Superview"),
                os.path.join(home, "Library", "Application Support", "Superview Encoder", "settings.json"))
    return (os.path.join(home, "Videos", "Superview"),
            os.path.join(appdata or home, "Superview Encoder", "settings.json"))


DEFAULT_OUT, SETTINGS_PATH = default_paths(sys.platform, os.path.expanduser("~"), os.environ.get("APPDATA"))
FINISHED = ("done", "skipped", "failed", "cancelled")


def _fmt_secs(s):
    s = int(round(s))
    return "%dm %02ds" % (s // 60, s % 60) if s >= 60 else "%ds" % s


class Controller:
    def __init__(self, ffmpeg, ffprobe, encoder, settings_path=SETTINGS_PATH, on_change=None, eng=engine):
        self.ffmpeg, self.ffprobe, self.encoder, self.eng = ffmpeg, ffprobe, encoder, eng
        self.settings_path = settings_path
        self.on_change = on_change or (lambda: None)
        self.output_dir = self._load_output_dir()
        self.items = []
        self.error = None
        self._ids = itertools.count(1)
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._cancel = threading.Event()
        self._stop = False
        self._last_push = 0.0
        self._thread = threading.Thread(target=self._worker, daemon=True)

    # ---------------------------------------------------------- settings
    def _load_output_dir(self):
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                return json.load(f).get("output_dir") or DEFAULT_OUT
        except (OSError, ValueError):
            return DEFAULT_OUT

    def set_output_dir(self, path):
        with self._lock:
            self.output_dir = path
            self.error = None
        try:
            os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump({"output_dir": path}, f)
        except OSError:
            pass
        self._wake.set()
        self._notify(force=True)

    # ---------------------------------------------------------- lifecycle
    def start(self):
        self._thread.start()

    def shutdown(self):
        self._stop = True
        self._cancel.set()
        self._wake.set()
        if self._thread.is_alive():
            self._thread.join(timeout=10)

    # ---------------------------------------------------------- commands
    def add_paths(self, paths):
        found = []
        for p in paths:
            if os.path.isdir(p):
                found += sorted(os.path.join(p, n) for n in os.listdir(p)
                                if n.lower().endswith(self.eng.VIDEO_EXTS)
                                and os.path.isfile(os.path.join(p, n)))
            elif os.path.isfile(p):
                found.append(p)
        added = 0
        with self._lock:
            active = {os.path.normcase(i["path"]) for i in self.items if i["status"] in ("waiting", "converting")}
            for p in found:
                key = os.path.normcase(os.path.abspath(p))
                if key in active:
                    continue
                active.add(key)
                self.items.append({"id": next(self._ids), "path": os.path.abspath(p), "name": os.path.basename(p),
                                   "size": os.path.getsize(p), "status": "waiting", "pct": 0.0, "eta": None,
                                   "speed": None, "detail": "", "error": None, "meta": ""})
                added += 1
        if added:
            self._wake.set()
            self._notify(force=True)
        return added

    def remove(self, item_id):
        with self._lock:
            self.items = [i for i in self.items if not (i["id"] == item_id and i["status"] == "waiting")]
        self._notify(force=True)

    def cancel_current(self):
        self._cancel.set()

    def clear_finished(self):
        with self._lock:
            self.items = [i for i in self.items if i["status"] not in FINISHED]
        self._notify(force=True)

    def is_busy(self):
        with self._lock:
            return any(i["status"] == "converting" for i in self.items)

    # ---------------------------------------------------------- state
    def snapshot(self):
        with self._lock:
            items = [dict(i) for i in self.items]
            cur = next((n for n, i in enumerate(items, 1) if i["status"] == "converting"), None)
            enc = self.encoder
            return {"items": items,
                    "current": {"index": cur, "total": len(items)} if cur else None,
                    "output_dir": self.output_dir, "error": self.error,
                    "encoder": {"label": enc.label, "gpu": enc.gpu} if enc else None}

    def _notify(self, force=False):
        now = time.monotonic()
        if force or now - self._last_push >= 0.25:
            self._last_push = now
            try:
                self.on_change()
            except Exception:
                pass

    def _update(self, item, **kw):
        with self._lock:
            item.update(kw)

    # ---------------------------------------------------------- worker
    def _next_waiting(self):
        with self._lock:
            return next((i for i in self.items if i["status"] == "waiting"), None)

    def _output_ok(self, out_dir):
        try:
            os.makedirs(out_dir, exist_ok=True)
            with tempfile.TemporaryFile(dir=out_dir):
                pass
            return True
        except OSError:
            return False

    def _worker(self):
        while not self._stop:
            item = self._next_waiting()
            out_dir = self.output_dir
            if item is not None and not self._output_ok(out_dir):
                with self._lock:
                    self.error = "Can't write to %s. Choose another folder." % out_dir
                self._notify(force=True)
                item = None
            if item is None:
                self._wake.wait()
                self._wake.clear()
                continue
            self._run(item, out_dir)

    def _run(self, item, out_dir):
        info = self.eng.probe(self.ffprobe, item["path"])
        job, reason = self.eng.plan_job(info, item["path"], out_dir)
        if reason:
            self._update(item, status="skipped", detail=reason)
            self._notify(force=True)
            return
        if self.encoder is None:
            self._update(item, status="failed", detail="click for details ▾",
                         error="No working video encoder found in the bundled ffmpeg.")
            self._notify(force=True)
            return
        bits = "10-bit" if job.ten_bit else "8-bit"
        if job.ten_bit and not self.encoder.ten_bit:
            bits = "10-bit → 8-bit"
        meta = "%d×%d → %d×%d · %d Mbps · %s" % (job.in_w, job.in_h, job.out_w, job.out_h,
                                                round(job.bitrate / 1e6), bits)
        self._cancel.clear()
        self._update(item, status="converting", detail="converting", meta=meta, pct=0.0)
        self._notify(force=True)
        started = time.monotonic()

        def progress(frac, speed):
            elapsed = time.monotonic() - started
            eta = elapsed / frac * (1 - frac) if frac > 0.01 else None
            self._update(item, pct=round(frac * 100, 1), eta=eta, speed=speed)
            self._notify()

        try:
            self.eng.convert(self.ffmpeg, job, self.encoder, progress, self._cancel)
            self._update(item, status="done", pct=100.0, eta=None,
                         detail=_fmt_secs(time.monotonic() - started))
        except self.eng.Cancelled:
            self._update(item, status="cancelled", eta=None, detail="cancelled")
        except self.eng.ConvertError as e:
            self._update(item, status="failed", eta=None, detail="click for details ▾", error=str(e))
        except Exception as e:  # never let one file kill the worker
            self._update(item, status="failed", eta=None, detail="click for details ▾", error=repr(e))
        self._notify(force=True)
