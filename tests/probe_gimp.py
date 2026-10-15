# -*- coding: utf-8 -*-
from gimpfu import *
import json
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
names = ["gimp-file-save", "file-png-save2", "gimp-image-select-item", "gimp-layer-set-offsets"]
report = {"gimp_version": gimp.version, "procedures": {}}
for name in names:
    proc = pdb[name]
    report["procedures"][name] = {"params": proc.params}
report["registered"] = [name for name in pdb.query() if "smart-subject" in name]
with open(os.path.join(ROOT, "tests", "probe.json"), "wb") as stream:
    stream.write(json.dumps(report, indent=2))
