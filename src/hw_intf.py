#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import threading
from typing import Optional, Tuple
import sys
from PyQt5.QtWidgets import QWidget
from dash_utils import bip32_path_n_to_string
from hw_common import HardwareWalletPinException
import logging
from app_config import HWType
from wnd_utils import WndUtils


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
        main_ui = args[0]
        client = main_ui.hw_client
        if not client:
            client = main_ui.connectHardwareWallet()
        if not client:
            raise Exception('Not connected to a hardware wallet')
        try:
            control_trezor_keepkey_libs(main_ui.config.hw_type)
            if main_ui.config.hw_type == HWType.trezor:

                import hw_intf_trezor as trezor
                import trezorlib.client as client
                try:
                    ret = func(*args, **kwargs)
                except client.PinException as e:
                    raise HardwareWalletPinException(e.args[1])

            elif main_ui.config.hw_type == HWType.keepkey:

                import hw_intf_keepkey as keepkey
                import keepkeylib.client as client
                try:
                    ret = func(*args, **kwargs)
                except client.PinException as e:
                    raise HardwareWalletPinException(e.args[1])

            elif main_ui.config.hw_type == HWType.ledger_nano_s:

                ret = func(*args, **kwargs)

            else:
                raise Exception('Uknown hardware wallet type: ' + main_ui.config.hw_type)

        except OSError as e:
            logging.exception('Exception calling %s function' % func.__name__)
            logging.info('Disconnecting HW after OSError occurred')
            main_ui.disconnectHardwareWallet()
            raise

        except HardwareWalletPinException:
            raise

        except Exception as e:
            logging.exception('Exception calling %s function' % func.__name__)
            raise

        return ret

    return catch_hw_client


def connect_hw(hw_type: str, passphrase_encoding: str):
    """
    Initializes connection with a hardware wallet.
    :param hw_type: symbol of the hardware wallet type
    :param passphrase_encoding: (for Keepkey only) it allows forcing the passphrase encoding compatible with BIP-39
        standard (NFKD), which is used by Trezor devices; by default Keepkey uses non-standard encoding (NFC).
    :return:
    """
    control_trezor_keepkey_libs(hw_type)
    if hw_type == HWType.trezor:
        import hw_intf_trezor as trezor
        import trezorlib.client as client
        try:
            return trezor.connect_trezor()
        except client.PinException as e:
            raise HardwareWalletPinException(e.args[1])

    elif hw_type == HWType.keepkey:
        import hw_intf_keepkey as keepkey
        import keepkeylib.client as client
        try:
            return keepkey.connect_keepkey(passphrase_encoding=passphrase_encoding, device_id=None)
        except client.PinException as e:
            raise HardwareWalletPinException(e.args[1])

    elif hw_type == HWType.ledger_nano_s:
        import hw_intf_ledgernano as ledger
        return ledger.connect_ledgernano()

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
            hw_client.clear_session()
            hw_client.close()
        elif hw_type == HWType.ledger_nano_s:
            hw_client.dongle.close()
    except Exception as e:
        # probably already disconnected
        logging.exception('Disconnect HW error')


def get_hw_label(main_ui, hw_client):
    hw_type = get_hw_type(hw_client)
    if hw_type in (HWType.trezor, HWType.keepkey):
        return hw_client.features.label
    elif hw_type == HWType.ledger_nano_s:
        return 'Ledger Nano S'


@control_hw_call
def get_hw_firmware_version(main_ui, hw_client):
    hw_type = get_hw_type(hw_client)
    if hw_type in (HWType.trezor, HWType.keepkey):

        return str(hw_client.features.major_version) + '.' + str(hw_client.features.minor_version) + '.' + \
                   str(hw_client.features.patch_version)

    elif hw_type == HWType.ledger_nano_s:

        return hw_client.getFirmwareVersion().get('version')


