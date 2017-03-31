#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

from trezorlib.client import TextUIMixin as trezor_TextUIMixin
from trezorlib.client import ProtocolMixin as trezor_ProtocolMixin
from trezorlib.client import BaseClient as trezor_BaseClient
from src.hw_common import HardwareWalletCancelException
from trezorlib import messages_pb2 as trezor_proto


class MyTrezorTextUIMixin(trezor_TextUIMixin):

    def __init__(self, transport, ask_for_pin_fun, ask_for_pass_fun):
        trezor_TextUIMixin.__init__(self, transport)
        self.ask_for_pin_fun = ask_for_pin_fun
        self.ask_for_pass_fun = ask_for_pass_fun

    def callback_PassphraseRequest(self, msg):
        passphrase = self.ask_for_pass_fun(msg)
        if not passphrase:
            raise HardwareWalletCancelException('Cancelled')
        return trezor_proto.PassphraseAck(passphrase=passphrase)

    def callback_PinMatrixRequest(self, msg):
        if msg.type == 1:
            desc = 'Enter current PIN'
        elif msg.type == 2:
            desc = 'Enter new PIN'
        elif msg.type == 3:
            desc = 'Enter new PIN again'
        else:
            desc = 'Enter PIN'
        pin = self.ask_for_pin_fun(desc)
        if not pin:
            raise HardwareWalletCancelException('Cancelled')
        return trezor_proto.PinMatrixAck(pin=pin)


class MyTrezorClient(trezor_ProtocolMixin, MyTrezorTextUIMixin, trezor_BaseClient):
    def __init__(self, transport, ask_for_pin_fun, ask_for_pass_fun):
        trezor_ProtocolMixin.__init__(self, transport, ask_for_pin_fun, ask_for_pass_fun)
        MyTrezorTextUIMixin.__init__(self, transport, ask_for_pin_fun, ask_for_pass_fun)
        trezor_BaseClient.__init__(self, transport)


def connect_trezor(ask_for_pin_fun, ask_for_pass_fun):
    try:
        from trezorlib.transport_hid import HidTransport
        transport = None
        for d in HidTransport.enumerate():
            transport = HidTransport(d)
            break

        if transport:
            client = MyTrezorClient(transport, ask_for_pin_fun, ask_for_pass_fun)
            return client
        else:
            return None

    except Exception as e:
        raise


def reconnect_trezor(client, ask_for_pin_fun, ask_for_pass_fun):
    try:
        from trezorlib.transport_hid import HidTransport
        client.init_device()
        return connect_trezor(ask_for_pin_fun, ask_for_pass_fun)
    except Exception as e:
        raise
