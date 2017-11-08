#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03


class HardwareWalletCancelException(Exception):
    pass


class HardwareWalletPinException(Exception):
    def __init__(self, msg):
        self.msg = msg


def clean_bip32_path(bip32_path):
    # Keepkey and Ledger don't accept BIP32 "m/" prefix
    bip32_path.strip()
    if bip32_path.lower().find('m/') >= 0:
        # removing m/ prefix because of keepkey library
        bip32_path = bip32_path[2:]
    return bip32_path

