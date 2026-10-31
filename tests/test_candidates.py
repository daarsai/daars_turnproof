from turnproof.events.candidates import best_zone, occupancy_series
from turnproof.perception.sam_parse import Det

CFG = {
    "zones": {
        "aft_hold": {"x0": 0.62, "x1": 0.95, "y0": 0.45, "y1": 0.95, "pad_out": 0.35},
        "forward_hold": {"x0": 0.08, "x1": 0.40, "y0": 0.45, "y1": 0.95, "pad_out": 0.35},
    },
    "rules": {
        "docked_overlap_tau": 0.3,
        "docked_min_s": 3,
        "undocked_min_s": 3,
        "smooth_window_s": 0,
        "merge_gap_s": 0,
    },
    "sampling": {"logic_fps": 1},
}
FPS = 1.0
W, H = 1280, 516
AC = (392, 0, 1267, 363)  # real aircraft box from clip1


def det(frame, box, c=0.9, ordinal=0):
    return Det(frame, ordinal, *box, W, H, c)


def test_series_ignores_aircraft_labelled_as_vehicle():
    aircraft = {0: [det(0, AC)]}
    vehicles = {0: [det(0, AC, 0.95, 5)]}  # the plane mislabelled as a vehicle
    s = occupancy_series(vehicles, aircraft, CFG["zones"], "forward_hold")
    assert s == [(0, 0.0, 0.0)]


def test_full_cycle_in_forward_hold():
    aircraft = {0: [det(0, AC)]}
    # forward hold zone for AC: x in [392+0.08*875, 392+0.40*875] = [462, 742]; y in [163, 345+127]
    inside = (480, 200, 600, 330)
    away = (100, 420, 200, 500)  # left of the aircraft, outside both hold zones
    vehicles = {}
    for f in range(5):
        vehicles[f] = [det(f, away)]
    for f in range(5, 15):
        vehicles[f] = [det(f, inside)]
    for f in range(15, 22):
        vehicles[f] = [det(f, away)]
    zone, hits, _cycles = best_zone(vehicles, aircraft, CFG, FPS, nose_left=False)
    assert zone == "forward_hold"
    assert [(h.name, h.frame_index) for h in hits] == [
        ("loader_docked_start", 5),
        ("loading_complete", 15),
    ]
