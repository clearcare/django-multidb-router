import itertools
import random
from distutils.version import LooseVersion

import django
from django.conf import settings

from .pinning import this_thread_is_pinned, db_write  # noqa

import threading

DEFAULT_DB_ALIAS = 'default'

db_router = getattr(settings, 'DATABASE_ROUTERS')
IS_MULTI_TENANT=False
if db_router:
    if 'multidb.PinningMasterSlaveRouter' in db_router:
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
    else:
        IS_MULTI_TENANT = True
        dbs = list(settings.SLAVE_DATABASES)
        # Shuffle the list so the first slave db isn't slammed during startup.
        random.shuffle(dbs)
        slaves = itertools.cycle(dbs)
        def parse_tenant_id_from_db_config(db_config_name):
            try:
                return db_config_name.split(".")[0]
            except:
                return None
        # Set the slaves as test mirrors of the master.
        for db in dbs:
            # the SLAVE_DATABASES is expected to be an array of tenant_id.db_key
            # resolved_db_name = MultiTenantMasterSlaveRouter().resolve_multi_tenant_db(
            #                                             DEFAULT_DB_ALIAS, 
            #                                             parse_tenant_id_from_db_config(db))

            # get me all db across tenant based on the db in loop
            tenant_databases_matching_dbs = [x for x in settings.DATABASES if db in x]
            
            # for each matched tenant db, set its correspoinding default value as mirror
            for tenant_matched_db in tenant_databases_matching_dbs:
                tenant_id = parse_tenant_id_from_db_config(tenant_matched_db)
                if LooseVersion(django.get_version()) >= LooseVersion('1.7'):
                    settings.DATABASES[tenant_matched_db].get('TEST', {})['MIRROR'] = tenant_id+".default" #DEFAULT_DB_ALIAS
                else:
                    settings.DATABASES[tenant_matched_db]['TEST_MIRROR'] = tenant_id+".default" #DEFAULT_DB_ALIAS
        else:
            # get me all db across tenant based on the db in loop
            tenant_databases_matching_dbs = [x for x in settings.DATABASES if db in x]

            # for each matched tenant db, set its correspoinding default value as mirror
            for tenant_matched_db in tenant_databases_matching_dbs:
                tenant_id = parse_tenant_id_from_db_config(tenant_matched_db)
                slaves = itertools.repeat(tenant_id+".default")
    

class MasterSlaveRouter(object):

    def get_slave(self):
        """Returns the alias of a slave database."""
        return next(slaves)

    def db_for_read(self, model, **hints):
        """Send reads to slaves in round-robin."""
        return self.get_slave()

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
        """Send reads to slaves in round-robin unless this thread is "stuck" to
        the master."""
        return DEFAULT_DB_ALIAS if this_thread_is_pinned() else self.get_slave()

class MultiTenantMasterSlaveRouter(MasterSlaveRouter):

    def get_slave(self, tenant_id='0', sub_domain=None):
        return self._get_slave(tenant_id, sub_domain)

    def _get_slave(self, tenant_id='0', sub_domain=None):
        """Returns the alias of a slave database.
            tenant_id = 0 for unit tests
            tenant id derived from sub_domain value will override tenant id param
        """
        if sub_domain is not None:
            tenant_id = self.get_tenant_id(sub_domain=sub_domain)
        resolved_slave_node = self.get_tenant_slave_node(next(slaves), tenant_id)
        return resolved_slave_node

    def get_tenant_slave_node(self, slave_node, tenant_id):
        if slave_node == DEFAULT_DB_ALIAS:
            slave_node = tenant_id + "." + DEFAULT_DB_ALIAS
        if (tenant_id + ".") in slave_node:
            if (settings.TENANT_LOG_MODE == "DEBUG"):
                print("slave node found for tenant = " + str(slave_node))
            return slave_node
        else:
            if (settings.TENANT_LOG_MODE == "DEBUG"):
                print("no slave node found for tenant, provided node name = " + str(slave_node))
            return self.get_tenant_slave_node(next(slaves), tenant_id)

    def db_for_read(self, model, **hints):
        """Send reads to slaves in round-robin."""
        # print("db for read " + model.__name__ if model is not None else "No Model")
        resolved_db = self.get_slave(self.get_tenant_id())
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

    def get_tenant_id(self, sub_domain=None):
        db_id = '0'
        if sub_domain is None:
            current_thread = threading.current_thread().__dict__
            subdomain = current_thread.get('subdomain')
        else:
            subdomain = sub_domain
        for k,v in TENANT_CONFIG.items():
            if subdomain in v:
                db_id = str(k)
        if (settings.TENANT_LOG_MODE == "DEBUG"):
            print("tenant resolving -- subdomain={}::db_id={}".format(subdomain, db_id))
        return db_id

    def resolve_multi_tenant_db(self, db_name, tenant_id=None):
        try:
            db_id = self.get_tenant_id() if tenant_id is None else tenant_id
            resolved_db = '{}.{}'.format(db_id, db_name)
            # print('{}:{}'.format(subdomain, resolved_db))
            return resolved_db
        except:
            # print("no subdomain value set")
            return db_name

