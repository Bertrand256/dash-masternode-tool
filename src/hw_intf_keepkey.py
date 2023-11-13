#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import binascii
import hashlib
import logging
import threading
import unicodedata
import hid
from decimal import Decimal
from typing import Optional, Tuple, List, Generator, Iterator, Any

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtWidgets import QDialog, QLineEdit, QWidget
from keepkeylib.transport_hid import HidTransport, DEVICE_IDS, is_normal_link, is_debug_link
from keepkeylib.transport_webusb import WebUsbTransport
from keepkeylib.client import TextUIMixin as keepkey_TextUIMixin, format_mnemonic
from keepkeylib.client import ProtocolMixin as keepkey_ProtocolMixin
from keepkeylib.client import BaseClient as keepkey_BaseClient, CallException
from keepkeylib import messages_pb2 as keepkey_proto
from keepkeylib.tx_api import TxApiInsight
from mnemonic import Mnemonic

import dash_utils
import hw_common
from app_runtime_data import AppRuntimeData
from common import CancelException
from hw_common import ask_for_pin_callback, ask_for_pass_callback, ask_for_word_callback, \
    HWSessionBase, HWDevice, HWType
import keepkeylib.types_pb2 as proto_types
import wallet_common
from hw_common import clean_bip32_path

from dash_tx import DashTxType, serialize_cbTx, serialize_Lelantus, serialize_Spark

from wnd_utils import WndUtils


class CharInputLineEdit(QLineEdit):
    """
    Used in conjunction with CharInputDlg to get word characters when recovering Keepkey. Created to make
    possible responding to the keyPressEvent, which is not feasible with the standard QLineEdit.
    """
    keyPressed = QtCore.pyqtSignal(int)

    def __init__(self, *args):
        super().__init__(*args)
        self.setEchoMode(QLineEdit.Password)

    def keyPressEvent(self, event):
        # convert the Qt key code to an ascii character meeting the needs of
        # the MyKeepkeyTextUIMixin.callback_CharacterRequest method.
        key_ascii = event.key()
        if key_ascii == Qt.Key_Tab:
            key_ascii = 0x09
        elif key_ascii == Qt.Key_Backspace:
            key_ascii = 0x08
        elif key_ascii in (Qt.Key_Enter, Qt.Key_Return):
            key_ascii = 0x0d
        elif key_ascii == Qt.Key_Escape:
            key_ascii = 0x03

        super().keyPressEvent(event)
        self.keyPressed.emit(key_ascii)


class CharInputDlg(QDialog):
    """
    The class used as an intermediary in retrieving individual characters of recovery words in collaboration with
    Keppkey's recovery cipher matrix.
    """
    def __init__(self, parent: Optional[QWidget] = None):
        QDialog.__init__(self, parent)
        self.ev = threading.Event()
        self.key_pressed: int = 0
        self.waiting_for_input = False
        self.edt_input = CharInputLineEdit()
        self.setupUi(self)

    def setupUi(self, dialog: QDialog):
        self.setObjectName("CharInputDlg")
        self.resize(486, 96)
        size_policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        size_policy.setHorizontalStretch(0)
        size_policy.setVerticalStretch(0)
        size_policy.setHeightForWidth(self.sizePolicy().hasHeightForWidth())
        self.setSizePolicy(size_policy)
        self.setModal(True)
        self.layout_main = QtWidgets.QVBoxLayout(self)
        self.lbl_message1 = QtWidgets.QLabel(self)
        self.lbl_message1.setWordWrap(False)
        self.layout_main.addWidget(self.lbl_message1)
        self.lbl_message2 = QtWidgets.QLabel(self)
        self.layout_main.addWidget(self.lbl_message2)
        self.layout_main.addWidget(self.edt_input)
        self.setWindowTitle("Keepkey recovery words input")
        self.lbl_message1.setText(
            "<span>Use recovery cipher on device to input mnemonic. Words are autocompleted<br>"
            "at 3 or 4 characters (use <b>spacebar</b> to progress to next word after match, use<br>"
            "<b>backspace</b> to correct bad character or word entries).</span>")
        self.lbl_message2.setText("")
        self.edt_input.keyPressed.connect(self.on_key_pressed)

    def on_key_pressed(self, key: int):
        self.key_pressed = key
        self.ev.set()

    def clear(self):
        self.edt_input.clear()

    def showEvent(self, _):
        def set():
            self.setFixedSize(self.sizeHint())
        QTimer.singleShot(100, set)

    def closeEvent(self, _):
        if self.waiting_for_input:
            self.key_pressed = 0x03  # simulate pressing escape

    def ask_for_char(self, cur_characters: Optional[str], label: Optional[str] = None) -> int:
        if label:
            self.lbl_message2.setText('<b>' + label + '</b>')
        if cur_characters is not None:
            self.edt_input.setText(cur_characters)
        self.key_pressed = None
        self.edt_input.setFocus()
        try:
            self.waiting_for_input = True
            while True:
                QtWidgets.qApp.processEvents()
                if self.key_pressed:
                    break
        finally:
            self.waiting_for_input = False

        return self.key_pressed


