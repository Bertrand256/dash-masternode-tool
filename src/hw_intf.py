#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import hashlib
import sqlite3
import threading
from functools import partial
from typing import Optional, Tuple, List, ByteString, Callable, Dict
import sys

import usb1
from PyQt5 import QtWidgets

import dash_utils
from common import CancelException
from dash_utils import bip32_path_n_to_string
from hw_common import HardwareWalletPinException, HwSessionInfo, get_hw_type, HWNotConnectedException
import logging
from app_defs import HWType
from wallet_common import UtxoType, TxOutputType
from wnd_utils import WndUtils


DEFAULT_HW_BUSY_MESSAGE = '<b>Complete the action on your hardware wallet device</b>'
DEFAULT_HW_BUSY_TITLE = 'Please confirm'


# Dict[str <hd tree ident>, Dict[str <bip32 path>, Tuple[str <address>, int <db id>]]]
bip32_address_map: Dict[str, Dict[str, Tuple[str, int]]] = {}

hd_tree_db_map: Dict[str, int] = {}  # Dict[str <hd tree ident>, int <db id>]


def control_trezor_keepkey_libs(connecting_to_hw):
    """
    Check if trying to switch between Trezor and Keepkey on Linux. It's not allowed because Trezor/Keepkey's client
    libraries use objects with the same names (protobuf), which causes errors when switching between them.
    :param connecting_to_hw: type of the hardware wallet we are going to connect to.
    :return:
    """
    if sys.platform == 'linux' and ((connecting_to_hw == HWType.trezor and 'keepkeylib' in sys.modules.keys()) or
       (connecting_to_hw == HWType.keepkey and 'trezorlib' in sys.modules.keys())):
        raise Exception('On linux OS switching between Trezor/Keepkey wallets requires restarting the '
                        'application.\n\nPlease restart the application to continue.')


def control_hw_call(func):
    """
    Decorator for some of the hardware wallet functions. It ensures, that hw client connection is open (and if is not, 
    it makes attempt to open it). The s econt thing is to catch OSError exception as a result of disconnecting 
    hw cable. After this, connection has to be closed and opened again, otherwise 'read error' occurrs. 
    :param func: function decorated. First argument of the function has to be the reference to the MainWindow object.
    """
    def catch_hw_client(*args, **kwargs):
        hw_session: HwSessionInfo = args[0]
        client = hw_session.hw_client
        if not client:
            client = hw_session.hw_connect()
        if not client:
            raise HWNotConnectedException()
        try:
            try:
                # protect against simultaneous access to the same device from different threads
                hw_session.acquire_client()

                control_trezor_keepkey_libs(hw_session.hw_type)
                if hw_session.hw_type == HWType.trezor:

                    import hw_intf_trezor as trezor
                    import trezorlib.client as client
                    from trezorlib import exceptions

                    try:
                        ret = func(*args, **kwargs)
                    except exceptions.PinException as e:
                        raise HardwareWalletPinException(e.args[1])

                elif hw_session.hw_type == HWType.keepkey:

                    import hw_intf_keepkey as keepkey
                    import keepkeylib.client as client
                    try:
                        ret = func(*args, **kwargs)
                    except client.PinException as e:
                        raise HardwareWalletPinException(e.args[1])

                elif hw_session.hw_type == HWType.ledger_nano_s:

                    ret = func(*args, **kwargs)

                else:
                    raise Exception('Uknown hardware wallet type: ' + hw_session.hw_type)
            finally:
                hw_session.release_client()

        except (OSError, usb1.USBErrorNoDevice) as e:
            logging.exception('Exception calling %s function' % func.__name__)
            logging.info('Disconnecting HW after OSError occurred')
            hw_session.hw_disconnect()
            raise HWNotConnectedException('The hardware wallet device has been disconnected with the '
                                          'following error: ' + str(e))

        except HardwareWalletPinException:
            raise

        except CancelException:
            raise

        except Exception as e:
            logging.exception('Exception calling %s function' % func.__name__)
            raise

        return ret

    return catch_hw_client


def get_device_list(hw_type: HWType, return_clients: bool = True, allow_bootloader_mode: bool = False) \
    -> Tuple[List[Dict], List[Exception]]:
    """
    :return: Tuple[List[Dict <{'client': MyTrezorClient, 'device_id': str, 'desc',: str, 'model': str}>],
                   List[Exception]]
    """

    if hw_type == HWType.trezor:

        import hw_intf_trezor as trezor
        return trezor.get_device_list(return_clients, allow_bootloader_mode=allow_bootloader_mode)

    elif hw_type == HWType.keepkey:

        import hw_intf_keepkey as keepkey
        return keepkey.get_device_list(return_clients, allow_bootloader_mode=allow_bootloader_mode)

    elif hw_type == HWType.ledger_nano_s:

        raise Exception('Invalid HW type: ' + str(hw_type))


