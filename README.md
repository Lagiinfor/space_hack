# SPHEREx Sky Flip-book (runs on your own computer)

*Every pixel is a spectrum, every spectrum has a history.*

## Setting it up on a new Windows computer (first time only)

1. **Install Python.** Go to https://www.python.org/downloads/ and download Python 3.12 (or newer).
   Run the installer and, on its first screen, **tick "Add python.exe to PATH"** before clicking *Install Now*.
2. **Download this project.** On the project's GitHub page, click the green **Code** button, then
   **Download ZIP**. Right-click the downloaded ZIP, choose **Extract All…**, and put the folder somewhere
   easy, such as your Desktop. (If you use Git, `git clone` works too.)
3. **Start it.** Open the folder and double-click **start.bat**. The first time, it sets up Python's add-ons
   for this project (a private folder called `.venv`); this takes a few minutes and needs internet.
   After that it says "Ready!" and opens your browser.
   - If Windows shows "Windows protected your PC", click **More info**, then **Run anyway**.
   - If it says Python can't be found, reinstall Python and make sure "Add python.exe to PATH" is ticked.

The five tour targets open straight away: their stacked pictures are included. The single photos behind them
(needed for spectra, lenses and the mover search) are not included, to keep the download small; the first time
you open a tour target, the tool fetches them from NASA in the background (2 to 4 minutes per target). Clicking for a
spectrum during that time just waits until they are in.

To fetch them all up front instead, double-click **download_photos.bat** (about 4 to 15 minutes; safe to run again,
it skips photos you already have). Any new sky position you type in the app is downloaded from NASA automatically.

## How to start it (every time)

1. Open the `spherex-sky-tool` folder.
2. Double-click **start.bat**. A black window opens; after a few seconds it says "Ready!" and your browser opens
   at http://127.0.0.1:8000. If the tool is already running, it just opens the browser.
3. Keep the black window open while you use the tool. Close it to stop.

Only your computer can see it; nothing is published.

## What you can do

A full plain-language guide is built into the app: click **📖 Guide** at the top right (or open http://127.0.0.1:8000/guide.html).

| Feature | How |
|---|---|
| **Guided tour** | Click one of the five NASA test targets (top right). They are saved on your computer, so they open instantly. |
| **Any position** | Type `269.4464 4.7686`, `17 57 47.1 +04 46 07`, or a name like `RW Aur`, then press **Show**. The first visit to a spot downloads every SPHEREx image of it (2 to 4 minutes); after that it opens instantly. |
| **Field of view** | 2.4′, 3.6′, 6′ or 9′. Bigger shows more sky (good for fast movers) but downloads more. |
| **Fair flip-book** | One picture per ~6-month sky pass, per detector (wavelength band). Every frame in a band covers the same wavelengths, so only real changes blink. |
| **Blink controls** | Play/pause (space bar), step (arrow keys), speed, brightness, faint-star lift, blink all passes or just first ↔ last. |
| **Difference views** | *Difference*: each pass minus the average (red = brighter, blue = fainter; a mover is a red/blue pair). *Change since first pass*. *All passes added*: the deepest picture. Press **d** to toggle. |
| **Click for spectrum** | Click any object. You get its brightness at every wavelength in every exposure, one curve per sky pass, with molecule bands marked. The measurement *follows* moving objects pass by pass, and reports how far and which way they moved. |
| **Molecule lenses** | False-colour views from chosen wavelength windows: Infrared colour, Methane, Water ice, CO₂/CO. Ordinary stars come out white; anything coloured has unusual chemistry. WISE 0855 and Epsilon Indi B (brown dwarfs) come out red in the Methane lens. |
| **Automatic mover search** | Runs on every position. Finds every point of light in each pass, links them, flags anything that moved steadily well beyond the field's own wobble, and checks it against Gaia: *known* (Gaia predicts it) or *candidate* (nothing explains it). Arrows on the picture (4x longer than the real motion so they're visible). On the tour: Barnard's Star and Epsilon Indi B come out *known*; WISE 0855 (not in Gaia) comes out as a *candidate*, found with no hint; RW Aurigae and R Draconis show no movers. Search code: the team engine's `spx/movers.py`. |
| **Gaia overlay** | Circles where ESA's Gaia catalogue predicts each star on the date of each pass (proper motion + parallax). Fast movers get a dashed path. Press **g** to toggle. |
| **Problem flags** | Tint pixels the archive flagged (saturation, cosmic rays, ghosts, satellite streaks, bad pixels, afterimages) in the pass on screen. |
| **Exposure list** | Under "This position": every exposure in the frame on screen, with its date, detector and the wavelength it saw here. |
| **Share / save** | *Copy share link* (the link reopens the exact view: position, field, band, mode, lens, Gaia), *Save picture* (PNG), *Save animation* (GIF). |

