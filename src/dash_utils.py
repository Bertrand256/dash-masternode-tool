#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

import binascii
import base64
import logging
import re
import struct
import typing
import hashlib
from random import randint

import bitcoin
from bip32utils import Base58
import base58
from typing import Literal, cast
from blspy import (PrivateKey, Util, AugSchemeMPL, PopSchemeMPL, G1Element, G2Element)
from bls_py import bls as bls_legacy
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import cryptography.hazmat.primitives.serialization


# Bitcoin opcodes used in the application
OP_DUP = b'\x76'
OP_HASH160 = b'\xA9'
OP_EQUALVERIFY = b'\x88'
OP_CHECKSIG = b'\xAC'
OP_EQUAL = b'\x87'

DEFAULT_SENTINEL_VERSION = 0x010001  # sentinel version before implementation of nSentinelVersion in CMasternodePing
DEFAULT_DAEMON_VERSION = 120200  # daemon version before implementation of nDaemonVersion in CMasternodePing
MASTERNODE_TX_MINIMUM_CONFIRMATIONS = 15
DASH_PLATFORM_DEFAULT_P2P_PORT = 26656
DASH_PLATFORM_DEFAULT_HTTP_PORT = 443

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


def get_chain_params(dash_network: str):
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
    """Convert public key to a Dash address."""
    pubkey_bin = bytes.fromhex(pub_key)
    pub_hash = bitcoin.bin_hash160(pubkey_bin)
    data = bytes([get_chain_params(dash_network).PREFIX_PUBKEY_ADDRESS]) + pub_hash
    checksum = bitcoin.bin_dbl_sha256(data)[0:4]
    return base58.b58encode(data + checksum)


def address_to_pubkey_hash(address: str) -> typing.Optional[bytes]:
    try:
        data = base58.b58decode(address)
        if len(data) > 5:
            pubkey_hash = data[0:-4]
            checksum = data[-4:]
            if bitcoin.bin_dbl_sha256(pubkey_hash)[0:4] == checksum:
                return pubkey_hash[1:]
    except Exception:
        logging.exception('Address validation failure.')
    return None


def wif_privkey_to_address(privkey: str, dash_network: str):
    pubkey = wif_privkey_to_pubkey(privkey)
    return pubkey_to_address(pubkey, dash_network)


def validate_address(address: str, dash_network: typing.Optional[str] = None) -> bool:
    """Validates if the 'address' is a valid Dash address.
    :address: address to be validated
    :dash_network: the dash network type against which the address will be validated; if the value is None, then
      the network type prefix validation will be skipped
    """
    try:
        data = base58.b58decode(address)
        if len(data) > 5:
            prefix = data[0]
            if dash_network:
                prefix_valid = (prefix == get_chain_params(dash_network).PREFIX_PUBKEY_ADDRESS or
                                prefix == get_chain_params(dash_network).PREFIX_SCRIPT_ADDRESS)
            else:
                prefix_valid = (prefix == ChainParamsMainNet.PREFIX_PUBKEY_ADDRESS or
                                prefix == ChainParamsMainNet.PREFIX_SCRIPT_ADDRESS or
                                prefix == ChainParamsTestNet.PREFIX_PUBKEY_ADDRESS or
                                prefix == ChainParamsTestNet.PREFIX_SCRIPT_ADDRESS)
            if prefix_valid:
                pubkey_hash = data[:-4]
                checksum = data[-4:]
                if bitcoin.bin_dbl_sha256(pubkey_hash)[0:4] == checksum:
                    return True
    except Exception:
        logging.exception('Address validation failure.')
    return False


def generate_wif_privkey(dash_network: str, compressed: bool = False):
    """
    Based on Andreas Antonopolous work from 'Mastering Bitcoin'.
    """
    valid = False
    privkey = 0
    while not valid:
        privkey = bitcoin.random_key()
        decoded_private_key = bitcoin.decode_privkey(privkey, 'hex')
        valid = 0 < decoded_private_key < bitcoin.N
    if compressed:
        privkey += '01'
    data = bytes([get_chain_params(dash_network).PREFIX_SECRET_KEY]) + bytes.fromhex(privkey)
    checksum = bitcoin.bin_dbl_sha256(data)[0:4]
    return base58.b58encode(data + checksum)