def cancel_hw_thread_dialog(hw_client):
    try:
        hw_type = get_hw_type(hw_client)
        if hw_type == HWType.trezor:
            hw_client.cancel()
        elif hw_type == HWType.keepkey:
            hw_client.cancel()
        elif hw_type == HWType.ledger_nano_s:
            return False
        raise CancelException('Cancel')
    except CancelException:
        raise
    except Exception as e:
        logging.warning('Error when canceling hw session. Details: %s', str(e))
        return True


def connect_hw(hw_session: Optional[HwSessionInfo], hw_type: HWType, device_id: Optional[str] = 'NFC',
               passphrase_encoding: Optional[str] = None):
    """
    Initializes connection with a hardware wallet.
    :param hw_type: symbol of the hardware wallet type
    :param passphrase_encoding: (for Keepkey only) it allows forcing the passphrase encoding compatible with BIP-39
        standard (NFKD), which is used by Trezor devices; by default Keepkey uses non-standard encoding (NFC).
    :return:
    """
    def get_session_info_trezor(get_public_node_fun, hw_session: HwSessionInfo, hw_client):
        nonlocal hw_type

        def call_get_public_node(ctrl, get_public_node_fun, path_n):
            pk = get_public_node_fun(path_n).node.public_key
            return pk

        path = dash_utils.get_default_bip32_base_path(hw_session.app_config.dash_network)
        path_n = dash_utils.bip32_path_string_to_n(path)

        # show message for Trezor T device while waiting for the user to choose the passphrase input method
        pub = WndUtils.run_thread_dialog(call_get_public_node, (get_public_node_fun, path_n),
                                         title=DEFAULT_HW_BUSY_TITLE, text=DEFAULT_HW_BUSY_MESSAGE,
                                         force_close_dlg_callback=partial(cancel_hw_thread_dialog, hw_client),
                                         show_window_delay_ms=1000)

        if pub:
            hw_session.set_base_info(path, pub)
        else:
            raise Exception('Couldn\'t read data from the hardware wallet.')

    control_trezor_keepkey_libs(hw_type)
    if hw_type == HWType.trezor:
        import hw_intf_trezor as trezor
        import trezorlib.client as client
        from trezorlib import btc, exceptions
        try:
            if hw_session and hw_session.app_config:
                use_webusb = hw_session.app_config.trezor_webusb
                use_bridge = hw_session.app_config.trezor_bridge
                use_udp = hw_session.app_config.trezor_udp
                use_hid = hw_session.app_config.trezor_hid
            else:
                use_webusb = True
                use_bridge = True
                use_udp = True
                use_hid = True

            cli = trezor.connect_trezor(device_id=device_id, use_webusb=use_webusb, use_bridge=use_bridge,
                                        use_udp=use_udp, use_hid=use_hid)
            if cli and hw_session:
                try:
                    get_public_node_fun = partial(btc.get_public_node, cli)
                    get_session_info_trezor(get_public_node_fun, hw_session, cli)
                except (CancelException, exceptions.Cancelled):
                    # cancel_hw_operation(cli)
                    disconnect_hw(cli)
                    raise CancelException()
                except Exception as e:
                    # in the case of error close the session
                    disconnect_hw(cli)
                    raise
            return cli
        except exceptions.PinException as e:
            raise HardwareWalletPinException(e.args[1])

    elif hw_type == HWType.keepkey:
        import hw_intf_keepkey as keepkey
        import keepkeylib.client as client
        try:
            cli = keepkey.connect_keepkey(passphrase_encoding=passphrase_encoding, device_id=device_id)
            if cli and hw_session:
                try:
                    get_session_info_trezor(cli.get_public_node, hw_session, cli)
                except CancelException:
                    cancel_hw_operation(cli)
                    disconnect_hw(cli)
                    raise
                except Exception:
                    # in the case of error close the session
                    disconnect_hw(cli)
                    raise
            return cli

        except client.PinException as e:
            raise HardwareWalletPinException(e.args[1])

    elif hw_type == HWType.ledger_nano_s:
        import hw_intf_ledgernano as ledger
        cli = ledger.connect_ledgernano()
        if cli and hw_session:
            try:
                path = dash_utils.get_default_bip32_base_path(hw_session.app_config.dash_network)
                ap = ledger.get_address_and_pubkey(cli, path)
                hw_session.set_base_info(path, ap['publicKey'])
            except CancelException:
                cancel_hw_operation(cli)
                disconnect_hw(cli)
                raise
            except Exception:
                # in the case of error close the session
                disconnect_hw(cli)
                raise
        return cli

    else:
        raise Exception('Invalid HW type: ' + str(hw_type))


