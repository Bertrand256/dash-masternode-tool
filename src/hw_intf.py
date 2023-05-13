#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
from __future__ import annotations
import functools
import hashlib
import re
import urllib, urllib.request, urllib.parse
from functools import partial
from io import BytesIO
from typing import Optional, Tuple, List, ByteString, Dict, cast, Any, Literal
import sys

import simplejson
import trezorlib
import trezorlib.btc
import trezorlib.exceptions
import trezorlib.misc
import keepkeylib.client
import usb1
from PyQt5.QtCore import pyqtSlot, QObject
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QDialog, QWidget
from trezorlib.tools import Address

import app_defs
import dash_utils
from app_runtime_data import AppRuntimeData
from dash_utils import bip32_path_n_to_string
from hw_common import HWType, HWDevice, HWPinException, get_hw_type_from_client, HWNotConnectedException, \
    DEFAULT_HW_BUSY_TITLE, DEFAULT_HW_BUSY_MESSAGE, HWSessionBase, HWFirmwareWebLocation, HWModel
import logging

from method_call_tracker import MethodCallTracker
from thread_fun_dlg import CtrlObject
from wallet_common import UtxoType, TxOutputType
from wnd_utils import WndUtils
import hw_intf_ledgernano as ledger
import hw_intf_keepkey as keepkey
import hw_intf_trezor as trezor
from app_defs import get_note_url
from app_utils import SHA256, url_path_join
from common import CancelException, InternalError
from thread_utils import EnhRLock

# Dict[str <hd tree ident>, Dict[str <bip32 path>, Tuple[str <address>, int <db id>]]]
bip32_address_map: Dict[str, Dict[str, Tuple[str, int]]] = {}

hd_tree_db_map: Dict[str, int] = {}  # Dict[str <hd tree ident>, int <db id>]

log = logging.getLogger('dmt.hw_intf')


def control_hw_call(func):
    """
    Decorator for some of the hardware wallet functions. It ensures, that hw client connection is open (and if is not, 
    it makes attempt to open it). The s econt thing is to catch OSError exception as a result of disconnecting 
    hw cable. After this, connection has to be closed and opened again, otherwise 'read error' occurs.
    :param func: function decorated. First argument of the function has to be the reference to the MainWindow object.
    """

    def catch_hw_client(*args, **kwargs):
        hw_session: HwSessionInfo = args[0]
        client = hw_session.hw_client
        if not client:
            client = hw_session.connect_hardware_wallet()
        if not client:
            raise HWNotConnectedException()
        try:
            try:
                # protect against simultaneous access to the same device from different threads
                hw_session.acquire_client()

                if hw_session.hw_type == HWType.trezor:

                    try:
                        ret = func(*args, **kwargs)
                    except trezorlib.exceptions.PinException as e:
                        raise HWPinException(e.args[1])

                elif hw_session.hw_type == HWType.keepkey:

                    try:
                        ret = func(*args, **kwargs)
                    except keepkeylib.client.PinException as e:
                        raise HWPinException(e.args[1])

                elif hw_session.hw_type == HWType.ledger_nano:

                    ret = func(*args, **kwargs)

                else:
                    raise Exception('Unknown hardware wallet type: ' + str(hw_session.hw_type))
            finally:
                hw_session.release_client()

        except (OSError, usb1.USBErrorNoDevice) as e:
            logging.exception('Exception calling %s function' % func.__name__)
            logging.info('Disconnecting HW after OSError occurred')
            hw_session.hw_disconnect()
            raise HWNotConnectedException('The hardware wallet device has been disconnected with the '
                                          'following error: ' + str(e))

        except HWPinException:
            raise

        except CancelException:
            raise

        except Exception:
            logging.exception('Exception calling %s function' % func.__name__)
            raise

        return ret

    return catch_hw_client


def get_hw_device_state_str(hw_device: HWDevice):
    """Returns a string that comprises of all the information that relates to a hw device state. Used mainly to
    estimate whether the UI should refresh the information about a given device."""
    dev_state_str = ''
    if hw_device:
        dev_state_str = hw_device.device_id + '|' + ('B' if hw_device.bootloader_mode else 'NB') + '|' + \
                   ('I' if hw_device.initialized else 'NI') + '|' + ('L' if hw_device.locked else 'U') + '|' + \
                   str(hw_device.device_label)
    return dev_state_str


def get_device_list(hw_types: Tuple[HWType, ...], allow_bootloader_mode: bool = False,
                    use_webusb=True, use_bridge=True, use_udp=True, use_hid=True, passphrase_encoding='NFC') \
        -> List[HWDevice]:
    dev_list = []

    if HWType.trezor in hw_types:
        try:
            devs = trezor.get_device_list(allow_bootloader_mode=allow_bootloader_mode,
                                          use_webusb=use_webusb, use_bridge=use_bridge, use_udp=use_udp, use_hid=use_hid)
            dev_list.extend(devs)
        except Exception as e:
            log.exception('Exception while connecting Trezor device: ' + str(e))

    if HWType.keepkey in hw_types:
        try:
            devs = keepkey.get_device_list(passphrase_encoding, allow_bootloader_mode=allow_bootloader_mode)
            dev_list.extend(devs)
        except Exception as e:
            log.exception('Exception while connecting Keepkey device: ' + str(e))

    if HWType.ledger_nano in hw_types:
        try:
            devs = ledger.get_device_list(allow_bootloader_mode=allow_bootloader_mode)
            dev_list.extend(devs)
        except Exception as e:
            log.exception('Exception while connecting Ledger Nano device: ' + str(e))

    return dev_list


def cancel_hw_thread_dialog(hw_client):
    try:
        hw_type = get_hw_type_from_client(hw_client)
        if hw_type == HWType.trezor:
            hw_client.cancel()
        elif hw_type == HWType.keepkey:
            hw_client.cancel()
        elif hw_type == HWType.ledger_nano:
            return False
        raise CancelException('Cancel')
    except CancelException:
        raise
    except Exception as e:
        logging.exception('Error when canceling hw session. Details: %s', str(e))
        return True


def cancel_hw_operation(hw_client):
    try:
        hw_type = get_hw_type_from_client(hw_client)
        if hw_type in (HWType.trezor, HWType.keepkey):
            hw_client.cancel()
    except Exception as e:
        logging.error('Error when cancelling hw operation: %s', str(e))


def get_hw_label(hw_client):
    hw_type = get_hw_type_from_client(hw_client)
    if hw_type in (HWType.trezor, HWType.keepkey):
        return hw_client.features.label
    elif hw_type == HWType.ledger_nano:
        return 'Ledger Nano S'


def firmware_update(hw_client, raw_data: bytes):
    hw_type = get_hw_type_from_client(hw_client)
    if hw_type == HWType.trezor:
        trezor.firmware_update(hw_client, raw_data)
    elif HWType.keepkey:
        hw_client.firmware_update(fp=BytesIO(raw_data))
    elif hw_type == HWType.ledger_nano:
        raise Exception('Ledger Nano S is not supported.')


def action_on_device_message(message=DEFAULT_HW_BUSY_MESSAGE, title=DEFAULT_HW_BUSY_TITLE, is_method_call: bool = False):
    def decorator_f(func):
        def wrapped_f(*args, **kwargs):
            hw_client = None
            hw_client_names = ('MyTrezorClient', 'KeepkeyClient')

            # look for hw client:
            for arg in args:
                name = type(arg).__name__
                if name in hw_client_names:
                    hw_client = arg
                    break
                elif name == 'HWDevice':
                    hw_client = arg.hw_client
                    break

            if not hw_client:
                for arg_name in kwargs:
                    name = type(kwargs[arg_name]).__name__
                    if name in hw_client_names:
                        hw_client = kwargs[arg_name]
                        break
                    elif name == 'HWDevice':
                        hw_client = kwargs[arg_name].hw_client
                        break

            def thread_dialog(ctrl):
                if ctrl:
                    ctrl.dlg_config(dlg_title=title, show_progress_bar=False)
                    ctrl.display_msg(message)

                if is_method_call and len(args):
                    return func(*args[1:], **kwargs)  # if the call relates to a method call, skip passing the self
                                                      # attribute, which is the first one
                else:
                    return func(*args, **kwargs)

            return WndUtils.run_thread_dialog(thread_dialog, (), True, show_window_delay_ms=1000,
                                              force_close_dlg_callback=partial(cancel_hw_thread_dialog, hw_client))

        return wrapped_f

    return decorator_f


