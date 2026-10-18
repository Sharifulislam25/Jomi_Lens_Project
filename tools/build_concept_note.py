"""Builds docs/CONCEPT_NOTE.pdf (rulebook: PDF, at most 4 pages). Team facts are PLACEHOLDERS: fill them in before submitting."""
import sys
from pathlib import Path
from xml.sax.saxutils import escape as esc

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parent.parent / "docs" / "CONCEPT_NOTE.pdf"
NAVY = colors.HexColor("#0b3c5d")
ss = getSampleStyleSheet()
B = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.3, leading=12.2, spaceAfter=3)
H = ParagraphStyle("h", parent=ss["Heading2"], fontSize=11.5, textColor=NAVY, spaceBefore=7, spaceAfter=3, keepWithNext=1)
S = ParagraphStyle("s", parent=B, fontSize=8.2, leading=10.4, textColor=colors.HexColor("#555555"))
T = ParagraphStyle("t", parent=ss["Title"], fontSize=17, textColor=NAVY, spaceAfter=2, alignment=0)
BUL = ParagraphStyle("bul", parent=B, leftIndent=11, bulletIndent=2, spaceAfter=1.5)


def P(x, st=B):
    return Paragraph(esc(x), st)


def M(x, st=B):
    return Paragraph(x, st)


def bullets(items):
    return [Paragraph(esc(i), BUL, bulletText="•") for i in items]


def tbl(rows, widths, head=True):
    t = Table([[Paragraph(esc(c), S if i else ParagraphStyle("th", parent=S, textColor=colors.white)) for c in r] for i, r in enumerate(rows)], colWidths=widths, repeatRows=1)
    st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#adb5bd")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    if head:
        st.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    t.setStyle(TableStyle(st))
    return t


