#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import json
import binascii
from trezorlib.client import TextUIMixin as trezor_TextUIMixin
from trezorlib.client import ProtocolMixin as trezor_ProtocolMixin
from trezorlib.client import BaseClient as trezor_BaseClient
from trezorlib.tx_api import TxApiInsight
from src.hw_common import HardwareWalletCancelException
from trezorlib import messages_pb2 as trezor_proto
import trezorlib.types_pb2 as proto_types


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


class MyTxApiInsight(TxApiInsight):

    def __init__(self, network, url, dashd_inf, cache_dir, zcash=None):
        TxApiInsight.__init__(self, network, url, zcash)
        self.dashd_inf = dashd_inf
        self.cache_dir = cache_dir

    def fetch_json(self, url, resource, resourceid):
        cache_file = ''
        if self.cache_dir:
            cache_file = '%s/%s_%s_%s.json' % (self.cache_dir, self.network, resource, resourceid)
            try: # looking into cache first
                j = json.load(open(cache_file))
                return j
            except:
                pass
        try:
            j = self.dashd_inf.getrawtransaction(resourceid.decode("utf-8"), 1)
        except Exception as e:
            raise
        if cache_file:
            try: # saving into cache
                json.dump(j, open(cache_file, 'w'))
            except Exception as e:
                pass
        return j


def prepare_transfer_tx(main_ui, utxos_to_spend, dest_address, tx_fee):
    """
    Creates a signed transaction.
    :param main_ui: Main window for configuration data
    :param utxos_to_spend: list of utxos to send
    :param dest_address: destination (Dash) address
    :param tx_fee: transaction fee
    :return: tuple (serialized tx, total transaction amount in satoshis)
    """
    tx_api = MyTxApiInsight('insight_dash', None, main_ui.dashd_intf, main_ui.config.cache_dir)
    client = main_ui.hw_client
    client.set_tx_api(tx_api)
    inputs = []
    outputs = []
    amt = 0
    for utxo in utxos_to_spend:
        if not utxo.get('bip32_path', None):
            raise Exception('No BIP32 path for UTXO ' + utxo['txid'])
        address_n = client.expand_path(utxo['bip32_path'])
        it = proto_types.TxInputType(address_n=address_n, prev_hash=binascii.unhexlify(utxo['txid']),
                                     prev_index=utxo['outputIndex'])
        inputs.append(it)
        amt += utxo['satoshis']
    amt -= tx_fee
    amt = int(amt)

    ot = proto_types.TxOutputType(
        address=dest_address,
        amount=amt,
        script_type=proto_types.PAYTOADDRESS
    )
    outputs.append(ot)
    signed = client.sign_tx('Dash', inputs, outputs)
    return signed[1], amt


def sign_message(main_ui, bip32path, message):
    client = main_ui.hw_client
    address_n = client.expand_path(bip32path)
    return client.sign_message('Dash', address_n, message)


def change_pin(main_ui, remove=False):
    if main_ui.hw_client:
        main_ui.hw_client.change_pin(remove)
    else:
        raise Exception('HW client not set.')