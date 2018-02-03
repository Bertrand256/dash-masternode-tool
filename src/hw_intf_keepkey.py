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
from mnemonic import Mnemonic
from hw_common import HardwareWalletCancelException, ask_for_pin_callback, ask_for_pass_callback, ask_for_word_callback
import keepkeylib.types_pb2 as proto_types
from wnd_utils import WndUtils
from hw_common import clean_bip32_path


class MyKeepkeyTextUIMixin(keepkey_TextUIMixin):

    def __init__(self, transport, ask_for_pin_fun, ask_for_pass_fun, passphrase_encoding):
        keepkey_TextUIMixin.__init__(self, transport)
        self.ask_for_pin_fun = ask_for_pin_fun
        self.ask_for_pass_fun = ask_for_pass_fun
        self.passphrase_encoding = passphrase_encoding
        self.__mnemonic = Mnemonic('english')

    def callback_PassphraseRequest(self, msg):
        passphrase = self.ask_for_pass_fun(msg)
        if passphrase is None:
            raise HardwareWalletCancelException('Cancelled')
        else:
            if self.passphrase_encoding in ('NFKD', 'NFC'):
                passphrase = unicodedata.normalize(self.passphrase_encoding, passphrase)
            else:
                raise Exception('Invalid passphrase encoding value: ' + self.passphrase_encoding)
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

    def callback_WordRequest(self, msg):
        msg = "Enter one word of mnemonic: "
        word = ask_for_word_callback(msg, self.__mnemonic.wordlist)
        if not word:
            raise HardwareWalletCancelException('Cancelled')
        return keepkey_proto.WordAck(word=word)


class MyKeepkeyClient(keepkey_ProtocolMixin, MyKeepkeyTextUIMixin, keepkey_BaseClient):
    def __init__(self, transport, ask_for_pin_fun, ask_for_pass_fun, passphrase_encoding):
        keepkey_ProtocolMixin.__init__(self, transport, ask_for_pin_fun, ask_for_pass_fun, passphrase_encoding)
        MyKeepkeyTextUIMixin.__init__(self, transport, ask_for_pin_fun, ask_for_pass_fun, passphrase_encoding)
        keepkey_BaseClient.__init__(self, transport)


def connect_keepkey(passphrase_encoding: Optional[str] = 'NFC',
                    device_id: Optional[str] = None) -> Optional[MyKeepkeyClient]:
    """
    Connect to a Keepkey device.
    :passphrase_encoding: Allowed values: 'NFC' or 'NFKD'. Note: Keekpey uses NFC encoding for passphrases, which is
        incompatible with BIP-39 standard (NFKD). This argument gives the possibility to enforce comforming the
        standard encoding.
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
            client = MyKeepkeyClient(transport, ask_for_pin_callback, ask_for_pass_callback, passphrase_encoding)
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
            j = self.dashd_inf.getrawtransaction(resourceid, 1)
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
        client = connect_keepkey(device_id=hw_device_id)

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

    except HardwareWalletCancelException:
        if client:
            client.close()
        raise


def wipe_device(hw_device_id) -> Tuple[str, bool]:
    """
    :param hw_device_id:
    :return: Tuple
        [0]: Device id. If a device is wiped before initializing with mnemonics, a new device id is generated. It's
            returned to the caller.
        [1]: True, if the user cancelled the operation. In this case we deliberately don't raise the 'cancelled'
            exception, because in the case of changing of the device id (when wiping) we want to pass the new device
            id back to the caller.
    """
    client = None
    try:
        client = connect_keepkey(device_id=hw_device_id)

        if client:
            client.wipe_device()
            hw_device_id = client.features.device_id
            client.close()
            return hw_device_id, False
        else:
            raise Exception('Couldn\'t connect to Keepkey device.')

    except CallException as e:
        if client:
            client.close()
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            raise
        else:
            return hw_device_id, True  # cancelled by user

    except HardwareWalletCancelException:
        if client:
            client.close()
        return hw_device_id, True  # cancelled by user


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
        [1]: True, if the user cancelled the operation. In this case we deliberately don't raise the 'cancelled'
            exception, because in the case of changing of the device id (when wiping) we want to pass the new device
            id back to the caller.
    """
    client = None
    try:
        client = connect_keepkey(device_id=hw_device_id)

        if client:
            if client.features.initialized:
                client.wipe_device()
                hw_device_id = client.features.device_id
            client.load_device_by_mnemonic(mnemonic, pin, passphrase_enbled, hw_label, language=language)
            client.close()
            return hw_device_id, False
        else:
            raise Exception('Couldn\'t connect to Keepkey device.')

    except CallException as e:
        if client:
            client.close()
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            raise
        else:
            return hw_device_id, True  # cancelled by user

    except HardwareWalletCancelException:
        if client:
            client.close()
        return hw_device_id, True  # cancelled by user


