#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

from PyQt5.QtWidgets import QInputDialog
from PyQt5.QtWidgets import QLineEdit


class SshPassCache(object):
    cache = {}

    @staticmethod
    def get_password(window, username, host):
        key = username + '@' + host
        password = SshPassCache.cache.get(key)
        if not password:
            password, ok = QInputDialog.getText(window, 'Password Dialog',
                                                'Enter password for ' + key + ':', echo=QLineEdit.Password)
        return password

    @staticmethod
    def save_password(username, host, password):
        SshPassCache.cache[username + '@' + host] = password

