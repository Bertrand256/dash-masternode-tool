#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

from PyQt5.QtWidgets import QMessageBox


class WndUtils:
    def __init__(self):
        pass

    def errorMsg(self, message):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setText(message)
        msg.exec_()

    def warnMsg(self, message):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setText(message)
        msg.exec_()

    def infoMsg(self, message):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setText(message)
        msg.exec_()

