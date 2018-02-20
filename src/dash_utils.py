#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

import binascii
import typing
import bitcoin
import base58


# Bitcoin opcodes used in the application
OP_DUP = b'\x76'
OP_HASH160 = b'\xA9'
OP_EQUALVERIFY = b'\x88'
OP_CHECKSIG = b'\xAC'
OP_EQUAL = b'\x87'


class ChainParams(object):
    B58_PREFIXES_PUBKEY_ADDRESS = None
    B58_PREFIXES_SCRIPT_ADDRESS = None
    B58_PREFIXES_SECRET_KEY = None
    PREFIX_PUBKEY_ADDRESS = None
    PREFIX_SCRIPT_ADDRESS = None
    PREFIX_SECRET_KEY = None
    BIP44_COIN_TYPE = None


class ChainParamsMainNet(ChainParams):
    B58_PREFIXES_PUBKEY_ADDRESS = ['X']
    B58_PREFIXES_SCRIPT_ADDRESS = ['7']
    B58_PREFIXES_SECRET_KEY = ['7', 'X']
    PREFIX_PUBKEY_ADDRESS = 76
    PREFIX_SCRIPT_ADDRESS = 16
    PREFIX_SECRET_KEY = 204
    BIP44_COIN_TYPE = 5


class ChainParamsTestNet(ChainParams):
    B58_PREFIXES_PUBKEY_ADDRESS = ['y']
    B58_PREFIXES_SCRIPT_ADDRESS = ['8', '9']
    B58_PREFIXES_SECRET_KEY = ['9', 'c']
    PREFIX_PUBKEY_ADDRESS = 140
    PREFIX_SCRIPT_ADDRESS = 19
    PREFIX_SECRET_KEY = 239
    BIP44_COIN_TYPE = 1


def get_chain_params(dash_network: str) -> typing.ClassVar[ChainParams]:
    if dash_network == 'MAINNET':
        return ChainParamsMainNet
    elif dash_network == 'TESTNET':
        return ChainParamsTestNet
    else:
        raise Exception('Invalid \'network\' value.')


def get_default_bip32_path(dash_network: str):
    return bip32_path_n_to_string([44 + 0x80000000, get_chain_params(dash_network).BIP44_COIN_TYPE + 0x80000000, 0x80000000, 0, 0])


def get_default_bip32_base_path(dash_network: str):
    return bip32_path_n_to_string([44 + 0x80000000, get_chain_params(dash_network).BIP44_COIN_TYPE + 0x80000000])


def get_default_bip32_base_path_n(dash_network: str):
    return [44 + 0x80000000, get_chain_params(dash_network).BIP44_COIN_TYPE + 0x80000000]


def validate_bip32_path(path: str) -> bool:
    try:
        path_n = bip32_path_string_to_n(path)
        for e in path_n:
            if e < 0 or e > 0xFFFFFFFF:
                return False
        return True
    except Exception:
        return False


def pubkey_to_address(pub_key, dash_network: str):
    """Convert public key to Dash address."""
    pubkey_bin = bytes.fromhex(pub_key)
    pub_hash = bitcoin.bin_hash160(pubkey_bin)
    data = bytes([get_chain_params(dash_network).PREFIX_PUBKEY_ADDRESS]) + pub_hash
    checksum = bitcoin.bin_dbl_sha256(data)[0:4]
    return base58.b58encode(data + checksum)


def validate_address(address: str, dash_network: typing.Optional[str]) -> bool:
    """Validates if the 'address' is a valid Dash address.
    :address: address to be validated
    :dash_network: the dash network type against which the address will be validated; if the value is None, then
      the network type prefix validation will be skipped
    """
    data = base58.b58decode(address)
    if len(data) > 5:
        prefix = data[0]
        if dash_network:
            prefix_valid = (prefix == get_chain_params(dash_network).PREFIX_PUBKEY_ADDRESS)
        else:
            prefix_valid = (prefix == ChainParamsMainNet.PREFIX_PUBKEY_ADDRESS or
                            prefix == ChainParamsTestNet.PREFIX_PUBKEY_ADDRESS)
        if prefix_valid:
            pukey_hash = data[:-4]
            checksum = data[-4:]
            if bitcoin.bin_dbl_sha256(pukey_hash)[0:4] == checksum:
                return True
    return False


