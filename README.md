# JomiLens Verify

**Citizen pre-purchase land verification for Joydebpur, Gazipur: prototype for LandTech 2026 (track: Digital Land Records, Verification & Digitization; problem statement P5).**

> **Prototype for demonstration only. Not an official land record, legal opinion, ownership certificate, or proof of title.**
> **All parcels, land records, surveys, cases, notices, signatures, transactions and documents are SYNTHETIC (fictional).** No real person, NID, phone number, address or actual land record is used.
> Scope: **the Joydebpur focus area of Gazipur Sadar, Gazipur** (about 5 x 5.5 km around Joydebpur junction, clipped to the upazila). Admins may digitise parcels anywhere in Gazipur Sadar.

## What it does
Sign in (citizen or admin, separate doors) -> explore a real map of Joydebpur or **search** by dag, khatian, mouza, parcel id or landmark -> select a synthetic demo parcel (or a user-drawn polygon / mapped feature, clearly labelled) -> read its profile -> see a **traffic-light safety summary** (with a Bangla voice button) above **ten checks** -> review open satellite imagery history and possible surface change -> download a PDF with results, evidence, sources, uncertainty, unresolved questions and a **Google Maps link** -> **report a problem** and message the support team.
Administrators answer reports and messages, correct parcel coordinates in a **GIS editor**, manage accounts, send notifications, and every admin action lands in an **audit log**.

| P5 / track need | Check(s) | What a result does NOT mean |
|---|---|---|
| Ownership | Record consistency; conflicting / duplicate sales (overlap, repeated sale, broken chain, rapid transfers, holder mismatch); **boundary overlap with other registered parcels** | not proof records are real or complete; not proof of fraud |
| Mutation history | Registration (sub-registry) vs mutation (AC Land); survey chain CS -> SA -> RS -> BS (declared lineage, area drift) | dag numbers are not compared across surveys (renumbering is normal) |
| Pending cases | Case register (synthetic) | absence of an entry counts only where the register covers the parcel, else UNAVAILABLE |
| Khas / acquisition | Khas / vested / acquisition register (synthetic) | same coverage rule |
| Forged / altered documents | SHA-256 integrity | a match is **not** proof of authenticity |
| Mortgage / lien | Encumbrance register (synthetic): active mortgage or lien needs review; court attachment is a conflict | same coverage rule; the loan terms decide what a buyer may do |
| Cryptographic validation | Ed25519 issuer signature (**simulated** issuer) + hash-chained append-only ledger + QR code | a valid signature shows the file equals what the simulated issuer signed, not that it is true or legal |

Statuses: `PASS`, `REVIEW_REQUIRED`, `CONFLICT_FOUND`, `UNAVAILABLE`, `NOT_RUN`. The overall status is `PASS` only when every check ran and passed.
The **safety summary** is derived only from those statuses: red (any conflict), blue (khas/acquisition conflict only), amber (review needed or partly unchecked), green (all passed; *not* proof of clean title), grey (nothing could be checked).
Find a parcel by **dag or khatian number** (normalised, every match listed) or by clicking the map (a click up to 25 m outside a small parcel still finds it; a click inside an overlap names every parcel).

## Run it
```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```
The synthetic database is created automatically on first run (`data/verify/verify.sqlite`); rebuild it with `python tools/seed_verify_db.py` (this also deletes accounts, reports and messages).
Maps, place search and imagery need internet; the demo parcels, records, checks, accounts, inbox and reports work offline.
Behind a company or campus proxy with its own certificate, set `SSL_CERT_FILE` (or `CURL_CA_BUNDLE` / `REQUESTS_CA_BUNDLE`) to its CA bundle: it is passed to GDAL for Sentinel-2. TLS verification is never switched off.