@action_on_device_message()
def ping_device(hw_device: HWDevice, message: str):
    def ledger_ping(ctrl):
        """The only way to make Ledger Nano to display a message is to use the message signing feature."""
        message = "Ping from DMT"
        message_hash = hashlib.sha256(message.encode('ascii')).hexdigest().upper()
        ctrl.dlg_config(dlg_title=message, show_progress_bar=False)
        display_label = '<b>This is a "ping" message from DMT</b> (we had to use the message signing feature).<br>' \
                        '<b>Message: </b>' + message + '<br>' \
                                                       '<b>SHA256 hash:</b> ' + message_hash + '<br>' \
                                                                                               '<br>Click "Sign" on the device to close this dialog.</b>'
        ctrl.display_msg(display_label)
        try:
            ledger.sign_message(hw_device.hw_client, dash_utils.get_default_bip32_path('MAINNET'), message, None)
        except CancelException:
            pass

    if hw_device.hw_type == HWType.trezor:
        trezor.ping(hw_device.hw_client, message)
    elif hw_device.hw_type == HWType.keepkey:
        keepkey.ping(hw_device.hw_client, message)
    elif hw_device.hw_type == HWType.ledger_nano:
        WndUtils.run_thread_dialog(ledger_ping, (), True, force_close_dlg_callback=partial(cancel_hw_thread_dialog,
                                                                                           hw_device.hw_client))
    else:
        logging.error('Invalid HW type: ' + str(hw_device.hw_type))


@action_on_device_message()
def change_pin(hw_device: HWDevice, remove=False):
    if hw_device and hw_device.hw_client:
        if hw_device.hw_type == HWType.trezor:
            return trezor.change_pin(hw_device.hw_client, remove)
        elif hw_device.hw_type == HWType.keepkey:
            return keepkey.change_pin(hw_device.hw_client, remove)
        elif hw_device.hw_type == HWType.ledger_nano:
            raise Exception('Ledger Nano S is not supported.')
        else:
            logging.error('Invalid HW type: ' + str(hw_device.hw_type))


@action_on_device_message()
def set_passphrase_option(hw_device: HWDevice, enabled: bool):
    if hw_device.hw_type == HWType.trezor:
        trezor.enable_passphrase(hw_device.hw_client, enabled)
    elif hw_device.hw_type == HWType.keepkey:
        keepkey.enable_passphrase(hw_device.hw_client, enabled)
    elif hw_device.hw_type == HWType.ledger_nano:
        raise Exception('Ledger Nano is not supported.')
    else:
        logging.error('Invalid HW type: ' + str(hw_device.hw_type))


@action_on_device_message()
def set_label(hw_device: HWDevice, label: str):
    if hw_device and hw_device.hw_client:
        if hw_device.hw_type == HWType.trezor:
            return trezor.set_label(hw_device.hw_client, label)
        elif hw_device.hw_type == HWType.keepkey:
            return keepkey.set_label(hw_device.hw_client, label)
        elif hw_device.hw_type == HWType.ledger_nano:
            raise Exception('Ledger Nano S is not supported.')
        else:
            logging.error('Invalid HW type: ' + str(hw_device.hw_type))


@action_on_device_message()
def set_passphrase_always_on_device(hw_device: HWDevice, enabled: bool):
    if hw_device.hw_type == HWType.trezor:
        trezor.set_passphrase_always_on_device(hw_device.hw_client, enabled)
    elif hw_device.hw_type == HWType.keepkey:
        raise Exception('Keepkey is not not supported.')
    elif hw_device.hw_type == HWType.ledger_nano:
        raise Exception('Ledger Nano S is not supported.')
    else:
        logging.error('Invalid HW type: ' + str(hw_device.hw_type))


@action_on_device_message()
def set_wipe_code(hw_device: HWDevice, remove: bool):
    if hw_device.hw_type == HWType.trezor:
        trezor.set_wipe_code(hw_device.hw_client, remove)
    elif hw_device.hw_type == HWType.keepkey:
        raise Exception('Keepkey is not supported.')
    elif hw_device.hw_type == HWType.ledger_nano:
        raise Exception('Ledger Nano S is not supported.')
    else:
        logging.error('Invalid HW type: ' + str(hw_device.hw_type))


@action_on_device_message()
def set_sd_protect(hw_device: HWDevice, operation: Literal["enable", "disable", "refresh"]):
    if hw_device.hw_type == HWType.trezor:
        trezor.sd_protect(hw_device.hw_client, operation)
    elif hw_device.hw_type == HWType.keepkey:
        raise Exception('Keepkey is not supported.')
    elif hw_device.hw_type == HWType.ledger_nano:
        raise Exception('Ledger Nano S is not supported.')
    else:
        logging.error('Invalid HW type: ' + str(hw_device.hw_type))


def hw_connection_tracker(func):
    """
    The purpose of this decorator function is to track:
      a) whether the connection state to the hardware wallet has changed
      b) whether selected hw device has changed
    within the HWDevices object, and if so, to emit appropriate Qt signals. We are using MethodCallTracker here
    to emit signals only once, even if the connection/selection status changes several times within the call chain.
    Note, that the connected hardware wallet device is not the same as the selected one, as the HWDevices class has
    the ability of selecting devices without the need of connecting to it.
    """

    @functools.wraps(func)
    def wrapper(self: HWDevices, *args, **kwargs):
        def get_hw_client_state_str():
            hw_device = self.get_selected_device()
            if hw_device and hw_device.hw_client:
                return get_hw_device_state_str(hw_device)
            else:
                return ''

        call_count = MethodCallTracker.get_call_depth_by_class(self)
        hw_client_hash_old = ''
        hw_dev_hash_old = ''
        if call_count == 0:
            hw_client_hash_old = get_hw_client_state_str()
            hw_dev_hash_old = get_hw_device_state_str(self.get_selected_device())

        ret = None
        with MethodCallTracker(self, func):
            ret = func(self, *args, **kwargs)

        if call_count == 0:
            hw_hash_new = get_hw_client_state_str()
            hw_dev_hash_new = get_hw_device_state_str(self.get_selected_device())

            if hw_client_hash_old != hw_hash_new:
                self.sig_connected_hw_device_changed.emit(self.get_selected_device())

            if hw_dev_hash_old != hw_dev_hash_new:
                self.sig_selected_hw_device_changed.emit(self.get_selected_device())

        return ret

    return wrapper


