"""Replace expanded deformable convolutions with ONNX native DeformConv.

Weights remain byte-for-byte identical. Requires ONNX Runtime >=1.25.
Development dependency: onnx==1.18.0. Does not run during inference.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "build-libs"))
import onnx
from onnx import helper


def optimize(source, target):
    model = onnx.load(source)
    nodes = list(model.graph.node)
    names = {node.name: node for node in nodes}
    prefixes = [node.name.rsplit("/offset_conv/Conv", 1)[0] for node in nodes
                if node.name.endswith("/atrous_conv/offset_conv/Conv")]
    replacements = {}
    removed = set()
    for prefix in prefixes:
        offset = names[prefix + "/offset_conv/Conv"]
        regular = names[prefix + "/Conv"]
        modulation = names[prefix + "/Mul"]
        attrs = {attr.name: helper.get_attribute_value(attr) for attr in offset.attribute}
        weights = next(weight for weight in model.graph.initializer if weight.name == regular.input[1])
        # The expanded export's final Conv has stride==kernel_size; the true
        # deformation samples at the same geometry as its offset convolution.
        native = helper.make_node("DeformConv", [offset.input[0], regular.input[1], offset.output[0], "", modulation.output[0]],
                                  list(regular.output), name=prefix+"/NativeDeformConv",
                                  kernel_shape=list(weights.dims[2:]), pads=attrs["pads"],
                                  strides=attrs["strides"], dilations=attrs["dilations"], group=1, offset_group=1)
        replacements[regular.name] = native
        preserve = {offset.name, prefix+"/modulator_conv/Conv", prefix+"/Sigmoid", prefix+"/Constant", modulation.name,
                    prefix+"/Add_3", prefix+"/Constant_48"}
        # Preserve bias addition by tracing its constant, rather than relying on
        # constant numbering (which differs with each export).
        final = names.get(prefix+"/Add_3")
        if final:
            producers = {value: node.name for node in nodes for value in node.output}
            preserve.update(producers[value] for value in final.input if value in producers and value != regular.output[0])
        for node in nodes:
            if node.name.startswith(prefix+"/") and node.name not in preserve and node.name != regular.name:
                removed.add(node.name)
    transformed = [replacements.get(node.name, node) for node in nodes if node.name not in removed]
    # Remove dead nodes and initializers by traversing backward from graph outputs.
    producers = {value: node for node in transformed for value in node.output}
    needed, visited, kept = set(), set(), []
    def visit(value):
        needed.add(value)
        node = producers.get(value)
        if node is None or node.name in visited:
            return
        visited.add(node.name)
        for dependency in node.input:
            visit(dependency)
        kept.append(node)
    sys.setrecursionlimit(10000)
    for output in model.graph.output:
        visit(output.name)
    del model.graph.node[:]
    model.graph.node.extend(kept)
    kept_initializers = [value for value in model.graph.initializer if value.name in needed]
    del model.graph.initializer[:]
    model.graph.initializer.extend(kept_initializers)
    # Constant nodes do not need runtime graph scheduling or shape propagation.
    # Store their tensors directly as initializers without changing their bytes.
    executable = []
    for node in model.graph.node:
        if node.op_type == "Constant" and len(node.attribute) == 1 and node.attribute[0].name == "value":
            tensor = onnx.TensorProto()
            tensor.CopyFrom(node.attribute[0].t)
            tensor.name = node.output[0]
            model.graph.initializer.append(tensor)
        else:
            executable.append(node)
    del model.graph.node[:]
    model.graph.node.extend(executable)
    del model.graph.value_info[:]
    model.opset_import[0].version = 22
    onnx.checker.check_model(model)
    onnx.save(model, target)
    return {"native_deform_convolutions": len(prefixes), "bytes": Path(target).stat().st_size,
            "sha256": hashlib.sha256(Path(target).read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("target")
    args = parser.parse_args()
    print(json.dumps(optimize(args.source, args.target), indent=2))