def disconnect_hw(hw_client):
    try:
        hw_type = get_hw_type(hw_client)
        if hw_type in (HWType.trezor, HWType.keepkey):
            hw_client.close()
        elif hw_type == HWType.ledger_nano_s:
            hw_client.dongle.close()
    except Exception as e:
        # probably already disconnected
        logging.exception('Disconnect HW error')


def cancel_hw_operation(hw_client):
    try:
        hw_type = get_hw_type(hw_client)
        if hw_type in (HWType.trezor, HWType.keepkey):
            hw_client.cancel()
    except Exception as e:
        logging.error('Error when cancelling hw operation: %s', str(e))


def get_hw_label(hw_client):
    hw_type = get_hw_type(hw_client)
    if hw_type in (HWType.trezor, HWType.keepkey):
        return hw_client.features.label
    elif hw_type == HWType.ledger_nano_s:
        return 'Ledger Nano S'


@control_hw_call
def get_hw_firmware_version(hw_session: HwSessionInfo):
    hw_type = get_hw_type(hw_session.hw_client)
    if hw_type in (HWType.trezor, HWType.keepkey):

        return str(hw_session.hw_client.features.major_version) + '.' + \
               str(hw_session.hw_client.features.minor_version) + '.' + \
               str(hw_session.hw_client.features.patch_version)

    elif hw_type == HWType.ledger_nano_s:

        return hw_session.hw_client.getFirmwareVersion().get('version')


@control_hw_call
def sign_tx(hw_session: HwSessionInfo, utxos_to_spend: List[UtxoType],
            tx_outputs: List[TxOutputType], tx_fee):
    """
    Creates a signed transaction.
    :param main_ui: Main window for configuration data
    :param utxos_to_spend: list of utxos to send
    :param tx_outputs: destination addresses. Fields: 0: dest Dash address. 1: the output value in satoshis,
        2: the bip32 path of the address if the output is the change address or None otherwise
    :param tx_fee: transaction fee
    :param rawtransactions: dict mapping txid to rawtransaction
    :return: tuple (serialized tx, total transaction amount in satoshis)
    """
    def sign(ctrl):
        ctrl.dlg_config_fun(dlg_title="Confirm transaction signing.", show_progress_bar=False)
        ctrl.display_msg_fun('<b>Click the confirmation button on your hardware wallet<br>'
                             'and wait for the transaction to be signed...</b>')

        if hw_session.app_config.hw_type == HWType.trezor:
            import hw_intf_trezor as trezor

            return trezor.sign_tx(hw_session, utxos_to_spend, tx_outputs, tx_fee)

        elif hw_session.app_config.hw_type == HWType.keepkey:
            import hw_intf_keepkey as keepkey

            return keepkey.sign_tx(hw_session, utxos_to_spend, tx_outputs, tx_fee)

        elif hw_session.app_config.hw_type == HWType.ledger_nano_s:
            import hw_intf_ledgernano as ledger

            return ledger.sign_tx(hw_session, utxos_to_spend, tx_outputs, tx_fee)

        else:
            logging.error('Invalid HW type: ' + str(hw_session.app_config.hw_type))

    # execute the 'prepare' function, but due to the fact that the call blocks the UI until the user clicks the HW
    # button, it's done inside a thread within a dialog that shows an appropriate message to the user
    sig = WndUtils.run_thread_dialog(sign, (), True,
                                     force_close_dlg_callback=partial(cancel_hw_thread_dialog, hw_session.hw_client))
    return sig