# noinspection PyTypeChecker
class HWDevices(QObject):
    """
    Manages information about all hardware wallet devices connected to the computer.
    """
    sig_selected_hw_device_changed = QtCore.pyqtSignal(object)
    sig_connected_hw_device_changed = QtCore.pyqtSignal(object)

    __instance = None

    class HWDevicesState:
        def __init__(self, connected_dev_ids: List[str], selected_device_id: Optional[str],
                     selected_device_model: Optional[str],
                     selected_device_bootloader_mode: Optional[bool],
                     allow_bootloader_mode: bool, hw_types_allowed: Tuple[HWType, ...]):
            self.connected_device_ids: List[str] = connected_dev_ids
            self.device_id_selected: Optional[str] = selected_device_id
            self.selected_device_model = selected_device_model
            self.selected_device_bootloader_mode = selected_device_bootloader_mode
            self.allow_bootloader_mode: bool = allow_bootloader_mode
            self.hw_types_allowed: Tuple[HWType, ...] = hw_types_allowed

    @staticmethod
    def get_instance() -> 'HWDevices':
        return HWDevices.__instance

    def __init__(self, use_webusb=True, use_bridge=True, use_udp=True, use_hid=True, passphrase_encoding='NFC'):
        super(HWDevices, self).__init__()
        if HWDevices.__instance is not None:
            raise Exception('Internal error: cannot create another instance of this class')
        HWDevices.__instance = self
        self.__hw_devices: List[HWDevice] = []
        self.__hw_device_id_selected: Optional[str] = None  # device id of the hw client selected
        self.__selected_device_bootloader_mode: Optional[bool] = None
        self.__selected_device_model: Optional[str] = None
        self.__devices_fetched = False
        self.__use_webusb = use_webusb
        self.__use_bridge = use_bridge
        self.__use_udp = use_udp
        self.__use_hid = use_hid
        self.__hw_types_allowed: Tuple[HWType, ...] = (HWType.trezor, HWType.keepkey, HWType.ledger_nano)
        self.__passphrase_encoding: Optional[str] = passphrase_encoding
        self.__saved_states: List[HWDevices.HWDevicesState] = []
        self.__allow_bootloader_mode: bool = False

    def set_allow_bootloader_mode(self, allow: bool):
        self.__allow_bootloader_mode = allow

    def save_state(self):
        connected_devices = []
        for dev in self.__hw_devices:
            if dev.hw_client:
                connected_devices.append(dev.device_id)
        self.__saved_states.append(HWDevices.HWDevicesState(
            connected_devices, self.__hw_device_id_selected, self.__selected_device_model,
            self.__selected_device_bootloader_mode, self.__allow_bootloader_mode, self.__hw_types_allowed))

    @hw_connection_tracker
    def restore_state(self):
        if self.__saved_states:
            state = self.__saved_states.pop()
            self.__allow_bootloader_mode = state.allow_bootloader_mode
            self.__hw_types_allowed = state.hw_types_allowed

            # reconnect all the devices that were connected during the call of 'save_state'
            for dev_id in state.connected_device_ids:
                dev = self.get_device_by_id(dev_id)
                if dev and not dev.hw_client:
                    try:
                        self.open_hw_session(dev)
                    except Exception as e:
                        log.error(f'Cannot reconnect device {dev.device_id} due to the following error: ' + str(e))

            # disconnect all the currently connected devices where weren't connected
            # during save_state
            for dev in self.__hw_devices:
                if dev.hw_client and dev.device_id not in state.connected_device_ids:
                    try:
                        self.close_hw_session(dev)
                    except Exception as e:
                        log.error(f'Cannot disconnect device {dev.device_id} due to the following error: ' + str(e))

            # restore the currently selected device
            if state.device_id_selected and (self.__hw_device_id_selected != state.device_id_selected or
                                             self.__selected_device_model != state.selected_device_model or
                                             self.__selected_device_bootloader_mode != state.selected_device_bootloader_mode):
                dev = self.get_device_by_id(state.device_id_selected)
                if dev:
                    self.set_current_device(dev)
        else:
            raise InternalError('There are no saved states')

    @hw_connection_tracker
    def load_hw_devices(self, force_fetch: bool = False) -> bool:
        """
        Load all instances of the selected hardware wallet type. If there is more than one, user has to select which
        one he is going to use.
        :return True is anything has changed about the state of the connected hw devices during the process.
        """
        state_changed = False

        if force_fetch or not self.__devices_fetched:
            # save the current state to see if anything has changed during the process
            prev_dev_list = [get_hw_device_state_str(d) for d in self.__hw_devices]
            prev_dev_list.sort()

            if force_fetch:
                self.save_state()
                restore_state = True
            else:
                restore_state = False

            self.clear_devices()
            self.__hw_devices = get_device_list(
                hw_types=self.__hw_types_allowed, use_webusb=self.__use_webusb,
                use_bridge=self.__use_bridge, use_udp=self.__use_udp, use_hid=self.__use_hid,
                passphrase_encoding=self.__passphrase_encoding,
                allow_bootloader_mode=self.__allow_bootloader_mode
            )

            self.__devices_fetched = True
            if self.__hw_device_id_selected:
                if self.get_selected_device_index() is None:
                    self.__hw_device_id_selected = None
                    self.__selected_device_model = None
                    self.__selected_device_bootloader_mode = None

            if restore_state:
                try:
                    self.restore_state()
                except Exception as e:
                    log.error('Error while restoring hw devices state: ' + str(e))

            cur_dev_list = [get_hw_device_state_str(d) for d in self.__hw_devices]
            cur_dev_list.sort()

            state_changed = (','.join(prev_dev_list) != ','.join(cur_dev_list))
        return state_changed

    @hw_connection_tracker
    def close_all_hw_clients(self):
        try:
            for idx, hw_inst in enumerate(self.__hw_devices):
                if hw_inst.hw_client:
                    self.close_hw_session(hw_inst)
        except Exception as e:
            logging.exception(str(e))

    @hw_connection_tracker
    def clear_devices(self):
        self.close_all_hw_clients()
        self.__hw_devices.clear()

    @hw_connection_tracker
    def clear(self):
        self.clear_devices()
        self.__hw_device_id_selected = None
        self.__selected_device_model = None
        self.__selected_device_bootloader_mode = None

    def set_hw_types_allowed(self, allowed: Tuple[HWType, ...]):
        self.__hw_types_allowed = allowed[:]

    def get_selected_device_index(self) -> int:
        return next((i for i, device in enumerate(self.__hw_devices)
                     if device.device_id == self.__hw_device_id_selected), -1)

    def get_devices(self) -> List[HWDevice]:
        return self.__hw_devices

    def get_selected_device(self) -> Optional[HWDevice]:
        idx = self.get_selected_device_index()
        if idx >= 0:
            return self.__hw_devices[idx]
        else:
            return None

    def get_device_by_id(self, device_id: str) -> Optional[HWDevice]:
        for dev in self.__hw_devices:
            if dev.device_id == device_id:
                return dev
        return None

    @hw_connection_tracker
    def set_current_device(self, device: HWDevice):
        if device in self.__hw_devices:
            if device.device_id != self.__hw_device_id_selected or device.model_symbol != self.__selected_device_model \
                    or device.bootloader_mode != self.__selected_device_bootloader_mode:
                self.__hw_device_id_selected = device.device_id
                self.__selected_device_model = device.model_symbol
                self.__selected_device_bootloader_mode = device.bootloader_mode
        else:
            raise Exception('Non existent hw device object.')

    @hw_connection_tracker
    def set_current_device_by_index(self, index: int):
        if 0 <= index < len(self.__hw_devices):
            self.set_current_device(self.__hw_devices[index])
        else:
            raise Exception('Device index out of bounds.')

    @hw_connection_tracker
    def open_hw_session(self, hw_device: HWDevice, force_reconnect: bool = False):
        if hw_device.hw_client and force_reconnect:
            self.close_hw_session(hw_device)
            reconnected = True
        else:
            reconnected = False

        if not hw_device.hw_client:
            if hw_device.hw_type == HWType.trezor:
                hw_device.hw_client = trezor.open_session(hw_device.device_id, hw_device.transport_id)
                if hw_device.hw_client and hw_device.hw_client.features:
                    hw_device.bootloader_mode = hw_device.hw_client.features.bootloader_mode
                else:
                    hw_device.bootloader_mode = False
                if reconnected and hw_device.hw_client:
                    trezor.apply_device_attributes(hw_device, hw_device.hw_client)
            elif hw_device.hw_type == HWType.keepkey:
                hw_device.hw_client = keepkey.open_session(hw_device.device_id, self.__passphrase_encoding)
                if hw_device.hw_client and hw_device.hw_client.features:
                    hw_device.bootloader_mode = hw_device.hw_client.features.bootloader_mode
                else:
                    hw_device.bootloader_mode = False
                if reconnected:
                    keepkey.apply_device_attributes(hw_device, hw_device.hw_client)
            elif hw_device.hw_type == HWType.ledger_nano:
                hw_device.hw_client = ledger.open_session(cast(ledger.HIDDongleHIDAPI, hw_device.transport_id))
            else:
                raise Exception('Invalid HW type: ' + str(hw_device.hw_type))

    @hw_connection_tracker
    def close_hw_session(self, hw_device: HWDevice):
        if hw_device.hw_client:
            try:
                if hw_device.hw_type == HWType.trezor:
                    trezor.close_session(hw_device.hw_client)
                elif hw_device.hw_type == HWType.keepkey:
                    keepkey.close_session(hw_device.hw_client)
                elif hw_device.hw_type == HWType.ledger_nano:
                    ledger.close_session(cast(ledger.HIDDongleHIDAPI, hw_device.transport_id))

                del hw_device.hw_client
                hw_device.hw_client = None
            except Exception:
                # probably already disconnected
                logging.exception('Disconnect HW error')

    @hw_connection_tracker
    def select_device(self, parent_dialog, open_client_session: bool = False) -> Optional[HWDevice]:
        self.load_hw_devices()

        dlg = SelectHWDeviceDlg(parent_dialog, "Select hardware wallet device", self)
        if dlg.exec_():
            self.set_current_device(dlg.selected_hw_device)
            if dlg.selected_hw_device and open_client_session:
                self.open_hw_session(dlg.selected_hw_device)
            return dlg.selected_hw_device
        return None

    def ping_device(self, hw_device: HWDevice):
        opened_session_here = False
        try:
            if not hw_device.hw_client:
                self.open_hw_session(hw_device)
                opened_session_here = True
            ping_device(hw_device, 'Hello from DMT')
        except Exception as e:
            raise
        finally:
            if opened_session_here:
                self.close_hw_session(hw_device)

    @hw_connection_tracker
    def initialize_device(self, hw_device: HWDevice, word_count: int, passphrase_enabled: bool, pin_enabled: bool,
                          hw_label: str, parent_window=None) -> Optional[str]:
        """
        Initialize device with a newly generated words.
        :return: Device id. If the device is wiped before initialization, a new device id is generated.
        """

        def load(ctrl) -> Optional[str]:
            ctrl.dlg_config(dlg_title="Please confirm", show_progress_bar=False)
            ctrl.display_msg('<b>Read the messages displayed on your hardware wallet <br>'
                             'and click the confirmation button when necessary...</b>')
            if hw_device.device_id or hw_device.hw_client:
                if hw_device.hw_type == HWType.trezor:
                    return trezor.initialize_device(hw_device.device_id, hw_device.transport_id, hw_device.hw_client,
                                                    strength, passphrase_enabled, pin_enabled, hw_label)
                elif hw_device.hw_type == HWType.keepkey:
                    return keepkey.initialize_device(hw_device.device_id, hw_device.hw_client, strength,
                                                     passphrase_enabled, pin_enabled, hw_label,
                                                     self.__passphrase_encoding)
                else:
                    raise Exception('Not supported by Ledger Nano S.')

        if hw_device.hw_type == HWType.ledger_nano:
            raise Exception('Not supported by Ledger Nano S.')
        else:
            if word_count not in (12, 18, 24):
                raise Exception('Invalid word count.')
            strength = {24: 32, 18: 24, 12: 16}.get(word_count) * 8

            new_hw_device_id = WndUtils.run_thread_dialog(load, (), True, center_by_window=parent_window)

            # during the initialization device_id (on Trezor) and some other values might have changed
            # so we need to reload them
            if new_hw_device_id != hw_device.device_id:
                if self.__hw_device_id_selected == hw_device.device_id:
                    self.__hw_device_id_selected = new_hw_device_id
                hw_device.device_id = new_hw_device_id

            if hw_device.hw_client is not None:
                try:
                    # reopen the client connection as some values read from it could have been changed
                    # during the initialization
                    self.open_hw_session(hw_device, force_reconnect=True)
                except Exception as e:
                    log.warning("Couldn't reconnect hardware wallet after initialization: " + str(e))

            return new_hw_device_id

    @hw_connection_tracker
    def recover_device(self, hw_device: HWDevice, word_count: int, passphrase_enabled: bool, pin_enabled: bool,
                       hw_label: str, input_type: Literal["scrambled_words", "matrix"],
                       parent_window=None) -> Optional[str]:
        """
        Recover hardware wallet using seed words and the device screen.
        :return: The device id. If the device is wiped before recovery, a new device id is generated.
        """

        def load(ctrl: CtrlObject) -> Optional[str]:

            ctrl.dlg_config(dlg_title="Please confirm", show_progress_bar=False)
            ctrl.display_msg('<b>Read the messages displayed on your hardware wallet <br>'
                             'and click the confirmation button when necessary...</b>')

            if hw_device.device_id or hw_device.hw_client:
                if hw_device.hw_type == HWType.trezor:
                    return trezor.recover_device(hw_device.device_id, hw_device.transport_id, hw_device.hw_client,
                                                 word_count, passphrase_enabled, pin_enabled, hw_label, input_type,
                                                 ctrl.dialog)
                elif hw_device.hw_type == HWType.keepkey:
                    return keepkey.recover_device(hw_device.device_id, hw_device.hw_client, word_count,
                                                  passphrase_enabled, pin_enabled, hw_label, self.__passphrase_encoding,
                                                  ctrl.dialog)
            else:
                raise HWNotConnectedException()

        if hw_device.hw_type == HWType.ledger_nano:
            raise Exception('Not supported by Ledger Nano S.')
        else:
            new_hw_device_id = WndUtils.run_thread_dialog(load, (), True, center_by_window=parent_window)

            # during the recovery device_id (on Trezor) and some other values might have changed
            # so we need to reload them
            if new_hw_device_id != hw_device.device_id:
                if self.__hw_device_id_selected == hw_device.device_id:
                    self.__hw_device_id_selected = new_hw_device_id
                hw_device.device_id = new_hw_device_id

            if hw_device.hw_client is not None:
                try:
                    # reopen the client connection as some values read from it could have been changed
                    # during the initialization
                    self.open_hw_session(hw_device, force_reconnect=True)
                except Exception as e:
                    log.warning("Couldn't reconnect hardware wallet after recovery: " + str(e))

            return new_hw_device_id

    @hw_connection_tracker
    def recover_device_with_seed_input(self, hw_device: HWDevice, mnemonic_words: str, pin: str, passphrase: str,
                                       secondary_pin: str) -> Optional[str]:
        """
        Initializes hardware wallet with the mnemonic words provided by the user.
        """

        if hw_device.device_id or hw_device.hw_client:
            if hw_device.hw_type == HWType.ledger_nano:
                hw_device_id = ledger.recover_device_with_seed_input(
                    cast(ledger.HIDDongleHIDAPI, hw_device.transport_id), mnemonic_words, pin, passphrase,
                    secondary_pin)
                return hw_device_id
            else:
                raise Exception('Not available for Trezor/Keepkey')

    @hw_connection_tracker
    def wipe_device(self, hw_device: HWDevice, parent_window=None) -> str:
        """
        Wipes the hardware wallet device.
        """

        def wipe(ctrl):
            ctrl.dlg_config(dlg_title="Confirm wiping device.", show_progress_bar=False)
            ctrl.display_msg('<b>Read the messages displayed on your hardware wallet <br>'
                             'and click the confirmation button when necessary...</b>')

            if hw_device.device_id or hw_device.hw_client:
                if hw_device.hw_type == HWType.trezor:
                    return trezor.wipe_device(hw_device.device_id, hw_device.transport_id, hw_device.hw_client)
                elif hw_device.hw_type == HWType.keepkey:
                    return keepkey.wipe_device(hw_device.device_id, hw_device.hw_client, self.__passphrase_encoding)
                else:
                    raise Exception('Not supported by Ledger Nano.')

        new_hw_device_id = WndUtils.run_thread_dialog(wipe, (), True, center_by_window=parent_window)

        # during the wipe, device_id (on Trezor) and other values change, so here we need to reload them
        if new_hw_device_id != hw_device.device_id:
            if self.__hw_device_id_selected == hw_device.device_id:
                self.__hw_device_id_selected = new_hw_device_id
            hw_device.device_id = new_hw_device_id

        if hw_device.hw_client is not None:
            try:
                # reopen the client connection as some values read from it could have been changed
                # during the initialization
                self.open_hw_session(hw_device, force_reconnect=True)
            except Exception as e:
                log.warning("Couldn't reconnect hardware wallet after initialization: " + str(e))

        return new_hw_device_id

    @staticmethod
    def change_pin(hw_device: HWDevice, remove=False):
        if hw_device and hw_device.hw_client:
            change_pin(hw_device, remove)

    @staticmethod
    def set_passphrase_option(hw_device: HWDevice, enabled: bool):
        if hw_device and hw_device.hw_client:
            set_passphrase_option(hw_device, enabled)

    @staticmethod
    def set_passphrase_always_on_device(hw_device: HWDevice, enabled: bool):
        if hw_device and hw_device.hw_client:
            set_passphrase_always_on_device(hw_device, enabled)

    @staticmethod
    def set_wipe_code(hw_device: HWDevice, remove: bool):
        if hw_device and hw_device.hw_client:
            set_wipe_code(hw_device, remove)

    @staticmethod
    def set_sd_protect(hw_device: HWDevice, operation: Literal["enable", "disable", "refresh"]):
        if hw_device and hw_device.hw_client:
            set_sd_protect(hw_device, operation)

    @hw_connection_tracker
    def set_label(self, hw_device: HWDevice, label: str):
        if hw_device and hw_device.hw_client:
            set_label(hw_device, label)
            if hw_device.hw_type in (HWType.trezor, HWType.keepkey) and hw_device.hw_client:
                trezor.apply_device_attributes(hw_device, hw_device.hw_client)

    @staticmethod
    def hw_encrypt_value(hw_device: HWDevice, bip32_path_n: List[int], label: str,
                         value: bytes, ask_on_encrypt=True, ask_on_decrypt=True) -> Tuple[bytearray, bytearray]:
        """
        Encrypts value with hardware wallet.
        :return Tuple
          0: encrypted data
          1: public key
        """
        def encrypt(ctrl: CtrlObject):
            ctrl.dlg_config(dlg_title="Data encryption", show_progress_bar=False)
            ctrl.display_msg(f'<b>Encrypting \'{label}\'...</b>'
                             f'<br><br>Enter the hardware wallet PIN/passphrase (if needed) to encrypt data.<br><br>'
                             f'<b>Note:</b> encryption passphrase is independent from the wallet passphrase  <br>'
                             f'and can vary for each encrypted file.')

            if hw_device.hw_type == HWType.trezor:
                try:
                    data = trezorlib.misc.encrypt_keyvalue(hw_device.hw_client, cast(Address, bip32_path_n), label,
                                                           value, ask_on_encrypt, ask_on_decrypt)
                    pub_key = trezorlib.btc.get_public_node(hw_device.hw_client, bip32_path_n).node.public_key
                    return data, pub_key
                except (CancelException, trezorlib.exceptions.Cancelled):
                    raise CancelException()

            elif hw_device.hw_type == HWType.keepkey:
                data = hw_device.hw_client.encrypt_keyvalue(bip32_path_n, label, value, ask_on_encrypt, ask_on_decrypt)
                pub_key = hw_device.hw_client.get_public_node(bip32_path_n).node.public_key
                return data, pub_key

            elif hw_device.hw_type == HWType.ledger_nano:
                raise Exception('Feature not available for Ledger Nano S.')

            else:
                raise Exception('Invalid HW type: ' + HWType.get_desc(hw_device.hw_type))

        if len(value) != 32:
            raise ValueError("Invalid password length (<> 32).")

        return WndUtils.run_thread_dialog(
            encrypt, (), True, force_close_dlg_callback=partial(cancel_hw_thread_dialog, hw_device.hw_client),
            show_window_delay_ms=200)

    @staticmethod
    def hw_decrypt_value(hw_device: HWDevice, bip32_path_n: List[int], label: str,
                         value: bytes, ask_on_encrypt=True, ask_on_decrypt=True) -> Tuple[bytearray, bytearray]:
        """
        Encrypts value using hardware wallet.
        :return Tuple
          0: decrypted data
          1: public key
        """

        def decrypt(ctrl: CtrlObject):
            ctrl.dlg_config(dlg_title="Data decryption", show_progress_bar=False)
            ctrl.display_msg(f'<b>Decrypting \'{label}\'...</b><br><br>Enter the hardware wallet PIN/passphrase '
                             f'(if needed)<br> and click the confirmation button to decrypt data.')

            if hw_device.hw_type == HWType.trezor:
                try:
                    client = hw_device.hw_client
                    data = trezorlib.misc.decrypt_keyvalue(client, cast(Address, bip32_path_n), label, value,
                                                           ask_on_encrypt, ask_on_decrypt)
                    pub_key = trezorlib.btc.get_public_node(client, bip32_path_n).node.public_key
                    return data, pub_key
                except (CancelException, trezorlib.exceptions.Cancelled):
                    raise CancelException()

            elif hw_device.hw_type == HWType.keepkey:
                client = hw_device.hw_client
                data = client.decrypt_keyvalue(bip32_path_n, label, value, ask_on_encrypt, ask_on_decrypt)
                pub_key = client.get_public_node(bip32_path_n).node.public_key
                return data, pub_key

            elif hw_device.hw_type == HWType.ledger_nano:
                raise Exception('Feature not available for Ledger Nano S.')

            else:
                raise Exception('Invalid HW type: ' + HWType.get_desc(hw_device.hw_type))

        if len(value) != 32:
            raise ValueError("Invalid password length (<> 32).")

        return WndUtils.run_thread_dialog(
            decrypt, (), True, force_close_dlg_callback=partial(cancel_hw_thread_dialog, hw_device.hw_client))


