# skydata

A small command-line program that answers astronomy questions with JSON. Send it a request on stdin and it prints facts on stdout: where the Sun, Moon and planets are at given moments, house cusps for a place, and the exact times of sign crossings, separations, stations and eclipses inside a time window.

All astronomy comes from [Swiss Ephemeris](https://www.astro.com/swisseph/swephinfo_e.htm) through [pyswisseph](https://pypi.org/project/pyswisseph/). skydata adds request checking, the event searches, and a stable JSON format.

## License

skydata is free software under the GNU Affero General Public License, version 3 only (see [LICENSE](LICENSE)).

It depends on:

- **Swiss Ephemeris**, copyright Astrodienst AG, Zurich, Switzerland, used here under the GNU Affero General Public License. Astrodienst also offers a paid Swiss Ephemeris Professional License. Source: [github.com/aloistr/swisseph](https://github.com/aloistr/swisseph).
- **pyswisseph** 2.10.3.2 by Stanislas Marquis, GNU Affero General Public License v3, which bundles Swiss Ephemeris 2.10.03. Source: [github.com/astrorigin/pyswisseph](https://github.com/astrorigin/pyswisseph).

Every version of skydata that runs anywhere for Ninsim, Inc. is a tagged release in this repository, so the source of what runs is always public here.

## Install

Needs Python 3.10 or later.

```
git clone https://github.com/ninsim/skydata.git
cd skydata
git checkout v0.1.0          # a release tag
python3 -m venv .venv
.venv/bin/pip install .      # installs the pinned pyswisseph==2.10.3.2
```

Swiss Ephemeris needs its data files (`.se1`). Astrodienst publishes them at [github.com/aloistr/swisseph/tree/master/ephe](https://github.com/aloistr/swisseph/tree/master/ephe), which is where [astro.com/ftp/swisseph/ephe](https://www.astro.com/ftp/swisseph/ephe/) points. For 1800 to 2399 you need `sepl_18.se1` (planets), `semo_18.se1` (Moon) and `seas_18.se1` (Chiron and the main asteroids). Other centuries use the files with other numbers. Upstream sometimes updates these files, and the fingerprint described below identifies the exact set an installation uses.

Then write the release record once:

```
.venv/bin/skydata release --ephe-path /path/to/ephe
```

This hashes every file under that directory and writes `RELEASE.json` beside the virtual environment (here, in the clone). Use `--release PATH` or the `SKYDATA_RELEASE` environment variable to put it elsewhere. Run it again after upgrading skydata or pyswisseph or changing the ephemeris files. Every call compares the running versions, and the path, size and modification time of every file under the directory, with the record, and refuses to answer while they differ. Hashing every call would be too slow, so a file rewritten with the same size and modification time would go unnoticed: treat the directory as read-only once released.

## Use

```
echo '{"op": "sky", "times": ["2027-03-20T12:00:00Z"], "bodies": ["sun", "moon"]}' | skydata
```

```
skydata [--out PATH] [--release PATH] < request.json
skydata release --ephe-path DIR [--release PATH]
skydata --version
```

### Conventions

- Times are UTC, written like `2027-03-20T12:00:00Z` (up to six decimal places on the seconds, `Z` or `+00:00`). skydata does no time zone work. UTC is treated as Universal Time, ignoring the under-one-second difference between UTC and UT1.
- Julian days (`jd_ut`) are Universal Time on the proleptic Gregorian calendar, the same as `swe.julday(..., GREG_CAL)`.
- Positions are geocentric and apparent (light time, aberration, light deflection and nutation applied), tropical, referred to the true ecliptic and equinox of date. Equatorial coordinates use the true equator of date.
- Longitude, latitude, right ascension and declination are in degrees, with longitude from 0 to 360. Distance is in astronomical units. Speeds are per day. Geographic longitude is east positive.
- No silent fallback. When its data files do not cover a date, Swiss Ephemeris quietly switches to a less precise built-in model. skydata checks for that on every calculation and fails instead.

### Bodies

`sun`, `moon`, `mercury`, `venus`, `mars`, `jupiter`, `saturn`, `uranus`, `neptune`, `pluto`, `chiron`, `ceres`, `pallas`, `juno`, `vesta`, `true_node`, `mean_node`, `mean_apogee` (mean lunar apogee, often called Black Moon Lilith), `osculating_apogee`.

### `sky`: positions at instants

```json
{"op": "sky",
 "times": ["2027-03-20T12:00:00Z"],
 "bodies": ["sun", "moon"],
 "equatorial": true,
 "place": {"lat": 51.5, "lon": -0.1, "house_system": "P"}}
```

`bodies` defaults to the Sun through Pluto plus `chiron`, `true_node`, `mean_node` and `mean_apogee`. `equatorial` defaults to false. `place` is optional and `house_system` defaults to `P` (Placidus).

Each result has the time, `jd_ut`, and per body `lon`, `lat`, `dist`, `lon_speed`, `lat_speed`, `dist_speed`, plus `ra`, `dec`, `ra_speed`, `dec_speed` when `equatorial` is true. With a place it adds `houses` (the 12 `cusps`, `ascendant`, `midheaven`, `armc`, `vertex`, `equatorial_ascendant`, `co_ascendant_koch`, `co_ascendant_munkasey`, `polar_ascendant`) and `local_sidereal_time` in hours.

House systems are the Swiss Ephemeris letters that give 12 cusps: `A B C D E F H I i K L M N O P Q R S T U V W X Y`. Placidus and Koch are undefined inside the polar circles, and skydata rejects them there rather than substituting another system. Ask for `O` (Porphyry) or another system if you want one.

### `events`: exact times in a window

```json
{"op": "events",
 "start": "2027-01-01T00:00:00Z", "end": "2028-01-01T00:00:00Z",
 "find": [
   {"type": "crossing", "body": "sun", "degrees": [0, 90, 180, 270]},
   {"type": "separation", "a": "sun", "b": "moon", "angles": [0, 180]},
   {"type": "station", "body": "mercury"},
   {"type": "eclipse", "kind": "solar"}]}
```

- `crossing`: the body's longitude passes a degree.
- `separation`: the signed difference `lon(b) - lon(a)`, taken from 0 to 360, passes an angle. A square between two bodies is both 90 and 270.
- `station`: the body's longitude speed changes sign.
- `eclipse`: a solar or lunar eclipse, at its time of greatest eclipse, with its type (`total`, `annular`, `hybrid`, `partial` or `penumbral`).

The window includes `start` and excludes `end`. Results come back in the order of `find`, each with its events sorted by time. Every event has `time` and `jd_ut`. Crossings and separations also carry the `degree` or `angle` matched and a `direction`, `increasing` or `decreasing`, which tells a direct pass from a retrograde one. Stations carry `direction` `retrograde` or `direct`. Eclipses carry `type`.

How the searches work: they sample every 6 hours, and halve a step (down to 15 minutes) wherever the motion between two samples disagrees with their speeds by more than 1 percent, which is where a step could hide a reversal. They then split the window wherever the speed changes sign and bisect each bracketed root until the bracket is one floating-point step wide (about 40 microseconds for current dates). Each pass of a retrograde loop falls in its own piece, so all three passes are found. The extra samples matter for the true node, which turns often, and for the few hours when a body passes behind the Sun and light bending wiggles its apparent position by up to about 2 arcseconds. A slow planet's speed crosses zero so gently that its station time is only meaningful to a few seconds. Swiss Ephemeris output for the true node occasionally jumps by a fraction of an arcsecond within a second. Next to such a jump a one-second scan can find a second crossing of the same target a few seconds away, where skydata reports one.

### Responses

Every response repeats the request with defaults filled in, and carries the skydata version, the schema version, the Swiss Ephemeris version and the fingerprint of the ephemeris files:

```json
{"skydata": {"version": "0.1.0", "schema": 1},
 "release": {"skydata_version": "0.1.0", "schema_version": 1, "swisseph_version": "2.10.03",
             "ephemeris_fingerprint": "sha256:..."},
 "request": {...},
 "results": [...]}
```

Numbers are full double precision. Round them as your use needs.

### `--out PATH`

Writes the same bytes to PATH as well as stdout. skydata writes a temporary file beside PATH, writes stdout, and only then renames the temporary file over PATH. If anything fails, PATH is left as it was and the temporary file is removed. Exit 0 means both writes completed. The directory must already exist.

### Exit codes

| Code | Meaning | Retry? |
|---|---|---|
| 0 | success | |
| 1 | a crash or a write error | once is reasonable |
| 2 | the request is invalid, or asks for houses that are undefined at that place | no |
| 3 | ephemeris files missing or not covering the date, or the release record missing or stale | no, fix the installation |

On failure stderr carries one line starting with `skydata:`.

## Tests

```
.venv/bin/pip install '.[test]'
SKYDATA_TEST_EPHE=/path/to/ephe .venv/bin/python -m pytest
```

Without `SKYDATA_TEST_EPHE` the tests that need ephemeris files are skipped. The reference values in `tests/reference` were taken from direct Swiss Ephemeris 2.10.03 calls for 2027 and for invented birth moments.