## Accounts and roles
| | Citizen | Administrator |
|---|---|---|
| Sign-in page | **Citizen Login** (`/citizen-login`) | **Admin Portal** (`/admin-portal`), a separate door |
| How accounts are made | self-registration with a nickname and password (no phone, NID or e-mail; values that look like them are refused) | only by the seed or by another admin |
| Demo account | `citizen` / `JomiCitizen#2026` | `admin` / `JomiAdmin#2026` (set `JOMILENS_ADMIN_PASSWORD` before the first run to choose your own) |
| Session length | 8 hours | 2 hours |
| Sees | Explore, Find a land, Profile, Verification, Satellite, Report, **Inbox**, Draw a plot, My account | Dashboard (stats, CSV exports), Reports & messages, **GIS coordinate editor**, Users, Send notification, **Audit log**, plus the citizen pages |

Each door refuses the other role. Passwords are hashed with scrypt (random salt per user) and compared in constant time; "wrong username" and "wrong password" give the same message; 5 failures in 15 minutes lock that username for 15 minutes.
A citizen sees only their own verification runs, reports and messages. Admins reset passwords to a one-time temporary password that must be changed at the next sign-in, and cannot disable themselves.
Logged events: sign-ins (successful, failed, locked), registration, account changes, report status changes, replies, notifications, parcel edits (with the old and new outline). Passwords are never logged.
CSV exports prefix cells that start with `=`, `+`, `-` or `@` so a spreadsheet cannot run them as formulas.
Streamlit keeps the sign-in in the browser tab's session: reloading the page signs you out (by design for this prototype).

## Feature checklist
| Feature | Where | Notes |
|---|---|---|
| Joydebpur, Gazipur demo data | `src/verify_seed.py` | 25 parcels in Demo Mouza 1 to 5 with dag, khatian, survey records and fictional asking prices (BDT, per decimal) |
| Separate citizen and admin sign-in | `src/accounts.py`, `src/ui_auth.py` | see above |
| Admin GIS coordinate editor | `src/parcel_admin.py`, `src/ui_admin_gis.py` | drag corners, click the map to place a corner, type lat/lng in a table, or move the parcel by metres; digitise new parcels (JL-0001...); retire/restore. Saves are refused outside Gazipur Sadar or when overlap with another parcel would grow; undo from history |
| Problem reports and messaging | `src/support.py`, `src/ui_inbox.py`, `src/ui_admin.py` | five categories; one private thread per citizen; status changes post a message to the citizen |
| PDF report with Google Maps link | `src/report_generator.py` | clickable link on the cover and in section 1; mouza and asking price |
| Multi-year satellite comparison | `src/sentinel.py`, `src/ui_satellite_verify.py` | Sentinel-2, one dry-season scene per year since 2018, real capture dates |
| Admin-to-user notifications | `src/support.py` | to one user or everyone; read state per user; unread badge in the sidebar |
| Audit log and user management | `src/vdb.audit`, `src/ui_admin.py` | filter, inspect details, CSV export; enable/disable, reset password, create accounts |
| Smart partial / fuzzy search | `src/search.py`, `src/ui_search.py` | substring and prefix matches on id, title, mouza, dag, khatian; dag numbers compared after normalising (`Dag No. 0125` = `125`); close spelling for words only, never for numbers; landmarks list demo parcels within 1.2 km |

## Tests and static checks
```bash
pip install -r requirements-dev.txt
python -m pytest tests -q          # last run: 168 passed
python -m pyflakes src app.py      # no undefined names
```
Covered: geometry (area, perimeter, units, invalid / self-crossing / malformed GeoJSON); all ten checks including boundary overlap, mortgage/lien, re-hashed forgery, tampered ledger, lineage break, rapid transfers; signatures, hash chain and QR codes;
state invalidation on parcel change; report content, PDF escaping and the Google Maps link; Joydebpur coverage; accounts, doors, lockout, password reset and session expiry;
problem reports, messages and notifications (including personal-data refusal); fuzzy search; the outline editor's overlap and boundary rules; CSV formula-injection guard; Sentinel-2 failure handling; Bangla text completeness; SQL-injection safety; no personal data in fixtures.
Not covered by automation: the live imagery and place-search services (checked manually) and visual layout. Both portals were clicked through in headless Chromium with Playwright (sign-in at the wrong door, search, report, message, verification, PDF, GIS save, notification, audit log).

