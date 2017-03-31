#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

import binascii

import bitcoin

from src import base58


def pubkey_to_address(pubkey):
    """
    Based on project: https://github.com/chaeplin/dashmnb with some changes related to usage of bitcoin library.
    """
    pubkey_bin = bytes.fromhex(pubkey)
    pub_hash = bitcoin.bin_hash160(pubkey_bin)
    data = bytes([76]) + pub_hash
    checksum = bitcoin.bin_dbl_sha256(data)[0:4]
    return base58.b58encode(data + checksum)


def generate_privkey():
    """
    Based on Andreas Antonopolous work from 'Mastering Bitcoin'.
    """
    valid = False
    privkey = 0
    while not valid:
        privkey = bitcoin.random_key()
        decoded_private_key = bitcoin.decode_privkey(privkey, 'hex')
        valid = 0 < decoded_private_key < bitcoin.N
    data = bytes([204]) + bytes.fromhex(privkey)
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
        return int(253).to_bytes(1, byteorder='big') + \
            x.to_bytes(2, byteorder='little')
    elif x < 4294967296:
        return int(254).to_bytes(1, byteorder='big') + \
            x.to_bytes(4, byteorder='little')
    else:
        return int(255).to_bytes(1, byteorder='big') + \
            x.to_bytes(8, byteorder='little')


def wif_to_privkey(string):
    """
    Based on project: https://github.com/chaeplin/dashmnb with some changes related to usage of bitcoin library.
    """
    wif_compressed = 52 == len(string)
    pvkeyencoded = base58.b58decode(string).hex()
    wifversion = pvkeyencoded[:2]
    wif_prefix = 204
    checksum = pvkeyencoded[-8:]

    vs = bytes.fromhex(pvkeyencoded[:-8])
    check = binascii.unhexlify(bitcoin.dbl_sha256(vs))[0:4]

    if wifversion == wif_prefix.to_bytes(1, byteorder='big').hex() and checksum == check.hex():
        if wif_compressed:
            privkey = pvkeyencoded[2:-10]
        else:
            privkey = pvkeyencoded[2:-8]

        return privkey
    else:
        return None


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


def ecdsa_sign(msg, priv):
    """
    Based on project: https://github.com/chaeplin/dashmnb with some changes related to usage of bitcoin library.
    """
    v, r, s = bitcoin.ecdsa_raw_sign(electrum_sig_hash(msg), priv)
    sig = bitcoin.encode_sig(v, r, s)
    pubkey = bitcoin.privkey_to_pubkey(wif_to_privkey(priv))

    ok = bitcoin.ecdsa_raw_verify(electrum_sig_hash(msg), bitcoin.decode_sig(sig), pubkey)
    if not ok:
        raise Exception('Bad signature!')
    return sig


def serialize_input_str(tx, prevout_n, sequence, script_sig):
    """
    Based on project: https://github.com/chaeplin/dashmnb.
    """
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
