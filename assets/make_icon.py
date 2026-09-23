"""Draws icon.ico: black tile, grey 4:3 frame, orange 16:9 frame. Dev-only (Pillow)."""
import os
from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 255))
d = ImageDraw.Draw(img)
d.rectangle([78, 58, 178, 198], outline=(139, 139, 139, 255), width=10)      # 4:3 (portrait-ish inner)
d.rectangle([20, 72, 236, 184], outline=(255, 90, 0, 255), width=14)         # 16:9 accent
img.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico"),
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

# macOS bundle icon (PyInstaller --icon on the Mac runners)
big = img.resize((1024, 1024), Image.NEAREST)
big.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.icns"))
