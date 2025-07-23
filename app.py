import os
import json
import time
import logging
import streamlit as st
from invoice_extractor import InvoiceExtractor
from helper import InvoiceHelper
from dotenv import load_dotenv
from google.oauth2 import service_account
from langchain_google_genai import ChatGoogleGenerativeAI

# Load credentials from Streamlit secrets
# service_account_info = json.loads(st.secrets["GOOGLE_APPLICATION_CREDENTIALS_JSON"])
# credentials = service_account.Credentials.from_service_account_info(service_account_info)

# Load Google API Key from .env
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set up Gemini model
# llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=GOOGLE_API_KEY)

# calling classes
extractor = InvoiceExtractor()
handler = InvoiceHelper()

# Set page config
st.set_page_config(page_title="📄 Multi-Invoice Processor", 
                   layout="wide", 
                   initial_sidebar_state="expanded")

with st.sidebar:
    st.header("⚙️ Configuration")

    # API Key input
    api_key = st.text_input(
        "Google AI API Key",
        type="password",
        help="Enter your Google AI API key"
    )
            
    if api_key:
        llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=api_key)
        st.success("✅ API Key configured")
    else:
        st.warning("⚠️ Please enter your API key")
                
st.title("📄 Upload Supplier Invoices")

# File uploader (multiple files)
uploaded_files = st.file_uploader("Upload one or more PDF invoices", type=["pdf"], accept_multiple_files=True)

# Create output directories
os.makedirs("temp_docs", exist_ok=True)
os.makedirs("results", exist_ok=True)

# Process button
if uploaded_files and st.button("🚀 Process Invoices"):
    logger.info(f"Received {len(uploaded_files)} Invoices")
    for uploaded_file in uploaded_files:
        logger.info(f"==========Processing {uploaded_file.name}=============")
        with st.spinner(f"Processing {uploaded_file.name}..."):

            # Save file to temp folder
            file_path = os.path.join("temp_docs", uploaded_file.name)
            with open(file_path, "wb") as f:
                f.write(uploaded_file.read())

            base_filename = os.path.splitext(uploaded_file.name)[0]
            json_filename = f"{base_filename}.json"
            json_path = os.path.join("results", json_filename)

            updated_data = handler.exctract_invoice_data(file_path, llm)

            # Step 4: Save JSON
            with open(json_path, "w") as f:
                json.dump(updated_data, f, indent=4)

            # Step 5: Display results
            logger.info(f"Processed and saved: `results/{json_filename}`")
            st.download_button(
                label="📥 Download JSON",
                data=json.dumps(updated_data, indent=4),
                file_name=json_filename,
                mime="application/json",
                key=json_filename
            )

            with st.expander(f"📋 View Extracted Data for `{uploaded_file.name}`"):
                st.json(updated_data)
        logger.info(f"======================================")
