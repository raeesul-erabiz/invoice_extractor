import os
import streamlit as st
import pdfplumber
import json
import logging
from langchain.prompts import PromptTemplate
from langchain.schema.messages import HumanMessage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_text_from_pdf(pdf_path):
    """Extracts text content from a PDF file."""
    logging.info(f"📄 Extracting text from PDF: `{os.path.basename(pdf_path)}`")
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                logging.info(f"🔄 Processing page {page_num}...")
                extracted_text = page.extract_text()
                if extracted_text:
                    text += extracted_text + "\n"
                    logging.info(f"✅ Extracted {len(extracted_text)} characters from page {page_num}")
        if text:
            logging.info(f"🟢 Extracted total {len(text)} characters.")
            return text
        else:
            logging.warning("⚠️ No text content found in the PDF.")
            return None
    except Exception as e:
        logging.error(f"❌ Error extracting text from PDF: {str(e)}")
        return None


def extract_invoice_data(text, llm):
    logging.info("🧠 Running LLM for structured invoice data...")
    
    prompt_template = PromptTemplate(
        input_variables=["text"],
        template="""
You are an expert AI system specialized in extracting structured data from supplier invoices.

You will be provided with one or more supplier invoice pages. Your task is to extract the following structured invoice data in strict JSON format.

IMPORTANT INSTRUCTIONS:
1. Extract all visible data from the invoice without skipping any field.
2. Use exact field names and structure shown in the output schema.
3. If a field is missing or unclear, return it as an empty string "" or null.
4. Always return the invoice_date and due_date in the format DD/MM/YYYY (e.g., 27/06/2025).
5. Return only the JSON object without any explanation or commentary.
6. Do not hallucinate or invent values.

===== HEADER FIELDS =====
Extract the following fields from the header or summary section of the invoice:
- supplier_name: usually near the top or next to "TAX INVOICE"
- store_name: store address can found under "Ship To:"
- invoice_number: near the label "Invoice:"
- invoice_date: must be formatted as DD/MM/YYYY
- due_date: must be formatted as DD/MM/YYYY
- purchase_order: near "PO", "Purchase Order", or "Reference"
- total_excl_tax: Total amount excluding GST. labeled like "Net Line Total" or "Total Excl. GST"
- total_tax: Total tax amount of invoice. labeled like "TOTAL GST" or "GST Amount"
- rounding: labeled as "Rounding on Invoices"
- total_amount: Total amount including GST. labeled like "INVOICE TOTAL (GST Incl.)"

===== LINE ITEM FIELDS =====
For each product listed in the line items section:
- product_name: return the **exact** value of Description like '1KX12 CHICKEN BITES SOUTHER STYLE SUBWAY', '2000 COOKIE BAG REFRESH SUBWAY'
- product_code: the numeric or alphanumeric code before the description
- order_quantity: from "Qty Supplied"
- order_unit: always return "CTN"
- order_unit_price_excl: calculated as line_total_excl / Qty Supplied
- order_unit_price_incl: calculated as order_unit_price_excl + order_unit_tax
- order_unit_tax: calculated as GST / Qty Supplied
- line_total_excl: Line total Net Value excluding GST 
- line_total_incl: Total Incl. GST
- gst_indicator: "GST" if order_unit_tax > 0 else "NO GST"

===== SPECIAL CONDITIONS =====
Exclude the following line items from `Line_Items` and handle them separately:

- If `product_name` or description contains **"Freight"** or **"Fuel Levy"**:
  - Set `"shipping_cost"` to the Net Value (excluding GST), or `0.0` if not found.

- If it contains **"Case Rate"**:
  - Set `"picking_charge"` to the Net Value, or `0.0` if not found.

- If it contains **"Direct Debit Incentive"** or **"Minimum Order Qty Incentive"**:
  - Set `"discount_amount"` to the Net Value, or `0.0` if not found.

===== OUTPUT FORMAT =====
Always return a valid JSON object in the following structure:

```json
{{
  "supplier_name": "",
  "store_name": "",
  "invoice_number": "",
  "invoice_date": "",
  "due_date": "",
  "purchase_order": "",
  "Line_Items": [
    {{
      "product_name": "",
      "product_code": "",
      "order_quantity": "",
      "order_unit": "CTN",
      "order_unit_price_excl": "",
      "order_unit_price_incl": "",
      "order_unit_tax": "",
      "gst_indicator": "",
      "line_total_excl": "",
      "line_total_incl": ""
    }}
  ],
  "discount_amount": "",
  "total_excl_tax": "",
  "shipping_cost": "",
  "total_tax": "",
  "rounding": "",
  "picking_charge": "",
  "total_amount": ""
}}

Here is the invoice text:
{text}
"""
    )

    prompt = prompt_template.format(text=text)
    response = llm.invoke([HumanMessage(content=prompt)])
    try:
        # Clean the response content to handle potential markdown formatting
        content = response.content.strip()
        
        # Remove markdown code blocks if present
        if content.startswith("```json"):
            content = content[7:]  # Remove ```json
        if content.startswith("```"):
            content = content[3:]   # Remove ```
        if content.endswith("```"):
            content = content[:-3]  # Remove trailing ```
        
        # Parse JSON
        extracted_data = json.loads(content)

        return extracted_data
    except json.JSONDecodeError:
        return {"error": "Failed to parse JSON from LLM response", "raw_output": response.content}