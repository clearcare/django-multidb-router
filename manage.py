import os
import sys
import time

from django.utils import autoreload

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "multidb.test_settings")
    import multidb
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)