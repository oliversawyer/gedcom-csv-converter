import os  
import sys
import streamlit as st
import pandas as pd

# ✅ set_page_config MUST be first
st.set_page_config(
    page_title="Free GED to CSV Converter",
    layout="wide",
    page_icon="📁"
)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))
from pipeline import load_artifacts, convert_bytes_to_csv

# ✅ Inject GA AFTER the page config—not before
GA_TAG = """
<script async src="https://www.googletagmanager.com/gtag/js?id=G-FEE8NK2J8V"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-FEE8NK2J8V');
</script>
"""

from streamlit.components.v1 import html
html(GA_TAG, height=0)



# --- REMOVE WHITE STREAMLIT HEADER BAR ---
hide_streamlit_header = """
<style>
header {visibility: hidden !important;}
.block-container { padding-top: 0rem !important; }
</style>
"""
st.markdown(hide_streamlit_header, unsafe_allow_html=True)

# --- CUSTOM UI STYLING + HERO SECTION ---
st.markdown(
    """
    <style>
        .stApp { background-color: #0d1117; color: #f0f0f0; font-family: 'Segoe UI', sans-serif; }
        .hero { text-align: center; padding: 2rem 0 1rem 0; border-bottom: 1px solid rgba(255,255,255,0.1); }
        .hero h1 { font-size: 3rem; color: #f9d342; }
        .hero p { font-size: 1.1rem; color: #cfcfcf; margin-top: -10px; }
        .upload-area { background-color: #161b22; padding: 2rem; border-radius: 10px; box-shadow: 0px 0px 8px rgba(0,0,0,0.3); }
        footer { text-align: center; color: #999; font-size: 0.9rem; margin-top: 3rem; padding-top: 1rem; border-top: 1px solid rgba(255,255,255,0.1); }
    </style>

    <div class="hero">
        <h1>📂 GEDCOM → CSV Converter</h1>
        <p>Upload your .ged genealogy file and instantly generate a cleaned CSV file for analysis.</p>
    </div>
    """,
    unsafe_allow_html=True
)

# --- LOAD CONVERSION LOGIC ---
load_artifacts()

uploaded_file = st.file_uploader("Choose a GEDCOM file", type=["ged"])

if uploaded_file:
    st.info(f"Processing: {uploaded_file.name}")
    try:
        csv_text = convert_bytes_to_csv(uploaded_file.read())
        st.success("✅ Conversion successful!")

        st.download_button(
            label="Download CSV File",
            data=csv_text.encode("utf-8"),
            file_name=uploaded_file.name.replace(".ged", ".csv"),
            mime="text/csv"
        )

        df = pd.read_csv(pd.io.common.BytesIO(csv_text.encode("utf-8")))
        st.write("### Preview of results")
        st.dataframe(df.head(20))

    except Exception as e:
        st.error(f"Error: {e}")

st.markdown(
    """
    <div style="margin-top:2rem; padding:1rem; background-color:#1b1f22; border-radius:8px;">
        <h3 style="color:#f9d342; margin-bottom:0.5rem;">🔒 Privacy & Security</h3>
        <p style="color:#cfcfcf;">Your uploaded files are processed locally — they are <b>never stored or shared</b>.</p>
        <p style="color:#cfcfcf; margin-top:1rem;">
            For support or feedback, contact <span style="color:#f9d342;">COMINGSOON</span>.
        </p>
    </div>
    """,
    unsafe_allow_html=True
)





#cd "C:\Users\olive\OneDrive\Desktop\model_webapp\app"
#git add app.py
#git commit -m "Fix: replace gedcom with python-gedcom for deployment"
#git push
