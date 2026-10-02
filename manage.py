#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main() -> None:
    # Production is the default so that a missing variable can never select
    # debug settings. Development sets DJANGO_SETTINGS_MODULE in .env.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "caipo.config.settings.production")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
