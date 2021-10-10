"""
This is a setup.py script generated by py2applet

Usage:
    python setup.py py2app
"""

import time

from setuptools import setup

from app.res.const import Const

APP = ['__main__.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': True,
    'iconfile': 'app/res/icon.icns',
    'plist': {
        'CFBundleName': Const.app_name,
        'CFBundleDisplayName': Const.app_name,
        'CFBundleGetInfoString': Const.github_page,
        'CFBundleIdentifier': Const.app_name,
        'CFBundleVersion': Const.version,
        'CFBundleShortVersionString': Const.version,
        'NSHumanReadableCopyright': "Copyright © %d, %s, All Rights Reserved" % (
        time.localtime().tm_year, Const.author),
        'LSUIElement': True,
    }
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app', 'rumps', 'requests'],
)
