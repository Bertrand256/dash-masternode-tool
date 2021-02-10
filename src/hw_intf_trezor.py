#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import sys
from typing import Optional, Tuple, List, Iterable, Type
import binascii

from mnemonic import Mnemonic
from trezorlib.client import TrezorClient, PASSPHRASE_ON_DEVICE
from trezorlib.exceptions import TrezorFailure
from trezorlib.transport import Transport
from trezorlib import messages as trezor_proto, exceptions, btc
from trezorlib.ui import PIN_CURRENT, PIN_NEW, PIN_CONFIRM
from trezorlib import device
import trezorlib.firmware as firmware

import dash_utils
import hw_common
from common import CancelException
from hw_common import ask_for_pass_callback, ask_for_pin_callback, \
    ask_for_word_callback, HWSessionBase, HWType
import logging
import wallet_common

log = logging.getLogger('dmt.hw_intf_trezor')


class TrezorUi(object):
    def __init__(self):
        self.prompt_shown = False
        pass

    @staticmethod
    def get_pin(code=None) -> str:
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

    @staticmethod
    def get_passphrase(available_on_device: bool) -> str:
        passphrase = ask_for_pass_callback(available_on_device)
        if passphrase is hw_common.PASSPHRASE_ON_DEVICE:
            return PASSPHRASE_ON_DEVICE
        else:
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
        # workround for the issue introduced by Windows update #1903
        # details: https://github.com/spesmilo/electrum/issues/5420:
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
        use_hid=True) -> List[hw_common.HWDevice]:
    ret_list = []
    exception: Optional[Exception] = None
    device_ids = []
    in_bootloader_mode = False

    devices = enumerate_devices(use_webusb=use_webusb, use_bridge=use_bridge, use_udp=use_udp, use_hid=use_hid)
    for d in devices:
        try:
            client = MyTrezorClient(d, ui=TrezorUi())

            if client.features.bootloader_mode:
                if in_bootloader_mode:
                    # in bootloader mode the device_id attribute isn't available, so for a given client object
                    # we are unable to distinguish between being the same device reached with the different
                    # transport and being another device
                    # for that reason, to avoid returning duplicate clients for the same device, we don't return
                    # more than one instance of a device in bootloader mod
                    client.close()
                    continue
                in_bootloader_mode = True

            device_id = client.get_device_id()
            if not device_id and hasattr(d, 'device') and getattr(d, 'device').__class__.__name__ == 'USBDevice' and \
                    hasattr(getattr(d, 'device'), 'getSerialNumber'):
                device_id = getattr(d, 'device').getSerialNumber()

            if (not client.features.bootloader_mode or allow_bootloader_mode) and \
                    (device_id not in device_ids or client.features.bootloader_mode):

                version = f'{client.features.major_version}.{client.features.minor_version}.' \
                          f'{client.features.patch_version}'
                device_model = 'Trezor ' + {'1': 'One'}.get(client.features.model, client.features.model)

                ret_list.append(
                    hw_common.HWDevice(
                        hw_type=HWType.trezor,
                        device_id=device_id,
                        device_label=client.features.label if client.features.label else None,
                        device_version=version,
                        device_model=device_model,
                        client=client if return_clients else None,
                        bootloader_mode=client.features.bootloader_mode,
                        transport=d
                    ))
                device_ids.append(client.features.device_id)  #it's empty in bootloader mode
                if not return_clients:
                    client.close()
            else:
                # the same device is already connected using different connection medium
                client.close()
        except Exception as e:
            logging.warning(f'Cannot create Trezor client ({d.__class__.__name__}) due to the following error: ' +
                            str(e))
            exception = e

    if not ret_list and exception:
        raise exception
    return ret_list


def open_session(hw_device_transport: object) -> Optional[MyTrezorClient]:
    client = MyTrezorClient(hw_device_transport, ui=TrezorUi())
    logging.info('Trezor connected. Firmware version: %s.%s.%s, vendor: %s, initialized: %s, '
                 'pp_protection: %s, bootloader_mode: %s ' %
                 (str(client.features.major_version),
                  str(client.features.minor_version),
                  str(client.features.patch_version), str(client.features.vendor),
                  str(client.features.initialized),
                  str(client.features.passphrase_protection),
                  str(client.features.bootloader_mode)))
    return client


def close_session(client: MyTrezorClient):
    client.close()


def json_to_tx(tx_json):
    t = btc.from_json(tx_json)
    dip2_type = tx_json.get("type", 0)

    if t.version == 3 and dip2_type != 0:
        # It's a DIP2 special TX with payload

        if "extraPayloadSize" not in tx_json or "extraPayload" not in tx_json:
            raise ValueError("Payload data missing in DIP2 transaction")

        if tx_json["extraPayloadSize"] * 2 != len(tx_json["extraPayload"]):
            raise ValueError(
                "extra_data_len (%d) does not match calculated length (%d)"
                % (tx_json["extraPayloadSize"], len(tx_json["extraPayload"]) * 2)
            )
        t.extra_data = dash_utils.num_to_varint(tx_json["extraPayloadSize"]) + bytes.fromhex(
            tx_json["extraPayload"]
        )

    # Trezor firmware doesn't understand the split of version and type, so let's mimic the
    # old serialization format
    t.version |= dip2_type << 16

    return t


