"""PC-side conversion of the pinned fully convolutional model; weights are unchanged."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from edgevision.assets import ASSETS,verify

def build(size):
    root=Path(__file__).resolve().parents[1]
    base=root/"models/yolox_nano.onnx"
    digest=ASSETS["models/yolox_nano.onnx"][1];verify(base,digest)
    original=onnx.load(base);model=onnx.ModelProto();model.CopyFrom(original)
    anchors=sum((size//stride)**2 for stride in (8,16,32))
    for index in (2,3):model.graph.input[0].type.tensor_type.shape.dim[index].dim_value=size
    model.graph.output[0].type.tensor_type.shape.dim[1].dim_value=anchors
    del model.graph.value_info[:]
    model=onnx.shape_inference.infer_shapes(model);onnx.checker.check_model(model)
    assert len(original.graph.initializer)==len(model.graph.initializer)
    assert all(a.SerializeToString()==b.SerializeToString() for a,b in zip(original.graph.initializer,model.graph.initializer))
    path=root/f"models/yolox_nano_{size}.onnx"
    assert path.resolve().is_relative_to(root) and not path.is_symlink()
    onnx.save(model,path)
    options=ort.SessionOptions();options.intra_op_num_threads=2
    session=ort.InferenceSession(str(path),sess_options=options,providers=["CPUExecutionProvider"])
    output=session.run(None,{"images":np.zeros((1,3,size,size),np.float32)})[0]
    assert output.shape==(1,anchors,85) and np.isfinite(output).all()
    entry={"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"base_sha256":digest,
        "input_shape":[1,3,size,size],"output_shape":[1,anchors,85],"weights_unchanged":True,
        "transformation":"fixed spatial dimensions and inferred shape metadata; no retraining or quantization",
        "generator":"scripts/build_fast_model.py","onnx_version":onnx.__version__}
    manifest=root/"models/manifest.json"
    assert not manifest.is_symlink()
    data=json.loads(manifest.read_text(encoding="utf-8"))
    data.setdefault("variants",{})[path.relative_to(root).as_posix()]=entry
    manifest.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"model":path.name,**entry},indent=2))

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size",type=int,choices=(320,352),default=320)
    build(parser.parse_args().size)
