#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-12
import bitcoin
import functools
from PyQt5.QtCore import QSize, pyqtSlot, QAbstractTableModel, QVariant, Qt, QPoint
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QDialog, QMenu, QApplication

from dash_utils import bip32_path_string_to_n, pubkey_to_address
from ui import ui_initialize_hw_dlg
from wnd_utils import WndUtils
from hw_intf import *
from mnemonic import Mnemonic


class HwInitializeDlg(QDialog, ui_initialize_hw_dlg.Ui_HwInitializeDlg, WndUtils):
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        ui_initialize_hw_dlg.Ui_HwInitializeDlg.__init__(self)
        WndUtils.__init__(self, parent.config)
        self.main_ui = parent
        self.current_step = 0
        self.action_type = None  # numeric value represting the action type from the first step
        self.word_count = 24
        self.mnemonic_words = [""] * 24
        self.grid_model = MnemonicModel(self, self.mnemonic_words)
        self.address_preview_model = PreviewAddressesModel(self)
        self.mnemonic = Mnemonic('english')
        self.step3_details_visible = False
        self.setupUi()

    def setupUi(self):
        ui_initialize_hw_dlg.Ui_HwInitializeDlg.setupUi(self, self)
        self.setWindowTitle("Hardware wallet initialization")
        self.viewMnemonic.setModel(self.grid_model)
        self.viewMnemonic.setColumnWidth(0, 30)
        self.viewMnemonic.verticalHeader().setDefaultSectionSize(
            self.viewMnemonic.verticalHeader().fontMetrics().height() + 6)
        self.set_word_count(self.word_count)
        self.rbWordsCount24.toggled.connect(functools.partial(self.set_word_count, 24))
        self.rbWordsCount18.toggled.connect(functools.partial(self.set_word_count, 18))
        self.rbWordsCount12.toggled.connect(functools.partial(self.set_word_count, 12))
        self.tabSteps.setCurrentIndex(0)
        self.btnBack.setEnabled(False)
        self.viewAddresses.setModel(self.address_preview_model)
        self.viewAddresses.setColumnWidth(0, 150)
        self.viewAddresses.verticalHeader().setDefaultSectionSize(
            self.viewAddresses.verticalHeader().fontMetrics().height() + 6)

        # words grid context menu
        self.popMenuWords = QMenu(self)
        # copy action
        self.actCopyWords = self.popMenuWords.addAction("\u274f Copy all words")
        self.actCopyWords.triggered.connect(self.on_actCopyWords_triggered)
        self.actCopyWords.setShortcut(QKeySequence("Ctrl+C"))
        # paste action
        self.actPasteWords = self.popMenuWords.addAction("\u23ce Paste")
        self.actPasteWords.triggered.connect(self.on_actPasteWords_triggered)
        self.actPasteWords.setShortcut(QKeySequence("Ctrl+V"))

    @pyqtSlot(bool)
    def on_btnNext_clicked(self, clicked):
        error = False
        if self.current_step == 0:
            # step: choose the action type
            if self.rbActRecoverMnemonicWords.isChecked():
                self.action_type = 0
            elif self.rbActRecoverHexEntropy.isChecked():
                self.action_type = 1
            elif self.rbActInitializeNewSeed.isChecked():
                self.action_type = 2
            elif self.rbActWipeDevice.isChecked():
                self.action_type = 3
            else:
                error = True

        elif self.current_step == 1:
            if self.action_type == 1:
                # recovery from hex entropy
                ent_str = self.edtHexEntropy.text()
                try:
                    entropy = bytes.fromhex(ent_str)
                    if len(entropy) not in (32, 24, 16):
                        self.warnMsg('The entropy hex-string can only have 16, 24 or 32 bytes.')
                        error = True
                    else:
                        words = self.entropy_to_mnemonic(entropy)
                        self.set_words(words)
                        self.set_word_count(len(words))
                except Exception as e:
                    self.warnMsg(str(e))
                    error = True
            elif self.action_type == 2:
                # generate a new seed and initialize device
                ent_len = {
                    24: 32,
                    18: 24,
                    12: 16}.get(self.word_count)
                if ent_len:
                    entropy = get_entropy(self.main_ui, ent_len)
                    words = self.entropy_to_mnemonic(entropy)
                    self.set_words(words)
                    self.set_word_count(len(words))
                else:
                    raise Exception("Internal error: invalid seed length.")

        elif self.current_step == 2:
            if self.action_type == 0:
                # verify all the seed words entered by the user
                wl = self.mnemonic.wordlist
                invalid_indexes = []
                for idx, word in enumerate(self.get_cur_mnemonic_words()):
                    if not word:
                        self.errorMsg('Cannot continue: empty word #%s.' % str(idx+1))
                        error = True
                        break
                    if word not in wl:
                        error = True
                        invalid_indexes.append(idx)

        elif self.current_step == 3:
            if self.action_type in (0,1,2):
                use_pin = self.chbStep3UsePIN.isChecked()
                use_pass = self.chbStep3UsePassphrase.isChecked()
                mnem = ' '.join(self.get_cur_mnemonic_words())
                label = self.edtHWLabel.text()
                if not label:
                    label = self.edtHWLabel.placeholderText()
                if not label:
                    label = 'My device'
                pin = ''
                if use_pin:
                    pin = self.main_ui.askForPinCallback('Enter new PIN', hide_numbers=False)
                    pin2 = self.main_ui.askForPinCallback('Enter new PIN again', hide_numbers=False)
                    if pin != pin2:
                        self.errorMsg('PIN does not match')
                load_device_by_mnemonic(self.main_ui, mnem, pin, use_pass, label)
                pass


        else:
            raise Exception("Internal error: invalid step.")
        # todo: check if max step
        if not error:
            self.current_step += 1
            self.tabSteps.setCurrentIndex(self.current_step)
            self.prepare_page()
            self.btnBack.setEnabled(True)

    @pyqtSlot(bool)
    def on_btnBack_clicked(self, clicked):
        if self.current_step > 0:

            if self.current_step == 2:
                if self.action_type in (1,2):
                    # clear the generated words
                    for idx in range(len(self.mnemonic_words)):
                        self.mnemonic_words[idx] = ''

            self.current_step -= 1
            self.tabSteps.setCurrentIndex(self.current_step)
            if self.current_step == 0:
                self.btnBack.setEnabled(False)

    def prepare_page(self):
        # display/hide controls on the current page (step), depending on the options set in prevous steps
        if self.current_step == 1:
            # Step 2
            if self.action_type == 0:
                # recovery based on mnemonic words
                self.gbNumberOfMnemonicWords.setVisible(True)
                self.lblStep1MnemonicWords.setVisible(True)
                self.lblStep1HexEntropy.setVisible(False)
                self.edtHexEntropy.setVisible(False)
                self.lblStep1MnemonicWords.setText('<b>Number of words in your recovery seed</b>')
            elif self.action_type == 1:
                # recovery based on hexadecimal entropy
                self.gbNumberOfMnemonicWords.setVisible(False)
                self.lblStep1MnemonicWords.setVisible(False)
                self.lblStep1HexEntropy.setVisible(True)
                self.edtHexEntropy.setVisible(True)
            elif self.action_type == 2:
                # recovery based on hexadecimal entropy
                self.gbNumberOfMnemonicWords.setVisible(True)
                self.lblStep1MnemonicWords.setVisible(True)
                self.lblStep1HexEntropy.setVisible(False)
                self.edtHexEntropy.setVisible(False)
                self.lblStep1MnemonicWords.setText('<b>Number of words to be generated (the higher the better)</b>')
                self.lblStep1Message1.setText('<span style="">Click the &lt;Continue&gt; button to generate new words of your recovery seed using your hardware wallet\'s random-number generator.</span>')
                self.lblStep1Message1.setVisible(True)
                self.lblStep1Message2.setVisible(False)

        elif self.current_step == 2:
            if self.action_type == 0:
                self.grid_model.set_read_only(False)
                self.lblStep2Title.setText('<b>Enter your recovery seed words</b>')
                self.viewMnemonic.setStyleSheet('')
            elif self.action_type == 1:
                self.grid_model.set_read_only(True)
                self.lblStep2Title.setText('<b>Below are the seed words for the provided hexadecimal entropy</b>')
                self.viewMnemonic.setStyleSheet('background-color:#e6e6e6')
            elif self.action_type == 2:
                self.grid_model.set_read_only(True)
                self.lblStep2Title.setText(
                    '<b>Below are the newly generated words of your recovery seed<br>'
                    '<span style="color:red"><b>Important!!!</b> Please, write them down and keep them safe. '
                    'If you lose them, you will lose access to your funds.</span>')
                self.viewMnemonic.setStyleSheet('background-color:#e6e6e6')

        elif self.current_step == 3:
            if self.mnemonic:
                ws = self.get_cur_mnemonic_words()
                ent = self.mnemonic.to_entropy(ws)
                self.lblStep3Message1.setText('Your recovery seed\'s entropy: ' + ent.hex())
                self.update_controls_state()

    def update_controls_state(self):
        if self.current_step == 3:
            self.wdgStep3Details.setVisible(self.step3_details_visible)
            if self.step3_details_visible:
                self.btnStep3Details.setText('Hide preview')
            else:
                self.btnStep3Details.setText('Preview addresses')

    @pyqtSlot(bool)
    def on_btnCancel_clicked(self):
        self.close()

    def connect_hardware_wallet(self):
        return self.main_ui.connectHardwareWallet()

    def set_word_count(self, word_count, checked=True):
        if checked:
            self.word_count = word_count
            self.grid_model.set_words_count(word_count)

    @pyqtSlot(bool)
    def on_btnWipeDevice_clicked(self, clicked):
        if self.connect_hardware_wallet():
            wipe_device(self.main_ui)

    @pyqtSlot(bool)
    def on_btnGenerateSeed_clicked(self, clicked):
        if self.connect_hardware_wallet():
            ent_len = {
                24: 32,
                18: 24,
                12: 16}.get(self.word_count)
            if ent_len:
                entropy = get_entropy(self.main_ui, ent_len)
                words = self.entropy_to_mnemonic(entropy)
                if len(words) != self.word_count:
                    raise Exception('Word count inconsistency')
                else:
                    self.set_words(words)
            else:
                raise Exception('Invalid word count.')

    def entropy_to_mnemonic(self, entropy):
        words = self.mnemonic.to_mnemonic(entropy)
        return words.split()

    def set_words(self, words):
        for idx, word in enumerate(words):
            if idx < len(self.mnemonic_words):
                self.mnemonic_words[idx] = word

    @pyqtSlot(QPoint)
    def on_viewMnemonic_customContextMenuRequested(self, point):
        self.popMenuWords.exec_(self.viewMnemonic.mapToGlobal(point))

    def get_cur_mnemonic_words(self):
        ws = []
        for idx, w in enumerate(self.mnemonic_words):
            if idx >= self.word_count:
                break
            ws.append(w)
        return ws

    def on_actCopyWords_triggered(self, checked):
        ws = self.get_cur_mnemonic_words()
        ws_str = '\n'.join(ws)
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(ws_str)

    def on_actPasteWords_triggered(self, checked):
        clipboard = QApplication.clipboard()
        if clipboard:
            ws_str = clipboard.text()
            if isinstance(ws_str, str):
                ws_str = ws_str.replace('\n',' ').replace('\r',' ')
                ws = ws_str.split()
                for idx, w in enumerate(ws):
                    if idx >= self.word_count:
                        break
                    self.mnemonic_words[idx] = w
                self.grid_model.refresh_view()

    @pyqtSlot(bool)
    def on_btnStep3Details_clicked(self):
        self.step3_details_visible = not self.step3_details_visible
        self.update_controls_state()

    @staticmethod
    def bip32_descend(*args):
        if len(args) == 2 and isinstance(args[1], list):
            key, path = args
        else:
            key, path = args[0], map(int, args[1:])
        for p in path:
            key = bitcoin.bip32_ckd(key, p)
        return key

    def get_bip32_private_key(self, path_n, master_key):
        priv = self.bip32_descend(master_key, path_n)
        ret = bitcoin.bip32_extract_key(priv)
        return ret

    def refresh_adresses_preview(self):
        if self.mnemonic:
            bip32_path = self.edtStep3Bip32Path.text()
            passphrase = self.edtStep3Passphrase.text()
            passphrase = self.mnemonic.normalize_string(passphrase)
            mnem_str = ' '.join(self.get_cur_mnemonic_words())
            bip32_seed = self.mnemonic.to_seed(mnem_str, passphrase)
            bip32_master_key = bitcoin.bip32_master_key(bip32_seed)
            bip32_path_n = bip32_path_string_to_n(bip32_path)
            if len(bip32_path_n) > 0:
                last_idx = bip32_path_n[-1]
                addresses = []
                for idx in range(10):
                    bip32_path_n[-1] = last_idx + idx
                    pk = self.get_bip32_private_key(bip32_path_n, bip32_master_key)
                    pubkey = bitcoin.privkey_to_pubkey(pk)
                    addr = pubkey_to_address(pubkey)
                    path_str = bip32_path_n_to_string(bip32_path_n)
                    addresses.append((path_str, addr))
                self.address_preview_model.apply_addresses(addresses)
                self.address_preview_model.refresh_view()
                self.viewAddresses.resizeColumnsToContents()

    @pyqtSlot(bool)
    def on_btnRefreshAddressesPreview_clicked(self, check):
        self.refresh_adresses_preview()

    @pyqtSlot()
    def on_edtStep3Passphrase_returnPressed(self):
        self.refresh_adresses_preview()

    @pyqtSlot()
    def on_edtStep3Bip32Path_returnPressed(self):
        self.refresh_adresses_preview()



