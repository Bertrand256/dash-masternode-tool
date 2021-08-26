import logging

from bitcoin import compress, bin_hash160
from btchip.btchip import *
from btchip.btchipComm import getDongle
from btchip.btchipUtils import compress_public_key
from typing import List

import dash_utils
from common import CancelException
from hw_common import clean_bip32_path, HwSessionInfo
import wallet_common
from wnd_utils import WndUtils
from dash_utils import *
from PyQt5.QtWidgets import QMessageBox
import unicodedata
from bip32utils import Base58
from dash_tx import DashTxType, serialize_cbTx, serialize_Lelantus


class btchip_dmt(btchip):
    def __init__(self, dongle):
        btchip.__init__(self, dongle)


    def getTrustedInput(self, transaction, index):
        result = {}
        # Header
        apdu = [self.BTCHIP_CLA, self.BTCHIP_INS_GET_TRUSTED_INPUT, 0x00, 0x00]
        params = bytearray.fromhex("%.8x" % (index))
        params.extend(transaction.version)
        writeVarint(len(transaction.inputs), params)
        apdu.append(len(params))
        apdu.extend(params)
        self.dongle.exchange(bytearray(apdu))
        # Each input
        for trinput in transaction.inputs:
            apdu = [self.BTCHIP_CLA, self.BTCHIP_INS_GET_TRUSTED_INPUT, 0x80, 0x00]
            params = bytearray(trinput.prevOut)
            writeVarint(len(trinput.script), params)
            apdu.append(len(params))
            apdu.extend(params)
            self.dongle.exchange(bytearray(apdu))
            offset = 0
            while True:
                blockLength = 251
                if ((offset + blockLength) < len(trinput.script)):
                    dataLength = blockLength
                else:
                    dataLength = len(trinput.script) - offset
                params = bytearray(trinput.script[offset: offset + dataLength])
                if ((offset + dataLength) == len(trinput.script)):
                    params.extend(trinput.sequence)
                apdu = [self.BTCHIP_CLA, self.BTCHIP_INS_GET_TRUSTED_INPUT, 0x80, 0x00, len(params)]
                apdu.extend(params)
                self.dongle.exchange(bytearray(apdu))
                offset += dataLength
                if (offset >= len(trinput.script)):
                    break
        # Number of outputs
        apdu = [self.BTCHIP_CLA, self.BTCHIP_INS_GET_TRUSTED_INPUT, 0x80, 0x00]
        params = []
        writeVarint(len(transaction.outputs), params)
        apdu.append(len(params))
        apdu.extend(params)
        self.dongle.exchange(bytearray(apdu))
        # Each output
        indexOutput = 0
        for troutput in transaction.outputs:
            apdu = [self.BTCHIP_CLA, self.BTCHIP_INS_GET_TRUSTED_INPUT, 0x80, 0x00]
            params = bytearray(troutput.amount)
            writeVarint(len(troutput.script), params)
            apdu.append(len(params))
            apdu.extend(params)
            self.dongle.exchange(bytearray(apdu))
            offset = 0
            while (offset < len(troutput.script)):
                blockLength = 255
                if ((offset + blockLength) < len(troutput.script)):
                    dataLength = blockLength
                else:
                    dataLength = len(troutput.script) - offset
                apdu = [self.BTCHIP_CLA, self.BTCHIP_INS_GET_TRUSTED_INPUT, 0x80, 0x00, dataLength]
                apdu.extend(troutput.script[offset: offset + dataLength])
                self.dongle.exchange(bytearray(apdu))
                offset += dataLength

        #Sending the lockTime and the extraPayload
        blockLength = 255
        buffer = []
        writeVarint(len(transaction.extra_data), buffer)
        offset = blockLength - len(transaction.lockTime) - len(buffer)
        apdu = [self.BTCHIP_CLA, self.BTCHIP_INS_GET_TRUSTED_INPUT, 0x80, 0x00, blockLength]
        apdu.extend(transaction.lockTime)
        apdu.extend(buffer)
        if offset > len(transaction.extra_data):
            offset = len(transaction.extra_data)
        apdu.extend(transaction.extra_data[0: offset])
        response = self.dongle.exchange(bytearray(apdu))
        while (offset < len(transaction.extra_data)):
            blockLength = 255
            if ((offset + blockLength) < len(transaction.extra_data)):
                dataLength = blockLength
            else:
                dataLength = len(transaction.extra_data) - offset
            apdu = [self.BTCHIP_CLA, self.BTCHIP_INS_GET_TRUSTED_INPUT, 0x80, 0x00, dataLength]
            apdu.extend(transaction.extra_data[offset: offset + dataLength])
            response = self.dongle.exchange(bytearray(apdu))
            offset += dataLength

        result['trustedInput'] = True
        result['value'] = response
        return result


