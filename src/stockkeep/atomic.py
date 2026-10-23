"""Small transaction helpers shared by services."""

from __future__ import annotations

import functools


def savepoint(func):
    """Run a service function inside a SAVEPOINT.

    A failure rolls back only this operation's writes, even when the caller
    catches the exception and later commits the surrounding session.  This is
    what makes sales, refunds and bulk imports all-or-nothing.
    """

    @functools.wraps(func)
    def wrapper(session, *args, **kwargs):
        with session.begin_nested():
            return func(session, *args, **kwargs)

    return wrapper
