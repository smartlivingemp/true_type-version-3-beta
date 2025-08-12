from flask import Blueprint, render_template
from bson import ObjectId
from datetime import datetime
from db import clients_collection, orders_collection, payments_collection

client_profile_bp = Blueprint("client_profile", __name__, template_folder="templates")

@client_profile_bp.route('/client/<client_id>')
def client_profile(client_id):
    try:
        # ✅ Validate ObjectId
        if not ObjectId.is_valid(client_id):
            return "Invalid client ID", 400

        # ✅ Fetch client document
        client = clients_collection.find_one({"_id": ObjectId(client_id)})
        if not client:
            return "Client not found", 404

        # ✅ Get all orders for this client
        all_orders = list(
            orders_collection.find({"client_id": str(client["_id"])}).sort("date", -1)
        )

        # ✅ Prepare each order with extra fields
        for order in all_orders:
            # Convert timestamps
            if "date" in order and not isinstance(order["date"], datetime):
                try:
                    order["date"] = datetime.fromtimestamp(order["date"] / 1000)
                except:
                    order["date"] = None
            if "due_date" in order and not isinstance(order["due_date"], datetime):
                try:
                    order["due_date"] = datetime.fromtimestamp(order["due_date"] / 1000)
                except:
                    order["due_date"] = None

            # Compute margin and returns
            try:
                p = float(order.get("p_bdc_omc", 0))
                s = float(order.get("s_bdc_omc", 0))
                q = float(order.get("quantity", 0))
                margin = s - p
                order["margin"] = round(margin, 2)
                order["returns"] = round(margin * q, 2)
            except:
                order["margin"] = 0.0
                order["returns"] = 0.0

            # Add default tax and debt fields
            try:
                order["tax"] = float(order.get("tax", 0))
            except:
                order["tax"] = 0.0
            try:
                order["total_debt"] = float(order.get("total_debt", 0))
            except:
                order["total_debt"] = 0.0

            # Aggregate confirmed payments for this order
            order_id = str(order["_id"])
            confirmed_payments = payments_collection.aggregate([
                {
                    "$match": {
                        "client_id": ObjectId(client_id),
                        "order_id": order["_id"],
                        "status": "confirmed"
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_paid": {"$sum": "$amount"}
                    }
                }
            ])
            payment_result = list(confirmed_payments)
            order["amount_paid"] = round(payment_result[0]["total_paid"], 2) if payment_result else 0.0
            order["amount_left"] = round(order["total_debt"] - order["amount_paid"], 2)

        # ✅ Latest approved order summary
        approved_orders = [o for o in all_orders if o.get("status") == "approved"]
        latest_approved = approved_orders[0] if approved_orders else None

        total_paid = 0
        amount_left = 0

        if latest_approved:
            order_id = latest_approved["_id"]
            confirmed_payments = list(payments_collection.find({
                "client_id": ObjectId(client_id),
                "order_id": order_id,
                "status": "confirmed"
            }))
            total_paid = sum(p.get("amount", 0) for p in confirmed_payments)
            total_debt = float(latest_approved.get("total_debt", 0))
            amount_left = max(total_debt - total_paid, 0)

        return render_template(
            "partials/client_profile.html",
            client=client,
            orders=all_orders,
            latest_approved=latest_approved,
            total_paid=round(total_paid, 2),
            amount_left=round(amount_left, 2)
        )

    except Exception as e:
        return f"An error occurred: {str(e)}", 500
