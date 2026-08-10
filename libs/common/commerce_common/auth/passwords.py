import bcrypt


def hash_password(plain: str) -> str:
    """One-way hash suitable for storing in the users table.

    bcrypt deliberately slows itself down so guessing passwords from a stolen
    database dump is expensive. We never store the plain password.
    """
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True only when `plain` matches the stored hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
