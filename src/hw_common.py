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
                 device_model: Optional[str], device_version: Optional[str],
                 client: Any, bootloader_mode: bool, transport: Optional[object]):
        self.transport = transport
        self.hw_type: HWType = hw_type
        self.device_id = device_id
        self.device_label = device_label
        self.device_version = device_version
        self.device_model = device_model
        self.client = client
        self.bootloader_mode = bootloader_mode

    def get_description(self, show_hw_type: bool = False):
        desc = self.device_model
        if self.device_label:
            desc += ' (' + self.device_label +')'
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


def select_hw_device(parent, label: str, devices: List[str]) -> Optional[int]:
    """
    Invokes dialog for selecting the particular instance of hardware wallet device.
    """
    # todo: adapt to refactorings
    # dlg = SelectHWDevice(parent, label, devices)
    # if dlg.exec_():
    #     return dlg.device_selected_index
    return None


class HWSessionBase(QObject):
    def __init__(self, app_config: Optional['AppConfig']):
        super().__init__()
        self._app_config = app_config

    def get_hw_client(self):
        return None

    @property
    def hw_client(self):
        return self.get_hw_client()

    @property
    def hw_coin_name(self):
        return self._app_config.hw_coin_name

    @property
    def is_testnet(self):
        return self._app_config.is_testnet()

    @property
    def dash_network(self):
        return self._app_config.dash_network

    @property
    def tx_cache_dir(self):
        return self._app_config.tx_cache_dir

    @property
    def app_config(self):
        return self._app_config

    @app_config.setter
    def app_config(self, app_config):
        self._app_config = app_config

    @property
    def dashd_intf(self):
        return self.__dashd_intf

    def set_dashd_intf(self, dashd_intf):
        self.__dashd_intf = dashd_intf

    def connect_hardware_wallet(self) -> Optional[object]:
        raise Exception('Not connected')

    def disconnect_hardware_wallet(self) -> None:
        raise Exception('Not connected')