# noinspection PyTypeChecker
class HwSessionInfo(HWSessionBase):
    sig_hw_connected = QtCore.pyqtSignal(HWDevice)
    sig_hw_disconnected = QtCore.pyqtSignal()
    sig_hw_connection_error = QtCore.pyqtSignal(str)

    def __init__(self, main_dlg, app_config: 'AppConfig', runtime_data: AppRuntimeData):
        super().__init__()

        self.__locks = {}  # key: hw_client, value: EnhRLock
        self.__main_dlg = main_dlg
        self.__runtime_data: AppRuntimeData = runtime_data
        self.__base_bip32_path: str = ''
        self.__base_public_key: bytes = b''
        self.__hd_tree_ident: str = ''
        self.__use_webusb = app_config.trezor_webusb
        self.__use_bridge = app_config.trezor_bridge
        self.__use_udp = app_config.trezor_udp
        self.__use_hid = app_config.trezor_hid
        self.__passphrase_encoding: Optional[str] = app_config.hw_keepkey_psw_encoding

        self.__hw_devices = HWDevices(use_webusb=self.__use_webusb, use_bridge=self.__use_bridge,
                                      use_udp=self.__use_udp, use_hid=self.__use_hid,
                                      passphrase_encoding=self.__passphrase_encoding)

    def signal_hw_connected(self):
        self.sig_hw_connected.emit(self.hw_device)

    def signal_hw_disconnected(self):
        self.sig_hw_disconnected.emit()

    def signal_hw_connection_error(self, message):
        self.sig_hw_connection_error.emit(message)

    @property
    def hw_device(self) -> Optional[HWDevice]:
        return self.__hw_devices.get_selected_device()

    def get_hw_client(self) -> Optional[object]:
        hw_device = self.hw_device
        if hw_device:
            return hw_device.hw_client
        return None

    @property
    def runtime_data(self) -> AppRuntimeData:
        return self.__runtime_data

    @property
    def hw_type(self) -> Optional[HWType]:
        if self.hw_device:
            return self.hw_device.hw_type
        else:
            return None

    @property
    def hw_model(self) -> Optional[HWModel]:
        if self.hw_device:
            return self.hw_device.get_hw_model()
        return None

    def acquire_client(self):
        cli = self.hw_client
        if cli:
            lock = self.__locks.get(cli)
            if not lock:
                lock = EnhRLock()
                self.__locks[cli] = lock
            lock.acquire()

    def release_client(self):
        cli = self.hw_client
        if cli:
            lock = self.__locks.get(cli)
            if not lock:
                raise Exception(f'Lock for client {str(cli)} not acquired before.')
            lock.release()

    def set_base_info(self, bip32_path: str, public_key: bytes):
        self.__base_bip32_path = bip32_path
        self.__base_public_key = public_key
        self.__hd_tree_ident = SHA256.new(public_key).digest().hex()

    @property
    def base_bip32_path(self):
        return self.__base_bip32_path

    @property
    def base_public_key(self):
        return self.__base_public_key

    def get_hd_tree_ident(self, coin_name: str):
        if not coin_name:
            raise Exception('Missing coin name')
        if not self.__hd_tree_ident:
            raise HWNotConnectedException()
        return self.__hd_tree_ident + bytes(coin_name, 'ascii').hex()

    def initiate_hw_session(self):
        """
        Read this information from the hw device that will cause it to ask the user for a BIP39 passphrase, if
        necessary. The point is to make sure that the device is fully initiated and ready for next calls.
        """

        def get_session_info_trezor(get_public_node_fun, hw_device_):
            def call_get_public_node(_, get_public_node_fun_, path_n_):
                pk = get_public_node_fun_(path_n_).node.public_key
                return pk

            path_ = dash_utils.get_default_bip32_base_path(self.__runtime_data.dash_network)
            path_n = dash_utils.bip32_path_string_to_n(path_)

            # show message for Trezor device while waiting for the user to choose the passphrase input method
            pub = WndUtils.run_thread_dialog(
                call_get_public_node, (get_public_node_fun, path_n),
                title=DEFAULT_HW_BUSY_TITLE, text=DEFAULT_HW_BUSY_MESSAGE,
                force_close_dlg_callback=partial(cancel_hw_thread_dialog, hw_device_.hw_client),
                show_window_delay_ms=1000)

            if pub:
                self.set_base_info(path_, pub)
            else:
                raise Exception('Couldn\'t read data from the hardware wallet.')

        def get_session_info_ledger(path: str, hw_device_):
            def call_get_public_node(_, path_):
                ap = ledger.get_address_and_pubkey(self, path_)
                return ap

            # show a message for Ledger device while waiting for the user to choose the passphrase input method
            ap = WndUtils.run_thread_dialog(
                call_get_public_node, (path,),
                title=DEFAULT_HW_BUSY_TITLE, text=DEFAULT_HW_BUSY_MESSAGE,
                force_close_dlg_callback=partial(cancel_hw_thread_dialog, hw_device_.hw_client),
                show_window_delay_ms=1000)

            if ap:
                self.set_base_info(path, ap['publicKey'])
            else:
                raise Exception('Couldn\'t read data from the hardware wallet.')

        hw_device = self.hw_device
        if not hw_device:
            raise Exception('Internal error: hw device not ready')
        self.__hw_devices.open_hw_session(hw_device)

        try:
            if hw_device.hw_type == HWType.trezor:
                try:
                    fun = partial(trezorlib.btc.get_public_node, hw_device.hw_client)
                    get_session_info_trezor(fun, hw_device)
                except trezorlib.exceptions.Cancelled:
                    raise CancelException()
                except trezorlib.exceptions.PinException as e:
                    raise HWPinException(e.args[1])

            elif hw_device.hw_type == HWType.keepkey:
                try:
                    get_session_info_trezor(hw_device.hw_client.get_public_node, hw_device)
                except keepkeylib.client.PinException as e:
                    raise HWPinException(e.args[1])

            elif hw_device.hw_type == HWType.ledger_nano:
                path = dash_utils.get_default_bip32_base_path(self.__runtime_data.dash_network)
                # ap = ledger.get_address_and_pubkey(self, path)
                # self.set_base_info(path, ap['publicKey'])
                get_session_info_ledger(path, hw_device)

        except CancelException:
            cancel_hw_operation(hw_device.hw_client)
            self.__hw_devices.close_hw_session(hw_device)
            raise
        except Exception:
            # in the case of error close the session
            self.__hw_devices.close_hw_session(hw_device)
            raise

    def connect_hardware_wallet_main_th(self, reload_devices: bool = False) -> Optional[object]:
        """
        Connects to hardware wallet device if not connected before. It must be called from the main thread.
        :return: Reference to hw client or None if not connected.
        """
        ret = None
        reload_devices_ = reload_devices
        if (not reload_devices_ and not self.__hw_devices.get_devices()) or not self.hw_client:
            # (re)load hardware wallet devices connected to the computer, if they haven't been loaded yet
            # or there is no session currently open to a hw device
            reload_devices_ = True

        self.__hw_devices.load_hw_devices(reload_devices_)

        if not self.hw_client:
            if len(self.__hw_devices.get_devices()) == 1:
                self.__hw_devices.set_current_device_by_index(0)
            elif len(self.__hw_devices.get_devices()) > 1:
                device = self.__hw_devices.select_device(self.__main_dlg)
                if not device:
                    raise CancelException('Cancelled')
            else:
                raise HWNotConnectedException("No hardware wallet device detected.")

            try:
                try:
                    self.initiate_hw_session()

                    if self.__runtime_data.dash_network == 'TESTNET':
                        # check if Dash testnet is supported by this hardware wallet
                        found_testnet_support = False
                        if self.hw_type in (HWType.trezor, HWType.keepkey):
                            try:
                                path = dash_utils.get_default_bip32_base_path(self.__runtime_data.dash_network)
                                path += "/0'/0/0"
                                path_n = dash_utils.bip32_path_string_to_n(path)
                                addr = get_address(self, path_n, False)
                                if addr and dash_utils.validate_address(addr, self.__runtime_data.dash_network):
                                    found_testnet_support = True
                            except Exception as e:
                                if str(e).find('Invalid coin name') < 0:
                                    raise

                        elif self.hw_type == HWType.ledger_nano:
                            addr = get_address(self, dash_utils.get_default_bip32_path(
                                self.__runtime_data.dash_network))
                            if dash_utils.validate_address(addr, self.__runtime_data.dash_network):
                                found_testnet_support = False

                        if not found_testnet_support:
                            url = get_note_url('DMT0002')
                            msg = f'Your hardware wallet device does not support Dash TESTNET ' \
                                  f'(<a href="{url}">see details</a>).'
                            try:
                                self.disconnect_hardware_wallet()
                            except Exception:
                                pass
                            self.signal_hw_connection_error(msg)
                            return
                    self.signal_hw_connected()

                except CancelException:
                    raise
                except Exception as e:
                    logging.exception('Exception while connecting hardware wallet')
                    try:
                        self.disconnect_hardware_wallet()
                    except Exception:
                        pass
                    self.signal_hw_connection_error(str(e))

                ret = self.hw_client
            except CancelException:
                raise
            except HWPinException as e:
                self.error_msg(e.msg)
                if self.hw_client:
                    self.hw_client.clear_session()
            except OSError:
                self.error_msg('Cannot open %s device.' % self.getHwName(), True)
            except Exception:
                if self.hw_client:
                    self.hw_client.init_device()
        else:
            ret = self.hw_client
        return ret

    def connect_hardware_wallet(self) -> Optional[object]:
        """
        Connects to hardware wallet device if not connected before.
        :return: Reference to hw client or None if not connected.
        """
        client = WndUtils.call_in_main_thread(self.connect_hardware_wallet_main_th)
        return client

    def disconnect_hardware_wallet(self) -> None:
        if self.hw_client:
            self.__hw_devices.close_hw_session(self.hw_device)
            self.signal_hw_disconnected()

    def save_state(self):
        self.__hw_devices.save_state()

    def restore_state(self):
        self.__hw_devices.restore_state()

    def set_hw_types_allowed(self, allowed: Tuple[HWType, ...]):
        self.__hw_devices.set_hw_types_allowed(allowed)

    def hw_encrypt_value(self, bip32_path_n: List[int], label: str,
                         value: bytes, ask_on_encrypt=True, ask_on_decrypt=True) -> Tuple[bytearray, bytearray]:
        if self.connect_hardware_wallet():
            hw_device = self.__hw_devices.get_selected_device()
            if hw_device:
                if hw_device.hw_type not in (HWType.trezor, HWType.keepkey):
                    raise Exception(HWType.get_desc(hw_device.hw_type) + ' device does not support data encryption.' )
                return self.__hw_devices.hw_encrypt_value(self.__hw_devices.get_selected_device(), bip32_path_n, label,
                                                          value, ask_on_encrypt, ask_on_decrypt)
            else:
                raise Exception('Hardware wallet not available')
        else:
            raise Exception('Hardware wallet not available')

    def hw_decrypt_value(self, bip32_path_n: List[int], label: str,
                         value: bytes, ask_on_encrypt=True, ask_on_decrypt=True) -> Tuple[bytearray, bytearray]:
        if self.connect_hardware_wallet():
            hw_device = self.__hw_devices.get_selected_device()
            if hw_device:
                if hw_device.hw_type not in (HWType.trezor, HWType.keepkey):
                    raise Exception(HWType.get_desc(hw_device.hw_type) + ' device does not support data encryption.' )
                return self.__hw_devices.hw_decrypt_value(self.__hw_devices.get_selected_device(), bip32_path_n, label,
                                                          value, ask_on_encrypt, ask_on_decrypt)
            else:
                raise Exception('Hardware wallet not available')
        else:
            raise Exception('Hardware wallet not available')