class MyKeepkeyTextUIMixin(keepkey_TextUIMixin):

    def __init__(self, transport, ask_for_pin_fun, ask_for_pass_fun, passphrase_encoding):
        keepkey_TextUIMixin.__init__(self, transport)
        self.ask_for_pin_fun = ask_for_pin_fun
        self.ask_for_pass_fun = ask_for_pass_fun
        self.passphrase_encoding = passphrase_encoding
        self.__mnemonic = Mnemonic('english')
        self.char_request_dialog: Optional[CharInputDlg] = None
        self.char_request_dialog_shown: bool = False
        self.parent_dialog: Optional[QWidget] = None

    def _request_character(self, cur_characters: Optional[str], label: Optional[str] = None) -> int:
        if not self.char_request_dialog:
            self.char_request_dialog = CharInputDlg(self.parent_dialog)
            self.char_request_dialog.show()
            self.char_request_dialog_shown = True
        elif not self.char_request_dialog_shown:
            self.char_request_dialog.clear()
            self.char_request_dialog.show()
            self.char_request_dialog_shown = True
        return self.char_request_dialog.ask_for_char(cur_characters, label)

    def request_character(self, cur_characters: Optional[str], label: Optional[str] = None) -> int:
        return WndUtils.call_in_main_thread(self._request_character, cur_characters, label)

    def hide_request_character_dialog(self):
        if self.char_request_dialog and self.char_request_dialog_shown:
            def hide():
                self.char_request_dialog.hide()
                del self.char_request_dialog
                self.char_request_dialog = None
                self.char_request_dialog_shown = False
            WndUtils.call_in_main_thread(hide)

    def callback_PassphraseRequest(self, msg):
        passphrase = self.ask_for_pass_fun()
        if passphrase is None:
            raise CancelException('Cancelled')
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
            raise CancelException('Cancelled')
        return keepkey_proto.PinMatrixAck(pin=pin)

    def callback_WordRequest(self, msg):
        msg = "Enter one word of mnemonic: "
        word = ask_for_word_callback(msg, self.__mnemonic.wordlist)
        if not word:
            raise CancelException('Cancelled')
        return keepkey_proto.WordAck(word=word)

    def callback_CharacterRequest(self, msg):
        from keepkeylib import messages_pb2 as proto
        if self.character_request_first_pass:
            self.character_request_first_pass = False

        # format mnemonic for console
        input_label = f'WORD {msg.word_pos + 1}:'

        while True:
            cur_str = msg.character_pos * '*'
            character_ascii = self.request_character(cur_str, input_label)

            # capture escape
            if character_ascii in (3, 4):
                return proto.Cancel()

            if 65 <= character_ascii <= 90:
                character_ascii = ord(chr(character_ascii).lower())

            if 97 <= character_ascii <= 122 and msg.character_pos != 4:
                # capture characters a-z
                character = chr(character_ascii).lower()
                return proto.CharacterAck(character=character)

            elif character_ascii == 32 and msg.word_pos < 23 and msg.character_pos >= 3:
                # capture spaces
                return proto.CharacterAck(character=' ')

            elif character_ascii == 8 or character_ascii == 127 \
            and (msg.word_pos > 0 or msg.character_pos > 0):
                # capture backspaces
                return proto.CharacterAck(delete=True)

            elif character_ascii == 13 and msg.word_pos in (11, 17, 23):
                # capture returns
                return proto.CharacterAck(done=True)


class MyKeepkeyClient(keepkey_ProtocolMixin, MyKeepkeyTextUIMixin, keepkey_BaseClient):
    def __init__(self, transport, ask_for_pin_fun, ask_for_pass_fun, passphrase_encoding):
        keepkey_ProtocolMixin.__init__(self, transport, ask_for_pin_fun, ask_for_pass_fun, passphrase_encoding)
        MyKeepkeyTextUIMixin.__init__(self, transport, ask_for_pin_fun, ask_for_pass_fun, passphrase_encoding)
        keepkey_BaseClient.__init__(self, transport)

    def validate_firmware(self, fingerprint: str, firmware_data: bytes):
        try:
            if firmware_data[:8] == b'4b504b59':
                firmware_data = binascii.unhexlify(firmware_data)
        except Exception as e:
            logging.exception('Error while decoding hex data.')
            raise Exception(f'Error while decoding hex data: ' + str(e))

        if firmware_data[:4] != b'KPKY':
            raise Exception('KeepKey firmware header expected')

        cur_fp = hashlib.sha256(firmware_data).hexdigest()
        if fingerprint and cur_fp != fingerprint:
            raise Exception("Fingerprints do not match.")