@control_hw_call
def hw_sign_message(hw_session: HwSessionInfo, bip32path, message, display_label: str = None):
    def sign(ctrl, display_label):
        ctrl.dlg_config_fun(dlg_title="Confirm message signing.", show_progress_bar=False)
        if not display_label:
            if hw_session.app_config.hw_type == HWType.ledger_nano_s:
                message_hash = hashlib.sha256(message.encode('ascii')).hexdigest().upper()
                display_label = '<b>Click the confirmation button on your hardware wallet to sign the message...</b>' \
                                '<br><br><b>Message:</b><br><span>' + message + '</span><br><br><b>SHA256 hash</b>:' \
                                                                                '<br>' + message_hash
            else:
                display_label = '<b>Click the confirmation button on your hardware wallet to sign the message...</b>'
        ctrl.display_msg_fun(display_label)

        if hw_session.app_config.hw_type == HWType.trezor:
            import hw_intf_trezor as trezor

            return trezor.sign_message(hw_session, bip32path, message)

        elif hw_session.app_config.hw_type == HWType.keepkey:
            import hw_intf_keepkey as keepkey

            return keepkey.sign_message(hw_session, bip32path, message)

        elif hw_session.app_config.hw_type == HWType.ledger_nano_s:
            import hw_intf_ledgernano as ledger

            return ledger.sign_message(hw_session, bip32path, message)
        else:
            logging.error('Invalid HW type: ' + str(hw_session.app_config.hw_type))

    # execute the 'sign' function, but due to the fact that the call blocks the UI until the user clicks the HW
    # button, it's done inside a thread within a dialog that shows an appropriate message to the user
    sig = WndUtils.run_thread_dialog(sign, (display_label,), True,
                                     force_close_dlg_callback=partial(cancel_hw_thread_dialog, hw_session.hw_client))
    return sig


@control_hw_call
def change_pin(hw_session: HwSessionInfo, remove=False):
    if hw_session.app_config.hw_type == HWType.trezor:
        import hw_intf_trezor as trezor

        return trezor.change_pin(hw_session, remove)

    elif hw_session.app_config.hw_type == HWType.keepkey:
        import hw_intf_keepkey as keepkey

        return keepkey.change_pin(hw_session, remove)

    elif hw_session.app_config.hw_type == HWType.ledger_nano_s:

        raise Exception('Ledger Nano S not supported.')

    else:
        logging.error('Invalid HW type: ' + str(hw_session.app_config.hw_type))


@control_hw_call
def enable_passphrase(hw_session: HwSessionInfo, passphrase_enabled):
    if hw_session.app_config.hw_type == HWType.trezor:
        import hw_intf_trezor

        hw_intf_trezor.enable_passphrase(hw_session, passphrase_enabled)

    elif hw_session.app_config.hw_type == HWType.keepkey:

        hw_session.hw_client.apply_settings(use_passphrase=passphrase_enabled)

    elif hw_session.app_config.hw_type == HWType.ledger_nano_s:

        raise Exception('Ledger Nano S not supported.')

    else:
        logging.error('Invalid HW type: ' + str(hw_session.app_config.hw_type))


@control_hw_call
def get_address(hw_session: HwSessionInfo, bip32_path: str, show_display: bool = False, message_to_display: str = None):

    def _get_address(ctrl, hw_session: HwSessionInfo, bip32_path: str, show_display: bool = False,
                     message_to_display: str = None):
        if ctrl:
            ctrl.dlg_config_fun(dlg_title=DEFAULT_HW_BUSY_TITLE, show_progress_bar=False)
            if message_to_display:
                ctrl.display_msg_fun(message_to_display)
            else:
                ctrl.display_msg_fun('<b>Click the confirmation button on your hardware wallet to exit...</b>')

        client = hw_session.hw_client
        if client:
            if isinstance(bip32_path, str):
                bip32_path.strip()
                if bip32_path.lower().find('m/') >= 0:
                    # removing m/ prefix because of keepkey library
                    bip32_path = bip32_path[2:]

            if hw_session.app_config.hw_type == HWType.trezor:

                from trezorlib import btc
                from trezorlib import exceptions

                try:
                    if isinstance(bip32_path, str):
                        bip32_path = dash_utils.bip32_path_string_to_n(bip32_path)
                    ret = btc.get_address(client, hw_session.app_config.hw_coin_name, bip32_path, show_display)
                    return ret
                except (CancelException, exceptions.Cancelled):
                    raise CancelException()

            elif hw_session.app_config.hw_type == HWType.keepkey:

                from keepkeylib.client import CallException

                try:
                    if isinstance(bip32_path, str):
                        bip32_path = dash_utils.bip32_path_string_to_n(bip32_path)
                    return client.get_address(hw_session.app_config.hw_coin_name, bip32_path, show_display)
                except CallException as e:
                    if isinstance(e.args, tuple) and len(e.args) >= 2 and isinstance(e.args[1], str) and \
                            e.args[1].find('cancel') >= 0:
                        raise CancelException('Cancelled')

            elif hw_session.app_config.hw_type == HWType.ledger_nano_s:
                import hw_intf_ledgernano as ledger

                if isinstance(bip32_path, list):
                    # ledger requires bip32 path argument as a string
                    bip32_path = bip32_path_n_to_string(bip32_path)

                adr_pubkey = ledger.get_address_and_pubkey(client, bip32_path, show_display)
                return adr_pubkey.get('address')
            else:
                raise Exception('Unknown hardware wallet type: ' + hw_session.app_config.hw_type)
        else:
            raise Exception('HW client not open.')

    if message_to_display or show_display:
        msg_delay = 0
    else:
        msg_delay = 1000
        message_to_display = DEFAULT_HW_BUSY_MESSAGE

    return WndUtils.run_thread_dialog(_get_address, (hw_session, bip32_path, show_display, message_to_display),
                                      True, show_window_delay_ms=msg_delay,
                                      force_close_dlg_callback=partial(cancel_hw_thread_dialog, hw_session.hw_client))


