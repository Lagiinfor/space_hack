"""Catalogue entries for the test targets (Gaia DR3 unless noted).
ra/dec in degrees at `epoch`; pmra (includes cos dec) and pmdec in mas/yr; parallax in mas."""

TARGETS = {
    "barnard": dict(
        name="Barnard's Star", ra=269.44850252, dec=4.73942005, epoch=2016.0,
        pmra=-801.551, pmdec=10362.394, parallax=546.976,
    ),
}
