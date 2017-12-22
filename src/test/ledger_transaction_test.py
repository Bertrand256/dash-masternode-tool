#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-11

from btchip.btchip import *
from btchip.btchipUtils import *
import bitcoin

########################################################################################################################
### Input data - begin
########################################################################################################################

# Example UTXOs to include in the new transaction.
#   txid: the previous transaction id
#   outputIndex: UTXO's index in the previous transaction
#   bip32_path: path in the user's hardware wallet controlling this UTXO destination
utxos_to_spend = [
    {
        'txid': '85b65caa7b4dddc2d44e9d895067f903134b1714af323600a3fa4c2346f76603',
        'outputIndex': 1,
        'bip32_path': "44'/5'/0'/0/0"
    },
    {
        'txid': '1e8597d93faebb1f9192c58baca5334c6738899391d76ecd6827bd253e285632',
        'outputIndex': 0,
        'bip32_path': "44'/5'/0'/1/0"
    },
    {
        'txid': '739a009c472b302cc0a2517fa885bf9559b19d10efa51dcbf11749597ad25951',
        'outputIndex': 1,
        'bip32_path': "44'/5'/0'/0/1"
    },
]

# Cached raw-transaction data for transaction ids used in UTXOs being spent.
# Normally you would need to read that information from the network for each of the tramsaction ids used in UTXOs.
transactions_cache = {
    '85b65caa7b4dddc2d44e9d895067f903134b1714af323600a3fa4c2346f76603': '01000000016414e975156bfc2a3e65b0f642b417cb831e57bcfb201db897255832cb525923010000006b483045022100aa14fddc65763bd976ef06d715c36f56b7655bd868f9b051987ea44d4bef778702201c9223a336ac2bda02ade2ad916c9b7ddd776360c7d2cea8f34466fb87230dca012103e0a9fabe21f188bbcf10f08c3dfa12b698cd79c2f54a9db00a892ba71a4086d1feffffff02bcdb7909000000001976a914d49d98026ac8ae14b18c046e4ed8492656cc1bf488ac6e6f7057000000001976a914c4e67a872f860545b84ab8825c7f5fdf6038d93288ac4bb30b00',
    '1e8597d93faebb1f9192c58baca5334c6738899391d76ecd6827bd253e285632': '0100000001ebfc527107e418905af8d93c0ba44629a68446deceacabb30b97352b963b9789010000006a473044022073022ed113a640eddaf58b5ec643db0ec0d842c07970506b393b0c7d41e77b2002201eb04eafeebe0d7932f4ac7f658ec435c094f04c716dacd3769543632167ff0901210228dc084a458fbc4306c6fb216182a5255aa69cbfdd27230a5ee7fa7bba2a5623ffffffff027c4c3a04000000001976a9148d4414696c0bcc6402113654163bf4eb59885a8988ac6068bb01000000001976a914e65d642e2ef3dfbf41e1ace6a9650baba2d5ff5188ac00000000',
    '739a009c472b302cc0a2517fa885bf9559b19d10efa51dcbf11749597ad25951': '01000000017bd51f96e94b97f73d3f368dcd59f665f90789424baa51c820b109cb58d27c7e000000006b483045022100a698a861053d90b0116710aaff3395a426aab01c4d31af022c26ad5458c4ae5c022042d50db2906f09fb59b833533594677e6d410d6328cd12cd2e973036420baafb01210391f07fac182250875a3ccc8db742fc8375c88e59c32dfc17f60cd1a1ebd31923feffffff027be39c00000000001976a914d851fb201491736be63e0bf7716dad53c3b825cd88ac6eaa4404000000001976a914929b74150106ff3cffafa3148cc20cdd37611a6a88ac4bb30b00'
}

# outputs for the new transaction:
arg_outputs = [
    {
        'address': 'XmqUtfzxgSx7WzYkEd14ug2UrJgaCmANzV',
        'valueSat': 1664710
    },
    {
        'address': 'XnfG9X6GajFHLnGZbGxmGTemyKzwwHsuZN',
        'valueSat': 1607755714
    }
]

########################################################################################################################
### Input data - end
########################################################################################################################

# Bitcoin opcodes used to compose locking script
OP_DUP = b'\x76'
OP_HASH160 = b'\xA9'
OP_EQUALVERIFY = b'\x88'
OP_CHECKSIG = b'\xAC'
OP_EQUAL = b'\x87'


P2PKH_PREFIXES = ['X']
P2SH_PREFIXES = ['7']


def compose_tx_locking_script(dest_address):
    """
    Create a Locking script (ScriptPubKey) that will be assigned to a transaction output.
    :param dest_address: destination address in Base58Check format
    :return: sequence of opcodes and its arguments, defining logic of the locking script
    """

    pubkey_hash = bytearray.fromhex(bitcoin.b58check_to_hex(dest_address)) # convert address to a public key hash
    if len(pubkey_hash) != 20:
        raise Exception('Invalid length of the public key hash: ' + str(len(pubkey_hash)))

    if dest_address[0] in P2PKH_PREFIXES:
        # sequence of opcodes/arguments for p2pkh (pay-to-public-key-hash)
        scr = OP_DUP + \
              OP_HASH160 + \
              int.to_bytes(len(pubkey_hash), 1, byteorder='little') + \
              pubkey_hash + \
              OP_EQUALVERIFY + \
              OP_CHECKSIG
    elif dest_address[0] in P2SH_PREFIXES:
        # sequence of opcodes/arguments for p2sh (pay-to-script-hash)
        scr = OP_HASH160 + \
              int.to_bytes(len(pubkey_hash), 1, byteorder='little') + \
              pubkey_hash + \
              OP_EQUAL
    else:
        raise Exception('Invalid dest address prefix: ' + dest_address[0])
    return scr


