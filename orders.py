from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from bson import ObjectId, errors
from db import db
from datetime import datetime

orders_bp = Blueprint('orders', __name__, template_folder='templates')

orders_collection = db['orders']
clients_collection = db['clients']
bdc_collection = db['bdc']
products_collection = db['products']  # Products collection

def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def _nz(v):  # treat None as 0.0
    return v if v is not None else 0.0

@orders_bp.route('/', methods=['GET'])
def view_orders():
    if 'role' not in session or session['role'] not in ['admin', 'assistant']:
        flash("Access denied.", "danger")
        return redirect(url_for('login.login'))

    orders = list(orders_collection.find({'status': 'pending'}).sort('date', -1))
    bdcs = list(bdc_collection.find({}, {'name': 1}))  # _id included by default

    for order in orders:
        try:
            client = clients_collection.find_one({'_id': ObjectId(order.get('client_id'))})
        except Exception:
            client = None

        if client:
            order['client_name'] = client.get('name', 'No Name')
            order['client_image_url'] = client.get('image_url', '')
            order['client_id'] = client.get('client_id', '')
            order['client_profile_url'] = None
        else:
            order['client_name'] = 'Unknown'
            order['client_image_url'] = ''
            order['client_profile_url'] = None

        # Server-side initial display (fallbacks)
        p = _f(order.get('p_bdc_omc'))
        s = _f(order.get('s_bdc_omc'))
        p_tax = _f(order.get('p_tax'))
        s_tax = _f(order.get('s_tax'))
        q = _f(order.get('quantity')) or 0.0

        margin_price = (s - p) if (s is not None and p is not None) else None
        margin_tax = (s_tax - p_tax) if (s_tax is not None and p_tax is not None) else None

        order['margin'] = round(margin_price, 2) if margin_price is not None else None

        # returns for initial render
        ret_sbdc = (s * q) if (s is not None) else 0.0
        ret_stax = (s_tax * q) if (s_tax is not None) else 0.0
        ret_total = ret_sbdc + ret_stax

        order['returns_sbdc'] = round(ret_sbdc, 2)
        order['returns_stax'] = round(ret_stax, 2)
        order['returns_total'] = round(ret_total, 2)
        order['returns'] = round(ret_total, 2)  # legacy

    return render_template('partials/orders.html', orders=orders, bdcs=bdcs)