class MultiTenantMasterPinningSlaveRouter(MultiTenantMasterSlaveRouter):
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
        resolved_db = self.resolve_multi_tenant_db(DEFAULT_DB_ALIAS) if this_thread_is_pinned() else self.get_slave(self.get_tenant_id())
        print_with_thread_details("db for read override" , resolved_db, hints)
        return resolved_db





def get_tenant_config():
    import requests, json
    api_key = settings.TENANT_SERVICE_API_KEY
    api_endpoint = settings.TENANT_SERVICE_API_ENDPOINT
    headers = {"x-api-key": api_key}
    query = """
    query {
        getTenants {
            id,
            admin {
                portal {
                    url
                }
            },
            hq {
                portal {
                    url
                }
            },
            franchisor {
                id,
                agencies {
                    portal {
                        url
                    }
                }
            }
        }
    }
    """
    response = requests.post(api_endpoint,
                            json={'query': query}, headers=headers)

    items = response.json()['data']['getTenants']

    tenants = {}
    for item in items:
        agencies = [x['portal']['url'] for x in item['franchisor']['agencies']]
        base_portals = [item['admin']['portal']['url'], item['hq']['portal']['url']]
        tenants[item['id']] = [x for x in (base_portals + agencies)]
    return tenants

def get_env(name, default=None, prefix='CC_'):
    import os
    val = os.environ.get(prefix + name, default)
    try:
        return eval(val) # this is a potential security risk
    except:
        return val

TENANT_SERVICE_API_KEY = get_env(name="TENANT_SERVICE_API_KEY",default="da2-yhem3pedtjfmnhrrjeam4fdxwa")
TENANT_SERVICE_API_ENDPOINT = get_env(name="TENANT_SERVICE_API_ENDPOINT",default="https://ednpt77lq5bnndhvkzf4lfwkme.appsync-api.us-west-2.amazonaws.com/graphql")
TENANT_LOG_MODE = get_env(name="TENANT_LOG_MODE", default="DEBUG_ROUTER")
TENANT_DB_CONFIGS = {}

def print_with_thread_details(event_name, db_name, hints=None):
    subdomain = '--'
    thread_id = '--'
    try:
        current_thread = threading.current_thread().__dict__
        subdomain = current_thread.get('subdomain')
        thread_id = threading.current_thread().__name__
    except:
        pass
    if (settings.TENANT_LOG_MODE == "DEBUG"):
        print("event={}::thread={}::db={}::subdomain={}".format(
                                                        event_name,
                                                        thread_id, 
                                                        db_name, 
                                                        subdomain
                                                    ))
        try:
            if hints is not None:
                for k,v in hints.items():
                    try:
                        print("key = " + str(k))
                        #print("value = " + str(v))
                    except:
                        pass
        except Exception as e:
            print("hints exception: " + str(e))

TENANT_CONFIG = get_tenant_config()
print("router tenant config " + str(TENANT_CONFIG))