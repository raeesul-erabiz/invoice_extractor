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

You will be provided with text extracted from a supplier invoice PDF. Your task is to extract the following structured invoice data in **valid JSON format** using the instructions below.

===============================
IMPORTANT INSTRUCTIONS
===============================
1. Extract all relevant information without skipping any field.
2. Use **only** the fields and format shown in the schema below.
3. If a field is missing or unclear, return it as an empty string "" or null.
4. Dates must always be returned in the format DD/MM/YYYY (e.g., 27/06/2025).
5. Return **only** a JSON object — no commentary or markdown.
6. Do not hallucinate or guess values.
7. Use calculated values **only if labels are not found**.

===============================
HEADER FIELDS
===============================

Extract the following from the invoice header or summary section:

- `supplier_name`: Usually near the top or next to "TAX INVOICE".
- `store_name`: Found under or near "Ship To:", "Invoice To:" or delivery address.
- `invoice_number`: Labeled as "Invoice", "Invoice No", "Invoice Nr", etc.
- `invoice_date`: The invoice issue date.
- `due_date`: If a specific date is present, return it. If not, and there is a "Due in X days" or similar (e.g., "Terms: 14 Days"), calculate: `due_date = invoice_date + due days`.
- `purchase_order`: Labeled as "PO", "Purchase Order", "Reference", "Order Ref", or "Order No".
- `total_amount`: Total amount **including GST**, labeled as "INVOICE TOTAL (GST Incl.)", "TOTAL DUE", or "TOTAL AMOUNT".
- `total_tax`: Labeled as "TOTAL GST", "GST Amount", or "Total GST Included".
- `total_excl_tax`: If labeled (e.g., "Net Line Total", "Total Excl. GST", "SUB TOTAL"), extract the value. If not found, but both **"TAXABLE ITEM TOTAL"** and **"NON-TAXABLE ITEM TOTAL"** are available, calculate: `total_excl_tax = TAXABLE ITEM TOTAL + NON-TAXABLE ITEM TOTAL` Otherwise, calculate: `total_excl_tax = total_amount - total_tax`
- `rounding`: If a "Rounding" field or adjustment is shown, include it.

===============================
LINE ITEM FIELDS
===============================

For each product in the line items table:

- `product_code`: Value under column labeled "Item No", "Item Code", "Stock", "Product Code", "Code", or "Material No".
- `product_name`: Return the full string from the "Description" or "Product" column exactly as shown.
- `order_quantity`: From "Quantity", "Qty", "Qty Supplied", or "Sales Qty" column.
- `order_unit`: Always return "CTN"
- `line_total_excl`: From "Net Value", "Ex. GST Amount", "Total Amt Ex GST", or similar.
- `line_total_incl`: From "Total Incl. GST", "Total incl Taxes", or similar. If not found, calculate: `line_total_excl + line_total_tax`.
- `line_total_tax`: If labeled (e.g., "GST", "Tax Amount"), extract it. If not available, and a **Tax Rate** column exists, calculate: `line_total_tax = line_total_excl * (Tax Rate / 100)` Otherwise, calculate: `line_total_tax = line_total_incl - line_total_excl`
- `order_unit_price_excl`: Labeled as "Unit Price", "Unit Price Ex GST", or calculate: `line_total_excl / order_quantity`
- `order_unit_tax`: If not labeled, calculate: `line_total_tax / order_quantity`
- `order_unit_price_incl`: If not labeled, calculate: `order_unit_price_excl + order_unit_tax`
- `gst_indicator`: Return "GST" if `order_unit_tax > 0`, otherwise "NO GST"

===============================
SPECIAL CONDITIONS
===============================

Exclude the following items from `Line_Items` and handle separately:

- If `product_name` or description contains **"Freight"** or **"Fuel Levy"**:
  - Set `"shipping_cost"` to the line total excluding GST, or `0.0` if not found.

- If it contains **"Case Rate"**:
  - Set `"picking_charge"` to the line total excluding GST, or `0.0` if not found.

- If it contains **"Direct Debit Incentive"** or **"Minimum Order Qty Incentive"**:
  - Set `"discount_amount"` to the line total excluding GST, or `0.0` if not found.

These excluded items must not be included in `Line_Items`.

===============================
JSON OUTPUT FORMAT
===============================

Return only the following structured JSON:

```json
{{
  "supplier_name": "",
  "store_name": "",
  "invoice_number": "",
  "invoice_date": "",
  "due_date": "",
  "purchase_order": "",
  "discount_amount": "",
  "total_excl_tax": "",
  "shipping_cost": "",
  "total_tax": "",
  "rounding": "",
  "picking_charge": "",
  "total_amount": "",
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
      "line_total_incl": "",
      "line_total_tax": ""
    }}
  ]
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