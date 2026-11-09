"""Reproduce the app's code-drawn book/integral icon as Windows ICO (Pillow)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[1] / 'studyread' / 'web'
size = 512
image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
def point(x, y): return (x * 4, y * 4)
draw.rounded_rectangle((0, 0, 511, 511), radius=116, fill='#173f45')
def curve(a, b, c, d):
    return [point(*tuple((1-t)**3*a[i]+3*(1-t)**2*t*b[i]+3*(1-t)*t*t*c[i]+t**3*d[i] for i in (0,1)))
            for t in [j/30 for j in range(31)]]
book = curve((23,34),(41,26),(54,29),(64,37)) + curve((64,37),(74,29),(87,26),(105,34))
book += [point(105,98)] + curve((105,98),(88,91),(74,93),(64,100))
book += curve((64,100),(54,93),(40,91),(23,98))
draw.polygon(book, fill='#f5f1e5')
draw.line([point(64,38),point(64,97)],fill='#acc3b9',width=12)
draw.line(curve((83,47),(74,42),(76,55),(73,67))+curve((73,67),(70,79),(71,86),(63,82)),fill='#ba8650',width=16)
for y, end in [(49,51),(60,51),(71,47)]:
    draw.line([point(34,y),point(end,y)],fill='#7e9d94',width=12)
image.save(root / 'icon.png')
image.save(root / 'icon.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('Windows icon generated')
