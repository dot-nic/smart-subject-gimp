"""Offline constant folding with ORT; compact FP16 storage with FP32 casts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "build-libs"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime/Lib/site-packages"))
import onnx
from onnx import helper, numpy_helper, TensorProto
import onnxruntime as ort
import numpy as np

source, target = Path(sys.argv[1]), Path(sys.argv[2])
intermediate = target.with_suffix(".fp32.tmp.onnx")
options = ort.SessionOptions()
options.intra_op_num_threads = 4
options.log_severity_level = 3
options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
options.optimized_model_filepath = str(intermediate)
session = ort.InferenceSession(str(source), sess_options=options, providers=["CPUExecutionProvider"])
del session
model = onnx.load(intermediate)
casts = []
for tensor in model.graph.initializer:
    if tensor.data_type == TensorProto.FLOAT and len(tensor.dims) >= 1:
        original = tensor.name
        values = numpy_helper.to_array(tensor)
        compact = values.astype(np.float16)
        # Casts retain exact weights; leave folded parameters in FP32 when half
        # storage would round them or overflow them.
        if not np.array_equal(values, compact.astype(np.float32)):
            continue
        tensor.CopyFrom(numpy_helper.from_array(compact, name=original + ".stored_fp16"))
        casts.append(helper.make_node("Cast", [tensor.name], [original], to=TensorProto.FLOAT,
                                      name=original + ".restore_fp32"))
nodes = list(model.graph.node)
del model.graph.node[:]
model.graph.node.extend(casts + nodes)
del model.graph.value_info[:]
onnx.checker.check_model(model)
onnx.save(model, target)
intermediate.unlink()
print("compact_model_bytes", target.stat().st_size, "stored_fp16_tensors", len(casts))
