#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
from hw_common import HardwareWalletPinException
import logging


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
            raise Exception('Not connected to Hardware Wallet')
        try:

            if main_ui.config.hw_type == 'TREZOR':

                import hw_intf_trezor as trezor
                import trezorlib.client as client
                try:
                    ret = func(*args, **kwargs)
                except client.PinException as e:
                    raise HardwareWalletPinException(e.args[1])

            elif main_ui.config.hw_type == 'KEEPKEY':

                import hw_intf_keepkey as keepkey
                import keepkeylib.client as client
                try:
                    ret = func(*args, **kwargs)
                except client.PinException as e:
                    raise HardwareWalletPinException(e.args[1])

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
    try:
        if hw_type == 'TREZOR':
            import hw_intf_trezor as trezor
            import trezorlib.client as client
            try:
                return trezor.connect_trezor(ask_for_pin_fun, ask_for_pass_fun)
            except client.PinException as e:
                raise HardwareWalletPinException(e.args[1])
        elif hw_type == 'KEEPKEY':
            import hw_intf_keepkey as keepkey
            import keepkeylib.client as client
            try:
                return keepkey.connect_keepkey(ask_for_pin_fun, ask_for_pass_fun)
            except client.PinException as e:
                raise HardwareWalletPinException(e.args[1])
        else:
            logging.error('Unsupported HW type: ' + str(hw_type))
    except:
        logging.exception('Exception occurred')
        raise


def disconnect_hw(client):
    try:
        client.clear_session()
        client.close()
    except Exception as e:
        # HW must have been disconnected before
        logging.exception('Disconnect HW error')


@control_hw_call
def hw_get_address(main_ui, address_n):
    client = main_ui.hw_client
    if client:
        return client.get_address('Dash', address_n, False)


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
    if main_ui.config.hw_type == 'TREZOR':
        import hw_intf_trezor as trezor

        return trezor.prepare_transfer_tx(main_ui, utxos_to_spend, dest_address, tx_fee)

    elif main_ui.config.hw_type == 'KEEPKEY':
        import hw_intf_keepkey as keepkey

        return keepkey.prepare_transfer_tx(main_ui, utxos_to_spend, dest_address, tx_fee)

    else:
        logging.error('Unsupported HW type: ' + str(main_ui.config.hw_type))


@control_hw_call
def sign_message(main_ui, bip32path, message):
    if main_ui.config.hw_type == 'TREZOR':
        import hw_intf_trezor as trezor

        return trezor.sign_message(main_ui, bip32path, message)

    elif main_ui.config.hw_type == 'KEEPKEY':
        import hw_intf_keepkey as keepkey

        return keepkey.sign_message(main_ui, bip32path, message)

    else:
        logging.error('Unsupported HW type: ' + str(main_ui.config.hw_type))


@control_hw_call
def change_pin(main_ui, remove=False):
    if main_ui.config.hw_type == 'TREZOR':
        import hw_intf_trezor as trezor

        return trezor.change_pin(main_ui, remove)

    elif main_ui.config.hw_type == 'KEEPKEY':
        import hw_intf_keepkey as keepkey

        return keepkey.change_pin(main_ui, remove)
    else:
        logging.error('Unsupported HW type: ' + str(main_ui.config.hw_type))


@control_hw_call
def ping(main_ui, message, button_protection, pin_protection, passphrase_protection):
    client = main_ui.hw_client
    if client:
        return client.ping(message, button_protection=button_protection, pin_protection=pin_protection,
                            passphrase_protection=passphrase_protection)

