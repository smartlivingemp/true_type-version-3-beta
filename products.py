from flask import Blueprint, render_template, request, jsonify
from bson import ObjectId
from datetime import datetime
from db import db
import re

products_bp = Blueprint("products", __name__, template_folder="templates")
products_collection = db["products"]
clients_collection  = db["clients"]  # NEW: we’ll read clients + phone numbers

# -------------------- helpers --------------------

_GH_DEFAULT_CC = "233"  # Ghana (change if needed)

def _digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def _normalize_msisdn(raw: str, default_cc: str = _GH_DEFAULT_CC) -> str | None:
    """
    Return E.164-like digits WITHOUT '+' (for wa.me). Examples:
      '0541234567'   -> '233541234567'
      '+233541234567'-> '233541234567'
      '541234567'    -> '233541234567'  (assume local GSM without 0)
    """
    if not raw:
        return None
    d = _digits_only(raw)
    if not d:
        return None
    # Already has country code (length >= 11 and not starting with '0')
    if d.startswith(default_cc):
        return d
    # Local starting with 0: drop 0 and prepend CC
    if d.startswith("0") and len(d) >= 10:
        return default_cc + d[1:]
    # Bare 9-digit local (e.g., 54xxxxxxx): prepend CC
    if len(d) in (9,):
        return default_cc + d
    # If looks like an international number with another CC, accept as-is
    if len(d) >= 11 and not d.startswith("0"):
        return d
    return None

def _format_money(v):
    try:
        return float(v)
    except Exception:
        return 0.0

# 🔍 Render the Products Page
@products_bp.route("/products", methods=["GET"])
def manage_products():
    return render_template("partials/products.html")

# 📥 Load Products via AJAX
@products_bp.route("/products/load", methods=["GET"])
def load_products():
    products = list(products_collection.find().sort("date_added", -1))
    for p in products:
        p["_id"] = str(p["_id"])
        p["date_added"] = p.get("date_added", datetime.utcnow()).strftime("%Y-%m-%d")

        # Format price history timestamps to date strings for chart labels
        formatted_history = []
        for entry in p.get("price_history", []):
            ts = entry.get("timestamp") or datetime.utcnow()
            if not isinstance(ts, datetime):
                # in case it was stored as number/string
                try:
                    ts = datetime.fromisoformat(str(ts))
                except Exception:
                    ts = datetime.utcnow()
            formatted_history.append({
                "s_price": entry.get("s_price"),
                "p_price": entry.get("p_price"),
                "date": ts.strftime("%Y-%m-%d")
            })
        p["price_history"] = formatted_history

    return jsonify(products)

# ➕ Add Product with Price History
@products_bp.route("/products/add", methods=["POST"])
def add_product():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    s_price = data.get("s_price", "")
    p_price = data.get("p_price", "")

    if not name:
        return jsonify({"success": False, "message": "Product name is required."}), 400

    try:
        s_price = float(s_price)
        p_price = float(p_price)
    except Exception:
        return jsonify({"success": False, "message": "Prices must be numeric."}), 400

    now = datetime.utcnow()
    product = {
        "name": name,
        "description": description,
        "s_price": s_price,
        "p_price": p_price,
        "date_added": now,
        "price_history": [{
            "s_price": s_price,
            "p_price": p_price,
            "timestamp": now
        }]
    }

    result = products_collection.insert_one(product)
    product["_id"] = str(result.inserted_id)
    product["date_added"] = now.strftime("%Y-%m-%d")

    return jsonify({"success": True, "product": product})

# ❌ Delete Product
@products_bp.route("/products/delete/<product_id>", methods=["DELETE"])
def delete_product(product_id):
    try:
        oid = ObjectId(product_id)
    except Exception:
        return jsonify({"success": False, "message": "Invalid product id."}), 400
    result = products_collection.delete_one({"_id": oid})
    return jsonify({"success": result.deleted_count == 1})

# ✏️ Update Product and Append to Price History
@products_bp.route("/products/update/<product_id>", methods=["POST"])
def update_product(product_id):
    try:
        oid = ObjectId(product_id)
    except Exception:
        return jsonify({"success": False, "message": "Invalid product id."}), 400

    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    s_price = data.get("s_price", "")
    p_price = data.get("p_price", "")

    try:
        s_price = float(s_price)
        p_price = float(p_price)
    except Exception:
        return jsonify({"success": False, "message": "Prices must be numeric."}), 400

    now = datetime.utcnow()
    update_fields = {
        "name": name,
        "description": description,
        "s_price": s_price,
        "p_price": p_price
    }

    result = products_collection.update_one(
        {"_id": oid},
        {
            "$set": update_fields,
            "$push": {
                "price_history": {
                    "s_price": s_price,
                    "p_price": p_price,
                    "timestamp": now
                }
            }
        }
    )

    return jsonify({"success": result.modified_count == 1})

