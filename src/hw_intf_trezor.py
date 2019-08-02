#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import decimal
import importlib
import json
import os
import struct
import sys
import traceback
from typing import Optional, Tuple, List, Dict, Callable, Iterable, Type, Set
import binascii
from decimal import Decimal

import trezorlib
from bitcoinrpc.authproxy import EncodeDecimal
from mnemonic import Mnemonic
from trezorlib.client import TrezorClient
from trezorlib.tools import CallException
from trezorlib.transport import Transport
from trezorlib.tx_api import TxApi, _json_to_input, _json_to_bin_output, is_zcash
from trezorlib import messages as trezor_proto, exceptions, btc, messages
from trezorlib.ui import PIN_CURRENT, PIN_NEW, PIN_CONFIRM
#from trezorlib.transport import enumerate_devices, get_transport
from trezorlib import device
from trezorlib import coins

import dash_utils
from common import CancelException
from hw_common import ask_for_pass_callback, ask_for_pin_callback, \
    ask_for_word_callback, select_hw_device, HwSessionInfo
import logging
import wallet_common
from wnd_utils import WndUtils


log = logging.getLogger('dmt.hw_intf_trezor')


class TrezorUi(object):
    def __init__(self):
        self.prompt_shown = False
        pass

    def get_pin(self, code=None) -> str:
        if code == PIN_CURRENT:
            desc = "current PIN"
        elif code == PIN_NEW:
            desc = "new PIN"
        elif code == PIN_CONFIRM:
            desc = "new PIN again"
        else:
            desc = "PIN"

        pin = ask_for_pin_callback(desc)
        if pin is None:
            raise exceptions.Cancelled
        return pin

    def get_passphrase(self) -> str:
        passphrase = ask_for_pass_callback()
        if passphrase is None:
            raise exceptions.Cancelled
        return passphrase

    def button_request(self, msg_code):
        if not self.prompt_shown:
            pass

        self.prompt_shown = True


class MyTrezorClient(TrezorClient):

    def __init__(self, transport, ui=None, state=None):
        TrezorClient.__init__(self, transport, ui, state)

    def _callback_passphrase(self, msg):
        try:
            return TrezorClient._callback_passphrase(self, msg)
        except exceptions.Cancelled:
            raise CancelException('Cancelled')

    def _callback_pin(self, msg):
        try:
            return TrezorClient._callback_pin(self, msg)
        except exceptions.Cancelled:
            raise CancelException('Cancelled')


def all_transports() -> Iterable[Type[Transport]]:
    from trezorlib.transport.bridge import BridgeTransport
    from trezorlib.transport.hid import HidTransport
    from trezorlib.transport.udp import UdpTransport
    from trezorlib.transport.webusb import WebUsbTransport

    return [cls for cls in (BridgeTransport, HidTransport, UdpTransport, WebUsbTransport) if cls.ENABLED]


def enumerate_devices(
        use_webusb=True,
        use_bridge=True,
        use_udp=True,
        use_hid=True) -> Iterable[Transport]:

    devices = []  # type: List[Transport]
    for transport in all_transports():
        # workround for the issue introduced by Windows update #1903 (details: https://github.com/spesmilo/electrum/issues/5420):
        # 1. use BridgeTransport first and then WebUsbTransport
        # 2. if any BridgeTransport devices are found, skip scanning WevUsbTransport devices, otherwise it will
        #     breake the related "bridge" devices

        name = transport.__name__
        if (name == 'WebUsbTransport' and not use_webusb) or (name == 'BridgeTransport' and not use_bridge) or \
           (name == 'UdpTransport' and not use_udp) or (name == 'HidTransport' and not use_hid):
            log.info(f'Skipping {name}')
            continue

        if sys.platform == 'win32' and name == 'WebUsbTransport' and \
                len([d for d in devices if d.__class__.__name__ == 'BridgeTransport']):
            continue

        try:
            log.debug("About to enumerate {} devices".format(name))
            found = list(transport.enumerate())
            log.info("Enumerating {}: found {} devices".format(name, len(found)))
            devices.extend(found)
        except NotImplementedError:
            log.error("{} does not implement device enumeration".format(name))
        except Exception as e:
            excname = e.__class__.__name__
            log.exception("Failed to enumerate {}. {}: {}".format(name, excname, e))
    return devices


