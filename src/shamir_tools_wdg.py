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
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

import app_defs
from app_config import AppConfig
from app_defs import get_note_url
from common import CancelException
from method_call_tracker import MethodCallLimit, method_call_tracker
from seed_words_wdg import SeedWordsWdg
from ui.ui_shamir_tools_wdg import Ui_WdgShamirToolsHw
from wallet_tools_common import ActionPageBase
from hw_intf import HWDevices
from wnd_utils import WndUtils, ReadOnlyTableCellDelegate, QDetectThemeChange


class Step(Enum):
    STEP_NONE = 0
    STEP_MAIN_ACTION_TYPE = 1
    STEP_SPLIT_SHARES_THRESHOLD = 2
    STEP_SPLIT_INPUT_TYPE = 3
    STEP_SPLIT_INPUT = 4
    STEP_SPLIT_RESULT = 5
    STEP_MERGE_INPUT = 6
    STEP_MERGE_RESULT = 7


class Pages(Enum):
    PAGE_MAIN_ACTION_TYPE = 0
    PAGE_SPLIT_SHARES_THRESHOLD = 1
    PAGE_SPLIT_INPUT_TYPE = 2
    PAGE_SPLIT_INPUT = 3
    PAGE_SPLIT_RESULT = 4
    PAGE_MERGE_INPUT = 5
    PAGE_MERGE_RESULT = 6


class MainScenario(Enum):
    NONE = None
    SPLIT = 0
    MERGE = 1


class SplitInputType(Enum):
    NONE = None
    BIP39_SEED = 0
    STRING = 1
    HEX_STRING = 2
    GPG_PRIVATE_KEY = 3


