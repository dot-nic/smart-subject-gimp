"""Offline ONNX facade. No network imports or automatic downloads."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
_job_handle = None


def limit_memory(megabytes):
    """Hard limit on process committed memory (Windows) / address space (POSIX)."""
    global _job_handle
    size = int(megabytes) * 1024 * 1024
    if os.name == "nt":
        import ctypes as c
        from ctypes import wintypes as w

        class BASIC(c.Structure):
            _fields_ = [("PerProcessUserTimeLimit", c.c_int64), ("PerJobUserTimeLimit", c.c_int64),
                        ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", c.c_size_t),
                        ("MaximumWorkingSetSize", c.c_size_t), ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", c.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

        class IO(c.Structure):
            _fields_ = [(name, c.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount",
                       "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class EXTENDED(c.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO),
                        ("ProcessMemoryLimit", c.c_size_t), ("JobMemoryLimit", c.c_size_t),
                        ("PeakProcessMemoryUsed", c.c_size_t), ("PeakJobMemoryUsed", c.c_size_t)]

        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel.GetCurrentProcess.restype = w.HANDLE
        handle = kernel.CreateJobObjectW(None, None)
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.ProcessMemoryLimit = size
        if not handle or not kernel.SetInformationJobObject(handle, 9, c.byref(info), c.sizeof(info)):
            raise OSError(c.get_last_error(), "No se pudo configurar el limite de memoria")
        if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
            raise OSError(c.get_last_error(), "No se pudo aplicar el limite de memoria")
        _job_handle = handle  # retain until process exit
    else:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (size, size))


def peak_memory_mb():
    if os.name != "nt":
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak / (1024 * 1024 if sys.platform == "darwin" else 1024)
    import ctypes as c
    from ctypes import wintypes as w

    class COUNTERS(c.Structure):
        _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + [
            (name, c.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
            "PagefileUsage", "PeakPagefileUsage")]
    counters = COUNTERS()
    counters.cb = c.sizeof(counters)
    kernel = c.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = w.HANDLE
    psapi = c.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, c.c_void_p, w.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), c.byref(counters), counters.cb):
        return None
    return round(counters.PeakWorkingSetSize / 1048576, 2)


def status(path, progress, message, **extra):
    data = dict(progress=progress, message=message, **extra)
    if path:
        target = Path(path)
        temporary = target.with_suffix(".writing")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)
    return data


class BiRefNetAdapter:
    def __init__(self, model, threads):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        options.log_severity_level = 3
        self.session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0]
        shape = self.input.shape
        if len(shape) != 4 or shape[1] != 3:
            raise ValueError("El modelo debe tener entrada NCHW RGB")
        self.size = (shape[3] if isinstance(shape[3], int) else 512,
                     shape[2] if isinstance(shape[2], int) else 512)

    def predict(self, image):
        import numpy as np
        from PIL import Image
        rgb = image.convert("RGBA")
        # Transparent pixels have no semantic content; composite against white.
        background = Image.new("RGBA", rgb.size, (255, 255, 255, 255))
        background.alpha_composite(rgb)
        small = background.convert("RGB").resize(self.size, Image.Resampling.BILINEAR)
        array = np.asarray(small, dtype=np.float32) / 255.0
        array = (array - np.array([.485, .456, .406], dtype=np.float32)) / np.array([.229, .224, .225], dtype=np.float32)
        dtype = np.float16 if self.input.type == "tensor(float16)" else np.float32
        tensor = np.ascontiguousarray(array.transpose(2, 0, 1)[None], dtype=dtype)
        logits = self.session.run(None, {self.input.name: tensor})[-1]
        logits = np.asarray(logits, dtype=np.float32).squeeze()
        if logits.ndim != 2 or not np.isfinite(logits).all():
            raise ValueError("Salida ONNX invalida")
        alpha = 1.0 / (1.0 + np.exp(-np.clip(logits, -80, 80)))
        mask = Image.fromarray(np.round(alpha * 255).astype(np.uint8)).resize(image.size, Image.Resampling.BILINEAR)
        # Selection cannot include fully transparent source pixels. Partial source
        # alpha is deliberately not multiplied: GIMP applies it separately.
        if "A" in image.getbands():
            from PIL import ImageChops
            coverage = image.getchannel("A").point(lambda value: 255 if value else 0)
            mask = ImageChops.multiply(mask, coverage)
        return mask


def load_config():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if not 1 <= int(config["memory_limit_mb"]) <= 2048:
        raise ValueError("memory_limit_mb debe estar entre 1 y 2048")
    if not 1 <= int(config["threads"]) <= 32:
        raise ValueError("threads debe estar entre 1 y 32")
    model = (ROOT / config["model"]).resolve()
    if ROOT not in model.parents:
        raise ValueError("El modelo debe estar dentro del modulo")
    if not model.is_file():
        raise FileNotFoundError("Falta el modelo. Ejecutar setup.ps1")
    return config, model


def run_inference(input_path, output_path, status_path=None):
    from PIL import Image
    config, model = load_config()
    limit_memory(config["memory_limit_mb"])
    started = time.perf_counter()
    status(status_path, .1, "Cargando modelo local...")
    with Image.open(input_path) as source:
        if source.width * source.height > config["max_pixels"]:
            raise ValueError("Imagen demasiado grande para el limite de memoria configurado")
        image = source.copy()
    adapter = BiRefNetAdapter(model, config["threads"])
    loaded = time.perf_counter()
    status(status_path, .3, "Analizando imagen...")
    mask = adapter.predict(image)
    status(status_path, .9, "Guardando mascara...")
    target = Path(output_path)
    temporary = target.with_suffix(".writing")
    try:
        mask.save(temporary, format="PNG")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return status(status_path, 1, "Finalizado", seconds=round(time.perf_counter()-started, 3),
                  load_seconds=round(loaded-started, 3), peak_rss_mb=peak_memory_mb(), size=list(mask.size))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="input")
    parser.add_argument("--out", dest="output")
    parser.add_argument("--status")
    parser.add_argument("--doctor", action="store_true")
    args = parser.parse_args()
    try:
        if args.doctor:
            import hashlib
            config, model = load_config()
            manifest = json.loads((ROOT / "models/manifest.json").read_text(encoding="utf-8"))
            with model.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != manifest["sha256"]:
                raise ValueError("El modelo no coincide con el SHA-256 del manifiesto")
            limit_memory(config["memory_limit_mb"])
            adapter = BiRefNetAdapter(model, config["threads"])
            print(json.dumps(dict(ok=True, model=model.name, input_size=adapter.size,
                                  input_type=adapter.input.type, providers=adapter.session.get_providers(),
                                  peak_rss_mb=peak_memory_mb())))
        else:
            if not args.input or not args.output:
                parser.error("se requieren --in y --out")
            print(json.dumps(run_inference(args.input, args.output, args.status)))
        return 0
    except Exception as error:
        message = "%s: %s" % (type(error).__name__, error)
        status(args.status, 0, message, error=True)
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