## Architecture
```
app.py (st.navigation, English / Bangla)
 |- signed out: ui_verify_overview  ui_auth (Citizen Login | Admin Portal)
 |- citizen:    ui_landmap (Explore Joydebpur)  ui_search  ui_parcel  ui_verify  ui_satellite_verify  ui_verify_report  ui_inbox  ui_myplot  ui_auth (account)
 |- admin:      ui_admin (dashboard, users, reports & messages, notifications, audit)  ui_admin_gis  + the citizen pages
 +- core (no Streamlit): verification_engine  registry_crypto  geo_tools  landuse  vstate  privacy  i18n  accounts  support  search  parcel_admin  exporting
      data:    vdb (SQLite, parameterised SQL)  verify_seed (25 scenarios)  landmap (28k OSM areas, Joydebpur)  places (focus area, landmarks, search)
      imagery: sentinel (open, default)  wayback (Esri, optional)  real_analysis (comparison, kept separate)
      output:  report_generator (ReportLab; text escaped by default)
```
- **Data model** (`src/vdb.py`): parcels, land_records (incl. survey generations), transactions, document_hashes (signature, signer), ledger (per-parcel hash chain), issuer_keys, pending_cases, khas_acquisition, registry_coverage,
  imagery_observations, classifications, verification_runs (with the user who ran them), users, login_attempts, audit_log, problem_reports, messages, notifications, notification_reads. Runs are appended, never overwritten. Geometry is GeoJSON text, so the layer can move to PostgreSQL/PostGIS.
- **Geometry**: validated (finite, in range, >=3 distinct vertices, no self-intersection, non-zero area, inside Bangladesh by polygon test, size and vertex caps). Area is measured in a Lambert Azimuthal Equal-Area projection centred on the polygon with a geodesic cross-check.
- **Stale-result protection**: every result is stored with its parcel ID and dropped when the parcel changes; changed settings or uploaded files mark a run outdated and block the report.

## Coverage levels (honest labels)
1. **Geographic exploration:** the Gazipur Sadar boundary, the Joydebpur focus area, 29 landmarks, place search, imagery.
2. **Mapped features:** about 28,000 OpenStreetMap areas in the Joydebpur focus area (almost all buildings; few land-use and water areas because the extract has closed ways only). Approximate features, **not parcels**; open land is often unmapped.
3. **Verification-ready demo parcels:** 25 synthetic scenarios (`docs/DEMO_SCENARIOS.md`).
Not claimed: cadastral completeness, official boundaries, real ownership, legal validity or AI accuracy.

## Data sources, licences and attribution
| Data | Source | Licence / terms |
|---|---|---|
| Parcels, records, surveys, cases, notices, signatures, transactions, documents | Created by the project team (synthetic) | Project licence |
| Satellite imagery (default) | **Copernicus Sentinel-2 L2A** (ESA) via Element84 Earth Search and AWS Open Data | Free, full and open. "Contains modified Copernicus Sentinel data." |
| Mapped buildings, land use, water; landmarks; place search | OpenStreetMap contributors, via an Overpass API extract of the focus box (closed ways); two landmark coordinates from Nominatim; Photon | **ODbL 1.0** (attribution; the derived database `data/landmap/areas.sqlite` is a Derivative Database and is shared under the ODbL); Nominatim usage policy |
| Gazipur Sadar boundary, Joydebpur focus area | BBS / OCHA ROAP via geoBoundaries (generalised); focus box drawn by the team and clipped to the upazila | CC BY 3.0 IGO (ADM2, ADM3); CC0 (ADM1) |
| High-resolution viewer (**optional**) | Esri World Imagery and Wayback | **Not open data**: viewing only; check Esri's terms. Nothing from it is stored in this repository |
| Software | Streamlit, Folium/Leaflet, GeoPandas, Shapely, PyProj, OpenCV, ReportLab, cryptography, qrcode, rasterio, pystac-client, pyosmium, pytest | Open-source licences of each package |
No government portal was scraped, queried or bulk-downloaded. No live government API is used.

