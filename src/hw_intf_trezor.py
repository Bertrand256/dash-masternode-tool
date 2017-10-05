#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import json
import simplejson
import binascii
from trezorlib.client import TextUIMixin as trezor_TextUIMixin
from trezorlib.client import ProtocolMixin as trezor_ProtocolMixin
from trezorlib.client import BaseClient as trezor_BaseClient
from trezorlib.tx_api import TxApiInsight
from hw_common import HardwareWalletCancelException
from trezorlib import messages_pb2 as trezor_proto
import trezorlib.types_pb2 as proto_types
import base58
import logging
from wnd_utils import WndUtils


class MyTrezorTextUIMixin(trezor_TextUIMixin):

    def __init__(self, transport, ask_for_pin_fun, ask_for_pass_fun):
        trezor_TextUIMixin.__init__(self, transport)
        self.ask_for_pin_fun = ask_for_pin_fun
        self.ask_for_pass_fun = ask_for_pass_fun

    def callback_PassphraseRequest(self, msg):
        passphrase = self.ask_for_pass_fun(msg)
        if passphrase is None:
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
    """
    Connect to a Trezor device.
    :param ask_for_pin_fun: ref to a function displaying a dialog asking the user for a pin (Trezor and Keepkey)
    :param ask_for_pass_fun: ref to a function displaying a dialog asking the user for a passphrase (Trezor and Keepkey)
    :return: ref to a trezor client if connection successfull or None if we are sure that no Trezor device connected.
    """

    logging.info('Started function')
    def get_transport():
        from trezorlib.transport_hid import HidTransport
        count = len(HidTransport.enumerate())
        if not count:
            logging.warning('Number of Trezor devices: 0')
        for d in HidTransport.enumerate():
            transport = HidTransport(d)
            return transport

    # HidTransport.enumerate() has to be called in the main thread - second call from bg thread
    # causes SIGSEGV
    transport = WndUtils.callFunInTheMainThread(get_transport)
    logging.info('Read transport')
    if transport:
        logging.info('Transport is OK')
        client = MyTrezorClient(transport, ask_for_pin_fun, ask_for_pass_fun)
        logging.info('Trezor connected. Firmware version: %s.%s.%s, vendor: %s, initialized: %s, '
                     'pp_protection: %s, pp_cached: %s, bootloader_mode: %s ' %
                     (str(client.features.major_version),
                      str(client.features.minor_version),
                      str(client.features.patch_version), str(client.features.vendor),
                      str(client.features.initialized),
                      str(client.features.passphrase_protection), str(client.features.passphrase_cached),
                      str(client.features.bootloader_mode)))
        return client
    else:
        logging.warning('Transport is None')
        return None


class MyTxApiInsight(TxApiInsight):

    def __init__(self, network, url, dashd_inf, cache_dir, zcash=None):
        TxApiInsight.__init__(self, network, url, zcash)
        self.dashd_inf = dashd_inf
        self.cache_dir = cache_dir

    def fetch_json(self, resource, resourceid):
        cache_file = ''
        if self.cache_dir:
            cache_file = '%s/%s_%s_%s.json' % (self.cache_dir, self.network, resource, resourceid)
            try: # looking into cache first
                j = simplejson.load(open(cache_file))
                logging.info('Loaded transaction from existing file: ' + cache_file)
                return j
            except:
                pass
        try:
            j = self.dashd_inf.getrawtransaction(resourceid, 1)
        except Exception as e:
            raise
        if cache_file:
            try: # saving into cache
                simplejson.dump(j, open(cache_file, 'w'))
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
    for utxo_index, utxo in enumerate(utxos_to_spend):
        if not utxo.get('bip32_path', None):
            raise Exception('No BIP32 path for UTXO ' + utxo['txid'])
        address_n = client.expand_path(utxo['bip32_path'])
        it = proto_types.TxInputType(address_n=address_n, prev_hash=binascii.unhexlify(utxo['txid']),
                                     prev_index=int(utxo['outputIndex']))
        logging.info('BIP32 path: %s, address_n: %s, utxo_index: %s, prev_hash: %s, prev_index %s' %
                      (utxo['bip32_path'],
                       str(address_n),
                       str(utxo_index),
                       utxo['txid'],
                       str(utxo['outputIndex'])
                      ))
        inputs.append(it)
        amt += utxo['satoshis']
    amt -= tx_fee
    amt = int(amt)

    # check if dest_address is a Dash address or a script address and then set appropriate script_type
    # https://github.com/dashpay/dash/blob/master/src/chainparams.cpp#L140
    if dest_address.startswith('7'):
        stype = proto_types.PAYTOSCRIPTHASH
        logging.info('Transaction type: PAYTOSCRIPTHASH' + str(stype))
    else:
        stype = proto_types.PAYTOADDRESS
        logging.info('Transaction type: PAYTOADDRESS ' + str(stype))

    ot = proto_types.TxOutputType(
        address=dest_address,
        amount=amt,
        script_type=stype
    )
    logging.info('dest_address length: ' + str(len(dest_address)))
    outputs.append(ot)
    signed = client.sign_tx('Dash', inputs, outputs)
    logging.info('Signed transaction')
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