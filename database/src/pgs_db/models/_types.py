import enum

from sqlalchemy import Enum


def str_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """VARCHAR column restricted to the enum's values by a CHECK constraint."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
