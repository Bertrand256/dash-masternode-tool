#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import sqlite3
from typing import Optional, Tuple, List, ByteString, Callable, Dict
import sys
import dash_utils
from dash_utils import bip32_path_n_to_string
from hw_common import HardwareWalletPinException, HwSessionInfo
import logging
from app_defs import HWType
from wnd_utils import WndUtils


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
            raise Exception('Not connected to a hardware wallet')
        try:
            try:
                # protect against simultaneous access to the same device from different threads
                hw_session.acquire_client()

                control_trezor_keepkey_libs(hw_session.app_config.hw_type)
                if hw_session.app_config.hw_type == HWType.trezor:

                    import hw_intf_trezor as trezor
                    import trezorlib.client as client
                    try:
                        ret = func(*args, **kwargs)
                    except client.PinException as e:
                        raise HardwareWalletPinException(e.args[1])

                elif hw_session.app_config.hw_type == HWType.keepkey:

                    import hw_intf_keepkey as keepkey
                    import keepkeylib.client as client
                    try:
                        ret = func(*args, **kwargs)
                    except client.PinException as e:
                        raise HardwareWalletPinException(e.args[1])

                elif hw_session.app_config.hw_type == HWType.ledger_nano_s:

                    ret = func(*args, **kwargs)

                else:
                    raise Exception('Uknown hardware wallet type: ' + hw_session.app_config.hw_type)
            finally:
                hw_session.release_client()

        except OSError as e:
            logging.exception('Exception calling %s function' % func.__name__)
            logging.info('Disconnecting HW after OSError occurred')
            hw_session.hw_disconnect()
            raise

        except HardwareWalletPinException:
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


def connect_hw(hw_session: Optional[HwSessionInfo], hw_type: HWType, device_id: Optional[str] = 'NFC',
               passphrase_encoding: Optional[str] = None):
    """
    Initializes connection with a hardware wallet.
    :param hw_type: symbol of the hardware wallet type
    :param passphrase_encoding: (for Keepkey only) it allows forcing the passphrase encoding compatible with BIP-39
        standard (NFKD), which is used by Trezor devices; by default Keepkey uses non-standard encoding (NFC).
    :return:
    """
    def get_session_info_trezor(cli, hw_session: HwSessionInfo):
        path = dash_utils.get_default_bip32_base_path(hw_session.app_config.dash_network)
        path_n = dash_utils.bip32_path_string_to_n(path)
        pub = cli.get_public_node(path_n).node.public_key
        hw_session.set_base_info(path, pub)

    control_trezor_keepkey_libs(hw_type)
    if hw_type == HWType.trezor:
        import hw_intf_trezor as trezor
        import trezorlib.client as client
        try:
            cli = trezor.connect_trezor(device_id=device_id)
            if cli and hw_session:
                try:
                    get_session_info_trezor(cli, hw_session)
                except Exception:
                    # in the case of error close the session
                    disconnect_hw(cli)
                    raise
            return cli
        except client.PinException as e:
            raise HardwareWalletPinException(e.args[1])

    elif hw_type == HWType.keepkey:
        import hw_intf_keepkey as keepkey
        import keepkeylib.client as client
        try:
            cli = keepkey.connect_keepkey(passphrase_encoding=passphrase_encoding, device_id=device_id)
            if cli and hw_session:
                try:
                    get_session_info_trezor(cli, hw_session)
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
            except Exception:
                # in the case of error close the session
                disconnect_hw(cli)
                raise
        return cli

    else:
        raise Exception('Invalid HW type: ' + str(hw_type))


def get_hw_type(hw_client):
    """
    Return hardware wallet type (HWType) based on reference to a hw client.
    """
    if hw_client:
        t = type(hw_client).__name__

        if t.lower().find('trezor') >= 0:
            return HWType.trezor
        elif t.lower().find('keepkey') >= 0:
            return HWType.keepkey
        elif t.lower().find('btchip') >= 0:
            return HWType.ledger_nano_s
        else:
            raise Exception('Unknown hardware wallet type')
    else:
        raise Exception('Hardware wallet not connected')


def disconnect_hw(hw_client):
    try:
        hw_type = get_hw_type(hw_client)
        if hw_type in (HWType.trezor, HWType.keepkey):
            hw_client.cancel()
            hw_client.close()
        elif hw_type == HWType.ledger_nano_s:
            hw_client.dongle.close()
    except Exception as e:
        # probably already disconnected
        logging.exception('Disconnect HW error')


