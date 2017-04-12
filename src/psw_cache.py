#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import threading

from PyQt5.QtWidgets import QInputDialog, QMessageBox
from PyQt5.QtWidgets import QLineEdit

from src.wnd_utils import WndUtils


class SshPassCache(object):
    cache = {}

    @staticmethod
    def get_password(window, username, host):
        key = username + '@' + host
        password = SshPassCache.cache.get(key)
        if not password:
            def query_psw():
                password, ok = QInputDialog.getText(window, 'Password Dialog',
                                                    'Enter password for ' + key + ':', echo=QLineEdit.Password)
                return password, ok

            if threading.current_thread() != threading.main_thread():
                password, ok = WndUtils.callFunInTheMainThread(query_psw)
            else:
                password, ok = query_psw()

        return password

    @staticmethod
    def save_password(username, host, password):
        SshPassCache.cache[username + '@' + host] = password

