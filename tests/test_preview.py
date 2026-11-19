import json
import time
import urllib.request,urllib.error
import numpy as np
from edgevision.types import Frame,Detection

def read_stream_frame(response):
    assert response.readline().strip()==b"--frame"
    headers={}
    while True:
        line=response.readline().strip()
        if not line:break
        key,value=line.decode().split(":",1);headers[key.lower()]=value.strip()
    body=response.read(int(headers["content-length"]))
    assert response.read(2)==b"\r\n"
    assert body.startswith(b"\xff\xd8")
    return int(headers["x-sequence"]),body

def push(preview,seq):
    preview.update(Frame(seq,time.monotonic(),np.full((40,60,3),seq%256,np.uint8),"stream"),
                   [],[],[],[(10,0),(50,0),(50,39),(10,39)],{"processed_frames":seq,"events":0})

def test_mjpeg_stream_delivers_new_frames_without_polling():
    from edgevision.preview import PreviewServer
    preview=PreviewServer(port=0)
    try:
        push(preview,1)
        with urllib.request.urlopen(preview.url+"/stream.mjpg",timeout=2) as response:
            assert response.headers.get_content_type()=="multipart/x-mixed-replace"
            assert read_stream_frame(response)[0]==1
            for seq in range(2,50):push(preview,seq)
            seen=[]
            while not seen or seen[-1]!=49:
                seen.append(read_stream_frame(response)[0])
                assert len(seen)<=3
            assert all(a<b for a,b in zip([1]+seen,seen))
    finally:preview.close()

def test_preview_encoding_does_not_block_detector_thread(monkeypatch):
    from edgevision.preview import PreviewServer
    import cv2,threading
    entered=threading.Event();finish=threading.Event();original=cv2.imencode
    def blocked_encode(*args):
        entered.set();assert finish.wait(2)
        return original(*args)
    preview=PreviewServer(port=0)
    monkeypatch.setattr(cv2,"imencode",blocked_encode)
    try:
        start=time.monotonic();push(preview,1)
        assert time.monotonic()-start<.2
        assert entered.wait(1)
    finally:finish.set();preview.close()

def test_stream_preview_limits_bandwidth_without_changing_aspect_ratio():
    from edgevision.preview import PreviewServer
    import cv2
    preview=PreviewServer(port=0)
    try:
        image=np.zeros((720,1280,3),np.uint8)
        preview.update(Frame(1,time.monotonic(),image,"wide"),[],[],[],
                       [(0,0),(1279,0),(1279,719),(0,719)],{})
        with urllib.request.urlopen(preview.url+"/stream.mjpg",timeout=2) as stream:
            _,jpeg=read_stream_frame(stream)
        picture=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
        assert picture.shape==(270,480,3)
        assert image.shape==(720,1280,3)
    finally:preview.close()

def test_preview_exposes_only_live_frame_and_status():
    from edgevision.preview import PreviewServer
    preview=PreviewServer(port=0)
    try:
        assert preview.url.startswith("http://127.0.0.1:")
        preview.update(Frame(1,time.monotonic(),np.zeros((40,60,3),np.uint8),"test"),
                       [Detection(10,5,30,35,.9)],[],[],
                       [(20,0),(59,0),(59,39),(20,39)],{"processed_frames":1,"events":0})
        status=json.load(urllib.request.urlopen(preview.url+"/status",timeout=2))
        assert status["seq"]==1 and status["detections"]==1
        deadline=time.monotonic()+2
        while True:
            try:
                raw=urllib.request.urlopen(preview.url+"/frame.jpg",timeout=2).read();break
            except urllib.error.HTTPError as exc:
                if exc.code!=503 or time.monotonic()>deadline:raise
                time.sleep(.01)
        assert raw.startswith(b"\xff\xd8")
        try:
            urllib.request.urlopen(preview.url+"/../config.local.yaml",timeout=2)
            assert False,"Preview must never serve filesystem paths"
        except urllib.error.HTTPError as exc:
            assert exc.code==404
    finally:
        preview.close()

