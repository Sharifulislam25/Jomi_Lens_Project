"""Builds the JomiLens PDF report with ReportLab. Uses only demo/prototype data."""
import io
from datetime import datetime
from pathlib import Path

from PIL import Image as PILImage
from reportlab.graphics.shapes import Drawing, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from src.real_analysis import GENERAL_MESSAGE

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports"
NAVY, ORANGE = colors.HexColor("#1d3557"), colors.HexColor("#f77f00")
NOT_AVAILABLE = "Not available in prototype dataset."
DISCLAIMER = ("JomiLens provides GIS, satellite imagery and automated analytical observations for "
              "informational purposes. The system does not determine legal ownership, title validity, "
              "legal boundary, or illegal possession. Potential anomalies and detected changes require "
              "verification against authoritative records and, where appropriate, physical/official inspection.")
CHECKLIST = ["Verify original deed", "Verify Khatian", "Verify mutation", "Verify land tax records",
             "Verify official survey map", "Verify physical boundary", "Verify neighboring boundaries",
             "Consult appropriate authority/professional where necessary"]

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], textColor=NAVY, fontSize=15, spaceBefore=6, spaceAfter=6, keepWithNext=1)
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9.5, leading=13)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=8, textColor=colors.HexColor("#555555"), leading=10)


def clean(text) -> str:
    """The built-in PDF fonts lack some symbols (e.g. arrows), so swap them for plain text."""
    return str(text).replace("→", "->").replace("–", "-").replace("≠", "!=")


from xml.sax.saxutils import escape as esc


def P(text, style=BODY):
    """Paragraph from PLAIN text: &, < and > are escaped, so user-controlled text can never break or inject markup."""
    return Paragraph(esc(clean(text)), style)


def PM(markup, style=BODY):
    """Paragraph from trusted markup (<b>, <br/>). Escape every inserted value with esc() first."""
    return Paragraph(clean(markup), style)


def google_maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps?q={float(lat):.6f},{float(lon):.6f}"


def price_text(price_bdt, area_decimal) -> str:
    if not price_bdt:
        return "not listed"
    per = price_bdt / max(float(area_decimal or 0), 0.01)
    return f"BDT {price_bdt:,.0f} (BDT {per:,.0f} per decimal). Invented for the demo; not a valuation."


