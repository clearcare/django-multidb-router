# A Django settings module to support the tests

SECRET_KEY = 'dummy'
ROOT_URLCONF = 'multidb.tests'

INSTALLED_APPS = (
    'multidb',
)

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
