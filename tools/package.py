"""Make a portable ZIP; never include build tools, test images or bytecode."""
from pathlib import Path
import sys
import zipfile
root = Path(__file__).resolve().parents[1]
target = Path(sys.argv[1]).resolve()
with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or path == target:
            continue
        if "build-libs" in relative.parts or "__pycache__" in relative.parts or path.suffix in (".pyc", ".pyo"):
            continue
        if "tests" in relative.parts and path.suffix not in (".py", ".json", ".md"):
            continue
        if path.name in ("alternative-model.json", "benchmark-failed.json"):
            continue
        archive.write(path, "smart-subject/" + relative.as_posix())
print(target)
print("zip_bytes", target.stat().st_size)
