import re
import os
import time
import logging
from typing import Dict, Any
from collections import OrderedDict
from invoice_extractor import InvoiceExtractor

extractor = InvoiceExtractor()

# Configure logging
logging.basicConfig(level=logging.INFO)

class InvoiceHelper:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    def exctract_invoice_data(self, invoice_path, llm):
        # Step 1: Extract raw text
        self.logger.info(f"Extracting `{os.path.basename(invoice_path)}` invoice text uisng PDFPlumber")
        extracted_text = extractor.extract_text_from_pdf(invoice_path)

        if "LifeGrainCentralPtyLtd" in extracted_text:
            self.logger.debug("Received LifeGrain Central Kitchen Invoice")
            self.logger.info(f"Extracting `{os.path.basename(invoice_path)}` invoice text Using PyMuPDF")
            extracted_text = extractor.extract_text_from_pdf_pymupdf(invoice_path)
        
        # Step 2: LLM for structured data
        self.logger.info("Extracting invoice structured data uisng LLM")
        start = time.time()
        structured_data = extractor.extract_invoice_data(extracted_text, llm)
        elapsed = round(time.time() - start, 2)
        self.logger.info(f"LLM extraction completed in {elapsed}s")

        if "Allpress Espresso" in extracted_text:
            self.logger.debug("Received Allpress Espresso Invoice")
            allpress_text = extractor.extract_text_from_pdf_pymupdf(invoice_path)
                
            start = time.time()
            allpress_structured = extractor.extract_line_item_data(allpress_text, llm)
            elapsed = round(time.time() - start, 2)
            self.logger.info(f"LLM extraction completed in {elapsed}s")
            # print(structured_data)

            self.logger.info("Update product name of Allpress Espresso...")
            updated_data = self.update_product_names(structured_data, allpress_structured)

        # Step 3: Post-processing
        supplier = structured_data.get("supplier_name")
        
        self.logger.info(f"Extracting pack details of {supplier}")
        updated_data = self.extract_pack_details(structured_data)

        self.logger.info("Calculating Total Line Items.")
        updated_data = self.add_item_count(updated_data)

        self.logger.info("Calculating Line Item's Unit and Total Values")
        updated_data = self.calculate_missing_fields(updated_data)

        # Apply only for "Anchor Packaging"
        supplier_name = (updated_data.get("supplier_name") or "").strip().casefold()
        if supplier_name in {"tax invoice", "anchor packaging", "anchorpackaging.com.au"}:
            self.logger.info("Updating Anchor Packaging Line Items Tax.")
            updated_data = self.recalculate_anchor_packaging_gst(updated_data)

        # Replace Supplier Name
        lck_list = ['Plum SCH', 'Plume Liverpool', 'Lifegrain Liverpool Cafe', 'LifeGrain Central Pty Ltd', 'LifeGrain Sutherland']
        if updated_data.get('supplier_name') in lck_list:
            self.logger.info("Updating Supplier Name into LifeGrain Central Kitchen")
            updated_data['supplier_name'] = 'LifeGrain Central Kitchen'

        # Apply only for "PNM SYDNEY PTY LTD"
        if updated_data.get("supplier_name", "").strip().lower() == "pnm sydney pty ltd":
            self.logger.info("Re-Calculating Published Totals of Premier North Pak.")
            updated_data = self.reconcile_published_totals(updated_data)

        self.logger.info("Normalizing financial fields...")
        updated_data = self.normalize_financial_fields(updated_data)

        self.logger.info("Normalizing line item fields...")
        updated_data = self.normalize_line_items(updated_data)

        updated_data = self.adjust_published_subtotal_by_supplier(updated_data)

        self.logger.info("Calculating Totals and Variances...")
        updated_data = self.recalculate_totals_and_variances(updated_data)

        self.logger.info("Preparing the final output...")
        updated_data = self.reorder_invoice_data(updated_data)

        return updated_data

    def add_item_count(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Add 'item_count' based on the number of valid Line_Items."""
        data["item_count"] = len(data.get("Line_Items", []))
        self.logger.info(f"Total line items {data.get('item_count')}")
        return data

    def calculate_missing_fields(self, data: dict) -> dict:

        for item in data.get("Line_Items", []):
            try:
                # Handle None values properly
                excl = item.get("line_total_excl")
                incl = item.get("line_total_incl")
                tax = item.get("line_total_tax")
                qty = item.get("order_quantity")
                price_quantity = item.get("price/quantity")
                # unit_excl = item.get("order_unit_price_excl")
                # self.logger.info(f"extracted tax: {type(tax)}")

                if excl is not None and isinstance(excl, str) and "$" in excl:
                    self.logger.debug("Line Total Excluding GST has $ mark")
                    # Handle dollar values like $3.79 or $23.85 - use exact value without $
                    excl = float(excl.strip('$'))
                
                if excl is not None and isinstance(excl, str) and "," in excl:
                    self.logger.debug("Line Total Excluding GST has ',' mark")
                    # Handle comma-separated values like 1,256.02 - remove commas
                    excl = float(excl.replace(',', ''))

                # Convert to float with proper None handling
                excl = float(excl) if excl is not None else 0
                incl = float(incl) if incl is not None else 0
                qty = float(qty) if qty is not None else 1
                # unit_excl = float(unit_excl) if unit_excl is not None else 0

                if data.get("supplier_name", "").strip().lower() == "pnm sydney pty ltd":
                    self.logger.info("Calculating Order Quantity from Price/Quantity field for Premier North Pak.")
                    # Calculate new quantity if price/quantity is not null
                    if price_quantity is not None and excl != 0:
                        # Handle string format like '$37.90 / 1000'
                        if isinstance(price_quantity, str):
                            # Remove currency symbols and spaces
                            cleaned = price_quantity.replace('$', '').replace(' ', '')
                            # Split by '/' and calculate the division
                            if '/' in cleaned:
                                parts = cleaned.split('/')
                                if len(parts) == 2:
                                    numerator = float(parts[0])
                                    denominator = float(parts[1])
                                    price_quantity_value = numerator / denominator
                                else:
                                    price_quantity_value = float(cleaned)
                            else:
                                price_quantity_value = float(cleaned)
                        else:
                            price_quantity_value = float(price_quantity)
                            
                        qty = qty * price_quantity_value / excl
                        item["order_quantity"] = qty

                # Determine line_total_tax
                if tax is not None and isinstance(tax, str) and "%" in tax:
                    self.logger.debug("Line Total Tax in Percentage '%' format.")
                    tax_pct = float(tax.strip('%'))
                    tax_amt = excl * tax_pct / 100
                elif tax is not None and isinstance(tax, str) and "$" in tax:
                    self.logger.debug("Line Total Tax in $ format.")
                    # Handle dollar values like $3.79 or $23.85 - use exact value without $
                    tax_amt = float(tax.strip('$'))
                elif tax is not None and isinstance(tax, str):
                    tax_value = float(tax)
                    # Check if the original string contains a decimal point
                    if "." in tax:
                        self.logger.debug("Line Total Tax in Float format.")
                        # If it contains a decimal, treat as exact value (float)
                        tax_amt = tax_value
                    # If it's an integer (whole number), treat as percentage
                    elif tax_value == int(tax_value):
                        self.logger.debug("Line Total Tax in Integer '%' format.")
                        tax_amt = excl * (tax_value / 100)
                    else:
                        # If it's a float, use exact value
                        tax_amt = tax_value
                else:
                    # Handle case where tax is None or invalid
                    if incl > 0 and excl > 0:
                        tax_amt = incl - excl
                    else:
                        tax_amt = 0

                # Recalculate and update fields
                tax_amt = round(tax_amt, 4)
                
                self.logger.debug("Calculating Line Total Exluding or Including GST.")
                # Special condition: if excl > 0 and tax == 0.00 then incl = excl
                if incl > 0 and tax_amt == 0.00:
                    excl = incl
                # If we have excl but not incl, calculate incl
                elif excl > 0 and incl == 0:
                    incl = round(excl + tax_amt, 4)
                # If we have incl but not excl, calculate excl
                elif incl > 0 and excl == 0:
                    excl = round(incl - tax_amt, 4)
                # If we have both, ensure consistency
                elif excl > 0 and incl > 0:
                    incl = round(excl + tax_amt, 4)
                
                self.logger.debug("Calculating Line Unit Fields")
                unit_tax = round(tax_amt / qty, 4) if qty != 0 else 0
                unit_excl = round(excl / qty, 4) if qty != 0 else 0
                unit_incl = round(unit_excl + unit_tax, 4)
                gst_indicator = "GST" if unit_tax > 0 else "NO GST"

                if item.get("order_unit") in [None, ""]:
                    item["order_unit"] = "EA"
                
                self.logger.debug("Updating the Line Total and Unit Fields Value.")
                # Update line item fields
                item["line_total_excl"] = excl
                item["line_total_tax"] = tax_amt
                item["line_total_incl"] = incl
                item["order_unit_price_excl"] = unit_excl
                item["order_unit_tax"] = unit_tax
                item["order_unit_price_incl"] = unit_incl
                item["gst_indicator"] = gst_indicator

                self.logger.info(f"Extracted: {item.get('product_name')} - Qty: {qty}, Total: ${incl}")
            except Exception as e:
                self.logger.error(f"❌ Error processing line item: {e}")
        
        return data

    def extract_pack_details(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract order_unit_size, pack_unit, and pack_size from product_name for each line item."""
        
        pack_patterns = [
            # Most specific pattern for quantity X size + unit
            (r'(\d+)X(\d+(?:\.\d+)?)(GM)', 'gm_raw_pattern'),  # 85X160GM
            (r'(\d+)X(\d+(?:\.\d+)?)(KG|G|L|ML|PC|EA)', 'qtyxsize_unit'),  # 6X1KG, 8X9PC
            (r'(\d+)\s*[xX]\s*(\d+(?:\.\d+)?)([A-Z]{1,4})', 'spaced_qtyxsize_unit'),  # 12 X 1LT

            # Old legacy patterns (e.g. 1.5KX8, 500MLX12)
            (r'(\d+(?:\.\d+)?)(PK)X(\d+)', 'pk_pattern'),        # 30PKX6
            (r'(\d+(?:\.\d+)?)(K|KG)X(\d+)', 'kg_pattern'),      # 1.5KX8, 2KX6
            (r'(\d+(?:\.\d+)?)(G)X(\d+)', 'g_pattern'),          # 900GX10
            (r'(\d+(?:\.\d+)?)(ML)X(\d+)', 'ml_pattern'),        # 500MLX24
            (r'(\d+(?:\.\d+)?)(L)X(\d+)', 'l_pattern'),          # 1LX8
            (r'(\d+)\s*(PET|FLO|NRB)\s*X(\d+)', 'ml_pack_bottle_pattern'),  # 600 PET X24, 600 FLO X24, 600 NRB X24 
            
            # Simple unit size only
            (r'(\d+(?:\.\d+)?)(K|KG)', 'kg_single'),             # 1.5K
            (r'(\d+(?:\.\d+)?)(G)', 'g_single'),                 # 165G
            (r'(\d+(?:\.\d+)?)(ML)', 'ml_single'),               # 500ML
            (r'(\d+(?:\.\d+)?)(L)', 'l_single'),                 # 1L
            
            # Count-only formats
            (r'(\d+)X(\d+)', 'count_pattern'),                   # 8X1
            (r'^(\d+)\b', 'numeric_quantity_prefix'),            # 4000
            (r'(\d+)(PK)', 'pk_only_pattern'),                   # 6PK
        ]

        for item in data.get("Line_Items", []):
            if data.get("supplier_name", "").strip().lower() == "pnm sydney pty ltd":
                self.logger.info("Extracting pack details Price/Quantity field for Premier North Pak.")
                price_quantity = item.get("price/quantity")
                # Calculate new quantity if price/quantity is not null
                if price_quantity is not None:
                    order_unit_size, pack_unit, pack_size = None, None, None
                    # Handle string format like '$37.90 / 1000'
                    if isinstance(price_quantity, str):
                        # Remove currency symbols and spaces
                        cleaned = price_quantity.replace('$', '').replace(' ', '')
                        # Split by '/' and calculate the division
                        if '/' in cleaned:
                            parts = cleaned.split('/')
                            if len(parts) == 2:
                                pack_size = float(parts[1])
                                pack_unit = "EA"
                                order_unit_size = 1.0
                        
                    # Set extracted values or default empty
                    item["order_unit_size"] = order_unit_size
                    item["pack_size"] = pack_size
                    item["pack_unit"] = pack_unit

            else:
                self.logger.info("Extracting pack details using product name")
                product_name = item.get("product_name", "")
                order_unit_size, pack_unit, pack_size = None, None, None

                for pattern, pattern_type in pack_patterns:
                    match = re.search(pattern, product_name, re.IGNORECASE)
                    if match:
                        if pattern_type == 'qtyxsize_unit':
                            order_unit_size = int(match.group(1))
                            pack_size = float(match.group(2))
                            unit = match.group(3).upper()
                            pack_unit = (
                                'KG' if unit in ['K', 'KG']
                                else 'L' if unit in ['ML', 'L']
                                else 'EA' if unit in ['PC', 'EA']
                                else unit
                            )
                            if unit == 'G':
                                pack_size /= 1000
                                pack_unit = 'KG'
                            elif unit == 'ML':
                                pack_size /= 1000
                                pack_unit = 'L'

                        elif pattern_type == 'gm_raw_pattern':
                            order_unit_size = int(match.group(1))
                            pack_size = float(match.group(2)) / 1000 # GM → KG
                            pack_unit = 'KG'

                        elif pattern_type == 'spaced_qtyxsize_unit':
                            order_unit_size = int(match.group(1))
                            pack_size = float(match.group(2))
                            unit_raw = match.group(3).upper()

                            # Normalize the unit to standard form
                            if unit_raw in ["LT", "LTR", "LITRE", "LITRES"]:
                                pack_unit = "L"
                            elif unit_raw in ["ML", "MILLILITRE", "MILLILITRES"]:
                                pack_size /=1000
                                pack_unit = "L"
                            elif unit_raw in ["KG", "KGS", "KILOGRAM"]:
                                pack_unit = "KG"
                            elif unit_raw in ["G", "GM", "GRAM", "GRAMS"]:
                                pack_size /=1000
                                pack_unit = "KG"
                            elif unit_raw in ["PC", "PCS", "EA", "EACH"]:
                                pack_unit = "EA"
                            else:
                                pack_unit = unit_raw  # fallback if new/unknown

                        elif pattern_type == 'pk_pattern':
                            order_unit_size = int(match.group(1))
                            pack_size = float(match.group(3))
                            pack_unit = 'EA'

                        elif pattern_type in ['kg_pattern', 'g_pattern', 'ml_pattern', 'l_pattern']:
                            pack_size = float(match.group(1))
                            unit = match.group(2).upper()
                            order_unit_size = int(match.group(3))

                            if unit == 'G':
                                pack_size /= 1000
                                pack_unit = 'KG'
                            elif unit == 'ML':
                                pack_size /= 1000
                                pack_unit = 'L'
                            elif unit == 'K':
                                pack_unit = 'KG'
                            elif unit == 'L':
                                pack_unit = 'L'
                            else:
                                pack_unit = unit
                            
                        elif pattern_type == 'ml_pack_bottle_pattern':
                            pack_size = float(match.group(1)) / 1000  # convert ml to L
                            pack_unit = "L"
                            order_unit_size = int(match.group(3))

                        elif pattern_type in ['kg_single', 'g_single', 'ml_single', 'l_single']:
                            pack_size = float(match.group(1))
                            unit = match.group(2).upper()
                            order_unit_size = 1

                            if unit == 'G':
                                pack_size /= 1000
                                pack_unit = 'KG'
                            elif unit == 'ML':
                                pack_size /= 1000
                                pack_unit = 'L'
                            elif unit == 'K':
                                pack_unit = 'KG'
                            elif unit == 'L':
                                pack_unit = 'L'
                            else:
                                pack_unit = unit
                        
                        elif pattern_type == 'count_pattern':
                            order_unit_size = int(match.group(1))
                            pack_size = float(match.group(2))
                            pack_unit = 'EA'

                        elif pattern_type == 'numeric_quantity_prefix':
                            order_unit_size = 1
                            pack_size = 1.0
                            pack_unit = 'EA'
                        
                        elif pattern_type == 'pk_only_pattern':
                            order_unit_size = int(match.group(1))
                            pack_size = 1.0
                            pack_unit = 'EA'

                        break  # Exit loop after the first matching pattern

                # Set extracted values or default empty
                item["order_unit_size"] = order_unit_size if order_unit_size is not None else 1
                item["pack_size"] = pack_size if pack_size is not None else 1.0
                item["pack_unit"] = pack_unit if pack_unit is not None else 'EA'

        return data

    
    def normalize_line_items(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize values in each line item: clean product name and convert numeric fields."""
        
        numeric_keys = [
            "order_quantity", "order_unit_price_excl", "order_unit_price_incl",
            "order_unit_tax", "line_total_excl", "line_total_incl", "line_total_tax", "pack_size"
        ]
        
        for item in data.get("Line_Items", []):
            # Clean product name: remove \n and extra whitespace
            name = item.get("product_name", "")
            item["product_name"] = ' '.join(name.replace("\n", " ").split())

            # Convert numeric fields
            for key in numeric_keys:
                value = item.get(key)
                try:
                    item[key] = float(str(value).replace(",", "")) if value not in [None, ""] else 0.0
                except (ValueError, TypeError):
                    item[key] = 0.0

        return data

    def normalize_financial_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert financial string fields to float and replace null/empty with 0.0."""
        
        keys_to_normalize = [
            "discount_amount", "total_excl_tax", "shipping_cost", "total_tax", "rounding",
            "picking_charge", "total_amount", "published_subtotal_excl", "published_gst_total",
            "published_total_incl"
        ]
        
        for key in keys_to_normalize:
            value = data.get(key)
            try:
                if value is None or value == "":
                    data[key] = 0.0
                else:
                    # Remove commas and convert to float
                    data[key] = float(str(value).replace(",", ""))
            except (ValueError, TypeError):
                # If conversion fails, fallback to 0.0
                data[key] = 0.0

        return data

    def reorder_invoice_data(self, data: dict) -> dict:
        # Desired top-level order
        top_level_order = [
            "supplier_name", "store_name", "invoice_number", "invoice_date", "due_date", "purchase_order",
            "item_count", "discount_amount", "total_excl_tax", "shipping_cost", "total_tax",
            "rounding", "picking_charge", "total_amount", "published_subtotal_excl", "published_gst_total",
            "published_total_incl", "subtotal_variance", "gst_variance", "total_variance", "Line_Items"
        ]

        # Desired line item order
        line_item_order = [
            "product_name", "product_code", "order_quantity", "order_unit",
            "order_unit_price_excl", "order_unit_price_incl", "order_unit_tax",
            "order_unit_size", "pack_size", "pack_unit", 
            "gst_indicator", "line_total_excl", "line_total_incl", "line_total_tax"
        ]

        # Reorder line items if present
        reordered_items = []
        for item in data.get("Line_Items", []):
            item.pop("price/quantity", None)  # Safely remove if it exists
            reordered_item = OrderedDict()
            for key in line_item_order:
                if key in item:
                    reordered_item[key] = item[key]
            # Append any unexpected keys at the end
            for k in item:
                if k not in reordered_item:
                    reordered_item[k] = item[k]
            reordered_items.append(reordered_item)

        # Build the final top-level dict
        reordered_data = OrderedDict()
        for key in top_level_order:
            if key == "Line_Items":
                reordered_data[key] = reordered_items
            elif key in data:
                reordered_data[key] = data[key]
        # Append any other top-level fields not listed
        for k in data:
            if k not in reordered_data:
                reordered_data[k] = data[k]

        return reordered_data

    def recalculate_anchor_packaging_gst(self, data: dict) -> dict:
        self.logger.info("Adding 10% Tax for Every Line Item.")
        data['supplier_name'] = "Anchor Packaging"
        
        for item in data.get("Line_Items", []):
            try:
                # Required input fields
                line_total_excl = float(item.get("line_total_excl", 0))
                order_quantity = float(item.get("order_quantity", 1))  # avoid division by zero

                # Calculations
                line_total_tax = round(line_total_excl * 0.10, 2)
                line_total_incl = round(line_total_excl + line_total_tax, 2)
                unit = "EA"
                order_unit_tax = round(line_total_tax / order_quantity, 4)
                order_unit_price_excl = round(line_total_excl / order_quantity, 4)
                order_unit_price_incl = round(order_unit_price_excl + order_unit_tax, 4)

                # Assign back to item
                item["line_total_tax"] = line_total_tax
                item["line_total_incl"] = line_total_incl
                item["order_quantity"] = order_quantity
                item["order_unit"] = unit
                item["order_unit_price_excl"] = order_unit_price_excl
                item["order_unit_tax"] = order_unit_tax
                item["order_unit_price_incl"] = order_unit_price_incl
                item["gst_indicator"] = "GST"
            except Exception as e:
                self.logger.error(f"Error processing item: {item}\n{e}")

        return data

    def reconcile_published_totals(self, data: dict, precision: int = 2) -> dict:
        # Sum values from line items
        line_items = data.get("Line_Items", [])
        new_subtotal_excl = round(
            sum(float(item.get("line_total_excl", 0)) for item in line_items),
            precision,
        )
        new_gst_total = round(
            sum(float(item.get("line_total_tax", 0)) for item in line_items),
            precision,
        )
        new_total_incl = round(
            sum(float(item.get("line_total_incl", 0)) for item in line_items),
            precision,
        )

        # Fetch any existing published values (default to 0)
        published_subtotal_excl = round(float(data.get("published_subtotal_excl", 0)), precision)
        published_gst_total     = round(float(data.get("published_gst_total", 0)), precision)
        published_total_incl    = round(float(data.get("published_total_incl", 0)), precision)

        # Decide which values to keep
        data["published_subtotal_excl"] = (
            published_subtotal_excl
            if published_subtotal_excl == new_subtotal_excl
            else new_subtotal_excl
        )
        data["published_gst_total"] = (
            published_gst_total
            if published_gst_total == new_gst_total
            else new_gst_total
        )
        data["published_total_incl"] = (
            published_total_incl
            if published_total_incl == new_total_incl
            else new_total_incl
        )

        return data
    
    def update_product_names(self, structured: dict, new_structured: dict) -> dict:
        """
        Replace product_name in `structured` where product_code matches in `new_structured`.
        """
        # Build a lookup from new_structured by product_code
        code_to_name = {
            item.get("product_code"): item.get("product_name")
            for item in new_structured.get("Line_Items", [])
            if item.get("product_code") and item.get("product_name")
        }

        # Iterate and replace in structured
        for item in structured.get("Line_Items", []):
            code = item.get("product_code")
            if code in code_to_name:
                item["product_name"] = code_to_name[code]

        return structured

    def adjust_published_subtotal_by_supplier(self, data: dict) -> dict:
        """
        Adjust `published_subtotal_excl` based on supplier-specific rules.

        - For Coca-Cola: published_subtotal = total - gst
        - For Food & Dairy: published_subtotal = total (if subtotal is 0)
        """
        published_total = float(data.get("published_total_incl", 0))
        published_gst = float(data.get("published_gst_total", 0))
        published_subtotal = float(data.get("published_subtotal_excl", 0))
        supplier_name = data.get("supplier_name", "")

        if "Coca-Cola" in supplier_name:
            self.logger.info("Calculating Published SubTotal for Coca-Cola Invoice.")
            data["published_subtotal_excl"] = round(published_total - published_gst, 2)

        elif "Food & Dairy" in supplier_name:
            self.logger.info("Calculating Published SubTotal for Food & Dairy Invoice.")
            if published_total == 0 and published_subtotal > 0:
                data["published_total_incl"] = round(published_subtotal, 2)
            elif published_total > 0 and published_subtotal == 0:
                data["published_subtotal_excl"] = round(published_total, 2)

        return data


    def recalculate_totals_and_variances(self, data: dict) -> dict:
        line_items = data.get("Line_Items", [])

        # Step 1: Calculate totals from line items
        line_total_excl_tax = sum(float(item.get("line_total_excl", 0)) for item in line_items)

        # Extra components that contribute to GST (10%)
        shipping_cost = float(data.get("shipping_cost", 0))
        picking_charge = float(data.get("picking_charge", 0))
        discount_amount = float(data.get("discount_amount", 0))
        supplier_name = data.get("supplier_name", "")

        # Apply only for "PFD Food Services"
        if "PFD Food Services" in supplier_name:
            self.logger.info(f"Updating Shipping Cost of PFD Food Services")
            if shipping_cost > 0:
                shipping_tax = round(shipping_cost * 0.1, 2)
                data["shipping_cost"] = round(shipping_cost + shipping_tax, 2)

        # Compute Total Amount Excluding GST
        extra_total = (shipping_cost + picking_charge + discount_amount)
        total_excl_tax = line_total_excl_tax + extra_total

        # Compute base tax and add GST from extra charges
        item_tax = sum(float(item.get("line_total_tax", 0)) for item in line_items)
        extra_tax = (shipping_cost + picking_charge + discount_amount) * 0.1
        total_tax = item_tax + extra_tax

        # Total amount = sum of line item totals
        total_amount = total_excl_tax + total_tax

        # Step 2: Fetch published fields
        published_subtotal_excl = float(data.get("published_subtotal_excl", 0))
        published_gst_total = float(data.get("published_gst_total", 0))
        published_total_incl = float(data.get("published_total_incl", 0))

        # Step 3: Calculate variances
        subtotal_variance = round(published_subtotal_excl - total_excl_tax, 2)
        gst_variance = round(published_gst_total - total_tax, 2)
        total_variance = round(published_total_incl - total_amount, 2)

        # Step 4: Update the JSON
        data["total_excl_tax"] = round(total_excl_tax, 2)
        data["total_tax"] = round(total_tax, 2)
        data["total_amount"] = round(total_amount, 2)
        data["subtotal_variance"] = subtotal_variance
        data["gst_variance"] = gst_variance
        data["total_variance"] = total_variance

        return data

