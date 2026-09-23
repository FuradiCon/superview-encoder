"""
Superview Encoder -- desktop window. Drop 4:3 clips, get SuperView 16:9 out.

Wires jobs.Controller (queue) to the ui/ page through pywebview. Python owns
all state and pushes snapshots to window.render(); the page calls back via
window.pywebview.api.
"""

import ctypes
import json
import os
import sys

import webview
from webview.dom import DOMEventHandler

import engine
import jobs

TITLE = "Superview Encoder"


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
        os.startfile(self._ctl.output_dir)

    def cancel_current(self):
        self._ctl.cancel_current()

    def remove(self, item_id):
        self._ctl.remove(int(item_id))

    def clear_finished(self):
        self._ctl.clear_finished()


def _hwnd(window):
    return int(window.native.Handle.ToInt64())


def dark_title_bar(window):
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


def main():
    ffmpeg, ffprobe = engine.find_tools()
    encoder = engine.detect_encoder(ffmpeg) if ffmpeg else None
    window = None

    def push():
        if window is not None:
            window.run_js("window.render && window.render(%s)" % json.dumps(ctl.snapshot()))

    ctl = jobs.Controller(ffmpeg, ffprobe, encoder, on_change=push)
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
        if ctl.is_busy():
            MB_YESNO, MB_ICONWARNING, IDYES = 0x04, 0x30, 6
            answer = ctypes.windll.user32.MessageBoxW(
                _hwnd(window), "A video is still converting.\n\nStop it and quit? The unfinished file will be deleted.",
                TITLE, MB_YESNO | MB_ICONWARNING)
            if answer != IDYES:
                return False
        ctl.shutdown()

    def on_start():
        dark_title_bar(window)
        window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
        window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        ctl.start()
        if ffmpeg is None:
            ctl.error = "ffmpeg is missing from this copy of the app. Re-download it."
        push()

    window.events.closing += on_closing
    webview.start(on_start, icon=resource("assets", "icon.ico"))


if __name__ == "__main__":
    main()
