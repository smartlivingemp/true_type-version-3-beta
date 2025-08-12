from flask import Blueprint, render_template, request, redirect, session, url_for, flash
from db import db
from datetime import datetime
from bson import ObjectId

client_payment_bp = Blueprint("client_payment", __name__, template_folder="templates")

payments_col = db["payments"]
truck_payments_col = db["truck_payments"]
orders_col = db["orders"]
bank_accounts_col = db["bank_accounts"]

def _to_f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0

@client_payment_bp.route("/payment", methods=["GET", "POST"])
def client_payment():
    client_id = session.get("client_id")

    # ✅ Check login
    if not client_id:
        flash("⚠ Session expired. Please log in again.", "warning")
        return redirect(url_for("login.login"))

    # Support both storage styles in orders: ObjectId or string
    oid = ObjectId(client_id) if ObjectId.is_valid(client_id) else None
    client_match = {"$in": ([oid, str(client_id)] if oid else [str(client_id)])}
    client_for_payments = (oid or client_id)

    if request.method == "POST":
        payment_type = (request.form.get("payment_type") or "").strip().lower()  # "order" or "truck"
        amount_s = (request.form.get("amount") or "").strip()
        bank_name = (request.form.get("bank_name") or "").strip()
        account_last4 = (request.form.get("account_last4") or "").strip()
        proof_url = (request.form.get("proof_url") or "").strip()
        sel_order_id_s = (request.form.get("order_id") or "").strip()

        if not all([amount_s, bank_name, account_last4, proof_url]):
            flash("⚠ All fields are required.", "danger")
            return redirect(url_for("client_payment.client_payment"))

        amount = _to_f(amount_s)
        if amount <= 0:
            flash("⚠ Invalid amount format.", "danger")
            return redirect(url_for("client_payment.client_payment"))

        payment_data = {
            "client_id": client_for_payments,  # keep ObjectId when we can
            "amount": amount,
            "bank_name": bank_name,
            "account_last4": account_last4,
            "proof_url": proof_url,
            "status": "pending",
            "date": datetime.utcnow()
        }

        try:
            if payment_type == "truck":
                truck_payments_col.insert_one(payment_data)
                flash("✅ Truck payment submitted successfully!", "success")
            else:
                # Order payment now requires an explicit order selection
                if not sel_order_id_s or not ObjectId.is_valid(sel_order_id_s):
                    flash("⚠ Please select a valid order to pay for.", "danger")
                    return redirect(url_for("client_payment.client_payment"))

                sel_oid = ObjectId(sel_order_id_s)

                # Ensure the selected order belongs to this client
                owned = orders_col.find_one({"_id": sel_oid, "client_id": client_match})
                if not owned:
                    flash("⚠ Selected order not found for your account.", "danger")
                    return redirect(url_for("client_payment.client_payment"))

                # Save with order_id reference
                doc = dict(payment_data)
                doc["order_id"] = sel_oid
                payments_col.insert_one(doc)
                flash("✅ Payment submitted successfully!", "success")

        except Exception as e:
            flash(f"❌ Error saving payment: {str(e)}", "danger")

        return redirect(url_for("client_payment.client_payment"))

    # -------------------------
    # GET: Build “orders with debt”
    # -------------------------
    orders = list(
        orders_col.find({"client_id": client_match}).sort("date", -1)
    )

    # Map: order_id -> confirmed paid total
    def confirmed_paid_for(order_oid):
        cur = payments_col.find({
            "client_id": client_for_payments,
            "order_id": order_oid,
            "status": "confirmed"
        })
        return sum(_to_f(p.get("amount")) for p in cur)

    orders_with_debt = []
    full_outstanding_total = 0.0

    for o in orders:
        total_debt = _to_f(o.get("total_debt"))
        if total_debt <= 0:
            continue

        paid = confirmed_paid_for(o["_id"])
        outstanding = round(max(total_debt - paid, 0.0), 2)
        if outstanding > 0:
            orders_with_debt.append({
                "_id": str(o["_id"]),                                  # for form value
                "code": o.get("order_id") or str(o["_id"]),            # human code to display
                "product": o.get("product", ""),
                "date": o.get("date"),
                "total_debt": round(total_debt, 2),
                "paid": round(paid, 2),
                "outstanding": outstanding
            })
            full_outstanding_total += outstanding

    # Sort by most recent order date
    orders_with_debt.sort(key=lambda x: x["date"] or datetime.min, reverse=True)

    # Build a small map for front-end auto-fill (order -> outstanding)
    order_balance_map = {row["_id"]: row["outstanding"] for row in orders_with_debt}

    # ✅ Fetch and combine both payment types (history)
    order_payments = list(payments_col.find({"client_id": client_for_payments}).sort("date", -1))
    truck_payments = list(truck_payments_col.find({"client_id": client_for_payments}).sort("date", -1))

    combined_payments = []
    for p in order_payments:
        combined_payments.append({
            "type": "Order",
            "date": (p.get("date") or datetime.min).strftime("%Y-%m-%d %H:%M:%S"),
            "amount": _to_f(p.get("amount")),
            "bank_name": p.get("bank_name", "-"),
            "account_last4": p.get("account_last4", ""),
            "proof_url": p.get("proof_url", "#"),
            "status": p.get("status", "pending"),
            "feedback": p.get("feedback", "")
        })
    for p in truck_payments:
        combined_payments.append({
            "type": "Truck",
            "date": (p.get("date") or datetime.min).strftime("%Y-%m-%d %H:%M:%S"),
            "amount": _to_f(p.get("amount")),
            "bank_name": p.get("bank_name", "-"),
            "account_last4": p.get("account_last4", ""),
            "proof_url": p.get("proof_url", "#"),
            "status": p.get("status", "pending"),
            "feedback": p.get("feedback", "")
        })

    # Sort history by date string (safe because YYYY-MM-DD HH:MM:SS)
    combined_payments.sort(key=lambda x: x["date"], reverse=True)

    # ✅ Load available bank accounts
    bank_accounts = list(bank_accounts_col.find({}, {
        "bank_name": 1, "account_name": 1, "account_number": 1, "_id": 0
    }).sort("bank_name"))

    return render_template(
        "client/client_payment.html",
        payments=combined_payments,
        # For the UI dropdown and “Full payment” auto-fill:
        orders_with_debt=orders_with_debt,
        full_outstanding_total=round(full_outstanding_total, 2),
        order_balance_map=order_balance_map,
        bank_accounts=bank_accounts
    )