@control_hw_call
def get_address_and_pubkey(hw_session: HwSessionInfo, bip32_path):
    client = hw_session.hw_client
    if client:
        if isinstance(bip32_path, str):
            bip32_path.strip()
            if bip32_path.lower().find('m/') >= 0:
                # removing m/ prefix because of keepkey library
                bip32_path = bip32_path[2:]

        if hw_session.app_config.hw_type == HWType.trezor:

            from trezorlib import btc
            if isinstance(bip32_path, str):
                bip32_path = dash_utils.bip32_path_string_to_n(bip32_path)
            return {
                'address': btc.get_address(client, hw_session.app_config.hw_coin_name, bip32_path, False),
                'publicKey': btc.get_public_node(client, bip32_path).node.public_key
            }

        elif hw_session.app_config.hw_type == HWType.keepkey:
            if isinstance(bip32_path, str):
                bip32_path = dash_utils.bip32_path_string_to_n(bip32_path)
            return {
                'address': client.get_address(hw_session.app_config.hw_coin_name, bip32_path, False),
                'publicKey': client.get_public_node(bip32_path).node.public_key
            }


        elif hw_session.app_config.hw_type == HWType.ledger_nano_s:
            import hw_intf_ledgernano as ledger

            if isinstance(bip32_path, list):
                # ledger requires bip32 path argument as a string
                bip32_path = bip32_path_n_to_string(bip32_path)

            return ledger.get_address_and_pubkey(client, bip32_path)
        else:
            raise Exception('Unknown hardware wallet type: ' + hw_session.app_config.hw_type)


@control_hw_call
def get_xpub(hw_session: HwSessionInfo, bip32_path):
    client = hw_session.hw_client
    if client:
        if isinstance(bip32_path, str):
            bip32_path.strip()
            if bip32_path.lower().find('m/') >= 0:
                bip32_path = bip32_path[2:]

        if hw_session.app_config.hw_type == HWType.trezor:
            from trezorlib import btc
            if isinstance(bip32_path, str):
                bip32_path = dash_utils.bip32_path_string_to_n(bip32_path)

            return btc.get_public_node(client, bip32_path).xpub

        elif hw_session.app_config.hw_type == HWType.keepkey:
            if isinstance(bip32_path, str):
                bip32_path = dash_utils.bip32_path_string_to_n(bip32_path)

            return client.get_public_node(bip32_path).xpub

        elif hw_session.app_config.hw_type == HWType.ledger_nano_s:
            import hw_intf_ledgernano as ledger

            if isinstance(bip32_path, list):
                # ledger requires bip32 path argument as a string
                bip32_path = bip32_path_n_to_string(bip32_path)

            return ledger.get_xpub(client, bip32_path)
        else:
            raise Exception('Unknown hardware wallet type: ' + hw_session.app_config.hw_type)
    else:
        raise Exception('HW client not open.')


def wipe_device(hw_type: HWType, hw_device_id: Optional[str], parent_window = None) -> Tuple[Optional[str], bool]:
    """
    Wipes the hardware wallet device.
    :param hw_type: app_config.HWType
    :param hw_device_id: id of the device selected by the user (TrezorClient, KeepkeyClient)
    :param parent_window: ref to a window according to which will be centered message dialogs created here
    :return: Tuple
        Ret[0]: Device id. After wiping a new device id is generated, which is returned to the caller.
        Ret[1]: True, if the user cancelled the operation. In this situation we deliberately don't raise the 'cancelled'
            exception, because in the case of changing of the device id (when wiping) we want to pass it back to
            the caller.
    """
    def wipe(ctrl):
        ctrl.dlg_config_fun(dlg_title="Confirm wiping device.", show_progress_bar=False)
        ctrl.display_msg_fun('<b>Read the messages displyed on your hardware wallet <br>'
                             'and click the confirmation button when necessary...</b>')

        if hw_type == HWType.trezor:

            from hw_intf_trezor import wipe_device
            return wipe_device(hw_device_id)

        elif hw_type == HWType.keepkey:

            from hw_intf_keepkey import wipe_device
            return wipe_device(hw_device_id)

        elif hw_type == HWType.ledger_nano_s:

            raise Exception('Not supported by Ledger Nano S.')

        else:
            raise Exception('Invalid HW type: ' + str(hw_type))

    # execute the 'wipe' inside a thread to avoid blocking UI
    return WndUtils.run_thread_dialog(wipe, (), True, center_by_window=parent_window)