def test_preview_stop_controls_only_current_pipeline():
    from edgevision.preview import PreviewServer
    import threading
    stopped=threading.Event()
    preview=PreviewServer(port=0,on_stop=stopped.set)
    try:
        request=urllib.request.Request(preview.url+"/stop",data=b"",method="POST")
        urllib.request.urlopen(request,timeout=2).read()
        assert stopped.wait(1)
    finally:
        preview.close()

def test_history_snapshot_and_mqtt_status_are_readable_after_restart(tmp_path):
    from edgevision.preview import PreviewServer
    from edgevision.storage import EventStorage
    from edgevision.types import Event
    import pytest
    store = EventStorage(tmp_path, min_free_bytes=0)
    event = Event('saved', 'person_entered', '2026-10-29T08:50:54Z', .9,
                  'door', (1,2,20,30), None, 'camera', 3)
    store.save(event, np.zeros((40,40,3),np.uint8))
    preview = PreviewServer(port=0, event_store=EventStorage(tmp_path, min_free_bytes=0),
                            mqtt_status=lambda: {'state':'connected', 'acknowledged':2})
    try:
        status = json.load(urllib.request.urlopen(preview.url+'/status', timeout=2))
        assert status['mqtt']['acknowledged'] == 2
        history = json.load(urllib.request.urlopen(preview.url+'/events', timeout=2))
        assert history['events'][0]['event_id'] == 'saved'
        data = urllib.request.urlopen(preview.url+'/snapshots/saved', timeout=2).read()
        assert data.startswith(bytes([255,216]))
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(preview.url+'/snapshots/missing', timeout=2)
        assert missing.value.code == 404
        with pytest.raises(urllib.error.HTTPError) as unsafe:
            urllib.request.urlopen(preview.url+'/snapshots/..%2Fconfig.local.yaml', timeout=2)
        assert unsafe.value.code == 404
    finally:
        preview.close()

def test_history_storage_failure_is_visible_and_does_not_stop_preview():
    from edgevision.preview import PreviewServer
    from edgevision.storage import StorageError
    import pytest
    class BrokenStore:
        def recent_events(self, limit=50):
            raise StorageError('injected failure')
    preview = PreviewServer(port=0, event_store=BrokenStore())
    try:
        with pytest.raises(urllib.error.HTTPError) as failed:
            urllib.request.urlopen(preview.url+'/events', timeout=2)
        assert failed.value.code == 503
        assert json.loads(failed.value.read())['error']
        assert urllib.request.urlopen(preview.url+'/', timeout=2).status == 200
    finally:
        preview.close()

def test_dashboard_page_and_script_are_served_as_packaged_resources():
    from edgevision.preview import PreviewServer
    preview = PreviewServer(port=0)
    try:
        page = urllib.request.urlopen(preview.url+'/', timeout=2).read().decode('utf-8')
        assert 'MQTT 告警通道' in page
        assert '已保存的历史事件' in page
        script = urllib.request.urlopen(preview.url+'/dashboard.js', timeout=2).read().decode('utf-8')
        assert 'Asia/Shanghai' in script
    finally:
        preview.close()
def test_live_status_tracks_delayed_snapshot_after_last_frame(tmp_path):
    import json
    import time
    import urllib.request
    import numpy as np
    from edgevision.preview import PreviewServer
    from edgevision.types import Frame
    from test_storage import event
    preview = PreviewServer(port=0)
    try:
        record = event("delayed")
        frame = Frame(0, time.monotonic(), np.zeros((20, 20, 3), np.uint8), "test")
        preview.update(frame, [], [], [record], [(0,0),(10,0),(10,10)], {})
        record.snapshot_path = "2026-11-18/delayed.jpg"
        with urllib.request.urlopen(preview.url + "/status", timeout=2) as response:
            assert json.load(response)["recent_events"][0]["snapshot_path"] == record.snapshot_path
    finally:
        preview.close()
