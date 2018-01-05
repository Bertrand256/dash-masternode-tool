#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-12
from typing import List, Optional, Tuple
from PyQt5 import QtGui, QtCore
import bitcoin
import functools
import re
from PyQt5.QtCore import QSize, pyqtSlot, QAbstractTableModel, QVariant, Qt, QPoint
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QDialog, QMenu, QApplication, QLineEdit, QAction, QShortcut
from dash_utils import bip32_path_string_to_n, pubkey_to_address
from hw_common import HardwareWalletCancelException
from ui import ui_initialize_hw_dlg
from wnd_utils import WndUtils
from hw_intf import *
from mnemonic import Mnemonic


ACTION_RECOVER_FROM_WORDS_CONV = 1
ACTION_RECOVER_FROM_WORDS_SAFE = 2
ACTION_RECOVER_FROM_ENTROPY = 3
ACTION_INITIALIZE_NEW_SAFE = 4
ACTION_INITIALIZE_NEW_UNSAFE = 5
ACTION_WIPE_DEVICE = 6


STEP_SELECT_DEVICE_TYPE = 0
STEP_SELECT_DEVICE_INSTANCE = 1
STEP_CHOOSE_ACTION = 2
STEP_INPUT_NUMBER_OF_WORDS = 3
STEP_INPUT_ENTROPY = 4
STEP_INPUT_WORDS = 5
STEP_INPUT_HW_OPTIONS = 6
STEP_FINISHED = 7


