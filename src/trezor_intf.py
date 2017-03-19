#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

from trezorlib.client import TextUIMixin, ProtocolMixin, BaseClient
from trezorlib import messages_pb2 as proto


class TrezorCancelException(Exception):
    pass


class MyTextUIMixin(TextUIMixin):

    def __init__(self, transport, ask_for_pin_fun, ask_for_pass_fun):
        TextUIMixin.__init__(self, transport)
        self.ask_for_pin_fun = ask_for_pin_fun
        self.ask_for_pass_fun = ask_for_pass_fun

    def callback_PassphraseRequest(self, msg):
        passphrase = self.ask_for_pass_fun(msg)
        if not passphrase:
            raise TrezorCancelException('Cancelled')
        return proto.PassphraseAck(passphrase=passphrase)

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
            raise TrezorCancelException('Cancelled')
        return proto.PinMatrixAck(pin=pin)


class MyTrezorClient(ProtocolMixin, MyTextUIMixin, BaseClient):
    def __init__(self, transport, ask_for_pin_fun, askFoprPassFun):
        ProtocolMixin.__init__(self, transport, ask_for_pin_fun, askFoprPassFun)
        MyTextUIMixin.__init__(self, transport, ask_for_pin_fun, askFoprPassFun)
        BaseClient.__init__(self, transport)


def connect_trezor(ask_for_pin_fun, askFoprPassFun):
    try:
        from trezorlib.transport_hid import HidTransport
        transport = None
        for d in HidTransport.enumerate():
            transport = HidTransport(d)
            break

        if transport:
            client = MyTrezorClient(transport, ask_for_pin_fun, askFoprPassFun)
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
