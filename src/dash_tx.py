#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Dash-Electrum - lightweight Dash client
# Copyright (C) 2018 Dash Developers
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import struct

def bh2u(x: bytes) -> str:
    """
    str with hex representation of a bytes-like object

    >>> x = bytes((1, 2, 10))
    >>> bh2u(x)
    '01020A'
    """
    return x.hex()


def reverse(x: str):
    ret = bytearray.fromhex(x)
    ret.reverse()
    return ret


def serialize_cbTx(tx):
    res = (
        struct.pack('<H', tx["cbTx"]["version"]) +
        struct.pack('<I', tx["cbTx"]["height"]) +
        reverse(tx["cbTx"]["merkleRootMNList"])
    )
    if tx["cbTx"]["version"] > 1:
        res += reverse(tx["cbTx"]["merkleRootQuorums"])
    return bh2u(res)

def serialize_Lelantus(tx):
    return tx["lelantusData"]

class DashTxType:
    CLASSICAL_TX = 0
    SPEC_PRO_REG_TX = 1
    SPEC_PRO_UP_SERV_TX = 2
    SPEC_PRO_UP_REG_TX = 3
    SPEC_PRO_UP_REV_TX = 4
    SPEC_CB_TX = 5
    LELANTUS_JSPLIT = 8
