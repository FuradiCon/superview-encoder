# Superview Encoder

Stretch 4:3 action-cam footage (GoPro, DJI) to 16:9, GoPro "SuperView" style: the
middle of the frame stays natural and the edges take the stretch. Drag videos in from
any folder, and they're converted on your graphics card at the original quality.

![Superview Encoder](docs/screenshot.png)

## Download

**[⬇ Download Superview Encoder for Windows](https://github.com/FuradiCon/superview-encoder/releases/latest/download/Superview-Encoder.zip)** (about 88 MB, Windows 10/11)

1. Unzip the whole folder somewhere and keep the files together.
2. Double-click `Superview Encoder.exe`.
3. Drag videos or folders onto the window. Converted files land in `Videos\Superview`,
   or in whichever folder you pick with **Change…**.

**First run:** the app isn't code-signed, so Windows shows a blue "Windows protected your PC"
screen. Click **More info**, then **Run anyway**. You only need to do this once.

## What it does

- Uses the SuperView stretch formula from [Niek/superview](https://github.com/Niek/superview),
  byte for byte, and fixes its crash on DJI files, which carry a hidden preview video stream.
- Encodes to HEVC on NVIDIA, Intel, or AMD GPUs, and falls back to the CPU (slow) if none is available.
- Keeps 10-bit color and matches the source bitrate. There are no quality settings to fiddle with.
- Queues files one at a time. You can cancel, and failed files show ffmpeg's actual error.

## Building from source

Requires Python 3.14 on Windows.

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python tools\fetch_fonts.py          # fonts are already committed; only needed to refresh them
# put ffmpeg.exe + ffprobe.exe (Gyan "essentials" build) into ffmpeg\
.venv\Scripts\python -m pytest                     # 26 tests; -m "not slow" skips real encodes
.venv\Scripts\python app.py                        # run from source
powershell -ExecutionPolicy Bypass -File build.ps1 # build dist\ and the zip
```

## License

The app code is MIT licensed (see `LICENSE`). The release zip bundles FFmpeg (GPL v3, from
[gyan.dev](https://www.gyan.dev/ffmpeg/builds/)) and three fonts under the SIL Open Font License.
Their licenses and credits are in `dist-extras/LICENSES/`.