def cancel_hw_operation(hw_client):
    hw_type = get_hw_type(hw_client)
    if hw_type in (HWType.trezor, HWType.keepkey):
        hw_client.cancel()


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
def prepare_transfer_tx(hw_session: HwSessionInfo, utxos_to_spend, dest_addresses: List[Tuple[str, int, str]], tx_fee,
                        rawtransactions):
    """
    Creates a signed transaction.
    :param main_ui: Main window for configuration data
    :param utxos_to_spend: list of utxos to send
    :param dest_addresses: destination addresses. Fields: 0: dest Dash address. 1: the output value in satoshis,
        2: the bip32 path of the address if the output is the change address or None otherwise
    :param tx_fee: transaction fee
    :param rawtransactions: dict mapping txid to rawtransaction
    :return: tuple (serialized tx, total transaction amount in satoshis)
    """
    def prepare(ctrl):
        ctrl.dlg_config_fun(dlg_title="Confirm transaction signing.", show_progress_bar=False)
        ctrl.display_msg_fun('<b>Click the confirmation button on your hardware wallet<br>'
                             'and wait for the transaction to be signed...</b>')

        if hw_session.app_config.hw_type == HWType.trezor:
            import hw_intf_trezor as trezor

            return trezor.prepare_transfer_tx(hw_session, utxos_to_spend, dest_addresses, tx_fee)

        elif hw_session.app_config.hw_type == HWType.keepkey:
            import hw_intf_keepkey as keepkey

            return keepkey.prepare_transfer_tx(hw_session, utxos_to_spend, dest_addresses, tx_fee)

        elif hw_session.app_config.hw_type == HWType.ledger_nano_s:
            import hw_intf_ledgernano as ledger

            return ledger.prepare_transfer_tx(hw_session, utxos_to_spend, dest_addresses, tx_fee, rawtransactions)

        else:
            logging.error('Invalid HW type: ' + str(hw_session.app_config.hw_type))

    # execute the 'prepare' function, but due to the fact that the call blocks the UI until the user clicks the HW
    # button, it's done inside a thread within a dialog that shows an appropriate message to the user
    sig = WndUtils.run_thread_dialog(prepare, (), True)
    return sig


@control_hw_call
def hw_sign_message(hw_session: HwSessionInfo, bip32path, message, display_label: str = None):
    def sign(ctrl, display_label):
        ctrl.dlg_config_fun(dlg_title="Confirm message signing.", show_progress_bar=False)
        if display_label:
            ctrl.display_msg_fun(display_label)
        else:
            ctrl.display_msg_fun('<b>Click the confirmation button on your hardware wallet...</b>')

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
    sig = WndUtils.run_thread_dialog(sign, (display_label,), True)
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

        raise Exception('Ledger Nano S not supported yet.')

    else:
        logging.error('Invalid HW type: ' + str(hw_session.app_config.hw_type))


@control_hw_call
def ping(hw_session: HwSessionInfo, message, button_protection, pin_protection, passphrase_protection):
    client = hw_session.hw_client
    if client:
        return client.ping(message, button_protection=button_protection, pin_protection=pin_protection,
                            passphrase_protection=passphrase_protection)


@control_hw_call
def get_address(hw_session: HwSessionInfo, bip32_path):
    client = hw_session.hw_client
    if client:
        if isinstance(bip32_path, str):
            bip32_path.strip()
            if bip32_path.lower().find('m/') >= 0:
                # removing m/ prefix because of keepkey library
                bip32_path = bip32_path[2:]

        if hw_session.app_config.hw_type in (HWType.trezor, HWType.keepkey):
            if isinstance(bip32_path, str):
                # trezor/keepkey require bip32 path argument as an array of integers
                bip32_path = client.expand_path(bip32_path)

            return client.get_address(hw_session.app_config.hw_coin_name, bip32_path, False)

        elif hw_session.app_config.hw_type == HWType.ledger_nano_s:
            import hw_intf_ledgernano as ledger

            if isinstance(bip32_path, list):
                # ledger requires bip32 path argument as a string
                bip32_path = bip32_path_n_to_string(bip32_path)

            adr_pubkey = ledger.get_address_and_pubkey(client, bip32_path)
            return adr_pubkey.get('address')
        else:
            raise Exception('Unknown hwardware wallet type: ' + hw_session.app_config.hw_type)
    else:
        raise Exception('HW client not open.')


