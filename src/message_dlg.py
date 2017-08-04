#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

import sys
from PyQt5.QtCore import QSize, pyqtSlot
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QDialog, QLayout
from ui import ui_message_dlg


class MessageDlg(QDialog, ui_message_dlg.Ui_MessageDlg):
    def __init__(self, parent, message):
        QDialog.__init__(self, parent)
        ui_message_dlg.Ui_MessageDlg.__init__(self)
        self.message = message
        self.setupUi()

    def setupUi(self):
        ui_message_dlg.Ui_MessageDlg.setupUi(self, self)
        self.setWindowTitle("Message")
        self.lblMessage.setText(self.message)
        self.lblMessage.adjustSize()
        self.adjustSize()

    @pyqtSlot()
    def on_buttonBox_accepted(self):
        self.accept()

    @pyqtSlot()
    def on_buttonBox_rejected(self):
        self.reject()

