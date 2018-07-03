# A Django settings module to support the tests

SECRET_KEY = 'dummy'
ROOT_URLCONF = 'multidb.tests'

INSTALLED_APPS = (
    'multidb',
)

MIDDLEWARE_CLASSES = (
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware'
)

# The default database should point to the master.
DATABASES = {
    'default': {
        'NAME': 'master',
        'ENGINE': 'django.db.backends.sqlite3',
    },
    'slave': {
        'NAME': 'slave',
        'ENGINE': 'django.db.backends.sqlite3',
    },
}

SLAVE_DATABASES = ['slave']

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}
