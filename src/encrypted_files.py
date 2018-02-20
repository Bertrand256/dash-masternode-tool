#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04

import base64
import os
from typing import ByteString, List, Tuple
from PyQt5.QtWidgets import QMessageBox
from cryptography.fernet import Fernet, InvalidToken
from app_defs import HWType, get_note_url
from app_utils import SHA256, write_bytes_buf, write_int_list_buf, read_bytes_from_file, read_int_list_from_file
from common import CancelException
from dash_utils import num_to_varint, read_varint_from_file, bip32_path_n_to_string
from hw_common import HwSessionInfo
from hw_intf import hw_encrypt_value, hw_decrypt_value, hw_sign_message, get_address_and_pubkey
from wnd_utils import WndUtils


DMT_ENCRYPTED_DATA_PREFIX = b'DMTEF'
ENC_FILE_BLOCK_SIZE = 1000000


class NotConnectedToHardwareWallet (Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, *kwargs)


def prepare_hw_encryption_attrs(hw_session: HwSessionInfo, label: str) -> \
        Tuple[int, int, List[int], ByteString, ByteString, ByteString]:
    """

    :param hw_session:
    :param label:
    :return: 0: protocol id
             1: hw type id
             1: hw passphrase encoding
             2: hw bip32 path usad to encodind
    """
    # generate a new random password that will be used to encrypt with Trezor method + Fernet
    protocol = 1
    hw_type_bin = {
            HWType.trezor: 1,
            HWType.keepkey: 2,
            HWType.ledger_nano_s: 3
        }[hw_session.hw_type]

    key = Fernet.generate_key()  # encryption key
    key_bin = base64.urlsafe_b64decode(key)

    bip32_path_n = [10, 100, 1000]

    if hw_session.hw_type in (HWType.trezor, HWType.keepkey):
        # for trezor method, for encryption we use the raw key and the key encrypted with a device
        # will be part of a header
        encrypted_key_bin, pub_key = hw_encrypt_value(hw_session, bip32_path_n, label=label, value=key_bin)
        pub_key_hash = SHA256.new(pub_key).digest()
        return (protocol, hw_type_bin, bip32_path_n, key, encrypted_key_bin, pub_key_hash)

    elif hw_session.hw_type == HWType.ledger_nano_s:
        # Ledger Nano S does not have encryption/decryption features, so for encryption and decryptionwe will use
        # a hash of a signed message, where the message the raw key itself;
        # The raw key will be part of the encrypted header.

        display_label = f'<b>Click the sign message confirmation button on the <br>hardware wallet to encrypt \'{label}\'.</b>'
        bip32_path_str = bip32_path_n_to_string(bip32_path_n)
        sig = hw_sign_message(hw_session, bip32_path_str, key_bin.hex(), display_label=display_label)
        adr_pk = get_address_and_pubkey(hw_session, bip32_path_str)

        pub_key_hash = SHA256.new(adr_pk.get('publicKey')).digest()
        enc_key_hash = SHA256.new(sig.signature).digest()
        enc_key_hash = base64.urlsafe_b64encode(enc_key_hash)

        return (protocol, hw_type_bin, bip32_path_n, enc_key_hash, key_bin, pub_key_hash)


def write_file_encrypted(file_name: str, hw_session: HwSessionInfo, data: bytes):
    label = os.path.basename(file_name)

    protocol, hw_type_bin, bip32_path_n, encryption_key, encrypted_key_bin, pub_key_hash = \
        prepare_hw_encryption_attrs(hw_session, label)

    fer = Fernet(encryption_key)

    with open(file_name, 'wb') as f_ptr:

        header = DMT_ENCRYPTED_DATA_PREFIX + \
                 num_to_varint(protocol) + num_to_varint(hw_type_bin) + \
                 write_bytes_buf(bytearray(base64.b64encode(bytearray(label, 'utf-8')))) + \
                 write_bytes_buf(encrypted_key_bin) + \
                 write_int_list_buf(bip32_path_n) + \
                 write_bytes_buf(pub_key_hash)
        f_ptr.write(header)

        # slice the input data into ENC_FILE_BLOCK_SIZE-byte chunks, encrypt them and
        # write to file; each block will be preceded with the length of the encrypted
        # data chunk size
        begin_idx = 0
        while True:
            data_left = len(data) - begin_idx
            if data_left <= 0:
                break
            cur_input_chunk_size = min(ENC_FILE_BLOCK_SIZE, data_left)

            data_enc_base64 = fer.encrypt(data[begin_idx : begin_idx+cur_input_chunk_size])
            data_enc = base64.urlsafe_b64decode(data_enc_base64)
            cur_chunk_size_bin = len(data_enc).to_bytes(8, byteorder='little')  # write the size of the data chunk
            f_ptr.write(cur_chunk_size_bin)     # write the data
            f_ptr.write(data_enc)     # write the data
            begin_idx += cur_input_chunk_size


