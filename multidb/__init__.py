import itertools
import random
from distutils.version import LooseVersion

import django
from django.conf import settings

from .pinning import this_thread_is_pinned, db_write  # noqa

import threading

DEFAULT_DB_ALIAS = 'default'

def resolve_db_name(db, tenant_id):
    if "-" in db:
        return db
    return "{}-{}".format(db, tenant_id)

db_router = getattr(settings, 'DATABASE_ROUTERS')
IS_MULTI_TENANT=False
if db_router:
    if 'multidb.PinningMasterSlaveRouter' in db_router:
        if getattr(settings, 'SLAVE_DATABASES'):
            # Shuffle the list so the first slave db isn't slammed during startup.
            dbs = list(settings.SLAVE_DATABASES)
            print("resolved slave dbs across tenants = " + str(dbs))
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
        if getattr(settings, 'SLAVE_DATABASES'):
            dbs = list(settings.SLAVE_DATABASES)
            # lets resolve for tenancy per slave database mentioned
            # e.g: SLAVE_DATABASES=[slavedb1,slavedb2] should result in [tenant-1.slavedb1,tenant-1.slavedb2...]
            resolved_dbs = []
            for db in dbs:
                tenant_databases_matching_dbs = [resolved_dbs.append(x) for x in settings.DATABASES if "." in x and x.split(".")[1].lower()==db.lower() ]
                #resolved_dbs.update(tenant_databases_matching_dbs)

            dbs = resolved_dbs
            print("resolved slave dbs across tenants = " + str(dbs))
            # Shuffle the list so the first slave db isn't slammed during startup.
            random.shuffle(dbs)
            slaves = itertools.cycle(dbs)
            def parse_tenant_id_from_db_config(db_config_name):
                try:
                    return db_config_name.split("-")[1]
                except:
                    return None
            # Set the slaves as test mirrors of the master.
            for db in dbs:
                # for each matched tenant db, set its correspoinding default value as mirror
                tenant_id = parse_tenant_id_from_db_config(db)
                if LooseVersion(django.get_version()) >= LooseVersion('1.7'):
                    settings.DATABASES[db].get('TEST', {})['MIRROR'] = resolve_db_name(DEFAULT_DB_ALIAS, tenant_id) # tenant_id+".default" #DEFAULT_DB_ALIAS
                else:
                    settings.DATABASES[db]['TEST_MIRROR'] = resolve_db_name(DEFAULT_DB_ALIAS, tenant_id) #tenant_id+".default" #DEFAULT_DB_ALIAS
        else:
            # get me all default tenant db and add it to slaves node
            tenant_databases_matching_dbs = [x for x in settings.DATABASES if 'default' in x and "-" in x]
            print("tenant_databases_matching_dbs: {}".format(str(tenant_databases_matching_dbs)))
            random.shuffle(tenant_databases_matching_dbs)
            slaves = itertools.cycle(tenant_databases_matching_dbs)

def get_slave(sub_domain=None):
    if 'multidb.PinningMasterSlaveRouter' in db_router:
        MasterSlaveRouter().get_slave(sub_domain)
    else:
        MultiTenantMasterPinningSlaveRouter().get_slave(sub_domain=sub_domain)

