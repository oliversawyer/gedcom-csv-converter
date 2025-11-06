import os 
import sys
import streamlit as st
import pandas as pd

# Ensure root path is available
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

# Import converter logic from pipeline.py (same folder)
from pipeline import load_artifacts, convert_bytes_to_csv
import streamlit.components.v1 as components

# --- Google Analytics tag ---
import streamlit.components.v1 as components


# --- PAGE CONFIG (Only once, and must be first UI call) ---
st.set_page_config(
    page_title="Free GED to CSV Converter",
    layout="wide",
    page_icon="📁"
)


# --- SEO META TAGS (Insert this right after GA code block) ---
st.markdown("""
<head>
<title>Free GEDCOM to CSV Converter | Online GEDCOM File Converter</title>
<meta name="description" content="Convert GEDCOM (.ged) genealogy family tree files to CSV instantly online. Free, fast, and private GEDCOM to CSV converter tool. No downloads required.">
<meta name="keywords" content="GEDCOM converter, convert GED file, GED to CSV, genealogy data converter, family tree data export, ancestry file converter">
<meta property="og:title" content="Free GEDCOM to CSV Converter">
<meta property="og:description" content="Convert GED files to CSV instantly — free, fast, and privacy-friendly. No signup needed.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://gedcsvconverter.com">
</head>
""", unsafe_allow_html=True)



# --- GOOGLE ANALYTICS (MUST come immediately after set_page_config) ---
GA_ID = "G-FEE8NK2J8V"
st.markdown(f"""
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{GA_ID}');
</script>
""", unsafe_allow_html=True)


# --- CUSTOM HTML HEADER ---
st.markdown(
    """
    <style>
        /* Global background */
        .stApp {
            background-color: #0d1117;
            color: #f0f0f0;
            font-family: 'Segoe UI', sans-serif;
        }

        /* Header section */
        .hero {
            text-align: center;
            padding: 2rem 0 1rem 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .hero h1 {
            font-size: 3rem;
            color: #f9d342;
        }
        .hero p {
            font-size: 1.1rem;
            color: #cfcfcf;
            margin-top: -10px;
        }

        /* Upload card */
        .upload-area {
            background-color: #161b22;
            padding: 2rem;
            border-radius: 10px;
            box-shadow: 0px 0px 8px rgba(0,0,0,0.3);
        }

        /* Footer */
        footer {
            text-align: center;
            color: #999;
            font-size: 0.9rem;
            margin-top: 3rem;
            padding-top: 1rem;
            border-top: 1px solid rgba(255,255,255,0.1);
        }
    </style>

    <div class="hero">
        <h1>📂 GEDCOM → CSV Converter</h1>
        <p>Upload your .ged genealogy file and instantly generate a cleaned CSV file for analysis.</p>
    </div>
    """,
    unsafe_allow_html=True
)

# --- INITIALIZATION ---
load_artifacts()

# --- FILE UPLOADER ---
uploaded_file = st.file_uploader("Choose a GEDCOM file", type=["ged"])

if uploaded_file:
    st.info(f"Processing: {uploaded_file.name}")
    try:
        csv_text = convert_bytes_to_csv(uploaded_file.read())
        st.success("Conversion successful!")

        # Download button
        st.download_button(
            label="Download CSV File",
            data=csv_text.encode("utf-8"),
            file_name=uploaded_file.name.replace(".ged", ".csv"),
            mime="text/csv"
        )

        # Preview
        df = pd.read_csv(pd.io.common.BytesIO(csv_text.encode("utf-8")))
        st.write("### Preview of results")
        st.dataframe(df.head(20))
    except Exception as e:
        st.error(f"Error: {e}")



# --- ABOUT SECTION ---
st.markdown(
    """
    <div style="margin-top:2rem; padding:1rem; background-color:#1b1f22; border-radius:8px;">
        <h3 style="color:#f9d342; margin-bottom:0.5rem;">🔒 Privacy & Security</h3>
        <p style="color:#cfcfcf; font-size:1rem; line-height:1.6;">
            Your uploaded files are processed locally — they are <b>never stored or shared</b>.
            Once converted, you can download your CSV instantly, and the temporary file is deleted.
        </p>
        <p style="color:#cfcfcf; font-size:1rem; line-height:1.6; margin-top:1rem;">
            Thank you for using this site. This is a work in progress — please email 
            <a href="mailto:YOUR_EMAIL@domain.com" style="color:#f9d342; text-decoration:none;">YOUR_EMAIL@domain.com</a>
            with any feedback or issues so I can continue improving it.
        </p>
    </div>
    """,
    unsafe_allow_html=True
)






#cd "C:\Users\olive\OneDrive\Desktop\model_webapp\app"
#git add app.py
#git commit -m "Fix: replace gedcom with python-gedcom for deployment"
#git push