def validate_wif_privkey(privkey: str, dash_network: str) -> bool:
    try:
        data = base58.b58decode(privkey)
        if len(data) not in (37, 38):
            raise Exception('Invalid private key length')

        if data[0] != get_chain_params(dash_network).PREFIX_SECRET_KEY:
            raise Exception('Invalid private key prefix.')

        checksum = data[-4:]
        data = data[:-4]

        if len(data) == 34:
            compressed = data[-1]
        else:
            compressed = 0
        if compressed not in (0, 1):
            raise Exception('Invalid the compressed byte value: ' + str(compressed))

        checksum_cur = bitcoin.bin_dbl_sha256(data)[0:4]
        if checksum != checksum_cur:
            raise Exception('Invalid private key checksum')
    except Exception as e:
        logging.warning(str(e))
        return False
    return True


def wif_privkey_to_pubkey(privkey):
    pub = bitcoin.privkey_to_pubkey(privkey)
    return pub


def generate_bls_privkey() -> str:
    """
    :return: Generated BLS private key as a hex string.
    """
    max_iterations = 2000
    for i in range(0, max_iterations):
        privkey = bitcoin.random_key()
        pk_bytes = bytes.fromhex(privkey)
        num_pk = bitcoin.decode_privkey(privkey, 'hex')
        if 0 < num_pk < bitcoin.N:
            try:
                pk: PrivateKey = AugSchemeMPL.key_gen(pk_bytes)
                return bytes(pk).hex()
            except Exception as e:
                logging.warning('Could not process "%s" as a BLS private key. Error details: %s',
                                pk_bytes.hex(), str(e))
        else:
            logging.warning('Skipping the generated key: %s', pk_bytes.hex())
    raise Exception("Could not generate BLS private key")


def bls_privkey_to_pubkey(privkey: str) -> str:
    pk_bin = bytes.fromhex(privkey)
    pk = PrivateKey.from_bytes(pk_bin)
    pubkey = bytes(pk.get_g1()).hex()
    return pubkey


def validate_bls_privkey(privkey: str) -> bool:
    try:
        pub = bls_privkey_to_pubkey(privkey)
        return True if pub else False
    except Exception:
        return False


def validate_bls_pubkey(pubkey: str) -> bool:
    try:
        pk = G1Element.from_bytes(bytes.fromhex(pubkey))
        return True
    except Exception as e:
        return False


def bls_privkey_to_pubkey_legacy(privkey: str) -> str:
    """
    :param privkey: BLS privkey as a hex string
    :return: BLS pubkey as a hex string.
    """
    pk_bin = bytes.fromhex(privkey)
    if len(pk_bin) != 32:
        raise Exception(f'Invalid private key length: {len(pk_bin)} (should be 32)')
    pk = bls_legacy.PrivateKey.from_bytes(pk_bin)
    pubkey = pk.get_public_key()
    pubkey_bin = pubkey.serialize()
    return pubkey_bin.hex()


def validate_bls_privkey_legacy(privkey: str) -> bool:
    try:
        pub = bls_privkey_to_pubkey_legacy(privkey)
        return True if pub else False
    except Exception:
        return False


def validate_bls_pubkey_legacy(pubkey: str) -> bool:
    try:
        bls_legacy.PublicKey.from_bytes(bytes.fromhex(pubkey))
        return True
    except Exception:
        return False


def num_to_varint(n):
    if n == 0:
        return b"\x00"
    elif n < 253:
        return struct.pack("<B", n)
    elif n <= 65535:
        return struct.pack("<BH", 253, n)
    elif n <= 4294967295:
        return struct.pack("<BL", 254, n)
    else:
        return struct.pack("<BQ", 255, n)


def read_varint_from_buf(buffer, offset) -> typing.Tuple[int, int]:
    if buffer[offset] < 0xfd:
        value_size = 1
        value = buffer[offset]
    elif buffer[offset] == 0xfd:
        value_size = 3
        value = int.from_bytes(buffer[offset + 1: offset + 3], byteorder='little')
    elif buffer[offset] == 0xfe:
        value_size = 5
        value = int.from_bytes(buffer[offset + 1: offset + 5], byteorder='little')
    elif buffer[offset] == 0xff:
        value_size = 9
        value = int.from_bytes(buffer[offset + 1: offset + 9], byteorder='little')
    else:
        raise Exception("Invalid varint size")
    return value, value_size + offset


