#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

import binascii
import base64
import bitcoin
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base58


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


def bip32_path_n_to_string(path_n):
    ret = ''
    for elem in path_n:
        if elem >= 0x80000000:
            ret += ('/' if ret else '') + str(elem - 0x80000000) + "'"
        else:
            ret += ('/' if ret else '') + str(elem)
    return ret


def encrypt(input_str, key):
    salt = b'D9\x82\xbfSibW(\xb1q\xeb\xd1\x84\x118'
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    key = base64.urlsafe_b64encode(kdf.derive(key.encode('utf-8')))
    fer = Fernet(key)
    h = fer.encrypt(input_str.encode('utf-8'))
    h = h.hex()
    return h


def decrypt(input_str, key):
    try:
        input_str = binascii.unhexlify(input_str)
        salt = b'D9\x82\xbfSibW(\xb1q\xeb\xd1\x84\x118'
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(key.encode('utf-8')))
        fer = Fernet(key)
        h = fer.decrypt(input_str)
        h = h.decode('utf-8')
    except:
        return ''
    return h


def seconds_to_human(number_of_seconds, out_seconds=True, out_minutes=True, out_hours=True):
    """
    Converts number of seconds to string representation.
    :param out_seconds: False, if seconds part in output is to be trucated
    :param number_of_seconds: number of seconds.
    :return: string representation of time delta
    """
    human_strings = []

    weeks = 0
    days = 0
    hours = 0
    if number_of_seconds > 604800:
        # days
        weeks = int(number_of_seconds / 604800)
        number_of_seconds = number_of_seconds - (weeks * 604800)
        elem_str = str(int(weeks)) + ' week'
        if weeks > 1:
            elem_str += 's'
        human_strings.append(elem_str)

    if number_of_seconds > 86400:
        # days
        days = int(number_of_seconds / 86400)
        number_of_seconds = number_of_seconds - (days * 86400)
        elem_str = str(int(days)) + ' day'
        if days > 1:
            elem_str += 's'
        human_strings.append(elem_str)

    if (out_hours and weeks + days > 0) and number_of_seconds > 3600:
        hours = int(number_of_seconds / 3600)
        number_of_seconds = number_of_seconds - (hours * 3600)
        elem_str = str(int(hours)) + ' hour'
        if hours > 1:
            elem_str += 's'
        human_strings.append(elem_str)

    if (out_minutes and weeks + days + hours > 0) and number_of_seconds > 60:
        minutes = int(number_of_seconds / 60)
        number_of_seconds = number_of_seconds - (minutes * 60)
        elem_str = str(int(minutes)) + ' minute'
        if minutes > 1:
            elem_str += 's'
        human_strings.append(elem_str)

    if out_seconds and number_of_seconds >= 1:
        elem_str = str(int(number_of_seconds)) + ' second'
        if number_of_seconds > 1:
            elem_str += 's'
        human_strings.append(elem_str)

    return ' '.join(human_strings)
