#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

from keepkeylib.client import TextUIMixin as keepkey_TextUIMixin
from keepkeylib.client import ProtocolMixin as keepkey_ProtocolMixin
from keepkeylib.client import BaseClient as keepkey_BaseClient
from keepkeylib import messages_pb2 as keepkey_proto
from src.hw_common import HardwareWalletCancelException


class MyKeepkeyTextUIMixin(keepkey_TextUIMixin):

    def __init__(self, transport, ask_for_pin_fun, ask_for_pass_fun):
        keepkey_TextUIMixin.__init__(self, transport)
        self.ask_for_pin_fun = ask_for_pin_fun
        self.ask_for_pass_fun = ask_for_pass_fun

    def callback_PassphraseRequest(self, msg):
        passphrase = self.ask_for_pass_fun(msg)
        if not passphrase:
            raise HardwareWalletCancelException('Cancelled')
        return keepkey_proto.PassphraseAck(passphrase=passphrase)

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
        return keepkey_proto.PinMatrixAck(pin=pin)


class MyKeepkeyClient(keepkey_ProtocolMixin, MyKeepkeyTextUIMixin, keepkey_BaseClient):
    def __init__(self, transport, ask_for_pin_fun, ask_for_pass_fun):
        keepkey_ProtocolMixin.__init__(self, transport, ask_for_pin_fun, ask_for_pass_fun)
        MyKeepkeyTextUIMixin.__init__(self, transport, ask_for_pin_fun, ask_for_pass_fun)
        keepkey_BaseClient.__init__(self, transport)


def connect_keepkey(ask_for_pin_fun, ask_for_pass_fun):
    try:
        from keepkeylib.transport_hid import HidTransport

        transport = None
        for d in HidTransport.enumerate():
            transport = HidTransport(d)
            break

        if transport:
            client = MyKeepkeyClient(transport, ask_for_pin_fun, ask_for_pass_fun)
            return client
        else:
            return None

    except Exception as e:
        raise


def reconnect_keepkey(client, ask_for_pin_fun, ask_for_pass_fun):
    try:
        from trezorlib.transport_hid import HidTransport
        client.init_device()
        return connect_keepkey(ask_for_pin_fun, ask_for_pass_fun)
    except Exception as e:
        raise
