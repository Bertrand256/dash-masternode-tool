#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04

import base64
from typing import Optional

from PyQt5.QtWidgets import QDialog
import wnd_utils as wnd_utils
import hw_intf
from app_runtime_data import AppRuntimeData
from hw_common import HWType
from common import CancelException
from dash_utils import ecdsa_sign
from ui import ui_sign_message_dlg
import logging


class SignMessageDlg(QDialog, ui_sign_message_dlg.Ui_SignMessageDlg, wnd_utils.WndUtils):
    def __init__(self, main_ui, hw_session: Optional[hw_intf.HwSessionInfo], rt_data: Optional[AppRuntimeData],
                 bip32path: Optional[str], address: Optional[str], private_key: Optional[str] = ""):
        QDialog.__init__(self, parent=main_ui)
        self.hw_session = hw_session
        self.rt_data = rt_data
        self.bip32path = bip32path
        self.address = address
        self.private_key = private_key
        self.app_config = main_ui.app_config
        self.setupUi(self)

    def setupUi(self, dialog: QDialog):
        ui_sign_message_dlg.Ui_SignMessageDlg.setupUi(self, self)
        self.setWindowTitle('Sign message')
        self.btnSignMessage.clicked.connect(self.btnSignMessageClick)
        self.btnClose.clicked.connect(self.close)
        self.lblSigningAddress.setText(self.address)

    def btnSignMessageClick(self):
        try:
            msg_to_sign = self.edtMessageToSign.toPlainText()
            if msg_to_sign:
                # for ledger HW check if the message contains non-ascii characters
                if self.hw_session and self.bip32path and self.address:
                    if self.hw_session.hw_type == HWType.ledger_nano:
                        try:
                            msg_to_sign.encode('ascii')
                        except UnicodeEncodeError:
                            self.warn_msg('Ledger wallets cannot sign non-ASCII and non-printable characters. Please '
                                         'remove them from your message and try again.')
                            return
                        if len(msg_to_sign) > 140:
                            self.warn_msg('Ledger wallets cannot sign messages longer than 140 characters. Please '
                                         'remove any extra characters and try again.')
                            return

                    sig = hw_intf.hw_sign_message(self.hw_session, self.rt_data.hw_coin_name, self.bip32path,
                                                  msg_to_sign)
                    signed = base64.b64encode(sig.signature)
                    self.edtSignedMessage.setPlainText(signed.decode('ascii'))
                    self.edtSignedMessage.update()
                    if sig.address != self.address:
                        self.warn_msg('Message signed but signing address (%s) for BIP32 path (%s) differs from '
                                     'required one: %s\n\nDid you enter correct passphrase?' % (sig.address, self.bip32path, self.address))
                elif self.private_key:
                    sig = ecdsa_sign(msg_to_sign, self.private_key, self.app_config.dash_network)
                    self.edtSignedMessage.setPlainText(sig)
                    self.edtSignedMessage.update()
                else:
                    raise Exception('Invalid arguments')
            else:
                self.error_msg('Empty message cannot be signed.')

        except CancelException:
            logging.warning('CancelException')

        except Exception as e:
            logging.exception('Sign message exception:')
            self.error_msg(str(e))

