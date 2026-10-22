"""skydata: astronomical facts from Swiss Ephemeris as JSON."""

__version__ = "0.1.0"

# Bumped whenever the request or response format changes in a way a caller
# could notice. Cached responses keyed on an older schema must not be reused.
SCHEMA_VERSION = 1
