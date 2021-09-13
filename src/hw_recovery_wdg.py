#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2021-04

import binascii
import functools
import logging
import os
import re
import ssl
import threading
import time
import urllib, urllib.request, urllib.parse
from enum import Enum
from io import BytesIO
from typing import Callable, Optional, List, Dict, Tuple, Literal

import simplejson
from PyQt5 import QtGui, QtCore
from PyQt5.QtCore import pyqtSlot, QItemSelection, QItemSelectionModel, Qt, QVariant, QAbstractTableModel, QPoint, \
    QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QWidget, QMessageBox, QTableWidgetItem, QLineEdit, QMenu, QShortcut, QApplication
from mnemonic import Mnemonic

import app_defs
from app_config import AppConfig
from app_defs import get_note_url
from common import CancelException
from hw_common import HWDevice, HWType, HWModel
from method_call_tracker import MethodCallLimit, method_call_tracker
from seed_words_wdg import SeedWordsWdg
from ui.ui_hw_recovery_wdg import Ui_WdgRecoverHw
from wallet_tools_common import ActionPageBase
from hw_intf import HWDevices
from wnd_utils import WndUtils, ReadOnlyTableCellDelegate, QDetectThemeChange


class Step(Enum):
    STEP_NONE = 0
    STEP_SEED_SOURCE = 1
    STEP_NUMBER_OF_WORDS = 2
    STEP_HEX_ENTROPY = 3
    STEP_SEED_WORDS = 4
    STEP_OPTIONS = 5
    STEP_RECOVERING = 6
    STEP_FINISHED = 7
    STEP_NO_HW_ERROR = 8


class Pages(Enum):
    PAGE_SEED_SOURCE = 0
    PAGE_NUMBER_OF_WORDS = 1
    PAGE_HEX_ENTROPY = 2
    PAGE_SEED_WORDS = 3
    PAGE_OPTIONS = 4


class Scenario(Enum):
    NONE = None
    ON_DEVICE = 0  # secure: STEP_NONE -> STEP_SEED_SOURCE -> STEP_NUMBER_OF_WORDS -> STEP_OPTIONS -> STEP_FINISHED
    IN_APP_WORDS = 1  # insecure/words: STEP_NONE -> STEP_SEED_SOURCE -> STEP_NUMBER_OF_WORDS -> STEP_SEED_WORDS ->
    # STEP_OPTIONS -> STEP_FINISHED
    IN_APP_ENTROPY = 2  # STEP_NONE -> STEP_SEED_SOURCE -> STEP_HEX_ENTROPY -> STEP_SEED_WORDS -> STEP_OPTIONS ->
    # STEP_FINISHED