class HWDevicesListWdg(QWidget):
    sig_device_toggled = QtCore.pyqtSignal(HWDevice, bool)

    def __init__(self, parent, hw_devices: HWDevices):
        QWidget.__init__(self, parent=parent)
        self.hw_devices: HWDevices = hw_devices
        self.layout_main: Optional[QtWidgets.QVBoxLayout] = None
        self.spacer: Optional[QtWidgets.QSpacerItem] = None
        self.selected_hw_device: Optional[HWDevice] = self.hw_devices.get_selected_device()
        self.setupUi(self)

    def setupUi(self, dlg):
        dlg.setObjectName("HWDevicesListWdg")
        self.layout_main = QtWidgets.QVBoxLayout(dlg)
        self.layout_main.setObjectName('layout_main')
        self.layout_main.setContentsMargins(0, 0, 0, 0)
        self.layout_main.setSpacing(3)
        self.layout_main.setObjectName("verticalLayout")
        self.spacer = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.layout_main.addItem(self.spacer)
        self.retranslateUi(dlg)
        QtCore.QMetaObject.connectSlotsByName(dlg)
        self.devices_to_ui()

    def retranslateUi(self, widget):
        _translate = QtCore.QCoreApplication.translate
        widget.setWindowTitle(_translate("HWDevicesListWdg", "Form"))

    def set_selected_hw_device(self, hw_device: Optional[HWDevice]):
        self.selected_hw_device = hw_device

    def devices_to_ui(self):
        selected_device = self.selected_hw_device
        for hl_index in reversed(range(self.layout_main.count())):
            ctrl = self.layout_main.itemAt(hl_index)
            if ctrl and isinstance(ctrl, QtWidgets.QHBoxLayout) and ctrl.objectName() and \
                    ctrl.objectName().startswith('hl-hw-device-'):
                WndUtils.remove_item_from_layout(self.layout_main, ctrl)

        # create a list of radio buttons associated with each hw device connected to the computer;
        # each radio button is enclosed inside a horizontal layout along with a hyperlink control
        # allowing the identification of the appropriate hw device by highlighting its screen
        insert_idx = self.layout_main.indexOf(self.spacer)
        dev_cnt = len(self.hw_devices.get_devices())
        for idx, dev in enumerate(self.hw_devices.get_devices()):
            hl = QtWidgets.QHBoxLayout()
            hl.setSpacing(4)
            hl.setObjectName('hl-hw-device-' + str(idx))
            self.layout_main.insertLayout(insert_idx, hl)

            rb = QtWidgets.QRadioButton(self)
            rb.setText(dev.get_description())
            rb.toggled.connect(partial(self.on_device_rb_toggled, idx))
            if selected_device == dev:
                rb.setChecked(True)

            hl.addWidget(rb)

            if dev_cnt > 1:
                # link to identify hw devices show only if there are more then one connected to the computer
                lnk = QtWidgets.QLabel(self)
                lnk.setText('[<a href="identify-hw-device">ping device</a>]')
                lnk.linkActivated.connect(partial(self.on_hw_show_link_activated, dev))
                hl.addWidget(lnk)

            hl.addSpacerItem(
                QtWidgets.QSpacerItem(10, 10, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum))

            insert_idx += 1

    def on_device_rb_toggled(self, hw_device_index: int, checked: bool):
        devs = self.hw_devices.get_devices()
        if 0 <= hw_device_index < len(devs):
            self.sig_device_toggled.emit(devs[hw_device_index], checked)

    def on_hw_show_link_activated(self, hw_device, link):
        try:
            self.hw_devices.ping_device(hw_device)
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    def update(self):
        self.devices_to_ui()