def get_device_list(
        return_clients: bool = True,
        allow_bootloader_mode: bool = False,
        use_webusb=True,
        use_bridge=True,
        use_udp=True,
        use_hid=True) -> Tuple[List[Dict], List[Exception]]:
    """
    :return: Tuple[List[Dict <{'client': MyTrezorClient, 'device_id': str, 'desc',: str, 'model': str}>],
                   List[Exception]]
    """
    ret_list = []
    exceptions: List[Exception] = []
    device_ids = []
    was_bootloader_mode = False

    devices = enumerate_devices(use_webusb=use_webusb, use_bridge=use_bridge, use_udp=use_udp, use_hid=use_hid)
    for d in devices:
        try:
            client = MyTrezorClient(d, ui=TrezorUi())

            if client.features.bootloader_mode:
                if was_bootloader_mode:
                    # in bootloader mode the device_id attribute isn't available, so for a given client object
                    # we are unable to distinguish between being the same device reached with the different
                    # transport and being another device
                    # for that reason, to avoid returning duplicate clients for the same device, we don't return
                    # more than one instance of a device in bootloader mod
                    client.close()
                    continue
                was_bootloader_mode = True

            if (not client.features.bootloader_mode or allow_bootloader_mode) and \
                (client.features.device_id not in device_ids or client.features.bootloader_mode):

                version = f'{client.features.major_version}.{client.features.minor_version}.' \
                          f'{client.features.patch_version}'
                if client.features.label:
                    desc = client.features.label
                else:
                    desc = '[UNNAMED]'
                desc = f'{desc} (ver: {version}, id: {client.features.device_id})'

                c = {
                    'client': client,
                    'device_id': client.features.device_id,
                    'desc': desc,
                    'model': client.features.model,
                    'bootloader_mode': client.features.bootloader_mode
                }

                ret_list.append(c)
                device_ids.append(client.features.device_id)  # beware: it's empty in bootloader mode
            else:
                # the same device is already connected using different connection medium
                client.close()
        except Exception as e:
            logging.warning(
                f'Cannot create Trezor client ({d.__class__.__name__}) due to the following error: ' + str(e))
            exceptions.append(e)

    if not return_clients:
        for cli in ret_list:
            cli['client'].close()
            cli['client'] = None

    return ret_list, exceptions


def connect_trezor(device_id: Optional[str] = None,
                   use_webusb=True,
                   use_bridge=True,
                   use_udp=True,
                   use_hid=True) -> Optional[MyTrezorClient]:
    """
    Connect to a Trezor device.
    :param device_id:
    :return: ref to a trezor client if connection successfull or None if we are sure that no Trezor device connected.
    """

    logging.info('Started function')
    def get_client() -> Optional[MyTrezorClient]:

        hw_clients, exceptions = get_device_list(use_webusb=use_webusb, use_bridge=use_bridge, use_udp=use_udp,
                                                 use_hid=use_hid)
        if not hw_clients:
            if exceptions:
                raise exceptions[0]
        else:
            selected_client = None
            if device_id:
                # we have to select a device with the particular id number
                for cli in hw_clients:
                    if cli['device_id'] == device_id:
                        selected_client = cli['client']
                        break
                    else:
                        cli['client'].close()
                        cli['client'] = None
            else:
                # we are not forced to automatically select the particular device
                if len(hw_clients) > 1:
                    hw_names = [a['desc'] for a in hw_clients]

                    selected_index = select_hw_device(None, 'Select Trezor device', hw_names)
                    if selected_index is not None and (0 <= selected_index < len(hw_clients)):
                        selected_client = hw_clients[selected_index]['client']
                else:
                    selected_client = hw_clients[0]['client']

            # close all the clients but the selected one
            for cli in hw_clients:
                if cli['client'] != selected_client:
                    cli['client'].close()
                    cli['client'] = None

            return selected_client
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


def is_dash(coin):
    return coin["coin_name"].lower().startswith("dash")