class MyHidTransport(HidTransport):
    """
    Class based on Keepkey's HidTransport, the purpose of which is to modify the enumerate method to return
    the serial number of the hw device, needed when switching between normal and bootloader mode.
    """
    def __init__(self, device_paths, *args, **kwargs):
        super(MyHidTransport, self).__init__(device_paths, *args, **kwargs)

    @classmethod
    def enumerate(cls):
        """
        Slightly modified function
        """
        devices = {}
        for d in hid.enumerate(0, 0):
            vendor_id = d['vendor_id']
            product_id = d['product_id']
            serial_number = d['serial_number']
            interface_number = d['interface_number']
            path = d['path']

            # HIDAPI on Mac cannot detect correct HID interfaces, so device with
            # DebugLink doesn't work on Mac...
            if devices.get(serial_number) is not None and devices[serial_number][0] == path:
                raise Exception("Two devices with the same path and S/N found. This is Mac, right? :-/")

            if (vendor_id, product_id) in DEVICE_IDS:
                devices.setdefault(serial_number, [None, None, None])
                if is_normal_link(d):
                    devices[serial_number][0] = path
                elif is_debug_link(d):
                    devices[serial_number][1] = path
                else:
                    raise Exception("Unknown USB interface number: %d" % interface_number)
                devices[serial_number][2] = serial_number  # to pass serial number we're using the last element

        # List of two-tuples (path_normal, path_debuglink)
        return list(devices.values())


def enumerate_devices(device_id: Optional[str]) -> Iterator[Tuple[type, any, str]]:
    transports = [MyHidTransport, WebUsbTransport]
    for t in transports:
        for d in t.enumerate():
            if d.__class__.__name__ == 'USBDevice' and hasattr(d, 'getSerialNumber'):
                cur_device_id = d.getSerialNumber()
            elif t == MyHidTransport and isinstance(d, list) and len(d) >= 3:
                cur_device_id = d[2]
                d[2] = None  # restore None in the last element of the list used by MyHidTransport.enumerate
            else:
                cur_device_id = None
                logging.warning('Could not get the device serial number')

            if not device_id:
                yield t, d, cur_device_id
            elif cur_device_id == device_id:
                yield t, d, cur_device_id
                break


def apply_device_attributes(hw_device: hw_common.HWDevice, client: Any, serial_number: Optional[str] = None):
    hw_device.device_id = serial_number if serial_number else client.features.device_id
    hw_device.firmware_version = f'{client.features.major_version}.{client.features.minor_version}.' \
                                 f'{client.features.patch_version}'
    hw_device.model_symbol = 'keepkey'
    hw_device.device_label = client.features.label if client.features.label else None
    hw_device.initialized = client.features.initialized
    hw_device.bootloader_mode = client.features.bootloader_mode if client.features.bootloader_mode \
                                                                   is not None else False


def get_device_list(passphrase_encoding: Optional[str] = 'NFC',
                    allow_bootloader_mode: bool = False) -> List[HWDevice]:

    ret_list = []
    exception: Optional[Exception] = None
    device_ids = []
    was_bootloader_mode = False

    for transport_cls, d, serial_number in enumerate_devices(None):
        try:
            transport = transport_cls(d)
            client = MyKeepkeyClient(transport, ask_for_pin_callback, ask_for_pass_callback, passphrase_encoding)
            device_transport_id = hashlib.sha256(str(d).encode('ascii')).hexdigest()
            device_id = serial_number

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

            if (not client.features.bootloader_mode or allow_bootloader_mode) and device_id not in device_ids:

                hw_dev = hw_common.HWDevice(hw_type=HWType.keepkey, hw_client=None,
                                            transport_id=device_transport_id)
                apply_device_attributes(hw_dev, client, device_id)
                ret_list.append(hw_dev)
                device_ids.append(device_id)
            client.close()
        except Exception as e:
            logging.warning(
                f'Cannot create Keepkey client ({d.__class__.__name__}) due to the following error: ' + str(e))
            exception = e

    if not ret_list and exception:
        raise exception
    return ret_list


