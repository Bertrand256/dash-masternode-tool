#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
from src.hw_common import HardwareWalletPinException


def connect_hw(hw_type, ask_for_pin_fun, ask_for_pass_fun):
    if hw_type == 'TREZOR':
        import src.hw_intf_trezor as trezor
        import trezorlib.client as client
        try:
            return trezor.connect_trezor(ask_for_pin_fun, ask_for_pass_fun)
        except client.PinException as e:
            raise HardwareWalletPinException(e.args[1])
    else:
        import src.hw_intf_keepkey as keepkey
        import keepkeylib.client as client
        try:
            return keepkey.connect_keepkey(ask_for_pin_fun, ask_for_pass_fun)
        except client.PinException as e:
            raise HardwareWalletPinException(e.args[1])


def reconnect_hw(hw_type, client, ask_for_pin_fun, ask_for_pass_fun):
    if hw_type == 'TREZOR':
        from src.hw_intf_trezor import reconnect_trezor
        return reconnect_trezor(client, ask_for_pin_fun, ask_for_pass_fun)
    else:
        from src.hw_intf_keepkey import reconnect_keepkey
        return reconnect_keepkey(client, ask_for_pin_fun, ask_for_pass_fun)


def hw_get_address(client, address_n):
    return client.get_address('Dash', address_n, False)


def disconnect_hw(client):
    try:
        client.clear_session()
        client.close()
    except Exception as e:
        pass  # HW must have been disconnected