class MasterSlaveRouter(object):

    def get_slave(self, subdomain=None):
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
            tenant_id = 0 for unit tests and assuming 0 is not used in tenant values
            tenant id derived from sub_domain value will override tenant id param
        """
        if sub_domain is not None:
            tenant_id = self.get_tenant_id(sub_domain=sub_domain)
        # check if slaves has tenant specific values, if not return empty
        try:
            if not slaves or tenant_id == '0':
                return resolve_db_name(DEFAULT_DB_ALIAS, tenant_id)
        except:
            return resolve_db_name(DEFAULT_DB_ALIAS, tenant_id)
        import pdb;pdb.set_trace()
        print("resolving slave nodes: {}".format(next(slaves)))
        resolved_slave_node = self.get_tenant_slave_node(next(slaves), tenant_id)
        return resolved_slave_node

    def get_tenant_slave_node(self, slave_node, tenant_id):
        print("get_tenant_slave_node: {},{}".format(slave_node, tenant_id))
        if slave_node == DEFAULT_DB_ALIAS:
            slave_node = resolve_db_name(DEFAULT_DB_ALIAS, tenant_id)
        if ("-" + tenant_id) in slave_node:
            if (settings.TENANT_LOG_MODE == "DEBUG_ROUTER"):
                print("slave node found for tenant: {}, provided slave node: {} ".format(tenant_id,slave_node))
            return slave_node
        else:
            if (settings.TENANT_LOG_MODE == "DEBUG_ROUTER"):
                print("No slave node found for tenant: {}, provided slave node: {} ".format(tenant_id,slave_node))
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
        if TENANT_CONFIG is not None:
            db_id = TENANT_CONFIG.get(subdomain, {}).get('tenant_id', '0')

        if (settings.TENANT_LOG_MODE == "DEBUG_ROUTER_TENANT_RESOLVE"):
            print("tenant resolving -- subdomain={}::db_id={}".format(subdomain, db_id))
        return db_id

    def resolve_multi_tenant_db(self, db_name, tenant_id=None):
        try:
            if "-" in db_name:
                return db_name
            db_id = self.get_tenant_id() if tenant_id is None else tenant_id
            resolved_db = resolve_db_name(db_name, db_id)
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

def get_tenants():
    import requests, json
    api_key = TENANT_SERVICE_API_KEY
    api_endpoint = TENANT_SERVICE_API_ENDPOINT
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
            },
            web_write_elb_conf {
                    ENGINE
                    NAME
                    USER
                    PASSWORD
                    HOST
                    PORT
                },
            web_read_elb_conf {
                    ENGINE
                    NAME
                    USER
                    PASSWORD
                    HOST
                    PORT
                },
            worker_read_elb_conf {
                    ENGINE
                    NAME
                    USER
                    PASSWORD
                    HOST
                    PORT
                },
            worker_write_elb_conf {
                    ENGINE
                    NAME
                    USER
                    PASSWORD
                    HOST
                    PORT
                },
            reporting_read_elb_conf {
                    ENGINE
                    NAME
                    USER
                    PASSWORD
                    HOST
                    PORT
                }
        }
    }
    """
    response = requests.post(api_endpoint,
                            json={'query': query}, headers=headers)

    items = response.json()['data']['getTenants']
    return items
    # tenants = {}
    # for item in items:
    #     agencies = [x['portal']['url'] for x in item['franchisor']['agencies']]
    #     base_portals = [item['admin']['portal']['url'], item['hq']['portal']['url']]
    #     tenants[item['id']] = [x for x in (base_portals + agencies)]
    # return tenants

def get_tenant_url_mappings():
    items = get_tenants()
    tenants = {}
    for item in items:
        agencies = [x['portal']['url'] for x in item['franchisor']['agencies']]
        base_portals = [item['admin']['portal']['url'], item['hq']['portal']['url']]
        tenants[item['id']] = [x for x in (base_portals + agencies)]
    return tenants

def get_tenant_db_configs():
    return settings.DATABASES
    # items = get_tenants()
    # DATABASES = {}
    # for item in items:
    #     id = item['id']
    #     tenant_db_config = {
    #         '{}.default'.format(id): item['web_write_elb_conf'],
    #         '{}.masterdb'.format(id): item['web_write_elb_conf'],
    #         '{}.masterdb2'.format(id): item['web_write_elb_conf'],
    #         '{}.workerslavedb1'.format(id): item['worker_read_elb_conf'],
    #         '{}.slavedb1'.format(id): item['worker_read_elb_conf'],
    #         '{}.slavedb2'.format(id): item['worker_read_elb_conf'],
    #         '{}.slavedb3'.format(id): item['worker_read_elb_conf'],
    #         '{}.slavedb4'.format(id): item['worker_read_elb_conf'],
    #         '{}.api-slave-db1'.format(id): item['reporting_read_elb_conf']
    #     }
    #     DATABASES.update(tenant_db_config)
    # return DATABASES

def get_env(name, default=None, prefix='CC_'):
    import os
    val = os.environ.get(prefix + name, default)
    try:
        return eval(val) # this is a potential security risk
    except:
        return val


if 'multidb.MultiTenantMasterPinningSlaveRouter' in db_router:
    TENANT_SERVICE_API_KEY = settings.TENANT_SERVICE_API_KEY #get_env(name="TENANT_SERVICE_API_KEY",default="da2-yhem3pedtjfmnhrrjeam4fdxwa")
    TENANT_SERVICE_API_ENDPOINT = settings.TENANT_SERVICE_API_ENDPOINT #get_env(name="TENANT_SERVICE_API_ENDPOINT",default="https://ednpt77lq5bnndhvkzf4lfwkme.appsync-api.us-west-2.amazonaws.com/graphql")
    TENANT_LOG_MODE = settings.TENANT_LOG_MODE #get_env(name="TENANT_LOG_MODE", default="DEBUG_TURNED_OFF")
    TENANT_DB_CONFIGS = {}
    TENANT_CONFIG = settings.TENANT_CONFIGS #get_tenant_url_mappings()
    TENANT_DB = settings.TENANT_DB_CONFIGS #get_tenant_db_configs()

def print_with_thread_details(event_name, db_name, hints=None):
    if (settings.TENANT_LOG_MODE == "DEBUG"):
        subdomain = '--'
        thread_id = '--'
        try:
            current_thread = threading.current_thread().__dict__
            subdomain = current_thread.get('subdomain')
            thread_id = threading.current_thread().__name__
        except:
            pass
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


# print("router tenant url mappings " + str(TENANT_CONFIG))
# print("router db config " + str(TENANT_DB))