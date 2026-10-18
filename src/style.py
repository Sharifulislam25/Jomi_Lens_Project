"""Small CSS layer that makes the Streamlit app look like a product."""
import streamlit as st

CSS = """
<style>
.block-container {padding-top: 1.2rem; max-width: 1280px;}
h1, h2, h3 {letter-spacing: -0.01em;}
.hero {background: linear-gradient(120deg, #0b3c5d 0%, #0e7c86 62%, #f2a541 135%); border-radius: 20px;
       padding: 34px 40px; color: #fff; margin-bottom: 18px; box-shadow: 0 8px 24px rgba(11,60,93,.25);}
.hero h1 {margin: 0; font-size: 2.7rem; color: #fff; letter-spacing: .04em;}
.hero .tag {font-size: 1.15rem; opacity: .95; margin: 4px 0 10px 0;}
.hero p {opacity: .9; max-width: 780px; margin: 0 0 6px 0;}
.pill {display: inline-block; background: rgba(255,255,255,.17); padding: 4px 13px; border-radius: 999px;
       margin: 6px 6px 0 0; font-size: .85rem;}
div[data-testid="stMetric"] {background: #fff; border: 1px solid #dbe8ee; border-radius: 14px; padding: 10px 14px;
       box-shadow: 0 1px 3px rgba(20,48,63,.06);}
div[data-testid="stMetricValue"] {font-size: 1.45rem;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 14px;}
.stButton > button, .stDownloadButton > button {border-radius: 10px; font-weight: 600;}
section[data-testid="stSidebar"] {background: #eaf2f6;}
.note {background: #fff8e6; border-left: 4px solid #f2a541; padding: 10px 14px; border-radius: 8px; font-size: .92rem;}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)
