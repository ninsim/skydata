"""The events operation: exact times inside a window [start, end).

Every search except eclipses works on a track, an angle in degrees (mod 360)
with its rate in degrees per day: a body's longitude for crossings and
stations, the difference lon(b) - lon(a) for separations.

1. Sample the track every STEP_DAYS from start to end. Where the angle moved
   between two samples differs by more than CURVATURE from what the average
   of their two rates predicts, the step may hide a reversal, so halve it,
   down to MIN_STEP_DAYS. This catches the true node's quick turns and the few
   hours when light bending near the Sun wiggles a slow body's apparent
   position by up to about 2 arcseconds.
2. Where the rate changes sign between two samples, bisect to the turning
   point (a station, for a body) and split there. Each piece now moves one way.
3. Each piece moves a few degrees at most, so a target is crossed at most once
   in it. Where the angle to the target changes sign without wrapping through
   the opposite point, bisect to the crossing.

Bisection runs until the bracket is one floating-point step wide, which for
current dates is about 40 microseconds. All three passes of a retrograde loop
are found because each pass falls in its own piece.
"""

from __future__ import annotations

from skydata import ephem

STEP_DAYS = 0.25
MIN_STEP_DAYS = 1 / 96  # 15 minutes
CURVATURE = 0.01


def events(request: dict) -> list:
    jd0 = ephem.julian_day(ephem.parse_time(request["start"], "start"))
    jd1 = ephem.julian_day(ephem.parse_time(request["end"], "end"))
    sampler = _Sampler()
    results = []
    for finder in request["find"]:
        kind = finder["type"]
        if kind == "eclipse":
            found = _eclipses(finder["kind"], jd0, jd1)
        elif kind == "station":
            track = sampler.body(finder["body"])
            found = [{"time": ephem.format_jd(t), "jd_ut": t, "direction": direction}
                     for t, direction in _pieces(track, jd0, jd1)[1]]
        elif kind == "crossing":
            found = _crossings(sampler.body(finder["body"]), finder["degrees"], "degree", jd0, jd1)
        else:
            found = _crossings(sampler.separation(finder["a"], finder["b"]),
                               finder["angles"], "angle", jd0, jd1)
        results.append({"find": finder, "events": found})
    return results


class _Sampler:
    """Body positions shared by every finder in one request."""

    def __init__(self):
        self._memo = {}

    def _calc(self, jd: float, body: int) -> tuple:
        key = (jd, body)
        values = self._memo.get(key)
        if values is None:
            values = self._memo[key] = ephem.calc(jd, body)
        return values

    def body(self, name: str):
        body = ephem.BODIES[name]

        def track(jd):
            values = self._calc(jd, body)
            return values[0], values[3]
        return track

    def separation(self, a_name: str, b_name: str):
        a, b = ephem.BODIES[a_name], ephem.BODIES[b_name]

        def track(jd):
            va, vb = self._calc(jd, a), self._calc(jd, b)
            return (vb[0] - va[0]) % 360.0, vb[3] - va[3]
        return track


def _wrap(angle: float) -> float:
    """Angle folded into [-180, 180)."""
    return (angle + 180.0) % 360.0 - 180.0


def _grid(jd0: float, jd1: float) -> list:
    points = []
    index = 0
    while True:
        jd = jd0 + index * STEP_DAYS
        if jd >= jd1:
            break
        points.append(jd)
        index += 1
    points.append(jd1)
    return points


def _flip(predicate, lo: float, hi: float) -> float:
    """First point (to float precision) in (lo, hi] where predicate differs from predicate(lo)."""
    side = predicate(lo)
    while True:
        mid = (lo + hi) / 2.0
        if mid <= lo or mid >= hi:
            return hi
        if predicate(mid) == side:
            lo = mid
        else:
            hi = mid


def _samples(track, jd0: float, jd1: float) -> list:
    """(jd, value, rate) on the grid, with extra samples where a step hides curvature."""
    grid = _grid(jd0, jd1)
    samples = [(grid[0], *track(grid[0]))]
    for jd in grid[1:]:
        pending = [(jd, *track(jd))]
        while pending:
            a, value_a, rate_a = samples[-1]
            b, value_b, rate_b = pending[-1]
            moved = _wrap(value_b - value_a)
            predicted = (rate_a + rate_b) / 2.0 * (b - a)
            if b - a > MIN_STEP_DAYS and \
                    abs(moved - predicted) > CURVATURE * max(abs(moved), abs(predicted)):
                mid = (a + b) / 2.0
                pending.append((mid, *track(mid)))
            else:
                samples.append(pending.pop())
    return samples


def _pieces(track, jd0: float, jd1: float):
    """Split [jd0, jd1] where the rate changes sign.

    Returns the pieces as (a, b, value_a, value_b) and the turning points as
    (jd, 'retrograde' | 'direct').
    """
    pieces, turns = [], []
    samples = _samples(track, jd0, jd1)
    a, value_a, rate_a = samples[0]
    if rate_a == 0 and samples[1][2] > 0:
        # Stationary exactly at the window start and turning direct: the sign
        # change happened at start itself, which [start, end) includes.
        turns.append((a, "direct"))
    for b, value_b, rate_b in samples[1:]:
        if (rate_a < 0) != (rate_b < 0):
            turn = _flip(lambda t: track(t)[1] < 0, a, b)
            if turn < jd1:
                turns.append((turn, "retrograde" if rate_b < 0 else "direct"))
            value_turn = track(turn)[0]
            pieces.append((a, turn, value_a, value_turn))
            a, value_a = turn, value_turn
        pieces.append((a, b, value_a, value_b))
        a, value_a, rate_a = b, value_b, rate_b
    return pieces, turns


def _crossings(track, targets: list, label: str, jd0: float, jd1: float) -> list:
    pieces, _ = _pieces(track, jd0, jd1)
    found = []
    for order, target in enumerate(targets):
        def below(t, target=target):
            return _wrap(track(t)[0] - target) < 0

        for index, (a, b, value_a, value_b) in enumerate(pieces):
            gap_a, gap_b = _wrap(value_a - target), _wrap(value_b - target)
            if index == 0 and gap_a == 0 and gap_b > 0:
                # Exactly on target at the window start, moving up. The sign
                # change happened at start itself, which [start, end) includes.
                found.append((a, order, target, "increasing"))
                continue
            if (gap_a < 0) == (gap_b < 0) or abs(gap_b - gap_a) >= 180.0:
                continue  # no sign change, or only the wrap at the opposite point
            t = _flip(below, a, b)
            if jd0 <= t < jd1:
                found.append((t, order, target, "increasing" if gap_a < 0 else "decreasing"))
    found.sort()
    return [{"time": ephem.format_jd(t), "jd_ut": t, label: target, "direction": direction}
            for t, _, target, direction in found]


def _eclipses(kind: str, jd0: float, jd1: float) -> list:
    found = []
    # Swiss Ephemeris skips an eclipse whose maximum falls within about a
    # minute after the search start, so search from a day early and filter.
    # Two eclipses of one kind are always weeks apart.
    jd = jd0 - 1.0
    while True:
        maximum, eclipse_type = ephem.next_eclipse(jd, kind)
        if maximum >= jd1:
            break
        if maximum >= jd0:
            found.append({"time": ephem.format_jd(maximum), "jd_ut": maximum, "type": eclipse_type})
        jd = max(maximum, jd) + 1.0
    return found