def open_session(device_id: str, passphrase_encoding: Optional[str] = 'NFC') -> Optional[MyKeepkeyClient]:
    for transport_cls, d, serial_number in enumerate_devices(device_id):
        transport = transport_cls(d)
        client = MyKeepkeyClient(transport, ask_for_pin_callback, ask_for_pass_callback, passphrase_encoding)
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
    return None


def close_session(client: MyKeepkeyClient):
    client.close()


class MyTxApiInsight(TxApiInsight):

    def __init__(self, network, url, dashd_inf, cache_dir, zcash=None):
        TxApiInsight.__init__(self, network, url, zcash)
        self.dashd_inf = dashd_inf
        self.cache_dir = cache_dir
        self.skip_cache = False

    def fetch_json(self, url, resource, resourceid):
        if resource == 'tx':
            try:
                j = self.dashd_inf.getrawtransaction(resourceid, 1, skip_cache=self.skip_cache)
                return j
            except Exception:
                raise
        else:
            raise Exception('Invalid operation type: ' + resource)

    def get_tx(self, txhash):
        data = self.fetch_json(self.url, 'tx', txhash)

        t = proto_types.TransactionType()
        t.version = data['version']
        t.lock_time = data['locktime']

        for vin in data['vin']:
            i = t.inputs.add()
            if 'coinbase' in vin.keys():
                i.prev_hash = b"\0" * 32
                i.prev_index = 0xffffffff  # signed int -1
                i.script_sig = binascii.unhexlify(vin['coinbase'])
                i.sequence = vin['sequence']

            else:
                i.prev_hash = binascii.unhexlify(vin['txid'])
                i.prev_index = vin['vout']
                i.script_sig = binascii.unhexlify(vin['scriptSig']['hex'])
                i.sequence = vin['sequence']

        for vout in data['vout']:
            o = t.bin_outputs.add()
            o.amount = int(Decimal(str(vout['value'])) * 100000000)
            o.script_pubkey = binascii.unhexlify(vout['scriptPubKey']['hex'])

        dip2_type = data.get("type", 0)

        if t.version == 3 and dip2_type != 0:
            # It's a DIP2 special TX with payload
            if dip2_type == DashTxType.SPEC_CB_TX:
                data["extraPayload"] = serialize_cbTx(data)
            elif dip2_type == DashTxType.LELANTUS_JSPLIT:
                data["extraPayload"] = serialize_Lelantus(data)
            elif dip2_type == DashTxType.SPARK_SPEND:
                data["extraPayload"] = serialize_Spark(data)
            else:
                raise NotImplementedError("Only spending of V3 coinbase outputs has been inplemented. "
                    "Please file an issue at https://github.com/firoorg/firo-masternode-tool/issues containing "
                    "the tx type=" + str(dip2_type))
            data["extraPayloadSize"] = len(data["extraPayload"]) >> 1

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

        # KeepKey firmware doesn't understand the split of version and type, so let's mimic the
        # old serialization format
        t.version |= dip2_type << 16

        return t


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

    insight_network = 'insight_dash'
    if rt_data.is_testnet:
        insight_network += '_testnet'
    dash_network = rt_data.dash_network

    tx_api = MyTxApiInsight(insight_network, '', rt_data.dashd_intf, rt_data.tx_cache_dir)
    client = hw_session.hw_client
    client.set_tx_api(tx_api)
    inputs = []
    outputs = []
    inputs_amount = 0
    for utxo_index, utxo in enumerate(utxos_to_spend):
        if not utxo.bip32_path:
            raise Exception('No BIP32 path for UTXO ' + utxo.txid)
        address_n = client.expand_path(clean_bip32_path(utxo.bip32_path))
        it = proto_types.TxInputType(address_n=address_n, prev_hash=binascii.unhexlify(utxo.txid),
                                     prev_index=utxo.output_index)
        inputs.append(it)
        inputs_amount += utxo.satoshis

    outputs_amount = 0
    for out in tx_outputs:
        outputs_amount += out.satoshis
        if out.address[0] in dash_utils.get_chain_params(dash_network).B58_PREFIXES_SCRIPT_ADDRESS:
            stype = proto_types.PAYTOSCRIPTHASH
            logging.debug('Transaction type: PAYTOSCRIPTHASH' + str(stype))
        elif out.address[0] in dash_utils.get_chain_params(dash_network).B58_PREFIXES_PUBKEY_ADDRESS:
            stype = proto_types.PAYTOADDRESS
            logging.debug('Transaction type: PAYTOADDRESS ' + str(stype))
        else:
            raise Exception('Invalid prefix of the destination address.')
        if out.bip32_path:
            address_n = client.expand_path(out.bip32_path)
        else:
            address_n = None

        ot = proto_types.TxOutputType(
            address=out.address if address_n is None else None,
            address_n=address_n,
            amount=out.satoshis,
            script_type=stype
        )
        outputs.append(ot)

    if outputs_amount + tx_fee != inputs_amount:
        raise Exception('Transaction validation failure: inputs + fee != outputs')

    signed = client.sign_tx(rt_data.hw_coin_name, inputs, outputs)
    logging.info('Signed transaction')
    return signed[1], inputs_amount


