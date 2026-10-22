from datetime import datetime, timezone

import pytest
import swisseph as swe

from conftest import REFERENCE, run
from skydata import ephem
from skydata.spec import DEFAULT_BODIES

NATAL = [case for case in REFERENCE["natal"] if not case.get("expect_error")]
POLAR = [case for case in REFERENCE["natal"] if case.get("expect_error")]


@pytest.mark.parametrize("case", NATAL, ids=[case["id"] for case in NATAL])
def test_natal_instants_match_reference(ask, case):
    response = ask({"op": "sky", "times": [case["time"]], "equatorial": True,
                    "place": case["place"]})
    result = response["results"][0]
    places = case["decimals"]
    assert round(result["jd_ut"], places) == case["jd_ut"]
    assert round(result["local_sidereal_time"], places) == case["local_sidereal_time"]
    for name, expected in case["bodies"].items():
        got = result["bodies"][name]
        for key, value in expected.items():
            assert round(got[key], places) == value, (name, key)
    houses = result["houses"]
    assert [round(c, places) for c in houses["cusps"]] == case["cusps"]
    assert round(houses["ascendant"], places) == case["ascendant"]
    assert round(houses["midheaven"], places) == case["midheaven"]
    assert round(houses["vertex"], places) == case["vertex"]


@pytest.mark.parametrize("case", POLAR, ids=[case["id"] for case in POLAR])
def test_placidus_inside_polar_circle_is_rejected(release_path, ask, case):
    request = {"op": "sky", "times": ["1992-12-21T11:00:00Z"], "place": case["place"]}
    code, out, err = run(request, release_path)
    assert code == 2 and out == b"" and "polar circle" in err
    porphyry = {**request, "place": {**case["place"], "house_system": "O"}}
    assert len(ask(porphyry)["results"][0]["houses"]["cusps"]) == 12


@pytest.mark.parametrize("day", REFERENCE["noon_positions"], ids=lambda d: d["time"][:10])
def test_daily_noon_positions_match_reference(ask, day):
    result = ask({"op": "sky", "times": [day["time"]]})["results"][0]
    for name, expected in day["bodies"].items():
        for key, value in expected.items():
            assert round(result["bodies"][name][key], day["decimals"]) == value, (name, key)


def test_values_are_swiss_ephemeris_values_unchanged(ask):
    names = list(ephem.BODIES)
    result = ask({"op": "sky", "times": ["2027-03-20T12:00:00Z"], "bodies": names,
                  "equatorial": True})["results"][0]
    jd = swe.julday(2027, 3, 20, 12.0)
    for name in names:
        ecliptic = swe.calc_ut(jd, ephem.BODIES[name], swe.FLG_SWIEPH | swe.FLG_SPEED)[0]
        equator = swe.calc_ut(jd, ephem.BODIES[name],
                              swe.FLG_SWIEPH | swe.FLG_SPEED | swe.FLG_EQUATORIAL)[0]
        got = result["bodies"][name]
        assert [got[k] for k in ("lon", "lat", "dist", "lon_speed", "lat_speed", "dist_speed")] \
            == list(ecliptic)
        assert [got[k] for k in ("ra", "dec", "ra_speed", "dec_speed")] \
            == [equator[0], equator[1], equator[3], equator[4]]


def test_default_bodies_and_no_equatorial(ask):
    result = ask({"op": "sky", "times": ["2027-03-20T12:00:00Z"]})["results"][0]
    assert list(result["bodies"]) == DEFAULT_BODIES
    assert "ra" not in result["bodies"]["sun"] and "houses" not in result


def test_many_times_keep_their_order(ask):
    times = ["2028-02-29T00:00:00Z", "2027-01-01T00:00:00.5Z", "2027-06-01T23:59:59.999999+00:00"]
    results = ask({"op": "sky", "times": times, "bodies": ["moon"]})["results"]
    assert [r["time"] for r in results] == ["2028-02-29T00:00:00Z", "2027-01-01T00:00:00.500000Z",
                                           "2027-06-01T23:59:59.999999Z"]
    assert results[1]["jd_ut"] == swe.julday(2027, 1, 1, 0.5 / 3600.0)


@pytest.mark.parametrize("system", ephem.HOUSE_SYSTEMS)
def test_every_accepted_house_system_is_a_real_one(ask, system):
    if system != "P":
        assert swe.house_name(system.encode()) != "Placidus"
    result = ask({"op": "sky", "times": ["2027-03-20T12:00:00Z"],
                  "place": {"lat": 45.0, "lon": 7.0, "house_system": system}})["results"][0]
    assert result["houses"]["system"] == system and len(result["houses"]["cusps"]) == 12


def test_time_formatting_and_round_trip():
    early = datetime(950, 7, 4, 3, 2, 1, 5, tzinfo=timezone.utc)
    assert ephem.format_time(early) == "0950-07-04T03:02:01.000005Z"
    moment = ephem.parse_time("2027-04-06T23:51:10.123456Z", "t")
    jd = ephem.julian_day(moment)
    assert abs((ephem.datetime_from_jd(jd) - moment).total_seconds()) < 1e-4
