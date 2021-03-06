``multidb`` provides two Django database routers useful in master-slave
deployments:

* ``multidb.MasterSlaveRouter`` simply sends all read queries to a
  slave database; and all inserts, updates, and deletes to the
  ``default`` database. Use it like this::

     DATABASES = {
         'default': {...},
         'shadow-1': {...},
         'shadow-2': {...},
     }
     SLAVE_DATABASES = ['shadow-1', 'shadow-2']
     DATABASE_ROUTERS = ('multidb.MasterSlaveRouter',)

  The slave databases are chosen in round-robin fashion.

* ``multidb.PinningMasterSlaveRouter`` distinguishes HTTP requests
  into ones that are "pinned to the write db" and those that are not
  pinned. A request is pinned either if it is likely to write to the
  database (most usually this means a POST request), or if a short
  while ago there was a request by the same user that may have
  written to the database (this is in order to account for
  replication lags). Pinned requests use the ``default`` database for
  reading; otherwise they use the slaves in round-robin fashion.

  This is an example configuration; but see the configuration
  reference below for details::

     DATABASES = {
         'default': {...},
         'shadow-1': {...},
         'shadow-2': {...},
     }
     SLAVE_DATABASES = ['shadow-1', 'shadow-2']
     DATABASE_ROUTERS = ('multidb.PinningMasterSlaveRouter',)

     # PinningMasterSlaveRouter must always be used in
     # combination with PinningRouterMiddleware, which must
     # always be listed first in MIDDLEWARE_CLASSES
     MIDDLEWARE_CLASSES = (
         'multidb.middleware.PinningRouterMiddleware',
         ...more middleware here...
     )

     MULTIDB_PINNING_VIEWS = ('django.contrib.syndication.views.Feed',
                              'myapp.core.views.myview')
     MULTIDB_PINNING_SECONDS = 5
     MULTIDB_PINNING_COOKIE = 'multidb_pin_writes'

Configuration parameters
========================

SLAVE_DATABASES
   A list of database aliases that can be found in ``DATABASES``.

MULTIDB_PINNING_COOKIE
   ``PinningRouterMiddleware`` attaches a cookie to any user agent who
   has just written. This specifies the name of the cookie; default
   "multidb_pin_writes".
   
MULTIDB_PINNING_SECONDS
   Specifies how long requests will be pinned after a request that may
   have written to the database; default 15 seconds. Specify a value
   that you are certain is longer than your replication lag.

MULTIDB_PINNING_VIEWS
   A list of views that are considered to be writes, and therefore
   result in pinning.  The setting is a sequence of strings, which are
   the full paths of the view names, such as
   ``myapp.core.views.myview``. If the view is a generic view, the
   view name is the name of the class (i.e. without the ``.as_view``).
   If the view is an object (such as the object returned by
   ``django.contrib.syndication.views.Feed()``), the view name is the
   name of the class (``django.contrib.syndication.views.Feed`` in our
   example).

   ``PinningRouterMiddleware`` assumes that requests with HTTP methods
   that are not ``GET``, ``TRACE``, ``HEAD``, or ``OPTIONS`` are
   always writes; therefore you don't need to specify those in
   ``MULTIDB_PINNING_VIEWS``. In fact, if your application follows the
   standard recommendation that ``GET`` should not have side effects,
   then, in theory, everything should work correctly without
   specifying ``MULTIDB_PINNING_VIEWS``. In practice things don't
   always work out like this, but needing to specify stuff in
   ``MULTIDB_PINNING_VIEWS`` should be an exception.

MULTIDB_COOKIELESS_CACHE
   Pinning normally works with a cookie. By specifying
   ``MULTIDB_COOKIELESS_CACHE``, you can make pinning work for
   cookieless users as well. This works by saving state information in
   the cache instead of at a cookie; this information includes the
   client fingerprint (a hash of the client's IP address, User-Agent,
   and some other HTTP headers).

   ``MULTIDB_COOKIELESS_CACHE`` is a key from ``CACHES``. That cache
   will be used for storing state information for cookieless users;
   the default is to not this, meaning there will be no pinning for
   cookieless users.

   If you specify ``MULTIDB_COOKIELESS_CACHE``, make sure the cache
   specified is shared among all servers; if one request by the user
   goes to server A and the next by the same user goes to B, A and B
   must be using the same cache; storing state information on a local
   cache will fail.

MULTIDB_COOKIELESS_COOKIE
   When ``MULTIDB_COOKIELESS_CACHE`` is set to a non-empty value,
   ``django-multidb-router`` uses an additional cookie in order to
   check whether a user is cookieless. The first time a user visits he
   sends no cookies, so ``django-multidb-router`` will check the
   cache and will not find any information there. A first time visit
   is normally not a write, so ``django-multidb-router`` will not need
   to pin the user (but even if it does so in the cache, it's no big
   deal). When responding to this first time visit, it will set a
   cookie that expires at the end of the brower session. When, in
   subsequent requests, ``django-multidb-router`` receives that
   cookie, it knows that the user uses cookies and will therefore not
   make any attempt to get state information from the cache, as it is
   less reliable.

   ``MULTIDB_COOKIELESS_COOKIE`` can be used to change the name of the
   cookie. The default is "multidb_use_cookies".

API
===

Normally you only need to install ``django-multidb-router`` and change
your configuration; you shouldn't need to modify application code.
However, there are some facilities you might need to use.

If you want to get a connection to a slave in your app, use
``multidb.get_slave``::

    from django.db import connections
    import multidb

    connection = connections[multidb.get_slave()]

Instead of listing a view in ``MULTIDB_PINNING_VIEWS``, you can
decorate it with the ``multidb.db_write`` decorator.

You can also manually set ``response._db_write = True`` to indicate
that a write occurred. This will not result in using the ``default``
database in this request, but only in the next request.

``multidb.pinning.use_master`` is both a context manager and a
decorator for wrapping code to use the master database. You can use it
as a context manager::

    from multidb.pinning import use_master

    with use_master:
        touch_the_database()
    touch_another_database()

or as a decorator::

    from multidb.pinning import use_master

    @use_master
    def func(*args, **kw):
        """Touches the master database."""

Running the Tests
=================

::

    ./run.sh test
