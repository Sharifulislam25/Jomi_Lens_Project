# Known issues, limits and next steps

## Limits by design
- **No official boundaries or records.** Everything legal-looking is synthetic. Boundary types are labelled (`synthetic_demo`, `user_drawn`, `approximate_feature`); `official_verified` is never used because no authenticated source is loaded.
- **A mapped building or land-use polygon is not a parcel.** Open land is often unmapped, so many places have nothing to select. Use **Draw a plot** for those.
- **Synthetic parcels sit on real land.** Their outlines, records and asking prices are fictional; the imagery at that location is real. DV-011 is placed in Joydebpur where open Sentinel-2 imagery shows visible surface change between December 2018 and December 2025 (vegetation cleared, bright new surfaces).
- **The issuer is simulated.** The Ed25519 key is derived from a public string so the demo is reproducible. Signatures demonstrate the mechanism; they carry no legal authority. A real deployment needs issuer-controlled keys, key rotation and an independently anchored ledger head.
- **The case, khas/acquisition and encumbrance (mortgage) registers are synthetic.** "No entry" is meaningful only where the register covers the parcel (otherwise UNAVAILABLE).
- **Imagery.** Sentinel-2 is 10 m per pixel: a 40 m parcel is about 16 pixels, so plot-level percentages are rough (the app warns and also shows the whole-view change as a noise baseline). Haze and atmosphere can mimic change (one 2018 scene is visibly hazy). The optional Esri viewer uses release dates, not capture dates, is not open data, and should be checked against Esri's terms before any public or commercial use.
- **Change analysis is a screening tool**: colour differences between dates. It reports "possible surface change", never construction or legal status.
- **Land-use labels are rule-based** (mapped OpenStreetMap features plus a greenness hint). Confidence is not reported because it has not been calibrated. No machine-learning model is used.
- **Hash and signature scope.** A match means the file equals the copy that was signed; it does not prove the content is true or legally effective.
- **Bangla is partial.** Navigation, headings, buttons, statuses, check names, overall summaries and disclaimers are translated; scenario text, evidence tables, per-check explanations and the PDF are English (the built-in PDF fonts cannot shape Bangla conjuncts).

- **Boundary overlap compares only the synthetic register.** Real neighbouring parcels are unknown; an overlap with an OpenStreetMap feature is not a legal overlap.
- **The voice summary depends on the device.** It uses the browser's speech synthesis. Many desktop browsers have no Bangla voice; the button then says so instead of reading Bangla with an English voice. It was checked in a headless browser for rendering only, not for audio.
- **The traffic light adds no judgement of its own.** It is a colour for the statuses already shown; green means "nothing found in the checked synthetic records", not clean title.

## Technical issues
- Place search and imagery need internet (first imagery fetch 10 to 30 s). Everything else works offline. Cached tiles/scenes are stored under `cache/`.
- The national outline used to test "inside Bangladesh" and the Gazipur Sadar boundary are generalised (about 0.4 km); a 0.5 km margin is allowed at the national border.
- The OpenStreetMap extract has closed ways only: large parks and water bodies mapped as multipolygon relations are missing, so land-use and water counts are low. Most of the map is buildings.
- Place search outside the focus area is refused; Nominatim rate-limits quickly (HTTP 429), and Photon is the fallback.
- SQLite is shared by all sessions of one running app (synthetic data only). Citizens see only their own runs, reports and messages; admins see everything. User-drawn plots are never written to the database.
- Sign-in lives in the Streamlit session of one browser tab: reloading the page signs you out. There is no "remember me", no e-mail password reset (no e-mail is collected) and no two-factor login; an admin resets passwords to a one-time temporary password.
- The lockout is per username, so someone could lock a known username for 15 minutes by guessing wrong. A real deployment would add per-IP rate limits and a CAPTCHA.
- Changing the database schema deletes and reseeds the demo database (including accounts, reports and messages). Fine for a demo, not for real data, which would need migrations.
- The GIS editor changes only the synthetic outline. It does not change any record or signed document; verification must be re-run. Editing is by mouse or typed coordinates, so accuracy is a few metres at best.
- Reading Sentinel-2 uses GDAL over HTTPS. Behind a proxy with its own certificate, point `SSL_CERT_FILE` (or `CURL_CA_BUNDLE`, `REQUESTS_CA_BUNDLE`) at the CA bundle; the app passes it to GDAL. There is no switch that turns TLS verification off (an earlier opt-in switch was removed).
- OpenStreetMap place search uses the public Nominatim service (rate-limited; Photon is the fallback).
- Tests do not call live network services; the live Sentinel-2 and OpenStreetMap paths were verified manually in a browser, not by the automated suite.
- A few unused imports remain in `tools/` and `tests/` (pyflakes).

## Provenance
See `docs/provenance/README.md`: part of the verification engine and database schema was found as uncommitted work in the working folder; the assistant's overwrite of an untracked file (`registry_crypto.py`, never in Git) is documented there.

## Next steps
1. Authorised access to real registers (no scraping) and issuer-side signing at registration.
2. Validated change detection (Sentinel-2 indices with reviewed ground truth) and calibrated land-use classification.
3. Flood and erosion layers for a chosen parcel.
4. Full Bangla coverage, including the PDF (HarfBuzz-based shaping).
5. PostgreSQL/PostGIS with schema migrations, persistent sign-in (secure cookies), per-IP rate limiting and two-factor sign-in for admins.
6. Usability testing with ordinary buyers, women and older people.
