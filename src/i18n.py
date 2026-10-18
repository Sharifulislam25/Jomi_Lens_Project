"""English / Bangla (বাংলা) interface text. Bangla covers navigation, headings, buttons, statuses, check names, overall summaries and disclaimers.
Evidence tables, detailed explanations and the PDF report stay in English (the built-in PDF fonts cannot shape Bangla conjuncts)."""
import streamlit as st

LANGS = {"en": "English", "bn": "বাংলা"}
TEXT = {
    "nav.overview": ("Overview", "পরিচিতি"), "nav.explore": ("Explore Joydebpur", "জয়দেবপুর মানচিত্র"), "nav.profile": ("Parcel profile", "জমির প্রোফাইল"),
    "nav.verify": ("Verification", "যাচাই"), "nav.satellite": ("Satellite & land use", "স্যাটেলাইট ও ভূমি ব্যবহার"), "nav.report": ("Report", "প্রতিবেদন"),
    "nav.myplot": ("Draw a plot", "জমি আঁকুন"), "nav.group": ("JomiLens Verify", "জমিলেন্স ভেরিফাই"), "nav.tools": ("Tools", "টুলস"),
    "nav.signin": ("Sign in", "সাইন ইন"), "nav.citizen_login": ("Citizen Login", "নাগরিক লগইন"), "nav.admin_login": ("Admin Portal", "প্রশাসক পোর্টাল"),
    "nav.account": ("My account", "আমার অ্যাকাউন্ট"), "nav.search": ("Find a land", "জমি খুঁজুন"), "nav.inbox": ("Inbox", "ইনবক্স"), "nav.me": ("Me", "আমি"),
    "nav.admin": ("Admin Portal", "প্রশাসক পোর্টাল"), "nav.a_dash": ("Dashboard", "ড্যাশবোর্ড"), "nav.a_support": ("Reports & messages", "অভিযোগ ও বার্তা"),
    "nav.a_gis": ("GIS coordinate editor", "জিআইএস স্থানাঙ্ক সম্পাদক"), "nav.a_users": ("Users", "ব্যবহারকারী"), "nav.a_notify": ("Send notification", "বিজ্ঞপ্তি পাঠান"),
    "nav.a_audit": ("Audit log", "অডিট লগ"),
    "disclaimer": ("Prototype for demonstration only. Not an official land record, legal opinion, ownership certificate, or proof of title.",
                   "শুধুমাত্র প্রদর্শনের জন্য প্রোটোটাইপ। এটি সরকারি ভূমি রেকর্ড, আইনি মতামত, মালিকানা সনদ বা মালিকানার প্রমাণ নয়।"),
    "synthetic": ("All parcels, records, transactions and documents in the demo are SYNTHETIC (fictional). No real person or land record is shown.",
                  "এই ডেমোর সব জমি, দলিল, খতিয়ান ও লেনদেন কাল্পনিক (কৃত্রিম)। কোনো প্রকৃত ব্যক্তি বা প্রকৃত ভূমি রেকর্ড দেখানো হয় না।"),
    "tagline": ("Check before you buy: citizen pre-purchase land verification for Joydebpur, Gazipur (prototype)", "কেনার আগে যাচাই করুন: জয়দেবপুর, গাজীপুরের জন্য নাগরিকের ক্রয়-পূর্ব জমি যাচাই (প্রোটোটাইপ)"),
    "run": ("▶️ Run verification", "▶️ যাচাই চালান"), "no_run": ("No run yet for this parcel. Press **Run verification**.", "এই জমির জন্য এখনো যাচাই চালানো হয়নি। **যাচাই চালান** চাপুন।"),
    "parcel": ("Parcel", "জমি"), "overall": ("Overall", "সামগ্রিক ফলাফল"), "means": ("What this result means", "এই ফলাফলের অর্থ কী"),
    "limits": ("Limitations", "সীমাবদ্ধতা"), "settings": ("Settings", "সেটিংস"), "gen_report": ("📄 Generate report", "📄 প্রতিবেদন তৈরি করুন"),
    "download": ("⬇️ Download PDF", "⬇️ PDF ডাউনলোড"), "fetch": ("🛰️ Fetch satellite history", "🛰️ স্যাটেলাইট ইতিহাস আনুন"),
    "records": ("Linked records", "সংযুক্ত রেকর্ড"), "area_calc": ("Calculated area", "গণনাকৃত আয়তন"), "perimeter": ("Perimeter", "পরিসীমা"),
    "g.records": ("Ownership and records", "মালিকানা ও রেকর্ড"), "g.transfers": ("Transfers", "হস্তান্তর"),
    "g.integrity": ("Document and registry integrity", "দলিল ও রেজিস্ট্রির অখণ্ডতা"), "g.flags": ("Legal and status flags", "আইনি ও অবস্থাগত সতর্কতা"),
    "ov.workflow": ("The workflow", "কাজের ধাপ"), "ov.can": ("It can", "যা করতে পারে"), "ov.cannot": ("It cannot", "যা পারে না"),
    "ov.start": ("Start: Explore Joydebpur", "শুরু করুন: জয়দেবপুর মানচিত্র"), "parcels": ("Synthetic demo parcels", "কৃত্রিম ডেমো জমি"), "records_n": ("Fictional records", "কাল্পনিক রেকর্ড"),
    "checks_n": ("Checks per parcel", "প্রতি জমির যাচাই"), "runs_n": ("Verification runs saved", "সংরক্ষিত যাচাই"),
    "light": ("Safety summary", "নিরাপত্তা সারসংক্ষেপ"), "listen": ("🔊 Listen", "🔊 শুনুন"), "why": ("Why", "কারণ"),
    "find_ref": ("Find a parcel by dag or khatian number", "দাগ বা খতিয়ান নম্বর দিয়ে জমি খুঁজুন"), "open_profile": ("Open profile", "প্রোফাইল খুলুন"),
}
STATUS = {"PASS": "উত্তীর্ণ", "REVIEW_REQUIRED": "পর্যালোচনা প্রয়োজন", "CONFLICT_FOUND": "অসঙ্গতি পাওয়া গেছে", "UNAVAILABLE": "তথ্য নেই", "NOT_RUN": "চালানো হয়নি"}
CHECK_TITLES = {
    "record_consistency": "রেকর্ডের সামঞ্জস্য", "registration_mutation": "নিবন্ধন (সাব-রেজিস্ট্রি) বনাম নামজারি (এসি ল্যান্ড)", "survey_chain": "জরিপের ধারাবাহিকতা (সিএস → এসএ → আরএস → বিএস)",
    "conflicting_sales": "দ্বৈত বা পরস্পরবিরোধী বিক্রি", "document_integrity": "দলিলের অখণ্ডতা (SHA-256)", "document_authenticity": "দলিলের প্রামাণিকতা (সিমুলেটেড স্বাক্ষর ও লেজার)",
    "pending_cases": "চলমান মামলা", "khas_acquisition": "খাস / অর্পিত / অধিগ্রহণ অবস্থা",
    "boundary_overlap": "অন্য নিবন্ধিত জমির সঙ্গে সীমানা মিলে যাওয়া (ওভারল্যাপ)", "encumbrance": "বন্ধক, দায় বা ক্রোক"}