@control_hw_call
def prepare_transfer_tx(main_ui, utxos_to_spend, dest_address, tx_fee, rawtransactions):
    """
    Creates a signed transaction.
    :param main_ui: Main window for configuration data
    :param utxos_to_spend: list of utxos to send
    :param dest_address: destination (Dash) address
    :param tx_fee: transaction fee
    :param rawtransactions: dict mapping txid to rawtransaction
    :return: tuple (serialized tx, total transaction amount in satoshis)
    """
    def prepare(ctrl):
        ctrl.dlg_config_fun(dlg_title="Confirm message signing.", show_progress_bar=False)
        ctrl.display_msg_fun('<b>Click the confirmation button on your hardware wallet...</b>')

        if main_ui.config.hw_type == HWType.trezor:
            import hw_intf_trezor as trezor

            return trezor.prepare_transfer_tx(main_ui, utxos_to_spend, dest_address, tx_fee)

        elif main_ui.config.hw_type == HWType.keepkey:
            import hw_intf_keepkey as keepkey

            return keepkey.prepare_transfer_tx(main_ui, utxos_to_spend, dest_address, tx_fee)

        elif main_ui.config.hw_type == HWType.ledger_nano_s:
            import hw_intf_ledgernano as ledger

            return ledger.prepare_transfer_tx(main_ui, utxos_to_spend, dest_address, tx_fee, rawtransactions)

        else:
            logging.error('Invalid HW type: ' + str(main_ui.config.hw_type))

    # execute the 'prepare' function, but due to the fact that the call blocks the UI until the user clicks the HW
    # button, it's done inside a thread within a dialog that shows an appropriate message to the user
    sig = main_ui.threadFunctionDialog(prepare, (), True, center_by_window=main_ui)
    return sig


@control_hw_call
def sign_message(main_ui, bip32path, message):
    def sign(ctrl):
        ctrl.dlg_config_fun(dlg_title="Confirm message signing.", show_progress_bar=False)
        ctrl.display_msg_fun('<b>Click the confirmation button on your hardware wallet...</b>')

        if main_ui.config.hw_type == HWType.trezor:
            import hw_intf_trezor as trezor

            return trezor.sign_message(main_ui, bip32path, message)

        elif main_ui.config.hw_type == HWType.keepkey:
            import hw_intf_keepkey as keepkey

            return keepkey.sign_message(main_ui, bip32path, message)

        elif main_ui.config.hw_type == HWType.ledger_nano_s:
            import hw_intf_ledgernano as ledger

            return ledger.sign_message(main_ui, bip32path, message)
        else:
            logging.error('Invalid HW type: ' + str(main_ui.config.hw_type))

    # execute the 'sign' function, but due to the fact that the call blocks the UI until the user clicks the HW
    # button, it's done inside a thread within a dialog that shows an appropriate message to the user
    sig = main_ui.threadFunctionDialog(sign, (), True, center_by_window=main_ui)
    return sig


@control_hw_call
def change_pin(main_ui, remove=False):
    if main_ui.config.hw_type == HWType.trezor:
        import hw_intf_trezor as trezor

        return trezor.change_pin(main_ui, remove)

    elif main_ui.config.hw_type == HWType.keepkey:
        import hw_intf_keepkey as keepkey

        return keepkey.change_pin(main_ui, remove)

    elif main_ui.config.hw_type == HWType.ledger_nano_s:

        raise Exception('Ledger Nano S not supported yet.')

    else:
        logging.error('Invalid HW type: ' + str(main_ui.config.hw_type))


@control_hw_call
def ping(main_ui, message, button_protection, pin_protection, passphrase_protection):
    client = main_ui.hw_client
    if client:
        return client.ping(message, button_protection=button_protection, pin_protection=pin_protection,
                            passphrase_protection=passphrase_protection)


