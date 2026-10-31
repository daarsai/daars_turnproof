from pathlib import Path

from turnproof.perception.sam_parse import iou, largest, parse

FIX = Path(__file__).parent.parent / "fixtures" / "sam"


def test_parse_image_vehicle_fixture():
    dets = parse((FIX / "image_vehicle.txt").read_text())
    assert list(dets) == [0]
    objs = dets[0]
    assert len(objs) == 11
    first = objs[0]
    assert (first.x1, first.y1, first.x2, first.y2) == (560, 184, 629, 269)
    assert (first.w, first.h) == (1280, 516)
    assert abs(first.c - 0.8987) < 1e-3
    # ordinal 5 is the aircraft itself, mis-labelled as a vehicle; it is the largest box
    assert largest(objs).ordinal == 5


def test_parse_video_fixture_has_consecutive_frames():
    dets = parse((FIX / "video_aircraft_head.txt").read_text())
    frames = sorted(dets)
    assert frames[:3] == [0, 1, 2]
    assert all(len(dets[f]) >= 1 for f in frames)
    b = dets[0][0]
    assert (b.x1, b.y1, b.x2, b.y2) == (392, 0, 1267, 363)


def test_parse_out_of_order_and_no_confidence():
    txt = "<3f>0<|box;x1=1;y1=2;x2=5;y2=6;w=10;h=10|>,1<|box;x1=0;y1=0;x2=1;y2=1;w=10;h=10|>\n<1f>0<|box;x1=2;y1=2;x2=4;y2=4;w=10;h=10;c=0.5|>"
    d = parse(txt)
    assert sorted(d) == [1, 3]
    assert d[3][0].c is None and d[3][1].ordinal == 1
    assert d[1][0].c == 0.5


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == 1 / 3
    assert iou((0, 0, 1, 1), (5, 5, 6, 6)) == 0.0
