from functools import wraps
import threading

from multidb.conf import settings


__all__ = ['this_thread_is_pinned', 'pin_this_thread', 'unpin_this_thread',
           'use_master', 'db_write', 'set_db_write_for_this_thread',
           'use_slave', 'unset_db_write_for_this_thread',
           'this_thread_has_db_write_set',
           'set_db_write_for_this_thread_if_needed']


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


def set_db_write_for_this_thread():
    _locals.db_write = True


def unset_db_write_for_this_thread():
    _locals.db_write = False


def this_thread_has_db_write_set():
    """Return whether the db_write flag is set for the current thread
    (this means we should set the cookie."""
    return getattr(_locals, 'db_write', False)


def set_db_write_for_this_thread_if_needed(request, view_func=False):
    """Check whether this thread should be assumed to be writing to
    the database, and if yes set a flag.  (This function never unsets
    db_write if it's already set.)
    """
    if this_thread_has_db_write_set():
        # We have already set the db_write flag in a previous call
        return
    if request.method == 'POST':
        set_db_write_for_this_thread()
        return
    if not view_func:
        return
    module = view_func.__module__
    try:
        name = view_func.__name__
    except AttributeError:
        # view_func doesn't have __name__; it's probably an object view
        # like django.contrib.syndication.views.Feed().
        name = view_func.__class__.__name__
    view_name = module + '.' + name
    if view_name in settings.MULTIDB_PINNING_VIEWS:
        set_db_write_for_this_thread()
        return


class UseMaster(object):
    """A contextmanager/decorator to use the master database."""
    old = False

    def __call__(self, func):
        @wraps(func)
        def decorator(*args, **kw):
            with self:
                return func(*args, **kw)
        return decorator

    def __enter__(self):
        self.old = this_thread_is_pinned()
        pin_this_thread()

    def __exit__(self, type, value, tb):
        if not self.old:
            unpin_this_thread()

use_master = UseMaster()


class UseSlave(UseMaster):
    """A contextmanager/decorator to use the slave database."""
    "Use this in cases where the usual behavior would be to pin to master,"
    "such as when the request method is POST, but you know you're not doing any writing."
    old = False

    def __enter__(self):
        self.old = this_thread_is_pinned()
        unpin_this_thread()

    def __exit__(self, type, value, tb):
        if self.old:
            pin_this_thread()

use_slave = UseSlave()


def mark_as_write(response):
    """Mark a response as having done a DB write."""
    response._db_write = True
    return response


def db_write(fn):
    @wraps(fn)
    def _wrapped(*args, **kw):
        with use_master:
            response = fn(*args, **kw)
        return mark_as_write(response)
    return _wrapped
