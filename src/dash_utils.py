#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

import binascii
import base64
import logging
import struct
import typing
from random import randint

import bitcoin
from bip32utils import Base58
import base58
from bls_py import bls


# Bitcoin opcodes used in the application
OP_DUP = b'\x76'
OP_HASH160 = b'\xA9'
OP_EQUALVERIFY = b'\x88'
OP_CHECKSIG = b'\xAC'
OP_EQUAL = b'\x87'

DEFAULT_SENTINEL_VERSION = 0x010001  # sentinel version before implementation of nSentinelVersion in CMasternodePing
DEFAULT_DAEMON_VERSION = 120200  # daemon version before implementation of nDaemonVersion in CMasternodePing


class ChainParams(object):
    B58_PREFIXES_PUBKEY_ADDRESS = None
    B58_PREFIXES_SCRIPT_ADDRESS = None
    B58_PREFIXES_SECRET_KEY = None
    PREFIX_PUBKEY_ADDRESS = None
    PREFIX_SCRIPT_ADDRESS = None
    PREFIX_SECRET_KEY = None
    BIP44_COIN_TYPE = None


class ChainParamsMainNet(ChainParams):
    B58_PREFIXES_PUBKEY_ADDRESS = ['a', 'Z']
    B58_PREFIXES_SCRIPT_ADDRESS = ['3', '4']
    B58_PREFIXES_SECRET_KEY = ['8', 'Y']
    PREFIX_PUBKEY_ADDRESS = 82
    PREFIX_SCRIPT_ADDRESS = 7
    PREFIX_SECRET_KEY = 210
    BIP44_COIN_TYPE = 136


class ChainParamsTestNet(ChainParams):
    B58_PREFIXES_PUBKEY_ADDRESS = ['T']
    B58_PREFIXES_SCRIPT_ADDRESS = ['2']
    B58_PREFIXES_SECRET_KEY = ['7', 'U']
    PREFIX_PUBKEY_ADDRESS = 65
    PREFIX_SCRIPT_ADDRESS = 178
    PREFIX_SECRET_KEY = 185
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


def validate_address(address: str, dash_network: typing.Optional[str]) -> bool:
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


def validate_wif_privkey(privkey: str, dash_network: str):
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
            if pk_bytes[0] >= 0x74:
                if i == max_iterations - 1: # BLS restriction: the first byte is less than 0x74
                    # after 'limit' iterations we couldn't get the first byte "compatible" with BLS so
                    # the last resort is to change it to a random value < 0x73
                    tmp_pk_bytes = bytearray(pk_bytes)
                    tmp_pk_bytes[0] = randint(0, 0x73)
                    logging.warning('Changing the first byte of the generated BLS key from %s to %s to meet '
                                    'the requirements', str(pk_bytes[0]), str(tmp_pk_bytes[0]))
                    pk_bytes = bytes(tmp_pk_bytes)
                else:
                    continue

            try:
                pk = bls.PrivateKey.from_bytes(pk_bytes)
                pk_bin = pk.serialize()
                return pk_bin.hex()
            except Exception as e:
                logging.warning('Could not process "%s" as a BLS private key. Error details: %s',
                                pk_bytes.hex(), str(e))
        else:
            logging.warning('Skipping the generated key: %s', pk_bytes.hex())
    raise Exception("Could not generate BLS private key")


def bls_privkey_to_pubkey(privkey: str) -> str:
    """
    :param privkey: BLS privkey as a hex string
    :return: BLS pubkey as a hex string.
    """
    pk = bls.PrivateKey.from_bytes(bytes.fromhex(privkey))
    pubkey = pk.get_public_key()
    pubkey_bin = pubkey.serialize()
    return pubkey_bin.hex()


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
    if path_str:
        elems = [int(elem[:-1]) + 0x80000000 if elem.endswith("'") else int(elem) for elem in path_str.split('/')]
    else:
        elems = []
    return elems


def bip32_path_string_append_elem(path_str: str, elem: int):
    path_n = bip32_path_string_to_n(path_str)
    path_n.append(elem)
    return bip32_path_n_to_string(path_n)


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


class COutPoint(object):
    def __init__(self, hash: bytes, index: int):
        self.hash: bytes = hash
        self.index: int = index

    def serialize(self) -> str:
        ser_str = self.hash[::-1].hex()
        ser_str += int(self.index).to_bytes(4, byteorder='little').hex()
        return ser_str


class CTxIn(object):
    def __init__(self, prevout: COutPoint):
        self.prevout: COutPoint = prevout
        self.script = ''
        self.sequence = 0xffffffff

    def serialize(self):
        return self.prevout.serialize() + '00' + self.sequence.to_bytes(4, byteorder='little').hex()