def load_device_by_mnemonic(hw_type: HWType, hw_device_id: Optional[str], mnemonic_words: str,
                            pin: str, passphrase_enbled: bool, hw_label: str, passphrase: str,
                            secondary_pin: str, parent_window = None) -> Tuple[Optional[str], bool]:
    """
    Initializes hardware wallet with a mnemonic words. For security reasons use this function only on an offline
    system, that will never be connected to the Internet.
    :param hw_type: app_config.HWType
    :param hw_device_id: id of the device selected by the user (TrezorClient, KeepkeyClient); None for Ledger Nano S
    :param mnemonic_words: string of 12/18/24 mnemonic words (separeted by spaces)
    :param pin: string with a new pin
    :param passphrase_enbled: if True, hw will have passphrase enabled (Trezor/Keepkey)
    :param hw_label: label for device (Trezor/Keepkey)
    :param passphrase: passphrase to be saved in the device (Ledger Nano S)
    :param secondary_pin: PIN securing passphrase (Ledger Nano S)
    :param parent_window: ref to a window according to which will be centered message dialogs created here
    :return: Tuple
        Ret[0]: Device id. If a device is wiped before initializing with mnemonics, a new device id is generated. It's
            returned to the caller.
        Ret[1]: True, if the user cancelled the operation. In this situation we deliberately don't raise the 'cancelled'
            exception, because in the case of changing of the device id (when wiping) we want to pass it back to
            the caller.
        Ret[0] and Ret[1] are None for Ledger devices.
    """
    def load(ctrl, hw_device_id: str, mnemonic: str, pin: str, passphrase_enbled: bool, hw_label: str) -> \
            Tuple[Optional[str], bool]:

        ctrl.dlg_config_fun(dlg_title="Please confirm", show_progress_bar=False)
        ctrl.display_msg_fun('<b>Read the messages displyed on your hardware wallet <br>'
                             'and click the confirmation button when necessary...</b>')

        if hw_device_id:
            if hw_type == HWType.trezor:
                raise Exception('Feature no longer available for Trezor')
            elif hw_type == HWType.keepkey:
                from hw_intf_keepkey import load_device_by_mnemonic
                return load_device_by_mnemonic(hw_device_id, mnemonic, pin, passphrase_enbled, hw_label)
            else:
                raise Exception('Not supported by Ledger Nano S.')
        else:
            raise HWNotConnectedException()

    if hw_type == HWType.ledger_nano_s:
        import hw_intf_ledgernano
        hw_intf_ledgernano.load_device_by_mnemonic(mnemonic_words, pin, passphrase, secondary_pin)
        return hw_device_id, False
    else:
        return WndUtils.run_thread_dialog(load, (hw_device_id, mnemonic_words, pin, passphrase_enbled, hw_label),
                                          True)


