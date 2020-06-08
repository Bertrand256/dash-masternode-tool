#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-12
import binascii
import hashlib
import os
import ssl
import time
import urllib, urllib.parse, urllib.request
from io import BytesIO
from typing import List
import simplejson
from PyQt5 import QtGui, QtWidgets
import bitcoin
import functools
import re
from PyQt5.QtCore import pyqtSlot, QAbstractTableModel, QVariant, Qt, QPoint, QItemSelection, QItemSelectionModel, \
    QEventLoop
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QDialog, QMenu, QApplication, QLineEdit, QShortcut, QMessageBox, QTableWidgetItem
import app_cache
import app_defs
from dash_utils import pubkey_to_address
from thread_fun_dlg import CtrlObject
from ui import ui_initialize_hw_dlg
from doc_dlg import show_doc_dlg
from hw_intf import *
from mnemonic import Mnemonic
from wnd_utils import ReadOnlyTableCellDelegate


ACTION_RECOVER_FROM_WORDS_CONV = 1
ACTION_RECOVER_FROM_WORDS_SAFE = 2
ACTION_RECOVER_FROM_ENTROPY = 3
ACTION_INITIALIZE_NEW_SAFE = 4
ACTION_WIPE_DEVICE = 5
ACTION_UPLOAD_FIRMWARE = 6


STEP_SELECT_DEVICE_TYPE = 0
STEP_SELECT_DEVICE_INSTANCE = 1
STEP_SELECT_ACTION = 2
STEP_INPUT_NUMBER_OF_WORDS = 3
STEP_INPUT_ENTROPY = 4
STEP_INPUT_WORDS = 5
STEP_INPUT_HW_OPTIONS = 6
STEP_FINISHED = 7
STEP_INPUT_FIRMWARE_SOURCE = 8
STEP_UPLOAD_FIRMWARE = 9

CACHE_ITEM_LAST_FIRMWARE_FILE = 'HwInitializeDlg_LastFirmwareFile'


