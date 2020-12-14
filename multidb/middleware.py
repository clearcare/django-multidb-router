
from hashlib import md5

from django.core.cache import get_cache

from multidb.conf import settings
from .pinning import (pin_this_thread, unpin_this_thread,
                      set_db_write_for_this_thread_if_needed,
                      this_thread_has_db_write_set,
                      unset_db_write_for_this_thread)

import threading


READ_ONLY_METHODS = frozenset(['GET', 'TRACE', 'HEAD', 'OPTIONS'])


class PinningRouterMiddleware(object):

    def _client_fingerprint(self, request):
        """Return hash generated from client IP and browser headers."""
        HASH_COMPONENTS = ('HTTP_X_FORWARDED_FOR', 'REMOTE_ADDR',
                           'HTTP_ACCEPT_ENCODING', 'HTTP_ACCEPT_LANGUAGE',
                           'HTTP_USER_AGENT')
        idstring = '\n'.join([request.META.get(component, '')
                              for component in HASH_COMPONENTS])
        return md5(idstring).hexdigest()

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
        cache = get_cache(settings.MULTIDB_COOKIELESS_CACHE)
        return bool(cache.get(self._client_fingerprint(request)))

    def process_request(self, request):
        """Set the thread's pinning flag according to the presence of the
        incoming cookie and/or client fingerprint in the cache."""
        try:
            host = request.get_host()
            subdomain = host.split('.')[0]
            request.subdomain = subdomain
            #print("subdomain :" + subdomain)
            
            def set_subdomain(sub_domain):
                try:
                    from core import Chipmunk
                    # current_thread = threading.current_thread()
                    # current_thread.__dict__['subdomain'] = sub_domain
                    Chipmunk.sub_domain = sub_domain
                except Exception as e:
                    print("error in router set domain : {}".format(str(e)))
                    raise

            set_subdomain(subdomain)
        except:
            print("no subdomain set")
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

    def _pin_next_requests(self, request, response):
        # Set the cookie anyway
        response.set_cookie(settings.MULTIDB_PINNING_COOKIE, value='y',
                            max_age=settings.MULTIDB_PINNING_SECONDS)

        # If there's suspicion we are cookieless, try to set cache as well
        if settings.MULTIDB_COOKIELESS_CACHE \
                and settings.MULTIDB_COOKIELESS_COOKIE not in request.COOKIES:
            cache = get_cache(settings.MULTIDB_COOKIELESS_CACHE)
            cache.set(self._client_fingerprint(request), 'y',
                      settings.MULTIDB_PINNING_SECONDS)

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





