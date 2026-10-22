from datetime import datetime, timedelta, timezone

import pytest

from conftest import REFERENCE
from skydata import ephem, events

YEAR = {"start": "2027-01-01T00:00:00Z", "end": "2028-01-01T00:00:00Z"}


def find(ask, *finders, start=YEAR["start"], end=YEAR["end"]):
    response = ask({"op": "events", "start": start, "end": end, "find": list(finders)})
    return [result["events"] for result in response["results"]]


def to_second(text):
    moment = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    fraction = float("0" + text[19:-1]) if len(text) > 20 else 0.0
    return moment + timedelta(seconds=round(fraction))


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_lunations_2027_match_reference_to_the_second(ask):
    (found,) = find(ask, {"type": "separation", "a": "sun", "b": "moon", "angles": [0, 180]})
    expected = REFERENCE["lunations_2027"]["events"]
    assert [(iso(to_second(e["time"])), e["angle"]) for e in found] \
        == [(e["time"], e["angle"]) for e in expected]
    assert {e["direction"] for e in found} == {"increasing"}


def test_sun_sign_crossings_2027_match_reference(ask):
    degrees = list(range(0, 360, 30))
    (found,) = find(ask, {"type": "crossing", "body": "sun", "degrees": degrees})
    expected = REFERENCE["sun_crossings_2027"]
    places = expected["decimals"]
    assert [(e["degree"], round(e["jd_ut"], places)) for e in found] \
        == [(e["degree"], e["jd_ut"]) for e in expected["events"]]


def test_eclipses_2027_match_reference(ask):
    solar, lunar = find(ask, {"type": "eclipse", "kind": "solar"}, {"type": "eclipse", "kind": "lunar"})
    found = [("solar", e["type"], e["jd_ut"]) for e in solar] + \
            [("lunar", e["type"], e["jd_ut"]) for e in lunar]
    assert found == [(e["kind"], e["type"], e["jd_ut"]) for e in REFERENCE["eclipses_2027"]]


def test_moon_crossing_zero_aries_wraps_cleanly(ask):
    (found,) = find(ask, {"type": "crossing", "body": "moon", "degrees": [0]})
    assert len(found) == 13 and {e["direction"] for e in found} == {"increasing"}
    gaps = [b["jd_ut"] - a["jd_ut"] for a, b in zip(found, found[1:])]
    assert all(27.0 < gap < 27.7 for gap in gaps)
    times = [e["time"] for e in found]
    response = ask({"op": "sky", "times": times, "bodies": ["moon"]})
    for result in response["results"]:
        lon = result["bodies"]["moon"]["lon"]
        assert min(lon, 360.0 - lon) < 1e-6


@pytest.mark.parametrize("pair, window, expected", [
    (("mercury", "uranus", 90), ("2027-01-15", "2027-04-01"),
     ["2027-02-02T12:17:55Z", "2027-02-16T22:38:05Z", "2027-03-20T14:10:12Z"]),
    (("mercury", "pluto", 90), ("2027-09-25", "2027-11-30"),
     ["2027-10-06T00:32:13Z", "2027-10-09T05:25:17Z", "2027-11-13T09:38:29Z"]),
    (("mercury", "saturn", 180), ("2027-09-01", "2027-11-30"),
     ["2027-09-23T10:14:21Z", "2027-10-21T04:32:01Z", "2027-11-04T08:54:57Z"]),
])
def test_mercury_retrograde_makes_three_exact_passes(ask, pair, window, expected):
    a, b, angle = pair
    (found,) = find(ask, {"type": "separation", "a": a, "b": b, "angles": [angle]},
                    start=f"{window[0]}T00:00:00Z", end=f"{window[1]}T00:00:00Z")
    assert len(found) == 3
    for event, want in zip(found, expected):
        assert abs((to_second(event["time"]) - to_second(want)).total_seconds()) <= 1
    assert [e["direction"] for e in found] == ["decreasing", "increasing", "decreasing"]


def test_one_degree_crossed_three_times_in_a_retrograde_loop(ask):
    mid = ask({"op": "sky", "times": ["2027-02-20T00:00:00Z"], "bodies": ["mercury"]})
    degree = int(mid["results"][0]["bodies"]["mercury"]["lon"]) + 0.5
    (found,) = find(ask, {"type": "crossing", "body": "mercury", "degrees": [degree]},
                    start="2027-01-15T00:00:00Z", end="2027-04-01T00:00:00Z")
    assert [e["direction"] for e in found] == ["increasing", "decreasing", "increasing"]


def test_mercury_stations_2027_alternate(ask):
    (found,) = find(ask, {"type": "station", "body": "mercury"})
    expected = ["2027-02-09T17:36:05Z", "2027-03-03T12:32:02Z", "2027-06-10T18:15:14Z",
                "2027-07-04T19:39:23Z", "2027-10-07T14:37:04Z", "2027-10-28T14:10:38Z"]
    assert [iso(to_second(e["time"])) for e in found] == expected
    assert [e["direction"] for e in found] == ["retrograde", "direct"] * 3


def test_bodies_without_stations_report_none(ask):
    assert find(ask, *({"type": "station", "body": b} for b in ("sun", "moon", "mean_node"))) \
        == [[], [], []]


NEW_MOON = "2027-04-06T23:51:10Z"  # nine minutes before a UTC day boundary