@control_hw_call
def get_address(main_ui, bip32_path):
    client = main_ui.hw_client
    if client:
        if isinstance(bip32_path, str):
            bip32_path.strip()
            if bip32_path.lower().find('m/') >= 0:
                # removing m/ prefix because of keepkey library
                bip32_path = bip32_path[2:]

        if main_ui.config.hw_type in (HWType.trezor, HWType.keepkey):
            if isinstance(bip32_path, str):
                # trezor/keepkey require bip32 path argument as an array of integers
                bip32_path = client.expand_path(bip32_path)

            return client.get_address('Dash', bip32_path, False)

        elif main_ui.config.hw_type == HWType.ledger_nano_s:
            import hw_intf_ledgernano as ledger

            if isinstance(bip32_path, list):
                # ledger requires bip32 path argument as a string
                bip32_path = bip32_path_n_to_string(bip32_path)

            adr_pubkey = ledger.get_address_and_pubkey(client, bip32_path)
            return adr_pubkey.get('address')
        else:
            raise Exception('Unknown hwardware wallet type: ' + main_ui.config.hw_type)
    else:
        raise Exception('HW client not open.')


@control_hw_call
def get_address_and_pubkey(main_ui, bip32_path):
    client = main_ui.hw_client
    if client:
        bip32_path.strip()
        if bip32_path.lower().find('m/') >= 0:
            # removing m/ prefix because of keepkey library
            bip32_path = bip32_path[2:]

        if main_ui.config.hw_type in (HWType.trezor, HWType.keepkey):
            if isinstance(bip32_path, str):
                # trezor/keepkey require bip32 path argument as an array of integers
                bip32_path = client.expand_path(bip32_path)

            return {
                'address': client.get_address('Dash', bip32_path, False),
                'publicKey': client.get_public_node(bip32_path).node.public_key
            }

        elif main_ui.config.hw_type == HWType.ledger_nano_s:
            import hw_intf_ledgernano as ledger

            if isinstance(bip32_path, list):
                # ledger requires bip32 path argument as a string
                bip32_path = bip32_path_n_to_string(bip32_path)

            return ledger.get_address_and_pubkey(client, bip32_path)
        else:
            raise Exception('Unknown hwardware wallet type: ' + main_ui.config.hw_type)


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
    return WndUtils.threadFunctionDialog(wipe, (), True, center_by_window=parent_window)


@control_hw_call
def get_entropy(main_ui, len_bytes):
    def entropy(ctrl, len_bytes):
        ctrl.dlg_config_fun(dlg_title="Please confirm", show_progress_bar=False)
        ctrl.display_msg_fun('<b>Read the messages displyed on your hardware wallet <br>'
                             'and click the confirmation button when necessary...</b>')

        client = main_ui.hw_client
        if client:
            if main_ui.config.hw_type == HWType.trezor:

                from hw_intf_trezor import get_entropy
                return get_entropy(client, len_bytes)

            elif main_ui.config.hw_type == HWType.keepkey:

                from hw_intf_keepkey import get_entropy
                return get_entropy(client, len_bytes)

            elif main_ui.config.hw_type == HWType.ledger_nano_s:
                raise Exception('Not supported by Ledger Nano S.')
            else:
                raise Exception('Invalid HW type: ' + str(main_ui.config.hw_type))
        else:
            raise Exception('Not connected to a hardware wallet')

    # execute the 'entropy' inside a thread to avoid blocking UI
    return main_ui.threadFunctionDialog(entropy, (len_bytes,), True, center_by_window=main_ui)


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
        return WndUtils.threadFunctionDialog(load, (hw_device_id, mnemonic_words, pin, passphrase_enbled, hw_label), True)


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
        return WndUtils.threadFunctionDialog(load, (hw_type, hw_device_id, word_count, passphrase_enabled, pin_enabled,
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

        return WndUtils.threadFunctionDialog(load, (hw_type, hw_device_id, strength, passphrase_enabled, pin_enabled,
                                                    hw_label), True, center_by_window=parent_window)
