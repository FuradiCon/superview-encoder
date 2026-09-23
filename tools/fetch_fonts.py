"""Download the dashboard's three font families as latin woff2 into ui/fonts/."""
import os, re, urllib.request

CSS = ("https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@600;700"
       "&family=Public+Sans:wght@400;600&family=Spline+Sans+Mono:wght@400;500&display=swap")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "fonts")

css = urllib.request.urlopen(urllib.request.Request(CSS, headers=UA)).read().decode()
os.makedirs(OUT, exist_ok=True)
blocks = re.findall(r"/\* latin \*/\s*@font-face\s*{(.*?)}", css, re.S)
urls = [re.search(r"url\((https://[^)]+\.woff2)\)", b).group(1) for b in blocks]
for block in blocks:
    fam = re.search(r"font-family: '([^']+)'", block).group(1)
    wt = re.search(r"font-weight: (\d+)", block).group(1)
    url = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
    # variable fonts come back as one file for every weight: save it once, unweighted
    name = fam.replace(" ", "") + ("" if urls.count(url) > 1 else "-" + wt) + ".woff2"
    if os.path.exists(os.path.join(OUT, name)) and urls.count(url) > 1:
        continue
    urllib.request.urlretrieve(url, os.path.join(OUT, name))
    print(name)
