#!/usr/bin/python3
# -*- coding: utf-8 -*-
import os
import sys
import PyQt5.QtWidgets as qwi
from PyQt5.QtGui import QIcon
from src import wnd_main


if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        app_path = base_path = sys._MEIPASS
    else:
        app_path = os.path.dirname(__file__)

    app = qwi.QApplication(sys.argv)
    window = qwi.QMainWindow()
    ui = wnd_main.Ui_MainWindow(app_path)
    ui.setupUi(window)
    window.show()

    try:
        ico_path = os.path.join(app_path, 'img', 'dmt.ico')
        if os.path.exists(ico_path):
            app_icon = QIcon(ico_path)
            app.setWindowIcon(app_icon)
    except:
        pass
    sys.exit(app.exec_())