class CMasternodePing(object):
    def __init__(self, mn_outpoint: COutPoint, block_hash: bytes, sig_time: int, rpc_node_protocol_version: int):
        self.mn_outpoint: COutPoint = mn_outpoint  # protocol >= 70209
        self.mn_tx_in = CTxIn(mn_outpoint)  # protocol <= 70208
        self.block_hash: bytes = block_hash
        self.sig_time: int = sig_time
        self.rpc_node_protocol_version: int = rpc_node_protocol_version
        self.sig = None
        self.sig_message = ''
        self.sentinel_is_current = 0
        self.sentinel_version = DEFAULT_SENTINEL_VERSION
        self.daemon_version = DEFAULT_DAEMON_VERSION

    def get_hash(self):
        self.sig_message = self.mn_outpoint.serialize()
        self.sig_message += self.block_hash[::-1].hex()
        self.sig_message += self.sig_time.to_bytes(8, "little").hex()
        self.sig_message += self.sentinel_is_current.to_bytes(1, "little").hex()
        self.sig_message += self.sentinel_version.to_bytes(4, "little").hex()
        self.sig_message += self.daemon_version.to_bytes(4, "little").hex()
        hash = bitcoin.bin_dbl_sha256(bytes.fromhex(self.sig_message))
        return hash

    def sign_message(self, priv_key, dash_network):
        self.sig_message = f'CTxIn(COutPoint({self.mn_outpoint.hash.hex()}, {self.mn_outpoint.index}), ' \
                           f'scriptSig=){self.block_hash.hex()}{str(self.sig_time)}'
        r = ecdsa_sign(self.sig_message, priv_key, dash_network)
        self.sig = base64.b64decode(r)
        return self.sig

    def sign(self, priv_key, dash_network, is_spork6_active: bool):
        if is_spork6_active:
            hash = self.get_hash()
            r = ecdsa_sign_raw(hash, priv_key, dash_network)
            self.sig = base64.b64decode(r)
        else:
            self.sig = self.sign_message(priv_key, dash_network)
        return self.sig

    def serialize(self):
        if self.rpc_node_protocol_version <= 70208:
            ser_str = self.mn_tx_in.serialize()
        else:
            ser_str = self.mn_outpoint.serialize()

        ser_str += self.block_hash[::-1].hex()
        ser_str += self.sig_time.to_bytes(8, byteorder='little').hex()
        ser_str += num_to_varint(len(self.sig)).hex() + self.sig.hex()

        if self.rpc_node_protocol_version >= 70209:
            ser_str += self.sentinel_is_current.to_bytes(1, "little").hex()
            ser_str += self.sentinel_version.to_bytes(4, "little").hex()
            ser_str += self.daemon_version.to_bytes(4, "little").hex()
        else:
            ser_str += '0001000100'

        return ser_str

    def __str__(self):
        ret = f'CMasternodePing(\n' \
              f'  mn_outpoint.hash: {self.mn_outpoint.hash.hex()}\n' \
              f'  mn_outpoint.index: {self.mn_outpoint.index}\n' \
              f'  block_hash: {self.block_hash.hex()}\n' \
              f'  sig_time: {self.sig_time}\n' \
              f'  sig_message: {self.sig_message}\n' \
              f'  sig: {self.sig.hex() if self.sig else "None"}\n' \
              f'  serialized: {self.serialize()}\n)'
        return ret


class CMasternodeBroadcast(object):
    def __init__(self, mn_ip: str,
                 mn_port: int,
                 pubkey_collateral: bytes,
                 pubkey_masternode: bytes,
                 collateral_tx: bytes,
                 collateral_tx_index: int,
                 block_hash: bytes,
                 sig_time: int,
                 protocol_version: int,
                 rpc_node_protocol_version: int,
                 spork6_active: bool):

        self.mn_ip: str = mn_ip
        self.mn_port: int = mn_port
        self.pubkey_collateral: bytes = pubkey_collateral
        self.pubkey_masternode: bytes = pubkey_masternode
        self.sig = None
        self.sig_time: int = sig_time
        self.protocol_version: int = protocol_version
        self.collateral_outpoint = COutPoint(collateral_tx, int(collateral_tx_index))
        self.rpc_node_protocol_version = rpc_node_protocol_version
        self.spork6_active = spork6_active
        self.mn_ping: CMasternodePing = CMasternodePing(self.collateral_outpoint, block_hash, sig_time,
                                                        rpc_node_protocol_version)

    def get_message_to_sign(self):
        str_for_serialize = self.mn_ip + ':' + str(self.mn_port) + str(self.sig_time) + \
            binascii.unhexlify(bitcoin.hash160(self.pubkey_collateral))[::-1].hex() + \
            binascii.unhexlify(bitcoin.hash160(self.pubkey_masternode))[::-1].hex() + \
            str(self.protocol_version)
        return str_for_serialize

    def sign(self, collateral_bip32_path: str, hw_sign_message_fun: typing.Callable, hw_session,
             mn_privkey_wif: str, dash_network: str):

        self.mn_ping.sign(mn_privkey_wif, dash_network, is_spork6_active=self.spork6_active)

        str_for_serialize = self.get_message_to_sign()
        self.sig = hw_sign_message_fun(hw_session, collateral_bip32_path, str_for_serialize)

        return self.sig

    def serialize(self):
        if not self.sig:
            raise Exception('Message not signed.')

        if self.rpc_node_protocol_version <= 70208:
            ser_str = self.mn_ping.mn_tx_in.serialize()
        else:
            ser_str = self.mn_ping.mn_outpoint.serialize()

        addr = '00000000000000000000ffff'
        ip_elems = map(int, self.mn_ip.split('.'))
        for i in ip_elems:
            addr += i.to_bytes(1, byteorder='big').hex()
        addr += int(self.mn_port).to_bytes(2, byteorder='big').hex()

        ser_str += addr
        ser_str += num_to_varint(len(self.pubkey_collateral)).hex() + self.pubkey_collateral.hex()
        ser_str += num_to_varint(len(self.pubkey_masternode)).hex() + self.pubkey_masternode.hex()
        ser_str += num_to_varint(len(self.sig.signature)).hex() + self.sig.signature.hex()
        ser_str += self.sig_time.to_bytes(8, byteorder='little').hex()
        ser_str += int(self.protocol_version).to_bytes(4, byteorder='little').hex()
        ser_str += self.mn_ping.serialize()

        return ser_str

    def __str__(self):
        ret = f'\nCMasternodeBroadcast(\n' \
              f'  pubkey_collateral: {self.pubkey_collateral.hex()}\n' \
              f'  pubkey_masternode: {self.pubkey_masternode.hex()}\n' \
              f'{str(self.mn_ping)})'
        return ret