class WdgShamirTools(QWidget, QDetectThemeChange, Ui_WdgShamirToolsHw, ActionPageBase):
    def __init__(self, parent, hw_devices: HWDevices):
        QWidget.__init__(self, parent=parent)
        QDetectThemeChange.__init__(self)
        Ui_WdgShamirToolsHw.__init__(self)
        ActionPageBase.__init__(self, parent, parent.app_config, hw_devices, 'Shamir tools')

        self.current_step: Step = Step.STEP_MAIN_ACTION_TYPE
        self.scenario: MainScenario = MainScenario.NONE
        self.split_input_type: SplitInputType = SplitInputType.NONE
        self.mnemonic = Mnemonic('english')
        # self.words_wdg = SeedWordsWdg(self)
        self.share_count = 0
        self.threashold = 0
        self.input_data: Optional[bytearray] = None
        self.setupUi(self)

    def setupUi(self, dlg):
        Ui_WdgShamirToolsHw.setupUi(self, self)
        self.rbActionTypeSplit.toggled.connect(self.on_main_action_type_change)
        self.rbActionTypeCombine.toggled.connect(self.on_main_action_type_change)
        self.rbInputBIP39Seed.toggled.connect(self.on_spolit_input_data_type_change)
        self.rbInputCharString.toggled.connect(self.on_spolit_input_data_type_change)
        self.rbInputHexString.toggled.connect(self.on_spolit_input_data_type_change)
        self.rbInputGPGPrivateKey.toggled.connect(self.on_spolit_input_data_type_change)
        self.cboShares.setCurrentIndex(3)
        self.update_ui_for_threashold()
        self.update_styles()

    def initialize(self):
        ActionPageBase.initialize(self)
        self.set_hw_panel_visible(False)
        self.set_controls_initial_state_for_step()
        self.current_step = Step.STEP_MAIN_ACTION_TYPE
        self.update_ui()

    def onThemeChanged(self):
        self.update_styles()

    def update_styles(self):
        pass

    def get_split_input_data(self) -> bool:
        ret = False

        inp_str = self.edtInputSecret.toPlainText()
        inp_str = inp_str.strip()
        if not inp_str:
            WndUtils.error_msg('Input not provided')
        else:
            if self.split_input_type == SplitInputType.BIP39_SEED:
                try:
                    in_words_str = re.split(r"\s+", inp_str)
                    in_words = [x for x in in_words_str if x.strip()]
                    if len(in_words) not in (12, 18, 24):
                        WndUtils.error_msg('The BIP-39 word set should contain 12, 18 or 24 words and the '
                                           f'entered one has: {len(in_words)}')
                    else:
                        self.input_data = self.mnemonic.to_entropy(in_words)
                        ret = True
                except Exception as e:
                    WndUtils.error_msg('BIP-39 seed words error, details: ' + str(e))

            elif self.split_input_type == SplitInputType.STRING:
                self.input_data = inp_str.encode('utf-8')
                ret = True

            elif self.split_input_type == SplitInputType.HEX_STRING:
                try:
                    match = re.match(r"^(0[xX])?(.*)", inp_str, re.IGNORECASE)  # extract the leading 0x string
                    if match and len(match.groups()) >= 2 and match.group(2):
                        inp_str = match.group(2)
                        self.input_data = bytes.fromhex(inp_str)
                        ret = True
                    else:
                        WndUtils.error_msg('The data does not appear to be in hex string format.')
                except Exception as e:
                    WndUtils.error_msg('Input data format error, details: ' + str(e))

            elif self.split_input_type == SplitInputType.GPG_PRIVATE_KEY:
                gpg_pass = None  # .encode('ascii')
                try:
                    if re.fullmatch(r'^([0-9a-fA-F]{2})+$', inp_str):
                        rpc_enc_privkey_obj = serialization.load_der_private_key(
                            bytes.fromhex(inp_str),
                            password=gpg_pass,
                            backend=default_backend())
                    else:
                        rpc_enc_privkey_obj = serialization.load_pem_private_key(
                            inp_str.encode('ascii'),
                            password=gpg_pass,
                            backend=default_backend())
                except Exception as e:
                    WndUtils.error_msg('GPG private key input format error, details: ' + str(e) )
                ret = False
        return ret

    def set_current_step(self, step: Step):
        if self.current_step != step:
            self.current_step = step
            self.set_controls_initial_state_for_step()
            self.update_ui()

    def go_to_next_step(self):
        if self.current_step == Step.STEP_MAIN_ACTION_TYPE:
            if self.scenario == MainScenario.SPLIT:
                self.set_current_step(Step.STEP_SPLIT_SHARES_THRESHOLD)
            elif self.scenario == MainScenario.MERGE:
                self.set_current_step(Step.STEP_MERGE_INPUT)

        elif self.current_step == Step.STEP_SPLIT_SHARES_THRESHOLD:
            self.share_count = self.cboShares.currentIndex() + 2
            self.threashold = self.cboThreashold.currentIndex() + 1
            self.set_current_step(Step.STEP_SPLIT_INPUT_TYPE)

        elif self.current_step == Step.STEP_SPLIT_INPUT_TYPE:
            if self.split_input_type == SplitInputType.NONE:
                WndUtils.error_msg('You must select the input data type.')
            else:
                self.set_current_step(Step.STEP_SPLIT_INPUT)

        elif self.current_step == Step.STEP_SPLIT_INPUT:
            if self.get_split_input_data():
                self.set_current_step(Step.STEP_SPLIT_RESULT)

        elif self.current_step == Step.STEP_MERGE_INPUT:
            self.set_current_step(Step.STEP_MERGE_RESULT)

    def go_to_prev_step(self):
        if self.current_step == Step.STEP_MAIN_ACTION_TYPE:
            self.exit_page()

        elif self.current_step == Step.STEP_SPLIT_SHARES_THRESHOLD:
            self.set_current_step(Step.STEP_MAIN_ACTION_TYPE)

        elif self.current_step == Step.STEP_SPLIT_INPUT_TYPE:
            self.set_current_step(Step.STEP_SPLIT_SHARES_THRESHOLD)

        elif self.current_step == Step.STEP_SPLIT_INPUT:
            self.set_current_step(Step.STEP_SPLIT_INPUT_TYPE)

        elif self.current_step == Step.STEP_SPLIT_RESULT:
            self.set_current_step(Step.STEP_SPLIT_INPUT)

        elif self.current_step == Step.STEP_MERGE_INPUT:
            self.set_current_step(Step.STEP_MAIN_ACTION_TYPE)

        elif self.current_step == Step.STEP_MERGE_RESULT:
            self.set_current_step(Step.STEP_MERGE_INPUT)

    def set_controls_initial_state_for_step(self):
        self.set_btn_cancel_enabled(True)
        self.set_btn_cancel_visible(True)
        self.set_btn_close_visible(False)
        self.set_btn_close_enabled(False)
        self.set_hw_change_enabled(True)

        if self.current_step == Step.STEP_MAIN_ACTION_TYPE:
            self.set_btn_back_enabled(True)
            self.set_btn_back_visible(True)
            self.set_btn_continue_enabled(True)
            self.set_btn_continue_visible(True)
            self.lblPage0Message.setVisible(True)

        elif self.current_step in (Step.STEP_SPLIT_INPUT_TYPE, Step.STEP_SPLIT_INPUT):
            self.set_btn_back_enabled(True)
            self.set_btn_back_visible(True)
            self.set_btn_continue_enabled(True)
            self.set_btn_continue_visible(True)

        elif self.current_step == Step.STEP_SPLIT_RESULT:
            self.set_btn_back_enabled(True)
            self.set_btn_back_visible(True)
            self.set_btn_continue_visible(False)
            self.set_btn_close_visible(True)
            self.set_btn_close_enabled(True)

        elif self.current_step == Step.STEP_MERGE_INPUT:
            self.set_btn_back_enabled(False)
            self.set_btn_back_visible(True)
            self.set_btn_continue_enabled(True)
            self.set_btn_continue_visible(True)

        elif self.current_step == Step.STEP_MERGE_RESULT:
            self.set_btn_back_enabled(True)
            self.set_btn_back_visible(True)
            self.set_btn_continue_visible(False)
            self.set_btn_close_visible(True)
            self.set_btn_close_enabled(True)

    def update_ui(self):
        try:
            if self.current_step == Step.STEP_MAIN_ACTION_TYPE:
                self.pages.setCurrentIndex(Pages.PAGE_MAIN_ACTION_TYPE.value)
                self.update_action_subtitle('choose main action type')
                self.lblPage0Message.setText(
                    '<div>This functionality allows you to divide sensitive information into separate parts '
                    '(shares) with the intention of storing them in separate places in order to protect the '
                    'original information against unauthorized reconstruction (or at least make it very '
                    'difficult) and against the loss of some of the shares.</div><br>'
                    '<div>The <b>Shamir secret sharing</b> method in the implementation by Satoshilabs (the '
                    'manufacturer of Trezor devices), described in the SLIP-0039 standard, was used here.</div>'
                    '<br><b>Sources:</b><ul>'
                    '<li><a href="https://blog.trezor.io/multisig-and-split-backups-two-ways-'
                    'to-make-your-bitcoin-more-secure-7174ba78ce45">Multisig and split backups: two ways to keep '
                    'your bitcoin secure</a></li>'
                    '<li><a href="https://wiki.trezor.io/Shamir_Backup#Recovery_Mode">Shamir Backup</a></li>'
                    '<li><a href="https://github.com/satoshilabs/slips/blob/master/slip-0039.md">SLIP-0039 : '
                    'Shamir\'s Secret-Sharing for Mnemonic Codes</a></li>'
                    '</ul><div style="color:red">Note: for the sake of the security of your data use this '
                    'feature only on a computer that is not and will never be connected to any network. '
                    'I suggest using a Linux distribution launched once from a read-only removable media, '
                    'without a network connection.<div>')

            elif self.current_step == Step.STEP_SPLIT_SHARES_THRESHOLD:
                self.update_action_subtitle('split secret')
                self.pages.setCurrentIndex(Pages.PAGE_SPLIT_SHARES_THRESHOLD.value)
                cur_shares = self.cboShares.currentIndex() + 2
                cur_threshold = self.cboThreashold.currentIndex() + 1
                self.lblPage1Message.setText(f'<div>You will need {cur_threshold} shares '
                                             f'out of all {cur_shares} to recreate the '
                                             f'secret.</div>')

            elif self.current_step == Step.STEP_SPLIT_INPUT_TYPE:
                self.update_action_subtitle('split secret')
                self.pages.setCurrentIndex(Pages.PAGE_SPLIT_INPUT_TYPE.value)
                if self.split_input_type == SplitInputType.BIP39_SEED:
                    self.lblPage2Message.setText(
                        '<div>In this scenario, you will be able to split the set of words (12, 18, or 24) that '
                        f'make up your BIP-39 recovery seed. As a result you will get {self.share_count} SLIP-39 '
                        f'compatible word sets (shares), of which {self.threashold} will be needed to recreate '
                        f'the original.</div><br>'
                        f'<div><span style="color:red;font-weight:bold">Note to Trezor T users</span>: although '
                        f'the resulting word sets are '
                        f'compatible with the SLIP-39 standard, due to the way it is implemented, you '
                        f'won\'t be able to use the shares generated here to recreate the wallet directly '
                        f'on Trezor T (see details). You will have to use this app or your own code '
                        f'utilizing the official SLIP-39 library from Satoshilabs to recreate the original '
                        f'BIP-39 recovery seed (see example).</div>')
                elif self.split_input_type == SplitInputType.STRING:
                    self.lblPage2Message.setText(
                        f'<div>Here you will be able to protect any unicode-type string (e.g. password) by splitting '
                        f'it into {self.share_count} SLIP-39 compatible word sets (shares), of '
                        f'which {self.threashold} will be needed to recreate the original.</div>')
                elif self.split_input_type == SplitInputType.HEX_STRING:
                    self.lblPage2Message.setText(
                        f'<div>Here you will be able to protect any set of bytes given as a hex string by splitting '
                        f'it into {self.share_count} SLIP-39 compatible word sets (shares), of '
                        f'which {self.threashold} will be needed to recreate the original.</div>')
                elif self.split_input_type == SplitInputType.GPG_PRIVATE_KEY:
                    self.lblPage2Message.setText(
                        f'<div>Here you will be able to secure your GPG private key given in ASCII form, by '
                        f'splitting it into {self.share_count} SLIP-39 compatible word sets (shares) of'
                        f' which {self.threashold} will be needed to recreate the original. The number of words in '
                        f'the resulting sets will be large (depending on the length of the key), so the recovery '
                        f'process will be quite arduous. For this reason, such key protection should be treated '
                        f'as a last resort and not something we will use every day.</div>')
                else:
                    self.lblPage2Message.setText('')

            elif self.current_step == Step.STEP_SPLIT_INPUT:
                self.update_action_subtitle('split secret')
                self.pages.setCurrentIndex(Pages.PAGE_SPLIT_INPUT.value)
                if self.split_input_type == SplitInputType.BIP39_SEED:
                    self.lblPage3Title.setText('Enter the input secret (BIP-39 seed words)')
                elif self.split_input_type == SplitInputType.STRING:
                    self.lblPage3Title.setText('Enter the input secret (character string)')
                elif self.split_input_type == SplitInputType.HEX_STRING:
                    self.lblPage3Title.setText('Enter the input secret (hexadecimal string)')
                elif self.split_input_type == SplitInputType.GPG_PRIVATE_KEY:
                    self.lblPage3Title.setText('Enter the input secret (GPG private key in ASCII format)')

            elif self.current_step == Step.STEP_SPLIT_RESULT:
                self.update_action_subtitle('split results')
                self.pages.setCurrentIndex(Pages.PAGE_SPLIT_RESULT.value)

            elif self.current_step == Step.STEP_MERGE_INPUT:
                self.update_action_subtitle('merge/recover shares')
                self.pages.setCurrentIndex(Pages.PAGE_MERGE_INPUT.value)

            elif self.current_step == Step.STEP_MERGE_RESULT:
                self.update_action_subtitle('merge/recover shares')
                self.pages.setCurrentIndex(Pages.PAGE_MERGE_RESULT.value)

            self.show_action_page()
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    def update_ui_for_threashold(self):
        shares_count = self.cboShares.currentIndex() + 2
        if self.cboThreashold.count() != shares_count:
            old_state = self.cboThreashold.blockSignals(True)
            try:
                thr_items = [str(i + 1) for i in range(0, shares_count)]
                self.cboThreashold.clear()
                self.cboThreashold.addItems(thr_items)
                new_th_value = int(shares_count * 0.75)
                if new_th_value < 1:
                    new_th_value = 1
                self.cboThreashold.setCurrentIndex(new_th_value - 1)
            finally:
                self.cboThreashold.blockSignals(old_state)
            self.update_ui()

    @pyqtSlot(bool)
    def on_main_action_type_change(self, checked: bool):
        if checked:
            if self.rbActionTypeSplit.isChecked():
                self.scenario = MainScenario.SPLIT
            elif self.rbActionTypeCombine.isChecked():
                self.scenario = MainScenario.MERGE
            self.update_ui()

    @pyqtSlot(int)
    def on_cboShares_currentIndexChanged(self):
        self.update_ui_for_threashold()

    @pyqtSlot(int)
    def on_cboThreashold_currentIndexChanged(self):
        self.update_ui()

    @pyqtSlot(bool)
    def on_spolit_input_data_type_change(self, checked: bool):
        if checked:
            if self.rbInputBIP39Seed.isChecked():
                self.split_input_type = SplitInputType.BIP39_SEED
            elif self.rbInputCharString.isChecked():
                self.split_input_type = SplitInputType.STRING
            elif self.rbInputHexString.isChecked():
                self.split_input_type = SplitInputType.HEX_STRING
            elif self.rbInputGPGPrivateKey.isChecked():
                self.split_input_type = SplitInputType.GPG_PRIVATE_KEY
            self.update_ui()