@orders_bp.route('/update/<order_id>', methods=['POST'])
def update_order(order_id):
    if 'role' not in session or session['role'] not in ['admin', 'assistant']:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    form = request.form
    mode = (form.get("order_type") or "combo").strip().lower()  # 's_bdc' | 's_tax' | 'combo'

    fields = {
        "omc": form.get("omc"),
        "bdc": form.get("bdc"),  # may be None when S‑Tax
        "depot": form.get("depot"),
        "p_bdc_omc": form.get("p_bdc_omc"),
        "s_bdc_omc": form.get("s_bdc_omc"),
        "p_tax": form.get("p_tax"),
        "s_tax": form.get("s_tax"),
        "due_date": form.get("due_date"),
        "payment_type": (form.get("payment_type") or "").strip(),
        "payment_amount": form.get("payment_amount"),
        "shareholder": (form.get("shareholder") or "").strip()
    }

    # Basic requireds: OMC & DEPOT always; BDC required unless S‑Tax
    if not all([fields["omc"], fields["depot"]]):
        return jsonify({"success": False, "error": "OMC and DEPOT are required."}), 400
    if mode != "s_tax" and not fields["bdc"]:
        return jsonify({"success": False, "error": "BDC is required for this order type."}), 400

    # Fetch order + client
    try:
        order = orders_collection.find_one({"_id": ObjectId(order_id)})
    except Exception:
        order = None
    if not order:
        return jsonify({"success": False, "error": "Order not found"}), 404

    client_name = ""
    try:
        client = clients_collection.find_one({"_id": ObjectId(order.get("client_id"))})
        client_name = client.get("name", "") if client else ""
    except Exception:
        pass

    # Parse numeric inputs
    p = _f(fields["p_bdc_omc"])   # P-BDC
    s = _f(fields["s_bdc_omc"])   # S-BDC
    p_tax = _f(fields["p_tax"])   # P-Tax
    s_tax = _f(fields["s_tax"])   # S-Tax

    # Quantity from the order
    q = _f(order.get("quantity")) or 0.0

    # Validate based on order type
    if mode not in ("s_bdc", "s_tax", "combo"):
        return jsonify({"success": False, "error": "Invalid order type."}), 400

    if mode == "s_bdc":
        if s is None:
            return jsonify({"success": False, "error": "S-BDC is required for S-BDC type."}), 400
    elif mode == "s_tax":
        if s_tax is None:
            return jsonify({"success": False, "error": "S-Tax is required for S-Tax type."}), 400
    else:  # combo
        if s is None or s_tax is None:
            return jsonify({"success": False, "error": "S-BDC and S-Tax are required for Combo type."}), 400

    # Compute margins per L
    margin_price = (s - p) if (s is not None and p is not None) else None
    margin_tax = (s_tax - p_tax) if (s_tax is not None and p_tax is not None) else None

    # Compute total debt by order type
    if mode == "s_bdc":
        total_debt = _nz(s) * q
        active_margin = margin_price
    elif mode == "s_tax":
        total_debt = _nz(s_tax) * q
        active_margin = margin_tax
    else:  # combo
        total_debt = (_nz(s) + _nz(s_tax)) * q
        active_margin = margin_price  # display

    # Returns (always)
    returns_sbdc = (_nz(s) * q) if (s is not None) else 0.0
    returns_stax = (_nz(s_tax) * q) if (s_tax is not None) else 0.0
    returns_total = returns_sbdc + returns_stax

    # Build update doc
    update_data = {
        "omc": fields["omc"],
        "depot": fields["depot"],
        "shareholder": fields["shareholder"] or None,
        "p_bdc_omc": p,
        "s_bdc_omc": s,
        "p_tax": p_tax,
        "s_tax": s_tax,
        "order_type": mode,
        "total_debt": round(total_debt, 2),
        "returns_sbdc": round(returns_sbdc, 2),
        "returns_stax": round(returns_stax, 2),
        "returns_total": round(returns_total, 2),
        "returns": round(returns_total, 2),  # legacy
    }
    if margin_price is not None:
        update_data["margin_price"] = round(margin_price, 2)
    if margin_tax is not None:
        update_data["margin_tax"] = round(margin_tax, 2)
    if active_margin is not None:
        update_data["margin"] = round(active_margin, 2)

    # Due date
    if fields["due_date"]:
        try:
            update_data["due_date"] = datetime.strptime(fields["due_date"], "%Y-%m-%d")
        except ValueError:
            return jsonify({"success": False, "error": "Invalid date format"}), 400
    else:
        update_data["due_date"] = None

    # BDC lookup & set only when not S‑Tax
    bdc_id = None
    if mode != "s_tax":
        try:
            bdc_id = ObjectId(fields["bdc"])
        except (ValueError, errors.InvalidId):
            return jsonify({"success": False, "error": "Invalid BDC ID"}), 400

        bdc = bdc_collection.find_one({"_id": bdc_id})
        if not bdc:
            return jsonify({"success": False, "error": "BDC not found"}), 404

        update_data["bdc_id"] = bdc_id
        update_data["bdc_name"] = bdc.get("name", "")

    # ---------------------------
    # Payment handling
    # ---------------------------
    payment_type_norm = (fields["payment_type"] or "").strip().lower()

    # If order_type is S-Tax, ignore any posted payment fields (UI disables them)
    if mode != "s_tax" and payment_type_norm in ("cash", "from account", "credit"):
        calc_amount = None

        if payment_type_norm in ("cash", "from account", "credit"):
            # UI now auto-fills qty × P-BDC for all three; validate P-BDC exists
            if p is None:
                return jsonify({"success": False, "error": "P-BDC is required to compute payment amount"}), 400
            calc_amount = round(q * p, 2)

        if calc_amount is not None:
            payment_entry = {
                "order_id": ObjectId(order_id),
                "payment_type": fields["payment_type"],   # original case
                "amount": calc_amount,
                "client_name": client_name or "—",
                "product": order.get("product", ""),
                "vehicle_number": order.get("vehicle_number", ""),
                "driver_name": order.get("driver_name", ""),
                "driver_phone": order.get("driver_phone", ""),
                "quantity": order.get("quantity", ""),
                "region": order.get("region", ""),
                "delivery_status": "pending",
                "shareholder": fields["shareholder"] or None,
                "date": datetime.utcnow()
            }

            # Push to ORDER
            orders_collection.update_one(
                {"_id": ObjectId(order_id)},
                {"$push": {"payment_details": payment_entry}}
            )

            # Also push to BDC only if we have one (i.e., not S‑Tax)
            if bdc_id:
                bdc_collection.update_one(
                    {"_id": bdc_id},
                    {"$push": {"payment_details": payment_entry}}
                )

    # Status – approve if totals + margin exist as appropriate (independent of balance)
    complete_fields = (update_data.get("total_debt") is not None) and (
        (mode == "s_tax" and ("margin" in update_data or "returns_total" in update_data)) or
        (mode in ("s_bdc", "combo") and ("margin" in update_data or "returns_total" in update_data))
    )
    update_data["status"] = "approved" if complete_fields else "pending"
    update_data["delivery_status"] = "pending"

    orders_collection.update_one({"_id": ObjectId(order_id)}, {"$set": update_data})

    return jsonify({
        "success": True,
        "message": "Order updated" + (" and approved" if complete_fields else " (still pending)")
    })

@orders_bp.route('/get_product_price', methods=['GET'])
def get_product_price():
    product_name = (request.args.get('name', '') or '').strip().lower()
    product = products_collection.find_one({'name': {'$regex': f'^{product_name}$', '$options': 'i'}})
    if not product:
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    return jsonify({
        'success': True,
        'p_price': product.get('p_price', 0),
        's_price': product.get('s_price', 0)
    })