class SelectHWDeviceDlg(QDialog):
    def __init__(self, parent, label: str, hw_devices: HWDevices):
        QDialog.__init__(self, parent=parent)
        self.hw_devices: HWDevices = hw_devices
        self.selected_hw_device: Optional[HWDevice] = self.hw_devices.get_selected_device()
        self.label = label
        self.lay_main: Optional[QtWidgets.QVBoxLayout] = None
        self.device_list_wdg: Optional[HWDevicesListWdg] = None
        self.lbl_title: Optional[QtWidgets.QLabel] = None
        self.btnbox_main: Optional[QtWidgets.QDialogButtonBox] = None
        self.tm_update_dlg_size: Optional[int] = None
        self.setupUi(self)

    def setupUi(self, dialog):
        dialog.setObjectName("SelectHWDevice")
        self.lay_main = QtWidgets.QVBoxLayout(dialog)
        self.lay_main.setContentsMargins(12, 12, 12, 3)
        self.lay_main.setSpacing(12)
        self.lay_main.setObjectName("lay_main")
        self.device_list_wdg = HWDevicesListWdg(self.parent(), self.hw_devices)
        self.device_list_wdg.sig_device_toggled.connect(self.on_device_toggled)
        self.lbl_title = QtWidgets.QLabel(dialog)
        self.lbl_title.setText(
            '<span><b>Select your hardware wallet device</b> [<a href="reload-devices">reload devices</a>]</span>')
        self.lbl_title.linkActivated.connect(self.on_reload_hw_devices)
        self.lay_main.addWidget(self.lbl_title)
        self.lay_main.addWidget(self.device_list_wdg)
        self.btnbox_main = QtWidgets.QDialogButtonBox(dialog)
        self.btnbox_main.setStandardButtons(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Ok)
        self.btnbox_main.setObjectName("btn_main")
        self.btnbox_main.accepted.connect(self.on_btn_main_accepted)
        self.btnbox_main.rejected.connect(self.on_btn_main_rejected)
        self.lay_main.addWidget(self.btnbox_main)
        self.retranslateUi(dialog)
        self.setFixedSize(self.sizeHint())
        self.update_buttons_state()

    def retranslateUi(self, dialog):
        _translate = QtCore.QCoreApplication.translate
        dialog.setWindowTitle('Hardware wallet selection')

    @pyqtSlot(HWDevice, bool)
    def on_device_toggled(self, device: HWDevice, selected: bool):
        if not selected:
            if device == self.selected_hw_device:
                self.selected_hw_device = None
        else:
            self.selected_hw_device = device
        self.update_buttons_state()

    def on_reload_hw_devices(self, link):
        try:
            selected_id = self.selected_hw_device.device_id if self.selected_hw_device else None
            anything_changed = self.hw_devices.load_hw_devices(force_fetch=True)

            if selected_id:
                # restore the device selected in the device list if was selected before and is still connected
                self.selected_hw_device = self.hw_devices.get_device_by_id(selected_id)
                self.device_list_wdg.set_selected_hw_device(self.selected_hw_device)

            if anything_changed:
                self.device_list_wdg.update()
                # launch timer resizing the window size - resizing it directly here has no effect
                self.tm_update_dlg_size = self.startTimer(10)
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    def timerEvent(self, event):
        if self.tm_update_dlg_size:
            self.killTimer(self.tm_update_dlg_size)
            self.tm_update_dlg_size = None
        self.setFixedSize(self.sizeHint())

    def update_buttons_state(self):
        b = self.btnbox_main.button(QtWidgets.QDialogButtonBox.Ok)
        if b:
            b.setEnabled(self.selected_hw_device is not None)

    def on_btn_main_accepted(self):
        if self.selected_hw_device is not None:
            self.accept()

    def on_btn_main_rejected(self):
        self.reject()


