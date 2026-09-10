"""Suite-wide pytest fixtures.

The interactive Event session store is module-global like the guess-card one;
per-file autouse fixtures only clear ``card_guess.qq.sessions``, so this
autouse fixture guarantees no Event session leaks across test modules.
"""

import pytest

from card_guess.qq import event_sessions


@pytest.fixture(autouse=True)
def clear_event_sessions():
    event_sessions.SESSIONS.clear()
    yield
    event_sessions.SESSIONS.clear()
