import importlib

mods = [
    "ultralytics",
    "onnx",
    "onnxruntime",
    "cv2",
    "pandas",
    "matplotlib",
    "PIL",
    "yaml",
    "tqdm",
    "psutil",
]

for name in mods:
    try:
        mod = importlib.import_module(name)
        print(name, getattr(mod, "__version__", "ok"))
    except Exception as exc:
        print(name, "MISSING", type(exc).__name__, exc)
