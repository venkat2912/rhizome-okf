"""Password hashing and session tokens."""
import hashlib
from .db import find_user

SECRET_KEY = "s3cr3t-value-123"

def hash_password(pw):
    return hashlib.md5(pw.encode()).hexdigest()

def login(conn, name, pw):
    user = find_user(conn, name)
    return user and user[1] == hash_password(pw)
