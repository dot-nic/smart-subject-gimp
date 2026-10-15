#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GIMP 2.10 entry point; keep this file named like its containing folder."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gimpfu import *
from client_gimp2 import select_subject, mask_subject

PARAMS = [(PF_IMAGE, "image", "Imagen", None),
          (PF_DRAWABLE, "drawable", "Capa activa", None)]

register("python-fu-smart-subject-select", "Seleccionar sujeto con IA local",
         "BiRefNet local; genera una seleccion suave sin modificar la capa.",
         "Smart Subject contributors", "MIT", "2026", "Sujeto (IA local)...",
         "RGB*, GRAY*", PARAMS, [], select_subject, menu="<Image>/Select")

register("python-fu-smart-subject-mask", "Mascara de sujeto con IA local",
         "Crea una mascara no destructiva. Si existe, combina ambas mascaras.",
         "Smart Subject contributors", "MIT", "2026", "Máscara de Sujeto (IA)...",
         "RGB*, GRAY*", PARAMS, [], mask_subject, menu="<Image>/Layer/Mask",
         on_query=lambda: gimp.menu_register("python-fu-smart-subject-mask", "<Layers>/Mask"))

main()