class WdgRecoverHw(QWidget, QDetectThemeChange, Ui_WdgRecoverHw, ActionPageBase):
    def __init__(self, parent, hw_devices: HWDevices):
        QWidget.__init__(self, parent=parent)
        QDetectThemeChange.__init__(self)
        Ui_WdgRecoverHw.__init__(self)
        ActionPageBase.__init__(self, parent, parent.app_config, hw_devices, 'Recover from backup seed')

        self.cur_hw_device: Optional[HWDevice] = self.hw_devices.get_selected_device()
        self.current_step: Step = Step.STEP_NONE
        self.hw_conn_change_allowed = True
        self.scenario: Scenario = Scenario.NONE
        self.entropy: Optional[bytearray] = None
        self.word_count: int = 24
        self.mnemonic = Mnemonic('english')
        self.words_wdg = SeedWordsWdg(self)
        self.setupUi(self)

    def setupUi(self, dlg):
        Ui_WdgRecoverHw.setupUi(self, self)
        self.rbSeedSourceHwScreen.toggled.connect(self.on_seed_source_change)
        self.rbSeedSourceAppWords.toggled.connect(self.on_seed_source_change)
        self.rbSeedSourceAppEntropy.toggled.connect(self.on_seed_source_change)
        self.pages.setCurrentIndex(Pages.PAGE_OPTIONS.value)
        WndUtils.set_icon(self, self.btnShowPIN, 'eye@16px.png')
        WndUtils.set_icon(self, self.btnShowSecondaryPIN, 'eye@16px.png')
        WndUtils.set_icon(self, self.btnShowPassphrase, 'eye@16px.png')
        self.rbWordsCount12.toggled.connect(self.on_radio_word_count_toggled)
        self.rbWordsCount18.toggled.connect(self.on_radio_word_count_toggled)
        self.rbWordsCount24.toggled.connect(self.on_radio_word_count_toggled)
        self.btnShowPIN.pressed.connect(functools.partial(self.edtPrimaryPIN.setEchoMode, QLineEdit.Normal))
        self.btnShowPIN.released.connect(functools.partial(self.edtPrimaryPIN.setEchoMode, QLineEdit.Password))
        self.btnShowSecondaryPIN.pressed.connect(functools.partial(self.edtSecondaryPIN.setEchoMode,
                                                                   QLineEdit.Normal))
        self.btnShowSecondaryPIN.released.connect(functools.partial(self.edtSecondaryPIN.setEchoMode,
                                                                    QLineEdit.Password))
        self.btnShowPassphrase.pressed.connect(functools.partial(self.edtPassphrase.setEchoMode,
                                                                 QLineEdit.Normal))
        self.btnShowPassphrase.released.connect(functools.partial(self.edtPassphrase.setEchoMode,
                                                                  QLineEdit.Password))

        lay = self.page3.layout()
        lay.addWidget(self.words_wdg)
        self.set_word_count(self.word_count)
        self.update_styles()

    def initialize(self):
        ActionPageBase.initialize(self)
        self.set_hw_panel_visible(True)
        self.set_controls_initial_state_for_step()
        self.current_step = Step.STEP_NONE
        self.update_ui()

        with MethodCallLimit(self, self.on_connected_hw_device_changed, call_count_limit=1):
            if not self.cur_hw_device:
                self.hw_devices.select_device(self.parent(), open_client_session=False)
            # else:
            #     if not self.cur_hw_device.hw_client:
            #         self.hw_devices.open_hw_session(self.cur_hw_device)
            self.on_connected_hw_device_changed(self.hw_devices.get_selected_device())

    def onThemeChanged(self):
        self.update_styles()

    def update_styles(self):
        self.lblPinMessage.setStyleSheet('QLabel {color: gray}')

    @method_call_tracker
    def on_connected_hw_device_changed(self, cur_hw_device: HWDevice):
        self.cur_hw_device = cur_hw_device
        if self.hw_conn_change_allowed:
            if self.on_validate_hw_device(cur_hw_device):
                if self.current_step != Step.STEP_SEED_SOURCE:
                    self.set_current_step(Step.STEP_SEED_SOURCE)
                else:
                    self.set_controls_initial_state_for_step()
                    self.update_ui()
            else:
                self.set_current_step(Step.STEP_NO_HW_ERROR)

    def on_validate_hw_device(self, hw_device: HWDevice) -> bool:
        if not hw_device:
            return False
        else:
            return True

    def set_current_step(self, step: Step):
        if self.current_step != step:
            self.current_step = step
            self.set_controls_initial_state_for_step()
            self.update_ui()

    def go_to_next_step(self):
        if self.current_step == Step.STEP_SEED_SOURCE:
            if self.scenario in (Scenario.ON_DEVICE, Scenario.IN_APP_WORDS):
                self.set_current_step(Step.STEP_NUMBER_OF_WORDS)
            elif self.scenario == Scenario.IN_APP_ENTROPY:
                self.set_current_step(Step.STEP_HEX_ENTROPY)

        elif self.current_step == Step.STEP_NUMBER_OF_WORDS:
            if self.word_count in (12, 18, 24):
                if self.scenario == Scenario.ON_DEVICE:
                    self.set_current_step(Step.STEP_OPTIONS)
                elif self.scenario == Scenario.IN_APP_WORDS:
                    self.set_current_step(Step.STEP_SEED_WORDS)
                    self.set_word_count(self.word_count)
            else:
                WndUtils.error_msg('Choose the number of the seed words.')

        elif self.current_step == Step.STEP_HEX_ENTROPY:
            if self.apply_entropy_input():
                self.set_current_step(Step.STEP_OPTIONS)

        elif self.current_step == Step.STEP_SEED_WORDS:
            if self.apply_words_input():
                self.set_current_step(Step.STEP_OPTIONS)

        elif self.current_step == Step.STEP_OPTIONS:
            self.set_current_step(Step.STEP_RECOVERING)
            self.recover_hw()

        elif self.current_step == Step.STEP_RECOVERING:
            self.set_current_step(Step.STEP_FINISHED)

    def go_to_prev_step(self):
        if self.current_step in (Step.STEP_SEED_SOURCE, Step.STEP_NO_HW_ERROR):
            self.exit_page()

        elif self.current_step == Step.STEP_OPTIONS:
            if self.scenario == Scenario.ON_DEVICE:
                self.set_current_step(Step.STEP_NUMBER_OF_WORDS)
            elif self.scenario == Scenario.IN_APP_WORDS:
                self.set_current_step(Step.STEP_SEED_WORDS)
            elif self.scenario == Scenario.IN_APP_ENTROPY:
                self.set_current_step(Step.STEP_HEX_ENTROPY)

        elif self.current_step == Step.STEP_SEED_WORDS:
            self.set_current_step(Step.STEP_NUMBER_OF_WORDS)

        elif self.current_step in (Step.STEP_HEX_ENTROPY, Step.STEP_NUMBER_OF_WORDS):
            self.set_current_step(Step.STEP_SEED_SOURCE)

        elif self.current_step in (Step.STEP_FINISHED, Step.STEP_RECOVERING):
            self.set_current_step(Step.STEP_OPTIONS)

    def set_controls_initial_state_for_step(self):
        self.set_btn_cancel_enabled(True)
        self.set_btn_cancel_visible(True)
        self.set_btn_close_visible(False)
        self.set_btn_close_enabled(False)
        self.set_hw_change_enabled(True)
        self.btnPreviewAddresses.hide()

        if self.current_step == Step.STEP_SEED_SOURCE:
            self.set_btn_back_enabled(True)
            self.set_btn_back_visible(True)
            self.set_btn_continue_enabled(True)
            self.set_btn_continue_visible(True)
            self.lblActionTypeMessage.setVisible(False)

        elif self.current_step == Step.STEP_SEED_WORDS:
            self.set_btn_back_enabled(True)
            self.set_btn_back_visible(True)
            self.set_btn_continue_enabled(True)
            self.set_btn_continue_visible(True)

        elif self.current_step == Step.STEP_OPTIONS:
            self.set_btn_back_enabled(True)
            self.set_btn_back_visible(True)
            self.set_btn_continue_enabled(True)
            self.set_btn_continue_visible(True)

        elif self.current_step == Step.STEP_RECOVERING:
            self.set_btn_back_enabled(False)
            self.set_btn_back_visible(True)
            self.set_btn_continue_enabled(False)
            self.set_btn_continue_visible(True)
            self.set_hw_change_enabled(False)

        elif self.current_step == Step.STEP_FINISHED:
            self.set_btn_back_enabled(True)
            self.set_btn_back_visible(True)
            self.set_btn_continue_visible(False)
            self.set_btn_close_visible(True)
            self.set_btn_close_enabled(True)
            self.set_hw_change_enabled(False)

        elif self.current_step == Step.STEP_NO_HW_ERROR:
            self.set_btn_back_visible(True)
            self.set_btn_continue_visible(False)

    def update_ui(self):
        try:
            # if self.cur_hw_device and self.cur_hw_device.hw_client:
            if self.cur_hw_device:
                if self.current_step == Step.STEP_SEED_SOURCE:
                    self.pages.setCurrentIndex(Pages.PAGE_SEED_SOURCE.value)
                    self.update_action_subtitle('choose scenario')

                    if self.cur_hw_device.hw_type in (HWType.trezor, HWType.keepkey):
                        self.rbSeedSourceHwScreen.setEnabled(True)
                        self.rbSeedSourceAppWords.setEnabled(False)
                        self.rbSeedSourceAppEntropy.setEnabled(False)
                        self.rbSeedSourceHwScreen.setChecked(True)
                    elif self.cur_hw_device.hw_type == HWType.ledger_nano:
                        self.rbSeedSourceHwScreen.setEnabled(False)
                        self.rbSeedSourceAppWords.setEnabled(True)
                        self.rbSeedSourceAppEntropy.setEnabled(True)
                        if not self.rbSeedSourceAppWords.isChecked() and not self.rbSeedSourceAppEntropy.isChecked():
                            self.rbSeedSourceAppWords.setChecked(True)

                    if self.scenario in (Scenario.IN_APP_WORDS, Scenario.IN_APP_ENTROPY):
                        self.lblActionTypeMessage.setVisible(True)
                        self.lblActionTypeMessage.setText(
                            '<b style="color:red">Use this method only for test seeds and for real seeds only on an '
                            'offline computer that will never be connected to the network.</b>')
                    else:
                        self.lblActionTypeMessage.setVisible(False)

                elif self.current_step == Step.STEP_NUMBER_OF_WORDS:
                    self.update_action_subtitle('number of seed words')
                    self.pages.setCurrentIndex(Pages.PAGE_NUMBER_OF_WORDS.value)
                    if self.cur_hw_device.get_hw_model() == HWModel.trezor_t:
                        self.lblPage1Message.show()
                        self.lblPage1Message.setText('Note: Trezor T may ask you for the number words of your recovery '
                                                     'seed regardless of this setting.')
                    else:
                        self.lblPage1Message.hide()

                elif self.current_step == Step.STEP_HEX_ENTROPY:
                    self.update_action_subtitle('hexadecimal entropy')
                    self.pages.setCurrentIndex(Pages.PAGE_HEX_ENTROPY.value)

                elif self.current_step == Step.STEP_SEED_WORDS:
                    self.update_action_subtitle('seed words')
                    self.pages.setCurrentIndex(Pages.PAGE_SEED_WORDS.value)

                elif self.current_step == Step.STEP_OPTIONS:
                    self.update_action_subtitle('hardware wallet options')
                    self.pages.setCurrentIndex(Pages.PAGE_OPTIONS.value)

                    if self.cur_hw_device.hw_type in (HWType.trezor, HWType.keepkey):
                        self.btnShowPIN.hide()
                        self.edtPrimaryPIN.hide()
                        self.edtPassphrase.hide()
                        self.btnShowPassphrase.hide()
                        self.edtSecondaryPIN.hide()
                        self.btnShowSecondaryPIN.hide()
                        self.edtDeviceLabel.show()
                        self.lblDeviceLabel.show()
                        self.lblPinMessage.show()
                        self.lblPinMessage.setText('Note: if set, the device will ask you for a new PIN '
                                                   'during the recovery.')
                        self.lblPassphraseMessage.show()
                        self.lblPassphraseMessage.setText(
                            '<span style="color:gray">Note: passphrase is not stored on the device - if this setting '
                            'is on, you will<br>be asked for it every time you open the wallet.</span>')
                    elif self.cur_hw_device.hw_type == HWType.ledger_nano:
                        self.btnShowPIN.show()
                        self.edtPrimaryPIN.show()
                        self.edtPassphrase.show()
                        self.btnShowPassphrase.show()
                        self.edtSecondaryPIN.show()
                        self.btnShowSecondaryPIN.show()
                        self.edtDeviceLabel.hide()
                        self.lblDeviceLabel.hide()
                        self.lblPinMessage.hide()
                        self.lblPassphraseMessage.hide()

                        if self.chbUsePIN.isChecked():
                            self.edtPrimaryPIN.setReadOnly(False)
                            self.btnShowPIN.setEnabled(True)
                            self.edtSecondaryPIN.setReadOnly(False)
                            self.btnShowSecondaryPIN.setEnabled(True)
                        else:
                            self.edtPrimaryPIN.setReadOnly(True)
                            self.btnShowPIN.setDisabled(True)
                            self.edtSecondaryPIN.setReadOnly(True)
                            self.btnShowSecondaryPIN.setDisabled(True)
                        if self.chbUsePassphrase.isChecked():
                            self.edtPassphrase.setReadOnly(False)
                            self.btnShowPassphrase.setEnabled(True)
                        else:
                            self.edtPassphrase.setReadOnly(True)
                            self.btnShowPassphrase.setDisabled(True)

                    if self.scenario == Scenario.IN_APP_WORDS and self.entropy:
                        self.lblOptionsEntropy.setText('Your recovery seed hexadecimal entropy: ' +
                                                       self.entropy.hex())
                        self.lblOptionsEntropy.setVisible(True)
                    else:
                        self.lblOptionsEntropy.setVisible(False)

                    # if self.scenario in (Scenario.IN_APP_WORDS, Scenario.IN_APP_ENTROPY):
                    #     self.btnPreviewAddresses.show()
                    # else:
                    #     self.btnPreviewAddresses.hide()

                    if self.scenario == Scenario.ON_DEVICE and self.cur_hw_device.get_hw_model() == HWModel.trezor_one:
                        self.lblDeviceWordsInputType.show()
                        self.gbDeviceWordsInputType.show()
                    else:
                        self.lblDeviceWordsInputType.hide()
                        self.gbDeviceWordsInputType.hide()

                    if self.cur_hw_device.hw_type in (HWType.trezor, HWType.keepkey):
                        if self.cur_hw_device.initialized:
                            self.lblOptionsPageMessage.show()
                            self.lblOptionsPageMessage.setText(
                                'Note: The currently selected device is initialized. If you '
                                'continue, the device will be wiped before starting recovery.')
                            self.lblOptionsPageMessage.setWordWrap(True)
                            self.lblOptionsPageMessage.setStyleSheet('QLabel{color:red}')
                        else:
                            self.lblOptionsPageMessage.hide()
                    elif self.cur_hw_device.hw_type == HWType.ledger_nano:
                        msg_text = '<span><b>Important! Start your Ledger Nano S wallet in recovery mode:</b></span>' \
                                   '<ol><li>Clear the device by selecting the \'Settings->Device->Reset all\' menu ' \
                                   'item.</li>' \
                                   '<li>Power the device off.</li>' \
                                   '<li>Power the device on while holding down the right-hand physical button.</li>' \
                                   '</ol>'
                        self.lblOptionsPageMessage.show()
                        self.lblOptionsPageMessage.setText(msg_text)
                        self.lblOptionsPageMessage.setStyleSheet('')

                elif self.current_step == Step.STEP_FINISHED:
                    self.update_action_subtitle('finished')
                    self.show_message_page('<b>Hardware wallet successfully recovered.</b>')
                    return

                elif self.current_step == Step.STEP_NO_HW_ERROR:
                    return
                self.show_action_page()
            else:
                self.show_message_page('Connect Trezor/Keepkey hardware wallet')
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_seed_source_change(self, checked):
        if checked:
            if self.rbSeedSourceHwScreen.isChecked():
                self.scenario = Scenario.ON_DEVICE
            elif self.rbSeedSourceAppWords.isChecked():
                self.scenario = Scenario.IN_APP_WORDS
            elif self.rbSeedSourceAppEntropy.isChecked():
                self.scenario = Scenario.IN_APP_ENTROPY
            self.update_ui()

    @pyqtSlot(bool)
    def on_chbUsePIN_toggled(self, checked):
        self.update_ui()

    @pyqtSlot(bool)
    def on_chbUsePassphrase_toggled(self, checked):
        self.update_ui()

    def apply_entropy_input(self) -> bool:
        success = True
        ent_str = self.edtHexEntropy.text()
        try:
            entropy = bytes.fromhex(ent_str)
            if len(entropy) not in (32, 24, 16):
                WndUtils.warn_msg('The entropy hex-string can only have 16, 24 or 32 bytes.')
                success = False
            else:
                self.entropy = entropy
                words = self.entropy_to_mnemonic(entropy)
                self.words_wdg.set_words(words)
                self.words_wdg.set_word_count(len(words))
        except Exception as e:
            WndUtils.warn_msg(str(e))
            success = False
        return success

    def entropy_to_mnemonic(self, entropy):
        words = self.mnemonic.to_mnemonic(entropy)
        return words.split()

    def set_word_count(self, word_count: int, checked=True):
        if checked:
            self.word_count = word_count
            self.words_wdg.set_word_count(word_count)

    def apply_words_input(self) -> bool:
        """
        Read all the seed words from the editor and convert them to entropy (self.entropy)
        :return: True if successful, False otherwise
        """
        success = True
        if self.scenario == Scenario.IN_APP_WORDS:
            wl = self.mnemonic.wordlist
            invalid_indexes = []
            suppress_error_message = False
            for idx, word in enumerate(self.words_wdg.get_cur_mnemonic_words()):
                if not word:
                    WndUtils.error_msg('Cannot continue - not all words are entered.')
                    success = False
                    suppress_error_message = True
                    break
                if word not in wl:
                    success = False
                    invalid_indexes.append(idx)

            if not success:
                # verify the whole word-set entered by the user (checksum)
                if not suppress_error_message:
                    WndUtils.error_msg('Cannot continue - invalid word(s): %s.' %
                                       ','.join(['#' + str(x + 1) for x in invalid_indexes]))
            else:
                try:
                    ws = self.words_wdg.get_cur_mnemonic_words()
                    self.entropy = self.mnemonic.to_entropy(ws)
                except Exception as e:
                    success = False
                    if str(e) == 'Failed checksum.':
                        WndUtils.error_msg('Invalid checksum of the provided words. You\'ve probably mistyped some'
                                           ' words or changed their order.')
                    else:
                        WndUtils.error_msg('There was an error in the provided word-list. Error details: ' + str(e))
        return success

    def on_radio_word_count_toggled(self, checked):
        if self.rbWordsCount12.isChecked():
            word_count = 12
        elif self.rbWordsCount18.isChecked():
            word_count = 18
        elif self.rbWordsCount24.isChecked():
            word_count = 24
        else:
            word_count = 24
        self.set_word_count(word_count)

    def recover_hw(self):
        try:
            self.hw_conn_change_allowed = False
            use_pin = True if self.chbUsePIN.isChecked() else False
            use_passphrase = True if self.chbUsePassphrase.isChecked() else False
            label = self.edtDeviceLabel.text()
            if self.scenario == Scenario.ON_DEVICE:
                input_type: Literal["scrambled_words", "matrix"] = "scrambled_words"
                if self.cur_hw_device.hw_type == HWType.trezor:
                    if self.rbWordsMatrix.isChecked():
                        input_type = "matrix"

                self.hw_devices.recover_device(self.cur_hw_device, word_count=self.word_count,
                                               passphrase_enabled=use_passphrase, pin_enabled=use_pin, hw_label=label,
                                               input_type=input_type, parent_window=self.parent_dialog)

            elif self.scenario in (Scenario.IN_APP_WORDS, Scenario.IN_APP_ENTROPY):
                words = ' '.join(self.entropy_to_mnemonic(self.entropy))
                pin = self.edtPrimaryPIN.text() if use_pin else ''
                secondary_pin = self.edtSecondaryPIN.text()
                passphrase = self.edtPassphrase.text() if use_passphrase else ''

                self.hw_devices.recover_device_with_seed_input(self.cur_hw_device, words, pin, passphrase,
                                                               secondary_pin)
            else:
                raise Exception('Not implemented')
            self.set_current_step(Step.STEP_FINISHED)
        except CancelException:
            self.go_to_prev_step()
            self.hw_devices.open_hw_session(self.cur_hw_device, force_reconnect=True)
        except Exception as e:
            self.go_to_prev_step()
            WndUtils.error_msg(str(e), True)
        finally:
            self.hw_conn_change_allowed = True
