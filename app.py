import os
import json
import time
import logging
import streamlit as st
from invoice_extractor import extract_text_from_pdf, extract_invoice_data
from helper import (
    extract_pack_details,
    add_item_count,
    normalize_financial_fields,
    normalize_line_items
)
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

# Load Google API Key from .env
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set up Gemini model
llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=GOOGLE_API_KEY)

# Set page config
st.set_page_config(page_title="📄 Multi-Invoice Processor", layout="centered")
st.title("📄 Upload Supplier Invoices")

# File uploader (multiple files)
uploaded_files = st.file_uploader("Upload one or more PDF invoices", type=["pdf"], accept_multiple_files=True)

# Create output directories
os.makedirs("temp_docs", exist_ok=True)
os.makedirs("results", exist_ok=True)

# Process button
if uploaded_files and st.button("🚀 Process Invoices"):
    for uploaded_file in uploaded_files:
        with st.spinner(f"Processing {uploaded_file.name}..."):

            # Save file to temp folder
            file_path = os.path.join("temp_docs", uploaded_file.name)
            with open(file_path, "wb") as f:
                f.write(uploaded_file.read())

            base_filename = os.path.splitext(uploaded_file.name)[0]
            json_filename = f"{base_filename}.json"
            json_path = os.path.join("results", json_filename)

            # Step 1: Extract raw text
            extracted_text = extract_text_from_pdf(file_path)

            # Step 2: LLM for structured data
            start = time.time()
            structured_data = extract_invoice_data(extracted_text, llm)
            elapsed = round(time.time() - start, 2)
            logging.info(f"✅ LLM extraction completed in {elapsed}s")

            # Step 3: Post-processing
            updated_data = extract_pack_details(structured_data)

            updated_data = add_item_count(updated_data)

            updated_data = normalize_financial_fields(updated_data)

            updated_data = normalize_line_items(updated_data)

            # Step 4: Save JSON
            with open(json_path, "w") as f:
                json.dump(updated_data, f, indent=4)

            # Step 5: Display results
            logging.info(f"✅ Processed and saved: `results/{json_filename}`")
            st.download_button(
                label="📥 Download JSON",
                data=json.dumps(updated_data, indent=4),
                file_name=json_filename,
                mime="application/json",
                key=json_filename
            )

            with st.expander(f"📋 View Extracted Data for `{uploaded_file.name}`"):
                st.json(updated_data)
