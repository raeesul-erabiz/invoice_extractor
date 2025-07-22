import os
import streamlit as st
import pdfplumber
import json
import logging
import fitz
from langchain.prompts import PromptTemplate
from langchain.schema.messages import HumanMessage

# Configure logging
logging.basicConfig(level=logging.INFO)

class InvoiceExtractor:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    def extract_text_from_pdf(self, pdf_path):
        """Extracts text content from a PDF file."""
        self.logger.info(f"Extracting text from PDF: `{os.path.basename(pdf_path)}`")
        text = ""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    self.logger.info(f"Processing page {page_num}...")
                    extracted_text = page.extract_text()
                    if extracted_text:
                        text += extracted_text + "\n"
                        self.logger.info(f"Extracted {len(extracted_text)} characters from page {page_num}")
            if text:
                self.logger.info(f"Extracted total {len(text)} characters.")
                return text
            else:
                self.logger.warning("No text content found in the PDF.")
                return None
        except Exception as e:
            self.logger.error(f"Error extracting text from PDF: {str(e)}")
            return None

    def extract_text_from_pdf_pymupdf(self, pdf_path):
        """Extracts text content from a PDF file using PyMuPDF (fitz)."""
        self.logger.info(f"Extracting text from PDF Using PyMuPDF: `{os.path.basename(pdf_path)}`")
        text = ""
        try:
            with fitz.open(pdf_path) as doc:
                for page_num in range(len(doc)):
                    self.logger.info(f"Processing page {page_num + 1}...")
                    page = doc[page_num]
                    extracted_text = page.get_text()
                    if extracted_text:
                        text += extracted_text + "\n"
                        self.logger.info(f"Extracted {len(extracted_text)} characters from page {page_num + 1}")
            if text:
                self.logger.info(f"Extracted total {len(text)} characters.")
                return text
            else:
                self.logger.warning("No text content found in the PDF.")
                return None
        except Exception as e:
            self.logger.error(f"Error extracting text from PDF: {str(e)}")
            return None

    def extract_invoice_data(self, text, llm):
        self.logger.info("Running LLM for structured invoice data...")

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
- `store_name`: Extract the full delivery address or recipient address located under or near headings such as "Ship To:", "Invoice To:", or "Delivery Address".
- `invoice_number`: Labeled as "Invoice", "Invoice No", "Invoice Nr", etc.
- `invoice_date`: The invoice issue date.
- `due_date`: If a specific date is present, return it. If not, and there is a "Due in X days" or similar (e.g., "Terms: 14 Days"), calculate: `due_date = invoice_date + due days`.
- `purchase_order`: Labeled as "PO", "Purchase Order", "Reference", "Customer Order No", "Order Ref", or "Order No".
- `published_total_incl`: Total amount **including GST**, labeled as "INVOICE TOTAL (GST Incl.)", "TOTAL DUE", or "TOTAL AMOUNT".
- `published_gst_total`: Labeled as "TOTAL GST", "GST", "GST Amount", or "Total GST".
- `published_subtotal_excl`: If labeled (e.g., "Net Line Total", "Total Excl. GST", "SUB TOTAL"), extract the value. If not found, but both **"TAXABLE ITEM TOTAL"** and **"NON-TAXABLE ITEM TOTAL"** are available, calculate: `published_subtotal_excl = TAXABLE ITEM TOTAL + NON-TAXABLE ITEM TOTAL`.
- `rounding`: If a "Rounding" field or adjustment is shown, include it.

===============================
LINE ITEM FIELDS
===============================

For each product in the line items table:

- `product_code`: A numeric or alphanumeric value found in the product code column (e.g., "No.", "Item No", "Item Code", "Stock", "Product Code", "Code", "Material No", etc.). Must be extracted **separately** from the description.
- `product_name`: Return the full string from the "Description" or "Product" column exactly as shown.
- `order_quantity`: Extract the value only from a properly labeled column such as **"Quantity"**, **"Qty"**, **"Qty Supplied"**, **"Ordered"**, **"Inv Qty"**, or **"Sales Qty"**. Do not extract numeric values from product descriptions, item names, or nearby fields unless they are clearly under one of the specified column headers. 
- `price/quantity`: Extract the value **only if** there is a column explicitly labeled "PRICE / QTY". Do not infer or calculate this value from any other field. If the column "PRICE / QTY" does not exist or the value is missing, return this field as empty.
- `order_unit`: Extract the value under the "Unit" or "UOM" column (e.g., Bottle, Box, Ctn, Pack, etc.).
- `line_total_excl`: Extract value from a column labeled "Net Value", "Ex. GST Amount", "Total Amt Ex GST", "Extended Price IncL CDS excl GST", or similar.
- `line_total_tax`: Extract the raw tax value for each line item from any of the following columns (if present): **"GST"**, **"GST Amt"**, **"Tax Amount"**, **"Tax Rate"**, **"GST Rate"**, **"GST %"**, or **"Tax %"**.  
  - Do not perform any calculations — only extract the value **exactly as shown**, even if it's a **percentage** (e.g., `10`, `10%`, or `0%`), or a raw numeric amount (e.g., `12.21`, `13.02`, `26.04`, or similar).  
  - **Do not skip 0%** — return `"0%"` or `0` as-is if that's what appears in the invoice.  
  - If none of these columns exist, or no value is shown, leave this field empty.
- `line_total_incl`: Extract value from a column labeled "Total Incl. GST", "Total incl Taxes", "Incl. GST Amount", or similar. Do not calculate this value.

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
  "published_subtotal_excl": "",
  "shipping_cost": "",
  "published_gst_total": "",
  "rounding": "",
  "picking_charge": "",
  "published_total_incl": "",
  "Line_Items": [
    {{
      "product_code": "",
      "product_name": "",
      "order_quantity": "",
      "price/quantity": "",
      "order_unit": "",
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

    def extract_line_item_data(self, text, llm):
      self.logger.info("Running LLM for structured invoice data...")

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
4. Return **only** a JSON object — no commentary or markdown.
5. Do not hallucinate or guess values.
6. Use calculated values **only if labels are not found**.

===============================
LINE ITEM FIELDS
===============================

For each product in the line items table:

- `product_code`: A numeric or alphanumeric value found in the product code column (e.g., "No.", "Item No", "Item Code", "Stock", "Product Code", "Code", "Material No", etc.). Must be extracted **separately** from the description.
- `product_name`: Return the full string from the "Description" or "Product" column exactly as shown.

===============================
JSON OUTPUT FORMAT
===============================

Return only the following structured JSON:

```json
{{
  "Line_Items": [
    {{
      "product_code": "",
      "product_name": ""
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