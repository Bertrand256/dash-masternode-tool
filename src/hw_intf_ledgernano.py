from btchip.btchip import *
from btchip.btchipComm import getDongle
import logging
from btchip.btchipUtils import compress_public_key


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
    # Ledger doesn'n accept characters other that ascii printable:
    # https://ledgerhq.github.io/btchip-doc/bitcoin-technical.html#_sign_message
    message = message.encode('ascii', 'ignore')
    info = client.signMessagePrepare(bip32path, message)
    signature = client.signMessageSign()
    pubkey = client.getWalletPublicKey(bip32path)

    rLength = signature[3]
    r = signature[4: 4 + rLength]
    sLength = signature[4 + rLength + 1]
    s = signature[4 + rLength + 2:]
    if rLength == 33:
        r = r[1:]
    if sLength == 33:
        s = s[1:]

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