## Rulebook compliance checklist (sections 7 to 10)
- Synthetic data only; fixtures labelled in the database, UI and PDF. Asking prices are invented and labelled "not a valuation". Usernames, messages, reports and notifications refuse text that looks like a phone, NID or e-mail. My Plot rejects entries that look like NID numbers, phone numbers or e-mail addresses; real names must not be entered.
- No scraping or automated querying of any government portal; no security testing of any live system.
- Open-source libraries and open data with sources credited here. Esri imagery is optional and not bundled.
- Repository kept with its commit history; see **Git history** below. AI tools disclosed below.
- Concept note: `docs/CONCEPT_NOTE.pdf` (PDF, at most 4 pages). Demo video script: `docs/DEMO_SCRIPT.md`.

## AI tool disclosure
This project was developed with the help of **Claude** (a large language model by Anthropic), used as a coding and design assistant to draft and revise code, tests, fixtures and documentation, and to review the code against the rulebook.
**[TEAM: replace this paragraph with your own account of which parts you wrote, which parts the assistant drafted, and how you reviewed and tested them.]** Both student members must be able to explain every module.
Team: [TEAM NAME]; students [STUDENT 1], [STUDENT 2]; faculty mentor [NAME]; industry mentor [NAME].

## Changes since Round 1
Not applicable yet (first submission). Add a short summary here before the Final Round, as the rulebook requires.

### Ideas adopted from the team's React/Node/PostGIS blueprint (and what was left out)
Adopted, in the existing Python stack: click-to-identify with a small distance allowance (25 m, not 50 m; containment always wins), dag/khatian search,
overlap detection between registered boundaries (Shapely instead of PostGIS `ST_Intersects`), the "mortgaged" status (as a synthetic encumbrance register),
a traffic-light summary (worded so green never claims clean title), and a Bangla voice summary (browser speech synthesis).
Adopted later (October 2026, matching the team's MERN build): the Joydebpur focus area and grid, separate citizen and admin sign-in, admin user management,
audit log, problem reports, messaging, notifications and the coordinate editor, all re-implemented in Python.
Not adopted: citizen login by phone/NID and NID hashing (the rulebook forbids collecting real personal data, and the blueprint's demo account used a
real-format phone number; accounts here use nicknames), dispute overrides (no authority to model), the React/Node/PostGIS rewrite for this branch, and
the tile "fix" (Esri's tile URLs really are `{z}/{y}/{x}`; swapping them breaks the layer).

## Git history
The project was created in AI-assisted sessions before this repository existed, so the history begins at a baseline commit; later phases are separate commits (`git log --oneline`). Commits so far use a placeholder author; **from now on each student should commit under their own name**.
Do not rewrite or backdate history. `docs/provenance/README.md` documents one incident: uncommitted work found in the working folder, and an untracked file that was overwritten.

## Rebuilding data (optional)
```bash
python tools/seed_verify_db.py                          # synthetic Verify database + fixture documents + demo accounts
python tools/build_admin_lookup.py                      # district / upazila lookup from the bundled boundaries
python tools/build_landmap_from_extract.py              # pre-plotted OSM areas + landmarks from data/landmap/joydebpur_osm.json.gz
python tools/build_concept_note.py                      # regenerate docs/CONCEPT_NOTE.pdf
python tools/build_scenarios_doc.py                     # regenerate docs/DEMO_SCENARIOS.md from the engine
```
The OSM extract (`joydebpur_osm.json.gz`) was taken once from the Overpass API for the focus box; it contains closed ways only, so multipolygon relations (large parks, some water bodies) are missing.
