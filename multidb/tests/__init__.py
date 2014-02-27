from django.http import HttpRequest, HttpResponse
from django.test import TestCase
from django.test.client import Client

from nose.tools import eq_

from multidb import (DEFAULT_DB_ALIAS, MasterSlaveRouter,
                     PinningMasterSlaveRouter, get_slave)
from multidb.conf import settings
from multidb.middleware import PinningRouterMiddleware
from multidb.pinning import (this_thread_is_pinned, pin_this_thread,
                             unpin_this_thread, use_master, db_write)


class UnpinningTestCase(TestCase):
    """Test case that unpins the thread on tearDown"""

    def tearDown(self):
        unpin_this_thread()


class MasterSlaveRouterTests(TestCase):
    """Tests for MasterSlaveRouter"""

    def test_db_for_read(self):
        eq_(MasterSlaveRouter().db_for_read(None), get_slave())
        # TODO: Test the round-robin functionality.

    def test_db_for_write(self):
        eq_(MasterSlaveRouter().db_for_write(None), DEFAULT_DB_ALIAS)

    def test_allow_syncdb(self):
        """Make sure allow_syncdb() does the right thing for both masters and
        slaves"""
        router = MasterSlaveRouter()
        assert router.allow_syncdb(DEFAULT_DB_ALIAS, None)
        assert not router.allow_syncdb(get_slave(), None)


class PinningTests(UnpinningTestCase):
    """Tests for "pinning" functionality, above and beyond what's inherited
    from MasterSlaveRouter"""

    def test_pinning_encapsulation(self):
        """Check the pinning getters and setters."""
        assert not this_thread_is_pinned(), \
            "Thread started out pinned or this_thread_is_pinned() is broken."

        pin_this_thread()
        assert this_thread_is_pinned(), \
            "pin_this_thread() didn't pin the thread."

        unpin_this_thread()
        assert not this_thread_is_pinned(), \
            "Thread remained pinned after unpin_this_thread()."

    def test_pinned_reads(self):
        """Test PinningMasterSlaveRouter.db_for_read() when pinned and when
        not."""
        router = PinningMasterSlaveRouter()

        eq_(router.db_for_read(None), get_slave())

        pin_this_thread()
        eq_(router.db_for_read(None), DEFAULT_DB_ALIAS)

    def test_db_write_decorator(self):

        def read_view(req):
            eq_(router.db_for_read(None), get_slave())
            return HttpResponse()

        @db_write
        def write_view(req):
            eq_(router.db_for_read(None), DEFAULT_DB_ALIAS)
            return HttpResponse()

        router = PinningMasterSlaveRouter()
        eq_(router.db_for_read(None), get_slave())
        write_view(HttpRequest())
        read_view(HttpRequest())