@control_hw_call
def get_address_and_pubkey(hw_session: HwSessionInfo, bip32_path):
    client = hw_session.hw_client
    if client:
        bip32_path.strip()
        if bip32_path.lower().find('m/') >= 0:
            # removing m/ prefix because of keepkey library
            bip32_path = bip32_path[2:]

        if hw_session.app_config.hw_type in (HWType.trezor, HWType.keepkey):
            if isinstance(bip32_path, str):
                # trezor/keepkey require bip32 path argument as an array of integers
                bip32_path = client.expand_path(bip32_path)

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
            raise Exception('Unknown hwardware wallet type: ' + hw_session.app_config.hw_type)


def get_address_ext(hw_session: HwSessionInfo,
                    bip32_path_n: List[int],
                    db_cursor: sqlite3.Cursor,
                    encrypt_fun: Callable,
                    decrypt_fun: Callable):
    """
    Reads address of a specific bip32 path from hardware wallet, using db cache to speed-up operation
    by avoiding utilization the hardware wallet device as quite slow for this operation.
    :param hw_session:
    :param bip32_path_n:
    :param db_cursor:
    :param encrypt_fun:
    :param decrypt_fun:
    :return:
    """
    global hd_tree_db_map, bip32_address_map

    def get_hd_tree_db_id(tree_ident: str):
        db_id = hd_tree_db_map.get(tree_ident)
        if not db_id:
            db_cursor.execute('select id from ADDRESS_HD_TREE where ident=?', (tree_ident,))
            row = db_cursor.fetchone()
            if not row:
                db_cursor.execute('insert into ADDRESS_HD_TREE(ident) values(?)', (tree_ident,))
                db_id = db_cursor.lastrowid
                hd_tree_db_map[tree_ident] = db_id
            else:
                db_id = row[0]
        return db_id

    try:
        map_dict = bip32_address_map.get(hw_session.hd_tree_ident)
        if not map_dict:
            map_dict = {}
            bip32_address_map[hw_session.hd_tree_ident] = map_dict

        path_str = dash_utils.bip32_path_n_to_string(bip32_path_n)
        address = map_dict.get(path_str)
        db_id = None
        if not address:
            # look for address in db cache
            hd_tree_id = get_hd_tree_db_id(hw_session.hd_tree_ident)
            db_cursor.execute('select id, address from ADDRESS where tree_id=? and path=?', (hd_tree_id, path_str))
            row = db_cursor.fetchone()
            if row:
                db_id, address = row
                # address is encrypted; try to decrypt it
                try:
                    address = decrypt_fun(address).decode('ascii')
                    if not dash_utils.validate_address(address, hw_session.app_config.dash_network):
                        address = None
                except Exception:
                    address = None

            if not address:
                address = get_address(hw_session, bip32_path_n)
                map_dict[path_str] = address
                address_encrypted = encrypt_fun(bytes(address, 'ascii'))
                if db_id:
                    # update db record: it was encrypted with no longer valid encryption key
                    db_cursor.execute('update ADDRESS set address=? where id=?', (address_encrypted, db_id))
                else:
                    db_cursor.execute('insert into ADDRESS(tree_id, path, address) values(?,?,?)',
                                      (hd_tree_id, path_str, address_encrypted))
        return address
    except Exception as e:
        logging.exception('Unhandled exception occurred')
        return get_address(hw_session, bip32_path_n)


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

                from hw_intf_trezor import load_device_by_mnemonic
                return load_device_by_mnemonic(hw_device_id, mnemonic, pin, passphrase_enbled, hw_label)

            elif hw_type == HWType.keepkey:

                from hw_intf_keepkey import load_device_by_mnemonic
                return load_device_by_mnemonic(hw_device_id, mnemonic, pin, passphrase_enbled, hw_label)

            else:
                raise Exception('Not supported by Ledger Nano S.')
        else:
            raise Exception('Not connected to a hardware wallet')

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
            raise Exception('Not connected to a hardware wallet')

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
            raise Exception('Not connected to a hardware wallet')

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

        if hw_session.hw_type in (HWType.trezor, HWType.keepkey):

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

    return WndUtils.run_thread_dialog(encrypt, (hw_session, bip32_path_n, label, value), True)


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

        if hw_session.hw_type in (HWType.trezor, HWType.keepkey):

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

    return WndUtils.run_thread_dialog(decrypt, (hw_session, bip32_path_n, label, value), True)


