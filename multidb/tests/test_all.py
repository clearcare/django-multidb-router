from datetime import datetime
import time

from django.http import HttpRequest, HttpResponse
from django.test import TestCase
from django.test.client import Client
from django.test.utils import override_settings

from multidb import (DEFAULT_DB_ALIAS, MasterSlaveRouter,
                     PinningMasterSlaveRouter, get_slave)
from multidb.conf import settings
from multidb.middleware import PinningRouterMiddleware
from multidb.pinning import (this_thread_is_pinned, pin_this_thread,
                             unpin_this_thread, use_master, db_write)


def expire_cookies(cookies):
    cookie_names = cookies.keys()
    for cookie_name in cookie_names:
        cookie = cookies[cookie_name]
        try:
            cookie_expiration_date = datetime.strptime(
                cookie['expires'], '%a, %d-%b-%Y %H:%M:%S %Z')
            if cookie_expiration_date < datetime.utcnow():
                del cookies[cookie_name]
        except ValueError:
            pass


class MasterSlaveRouterTests(TestCase):
    """Tests for MasterSlaveRouter"""

    def test_db_for_read(self):
        self.assertEquals(MasterSlaveRouter().db_for_read(None), get_slave())
        # TODO: Test the round-robin functionality.

    def test_db_for_write(self):
        self.assertEquals(MasterSlaveRouter().db_for_write(None),
                          DEFAULT_DB_ALIAS)

    def test_allow_syncdb(self):
        """Make sure allow_syncdb() does the right thing for both masters and
        slaves"""
        router = MasterSlaveRouter()
        self.assertTrue(router.allow_syncdb(DEFAULT_DB_ALIAS, None))
        self.assertFalse(router.allow_syncdb(get_slave(), None))


class PinningTests(TestCase):
    """Tests for "pinning" functionality, above and beyond what's inherited
    from MasterSlaveRouter"""

    def tearDown(self):
        unpin_this_thread()

    def test_pinning_encapsulation(self):
        """Check the pinning getters and setters."""
        self.assertFalse(this_thread_is_pinned())
        pin_this_thread()
        self.assertTrue(this_thread_is_pinned())
        unpin_this_thread()
        self.assertFalse(this_thread_is_pinned())

    def test_pinned_reads(self):
        """Test PinningMasterSlaveRouter.db_for_read() when pinned and when
        not."""
        router = PinningMasterSlaveRouter()

        self.assertEquals(router.db_for_read(None), get_slave())

        pin_this_thread()
        self.assertEquals(router.db_for_read(None), DEFAULT_DB_ALIAS)

    def test_db_write_decorator(self):

        def read_view(req):
            self.assertEquals(router.db_for_read(None), get_slave())
            return HttpResponse()

        @db_write
        def write_view(req):
            self.assertEquals(router.db_for_read(None), DEFAULT_DB_ALIAS)
            return HttpResponse()

        router = PinningMasterSlaveRouter()
        self.assertEquals(router.db_for_read(None), get_slave())
        write_view(HttpRequest())
        read_view(HttpRequest())


