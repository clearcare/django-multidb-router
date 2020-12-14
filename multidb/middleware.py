from __future__ import unicode_literals
from hashlib import md5

from django.core.cache import get_cache

from multidb.conf import settings
from .pinning import (pin_this_thread, unpin_this_thread,
                      set_db_write_for_this_thread_if_needed,
                      this_thread_has_db_write_set,
                      unset_db_write_for_this_thread)

import threading

from contextlib import contextmanager
from threading import local


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
                    import Chipmunk
                    # current_thread = threading.current_thread()
                    # current_thread.__dict__['subdomain'] = sub_domain
                    chipmunk.sub_domain = sub_domain
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



_thread_locals = local()


class _Chipmunk(object):
    """
    This is a global storage utility class with a very silly name. It uses a thread local object for storage in order
    to isolate data. It avoids the issue of global namespace conflicts by not allowing you to assign a value to an
    attribute that already exists. Also implements the `in` operator to test for inclusion and the bool() method to
    test whether the Chipmunk is holding anything.
    """
    __locals = _thread_locals

    def __repr__(self):
        return "Chipmunk"

    def __str__(self):
        return str("Global Chipmunk Object")

    def __unicode__(self):
        return "Global Chipmunk Object"

    def __contains__(self, item):
        """
        Test whether a value with the given name has been stored already.
        """
        return hasattr(self.__class__.__locals, item)

    def __nonzero__(self):
        return bool(self.__class__.__locals.__dict__)

    def __getattribute__(self, name):
        """
        Provide access to the stored attributes with the simple attribute access method (Chipmunk.attr)
        """
        accessible_attributes = {
            'store_data', 'get_data', 'delete_data', 'hold_this',
            'empty', '_Chipmunk__locals', '__class__'
        }
        if name in accessible_attributes:
            return object.__getattribute__(self, name)
        return self.get_data(name)

    def __setattr__(self, name, value):
        """
        Store all assigned attributes in the thread local object.
        """
        if not name == '__new__':
            return self.store_data(name, value)

    def __delattr__(self, name):
        """
        Remove deleted attributes from the thread local object.
        """
        return self.delete_data(name)

    @classmethod
    def store_data(cls, name, data):
        """
        Store the attribute in the thread local object if none witht he same name exist.
        """
        if hasattr(cls.__locals, name):
            raise AttributeError("Chipmunk can't store attribute \"%s\", it's already holding one." % name)

        setattr(cls.__locals, name, data)

    @classmethod
    def get_data(cls, name, default=None):
        """
        Retrieve the desired attribute from the thread local object or the given default value
        """
        data = getattr(cls.__locals, name, default)
        return data

    @classmethod
    def delete_data(cls, name):
        """
        Deletes the attribute with the given name from the thread local object
        """
        try:
            return delattr(cls.__locals, name)
        except AttributeError:
            return None

    @classmethod
    def empty(cls):
        cls.__locals.__dict__.clear()

    @contextmanager
    def hold_this(self, name, data):
        """
        Tell the Chipmunk to hold some data. If it is already holding something with the same name it will pop that
        object off on entry, store the new data, and then replace the data when the context manager is done.
        """
        if name in self:
            old_value = self.get_data(name)
            self.delete_data(name)

        self.store_data(name, data)
        try:
            yield
        finally:
            self.delete_data(name)
            try:
                self.store_data(name, old_value)
            except NameError:
                pass


Chipmunk = _Chipmunk()
