#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
from dash_utils import bip32_path_n_to_string
from hw_common import HardwareWalletPinException
import logging
from app_config import HWType


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
            if not main_ui.connectHardwareWallet():
                return
        if not client:
            raise Exception('Not connected to Hardware Wallet')
        try:

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


def connect_hw(hw_type, ask_for_pin_fun, ask_for_pass_fun):
    if hw_type == HWType.trezor:
        import hw_intf_trezor as trezor
        import trezorlib.client as client
        try:
            return trezor.connect_trezor(ask_for_pin_fun, ask_for_pass_fun)
        except client.PinException as e:
            raise HardwareWalletPinException(e.args[1])

    elif hw_type == HWType.keepkey:
        import hw_intf_keepkey as keepkey
        import keepkeylib.client as client
        try:
            return keepkey.connect_keepkey(ask_for_pin_fun, ask_for_pass_fun)
        except client.PinException as e:
            raise HardwareWalletPinException(e.args[1])

    elif hw_type == HWType.ledger_nano_s:
        import hw_intf_ledgernano as ledger
        return ledger.connect_ledgernano()

    else:
        raise Exception('Unsupported HW type: ' + str(hw_type))


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


@control_hw_call
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
def prepare_transfer_tx(main_ui, utxos_to_spend, dest_address, tx_fee):
    """
    Creates a signed transaction.
    :param main_ui: Main window for configuration data
    :param utxos_to_spend: list of utxos to send
    :param dest_address: destination (Dash) address
    :param tx_fee: transaction fee
    :return: tuple (serialized tx, total transaction amount in satoshis)
    """
    if main_ui.config.hw_type == HWType.trezor:
        import hw_intf_trezor as trezor

        return trezor.prepare_transfer_tx(main_ui, utxos_to_spend, dest_address, tx_fee)

    elif main_ui.config.hw_type == HWType.keepkey:
        import hw_intf_keepkey as keepkey

        return keepkey.prepare_transfer_tx(main_ui, utxos_to_spend, dest_address, tx_fee)

    elif main_ui.config.hw_type == HWType.ledger_nano_s:
        raise Exception('Ledger Nano S not supported yet.')
    else:
        logging.error('Unsupported HW type: ' + str(main_ui.config.hw_type))


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
            logging.error('Unsupported HW type: ' + str(main_ui.config.hw_type))

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
        logging.error('Unsupported HW type: ' + str(main_ui.config.hw_type))


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