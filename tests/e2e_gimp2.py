# -*- coding: utf-8 -*-
from gimpfu import *
import hashlib
import json
import os
import tempfile
import time
import traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
report = {"checks": [], "gimp_version": gimp.version}
image = None
def check(condition, message):
    if not condition:
        raise AssertionError(message)
    report["checks"].append(message)
def raw(layer):
    return layer.get_pixel_rgn(0,0,layer.width,layer.height,False,False)[:,:]
try:
    fixture = os.path.join(ROOT, "tests/fixtures/tiger.jpg")
    image = pdb.gimp_file_load(fixture, fixture, run_mode=RUN_NONINTERACTIVE)
    layer = image.layers[0]
    before = hashlib.sha256(raw(layer)).hexdigest()
    temporary_before = set(name for name in os.listdir(tempfile.gettempdir()) if name.startswith("gimp-smart-subject-"))
    started = time.time()
    pdb.python_fu_smart_subject_select(image,layer,run_mode=RUN_NONINTERACTIVE)
    report["select_seconds"] = round(time.time()-started,3)
    check(not pdb.gimp_selection_is_empty(image), "sujeto seleccionado por comando registrado")
    check(hashlib.sha256(raw(layer)).hexdigest() == before, "seleccion conserva pixeles")
    check(len(image.layers) == 1 and layer.mask is None, "seleccion conserva estructura")
    selected = raw(pdb.gimp_image_get_selection(image))
    started = time.time()
    pdb.python_fu_smart_subject_mask(image,layer,run_mode=RUN_NONINTERACTIVE)
    report["mask_seconds"] = round(time.time()-started,3)
    check(layer.mask is not None, "mascara creada por comando registrado")
    check(raw(pdb.gimp_image_get_selection(image)) == selected, "mascara conserva seleccion")
    check(hashlib.sha256(raw(layer)).hexdigest() == before, "mascara conserva pixeles")
    temporary_after = set(name for name in os.listdir(tempfile.gettempdir()) if name.startswith("gimp-smart-subject-"))
    check(temporary_before == temporary_after, "temporales de imagen eliminados")
    pdb.gimp_selection_none(image)
    output = os.path.join(ROOT, "tests/tiger-result.xcf")
    pdb.gimp_xcf_save(0, image,layer,output,output)
    report["ok"] = True
except Exception:
    report["ok"] = False
    report["error"] = traceback.format_exc()
finally:
    if image is not None:
        pdb.gimp_image_delete(image)
    with open(os.path.join(ROOT, "tests/e2e.json"), "wb") as stream:
        stream.write(json.dumps(report, indent=2))
