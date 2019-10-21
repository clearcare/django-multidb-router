import itertools
import random
from distutils.version import LooseVersion

import django
from django.conf import settings

from .pinning import this_thread_is_pinned, db_write  # noqa


DEFAULT_DB_ALIAS = 'default'


class MasterSlaveRouter(object):

    def db_for_read(self, model, **hints):
        """Send reads to slaves in round-robin."""
        print("db for read " + model.__name__)
        return self.resolve_multi_tenant_db(get_slave())

    def db_for_write(self, model, **hints):
        """Send all writes to the master."""
        print("db for write: " + model.__name__)
        return self.resolve_multi_tenant_db(DEFAULT_DB_ALIAS)

    def allow_relation(self, obj1, obj2, **hints):
        """Allow all relations, so FK validation stays quiet."""
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == self.resolve_multi_tenant_db(DEFAULT_DB_ALIAS)

    def allow_syncdb(self, db, model):
        """Only allow syncdb on the master."""
        return db == self.resolve_multi_tenant_db(DEFAULT_DB_ALIAS)

    def resolve_multi_tenant_db(self, db_name):
        import threading
        db_id = '0'
        current_thread = threading.current_thread().__dict__
        subdomain = current_thread.get('subdomain')
        for k,v in TENANT_CONFIG.items():
            if subdomain in v:
                db_id = str(k)
        return '{}-{}'.format(db_name, db_id)


class PinningMasterSlaveRouter(MasterSlaveRouter):
    """Router that sends reads to master if a certain flag is set. Writes
    always go to master.
    Typically, we set a cookie in middleware for certain request HTTP methods
    and give it a max age that's certain to be longer than the replication lag.
    The flag comes from that cookie.
    
    """
    def db_for_read(self, model, **hints):
        """Send reads to slaves in round-robin unless this thread is "stuck" to
        the master."""
        print("db for read override " + model.__name__)
        db_to_return = DEFAULT_DB_ALIAS if this_thread_is_pinned() else get_slave()
        return self.resolve_multi_tenant_db(db_to_return)

TENANT_CONFIG = {
    '0': ['bg-hisc'],
    '1': ['metzler'],
}

if getattr(settings, 'SLAVE_DATABASES'):
    # Shuffle the list so the first slave db isn't slammed during startup.
    dbs = list(settings.SLAVE_DATABASES)
    random.shuffle(dbs)
    slaves = itertools.cycle(dbs)
    # Set the slaves as test mirrors of the master.
    for db in dbs:
        resolved_db_name= MasterSlaveRouter().resolve_multi_tenant_db(DEFAULT_DB_ALIAS)
        if LooseVersion(django.get_version()) >= LooseVersion('1.7'):
            settings.DATABASES[db].get('TEST', {})['MIRROR'] = resolved_db_name #DEFAULT_DB_ALIAS
        else:
            settings.DATABASES[db]['TEST_MIRROR'] = resolved_db_name #DEFAULT_DB_ALIAS
else:
    slaves = itertools.repeat(DEFAULT_DB_ALIAS)


def get_slave():
    """Returns the alias of a slave database."""
    return next(slaves)