@control_hw_call
def sign_tx(hw_session: HwSessionInfo, utxos_to_spend: List[UtxoType], tx_outputs: List[TxOutputType], tx_fee):
    """
    Creates a signed transaction.
    :param hw_session:
    :param utxos_to_spend: list of utxos to send
    :param tx_outputs: destination addresses. Fields: 0: dest Dash address. 1: the output value in satoshis,
        2: the bip32 path of the address if the output is the change address or None otherwise
    :param tx_fee: transaction fee
    :return: tuple (serialized tx, total transaction amount in satoshis)
    """

    def sign(ctrl):
        ctrl.dlg_config(dlg_title="Confirm transaction signing.", show_progress_bar=False)
        ctrl.display_msg('<b>Click the confirmation button on your hardware wallet<br>'
                         'and wait for the transaction to be signed...</b>')

        if hw_session.hw_type == HWType.trezor:

            return trezor.sign_tx(hw_session, hw_session.runtime_data, utxos_to_spend, tx_outputs, tx_fee)

        elif hw_session.hw_type == HWType.keepkey:

            return keepkey.sign_tx(hw_session, hw_session.runtime_data, utxos_to_spend, tx_outputs, tx_fee)

        elif hw_session.hw_type == HWType.ledger_nano:

            return ledger.sign_tx(hw_session, hw_session.runtime_data, utxos_to_spend, tx_outputs, tx_fee)

        else:
            logging.error('Invalid HW type: ' + str(hw_session.hw_type))

    # execute the 'prepare' function, but due to the fact that the call blocks the UI until the user clicks the HW
    # button, it's done inside a thread within a dialog that shows an appropriate message to the user
    sig = WndUtils.run_thread_dialog(sign, (), True,
                                     force_close_dlg_callback=partial(cancel_hw_thread_dialog, hw_session.hw_client))
    return sig


@control_hw_call
def hw_sign_message(hw_session: HwSessionInfo, hw_coin_name: str, bip32path, message, display_label: str = None):
    def sign(ctrl, display_label_):
        ctrl.dlg_config(dlg_title="Confirm message signing.", show_progress_bar=False)
        if not display_label_:
            if hw_session.hw_type == HWType.ledger_nano:
                message_hash = hashlib.sha256(message.encode('ascii')).hexdigest().upper()
                display_label_ = '<b>Click the confirmation button on your hardware wallet to sign the message...</b>' \
                                 '<br><br><b>Message:</b><br><span>' + message + '</span><br><br><b>SHA256 hash</b>:' \
                                                                                 '<br>' + message_hash
            else:
                display_label_ = '<b>Click the confirmation button on your hardware wallet to sign the message...</b>'
        ctrl.display_msg(display_label_)

        if hw_session.hw_type == HWType.trezor:

            return trezor.sign_message(hw_session.hw_client, hw_coin_name, bip32path, message)

        elif hw_session.hw_type == HWType.keepkey:

            return keepkey.sign_message(hw_session.hw_client, hw_coin_name, bip32path, message)

        elif hw_session.hw_type == HWType.ledger_nano:

            return ledger.sign_message(hw_session.hw_client, bip32path, message, hw_session)
        else:
            logging.error('Invalid HW type: ' + str(hw_session.hw_type))

    # execute the 'sign' function, but due to the fact that the call blocks the UI until the user clicks the HW
    # button, it's done inside a thread within a dialog that shows an appropriate message to the user
    sig = WndUtils.run_thread_dialog(sign, (display_label,), True,
                                     force_close_dlg_callback=partial(cancel_hw_thread_dialog, hw_session.hw_client))
    return sig


@control_hw_call
def get_address(hw_session: HwSessionInfo, bip32_path: str, show_display: bool = False,
                message_to_display: str = None, asynchr: bool = True):
    def _get_address(ctrl):
        nonlocal hw_session, bip32_path, show_display, message_to_display
        try:
            if ctrl:
                ctrl.dlg_config(dlg_title=DEFAULT_HW_BUSY_TITLE, show_progress_bar=False)
                if message_to_display:
                    ctrl.display_msg(message_to_display)
                else:
                    ctrl.display_msg('<b>Click the confirmation button on your hardware wallet to exit...</b>')

            client = hw_session.hw_client
            if client:
                if isinstance(bip32_path, str):
                    bip32_path.strip()
                    if bip32_path.lower().find('m/') >= 0:
                        # removing m/ prefix because of keepkey library
                        bip32_path = bip32_path[2:]

                if hw_session.hw_type == HWType.trezor:

                    try:
                        if isinstance(bip32_path, str):
                            bip32_path = dash_utils.bip32_path_string_to_n(bip32_path)
                        ret = trezorlib.btc.get_address(client, hw_session.runtime_data.hw_coin_name, bip32_path,
                                                        show_display)
                        return ret
                    except (CancelException, trezorlib.exceptions.Cancelled):
                        raise CancelException()

                elif hw_session.hw_type == HWType.keepkey:

                    try:
                        if isinstance(bip32_path, str):
                            bip32_path = dash_utils.bip32_path_string_to_n(bip32_path)
                        return client.get_address(hw_session.runtime_data.hw_coin_name, bip32_path, show_display)
                    except keepkeylib.client.CallException as e:
                        if isinstance(e.args, tuple) and len(e.args) >= 2 and isinstance(e.args[1], str) and \
                                e.args[1].find('cancel') >= 0:
                            raise CancelException('Cancelled')

                elif hw_session.hw_type == HWType.ledger_nano:

                    if isinstance(bip32_path, list):
                        # ledger requires bip32 path argument as a string
                        bip32_path = bip32_path_n_to_string(bip32_path)

                    adr_pubkey = ledger.get_address_and_pubkey(hw_session, bip32_path, show_display)
                    return adr_pubkey.get('address')
                else:
                    raise Exception('Unknown hardware wallet type: ' + str(hw_session.hw_type))
            else:
                raise Exception('HW client not open.')
        finally:
            pass

    if message_to_display or show_display:
        msg_delay = 0
    else:
        msg_delay = 1000
        message_to_display = DEFAULT_HW_BUSY_MESSAGE

    if asynchr:
        return WndUtils.run_thread_dialog(_get_address, (), True, show_window_delay_ms=msg_delay,
                                          force_close_dlg_callback=partial(cancel_hw_thread_dialog,
                                                                           hw_session.hw_client))
    else:
        return _get_address(None)


