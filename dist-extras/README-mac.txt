SUPERVIEW ENCODER (Mac)
Stretches 4:3 DVR video to 16:9, GoPro "SuperView" style:
the middle stays natural, the edges take the stretch.

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

Needs macOS 12 or later. There are separate downloads for Apple Silicon and
Intel Macs (Apple menu -> About This Mac -> "Chip" says Apple M-something or Intel).