class MnemonicModel(QAbstractTableModel):
    def __init__(self, parent, mnemonic_word_list):
        QAbstractTableModel.__init__(self, parent)
        self.parent = parent
        self.mnemonic_word_list = mnemonic_word_list
        self.words_count = 24
        self.read_only = False
        self.columns = [
            "#",
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
        return self.words_count

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
        if row_idx >= 0 and row_idx < self.words_count and row_idx < len(self.mnemonic_word_list):
            self.mnemonic_word_list[row_idx] = data
        return True

    def flags(self, index):
        col_idx = index.column()
        if col_idx == 1:
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
                        return str(row_idx + 1)
                    elif col_idx == 1:
                        if row_idx >= 0 and row_idx < self.words_count and row_idx < len(self.mnemonic_word_list):
                            return self.mnemonic_word_list[row_idx]
                elif role == Qt.ForegroundRole:
                    pass

                elif role == Qt.BackgroundRole:
                    pass
                elif role == Qt.TextAlignmentRole:
                    pass
                elif role == Qt.FontRole:
                    pass
        return QVariant()


class PreviewAddressesModel(QAbstractTableModel):
    def __init__(self, parent):
        QAbstractTableModel.__init__(self, parent)
        self.columns = [
            "Path",
            'Address'
        ]
        self.addresses = []  # list of tuples: bip32 path, dash address

    def refresh_view(self):
        self.beginResetModel()
        self.endResetModel()

    def columnCount(self, parent=None, *args, **kwargs):
        return len(self.columns)

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.addresses)

    def apply_addresses(self, addresses):
        self.addresses.clear()
        for a in addresses:
            self.addresses.append((a[0], a[1]))

    def headerData(self, section, orientation, role=None):
        if role != 0:
            return QVariant()
        if orientation == 0x1:
            if section < len(self.columns):
                return self.columns[section]
            return ''
        else:
            return '  '

    def flags(self, index):
        col_idx = index.column()
        if col_idx == 1:
            ret = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        else:
            ret = Qt.ItemIsEnabled
        return ret

    def data(self, index, role=None):
        if index.isValid():
            col_idx = index.column()
            row_idx = index.row()
            if col_idx < len(self.columns) and row_idx < len(self.addresses):
                if role in (Qt.DisplayRole, Qt.EditRole):
                    return str(self.addresses[row_idx][col_idx])
                elif role == Qt.ForegroundRole:
                    pass
                elif role == Qt.BackgroundRole:
                    pass
                elif role == Qt.TextAlignmentRole:
                    pass
                elif role == Qt.FontRole:
                    pass
        return QVariant()