@control_hw_call
def get_address_and_pubkey(hw_session: HwSessionInfo, hw_coin_name: str, bip32_path: str):
    client = hw_session.hw_client
    if client:
        if isinstance(bip32_path, str):
            bip32_path.strip()
            if bip32_path.lower().find('m/') >= 0:
                # removing m/ prefix because of keepkey library
                bip32_path = bip32_path[2:]

        if hw_session.hw_type == HWType.trezor:

            if isinstance(bip32_path, str):
                bip32_path = dash_utils.bip32_path_string_to_n(bip32_path)
            return {
                'address': trezorlib.btc.get_address(client, hw_coin_name, bip32_path, False),
                'publicKey': trezorlib.btc.get_public_node(client, bip32_path).node.public_key
            }

        elif hw_session.hw_type == HWType.keepkey:
            if isinstance(bip32_path, str):
                bip32_path = dash_utils.bip32_path_string_to_n(bip32_path)
            return {
                'address': client.get_address(hw_coin_name, bip32_path, False),
                'publicKey': client.get_public_node(bip32_path).node.public_key
            }

        elif hw_session.hw_type == HWType.ledger_nano:

            if isinstance(bip32_path, list):
                # ledger requires bip32 path argument as a string
                bip32_path = bip32_path_n_to_string(bip32_path)

            return ledger.get_address_and_pubkey(hw_session, bip32_path)
        else:
            raise Exception('Unknown hardware wallet type: ' + str(hw_session.hw_type.value))


@control_hw_call
def get_xpub(hw_session: HwSessionInfo, bip32_path: str):
    client = hw_session.hw_client
    if client:
        if isinstance(bip32_path, str):
            bip32_path.strip()
            if bip32_path.lower().find('m/') >= 0:
                bip32_path = bip32_path[2:]

        if hw_session.hw_type == HWType.trezor:
            if isinstance(bip32_path, str):
                bip32_path = dash_utils.bip32_path_string_to_n(bip32_path)

            return trezorlib.btc.get_public_node(client, bip32_path).xpub

        elif hw_session.hw_type == HWType.keepkey:
            if isinstance(bip32_path, str):
                bip32_path = dash_utils.bip32_path_string_to_n(bip32_path)

            return client.get_public_node(bip32_path).xpub

        elif hw_session.hw_type == HWType.ledger_nano:

            if isinstance(bip32_path, list):
                # ledger requires bip32 path argument as a string
                bip32_path = bip32_path_n_to_string(bip32_path)

            return ledger.get_xpub(client, bip32_path)
        else:
            raise Exception('Unknown hardware wallet type: ' + str(hw_session.hw_type))
    else:
        raise Exception('HW client not open.')


def get_hw_firmware_web_sources(hw_models_allowed: Tuple[HWModel, ...],
                                only_official=True, only_latest=False) -> List[HWFirmwareWebLocation]:
    def get_trezor_firmware_list_from_url(
            base_url: str, list_url: str, official_source: bool = False, only_latest: bool = False,
            model_for_this_source: Optional[str] = None, testnet_support: bool = False) -> List[HWFirmwareWebLocation]:

        ret_fw_sources_: List[HWFirmwareWebLocation] = []
        r = urllib.request.Request(list_url, data=None, headers={'User-Agent': app_defs.BROWSER_USER_AGENT})
        f = urllib.request.urlopen(r)
        c = f.read()
        fw_list = simplejson.loads(c)
        latest_version = ''
        for idx, f in enumerate(fw_list):
            url_ = url_path_join(base_url, f.get('url'))
            version = f.get('version')
            if isinstance(version, list):
                version = '.'.join(str(x) for x in version)
            else:
                version = str(version)
            if idx == 0:
                latest_version = version
            cur_model_str = f.get('model') if f.get('model') else model_for_this_source

            if not only_latest or version == latest_version:
                allowed = next((x for x in hw_models_allowed if HWModel.get_hw_type(x) == HWType.trezor and
                                HWModel.get_model_str(x) == cur_model_str), None)
                if allowed:
                    ret_fw_sources_.append(
                        HWFirmwareWebLocation(
                            version=version,
                            url=url_,
                            device=HWType.trezor,
                            official=official_source,
                            model=cur_model_str,
                            testnet_support=testnet_support,
                            notes=f.get('notes', ''),
                            fingerprint=f.get('fingerprint', ''),
                            changelog=f.get('changelog', '')
                        ))
        return ret_fw_sources_

    def get_keepkey_firmware_list_from_url(
            base_url: str, list_url: str, official_source: bool = False, only_latest: bool = False,
            testnet_support: bool = False) -> List[HWFirmwareWebLocation]:
        """
        Keepkey releases json format as of March 2021:
        {
          "latest": {
            "firmware": {
              "version": "v6.7.0",
              "url": "v6.7.0/firmware.keepkey.bin"
            },
            "bootloader": {
              "version": "v1.1.0",
              "url": "bl_v1.1.0/blupdater.bin"
            }
          },
          "hashes": {
            "bootloader": {
              "6397c446f6b9002a8b150bf4b9b4e0bb66800ed099b881ca49700139b0559f10": "v1.0.0",
              .....
              "9bf1580d1b21250f922b68794cdadd6c8e166ae5b15ce160a42f8c44a2f05936": "v2.0.0"
            },
            "firmware": {
              "24071db7596f0824e51ce971c1ec39ac5a07e7a5bcaf5f1b33313de844e25580": "v6.7.0",
              ....
              "a05b992c1cadb151117704a03af8b7020482061200ce7bc72f90e8e4aba01a4f": "v5.11.0"
            }
          }
        }
        """
        ret_fw_sources_: List[HWFirmwareWebLocation] = []

        # Shapeshift doesn't allow querying their sites with firmware releases from non-browser code (error 403),
        # so we need to pass some browser-looking "user agent" value.
        r = urllib.request.Request(list_url, data=None, headers={'User-Agent': app_defs.BROWSER_USER_AGENT})
        f = urllib.request.urlopen(r)
        c = f.read()
        fw_list = simplejson.loads(c)
        latest_version = ''
        if fw_list.get('latest') and fw_list.get('latest').get('firmware'):
            latest_version = fw_list['latest']['firmware'].get('version')
            latest_url = fw_list['latest']['firmware'].get('url')

        if fw_list.get('hashes') and fw_list.get('hashes').get('firmware'):
            hf = fw_list.get('hashes').get('firmware')
            if isinstance(hf, dict):
                for hash in hf:
                    version = hf[hash]
                    url_ = url_path_join(base_url, version, 'firmware.keepkey.bin')
                    if version.startswith('v'):
                        version = version[1:]
                    if not only_latest or version == latest_version:
                        ret_fw_sources_.append(
                            HWFirmwareWebLocation(
                                version=version,
                                url=url_,
                                device=HWType.keepkey,
                                official=official_source,
                                model='',
                                testnet_support=testnet_support,
                                fingerprint=hash
                            ))

        return ret_fw_sources_

    ret_fw_sources: List[HWFirmwareWebLocation] = []

    try:
        project_url = app_defs.PROJECT_URL.replace('//github.com', '//raw.githubusercontent.com')
        url = url_path_join(project_url, 'master', 'hardware-wallets/firmware/firmware-sources.json')

        response = urllib.request.urlopen(url)
        contents = response.read()
        for fw_src_def in simplejson.loads(contents):
            try:
                official_source = fw_src_def.get('official')
                hw_type = HWType.from_string(fw_src_def.get('device')) if fw_src_def.get('device') else None
                hw_model_symbol = fw_src_def.get('model')
                url = fw_src_def.get('url')
                url_base = fw_src_def.get('url_base')
                testnet_support = fw_src_def.get('testnetSupport', True)
                if not url_base:
                    url_base = project_url

                if not re.match('\s*http(s)?://', url, re.IGNORECASE):
                    url = url_path_join(url_base, url)

                if only_official is False or official_source is True:
                    allowed_model = next((x for x in hw_models_allowed if HWModel.get_hw_type(x) == hw_type and
                                          (not hw_model_symbol or HWModel.get_model_str(x) == hw_model_symbol)), None)

                    if allowed_model:
                        if hw_type == HWType.trezor:
                            lst = get_trezor_firmware_list_from_url(
                                base_url=url_base, list_url=url, only_latest=only_latest,
                                official_source=official_source, model_for_this_source=hw_model_symbol,
                                testnet_support=testnet_support)

                            ret_fw_sources.extend(lst)
                        elif hw_type == HWType.keepkey:
                            lst = get_keepkey_firmware_list_from_url(
                                base_url=url_base, list_url=url, official_source=official_source,
                                only_latest=only_latest, testnet_support=testnet_support)
                            ret_fw_sources.extend(lst)

            except Exception:
                logging.exception('Exception while processing firmware source')
    except Exception as e:
        logging.error('Error while loading hardware-wallets/firmware/releases.json file from GitHub: ' + str(e))

    return ret_fw_sources
