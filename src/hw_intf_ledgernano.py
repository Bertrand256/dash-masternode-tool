from btchip.btchip import *
from btchip.btchipComm import getDongle
import logging
from btchip.btchipUtils import compress_public_key
from hw_common import HardwareWalletCancelException
from wnd_utils import WndUtils
from PyQt5.QtWidgets import QMessageBox


def process_ledger_exceptions(func):
    """
    Catch exceptions for known user errors and expand the exception message with some suggestions.
    :param func: function decorated.
    """
    def process_ledger_exceptions_int(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BTChipException as e:
            logging.exception('Error communicating with Ledger hardware wallet.')
            if (e.sw == 0x6d00):
                e.message += '\n\nMake sure the Dash app is running on your Ledger device.'
            elif (e.sw == 0x6982):
                e.message += '\n\nMake sure you have entered the PIN on your Ledger device.'
            raise
    return process_ledger_exceptions_int


@process_ledger_exceptions
def connect_ledgernano():
    dongle = getDongle()
    app = btchip(dongle)
    try:
        ver = app.getFirmwareVersion()
        logging.info('Ledger Nano S connected. Firmware version: %s, specialVersion: %s, compressedKeys: %s' %
                     (str(ver.get('version')), str(ver.get('specialVersion')), ver.get('compressedKeys')))

        client = btchip(dongle)
        return client
    except:
        dongle.close()
        raise


class MessageSignature:
    def __init__(self, address, signature):
        self.address = address
        self.signature = signature


@process_ledger_exceptions
def sign_message(main_ui, bip32path, message):
    client = main_ui.hw_client
    # Ledger doesn't accept characters other that ascii printable:
    # https://ledgerhq.github.io/btchip-doc/bitcoin-technical.html#_sign_message
    message = message.encode('ascii', 'ignore')

    ok = False
    for i in range(1,4):
        info = client.signMessagePrepare(bip32path, message)
        if info['confirmationNeeded'] and  info['confirmationType'] == 34:
            if i == 1 or \
                WndUtils.queryDlg('Another application (such as Ledger Wallet Bitcoin app) has probably taken over '
                     'the communication with the Ledger device.'
                     '\n\nTo continue, close that application and click the <b>Retry</b> button.'
                     '\nTo cancel, click the <b>Abort</b> button',
                 buttons=QMessageBox.Retry | QMessageBox.Abort,
                 default_button=QMessageBox.Retry, icon=QMessageBox.Warning) == QMessageBox.Retry:

                # we need to reconnect the device; first, we'll try to reconnect to HW without closing the intefering
                # application; it it doesn't help we'll display a message requesting the user to close the app
                main_ui.disconnectHardwareWallet()
                if main_ui.connectHardwareWallet():
                    client = main_ui.hw_client
                else:
                    raise Exception('Hardware wallet reconnect error.')
            else:
                break
        else:
            ok = True
            break

    if not ok:
        raise HardwareWalletCancelException('Cancelled')

    try:
        signature = client.signMessageSign()
    except Exception as e:
        logging.exception('Exception while signing message with Ledger Nano S')
        raise Exception('Exception while signing message with Ledger Nano S. Details: ' + str(e))

    try:
        pubkey = client.getWalletPublicKey(bip32path)
    except Exception as e:
        logging.exception('Could not get public key for BIP32 path on Ledger Nano S')
        raise Exception('Could not get public key for BIP32 path on Ledger Nano S. Details: ' + str(e))

    if len(signature) > 4:
        r_length = signature[3]
        r = signature[4: 4 + r_length]
        if len(signature) > 4 + r_length + 1:
            s_length = signature[4 + r_length + 1]
            if len(signature) > 4 + r_length + 2:
                s = signature[4 + r_length + 2:]
                if r_length == 33:
                    r = r[1:]
                if s_length == 33:
                    s = s[1:]
            else:
                logging.error('client.signMessageSign() returned invalid response (code 3): ' + signature.hex())
                raise Exception('Invalid signature returned (code 3).')
        else:
            logging.error('client.signMessageSign() returned invalid response (code 2): ' + signature.hex())
            raise Exception('Invalid signature returned (code 2).')
    else:
        logging.error('client.signMessageSign() returned invalid response (code 1): ' + signature.hex())
        raise Exception('Invalid signature returned (code 1).')

    return MessageSignature(
        pubkey.get('address').decode('ascii'),
        bytes(chr(27 + 4 + (signature[0] & 0x01)), "utf-8") + r + s
    )


@process_ledger_exceptions
def get_address_and_pubkey(client, bip32_path):
    bip32_path.strip()
    if bip32_path.lower().find('m/') >= 0:
        bip32_path = bip32_path[2:]

    nodedata = client.getWalletPublicKey(bip32_path)

    return {
        'address': nodedata.get('address').decode('utf-8'),
        'publicKey': compress_public_key(nodedata.get('publicKey'))
    }
