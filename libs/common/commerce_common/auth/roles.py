from enum import Enum


class Role(str, Enum):
    """Application roles carried in the JWT `role` claim."""

    SHOPPER = "shopper"
    ADMIN = "admin"
