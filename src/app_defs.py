#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-03


APP_NAME_SHORT = 'DashMasternodeTool'
APP_NAME_LONG = 'Dash Masternode Tool'
APP_DATA_DIR_NAME = '.dmt'
PROJECT_URL = 'https://github.com/Bertrand256/dash-masternode-tool'
FEE_DUFF_PER_BYTE = 1
MIN_TX_FEE = 1000
SCREENSHOT_MODE = False


class HWType:
    trezor = 'TREZOR'
    keepkey = 'KEEPKEY'
    ledger_nano_s = 'LEDGERNANOS'

    @staticmethod
    def get_desc(hw_type):
        if hw_type == HWType.trezor:
            return 'Trezor'
        elif hw_type == HWType.keepkey:
            return 'KeepKey'
        elif hw_type == HWType.ledger_nano_s:
            return 'Ledger Nano S'
        else:
            return '???'


def get_note_url(note_symbol):
    """
    Returns an URL to a project documentation page related to the note symbol passed as an argument.
    :param note_symbol: Symbol of the note, for example: DMT00001
    :return: URL
    """
    return PROJECT_URL + f'/blob/master/doc/notes.md#note-{note_symbol.lower()}'

