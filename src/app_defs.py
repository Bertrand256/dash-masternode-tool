#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-03
import collections
import logging
from enum import Enum
from typing import List

from PyQt5.QtGui import QColor

APP_NAME_SHORT = 'DashMasternodeTool'
APP_NAME_LONG = 'Dash Masternode Tool'
APP_DATA_DIR_NAME = '.dmt'
PROJECT_URL = 'https://github.com/Bertrand256/dash-masternode-tool'
FEE_DUFF_PER_BYTE = 1
MIN_TX_FEE = 1000
SCREENSHOT_MODE = False
DEBUG_MODE = False
DEFAULT_LOG_FORMAT = '%(asctime)s %(levelname)s|%(name)s|%(threadName)s|%(filename)s|%(funcName)s|%(message)s'
KnownLoggerType = collections.namedtuple('KnownLoggerType', 'name external')
APP_PATH = ''
APP_IMAGE_DIR = ''
BROWSER_USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) ' \
                     'Chrome/88.0.4324.152 Safari/537.36'

COLOR_WARNING_STR = '#e65c00'
COLOR_WARNING = QColor(COLOR_WARNING_STR)
COLOR_ERROR_STR = 'red'
COLOR_ERROR = QColor(COLOR_ERROR_STR)


class AppTextMessageType(Enum):
    INFO = 'info'
    WARN = 'warn'
    ERROR = 'error'


class DispMessage(object):
    NEW_VERSION = 1
    DASH_NET_CONNECTION = 2
    OTHER_1 = 3
    OTHER_2 = 4

    def __init__(self, message: str, type: AppTextMessageType):
        """
        :param type: 'warn'|'error'|'info'
        :param message: a message
        """
        self.message = message
        self.type: AppTextMessageType = type
        self.hidden = False


def get_note_url(note_symbol):
    """
    Returns an URL to a project documentation page related to the note symbol passed as an argument.
    :param note_symbol: Symbol of the note, for example: DMT00001
    :return: URL
    """
    return PROJECT_URL + f'/blob/master/doc/notes.md#note-{note_symbol.lower()}'


def get_doc_url(doc_file_name: str, use_doc_subdir=True):
    """
    Returns an URL to a project documentation page.
    :return: URL
    """
    return PROJECT_URL + f'/blob/master/{"doc/" if use_doc_subdir else "" }{doc_file_name}'


__KNOWN_LOGGERS = [
    KnownLoggerType(name='dmt.wallet_dlg', external=False),
    KnownLoggerType(name='dmt.bip44_wallet', external=False),
    KnownLoggerType(name='dmt.dashd_intf', external=False),
    KnownLoggerType(name='dmt.db_intf', external=False),
    KnownLoggerType(name='dmt.proposals', external=False),
    KnownLoggerType(name='dmt.ext_item_model', external=False),
    KnownLoggerType(name='dmt.hw_intf', external=False),
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
    # add existing loggers which are not known: some new libraries (or new versions) can introduce new
    # loggers
    for lname in logging.Logger.manager.loggerDict:
        l = logging.Logger.manager.loggerDict[lname]
        if isinstance(l, logging.Logger):
            if not any(lname in name for name in __KNOWN_LOGGERS):
                __KNOWN_LOGGERS.append(KnownLoggerType(name=lname, external=True))
    return __KNOWN_LOGGERS[:]