class MiddlewareTests(UnpinningTestCase):
    """Tests for the middleware that supports pinning"""
    urls = 'multidb.tests.urls'

    def setUp(self):
        super(MiddlewareTests, self).setUp()

        # Every test uses these, so they're okay as attrs.
        self.request = HttpRequest()
        self.middleware = PinningRouterMiddleware()

    def test_pin_on_cookie(self):
        """Thread should pin when the cookie is set."""

        self.request.COOKIES[settings.MULTIDB_PINNING_COOKIE] = 'y'
        self.middleware.process_request(self.request)
        assert this_thread_is_pinned()

    def test_unpin_on_no_cookie(self):
        """Thread should unpin when cookie is absent and method is GET."""
        pin_this_thread()
        self.request.method = 'GET'
        self.middleware.process_request(self.request)
        assert not this_thread_is_pinned()

    def test_pin_on_post(self):
        """Thread should pin when method is POST."""
        self.request.method = 'POST'
        self.middleware.process_request(self.request)
        assert this_thread_is_pinned()

    def test_process_response(self):
        """Make sure the cookie gets set on POST requests and not otherwise."""
        self.request.method = 'GET'
        self.middleware.process_request(self.request)
        response = self.middleware.process_response(self.request,
                                                    HttpResponse())
        assert settings.MULTIDB_PINNING_COOKIE not in response.cookies

        self.request.method = 'POST'
        self.middleware.process_request(self.request)
        response = self.middleware.process_response(self.request,
                                                    HttpResponse())
        assert settings.MULTIDB_PINNING_COOKIE in response.cookies
        eq_(response.cookies[settings.MULTIDB_PINNING_COOKIE]['max-age'],
            settings.MULTIDB_PINNING_SECONDS)

    def test_attribute(self):
        """The cookie should get set if the _db_write attribute is True."""
        res = HttpResponse()
        res._db_write = True
        response = self.middleware.process_response(self.request, res)
        assert settings.MULTIDB_PINNING_COOKIE in response.cookies

    def test_db_write_decorator(self):
        """The @db_write decorator should make any view set the cookie."""
        req = self.request
        req.method = 'GET'

        def view(req):
            return HttpResponse()
        response = self.middleware.process_response(req, view(req))
        assert settings.MULTIDB_PINNING_COOKIE not in response.cookies

        @db_write
        def write_view(req):
            return HttpResponse()
        response = self.middleware.process_response(req, write_view(req))
        assert settings.MULTIDB_PINNING_COOKIE in response.cookies

    def test_multidb_pinning_views_setting(self):
        middleware = ('multidb.middleware.PinningRouterMiddleware',)
        pinning_views = ('multidb.tests.views.dummy_view',
                         'multidb.tests.views.class_based_dummy_view',
                         'multidb.tests.views.object_dummy_view')
        with self.settings(MIDDLEWARE_CLASSES=middleware,
                           MULTIDB_PINNING_VIEWS=pinning_views):
            # We use a new client in each request so that it doesn't have
            # cookies.
            c = Client()
            response = c.get('/dummy/')
            self.assertEquals(response.content, "pinned")
            self.assertTrue(settings.MULTIDB_PINNING_COOKIE in response.cookies)
            c = Client()
            response = c.get('/cdummy/')
            self.assertEquals(response.content, "pinned")
            self.assertTrue(settings.MULTIDB_PINNING_COOKIE in response.cookies)
            c = Client()
            response = c.get('/odummy/')
            self.assertEquals(response.content, "pinned")
            self.assertTrue(settings.MULTIDB_PINNING_COOKIE in response.cookies)
        with self.settings(MIDDLEWARE_CLASSES=middleware,
                           MULTIDB_PINNING_VIEWS=()):
            c = Client()
            response = c.get('/dummy/')
            self.assertEquals(response.content, "not pinned")
            self.assertFalse(settings.MULTIDB_PINNING_COOKIE in response.cookies)
            c = Client()
            response = c.get('/cdummy/')
            self.assertEquals(response.content, "not pinned")
            self.assertFalse(settings.MULTIDB_PINNING_COOKIE in response.cookies)
            c = Client()
            response = c.get('/odummy/')
            self.assertEquals(response.content, "not pinned")
            self.assertFalse(settings.MULTIDB_PINNING_COOKIE in response.cookies)


class ContextDecoratorTests(TestCase):
    def test_decorator(self):
        @use_master
        def check():
            assert this_thread_is_pinned()
        unpin_this_thread()
        assert not this_thread_is_pinned()
        check()
        assert not this_thread_is_pinned()

    def test_decorator_resets(self):
        @use_master
        def check():
            assert this_thread_is_pinned()
        pin_this_thread()
        assert this_thread_is_pinned()
        check()
        assert this_thread_is_pinned()

    def test_context_manager(self):
        unpin_this_thread()
        assert not this_thread_is_pinned()
        with use_master:
            assert this_thread_is_pinned()
        assert not this_thread_is_pinned()

    def text_context_manager_resets(self):
        pin_this_thread()
        assert this_thread_is_pinned()
        with use_master:
            assert this_thread_is_pinned()
        assert this_thread_is_pinned()

    def test_context_manager_exception(self):
        unpin_this_thread()
        assert not this_thread_is_pinned()
        with self.assertRaises(ValueError):
            with use_master:
                assert this_thread_is_pinned()
                raise ValueError
        assert not this_thread_is_pinned()