def read_varint_from_file(fptr: typing.BinaryIO) -> int:
    buffer = fptr.read(1)
    if buffer[0] < 0xfd:
        value_size = 1
        value = buffer[0]
    elif buffer[0] == 0xfd:
        value_size = 2
        buffer = fptr.read(value_size)
        value = int.from_bytes(buffer[0: 2], byteorder='little')
    elif buffer[0] == 0xfe:
        value_size = 4
        buffer = fptr.read(value_size)
        value = int.from_bytes(buffer[0: 4], byteorder='little')
    elif buffer[0] == 0xff:
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
    privkey_encoded = base58.b58decode(wif_key).hex()
    wif_prefix_cur = privkey_encoded[:2]
    wif_prefix_network = get_chain_params(dash_network).PREFIX_SECRET_KEY
    wif_prefix_network_str = wif_prefix_network.to_bytes(1, byteorder='big').hex()
    checksum_stored = privkey_encoded[-8:]

    vs = bytes.fromhex(privkey_encoded[:-8])
    checksum_actual = binascii.unhexlify(bitcoin.dbl_sha256(vs))[0:4]
    checksum_actual_str = checksum_actual.hex()

    if wif_prefix_cur == wif_prefix_network_str and checksum_stored == checksum_actual_str:
        privkey = privkey_encoded[2:-8]
        return privkey
    else:
        if wif_prefix_cur != wif_prefix_network_str:
            logging.warning('Private key and network prefixes differ. PK prefix: %s, network prefix: %s', wif_prefix_cur,
                            wif_prefix_network_str)
        if checksum_stored != checksum_actual_str:
            logging.warning('Invalid private key checksum. PK checksum: %s, required: %s', checksum_stored,
                            checksum_actual_str)
        return None


def wif_privkey_to_uncompressed(wif_key: str):
    privkey_encoded = base58.b58decode(wif_key)
    if len(privkey_encoded) == 38 and privkey_encoded[33] == 0x01:
        # [1-byte prefix][32-byte privkey][optional 1-byte compression suffix][4-byte checksum]
        data = privkey_encoded[:33]
        checksum = bitcoin.bin_dbl_sha256(data)[0:4]
        return base58.b58encode(data + checksum)
    else:
        return wif_key


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
    """Signs a message with the Elliptic Curve algorithm.
    """

    v, r, s = bitcoin.ecdsa_raw_sign(electrum_sig_hash(msg), wif_priv_key)
    sig = bitcoin.encode_sig(v, r, s)
    pubkey = bitcoin.privkey_to_pubkey(wif_to_privkey(wif_priv_key, dash_network))

    ok = bitcoin.ecdsa_raw_verify(electrum_sig_hash(msg), bitcoin.decode_sig(sig), pubkey)
    if not ok:
        raise Exception('Bad signature!')
    return sig


def ecdsa_sign_raw(msg_raw: bytes, wif_priv_key: str, dash_network: str):
    """Signs raw bytes (a message hash) with the Elliptic Curve algorithm.
    """

    v, r, s = bitcoin.ecdsa_raw_sign(msg_raw, wif_priv_key)
    sig = bitcoin.encode_sig(v, r, s)
    pubkey = bitcoin.privkey_to_pubkey(wif_to_privkey(wif_priv_key, dash_network))

    ok = bitcoin.ecdsa_raw_verify(msg_raw, bitcoin.decode_sig(sig), pubkey)
    if not ok:
        raise Exception('Bad signature!')
    return sig


def serialize_input_str(tx, prevout_n, sequence, script_sig):
    """Based on project: https://github.com/chaeplin/dashmnb."""
    s = ['CTxIn(', 'COutPoint(%s, %s)' % (tx, prevout_n), ', ']
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
    if path_str:
        elems = [int(elem[:-1]) + 0x80000000 if elem.endswith("'") else int(elem) for elem in path_str.split('/')]
    else:
        elems = []
    return elems


def bip32_path_string_append_elem(path_str: str, elem: int):
    path_n = bip32_path_string_to_n(path_str)
    path_n.append(elem)
    return bip32_path_n_to_string(path_n)


