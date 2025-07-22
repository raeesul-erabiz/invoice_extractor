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

            # Step 1: Extract raw text
            extracted_text = extractor.extract_text_from_pdf(file_path)
            # logger.info(f"Extracted Text: {extracted_text}")

            if "LifeGrainCentralPtyLtd" in extracted_text:
                extracted_text = extractor.extract_text_from_pdf_pymupdf(file_path)
                # logger.info(f"Extracted Text: {extracted_text}")

            # Step 2: LLM for structured data
            start = time.time()
            structured_data = extractor.extract_invoice_data(extracted_text, llm)
            elapsed = round(time.time() - start, 2)
            logger.info(f"LLM extraction completed in {elapsed}s")
            print(structured_data)

            if "Allpress Espresso" in extracted_text:
                new_extracted_text = extractor.extract_text_from_pdf_pymupdf(file_path)
                
                start = time.time()
                new_structured_data = extractor.extract_line_item_data(new_extracted_text, llm)
                elapsed = round(time.time() - start, 2)
                logger.info(f"LLM extraction completed in {elapsed}s")
                # print(structured_data)

                updated_data = handler.update_product_names(structured_data, new_structured_data)

            # Step 3: Post-processing
            updated_data = handler.extract_pack_details(structured_data)

            updated_data = handler.add_item_count(updated_data)

            updated_data = handler.calculate_missing_fields(updated_data)

            # Apply only for "Anchor Packaging"
            supplier_name = (updated_data.get("supplier_name") or "").strip().casefold()
            if supplier_name in {"tax invoice", "anchor packaging", "anchorpackaging.com.au"}:
                updated_data = handler.recalculate_anchor_packaging_gst(updated_data)

            # Replace Supplier Name
            if updated_data.get('supplier_name') == 'Plum SCH':
                updated_data['supplier_name'] = 'LifeGrain Central Kitchen'

            # Apply only for "PNM SYDNEY PTY LTD"
            if updated_data.get("supplier_name", "").strip().lower() == "pnm sydney pty ltd":
                updated_data = handler.reconcile_published_totals(updated_data)

            updated_data = handler.normalize_financial_fields(updated_data)

            updated_data = handler.normalize_line_items(updated_data)

            # updated_data = handler.validate_and_correct_line_totals(updated_data)

            updated_data = handler.recalculate_totals_and_variances(updated_data)

            updated_data = handler.reorder_invoice_data(updated_data)

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
