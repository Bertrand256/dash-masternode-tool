from enum import Enum
from typing import Optional

from PyQt5.QtWidgets import QWidget

from common import CancelException
from hw_common import HWDevice, HWType
from method_call_tracker import MethodCallLimit, method_call_tracker
from ui.ui_hw_initialize_wdg import Ui_WdgInitializeHw
from wallet_tools_common import ActionPageBase
from hw_intf import HWDevices
from wnd_utils import WndUtils


class Step(Enum):
    STEP_NONE = 0
    STEP_INPUT_OPTIONS = 1
    STEP_INITIALIZING_HW = 2
    STEP_FINISHED = 3
    STEP_NO_HW_ERROR = 4


class Pages(Enum):
    PAGE_OPTIONS = 0


class WdgInitializeHw(QWidget, Ui_WdgInitializeHw, ActionPageBase):
    def __init__(self, parent, hw_devices: HWDevices):
        QWidget.__init__(self, parent=parent)
        Ui_WdgInitializeHw.__init__(self)
        ActionPageBase.__init__(self, parent, parent.app_config, hw_devices, 'Initialize with new seed')

        self.cur_hw_device: Optional[HWDevice] = self.hw_devices.get_selected_device()
        self.current_step: Step = Step.STEP_NONE
        self.hw_conn_change_allowed = True
        self.setupUi(self)

    def setupUi(self, dlg):
        Ui_WdgInitializeHw.setupUi(self, self)
        self.pages.setCurrentIndex(Pages.PAGE_OPTIONS.value)

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
        if self.hw_conn_change_allowed:
            if self.on_validate_hw_device(cur_hw_device):
                if self.current_step in (Step.STEP_NO_HW_ERROR, Step.STEP_NONE):
                    self.set_current_step(Step.STEP_INPUT_OPTIONS)
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
        if self.current_step == Step.STEP_INPUT_OPTIONS:
            self.set_current_step(Step.STEP_INITIALIZING_HW)
            self.init_hw()
        elif self.current_step == Step.STEP_INITIALIZING_HW:
            self.set_current_step(Step.STEP_FINISHED)

    def go_to_prev_step(self):
        if self.current_step in (Step.STEP_INPUT_OPTIONS, Step.STEP_NO_HW_ERROR):
            self.exit_page()
        elif self.current_step in (Step.STEP_FINISHED, Step.STEP_INITIALIZING_HW):
            self.set_current_step(Step.STEP_INPUT_OPTIONS)

    def set_controls_initial_state_for_step(self):
        self.set_btn_cancel_enabled(True)
        self.set_btn_cancel_visible(True)
        self.set_btn_close_visible(False)
        self.set_btn_close_enabled(False)
        self.set_hw_change_enabled(False)
        self.set_hw_change_enabled(True)

        if self.current_step == Step.STEP_INPUT_OPTIONS:
            self.set_btn_back_enabled(True)
            self.set_btn_back_visible(True)
            self.set_btn_continue_enabled(True)
            self.set_btn_continue_visible(True)
            self.rbWordsCount12.setEnabled(True)
            self.rbWordsCount18.setEnabled(True)
            self.rbWordsCount24.setEnabled(True)
            self.chbUsePIN.setEnabled(True)
            self.chbUsePassphrase.setEnabled(True)
            self.edtDeviceLabel.setEnabled(True)
        elif self.current_step == Step.STEP_INITIALIZING_HW:
            self.set_btn_back_enabled(False)
            self.set_btn_back_visible(True)
            self.set_btn_continue_enabled(False)
            self.set_btn_continue_visible(True)
            self.set_hw_change_enabled(False)
            self.rbWordsCount12.setDisabled(True)
            self.rbWordsCount18.setDisabled(True)
            self.rbWordsCount24.setDisabled(True)
            self.chbUsePIN.setDisabled(True)
            self.chbUsePassphrase.setDisabled(True)
            self.edtDeviceLabel.setDisabled(True)
        elif self.current_step == Step.STEP_FINISHED:
            self.set_btn_back_enabled(True)
            self.set_btn_back_visible(True)
            self.set_btn_continue_visible(False)
            self.set_btn_close_visible(True)
            self.set_btn_close_enabled(True)
            self.set_hw_change_enabled(False)
        elif self.current_step == Step.STEP_NO_HW_ERROR:
            self.set_btn_back_visible(True)
            self.set_btn_continue_visible(False)

    def update_ui(self):
        try:
            if self.cur_hw_device and self.cur_hw_device.hw_client and self.cur_hw_device.hw_type != HWType.ledger_nano:
                if self.current_step == Step.STEP_INPUT_OPTIONS:
                    self.pages.setCurrentIndex(Pages.PAGE_OPTIONS.value)
                    self.update_action_subtitle('enter hardware wallet options')
                elif self.current_step == Step.STEP_INITIALIZING_HW:
                    self.update_action_subtitle('initializing device')
                    self.pages.setCurrentIndex(Pages.PAGE_OPTIONS.value)
                elif self.current_step == Step.STEP_FINISHED:
                    self.update_action_subtitle('finished')
                    self.show_message_page('<b>Hardware wallet successfully initialized.</b>')
                    return
                self.show_action_page()
            else:
                self.show_message_page('Connect Trezor/Keepkey hardware wallet')
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    def init_hw(self):
        try:
            self.hw_conn_change_allowed = False
            if self.rbWordsCount12.isChecked():
                word_count = 12
            elif self.rbWordsCount18.isChecked():
                word_count = 18
            elif self.rbWordsCount24.isChecked():
                word_count = 24
            else:
                WndUtils.error_msg('Enter the valid number of seed words count.')
                return

            use_pin = True if self.chbUsePIN.isChecked() else False
            use_passphrase = True if self.chbUsePassphrase.isChecked() else False
            label = self.edtDeviceLabel.text()

            self.hw_devices.initialize_device(self.cur_hw_device, word_count, use_passphrase,
                                              use_pin, label, parent_window=self.parent_dialog)
            self.set_current_step(Step.STEP_FINISHED)
        except CancelException:
            self.go_to_prev_step()
            self.hw_devices.open_hw_session(self.cur_hw_device, force_reconnect=True)
        except Exception as e:
            WndUtils.error_msg(str(e), True)
            self.go_to_prev_step()
        finally:
            self.hw_conn_change_allowed = True