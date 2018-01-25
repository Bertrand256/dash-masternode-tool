#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-01
from PyQt5.QtCore import pyqtSlot, QStringListModel
from PyQt5.QtWidgets import QDialog, QLayout, QCompleter
from wnd_utils import WndUtils
from ui import ui_hw_word_dlg


class HardwareWalletWordDlg(QDialog, ui_hw_word_dlg.Ui_HardwareWalletWordDlg, WndUtils):
    def __init__(self, message, wordlist):
        QDialog.__init__(self)
        WndUtils.__init__(self, app_config=None)
        ui_hw_word_dlg.Ui_HardwareWalletWordDlg.__init__(self)
        self.wordlist = wordlist
        self.message = message
        self.word = ''
        self.setupUi()

    def setupUi(self):
        ui_hw_word_dlg.Ui_HardwareWalletWordDlg.setupUi(self, self)
        self.setWindowTitle('')
        self.lblWord.setText(self.message)
        self.setWindowTitle('Get word')
        model = QStringListModel()
        model.setStringList(self.wordlist)
        self.completer = QCompleter()
        self.completer.setModel(model)
        self.edtWord.setCompleter(self.completer)
        self.layout().setSizeConstraint(QLayout.SetFixedSize)

    @pyqtSlot(bool)
    def on_btnEnter_clicked(self):
        text = self.edtWord.text()
        if not text:
            WndUtils.errorMsg('Word cannot be empty.')
        elif text not in self.wordlist:
            WndUtils.errorMsg('Word is not in the allowed wordlist.')
        else:
            self.accept()

    def get_word(self):
        return self.edtWord.text()
