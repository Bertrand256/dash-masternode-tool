#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import base64
import threading
from functools import partial

import bitcoin
from PyQt5 import QtWidgets, QtCore
from typing import List, Optional, Callable, ByteString, Tuple
from PyQt5.QtWidgets import QDialog, QCheckBox, QRadioButton
import hw_pass_dlg
import hw_pin_dlg
import hw_word_dlg
from app_defs import HWType
from app_utils import SHA256
from thread_utils import EnhRLock
from wnd_utils import WndUtils


class HardwareWalletCancelException(Exception):
    pass


class HardwareWalletPinException(Exception):
    def __init__(self, msg):
        self.msg = msg


class HwSessionInfo(object):
    def __init__(self,
                 get_hw_client_function: Callable[[], object],
                 hw_connect_function: Callable[[object], None],
                 hw_disconnect_function: Callable[[], None],
                 app_config: object,
                 dashd_intf: object):
        self.__locks = {}  # key: hw_client, value: EnhRLock
        self.__app_config = app_config
        self.__dashd_intf = dashd_intf
        self.__get_hw_client_function = get_hw_client_function
        self.__hw_connect_function: Callable = hw_connect_function
        self.__hw_disconnect_function: Callable = hw_disconnect_function
        self.__base_bip32_path: str = ''
        self.__base_public_key: bytes = ''
        self.__hd_tree_ident: str = ''

    @property
    def hw_client(self):
        return self.__get_hw_client_function()

    @property
    def hw_connect(self):
        return self.__hw_connect_function

    @property
    def hw_disconnect(self):
        return self.__hw_disconnect_function

    @property
    def hw_type(self):
        return self.__app_config.hw_type

    @property
    def app_config(self):
        return self.__app_config

    @property
    def dashd_intf(self):
        return self.__dashd_intf

    def set_dashd_intf(self, dashd_intf):
        self.__dashd_intf = dashd_intf

    def acquire_client(self):
        cli = self.__get_hw_client_function()
        lock = self.__locks.get(cli)
        if not lock:
            lock = EnhRLock()
            self.__locks[cli] = lock
        lock.acquire()

    def release_client(self):
        cli = self.__get_hw_client_function()
        lock = self.__locks.get(cli)
        if not lock:
            raise Exception(f'Lock for client {str(cli)} not acquired before.')
        lock.release()

    def set_base_info(self, bip32_path: str, public_key: bytes):
        self.__base_bip32_path = bip32_path
        self.__base_public_key = public_key
        self.__hd_tree_ident = SHA256.new(public_key).digest().hex()

    @property
    def base_bip32_path(self):
        return self.__base_bip32_path

    @property
    def base_public_key(self):
        return self.__base_public_key

    @property
    def hd_tree_ident(self):
        coin_name = self.__app_config.hw_coin_name
        if not coin_name:
            raise Exception('Coin name not set in configuration')
        return self.__hd_tree_ident + bytes(coin_name, 'ascii').hex()


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


def ask_for_pass_callback(msg):
    def dlg():
        ui = hw_pass_dlg.HardwareWalletPassDlg()
        if ui.exec_():
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


class SelectHWDevice(QDialog):
    def __init__(self, parent, label: str, device_list: List[str]):
        QDialog.__init__(self, parent=parent)
        self.device_list = device_list
        self.device_radiobutton_list = []
        self.device_selected_index = None
        self.label = label
        self.setupUi(self)

    def setupUi(self, Form):
        Form.setObjectName("SelectHWDevice")
        self.lay_main = QtWidgets.QVBoxLayout(Form)
        self.lay_main.setContentsMargins(-1, 3, -1, 3)
        self.lay_main.setObjectName("lay_main")
        self.gb_devices = QtWidgets.QGroupBox(Form)
        self.gb_devices.setFlat(False)
        self.gb_devices.setCheckable(False)
        self.gb_devices.setObjectName("gb_devices")
        self.lay_main.addWidget(self.gb_devices)

        self.lay_devices = QtWidgets.QVBoxLayout(self.gb_devices)
        for idx, dev in enumerate(self.device_list):
            rb = QRadioButton(self.gb_devices)
            rb.setText(dev)
            rb.toggled.connect(partial(self.on_item_toggled, idx))
            self.device_radiobutton_list.append(rb)
            self.lay_devices.addWidget(rb)

        self.btn_main = QtWidgets.QDialogButtonBox(Form)
        self.btn_main.setStandardButtons(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Ok)
        self.btn_main.setObjectName("btn_main")
        self.lay_main.addWidget(self.btn_main)
        self.retranslateUi(Form)
        QtCore.QMetaObject.connectSlotsByName(Form)
        self.setFixedSize(self.sizeHint())

    def retranslateUi(self, Form):
        _translate = QtCore.QCoreApplication.translate
        Form.setWindowTitle('Select hardware wallet device')
        self.gb_devices.setTitle(self.label)

    def on_btn_main_accepted(self):
        if self.device_selected_index is None:
            WndUtils.errorMsg('No item selected.')
        else:
            self.accept()

    def on_btn_main_rejected(self):
        self.reject()

    def on_item_toggled(self, index, checked):
        if checked:
            self.device_selected_index = index


def select_hw_device(parent, label: str, devices: List[str]) -> Optional[int]:
    """ Invokes dialog for selecting the particular instance of hardware wallet device.
    :param parent:
    :param devices:
    :return: index of selected device from 'devices' list or None if user cancelled the action.
    """
    dlg = SelectHWDevice(parent, label, devices)
    if dlg.exec_():
        return dlg.device_selected_index
    return None