@pytest.mark.parametrize("start, end, included", [
    ("2027-04-06T00:00:00Z", "2027-04-07T00:00:00Z", True),
    ("2027-04-07T00:00:00Z", "2027-04-08T00:00:00Z", False),
    ("2027-04-06T00:00:00Z", "2027-04-06T23:51:11Z", True),
    ("2027-04-06T00:00:00Z", "2027-04-06T23:51:09Z", False),
    ("2027-04-06T23:51:09Z", "2027-04-07T00:00:00Z", True),
    ("2027-04-06T23:51:11Z", "2027-04-07T00:00:00Z", False),
])
def test_event_near_a_window_edge(ask, start, end, included):
    (found,) = find(ask, {"type": "separation", "a": "sun", "b": "moon", "angles": [0]},
                    start=start, end=end)
    assert [iso(to_second(e["time"])) for e in found] == ([NEW_MOON] if included else [])


def test_six_hour_scan_misses_nothing_a_one_hour_scan_finds(ask, monkeypatch):
    finders = [{"type": "station", "body": body}
               for body in ("mercury", "venus", "mars", "jupiter", "pluto", "chiron", "true_node")]
    finders += [{"type": "crossing", "body": "true_node", "degrees": [0, 90, 180, 270]},
                {"type": "separation", "a": "true_node", "b": "moon", "angles": [0, 90, 180, 270]},
                {"type": "separation", "a": "mercury", "b": "venus", "angles": [0, 60, 90, 120, 180]}]
    coarse = find(ask, *finders)
    monkeypatch.setattr(events, "STEP_DAYS", 1 / 24)
    fine = find(ask, *finders)
    for finder, got, want in zip(finders, coarse, fine):
        assert len(got) == len(want)
        # A slow planet's speed passes zero so gently that its station is only
        # defined to a few seconds (Pluto: about 2 s), so stations get 5 s.
        tolerance = 5 / 86400 if finder["type"] == "station" else 1e-8
        for a, b in zip(got, want):
            assert abs(a["jd_ut"] - b["jd_ut"]) < tolerance
            assert a["direction"] == b["direction"]


def test_light_bending_wiggle_near_the_sun_finds_all_three_roots(ask):
    # Chiron passes behind the Sun on 2027-04-20. Light bending makes the
    # Uranus-Chiron separation reverse twice within one 6 hour step. Found by
    # the phase 1 review with a ten-minute scan.
    (found,) = find(ask, {"type": "separation", "a": "uranus", "b": "chiron",
                          "angles": [326.65825913402955]},
                    start="2027-04-20T00:00:00Z", end="2027-04-21T00:00:00Z")
    expected = ["2027-04-20T14:50:34Z", "2027-04-20T16:21:36Z", "2027-04-20T17:52:47Z"]
    assert [iso(to_second(e["time"])) for e in found] == expected
    assert [e["direction"] for e in found] == ["increasing", "decreasing", "increasing"]


@pytest.mark.parametrize("eclipse", REFERENCE["eclipses_2027"], ids=lambda e: f"{e['kind']}-{e['jd_ut']}")
@pytest.mark.parametrize("start_offset, end_offset, included", [
    (-1, 86400, True),     # a second before the maximum: Swiss Ephemeris alone would skip it
    (1, 86400, False),
    (-86400, 1, True),
    (-86400, -1, False),
])
def test_eclipse_at_a_window_edge(ask, eclipse, start_offset, end_offset, included):
    maximum = datetime(2000, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=eclipse["jd_ut"] - 2451545.0)
    start = maximum + timedelta(seconds=start_offset)
    end = maximum + timedelta(seconds=end_offset)
    (found,) = find(ask, {"type": "eclipse", "kind": eclipse["kind"]},
                    start=ephem.format_time(start), end=ephem.format_time(end))
    assert [e["jd_ut"] for e in found] == ([eclipse["jd_ut"]] if included else [])


def test_events_sorted_by_time_across_targets(ask):
    (found,) = find(ask, {"type": "crossing", "body": "sun", "degrees": [270, 0, 90]})
    assert [e["degree"] for e in found] == [0, 90, 270]


# The exact-edge rules, on a synthetic track that hits its target exactly on a grid point.

JD0 = 2461000.0


def line(rate, start_value):
    return lambda jd: ((start_value + rate * (jd - JD0)) % 360.0, rate)


def test_exact_hit_at_window_start_is_included():
    found = events._crossings(line(1.0, 0.0), [0.0], "degree", JD0, JD0 + 10)
    assert [(e["jd_ut"], e["direction"]) for e in found] == [(JD0, "increasing")]


def test_exact_hit_at_window_end_is_excluded():
    assert events._crossings(line(1.0, 350.0), [0.0], "degree", JD0, JD0 + 10) == []
    assert len(events._crossings(line(1.0, 350.0), [0.0], "degree", JD0, JD0 + 10.5)) == 1


def test_exact_hit_on_an_interior_grid_point_is_counted_once():
    found = events._crossings(line(-2.0, 1.0), [0.0], "degree", JD0, JD0 + 3)
    assert len(found) == 1 and found[0]["direction"] == "decreasing"
    assert abs(found[0]["jd_ut"] - (JD0 + 0.5)) < 1e-8


def test_opposite_point_wrap_is_not_a_crossing():
    assert events._crossings(line(1.0, 175.0), [0.0], "degree", JD0, JD0 + 10) == []
