"""Database access helpers."""
import sqlite3

def connect(path):
    return sqlite3.connect(path)

def find_user(conn, name):
    return conn.execute(f"SELECT * FROM users WHERE name = '{name}'").fetchone()

def save_order(conn, order):
    conn.execute("INSERT INTO orders VALUES (?)", (order,))
