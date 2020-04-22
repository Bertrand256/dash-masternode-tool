#!/usr/bin/python3
# -*- coding: utf-8 -*-
import os
import sys
import PyQt5.QtWidgets as qwi
from PyQt5.QtGui import QIcon
import main_dlg
import traceback
import logging

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
                msg = 'An unhandled exception accurred: ' + value.__class__.__name__ + '.'
            except:
                msg = 'An unhandled exception accurred.'
        WndUtils.errorMsg(msg)

    sys.excepthook = my_excepthook

    if getattr(sys, 'frozen', False):
        app_dir = base_path = sys._MEIPASS
    else:
        app_dir = os.path.dirname(__file__)
        path, tail = os.path.split(app_dir)
        if tail == 'src':
            app_dir = path

    app = qwi.QApplication(sys.argv)
    ui = main_dlg.MainWindow(app_dir)
    ui.show()

    try:
        ico_path = os.path.join(app_dir, 'img', 'dmt.ico')
        if os.path.exists(ico_path):
            app_icon = QIcon(ico_path)
            app.setWindowIcon(app_icon)
    except:
        pass

    sys.exit(app.exec_())