def process_ledger_exceptions(func):
    """
    Catch exceptions for known user errors and expand the exception message with some suggestions.
    :param func: function decorated.
    """
    def process_ledger_exceptions_int(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BTChipException as e:
            logging.exception('Error while communicating with Ledger hardware wallet.')
            if (e.sw in (0x6d00, 0x6700)):
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

        client = btchip_dmt(dongle)
        return client
    except:
        dongle.close()
        raise


class MessageSignature:
    def __init__(self, address, signature):
        self.address = address
        self.signature = signature


@process_ledger_exceptions
def sign_message(hw_session: HwSessionInfo, bip32_path, message):

    client = hw_session.hw_client
    # Ledger doesn't accept characters other that ascii printable:
    # https://ledgerhq.github.io/btchip-doc/bitcoin-technical.html#_sign_message
    message = message.encode('ascii', 'ignore')
    bip32_path = clean_bip32_path(bip32_path)

    ok = False
    for i in range(1,4):
        info = client.signMessagePrepare(bip32_path, message)
        if info['confirmationNeeded'] and info['confirmationType'] == 34:
            if i == 1 or \
                WndUtils.queryDlg('Another application (such as Ledger Wallet Bitcoin app) has probably taken over '
                     'the communication with the Ledger device.'
                     '\n\nTo continue, close that application and click the <b>Retry</b> button.'
                     '\nTo cancel, click the <b>Abort</b> button',
                 buttons=QMessageBox.Retry | QMessageBox.Abort,
                 default_button=QMessageBox.Retry, icon=QMessageBox.Warning) == QMessageBox.Retry:

                # we need to reconnect the device; first, we'll try to reconnect to HW without closing the intefering
                # application; it it doesn't help we'll display a message requesting the user to close the app
                hw_session.hw_disconnect()
                if hw_session.hw_connect():
                    client = hw_session.hw_client
                else:
                    raise Exception('Hardware wallet reconnect error.')
            else:
                break
        else:
            ok = True
            break

    if not ok:
        raise CancelException('Cancelled')

    try:
        signature = client.signMessageSign()
    except Exception as e:
        logging.exception('Exception while signing message with Ledger Nano S')
        raise Exception('Exception while signing message with Ledger Nano S. Details: ' + str(e))

    try:
        pubkey = client.getWalletPublicKey(bip32_path)
    except Exception as e:
        logging.exception('Could not get public key for BIP32 path from Ledger Nano S')
        raise Exception('Could not get public key for BIP32 path from Ledger Nano S. Details: ' + str(e))

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
        pubkey.get('address') if isinstance(pubkey.get('address'), str) else pubkey.get('address').decode('ascii'),
        bytes(chr(27 + 4 + (signature[0] & 0x01)), "utf-8") + r + s
    )


@process_ledger_exceptions
def get_address_and_pubkey(client, bip32_path, show_display=False):
    bip32_path = clean_bip32_path(bip32_path)
    bip32_path.strip()
    if bip32_path.lower().find('m/') >= 0:
        bip32_path = bip32_path[2:]

    nodedata = client.getWalletPublicKey(bip32_path, showOnScreen=show_display)
    return {
        'address': nodedata.get('address') if isinstance(nodedata.get('address'), str) else nodedata.get('address').decode('utf-8'),
        'publicKey': compress_public_key(nodedata.get('publicKey'))
    }


@process_ledger_exceptions
def get_xpub(client, bip32_path):
    bip32_path = clean_bip32_path(bip32_path)
    bip32_path.strip()
    if bip32_path.lower().find('m/') >= 0:
        bip32_path = bip32_path[2:]
    path_n = bip32_path_string_to_n(bip32_path)
    parent_bip32_path = bip32_path_n_to_string(path_n[:-1])
    depth = len(path_n)
    index = path_n[-1]

    nodedata = client.getWalletPublicKey(bip32_path)
    pubkey = compress(nodedata.get('publicKey'))
    chaincode = nodedata.get('chainCode')

    parent_nodedata = client.getWalletPublicKey(parent_bip32_path)
    parent_pubkey = compress(parent_nodedata['publicKey'])
    parent_fingerprint = bin_hash160(parent_pubkey)[:4]

    xpub_raw = bytes.fromhex('0488b21e') + depth.to_bytes(1, 'big') + parent_fingerprint + index.to_bytes(4, 'big') + \
           chaincode + pubkey
    xpub = Base58.check_encode(xpub_raw)

    return xpub


