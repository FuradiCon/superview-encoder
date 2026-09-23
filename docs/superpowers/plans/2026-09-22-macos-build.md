# Superview Encoder macOS Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce unsigned Apple Silicon and Intel Mac builds of Superview Encoder from the same codebase, built and verified on GitHub Actions, attached to GitHub releases next to the Windows zip.

**Architecture:** Small `sys.platform` switches go in `engine.py`, `jobs.py`, and `app.py`. A new `--self-test` mode exercises the real window and bundled ffmpeg without a human. A matrix workflow on `macos-15` and `macos-15-intel` runs tests, builds `.app` bundles with PyInstaller, self-tests them, and uploads zips.

**Tech Stack:** Python 3.14, pywebview 6.2.1 (Cocoa/WKWebView via pyobjc on Mac), PyInstaller 6.22.3, ffmpeg 9.0.2 static builds from ffmpeg.martin-riedl.de, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-22-macos-build-design.md`

## Global Constraints

- Repo: `D:\BOT Guide\Superview\encoder` (remote `FuradiCon/superview-encoder`, branch `main`).
- Windows behavior must not change. Run the full local test suite after every task.
- Unsigned. No Apple Developer ID and no notarization.
- Asset names: `Superview-Encoder.zip` (Windows, unchanged), `Superview-Encoder-Mac-AppleSilicon.zip`, and `Superview-Encoder-Mac-Intel.zip`.
- Runners: `macos-15` (arm64) and `macos-15-intel` (x86_64). GitHub Actions minutes are free for this public repo.
- Pinned ffmpeg 9.0.2 zips (SHA-256):
  - arm64 `https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffmpeg.zip` `c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924`
  - arm64 `.../arm64/1789931890_9.0.2/ffprobe.zip` `fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6`
  - x86_64 `https://ffmpeg.martin-riedl.de/download/macos/amd64/1789931006_9.0.2/ffmpeg.zip` `7c6b4125b191cbf773832dc51f424cf2b6bb7da43007d1e066f95909e47cacd4`
  - x86_64 `.../amd64/1789931006_9.0.2/ffprobe.zip` `2322438ed2f6319a691291b247d09c69dcaa3a982460d1f269a7e1af335cfdfd`
  - Each zip holds a single binary (`ffmpeg` or `ffprobe`) at its root.
- Mac defaults: output goes to `~/Movies/Superview`, settings to `~/Library/Application Support/Superview Encoder/settings.json`.
- pywebview facts (checked in source): on Cocoa `window.native` is the `NSWindow`; the `closing` handlers run synchronously on the main thread inside `windowShouldClose_`, and returning `False` cancels the close.

---

### Task 1: Engine platform switches, quarantine clean-up, test-clip helper

**Files:** Modify `engine.py`. Create `tests/test_platform.py`.

**Interfaces (Produces):**
- `IS_MAC: bool`, `IS_WIN: bool`, `NO_WINDOW: int` (0 off Windows)
- `candidates_for(platform: str) -> list[tuple[str, str, bool]]`. `CANDIDATES = candidates_for(sys.platform)`
- `tool_name(name: str, platform: str = sys.platform) -> str`
- `clear_quarantine(paths: list[str]) -> None` (a no-op off macOS)
- `make_test_clip(ffmpeg: str, path: str, w: int = 1440, h: int = 1080, secs: int = 2) -> None`
- `encoder_args` supports `hevc_videotoolbox`

