from ultralytics import YOLO

# 1. Load your trained custom model
model = YOLO("best_crowdd.pt")

# 2. Export the model to ONNX format
# Setting dynamic=True allows the model to accept different image batch sizes later
success = model.export(format="onnx", dynamic=True) 

print("Export complete:", success)
