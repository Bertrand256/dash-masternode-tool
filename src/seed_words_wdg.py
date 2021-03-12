#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2021-04

from typing import Optional, List

from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import QVariant, QAbstractTableModel, pyqtSlot, QPoint, QTimer, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QWidget, QMenu, QShortcut, QApplication, QLabel
from mnemonic import Mnemonic

from wnd_utils import WndUtils


class SeedWordsWdg(QWidget):

    def __init__(self, parent):
        QWidget.__init__(self, parent=parent)
        self.layout_main: Optional[QtWidgets.QVBoxLayout] = None
        self.spacer: Optional[QtWidgets.QSpacerItem] = None
        self.word_count: int = 24
        self.mnemonic_words: List[str] = [""] * 24
        self.mnemonic = Mnemonic('english')
        self.grid_model = MnemonicModel(self, self.mnemonic_words, self.mnemonic.wordlist)
        self.popMenuWords: Optional[QMenu] = None
        self.setupUi(self)

    def setupUi(self, dlg):
        dlg.setObjectName("SeedWordsWdg")
        self.layout_main = QtWidgets.QVBoxLayout(dlg)
        self.layout_main.setObjectName('layout_main')
        self.layout_main.setContentsMargins(0, 0, 0, 0)
        self.layout_main.setSpacing(3)
        self.layout_main.setObjectName("verticalLayout")

        self.viewMnemonic = QtWidgets.QTableView(self)
        self.viewMnemonic.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.viewMnemonic.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.viewMnemonic.setObjectName("viewMnemonic")
        self.viewMnemonic.horizontalHeader().setVisible(False)
        self.viewMnemonic.horizontalHeader().setStretchLastSection(True)
        self.viewMnemonic.verticalHeader().setVisible(False)
        self.layout_main.addWidget(self.viewMnemonic)

        self.msg = QtWidgets.QLabel(self)
        self.msg.setWordWrap(True)
        self.msg.setObjectName("msg")
        self.msg.setText('You can copy and paste the complete set of seed words into this dialog directly (separated '
                         'by spaces, commas or line breaks).')
        self.layout_main.addWidget(self.msg)

        self.viewMnemonic.verticalHeader().setDefaultSectionSize(
            self.viewMnemonic.verticalHeader().fontMetrics().height() + 6)
        self.viewMnemonic.customContextMenuRequested.connect(self.on_viewMnemonic_customContextMenuRequested)
        # words grid context menu
        self.popMenuWords = QMenu(self)
        # copy action
        self.actCopyWords = self.popMenuWords.addAction("\u274f Copy all words")
        self.actCopyWords.triggered.connect(self.on_copy_seed_words_triggered)
        self.actCopyWords.setShortcut(QKeySequence("Ctrl+C"))  # not working on Mac (used here to display
        # shortcut in menu item
        QShortcut(QKeySequence("Ctrl+C"), self.viewMnemonic).activated.connect(self.on_copy_seed_words_triggered)

        # paste action
        self.act_paste_words = self.popMenuWords.addAction("\u23ce Paste")
        self.act_paste_words.triggered.connect(self.on_paste_seed_words_triggered)
        self.act_paste_words.setShortcut(QKeySequence("Ctrl+V"))
        QShortcut(QKeySequence("Ctrl+V"), self.viewMnemonic).activated.connect(self.on_paste_seed_words_triggered)

    def set_word_count(self, word_count):
        self.word_count = word_count
        self.grid_model.set_words_count(word_count)

        def setup_mnem_view():
            width = self.viewMnemonic.width()
            width = int((width - (2 * 40)) / 2)
            self.viewMnemonic.setModel(self.grid_model)
            self.viewMnemonic.setColumnWidth(0, 40)
            self.viewMnemonic.setColumnWidth(1, width)
            self.viewMnemonic.setColumnWidth(2, 40)

        QTimer.singleShot(10, setup_mnem_view)

    def set_words(self, words):
        for idx, word in enumerate(words):
            if idx < len(self.mnemonic_words):
                self.mnemonic_words[idx] = word

    def get_cur_mnemonic_words(self):
        ws = []
        for idx, w in enumerate(self.mnemonic_words):
            if idx >= self.word_count:
                break
            ws.append(w)
        return ws

    def on_copy_seed_words_triggered(self):
        try:
            ws = self.get_cur_mnemonic_words()
            ws_str = '\n'.join(ws)
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(ws_str)
        except Exception as e:
            self.error_msg(str(e))

    def on_paste_seed_words_triggered(self):
        try:
            clipboard = QApplication.clipboard()
            if clipboard:
                ws_str = clipboard.text()
                if isinstance(ws_str, str):
                    ws_str = ws_str.replace('\n', ' ').replace('\r', ' ').replace(",", ' ')
                    ws = ws_str.split()
                    for idx, w in enumerate(ws):
                        if idx >= self.word_count:
                            break
                        self.mnemonic_words[idx] = w
                    self.grid_model.refresh_view()
        except Exception as e:
            self.error_msg(str(e))

    @pyqtSlot(QPoint)
    def on_viewMnemonic_customContextMenuRequested(self, point):
        try:
            self.popMenuWords.exec_(self.viewMnemonic.mapToGlobal(point))
        except Exception as e:
            self.error_msg(str(e))


