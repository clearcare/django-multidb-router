from django.conf import settings

from appconf import AppConf


class MultidbRouterConf(AppConf):
    PINNING_VIEWS = ()
    PINNING_COOKIE = 'multidb_pin_writes'
    PINNING_SECONDS = 15
    COOKIELESS_COOKIE = 'multidb_use_cookies'
    COOKIELESS_CACHE = None
