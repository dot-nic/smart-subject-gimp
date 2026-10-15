"""Extract portable bundle under a new Unicode path and run offline."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
root = Path(__file__).resolve().parents[1]
archive_path = Path(sys.argv[1])
with tempfile.TemporaryDirectory(prefix="GIMP modulo portatil ") as temporary:
    extracted = Path(temporary) / "Prueba portátil"
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(extracted)
    module = extracted / "smart-subject"
    environment = os.environ.copy()
    environment.pop("PYTHONHOME",None)
    environment.pop("PYTHONPATH",None)
    command = [str(module / "runtime/python.exe"), str(module / "backend/engine.py")]
    doctor = subprocess.run(command + ["--doctor"], capture_output=True, env=environment, timeout=120)
    assert doctor.returncode == 0, doctor.stderr.decode("utf-8","replace")
    inference = subprocess.run(command + ["--in", str(root / "tests/fixtures/tiger.jpg"),
                                          "--out", str(extracted / "mask.png")],
                               capture_output=True, env=environment, timeout=120)
    assert inference.returncode == 0, inference.stderr.decode("utf-8","replace")
    report = {"ok": True, "unicode_path": True, "doctor": json.loads(doctor.stdout),
              "inference": json.loads(inference.stdout)}
    (root / "tests/portability.json").write_text(json.dumps(report,indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report,indent=2))