def json_to_tx(coin, data):
    t = messages.TransactionType()
    t.version = data["version"]
    t.lock_time = data.get("locktime")

    if coin["decred"]:
        t.expiry = data["expiry"]

    t.inputs = [_json_to_input(coin, vin) for vin in data["vin"]]
    t.bin_outputs = [_json_to_bin_output(coin, vout) for vout in data["vout"]]

    # zcash extra data
    if is_zcash(coin) and t.version >= 2:
        joinsplit_cnt = len(data["vjoinsplit"])
        if joinsplit_cnt == 0:
            t.extra_data = b"\x00"
        elif joinsplit_cnt >= 253:
            # we assume cnt < 253, so we can treat varIntLen(cnt) as 1
            raise ValueError("Too many joinsplits")
        elif "hex" not in data:
            raise ValueError("Raw TX data required for Zcash joinsplit transaction")
        else:
            rawtx = bytes.fromhex(data["hex"])
            extra_data_len = 1 + joinsplit_cnt * 1802 + 32 + 64
            t.extra_data = rawtx[-extra_data_len:]

    if is_dash(coin):
        dip2_type = data.get("type", 0)

        if t.version == 3 and dip2_type != 0:
            # It's a DIP2 special TX with payload

            if "extraPayloadSize" not in data or "extraPayload" not in data:
                raise ValueError("Payload data missing in DIP2 transaction")

            if data["extraPayloadSize"] * 2 != len(data["extraPayload"]):
                raise ValueError(
                    "extra_data_len (%d) does not match calculated length (%d)"
                    % (data["extraPayloadSize"], len(data["extraPayload"]) * 2)
                )
            t.extra_data = dash_utils.num_to_varint(data["extraPayloadSize"]) + bytes.fromhex(
                data["extraPayload"]
            )

        # Trezor firmware doesn't understand the split of version and type, so let's mimic the
        # old serialization format
        t.version |= dip2_type << 16

    return t



class MyTxApiInsight(TxApi):

    def __init__(self, network, url, dashd_inf, cache_dir):
        TxApi.__init__(self, network)
        self.dashd_inf = dashd_inf
        self.cache_dir = cache_dir
        self.skip_cache = False

    def fetch_json(self, *path, **params):
        if path:
            if len(path) >= 2:
                if path[0] == 'tx':
                    try:
                        j = self.dashd_inf.getrawtransaction(path[1], 1, skip_cache=self.skip_cache)
                        return j
                    except Exception as e:
                        raise
                else:
                    raise Exception('Invalid operation type: ' + path[0])
            else:
                Exception('Needs tx hash in argument list')
        else:
            raise Exception('No arguments')

    def get_block_hash(self, block_number):
        return self.dashd_inf.getblockhash(block_number)

    def current_height(self):
        return self.dashd_inf.getheight()

    def get_tx_data(self, txhash):
        data = self.fetch_json("tx", txhash)
        return data

    def get_tx(self, txhash):
        data = None
        try:
            data = self.get_tx_data(txhash)
            return json_to_tx(self.coin_data, data)
        except Exception as e:
            log.error(str(e))
            log.error('tx data: ' + str(data))
            raise


def sign_tx(hw_session: HwSessionInfo, utxos_to_spend: List[wallet_common.UtxoType],
            tx_outputs: List[wallet_common.TxOutputType], tx_fee):
    """
    Creates a signed transaction.
    :param hw_session:
    :param utxos_to_spend: list of utxos to send
    :param tx_outputs: list of transaction outputs
    :param tx_fee: transaction fee
    :return: tuple (serialized tx, total transaction amount in satoshis)
    """
    def load_prev_txes(tx_api, skip_cache: bool = False):
        txes = {}
        tx_api.skip_cache = skip_cache
        for utxo in utxos_to_spend:
            prev_hash = bytes.fromhex(utxo.txid)
            if prev_hash not in txes:
                tx = tx_api[prev_hash]
                txes[prev_hash] = tx
        return txes

    insight_network = 'insight_dash'
    if hw_session.app_config.is_testnet():
        insight_network += '_testnet'
    dash_network = hw_session.app_config.dash_network

    c_name = hw_session.app_config.hw_coin_name
    coin = coins.by_name[c_name]
    url = hw_session.app_config.get_tx_api_url()
    coin['bitcore'].clear()
    coin['bitcore'].append(url)

    tx_api = MyTxApiInsight(coin, '', hw_session.dashd_intf, hw_session.app_config.tx_cache_dir)
    client = hw_session.hw_client
    inputs = []
    outputs = []
    inputs_amount = 0
    for utxo_index, utxo in enumerate(utxos_to_spend):
        if not utxo.bip32_path:
            raise Exception('No BIP32 path for UTXO ' + utxo.txid)

        address_n = dash_utils.bip32_path_string_to_n(utxo.bip32_path)
        it = trezor_proto.TxInputType(
            address_n=address_n,
            prev_hash=binascii.unhexlify(utxo.txid),
            prev_index=int(utxo.output_index))

        inputs.append(it)
        inputs_amount += utxo.satoshis

    outputs_amount = 0
    for out in tx_outputs:
        outputs_amount += out.satoshis
        if out.address[0] in dash_utils.get_chain_params(dash_network).B58_PREFIXES_SCRIPT_ADDRESS:
            stype = trezor_proto.OutputScriptType.PAYTOSCRIPTHASH
            logging.debug('Transaction type: PAYTOSCRIPTHASH' + str(stype))
        elif out.address[0] in dash_utils.get_chain_params(dash_network).B58_PREFIXES_PUBKEY_ADDRESS:
            stype = trezor_proto.OutputScriptType.PAYTOADDRESS
            logging.debug('Transaction type: PAYTOADDRESS ' + str(stype))
        else:
            raise Exception('Invalid prefix of the destination address.')
        if out.bip32_path:
            address_n = dash_utils.bip32_path_string_to_n(out.bip32_path)
        else:
            address_n = None

        ot = trezor_proto.TxOutputType(
            address=out.address if address_n is None else None,
            address_n=address_n,
            amount=out.satoshis,
            script_type=stype
        )
        outputs.append(ot)

    if outputs_amount + tx_fee != inputs_amount:
        raise Exception('Transaction validation failure: inputs + fee != outputs')

    try:
        for skip_cache in (False, True):
            txes = load_prev_txes(tx_api, skip_cache)
            try:
                signed = btc.sign_tx(client, hw_session.app_config.hw_coin_name, inputs, outputs, prev_txes=txes)
                return signed[1], inputs_amount
            except exceptions.Cancelled:
                raise
            except Exception as e:
                if skip_cache:
                    raise
                log.exception('Exception occurred while signing transaction. Turning off the transaction cache '
                              'and retrying...')
        raise Exception('Internal error: transaction not signed')
    except exceptions.Cancelled:
        raise CancelException('Cancelled')