story = [
    Paragraph("JomiLens Verify", T),
    M("<b>LandTech 2026 concept note</b> · Track: Digital Land Records, Verification &amp; Digitization · <b>Problem statement P5: Citizen Pre-Purchase Verification</b>", B),
    P("Prototype for demonstration only. Not an official land record, legal opinion, ownership certificate, or proof of title. All demo parcels, records and documents are synthetic.", S),

    P("1. The problem in the Bangladesh context", H),
    P("Land disputes are among the most common civil cases in Bangladesh. The rulebook traces many of them to forged deeds, conflicting khatians across survey generations (CS, SA, RS, BS) and "
      "records split between the sub-registry office (registration) and the AC Land office (mutation). A citizen about to buy a plot rarely has a neutral way to see, in one place, whether the "
      "documents they are shown agree with each other, whether the same plot has been offered twice, whether a copied deed is the one originally recorded, whether a case or an acquisition notice "
      "is attached, and what the land physically looked like over time. Checking therefore depends on brokers and personal connections, which favours people who already have them."),
    P("Reports collected by the team describe the scale: a study reported by The Daily Star (date not stated on the page) found about one household in seven involved in a land dispute, and a UNB "
      "report of 4 April 2026 says about 80 percent of civil and criminal cases are land-related. The same report describes digitised services (online mutation, QR-coded khatians) and drone-based "
      "digital survey maps. These are secondary sources and will be re-verified before the final. Digitisation exists on the state side; what is missing for a buyer is an independent, plain-language "
      "cross-check that never claims to replace it. We pilot in Joydebpur (Gazipur Sadar, Gazipur), a fast-growing area beside Dhaka where farmland is turning into housing and land changes hands quickly."),

    P("2. The proposed solution", H),
    P("JomiLens Verify is a map-based \"check before you buy\" tool. It keeps four things strictly apart: (1) physical geography (open satellite imagery and mapped features), (2) official legal parcel "
      "records (not available in the prototype and never faked), (3) ownership evidence (fictional records used to demonstrate checks) and (4) inferred land use (rule-based and labelled preliminary). "
      "A citizen signs in with a nickname (no phone, NID or e-mail), explores Joydebpur or searches by dag, khatian, mouza or landmark, selects a parcel (a synthetic demo parcel, a user-drawn polygon or a mapped feature, each labelled), reads its profile, sees a traffic-light summary (also read aloud in Bangla) and runs ten checks and downloads a PDF that states "
      "results, evidence, sources, uncertainty, a Google Maps link and the human steps still required. If something looks wrong, the citizen reports it and talks to the support team in an inbox. Staff use a separate Admin Portal to answer reports, correct parcel coordinates on a map (every change audit-logged), manage accounts and send notices. The overall status is PASS only if every check ran and passed; a missing register is UNAVAILABLE, never a pass."),
    tbl([["What P5 asks for", "Checks that cover it"],
         ["Ownership", "Record consistency (dag, khatian, area with unit conversion, tolerance) · Conflicting and duplicate sales, rapid transfers, last buyer vs recorded holder · Boundary overlap with other registered parcels"],
         ["Mutation history", "Registration (sub-registry) vs mutation (AC Land): party, order, deadline · Survey chain CS to SA to RS to BS: declared lineage, area drift"],
         ["Pending cases", "Case register (synthetic): a pending case that restricts transfer is a conflict; no coverage means UNAVAILABLE"],
         ["Khas or acquisition status", "Khas / vested / acquisition register (synthetic): notified or completed entries are conflicts; proposed ones need review"],
         ["Buyer risk: mortgage or lien", "Encumbrance register (synthetic): active mortgage or lien needs review; a court attachment is a conflict"],
         ["Track: forged or altered documents, tamper-proof validation", "SHA-256 integrity · Ed25519 issuer signature (simulated issuer) · hash-chained append-only ledger · QR code that anyone can check offline"]],
        [4.3 * cm, 12.9 * cm]),

    P("3. Architecture and technology", H),
    P("Python 3.12 and Streamlit (interface, English and Bangla); Folium/Leaflet (maps); SQLite (synthetic registry; the data layer is structured so it can move to PostgreSQL/PostGIS); Shapely and PyProj "
      "(validated geometry, equal-area measurement); cryptography (Ed25519), qrcode and OpenCV (QR); ReportLab (PDF); pytest (168 automated tests). Accounts: scrypt-hashed passwords, separate citizen and admin sign-in, lockout after repeated failures, short admin sessions. The verification engine is a set of pure functions "
      "with no UI or database, so every rule is testable and explainable. Results are bound to the parcel that produced them and discarded when the parcel changes; runs are saved append-only."),
    P("Open data only: OpenStreetMap (about 28,000 buildings and other areas in the Joydebpur focus area), the BBS/OCHA Gazipur Sadar boundary, and Copernicus Sentinel-2 imagery (free, full and open licence). For each year "
      "the app picks a low-cloud scene from the same dry season (December to February) with its real capture date, so changes are more likely to be real. A high-resolution Esri viewer is optional, "
      "clearly marked as not open data. No government portal is queried, scraped or downloaded from, and no real personal data is used."),

    P("4. Key features", H),
] + bullets([
    "Joydebpur exploration with honest coverage levels: geographic exploration, mapped features (not parcels), and 25 verification-ready synthetic parcels in five fictional mouzas with fictional asking prices. No cadastral completeness is claimed.",
    "Smart search that forgives spelling mistakes in words (never in numbers); problem reports, a citizen-support inbox and admin notifications; an audit-logged GIS coordinate editor.",
    "Parcel profile that separates calculated geometry from recorded area, shows the boundary source, surveys, registers and data limits.",
    "A traffic-light summary a citizen can read or hear in Bangla, above ten checks per parcel, each with status, evidence, limitations and a plain-language meaning; QR verification of a document against a file; a ledger view.",
    "Open satellite history with before/after slider, resolution and noise warnings; cautious wording (\"possible surface change\"); rule-based land-use label with no invented confidence score.",
    "PDF report for the current parcel and current run, with report ID, sources, uncertainty and a human verification checklist; stale or mixed results are refused.",
    "Bangla interface for navigation, headings, statuses and check names.",
]) + [
    P("5. Plan for countrywide implementation", H),
    P("Phase 0 (now): Joydebpur pilot on synthetic fixtures and open data. Phase 1: a written data-sharing agreement with the land administration for read-only, authorised access to cadastral boundaries "
      "and the case, khas and acquisition registers (no scraping), and issuer-side signing of each deed at registration so a citizen can verify a copy; link to the e-Mutation workflow. Phase 2: Dhaka and other "
      "city corporations, with parcel identities mapped across survey generations (CS/SA/RS/BS/BDS) and tolerant of renumbering. Phase 3: national roll-out on PostgreSQL/PostGIS with vector tiles, "
      "scheduled imagery jobs, Bangla and low-bandwidth/SMS access. Governance throughout: privacy by design, role-based access and audit logs for any real data, published accuracy tests, human "
      "review before any result is relied on, and open-source release so others can inspect the rules."),

    P("6. Limits we state openly", H),
    P("No official boundaries or records are used. A mapped building is not a parcel. Satellite imagery shows physical conditions, not ownership. A hash or signature match shows a file equals the copy "
      "that was signed by a simulated issuer, not that it is genuine or legal. Sentinel-2 is 10 m per pixel, so small parcels cover only a few pixels (the app warns). Land-use labels are preliminary and uncalibrated."),

    P("7. Team and mentors", H),
    tbl([["Role", "Name / affiliation"],
         ["Team name", "[TEAM NAME: fill in]"], ["Student 1 (Team Leader)", "[NAME, DIU ID or alumni proof: fill in]"], ["Student 2", "[NAME, DIU ID or alumni proof: fill in]"],
         ["Faculty mentor", "[NAME, department: fill in]"], ["Industry mentor", "[NAME, organisation: fill in]"]], [5 * cm, 12.2 * cm]),
    P("Repository, README (setup, data sources, AI-tool disclosure), demo video script and scenario list accompany this note. AI coding assistance (Claude) is disclosed in the README.", S),
]

doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=1.9 * cm, rightMargin=1.9 * cm, topMargin=1.6 * cm, bottomMargin=1.5 * cm, title="JomiLens Verify concept note", author="[TEAM NAME]")
doc.build(story)
n = len(PdfReader(str(OUT)).pages)
print(f"{OUT.name}: {n} page(s)")
sys.exit(0 if n <= 4 else 1)
