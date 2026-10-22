"""Request validation. Returns the request with every default filled in.

Unknown keys are rejected rather than ignored, so a misspelled option fails
loudly instead of silently computing something else.
"""

from __future__ import annotations

from skydata.ephem import BODIES, HOUSE_SYSTEMS, parse_time
from skydata.errors import RequestError

DEFAULT_BODIES = ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn", "uranus",
                  "neptune", "pluto", "chiron", "true_node", "mean_node", "mean_apogee"]


def normalize(request) -> dict:
    if not isinstance(request, dict):
        raise RequestError("request: expected a JSON object")
    op = request.get("op")
    if op == "sky":
        return _sky(request)
    if op == "events":
        return _events(request)
    raise RequestError("op: expected 'sky' or 'events'")


def _keys(obj: dict, where: str, required: tuple, optional: tuple = ()) -> None:
    for key in required:
        if key not in obj:
            raise RequestError(f"{where}{key}: required")
    extra = sorted(set(obj) - set(required) - set(optional))
    if extra:
        raise RequestError(f"{where}{extra[0]}: unknown key")


def _number(value, where: str, low: float, high: float, high_open: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestError(f"{where}: expected a number")
    if not (low <= value < high if high_open else low <= value <= high):
        bracket = ")" if high_open else "]"
        raise RequestError(f"{where}: expected a number in [{low:g}, {high:g}{bracket}")


def _body(value, where: str) -> None:
    if not isinstance(value, str) or value not in BODIES:
        raise RequestError(f"{where}: unknown body (known: {', '.join(BODIES)})")


def _unique_list(value, where: str, check) -> list:
    """A non-empty list whose items pass check(item, where) and are all distinct."""
    if not isinstance(value, list) or not value:
        raise RequestError(f"{where}: expected a non-empty list")
    for index, item in enumerate(value):
        check(item, f"{where}[{index}]")
    if len(set(value)) != len(value):
        raise RequestError(f"{where}: duplicate entries")
    return value


def _angle(value, where: str) -> None:
    _number(value, where, 0, 360, high_open=True)


def _sky(request: dict) -> dict:
    _keys(request, "", ("op", "times"), ("bodies", "equatorial", "place"))
    times = request["times"]
    if not isinstance(times, list) or not times:
        raise RequestError("times: expected a non-empty list")
    for index, text in enumerate(times):
        parse_time(text, f"times[{index}]")
    bodies = _unique_list(request.get("bodies", DEFAULT_BODIES), "bodies", _body)
    equatorial = request.get("equatorial", False)
    if not isinstance(equatorial, bool):
        raise RequestError("equatorial: expected true or false")
    normalized = {"op": "sky", "times": times, "bodies": bodies, "equatorial": equatorial}
    place = request.get("place")
    if place is not None:
        if not isinstance(place, dict):
            raise RequestError("place: expected an object")
        _keys(place, "place.", ("lat", "lon"), ("house_system",))
        _number(place["lat"], "place.lat", -90, 90)
        _number(place["lon"], "place.lon", -180, 180)
        system = place.get("house_system", "P")
        if system not in HOUSE_SYSTEMS:
            raise RequestError(f"place.house_system: expected one of {' '.join(HOUSE_SYSTEMS)}")
        normalized["place"] = {"lat": place["lat"], "lon": place["lon"], "house_system": system}
    return normalized


def _events(request: dict) -> dict:
    _keys(request, "", ("op", "start", "end", "find"))
    start = parse_time(request["start"], "start")
    end = parse_time(request["end"], "end")
    if end <= start:
        raise RequestError("end: must be later than start")
    find = request["find"]
    if not isinstance(find, list) or not find:
        raise RequestError("find: expected a non-empty list")
    return {"op": "events", "start": request["start"], "end": request["end"],
            "find": [_finder(item, f"find[{index}]") for index, item in enumerate(find)]}


def _finder(item, where: str) -> dict:
    if not isinstance(item, dict):
        raise RequestError(f"{where}: expected an object")
    kind = item.get("type")
    if kind == "crossing":
        _keys(item, f"{where}.", ("type", "body", "degrees"))
        _body(item["body"], f"{where}.body")
        _unique_list(item["degrees"], f"{where}.degrees", _angle)
    elif kind == "separation":
        _keys(item, f"{where}.", ("type", "a", "b", "angles"))
        _body(item["a"], f"{where}.a")
        _body(item["b"], f"{where}.b")
        if item["a"] == item["b"]:
            raise RequestError(f"{where}.b: must differ from a")
        _unique_list(item["angles"], f"{where}.angles", _angle)
    elif kind == "station":
        _keys(item, f"{where}.", ("type", "body"))
        _body(item["body"], f"{where}.body")
    elif kind == "eclipse":
        _keys(item, f"{where}.", ("type", "kind"))
        if item["kind"] not in ("solar", "lunar"):
            raise RequestError(f"{where}.kind: expected 'solar' or 'lunar'")
    else:
        raise RequestError(f"{where}.type: expected crossing, separation, station or eclipse")
    return item
