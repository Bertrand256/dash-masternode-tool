#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

import os
import sys

from PyQt5 import QtWidgets
from PyQt5.QtCore import QSize, pyqtSlot
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QDialog

from ui import ui_about_dlg
from wnd_utils import WndUtils, QDetectThemeChange


class AboutDlg(QDialog, QDetectThemeChange, ui_about_dlg.Ui_AboutDlg, WndUtils):
    def __init__(self, parent, app_version_str):
        QDialog.__init__(self, parent)
        ui_about_dlg.Ui_AboutDlg.__init__(self)
        WndUtils.__init__(self, parent.app_config)
        self.app_version_str = app_version_str
        self.setupUi(self)

    def setupUi(self, dialog: QtWidgets.QDialog):
        ui_about_dlg.Ui_AboutDlg.setupUi(self, self)
        self.setWindowTitle("About")
        img = QPixmap(os.path.join(self.app_config.app_dir, "img/dmt.png"))
        img = img.scaled(QSize(64, 64))
        self.lblImage.setPixmap(img)
        self.lblAppName.setText('Dash Masternode Tool ' + self.app_version_str)
        self.textAbout.setOpenExternalLinks(True)
        self.textAbout.viewport().setAutoFillBackground(False)
        if sys.platform == 'win32':
            self.resize(600, 310)
            self.textAbout.setHtml(self.textAbout.toHtml().replace('font-size:11pt', 'font-size:10pt'))
            self.textAbout.setHtml(self.textAbout.toHtml().replace('font-size:9pt', 'font-size:8pt'))
        elif sys.platform == 'darwin':
            self.textAbout.setHtml(self.textAbout.toHtml().replace('font-size:11pt', 'font-size:13pt'))
        elif sys.platform == 'linux':
            self.resize(620, 320)
        self.display_info()

    @pyqtSlot(bool)
    def on_btnClose_clicked(self):
        self.close()

    def onThemeChanged(self):
        self.display_info()

    def display_info(self):
        html = f"""<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0//EN" "http://www.w3.org/TR/REC-html40/strict.dtd">
<html><head><meta name="qrichtext" content="1" /><style type="text/css">
p, li {{ white-space: pre-wrap; }}
</style></head><body style=" font-family:'Arial'; font-size:13pt; font-weight:400; font-style:normal;">
<p style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;">
<span style=" ">This application is free for commercial and non-commercial use.</span></p>
<p style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;">
</p>
<p style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;">
<span style="font-weight:600;">Project's GitHub URL: </span><a href="https://github.com/Bertrand256/dash-masternode-tool">
<span>https://github.com/Bertrand256/dash-masternode-tool</span>
</a></p>
<p style="-qt-paragraph-type:empty; margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; 
-qt-block-indent:0; text-indent:0px; "><br /></p>
<p style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;">
<span style="font-weight:600;">Special thanks to:</span></p>
<ul style="margin-top: 0px; margin-bottom: 0px; margin-left: 0px; margin-right: 0px; -qt-list-indent: 1;">
<li style=" margin-top:4px; margin-bottom:0px; margin-left:0px; margin-right:0px; 
  -qt-block-indent:0; text-indent:0px;">chaeplin for <a href="https://github.com/chaeplin/dashmnb">dashmnb</a>, which inspired the creation of this program</li>
<li style=" " style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; 
  -qt-block-indent:0; text-indent:0px;">Andreas Antonopolous for his excellent technical book <a href="https://shop.oreilly.com/product/0636920049524.do">Mastering Bitcoin</a> (<a href="https://github.com/bitcoinbook/bitcoinbook/tree/develop">GitHub version</a>)</li>
<li style=" " style=" margin-top:0px; margin-bottom:6px; margin-left:0px; margin-right:0px; 
  -qt-block-indent:0; text-indent:0px;">Vitalik Buterin for <a href="https://github.com/vbuterin/pybitcointools">pybitcointools</a> library, which is used in this app</li></ul>
<p style="-qt-paragraph-type:empty; margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; 
  -qt-block-indent:0; text-indent:0px; font-size:8.25pt;"><br /></p>
<p style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;">
  <span style=" font-weight:600;">Author:</span><span style=" "> Bertrand256 (<a href="mailto:blogin@protonmail.com">blogin@protonmail.com</a>)</span>
</p>
</body></html>
"""
        self.textAbout.setHtml(html)