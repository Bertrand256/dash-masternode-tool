#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2021-05

from PyQt5.QtWidgets import QWidget


class WidgetTemplate(QWidget):
    def __init__(self, parent):
        QWidget.__init__(self, parent=parent)
        self.setupUi(self)

    def setupUi(self, dlg):
        WidgetTemplate.setupUi(self, self)
        WidgetTemplate.setObjectName("WidgetTemplate")
        WidgetTemplate.resize(640, 300)
