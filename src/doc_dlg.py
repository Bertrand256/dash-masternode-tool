#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-01

from PyQt5.QtCore import pyqtSlot
from PyQt5.QtWidgets import QDialog, QLayout
from ui import ui_doc_dlg
from wnd_utils import WndUtils


class DocDlg(QDialog, ui_doc_dlg.Ui_DocDlg, WndUtils):
    def __init__(self, parent, doc_text, window_title=None):
        QDialog.__init__(self, parent)
        ui_doc_dlg.Ui_DocDlg.__init__(self)
        WndUtils.__init__(self)
        self.doc_text = doc_text
        self.window_title = window_title
        self.setupUi()

    def setupUi(self):
        ui_doc_dlg.Ui_DocDlg.setupUi(self, self)
        self.setWindowTitle(self.window_title)
        # self.textMain.viewport().setAutoFillBackground(False)
        self.textMain.setHtml(self.doc_text)

    @pyqtSlot(bool)
    def on_btnClose_clicked(self):
        self.close()


def show_doc_dlg(parent, doc_text, window_title=None):
    ui = DocDlg(parent, doc_text, window_title)
    ui.exec_()