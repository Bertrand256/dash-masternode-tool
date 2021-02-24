#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import logging
import threading
from enum import Enum
from functools import partial

from PyQt5 import QtWidgets, QtCore
from typing import List, Optional, Callable, ByteString, Tuple, Any
from PyQt5.QtCore import QObject, pyqtSlot
from PyQt5.QtWidgets import QDialog, QCheckBox, QRadioButton, QWidget

import hw_pass_dlg
import hw_pin_dlg
import hw_word_dlg
from wnd_utils import WndUtils


DEFAULT_HW_BUSY_MESSAGE = '<b>Complete the action on your hardware wallet device</b>'
DEFAULT_HW_BUSY_TITLE = 'Please confirm'

PASSPHRASE_ON_DEVICE = object()


class HWPinException(Exception):
    def __init__(self, msg):
        self.msg = msg


class HWNotConnectedException(Exception):
    def __init__(self, msg: str = None):
        if not msg:
            msg = 'Not connected to a hardware wallet'
        Exception.__init__(self, msg)


class HWType(Enum):
    trezor = 'TREZOR'
    keepkey = 'KEEPKEY'
    ledger_nano = 'LEDGERNANOS'

    @staticmethod
    def get_desc(hw_type):
        if hw_type == HWType.trezor:
            return 'Trezor'
        elif hw_type == HWType.keepkey:
            return 'KeepKey'
        elif hw_type == HWType.ledger_nano:
            return 'Ledger Nano'
        else:
            return '???'

    @staticmethod
    def from_string(hw_type_str: str) -> Optional['HWType']:
        if hw_type_str == HWType.trezor.value:
            return HWType.trezor
        elif hw_type_str == HWType.keepkey.value:
            return HWType.keepkey
        elif hw_type_str == HWType.ledger_nano.value:
            return HWType.ledger_nano
        return None


def get_hw_type_from_client(hw_client) -> HWType:
    """
    Return hardware wallet type (HWType) based on reference to a hw client.
    """
    if hw_client:
        t = type(hw_client).__name__

        if t.lower().find('trezor') >= 0:
            return HWType.trezor
        elif t.lower().find('keepkey') >= 0:
            return HWType.keepkey
        elif t.lower().find('btchip') >= 0:
            return HWType.ledger_nano
        else:
            raise Exception('Unknown hardware wallet type')
    else:
        raise Exception('Hardware wallet not connected')


class HWDevice(object):
    """
    Represents a hardware wallet device connected to the computer.
    """
    def __init__(self, hw_type: HWType, device_id: Optional[str], device_label: Optional[str],
                 device_model: Optional[str], firmware_version: Optional[str],
                 hw_client: Any, bootloader_mode: bool, transport: Optional[object]):
        self.transport = transport
        self.hw_type: HWType = hw_type
        self.device_id = device_id
        self.device_label = device_label
        self.firmware_version = firmware_version
        self.device_model = device_model
        self.hw_client = hw_client
        self.bootloader_mode = bootloader_mode

    def get_description(self):
        if self.hw_type == HWType.trezor:
            desc = 'Trezor ' + {'1': 'One'}.get(self.device_model, self.device_model)
        else:
            desc = self.device_model
        if self.device_label:
            desc += ' (' + self.device_label + ')'
        if not desc:
            desc = HWType.get_desc(self.hw_type)
        return desc


def clean_bip32_path(bip32_path):
    # Keepkey and Ledger don't accept BIP32 "m/" prefix
    bip32_path.strip()
    if bip32_path.lower().find('m/') >= 0:
        # removing m/ prefix because of keepkey library
        bip32_path = bip32_path[2:]
    return bip32_path


def ask_for_pin_callback(msg, hide_numbers=True):
    def dlg():
        ui = hw_pin_dlg.HardwareWalletPinDlg(msg, hide_numbers=hide_numbers)
        if ui.exec_():
            return ui.pin
        else:
            return None

    if threading.current_thread() != threading.main_thread():
        return WndUtils.call_in_main_thread(dlg)
    else:
        return dlg()


def ask_for_pass_callback(pass_available_on_device: bool = False):
    def dlg():
        ui = hw_pass_dlg.HardwareWalletPassDlg(pass_available_on_device)
        if ui.exec_():
            if ui.getEnterOnDevice():
                return PASSPHRASE_ON_DEVICE
            else:
                return ui.getPassphrase()
        else:
            return None

    if threading.current_thread() != threading.main_thread():
        return WndUtils.call_in_main_thread(dlg)
    else:
        return dlg()


def ask_for_word_callback(msg: str, wordlist: List[str]) -> str:
    def dlg():
        ui = hw_word_dlg.HardwareWalletWordDlg(msg, wordlist)
        if ui.exec_():
            return ui.get_word()
        else:
            return None

    if threading.current_thread() != threading.main_thread():
        return WndUtils.call_in_main_thread(dlg)
    else:
        return dlg()


class HWSessionBase(QObject):
    def __init__(self):
        super().__init__()

    def get_hw_client(self):
        return None

    @property
    def hw_client(self):
        return self.get_hw_client()

    def connect_hardware_wallet(self) -> Optional[object]:
        raise Exception('Not connected')

    def disconnect_hardware_wallet(self) -> None:
        raise Exception('Not connected')

