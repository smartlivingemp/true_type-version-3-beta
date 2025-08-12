from flask import Blueprint, render_template, request, jsonify
from datetime import datetime
from db import db
import calendar

tax_bp = Blueprint("tax", __name__)
tax_col = db["tax_records"]

@tax_bp.route("/tax", methods=["GET"])
def tax_dashboard():
    taxes = list(tax_col.find().sort("payment_date", -1))

    # 🔢 Total tax paid
    total_tax = sum(float(tax.get("amount", 0)) for tax in taxes)

    # 📈 Monthly trend
    trend_data = {month: 0 for month in calendar.month_name if month}  # Jan - Dec

    for tax in taxes:
        dt = tax.get("payment_date")
        if isinstance(dt, str):
            try:
                dt = datetime.strptime(dt, "%Y-%m-%d")
            except:
                continue
        elif not isinstance(dt, datetime):
            continue

        month = calendar.month_name[dt.month]
        trend_data[month] += float(tax.get("amount", 0))

    return render_template("partials/tax_dashboard.html", taxes=taxes, trend_data=trend_data, total_tax=total_tax)

@tax_bp.route("/tax/add", methods=["POST"])
def add_tax():
    try:
        tax_type = request.form.get("type")
        amount = float(request.form.get("amount"))
        payment_date = request.form.get("payment_date")
        reference = request.form.get("reference")
        paid_by = request.form.get("paid_by")

        new_tax = {
            "type": tax_type,
            "amount": amount,
            "payment_date": datetime.strptime(payment_date, "%Y-%m-%d"),
            "reference": reference,
            "paid_by": paid_by,
            "submitted_at": datetime.utcnow()
        }

        tax_col.insert_one(new_tax)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
