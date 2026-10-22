"""Thin layer over pyswisseph: time conversion, bodies, positions, houses, eclipses.

Conventions (see README): times are UTC, treated as Universal Time; Julian days
are UT on the proleptic Gregorian calendar. Positions are geocentric, apparent,
tropical, referred to the true equinox and ecliptic (or equator) of date.
Longitudes run 0 to 360, east positive. Distances are in AU, speeds per day.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import swisseph as swe

from skydata.errors import DataError, RequestError

BODIES = {
    "sun": swe.SUN,
    "moon": swe.MOON,
    "mercury": swe.MERCURY,
    "venus": swe.VENUS,
    "mars": swe.MARS,
    "jupiter": swe.JUPITER,
    "saturn": swe.SATURN,
    "uranus": swe.URANUS,
    "neptune": swe.NEPTUNE,
    "pluto": swe.PLUTO,
    "chiron": swe.CHIRON,
    "ceres": swe.CERES,
    "pallas": swe.PALLAS,
    "juno": swe.JUNO,
    "vesta": swe.VESTA,
    "true_node": swe.TRUE_NODE,
    "mean_node": swe.MEAN_NODE,
    "mean_apogee": swe.MEAN_APOG,
    "osculating_apogee": swe.OSCU_APOG,
}

# Swiss Ephemeris house methods that return 12 cusps. An unknown letter makes
# Swiss Ephemeris fall back to Placidus without saying so, hence the list.
# G (Gauquelin, 36 sectors) is left out.
HOUSE_SYSTEMS = tuple("ABCDEFHIiKLMNOPQRSTUVWXY")

ASCMC_NAMES = ("ascendant", "midheaven", "armc", "vertex", "equatorial_ascendant",
               "co_ascendant_koch", "co_ascendant_munkasey", "polar_ascendant")

POSITION_FLAGS = swe.FLG_SWIEPH | swe.FLG_SPEED

_TIME_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)")
_J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
_J2000_JD = 2451545.0


def set_ephe_path(path: str) -> None:
    swe.set_ephe_path(path)


def swisseph_version() -> str:
    return swe.version


def pyswisseph_build() -> str:
    """pyswisseph's own build stamp, which changes even when the bundled C library does not."""
    return str(swe.__version__)


def parse_time(text, where: str) -> datetime:
    """Parse an ISO 8601 UTC time such as 2027-03-20T12:00:00Z."""
    match = _TIME_RE.fullmatch(text) if isinstance(text, str) else None
    if not match:
        raise RequestError(f"{where}: expected a UTC time like 2027-03-20T12:00:00Z")
    year, month, day, hour, minute, second, fraction = match.groups()
    micro = int((fraction or "").ljust(6, "0"))
    try:
        return datetime(int(year), int(month), int(day), int(hour), int(minute),
                        int(second), micro, tzinfo=timezone.utc)
    except ValueError as exc:
        raise RequestError(f"{where}: {exc}") from None


def julian_day(moment: datetime) -> float:
    hours = moment.hour + moment.minute / 60.0 + (moment.second + moment.microsecond / 1e6) / 3600.0
    return swe.julday(moment.year, moment.month, moment.day, hours, swe.GREG_CAL)


def datetime_from_jd(jd: float) -> datetime:
    return _J2000 + timedelta(days=jd - _J2000_JD)


def format_time(moment: datetime) -> str:
    text = (f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"
            f"T{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}")
    if moment.microsecond:
        text += f".{moment.microsecond:06d}"
    return text + "Z"


def format_jd(jd: float) -> str:
    try:
        return format_time(datetime_from_jd(jd))
    except OverflowError:
        raise DataError("result time is outside the years 1 to 9999") from None


def calc(jd: float, body: int, equatorial: bool = False) -> tuple:
    """Position and speed of one body. Refuses Swiss Ephemeris' silent fallback.

    When its data files do not cover the date, Swiss Ephemeris quietly switches
    to the less precise built-in Moshier model and reports that only in the
    returned flags. That case is an error here.
    """
    flags = POSITION_FLAGS | (swe.FLG_EQUATORIAL if equatorial else 0)
    try:
        values, returned = swe.calc_ut(jd, body, flags)
    except swe.Error as exc:
        raise DataError(str(exc)) from None
    if not returned & swe.FLG_SWIEPH:
        raise DataError("Swiss Ephemeris data files do not cover this date "
                        "(it fell back to the built-in Moshier model)")
    return values


def houses(jd: float, lat: float, lon: float, system: str) -> tuple:
    try:
        return swe.houses_ex(jd, lat, lon, system.encode("ascii"), 0)
    except swe.Error:
        raise RequestError(f"place.house_system: Swiss Ephemeris cannot compute '{system}' houses "
                           "at this latitude (Placidus and Koch are undefined inside the "
                           "polar circle)") from None


def sidereal_time(jd: float) -> float:
    """Apparent Greenwich sidereal time in hours."""
    return swe.sidtime(jd)


def next_eclipse(jd: float, kind: str) -> tuple[float, str]:
    """Time of maximum and type of the next solar or lunar eclipse after jd."""
    try:
        if kind == "solar":
            result, times = swe.sol_eclipse_when_glob(jd, swe.FLG_SWIEPH, swe.ECL_ALLTYPES_SOLAR, False)
        else:
            result, times = swe.lun_eclipse_when(jd, swe.FLG_SWIEPH, 0, False)
    except swe.Error as exc:
        raise DataError(str(exc)) from None
    maximum = times[0]
    # The eclipse search reports no fallback flag, so check the files cover the
    # Sun and Moon at the moment it returned.
    calc(maximum, swe.SUN)
    calc(maximum, swe.MOON)
    return maximum, eclipse_type(result)


def eclipse_type(flags: int) -> str:
    if flags & swe.ECL_ANNULAR_TOTAL:
        return "hybrid"
    if flags & swe.ECL_ANNULAR:
        return "annular"
    if flags & swe.ECL_TOTAL:
        return "total"
    if flags & swe.ECL_PARTIAL:
        return "partial"
    if flags & swe.ECL_PENUMBRAL:
        return "penumbral"
    raise DataError(f"unrecognized eclipse type flags {flags}")
