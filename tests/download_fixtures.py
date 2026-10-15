"""Optional test setup; no photographs are downloaded during normal usage."""
from pathlib import Path
from urllib.request import urlopen
root = Path(__file__).resolve().parent / "fixtures"
root.mkdir(exist_ok=True)
url = "https://huggingface.co/datasets/Xenova/transformers.js-docs/resolve/main/tiger.jpg"
with urlopen(url, timeout=60) as response:
    (root / "tiger.jpg").write_bytes(response.read())
print("Fixture descargado:", root / "tiger.jpg")