OVERALL = {
    "PASS": ("All checks ran and passed on the synthetic records. This is not a finding that anything is genuine or legal.",
             "সব যাচাই চালানো হয়েছে এবং কাল্পনিক রেকর্ডে উত্তীর্ণ হয়েছে। এর মানে এই নয় যে কিছু খাঁটি বা আইনসম্মত।"),
    "REVIEW_REQUIRED": ("At least one check needs a person to look at it, or could not be completed. Nothing here is a clean pass.",
                        "অন্তত একটি যাচাইয়ে মানুষের দেখা দরকার, অথবা তা সম্পূর্ণ করা যায়নি। এটি পরিষ্কার উত্তীর্ণ নয়।"),
    "CONFLICT_FOUND": ("At least one check found a conflict in the synthetic records. In a real case this would need human verification against originals.",
                       "অন্তত একটি যাচাইয়ে কাল্পনিক রেকর্ডে অসঙ্গতি পাওয়া গেছে। বাস্তবে এটি মূল কাগজের সঙ্গে মানুষ দ্বারা যাচাই করতে হতো।"),
    "UNAVAILABLE": ("There was nothing to check for this parcel.", "এই জমির জন্য যাচাই করার মতো কিছু ছিল না।"), "NOT_RUN": ("Not run.", "চালানো হয়নি।")}


def lang() -> str:
    return st.session_state.get("lang", "en")


def t(key: str) -> str:
    en, bn = TEXT[key]
    return bn if lang() == "bn" else en


def status_text(status: str) -> str:
    return f"{STATUS[status]} · {status}" if lang() == "bn" and status in STATUS else status


def check_title(check_id: str, english: str) -> str:
    return CHECK_TITLES.get(check_id, english) if lang() == "bn" else english


def overall_text(status: str) -> str:
    en, bn = OVERALL[status]
    return bn if lang() == "bn" else en
