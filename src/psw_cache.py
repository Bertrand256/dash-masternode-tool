#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import threading

from PyQt5.QtWidgets import QInputDialog, QMessageBox
from PyQt5.QtWidgets import QLineEdit
from wnd_utils import WndUtils


class UserCancelledConnection(Exception):
    pass


class SshPassCache(object):
    cache = {}
    parent_window = None

    @staticmethod
    def ask_for_password(username, host, message=None):
        if not SshPassCache.parent_window:
            raise Exception('SshPassCache not initialized')

        def query_psw(msg):
            password, ok = QInputDialog.getText(SshPassCache.parent_window, 'Password Dialog',
                                                msg, echo=QLineEdit.Password)
            return password, ok

        if not message:
            message = 'Enter password for ' + username + '@' + host + ':'

        if threading.current_thread() != threading.main_thread():
            password, ok = WndUtils.call_in_main_thread(query_psw, message)
        else:
            password, ok = query_psw(message)

        if not ok:
            raise UserCancelledConnection
        return password

    @staticmethod
    def get_password(username, host, message=None):
        if not SshPassCache.parent_window:
            raise Exception('SshPassCache not initialized')

        if not message:
            message = 'Enter password for ' + username + '@' + host + ':'
        else:
            message = message + ':'

        key = username + '@' + host
        password = SshPassCache.cache.get(key)
        if not password:
            password = SshPassCache.ask_for_password(username, host, message)

        return password

    @staticmethod
    def save_password(username, host, password):
        SshPassCache.cache[username + '@' + host] = password

    @staticmethod
    def set_parent_window(parent_window):
        SshPassCache.parent_window = parent_window