class HwInitializeDlg(QDialog, ui_initialize_hw_dlg.Ui_HwInitializeDlg, WndUtils):
    def __init__(self, parent) -> None:
        QDialog.__init__(self, parent)
        ui_initialize_hw_dlg.Ui_HwInitializeDlg.__init__(self)
        WndUtils.__init__(self, parent.app_config)
        self.main_ui = parent
        self.app_config = parent.app_config
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
        self.hw_model: Optional[str] = None
        self.hw_device_id_selected = Optional[str]  # device id of the hw client selected
        self.hw_device_instances: List[List[str]] = []  # list of 3-element list: 0: device_id, 1: device label, 2: device model
        self.hw_device_index_selected: int = None  # index in self.hw_device_instances
        self.act_paste_words = None
        self.hw_action_mnemonic_words: Optional[str] = None
        self.hw_action_use_pin: Optional[bool] = None
        self.hw_action_pin: Optional[str] = None
        self.hw_action_use_passphrase: Optional[bool] = None
        self.hw_action_passphrase: Optional[str] = None  # only for Ledger
        self.hw_action_secondary_pin: Optional[str] = None # only for Ledger
        self.hw_action_label: Optional[str] = None
        self.hw_firmware_source_type: int = 0  # 0: local file, 1: internet
        self.hw_firmware_source_file: str = ''
        self.hw_firmware_web_sources: List[Dict] = []
        # subset of self.hw_firmware_web_sources dedicated to current hardware wallet type:
        self.hw_firmware_web_sources_cur_hw: List = []
        self.hw_firmware_url_selected: Dict = None
        self.hw_firmware_last_hw_type = None
        self.hw_firmware_last_hw_model = None
        self.setupUi()

    def setupUi(self):
        ui_initialize_hw_dlg.Ui_HwInitializeDlg.setupUi(self, self)
        self.setWindowTitle("Hardware wallet initialization/recovery")

        self.viewMnemonic.verticalHeader().setDefaultSectionSize(
            self.viewMnemonic.verticalHeader().fontMetrics().height() + 6)
        self.set_word_count(self.word_count)
        self.edtHwOptionsBip32Path.setText(dash_utils.get_default_bip32_path(self.app_config.dash_network))

        self.tabFirmwareWebSources.verticalHeader().setDefaultSectionSize(
            self.tabFirmwareWebSources.verticalHeader().fontMetrics().height() + 3)
        self.tabFirmwareWebSources.setItemDelegate(ReadOnlyTableCellDelegate(self.tabFirmwareWebSources))
        # self.tabFirmwareWebSources.

        self.rbDeviceTrezor.toggled.connect(self.on_device_type_changed)
        self.rbDeviceKeepkey.toggled.connect(self.on_device_type_changed)
        self.rbDeviceLedger.toggled.connect(self.on_device_type_changed)

        self.rbActRecoverWordsSafe.toggled.connect(self.on_rbActionType_changed)
        self.rbActRecoverMnemonicWords.toggled.connect(self.on_rbActionType_changed)
        self.rbActRecoverHexEntropy.toggled.connect(self.on_rbActionType_changed)
        self.rbActInitializeNewSeed.toggled.connect(self.on_rbActionType_changed)
        self.rbActWipeDevice.toggled.connect(self.on_rbActionType_changed)
        self.rbActUploadFirmware.toggled.connect(self.on_rbActionType_changed)

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
        self.act_paste_words = self.popMenuWords.addAction("\u23ce Paste")
        self.act_paste_words.triggered.connect(self.on_actPasteWords_triggered)
        self.act_paste_words.setShortcut(QKeySequence("Ctrl+V"))
        QShortcut(QKeySequence("Ctrl+V"), self.viewMnemonic).activated.connect(self.on_actPasteWords_triggered)

        self.fraDetails.setVisible(False)
        self.resize(self.size().width(), 350)
        self.apply_current_step_to_ui()
        self.update_current_tab()

    def read_action_type_from_ui(self):
        if self.rbActRecoverWordsSafe.isChecked():
            self.action_type = ACTION_RECOVER_FROM_WORDS_SAFE  # recover safe (onlline)
        elif self.rbActRecoverMnemonicWords.isChecked():
            self.action_type = ACTION_RECOVER_FROM_WORDS_CONV  # recover convenient (safe only when offline)
        elif self.rbActRecoverHexEntropy.isChecked():
            self.action_type = ACTION_RECOVER_FROM_ENTROPY
        elif self.rbActInitializeNewSeed.isChecked():
            self.action_type = ACTION_INITIALIZE_NEW_SAFE
        elif self.rbActWipeDevice.isChecked():
            self.action_type = ACTION_WIPE_DEVICE
        elif self.rbActUploadFirmware.isChecked():
            self.action_type = ACTION_UPLOAD_FIRMWARE
        else:
            raise Exception('Invalid action')

    def apply_current_step_to_ui(self):
        if self.current_step == STEP_SELECT_DEVICE_TYPE:
            idx = 0
        elif self.current_step == STEP_SELECT_DEVICE_INSTANCE:
            idx = 1
        elif self.current_step == STEP_SELECT_ACTION:
            idx = 2
        elif self.current_step == STEP_INPUT_NUMBER_OF_WORDS:
            idx = 3
        elif self.current_step == STEP_INPUT_ENTROPY:
            idx = 4
        elif self.current_step == STEP_INPUT_WORDS:
            idx = 5
        elif self.current_step == STEP_INPUT_HW_OPTIONS:
            idx = 6
        elif self.current_step == STEP_FINISHED:
            idx = 7
        elif self.current_step == STEP_INPUT_FIRMWARE_SOURCE:
            idx = 8
        elif self.current_step == STEP_UPLOAD_FIRMWARE:
            idx = 9
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

    def apply_step_select_device_type(self) -> bool:
        """Moves forward from the 'device type selection' step."""
        success = True
        if not self.hw_type:
            self.errorMsg('Select your hardware wallet type.')
            success = False
        else:
            self.set_next_step(STEP_SELECT_ACTION)
        return success

    def apply_step_select_action(self) -> bool:
        """Moves forward from the 'select action' step."""
        success = True
        self.read_action_type_from_ui()
        if self.action_type in (ACTION_RECOVER_FROM_WORDS_CONV, ACTION_RECOVER_FROM_WORDS_SAFE,
                                ACTION_INITIALIZE_NEW_SAFE):

            self.set_next_step(STEP_INPUT_NUMBER_OF_WORDS)

        elif self.action_type == ACTION_RECOVER_FROM_ENTROPY:

            self.set_next_step(STEP_INPUT_ENTROPY)

        elif self.action_type == ACTION_WIPE_DEVICE:
            if self.hw_type in (HWType.trezor, HWType.keepkey):
                if self.queryDlg('Do you really want to wipe your %s device?' % self.hw_type,
                                 buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                 default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Yes:
                    try:
                        self.load_hw_devices()
                        cnt = len(self.hw_device_instances)
                        if cnt == 0:
                            self.errorMsg('Couldn\'t find any %s devices connected to your computer.' %
                                          HWType.get_desc(self.hw_type))
                            success = False
                        elif cnt == 1:
                            # there is only one instance of this device type
                            self.hw_device_id_selected = self.hw_device_instances[0][0]
                            self.hw_device_index_selected = 0
                            success = self.apply_action_on_hardware_wallet()
                            if success:
                                self.set_next_step(STEP_FINISHED)
                        else:
                            # there is more than one instance of this device type; go to the device instance selection tab
                            self.set_next_step(STEP_SELECT_DEVICE_INSTANCE)
                            success = True
                    except CancelException:
                        self.warnMsg('Operation cancelled.')
                        success = False
                else:
                    success = False

        elif self.action_type == ACTION_UPLOAD_FIRMWARE:

            if self.hw_type in (HWType.trezor, HWType.keepkey):

                self.set_next_step(STEP_INPUT_FIRMWARE_SOURCE)

            else:
                self.errorMsg(f'{HWType.get_desc(self.hw_type)} is not supported.')
                success = False

        else:
            raise Exception('Not implemented')
        return success

    def apply_step_select_number_of_words(self) -> bool:
        """Moves forward from the 'select number of words' step."""

        if self.action_type == ACTION_RECOVER_FROM_WORDS_CONV:
            self.set_next_step(STEP_INPUT_WORDS)
        elif self.action_type == ACTION_RECOVER_FROM_WORDS_SAFE:
            self.set_next_step(STEP_INPUT_HW_OPTIONS)
        elif self.action_type == ACTION_INITIALIZE_NEW_SAFE:
            self.set_next_step(STEP_INPUT_HW_OPTIONS)
        else:
            raise Exception('Invalid action type.')
        return True

    def apply_step_input_entropy(self) -> bool:
        """Moves forward from the 'input entropy' step."""
        success = True
        ent_str = self.edtHexEntropy.text()
        try:
            entropy = bytes.fromhex(ent_str)
            if len(entropy) not in (32, 24, 16):
                self.warnMsg('The entropy hex-string can only have 16, 24 or 32 bytes.')
                success = False
            else:
                self.entropy = entropy
                words = self.entropy_to_mnemonic(entropy)
                self.set_words(words)
                self.set_word_count(len(words))
                self.set_next_step(STEP_INPUT_WORDS)
        except Exception as e:
            self.warnMsg(str(e))
            success = False
        return success

    def apply_step_input_words(self) -> bool:
        """Moves forward from the 'input words' step."""
        success = True
        if self.action_type == ACTION_RECOVER_FROM_WORDS_CONV:
            # verify all the seed words entered by the user
            wl = self.mnemonic.wordlist
            invalid_indexes = []
            suppress_error_message = False
            for idx, word in enumerate(self.get_cur_mnemonic_words()):
                if not word:
                    self.errorMsg('Cannot continue - not all words are entered.')
                    success = False
                    suppress_error_message = True
                    break
                if word not in wl:
                    success = False
                    invalid_indexes.append(idx)

            if not success:
                # verify the whole word-set entered by the user (checksum)
                if not suppress_error_message:
                    self.errorMsg('Cannot continue - invalid word(s): %s.' %
                                  ','.join(['#' + str(x + 1) for x in invalid_indexes]))
            else:
                try:
                    ws = self.get_cur_mnemonic_words()
                    self.entropy = self.mnemonic.to_entropy(ws)
                except Exception as e:
                    success = False
                    if str(e) == 'Failed checksum.':
                        self.errorMsg('Invalid checksum of the provided words. You\'ve probably mistyped some'
                                      ' words or changed their order.')
                    else:
                        self.errorMsg('There was an error in the provided word-list. Error details: ' + str(e))
        elif self.action_type == ACTION_RECOVER_FROM_ENTROPY:
            pass
        else:
            raise Exception('Invalid action type.')

        if success:
            self.set_next_step(STEP_INPUT_HW_OPTIONS)

        return success

    def apply_step_input_hw_options(self) -> bool:
        """Moves forward from the 'input hardware wallet options' step."""
        self.hw_action_use_pin = self.chbHwOptionsUsePIN.isChecked()
        self.hw_action_use_passphrase = self.chbHwOptionsUsePassphrase.isChecked()
        self.hw_action_label = self.edtHwOptionsDeviceLabel.text()
        success = True
        if not self.hw_action_label:
            self.hw_action_label = 'My %s' % HWType.get_desc(self.hw_type)

        if self.action_type in (ACTION_RECOVER_FROM_WORDS_CONV, ACTION_RECOVER_FROM_ENTROPY):
            self.hw_action_mnemonic_words = ' '.join(self.get_cur_mnemonic_words())
            self.hw_action_pin = ''
            self.hw_action_secondary_pin = ''
            self.hw_action_passphrase = ''
            if self.hw_action_use_pin:
                self.hw_action_pin = self.edtHwOptionsPIN.text()
                if len(self.hw_action_pin) not in (4, 8):
                    self.errorMsg('Invalid PIN length. It can only have 4 or 8 characters.')
                    success = False
                else:
                    if self.hw_type == HWType.ledger_nano_s:
                        if not re.match("^[0-9]+$", self.hw_action_pin):
                            self.errorMsg('Invalid PIN. Allowed characters: 0-9.')
                            success = False
                    else:
                        if not re.match("^[1-9]+$", self.hw_action_pin):
                            self.errorMsg('Invalid PIN. Allowed characters: 1-9.')
                            success = False
            if not success:
                self.edtHwOptionsPIN.setFocus()
            else:
                if self.hw_type == HWType.ledger_nano_s:
                    if self.hw_action_use_passphrase:
                        self.hw_action_passphrase = self.edtHwOptionsLedgerPassphrase.text()
                        if not self.hw_action_passphrase:
                            self.errorMsg('For Ledger Nano S you need to provide your passphrase - it will be '
                                          'stored in the device and secured by secondary PIN.')
                            self.edtHwOptionsLedgerPassphrase.setFocus()
                            success = False
                        else:
                            # validate secondary PIN
                            self.hw_action_secondary_pin = self.edtHwOptionsLedgerSecondaryPIN.text()
                            if not self.hw_action_secondary_pin:
                                self.errorMsg('Secondary PIN is required if you want to save passphrase '
                                              'in your Ledger Nano S.')
                                self.edtHwOptionsLedgerSecondaryPIN.setFocus()
                                success = False
                            else:
                                if len(self.hw_action_secondary_pin) not in (4, 8):
                                    self.errorMsg('Invalid secondary PIN length. '
                                                  'It can only have 4 or 8 characters.')
                                    success = False
                                elif not re.match("^[0-9]+$", self.hw_action_secondary_pin):
                                    self.errorMsg('Invalid secondary PIN. Allowed characters: 0-9.')
                                    success = False

                                if not success:
                                    self.edtHwOptionsLedgerSecondaryPIN.setFocus()
        elif self.action_type in (ACTION_RECOVER_FROM_WORDS_SAFE, ACTION_INITIALIZE_NEW_SAFE):
            pass
        else:
            raise Exception('Invalid action.')

        if success:
            # try to load devices
            self.load_hw_devices()
            cnt = len(self.hw_device_instances)
            if cnt == 0:
                self.errorMsg('Couldn\'t find any %s devices connected to your computer.' %
                              HWType.get_desc(self.hw_type))
            elif cnt == 1:
                # there is only one instance of this device type
                self.hw_device_id_selected = self.hw_device_instances[0][0]
                self.hw_device_index_selected = 0
                success = self.apply_action_on_hardware_wallet()
                if success:
                    self.set_next_step(STEP_FINISHED)
            else:
                # there is more than one instance of this device type; go to the device instance selection tab
                self.set_next_step(STEP_SELECT_DEVICE_INSTANCE)
                success = True
        return success

    def apply_step_select_device_id(self) -> bool:
        """Moves forward from the 'select device instance' step."""
        success = False
        idx = self.cboDeviceInstance.currentIndex()
        if idx >= 0 and idx < len(self.hw_device_instances):
            self.hw_device_id_selected = self.hw_device_instances[idx][0]
            self.hw_device_index_selected = idx

            if self.action_type == ACTION_UPLOAD_FIRMWARE:
                device_model = self.hw_device_instances[idx][2]
                if self.hw_firmware_source_type == 1:  # firmware from Internet, check model copatibility
                    if self.hw_firmware_url_selected:
                        fw_model = self.hw_firmware_url_selected.get('model')
                        if str(fw_model) != str(device_model):
                            self.errorMsg(f'The firmware selected is dedicated the device model "{fw_model}", '
                                          f'but the selected device is model "{device_model}".' )
                        else:
                            self.set_next_step(STEP_UPLOAD_FIRMWARE)
                            success = True
                    else:
                        self.errorMsg('No firmware selected!')
                else:
                    # for uploading from the file, we cannot verify model compatibility
                    self.set_next_step(STEP_UPLOAD_FIRMWARE)
                    success = True
            else:
                success = self.apply_action_on_hardware_wallet()
                if success:
                    self.set_next_step(STEP_FINISHED)
        else:
            self.errorMsg('No %s device instances.' % HWType.get_desc(self.hw_type))
        return success

    def apply_action_on_hardware_wallet(self) -> bool:
        """Executes command on hardware wallet device related to the selected actions."""
        if self.action_type in (ACTION_RECOVER_FROM_WORDS_CONV, ACTION_RECOVER_FROM_ENTROPY):

            device_id, cancelled = load_device_by_mnemonic(
                self.hw_type, self.hw_device_id_selected, self.hw_action_mnemonic_words, self.hw_action_pin,
                self.hw_action_use_passphrase, self.hw_action_label,
                self.hw_action_passphrase, self.hw_action_secondary_pin, parent_window=self.main_ui)

        elif self.action_type == ACTION_RECOVER_FROM_WORDS_SAFE:

            device_id, cancelled = recovery_device(self.hw_type, self.hw_device_id_selected, self.word_count,
                                                   self.hw_action_use_passphrase, self.hw_action_use_pin, self.hw_action_label, parent_window=self.main_ui)

        elif self.action_type == ACTION_INITIALIZE_NEW_SAFE:

            device_id, cancelled = reset_device(self.hw_type, self.hw_device_id_selected, self.word_count,
                                                self.hw_action_use_passphrase, self.hw_action_use_pin, self.hw_action_label, parent_window=self.main_ui)

        elif self.action_type == ACTION_WIPE_DEVICE:

            device_id, cancelled = wipe_device(self.hw_type, self.hw_device_id_selected, parent_window=self.main_ui)

        else:
            raise Exception('Invalid action.')

        if device_id and self.hw_device_id_selected and self.hw_device_id_selected != device_id:
            # if Trezor or Keepkey is wiped during the initialization then it gets a new device_id
            # update the deice id in the device combobox and a list associated with it
            self.hw_device_id_selected = device_id
            idx = self.cboDeviceInstance.currentIndex()
            if idx >= 0 and idx < len(self.hw_device_instances):
                self.hw_device_instances[idx][0] = device_id
                if self.hw_action_label is None:
                    self.hw_action_label = ''
                lbl = self.hw_action_label + ' (' + device_id + ')'
                self.cboDeviceInstance.setItemText(idx, lbl)

        if cancelled:
            self.warnMsg('Operation cancelled.')
            return False
        else:
            self.set_next_step(STEP_FINISHED)
            return True

    def apply_input_firmware_source(self) -> bool:
        ret = False
        if self.hw_firmware_source_type == 0:
            if not self.hw_firmware_source_file:
                self.errorMsg('Enter the file name of the firmware.')
            elif not os.path.isfile(self.hw_firmware_source_file):
                self.errorMsg(f'File \'{self.hw_firmware_source_file}\' does not exist.')
            else:
                ret = True
        elif self.hw_firmware_source_type == 1:
            if not self.hw_firmware_url_selected:
                self.errorMsg('No firmware selected.')
            else:
                ret = True

        if ret:
            self.set_next_step(STEP_UPLOAD_FIRMWARE)

        return ret

    def get_file_fingerprint(self, file_name, begin_offset):
        try:
            with open(file_name, 'rb') as fptr:
                data = fptr.read()
                return hashlib.sha256(data[begin_offset:]).hexdigest()
        except Exception:
            logging.exception('Exeption while counting firmware fingerprint')
            return None

    def verify_hw_firmware_fingerprint(self, hw_model: str, data: ByteString, valid_fingerprint: str) \
            -> Tuple[bool, str]:
        if hw_model == '1':
            cur_fp = hashlib.sha256(data[256:]).hexdigest()
            if valid_fingerprint and cur_fp != valid_fingerprint:
                return False, cur_fp
        return True, valid_fingerprint

    def apply_upload_firmware(self) -> bool:

        def do_wipe(ctrl, hw_client):
            ctrl.dlg_config_fun(dlg_title="Confirm wiping device.", show_progress_bar=False)
            ctrl.display_msg_fun('<b>Wiping device...</b><br>Read the messages displyed on your hardware wallet <br>'
                                 'and click the confirmation button when necessary.')
            hw_client.wipe_device()

        ret = False
        wiped = False
        try:
            while True:
                # in bootloader mode, there is not possibility do get the device_id; to know which of the devices has
                # to be flashed, user has to leave only one device in bootloader mode at the time of this step
                hw_clients, _ = get_device_list(hw_type=self.hw_type, allow_bootloader_mode=True)

                boot_clients = []
                for c in hw_clients:
                    try:
                        if c['bootloader_mode']:
                            boot_clients.append(c['client'])
                        else:
                            c['client'].close()
                    except Exception:
                        pass

                try:
                    if len(boot_clients) > 1:
                        raise Exception('There can be only one device in the bootloader mode at the time of updating '
                                        'firmware')
                    elif len(boot_clients) == 0:
                        raise Exception('Enable bootloader mode in your device')

                    hw_client = boot_clients[0]

                    wipe = self.chbWipeDevice.isChecked()
                    if wipe and not wiped:
                        try:
                            self.run_thread_dialog(do_wipe, (hw_client,), True, center_by_window=self)
                        except Exception as e:
                            msg = str(e)
                            if not re.match('.*disconnected*.', msg, re.IGNORECASE) and \
                                    not re.match('.*Could not write message \(error=400 str=LIBUSB_ERROR_PIPE\)', msg,
                                                 re.IGNORECASE):
                                raise

                        if self.queryDlg('Reconnect the device in bootloader mode and click "OK" to continue.',
                                         buttons=QMessageBox.Ok | QMessageBox.Cancel, default_button=QMessageBox.Ok,
                                         icon=QMessageBox.Information) != QMessageBox.Ok:
                            return False
                        else:
                            wiped = True
                            continue

                    ret = self.run_thread_dialog(self.apply_upload_firmware_thread, (hw_client, wipe))
                    if not ret:
                        raise Exception('Unknown error while uploading firmware')
                    else:
                        self.set_next_step(STEP_FINISHED)
                        break

                finally:
                    for c in boot_clients:
                        try:
                            c.close()
                        except Exception:
                            pass

        except Exception as e:
            msg = str(e).replace('<', '').replace('>', '')
            logging.exception('Error while uploading firmware')
            self.errorMsg(msg)

        return ret

    def apply_upload_firmware_thread(self, ctrl: CtrlObject, hw_client, wipe_data: bool) -> bool:
        ret = False
        ctrl.dlg_config_fun(dlg_title='Firmware update')
        firmware_fingerprint = None
        firmware_hw_model = None

        if self.hw_firmware_source_type == 0:
            local_file_path = self.hw_firmware_source_file
            with open(local_file_path, 'rb') as fptr:
                data = fptr.read()

        elif self.hw_firmware_source_type == 1:
            ctrl.display_msg_fun('Downloading firmware, please wait....')
            url = self.hw_firmware_url_selected.get('url')
            firmware_fingerprint = self.hw_firmware_url_selected.get("fingerprint")
            firmware_hw_model = self.hw_firmware_url_selected.get('model')
            file_name = os.path.basename(urllib.parse.urlparse(url).path)
            local_file_path = os.path.join(self.main_ui.app_config.cache_dir, file_name)

            response = urllib.request.urlopen(url, context=ssl._create_unverified_context())
            data = response.read()
            try:
                # save firmware file in cache
                with open(local_file_path, 'wb') as out_fptr:
                    out_fptr.write(data)
            except Exception as e:
                pass
        else:
            raise Exception('Invalid firmware source')

        if data:
            ctrl.display_msg_fun('<b>Uploading firmware...</b>'
                                 '<br>Click the confirmation button on your device if necessary.')
            with open(local_file_path, 'rb') as fptr:
                data = fptr.read()

                if self.hw_type == HWType.trezor:

                    try:
                        if data[:8] == b'54525a52' or data[:8] == b'54525a56':
                            data = binascii.unhexlify(data)
                    except Exception as e:
                        logging.exception('Error while decoding hex data.')
                        raise Exception(f'Error while decoding hex data: ' + str(e))

                    if data[:4] != b'TRZR' and data[:4] != b'TRZV':
                        raise Exception('TREZOR firmware header expected')

                elif self.hw_type == HWType.keepkey:

                    try:
                        if data[:8] == b'4b504b59':
                            data = binascii.unhexlify(data)
                    except Exception as e:
                        logging.exception('Error while decoding hex data.')
                        raise Exception(f'Error while decoding hex data: ' + str(e))

                    if data[:4] != b'KPKY':
                        raise Exception('KeepKey firmware header expected')

                if firmware_fingerprint and firmware_hw_model:
                    valid, cur_fp = self.verify_hw_firmware_fingerprint(firmware_hw_model, data, firmware_fingerprint)

                    if not valid:
                        raise Exception(f'Firmware fingerpring mismatch, expected: '
                                        f'{firmware_fingerprint}, current: {cur_fp}')

                ret = hw_client.firmware_update(fp=BytesIO(data))

        return ret

    @pyqtSlot(bool)
    def on_btnNext_clicked(self, clicked):
        success = False
        if self.current_step == STEP_SELECT_DEVICE_TYPE:

            success = self.apply_step_select_device_type()

        elif self.current_step == STEP_SELECT_DEVICE_INSTANCE:

            success = self.apply_step_select_device_id()

        elif self.current_step == STEP_SELECT_ACTION:

            success = self.apply_step_select_action()

        elif self.current_step == STEP_INPUT_NUMBER_OF_WORDS:

            success = self.apply_step_select_number_of_words()

        elif self.current_step == STEP_INPUT_ENTROPY:

            success = self.apply_step_input_entropy()

        elif self.current_step == STEP_INPUT_WORDS:

            success = self.apply_step_input_words()

        elif self.current_step == STEP_INPUT_HW_OPTIONS:

             success = self.apply_step_input_hw_options()

        elif self.current_step == STEP_FINISHED:

            self.close()

        elif self.current_step == STEP_INPUT_FIRMWARE_SOURCE:

            success = self.apply_input_firmware_source()

        elif self.current_step == STEP_UPLOAD_FIRMWARE:

            success = self.apply_upload_firmware()

        else:
            raise Exception("Internal error: invalid step.")

        if success:
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
            msg_text = ''

            if self.hw_type == HWType.ledger_nano_s:
                msg_text = '<span><b>Important! Start your Ledger Nano S wallet in recovery mode:</b></span>' \
                           '<ol><li>Clear the device by selecting the \'Settings->Device->Reset all\' menu item.</li>' \
                           '<li>Power the device off.</li>' \
                           '<li>Power the device on while holding down the right-hand physical button.</li>' \
                           '</ol>'

            if sys.platform == 'linux':
                if msg_text:
                    msg_text += '<br>'
                msg_text += '<b>Important!</b> To make hardware wallet devices visible on linux, ' \
                            'add the appropriate udev rules (<a href="udev_linux">see the details</a>).'
            self.lblStepDeviceTypeMessage.setText(msg_text)

        elif self.current_step == STEP_SELECT_DEVICE_INSTANCE:

            self.lblStepDeviceInstanceMessage.setText("<b>Select which '%s' device you want to use</b>" %
                                                      HWType.get_desc(self.hw_type))

        elif self.current_step == STEP_SELECT_ACTION:
            self.rbActRecoverMnemonicWords.setVisible(self.hw_type != HWType.trezor)
            self.rbActRecoverHexEntropy.setVisible(self.hw_type != HWType.trezor)
            if self.hw_type == HWType.ledger_nano_s:
                # turn off options not applicable for ledger walltes
                self.rbActRecoverWordsSafe.setDisabled(True)
                self.rbActInitializeNewSeed.setDisabled(True)
                self.rbActWipeDevice.setDisabled(True)
                self.rbActUploadFirmware.setDisabled(True)
                if self.rbActRecoverWordsSafe.isChecked() or self.rbActInitializeNewSeed.isChecked() or \
                   self.rbActWipeDevice.isChecked():
                    self.rbActRecoverMnemonicWords.setChecked(True)
            else:
                self.rbActRecoverWordsSafe.setEnabled(True)
                self.rbActInitializeNewSeed.setEnabled(True)
                self.rbActWipeDevice.setEnabled(True)
                self.rbActUploadFirmware.setEnabled(True)

            if self.action_type in (ACTION_RECOVER_FROM_WORDS_CONV, ACTION_RECOVER_FROM_ENTROPY):
                self.lblActionTypeMessage.setText(
                    '<span style="color:red;font-weight:bold">This feature should only be used on offline systems '
                    'which will never be connected to the internet.</span>')
            else:
                self.lblActionTypeMessage.setText('')

        elif self.current_step in (STEP_INPUT_NUMBER_OF_WORDS, STEP_INPUT_ENTROPY):

            if self.action_type in (ACTION_RECOVER_FROM_WORDS_CONV, ACTION_RECOVER_FROM_WORDS_SAFE,
                                    ACTION_INITIALIZE_NEW_SAFE):
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
            else:
                raise Exception('Invalid action type')

        elif self.current_step in (STEP_INPUT_WORDS,):
            self.lblStepWordListMessage2.setVisible(True)
            if self.action_type == ACTION_RECOVER_FROM_WORDS_CONV:
                self.grid_model.set_read_only(False)
                self.lblStepWordListTitle.setText('<b>Enter the recovery seed words</b>')
                self.viewMnemonic.setStyleSheet('')
            elif self.action_type == ACTION_RECOVER_FROM_ENTROPY:
                self.grid_model.set_read_only(True)
                self.lblStepWordListMessage2.setVisible(False)
                self.lblStepWordListTitle.setText('<b>Below are the seed words for the provided hexadecimal entropy</b>')
                self.viewMnemonic.setStyleSheet('background-color:#e6e6e6')
            else:
                raise Exception('Invalid action type')

            # estimate words columns widths
            width = self.viewMnemonic.width()
            width = int((width - (2 * 40)) / 2)
            self.viewMnemonic.setModel(self.grid_model)
            self.viewMnemonic.setColumnWidth(0, 40)
            self.viewMnemonic.setColumnWidth(1, width)
            self.viewMnemonic.setColumnWidth(2, 40)

        elif self.current_step == STEP_INPUT_HW_OPTIONS:
            self.edtHwOptionsDeviceLabel.setPlaceholderText('My %s' % HWType.get_desc(self.hw_type))
            if self.action_type in (ACTION_RECOVER_FROM_WORDS_CONV, ACTION_RECOVER_FROM_ENTROPY):
                if self.entropy:
                    self.lblHwOptionsMessage1.setText('Your recovery seed hexadecimal entropy: ' + self.entropy.hex())
                self.fraDetails.setVisible(self.hw_options_details_visible)

                if self.hw_options_details_visible:
                    self.btnHwOptionsDetails.setText('Hide preview')
                else:
                    self.btnHwOptionsDetails.setText('Show prewiew')

                self.edtHwOptionsPIN.setVisible(self.chbHwOptionsUsePIN.isChecked())
                self.btnShowPIN.setVisible(self.chbHwOptionsUsePIN.isChecked())
                self.btnHwOptionsDetails.setVisible(True)

            elif self.action_type in (ACTION_RECOVER_FROM_WORDS_SAFE, ACTION_INITIALIZE_NEW_SAFE):
                # trezor/keepkey device will ask for pin, so we'll hide the PIN editbox
                self.edtHwOptionsPIN.setVisible(False)
                self.btnShowPIN.setVisible(False)
                self.btnHwOptionsDetails.setVisible(False)
            else:
                raise Exception('Invalid action.')

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

        elif self.current_step == STEP_INPUT_FIRMWARE_SOURCE:

            if self.hw_type == HWType.trezor:
                self.gbTrezorModel.setVisible(True)
                if self.rbTrezorModelOne.isChecked():
                    self.hw_model = '1'
                else:
                    self.hw_model = 'T'
            else:
                self.gbTrezorModel.setVisible(False)
                self.hw_model = '1'

            if self.rbFirmwareSourceLocalFile.isChecked():
                self.hw_firmware_source_type = 0
                self.tabFirmwareWebSources.setVisible(False)
                self.edtFirmwareNotes.setVisible(False)
                self.wdgFirmwareFile.setVisible(True)
            else:
                self.hw_firmware_source_type = 1
                self.tabFirmwareWebSources.setVisible(True)
                self.edtFirmwareNotes.setVisible(True)
                self.wdgFirmwareFile.setVisible(False)
                if not self.hw_firmware_web_sources:
                    self.load_remote_firmware_list()

                if self.hw_type != self.hw_firmware_last_hw_type or self.hw_model != self.hw_firmware_last_hw_model:
                    self.display_firmware_list()
                    self.hw_firmware_last_hw_type = self.hw_type
                    self.hw_firmware_last_hw_model = self.hw_model

        elif self.current_step == STEP_UPLOAD_FIRMWARE:

            if self.hw_type == HWType.trezor:

                if self.hw_model == 'T':
                    msg_text = '<span style="color:red"><b>WARNING: Before updating firmware, please make sure that ' \
                               'you have backup of recovery seed.</b></span><br><br>' \
                               '<span><b>Start your Trezor T in bootloader mode:</b></span>' \
                               '<ol><li>Disconnect TREZOR.</li>' \
                               '<li>When connecting, slide your finger on the display.</li>' \
                               '<li>Confirm connection in bootloader mode on device.</li>' \
                               '</ol><br>' \
                               'Then click "<b>Continue</b>" to upload firmware.'
                    self.lblUploadFirmwareMessage.setText(msg_text)

                elif self.hw_model == '1':
                    msg_text = '<span style="color:red"><b>WARNING: Before updating firmware, please make sure that ' \
                               'you have backup of recovery seed.</b></span><br><br>' \
                               '<span><b>Start your Trezor One in bootloader mode:</b></span>' \
                               '<ol><li>Disconnect TREZOR.</li>' \
                               '<li>When connecting, hold both buttons pressed.</li>' \
                               '</ol><br>' \
                               'Then click "<b>Continue</b>" to upload firmware.'
                    self.lblUploadFirmwareMessage.setText(msg_text)

                else:
                    self.errorMsg('Invalid model of the selected device...')

            elif self.hw_type == HWType.keepkey:
                msg_text = '<span style="color:red"><b>WARNING: Before updating firmware, please make sure that ' \
                           'you have backup of recovery seed.</b></span><br><br>' \
                           '<span><b>Start your Keepkey in bootloader mode:</b></span>' \
                           '<ol><li>Disconnect Keepkey.</li>' \
                           '<li>When connecting, hold button pressed.</li>' \
                           '</ol><br>' \
                           'Then click "<b>Continue</b>" to upload firmware.'
                self.lblUploadFirmwareMessage.setText(msg_text)

        elif self.current_step == STEP_FINISHED:
            if self.action_type == ACTION_UPLOAD_FIRMWARE:
                self.lblStepSummaryTitle.setText('﻿<h2>Firmware upload finished.</h2><h3>You can now initialize '
                                                 'your device with seed words.</h3><span>Important: unplug and '
                                                 'reconnect the device.</span>')
            else:
                self.lblStepSummaryTitle.setText('<h2>Operation successfully finished.</h2>')

    @pyqtSlot(bool)
    def on_btnCancel_clicked(self):
        self.close()

    def connect_hardware_wallet(self):
        return self.main_ui.connect_hardware_wallet()

    def set_word_count(self, word_count, checked=True):
        if checked:
            self.word_count = word_count
            self.grid_model.set_words_count(word_count)

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
            bip32_path_n = dash_utils.bip32_path_string_to_n(bip32_path)
            if len(bip32_path_n) > 0:
                last_idx = bip32_path_n[-1]
                addresses = []
                for idx in range(10):
                    bip32_path_n[-1] = last_idx + idx
                    pk = self.get_bip32_private_key(bip32_path_n, bip32_master_key)
                    pubkey = bitcoin.privkey_to_pubkey(pk)
                    addr = pubkey_to_address(pubkey, self.app_config.dash_network)
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

        control_trezor_keepkey_libs(self.hw_type)
        self.main_ui.disconnect_hardware_wallet()  # disconnect hw if it's open in the main window
        self.hw_device_instances.clear()
        self.cboDeviceInstance.clear()

        if self.hw_type in (HWType.trezor, HWType.keepkey):

            devs, _ = get_device_list(self.hw_type, return_clients=False)
            for dev in devs:
                device_id = dev['device_id']
                label = dev['desc']
                model = dev['model']
                self.hw_device_instances.append([device_id, label, model])
                self.cboDeviceInstance.addItem(label)

        elif self.hw_type == HWType.ledger_nano_s:
            from btchip.btchipComm import getDongle
            from btchip.btchipException import BTChipException
            try:
                dongle = getDongle()
                if dongle:
                    lbl = HWType.get_desc(self.hw_type)
                    self.hw_device_instances.append([None, lbl, None])
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

    @pyqtSlot(str)
    def on_lblStepDeviceTypeMessage_linkActivated(self, link_text):
        text = '<h4>To enable hardware wallet devices on your linux system execute the following commands from ' \
               'the command line.</h4>' \
               '<b>For Trezor hardware wallets:</b><br>' \
               '<code>echo "SUBSYSTEM==\\"usb\\", ATTR{idVendor}==\\"534c\\", ATTR{idProduct}==\\"0001\\", ' \
               'TAG+=\\"uaccess\\", TAG+=\\"udev-acl\\", SYMLINK+=\\"trezor%n\\"" | ' \
               'sudo tee /etc/udev/rules.d/51-trezor-udev.rules<br>' \
               'sudo udevadm trigger<br>'\
               'sudo udevadm control --reload-rules' \
               '</code><br><br>' \
               '<b>For Keepkey hardware wallets:</b><br>' \
               '<code>echo "SUBSYSTEM==\\"usb\\", ATTR{idVendor}==\\"2b24\\", ATTR{idProduct}==\\"0001\\", ' \
               'MODE=\\"0666\\", GROUP=\\"dialout\\", SYMLINK+=\\"keepkey%n\\"" | ' \
               'sudo tee /etc/udev/rules.d/51-usb-keepkey.rules'\
               '<br>echo "KERNEL==\\"hidraw*\\", ATTRS{idVendor}==\\"2b24\\", ATTRS{idProduct}==\\"0001\\", ' \
               'MODE=\\"0666\\", GROUP=\\"dialout\\"" | sudo tee -a /etc/udev/rules.d/51-usb-keepkey.rules<br>' \
               'sudo udevadm trigger<br>'\
               'sudo udevadm control --reload-rules' \
               '</code><br><br>' \
               '<b>For Ledger hardware wallets:</b><br>' \
               '<code>echo "SUBSYSTEMS==\\"usb\\", ATTRS{idVendor}==\\"2581\\", ATTRS{idProduct}==\\"1b7c\\", ' \
               'MODE=\\"0660\\", GROUP=\\"plugdev\\"" | sudo tee /etc/udev/rules.d/20-hw1.rules<br>' \
               'echo "SUBSYSTEMS==\\"usb\\", ATTRS{idVendor}==\\"2581\\", ATTRS{idProduct}==\\"2b7c\\", ' \
               'MODE=\\"0660\\", GROUP=\\"plugdev\\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules<br>' \
               'echo "SUBSYSTEMS==\\"usb\\", ATTRS{idVendor}==\\"2581\\", ATTRS{idProduct}==\\"3b7c\\", ' \
               'MODE=\\"0660\\", GROUP=\\"plugdev\\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules<br>' \
               'echo "SUBSYSTEMS==\\"usb\\", ATTRS{idVendor}==\\"2581\\", ATTRS{idProduct}==\\"4b7c\\", ' \
               'MODE=\\"0660\\", GROUP=\\"plugdev\\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules<br>' \
               'echo "SUBSYSTEMS==\\"usb\\", ATTRS{idVendor}==\\"2581\\", ATTRS{idProduct}==\\"1807\\", ' \
               'MODE=\\"0660\\", GROUP=\\"plugdev\\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules<br>' \
               'echo "SUBSYSTEMS==\\"usb\\", ATTRS{idVendor}==\\"2581\\", ATTRS{idProduct}==\\"1808\\", ' \
               'MODE=\\"0660\\", GROUP=\\"plugdev\\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules<br>' \
               'echo "SUBSYSTEMS==\\"usb\\", ATTRS{idVendor}==\\"2c97\\", ATTRS{idProduct}==\\"0000\\", ' \
               'MODE=\\"0660\\", GROUP=\\"plugdev\\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules<br>' \
               'echo "SUBSYSTEMS==\\"usb\\", ATTRS{idVendor}==\\"2c97\\", ATTRS{idProduct}==\\"0001\\", ' \
               'MODE=\\"0660\\", GROUP=\\"plugdev\\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules<br>' \
               'sudo udevadm trigger<br>'\
               'sudo udevadm control --reload-rules' \
               '</code>'
        style_sheet = 'font-size:12px'
        show_doc_dlg(self, text, style_sheet, 'Help')

    @pyqtSlot(bool)
    def on_rbFirmwareSourceInternet_toggled(self, checked):
        if checked:
            self.hw_firmware_source_type = 1
            self.update_current_tab()

    @pyqtSlot(bool)
    def on_rbFirmwareSourceLocalFile_toggled(self, checked):
        if checked:
            self.hw_firmware_source_type = 0
            self.update_current_tab()

    @pyqtSlot(bool)
    def on_rbTrezorModelOne_toggled(self, checked):
        if checked:
            self.hw_model = '1'
            self.update_current_tab()

    @pyqtSlot(bool)
    def on_rbTrezorModelT_toggled(self, checked):
        if checked:
            self.hw_model = 'T'
            self.update_current_tab()

    @pyqtSlot(bool)
    def on_btnChooseFirmwareFile_clicked(self, checked):
        last_file = app_cache.get_value(CACHE_ITEM_LAST_FIRMWARE_FILE, '', str)
        dir = os.path.dirname(last_file)

        file_name = WndUtils.open_file_query(self, self.app_config,
                                             message='Enter the path to the firmware file',
                                             directory=dir,
                                             filter="All Files (*);;BIN files (*.bin)",
                                             initial_filter="BIN files (*.bin)")
        if file_name:
            app_cache.set_value(CACHE_ITEM_LAST_FIRMWARE_FILE, file_name)
            self.hw_firmware_source_file = file_name
            self.edtFirmareFilePath.setText(file_name)
            if self.hw_type == HWType.trezor and self.hw_model == '1':
                fp = self.get_file_fingerprint(file_name, 256)

    @pyqtSlot(str)
    def on_edtFirmwareFilePath_textChanged(self, text):
        self.hw_firmware_source_file = text

    def load_remote_firmware_list(self):
        self.run_thread_dialog(self.load_remote_firmware_list_thread, (), center_by_window=self)

    def load_remote_firmware_list_thread(self, ctrl: CtrlObject):
        ctrl.dlg_config_fun(dlg_title='Downloading firmware sources', max_width=self.width())

        def load_from_url(base_url: str, list_url, device: str = None, official: bool = False, model: str = None):
            ctrl.display_msg_fun(f'<b>Downloading firmware list from:</b><br>{list_url}<br><br>Please wait...')
            response = urllib.request.urlopen(list_url, context=ssl._create_unverified_context())
            contents = response.read()
            fl = simplejson.loads(contents)
            for f in fl:
                url = f.get('url')
                if url.startswith('/') and base_url.endswith('/'):
                    f['url'] = base_url + url[1:]
                elif not base_url.endswith('/') and not url.startswith('/'):
                    f['url'] = base_url + '/' + url
                else:
                    f['url'] = base_url + url
                if not f.get('device') and device:
                    f['device'] = device
                if not f.get('official') and official:
                    f['official'] = official
                if not f.get('model') and model:
                    f['model'] = model
                self.hw_firmware_web_sources.append(f)

        try:
            self.hw_firmware_url_selected = None
            self.hw_firmware_web_sources.clear()
            project_url = app_defs.PROJECT_URL.replace('//github.com', '//raw.githubusercontent.com')
            if not project_url.endswith('/'):
                project_url += '/'
            project_url += 'master/'

            url = urllib.parse.urljoin(project_url, 'hardware-wallets/firmware/firmware-sources.json')
            ctrl.display_msg_fun(f'<b>Downloading firmware sources from:</b><br>{url}<br><br>Please wait...')
            response = urllib.request.urlopen(url, context=ssl._create_unverified_context())
            contents = response.read()
            srcs = simplejson.loads(contents)
            for s in srcs:
                try:
                    official = s.get('official')
                    device = s.get('device')
                    model = s.get('model')
                    url = s.get('url')
                    url_base = s.get('url_base')
                    if not url_base:
                        url_base = project_url

                    if not re.match('\s*http://', url, re.IGNORECASE):
                        url = urllib.parse.urljoin(url_base, url)

                    load_from_url(base_url=url_base, list_url=url, device=device, official=official,
                                  model=model)

                except Exception:
                    logging.exception('Exception while processing firmware source')
        except Exception as e:
            logging.error('Error while loading hardware-wallets/firmware/releases.json file from GitHub: ' + str(e))
            raise

    def display_firmware_list(self):
        """Display list of firmwares available for the currently selected hw type."""

        def item(value):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            return item

        self.hw_firmware_url_selected = None
        self.hw_firmware_web_sources_cur_hw.clear()
        for f in self.hw_firmware_web_sources:
            if f.get('device').lower() == self.hw_type.lower() and \
                    (self.hw_type != HWType.trezor or self.hw_model == f.get('model')):
                self.hw_firmware_web_sources_cur_hw.append(f)

        self.tabFirmwareWebSources.setRowCount(len(self.hw_firmware_web_sources_cur_hw))
        for row, f in enumerate(self.hw_firmware_web_sources_cur_hw):
            version = f.get('version', None)
            if isinstance(version, list):
                version = '.'.join(str(x) for x in version)
            else:
                version = str(version)
            if f.get('testnet', False):
                testnet = 'Yes'
            else:
                testnet = 'No'
            if f.get('official', False):
                official = 'Yes'
            else:
                official = 'Custom/Unofficial'

            if f.get('device').lower() == 'trezor':
                if f.get('model', '1') == '1':
                    model = 'Trezor 1'
                else:
                    model = 'Trezor T'
            else:
                model = str(f.get('model', 1))

            self.tabFirmwareWebSources.setItem(row, 0, item(version))
            self.tabFirmwareWebSources.setItem(row, 1, item(model))
            self.tabFirmwareWebSources.setItem(row, 2, item(official))
            self.tabFirmwareWebSources.setItem(row, 3, item(testnet))
            self.tabFirmwareWebSources.setItem(row, 4, item(str(f.get('url', ''))))
            self.tabFirmwareWebSources.setItem(row, 5, item(str(f.get('fingerprint', ''))))
        self.tabFirmwareWebSources.resizeColumnsToContents()
        if len(self.hw_firmware_web_sources_cur_hw) > 0:
            self.tabFirmwareWebSources.selectRow(0)
            # self.on_tabFirmwareWebSources_itemSelectionChanged isnn't always fired up if there was previously
            # selected row, so we need to force selecting new row:
            self.select_firmware(0)
        else:
            sm = self.tabFirmwareWebSources.selectionModel()
            s = QItemSelection()
            sm.select(s, QItemSelectionModel.Clear | QItemSelectionModel.Rows)
            # force deselect firmware:
            self.select_firmware(-1)

        max_col_width = 230
        for idx in range(self.tabFirmwareWebSources.columnCount()):
            w = self.tabFirmwareWebSources.columnWidth(idx)
            if w > max_col_width:
                self.tabFirmwareWebSources.setColumnWidth(idx, max_col_width)

    def on_tabFirmwareWebSources_itemSelectionChanged(self):
        idx = self.tabFirmwareWebSources.currentIndex()
        row_index = -1
        if idx:
            row_index = idx.row()
        self.select_firmware(row_index)

    def select_firmware(self, row_index):
        if row_index >= 0:
            item = self.tabFirmwareWebSources.item(row_index, 0)
            if item:
                idx = self.tabFirmwareWebSources.indexFromItem(item)
                if idx:
                    row = idx.row()
                    if 0 <= row <= len(self.hw_firmware_web_sources_cur_hw):
                        cfg = self.hw_firmware_web_sources_cur_hw[row]
                        self.hw_firmware_url_selected = cfg
                        notes = cfg.get('notes','')
                        chl = self.hw_firmware_web_sources_cur_hw[row].get('changelog','')
                        if notes:
                            chl += '\n' + notes
                        self.edtFirmwareNotes.setText(chl)
                        return
        self.hw_firmware_url_selected = None
        self.edtFirmwareNotes.clear()


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