def recovery_device(hw_device_id: str, word_count: int, passphrase_enabled: bool, pin_enabled: bool, hw_label: str) \
        -> Tuple[str, bool]:
    """
    :param hw_device_id:
    :param passphrase_enbled:
    :param pin_enbled:
    :param hw_label:
    :return: Tuple
        [0]: Device id. If a device is wiped before initializing with mnemonics, a new device id is generated. It's
            returned to the caller.
        [1]: True, if the user cancelled the operation. In this case we deliberately don't raise the 'cancelled'
            exception, because in the case of changing of the device id (when wiping) we want to pass the new device
            id back to the caller.
    """
    client = None
    try:
        client = connect_keepkey(device_id=hw_device_id)

        if client:
            if client.features.initialized:
                client.wipe_device()
                hw_device_id = client.features.device_id

            client.recovery_device(use_trezor_method=True, word_count=word_count,
                                   passphrase_protection=passphrase_enabled, pin_protection=pin_enabled,
                                   label=hw_label, language='english')
            client.close()
            return hw_device_id, False
        else:
            raise Exception('Couldn\'t connect to Keepkey device.')

    except CallException as e:
        if client:
            client.close()
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            raise
        else:
            return hw_device_id, True  # cancelled by user

    except HardwareWalletCancelException:
        if client:
            client.close()
        return hw_device_id, True  # cancelled by user


def reset_device(hw_device_id: str, strength: int, passphrase_enabled: bool, pin_enabled: bool,
                 hw_label: str) -> Tuple[str, bool]:
    """
    Initialize device with a newly generated words.
    :param hw_type: app_config.HWType
    :param hw_device_id: id of the device selected by the user
    :param strength: number of bits of entropy (will have impact on number of words)
    :param passphrase_enbled: if True, hw will have passphrase enabled
    :param pin_enabled: if True, hw will have pin enabled
    :param hw_label: label for device (Trezor/Keepkey)
    :return: Tuple
        Ret[0]: Device id. If a device is wiped before initializing with mnemonics, a new device id is generated. It's
            returned to the caller.
        Ret[1]: True, if the user cancelled the operation. In this situation we deliberately don't raise the
            'cancelled' exception, because in the case of changing of the device id (when wiping) we want to pass
            it back to the caller function.
    """
    client = None
    try:
        client = connect_keepkey(device_id=hw_device_id)

        if client:
            if client.features.initialized:
                client.wipe_device()
                hw_device_id = client.features.device_id

            client.reset_device(display_random=True, strength=strength, passphrase_protection=passphrase_enabled,
                                pin_protection=pin_enabled, label=hw_label, language='english')
            client.close()
            return hw_device_id, False
        else:
            raise Exception('Couldn\'t connect to Keepkey device.')

    except CallException as e:
        if client:
            client.close()
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            raise
        else:
            return hw_device_id, True  # cancelled by user

    except HardwareWalletCancelException:
        if client:
            client.close()
        return hw_device_id, True  # cancelled by user