def compose_tx_locking_script(dest_address, dash_network: str):
    """
    Create a Locking script (ScriptPubKey) that will be assigned to a transaction output.
    :param dest_address: destination address in Base58Check format
    :return: sequence of opcodes and its arguments, defining logic of the locking script
    """

    pubkey_hash = bytearray.fromhex(bitcoin.b58check_to_hex(dest_address)) # convert address to a public key hash
    if len(pubkey_hash) != 20:
        raise Exception('Invalid length of the public key hash: ' + str(len(pubkey_hash)))

    if dest_address[0] in get_chain_params(dash_network).B58_PREFIXES_PUBKEY_ADDRESS:
        # sequence of opcodes/arguments for p2pkh (pay-to-public-key-hash)
        scr = OP_DUP + \
              OP_HASH160 + \
              int.to_bytes(len(pubkey_hash), 1, byteorder='little') + \
              pubkey_hash + \
              OP_EQUALVERIFY + \
              OP_CHECKSIG
    elif dest_address[0] in get_chain_params(dash_network).B58_PREFIXES_SCRIPT_ADDRESS:
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


def convert_dash_xpub(xpub, dest_prefix: str):
    if dest_prefix != xpub[0:4]:
        if dest_prefix == 'xpub':
            raw = Base58.check_decode(xpub)
            raw = bytes.fromhex('0488b21e') + raw[4:]
            xpub = Base58.check_encode(raw)
        elif dest_prefix == 'drkp':
            raw = Base58.check_decode(xpub)
            raw = bytes.fromhex('02fe52cc') + raw[4:]
            xpub = Base58.check_encode(raw)
    return xpub


def generate_ed25519_private_key() -> str:
    """
    Generates an ed25519 private key as a hex-encoded 32-byte binary value
    :return: hex-encoded string
    """
    pk = Ed25519PrivateKey.generate()
    pk_bin = pk.private_bytes_raw()
    return pk_bin.hex()


def parse_ed25519_private_key(priv_key: str) -> Ed25519PrivateKey:
    """
    Parses ed25519 private key from a few formats.
    :param priv_key: Private key as a string in formats:
                       a) PEM with "-----BEGIN/END PRIVATE KEY" enclosing
                       b) PEM without "-----BEGIN/END PRIVATE KEY" enclosing (bare Base64 string)
                       c) private + public keys concatenated (64 byte)
                       d) hex-encoded 32-byte value (64-byte string)
    :return: 32-byte private key as a hex string
    """
    try:
        match = re.match(r"-+BEGIN PRIVATE KEY-+\n(.+)\n-+END PRIVATE KEY-+", priv_key, re.IGNORECASE)
        if match and len(match.groups()) == 1:
            base64_str = match.group(1)
            priv_key = base64.b64decode(base64_str)
        elif len(priv_key) == 64:
            # assume that priv-key is a hex-encoded binary value
            priv_key = bytes.fromhex(priv_key)
        else:
            # assume, that priv_key is a base64 encoded private key with or without a DER "header""
            priv_key = base64.b64decode(priv_key)

        pub_key_in = None
        if len(priv_key) == 48:
            priv_key = priv_key[16:]  # extract private key from DER encoding
        elif len(priv_key) == 32:
            pass
        elif len(priv_key) == 64:
            # Assume that the input string contains a combined private key and public key
            priv_key, pub_key_in = priv_key[0:32], priv_key[32:]
        else:
            raise Exception('Invalid private key format (1)')

        pk = Ed25519PrivateKey.from_private_bytes(priv_key)
        if pub_key_in:
            pub_key_hex = pk.public_key().public_bytes(
                cryptography.hazmat.primitives.serialization.Encoding.Raw,
                cryptography.hazmat.primitives.serialization.PublicFormat.Raw).hex()

            if pub_key_in.hex() != pub_key_hex:
                raise Exception('Invalid private key format (2)')

        return pk
    except Exception as e:
        raise Exception('Invalid private key format (3): ' + str(e))


def ed25519_private_key_to_pubkey(priv_key: str) -> str:
    """
    Converts Ed25519 private key to a public key.
    :param priv_key: see function parse_ed25519_private_key
    :return: 32-byte public key as a hex string
    """
    pk = parse_ed25519_private_key(priv_key)
    pub_key_hex = pk.public_key().public_bytes(cryptography.hazmat.primitives.serialization.Encoding.Raw,
                                               cryptography.hazmat.primitives.serialization.PublicFormat.Raw).hex()
    return pub_key_hex


