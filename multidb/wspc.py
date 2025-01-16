
import threading
from hashlib import md5
from django.core.cache import caches
from django.conf import settings
from .pinning import pin_this_thread, unpin_this_thread, UsePrimaryDB
from .pinning import this_thread_is_pinned
from .middleware import PinningRouterMiddleware


_locals = threading.local()


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


class CCPinningRouterMiddleware(PinningRouterMiddleware):

    def _client_fingerprint(self, request):
        """Return hash generated from client IP and browser headers."""
        HASH_COMPONENTS = ('HTTP_X_FORWARDED_FOR', 'REMOTE_ADDR',
                           'HTTP_ACCEPT_ENCODING', 'HTTP_ACCEPT_LANGUAGE',
                           'HTTP_USER_AGENT')
        idstring = '\n'.join([request.META.get(component, '')
                              for component in HASH_COMPONENTS])
        return md5(idstring.encode('utf-8')).hexdigest()

    def _pinned_because_of_prior_request(self, request):
        """Return True if a previous request has pinned us."""

        # If pinning cookie set, the answer's yes
        if settings.MULTIDB_PINNING_COOKIE in request.COOKIES:
            return True

        # We don't have pinning cookie; if we aren't configured to use the
        # client fingerprint, end of story, it's a no.
        if not settings.MULTIDB_COOKIELESS_CACHE:
            return False

        # We are configured to use the client fingerprint. This means we also
        # use an additional cookie to signify the existence of cookies. If it's
        # set, we're not cookieless, so the absence of the pinning cookie means
        # it's a no.
        if settings.MULTIDB_COOKIELESS_COOKIE in request.COOKIES:
            return False

        # We're possibly cookieless, and we are configured to use client
        # fingerprints. Check it.
        if settings.MULTIDB_COOKIELESS_CACHE:
            cache_name = settings.MULTIDB_COOKIELESS_CACHE
        else:
            cache_name = 'default'
        cache = caches[cache_name]
        return bool(cache.get(self._client_fingerprint(request)))

    def _pin_next_requests(self, request, response):
        # Set the cookie anyway
        response.set_cookie(settings.MULTIDB_PINNING_COOKIE, value='y',
                            max_age=settings.MULTIDB_PINNING_SECONDS)

        # If there's suspicion we are cookieless, try to set cache as well
        if settings.MULTIDB_COOKIELESS_CACHE:
            cache_name = settings.MULTIDB_COOKIELESS_CACHE
        else:
            cache_name = 'default'
        if settings.MULTIDB_COOKIELESS_COOKIE not in request.COOKIES:
            cache = caches[cache_name]
            cache.set(self._client_fingerprint(request), 'y',
                      settings.MULTIDB_PINNING_SECONDS)

    def process_request(self, request):
        """Set the thread's pinning flag according to the presence of the
        incoming cookie and/or client fingerprint in the cache."""
        unset_db_write_for_this_thread()
        set_db_write_for_this_thread_if_needed(request)
        if self._pinned_because_of_prior_request(request) \
                or this_thread_has_db_write_set():
            pin_this_thread()
        else:
            # In case the last request this thread served was pinned:
            unpin_this_thread()

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Pin the thread if the current view is in MULTIDB_PINNING_VIEWS."""
        set_db_write_for_this_thread_if_needed(request, view_func)
        if this_thread_has_db_write_set():
            pin_this_thread()

    def process_response(self, request, response):
        # If there is reason to think there was a DB write, pin the next
        # requests
        if this_thread_has_db_write_set() or getattr(response, '_db_write',
                                                     False):
            self._pin_next_requests(request, response)

        # If we are configured to use client fingerprints, signify that this
        # user is not cookieless
        if settings.MULTIDB_COOKIELESS_CACHE:
            response.set_cookie(settings.MULTIDB_COOKIELESS_COOKIE, value='y')

        return response


class UseSlave(UsePrimaryDB):
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