# -------------------------------------------------
# NEW: Clients list for WhatsApp share modal
# -------------------------------------------------
@products_bp.route("/products/clients", methods=["GET"])
def list_clients_for_share():
    """
    Returns [{_id, name, phones: [raw], wa_numbers:[digits], primary_wa: '2335...'}]
    We try to extract numbers from common fields.
    """
    docs = list(clients_collection.find({}, {
        "name": 1,
        "client_id": 1,
        "phone": 1,
        "phone_number": 1,
        "whatsapp": 1,
        "mobile": 1,
        "phones": 1
    }).sort("name", 1))

    results = []
    for d in docs:
        cid = str(d.get("_id"))
        name = d.get("name") or d.get("client_id") or cid

        raw_list = []
        for key in ("phone", "phone_number", "whatsapp", "mobile"):
            v = d.get(key)
            if isinstance(v, str) and v.strip():
                raw_list.append(v.strip())
        if isinstance(d.get("phones"), list):
            for v in d["phones"]:
                if isinstance(v, str) and v.strip():
                    raw_list.append(v.strip())

        wa_numbers = []
        for raw in raw_list:
            n = _normalize_msisdn(raw)
            if n and n not in wa_numbers:
                wa_numbers.append(n)

        results.append({
            "_id": cid,
            "name": name,
            "phones": raw_list,
            "wa_numbers": wa_numbers,
            "primary_wa": wa_numbers[0] if wa_numbers else None
        })

    # Keep only clients that have at least one WhatsAppable number
    results = [r for r in results if r["primary_wa"]]
    return jsonify(results)

# -------------------------------------------------
# NEW: Default share message for a product
# -------------------------------------------------
@products_bp.route("/products/share/default_message", methods=["GET"])
def default_share_message():
    product_id = request.args.get("product_id")
    if not product_id:
        return jsonify({"success": False, "message": "product_id is required"}), 400
    try:
        p = products_collection.find_one({"_id": ObjectId(product_id)}, {"name":1, "s_price":1})
    except Exception:
        p = None
    if not p:
        return jsonify({"success": False, "message": "Product not found"}), 404

    name = p.get("name") or "Product"
    s_price = _format_money(p.get("s_price"))
    msg = f"This is the price for {name}: {s_price:.2f}"
    return jsonify({"success": True, "message": msg})

# -------------------------------------------------
# NEW: Build WhatsApp share links for selected clients
# -------------------------------------------------
@products_bp.route("/products/share/build", methods=["POST"])
def build_share_links():
    """
    Body: {
      "product_id": "...",
      "message": "optional custom text",
      "client_ids": ["...", "..."]
    }
    Returns: { success: true, links: [ {client_id, name, number, url} ] }
    NOTE: WhatsApp does NOT support multi-recipient preselection.
          Open each link in a new tab/window so the user taps 'Send' per chat.
    """
    data = request.get_json(force=True, silent=True) or {}
    product_id = data.get("product_id")
    custom_msg = (data.get("message") or "").strip()
    client_ids = data.get("client_ids") or []

    if not product_id or not client_ids:
        return jsonify({"success": False, "message": "product_id and client_ids are required"}), 400

    try:
        p = products_collection.find_one({"_id": ObjectId(product_id)}, {"name":1, "s_price":1})
    except Exception:
        p = None
    if not p:
        return jsonify({"success": False, "message": "Product not found"}), 404

    # Default message if not provided
    if not custom_msg:
        name = p.get("name") or "Product"
        s_price = _format_money(p.get("s_price"))
        custom_msg = f"This is the price for {name}: {s_price:.2f}"

    # Fetch selected clients
    oids = []
    for cid in client_ids:
        try:
            oids.append(ObjectId(cid))
        except Exception:
            continue
    if not oids:
        return jsonify({"success": False, "message": "No valid client ids."}), 400

    docs = list(clients_collection.find({"_id": {"$in": oids}}, {
        "name":1, "phone":1, "phone_number":1, "whatsapp":1, "mobile":1, "phones":1
    }))

    links = []
    for d in docs:
        cid = str(d["_id"])
        name = d.get("name") or cid

        # collect phones
        raw_list = []
        for key in ("phone", "phone_number", "whatsapp", "mobile"):
            v = d.get(key)
            if isinstance(v, str) and v.strip():
                raw_list.append(v.strip())
        if isinstance(d.get("phones"), list):
            for v in d["phones"]:
                if isinstance(v, str) and v.strip():
                    raw_list.append(v.strip())

        # choose first whatsapp-able number
        wa_number = None
        for raw in raw_list:
            n = _normalize_msisdn(raw)
            if n:
                wa_number = n
                break

        if not wa_number:
            continue

        # Build wa.me URL
        # (encode on the frontend or do a simple safe replace here)
        text = custom_msg
        # very basic encoding (frontend should still encodeURIComponent)
        text = text.replace("&", "%26").replace("#", "%23").replace("+", "%2B")
        url = f"https://wa.me/{wa_number}?text={text}"

        links.append({
            "client_id": cid,
            "name": name,
            "number": wa_number,
            "url": url
        })

    return jsonify({"success": True, "links": links, "message": custom_msg})


