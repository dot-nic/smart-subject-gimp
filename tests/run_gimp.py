"""Run batch files with explicit globals (GIMP's eval has its own __file__)."""
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
script = root / "tests" / (sys.argv[1] if len(sys.argv) > 1 else "probe_gimp.py")
report_name = {"probe_gimp.py": "probe.json", "integration_gimp2.py": "integration.json", "e2e_gimp2.py": "e2e.json"}.get(script.name)
if report_name:
    (root / "tests" / report_name).unlink(missing_ok=True)
gimp = sys.argv[2] if len(sys.argv) > 2 else r"C:\Program Files\GIMP 2\bin\gimp-console-2.10.exe"
code = "execfile(%r, {'__file__': %r, '__name__': '__main__'})" % (str(script), str(script))
command = [gimp, "-n", "-i", "-d", "-f", "-s", "-c", "--batch-interpreter=python-fu-eval",
           "-b", code, "-b", "pdb.gimp_quit(0)"]
result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300,
                        creationflags=0x08000000 if sys.platform == "win32" else 0)
log = result.stdout.decode("utf-8", "replace")
(root / "tests" / "gimp-last-run.log").write_text(log, encoding="utf-8")
print("\n".join(line for line in log.splitlines() if any(word in line for word in ("batch command", "Traceback", "Error:", "RuntimeError", "AssertionError"))))
print("GIMP exit:", result.returncode)
if report_name:
    report = json.loads((root / "tests" / report_name).read_text(encoding="utf-8"))
    if report.get("ok") is False:
        print(report.get("error", "Pruebas fallidas"))
        sys.exit(1)
sys.exit(result.returncode)