def generate_privkey(dash_network: str):
    """
    Based on Andreas Antonopolous work from 'Mastering Bitcoin'.
    """
    valid = False
    privkey = 0
    while not valid:
        privkey = bitcoin.random_key()
        decoded_private_key = bitcoin.decode_privkey(privkey, 'hex')
        valid = 0 < decoded_private_key < bitcoin.N
    data = bytes([get_chain_params(dash_network).PREFIX_SECRET_KEY]) + bytes.fromhex(privkey)
    checksum = bitcoin.bin_dbl_sha256(data)[0:4]
    return base58.b58encode(data + checksum)


def num_to_varint(a):
    """
    Based on project: https://github.com/chaeplin/dashmnb
    """
    x = int(a)
    if x < 253:
        return x.to_bytes(1, byteorder='big')
    elif x < 65536:
        return int(253).to_bytes(1, byteorder='big') + x.to_bytes(2, byteorder='little')
    elif x < 4294967296:
        return int(254).to_bytes(1, byteorder='big') + x.to_bytes(4, byteorder='little')
    else:
        return int(255).to_bytes(1, byteorder='big') + x.to_bytes(8, byteorder='little')


def read_varint_from_buf(buffer, offset) -> typing.Tuple[int, int]:
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
    return value, value_size + offset


def read_varint_from_file(fptr: typing.BinaryIO) -> int:
    buffer = fptr.read(1)
    if (buffer[0] < 0xfd):
        value_size = 1
        value = buffer[0]
    elif (buffer[0] == 0xfd):
        value_size = 2
        buffer = fptr.read(value_size)
        value = int.from_bytes(buffer[0: 2], byteorder='little')
    elif (buffer[0] == 0xfe):
        value_size = 4
        buffer = fptr.read(value_size)
        value = int.from_bytes(buffer[0: 4], byteorder='little')
    elif (buffer[0] == 0xff):
        value_size = 8
        buffer = fptr.read(value_size)
        value = int.from_bytes(buffer[0: 8], byteorder='little')
    else:
        raise Exception("Invalid varint size")
    if value_size != len(buffer):
        raise ValueError('File end before read completed.')
    return value


def wif_to_privkey(wif_key: str, dash_network: str):
    """
    Based on project: https://github.com/chaeplin/dashmnb with some changes related to usage of bitcoin library.
    """
    wif_compressed = (52 == len(wif_key))
    privkey_encoded = base58.b58decode(wif_key).hex()
    wif_version = privkey_encoded[:2]
    wif_prefix = get_chain_params(dash_network).PREFIX_SECRET_KEY
    checksum = privkey_encoded[-8:]

    vs = bytes.fromhex(privkey_encoded[:-8])
    check = binascii.unhexlify(bitcoin.dbl_sha256(vs))[0:4]

    if wif_version == wif_prefix.to_bytes(1, byteorder='big').hex() and checksum == check.hex():
        if wif_compressed:
            privkey = privkey_encoded[2:-10]
        else:
            privkey = privkey_encoded[2:-8]

        return privkey
    else:
        return None


def privkey_valid(privkey):
    try:
        pk = bitcoin.decode_privkey(privkey, 'wif')
        pkhex = bitcoin.encode_privkey(pk, 'hex')
        if len(pkhex) in (62, 64):
            return True
        else:
            return False
    except Exception as e:
        return False


def from_string_to_bytes(a):
    """
    Based on project: https://github.com/chaeplin/dashmnb.
    """
    return a if isinstance(a, bytes) else bytes(a, 'utf-8')


