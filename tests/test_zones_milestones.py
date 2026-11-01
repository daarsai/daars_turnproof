from turnproof.events.milestones import detect
from turnproof.zones.aircraft_zones import all_zones, overlap_ratio, zone_from_aircraft

CFG = {
    "aft_hold": {"x0": 0.6, "x1": 0.9, "y0": 0.5, "y1": 1.0, "pad_out": 0.5},
    "forward_hold": {"x0": 0.1, "x1": 0.4, "y0": 0.5, "y1": 1.0, "pad_out": 0.5},
}


def test_zone_fractions_and_padding():
    z = zone_from_aircraft((100, 100, 300, 200), CFG["aft_hold"])
    assert z == (220, 150, 280, 250)  # pad_out 0.5 * h(100) extends below


def test_nose_right_mirrors_x():
    z = zone_from_aircraft((0, 0, 100, 100), CFG["aft_hold"], nose_right=True)
    assert (round(z[0], 6), round(z[2], 6)) == (10, 40)


def test_overlap_ratio():
    zone = (0, 0, 100, 100)
    assert overlap_ratio((50, 50, 150, 150), zone) == 0.25
    assert overlap_ratio((200, 200, 210, 210), zone) == 0.0
    assert overlap_ratio((10, 10, 20, 20), zone) == 1.0


def test_all_zones_names():
    assert set(all_zones((0, 0, 10, 10), CFG)) == {"aft_hold", "forward_hold"}


def test_milestones_with_hysteresis():
    # 3 noisy frames inside (not enough), then 6 inside -> docked at first of those 6
    s = [(i, 0.0, 0.9) for i in range(4)]
    s += [(4, 0.5, 0.9), (5, 0.5, 0.9), (6, 0.5, 0.9), (7, 0.0, 0.9)]  # blip, resets
    s += [(i, 0.6, 0.95) for i in range(8, 14)]  # 6 inside -> docked at 8
    s += [(i, 0.6, 0.95) for i in range(14, 30)]
    s += [(i, 0.1, 0.8) for i in range(30, 36)]  # 6 outside -> complete at 30
    hits, cycles = detect(s, tau=0.3, min_docked=6, min_undocked=6)
    assert len(cycles) == 1
    assert [(h.name, h.frame_index) for h in hits] == [
        ("loader_docked_start", 8),
        ("loading_complete", 30),
    ]


def test_no_milestone_if_never_docked():
    assert detect([(i, 0.1, 0.9) for i in range(50)], 0.3, 6, 6) == ([], [])


def test_flicker_is_merged_and_longest_cycle_wins():
    s = []
    s += [(i, 0.6, 0.9) for i in range(30)]  # docked (present at start)
    s += [(i, 0.0, 0.0) for i in range(30, 38)]  # 8-frame flicker gap (< merge_gap 10)
    s += [(i, 0.6, 0.9) for i in range(38, 60)]  # docked again
    s += [(i, 0.0, 0.0) for i in range(60, 80)]  # real departure
    s += [(i, 0.6, 0.5) for i in range(80, 88)]  # short second visit (shorter cycle)
    s += [(i, 0.0, 0.0) for i in range(88, 100)]
    hits, cycles = detect(s, 0.3, 6, 6, smooth_window=1, merge_gap=10)
    assert len(cycles) == 2
    assert [(h.name, h.frame_index) for h in hits] == [
        ("loader_docked_start", 0),
        ("loading_complete", 60),
    ]
    assert hits[0].present_at_clip_start is True
    assert hits[1].confidence > 0.5  # confidence comes from the docked run, never 0.0


def test_leading_flicker_is_joined_to_first_cycle():
    # detected at 0-4, flicker, solid from 13 onward, departs at 60, never returns
    s = [(i, 0.6, 0.9) for i in range(5)] + [(i, 0.0, 0.0) for i in range(5, 13)]
    s += [(i, 0.6, 0.9) for i in range(13, 60)] + [(i, 0.0, 0.0) for i in range(60, 80)]
    hits, cycles = detect(s, 0.3, 6, 6, smooth_window=1, merge_gap=20)
    assert len(cycles) == 1
    assert (hits[0].frame_index, hits[0].present_at_clip_start) == (0, True)
    assert hits[1].frame_index == 60
