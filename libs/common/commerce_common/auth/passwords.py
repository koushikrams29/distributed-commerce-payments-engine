import bcrypt

# bcrypt only reads the first 72 bytes; bcrypt>=5 raises instead of truncating.
MAX_PASSWORD_BYTES = 72


def hash_password(plain: str) -> str:
    """One-way hash suitable for storing in the users table.

    bcrypt deliberately slows itself down so guessing passwords from a stolen
    database dump is expensive. We never store the plain password.
    """
    encoded = plain.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True only when `plain` matches the stored hash."""
    encoded = plain.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        # hash_password never stores one this long, so it cannot match.
        return False
    return bcrypt.checkpw(encoded, hashed.encode("utf-8"))
