# YOLOv8n-320 Evaluation and ONNX Export

PT: `C:\Users\Heda\Desktop\index\ai\export\best.pt`

ONNX: `C:\Users\Heda\Desktop\index\ai\export\best.onnx`

ONNX size: **11.554 MB**

Validation: `{"precision": 0.8637453901016711, "recall": 0.8414688463275721, "map50": 0.8389766471699489, "map50_95": 0.4605540563977451, "speed_ms": {"preprocess": 0.24813847619043372, "inference": 0.8660609523812604, "loss": 0.0003523809521409151, "postprocess": 0.8202165714296175}}`

Local CPU benchmark: `{"min": 6.8755999999439155, "mean": 12.644354237297302, "median": 11.308900000017275, "p95": 21.44708999996965, "max": 33.65720000010697}`

Input: `{'name': 'images', 'shape': [1, 3, 320, 320], 'type': 'tensor(float)'}`

Output: `{'name': 'output0', 'shape': [1, 8, 2100], 'type': 'tensor(float)'}`