def read_varint(buffer, offset):
    if (buffer[offset] < 0xfd):
        value_size = 1
        value = buffer[offset]
    elif (buffer[offset] == 0xfd):
        value_size = 3
        value = int.from_bytes(buffer[offset + 1: offset + 3], byteorder='little')
    elif (buffer[offset] == 0xfe):
        value_size = 5
        value = int.from_bytes(buffer[offset + 1: offset + 5], byteorder='little')
    elif (buffer[offset] == 0xff):
        value_size = 9
        value = int.from_bytes(buffer[offset + 1: offset + 9], byteorder='little')
    else:
        raise Exception("Invalid varint size")
    return value, value_size


def extract_pkh_from_locking_script(script):
    if len(script) == 25:
        if script[0:1] == OP_DUP and script[1:2] == OP_HASH160:
            if read_varint(script, 2)[0] == 20:
                return script[3:23]
            else:
                raise Exception('Non-standard public key hash length (should be 20)')
    raise Exception('Non-standard locking script type (should be P2PKH)')


dongle = getDongle(False)
app = btchip(dongle)


# Each of the UTXOs (utxos_to_send list) will become an input in the new transaction.
# For each of those inputs, create a Ledger's 'trusted input', that will be used by the device to sign a transaction
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

starting = True
for idx, utxo in enumerate(utxos_to_spend):

    raw_tx = bytearray.fromhex(transactions_cache[utxo['txid']])
    if not raw_tx:
        raise Exception("Can't find raw transaction for txid: " + transactions_cache[utxo['txid']])

    # parse the raw transaction, so that we can extract the UTXO locking script we refer to
    prev_transaction = bitcoinTransaction(raw_tx)

    utxo_tx_index = utxo['outputIndex']
    if utxo_tx_index < 0 or utxo_tx_index > len(prev_transaction.outputs):
        raise Exception('Incorrent value of outputIndex for UTXO %s' % str(idx))

    trusted_input = app.getTrustedInput(prev_transaction, utxo_tx_index)
    trusted_inputs.append(trusted_input)

    bip32path = utxo['bip32_path']
    pubkey = bip32_to_address.get(bip32path)
    if not pubkey:
        pubkey = compress_public_key(app.getWalletPublicKey(bip32path)['publicKey'])
        bip32_to_address[bip32path] = pubkey
    pubkey_hash = bitcoin.bin_hash160(pubkey)

    # verify if the public key hash of the wallet's bip32 path is the same as specified in the UTXO locking script
    # if they differ, signature and public key we produce and are going to include in the unlocking script won't
    # match the locking script conditions - transaction will be rejected by the network
    pubkey_hash_from_script = extract_pkh_from_locking_script(prev_transaction.outputs[utxo_tx_index].script)
    if pubkey_hash != pubkey_hash_from_script:
        print("Error: different public key hashes for the BIP32 path %s (UTXO %s) and the UTXO locking script. Your "
              "signed transaction will not be validated by the network." %
              (bip32path, str(idx)))

    arg_inputs.append({
        'locking_script': prev_transaction.outputs[utxo['outputIndex']].script,
        'pubkey': pubkey,
        'bip32_path': bip32path,
        'outputIndex': utxo['outputIndex'],
        'txid': utxo['txid']
    })


new_transaction = bitcoinTransaction()  # new transaction object for serialization at the last stage
new_transaction.version = bytearray([0x01, 0x00, 0x00, 0x00])
for o in arg_outputs:
    output = bitcoinOutput()
    output.script = compose_tx_locking_script(o['address'])
    output.amount = int.to_bytes(o['valueSat'], 8, byteorder='little')
    new_transaction.outputs.append(output)

# join all outputs - will be used by Ledger for sigining transaction
all_outputs_raw = new_transaction.serializeOutputs()

# sign all inputs on Ledger and add inputs in the new_transaction object for serialization
for idx, new_input in enumerate(arg_inputs):

    app.startUntrustedTransaction(starting, idx, trusted_inputs, new_input['locking_script'])
    out = app.finalizeInputFull(all_outputs_raw)
    sig = app.untrustedHashSign(new_input['bip32_path'], lockTime=0)
    new_input['signature'] = sig

    input = bitcoinInput()
    input.prevOut = bytearray.fromhex(new_input['txid'])[::-1] + \
                    int.to_bytes(new_input['outputIndex'], 4, byteorder='little')
    input.script = bytearray([len(sig)]) + sig + bytearray([0x21]) + new_input['pubkey']
    input.sequence = bytearray([0xFF, 0xFF, 0xFF, 0xFF])
    new_transaction.inputs.append(input)

    starting = False

new_transaction.lockTime = bytearray([0, 0, 0, 0])

tx_raw = new_transaction.serialize()
print(bytearray(tx_raw).hex())