def table(rows, col_widths=None, header=True):
    """A simple styled table. rows[0] is the header row when header=True."""
    t = Table([[c if isinstance(c, Paragraph) else P(c, SMALL if i else ParagraphStyle("th", parent=SMALL, textColor=colors.white)) for c in r]
               for i, r in enumerate(rows)], colWidths=col_widths, repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#adb5bd")), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    t.setStyle(TableStyle(style))
    return t


def pil_image(img: PILImage.Image, width_cm: float, max_h_cm: float = None):
    """Turn a PIL image into a ReportLab image of the given width (shrunk if it would be taller than max_h_cm)."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=82)
    buf.seek(0)
    w = width_cm * cm
    if max_h_cm and w * img.height / img.width > max_h_cm * cm:
        w = max_h_cm * cm * img.width / img.height
    return Image(buf, width=w, height=w * img.height / img.width)


def plot_layout_drawing(neighbours, selected_id):
    """Schematic top-down drawing of the plots (no basemap) from the demo geometry."""
    minx, miny, maxx, maxy = neighbours.total_bounds
    width, height = 470, 250
    pad = 20
    import math
    kx = math.cos(math.radians((miny + maxy) / 2))           # shrink longitude so shapes are not stretched
    span_x, span_y = max((maxx - minx) * kx, 1e-9), max(maxy - miny, 1e-9)
    scale = min((width - 2 * pad) / span_x, (height - 2 * pad) / span_y)
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#f1f3f5"), strokeColor=colors.HexColor("#adb5bd")))
    for _, r in neighbours.iterrows():
        pts = []
        for x, y in list(r.geometry.exterior.coords):
            pts += [pad + (x - minx) * kx * scale, pad + (y - miny) * scale]
        sel = r["plot_id"] == selected_id
        d.add(Polygon(pts, fillColor=ORANGE if sel else colors.HexColor("#a8dadc"),
                      strokeColor=colors.HexColor("#d62828") if sel else colors.HexColor("#457b9d"),
                      strokeWidth=2 if sel else 1))
        cx = sum(pts[0::2]) / len(pts[0::2])
        cy = sum(pts[1::2]) / len(pts[1::2])
        d.add(String(cx, cy, r["label"] if "label" in r.index else f"Dag {r['dag_no']}", textAnchor="middle", fontSize=8))
    d.add(String(width - 14, height - 16, "N", fontSize=11, textAnchor="middle", fontName="Helvetica-Bold"))
    return d


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#555555"))
    canvas.drawString(2 * cm, 1.2 * cm, "JomiLens prototype - synthetic data, informational only - not an official land record or legal proof")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.restoreState()


def points_drawing(points, label="Plot"):
    """Schematic drawing of one polygon given as [(lon, lat), ...]."""
    import geopandas as gpd
    from shapely.geometry import Polygon
    g = gpd.GeoDataFrame({"plot_id": ["X"], "dag_no": ["-"], "label": [label]}, geometry=[Polygon(points)], crs="EPSG:4326")
    return plot_layout_drawing(g, "X")


def generate_custom_report(case: dict) -> tuple:
    """PDF for a user-marked plot. case = {details, metrics, history (prepared real chips), compare}."""
    from src.real_analysis import with_outline
    from src.wayback import ATTRIBUTION
    d, m, hist, cmpd = case["details"], case["metrics"], case.get("history") or [], case.get("compare")
    now = datetime.now()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                            title="JomiLens Plot Report", author="JomiLens (prototype)")
    place = d.get("site_name") or ", ".join(x for x in [d.get("mouza"), d.get("upazila"), d.get("district")] if x) or "User-marked plot"
    s = [Spacer(1, 4 * cm),
         Paragraph("JOMILENS", ParagraphStyle("c1", parent=styles["Title"], fontSize=40, leading=48, spaceAfter=10, textColor=NAVY)),
         Paragraph("See Your Land. Understand Your Land.", ParagraphStyle("c2", parent=styles["Title"], fontSize=12, leading=16, textColor=ORANGE)),
         Spacer(1, 1.5 * cm),
         Paragraph("PLOT LOCATION &amp;<br/>SATELLITE HISTORY REPORT", ParagraphStyle("c3", parent=styles["Title"], fontSize=22, leading=28)),
         Spacer(1, 1.5 * cm),
         Paragraph(f"Generated: {now:%Y-%m-%d %H:%M}", ParagraphStyle("c4", parent=BODY, alignment=1, fontSize=11)),
         Paragraph(esc(clean(place)), ParagraphStyle("c5", parent=BODY, alignment=1, fontSize=11)),
         Spacer(1, 3 * cm),
         Paragraph(esc(d.get("source_note") or "Plot boundary and details were entered by the user and are not verified by JomiLens."),
                   ParagraphStyle("c6", parent=SMALL, alignment=1)), PageBreak()]

    s.append(P("1. Plot Information" if d.get("site_name") else "1. Plot Information (user-entered, unverified)", H1))
    if d.get("site_name"):
        s.append(PM(f"<b>{esc(str(d['site_name']))}</b>. {esc(str(d.get('source_note', '')))}"))
    s.append(table([["Field", "Value"], ["Division", d["division"] or "-"], ["District", d["district"] or "-"], ["Upazila", d["upazila"] or "-"],
                    ["Mouza", d["mouza"] or "-"], ["Sheet", d["sheet"] or "-"], ["Survey", d["survey"] or "-"], ["Dag", d["dag_no"] or "-"],
                    ["Khatian", d["khatian"] or "-"],
                    ["Recorded area", f"{d['recorded_area']} decimals" if d["recorded_area"] else "Not provided"],
                    ["Marked-boundary area", f"{m['area_sqm']} m2 | {m['area_decimal']} decimals | {m['area_katha']} katha | {m['area_bigha']} bigha"],
                    ["Perimeter", f"{m['perimeter_m']} m"]], [5 * cm, 11 * cm]))

    s.append(P("2. Precise Location", H1))
    c = m["centroid"]
    s.append(P(f"Plot centre: {c[0]:.6f}, {c[1]:.6f} (lat, lon)."))
    s.append(table([["Corner", "Latitude", "Longitude", "Latitude (DMS)", "Longitude (DMS)"]] +
                   [[x["n"], x["lat"], x["lon"], x["lat_dms"], x["lon_dms"]] for x in m["corners"][:40]], [1.6 * cm, 2.8 * cm, 2.8 * cm, 4.9 * cm, 4.9 * cm]))
    if len(m["corners"]) > 40:
        s.append(P(f"The outline has {len(m['corners'])} vertices; the first 40 are listed. The full list is available as CSV in the app.", SMALL))
    s.append(Spacer(1, 6))
    s.append(table([["From", "To", "Length (m)", "Bearing (deg)"]] +
                   [[x["from"], x["to"], x["length_m"], x["bearing_deg"]] for x in m["sides"][:40]], [2.5 * cm, 2.5 * cm, 4 * cm, 4 * cm]))
    s += [Spacer(1, 6), points_drawing(m["points"], "Marked plot"),
          P("Schematic outline of the marked boundary. Accuracy depends on how the corners were measured.", SMALL)]
    if hist:
        last = hist[-1]
        s += [Spacer(1, 6), pil_image(with_outline(last["raw"], last["poly_px"]), 11, 9),
              P(f"Real satellite view, version {last['date']}. Plot outline in yellow, corners numbered. {ATTRIBUTION}", SMALL)]

    s.append(P("3. Holder Information (user-entered, unverified)", H1))
    if d.get("site_name"):
        s.append(P("Not applicable: this is a public place shown for demonstration, not a land parcel. No ownership data is shown."))
    elif d["holders"]:
        s.append(table([["Holder", "Share", "Basis", "Note"]] +
                       [[h.get("Party label", ""), h.get("Share", ""), h.get("Basis (reference)", ""), h.get("Note", "")] for h in d["holders"]],
                      [4.5 * cm, 2 * cm, 6 * cm, 4.5 * cm]))
    else:
        s.append(P("No holder details were entered."))
    s.append(P("JomiLens does not look up or verify ownership. Compare with the official khatian, mutation and deed records.", SMALL))

    s.append(P("4. Real Satellite History", H1))
    if not hist:
        s.append(P("Historical satellite imagery was not fetched or is unavailable for this location."))
    else:
        cells = [[pil_image(with_outline(h["raw"], h["poly_px"]), 7.6, 6),
                  PM(f"<b>{esc(str(h['date']))}</b><br/>~{esc(str(h['resolution_m']))} m/pixel | greenness {esc(str(h['greenness']))}", SMALL)] for h in hist]
        rows = [[cells[i], cells[i + 1] if i + 1 < len(cells) else ""] for i in range(0, len(cells), 2)]
        s += [Table(rows, colWidths=[8.5 * cm, 8.5 * cm]),
              P("Dates are Esri Wayback version dates, not necessarily capture dates. Resolution, season and sensor differ between versions. " + ATTRIBUTION, SMALL)]

    s.append(P("5. Change Check", H1))
    if not cmpd:
        s.append(P("No before/after comparison was run."))
    else:
        cm_ = cmpd["cmp"]
        s.append(table([["Item", "Value"], ["Before version", cmpd["before"]], ["After version", cmpd["after"]],
                        ["Changed share of the plot", f"{cm_['changed_pct_plot']}%"], ["Greenness change", ("unavailable" if cm_["greenness_change"] is None else f"{cm_['greenness_change']:+}")]], [6 * cm, 10 * cm]))
        s.append(Spacer(1, 6))
        s.append(Table([[pil_image(cm_["difference"], 8, 8), pil_image(cm_["overlay"], 8, 8)]], colWidths=[8.5 * cm, 8.5 * cm]))
        s.append(P("Left: difference image. Right: changed pixels inside the plot (red). Differences in season, sensor and resolution can look like change.", SMALL))

    s.append(P("6. Potential Anomalies", H1))
    an = (cmpd or {}).get("anomalies") or []
    if an:
        s.append(P(GENERAL_MESSAGE))
        s.append(table([["Type", "Affected", "Observation", "Status"]] +
                       [[a["type"], f"{a['affected_pct']}%" if a["affected_pct"] is not None else "n/a", a["observation"], a["status"]] for a in an],
                      [4.2 * cm, 1.8 * cm, 7.6 * cm, 3.4 * cm]))
    else:
        s.append(P("No anomaly detected in the available imagery for the compared versions."))

    s.append(KeepTogether([P("7. Verification Checklist", H1)] + [P("[   ]  " + i) for i in CHECKLIST]))
    s.append(KeepTogether([P("8. Disclaimer", H1), P(DISCLAIMER),
                           P("Sources: Esri World Imagery Wayback (satellite imagery); OpenStreetMap contributors (place search); "
                             "BBS / OCHA via geoBoundaries (administrative boundaries).", SMALL)]))
    doc.build(s, onFirstPage=footer, onLaterPages=footer)
    data = buf.getvalue()
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"jomilens_plot_report_{now:%Y%m%d_%H%M%S}.pdf"
    path.write_bytes(data)
    return path, data


# ======================================================================= JomiLens Verify report
def _short_hash(h):
    return "-" if not h else (h if len(h) <= 24 else f"{h[:16]}...{h[-8:]}")


def _evidence_line(e: dict) -> str:
    parts = []
    for k, v in e.items():
        if v in (None, "", [], {}):
            continue
        if k in ("expected_sha256", "computed_sha256"):
            v = _short_hash(v)
        parts.append(f"{k}: {v}")
    return "; ".join(parts)[:420]


def generate_verify_report(case: dict) -> tuple:
    """PDF for the CURRENT parcel and CURRENT verification run. case keys: parcel, metrics, records, transactions, documents, run, run_id,
    imagery (optional), classification (optional). Raises ValueError if the run or imagery belongs to a different parcel (no stale reports)."""
    p, m, run = case["parcel"], case["metrics"], case.get("run")
    pid = p["parcel_id"]
    if run is not None and run.get("parcel_id") != pid:
        raise ValueError("The verification run belongs to a different parcel; refusing to build a mixed report.")
    img, cls = case.get("imagery"), case.get("classification")
    if img is not None and img.get("parcel_id") != pid:
        raise ValueError("The imagery belongs to a different parcel; refusing to build a mixed report.")
    if cls is not None and cls.get("parcel_id") != pid:
        raise ValueError("The land-use result belongs to a different parcel; refusing to build a mixed report.")
    now = datetime.now()
    report_id = f"JLV-{now:%Y%m%d-%H%M%S}-{pid}"
    gmaps = google_maps_url(m["centroid"][0], m["centroid"][1])
    def gm_cell():
        return PM(f'<link href="{esc(gmaps)}" color="blue"><u>{esc(gmaps)}</u></link>', SMALL)
    synthetic = bool(p.get("is_synthetic"))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                            title=f"JomiLens Verify report {report_id}", author="JomiLens Verify (prototype)")
    DIS = ("Prototype for demonstration only. Not an official land record, legal opinion, ownership certificate, or proof of title. "
           "This report is not an official government document.")
    s = [Spacer(1, 3 * cm),
         Paragraph("JOMILENS VERIFY", ParagraphStyle("c1", parent=styles["Title"], fontSize=34, leading=42, spaceAfter=8, textColor=NAVY)),
         Paragraph("Citizen pre-purchase verification report", ParagraphStyle("c2", parent=styles["Title"], fontSize=14, leading=18, textColor=ORANGE)),
         Spacer(1, 1 * cm),
         table([["Item", "Value"], ["Report ID", report_id], ["Generated", f"{now:%Y-%m-%d %H:%M:%S} (server local time)"], ["Parcel ID", pid],
                ["Data status", "SYNTHETIC / FICTIONAL demonstration data" if synthetic else "NOT from the synthetic database (user-drawn or mapped feature)"],
                ["Verification run", (case.get("run_id") or "-") if run else "Not run"], ["Location (Google Maps)", gm_cell()]], [4 * cm, 12 * cm]),
         Spacer(1, 0.8 * cm), P(DIS, ParagraphStyle("dis", parent=BODY, textColor=colors.HexColor("#b00020"), fontSize=10)), PageBreak()]

    # 1. parcel & geometry
    s.append(P("1. Parcel and geometry", H1))
    label = {"official_verified": "Official boundary (authenticated)", "synthetic_demo": "Synthetic demo parcel", "user_drawn": "User-drawn polygon",
             "approximate_feature": "Approximate mapped feature (OpenStreetMap)", "unknown": "Unknown"}.get(p.get("boundary_type"), "Unknown")
    s.append(table([["Field", "Value"], ["Parcel ID", pid], ["Title", p.get("scenario_title") or "-"], ["Boundary type", label],
                    ["Boundary source", p.get("boundary_source") or "unknown"], ["Boundary source date", p.get("boundary_source_date") or "not known"],
                    ["Administrative area", p.get("administrative_area") or "-"], ["Mouza", p.get("mouza") or "not recorded"],
                    ["Asking price (fictional)", price_text(p.get("asking_price_bdt"), m["area_decimal"])],
                    ["Calculated area", f"{m['area_sqm']:,} m2 = {m['area_decimal']} decimal = {m['area_katha']} katha (720 sq ft) = {m['area_bigha']} bigha (33 decimal)"],
                    ["Perimeter", f"{m['perimeter_m']} m"], ["Measurement method", m["crs"]],
                    ["Centre (lat, lon)", f"{m['centroid'][0]:.6f}, {m['centroid'][1]:.6f}"], ["Open in Google Maps", gm_cell()]], [4.2 * cm, 11.8 * cm]))
    s.append(P("Calculated area comes from the drawn geometry and is not the officially recorded area. A mapped feature or synthetic outline is not a legal boundary.", SMALL))
    s.append(Spacer(1, 6))
    cr = m["corners"][:12]
    s.append(table([["Corner", "Latitude", "Longitude"]] + [[c["n"], c["lat"], c["lon"]] for c in cr], [2 * cm, 4 * cm, 4 * cm]))
    if len(m["corners"]) > 12:
        s.append(P(f"{len(m['corners'])} vertices in total; first 12 shown.", SMALL))

    # 2. records
    s.append(P("2. Records checked and provenance", H1))
    recs, txs, docs = case.get("records") or [], case.get("transactions") or [], case.get("documents") or []
    ctx = case.get("context") or {}
    surveys = [r for r in recs if r.get("survey_gen")]
    recs = [r for r in recs if not r.get("survey_gen")]
    if not recs:
        s.append(P("No records are available for this parcel in this prototype (real land records are not accessed)."))
    else:
        s.append(P("All records below are FICTIONAL demonstration records created by the project team.", SMALL))
        s.append(table([["Type", "Reference", "Dag", "Khatian", "Area", "Date", "Party label"]] +
                       [[r["record_type"], r["record_reference"], r["dag_ref"], r["khatian_ref"], f"{r['recorded_area']} {r['area_unit']}", r["record_date"], r["recorded_party_label"]] for r in recs],
                      [1.8 * cm, 3.3 * cm, 1.8 * cm, 2 * cm, 2.4 * cm, 2.2 * cm, 2.5 * cm]))
        s.append(P("Provenance: " + (recs[0].get("source_description") or "synthetic fixture"), SMALL))
    if txs:
        s.append(Spacer(1, 6))
        s.append(table([["Transaction", "Seller (demo ID)", "Buyer (demo ID)", "Date", "Status"]] +
                       [[t["transaction_id"], t["seller_demo_id"], t["buyer_demo_id"], t["transaction_date"], t["transaction_status"]] for t in txs], [2.8 * cm, 3.6 * cm, 3.6 * cm, 2.6 * cm, 3.4 * cm]))
    if surveys:
        s.append(Spacer(1, 6))
        s.append(table([["Survey", "Reference", "Dag", "Declares previous dag", "Area", "Year"]] +
                       [[r["survey_gen"], r["record_reference"], r["dag_ref"], r["prev_dag_ref"] or "-", f"{r['recorded_area']} {r['area_unit']}", (r["record_date"] or "")[:4]] for r in surveys],
                      [1.8 * cm, 3.4 * cm, 2 * cm, 4 * cm, 3 * cm, 1.8 * cm]))
    if docs:
        s.append(Spacer(1, 6))
        s.append(table([["Document", "Record", "Stored SHA-256", "Signer (simulated)", "Source status"]] +
                       [[d["document_id"], d["record_id"], _short_hash(d.get("expected_sha256")), d.get("signer_kid") or "unsigned", d.get("source_status") or "-"] for d in docs],
                      [2.4 * cm, 2.2 * cm, 4.2 * cm, 4 * cm, 3.2 * cm]))
    cov = ctx.get("coverage") or {}
    if ctx:
        s.append(Spacer(1, 6))
        s.append(P(f"Registers (synthetic): case register covers this parcel: {'yes' if cov.get('case_register') else 'NO'}; khas / acquisition register covers this parcel: "
                   f"{'yes' if cov.get('khas_register') else 'NO'}; encumbrance register covers this parcel: {'yes' if cov.get('encumbrance_register') else 'NO'}. "
                   "Absence of an entry is meaningful only where the register covers the parcel.", SMALL))
        if ctx.get("encumbrances"):
            s.append(table([["Entry", "Kind", "Holder (synthetic)", "Status", "Registered", "Released"]] +
                           [[e["entry_id"], e["kind"], e["holder_label"], e["status"], e["registered_date"], e["released_date"] or "-"] for e in ctx["encumbrances"]],
                          [2.2 * cm, 2.2 * cm, 4 * cm, 2.2 * cm, 2.6 * cm, 2.6 * cm]))
        if ctx.get("cases"):
            s.append(table([["Case", "Type", "Court (synthetic)", "Status", "Filed", "Restricts transfer"]] +
                           [[c_["case_id"], c_["case_type"], c_["court_label"], c_["status"], c_["filed_date"], "yes" if c_["restricts_transfer"] else "no"] for c_ in ctx["cases"]],
                          [2.4 * cm, 2.4 * cm, 3.6 * cm, 2.2 * cm, 2.4 * cm, 3 * cm]))
        if ctx.get("khas"):
            s.append(table([["Entry", "Type", "Authority (synthetic)", "Notice", "Date", "Status"]] +
                           [[k["entry_id"], k["status_type"], k["authority_label"], k["notice_ref"], k["notice_date"], k["status"]] for k in ctx["khas"]],
                          [2.2 * cm, 2.2 * cm, 3.6 * cm, 3.4 * cm, 2.4 * cm, 2.2 * cm]))
        if ctx.get("ledger"):
            led = ctx["ledger"]
            s.append(P(f"Document ledger: {len(led)} hash-chained entr{'y' if len(led) == 1 else 'ies'}; chain head {_short_hash(led[-1]['entry_hash'])}. "
                       "The head hash is only as trustworthy as where it is stored; a real registry would anchor it outside its own system.", SMALL))

    # 3. verification
    s.append(P("3. Verification run", H1))
    if not run:
        s.append(P("Verification was not run for this parcel (it needs synthetic records)."))
    else:
        s.append(table([["Item", "Value"], ["Overall status", run["overall_status"]], ["Run time (UTC)", run["created_at"]], ["Engine version", run["engine_version"]],
                        ["Settings", ", ".join(f"{k}={v}" for k, v in run["settings"].items())],
                        ["Uploaded files used", ", ".join(run.get("uploaded_documents") or []) or "none"]], [4 * cm, 12 * cm]))
        s.append(P("The overall status keeps uncertainty: PASS appears only when every check ran and passed. It is not a legal or fraud finding.", SMALL))
        from src.verification_engine import safety_summary
        ss = safety_summary(run)
        light = {"green": "GREEN", "amber": "AMBER", "red": "RED", "blue": "BLUE", "grey": "GREY"}[ss["level"]]
        lc = {"green": "#1b7f3b", "amber": "#a15c00", "red": "#b3261e", "blue": "#1a4f9c", "grey": "#555555"}[ss["level"]]
        s.append(PM(f"<font color='{lc}'><b>Safety summary: {light}</b></font> - {esc(ss['label_en'])}" +
                    (f" Tags: {esc(', '.join(ss['tags']))}." if ss["tags"] else ""), ParagraphStyle("light", parent=BODY, fontSize=11, leading=15, spaceBefore=4)))
        if ss["reasons"]:
            s.append(table([["Check", "Status", "Reason"]] + [[r["title"], r["status"], r["summary"]] for r in ss["reasons"]], [5 * cm, 3.2 * cm, 7.8 * cm]))
        for r in run["results"]:
            block = [P(f"{r['title']}: {r['status']}", ParagraphStyle("h2", parent=H1, fontSize=12, spaceBefore=10)), P(r["summary"]),
                     P("What this result means: " + r["meaning"], SMALL)]
            if r["evidence"]:
                block.append(table([["Evidence"]] + [[_evidence_line(e)] for e in r["evidence"]], [16 * cm]))
            block += [P("Limitations: " + " ".join(r["limitations"]), SMALL), P(f"check_id {r['check_id']} - {r['timestamp']}", SMALL)]
            s.append(KeepTogether(block[:3]))
            s += block[3:]

    # 4. imagery
    s.append(P("4. Satellite imagery", H1))
    if not img or not img.get("prepared"):
        s.append(P("Satellite imagery was not loaded in this session, or is unavailable. This section is unresolved." + (f" Reason: {img['message']}" if img and img.get("message") else "")))
    else:
        from src.real_analysis import with_outline
        from src.wayback import ATTRIBUTION
        prep = img["prepared"]
        cap = prep[0].get("date_kind") == "capture"
        if cap:
            from src.sentinel import ATTRIBUTION as S2_ATTR
            s.append(P(f"Provider: {prep[0].get('provider')}. {S2_ATTR} Retrieved in this session."))
            s.append(table([["Capture date", "Season", "Scene cloud cover (%)", "Resolution (m/pixel)"]] +
                           [[x["date"], x.get("season") or "-", x.get("cloud_cover"), x["resolution_m"]] for x in prep], [3.4 * cm, 4.6 * cm, 4.2 * cm, 3.8 * cm]))
            s.append(P("Capture dates come from the scene metadata. One low-cloud scene per dry season (December-February) is used so images are comparable. At 10 m per pixel a small parcel covers only a few pixels.", SMALL))
        else:
            s.append(P(f"Provider: Esri World Imagery Wayback (viewing only; not open data). {ATTRIBUTION}. Retrieved in this session."))
            s.append(table([["Version (release) date", "Capture date", "Resolution (m/pixel)"]] + [[x["date"], "not provided by this source", x["resolution_m"]] for x in prep], [5 * cm, 6 * cm, 5 * cm]))
            s.append(P("Dates are the release (version) dates of the basemap, NOT the dates the images were captured. Resolution, season and sensor differ between versions.", SMALL))
        cmpd = case.get("comparison")
        if cmpd:
            c_ = cmpd["cmp"]
            s.append(Spacer(1, 6))
            s.append(table([["Comparison setting / result", "Value"], ["Before version", cmpd["before"]], ["After version", cmpd["after"]], ["Sensitivity threshold", cmpd.get("threshold", "-")],
                            ["Changed share of the parcel", "unavailable" if c_["changed_pct_plot"] is None else f"{c_['changed_pct_plot']}%"],
                            ["Greenness change", "unavailable" if c_["greenness_change"] is None else f"{c_['greenness_change']:+}"]], [6 * cm, 10 * cm]))
            for w in c_.get("warnings", []):
                s.append(P("Warning: " + w, SMALL))
            s.append(Table([[pil_image(c_["difference"], 7.5, 7), pil_image(c_["overlay"], 7.5, 7)]], colWidths=[8.5 * cm, 8.5 * cm]))
            s.append(P("Left: difference image. Right: pixels that differ inside the parcel (red). This is evidence of POSSIBLE surface change only, not proof of construction, ownership or legal land use.", SMALL))
        else:
            s.append(P("No before/after comparison was run."))

    # 5. land use
    s.append(P("5. Land-use result", H1))
    if not cls:
        s.append(P("No land-use classification was run for this parcel."))
    else:
        s.append(table([["Item", "Value"], ["Predicted class", cls["class_label"]], ["Method", f"{cls['method']} ({cls['model_version']})"],
                        ["Confidence", "not calibrated, therefore not reported"], ["Review status", cls["review_status"]], ["Evidence", cls["evidence_summary"]]], [4 * cm, 12 * cm]))
        s.append(P(" ".join(cls.get("caveats", [])), SMALL))

    # 6. unresolved + next steps
    s.append(P("6. Unresolved questions and suggested human verification", H1))
    unresolved = []
    if run:
        unresolved += [f"{r['title']} is {r['status']}: {r['summary']}" for r in run["results"] if r["status"] != "PASS"]
    else:
        unresolved.append("Record checks were not run.")
    if not img or not img.get("prepared"):
        unresolved.append("Satellite imagery history was not reviewed.")
    unresolved.append("The boundary is not an authenticated official boundary." if p.get("boundary_type") != "official_verified" else "Confirm the boundary source and accuracy.")
    for u in unresolved:
        s.append(P("- " + u))
    s.append(Spacer(1, 4))
    for step in ["[ ] Obtain and read the original deed, khatian and mutation records from the proper authority.",
                 "[ ] Compare references and areas against the originals, not copies.", "[ ] Check the transfer history with the registration office.",
                 "[ ] Have a licensed surveyor measure and mark the physical boundary.", "[ ] Consult a qualified lawyer before any purchase decision."]:
        s.append(P(step))

    # 7. disclaimer and sources
    s.append(KeepTogether([P("7. Disclaimer and sources", H1), P(DIS),
                           P("Sources: Copernicus Sentinel-2 (open imagery, ESA) and, optionally, Esri World Imagery Wayback (viewing only); OpenStreetMap contributors via Geofabrik "
                             "(mapped features, place search); BBS / OCHA via geoBoundaries (administrative boundaries). Records, surveys, registers, signatures and transactions are "
                             "synthetic fixtures made by the project team; the issuer signature key is a public demo key, not a real authority.", SMALL)]))
    doc.build(s, onFirstPage=footer, onLaterPages=footer)
    data = buf.getvalue()
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"{report_id}.pdf"
    path.write_bytes(data)
    return path, data
