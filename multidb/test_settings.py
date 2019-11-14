def get_env(name, default=None, prefix='CC_'):
    import os
    val = os.environ.get(prefix + name, default)
    try:
        return eval(val) # this is a potential security risk
    except:
        return val

def get_tenant_dbs():
    # hardcoded for now. But in reality, need to bring it from some cache db
    # config per tenant cluster
    tenant_0_db_config = {
            'ENGINE': 'django.db.backends.sqlite3',
            'HOST': get_env('DATABASE_HOST', 'cc_db'),
            'NAME': get_env('DATABASE_NAME', 'clearcare'),
            'PASSWORD': get_env('DATABASE_PASSWORD', 'postgres'), #Iris
            'PORT': get_env('DATABASE_PORT', 5432),
            'USER': get_env('DATABASE_USER', 'postgres'),
        }
    tenant_1_db_config = {
            'ENGINE': 'django.db.backends.sqlite3',
            'HOST': 'clearcare-aurora-dev-cluster.cluster-cytjqv3mkbyk.us-west-2.rds.amazonaws.com',
            'NAME': get_env('DATABASE_NAME', 'clearcare'),
            'PASSWORD': get_env('DATABASE_PASSWORD', 'postgres'), #Iris
            'PORT': get_env('DATABASE_PORT', 5432),
            'USER': get_env('DATABASE_USER', 'postgres'),
        }
    return {
            'default': tenant_0_db_config,
            '0.default': tenant_0_db_config,
            '0.masterdb': tenant_0_db_config,
            '0.masterdb2': tenant_0_db_config,
            '0.workerslavedb1': tenant_0_db_config,
            '0.slavedb1': tenant_0_db_config,
            '0.slavedb2': tenant_0_db_config,
            '0.slavedb3': tenant_0_db_config,
            '0.slavedb4': tenant_0_db_config,
            '0.api-slave-db1': tenant_0_db_config,
            # '1.default': tenant_1_db_config,
            # '1.masterdb': tenant_1_db_config,
            # '1.masterdb2': tenant_1_db_config,
            # '1.workerslavedb1': tenant_1_db_config,
            # '1.slavedb1': tenant_1_db_config,
            # '1.slavedb2': tenant_1_db_config,
            # '1.slavedb3': tenant_1_db_config,
            # '1.slavedb4': tenant_1_db_config,
            # '1.api-slave-db1': tenant_1_db_config,
        }

DATABASES = get_tenant_dbs()

DATABASE_ROUTERS = ('multidb.MultiTenantPinningMasterSlaveRouter',)

ROOT_URLCONF = __name__

SLAVE_DATABASES = ['default']

SECRET_KEY = '!q9)w@f2gf1+9z2bf75!avfhslm7baifav-(47ivv)x@f(r7sg'

TENANT_SERVICE_API_KEY = "da2-yhem3pedtjfmnhrrjeam4fdxwa"
TENANT_SERVICE_API_ENDPOINT = "https://ednpt77lq5bnndhvkzf4lfwkme.appsync-api.us-west-2.amazonaws.com/graphql"
TENANT_LOG_MODE = "DEBUG"