def ed25519_public_key_to_platform_id(public_key: str) -> str:
    """
    Converts ed25519 public key to Dash Platform ID
    :param public_key: hex encoded public key (32 byte)
    :return: platform id string
    """
    pub_bytes = bytes.fromhex(public_key)
    hashed = hashlib.sha256(pub_bytes)
    return hashed.digest()[0:20].hex()


class COutPoint(object):
    def __init__(self, hash: str, index: int):
        self.hash: bytes = bytes.fromhex(hash)
        self.index: int = index

    def serialize_for_sig(self, dash_network: Literal['MAINNET', 'TESTNET']) -> str:
        if dash_network == 'MAINNET':
            ser_str = self.hash.hex() + '-' + str(self.index)
        else:
            ser_str = self.hash[::-1].hex()
            ser_str += int(self.index).to_bytes(4, byteorder='little').hex()
        return ser_str


class CGovernanceVote(object):
    def __init__(self, mn_collateral_hash: str, mn_collateral_index: int, proposal_hash: str, vote: str, time: int):
        vote_outcome_dict = {
            'none': 0,
            'yes': 1,
            'no': 2,
            'abstain': 3
        }

        self.outpoint = COutPoint(mn_collateral_hash, mn_collateral_index)
        self.proposal_hash: bytes = bytes.fromhex(proposal_hash)
        self.vote_signal: int = 1  # VOTE_SIGNAL_FUNDING
        self.vote_outcome: int = vote_outcome_dict.get(vote)
        self.time: int = time

    def serialize(self, dash_network: Literal['MAINNET', 'TESTNET']):
        ser_str = self.outpoint.serialize_for_sig(dash_network)
        ser_str += '00' + 0xffffffff.to_bytes(4, byteorder='little').hex()
        ser_str += self.proposal_hash[::-1].hex()
        ser_str += self.vote_signal.to_bytes(4, byteorder='little').hex()
        ser_str += self.vote_outcome.to_bytes(4, byteorder='little').hex()
        ser_str += self.time.to_bytes(8, byteorder='little').hex()
        return ser_str

    def serialize_for_sig(self, dash_network: Literal['MAINNET', 'TESTNET']):
        ser_str = self.outpoint.serialize_for_sig(dash_network)
        if dash_network == 'MAINNET':
            ser_str += '|' + self.proposal_hash.hex() + '|' + str(self.vote_signal) + '|' + str(self.vote_outcome) + \
                       '|' + str(self.time)
        else:
            ser_str += self.proposal_hash[::-1].hex()
            ser_str += self.vote_outcome.to_bytes(4, byteorder='little').hex()
            ser_str += self.vote_signal.to_bytes(4, byteorder='little').hex()
            ser_str += self.time.to_bytes(8, byteorder='little').hex()
        return ser_str

    def get_hash(self):
        ser_str = self.serialize()
        hash = bitcoin.bin_dbl_sha256(bytes.fromhex(ser_str))
        return hash.hex()

    def get_data_for_signing(self, dash_network: Literal['MAINNET', 'TESTNET']) -> bytes:
        ser_str = self.serialize_for_sig(dash_network)
        if dash_network == 'TESTNET':
            data_for_sig = bitcoin.bin_dbl_sha256(bytes.fromhex(ser_str))
        else:
            data_for_sig = ser_str.encode('ascii')
        return data_for_sig

    def get_signed_vote(self, priv_key: str, dash_network: Literal['MAINNET', 'TESTNET']) -> str:
        """
        Sign a vote object.
        :param priv_key: Private key for voting.
        :param dash_network: TESTNET or MAINNET
        :return: Base64-encoded signature
        """
        ser_str = self.serialize_for_sig(dash_network)
        if dash_network == 'TESTNET':
            data_for_sig = bitcoin.bin_dbl_sha256(bytes.fromhex(ser_str))
            sig_base64 = ecdsa_sign_raw(data_for_sig, priv_key, dash_network)
        else:
            sig_base64 = ecdsa_sign(ser_str, priv_key, dash_network)
        return sig_base64
