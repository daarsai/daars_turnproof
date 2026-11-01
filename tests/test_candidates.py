from turnproof.events.candidates import best_zone, occupancy_series
from turnproof.perception.sam_parse import Det

CFG = {
    "zones": {
        "aft_hold": {"x0": 0.62, "x1": 0.95, "y0": 0.45, "y1": 0.95, "pad_out": 0.35},
        "forward_hold": {"x0": 0.08, "x1": 0.40, "y0": 0.45, "y1": 0.95, "pad_out": 0.35},
    },
    "rules": {
        "docked_overlap_tau": 0.3,
        "docked_min_real_s": 3,
        "undocked_min_real_s": 3,
        "merge_gap_real_s": 0,
        "smooth_window_s": 0,
        "floor_video_s": 0,
        "cap_video_s": 100,
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
    zone, hits, _cycles = best_zone(vehicles, aircraft, CFG, FPS, nose_right=False, speed=1.0)
    assert zone == "forward_hold"
    assert [(h.name, h.frame_index) for h in hits] == [
        ("loader_docked_start", 5),
        ("loading_complete", 15),
    ]


def test_departure_at_clip_end_is_accepted_with_flag():
    aircraft = {0: [det(0, AC)]}
    inside = (480, 200, 600, 330)
    away = (100, 420, 200, 500)
    vehicles = {f: [det(f, inside)] for f in range(10)}
    vehicles.update(
        {f: [det(f, away)] for f in range(10, 12)}
    )  # only 2 frames away, then clip ends
    cfg = {**CFG, "rules": {**CFG["rules"], "undocked_min_real_s": 5, "floor_video_s": 2}}
    _zone, hits, _c = best_zone(vehicles, aircraft, cfg, FPS, speed=1.0)
    assert [h.name for h in hits] == ["loader_docked_start", "loading_complete"]
    assert hits[1].departure_at_clip_end is True


def test_real_seconds_scale_with_speed_factor():
    from turnproof.events.candidates import _video_s

    assert _video_s(60, 12.0, 2.0, 12.0) == 5.0  # 1 real minute = 5 s of 12x video
    assert _video_s(60, 6.0, 2.0, 12.0) == 10.0
    assert _video_s(60, None, 2.0, 12.0) == 12.0  # unknown speed: real time, capped
    assert _video_s(60, 100.0, 2.0, 12.0) == 2.0  # floor


def test_event_library_names_flow_through_the_rule():
    aircraft = {0: [det(0, AC)]}
    inside = (480, 200, 600, 330)
    away = (100, 420, 200, 500)
    vehicles = {f: [det(f, inside if 5 <= f < 15 else away)] for f in range(22)}
    _zone, hits, _c = best_zone(
        vehicles, aircraft, CFG, FPS, speed=1.0,
        zones_enabled=["forward_hold"],
        milestone_names=("fuel_truck_docked_start", "fuelling_complete"),
    )  # fmt: skip
    assert [h.name for h in hits] == ["fuel_truck_docked_start", "fuelling_complete"]


def test_every_event_has_its_zones_in_every_view_preset():
    from pathlib import Path

    import yaml

    cfg = yaml.safe_load(Path("config/config.yaml").read_text())
    for name, ev in cfg["events"].items():
        assert ev["milestones"]["start"] != ev["milestones"]["end"]
        assert ev["delay_code_families"], name
        for view, zones in cfg["zone_presets"].items():
            assert any(z in zones for z in ev["zones"]), f"event {name} has no zone in view {view}"
    assert cfg["events"]["loading"]["validated"] is True
