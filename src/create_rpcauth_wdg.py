#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2021-05

import hmac
from binascii import hexlify
from os import urandom
from enum import Enum
from typing import Optional

from PyQt5.QtCore import pyqtSlot
from PyQt5.QtWidgets import QWidget, QApplication

from hw_common import HWDevice
from ui.ui_create_rpcauth_wdg import Ui_WdgCreateRpcauth
from wallet_tools_common import ActionPageBase
from hw_intf import HWDevices
from wnd_utils import WndUtils


class Step(Enum):
    STEP_DESCRIPTION = 0
    STEP_ENTER_USER_PASS = 1
    STEP_FINISHED = 2


class Pages(Enum):
    PAGE_DESCRIPTION = 0
    PAGE_ENTER_USER_PASS = 1
    PAGE_SUMMARY = 2


class WdgCreateRpcauth(QWidget, Ui_WdgCreateRpcauth, ActionPageBase):
    def __init__(self, parent, hw_devices: HWDevices):
        QWidget.__init__(self, parent=parent)
        Ui_WdgCreateRpcauth.__init__(self)
        ActionPageBase.__init__(self, parent, parent.app_config, hw_devices, 'Create rpcauth')

        self.cur_hw_device: Optional[HWDevice] = self.hw_devices.get_selected_device()
        self.current_step: Step = Step.STEP_DESCRIPTION
        self.rpcauth = ''
        self.setupUi(self)

    def setupUi(self, dlg):
        Ui_WdgCreateRpcauth.setupUi(self, self)
        # WndUtils.change_widget_font_attrs(self.lblDescription, point_size_diff=3, bold=True)
        self.pages.setCurrentIndex(Pages.PAGE_DESCRIPTION.value)

    def initialize(self):
        ActionPageBase.initialize(self)
        self.current_step: Step = Step.STEP_DESCRIPTION
        self.set_btn_cancel_visible(True)
        self.set_btn_back_visible(True)
        self.set_btn_continue_visible(True)
        self.set_hw_panel_visible(False)
        self.update_ui()
        self.set_controls_initial_state_for_step(False)

    def set_current_step(self, step: Step):
        if self.current_step != step:
            self.current_step = step
            self.set_controls_initial_state_for_step(False)
            self.update_ui()

    def go_to_next_step(self):
        try:
            if self.current_step == Step.STEP_DESCRIPTION:
                self.set_current_step(Step.STEP_ENTER_USER_PASS)

            elif self.current_step == Step.STEP_ENTER_USER_PASS:
                if self.generate_rpcauth():
                    self.set_current_step(Step.STEP_FINISHED)
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    def go_to_prev_step(self):
        if self.current_step == Step.STEP_DESCRIPTION:
            self.exit_page()
            return
        elif self.current_step == Step.STEP_ENTER_USER_PASS:
            self.current_step = Step.STEP_DESCRIPTION
        elif self.current_step == Step.STEP_FINISHED:
            self.current_step = Step.STEP_ENTER_USER_PASS
        else:
            raise Exception('Invalid step')
        self.set_controls_initial_state_for_step(True)
        self.update_ui()

    def set_controls_initial_state_for_step(self, moving_back: bool):
        self.set_btn_close_visible(False)
        self.set_btn_close_enabled(False)
        self.set_btn_continue_visible(True)

        if self.current_step == Step.STEP_DESCRIPTION:
            self.set_btn_cancel_enabled(True)
            self.set_btn_back_enabled(True)
            self.set_btn_continue_enabled(True)
        elif self.current_step == Step.STEP_ENTER_USER_PASS:
            self.set_btn_cancel_enabled(True)
            self.set_btn_back_enabled(True)
            self.set_btn_continue_enabled(True)
        elif self.current_step == Step.STEP_FINISHED:
            self.set_btn_cancel_enabled(True)
            self.set_btn_back_enabled(True)
            self.set_btn_continue_visible(False)
            self.set_btn_close_visible(True)
            self.set_btn_close_enabled(True)

    def update_ui(self):
        try:
            self.show_action_page()
            if self.current_step == Step.STEP_DESCRIPTION:
                self.update_action_subtitle('')
                self.pages.setCurrentIndex(Pages.PAGE_DESCRIPTION.value)

            elif self.current_step == Step.STEP_ENTER_USER_PASS:
                self.update_action_subtitle('enter username and password')
                self.pages.setCurrentIndex(Pages.PAGE_ENTER_USER_PASS.value)

            elif self.current_step == Step.STEP_FINISHED:
                self.update_action_subtitle('summary')
                self.display_summary()
                self.pages.setCurrentIndex(Pages.PAGE_SUMMARY.value)
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    def generate_rpcauth(self) -> bool:
        user = self.edtUser.text()
        password = self.edtPassword.text()
        ret = True
        if not user:
            WndUtils.error_msg('Enter username')
            ret = False
        if not password:
            WndUtils.error_msg('Enter password')
            ret = False

        salt = hexlify(urandom(16)).decode()
        m = hmac.new(bytearray(salt, 'utf-8'), bytearray(password, 'utf-8'), 'SHA256')
        password_hmac = m.hexdigest()
        self.rpcauth = f'rpcauth={user}:{salt}${password_hmac}'

        return ret

    def display_summary(self):
        msg = '<h3>Operation finished</h3>' \
              'Enter the following string into your <code>dash.conf</code> file and restart the <code>dashd</code> ' \
              'process:<br><br>' \
              f'<small><code>{self.rpcauth}</code></small><br><a href="copy_rpcauth">copy to clipboard</a><br><br>' \
              'Use the following credentials when connecting to the node via RPC interface:<br>' \
              f' <b>username</b>: {self.edtUser.text()}<br>' \
              f' <b>password</b>: {self.edtPassword.text()}'
        self.lblSummaryMessage.setText(msg)

    @pyqtSlot(str)
    def on_lblSummaryMessage_linkActivated(self, link: str):
        if link == 'copy_rpcauth':
            cl = QApplication.clipboard()
            cl.setText(self.rpcauth)