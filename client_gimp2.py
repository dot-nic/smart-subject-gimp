# -*- coding: utf-8 -*-
"""Thin gimpfu client; all GIMP API calls stay on the plugin main thread."""
from __future__ import division
import json
import os
import shutil
import subprocess
import tempfile
import time
from gimpfu import *

ROOT = os.path.dirname(os.path.abspath(__file__))
# Legacy PixelRgn exposes gamma-encoded Y' bytes even for linear coverage
# buffers. Encode alpha explicitly so 50% coverage remains 50% in GIMP.
def _encode_alpha(value):
    value = value / 255.0
    return int(round(255 * (12.92 * value if value <= .0031308 else 1.055 * value ** (1 / 2.4) - .055)))

def _decode_alpha(value):
    value = value / 255.0
    return int(round(255 * (value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4)))

ENCODE_ALPHA = ''.join(chr(_encode_alpha(value)) for value in range(256))
DECODE_ALPHA = [_decode_alpha(value) for value in range(256)]


def backend_command():
    executable = os.path.join(ROOT, "runtime", "python.exe" if os.name == "nt" else "bin/python")
    if not os.path.isfile(executable):
        raise RuntimeError("Falta el motor local. Ejecutar setup.ps1 dentro de smart-subject.")
    return [executable, os.path.join(ROOT, "backend", "engine.py")]


def run_inference(input_path, output_path, workspace):
    with open(os.path.join(ROOT, "config.json"), "rb") as stream:
        config = json.load(stream)
    status_path = os.path.join(workspace, "status.json")
    command = backend_command() + ["--in", input_path, "--out", output_path, "--status", status_path]
    environment = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH"):
        environment.pop(key, None)
    environment["PYTHONIOENCODING"] = "utf-8"
    kwargs = dict(env=environment, cwd=ROOT)
    if os.name == "nt":
        environment["PATH"] = os.path.join(ROOT, "runtime") + os.pathsep + os.path.join(environment.get("SystemRoot", "C:\\Windows"), "System32")
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    process = None
    started = time.time()
    with open(os.path.join(workspace, "backend.log"), "wb") as log:
        try:
            process = subprocess.Popen(command, stdout=log, stderr=log, **kwargs)
            while process.poll() is None:
                if time.time() - started > float(config["timeout_seconds"]):
                    raise RuntimeError("La inferencia supero el tiempo limite configurado.")
                try:
                    with open(status_path, "rb") as stream:
                        state = json.load(stream)
                    pdb.gimp_progress_set_text(state["message"].encode("utf-8"))
                    gimp.progress_update(.1 + .8 * float(state["progress"]))
                except (IOError, ValueError, KeyError):
                    pdb.gimp_progress_pulse()
                time.sleep(.15)
            if process.returncode != 0 or not os.path.isfile(output_path):
                with open(os.path.join(workspace, "backend.log"), "rb") as stream:
                    detail = stream.read()[-3000:].decode("utf-8", "replace")
                raise RuntimeError(u"El motor local fallo (codigo %s). %s" % (process.returncode, detail))
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()


def export_layer(drawable, filename):
    temporary = pdb.gimp_image_new(drawable.width, drawable.height, RGB)
    try:
        layer = pdb.gimp_layer_new_from_drawable(drawable, temporary)
        pdb.gimp_image_insert_layer(temporary, layer, None, 0)
        if layer.mask:
            pdb.gimp_layer_remove_mask(layer, MASK_DISCARD)
        pdb.gimp_layer_set_offsets(layer, 0, 0)
        pdb.gimp_layer_set_opacity(layer, 100)
        pdb.gimp_layer_set_mode(layer, NORMAL_MODE)
        pdb.gimp_item_set_visible(layer, True)
        pdb.gimp_file_save(temporary, layer, filename, filename, run_mode=RUN_NONINTERACTIVE)
    finally:
        pdb.gimp_image_delete(temporary)


