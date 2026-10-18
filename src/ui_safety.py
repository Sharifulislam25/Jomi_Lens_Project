"""Citizen safety card (traffic light) and a Bangla / English voice summary using the browser's built-in speech synthesis."""
import json
from html import escape

import streamlit as st

from src import i18n
from src.verification_engine import safety_summary

COLOURS = {"green": ("#1b7f3b", "#e6f4ea", "🟢"), "amber": ("#a15c00", "#fff4e0", "🟡"), "red": ("#b3261e", "#fde8e6", "🔴"),
           "blue": ("#1a4f9c", "#e7effb", "🔵"), "grey": ("#555555", "#efefef", "⚪")}
TAG_BN = {"mortgaged": "বন্ধক আছে", "case pending": "মামলা আছে", "boundary overlap": "সীমানা মিলে যাচ্ছে", "conflicting sale": "বিক্রিতে অসঙ্গতি"}


def speech_text(summary: dict, lang: str) -> str:
    """Short sentence(s) to read aloud. Built from the summary only (no new judgement)."""
    reasons = summary["reasons"][:3]
    if lang == "bn":
        parts = [f"জমি {summary['parcel_id']}।", summary["label_bn"]]
        if reasons:
            parts.append("প্রধান কারণ: " + "; ".join(i18n.CHECK_TITLES.get(r["check_id"], r["title"]) + ", " + i18n.STATUS.get(r["status"], r["status"]) for r in reasons) + "।")
        parts.append("এটি কাল্পনিক তথ্যের ওপর একটি প্রোটোটাইপ, আইনি প্রমাণ নয়।")
    else:
        parts = [f"Parcel {summary['parcel_id']}.", summary["label_en"]]
        if reasons:
            parts.append("Main reasons: " + "; ".join(f"{r['title']}, {r['status'].replace('_', ' ').lower()}" for r in reasons) + ".")
        parts.append("This is a prototype on synthetic data, not legal proof.")
    return " ".join(parts)


def _js(value) -> str:
    """JSON for embedding inside a <script> block: <, > and & are escaped so the text can never close the script tag."""
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def speech_html(text: str, lang: str) -> str:
    """A speak button. Prefers a Bangla voice for 'bn'; if the device has none, it says so instead of reading Bangla with an English voice."""
    want = "bn" if lang == "bn" else "en"
    label = i18n.TEXT["listen"][1 if lang == "bn" else 0]
    no_voice = ("এই ডিভাইসে বাংলা কণ্ঠ পাওয়া যায়নি। অ্যান্ড্রয়েডের Chrome বা বাংলা ভয়েস ইনস্টল করা ডিভাইসে চেষ্টা করুন।" if want == "bn"
                else "No English voice is available on this device.")
    return f"""<div style="font-family:sans-serif">
<button id="b" style="padding:6px 14px;border-radius:8px;border:1px solid #0e7c86;background:#fff;color:#0e7c86;font-weight:600;cursor:pointer">{escape(label)}</button>
<span id="m" style="margin-left:10px;font-size:13px;color:#a15c00"></span></div>
<script>
const TEXT = {_js(text)}, WANT = {_js(want)}, NOVOICE = {_js(no_voice)};
const btn = document.getElementById('b'), msg = document.getElementById('m');
function pick() {{ const v = speechSynthesis.getVoices(); return v.find(x => x.lang && x.lang.toLowerCase().startsWith(WANT)); }}
btn.onclick = () => {{
  if (!('speechSynthesis' in window)) {{ msg.textContent = 'Speech is not supported in this browser.'; return; }}
  speechSynthesis.cancel();
  const go = () => {{ const v = pick(); if (!v) {{ msg.textContent = NOVOICE; return; }}
    const u = new SpeechSynthesisUtterance(TEXT); u.voice = v; u.lang = v.lang; u.rate = 0.95; speechSynthesis.speak(u); msg.textContent = ''; }};
  if (speechSynthesis.getVoices().length) go(); else speechSynthesis.onvoiceschanged = go;
}};
</script>"""


def safety_card(run):
    """Render the traffic light for a run, with reasons and a voice button."""
    s = safety_summary(run)
    fg, bg, dot = COLOURS[s["level"]]
    bn = i18n.lang() == "bn"
    label = s["label_bn"] if bn else s["label_en"]
    tags = "".join(f"<span style='display:inline-block;margin:6px 6px 0 0;padding:2px 10px;border-radius:999px;background:#fff;border:1px solid {fg};font-size:13px'>"
                   f"{escape(TAG_BN.get(t, t) if bn else t)}</span>" for t in s["tags"])
    st.markdown(f"<div style='border-left:8px solid {fg};background:{bg};border-radius:12px;padding:14px 18px;margin:6px 0 10px 0'>"
                f"<div style='font-size:.85rem;color:{fg};font-weight:700;letter-spacing:.03em'>{escape(i18n.t('light')).upper()}</div>"
                f"<div style='font-size:1.25rem;font-weight:700;color:{fg};margin-top:2px'>{dot} {escape(label)}</div>{tags}</div>", unsafe_allow_html=True)
    if s["reasons"]:
        with st.expander(f"{i18n.t('why')} ({len(s['reasons'])})", expanded=s["level"] in ("red", "blue")):
            for r in s["reasons"]:
                st.markdown(f"- **{i18n.check_title(r['check_id'], r['title'])}**: {i18n.status_text(r['status'])}. {r['summary']}")
    html = speech_html(speech_text(s, "bn" if bn else "en"), "bn" if bn else "en")
    try:
        st.iframe(html, height=48)
    except AttributeError:
        import streamlit.components.v1 as components
        components.html(html, height=48)
    return s
