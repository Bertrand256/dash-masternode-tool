#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
from __future__ import annotations
import logging
import threading
from enum import Enum
from functools import partial

from PyQt5 import QtWidgets, QtCore
from typing import List, Optional, Callable, ByteString, Tuple, Any, Union
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
        if hw_type_str.lower() == HWType.trezor.value.lower():
            return HWType.trezor
        elif hw_type_str.lower() == HWType.keepkey.value.lower():
            return HWType.keepkey
        elif hw_type_str.lower() == HWType.ledger_nano.value.lower():
            return HWType.ledger_nano
        return None


class HWModel(Enum):
    trezor_one = 'TREZOR_ONE'
    trezor_t = 'TREZOR_T'
    keepkey = 'KEEPKEY'
    ledger_nano_s = 'LEDGER_NANO_S'
    ledger_nano_x = 'LEDGER_NANO_X'

    @staticmethod
    def get_hw_type(hw_model: HWModel) -> HWType:
        if hw_model in (HWModel.trezor_one, HWModel.trezor_t):
            return HWType.trezor
        elif hw_model == HWModel.keepkey:
            return HWType.keepkey
        elif hw_model in (HWModel.ledger_nano_s, HWModel.ledger_nano_s):
            return HWType.ledger_nano

    @staticmethod
    def get_model_str(hw_model: HWModel) -> str:
        return {
            HWModel.trezor_one: '1',
            HWModel.trezor_t: 'T',
            HWModel.keepkey: 'keepkey',
            HWModel.ledger_nano_s: 's',
            HWModel.ledger_nano_x: 'z'
        }[hw_model]

    @staticmethod
    def from_string(hw_type: HWType, hw_model_str: str) -> Optional['HWModel']:
        if hw_type == HWType.trezor:
            if hw_model_str.lower() == HWModel.get_model_str(HWModel.trezor_one).lower():
                return HWModel.trezor_one
            elif hw_model_str.lower() == HWModel.get_model_str(HWModel.trezor_t).lower():
                return HWModel.trezor_t
        elif hw_type == HWType.keepkey:
            return HWModel.keepkey
        elif hw_type == HWType.ledger_nano:
            if hw_model_str.lower() == HWModel.get_model_str(HWModel.ledger_nano_s).lower():
                return HWModel.ledger_nano_s
            elif hw_model_str.lower() == HWModel.get_model_str(HWModel.ledger_nano_x).lower():
                return HWModel.ledger_nano_x
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
    def __init__(self, hw_type: HWType, device_id: Optional[str] = None, device_label: Optional[str] = None,
                 model_symbol: Optional[str] = None, firmware_version: Optional[str] = None,
                 hw_client: Any = None, bootloader_mode: Optional[bool] = None,
                 transport_id: Optional[Union[object, str]] = None,
                 initialized: Optional[bool] = None, locked: Optional[bool] = False):
        self.transport_id = transport_id
        self.hw_type: HWType = hw_type
        self.device_id = device_id
        self.device_label = device_label
        self.firmware_version = firmware_version
        self.model_symbol = model_symbol
        self.hw_client = hw_client
        self.bootloader_mode = bootloader_mode
        self.initialized = initialized
        self.locked = locked

    def get_description(self):
        if self.hw_type == HWType.trezor:
            desc = 'Trezor'
            if self.model_symbol:
                desc += ' ' + {'1': 'One'}.get(self.model_symbol, self.model_symbol)
        else:
            desc = self.model_symbol
        if self.device_label:
            desc += ' (' + self.device_label + ')'
        if not desc:
            desc = HWType.get_desc(self.hw_type)
        if self.bootloader_mode:
            additional = 'bootloader mode'
        elif not self.initialized:
            additional = 'not initialized'
        else:
            additional = ''
        if additional:
            desc += ' [' + additional + ']'
        return desc

    def get_hw_model(self) -> Optional[HWModel]:
        return HWModel.from_string(self.hw_type, self.model_symbol)


class HWFirmwareWebLocation:
    def __init__(self, version: str, url: str, device: HWType, official: bool, model: Optional[str],
                 fingerprint: Optional[str], testnet_support: bool, notes: Optional[str] = None,
                 changelog: Optional[str] = None, latest: bool = False):
        self.version: str = version
        self.url: str = url
        self.device: HWType = device
        self.official: bool = official
        self.model: Optional[str] = model
        self.testnet_support: bool = testnet_support
        self.local_file: Optional[str] = None
        self.notes: Optional[str] = notes
        self.fingerprint: Optional[str] = fingerprint
        self.changelog: Optional[str] = changelog
        self.latest: bool = latest


def clean_bip32_path(bip32_path):
    # Keepkey and Ledger don't accept BIP32 "m/" prefix
    bip32_path.strip()
    if bip32_path.lower().find('m/') >= 0:
        # removing m/ prefix because of keepkey library
        bip32_path = bip32_path[2:]
    return bip32_path


def ask_for_pin_callback(msg, hide_numbers=True, parent_window: Optional[QWidget] = None):
    def dlg():
        ui = hw_pin_dlg.HardwareWalletPinDlg(msg, hide_numbers=hide_numbers, parent_window=parent_window)
        if ui.exec_():
            return ui.pin
        else:
            return None

    if threading.current_thread() != threading.main_thread():
        return WndUtils.call_in_main_thread(dlg)
    else:
        return dlg()


def ask_for_martix_element_callback(msg, columns: int = 3, parent_window: Optional[QWidget] = None):
    # noinspection SqlResolve
    def dlg():
        ui = hw_pin_dlg.HardwareWalletPinDlg(msg, hide_numbers=True, window_title='Enter element of seed word',
                                             max_length=1, button_heights=35, parent_window=parent_window,
                                             columns=columns)
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


def ask_for_word_callback(msg: str, wordlist: List[str], parent_window: Optional[QWidget] = None) -> str:
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

