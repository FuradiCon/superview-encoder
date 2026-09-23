"""
Superview Encoder -- desktop window. Drop 4:3 clips, get SuperView 16:9 out.

Wires jobs.Controller (queue) to the ui/ page through pywebview. Python owns
all state and pushes snapshots to window.render(); the page calls back via
window.pywebview.api. Runs on Windows (WinForms + WebView2) and macOS (Cocoa +
WKWebView).

    app.py              normal run
    app.py --self-test  open the real window, convert a generated clip through
                        the bundled ffmpeg, quit; exit code 0 = pass. Used by CI
                        on the Mac builds, which nobody here can click through.
"""

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

import webview
from webview.dom import DOMEventHandler

import engine
import jobs

TITLE = "Superview Encoder"
IS_MAC = sys.platform == "darwin"


def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


class Api:
    """Methods callable from JS as window.pywebview.api.<name>()."""

    def __init__(self, ctl):
        self._ctl = ctl
        self._window = None

    def get_state(self):
        return self._ctl.snapshot()

    def browse_files(self):
        paths = self._window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True,
            file_types=("Videos (*.mp4;*.mov)", "All files (*.*)"))
        if paths:
            self._ctl.add_paths(list(paths))

    def choose_output_dir(self):
        picked = self._window.create_file_dialog(webview.FileDialog.FOLDER,
                                                 directory=self._ctl.output_dir)
        if picked:
            self._ctl.set_output_dir(picked[0] if isinstance(picked, (list, tuple)) else picked)

    def open_output_dir(self):
        os.makedirs(self._ctl.output_dir, exist_ok=True)
        if IS_MAC:
            subprocess.run(["open", self._ctl.output_dir])
        else:
            os.startfile(self._ctl.output_dir)

    def cancel_current(self):
        self._ctl.cancel_current()

    def remove(self, item_id):
        self._ctl.remove(int(item_id))

    def clear_finished(self):
        self._ctl.clear_finished()


# ------------------------------------------------------------------ platform bits

def _hwnd(window):
    return int(window.native.Handle.ToInt64())


def _dark_title_bar_win(window):
    """Dark caption on Win10 20H1+ / Win11. Attribute 20 on current builds, 19 on older ones."""
    try:
        hwnd, on = _hwnd(window), ctypes.c_int(1)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                break
        # nudge a repaint so the caption picks up the change immediately
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
    except Exception:
        pass


