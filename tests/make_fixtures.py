from pathlib import Path
from PIL import Image
root = Path(__file__).resolve().parent
image = Image.new("L", (64, 48), 0)
for y in range(10, 40):
    for x in range(15, 50):
        image.putpixel((x, y), 128)
image.save(root / "fixtures/gradient.png")
