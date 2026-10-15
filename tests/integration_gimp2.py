# -*- coding: utf-8 -*-
"""Integration assertions run INSIDE real GIMP 2.10."""
from gimpfu import *
import hashlib
import json
import os
import sys
import time
import traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import client_gimp2 as client
report = {"gimp_version": gimp.version, "checks": []}


def check(condition, name):
    if not condition:
        raise AssertionError(name)
    report["checks"].append(name)


def pixels(drawable):
    return drawable.get_pixel_rgn(0, 0, drawable.width, drawable.height, False, False)[:,:]


def test_import(base, offsets):
    image = pdb.gimp_image_new(100, 90, base)
    try:
        layer = pdb.gimp_layer_new(image, 64, 48, RGBA_IMAGE if base == RGB else GRAYA_IMAGE, "Prueba", 100, NORMAL_MODE)
        pdb.gimp_image_insert_layer(image, layer, None, 0)
        pdb.gimp_drawable_fill(layer, WHITE_FILL)
        pdb.gimp_layer_set_offsets(layer, *offsets)
        before = pixels(layer)
        path = os.path.join(ROOT, "tests", "fixtures", "gradient.png")
        client.apply_result(image, layer, path, False)
        check(not pdb.gimp_selection_is_empty(image), "seleccion creada %s %s" % (base, offsets))
        check(len(image.layers) == 1 and layer.mask is None, "sin capas temporales %s %s" % (base, offsets))
        check(pixels(layer) == before, "pixeles originales intactos %s %s" % (base, offsets))
        check(pdb.gimp_image_get_active_layer(image) == layer, "capa activa conservada")
        # Fixture pixel (30,20) has 128 coverage. GIMP returns selection in canvas coordinates.
        x, y = 30+offsets[0], 20+offsets[1]
        report["selection_debug"] = {"bounds": pdb.gimp_selection_bounds(image), "value_at_offset": pdb.gimp_selection_value(image,x,y), "value_without_offset": pdb.gimp_selection_value(image,30,20)}
        check(abs(pdb.gimp_selection_value(image, x, y)-128) <= 1, "seleccion suave con offsets")
        selected = pixels(pdb.gimp_image_get_selection(image))
        client.apply_result(image, layer, path, True)
        check(layer.mask is not None, "mascara creada")
        check(abs(client.DECODE_ALPHA[ord(pixels(layer.mask)[20*64+30])]-128) <= 1, "mascara suave")
        check(pixels(pdb.gimp_image_get_selection(image)) == selected, "seleccion previa preservada")
        client.apply_result(image, layer, path, True)
        check(abs(client.DECODE_ALPHA[ord(pixels(layer.mask)[20*64+30])]-64) <= 1, "mascara existente combinada")
        check(pixels(layer) == before, "mascara no destructiva")
        check(pdb.gimp_layer_get_apply_mask(layer), "mascara activada")
        exported = os.path.join(ROOT, "tests", "exported.png")
        client.export_layer(layer, exported)
        check(os.path.getsize(exported) > 0, "exportacion PNG aislada")
    finally:
        pdb.gimp_image_delete(image)


try:
    check(pdb.gimp_procedural_db_proc_exists("python-fu-smart-subject-select"), "comando seleccionar registrado")
    check(pdb.gimp_procedural_db_proc_exists("python-fu-smart-subject-mask"), "comando mascara registrado")
    for base, offsets in [(RGB, (11, 9)), (RGB, (-7, -5)), (GRAY, (5, 7))]:
        test_import(base, offsets)
    report["ok"] = True
except Exception:
    report["ok"] = False
    report["error"] = traceback.format_exc()
finally:
    with open(os.path.join(ROOT, "tests", "integration.json"), "wb") as stream:
        stream.write(json.dumps(report, indent=2))
