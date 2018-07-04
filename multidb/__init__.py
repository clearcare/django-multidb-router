import itertools
import random
from distutils.version import LooseVersion

import django
from django.conf import settings

from .pinning import this_thread_is_pinned, db_write  # noqa


DEFAULT_DB_ALIAS = 'default'


if getattr(settings, 'SLAVE_DATABASES'):
    # Shuffle the list so the first slave db isn't slammed during startup.
    dbs = list(settings.SLAVE_DATABASES)
    random.shuffle(dbs)
    slaves = itertools.cycle(dbs)
    # Set the slaves as test mirrors of the master.
    for db in dbs:
        if LooseVersion(django.get_version()) >= LooseVersion('1.7'):
            settings.DATABASES[db].get('TEST', {})['MIRROR'] = DEFAULT_DB_ALIAS
        else:
            settings.DATABASES[db]['TEST_MIRROR'] = DEFAULT_DB_ALIAS
else:
    slaves = itertools.repeat(DEFAULT_DB_ALIAS)


def get_slave():
    """Returns the alias of a slave database."""
    return next(slaves)


class MasterSlaveRouter(object):

    def db_for_read(self, model, **hints):
        """Send reads to slaves in round-robin."""
        return get_slave()

    def db_for_write(self, model, **hints):
        """Send all writes to the master."""
        return DEFAULT_DB_ALIAS

    def allow_relation(self, obj1, obj2, **hints):
        """Allow all relations, so FK validation stays quiet."""
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == DEFAULT_DB_ALIAS

    def allow_syncdb(self, db, model):
        """Only allow syncdb on the master."""
        return db == DEFAULT_DB_ALIAS


class PinningMasterSlaveRouter(MasterSlaveRouter):
    """Router that sends reads to master if a certain flag is set. Writes
    always go to master.

    Typically, we set a cookie in middleware for certain request HTTP methods
    and give it a max age that's certain to be longer than the replication lag.
    The flag comes from that cookie.
    
    """
    def db_for_read(self, model, **hints):
        """Send reads to slaves in round-robin unless this thread is pinned."""
        return DEFAULT_DB_ALIAS if this_thread_is_pinned() else get_slave()
