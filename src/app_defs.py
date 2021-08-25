#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-03
import collections
import logging
from typing import List

APP_NAME_SHORT = 'firo-masternode-tool'
APP_NAME_LONG = 'Firo Masternode Tool'
APP_NAME_FOR_CRYPTING = 'Znode Tool'
APP_DATA_DIR_NAME = '.firo-masternode-tool'
PROJECT_URL = 'https://github.com/firoorg/firo-masternode-tool'
FEE_DUFF_PER_BYTE = 1
MIN_TX_FEE = 1000
SCREENSHOT_MODE = False
DEBUG_MODE = False
DEFAULT_LOG_FORMAT = '%(asctime)s %(levelname)s|%(name)s|%(threadName)s|%(filename)s|%(funcName)s|%(message)s'
KnownLoggerType = collections.namedtuple('KnownLoggerType', 'name external')
APP_PATH = ''
APP_IMAGE_DIR = ''


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


def get_doc_url(doc_file_name):
    """
    Returns an URL to a project documentation page.
    :return: URL
    """
    return PROJECT_URL + f'/blob/master/doc/{doc_file_name}'


__KNOWN_LOGGERS = [
    KnownLoggerType(name='dmt.wallet_dlg', external=False),
    KnownLoggerType(name='dmt.bip44_wallet', external=False),
    KnownLoggerType(name='dmt.dashd_intf', external=False),
    KnownLoggerType(name='dmt.db_intf', external=False),
    KnownLoggerType(name='dmt.proposals', external=False),
    KnownLoggerType(name='dmt.ext_item_model', external=False),
    KnownLoggerType(name='dmt.hw_intf_trezor', external=False),
    KnownLoggerType(name='dmt.reg_masternode', external=False),
    KnownLoggerType(name='dmt.transaction_dlg', external=False),
    KnownLoggerType(name='dmt.app_cache', external=False),
    KnownLoggerType(name='BitcoinRPC', external=True),
    KnownLoggerType(name='urllib3.connectionpool', external=True),
    KnownLoggerType(name='trezorlib.transport', external=True),
    KnownLoggerType(name='trezorlib.transport.bridge', external=True),
    KnownLoggerType(name='trezorlib.client', external=True),
    KnownLoggerType(name='trezorlib.protocol_v1', external=True),
]


def get_known_loggers() -> List[KnownLoggerType]:
    ll = []
    # add existing loggers which are not known: some new libraries (or new versions) can intruduce new
    # loggers
    for lname in logging.Logger.manager.loggerDict:
        l = logging.Logger.manager.loggerDict[lname]
        if isinstance(l, logging.Logger):
            if not any(lname in name for name in __KNOWN_LOGGERS):
                __KNOWN_LOGGERS.append(KnownLoggerType(name=lname, external=True))
    return __KNOWN_LOGGERS[:]
