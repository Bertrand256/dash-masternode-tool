#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import json
import binascii
import logging
import unicodedata
from typing import Optional, Tuple
from keepkeylib.client import TextUIMixin as keepkey_TextUIMixin
from keepkeylib.client import ProtocolMixin as keepkey_ProtocolMixin
from keepkeylib.client import BaseClient as keepkey_BaseClient, CallException
from keepkeylib import messages_pb2 as keepkey_proto
from keepkeylib.tx_api import TxApiInsight
from hw_common import HardwareWalletCancelException, ask_for_pin_callback, ask_for_pass_callback
import keepkeylib.types_pb2 as proto_types
from wnd_utils import WndUtils
from hw_common import clean_bip32_path


class MyKeepkeyTextUIMixin(keepkey_TextUIMixin):

    def __init__(self, transport, ask_for_pin_fun, ask_for_pass_fun):
        keepkey_TextUIMixin.__init__(self, transport)
        self.ask_for_pin_fun = ask_for_pin_fun
        self.ask_for_pass_fun = ask_for_pass_fun

    def callback_PassphraseRequest(self, msg):
        passphrase = self.ask_for_pass_fun(msg)
        if passphrase is None:
            raise HardwareWalletCancelException('Cancelled')
        else:
            passphrase = unicodedata.normalize('NFKD', passphrase)
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


def connect_keepkey(device_id: Optional[str] = None) -> Optional[MyKeepkeyClient]:
    """
    Connect to a Keepkey device.
    :return: ref to a keepkey client if connection successfull or None if we are sure that no Keepkey device connected.
    """

    logging.info('Started function')
    def get_client() -> Optional[MyKeepkeyClient]:
        from keepkeylib.transport_hid import HidTransport

        count = len(HidTransport.enumerate())
        if not count:
            logging.warning('Number of Keepkey devices: 0')

        for d in HidTransport.enumerate():
            transport = HidTransport(d)
            client = MyKeepkeyClient(transport, ask_for_pin_callback, ask_for_pass_callback)
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
        logging.info('Keepkey connected. Firmware version: %s.%s.%s, vendor: %s, initialized: %s, '
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
            msg = 'Cannot connect to the Keepkey device with this id: .' % device_id
        else:
            msg = 'Cannot find any Keepkey device.'
        raise Exception(msg)


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
        address_n = client.expand_path(clean_bip32_path(utxo['bip32_path']))
        it = proto_types.TxInputType(address_n=address_n, prev_hash=binascii.unhexlify(utxo['txid']),
                                     prev_index=utxo['outputIndex'])
        inputs.append(it)
        amt += utxo['satoshis']
    amt -= tx_fee
    amt = int(amt)

    # check if dest_address is a Dash address or a script address and then set appropriate script_type
    # https://github.com/dashpay/dash/blob/master/src/chainparams.cpp#L140
    if dest_address.startswith('7'):
        stype = proto_types.PAYTOSCRIPTHASH
    else:
        stype = proto_types.PAYTOADDRESS

    ot = proto_types.TxOutputType(
        address=dest_address,
        amount=amt,
        script_type=stype
    )
    outputs.append(ot)
    signed = client.sign_tx('Dash', inputs, outputs)
    return signed[1], amt


def sign_message(main_ui, bip32path, message):
    client = main_ui.hw_client
    address_n = client.expand_path(clean_bip32_path(bip32path))
    return client.sign_message('Dash', address_n, message)


def change_pin(main_ui, remove=False):
    if main_ui.hw_client:
        main_ui.hw_client.change_pin(remove)
    else:
        raise Exception('HW client not set.')


def apply_settings(main_ui, label=None, language=None, use_passphrase=None, homescreen=None):
    if main_ui.hw_client:
        main_ui.hw_client.apply_settings()
    else:
        raise Exception('HW client not set.')


def get_entropy(hw_device_id, len_bytes):
    client = None
    try:
        client = connect_keepkey(hw_device_id)

        if client:
            client.get_entropy(len_bytes)
            client.close()
        else:
            raise Exception('Couldn\'t connect to Trezor device.')
    except CallException as e:
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            raise
        else:
            if client:
                client.close()
            raise HardwareWalletCancelException('Cancelled')


def wipe_device(hw_device_id):
    client = None
    try:
        client = connect_keepkey(hw_device_id)

        if client:
            client.wipe_device()
            client.close()
        else:
            raise Exception('Couldn\'t connect to Trezor device.')
    except CallException as e:
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            raise
        else:
            if client:
                client.close()
            raise HardwareWalletCancelException('Cancelled')


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
        [0]: Device id. If a device is wiped before initializing with mnemonics, a new device id is generated. It's
            returned to the caller.
        [1]: False, if the user cancelled the operation. In this case we deliberately don't raise the 'cancelled'
            exception, because in the case of changing of the device id (when wiping) we want to pass the new device
            id back to the caller.
    """
    client = None
    try:
        client = connect_keepkey(hw_device_id)

        if client:
            if client.features.initialized:
                client.wipe_device()
                hw_device_id = client.features.device_id
            client.load_device_by_mnemonic(mnemonic, pin, passphrase_enbled, hw_label, language=language)
            client.close()
            return hw_device_id, True
        else:
            raise Exception('Couldn\'t connect to Keepkey device.')

    except CallException as e:
        if client:
            client.close()
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            raise
        else:
            return hw_device_id, False  # cancelled by the user