def _dark_title_bar_mac(window):
    try:
        from AppKit import NSAppearance
        from PyObjCTools import AppHelper
        AppHelper.callAfter(lambda: window.native.setAppearance_(
            NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua")))
    except Exception:
        pass


def dark_title_bar(window):
    (_dark_title_bar_mac if IS_MAC else _dark_title_bar_win)(window)


def confirm_quit(window):
    """True if the user agrees to stop the running conversion and quit."""
    text = "A video is still converting."
    info = "Stop it and quit? The unfinished file will be deleted."
    if IS_MAC:
        from AppKit import NSAlert, NSAlertFirstButtonReturn  # closing runs on the main thread here
        alert = NSAlert.alloc().init()
        alert.setMessageText_(text)
        alert.setInformativeText_(info)
        alert.addButtonWithTitle_("Quit")
        alert.addButtonWithTitle_("Keep converting")
        return alert.runModal() == NSAlertFirstButtonReturn
    MB_YESNO, MB_ICONWARNING, IDYES = 0x04, 0x30, 6
    return ctypes.windll.user32.MessageBoxW(_hwnd(window), text + "\n\n" + info,
                                            TITLE, MB_YESNO | MB_ICONWARNING) == IDYES


# ------------------------------------------------------------------ self-test

def run_self_test(window, ctl, ffmpeg, ffprobe, workdir):
    """Exercise the real window + bundled ffmpeg without a human. Returns a result dict."""
    res = {"ok": False, "platform": sys.platform, "ffmpeg": ffmpeg,
           "encoder": ctl.encoder.name if ctl.encoder else None}
    try:
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found")
        res["render_type"] = window.evaluate_js("typeof window.render")
        if res["render_type"] != "function":
            raise RuntimeError("UI did not load (window.render is %r)" % res["render_type"])
        src = os.path.join(workdir, "selftest.mp4")
        engine.make_test_clip(ffmpeg, src)
        ctl.set_output_dir(os.path.join(workdir, "out"))
        ctl.add_paths([src])
        end = time.monotonic() + 120
        item = ctl.snapshot()["items"][0]
        while time.monotonic() < end and item["status"] in ("waiting", "converting"):
            time.sleep(0.25)
            item = ctl.snapshot()["items"][0]
        res["status"], res["error"] = item["status"], item["error"]
        if item["status"] != "done":
            raise RuntimeError("conversion ended as %s: %s" % (item["status"], item["error"]))
        info = engine.probe(ffprobe, os.path.join(workdir, "out", "superview_selftest.mp4"))
        res["output"] = "%dx%d" % (info.width, info.height)
        if (info.width, info.height) != (1920, 1080):
            raise RuntimeError("unexpected output size " + res["output"])
        res["ok"] = True
    except Exception as e:
        res["error"] = repr(e)
    return res


SELF_TEST_RESULT = os.path.join(tempfile.gettempdir(), "superview-selftest.json")
SELF_TEST_LIMIT = 180  # seconds before the watchdog gives up; a self-test must never hang CI


def write_self_test_result(result):
    with open(SELF_TEST_RESULT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    if sys.stdout:
        print(json.dumps(result, indent=2), flush=True)


# ------------------------------------------------------------------ main

def main():
    self_test = "--self-test" in sys.argv
    workdir = tempfile.mkdtemp(prefix="superview-selftest-") if self_test else None
    result = {}
    started = time.monotonic()
    if self_test:
        def watchdog():
            result.setdefault("ok", False)
            result.setdefault("error", "self-test timed out after %ds" % SELF_TEST_LIMIT)
            write_self_test_result(result)
            os._exit(1)
        timer = threading.Timer(SELF_TEST_LIMIT, watchdog)
        timer.daemon = True
        timer.start()

    ffmpeg, ffprobe = engine.find_tools()
    engine.clear_quarantine([ffmpeg, ffprobe])
    encoder = engine.detect_encoder(ffmpeg) if ffmpeg else None
    window = None

    def push():
        if window is not None:
            window.run_js("window.render && window.render(%s)" % json.dumps(ctl.snapshot()))

    settings = os.path.join(workdir, "settings.json") if self_test else jobs.SETTINGS_PATH
    ctl = jobs.Controller(ffmpeg, ffprobe, encoder, settings_path=settings, on_change=push)
    api = Api(ctl)
    window = webview.create_window(TITLE, url=resource("ui", "index.html"), js_api=api,
                                   width=900, height=680, min_size=(720, 520),
                                   background_color="#000000")
    api._window = window

    def on_drop(e):
        files = e.get("dataTransfer", {}).get("files", [])
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            ctl.add_paths(paths)

    def on_closing():
        if ctl.is_busy() and not self_test and not confirm_quit(window):
            return False
        ctl.shutdown()

    def on_start():
        if self_test:
            # pywebview's own DOM helpers give up after 15s; slow CI VMs can need longer
            loaded = window.events.loaded.wait(90)
            result["load_seconds"] = round(time.monotonic() - started, 1)
            if not loaded:
                result.update(ok=False, error="window never finished loading (90s)")
                window.destroy()
                return
        dark_title_bar(window)
        try:
            window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
            window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        except Exception as e:
            if not self_test:
                raise
            result.update(ok=False, error="drag-and-drop setup failed: %r" % e)
            window.destroy()
            return
        ctl.start()
        if ffmpeg is None:
            ctl.error = "ffmpeg is missing from this copy of the app. Re-download it."
        push()
        if self_test:
            result.update(run_self_test(window, ctl, ffmpeg, ffprobe, workdir))
            window.destroy()

    window.events.closing += on_closing
    # on macOS the Dock/window icon comes from the .icns PyInstaller puts in the bundle
    webview.start(on_start, icon=None if IS_MAC else resource("assets", "icon.ico"))

    if self_test:
        result.setdefault("ok", False)
        write_self_test_result(result)
        ctl.shutdown()
        sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
