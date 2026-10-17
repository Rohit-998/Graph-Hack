"""Default world (NimbusPay). Kept as a module alias so existing imports and tests work.

Adding a world: create `firebreak/worlds/<name>.py` with the same attributes and
register it in `firebreak/worlds/__init__.py`.
"""

from .worlds.nimbuspay import *  # noqa: F401,F403
