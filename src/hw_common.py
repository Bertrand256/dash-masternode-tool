#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03


class HardwareWalletCancelException(Exception):
    pass


class HardwareWalletPinException(Exception):
    def __init__(self, msg):
        self.msg = msg
