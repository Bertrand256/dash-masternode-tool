#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QPainter, QBrush, QColor, QPen
from PyQt5.QtWidgets import QMessageBox, QWidget
import math


class WndUtils:
    def __init__(self):
        pass

    @staticmethod
    def errorMsg(message):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setText(message)
        msg.exec_()

    @staticmethod
    def warnMsg(message):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setText(message)
        msg.exec_()

    @staticmethod
    def infoMsg(message):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setText(message)
        msg.exec_()

    @staticmethod
    def queryDlg(message, buttons=QMessageBox.Ok | QMessageBox.Cancel, default_button=QMessageBox.Ok,
            icon=QMessageBox.Information):
        msg = QMessageBox()
        msg.setIcon(icon)
        msg.setText(message)
        msg.setStandardButtons(buttons)
        msg.setDefaultButton(default_button)
        return msg.exec_()


class WaitWidget(QWidget):
    def __init__(self, parent=None):

        QWidget.__init__(self, parent)
        palette = QPalette(self.palette())
        palette.setColor(palette.Background, Qt.transparent)
        self.setPalette(palette)
        self.timer_id = None

    def paintEvent(self, event):

        painter = QPainter()
        painter.begin(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(event.rect(), QBrush(QColor(255, 255, 255, 127)))
        painter.setPen(QPen(Qt.NoPen))

        for i in range(6):
            if self.counter % 6 == i:
                painter.setBrush(QBrush(QColor(0, 0, 0)))
            else:
                painter.setBrush(QBrush(QColor(200, 200, 200)))
            painter.drawEllipse(
                self.width() / 2 + 30 * math.cos(2 * math.pi * i / 6.0) - 10,
                self.height() / 2 + 30 * math.sin(2 * math.pi * i / 6.0) - 10,
                20, 20)

        painter.end()

    def showEvent(self, event):

        self.timer_id = self.startTimer(200)
        self.counter = 0

    def timerEvent(self, event):
        self.counter += 1
        self.update()

    def hideEvent(self, event):
        if self.timer_id:
            self.killTimer(self.timer_id)
            self.timer_id = None
