from typing import Callable, Optional

from PyQt5 import QtGui, QtCore
from PyQt5.QtWidgets import QWidget, QMessageBox

import hw_intf
from app_defs import get_note_url
from common import CancelException
from hw_common import HWDevice, HWType
from ui.ui_hw_update_firmware_wdg import Ui_WdgHwUpdateFirmware
from wallet_tools_common import ActionPageBase
from hw_intf import HWDevices
from wnd_utils import WndUtils


class WdgHwUpdateFirmware(QWidget, Ui_WdgHwUpdateFirmware, ActionPageBase):
    def __init__(self, parent, hw_devices: HWDevices):
        QWidget.__init__(self, parent=parent)
        Ui_WdgHwUpdateFirmware.__init__(self)
        ActionPageBase.__init__(self, hw_devices)

        self.cur_hw_device: Optional[HWDevice] = self.hw_devices.get_selected_device()
        self.setupUi(self)

    def setupUi(self, dlg):
        Ui_WdgHwUpdateFirmware.setupUi(self, self)

    def initialize(self):
        self.set_action_title('<b>Update hardware wallet firmware</b>')
        self.set_btn_cancel_visible(True)
        self.set_btn_back_visible(True)
        self.set_btn_back_text('Back')
        self.set_btn_continue_visible(False)
        self.set_btn_cancel_text('Close')
        self.set_hw_panel_visible(True)
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

    def on_btn_back_clicked(self):
        self.exit_page()

    def update_ui(self):
        try:
            pass
            # if self.cur_hw_device and self.cur_hw_device.hw_client:
            #     self.fraHwSettings.setVisible(True)
            #     self.lblMessage.setVisible(False)
            # else:
            #     self.fraHwSettings.setVisible(False)
            #     self.lblMessage.setVisible(True)
        except Exception as e:
            WndUtils.error_msg(str(e), True)