def load_device_by_mnemonic(mnemonic_words: str, pin: str, passphrase: str, secondary_pin: str):
    """
    Initialise Ledger Nano S device with a list of mnemonic words.
    :param mnemonic_words: 12, 18 or 24 mnemonic words separated with spaces to initialise device.
    :param pin: PIN to be set in the device (4- or 8-character string)
    :param passphrase: Passphrase to be set in the device or empty.
    :param secondary_pin: Secondary PIN to activate passphrase. It's required if 'passphrase' is set.
    """

    def process(ctrl, mnemonic_words, pin, passphrase, secondary_pin):
        ctrl.dlg_config_fun(dlg_title="Please confirm", show_progress_bar=False)
        ctrl.display_msg_fun('<b>Please wait while initializing device...</b>')

        dongle = getDongle()

        # stage 1: initialize the hardware wallet with mnemonic words
        apdudata = bytearray()
        if pin:
            apdudata += bytearray([len(pin)]) + bytearray(pin, 'utf8')
        else:
            apdudata += bytearray([0])

        # empty prefix
        apdudata += bytearray([0])

        # empty passphrase in this phase
        apdudata += bytearray([0])

        if mnemonic_words:
            apdudata += bytearray([len(mnemonic_words)]) + bytearray(mnemonic_words, 'utf8')
        else:
            apdudata += bytearray([0])

        apdu = bytearray([0xE0, 0xD0, 0x00, 0x00, len(apdudata)]) + apdudata
        dongle.exchange(apdu, timeout=3000)

        # stage 2: setup the secondary pin and the passphrase if provided
        if passphrase and secondary_pin:
            ctrl.display_msg_fun('<b>Configuring the passphrase, enter the primary PIN on your <br>'
                                 'hardware wallet when asked...</b>')

            apdudata = bytearray()
            if pin:
                apdudata += bytearray([len(pin)]) + bytearray(secondary_pin, 'utf8')
            else:
                apdudata += bytearray([0])

            # empty prefix
            apdudata += bytearray([0])

            if passphrase:
                passphrase = unicodedata.normalize('NFKD', passphrase)
                apdudata += bytearray([len(passphrase)]) + bytearray(passphrase, 'utf8')
            else:
                apdudata += bytearray([0])

            # empty mnemonic words in this phase
            apdudata += bytearray([0])

            apdu = bytearray([0xE0, 0xD0, 0x01, 0x00, len(apdudata)]) + apdudata
            dongle.exchange(apdu, timeout=3000)

        dongle.close()
        del dongle
    try:
        return WndUtils.run_thread_dialog(process, (mnemonic_words, pin, passphrase, secondary_pin), True)
    except BTChipException as e:
        if e.message == 'Invalid status 6982':
            raise Exception('Operation failed with the following error: %s. \n\nMake sure you have reset the device '
                            'and started it in recovery mode.' % e.message)
        else:
            raise
    except Exception as e:
        raise


