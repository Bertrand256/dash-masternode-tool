import binascii
import logging
import os
import re
import ssl
import threading
import time
import urllib, urllib.request, urllib.parse
from enum import Enum
from io import BytesIO
from typing import Callable, Optional, List, Dict

import simplejson
from PyQt5 import QtGui, QtCore
from PyQt5.QtCore import pyqtSlot, QItemSelection, QItemSelectionModel, Qt
from PyQt5.QtWidgets import QWidget, QMessageBox, QTableWidgetItem

import app_defs
import hw_intf
from app_config import AppConfig
from app_defs import get_note_url
from common import CancelException
from hw_common import HWDevice, HWType, HWFirmwareWebLocation
from thread_fun_dlg import CtrlObject
from ui.ui_hw_initialize_wdg import Ui_WdgInitializeHw
from wallet_tools_common import ActionPageBase
from hw_intf import HWDevices
from wnd_utils import WndUtils, ReadOnlyTableCellDelegate


class Step(Enum):
    STEP_SELECT_NUMBER_OF_SEED_WORDS = 1
    STEP_INPUT_HEX_ENTROPY = 2
    STEP_INPUT_SEED_WORDS = 3
    STEP_INPUT_OPTIONS = 4
    STEP_FINISHED = 5


class Pages(Enum):
    PAGE_FIRMWARE_SOURCE = 0
    PAGE_PREPARE_FIRMWARE = 1
    PAGE_UPLOAD_FIRMWARE = 2
    PAGE_MESSAGE = 3


class WdgInitializeHw(QWidget, Ui_WdgInitializeHw, ActionPageBase):
    def __init__(self, parent, hw_devices: HWDevices):
        QWidget.__init__(self, parent=parent)
        Ui_WdgInitializeHw.__init__(self)
        ActionPageBase.__init__(self, parent, parent.app_config, hw_devices)

        self.cur_hw_device: Optional[HWDevice] = self.hw_devices.get_selected_device()
        self.current_step: Step = Step.STEP_SELECT_FIRMWARE_SOURCE
        self.setupUi(self)

    def setupUi(self, dlg):
        Ui_WdgInitializeHw.setupUi(self, self)
        WndUtils.change_widget_font_attrs(self.lblMessage, point_size_diff=3, bold=True)
        self.pages.setCurrentIndex(Pages.PAGE_FIRMWARE_SOURCE.value)

    def initialize(self):
        self.set_title()
        self.set_btn_cancel_visible(True)
        self.set_btn_back_visible(True)
        self.set_btn_back_text('Back')
        self.set_btn_continue_visible(True)
        self.set_btn_cancel_text('Close')
        self.set_hw_panel_visible(True)
        self.set_controls_initial_state_for_step(False)
        self.update_ui()
        hw_changed = False
        if not self.cur_hw_device:
            self.hw_devices.select_device(self.parent())
            hw_changed = True
        if self.cur_hw_device and not self.cur_hw_device.hw_client:
            self.hw_devices.open_hw_session(self.cur_hw_device)
            hw_changed = True
        if hw_changed:
            self.update_ui()
            self.display_firmware_list()

    def on_close(self):
        self.finishing = True

    def on_current_hw_device_changed(self, cur_hw_device: HWDevice):
        if cur_hw_device:
            if cur_hw_device.hw_type == HWType.ledger_nano:
                # If the wallet type is not Trezor or Keepkey we can't use this page
                self.cur_hw_device = None
                self.update_ui()
                WndUtils.warn_msg('This feature is not available for Ledger devices.')
            else:
                self.cur_hw_device = self.hw_devices.get_selected_device()
                if not self.cur_hw_device.hw_client:
                    self.hw_devices.open_hw_session(self.cur_hw_device)
                self.update_ui()
                self.display_firmware_list()

    def set_title(self, subtitle: str = None):
        title = 'Initialize hardware wallet'
        if subtitle:
            title += ' - ' + subtitle
        self.set_action_title(f'<b>{title}</b>')

    def on_btn_continue_clicked(self):
        self.set_next_step()

    def on_btn_back_clicked(self):
        self.set_prev_step()

    def set_next_step(self):
        pass

    def set_prev_step(self):
        pass

    def set_controls_initial_state_for_step(self, moving_back: bool):
        pass

    def update_ui(self):
        try:
            if self.cur_hw_device and self.cur_hw_device.hw_client:
                pass
            else:
                self.lblMessage.setText('<b>Connect your hardware wallet device to continue</b>')
                self.pages.setCurrentIndex(Pages.PAGE_MESSAGE.value)
        except Exception as e:
            WndUtils.error_msg(str(e), True)

