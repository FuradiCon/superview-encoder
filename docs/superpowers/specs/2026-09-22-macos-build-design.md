# Superview Encoder for macOS: design

**Date:** 2026-09-22 · **Status:** approved in chat

## Goal

Ship Mac versions of Superview Encoder next to the Windows one, from the same codebase. Nobody
on the team has a Mac, so the builds and all automated verification run on GitHub-hosted macOS
runners. A friend's first launch is the only manual test.

## Decisions

| Question | Decision |
|---|---|
| Code signing | **Unsigned** (no Apple Developer account). Friends get past Gatekeeper using written instructions. |
| Architectures | **Two downloads**: Apple Silicon (arm64) and Intel (x86_64). No universal2 build. |
| Where builds happen | GitHub Actions, triggered when a release is published. The Windows build stays local (`build.ps1`). |
| Minimum macOS | 12 Monterey |

## Code changes (one codebase, small platform switches)

**engine.py**
- `CREATE_NO_WINDOW` is passed only on Windows. On other platforms `creationflags` is 0.
- Tool names are `ffmpeg`/`ffprobe` on macOS and `ffmpeg.exe`/`ffprobe.exe` on Windows. The
  bundled `ffmpeg/` folder is still checked first. The winget and System32 rules apply only on Windows.
- Encoder candidates on macOS are `hevc_videotoolbox` ("Apple HEVC", GPU), then `libx265`. On
  Windows they're unchanged. `hevc_videotoolbox` uses `p010le`/`nv12` like the other GPU
  encoders, with args `-c:v hevc_videotoolbox -b:v <bitrate> -maxrate <1.5×>`.
- New `clear_quarantine(paths)`, macOS only. It runs `xattr -d com.apple.quarantine` on the
  bundled ffmpeg/ffprobe and ignores errors. It's called once at startup, before encoder detection.

**jobs.py**
- On macOS the default output is `~/Movies/Superview` and settings live at
  `~/Library/Application Support/Superview Encoder/settings.json`. Windows is unchanged.

**app.py**
- Dark window frame: `dark_title_bar` does the DWM call on Windows. On macOS it sets the window's
  `NSAppearance` to `NSAppearanceNameDarkAqua`.
- Close-while-converting warning: Windows keeps `MessageBoxW`. macOS uses an `NSAlert`
  shown on the main thread.
- Open folder: `os.startfile` on Windows, `open <dir>` on macOS.
- **`--self-test` flag:** opens the real window, waits for the page to load, checks that
  `window.render` exists, runs the Controller on a generated 2-second 4:3 clip through the bundled
  ffmpeg until it's done, confirms the output is 16:9, writes the result to stdout, closes the
  window, and exits with code 0 on success or 1 on failure. There's a 120-second timeout.

**assets**
- `make_icon.py` also writes `icon.icns` (Pillow).

## Build (GitHub Actions, `.github/workflows/macos.yml`)

- Trigger: `release: published`, plus manual `workflow_dispatch` for dry runs that upload
  workflow artifacts instead of attaching to a release.
- Matrix: `macos-15` (arm64, asset suffix `AppleSilicon`) and `macos-15-intel` (x86_64, `Intel`).
  GitHub is expected to retire the Intel runner around 2027, and Intel builds stop then.
- Steps: setup-python 3.14, `pip install -r requirements.txt`, then download ffmpeg + ffprobe
  9.0.2 for the runner's architecture from ffmpeg.martin-riedl.de (pinned URLs, SHA-256 checked),
  then `pytest` (all 26 tests, including real encodes), then PyInstaller
  `--windowed --onedir --osx-bundle-identifier com.furadicon.superview-encoder` producing
  `Superview Encoder.app`, then add README-mac.txt and the licences, then run the built app with
  `--self-test`, then zip with `ditto -c -k --keepParent` (keeps symlinks and the ad-hoc
  signature), then `gh release upload` the zip to the triggering release.
- Asset names: `Superview-Encoder-Mac-AppleSilicon.zip` and `Superview-Encoder-Mac-Intel.zip`.

## First launch on a friend's Mac (untestable here, the main risk)

`dist-extras/README-mac.txt` (text steps, since there's no Mac to take real screenshots on):
1. Unzip, then **drag `Superview Encoder.app` into Applications**. Running it from Downloads
   triggers App Translocation, which makes it read-only and blocks the quarantine clean-up.
2. Open it. When macOS says it can't verify the app, click Done, then go to **System Settings →
   Privacy & Security → "Open Anyway"** and enter the Mac password.
3. If it still refuses, or ffmpeg is blocked, run this one line in Terminal:
   `xattr -cr "/Applications/Superview Encoder.app"`

The GitHub README gets three download links (Windows, Mac Apple Silicon, Mac Intel), a
"which Mac do I have?" hint (Apple menu → About This Mac → Chip), and the same steps.

## Testing

| What | How |
|---|---|
| Engine and queue on macOS | The existing 26 pytest tests on both runners (the real-encode tests use the runner's encoder, which is probably libx265, since the VMs have no GPU) |
| Platform switches | New unit tests that monkeypatch `sys.platform` for tool names, encoder candidates, default paths, and creationflags |
| The bundled app launches, the window loads, and bundled ffmpeg converts | `--self-test` inside the built `.app` on both runners |
| Windows didn't regress | Full local test suite + dev app launch + `build.ps1` on Windows |
| Drag and drop with a real mouse, looks, Gatekeeper flow | A friend's first try. Not covered by automation |

## Out of scope

Signing and notarization, universal2 builds, a DMG installer, auto-update, and building Windows in CI.
