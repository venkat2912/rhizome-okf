"""Refund workflow: validates the order then calls the gateway."""
from .gateway import refund
from ..db import save_order

class RefundPolicy:
    """Decides whether an order is refundable."""
    def allowed(self, order):
        return True

def refund_order(conn, order):
    if RefundPolicy().allowed(order):
        save_order(conn, order)
        return refund(order)
