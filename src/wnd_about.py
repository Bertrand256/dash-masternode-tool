#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

import sys
from PyQt5.QtCore import QSize
from PyQt5.QtGui import QPixmap
from src import wnd_about_base
from src.wnd_utils import WndUtils
import os


class Ui_DialogAbout(wnd_about_base.Ui_DialogAbout, WndUtils):
    def __init__(self, app_path, app_version_str):
        super().__init__()
        self.app_path = app_path
        self.app_version_str = app_version_str
        self.window = None

    def setupUi(self, window):
        self.window = window
        wnd_about_base.Ui_DialogAbout.setupUi(self, window)
        window.setWindowTitle("About")
        img = QPixmap(os.path.join(self.app_path, "img/dmt.png"))
        img = img.scaled(QSize(64, 64))
        self.lblImage.setPixmap(img)
        self.btnClose.clicked.connect(self.closeClicked)
        self.lblAppName.setText('Dash Masternode Tool ' + self.app_version_str)
        self.textAbout.setOpenExternalLinks(True)
        self.textAbout.viewport().setAutoFillBackground(False)
        if sys.platform == 'win32':
            self.window.resize(600, 310)
            self.textAbout.setHtml(self.textAbout.toHtml().replace('font-size:11pt', 'font-size:10pt'))
            self.textAbout.setHtml(self.textAbout.toHtml().replace('font-size:9pt', 'font-size:8pt'))
        elif sys.platform == 'darwin':
            # self.window.resize(600, 290)
            self.textAbout.setHtml(self.textAbout.toHtml().replace('font-size:11pt', 'font-size:13pt'))
        pass

    def closeClicked(self):
        self.window.accept()