def electrum_sig_hash(message):
    """
    Based on project: https://github.com/chaeplin/dashmnb.
    """
    padded = b"\x19DarkCoin Signed Message:\n" + \
        num_to_varint(len(message)) + from_string_to_bytes(message)
    return bitcoin.dbl_sha256(padded)


def ecdsa_sign(msg: str, wif_priv_key: str, dash_network: str):
    """Signs a message with the Elliptic Curve algorithm."""
    v, r, s = bitcoin.ecdsa_raw_sign(electrum_sig_hash(msg), wif_priv_key)
    sig = bitcoin.encode_sig(v, r, s)
    pubkey = bitcoin.privkey_to_pubkey(wif_to_privkey(wif_priv_key, dash_network))

    ok = bitcoin.ecdsa_raw_verify(electrum_sig_hash(msg), bitcoin.decode_sig(sig), pubkey)
    if not ok:
        raise Exception('Bad signature!')
    return sig


def serialize_input_str(tx, prevout_n, sequence, script_sig):
    """Based on project: https://github.com/chaeplin/dashmnb."""
    s = ['CTxIn(']
    s.append('COutPoint(%s, %s)' % (tx, prevout_n))
    s.append(', ')
    if tx == '00' * 32 and prevout_n == 0xffffffff:
        s.append('coinbase %s' % script_sig)
    else:
        script_sig2 = script_sig
        if len(script_sig2) > 24:
            script_sig2 = script_sig2[0:24]
        s.append('scriptSig=%s' % script_sig2)

    if sequence != 0xffffffff:
        s.append(', nSequence=%d' % sequence)
    s.append(')')
    return ''.join(s)


def bip32_path_n_to_string(path_n):
    ret = ''
    for elem in path_n:
        if elem >= 0x80000000:
            ret += ('/' if ret else '') + str(elem - 0x80000000) + "'"
        else:
            ret += ('/' if ret else '') + str(elem)
    return ret


def bip32_path_string_to_n(path_str):
    if path_str.startswith('m/'):
        path_str = path_str[2:]
    path_str = path_str.strip('/')
    elems = [int(elem[:-1]) + 0x80000000 if elem.endswith("'") else int(elem) for elem in path_str.split('/')]
    return elems


def compose_tx_locking_script(dest_address, dash_newtork: str):
    """
    Create a Locking script (ScriptPubKey) that will be assigned to a transaction output.
    :param dest_address: destination address in Base58Check format
    :return: sequence of opcodes and its arguments, defining logic of the locking script
    """

    pubkey_hash = bytearray.fromhex(bitcoin.b58check_to_hex(dest_address)) # convert address to a public key hash
    if len(pubkey_hash) != 20:
        raise Exception('Invalid length of the public key hash: ' + str(len(pubkey_hash)))

    if dest_address[0] in get_chain_params(dash_newtork).B58_PREFIXES_PUBKEY_ADDRESS:
        # sequence of opcodes/arguments for p2pkh (pay-to-public-key-hash)
        scr = OP_DUP + \
              OP_HASH160 + \
              int.to_bytes(len(pubkey_hash), 1, byteorder='little') + \
              pubkey_hash + \
              OP_EQUALVERIFY + \
              OP_CHECKSIG
    elif dest_address[0] in get_chain_params(dash_newtork).B58_PREFIXES_SCRIPT_ADDRESS:
        # sequence of opcodes/arguments for p2sh (pay-to-script-hash)
        scr = OP_HASH160 + \
              int.to_bytes(len(pubkey_hash), 1, byteorder='little') + \
              pubkey_hash + \
              OP_EQUAL
    else:
        raise Exception('Invalid dest address prefix: ' + dest_address[0])
    return scr


def extract_pkh_from_locking_script(script):
    if len(script) == 25:
        if script[0:1] == OP_DUP and script[1:2] == OP_HASH160:
            if read_varint_from_buf(script, 2)[0] == 20:
                return script[3:23]
            else:
                raise Exception('Non-standard public key hash length (should be 20)')
    raise Exception('Non-standard locking script type (should be P2PKH)')