class MiddlewareTests(TestCase):
    """Tests for the middleware that supports pinning"""
    urls = 'multidb.tests.urls'

    def setUp(self):
        super(MiddlewareTests, self).setUp()

        # Every test uses these, so they're okay as attrs.
        self.request = HttpRequest()
        self.middleware = PinningRouterMiddleware()

    def tearDown(self):
        unpin_this_thread()

    def test_pin_on_cookie(self):
        """Thread should pin when the cookie is set."""

        self.request.COOKIES[settings.MULTIDB_PINNING_COOKIE] = 'y'
        self.middleware.process_request(self.request)
        self.assertTrue(this_thread_is_pinned())

    def test_unpin(self):
        """Thread should unpin when method is GET."""
        pin_this_thread()
        self.request.method = 'GET'
        self.middleware.process_request(self.request)
        self.assertFalse(this_thread_is_pinned())

    def test_pin_on_post(self):
        """Thread should pin when method is POST."""
        self.request.method = 'POST'
        self.middleware.process_request(self.request)
        self.assertTrue(this_thread_is_pinned())

    def test_process_response(self):
        """Make sure the cookie gets set on POST requests and not otherwise."""
        self.request.method = 'GET'
        self.middleware.process_request(self.request)
        response = self.middleware.process_response(self.request,
                                                    HttpResponse())
        self.assertFalse(settings.MULTIDB_PINNING_COOKIE in response.cookies)

        self.request.method = 'POST'
        self.middleware.process_request(self.request)
        response = self.middleware.process_response(self.request,
                                                    HttpResponse())
        self.assertTrue(settings.MULTIDB_PINNING_COOKIE in response.cookies)
        self.assertEquals(
            response.cookies[settings.MULTIDB_PINNING_COOKIE]['max-age'],
            settings.MULTIDB_PINNING_SECONDS)

    def test_attribute(self):
        """The cookie should get set if the _db_write attribute is True."""
        res = HttpResponse()
        res._db_write = True
        response = self.middleware.process_response(self.request, res)
        self.assertTrue(settings.MULTIDB_PINNING_COOKIE in response.cookies)

    def test_db_write_decorator(self):
        """The @db_write decorator should make any view set the cookie."""
        req = self.request
        req.method = 'GET'

        def view(req):
            return HttpResponse()
        response = self.middleware.process_response(req, view(req))
        self.assertFalse(settings.MULTIDB_PINNING_COOKIE in response.cookies)

        @db_write
        def write_view(req):
            return HttpResponse()
        response = self.middleware.process_response(req, write_view(req))
        self.assertTrue(settings.MULTIDB_PINNING_COOKIE in response.cookies)

    @override_settings(MULTIDB_COOKIELESS_CACHE='default',
                       MULTIDB_PINNING_SECONDS=1,
                       MIDDLEWARE_CLASSES=(
                           'multidb.middleware.PinningRouterMiddleware',))
    def test_pinning_cookieless(self):
        # We use a new client in each request so that it doesn't have
        # cookies.

        # First request, not pinned
        c = Client()
        response = c.get('/dummy/')
        self.assertEquals(response.content, "not pinned")

        # Second request, POST; should be pinned
        c = Client()
        response = c.post('/dummy/')
        self.assertEquals(response.content, "pinned")

        # Another GET request; should be pinned
        c = Client()
        response = c.get('/dummy/')
        self.assertEquals(response.content, "pinned")

        # Now let's pretend another user, with a different fingerprint,
        # makes a request; should not be pinned
        c = Client()
        response = c.get('/dummy/', HTTP_USER_AGENT='SuperDuperBrowser')
        self.assertEquals(response.content, "not pinned")

        # But the original user should still be pinned
        c = Client()
        response = c.get('/dummy/')
        self.assertEquals(response.content, "pinned")

        # We wait until cache expires, we try again; should be not pinned
        time.sleep(2)
        c = Client()
        response = c.get('/dummy/')
        self.assertEquals(response.content, "not pinned")

    @override_settings(MULTIDB_COOKIELESS_CACHE='default',
                       MULTIDB_PINNING_SECONDS=1,
                       MIDDLEWARE_CLASSES=(
                           'multidb.middleware.PinningRouterMiddleware',))
    def test_pinning_cookieful_with_cookieless_configuration(self):
        # This test is similar to the previous one; we have a configuration
        # that could work with cookieless users, but we have a user with
        # cookies; we check that everything's ok.

        # We have two clients, with identical fingerprints; we'll mostly use
        # the first one
        c1 = Client()
        c2 = Client()

        # First request, not pinned
        response = c1.get('/dummy/')
        self.assertEquals(response.content, "not pinned")

        # Second request, POST; should be pinned
        response = c1.post('/dummy/')
        self.assertEquals(response.content, "pinned")

        # Another GET request; should be pinned
        response = c1.get('/dummy/')
        self.assertEquals(response.content, "pinned")

        # Now we try the other client; although it has the same fingerprint, it
        # should not be pinned, because the first one was pinned using a
        # cookie.
        response = c2.get('/dummy/')
        self.assertEquals(response.content, "not pinned")

        # But the original user should still be pinned
        response = c1.get('/dummy/')
        self.assertEquals(response.content, "pinned")

        # We wait until cache expires, we try again; should be not pinned
        time.sleep(2)
        expire_cookies(c1.cookies)
        response = c1.get('/dummy/')
        self.assertEquals(response.content, "not pinned")

    def test_multidb_pinning_views_setting(self):
        middleware = ('multidb.middleware.PinningRouterMiddleware',)
        pinning_views = ('multidb.tests.views.dummy_view',
                         'multidb.tests.views.class_based_dummy_view',
                         'multidb.tests.views.object_dummy_view')
        pinning_cookie = settings.MULTIDB_PINNING_COOKIE
        with self.settings(MIDDLEWARE_CLASSES=middleware,
                           MULTIDB_PINNING_VIEWS=pinning_views):
            # We use a new client in each request so that it doesn't have
            # cookies.
            c = Client()
            response = c.get('/dummy/')
            self.assertEquals(response.content, "pinned")
            self.assertTrue(pinning_cookie in response.cookies)
            c = Client()
            response = c.get('/cdummy/')
            self.assertEquals(response.content, "pinned")
            self.assertTrue(pinning_cookie in response.cookies)
            c = Client()
            response = c.get('/odummy/')
            self.assertEquals(response.content, "pinned")
            self.assertTrue(pinning_cookie in response.cookies)
        with self.settings(MIDDLEWARE_CLASSES=middleware,
                           MULTIDB_PINNING_VIEWS=()):
            c = Client()
            response = c.get('/dummy/')
            self.assertEquals(response.content, "not pinned")
            self.assertFalse(pinning_cookie in response.cookies)
            c = Client()
            response = c.get('/cdummy/')
            self.assertEquals(response.content, "not pinned")
            self.assertFalse(pinning_cookie in response.cookies)
            c = Client()
            response = c.get('/odummy/')
            self.assertEquals(response.content, "not pinned")
            self.assertFalse(pinning_cookie in response.cookies)


class ContextDecoratorTests(TestCase):
    def test_decorator(self):

        @use_master
        def check():
            self.assertTrue(this_thread_is_pinned())

        unpin_this_thread()
        self.assertFalse(this_thread_is_pinned())
        check()
        self.assertFalse(this_thread_is_pinned())

    def test_decorator_resets(self):

        @use_master
        def check():
            self.assertTrue(this_thread_is_pinned())

        pin_this_thread()
        self.assertTrue(this_thread_is_pinned())
        check()
        self.assertTrue(this_thread_is_pinned())

    def test_context_manager(self):
        unpin_this_thread()
        self.assertFalse(this_thread_is_pinned())
        with use_master:
            self.assertTrue(this_thread_is_pinned())
        self.assertFalse(this_thread_is_pinned())

    def text_context_manager_resets(self):
        pin_this_thread()
        self.assertTrue(this_thread_is_pinned())
        with use_master:
            self.assertTrue(this_thread_is_pinned())
        self.assertTrue(this_thread_is_pinned())

    def test_context_manager_exception(self):
        unpin_this_thread()
        self.assertFalse(this_thread_is_pinned())
        with self.assertRaises(ValueError):
            with use_master:
                self.assertTrue(this_thread_is_pinned())
                raise ValueError
        self.assertFalse(this_thread_is_pinned())
