#!/usr/bin/python3
# -*- coding: utf-8 -*-
import os
import sys

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication
import qdarkstyle

import main_dlg
import traceback
import logging

from app_cache import AppCache
from app_config import AppConfig
from wnd_utils import WndUtils


if __name__ == '__main__':
    def my_excepthook(type, value, tback):
        print('=========================')
        traceback.print_tb(tback)
        for fh in logging.RootLogger.root.handlers:
            if isinstance(fh, logging.FileHandler):
                traceback.print_exception(type, value, tback, file=fh.stream)
                fh.flush()
        msg = str(value)
        if not msg:
            try:
                msg = 'An unhandled exception occurred: ' + value.__class__.__name__ + '.'
            except:
                msg = 'An unhandled exception occurred.'
        WndUtils.error_msg(msg)

    sys.excepthook = my_excepthook

    if getattr(sys, 'frozen', False):
        app_dir = base_path = sys._MEIPASS
    else:
        app_dir = os.path.dirname(__file__)
        path, tail = os.path.split(app_dir)
        if tail == 'src':
            app_dir = path

    os.environ['QT_API'] = 'pyqt5'

    app = QApplication(sys.argv)
    ui_dark_mode_activated = False

    try:
        # check in the user configured the ui dark mode in the default global settings; if so, apply it here
        # (before GUI is instantiated) to avoid flickering caused by switching from the default UI theme
        config_file = AppConfig.get_default_global_settings_file_name()
        if config_file and os.path.exists(config_file):
            cache = AppCache('0.0.0')
            cache.set_file_name(config_file)
            dark_mode = cache.get_value('UI_USE_DARK_MODE', False, bool)
            if dark_mode:
                app.setStyleSheet(qdarkstyle.load_stylesheet())
                ui_dark_mode_activated = True
            del cache

    except Exception:
        pass

    ui = main_dlg.MainWindow(app_dir, ui_dark_mode_activated)
    ui.show()

    try:
        ico_path = os.path.join(app_dir, 'img', 'dmt.ico')
        if os.path.exists(ico_path):
            app_icon = QIcon(ico_path)
            app.setWindowIcon(app_icon)
    except:
        pass

    sys.exit(app.exec_())

