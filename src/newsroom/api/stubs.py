from typing import NoReturn

from newsroom.core.errors import NotImplementedYet


def planned(slice_name: str) -> NoReturn:
    """Contract-first stub: the route and its schemas exist; the behaviour ships in a slice."""
    raise NotImplementedYet(f"Planned for the '{slice_name}' slice")
