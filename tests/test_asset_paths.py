import hashlib
import io
import pytest

def test_partial_download_symlink_cannot_overwrite_another_file(tmp_path,monkeypatch):
    import edgevision.assets as assets
    root=tmp_path/"project";root.mkdir()
    outside=tmp_path/"outside";outside.write_bytes(b"preserve")
    partial=root/"sample.bin.part"
    try:
        partial.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation unavailable in this Windows account")
    data=b"asset"
    monkeypatch.setattr(assets,"ASSETS",{"sample.bin":("https://test",hashlib.sha256(data).hexdigest())})
    monkeypatch.setattr(assets.urllib.request,"urlopen",lambda *args,**kw:io.BytesIO(data))
    assets.download_assets(root)
    assert outside.read_bytes()==b"preserve"
