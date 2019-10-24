import itertools
import random
from distutils.version import LooseVersion

import django
from django.conf import settings

from .pinning import this_thread_is_pinned, db_write  # noqa

import threading

DEFAULT_DB_ALIAS = 'default'

class MasterSlaveRouter(object):

    def db_for_read(self, model, **hints):
        """Send reads to slaves in round-robin."""
        # print("db for read " + model.__name__ if model is not None else "No Model")
        resolved_db = get_slave(self.get_tenant_id())
        print_with_thread_details("db for read" , resolved_db)
        return resolved_db

    def db_for_write(self, model, **hints):
        """Send all writes to the master."""
        # print("db for write: " + model.__name__ if model is not None else "No Model")
        resolved_db =self.resolve_multi_tenant_db(DEFAULT_DB_ALIAS)
        print_with_thread_details("db for write" , resolved_db)
        return resolved_db

    def allow_relation(self, obj1, obj2, **hints):
        """Allow all relations, so FK validation stays quiet."""
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == self.resolve_multi_tenant_db(DEFAULT_DB_ALIAS)

    def allow_syncdb(self, db, model):
        """Only allow syncdb on the master."""
        return db == self.resolve_multi_tenant_db(DEFAULT_DB_ALIAS)

    def get_tenant_id(self):
        db_id = '0'
        current_thread = threading.current_thread().__dict__
        subdomain = current_thread.get('subdomain')
        for k,v in TENANT_CONFIG.items():
            if subdomain in v:
                db_id = str(k)
        print("tenant resolving -- subdomain={}::db_id={}".format(subdomain, db_id))
        return db_id

    def resolve_multi_tenant_db(self, db_name, tenant_id=None):
        try:
            db_id = self.get_tenant_id() if tenant_id is None else tenant_id
            resolved_db = '{}-{}'.format(db_name, db_id)
            # print('{}:{}'.format(subdomain, resolved_db))
            return resolved_db
        except:
            # print("no subdomain value set")
            return db_name

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
        # print("db for read override " + model.__name__ if model is not None else "No Model")
        resolved_db = self.resolve_multi_tenant_db(DEFAULT_DB_ALIAS) if this_thread_is_pinned() else get_slave(self.get_tenant_id())
        print_with_thread_details("db for read override" , resolved_db)
        return resolved_db



TENANT_CONFIG = {
    '0': ['bg-hisc','tenant-admin-0','tenant-hq-0','testserver'],
    '1': ['metzler','tenant-admin-1','tenant-hq-1'],
}

# if getattr(settings, 'SLAVE_DATABASES'):
#     # Shuffle the list so the first slave db isn't slammed during startup.
#     dbs = list(settings.SLAVE_DATABASES)
#     random.shuffle(dbs)
#     slaves = itertools.cycle(dbs)
#     # Set the slaves as test mirrors of the master.
#     for db in dbs:
#         resolved_db_name= MasterSlaveRouter().resolve_multi_tenant_db(DEFAULT_DB_ALIAS)
#         if LooseVersion(django.get_version()) >= LooseVersion('1.7'):
#             settings.DATABASES[db].get('TEST', {})['MIRROR'] = resolved_db_name #DEFAULT_DB_ALIAS
#         else:
#             settings.DATABASES[db]['TEST_MIRROR'] = resolved_db_name #DEFAULT_DB_ALIAS
# else:
#     slaves = itertools.repeat(DEFAULT_DB_ALIAS)

def print_with_thread_details(event_name, db_name):
    subdomain = '--'
    thread_id = '--'
    try:
        current_thread = threading.current_thread().__dict__
        subdomain = current_thread.get('subdomain')
        thread_id = current_thread.get('id')
    except:
        pass
    print("event={}::thread={}::db={}::subdomain={}".format(
                                                    event_name,
                                                    thread_id, 
                                                    db_name, 
                                                    subdomain
                                                ))

def get_tenant_slave_dbs():
    dbs = []
    try:
        # check for slaves-<tenantId> in the DATABASES config value to get a match
        tenant_slaves_list = [x for x,y in settings.DATABASES.items() if ("slave" in x)]
        dbs = tenant_slaves_list
    except:
        if getattr(settings, 'SLAVE_DATABASES'):
            dbs = list(settings.SLAVE_DATABASES)
    # Shuffle the list so the first slave db isn't slammed during startup.
    random.shuffle(dbs)
    slaves_temp = itertools.cycle(dbs)
    # Set the slaves as test mirrors of the master.
    for db in dbs:
        resolved_db_name = MasterSlaveRouter().resolve_multi_tenant_db(
                                                    DEFAULT_DB_ALIAS, 
                                                    parse_tenant_id_from_db_config(db))
        if LooseVersion(django.get_version()) >= LooseVersion('1.7'):
            settings.DATABASES[db].get('TEST', {})['MIRROR'] = resolved_db_name #DEFAULT_DB_ALIAS
        else:
            settings.DATABASES[db]['TEST_MIRROR'] = resolved_db_name #DEFAULT_DB_ALIAS
    # else:
    #     slaves = itertools.repeat(DEFAULT_DB_ALIAS)
    return slaves_temp

def parse_tenant_id_from_db_config(db_config_name):
    try:
        return db_config_name.split("-")[1]
    except:
        return None

def get_slave(tenant_id='0'):
    """Returns the alias of a slave database.
        tenant_id = 0 for unit tests
    """
    #return next(tenant_slaves)
    resolved_slave_node = get_tenant_slave_node(next(tenant_slaves), tenant_id)
    return resolved_slave_node

def get_tenant_slave_node(slave_node, tenant_id):
    if ("-" + tenant_id) in slave_node:
        return slave_node
    else:
        return get_tenant_slave_node(next(tenant_slaves), tenant_id)

tenant_slaves = get_tenant_slave_dbs()

