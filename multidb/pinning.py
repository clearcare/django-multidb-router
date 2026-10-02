"""An encapsulated thread-local variable that indicates whether future DB
writes should be "stuck" to the master."""

from functools import wraps
import threading
import warnings


__all__ = ['this_thread_is_pinned', 'pin_this_thread', 'unpin_this_thread',
           'reset_pin_state', 'use_primary_db', 'use_master', 'db_write']


_locals = threading.local()


def this_thread_is_pinned():
    """Return whether the current thread should send all its reads to the
    master DB."""
    return getattr(_locals, 'pinned', False)


def pin_this_thread():
    """Mark this thread as "stuck" to the master for all DB access."""
    _locals.pinned = True


def unpin_this_thread():
    """Unmark this thread as "stuck" to the master for all DB access.

    If the thread wasn't marked, do nothing.

    """
    _locals.pinned = False


def _pin_stack():
    """Return this thread's stack of saved pin states, creating it on demand.

    Each ``UsePrimaryDB.__enter__`` pushes the pin state it is about to
    override; the matching ``__exit__`` pops and restores it. A per-thread
    stack (rather than a single shared scalar) is what makes nested
    ``use_primary_db``/``use_master`` blocks restore correctly.
    """
    stack = getattr(_locals, 'pin_stack', None)
    if stack is None:
        stack = _locals.pin_stack = []
    return stack


def reset_pin_state():
    """Fully clear this thread's pin state: unpin and discard any saved stack.

    Intended to be called at the start of a request so pin state cannot leak
    between requests when threads/greenlets are reused (gunicorn gevent
    workers). Also recovers from a half-open nesting stack left by code that
    entered ``use_primary_db`` without a matching exit.
    """
    unpin_this_thread()
    del _pin_stack()[:]


class UsePrimaryDB(object):
    """A contextmanager/decorator to use the master database."""
    def __call__(self, func):
        @wraps(func)
        def decorator(*args, **kw):
            with self:
                return func(*args, **kw)
        return decorator

    def __enter__(self):
        _pin_stack().append(this_thread_is_pinned())
        pin_this_thread()

    def __exit__(self, type, value, tb):
        stack = _pin_stack()
        try:
            was_pinned = stack.pop()
        except IndexError:
            # No matching __enter__ frame (e.g. stack was reset mid-block).
            # Fall back to unpinning rather than leaving the thread pinned.
            was_pinned = False
        if was_pinned:
            pin_this_thread()
        else:
            unpin_this_thread()


class DeprecatedUseMaster(UsePrimaryDB):
    def __enter__(self):
        warnings.warn(
            '[multidb] @use_master has been deprecated, please switch to '
            '@use_primary_db',
            DeprecationWarning,
        )
        return super(DeprecatedUseMaster, self).__enter__()


use_primary_db = UsePrimaryDB()
use_master = DeprecatedUseMaster()


def mark_as_write(response):
    """Mark a response as having done a DB write."""
    response._db_write = True
    return response


def db_write(fn):
    @wraps(fn)
    def _wrapped(*args, **kw):
        with use_primary_db:
            response = fn(*args, **kw)
        return mark_as_write(response)
    return _wrapped
