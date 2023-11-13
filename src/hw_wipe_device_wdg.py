import logging
import re
from enum import Enum
from typing import Optional, Dict, Tuple

from PyQt5 import QtCore
from PyQt5.QtWidgets import QWidget, QMessageBox

import app_utils
import hw_intf
from app_defs import get_note_url
from common import CancelException
from hw_common import HWDevice, HWType, HWModel, HWFirmwareWebLocation
from method_call_tracker import method_call_tracker, MethodCallLimit
from thread_fun_dlg import CtrlObject
from ui.ui_hw_wipe_device_wdg import Ui_WdgWipeHwDevice
from wallet_tools_common import ActionPageBase
from hw_intf import HWDevices
from wnd_utils import WndUtils


class Step(Enum):
    STEP_NONE = 0
    STEP_INITIAL = 1
    STEP_WIPING_HW = 2
    STEP_FINISHED = 3
    STEP_NO_HW_ERROR = 4


class WdgWipeHwDevice(QWidget, Ui_WdgWipeHwDevice, ActionPageBase):
    def __init__(self, parent, hw_devices: HWDevices):
        QWidget.__init__(self, parent=parent)
        Ui_WdgWipeHwDevice.__init__(self)
        ActionPageBase.__init__(self, parent, parent.app_config, hw_devices, 'Wipe hardware wallet')

        self.current_step: Step = Step.STEP_NONE
        self.cur_hw_device: Optional[HWDevice] = self.hw_devices.get_selected_device()
        self.setupUi(self)

    def setupUi(self, dlg):
        Ui_WdgWipeHwDevice.setupUi(self, self)

    def initialize(self):
        ActionPageBase.initialize(self)
        self.set_hw_panel_visible(True)
        self.set_controls_initial_state_for_step()
        self.current_step = Step.STEP_NONE
        self.update_ui()

        with MethodCallLimit(self, self.on_connected_hw_device_changed, call_count_limit=1):
            if not self.cur_hw_device:
                self.hw_devices.select_device(self.parent(), open_client_session=True)
            else:
                if not self.cur_hw_device.hw_client:
                    self.hw_devices.open_hw_session(self.cur_hw_device)
            self.on_connected_hw_device_changed(self.cur_hw_device)

    @method_call_tracker
    def on_connected_hw_device_changed(self, cur_hw_device: HWDevice):
        self.cur_hw_device = cur_hw_device
        if self.on_validate_hw_device(cur_hw_device):
            if self.current_step in (Step.STEP_NO_HW_ERROR, Step.STEP_NONE):
                self.set_current_step(Step.STEP_INITIAL)
            else:
                self.update_ui()
        else:
            self.set_current_step(Step.STEP_NO_HW_ERROR)

    def on_validate_hw_device(self, hw_device: HWDevice) -> bool:
        if not hw_device or not hw_device.hw_client or hw_device.hw_type == HWType.ledger_nano:
            return False
        else:
            return True

    def set_current_step(self, step: Step):
        if self.current_step != step:
            self.current_step = step
            self.set_controls_initial_state_for_step()
            self.update_ui()

    def go_to_next_step(self):
        if self.current_step == Step.STEP_INITIAL:
            self.set_current_step(Step.STEP_WIPING_HW)
            self.wipe_hw()
        elif self.current_step == Step.STEP_WIPING_HW:
            self.set_current_step(Step.STEP_FINISHED)

    def go_to_prev_step(self):
        self.exit_page()

    def set_controls_initial_state_for_step(self):
        self.set_btn_cancel_enabled(True)
        self.set_btn_cancel_visible(True)
        self.set_btn_close_visible(False)
        self.set_btn_close_enabled(False)
        self.set_hw_change_enabled(True)

        if self.current_step == Step.STEP_INITIAL:
            self.set_btn_back_enabled(True)
            self.set_btn_back_visible(True)
            self.set_btn_continue_enabled(True)
            self.set_btn_continue_visible(True)
            self.set_hw_change_enabled(True)
            self.lblMessage.setText(f'<b>Click &lt;Continue&gt; to wipe your {HWType.get_desc(self.cur_hw_device.hw_type)} device.</b>')
        elif self.current_step == Step.STEP_WIPING_HW:
            self.set_btn_back_enabled(False)
            self.set_btn_back_visible(True)
            self.set_btn_continue_enabled(False)
            self.set_btn_continue_visible(True)
            self.set_hw_change_enabled(False)
            self.update_action_subtitle('wiping')
        elif self.current_step == Step.STEP_FINISHED:
            self.set_btn_back_enabled(True)
            self.set_btn_back_visible(True)
            self.set_btn_continue_visible(False)
            self.set_hw_change_enabled(False)
            self.set_btn_close_visible(True)
            self.set_btn_close_enabled(True)
            self.update_action_subtitle('finished')
            self.show_message_page('Operation completed.')
        elif self.current_step == Step.STEP_NO_HW_ERROR:
            self.set_btn_back_visible(True)
            self.set_btn_continue_visible(False)

    def update_ui(self):
        try:
            if self.cur_hw_device and self.cur_hw_device.hw_client and self.cur_hw_device.hw_type != HWType.ledger_nano:
                if self.current_step == Step.STEP_FINISHED:
                    self.update_action_subtitle('finished')
                    self.show_message_page('Operation completed.')
                elif self.current_step == Step.STEP_NO_HW_ERROR:
                    self.show_message_page()
                else:
                    self.show_action_page()
            else:
                self.show_message_page('Connect Trezor/Keepkey hardware wallet')
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    def wipe_hw(self):
        try:
            self.hw_devices.wipe_device(self.cur_hw_device, parent_window=self.parent_dialog)
            self.go_to_next_step()
        except CancelException:
            self.go_to_prev_step()
            self.hw_devices.open_hw_session(self.cur_hw_device, force_reconnect=True)
        except Exception as e:
            WndUtils.error_msg(str(e), True)
            self.go_to_prev_step()