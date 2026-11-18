import pytest

def test_asset_downloads_require_hash_verification(tmp_path):
    import pytest
    from edgevision.assets import verify
    p=tmp_path/"model";p.write_bytes(b"corrupted")
    with pytest.raises(ValueError,match="SHA-256"):
        verify(p,"0"*64)

def test_derived_model_must_match_registered_hash(tmp_path):
    import json,hashlib
    from edgevision.assets import verify_model,ASSETS
    folder=tmp_path/"models";folder.mkdir()
    model=folder/"yolox_nano_320.onnx";model.write_bytes(b"derived-model")
    digest=hashlib.sha256(model.read_bytes()).hexdigest()
    (folder/"manifest.json").write_text(json.dumps({"variants":{"models/yolox_nano_320.onnx":{
        "sha256":digest,"base_sha256":ASSETS["models/yolox_nano.onnx"][1]}}}))
    assert verify_model(model,tmp_path)==digest
    model.write_bytes(b"corrupted")
    with pytest.raises(ValueError,match="SHA-256"):verify_model(model,tmp_path)

def test_unregistered_model_is_not_reported_as_verified(tmp_path):
    from edgevision.assets import verify_model
    p=tmp_path/"model.onnx";p.write_bytes(b"unregistered")
    with pytest.raises(ValueError,match="registered"):
        verify_model(p,tmp_path)
