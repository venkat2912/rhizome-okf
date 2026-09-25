"""Talks to the external payment provider."""
import requests

def charge(amount):
    return requests.post("https://pay.example.com/charge", json={"amount": amount}, verify=False)

def refund(charge_id):
    return requests.post("https://pay.example.com/refund", json={"id": charge_id})
