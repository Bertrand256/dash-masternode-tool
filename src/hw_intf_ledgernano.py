from btchip.btchip import *
from btchip.btchipComm import getDongle
import logging

from dash_utils import pubkey_to_address


def connect_ledgernano():
    try:
        dongle = getDongle()
        app = btchip(dongle)
        ver = app.getFirmwareVersion()
        logging.info('Ledger Nano S connected. Firmware version: %s, specialVersion: %s, compressedKeys: %s' %
                     (str(ver.get('version')), str(ver.get('specialVersion')), ver.get('compressedKeys')))

        client = btchip(dongle)
        return client
    except Exception as e:
        raise


class MessageSignature:
    def __init__(self, address, signature):
        self.address = address
        self.signature = signature


def sign_message(main_ui, bip32path, message):
    client = main_ui.hw_client
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