class HwInitializeDlg(QDialog, ui_initialize_hw_dlg.Ui_HwInitializeDlg, WndUtils):
    def __init__(self, parent) -> None:
        QDialog.__init__(self, parent)
        ui_initialize_hw_dlg.Ui_HwInitializeDlg.__init__(self)
        WndUtils.__init__(self, parent.config)
        self.main_ui = parent
        self.current_step = STEP_SELECT_DEVICE_TYPE
        self.action_type: Optional[int] = None  # numeric value represting the action type from the first step
        self.word_count: int = 24
        self.mnemonic_words: List[str] = [""] * 24
        self.entropy: str = '' # current entropy (entered by the user or converted from mnemonic words)
        self.mnemonic = Mnemonic('english')
        self.grid_model = MnemonicModel(self, self.mnemonic_words, self.mnemonic.wordlist)
        self.address_preview_model = PreviewAddressesModel(self)
        self.hw_options_details_visible = False
        self.step_history: List[int] = []
        self.hw_type: Optional[HWType] = None  # HWType
        self.hw_device_id_selected = Optional[str]  # device id of the hw client selected
        self.hw_device_instances: List[List[str]] = []  # list of 2-element list: hw desc, ref to trezor/keepey/ledger client object
        self.setupUi()

    def setupUi(self):
        ui_initialize_hw_dlg.Ui_HwInitializeDlg.setupUi(self, self)
        self.setWindowTitle("Hardware wallet initialization")

        self.viewMnemonic.verticalHeader().setDefaultSectionSize(
            self.viewMnemonic.verticalHeader().fontMetrics().height() + 6)
        self.set_word_count(self.word_count)

        self.rbDeviceTrezor.toggled.connect(self.on_device_type_changed)
        self.rbDeviceKeepkey.toggled.connect(self.on_device_type_changed)
        self.rbDeviceLedger.toggled.connect(self.on_device_type_changed)

        self.rbActRecoverWordsSafe.toggled.connect(self.on_rbActionType_changed)
        self.rbActRecoverMnemonicWords.toggled.connect(self.on_rbActionType_changed)
        self.rbActRecoverHexEntropy.toggled.connect(self.on_rbActionType_changed)
        self.rbActInitializeNewSeed.toggled.connect(self.on_rbActionType_changed)
        self.rbActWipeDevice.toggled.connect(self.on_rbActionType_changed)

        self.rbWordsCount24.toggled.connect(functools.partial(self.set_word_count, 24))
        self.rbWordsCount18.toggled.connect(functools.partial(self.set_word_count, 18))
        self.rbWordsCount12.toggled.connect(functools.partial(self.set_word_count, 12))

        self.chbHwOptionsUsePIN.toggled.connect(self.update_current_tab)
        self.chbHwOptionsUsePassphrase.toggled.connect(self.update_current_tab)
        self.btnShowPIN.setText("\u29BF")
        self.btnShowPassphrase.setText("\u29BF")
        self.btnShowSecondaryPIN.setText("\u29BF")
        self.btnShowPIN.pressed.connect(functools.partial(self.edtHwOptionsPIN.setEchoMode, QLineEdit.Normal))
        self.btnShowPIN.released.connect(functools.partial(self.edtHwOptionsPIN.setEchoMode, QLineEdit.Password))
        self.btnShowPassphrase.pressed.connect(
            functools.partial(self.edtHwOptionsLedgerPassphrase.setEchoMode, QLineEdit.Normal))
        self.btnShowPassphrase.released.connect(
            functools.partial(self.edtHwOptionsLedgerPassphrase.setEchoMode, QLineEdit.Password))
        self.btnShowSecondaryPIN.pressed.connect(
            functools.partial(self.edtHwOptionsLedgerSecondaryPIN.setEchoMode, QLineEdit.Normal))
        self.btnShowSecondaryPIN.released.connect(
            functools.partial(self.edtHwOptionsLedgerSecondaryPIN.setEchoMode, QLineEdit.Password))

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
        self.actCopyWords.setShortcut(QKeySequence("Ctrl+C"))  # not working on Mac (used here to display
                                                               # shortcut in menu item
        QShortcut(QKeySequence("Ctrl+C"), self.viewMnemonic).activated.connect(self.on_actCopyWords_triggered)

        # paste action
        self.actPasteWords = self.popMenuWords.addAction("\u23ce Paste")
        self.actPasteWords.triggered.connect(self.on_actPasteWords_triggered)
        self.actPasteWords.setShortcut(QKeySequence("Ctrl+V"))
        QShortcut(QKeySequence("Ctrl+V"), self.viewMnemonic).activated.connect(self.on_actPasteWords_triggered)

        self.fraDetails.setVisible(False)
        self.apply_current_step_to_ui()

    def read_action_type_from_ui(self):
        if self.rbActRecoverWordsSafe.isChecked():
            self.action_type = ACTION_RECOVER_FROM_WORDS_SAFE  # recover safe (onlline)
        elif self.rbActRecoverMnemonicWords.isChecked():
            self.action_type = ACTION_RECOVER_FROM_WORDS_CONV  # recover convenient (safe only when offline)
        elif self.rbActRecoverHexEntropy.isChecked():
            self.action_type = ACTION_RECOVER_FROM_ENTROPY
        elif self.rbActInitializeNewSeed.isChecked():
            self.action_type = ACTION_INITIALIZE_NEW_UNSAFE
        elif self.rbActWipeDevice.isChecked():
            self.action_type = ACTION_WIPE_DEVICE
        else:
            raise Exception('Invalid action')

    def apply_current_step_to_ui(self):
        if self.current_step == STEP_SELECT_DEVICE_TYPE:
            idx = 0
        elif self.current_step == STEP_SELECT_DEVICE_INSTANCE:
            idx = 1
        elif self.current_step == STEP_CHOOSE_ACTION:
            idx = 2
        elif self.current_step == STEP_INPUT_NUMBER_OF_WORDS:
            idx = 3
        elif self.current_step == STEP_INPUT_ENTROPY:
            idx = 3
        elif self.current_step == STEP_INPUT_WORDS:
            idx = 4
        elif self.current_step == STEP_INPUT_HW_OPTIONS:
            idx = 5
        elif self.current_step == STEP_FINISHED:
            idx = 6
        else:
            raise Exception('Invalid step.')
        self.tabSteps.setCurrentIndex(idx)

    def set_next_step(self, step):
        if step != self.current_step:
            self.step_history.append(self.current_step)
            self.current_step = step
            self.apply_current_step_to_ui()
            if self.current_step == STEP_FINISHED:
                self.btnNext.setText('Close')

    @pyqtSlot(bool)
    def on_btnNext_clicked(self, clicked):
        error = False
        if self.current_step == STEP_SELECT_DEVICE_TYPE:
            if not self.hw_type:
                self.errorMsg('Select your hardware wallet type.')
                error = True
            else:
                # try to load devices
                self.load_hw_devices()
                cnt = len(self.hw_device_instances)
                if cnt == 0:
                    self.errorMsg('Couldn\'t find any %s devices connected to your computer.' %
                                  HWType.get_desc(self.hw_type))
                    error = True
                elif cnt == 1:
                    # there is only one instance of this device type; go to the actions tab
                    self.hw_device_id_selected = self.hw_device_instances[0][1]
                    self.set_next_step(STEP_CHOOSE_ACTION)
                else:
                    # there is more than one instance of this device type; go to the device instance selection tab
                    self.set_next_step(STEP_SELECT_DEVICE_INSTANCE)

        elif self.current_step == STEP_SELECT_DEVICE_INSTANCE:
            idx = self.cboDeviceInstance.currentIndex()
            if idx >= 0 and idx < len(self.hw_device_instances):
                self.hw_device_id_selected = self.hw_device_instances[idx][1]
                self.set_next_step(STEP_CHOOSE_ACTION)
            else:
                self.errorMsg('No %s device instances.' % HWType.get_desc(self.hw_type))

        elif self.current_step == STEP_CHOOSE_ACTION:
            # step: choose the action type
            self.read_action_type_from_ui()
            if self.action_type == ACTION_RECOVER_FROM_WORDS_CONV:
                self.set_next_step(STEP_INPUT_NUMBER_OF_WORDS)
            elif self.action_type == ACTION_RECOVER_FROM_ENTROPY:
                self.set_next_step(STEP_INPUT_ENTROPY)
            else:
                raise Exception('Not implemented')

        elif self.current_step in (STEP_INPUT_NUMBER_OF_WORDS, STEP_INPUT_ENTROPY):
            if self.action_type == ACTION_RECOVER_FROM_WORDS_CONV:
                self.set_next_step(STEP_INPUT_WORDS)

            elif self.action_type == ACTION_RECOVER_FROM_ENTROPY:
                # recovery from hex entropy
                ent_str = self.edtHexEntropy.text()
                try:
                    entropy = bytes.fromhex(ent_str)
                    if len(entropy) not in (32, 24, 16):
                        self.warnMsg('The entropy hex-string can only have 16, 24 or 32 bytes.')
                        error = True
                    else:
                        self.entropy = entropy
                        words = self.entropy_to_mnemonic(entropy)
                        self.set_words(words)
                        self.set_word_count(len(words))
                    if not error:
                        self.set_next_step(STEP_INPUT_WORDS)
                except Exception as e:
                    self.warnMsg(str(e))
                    error = True
            elif self.action_type == ACTION_INITIALIZE_NEW_UNSAFE:
                # generate a new seed and initialize device
                ent_len = {
                    24: 32,
                    18: 24,
                    12: 16}.get(self.word_count)
                if ent_len:
                    entropy = get_entropy(self.main_ui, ent_len)
                    words = self.entropy_to_mnemonic(entropy)
                    self.entropy = entropy
                    self.set_words(words)
                    self.set_word_count(len(words))
                    self.set_next_step(STEP_INPUT_WORDS)
                else:
                    raise Exception("Internal error: invalid seed length.")

        elif self.current_step == STEP_INPUT_WORDS:
            if self.action_type == ACTION_RECOVER_FROM_WORDS_CONV:
                # verify all the seed words entered by the user
                wl = self.mnemonic.wordlist
                invalid_indexes = []
                suppress_error_message = False
                for idx, word in enumerate(self.get_cur_mnemonic_words()):
                    if not word:
                        self.errorMsg('Cannot continue - enter all words.' )
                        error = True
                        suppress_error_message = True
                        break
                    if word not in wl:
                        error = True
                        invalid_indexes.append(idx)

                if error:
                    # verify the whole word-set entered by the user (checksum)
                    if not suppress_error_message:
                        self.errorMsg('Cannot continue - invalid word(s): %s.' %
                                      ','.join(['#' + str(x+1) for x in invalid_indexes]))
                else:
                    try:
                        ws = self.get_cur_mnemonic_words()
                        self.entropy = self.mnemonic.to_entropy(ws)
                    except Exception as e:
                        error = True
                        if str(e) == 'Failed checksum.':
                            self.errorMsg('Invalid checksum of the provided words. You\'ve probably mistyped some'
                                          ' words or changed their order.')
                        else:
                            self.errorMsg('There was an error in the provided word-list. Error details: ' + str(e))
            elif self.action_type == ACTION_RECOVER_FROM_ENTROPY:
                pass
            else:
                error = True
            if not error:
                self.set_next_step(STEP_INPUT_HW_OPTIONS)

        elif self.current_step == STEP_INPUT_HW_OPTIONS:
            if self.action_type in (ACTION_RECOVER_FROM_WORDS_CONV, ACTION_RECOVER_FROM_ENTROPY):
                use_pin = self.chbHwOptionsUsePIN.isChecked()
                use_passphrase = self.chbHwOptionsUsePassphrase.isChecked()
                mnemonic_words = ' '.join(self.get_cur_mnemonic_words())
                hw_label = self.edtHwOptionsDeviceLabel.text()
                if not hw_label:
                    hw_label = 'My hardware wallet'
                pin = ''
                secondary_pin = ''
                passphrase_for_ledger = ''
                error = False
                if use_pin:
                    pin = self.edtHwOptionsPIN.text()
                    if len(pin) not in (4, 8):
                        self.errorMsg('Invalid PIN length. It can only have 4 or 8 characters.')
                        error = True
                    else:
                        if self.hw_type == HWType.ledger_nano_s:
                            if not re.match("^[0-9]+$", pin):
                                self.errorMsg('Invalid PIN. Allowed characters: 0-9.')
                                error = True
                        else:
                            if not re.match("^[1-9]+$", pin):
                                self.errorMsg('Invalid PIN. Allowed characters: 1-9.')
                                error = True
                if error:
                    self.edtHwOptionsPIN.setFocus()
                else:
                    if self.hw_type == HWType.ledger_nano_s:
                        if use_passphrase:
                            passphrase_for_ledger = self.edtHwOptionsLedgerPassphrase.text()
                            if not passphrase_for_ledger:
                                self.errorMsg('Passphrase for Ledger Nano S device is required if you '
                                              'checked the option to use this feature.')
                                self.edtHwOptionsLedgerPassphrase.setFocus()
                                error = True
                            if not error:
                                # validate secondary PIN
                                secondary_pin = self.edtHwOptionsLedgerSecondaryPIN.text()
                                if not secondary_pin:
                                    self.errorMsg('Secondary PIN is required if you would like to save passphrase '
                                                  'in your Ledger Nano S device.')
                                    self.edtHwOptionsLedgerSecondaryPIN.setFocus()
                                    error = True
                                else:
                                    if len(secondary_pin) not in (4, 8):
                                        self.errorMsg('Invalid secondary PIN length. '
                                                      'It can only have 4 or 8 characters.')
                                        error = True
                                    elif not re.match("^[0-9]+$", secondary_pin):
                                        self.errorMsg('Invalid secondary PIN. Allowed characters: 0-9.')
                                        error = True

                                    if error:
                                        self.edtHwOptionsLedgerSecondaryPIN.setFocus()

                if not error:
                    device_id, finished = load_device_by_mnemonic(
                        self.hw_type, self.hw_device_id_selected, mnemonic_words, pin, use_passphrase, hw_label,
                        passphrase_for_ledger, secondary_pin)

                    if device_id and self.hw_device_id_selected and self.hw_device_id_selected != device_id:
                        # if Trezor or Keepkey is wiped during the initialization then it gets a new device_id
                        # update the deice id in the device combobox and a list associated with it
                        self.hw_device_id_selected = device_id
                        idx = self.cboDeviceInstance.currentIndex()
                        if idx >= 0 and idx < len(self.hw_device_instances):
                            self.hw_device_instances[idx][1] = device_id
                            lbl = hw_label + ' (' + device_id + ')'
                            self.cboDeviceInstance.setItemText(idx, lbl)

                    if not finished:
                        self.warnMsg('Operation cancelled.')
                    else:
                        self.set_next_step(STEP_FINISHED)

        elif self.current_step == STEP_FINISHED:
            self.close()

        else:
            raise Exception("Internal error: invalid step.")

        if not error:
            self.update_current_tab()
            self.btnBack.setEnabled(True)

    @pyqtSlot(bool)
    def on_btnBack_clicked(self, clicked):
        if self.current_step > 0:
            if self.current_step == STEP_FINISHED:
                self.btnNext.setText('Continue')

            if self.current_step == STEP_INPUT_ENTROPY:
                if self.action_type in (ACTION_RECOVER_FROM_ENTROPY,):
                    # clear the generated words
                    for idx in range(len(self.mnemonic_words)):
                        self.mnemonic_words[idx] = ''

            self.current_step = self.step_history.pop()
            self.apply_current_step_to_ui()
            if self.current_step == 0:
                self.btnBack.setEnabled(False)
            self.update_current_tab()

    def update_current_tab(self):
        # display/hide controls on the current page (step), depending on the options set in prevous steps
        if self.current_step == STEP_SELECT_DEVICE_TYPE:
            if self.hw_type == HWType.ledger_nano_s:
                self.lblStepDeviceTypeMessage.setText(
                    '<span><b>Important! Start your Ledger Nano S wallet in recovery mode:</b></span>'
                    '<ol><li>Clear the device by selecting its \'Settings->Device->Reset all\' menu item.</li>'
                    '<li>Power the device off.</li>'
                    '<li>Power the device on while holding its right-hand physical button.</li>'
                    '</ol>')
            else:
                self.lblStepDeviceTypeMessage.setText('')

        elif self.current_step == STEP_SELECT_DEVICE_INSTANCE:

            self.lblStepDeviceInstanceMessage.setText("<b>Select which '%s' device you are going to use.</b>" %
                                                      HWType.get_desc(self.hw_type))

        elif self.current_step == STEP_CHOOSE_ACTION:
            if self.hw_type == HWType.ledger_nano_s:
                # turn off options not applicable for ledger walltes
                self.rbActRecoverWordsSafe.setDisabled(True)
                self.rbActInitializeNewSeed.setDisabled(True)
                self.rbActWipeDevice.setDisabled(True)
                if self.rbActRecoverWordsSafe.isChecked() or self.rbActInitializeNewSeed.isChecked() or \
                   self.rbActWipeDevice.isChecked():
                    self.rbActRecoverMnemonicWords.setChecked(True)
            else:
                self.rbActRecoverWordsSafe.setEnabled(True)
                self.rbActInitializeNewSeed.setEnabled(True)
                self.rbActWipeDevice.setEnabled(True)

            if self.action_type in (ACTION_RECOVER_FROM_WORDS_CONV, ACTION_RECOVER_FROM_ENTROPY):
                self.lblActionTypeMessage.setText(
                    '<span style="color:red;font-weight:bold">Use this feature only on offline systems, ' \
                    'which will never be connected to the Internet.</span>')
            else:
                self.lblActionTypeMessage.setText('')

        elif self.current_step in (STEP_INPUT_NUMBER_OF_WORDS, STEP_INPUT_ENTROPY):

            if self.action_type == ACTION_RECOVER_FROM_WORDS_CONV:
                # recovery based on mnemonic words
                self.gbNumberOfMnemonicWords.setVisible(True)
                self.lblStep1MnemonicWords.setVisible(True)
                self.lblStep1HexEntropy.setVisible(False)
                self.edtHexEntropy.setVisible(False)
                self.lblStep1MnemonicWords.setText('<b>Number of words in your recovery seed</b>')
            elif self.action_type == ACTION_RECOVER_FROM_ENTROPY:
                # recovery based on hexadecimal entropy
                self.gbNumberOfMnemonicWords.setVisible(False)
                self.lblStep1MnemonicWords.setVisible(False)
                self.lblStep1HexEntropy.setVisible(True)
                self.edtHexEntropy.setVisible(True)
            elif self.action_type == ACTION_INITIALIZE_NEW_UNSAFE:
                # initializeing hw with an hexadecimal entropy generated on a device
                self.gbNumberOfMnemonicWords.setVisible(True)
                self.lblStep1MnemonicWords.setVisible(True)
                self.lblStep1HexEntropy.setVisible(False)
                self.edtHexEntropy.setVisible(False)
                self.lblStep1MnemonicWords.setText('<b>Number of words to be generated (the higher the better)</b>')
                self.lblStep1Message1.setText('<span style="">Click the &lt;Continue&gt; button to generate new words of your recovery seed using your hardware wallet\'s random-number generator.</span>')
                self.lblStep1Message1.setVisible(True)
                self.lblStep1Message2.setVisible(False)

        elif self.current_step in (STEP_INPUT_WORDS,):
            self.lblStepWordListMessage2.setVisible(True)
            if self.action_type == ACTION_RECOVER_FROM_WORDS_CONV:
                self.grid_model.set_read_only(False)
                self.lblStepWordListTitle.setText('<b>Enter your recovery seed words</b>')
                self.viewMnemonic.setStyleSheet('')
            elif self.action_type == ACTION_RECOVER_FROM_ENTROPY:
                self.grid_model.set_read_only(True)
                self.lblStepWordListMessage2.setVisible(False)
                self.lblStepWordListTitle.setText('<b>Below are the seed words for the provided hexadecimal entropy</b>')
                self.viewMnemonic.setStyleSheet('background-color:#e6e6e6')
            elif self.action_type == ACTION_INITIALIZE_NEW_UNSAFE:
                self.grid_model.set_read_only(True)
                self.lblStepWordListTitle.setText(
                    '<b>Below are the newly generated words of your recovery seed<br>'
                    '<span style="color:red"><b>Important!!!</b> Please, write them down and keep them safe. '
                    'If you lose them, you will lose access to your funds.</span>')
                self.viewMnemonic.setStyleSheet('background-color:#e6e6e6')

            # estimate words columns widths
            width = self.viewMnemonic.width()
            width = int((width - (2 * 40)) / 2)
            self.viewMnemonic.setModel(self.grid_model)
            self.viewMnemonic.setColumnWidth(0, 40)
            self.viewMnemonic.setColumnWidth(1, width)
            self.viewMnemonic.setColumnWidth(2, 40)

        elif self.current_step == STEP_INPUT_HW_OPTIONS:
            if self.action_type in (ACTION_RECOVER_FROM_WORDS_CONV, ACTION_RECOVER_FROM_ENTROPY,
                                    ACTION_INITIALIZE_NEW_UNSAFE):
                if self.entropy:
                    self.lblHwOptionsMessage1.setText('Your recovery seed\'s entropy: ' + self.entropy.hex())
                self.fraDetails.setVisible(self.hw_options_details_visible)
                if self.hw_options_details_visible:
                    self.btnHwOptionsDetails.setText('Hide preview')
                else:
                    self.btnHwOptionsDetails.setText('Show prewiew')

            self.edtHwOptionsPIN.setVisible(self.chbHwOptionsUsePIN.isChecked())

            if self.hw_type == HWType.ledger_nano_s:
                # for Ledger Nano we have to use PIN
                self.chbHwOptionsUsePIN.setChecked(True)
                self.chbHwOptionsUsePIN.setEnabled(False)
                self.wdgHwOptionsLedger.setVisible(self.chbHwOptionsUsePassphrase.isChecked())
                self.lblHwOptionsDeviceLabel.setVisible(False)
                self.edtHwOptionsDeviceLabel.setVisible(False)
            else:
                self.chbHwOptionsUsePIN.setEnabled(True)
                self.wdgHwOptionsLedger.setVisible(False)
                self.lblHwOptionsDeviceLabel.setVisible(True)
                self.edtHwOptionsDeviceLabel.setVisible(True)

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

    def on_actCopyWords_triggered(self):
        ws = self.get_cur_mnemonic_words()
        ws_str = '\n'.join(ws)
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(ws_str)

    def on_actPasteWords_triggered(self):
        clipboard = QApplication.clipboard()
        if clipboard:
            ws_str = clipboard.text()
            if isinstance(ws_str, str):
                ws_str = ws_str.replace('\n',' ').replace('\r',' ').replace(",",' ')
                ws = ws_str.split()
                for idx, w in enumerate(ws):
                    if idx >= self.word_count:
                        break
                    self.mnemonic_words[idx] = w
                self.grid_model.refresh_view()

    @pyqtSlot(bool)
    def on_btnHwOptionsDetails_clicked(self):
        self.hw_options_details_visible = not self.hw_options_details_visible
        self.update_current_tab()

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
            bip32_path = self.edtHwOptionsBip32Path.text()
            passphrase = self.edtHwOptionsPassphrase.text()
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
    def on_edtHwOptionsPassphrase_returnPressed(self):
        self.refresh_adresses_preview()

    @pyqtSlot()
    def on_edtHwOptionsBip32Path_returnPressed(self):
        self.refresh_adresses_preview()

    def load_hw_devices(self):
        """
        Load all instances of the selected hardware wallet type. If there is more than one, user has to select which
        one he is going to use.
        """
        self.hw_device_instances.clear()
        self.cboDeviceInstance.clear()

        if self.hw_type == HWType.trezor:
            import trezorlib.client as client
            from trezorlib.transport_hid import HidTransport

            for d in HidTransport.enumerate():
                transport = HidTransport(d)
                cl = client.TrezorClient(transport)
                lbl = cl.features.label + ' (' + cl.features.device_id + ')'
                self.hw_device_instances.append([lbl, cl.features.device_id])
                self.cboDeviceInstance.addItem(lbl)
                cl.clear_session()
                cl.close()

        elif self.hw_type == HWType.keepkey:
            import keepkeylib.client as client
            from keepkeylib.transport_hid import HidTransport

            for d in HidTransport.enumerate():
                transport = HidTransport(d)
                cl = client.KeepKeyClient(transport)
                lbl = cl.features.label + ' (' + cl.features.device_id + ')'
                self.hw_device_instances.append([lbl, cl.features.device_id])
                self.cboDeviceInstance.addItem(lbl)
                cl.clear_session()
                cl.close()

        elif self.hw_type == HWType.ledger_nano_s:
            from btchip.btchipComm import getDongle
            from btchip.btchipException import BTChipException
            try:
                dongle = getDongle()
                if dongle:
                    lbl = HWType.get_desc(self.hw_type)
                    self.hw_device_instances.append([lbl, None])
                    self.cboDeviceInstance.addItem(lbl)
                    dongle.close()
                    del dongle
            except BTChipException as e:
                if e.message != 'No dongle found':
                    raise

    @pyqtSlot(bool)
    def on_device_type_changed(self, checked):
        if checked:
            self.read_device_type_from_ui()
            self.update_current_tab()

    def read_device_type_from_ui(self):
        if self.rbDeviceTrezor.isChecked():
            self.hw_type = HWType.trezor
        elif self.rbDeviceKeepkey.isChecked():
            self.hw_type = HWType.keepkey
        elif self.rbDeviceLedger.isChecked():
            self.hw_type = HWType.ledger_nano_s
        else:
            self.hw_type = None

    @pyqtSlot(bool)
    def on_rbActionType_changed(self, checked):
        if checked:
            self.read_action_type_from_ui()
            self.update_current_tab()

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
        if row_idx >= 0 and row_idx < int(self.words_count/2):
            if col_idx == 1:
                idx = row_idx
            else:
                idx = row_idx + int(self.words_count/2)
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
                        return str(int(self.words_count/2) + row_idx + 1) + '.'
                    elif col_idx == 1:
                        if row_idx >= 0 and row_idx < int(self.words_count/2):
                            return self.mnemonic_word_list[row_idx]
                    elif col_idx == 3:
                        if row_idx >= 0 and row_idx < int(self.words_count/2):
                            return self.mnemonic_word_list[int(self.words_count/2) + row_idx]

                elif role == Qt.ForegroundRole:
                    if row_idx >= 0 and row_idx < int(self.words_count/2):
                        if col_idx in (0, 1):
                            word_col_idx = 1
                        else:
                            word_col_idx = 3

                        if word_col_idx == 1:
                            word = self.mnemonic_word_list[row_idx]
                        elif word_col_idx == 3 and row_idx < int(self.words_count/2):
                            word = self.mnemonic_word_list[int(self.words_count/2) + row_idx]
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