- [ ] **Step 1: Failing tests.** Create `tests/test_platform.py`:
```python
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
    assert out == "/Users/a/Movies/Superview"
    assert settings == "/Users/a/Library/Application Support/Superview Encoder/settings.json"


def test_default_paths_windows():
    out, settings = jobs.default_paths("win32", home=r"C:\Users\a", appdata=r"C:\Users\a\AppData\Roaming")
    assert out.replace("\\", "/") == "C:/Users/a/Videos/Superview"
    assert settings.replace("\\", "/") == "C:/Users/a/AppData/Roaming/Superview Encoder/settings.json"
```
(The `jobs.default_paths` tests are implemented in Task 2. They're in this file so all platform checks live together.)

Run: `.venv\Scripts\python -m pytest tests/test_platform.py -q`. Expected: failures (AttributeError).

- [ ] **Step 2: Implement in `engine.py`.**

Replace the constants block
```python
VIDEO_EXTS = (".mp4", ".mov")
CREATE_NO_WINDOW = 0x08000000  # keep ffmpeg from flashing console windows
```
with
```python
VIDEO_EXTS = (".mp4", ".mov")
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
NO_WINDOW = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW: no console flashes on Windows


def tool_name(name, platform=sys.platform):
    return name + ".exe" if platform == "win32" else name
```
Replace every `creationflags=CREATE_NO_WINDOW` with `creationflags=NO_WINDOW` (there are two, in `_run` and `convert`).

In `find_tools()`, use `tool_name("ffmpeg")` and `tool_name("ffprobe")` for the joined filenames. Only add the winget glob and the System32 rule when `IS_WIN`:
```python
def _candidate_dirs():
    here = os.path.dirname(os.path.abspath(__file__))
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(os.path.join(sys._MEIPASS, "ffmpeg"))
    dirs.append(os.path.join(here, "ffmpeg"))
    if IS_WIN:
        dirs += sorted(glob.glob(os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages",
            "Gyan.FFmpeg*", "ffmpeg-*", "bin")), reverse=True)
    return dirs


def find_tools():
    """(ffmpeg, ffprobe) paths, or (None, None). On Windows, skips System32,
    which on the dev machine holds a 2019 ffmpeg too old for current NVIDIA drivers."""
    for d in _candidate_dirs():
        f, p = os.path.join(d, tool_name("ffmpeg")), os.path.join(d, tool_name("ffprobe"))
        if os.path.isfile(f) and os.path.isfile(p):
            return f, p
    f, p = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if f and p and IS_WIN:
        sys32 = os.path.normcase(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"))
        if os.path.normcase(os.path.dirname(f)) == sys32:
            return None, None
    if f and p:
        return f, p
    return None, None
```

Replace `CANDIDATES = [...]` with:
```python
def candidates_for(platform):
    if platform == "darwin":
        return [("hevc_videotoolbox", "Apple HEVC", True), ("libx265", "CPU HEVC", False)]
    return [("hevc_nvenc", "NVIDIA HEVC", True), ("hevc_qsv", "Intel HEVC", True),
            ("hevc_amf", "AMD HEVC", True), ("libx265", "CPU HEVC", False)]


CANDIDATES = candidates_for(sys.platform)
```
`detect_encoder(ffmpeg, candidates=CANDIDATES)` stays as is. The existing tests pass their own stubs and still expect the Windows order on Windows.

In `encoder_args`, before the libx265 fallback:
```python
    if enc.name == "hevc_videotoolbox":
        return ["-c:v", "hevc_videotoolbox", "-b:v", b, "-maxrate", peak]
```

After `find_tools`, add:
```python
def clear_quarantine(paths):
    """macOS marks every file from a downloaded zip as quarantined; once the user
    has approved the app, it may lift that mark from its own bundled binaries so
    Gatekeeper doesn't block ffmpeg separately. Best effort, errors ignored."""
    if not IS_MAC:
        return
    for p in paths:
        if p:
            try:
                subprocess.run(["xattr", "-d", "com.apple.quarantine", p],
                               capture_output=True, stdin=subprocess.DEVNULL)
            except OSError:
                pass
```

After `detect_encoder`, add:
```python
def make_test_clip(ffmpeg, path, w=1440, h=1080, secs=2):
    """A small 4:3 clip for the app's --self-test."""
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc2=s=%dx%d:d=%d:r=30" % (w, h, secs),
                    "-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "log-level=error",
                    "-pix_fmt", "yuv420p", path],
                   check=True, capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
```

- [ ] **Step 3: Run.** `.venv\Scripts\python -m pytest tests/test_platform.py tests/test_engine.py -q`. Expected: engine and platform tests pass except the two `default_paths` tests (Task 2).

- [ ] **Step 4: Commit.** `git add engine.py tests/test_platform.py` then `git commit -m "feat(engine): macOS tool names, VideoToolbox encoder, quarantine clean-up"`

---

### Task 2: Per-platform default output and settings paths

**Files:** Modify `jobs.py`.

**Interfaces (Produces):** `default_paths(platform, home, appdata) -> tuple[str, str]` returns `(DEFAULT_OUT, SETTINGS_PATH)`. `DEFAULT_OUT` and `SETTINGS_PATH` keep their names.

- [ ] **Step 1: Implement.** Replace the three constants `APP_DIR`, `SETTINGS_PATH`, and `DEFAULT_OUT` with:
```python
def default_paths(platform, home, appdata):
    """(default output folder, settings.json path) for this OS."""
    if platform == "darwin":
        return (os.path.join(home, "Movies", "Superview"),
                os.path.join(home, "Library", "Application Support", "Superview Encoder", "settings.json"))
    return (os.path.join(home, "Videos", "Superview"),
            os.path.join(appdata or home, "Superview Encoder", "settings.json"))


DEFAULT_OUT, SETTINGS_PATH = default_paths(sys.platform, os.path.expanduser("~"), os.environ.get("APPDATA"))
```
Add `import sys` to the imports. On Windows, `os.path.join` in the tests produces backslashes, and the test normalises them. On macOS it produces the expected slashes. The Windows test runs on the Mac runner too, where the join uses `/`, which the test also accepts.

- [ ] **Step 2: Run everything.** `.venv\Scripts\python -m pytest -q`. Expected: `34 passed`

- [ ] **Step 3: Commit.** `git add jobs.py` then `git commit -m "feat(jobs): macOS default output and settings paths"`

---

### Task 3: app.py platform switches and `--self-test`

**Files:** Modify `app.py`.

**Interfaces:** Consumes `engine.IS_MAC`, `engine.clear_quarantine`, `engine.make_test_clip`, and `jobs.Controller(settings_path=...)`. Produces the CLI flag `--self-test`: exit code 0 on success, 1 on failure, and the result JSON is written to `<tempdir>/superview-selftest.json`, with the path also printed when stdout exists.

- [ ] **Step 1: Platform helpers.** In `app.py`:

Replace `open_output_dir` with:
```python
    def open_output_dir(self):
        os.makedirs(self._ctl.output_dir, exist_ok=True)
        if sys.platform == "darwin":
            subprocess.run(["open", self._ctl.output_dir])
        else:
            os.startfile(self._ctl.output_dir)
```
(Add `import subprocess`, `import tempfile`, `import threading`, and `import time`.)

Rename `dark_title_bar` to `_dark_title_bar_win` and add:
```python
def _dark_title_bar_mac(window):
    try:
        from AppKit import NSAppearance
        from PyObjCTools import AppHelper
        AppHelper.callAfter(lambda: window.native.setAppearance_(
            NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua")))
    except Exception:
        pass


def dark_title_bar(window):
    (_dark_title_bar_mac if sys.platform == "darwin" else _dark_title_bar_win)(window)


def confirm_quit(window):
    """True if the user agrees to stop the running conversion and quit."""
    text = "A video is still converting."
    info = "Stop it and quit? The unfinished file will be deleted."
    if sys.platform == "darwin":
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
```
Then in `main()`, `on_closing` becomes:
```python
    def on_closing():
        if ctl.is_busy() and not confirm_quit(window):
            return False
        ctl.shutdown()
```

- [ ] **Step 2: Self-test.** Add:
```python
def run_self_test(window, ctl, ffmpeg, ffprobe, workdir):
    """Exercise the real window + bundled ffmpeg without a human. Returns a result dict."""
    res = {"ok": False, "ffmpeg": ffmpeg, "encoder": ctl.encoder.name if ctl.encoder else None}
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
        while time.monotonic() < end:
            item = ctl.snapshot()["items"][0]
            if item["status"] not in ("waiting", "converting"):
                break
            time.sleep(0.25)
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
```

In `main()`:
- At the top: `self_test = "--self-test" in sys.argv`, and `workdir = tempfile.mkdtemp(prefix="superview-selftest-") if self_test else None`.
- After `find_tools()`: `engine.clear_quarantine([ffmpeg, ffprobe])`.
- Create the controller with `settings_path=os.path.join(workdir, "settings.json") if self_test else jobs.SETTINGS_PATH`, so the self-test never touches real settings.
- Keep `result = {}` in `main()`. At the end of `on_start`:
```python
        if self_test:
            result.update(run_self_test(window, ctl, ffmpeg, ffprobe, workdir))
            window.destroy()
```
- After `webview.start(...)` returns:
```python
    if self_test:
        out = os.path.join(tempfile.gettempdir(), "superview-selftest.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        if sys.stdout:
            print(json.dumps(result, indent=2))
        ctl.shutdown()
        sys.exit(0 if result.get("ok") else 1)
```
- Pass `icon=resource("assets", "icon.ico")` only when `sys.platform == "win32"`. On macOS the bundle icon comes from the `.icns` that PyInstaller embeds.

- [ ] **Step 3: Verify on Windows (dev).** Run `.venv\Scripts\python app.py --self-test; echo exit=$LASTEXITCODE`. Expected: the window flashes open and closes, the JSON shows `"ok": true, "encoder": "hevc_nvenc", "output": "1920x1080"`, and `exit=0`. Then run `.venv\Scripts\python app.py` normally and drop `tests\_out\dji10.mp4` (delete the old output first) to confirm the GUI is unchanged.

- [ ] **Step 4: Verify on Windows (frozen).** Run `build.ps1`, then `& "dist\Superview Encoder\Superview Encoder.exe" --self-test; $LASTEXITCODE` and read `$env:TEMP\superview-selftest.json`. Expected: `ok: true`, and `ffmpeg` points inside `_internal\ffmpeg`.

- [ ] **Step 5: Full tests, then commit.** `.venv\Scripts\python -m pytest -q` (34 passed). `git commit -am "feat(app): macOS dark frame, NSAlert quit guard, Finder open, --self-test"`

---

### Task 4: Mac icon, Mac README, credits, GitHub README

**Files:** Modify `assets/make_icon.py`, `dist-extras/LICENSES/CREDITS.txt`, and `README.md`. Create `assets/icon.icns` and `dist-extras/README-mac.txt`.

- [ ] **Step 1: Icon.** At the end of `make_icon.py` add:
```python
big = img.resize((1024, 1024), Image.NEAREST)
big.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.icns"))
```
Run `.venv\Scripts\python assets\make_icon.py`. Verify with `.venv\Scripts\python -c "from PIL import Image; im=Image.open('assets/icon.icns'); print(im.format, im.size)"`. Expected: `ICNS (1024, 1024)` or similar.

- [ ] **Step 2: `dist-extras/README-mac.txt`:**
```
SUPERVIEW ENCODER (Mac)
Stretches 4:3 action-cam video (GoPro, DJI) to 16:9, GoPro "SuperView" style.

INSTALL (one time)
1. Unzip, then drag "Superview Encoder" into your Applications folder.
   (Don't run it from Downloads -- macOS runs downloaded apps from a
   read-only hiding place, and the app can't finish setting itself up.)
2. Double-click it. macOS will say it can't verify the app, because it
   isn't signed with a paid Apple developer account. Click "Done".
3. Open System Settings -> Privacy & Security, scroll down, and click
   "Open Anyway" next to Superview Encoder. Enter your Mac password.
   From then on it opens normally.

STILL BLOCKED?
Open Terminal (Applications -> Utilities) and paste this one line, then
press Return:
    xattr -cr "/Applications/Superview Encoder.app"

USING IT
Drag videos or folders onto the window. Converted files go to Movies/Superview,
or pick another folder with "Change...". Uses the Mac's hardware video encoder
when it can; the top-right chip says "CPU - SLOW" if it can't.
Needs macOS 12 or later. There are separate downloads for Apple Silicon and Intel Macs
(Apple menu -> About This Mac -> "Chip").
```

- [ ] **Step 3: CREDITS.** Add this line after the Gyan line:
`  macOS builds use FFmpeg static builds by Martin Riedl (https://ffmpeg.martin-riedl.de), also GPL v3.`

- [ ] **Step 4: GitHub README.** Replace the Download section's single link with:
```markdown
| | Download |
|---|---|
| **Windows** 10/11 | [Superview-Encoder.zip](https://github.com/FuradiCon/superview-encoder/releases/latest/download/Superview-Encoder.zip) |
| **Mac, Apple Silicon** (M1 and later) | [Superview-Encoder-Mac-AppleSilicon.zip](https://github.com/FuradiCon/superview-encoder/releases/latest/download/Superview-Encoder-Mac-AppleSilicon.zip) |
| **Mac, Intel** | [Superview-Encoder-Mac-Intel.zip](https://github.com/FuradiCon/superview-encoder/releases/latest/download/Superview-Encoder-Mac-Intel.zip) |

Not sure which Mac you have? Apple menu → About This Mac → "Chip" says Apple M-something (Apple Silicon) or Intel.
```
Then add a "### Mac first launch" subsection with steps 1–3 and the Terminal line from README-mac.txt, and note that the Mac builds are untested by hand and to report problems in Issues.

- [ ] **Step 5: Commit.** `git add assets dist-extras README.md` then `git commit -m "docs: Mac icon, Mac README, three download links"`

---

### Task 5: GitHub Actions workflow and dry run

**Files:** Create `.github/workflows/macos.yml`.

- [ ] **Step 1: Workflow.**
```yaml
name: macOS builds

on:
  release:
    types: [published]
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - runner: macos-15
            arch: AppleSilicon
            ffmpeg_url: https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffmpeg.zip
            ffmpeg_sha: c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924
            ffprobe_url: https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffprobe.zip
            ffprobe_sha: fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6
          - runner: macos-15-intel
            arch: Intel
            ffmpeg_url: https://ffmpeg.martin-riedl.de/download/macos/amd64/1789931006_9.0.2/ffmpeg.zip
            ffmpeg_sha: 7c6b4125b191cbf773832dc51f424cf2b6bb7da43007d1e066f95909e47cacd4
            ffprobe_url: https://ffmpeg.martin-riedl.de/download/macos/amd64/1789931006_9.0.2/ffprobe.zip
            ffprobe_sha: 2322438ed2f6319a691291b247d09c69dcaa3a982460d1f269a7e1af335cfdfd
    runs-on: ${{ matrix.runner }}
    env:
      MACOSX_DEPLOYMENT_TARGET: "12.0"
      ASSET: Superview-Encoder-Mac-${{ matrix.arch }}.zip
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"

      - name: Install Python deps
        run: python -m pip install -r requirements.txt

      - name: Fetch ffmpeg 9.0.2 (pinned, checksummed)
        run: |
          mkdir -p ffmpeg
          curl -fsSL "${{ matrix.ffmpeg_url }}" -o /tmp/ffmpeg.zip
          curl -fsSL "${{ matrix.ffprobe_url }}" -o /tmp/ffprobe.zip
          echo "${{ matrix.ffmpeg_sha }}  /tmp/ffmpeg.zip"  | shasum -a 256 -c -
          echo "${{ matrix.ffprobe_sha }}  /tmp/ffprobe.zip" | shasum -a 256 -c -
          unzip -o /tmp/ffmpeg.zip -d ffmpeg
          unzip -o /tmp/ffprobe.zip -d ffmpeg
          chmod +x ffmpeg/ffmpeg ffmpeg/ffprobe
          ffmpeg/ffmpeg -hide_banner -encoders | grep -E "hevc_videotoolbox|libx265"

      - name: Tests (unit + real encodes)
        run: python -m pytest -q

      - name: Build .app
        run: |
          python -m PyInstaller --noconfirm --clean --windowed --onedir \
            --name "Superview Encoder" --icon assets/icon.icns \
            --osx-bundle-identifier com.furadicon.superview-encoder \
            --add-data "ui:ui" --add-data "ffmpeg:ffmpeg" \
            app.py

      - name: Self-test the built app
        run: |
          "dist/Superview Encoder.app/Contents/MacOS/Superview Encoder" --self-test || {
            cat "$TMPDIR/superview-selftest.json" 2>/dev/null; exit 1; }
          cat "$TMPDIR/superview-selftest.json"

      - name: Package
        run: |
          mkdir -p pkg
          cp -R "dist/Superview Encoder.app" pkg/
          cp dist-extras/README-mac.txt pkg/README.txt
          cp -R dist-extras/LICENSES pkg/
          ditto -c -k --keepParent pkg "$ASSET"
          du -sh pkg "$ASSET"

      - name: Upload to release
        if: github.event_name == 'release'
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh release upload "${{ github.event.release.tag_name }}" "$ASSET" --clobber

      - name: Keep as workflow artifact (dry runs)
        if: github.event_name == 'workflow_dispatch'
        uses: actions/upload-artifact@v4
        with:
          name: ${{ env.ASSET }}
          path: ${{ env.ASSET }}
```
Note: `ditto --keepParent pkg` makes the zip's top folder `pkg`. Rename the staging folder to `Superview Encoder` instead, so friends see a sensible folder name: use `mkdir -p "Superview Encoder"` and substitute it for `pkg` throughout.

- [ ] **Step 2: Push and dry run.** Run `git add .github` then `git commit -m "ci: macOS Apple Silicon + Intel builds"` then `git push`. Then run `gh workflow run macos.yml` and watch it with `gh run watch <id> --exit-status`. On failure, read the logs (`gh run view <id> --log-failed`), fix, push, and re-run. Stop and report to the user after 3 failed attempts on the same step.

- [ ] **Step 3: Inspect the artifacts.** Run `gh run download <id> -D tests/_out/mac`. Confirm both zips contain `Superview Encoder/Superview Encoder.app/Contents/MacOS/Superview Encoder`, `.../Contents/Resources/icon.icns` (or the PyInstaller-named equivalent), `_internal`/`Frameworks` containing `ffmpeg/ffmpeg`, `README.txt`, and `LICENSES/`. Record the sizes.

---

### Task 6: Release v1.1.0 (Windows + both Macs)

- [ ] **Step 1: Rebuild Windows** from the same commit with `build.ps1`, then run the frozen self-test (Task 3 Step 4).
- [ ] **Step 2: Publish.** Copy the zip to `%TEMP%\Superview-Encoder.zip`, then run `gh release create v1.1.0 "%TEMP%\Superview-Encoder.zip" --title "Superview Encoder 1.1.0" --notes <mac notes>`. Publishing triggers the macOS workflow, which attaches the two Mac zips.
- [ ] **Step 3: Verify.** Watch the run. Then confirm with `curl -sIL` that all three `releases/latest/download/...` links return 200 with sensible sizes.
