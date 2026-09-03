"""Compatibility launcher for the cross-instance share-link live check.

``python live_share_link_check.py [--skip-compose] [--cleanup]`` is exactly
``python live_check.py share-links [--skip-compose] [--cleanup]`` — the
implementation now lives in ``live_check.py`` (see its module docstring).
"""

import sys

import live_check


if __name__ == "__main__":
    sys.exit(live_check.main(["share-links", *sys.argv[1:]]))
