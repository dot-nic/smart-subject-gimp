"""Failure isolation and original alpha preservation with the actual model."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from PIL import Image
root = Path(__file__).resolve().parents[1]
engine = root / "backend/engine.py"
report = {"checks": []}
with tempfile.TemporaryDirectory(prefix="smart-subject-test-") as workspace:
    folder = Path(workspace)
    missing = subprocess.run([sys.executable, str(engine), "--in", str(folder / "missing.png"),
                              "--out", str(folder / "missing-mask.png")], capture_output=True)
    assert missing.returncode != 0 and not (folder / "missing-mask.png").exists()
    report["checks"].append("entrada inexistente no crea salida")
    image = Image.open(root / "tests/fixtures/tiger.jpg").convert("RGBA")
    image.paste((0,0,0,0), (0,0,50,image.height))
    image.save(folder / "alpha.png")
    result = subprocess.run([sys.executable, str(engine), "--in", str(folder / "alpha.png"),
                             "--out", str(folder / "mask.png")], capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    with Image.open(folder / "mask.png") as mask:
        assert mask.mode == "L" and mask.size == image.size
        assert mask.crop((0,0,50,image.height)).getextrema() == (0,0)
        assert mask.getextrema() == (0,255)
    report["checks"].append("PNG gris de dimensiones originales")
    report["checks"].append("pixeles transparentes excluidos")
    report["metrics"] = json.loads(result.stdout)
report["ok"] = True
(root / "tests/backend-checks.json").write_text(json.dumps(report,indent=2)+"\n", encoding="utf-8")
print(json.dumps(report,indent=2))
