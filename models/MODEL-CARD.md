---
license: mit
library_name: transformers.js
pipeline_tag: image-segmentation
base_model: ZhengPeng7/BiRefNet_lite
datasets:
  - ZhengPeng7/DIS5K
inference: false
tags:
  - background-removal
  - matting
  - onnx
  - webgpu
  - birefnet
  - alpha-matting
  - image-matting
  - foreground-extraction
  - salient-object-detection
  - dichotomous-image-segmentation
  - client-side
  - transformers-js
  - fp16
---

# BiRefNet_lite 512×512 (browser-ready ONNX)

A 512×512 ONNX re-export of [ZhengPeng7/BiRefNet_lite](https://huggingface.co/ZhengPeng7/BiRefNet_lite) that actually runs in a browser — solving the OOM wall that blocks every 1024×1024 variant from loading in `onnxruntime-web`. Drop it in with [`@huggingface/transformers`](https://huggingface.co/docs/transformers.js) to get high-quality alpha mattes entirely client-side, with no server round-trip.

Used in production by [Repper](https://repper.app) for per-motif matte refinement during foreground extraction.

## Quickstart (transformers.js, WebGPU)

```ts
import { AutoModel, AutoProcessor, RawImage } from '@huggingface/transformers';

const model = await AutoModel.from_pretrained('studioludens/birefnet-lite-512', {
    dtype: 'fp16',     // or 'fp32'
    device: 'webgpu',  // falls back to 'wasm' on unsupported hardware
});
const processor = await AutoProcessor.from_pretrained('studioludens/birefnet-lite-512');

const image = await RawImage.read('https://example.com/photo.jpg');
const { pixel_values } = await processor(image);

const { logits } = await model({ input_image: pixel_values });
// Apply sigmoid, upscale back to original resolution, use as alpha matte.
```

## Why this repo exists — variant comparison

| Variant | Input res | Runtime | Works in browser? |
|---------|-----------|---------|-------------------|
| `ZhengPeng7/BiRefNet_lite` | 1024×1024 | PyTorch | — (not ONNX) |
| `onnx-community/BiRefNet_lite-ONNX` | 1024×1024 | ONNX | No (OOM) |
| **`studioludens/birefnet-lite-512` (this repo)** | **512×512** | **ONNX** | **Yes** |

The 1024×1024 ONNX variants — including `onnx-community/BiRefNet_lite-ONNX` — fail in every browser backend we tested:

| Backend | Variant | Failure |
|---------|---------|---------|
| WebGPU  | fp16, cascaded | `std::bad_alloc` during `OrtRun` |
| WebGPU  | fp32, cascaded | `unaligned accesses` |
| WASM    | fp32, cascaded | `std::bad_alloc` during `OrtRun` |
| WASM    | fp32, original | `std::bad_alloc` during `OrtRun` |

**Root cause:** BiRefNet_lite's decoder produces very large intermediate tensors at 1024×1024 (multi-scale feature maps with 1024-way concatenations). The `onnxruntime-web` WASM heap is hardcoded at ~2–4 GB and cannot be raised at runtime, so peak working-set exceeds available memory regardless of backend or precision.

Reducing to **512×512** shrinks intermediate tensors by 4×. At 512×512 the graph also naturally uses **max 7 storage buffers per shader stage**, comfortably inside WebGPU's `maxStorageBuffersPerShaderStage` limit (10 on older Apple Silicon adapters, 16 on Chrome ≥146), so no graph surgery is needed.

For crop-level matte refinement this is a fair trade: the crop is already small, and edge quality is indistinguishable from the 1024 reference in our tests.

## Variants

| File | Precision | Size |
|------|-----------|------|
| `onnx/model.onnx` | fp32 | 183 MB |
| `onnx/model_fp16.onnx` | fp16 | 94 MB |

`config.json` sets `transformers.js_config.dtype = "fp16"` by default. Override at load time if you want fp32.

## Input / output

- **Input:** RGB image, resized to **512×512**, ImageNet normalization (`mean = [0.485, 0.456, 0.406]`, `std = [0.229, 0.224, 0.225]`), rescale factor `1/255`. Layout `NCHW`, input tensor name `input_image`.
- **Output:** Single-channel logits at 512×512. **Apply `sigmoid` externally** to get the alpha matte in `[0, 1]`. Resize back to original image dimensions with bilinear interpolation.

The `preprocessor_config.json` uses `ViTFeatureExtractor`, so `AutoProcessor.from_pretrained(...)` works out of the box.

## How it was built

### Export toolchain (why it's tricky)

BiRefNet uses `torchvision.ops.deform_conv2d` (deformable convolution), which has no canonical ONNX symbolic. Exporting cleanly is the hard part, and every "obvious" path fails:

| PyTorch | Approach | Result |
|---------|----------|--------|
| 2.0.1 | `deform_conv2d_onnx_exporter` (unpatched) | `NoneType + int` — shape info not propagated |
| 2.1.2 | Same | Same error |
| 2.6.0 | Same | Same error |
| 2.6.0 | New `torch.onnx.dynamo_export` | `DispatchError: No ONNX function for deform_conv2d` |
| 2.6.0 | Simplified `Conv` symbolic (drop offset) | Export works but **62% pixel error** — unusable |

**The fix** is [Kazuhito00's patch to `deform_conv2d_onnx_exporter`](https://github.com/Kazuhito00/deform-conv2d-onnx-exporter) (`_get_tensor_dim_size` stride-based fallback), which only works against PyTorch 2.0.1's legacy tracer. Newer PyTorch versions route `deform_conv2d` through a different export path where the patch doesn't apply.

### Why Docker

Installing PyTorch 2.0.1 locally is painful — the matching wheels are EOL, `pip install torch==2.0.1` tends to pull a binary incompatible with current Python / glibc / macOS, and the surrounding `torchvision` / `transformers` pins are finicky. The reliable path is a pinned Docker image:

```
Python 3.10
torch==2.0.1
torchvision (compatible with 2.0.1)
transformers + deform-conv2d-onnx-exporter (Kazuhito00's patched version)
```

### Export recipe

```bash
# Build once
docker build -t birefnet-export ./docker/

# Mount HF cache and output dir, run export
docker run --rm \
  -v "$(pwd)/docker":/work \
  -v "$HOME/.cache/huggingface":/root/.cache/huggingface \
  birefnet-export python /work/export_512_patched.py
```

The export script:

1. Loads `ZhengPeng7/BiRefNet_lite` via `transformers.AutoModelForImageSegmentation`.
2. Applies Kazuhito00's patched `deform_conv2d_onnx_exporter` before calling `torch.onnx.export`.
3. Exports with `opset=17`, fixed 512×512 input shape, constant folding enabled.
4. Writes `model.onnx` (fp32, ~183 MB, 17,488 nodes, max 7 bindings, 80 GatherND ops).

fp16 is produced separately via `onnxruntime.transformers.float16.convert_float_to_float16` applied to the fp32 export.

### Validation

Pixel-by-pixel comparison against the PyTorch forward pass on reference images. The 512 export matches PyTorch exactly (zero pixel diff when both are resized to the same output resolution).

### What didn't work

- **Graph surgery on the 1024 model** — cascading Concat/Split ops into chains of ≤8 inputs/outputs passes the WebGPU binding-limit check, but the OOM is about intermediate tensor size, not binding count.
- **`onnxslim` optimization** — collapses cascaded ops back into the originals and inflates file size.
- **Newer PyTorch exporters** (2.1.x, 2.6.x dynamo) — all fail to produce correct `deform_conv2d`. PyTorch 2.0.1 is the working configuration.
- **WebNN** — Chrome-only, still behind a flag, `GatherND` support unconfirmed, and requires bypassing transformers.js.

## Differences from upstream BiRefNet_lite

- **Input resolution 512×512** instead of 1024×1024 (unblocks browser inference).
- **Correct `deform_conv2d` export** via patched exporter on PyTorch 2.0.1 — output matches PyTorch reference exactly.
- **fp16 variant** shipped alongside fp32.
- **No graph surgery** — not needed at 512×512.

For full-image matting at 1024×1024, prefer the upstream PyTorch model or server-side ONNX. This export is tuned for browser deployment.

## Limitations

- 512×512 input limits edge detail on large images — use on crops or smaller inputs for best results.
- Adapters with fewer than ~10 storage buffers per shader stage fall back to WASM; the model still runs, just slower.
- No INT8 quantization yet. A quantized variant could roughly halve the fp16 size but hasn't been validated.

## License

Everything in this repository — the ONNX weights (`onnx/model.onnx`, `onnx/model_fp16.onnx`), the config files and this model card — is released under the [MIT License](LICENSE). Commercial use, redistribution and modification are allowed, including serving the model files to run in your users' browsers.

The weights are a converted copy of [ZhengPeng7/BiRefNet_lite](https://huggingface.co/ZhengPeng7/BiRefNet_lite), which is itself MIT-licensed ([code](https://github.com/ZhengPeng7/BiRefNet/blob/main/LICENSE), [weights](https://huggingface.co/ZhengPeng7/BiRefNet_lite)). The only condition is that the copyright notice and permission text in [`LICENSE`](LICENSE) travel with any copy you redistribute:

```
Copyright (c) 2024 ZhengPeng
Copyright (c) 2026 Studio Ludens V.O.F.
```

## Citation

```bibtex
@article{zheng2024birefnet,
  title={Bilateral Reference for High-Resolution Dichotomous Image Segmentation},
  author={Zheng, Peng and Gao, Dehong and Fan, Deng-Ping and Liu, Li and Laaksonen, Jorma and Ouyang, Wanli and Sebe, Nicu},
  journal={CAAI Artificial Intelligence Research},
  year={2024}
}
```
