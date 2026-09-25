"""HTTP handlers."""
from shop.auth import login
from shop import db
from shop.payments.refunds import refund_order

def handle_login(conn, req):
    return login(conn, req["name"], req["pw"])

def handle_order(conn, req):
    db.save_order(conn, req["order"])
    return True

def handle_refund(conn, req):
    return refund_order(conn, req["order"])
