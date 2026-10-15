"""Installer only: download pinned weights, verify upstream LFS SHA-256."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen, Request

ROOT = Path(__file__).resolve().parents[1]
REPO = "studioludens/birefnet-lite-512"
FILENAME = "onnx/model_fp16.onnx"


def get(url):
    return urlopen(Request(url, headers={"User-Agent": "SmartSubject-Installer/1.0"}), timeout=120)


def main():
    folder = ROOT / "models"
    folder.mkdir(exist_ok=True)
    manifest_path = folder / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        installed = folder / manifest["file"]
        if installed.is_file():
            with installed.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() == manifest["sha256"]:
                    print("Modelo instalado y verificado: " + installed.name)
                    return
        revision = manifest["revision"]
    else:
        with get("https://huggingface.co/api/models/" + REPO) as response:
            revision = json.load(response)["sha"]
    with get("https://huggingface.co/api/models/%s/revision/%s?blobs=true" % (REPO, revision)) as response:
        info = json.load(response)
    entry = next(x for x in info["siblings"] if x["rfilename"] == FILENAME)
    expected = entry["lfs"]["sha256"]
    target = folder / "upstream-fp16.download.onnx"
    if target.exists():
        with target.open("rb") as stream:
            valid = hashlib.file_digest(stream, "sha256").hexdigest() == expected
    else:
        valid = False
    if not valid:
        partial = target.with_suffix(".part")
        digest = hashlib.sha256()
        try:
            with get("https://huggingface.co/%s/resolve/%s/%s" % (REPO, revision, FILENAME)) as response, partial.open("wb") as stream:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    stream.write(chunk)
            if digest.hexdigest() != expected:
                raise RuntimeError("SHA-256 incorrecto: se descarta el modelo")
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
    for remote, local in [("LICENSE", "LICENSE-BiRefNet.txt"), ("README.md", "MODEL-CARD.md")]:
        with get("https://huggingface.co/%s/resolve/%s/%s" % (REPO, revision, remote)) as response:
            (folder / local).write_bytes(response.read())
    native = folder / "native.build.onnx"
    compact = folder / "birefnet-lite-512-native-fp16.onnx"
    # Build dependencies are only needed to reconstruct a deleted model;
    # the distributable already includes the verified optimized weights.
    subprocess.run([sys.executable, str(ROOT / "tools/optimize_model.py"), str(target), str(native)], check=True)
    subprocess.run([sys.executable, str(ROOT / "tools/prepare_model.py"), str(native), str(compact)], check=True)
    with compact.open("rb") as stream:
        optimized_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {"repository": REPO, "revision": revision, "upstream_file": FILENAME,
                "upstream_sha256": expected, "upstream_bytes": target.stat().st_size,
                "file": compact.name, "sha256": optimized_digest, "bytes": compact.stat().st_size,
                "transforms": ["20 expanded deformable convolutions replaced by native ONNX DeformConv",
                               "Constant tensors stored as initializers", "ORT 1.31.0 BASIC offline optimization"],
                "license": "MIT", "input_size": 512, "output": "logits", "normalization": "imagenet"}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    target.unlink()
    native.unlink()
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