class MyTxApiInsight(object):

    def __init__(self, dashd_inf, cache_dir):
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
                    except Exception:
                        raise
                else:
                    raise Exception('Invalid operation type: ' + path[0])
            else:
                Exception('Needs tx hash in argument list')
        else:
            raise Exception('No arguments')

    def get_tx(self, txhash: str):
        tx_json = None
        try:
            tx_json = self.fetch_json("tx", txhash)
            return json_to_tx(tx_json)
        except Exception as e:
            log.error(str(e))
            log.error('tx data: ' + str(tx_json))
            raise


def sign_tx(hw_session: HWSessionBase, utxos_to_spend: List[wallet_common.UtxoType],
            tx_outputs: List[wallet_common.TxOutputType], tx_fee):
    """
    Creates a signed transaction.
    :param hw_session:
    :param utxos_to_spend: list of utxos to send
    :param tx_outputs: list of transaction outputs
    :param tx_fee: transaction fee
    :return: tuple (serialized tx, total transaction amount in satoshis)
    """

    def load_prev_txes(tx_api_, skip_cache_: bool = False):
        txes_ = {}
        tx_api_.skip_cache = skip_cache_
        for utxo_ in utxos_to_spend:
            prev_hash_bin = bytes.fromhex(utxo_.txid)
            if prev_hash_bin not in txes_:
                tx = tx_api_.get_tx(utxo_.txid)
                txes_[prev_hash_bin] = tx
        return txes_

    insight_network = 'insight_dash'
    if hw_session.is_testnet():
        insight_network += '_testnet'
    dash_network = hw_session.dash_network

    tx_api = MyTxApiInsight(hw_session.dashd_intf, hw_session.tx_cache_dir)
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
                signed = btc.sign_tx(client, hw_session.hw_coin_name, inputs, outputs, prev_txes=txes)
                return signed[1], inputs_amount
            except exceptions.Cancelled:
                raise
            except Exception:
                if skip_cache:
                    raise
                log.exception('Exception occurred while signing transaction. Turning off the transaction cache '
                              'and retrying...')
        raise Exception('Internal error: transaction not signed')
    except exceptions.Cancelled:
        raise CancelException('Cancelled')


def sign_message(hw_session: HWSessionBase, bip32path, message):
    client = hw_session.hw_client
    address_n = dash_utils.bip32_path_string_to_n(bip32path)
    try:
        return btc.sign_message(client, hw_session.hw_coin_name, address_n, message)
    except exceptions.Cancelled:
        raise CancelException('Cancelled')


def ping(hw_client, message: str):
    hw_client.ping(message, True)


def change_pin(hw_client, remove=False):
    if hw_client:
        device.change_pin(hw_client, remove)
    else:
        raise Exception('HW client not set.')


def enable_passphrase(hw_client, passphrase_enabled):
    try:
        device.apply_settings(hw_client, use_passphrase=passphrase_enabled)
    except exceptions.Cancelled:
        pass


def set_passphrase_always_on_device(hw_client, enabled: bool):
    try:
        device.apply_settings(hw_client, passphrase_always_on_device=enabled)
    except exceptions.Cancelled:
        pass


def set_wipe_code(hw_client, remove=False):
    if hw_client:
        device.change_wipe_code(hw_client, remove)
    else:
        raise Exception('HW client not set.')


def wipe_device(hw_device_id) -> Tuple[str, bool]:
    # todo: change argument type to HWDevice
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
        client = open_session(hw_device_id)

        if client:
            device.wipe(client)
            hw_device_id = client.features.device_id
            client.close()
            return hw_device_id, False
        else:
            raise Exception('Couldn\'t connect to Trezor device.')

    except TrezorFailure as e:
        if client:
            client.close()
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            raise
        else:
            return hw_device_id, True  # cancelled by user
    except exceptions.Cancelled:
        return hw_device_id, True  # cancelled by user

    except CancelException:
        if client:
            client.close()
        return hw_device_id, True  # cancelled by user


def firmware_update(hw_client, raw_data: bytes):
    try:
        return firmware.update(hw_client, raw_data)
    except TrezorFailure as e:
        if e.args and e.args[0] == 99:
            raise CancelException('Cancelled')
        else:
            raise


def recover_device(hw_device_id: str, word_count: int, passphrase_enabled: bool, pin_enabled: bool, hw_label: str) \
        -> Tuple[str, bool]:
    # todo: change argument type to HWDevice
    """
    :param hw_device_id:
    :param word_count:
    :param passphrase_enabled:
    :param pin_enabled:
    :param hw_label:
    :return: Tuple
        [0]: Device id. If a device is wiped before initializing with mnemonics, a new device id is generated. It's
            returned to the caller.
        [1]: True, if the user cancelled the operation. In this case we deliberately don't raise the 'cancelled'
            exception, because in the case of changing of the device id (when wiping) we want to pass the new device
            id back to the caller.
    """
    mnem = Mnemonic('english')

    def ask_for_word(_type):
        nonlocal mnem
        msg = "Enter one word of mnemonic: "
        word = ask_for_word_callback(msg, mnem.wordlist)
        if not word:
            raise exceptions.Cancelled
        return word

    client = None
    try:
        client = open_session(hw_device_id)

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
    # todo: change argument type to HWDevice
    """
    Initialize device with a newly generated words.
    :param hw_device_id: id of the device selected by the user
    :param strength: number of bits of entropy (will have impact on number of words)
    :param passphrase_enabled: if True, hw will have passphrase enabled
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
        client = open_session(hw_device_id)

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

    except TrezorFailure as e:
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