@process_ledger_exceptions
def sign_tx(hw_session: HwSessionInfo, utxos_to_spend: List[wallet_common.UtxoType],
            tx_outputs: List[wallet_common.TxOutputType], tx_fee):
    client = hw_session.hw_client
    rawtransactions = {}
    decodedtransactions = {}

    # Each of the UTXOs will become an input in the new transaction. For each of those inputs, create
    # a Ledger's 'trusted input', that will be used by the the device to sign a transaction.
    trusted_inputs = []

    # arg_inputs: list of dicts
    #  {
    #    'locking_script': <Locking script of the UTXO used as an input. Used in the process of signing
    #                       transaction.>,
    #    'outputIndex': <index of the UTXO within the previus transaction>,
    #    'txid': <hash of the previus transaction>,
    #    'bip32_path': <BIP32 path of the HW key controlling UTXO's destination>,
    #    'pubkey': <Public key obtained from the HW using the bip32_path.>
    #    'signature' <Signature obtained as a result of processing the input. It will be used as a part of the
    #               unlocking script.>
    #  }
    #  Why do we need a locking script of the previous transaction? When hashing a new transaction before creating its
    #  signature, all placeholders for input's unlocking script has to be filled with locking script of the
    #  corresponding UTXO. Look here for the details:
    #    https://klmoney.wordpress.com/bitcoin-dissecting-transactions-part-2-building-a-transaction-by-hand)
    arg_inputs = []

    # A dictionary mapping bip32 path to a pubkeys obtained from the Ledger device - used to avoid
    # reading it multiple times for the same bip32 path
    bip32_to_address = {}

    # read previous transactins
    for utxo in utxos_to_spend:
        if utxo.txid not in rawtransactions:
            tx = hw_session.dashd_intf.getrawtransaction(utxo.txid, 1, skip_cache=False)
            if tx and tx.get('hex'):
                tx_raw = tx.get('hex')
            else:
                tx_raw = hw_session.dashd_intf.getrawtransaction(utxo.txid, 0, skip_cache=False)

            if tx_raw:
                rawtransactions[utxo.txid] = tx_raw
            decodedtransactions[utxo.txid] = tx

    amount = 0
    starting = True
    for idx, utxo in enumerate(utxos_to_spend):
        amount += utxo.satoshis

        raw_tx = rawtransactions.get(utxo.txid)
        if not raw_tx:
            raise Exception("Can't find raw transaction for txid: " + utxo.txid)
        else:
            raw_tx = bytearray.fromhex(raw_tx)

        # parse the raw transaction, so that we can extract the UTXO locking script we refer to
        prev_transaction = bitcoinTransaction(raw_tx)

        data = decodedtransactions[utxo.txid]
        dip2_type = data.get("type", 0)
        if data['version'] == 3 and dip2_type != 0:
            # It's a DIP2 special TX with payload
            if dip2_type == DashTxType.SPEC_CB_TX:
                data["extraPayload"] = serialize_cbTx(data)
            elif dip2_type == DashTxType.LELANTUS_JSPLIT:
                data["extraPayload"] = serialize_Lelantus(data)
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
            prev_transaction.extra_data = dash_utils.num_to_varint(data["extraPayloadSize"]) + bytes.fromhex(
                data["extraPayload"])
        else:
            prev_transaction.extra_data = bytes()

        utxo_tx_index = utxo.output_index
        if utxo_tx_index < 0 or utxo_tx_index > len(prev_transaction.outputs):
            raise Exception('Incorrent value of outputIndex for UTXO %s' % str(idx))

        trusted_input = client.getTrustedInput(prev_transaction, utxo_tx_index)
        trusted_inputs.append(trusted_input)

        bip32_path = utxo.bip32_path
        bip32_path = clean_bip32_path(bip32_path)
        pubkey = bip32_to_address.get(bip32_path)
        if not pubkey:
            pubkey = compress_public_key(client.getWalletPublicKey(bip32_path)['publicKey'])
            bip32_to_address[bip32_path] = pubkey
        pubkey_hash = bitcoin.bin_hash160(pubkey)

        # verify if the public key hash of the wallet's bip32 path is the same as specified in the UTXO locking script
        # if they differ, signature and public key we produce and are going to include in the unlocking script won't
        # match the locking script conditions - transaction will be rejected by the network
        pubkey_hash_from_script = extract_pkh_from_locking_script(prev_transaction.outputs[utxo_tx_index].script)
        if pubkey_hash != pubkey_hash_from_script:
            logging.error("Error: different public key hashes for the BIP32 path %s (UTXO %s) and the UTXO locking "
                          "script. Your signed transaction will not be validated by the network." %
              (bip32_path, str(idx)))

        arg_inputs.append({
            'locking_script': prev_transaction.outputs[utxo.output_index].script,
            'pubkey': pubkey,
            'bip32_path': bip32_path,
            'outputIndex': utxo.output_index,
            'txid': utxo.txid
        })

    amount -= int(tx_fee)
    amount = int(amount)

    new_transaction = bitcoinTransaction()  # new transaction object to be used for serialization at the last stage
    new_transaction.version = bytearray([0x01, 0x00, 0x00, 0x00])
    for out in tx_outputs:
        output = bitcoinOutput()
        output.script = compose_tx_locking_script(out.address, hw_session.app_config.dash_network)
        output.amount = int.to_bytes(out.satoshis, 8, byteorder='little')
        new_transaction.outputs.append(output)

    # join all outputs - will be used by Ledger for sigining transaction
    all_outputs_raw = new_transaction.serializeOutputs()

    # sign all inputs on Ledger and add inputs in the new_transaction object for serialization
    for idx, new_input in enumerate(arg_inputs):

        client.startUntrustedTransaction(starting, idx, trusted_inputs, new_input['locking_script'])
        client.finalizeInputFull(all_outputs_raw)
        sig = client.untrustedHashSign(new_input['bip32_path'], lockTime=0)
        new_input['signature'] = sig

        input = bitcoinInput()
        input.prevOut = bytearray.fromhex(new_input['txid'])[::-1] + \
                        int.to_bytes(new_input['outputIndex'], 4, byteorder='little')
        input.script = bytearray([len(sig)]) + sig + bytearray([0x21]) + new_input['pubkey']
        input.sequence = bytearray([0xFF, 0xFF, 0xFF, 0xFF])
        new_transaction.inputs.append(input)

        starting = False

    new_transaction.lockTime = bytearray([0, 0, 0, 0])

    tx_raw = bytearray(new_transaction.serialize())
    return tx_raw, amount