def sign_message(hw_client, hw_coin_name: str, bip32path: str, message: str):
    address_n = hw_client.expand_path(clean_bip32_path(bip32path))
    try:
        return hw_client.sign_message(hw_coin_name, address_n, message)
    except CallException as e:
        if e.args and len(e.args) >= 2 and e.args[1].lower().find('cancelled') >= 0:
            raise CancelException('Cancelled')
        else:
            raise


def ping(hw_client, message: str):
    hw_client.ping(message, True)


def change_pin(hw_client, remove=False):
    if hw_client:
        hw_client.change_pin(remove)
    else:
        raise Exception('HW client not set.')


def enable_passphrase(hw_client, passphrase_enabled):
    if hw_client:
        hw_client.apply_settings(use_passphrase=passphrase_enabled)
    else:
        raise Exception('HW client not set.')


def set_label(hw_client, label: str):
    if hw_client:
        hw_client.apply_settings(label=label)
    else:
        raise Exception('HW client not set.')


def wipe_device(hw_device_id: str, hw_client: Any, passphrase_encoding: Optional[str] = 'NFC') -> str:
    """
    :return: new device id
    """
    client = None
    try:
        if not hw_client:
            client = open_session(device_id=hw_device_id, passphrase_encoding=passphrase_encoding)
        else:
            client = hw_client

        if client:
            client.wipe_device()
            hw_device_id = client.features.device_id
            return hw_device_id
        else:
            raise Exception('Couldn\'t connect to Keepkey device.')

    except CallException as e:
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            raise
        else:
            raise CancelException
    finally:
        if client and hw_client != client:
            client.close()


def recover_device(hw_device_id: str, hw_client: Any, word_count: int, passphrase_enabled: bool, pin_enabled: bool,
                   hw_label: str, passphrase_encoding: Optional[str] = 'NFC', parent_window: Optional[QWidget] = None) \
        -> Optional[str]:
    """
    Restore a seed using the device screen.
    :return: A new device Id - depending on firmware, a new device id may be generated when wiping.
    """
    client = None
    try:
        if not hw_client:
            client = open_session(device_id=hw_device_id, passphrase_encoding=passphrase_encoding)
        else:
            client = hw_client

        if client:
            if client.features.initialized:
                client.wipe_device()
                hw_device_id = client.features.device_id

            client.parent_dialog = parent_window
            client.recovery_device(use_trezor_method=False, word_count=word_count,
                                   passphrase_protection=passphrase_enabled, pin_protection=pin_enabled,
                                   label=hw_label, language='english')
            client.close()
            return hw_device_id
        else:
            raise Exception('Couldn\'t connect to Keepkey device.')

    except CallException as e:
        if len(e.args) >= 1 and (e.args[1] == 'Action cancelled by user' or e.args[1] == 'Aborted'):
            raise CancelException
        else:
            raise
    finally:
        client.hide_request_character_dialog()
        client.parent_dialog = None
        if client and hw_client != client:
            client.close()


def initialize_device(hw_device_id: str, hw_client: Any, strength: int, passphrase_enabled: bool,
                      pin_enabled: bool, hw_label: str, passphrase_encoding: Optional[str] = 'NFC') -> Optional[str]:
    """
    :return: A new device Id - depending on firmware, a new device id may be generated when wiping.
    """
    client = None
    try:
        if not hw_client:
            client = open_session(device_id=hw_device_id, passphrase_encoding=passphrase_encoding)
        else:
            client = hw_client

        if client:
            if client.features.initialized:
                client.wipe_device()
                hw_device_id = client.features.device_id

            client.reset_device(display_random=True, strength=strength, passphrase_protection=passphrase_enabled,
                                pin_protection=pin_enabled, label=hw_label, language='english')
            return hw_device_id
        else:
            raise Exception('Couldn\'t connect to Keepkey device.')

    except CallException as e:
        if not (len(e.args) >= 0 and str(e.args[1]) == 'Action cancelled by user'):
            raise
        else:
            raise CancelException
    finally:
        if client and hw_client != client:
            client.close()

