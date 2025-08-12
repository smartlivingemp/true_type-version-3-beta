from flask import Blueprint, render_template, request, jsonify
from bson import ObjectId
from db import db
from datetime import datetime

manage_deliveries_bp = Blueprint("manage_deliveries", __name__, template_folder="templates")

orders_collection = db["orders"]
clients_collection = db["clients"]
bdc_collection = db["bdc"]

@manage_deliveries_bp.route("/deliveries", methods=["GET"])
def view_deliveries():
    filters = {"status": "approved"}

    # Optional filters
    delivery_status = request.args.get("status")
    if delivery_status:
        filters["delivery_status"] = delivery_status

    region = request.args.get("region")
    if region:
        filters["region"] = region

    bdc_name = request.args.get("bdc")
    if bdc_name:
        filters["bdc_name"] = bdc_name

    # Optimize by fetching only necessary fields
    projection = {
        "_id": 1, "client_id": 1, "bdc_name": 1, "product": 1,
        "vehicle_number": 1, "driver_name": 1, "driver_phone": 1,
        "quantity": 1, "region": 1, "delivery_status": 1,
        "date": 1, "delivered_date": 1
    }

    orders_cursor = orders_collection.find(filters, projection).sort("date", -1)
    orders = list(orders_cursor)

    # Batch-fetch clients
    client_ids = list({ObjectId(o["client_id"]) for o in orders if "client_id" in o})
    client_map = {
        str(c["_id"]): c.get("name", "Unknown")
        for c in clients_collection.find({"_id": {"$in": client_ids}}, {"name": 1})
    }

    deliveries = []
    pending_count = 0
    delivered_count = 0

    for order in orders:
        status = order.get("delivery_status", "pending").lower()
        client_id_str = str(order.get("client_id", ""))
        client_name = client_map.get(client_id_str, "Unknown")

        if status == "delivered":
            delivered_count += 1
        else:
            pending_count += 1

        deliveries.append({
            "order_id": str(order["_id"]),
            "bdc_name": order.get("bdc_name", "Unknown BDC"),
            "client_name": client_name,
            "product": order.get("product", ""),
            "vehicle_number": order.get("vehicle_number", ""),
            "driver_name": order.get("driver_name", ""),
            "driver_phone": order.get("driver_phone", ""),
            "quantity": order.get("quantity", ""),
            "region": order.get("region", ""),
            "delivery_status": status,
            "date": order.get("date"),
            "delivered_date": order.get("delivered_date")
        })

    regions = sorted(set(d["region"] for d in deliveries if d["region"]))
    bdcs = sorted(set(d["bdc_name"] for d in deliveries if d["bdc_name"]))

    return render_template("partials/manage_deliveries.html",
                           deliveries=deliveries,
                           regions=regions,
                           bdcs=bdcs,
                           summary={
                               "pending": pending_count,
                               "delivered": delivered_count
                           })


@manage_deliveries_bp.route("/deliveries/update_status/<order_id>", methods=["POST"])
def update_delivery_status(order_id):
    new_status = request.form.get("status", "").strip()
    if not new_status:
        return jsonify({"success": False, "message": "Status cannot be empty."}), 400

    order = orders_collection.find_one({"_id": ObjectId(order_id)})
    if not order:
        return jsonify({"success": False, "message": "Order not found."}), 404

    update_data = {"delivery_status": new_status}
    if new_status.lower() == "delivered":
        update_data["delivered_date"] = datetime.utcnow()

    history_entry = {
        "status": new_status,
        "timestamp": datetime.utcnow()
    }

    # Update in orders collection
    orders_result = orders_collection.update_one(
        {"_id": ObjectId(order_id)},
        {
            "$set": update_data,
            "$push": {"delivery_history": history_entry}
        }
    )

    # Also update in bdc.payment_details where order_id matches
    bdc_result = bdc_collection.update_one(
        {"payment_details.order_id": ObjectId(order_id)},
        {"$set": {"payment_details.$.delivery_status": new_status}}
    )

    if orders_result.modified_count == 1 or bdc_result.modified_count == 1:
        return jsonify({"success": True, "message": "Delivery status updated in order and BDC."})
    else:
        return jsonify({"success": False, "message": "No update made."})


@manage_deliveries_bp.route("/deliveries/history/<order_id>", methods=["GET"])
def get_delivery_history(order_id):
    try:
        order = orders_collection.find_one({"_id": ObjectId(order_id)}, {"delivery_history": 1})
        history = order.get("delivery_history", []) if order else []
        sorted_history = sorted(history, key=lambda x: x.get("timestamp", datetime.min), reverse=True)

        return jsonify({
            "success": True,
            "history": [
                {
                    "status": h["status"],
                    "timestamp": h["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
                }
                for h in sorted_history
            ]
        })
    except Exception:
        return jsonify({"success": False, "message": "Error fetching history."}), 500
