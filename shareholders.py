from flask import Blueprint, render_template, request
from datetime import datetime, timedelta
from collections import defaultdict
from db import db

shareholders_bp = Blueprint('shareholders', __name__)
orders_col = db['orders']

SHAREHOLDERS = ["Rex", "Simon", "Paul"]
SHARE_SPLIT = {
    "Rex": 0.35,
    "Simon": 0.35,
    "Paul": 0.30
}


def filter_orders_for_returns(period, start_date, end_date):
    now = datetime.utcnow()
    query = {"status": "approved"}

    if period == "week":
        query["date"] = {"$gte": now - timedelta(days=7)}
    elif period == "month":
        query["date"] = {"$gte": datetime(now.year, now.month, 1)}
    elif period == "custom" and start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query["date"] = {"$gte": start, "$lt": end}
        except ValueError:
            pass
    return list(orders_col.find(query))


def build_contributions(orders):
    total_orders = len(orders)
    total_quantity = sum(order.get("quantity", 0) for order in orders)
    total_returns = sum(round(order.get("margin", 0) * order.get("quantity", 0), 2) for order in orders)

    contributions = {name: {"orders": 0, "quantity": 0, "returns": 0} for name in SHAREHOLDERS}
    for order in orders:
        name = order.get("shareholder")
        qty = order.get("quantity", 0)
        margin = order.get("margin", 0)
        if name in contributions:
            contributions[name]["orders"] += 1
            contributions[name]["quantity"] += qty
            contributions[name]["returns"] += round(margin * qty, 2)

    for name in SHAREHOLDERS:
        returns = contributions[name]["returns"]
        contributions[name]["percentage_of_returns"] = round((returns / total_returns) * 100, 2) if total_returns else 0

    shared_returns = {
        name: round(SHARE_SPLIT[name] * total_returns, 2)
        for name in SHAREHOLDERS
    }

    return total_orders, total_quantity, total_returns, contributions, shared_returns


def build_volume_data(volume_period, volume_start, volume_end):
    now = datetime.utcnow()
    volume_query = {"status": "approved"}

    if volume_period == "week":
        volume_query["date"] = {"$gte": now - timedelta(days=7)}
    elif volume_period == "month":
        volume_query["date"] = {"$gte": datetime(now.year, now.month, 1)}
    elif volume_period == "today":
        volume_query["date"] = {"$gte": datetime(now.year, now.month, now.day)}
    elif volume_period == "custom" and volume_start and volume_end:
        try:
            vs = datetime.strptime(volume_start, "%Y-%m-%d")
            ve = datetime.strptime(volume_end, "%Y-%m-%d") + timedelta(days=1)
            volume_query["date"] = {"$gte": vs, "$lt": ve}
        except ValueError:
            pass

    volume_orders = list(orders_col.find(volume_query))
    volume_data = defaultdict(int)
    for order in volume_orders:
        name = order.get("shareholder")
        qty = order.get("quantity", 0)
        if name in SHAREHOLDERS:
            volume_data[name] += qty

    return volume_data


# ✅ Main Route - Handles Everything
@shareholders_bp.route('/shareholders')
def view_shareholders():
    # 🎯 Main summary filters
    period = request.args.get("period", "all")
    start_date = request.args.get("start")
    end_date = request.args.get("end")

    # 📦 Volume chart filters
    volume_period = request.args.get("volume_period", "all")
    volume_start = request.args.get("volume_start")
    volume_end = request.args.get("volume_end")

    orders = filter_orders_for_returns(period, start_date, end_date)
    total_orders, total_quantity, total_returns, contributions, shared_returns = build_contributions(orders)
    volume_data = build_volume_data(volume_period, volume_start, volume_end)

    return render_template("partials/shareholders.html",
                           total_orders=total_orders,
                           total_quantity=total_quantity,
                           total_returns=total_returns,
                           contributions=contributions,
                           shared_returns=shared_returns,
                           period=period,
                           start_date=start_date,
                           end_date=end_date,
                           volume_data=volume_data,
                           volume_period=volume_period,
                           volume_start=volume_start,
                           volume_end=volume_end)