def recovery_device(hw_type: HWType, hw_device_id: str, word_count: int, passphrase_enabled: bool, pin_enabled: bool,
                    hw_label: str, parent_window = None) -> Tuple[Optional[str], bool]:
    """
    :param hw_type: app_config.HWType
    :param hw_device_id: id of the device selected by the user (TrezorClient, KeepkeyClient); None for Ledger Nano S
    :param word_count: number of recovery words (12/18/24)
    :param passphrase_enbled: if True, hw will have passphrase enabled (Trezor/Keepkey)
    :param pin_enabled: if True, hw will have pin enabled (Trezor/Keepkey)
    :param hw_label: label for device (Trezor/Keepkey)
    :param parent_window: ref to a window according to which will be centered message dialogs created here
    :return: Tuple
        Ret[0]: Device id. If a device is wiped before recovering seed, a new device id is generated. It's
            returned to the caller.
        Ret[1]: True, if the user cancelled the operation. In this situation we deliberately don't raise the
            'cancelled' exception, because in the case of changing of the device id (when wiping) we want to pass
            it back to the caller function.
        Ret[0] and Ret[1] are None for Ledger devices.
    """
    def load(ctrl, hw_type: HWType, hw_device_id: str, word_count: int, passphrase_enabled: bool, pin_enabled: bool,
             hw_label: str) -> Tuple[Optional[str], bool]:

        ctrl.dlg_config_fun(dlg_title="Please confirm", show_progress_bar=False)
        ctrl.display_msg_fun('<b>Read the messages displyed on your hardware wallet <br>'
                             'and click the confirmation button when necessary...</b>')

        if hw_device_id:
            if hw_type == HWType.trezor:

                from hw_intf_trezor import recovery_device
                return recovery_device(hw_device_id, word_count, passphrase_enabled, pin_enabled, hw_label)

            elif hw_type == HWType.keepkey:

                from hw_intf_keepkey import recovery_device
                return recovery_device(hw_device_id, word_count, passphrase_enabled, pin_enabled, hw_label)

            else:
                raise Exception('Not supported by Ledger Nano S.')
        else:
            raise HWNotConnectedException()

    if hw_type == HWType.ledger_nano_s:
        raise Exception('Not supported by Ledger Nano S.')
    else:
        return WndUtils.run_thread_dialog(load, (hw_type, hw_device_id, word_count, passphrase_enabled, pin_enabled,
                                                 hw_label), True, center_by_window=parent_window)


def reset_device(hw_type: HWType, hw_device_id: str, word_count: int, passphrase_enabled: bool, pin_enabled: bool,
                 hw_label: str, parent_window = None) -> Tuple[Optional[str], bool]:
    """
    Initialize device with a newly generated words.
    :param hw_type: app_config.HWType
    :param hw_device_id: id of the device selected by the user (TrezorClient, KeepkeyClient); None for Ledger Nano S
    :param word_count: number of words (12/18/24)
    :param passphrase_enbled: if True, hw will have passphrase enabled (Trezor/Keepkey)
    :param pin_enabled: if True, hw will have pin enabled (Trezor/Keepkey)
    :param hw_label: label for device (Trezor/Keepkey)
    :param parent_window: ref to a window according to which will be centered message dialogs created here
    :return: Tuple
        Ret[0]: Device id. If a device is wiped before initializing with mnemonics, a new device id is generated. It's
            returned to the caller.
        Ret[1]: True, if the user cancelled the operation. In this situation we deliberately don't raise the
            'cancelled' exception, because in the case of changing of the device id (when wiping) we want to pass
            it back to the caller function.
        Ret[0] and Ret[1] are None for Ledger devices.
    """
    def load(ctrl, hw_type: HWType, hw_device_id: str, strength: int, passphrase_enabled: bool, pin_enabled: bool,
             hw_label: str) -> Tuple[Optional[str], bool]:

        ctrl.dlg_config_fun(dlg_title="Please confirm", show_progress_bar=False)
        ctrl.display_msg_fun('<b>Read the messages displyed on your hardware wallet <br>'
                             'and click the confirmation button when necessary...</b>')
        if hw_device_id:
            if hw_type == HWType.trezor:

                from hw_intf_trezor import reset_device
                return reset_device(hw_device_id, strength, passphrase_enabled, pin_enabled, hw_label)

            elif hw_type == HWType.keepkey:

                from hw_intf_keepkey import reset_device
                return reset_device(hw_device_id, strength, passphrase_enabled, pin_enabled, hw_label)

            else:
                raise Exception('Not supported by Ledger Nano S.')
        else:
            raise HWNotConnectedException()

    if hw_type == HWType.ledger_nano_s:
        raise Exception('Not supported by Ledger Nano S.')
    else:
        if word_count not in (12, 18, 24):
            raise Exception('Invalid word count.')
        strength = {24: 32, 18: 24, 12: 16}.get(word_count) * 8

        return WndUtils.run_thread_dialog(load, (hw_type, hw_device_id, strength, passphrase_enabled, pin_enabled,
                                                 hw_label), True, center_by_window=parent_window)

