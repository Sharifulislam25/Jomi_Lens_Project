# Demo script (about 3 minutes; rulebook maximum for the Round 1 video)

Say once at the start: *"Everything about records is synthetic, including the prices. This is a prototype, not an official record or legal advice."* Both students should be able to present any step.

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00 | **Overview** (signed out) | Show hero, red disclaimer, the two doors. | "Before buying land in Joydebpur, a buyer wants four answers: whose is it, what is its mutation history, is there a case, is it khas or being acquired. JomiLens Verify checks all four on synthetic data." |
| 0:12 | **Citizen Login** | Sign in as `citizen` / `JomiCitizen#2026`. | "Citizens sign in with a nickname. We never ask for a phone number, NID or e-mail. Admins have their own door; this one refuses them." |
| 0:22 | **Find a land** | Type `hospitl` (misspelt), then `540`. | "Search forgives spelling mistakes in words, never in numbers. A landmark lists demo parcels nearby; a dag number finds every record that uses it." |
| 0:35 | **Explore Joydebpur** | Map opens near the junction. Point at the legend, click a pink parcel. | "Pink dashed is a synthetic demo parcel. Orange outlines are OpenStreetMap buildings: approximate features, not parcels." Click **Open this parcel's profile**. |
| 0:45 | **Parcel profile** (DV-003) | Mouza, fictional price per decimal, **Open in Google Maps**. | "Mouza, asking price per decimal, and one tap to Google Maps. Calculated area comes from geometry, recorded area from records." |
| 0:55 | **Verification** (DV-003) | **Run verification**, point at the red card, press 🔊. | "A traffic light a citizen understands, read aloud in Bangla if the phone has a Bangla voice. Below it, ten checks. Records conflict: the khatian says 7.5 decimal, the deed 5.0." |
| 1:10 | **Verification** (DV-018, then DV-015, DV-016, DV-025) | Switch and run each. | "An altered deed with a replaced hash: the plain hash passes, the issuer signature and ledger catch it. A pending case: red. Notified acquisition: blue. Active bank mortgage: amber." |
| 1:35 | **Satellite & land use** (DV-011) | Fetch (cached before the demo), drag the slider. | "Open Sentinel-2, same dry season every year since 2018, real capture dates. Here vegetation was cleared and new bright surfaces appeared. At 10 m per pixel this is screening, not proof." |
| 1:50 | **Report** | Generate, download, show page 1 and click the Google Maps link. | "One PDF for this parcel and this run, with sources, uncertainty and what a human must still check." |
| 2:00 | **Inbox → Report a problem** | Choose DV-011, "Map location is wrong", write one line, send. | "If the map looks wrong, the citizen reports it. It goes to the land-office team, and the answer comes back here." |
| 2:12 | **Admin Portal** (new tab or after signing out) | Sign in as `admin`. Dashboard → **Reports & messages**: set the report to *in review* with a note. | "Staff work in a separate portal with 2-hour sessions. Changing the status messages the citizen automatically." |
| 2:25 | **GIS coordinate editor** | Open DV-011 from the report, *Move whole parcel* 2 m east (or drag a corner), write a reason, **Save**. Then try copying a neighbour's outline to show the refusal. | "Admins can correct where a parcel sits: drag, click, type coordinates or move by metres. A save that creates new overlap or leaves Gazipur Sadar is refused." |
| 2:40 | **Audit log** → **Send notification** | Show the edit with old and new outline; send a notice to everyone. | "Every sign-in, edit and message is logged. Notices reach one person or everyone." |
| 2:52 | Close | Overview. | "Next: authorised access to real registers and issuer-side signing at registration." |

Preparation: run with internet once and open DV-011's satellite page so imagery is cached; keep `streamlit run app.py` running; open the admin portal in a second browser window (each tab has its own sign-in); know DV-001 to DV-025 (see `docs/DEMO_SCENARIOS.md`). For the Final Round the rulebook allows 5 minutes of pitch and live demo plus 3 minutes of Q&A, and a pitch deck of at most 10 slides (not included here).
