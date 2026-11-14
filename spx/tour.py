"""The five test targets from the NASA challenge, used for the guided tour.
Positions are carried forward to 2026.2 (see resolve.py) so each object sits in the middle."""

TOUR = [
    dict(key="barnard", name="Barnard's Star", query="Barnard's star", band=3, field=0.06,
         kind="Fast-moving star",
         story="The fastest-moving star in our sky, 6 light-years away. It crawls about 10 arcseconds "
               "north each year. Watch it hop upward between the passes; in Difference view it shows as a "
               "red/blue pair that flips."),
    dict(key="epsindib", name="Epsilon Indi B", query="eps Indi B", band=6, field=0.06,
         kind="Pair of brown dwarfs",
         story="Two brown dwarfs (failed stars) orbiting each other, 12 light-years away. They move about "
               "4.7 arcseconds a year to the south-east. Too cool to shine much in visible light, they are "
               "brightest at SPHEREx's longest wavelengths: try the 4.4 to 5.0 micron band and the Methane lens."),
    dict(key="wise0855", name="WISE 0855", query="WISE J085510.83-071442.5", band=6, field=0.06,
         kind="Coldest known brown dwarf",
         story="The coldest known brown dwarf, about as cold as the North Pole, only 7.4 light-years away. "
               "It is nearly invisible at short wavelengths and shows up near 4.5 microns. Open the Methane lens: "
               "it is the one red dot in the field, because methane in its air darkens it at 3.3 microns. In "
               "Difference view it shows as a blue/red pair as it crawls west (to the right) about 8 arcseconds a "
               "year. Right now it is passing a faint background star, so its spectrum shows both: the star's light "
               "at short wavelengths and the brown dwarf's bump at 4 to 5 microns."),
    dict(key="rwaur", name="RW Aurigae", query="RW Aur", band=0, field=0.06,
         kind="Young variable star",
         story="A young star still surrounded by its planet-forming disk; dust in the disk passing in front of "
               "it makes its brightness jump around. Click it: it is too bright for SPHEREx's centre pixels, so "
               "the tool measures its outer glow. Between Sep 2025 and Sep 2026 its glow at 3 to 5 microns (the "
               "warm-dust wavelengths) faded to about half, while the short wavelengths barely changed."),
    dict(key="rdra", name="R Draconis", query="R Dra", band=0, field=0.06,
         kind="Pulsating giant",
         story="An old red giant that swells and shrinks every 8 months or so (a Mira variable). Click it: the "
               "June 2025 pass is clearly brighter than the November 2025 and June 2026 passes across most of the "
               "spectrum, a change much bigger than the measuring uncertainty. Note the wavy shape: that is water "
               "vapour in the giant's cool outer layers."),
]