class MnemonicModel(QAbstractTableModel):
    def __init__(self, parent, mnemonic_word_list, dictionary_words):
        QAbstractTableModel.__init__(self, parent)
        self.parent = parent
        self.dictionary_words = dictionary_words
        self.mnemonic_word_list = mnemonic_word_list
        self.words_count = 24
        self.read_only = False
        self.columns = [
            "#",
            'Word',
            '#',
            'Word'
        ]

    def set_words_count(self, words_count):
        self.words_count = words_count
        self.refresh_view()

    def refresh_view(self):
        self.beginResetModel()
        self.endResetModel()

    def set_read_only(self, ro):
        self.read_only = ro

    def columnCount(self, parent=None, *args, **kwargs):
        return len(self.columns)

    def rowCount(self, parent=None, *args, **kwargs):
        return self.words_count / 2

    def headerData(self, section, orientation, role=None):
        if role != 0:
            return QVariant()
        if orientation == 0x1:
            if section < len(self.columns):
                return self.columns[section]
            return ''
        else:
            return '  '

    def setData(self, index, data, role=None):
        row_idx = index.row()
        col_idx = index.column()
        if 0 <= row_idx < int(self.words_count / 2):
            if col_idx == 1:
                idx = row_idx
            else:
                idx = row_idx + int(self.words_count / 2)
            self.mnemonic_word_list[idx] = data
        return True

    def flags(self, index):
        col_idx = index.column()
        if col_idx in (1, 3):
            ret = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if not self.read_only:
                ret |= Qt.ItemIsEditable
        else:
            ret = Qt.ItemIsEnabled
        return ret

    def data(self, index, role=None):
        if index.isValid():
            col_idx = index.column()
            row_idx = index.row()
            if col_idx < len(self.columns):
                if role in (Qt.DisplayRole, Qt.EditRole):
                    if col_idx == 0:
                        return str(row_idx + 1) + '.'
                    elif col_idx == 2:
                        return str(int(self.words_count / 2) + row_idx + 1) + '.'
                    elif col_idx == 1:
                        if 0 <= row_idx < int(self.words_count / 2):
                            return self.mnemonic_word_list[row_idx]
                    elif col_idx == 3:
                        if 0 <= row_idx < int(self.words_count / 2):
                            return self.mnemonic_word_list[int(self.words_count / 2) + row_idx]

                elif role == Qt.ForegroundRole:
                    if 0 <= row_idx < int(self.words_count / 2):
                        if col_idx in (0, 1):
                            word_col_idx = 1
                        else:
                            word_col_idx = 3

                        if word_col_idx == 1:
                            word = self.mnemonic_word_list[row_idx]
                        elif word_col_idx == 3 and row_idx < int(self.words_count / 2):
                            word = self.mnemonic_word_list[int(self.words_count / 2) + row_idx]
                        else:
                            return
                        if word and word not in self.dictionary_words:
                            return QtGui.QColor('red')

                elif role == Qt.BackgroundRole:
                    if col_idx in (0, 2):
                        return QtGui.QColor('lightgray')
                elif role == Qt.TextAlignmentRole:
                    if col_idx in (0, 2):
                        return Qt.AlignRight
                elif role == Qt.FontRole:
                    pass

        return QVariant()
