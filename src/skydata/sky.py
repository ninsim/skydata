"""The sky operation: positions at given instants, with houses for a place."""

from __future__ import annotations

from skydata import ephem


def sky(request: dict) -> list:
    results = []
    for index, text in enumerate(request["times"]):
        moment = ephem.parse_time(text, f"times[{index}]")
        jd = ephem.julian_day(moment)
        entry = {"time": ephem.format_time(moment), "jd_ut": jd, "bodies": {}}
        for name in request["bodies"]:
            entry["bodies"][name] = _body(jd, ephem.BODIES[name], request["equatorial"])
        place = request.get("place")
        if place:
            entry.update(_place(jd, place))
        results.append(entry)
    return results


def _body(jd: float, body: int, equatorial: bool) -> dict:
    lon, lat, dist, lon_speed, lat_speed, dist_speed = ephem.calc(jd, body)
    facts = {"lon": lon, "lat": lat, "dist": dist,
             "lon_speed": lon_speed, "lat_speed": lat_speed, "dist_speed": dist_speed}
    if equatorial:
        ra, dec, _, ra_speed, dec_speed, _ = ephem.calc(jd, body, equatorial=True)
        facts.update({"ra": ra, "dec": dec, "ra_speed": ra_speed, "dec_speed": dec_speed})
    return facts


def _place(jd: float, place: dict) -> dict:
    cusps, ascmc = ephem.houses(jd, place["lat"], place["lon"], place["house_system"])
    houses = {"system": place["house_system"], "cusps": list(cusps)}
    houses.update(zip(ephem.ASCMC_NAMES, ascmc))
    local_sidereal = (ephem.sidereal_time(jd) + place["lon"] / 15.0) % 24.0
    return {"houses": houses, "local_sidereal_time": local_sidereal}
