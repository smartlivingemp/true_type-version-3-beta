from flask import Blueprint, render_template, session, redirect, url_for, flash
from db import db
from bson import ObjectId

approved_orders_bp = Blueprint('approved_orders', __name__, template_folder='templates')

orders_collection = db['orders']
clients_collection = db['clients']
payments_collection = db['payments']
settings_collection = db['settings']  # ✅ Add this

@approved_orders_bp.route('/approved_orders')
def view_approved_orders():
    if 'role' not in session or session['role'] not in ['admin', 'assistant']:
        flash("Access denied.", "danger")
        return redirect(url_for('login.login'))

    # ✅ Check settings for 'approve_orders'
    settings_doc = settings_collection.find_one() or {}
    if not settings_doc.get('approve_orders', False):
        return render_template('partials/home.html', dashboard_disabled=True)

    orders = list(orders_collection.find({'status': 'approved'}).sort('date', -1))

    for order in orders:
        try:
            client = clients_collection.find_one({'_id': ObjectId(order.get('client_id'))})
        except:
            client = None

        if client:
            order['client_name'] = client.get('name', 'Unknown')
            order['client_mongo_id'] = str(client['_id'])
        else:
            order['client_name'] = 'Unknown'
            order['client_mongo_id'] = '#'

        try:
            margin = float(order.get('margin', 0))
            quantity = float(order.get('quantity', 0))
            order['returns'] = round(margin * quantity, 2)
        except (TypeError, ValueError):
            order['returns'] = 0.0

        try:
            order['tax'] = float(order.get('tax', 0))
        except:
            order['tax'] = 0.0

        try:
            order['total_debt'] = float(order.get('total_debt', 0))
        except:
            order['total_debt'] = 0.0

        amount_paid_result = payments_collection.aggregate([
            {
                '$match': {
                    'order_id': str(order['_id']),
                    'status': 'confirmed'
                }
            },
            {
                '$group': {
                    '_id': None,
                    'total_paid': {'$sum': '$amount'}
                }
            }
        ])

        amount_paid_data = list(amount_paid_result)
        order['amount_paid'] = round(amount_paid_data[0]['total_paid'], 2) if amount_paid_data else 0.0
        order['amount_left'] = round(order['total_debt'] - order['amount_paid'], 2)

    return render_template('approved_orders.html', orders=orders)