def copy_mask_pixels(source, target, multiply=False):
    """64-row tiles keep Python 2 temporary allocations small."""
    width, height = target.width, target.height
    if (source.width, source.height) != (width, height):
        raise RuntimeError("La mascara no coincide con las dimensiones de la capa.")
    for y in range(0, height, 64):
        rows = min(64, height-y)
        data = source.get_pixel_rgn(0, y, width, rows, False, False)[0:width, y:y+rows]
        data = data[::source.bpp]
        region = target.get_pixel_rgn(0, y, width, rows, True, False)
        if multiply:
            existing = bytearray(region[0:width, y:y+rows])
            incoming = bytearray(data)
            for index in range(len(existing)):
                existing[index] = (DECODE_ALPHA[existing[index]] * incoming[index] + 127) // 255
            data = str(existing)
        data = data.translate(ENCODE_ALPHA)
        region[0:width, y:y+rows] = data
    target.flush()
    target.update(0, 0, width, height)


def apply_result(image, drawable, filename, as_mask):
    loaded = pdb.gimp_file_load(filename, filename, run_mode=RUN_NONINTERACTIVE)
    temporary_layer = None
    old_active = pdb.gimp_image_get_active_layer(image)
    pdb.gimp_image_undo_group_start(image)
    try:
        source = loaded.layers[0]
        if (source.width, source.height) != (drawable.width, drawable.height):
            raise RuntimeError("Dimensiones de mascara incorrectas")
        if as_mask:
            mask = drawable.mask
            if mask:
                copy_mask_pixels(source, mask, multiply=True)
            else:
                mask = pdb.gimp_layer_create_mask(drawable, ADD_BLACK_MASK)
                copy_mask_pixels(source, mask)
                pdb.gimp_layer_add_mask(drawable, mask)
            pdb.gimp_layer_set_apply_mask(drawable, True)
        else:
            # GIMP maps attached layer-mask coordinates to canvas coordinates,
            # including negative layer offsets and partially off-canvas layers.
            temporary_layer = pdb.gimp_layer_new(image, drawable.width, drawable.height,
                                                RGBA_IMAGE if image.base_type == RGB else GRAYA_IMAGE,
                                                "Smart Subject temporal", 100, NORMAL_MODE)
            pdb.gimp_image_insert_layer(image, temporary_layer, None, 0)
            pdb.gimp_layer_set_offsets(temporary_layer, *drawable.offsets)
            mask = pdb.gimp_layer_create_mask(temporary_layer, ADD_BLACK_MASK)
            copy_mask_pixels(source, mask)
            pdb.gimp_layer_add_mask(temporary_layer, mask)
            pdb.gimp_image_select_item(image, CHANNEL_OP_REPLACE, mask)
    finally:
        if temporary_layer is not None:
            pdb.gimp_image_remove_layer(image, temporary_layer)
        if old_active is not None:
            pdb.gimp_image_set_active_layer(image, old_active)
        pdb.gimp_image_undo_group_end(image)
        pdb.gimp_image_delete(loaded)


def execute(image, drawable, as_mask):
    if drawable is None or not pdb.gimp_item_is_layer(drawable) or pdb.gimp_item_is_group(drawable):
        raise RuntimeError("Selecciona una capa de pixeles, no un grupo ni una mascara.")
    workspace = tempfile.mkdtemp(prefix="gimp-smart-subject-")
    gimp.progress_init("Analizando imagen con IA local...")
    try:
        input_path = os.path.join(workspace, "input.png")
        output_path = os.path.join(workspace, "mask.png")
        export_layer(drawable, input_path)
        gimp.progress_update(.1)
        run_inference(input_path, output_path, workspace)
        pdb.gimp_progress_set_text("Aplicando resultado...")
        apply_result(image, drawable, output_path, as_mask)
        gimp.progress_update(1)
        gimp.displays_flush()
    finally:
        pdb.gimp_progress_end()
        shutil.rmtree(workspace, ignore_errors=True)


def select_subject(image, drawable):
    execute(image, drawable, False)


def mask_subject(image, drawable):
    execute(image, drawable, True)
