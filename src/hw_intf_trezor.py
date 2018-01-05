#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import json
from typing import Optional, Tuple
import simplejson
import binascii
import unicodedata
from trezorlib.client import TextUIMixin as trezor_TextUIMixin, normalize_nfc, ProtocolMixin as trezor_ProtocolMixin, \
    BaseClient as trezor_BaseClient, CallException
from trezorlib.tx_api import TxApiInsight
from hw_common import HardwareWalletCancelException, ask_for_pass_callback, ask_for_pin_callback
from trezorlib import messages_pb2 as trezor_proto
import trezorlib.types_pb2 as proto_types
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
        else:
            passphrase = unicodedata.normalize('NFKD', passphrase)
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


def connect_trezor(device_id: Optional[str] = None) -> Optional[MyTrezorClient]:
    """
    Connect to a Trezor device.
    :param device_id:
    :return: ref to a trezor client if connection successfull or None if we are sure that no Trezor device connected.
    """

    logging.info('Started function')
    def get_client() -> Optional[MyTrezorClient]:
        from trezorlib.transport_hid import HidTransport
        count = len(HidTransport.enumerate())
        if not count:
            logging.warning('Number of Trezor devices: 0')

        for d in HidTransport.enumerate():
            transport = HidTransport(d)
            client = MyTrezorClient(transport, ask_for_pin_callback, ask_for_pass_callback)
            if not device_id or client.features.device_id == device_id:
                return client
            else:
                client.clear_session()
                client.close()
        return None

    # HidTransport.enumerate() has to be called in the main thread - second call from bg thread
    # causes SIGSEGV
    client = WndUtils.call_in_main_thread(get_client)
    if client:
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
        if device_id:
            msg = 'Cannot connect to the Trezor device with this id: %s.' % device_id
        else:
            msg = 'Cannot find any Trezor device.'
        raise Exception(msg)


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


TxApiDash = TxApiInsight(network='insight_dash', url='https://dash-bitcore1.trezor.io/api/')


def prepare_transfer_tx(main_ui, utxos_to_spend, dest_address, tx_fee):
    """
    Creates a signed transaction.
    :param main_ui: Main window for configuration data
    :param utxos_to_spend: list of utxos to send
    :param dest_address: destination (Dash) address
    :param tx_fee: transaction fee
    :return: tuple (serialized tx, total transaction amount in satoshis)
    """
    # tx_api = MyTxApiInsight('insight_dash', None, main_ui.dashd_intf, main_ui.config.cache_dir)
    tx_api = TxApiDash
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


def load_device_by_mnemonic(hw_device_id: str, mnemonic: str, pin: str, passphrase_enbled: bool, hw_label: str,
                            language: Optional[str]=None) -> Tuple[str, bool]:
    """
    :param hw_device_id:
    :param mnemonic:
    :param pin:
    :param passphrase_enbled:
    :param hw_label:
    :param language:
    :return: Tuple
        Ret[0]: Device id. If a device is wiped before initializing with mnemonics, a new device id is generated. It's
            returned to the caller.
        Ret[1]: False, if the user cancelled the operation. In this situation we deliberately don't raise the 'cancelled'
            exception, because in the case of changing of the device id (when wiping) we want to pass it back to
            the caller.
    """
    client = None
    try:
        client = connect_trezor(hw_device_id)

        if client:
            if client.features.initialized:
                client.wipe_device()
                hw_device_id = client.features.device_id
            client.load_device_by_mnemonic(mnemonic, pin, passphrase_enbled, hw_label, language=language)
            client.close()
            return hw_device_id, True
        else:
            raise Exception('Couln\'t connect to Trezor device.')

    except CallException as e:
        if client:
            client.close()
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            raise
        else:
            return hw_device_id, False  # cancelled by the user
