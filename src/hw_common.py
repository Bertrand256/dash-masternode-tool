#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import threading

import hw_pass_dlg
import hw_pin_dlg
from wnd_utils import WndUtils


class HardwareWalletCancelException(Exception):
    pass


class HardwareWalletPinException(Exception):
    def __init__(self, msg):
        self.msg = msg


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