### Links you can type or embed

`http://localhost:8000/?ra=331.097&dec=-56.8008&field=0.06&band=6&view=diff&gaia=1`

Parameters: `ra`, `dec` (degrees), `field` (degrees: 0.04, 0.06, 0.1, 0.15), `band` (0 = all, 1-6 = detector),
`view` (`normal`, `diff`, `first`, `stack`), `mode=lens` with `lens` (`color`, `methane`, `ice`, `co2`), `gaia=1`.

## Things to know (honest limits)

- **Very bright stars are burnt out (saturated)** in SPHEREx: Barnard's Star, RW Aurigae and R Draconis. Their pictures
  and motion look fine. For their spectra the tool automatically measures the star's *outer glow* (a ring 18–37″ out,
  which is not saturated), the same way in every exposure, and says so. These numbers are not total brightness, but
  passes can be compared. Check on Barnard's Star (which should not change): its glow agrees between passes to about
  5–10% at most wavelengths, up to ~25% at the shortest ones (the star's blur shape differs a little by season).
  R Draconis fades by about half at 1 µm across the three passes, far more than that. A proper fix is to fit the
  star-shape model shipped in each file (the EPSF layer we currently skip downloading).
- **Name lookups** give a catalogue position for the year 2000; the tool moves it forward to 2026 using the object's
  known motion. Typed-in coordinates are used as they are, so for a fast mover type its present-day position.
- **Spectrum brightness** is measured in a 12″ circle with the sky around it removed. It is right for comparing passes
  and wavelengths, but not a calibrated total brightness (some light falls outside the circle, more at long wavelengths).
- **Lens colours** are balanced so typical stars are white, using the stars in that field. In a field with few stars the
  balance is rougher.
- If NASA's archive is busy, a request can fail; just press **Show** again. Results that came from a partial archive
  answer are not kept, so the next visit tries again.

## What is where

| File | Job |
|---|---|
| `download_photos.bat`, `scripts/download_photos.py` | Download all NASA photos for the tour targets (or any position) ahead of time. |
| `start.bat`, `scripts/launch.py` | One-click start: sets up Python packages on first run, waits until the tool is ready, then opens the browser. |
| `server/app.py` | The small local web server the page talks to. |
| `web/index.html`, `web/app.js`, `web/style.css` | The page: search, player, lenses, spectrum plot, overlays. `web/vendor/plotly.min.js` draws the spectrum plot (stored locally so it works offline). |
| `spx/flipbook.py` | The whole chain for one position: find images, download, stack per pass and band, package. |
| `spx/analysis.py` | On-demand extras: spectra, lenses, problem-flag maps, Gaia predictions, mover search. |
| `spx/movers.py` | Blind mover search, copied unchanged from the team engine package. |
| `spx/archive.py` | Talks to NASA's IRSA archive (SIA search, cutout downloads with retries). |
| `spx/frames.py` | Cleans each image (bad pixels, sky glow), groups by sky pass, stacks per detector. |
| `spx/resolve.py` | Names and coordinates to positions, moved forward for proper motion. |
| `spx/tour.py`, `scripts/prebuild.py` | The five test targets, and the script that downloads them ahead of time (`.venv\Scripts\python scripts\prebuild.py`). |
| `spx/wave_tables/` | Each detector's wavelength map (fixed hardware calibration), stored once. |
| `spx/astrometry.py`, `scripts/barnard_demo.py` | Star position measurement and the Barnard's Star proof from the first step. |
| `data/` | Everything downloaded and computed, per position. Safe to delete; it will be downloaded again when needed. |

## Changes made on top of the cloud proof package (`spherex-flipbook`), for merging back

1. **Image-layers-only download** (`archive._stream_image_layers`): each cutout file is ~4 MB, almost all of it a
   star-shape table (EPSF) we don't use yet. We stream the file and stop at the first table, keeping IMAGE, FLAGS,
   VARIANCE and ZODI (~130 KB). About 30x less data; a whole target is ~45 MB instead of ~1.4 GB.
2. **Stored wavelength tables** (`frames._wave_table`, `spx/wave_tables/D1-6.fits`): the WCS-WAVE table that maps
   detector pixel to wavelength is identical in every file of a detector, so it is stored once and attached to the
   slimmed files.
3. **Archive robustness**: "Server busy" replies are retried; if one data release fails to answer, the others are used
   and the incomplete list is not cached.
4. **Spectra that follow movers** (`analysis._follow`): per pass, the object is re-found in that pass's stack before
   measuring, so Barnard's Star or WISE 0855 are measured where they are, not where they were.
5. **Name lookup with motion** (`resolve.py`): CDS Sesame plus proper motion, moved from the year 2000 (SIMBAD's
   position date) to 2026.2. Note: the WISE 0855 coordinates in the challenge text (08h55m10.831s −07°14′42.53″) are
   from around 2014; by 2026 it has moved about 1.6′ west, outside a small field centred on those numbers. The tour
   uses its 2026 position.
6. **Windows file locking**: cutouts are read without memory-mapping so cached files can be deleted while the
   server runs.

## Fairness and quality checks (after the outside code review, 14 Nov 2026)

- **Same wavelength mix in every pass.** Each detector's range is cut into 6 narrow slices; each slice is stacked on
  its own and a frame is the plain average of the slices every well-covered pass has. Passes that miss slices or have
  too few photos are left out of the blink or labelled "limited comparison". "All colours" says how many detectors it
  averaged (only those fairly comparable in every pass).
- **No invented pixels.** Only small holes fully surrounded by data (burnt-out star centres) are filled; anything else
  stays "no data" and is drawn hatched.
- **One-off glitches thrown out.** Within a pass and detector, a pixel far brighter than all other photos agree on
  (cosmic ray, satellite glint, afterimage) is discarded before stacking. This removed the "blob" Lavi found near
  WISE 0855 in May 2026: it came from 1 of 99 photos (flagged TRANSIENT) plus 2 afterimages (flagged PERSIST); no known
  asteroid was there (checked with IMCCE SkyBoT).
- **Honest completeness.** A result is saved as complete only if every listed photo was downloaded and read; otherwise
  missing photos are retried on the next visit. Saved results carry a version number and build date and are rebuilt
  when the stacking method changes.
- **Spectra use the wavelength at the clicked spot**, follow movers, mark one-off bad photos, and separate
  "burnt-out centre" from "off the edge".
- **Automatic checks:** `.venv\Scripts\python scripts\self_test.py` (constant star stays constant, missing data is not
  filled, glitches removed, RA wrap, steady field star within 5%, Barnard's Star and Eps Indi B found as known movers,
  WISE 0855 found as a candidate, no false movers on RW Aur and R Dra).

Not done yet: a "check NASA for newer photos" button (saved results do record their date), and passes are still split
by 60-day gaps (fine for SPHEREx's real schedule; an unusual observing pattern could merge passes).
