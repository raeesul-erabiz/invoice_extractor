import re
import logging
from typing import Dict, Any
from collections import OrderedDict

# Configure logging
logging.basicConfig(level=logging.INFO)

class InvoiceHelper:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    def add_item_count(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Add 'item_count' based on the number of valid Line_Items."""
        data["item_count"] = len(data.get("Line_Items", []))
        self.logger.info(f"Total line items {data.get('item_count')}")
        return data

    def calculate_missing_fields(self, data: dict) -> dict:
        self.logger.info("Extracting pack details...")
        if "Coca-Cola" in data.get("supplier_name"):
            data["published_subtotal_excl"] = float(data.get("published_total_incl")) - float(data.get("published_gst_total"))

        for item in data.get("Line_Items", []):
            try:
                # self.logger.info(f"{item.get('product_name')}: {item.get('line_total_excl')}, {item.get('line_total_incl')}, {item.get('line_total_tax')}, {item.get('order_quantity')}, {item.get('price/quantity')}")
                
                # Handle None values properly
                excl = item.get("line_total_excl")
                incl = item.get("line_total_incl")
                tax = item.get("line_total_tax")
                qty = item.get("order_quantity")
                price_quantity = item.get("price/quantity")
                # unit_excl = item.get("order_unit_price_excl")
                # self.logger.info(f"extracted tax: {type(tax)}")

                if excl is not None and isinstance(excl, str) and "$" in excl:
                    # Handle dollar values like $3.79 or $23.85 - use exact value without $
                    excl = float(excl.strip('$'))

                # Convert to float with proper None handling
                excl = float(excl) if excl is not None else 0
                incl = float(incl) if incl is not None else 0
                qty = float(qty) if qty is not None else 1
                # unit_excl = float(unit_excl) if unit_excl is not None else 0

                if data.get("supplier_name", "").strip().lower() == "pnm sydney pty ltd":
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
                    tax_pct = float(tax.strip('%'))
                    tax_amt = excl * tax_pct / 100
                elif tax is not None and isinstance(tax, str) and "$" in tax:
                    # Handle dollar values like $3.79 or $23.85 - use exact value without $
                    tax_amt = float(tax.strip('$'))
                elif tax is not None and isinstance(tax, str):
                    tax_value = float(tax)
                    # If it's an integer (whole number), treat as percentage
                    if tax_value == int(tax_value):
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
                
                unit_tax = round(tax_amt / qty, 4) if qty != 0 else 0
                unit_excl = round(excl / qty, 4) if qty != 0 else 0
                unit_incl = round(unit_excl + unit_tax, 4)
                gst_indicator = "GST" if unit_tax > 0 else "NO GST"

                if item.get("order_unit") in [None, ""]:
                    item["order_unit"] = "EA"

                # Update line item fields
                item["line_total_excl"] = excl
                item["line_total_tax"] = tax_amt
                item["line_total_incl"] = incl
                item["order_unit_price_excl"] = unit_excl
                item["order_unit_tax"] = unit_tax
                item["order_unit_price_incl"] = unit_incl
                item["gst_indicator"] = gst_indicator

                self.logger.info(f"{item.get('product_name')}: {item.get('line_total_excl')}, {item.get('line_total_incl')}, {item.get('line_total_tax')}, {item.get('order_quantity')}")
            except Exception as e:
                self.logger.error(f"❌ Error processing line item: {e}")
        
        return data

    def extract_pack_details(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("Extracting pack details...")
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

    def remove_price_per_quantity_field(data: dict) -> dict:
        for item in data.get("Line_Items", []):
            item.pop("price/quantity", None)  # Safely remove if it exists
        return data

    def normalize_line_items(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("Normalizing line item fields...")
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
        self.logger.info("Normalizing financial fields...")
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
        self.logger.info("Preparing the final output...")
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
        self.logger.info("Updating Anchor Packaging Line Items Tax...")
        # # Apply only for "Anchor Packaging"
        # if data.get("supplier_name") != "anchorpackaging.com.au":
        #     return data  # No change needed
        
        data['supplier_name'] = "Anchor Packaging"

        for item in data.get("Line_Items", []):
            try:
                # Required input fields
                line_total_excl = float(item.get("line_total_excl", 0))
                order_quantity = float(item.get("order_quantity", 1))  # avoid division by zero
                # order_unit_price_excl = float(item.get("order_unit_price_excl", 0))
                # unit = item.get("order_unit")
                # unit = float(unit) if unit is not None else 1

                # Calculations
                line_total_tax = round(line_total_excl * 0.10, 2)
                line_total_incl = round(line_total_excl + line_total_tax, 2)
                # order_quantity = unit
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
                print(f"Error processing item: {item}\n{e}")

        return data

    def reconcile_published_totals(self, data: dict, precision: int = 2) -> dict:
        self.logger.info("Re-Calculating Published Totals of PNM SYDNEY PTY LTD...")
        # 1️⃣  Sum values from line items
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

        # 2️⃣  Fetch any existing published values (default to 0)
        published_subtotal_excl = round(float(data.get("published_subtotal_excl", 0)), precision)
        published_gst_total     = round(float(data.get("published_gst_total", 0)), precision)
        published_total_incl    = round(float(data.get("published_total_incl", 0)), precision)

        # 3️⃣  Decide which values to keep
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
        self.logger.info("Update product name of Allpress Espresso...")
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


    def recalculate_totals_and_variances(self, data: dict) -> dict:
        self.logger.info("Calculating Totals and Variances...")
        line_items = data.get("Line_Items", [])

        # Step 1: Calculate totals from line items
        line_total_excl_tax = sum(float(item.get("line_total_excl", 0)) for item in line_items)

        # Extra components that contribute to GST (10%)
        shipping_cost = float(data.get("shipping_cost", 0))
        picking_charge = float(data.get("picking_charge", 0))
        discount_amount = float(data.get("discount_amount", 0))

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

