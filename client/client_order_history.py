from flask import Blueprint, render_template, session, redirect, url_for
from bson import ObjectId
from datetime import datetime
from db import db

client_order_history_bp = Blueprint('client_order_history', __name__)
orders_col = db["orders"]
clients_col = db["clients"]
payments_col = db["payments"]

@client_order_history_bp.route("/order_history")
def client_order_history():
    client_id = session.get("client_id")

    # ✅ Validate session and ObjectId
    if not client_id or not ObjectId.is_valid(client_id):
        return redirect(url_for("login.client_login"))

    oid = ObjectId(client_id)

    # ✅ Fetch client
    client = clients_col.find_one({"_id": oid})
    if not client:
        return redirect(url_for("login.client_login"))

    # ✅ Fetch orders (match both storage styles: ObjectId or string)
    orders = list(
        orders_col.find({"client_id": {"$in": [oid, client_id]}})
        .sort("date", -1)
    )

    # ✅ Get latest approved order (if any)
    latest_approved = next((o for o in orders if (o.get("status") or "").lower() == "approved"), None)

    total_paid = 0.0
    amount_left = 0.0

    if latest_approved:
        order_id = latest_approved["_id"]
        total_debt = float(latest_approved.get("total_debt", 0) or 0)

        # 1) Primary: payments collection (confirmed only)
        confirmed = list(payments_col.find({
            "client_id": oid,          # client_id saved as ObjectId in payments
            "order_id": order_id,      # order_id saved as ObjectId in payments
            "status": "confirmed"
        }))
        total_paid = sum(float(p.get("amount", 0) or 0) for p in confirmed)

        # 2) Fallback: if no separate payments, try payments recorded on the order
        if total_paid == 0 and isinstance(latest_approved.get("payment_details"), list):
            # Sum amounts from order.payment_details if present
            total_paid = sum(float(pd.get("amount", 0) or 0) for pd in latest_approved["payment_details"])

        amount_left = max(total_debt - total_paid, 0.0)

    return render_template(
        "client/client_order_history.html",
        orders=orders,
        client=client,
        latest_approved=latest_approved,
        total_paid=round(total_paid, 2),
        amount_left=round(amount_left, 2)
    )