def read_file_encrypted(file_name: str, ret_attrs: dict, hw_session: HwSessionInfo):
    ret_attrs['encrypted'] = False

    with open(file_name, 'rb') as f_ptr:

        data = f_ptr.read(len(DMT_ENCRYPTED_DATA_PREFIX))
        if data == DMT_ENCRYPTED_DATA_PREFIX:
            ret_attrs['encrypted'] = True

            protocol = read_varint_from_file(f_ptr)
            if protocol == 1:  # with Trezor method + Fernet

                hw_type_bin = read_varint_from_file(f_ptr)
                hw_type = {
                        1: HWType.trezor,
                        2: HWType.keepkey,
                        3: HWType.ledger_nano_s
                    }.get(hw_type_bin)

                if hw_type:

                    if not hw_session.hw_type:
                        # probably application is calling this function before configuration was loaded (e.g. when
                        # decrypting encrypted config file) set the hw type to that from encrypted file and try to
                        # connect to the device
                        hw_session.app_config.hw_type = hw_type

                    if not hw_session.hw_client:
                        hw_session.app_config.hw_type = hw_type
                        if not hw_session.hw_connect():
                            raise NotConnectedToHardwareWallet(
                                f'This file was encrypted with {HWType.get_desc(hw_type)} hardware wallet, which'
                                ' has to be connected to decrypt the file.')

                    if not ((hw_type in (HWType.trezor, HWType.keepkey) and
                             hw_session.hw_type in (HWType.trezor, HWType.keepkey)) or (hw_type == hw_session.hw_type)):
                        raise Exception(f'This file was encrypted with a different hardware wallet type '
                                        f'({HWType.get_desc(hw_type)}) than the one currently connected '
                                        f'({HWType.get_desc(hw_session.hw_type)}). \n\n'
                                        f'Encryption methods for these devices are not compatible.')

                    data_label_bin = read_bytes_from_file(f_ptr)
                    label = base64.urlsafe_b64decode(data_label_bin).decode('utf-8')

                    encrypted_key_bin = read_bytes_from_file(f_ptr)

                    bip32_path_n = read_int_list_from_file(f_ptr)

                    pub_key_hash_hdr = read_bytes_from_file(f_ptr)

                    while True:
                        if hw_session.hw_type in (HWType.trezor, HWType.keepkey):
                            key_bin, pub_key = hw_decrypt_value(hw_session, bip32_path_n, label=label,
                                                                value=encrypted_key_bin)
                        elif hw_session.hw_type == HWType.ledger_nano_s:

                            display_label = f'<b>Click the sign message confirmation button on the <br>hardware wallet ' \
                                            f'to decrypt \'{label}\'.</b>'
                            bip32_path_str = bip32_path_n_to_string(bip32_path_n)
                            sig = hw_sign_message(hw_session, bip32_path_str, encrypted_key_bin.hex(),
                                                  display_label=display_label)
                            adr_pk = get_address_and_pubkey(hw_session, bip32_path_str)

                            pub_key = adr_pk.get('publicKey')
                            key_bin = SHA256.new(sig.signature).digest()

                        else:
                            raise Exception('Invalid hardware wallet type.')

                        pub_key_hash = SHA256.new(pub_key).digest()

                        if pub_key_hash_hdr == pub_key_hash:
                            break

                        url = get_note_url('DMT0003')
                        if WndUtils.queryDlg(
                                message='Inconsistency between encryption and decryption keys.\n\n' 
                                        'The reason may be using a different passphrase than it was used '
                                        'for encryption or running another application communicating with the device '
                                        f'simultaneously, like Trezor web wallet (see <a href="{url}">here</a>).\n\n' 
                                        'Do you want to try again?',
                                buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                            raise CancelException('User cancelled.')

                    key = base64.urlsafe_b64encode(key_bin)
                    fer = Fernet(key)

                    while True:
                        # data is written in blocks; if front of each block there is a block size value
                        data_bin = f_ptr.read(8)
                        if len(data_bin) == 0:
                            break  # end of file
                        elif len(data_bin) < 8:
                            raise ValueError('File end before read completed.')

                        data_chunk_size = int.from_bytes(data_bin, byteorder='little')
                        if data_chunk_size < 0 or data_chunk_size > 2000000000:
                            raise ValueError('Data corrupted: invalid data chunk size.')

                        data_bin = f_ptr.read(data_chunk_size)
                        if data_chunk_size != len(data_bin):
                            raise ValueError('File end before read completed.')
                        data_base64 = base64.urlsafe_b64encode(data_bin)
                        try:
                            data_decr = fer.decrypt(data_base64)
                        except InvalidToken:
                            raise Exception('Couldn\'t decrypt file (IvalidToken error). The file is probably '
                                            'corrupted or is encrypted with a different encryption method.')
                        yield data_decr
                else:
                    raise ValueError('Invalid hardware wallet type value.')
            else:
                raise ValueError('Invalid protocol value.')
        else:
            # the data inside the file isn't encrypted

            # read and yield raw data
            while True:
                # data is written in blocks; if front of each block there is a block size value
                data += f_ptr.read(ENC_FILE_BLOCK_SIZE)
                if not len(data):
                    break
                yield data
                data = bytes()

