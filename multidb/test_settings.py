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
            'default-0': tenant_0_db_config,
            'masterdb-0': tenant_0_db_config,
            'masterdb2-0': tenant_0_db_config,
            #'workerslavedb1-0': tenant_0_db_config,
            'slavedb1-0': tenant_0_db_config,
            # 'slavedb2-0': tenant_0_db_config,
            # 'slavedb3-0': tenant_0_db_config,
            # 'slavedb4-0': tenant_0_db_config,
            # 'api-slave-db1-0': tenant_0_db_config,
            'default-1': tenant_1_db_config,
            'masterdb-1': tenant_1_db_config,
            'masterdb2-1': tenant_1_db_config,
            'workerslavedb1-1': tenant_1_db_config,
            #'slavedb1-1': tenant_1_db_config,
            # 'slavedb2-1': tenant_1_db_config,
            # 'slavedb3-1': tenant_1_db_config,
            # 'slavedb4-1': tenant_1_db_config,
            # 'api-slave-db1-1': tenant_1_db_config,
        }

DATABASES = get_tenant_dbs()

ROOT_URLCONF = __name__

SECRET_KEY = '!q9)w@f2gf1+9z2bf75!avfhslm7baifav-(47ivv)x@f(r7sg'

TENANT_SERVICE_API_KEY = "da2-yhem3pedtjfmnhrrjeam4fdxwa"
TENANT_SERVICE_API_ENDPOINT = "https://ednpt77lq5bnndhvkzf4lfwkme.appsync-api.us-west-2.amazonaws.com/graphql"