#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import hashlib
import sys
from typing import Optional, Tuple, List, Iterable, Type, Any, Literal
import binascii

from PyQt5.QtWidgets import QMessageBox, QWidget
from mnemonic import Mnemonic
from trezorlib.client import TrezorClient, PASSPHRASE_ON_DEVICE
from trezorlib.exceptions import TrezorFailure
from trezorlib.transport import Transport
from trezorlib import messages as trezor_proto, exceptions, btc, messages
from trezorlib.ui import PIN_CURRENT, PIN_NEW, PIN_CONFIRM
from trezorlib import device
import trezorlib.firmware
import trezorlib

import dash_utils
import hw_common
from app_runtime_data import AppRuntimeData
from common import CancelException, HwNotInitialized
from hw_common import ask_for_pass_callback, ask_for_pin_callback, \
    ask_for_word_callback, HWSessionBase, HWType
import logging
import wallet_common
from wnd_utils import WndUtils


log = logging.getLogger('dmt.hw_intf_trezor')


BOOTLOADER_MODE_DUMMY_DEVICE_ID = '0000'


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

    def validate_firmware_internal(self, version, fw, expected_fingerprint=None):
        """Adapted version of the 'validate_firmware' function from trezorlib"""
        if version == trezorlib.firmware.FirmwareFormat.TREZOR_ONE:
            if fw.embedded_onev2:
                log.debug("Trezor One firmware with embedded v2 image (1.8.0 or later)")
            else:
                log.debug("Trezor One firmware image.")
        elif version == trezorlib.firmware.FirmwareFormat.TREZOR_ONE_V2:
            log.debug("Trezor One v2 firmware (1.8.0 or later)")
        elif version == trezorlib.firmware.FirmwareFormat.TREZOR_T:
            log.debug("Trezor T firmware image.")
            vendor = fw.vendor_header.text
            vendor_version = "{major}.{minor}".format(**fw.vendor_header.version)
            log.debug("Vendor header from {}, version {}".format(vendor, vendor_version))

        try:
            trezorlib.firmware.validate(version, fw, allow_unsigned=False)
            log.debug("Signatures are valid.")
        except trezorlib.firmware.Unsigned:
            if WndUtils.query_dlg('No signatures found. Continue?',
                                  buttons=QMessageBox.Yes | QMessageBox.No,
                                  default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.No:
                raise CancelException()

            try:
                trezorlib.firmware.validate(version, fw, allow_unsigned=True)
                log.debug("Unsigned firmware looking OK.")
            except trezorlib.firmware.FirmwareIntegrityError as e:
                log.exception(e)
                raise Exception("Firmware validation failed, aborting.")
        except trezorlib.firmware.FirmwareIntegrityError as e:
            log.exception(e)
            raise Exception("Firmware validation failed, aborting.")

        fingerprint = trezorlib.firmware.digest(version, fw).hex()
        log.debug("Firmware fingerprint: {}".format(fingerprint))
        if version == trezorlib.firmware.FirmwareFormat.TREZOR_ONE and fw.embedded_onev2:
            fingerprint_onev2 = trezorlib.firmware.digest(
                trezorlib.firmware.FirmwareFormat.TREZOR_ONE_V2, fw.embedded_onev2
            ).hex()
            log.debug("Embedded v2 image fingerprint: {}".format(fingerprint_onev2))
        if expected_fingerprint and fingerprint != expected_fingerprint:
            log.error("Expected fingerprint: {}".format(expected_fingerprint))
            raise Exception("Fingerprints do not match, aborting.")

    def validate_firmware(self, fingerprint: str, firmware_data: bytes):
        """
        Parses and validates firmware without the need to deal with parsing the firmware before validating to
        meet trezorlib requirements.
        """
        version, fw = trezorlib.firmware.parse(firmware_data)
        self.validate_firmware_internal(version, fw, fingerprint)

    def firmware_update(self, fingerprint: str, firmware_data: bytes):
        """Adapted version of the 'firmware_update' function from trezorlib"""
        f = self.features
        bootloader_version = (f.major_version, f.minor_version, f.patch_version)
        bootloader_onev2 = f.major_version == 1 and bootloader_version >= (1, 8, 0)
        model = f.model or "1"

        try:
            version, fw = trezorlib.firmware.parse(firmware_data)
        except Exception as e:
            raise

        self.validate_firmware_internal(version, fw, fingerprint)

        if (
                bootloader_onev2
                and version == trezorlib.firmware.FirmwareFormat.TREZOR_ONE
                and not fw.embedded_onev2
        ):
            raise Exception("Firmware is too old for your device. Aborting.")
        elif not bootloader_onev2 and version == trezorlib.firmware.FirmwareFormat.TREZOR_ONE_V2:
            raise Exception("You need to upgrade to bootloader 1.8.0 first.")

        if bootloader_onev2 and firmware_data[:4] == b"TRZR" and firmware_data[256: 256 + 4] == b"TRZF":
            log.debug("Extracting embedded firmware image.")
            firmware_data = firmware_data[256:]

        try:
            # if f.major_version == 1 and f.firmware_present is not False:
            #     # Trezor One does not send ButtonRequest
            #     "Please confirm the action on your Trezor device"
            trezorlib.firmware.update(self, firmware_data)
            return True

        except exceptions.Cancelled:
            raise CancelException("Update aborted on device.")
        except exceptions.TrezorException as e:
            raise Exception("Update failed: {}".format(e))


def all_transports() -> Iterable[Type[Transport]]:
    from trezorlib.transport.bridge import BridgeTransport
    from trezorlib.transport.hid import HidTransport
    from trezorlib.transport.udp import UdpTransport
    from trezorlib.transport.webusb import WebUsbTransport

    return [cls for cls in (BridgeTransport, WebUsbTransport, HidTransport, UdpTransport) if cls.ENABLED]


def enumerate_devices(
        use_webusb=True,
        use_bridge=True,
        use_udp=True,
        use_hid=True) -> Iterable[Transport]:
    devices = []  # type: List[Transport]
    for transport in all_transports():
        # workaround for the issue introduced by Windows update #1903
        # details: https://github.com/spesmilo/electrum/issues/5420:
        # 1. use BridgeTransport first and then WebUsbTransport
        # 2. if any BridgeTransport devices are found, skip scanning WevUsbTransport devices, otherwise it will
        #     break the related "bridge" devices

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
            log.debug("Enumerating {}: found {} devices".format(name, len(found)))
            devices.extend(found)
        except NotImplementedError:
            log.error("{} does not implement device enumeration".format(name))
        except Exception as e:
            excname = e.__class__.__name__
            log.exception("Failed to enumerate {}. {}: {}".format(name, excname, e))
    return devices


def get_trezor_device_id(hw_client) -> str:
    """
    Return trezor device_id/serial_number. If the device is in bootloader mode, return some constant value as a
    kind of a device identifier, but there will be no way to work with more than one Trezor device in this mode.
    """
    device_id = hw_client.get_device_id()
    if not device_id:
        return BOOTLOADER_MODE_DUMMY_DEVICE_ID
    return device_id


def apply_device_attributes(hw_device: hw_common.HWDevice, client: Any):
    hw_device.device_id = get_trezor_device_id(client)
    hw_device.firmware_version = f'{client.features.major_version}.{client.features.minor_version}.' \
                                 f'{client.features.patch_version}'
    hw_device.model_symbol = client.features.model if client.features.model is not None else '1'
    hw_device.device_label = client.features.label if client.features.label else None
    hw_device.initialized = client.features.initialized
    hw_device.bootloader_mode = client.features.bootloader_mode if client.features.bootloader_mode \
                                                                   is not None else False


def get_device_list(
        allow_bootloader_mode: bool = False,
        use_webusb=True,
        use_bridge=True,
        use_udp=True,
        use_hid=True) -> List[hw_common.HWDevice]:
    ret_list = []
    exception: Optional[Exception] = None
    device_ids = []

    devices = enumerate_devices(use_webusb=use_webusb, use_bridge=use_bridge, use_udp=use_udp, use_hid=use_hid)
    for d in devices:
        try:
            client = MyTrezorClient(d, ui=TrezorUi())

            logging.info('Found device ' + str(d))
            device_id = get_trezor_device_id(client)
            if not device_id:
                logging.warning(f'Skipping device {str(d)} with empty device_id.')
            device_transport_id = hashlib.sha256(str(d).encode('ascii')).hexdigest()

            if (not client.features.bootloader_mode or allow_bootloader_mode) and device_id not in device_ids:

                locked = client.features.unlocked is False
                hw_dev = hw_common.HWDevice(hw_type=HWType.trezor, hw_client=None,
                                            transport_id=device_transport_id, locked=locked)
                apply_device_attributes(hw_dev, client)
                ret_list.append(hw_dev)
                device_ids.append(device_id)
            client.close()
        except Exception as e:
            logging.warning(f'Cannot create Trezor client ({d.__class__.__name__}) due to the following error: ' +
                            str(e))
            exception = e

    if not ret_list and exception:
        raise exception
    return ret_list


def open_session(device_id: str, device_transport_id: str) -> Optional[MyTrezorClient]:
    for d in enumerate_devices():
        client = MyTrezorClient(d, ui=TrezorUi())
        cur_transport_id = hashlib.sha256(str(d).encode('ascii')).hexdigest()
        cur_device_id = get_trezor_device_id(client)
        if cur_device_id == device_id or (client.features.bootloader_mode and cur_transport_id == device_transport_id) \
                or (device_id == BOOTLOADER_MODE_DUMMY_DEVICE_ID and cur_transport_id == device_transport_id):
            # in bootloader mode device_id is not returned from Trezor so to find the device we need
            # to compare transport id based on usb path, but it won't work for bridge transport since each
            # time Trezor is reconnected, transport path reported by Trezor Bridge is different; that's why we
            # scan WebUsb devices first in enumerate_devices

            logging.info('Trezor connected. Firmware version: %s.%s.%s, vendor: %s, initialized: %s, '
                         'pp_protection: %s, bootloader_mode: %s ' %
                         (str(client.features.major_version),
                          str(client.features.minor_version),
                          str(client.features.patch_version), str(client.features.vendor),
                          str(client.features.initialized),
                          str(client.features.passphrase_protection),
                          str(client.features.bootloader_mode)))
            return client
        else:
            client.close()
            del client
    return None


def close_session(client: MyTrezorClient):
    client.close()


def json_to_tx(tx_json):
    t = btc.from_json(tx_json)
    dip2_type = tx_json.get("type", 0)

    t.inputs =[]
    for vin in tx_json["vin"]:
        if "scriptSig" in vin and vin["scriptSig"]["hex"] == "c9":
            i = messages.TxInputType()
            i.prev_hash = b"\0" * 32
            i.prev_index = vin["sequence"]
            i.script_sig = bytes.fromhex(vin["scriptSig"]["hex"])
            i.sequence = vin["sequence"]
            t.inputs.append(i)
        else:
            t.inputs.append(_json_to_input(tx_json, vin))
    t.bin_outputs = [_json_to_bin_output(tx_json, vout) for vout in tx_json["vout"]]

    if t.version == 3 and dip2_type != 0:
        if dip2_type == DashTxType.SPEC_CB_TX:
            tx_json["extraPayload"] = serialize_cbTx(tx_json)
        elif dip2_type == DashTxType.LELANTUS_JSPLIT:
            tx_json["extraPayload"] = serialize_Lelantus(tx_json)
        elif dip2_type == DashTxType.SPARK_SPEND:
            tx_json["extraPayload"] = serialize_Spark(tx_json)
        else:
            raise NotImplementedError("Only spending of V3 coinbase outputs has been inplemented. "
                "Please file an issue at https://github.com/firoorg/firo-masternode-tool/issues containing "
                "the tx type=" + str(dip2_type))
        tx_json["extraPayloadSize"] = len(tx_json["extraPayload"]) >> 1


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


def sign_tx(hw_session: HWSessionBase, rt_data: AppRuntimeData, utxos_to_spend: List[wallet_common.UtxoType],
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
    if rt_data.is_testnet:
        insight_network += '_testnet'
    dash_network = rt_data.dash_network

    tx_api = MyTxApiInsight(rt_data.dashd_intf, rt_data.tx_cache_dir)
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
            amount=utxo.satoshis,
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
                signed = btc.sign_tx(client, rt_data.hw_coin_name, inputs, outputs, prev_txes=txes)
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
    except exceptions.TrezorFailure as e:
        if e.failure.message == 'Device not initialized':
            raise HwNotInitialized(e.failure.message)
        else:
            raise


def sign_message(hw_client, hw_coin_name: str, bip32path: str, message: str):
    address_n = dash_utils.bip32_path_string_to_n(bip32path)
    try:
        return btc.sign_message(hw_client, hw_coin_name, address_n, message)
    except exceptions.Cancelled:
        raise CancelException('Cancelled')
    except exceptions.TrezorFailure as e:
        if e.failure.message == 'Device not initialized':
            raise HwNotInitialized(e.failure.message)
        else:
            raise


def ping(hw_client, message: str):
    hw_client.ping(message, True)


def change_pin(hw_client, remove=False):
    if hw_client:
        try:
            device.change_pin(hw_client, remove)
        except exceptions.Cancelled:
            raise CancelException('Cancelled')
        except exceptions.TrezorFailure as e:
            if e.failure.message == 'Device not initialized':
                raise HwNotInitialized(e.failure.message)
            else:
                raise
    else:
        raise Exception('HW client not set.')


def enable_passphrase(hw_client, passphrase_enabled):
    try:
        device.apply_settings(hw_client, use_passphrase=passphrase_enabled)
    except exceptions.Cancelled:
        pass
    except exceptions.TrezorFailure as e:
        if e.failure.message == 'Device not initialized':
            raise HwNotInitialized(e.failure.message)
        else:
            raise


def set_passphrase_always_on_device(hw_client, enabled: bool):
    try:
        device.apply_settings(hw_client, passphrase_always_on_device=enabled)
    except exceptions.Cancelled:
        pass
    except exceptions.TrezorFailure as e:
        if e.failure.message == 'Device not initialized':
            raise HwNotInitialized(e.failure.message)
        else:
            raise


def set_wipe_code(hw_client, remove=False):
    if hw_client:
        try:
            device.change_wipe_code(hw_client, remove)
        except exceptions.Cancelled:
            pass
        except exceptions.TrezorFailure as e:
            if e.failure.message == 'Device not initialized':
                raise HwNotInitialized(e.failure.message)
            else:
                raise
    else:
        raise Exception('HW client not set.')


def set_label(hw_client, label: str):
    if hw_client:
        try:
            device.apply_settings(hw_client, label=label)
        except exceptions.Cancelled:
            pass
        except exceptions.TrezorFailure as e:
            if e.failure.message == 'Device not initialized':
                raise HwNotInitialized(e.failure.message)
            else:
                raise
    else:
        raise Exception('HW client not set.')


def sd_protect(hw_client, operation: Literal["enable", "disable", "refresh"]):
    if hw_client:
        op_code = {
            "enable": messages.SdProtectOperationType.ENABLE,
            "disable": messages.SdProtectOperationType.DISABLE,
            "refresh": messages.SdProtectOperationType.REFRESH,
        }.get(operation)
        if op_code is not None:
            try:
                device.sd_protect(hw_client, op_code)
            except exceptions.Cancelled:
                pass
            except exceptions.TrezorFailure as e:
                if e.failure.message == 'Device not initialized':
                    raise HwNotInitialized(e.failure.message)
                else:
                    raise
        else:
            raise Exception('Invalid operation code.')
    else:
        raise Exception('HW client not set.')


def wipe_device(hw_device_id: str, hw_device_transport_id: Any, hw_client: Optional[Any]) -> str:
    """
    :return: new device id
    """
    client = None
    try:
        if not hw_client:
            client = open_session(hw_device_id, hw_device_transport_id)
        else:
            client = hw_client

        if client:
            device.wipe(client)
            hw_device_id = client.features.device_id
            return hw_device_id
        else:
            raise Exception('Couldn\'t connect to Trezor device.')

    except TrezorFailure as e:
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            if e.failure.message == 'Device not initialized':
                raise HwNotInitialized(e.failure.message)
            else:
                raise
        else:
            raise CancelException
    except exceptions.Cancelled:
        raise CancelException
    finally:
        if client and hw_client != client:
            client.close()


def recover_device(hw_device_id: str, hw_device_transport_id: Any, hw_client: Any, word_count: int,
                   passphrase_enabled: bool, pin_enabled: bool, hw_label: str,
                   input_type: Literal["scrambled_words", "matrix"], parent_window: Optional[QWidget] = None) -> Optional[str]:
    mnem = Mnemonic('english')
    type = {
        "scrambled_words": messages.RecoveryDeviceType.ScrambledWords
    }.get(input_type, messages.RecoveryDeviceType.Matrix)

    def ask_for_word(_type):
        nonlocal mnem
        if _type == 0:
            msg = "Enter one word of mnemonic: "
            word = ask_for_word_callback(msg, mnem.wordlist, parent_window)
            if not word:
                raise exceptions.Cancelled
            return word
        elif _type in (1, 2):
            # _type
            # 1: matrix has three columns
            # 2: matrix has two columns
            element = hw_common.ask_for_martix_element_callback("<span>Select the matrix element that corresponds<br>"
                                                                "to the part of the word displayed on<br>"
                                                                "the device screen</span>",
                                                                columns=3 if _type == 1 else 2,
                                                                parent_window=parent_window)
            if element:
                return element
            else:
                raise exceptions.Cancelled
        else:
            raise exceptions.Cancelled

    client = None
    try:
        if not hw_client:
            client = open_session(hw_device_id, hw_device_transport_id)
        else:
            client = hw_client

        if client:
            if client.features.initialized:
                device.wipe(client)
                hw_device_id = client.features.device_id

            device.recover(client, word_count, passphrase_enabled, pin_enabled, hw_label,
                           input_callback=ask_for_word, type=type)
            return hw_device_id
        else:
            raise Exception('Couldn\'t connect to Trezor device.')

    except exceptions.Cancelled:
        raise CancelException
    except exceptions.TrezorFailure as e:
        if e.failure.message == 'Device not initialized':
            raise HwNotInitialized(e.failure.message)
        else:
            raise
    finally:
        if client and hw_client != client:
            client.close()


def initialize_device(hw_device_id: str, hw_device_transport_id: Any, hw_client: Any, strength: int,
                      passphrase_enabled: bool, pin_enabled: bool, hw_label: str) -> Optional[str]:
    client = None
    try:
        if not hw_client:
            client = open_session(hw_device_id, hw_device_transport_id)
        else:
            client = hw_client

        if client:
            if client.features.initialized:
                device.wipe(client)
                hw_device_id = client.features.device_id

            device.reset(client, display_random=True, strength=strength, passphrase_protection=passphrase_enabled,
                         pin_protection=pin_enabled, label=hw_label, language='english', u2f_counter=0,
                         skip_backup=False)
            return hw_device_id
        else:
            raise Exception('Couldn\'t connect to Trezor device.')

    except TrezorFailure as e:
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            if e.failure.message == 'Device not initialized':
                raise HwNotInitialized(e.failure.message)
            else:
                raise
        else:
            raise CancelException
    except exceptions.Cancelled:
        raise CancelException
    finally:
        if client and hw_client != client:
            client.close()