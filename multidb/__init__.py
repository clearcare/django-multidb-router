import itertools
import random

from multidb.conf import settings

from .pinning import this_thread_is_pinned, db_write  # noqa


DEFAULT_DB_ALIAS = 'default'


if getattr(settings, 'SLAVE_DATABASES'):
    # Shuffle the list so the first slave db isn't slammed during startup.
    dbs = list(settings.SLAVE_DATABASES)
    random.shuffle(dbs)
    slaves = itertools.cycle(dbs)
    # Set the slaves as test mirrors of the master.
    for db in dbs:
        settings.DATABASES[db]['TEST_MIRROR'] = DEFAULT_DB_ALIAS
else:
    slaves = itertools.repeat(DEFAULT_DB_ALIAS)


def get_slave():
    """Returns the alias of a slave database."""
    return slaves.next()


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

    def allow_syncdb(self, db, model):
        """Only allow syncdb on the master."""
        return db == DEFAULT_DB_ALIAS


class PinningMasterSlaveRouter(MasterSlaveRouter):

    def db_for_read(self, model, **hints):
        """Send reads to slaves in round-robin unless this thread is pinned."""
        return DEFAULT_DB_ALIAS if this_thread_is_pinned() else get_slave()