def sign_message(hw_session: HwSessionInfo, bip32path, message):
    client = hw_session.hw_client
    address_n = dash_utils.bip32_path_string_to_n(bip32path)
    try:
        return btc.sign_message(client, hw_session.app_config.hw_coin_name, address_n, message)
    except exceptions.Cancelled:
        raise CancelException('Cancelled')


def change_pin(hw_session: HwSessionInfo, remove=False):
    if hw_session.hw_client:
        device.change_pin(hw_session.hw_client, remove)
    else:
        raise Exception('HW client not set.')


def enable_passphrase(hw_session: HwSessionInfo, passphrase_enabled):
    try:
        device.apply_settings(hw_session.hw_client, use_passphrase=passphrase_enabled)
    except exceptions.Cancelled:
        pass


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
        client = connect_trezor(hw_device_id)

        if client:
            device.wipe(client)
            hw_device_id = client.features.device_id
            client.close()
            return hw_device_id, False
        else:
            raise Exception('Couldn\'t connect to Trezor device.')

    except CallException as e:
        if client:
            client.close()
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            raise
        else:
            return hw_device_id, True  # cancelled by user

    except CancelException:
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
    mnem =  Mnemonic('english')

    def ask_for_word(type):
        nonlocal mnem
        msg = "Enter one word of mnemonic: "
        word = ask_for_word_callback(msg, mnem.wordlist)
        if not word:
            raise exceptions.Cancelled
        return word

    client = None
    try:
        client = connect_trezor(hw_device_id)

        if client:
            if client.features.initialized:
                device.wipe(client)
                hw_device_id = client.features.device_id

            device.recover(client, word_count, passphrase_enabled, pin_enabled, hw_label, language='english',
                           input_callback=ask_for_word)
            return hw_device_id, False
        else:
            raise Exception('Couldn\'t connect to Trezor device.')

    except exceptions.Cancelled:
        return hw_device_id, True

    except CancelException:
        return hw_device_id, True  # cancelled by user

    finally:
        if client:
            client.close()


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
        Ret[1]: False, if the user cancelled the operation. In this situation we deliberately don't raise the
            'cancelled' exception, because in the case of changing of the device id (when wiping) we want to pass
            it back to the caller function.
    """
    client = None
    try:
        client = connect_trezor(hw_device_id)

        if client:
            if client.features.initialized:
                device.wipe(client)
                hw_device_id = client.features.device_id

            device.reset(client, display_random=True, strength=strength, passphrase_protection=passphrase_enabled,
                                pin_protection=pin_enabled, label=hw_label, language='english', u2f_counter=0,
                                skip_backup=False)
            client.close()
            return hw_device_id, False
        else:
            raise Exception('Couldn\'t connect to Trezor device.')

    except CallException as e:
        if client:
            client.close()
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            raise
        else:
            return hw_device_id, True  # cancelled by user

    except CancelException:
        if client:
            client.close()
        return hw_device_id, True  # cancelled by user

