"""The five test targets from the NASA challenge, used for the guided tour.
Positions are carried forward to 2026.2 (see resolve.py) so each object sits in the middle."""

TOUR = [
    dict(key="barnard", name="Barnard's Star", query="Barnard's star", band=3, field=0.1, other=True,
         kind="Fast-moving star",
         story="The fastest-moving star in our sky, 6 light-years away. It crawls about 10 arcseconds "
               "north each year. Switch on 'Older photos (2010 →)' and the timeline starts with older photos from two other telescopes: NASA's WISE "
               "in 2010 and Canada's NEOSSat in 2019, then SPHEREx in 2025 and 2026. Watch the star march "
               "upward across 16 years (about 2.7 arcminutes). Without 'Older photos', choose 'Changes "
               "only' for the fair SPHEREx-only comparison: a red/blue pair that flips."),
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
    # ---- "More to explore": extra showpieces, each tested in SPHEREx data (14 Nov 2026)
    dict(key="luhman16", name="Luhman 16", query="Luhman 16", band=6, field=0.06, group="extra",
         kind="Nearest brown dwarfs",
         story="The closest brown dwarfs to the Sun, a pair 6.5 light-years away, only found in 2013. They are too "
               "red and faint for Gaia's catalogue, so the tool's automatic search flags them as a CANDIDATE mover "
               "at 2.8 arcseconds a year, exactly their known speed: a rediscovery with no hint. Their light peaks "
               "near 4 microns, the signature of a cool brown dwarf."),
    dict(key="kapteyn", name="Kapteyn's Star", query="Kapteyn's star", band=3, field=0.06, group="extra",
         kind="Runaway old star",
         story="One of the fastest stars on the sky, 8.6 arcseconds a year, 13 light-years away. It is an ancient "
               "star from the Milky Way's halo, cutting through our neighbourhood on a strange orbit. The search "
               "finds it as a KNOWN mover (Gaia predicts it); watch it hop between passes."),
    dict(key="m82", name="M82 (Cigar Galaxy)", query="M82", band=0, field=0.06, group="extra",
         kind="Starburst galaxy",
         story="A galaxy 12 million light-years away making stars ten times faster than the Milky Way. Open the "
               "Methane lens: the disk of stars looks blue-white, but a GREEN glow rises above and below it. That "
               "is the 3.3-micron light of tiny carbon-rich dust grains (PAHs) blown out of the galaxy by the "
               "starburst's wind. Nothing moves here, which is what a galaxy should do."),
    dict(key="barnard68", name="Barnard 68", query="Barnard 68", band=0, field=0.06, group="extra",
         kind="Dark cloud full of ice",
         story="A cold, dark cloud of gas and dust, a future birthplace of stars, 400 light-years away. It hides "
               "the stars behind it. Open the Water-ice lens: several stars seen through the cloud turn MAGENTA, "
               "because they lose light at 3 microns, where water ice absorbs. The ice coats dust grains inside "
               "the cloud: the raw material for comets and planets."),
    dict(key="eros", name="Eros, near-Earth asteroid", query="29.0314 28.7635", band=6, field=0.06, group="extra",
         kind="Asteroid caught in the act",
         story="On 13 January 2026 SPHEREx photographed the near-Earth asteroid 433 Eros as it crossed this spot, "
               "in 4 photos taken 2 minutes apart (8 with both detectors). Asteroids race across the sky, so Eros is "
               "only in those photos: the stacked flip-book leaves it out as a one-off, but the Asteroids panel "
               "finds it and plays its photos. NASA's published data says Eros is a near-Earth asteroid with no "
               "chance of hitting Earth in the next 100 years; its next close pass is in 2056, at 58 times the "
               "Moon's distance. (NASA's NEAR Shoemaker spacecraft landed on Eros in 2001.)"),
    dict(key="atlas3i", name="3I/ATLAS, interstellar comet", query="245.7594 -16.6614", band=2, field=0.06,
         group="extra", other=True,
         kind="Visitor from another star",
         story="Only the third object ever seen passing through our solar system from another star. In August 2025 "
               "both SPHEREx and Canada's NEOSSat photographed it. It is too faint and too fast to see in any single "
               "photo, so this view follows it: every photo is re-centred on where NASA's orbit says the comet was, "
               "then stacked. The dot at the centre mark is the comet, 25 to 47 times above the noise in SPHEREx and "
               "19 to 27 times in NEOSSat. Step through the dates: two telescopes, two countries, one visitor."),
]
