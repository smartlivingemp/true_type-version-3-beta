from flask import Blueprint, render_template, session, redirect, url_for, flash
from bson import ObjectId
from db import db
from datetime import datetime

client_dashboard_bp = Blueprint('client_dashboard', __name__, template_folder='templates')

clients_collection = db.clients
orders_collection = db.orders

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0

@client_dashboard_bp.route('/dashboard')
def dashboard():
    if 'client_id' not in session or 'client_name' not in session:
        flash("Please log in first", "warning")
        return redirect(url_for('login.login'))

    client_id = session['client_id']

    if not ObjectId.is_valid(client_id):
        flash("Invalid session. Please log in again.", "danger")
        return redirect(url_for('login.login'))

    oid = ObjectId(client_id)

    client = clients_collection.find_one({"_id": oid})
    if not client:
        flash("Client not found. Please contact support.", "danger")
        return redirect(url_for('login.login'))

    # ✅ Fetch all orders for this client (support both ObjectId and string storage)
    orders = list(
        orders_collection.find({"client_id": {"$in": [oid, client_id]}})
        .sort("date", -1)
    )

    total_orders = len(orders)
    total_debt = sum(_f(o.get("total_debt")) for o in orders)

    # Sum payments recorded on each order (payment_details array)
    total_paid = 0.0
    for o in orders:
        pds = o.get("payment_details", []) or []
        total_paid += sum(_f(p.get("amount")) for p in pds)

    amount_left = round(total_debt - total_paid, 2)

    latest_order = orders[0] if orders else None

    return render_template(
        'client/client_dashboard.html',
        client=client,
        total_orders=total_orders,
        total_debt=round(total_debt, 2),
        total_paid=round(total_paid, 2),
        amount_left=amount_left,
        latest_order=latest_order,
        recent_orders=orders[:5]  # Show 5 most recent
    )