@control_hw_call
def hw_encrypt_value(hw_session: HwSessionInfo, bip32_path_n: List[int], label: str,
                     value: ByteString, ask_on_encrypt=True, ask_on_decrypt=True) -> Tuple[bytearray, bytearray]:
    """Encrypts a value with a hardware wallet.
    :param hw_session:
    :param bip32_path_n: bip32 path of the private key used for encryption
    :param label: key (in the meaning of key-value) used for encryption
    :param value: value being encrypted
    :param ask_on_encrypt: see Trezor doc
    :param ask_on_decrypt: see Trezor doc
    """

    def encrypt(ctrl, hw_session: HwSessionInfo, bip32_path_n: List[int], label: str,
                value: bytearray):
        ctrl.dlg_config_fun(dlg_title="Data encryption", show_progress_bar=False)
        ctrl.display_msg_fun(f'<b>Encrypting \'{label}\'...</b>'
                             f'<br><br>Enter the hardware wallet PIN/passphrase (if needed) to encrypt data.<br><br>'
                             f'<b>Note:</b> encryption passphrase is independent from the wallet passphrase  <br>'
                             f'and can vary for each encrypted file.')

        if hw_session.hw_type == HWType.trezor:
            from trezorlib import misc, btc
            from trezorlib import exceptions

            try:
                client = hw_session.hw_client
                data = misc.encrypt_keyvalue(client, bip32_path_n, label, value, ask_on_encrypt, ask_on_decrypt)
                pub_key = btc.get_public_node(client, bip32_path_n).node.public_key
                return data, pub_key
            except (CancelException, exceptions.Cancelled):
                raise CancelException()

        elif hw_session.hw_type == HWType.keepkey:

            client = hw_session.hw_client
            data = client.encrypt_keyvalue(bip32_path_n, label, value, ask_on_encrypt, ask_on_decrypt)
            pub_key = client.get_public_node(bip32_path_n).node.public_key
            return data, pub_key

        elif hw_session.hw_type == HWType.ledger_nano_s:

            raise Exception('Feature not available for Ledger Nano S.')

        else:
            raise Exception('Invalid HW type: ' + str(hw_session))

    if len(value) != 32:
        raise ValueError("Invalid password length (<> 32).")

    return WndUtils.run_thread_dialog(encrypt, (hw_session, bip32_path_n, label, value), True,
                                      force_close_dlg_callback=partial(cancel_hw_thread_dialog, hw_session.hw_client),
                                      show_window_delay_ms=200)


@control_hw_call
def hw_decrypt_value(hw_session: HwSessionInfo, bip32_path_n: List[int], label: str,
                     value: ByteString, ask_on_encrypt=True, ask_on_decrypt=True) -> Tuple[bytearray, bytearray]:
    """
    :param hw_session:
    :param passphrase_encoding: (for Keepkey only) it allows forcing the passphrase encoding compatible with BIP-39
        standard (NFKD), which is used by Trezor devices; by default Keepkey uses non-standard encoding (NFC).
    :param bip32_path_n: bip32 path of the private key used for encryption
    :param label: key (in the meaning of key-value) used for encryption
    :param value: encrypted value to be decrypted,
    :param ask_on_encrypt: see Trezor doc
    :param ask_on_decrypt: see Trezor doc
    """

    def decrypt(ctrl, hw_session: HwSessionInfo, bip32_path_n: List[int], label: str, value: bytearray):
        ctrl.dlg_config_fun(dlg_title="Data decryption", show_progress_bar=False)
        ctrl.display_msg_fun(f'<b>Decrypting \'{label}\'...</b><br><br>Enter the hardware wallet PIN/passphrase '
                             f'(if needed)<br> and click the confirmation button to decrypt data.')

        if hw_session.hw_type == HWType.trezor:

            from trezorlib import misc, btc
            from trezorlib import exceptions

            try:
                client = hw_session.hw_client
                data = misc.decrypt_keyvalue(client, bip32_path_n, label, value, ask_on_encrypt, ask_on_decrypt)
                pub_key = btc.get_public_node(client, bip32_path_n).node.public_key
                return data, pub_key
            except (CancelException, exceptions.Cancelled):
                raise CancelException()

        elif hw_session.hw_type == HWType.keepkey:

            client = hw_session.hw_client
            data = client.decrypt_keyvalue(bip32_path_n, label, value, ask_on_encrypt, ask_on_decrypt)
            pub_key = client.get_public_node(bip32_path_n).node.public_key
            return data, pub_key

        elif hw_session.hw_type == HWType.ledger_nano_s:

            raise Exception('Feature not available for Ledger Nano S.')

        else:
            raise Exception('Invalid HW type: ' + str(hw_session))

    if len(value) != 32:
        raise ValueError("Invalid password length (<> 32).")

    return WndUtils.run_thread_dialog(decrypt, (hw_session, bip32_path_n, label, value), True,
                                      force_close_dlg_callback=partial(cancel_hw_thread_dialog, hw_session.hw_client))


