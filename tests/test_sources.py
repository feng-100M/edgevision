import cv2
import numpy as np
import pytest

def write_video(path,count=12,fps=10):
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"MJPG"),fps,(64,48))
    assert writer.isOpened()
    for i in range(count):
        writer.write(np.full((48,64,3),i*10,np.uint8))
    writer.release()

def test_file_source_has_repeatable_media_time(tmp_path):
    from edgevision.sources import VideoFileSource
    path=tmp_path/"input.avi";write_video(path)
    source=VideoFileSource(path,realtime=False)
    frames=list(source)
    assert len(frames)==12
    assert frames[3].source_time == pytest.approx(.3)
    assert frames[0].image.shape == (48,64,3)
    assert source.closed

def test_missing_video_reports_error(tmp_path):
    from edgevision.sources import VideoFileSource,SourceError
    with pytest.raises(SourceError):
        list(VideoFileSource(tmp_path/"missing.avi",realtime=False))

def test_rotation_180_corrects_frame_before_detection():
    from edgevision.sources import rotate_image
    image=np.arange(4*6*3,dtype=np.uint8).reshape(4,6,3)
    rotated=rotate_image(image,180)
    np.testing.assert_array_equal(rotated[0,0],image[-1,-1])
    np.testing.assert_array_equal(rotated[-1,-1],image[0,0])
    assert rotated.shape==image.shape

@pytest.mark.parametrize("rotation",[90,270])
def test_quarter_turn_swaps_frame_dimensions(rotation):
    from edgevision.sources import rotate_image
    assert rotate_image(np.zeros((4,6,3),np.uint8),rotation).shape==(6,4,3)

def test_horizontal_mirror_is_applied_after_rotation():
    from edgevision.sources import orient_image
    image=np.arange(4*6*3,dtype=np.uint8).reshape(4,6,3)
    corrected=orient_image(image,180,True)
    np.testing.assert_array_equal(corrected[0,-1],image[-1,-1])
    np.testing.assert_array_equal(corrected[-1,0],image[0,0])
    np.testing.assert_array_equal(orient_image(image,0,False),image)
