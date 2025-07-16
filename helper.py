import re
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_item_count(data: Dict[str, Any]) -> Dict[str, Any]:
    logging.info("🔢 Adding line item count...")
    """Add 'item_count' based on the number of valid Line_Items."""
    data["item_count"] = len(data.get("Line_Items", []))
    return data

def extract_pack_details(data: Dict[str, Any]) -> Dict[str, Any]:
    logging.info("📦 Extracting pack details...")
    """Extract order_unit_size, pack_unit, and pack_size from product_name for each line item."""
    
    pack_patterns = [
        # Most specific pattern for quantity X size + unit
        (r'(\d+)X(\d+(?:\.\d+)?)(GM)', 'gm_raw_pattern'),  # 85X160GM
        (r'(\d+)X(\d+(?:\.\d+)?)(KG|G|L|ML|PC|EA)', 'qtyxsize_unit'),  # 6X1KG, 8X9PC

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

from typing import Dict, Any

def normalize_line_items(data: Dict[str, Any]) -> Dict[str, Any]:
    logging.info("🧾 Normalizing line item fields...")
    """Normalize values in each line item: clean product name and convert numeric fields."""
    
    numeric_keys = [
        "order_quantity",
        "order_unit_price_excl",
        "order_unit_price_incl",
        "order_unit_tax",
        "line_total_excl",
        "line_total_incl",
        "pack_size"
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


def normalize_financial_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    logging.info("💰 Normalizing financial fields...")
    """Convert financial string fields to float and replace null/empty with 0.0."""
    
    keys_to_normalize = [
        "discount_amount",
        "total_excl_tax",
        "shipping_cost",
        "total_tax",
        "rounding",
        "picking_charge",
        "total_amount"
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
