import logging
import re
from enum import Enum
from typing import Callable, Optional, Dict, Tuple

from PyQt5 import QtGui, QtCore
from PyQt5.QtWidgets import QWidget, QMessageBox, QInputDialog

import app_utils
import hw_intf
from app_defs import get_note_url
from hw_common import HWDevice, HWType, HWModel, HWFirmwareWebLocation
from method_call_tracker import method_call_tracker, MethodCallTracker, MethodCallLimit
from thread_fun_dlg import CtrlObject
from ui.ui_hw_settings_wdg import Ui_WdgHwSettings
from wallet_tools_common import ActionPageBase, handle_hw_exceptions
from hw_intf import HWDevices
from wnd_utils import WndUtils, QDetectThemeChange, get_widget_font_color_green


class Step(Enum):
    STEP_NONE = 0
    STEP_SETTINGS = 1
    STEP_NO_HW_ERROR = 2


class WdgHwSettings(QWidget, QDetectThemeChange, Ui_WdgHwSettings, ActionPageBase):
    def __init__(self, parent, hw_devices: HWDevices):
        QWidget.__init__(self, parent=parent)
        QDetectThemeChange.__init__(self)
        Ui_WdgHwSettings.__init__(self)
        ActionPageBase.__init__(self, parent, parent.app_config, hw_devices, 'Hardware wallet settings')

        self.current_step: Step = Step.STEP_NONE
        self.cur_hw_device: Optional[HWDevice] = self.hw_devices.get_selected_device()
        self.hw_opt_pin_protection: Optional[bool] = None
        self.hw_opt_passphrase_protection: Optional[bool] = None
        self.hw_opt_passphrase_always_on_device: Optional[bool] = None
        self.hw_opt_wipe_code_protection: Optional[bool] = None  # https://wiki.trezor.io/User_manual:Wipe_code
        self.hw_opt_sd_protection: Optional[bool] = None  # https://wiki.trezor.io/User_manual:SD_card_protection
        self.hw_opt_auto_lock_delay_ms: Optional[int] = None
        self.hw_opt_firmware_version: str = '?'
        self.latest_firmware_version: Optional[str] = None
        self.latest_firmwares: Dict[HWModel, Optional[HWFirmwareWebLocation]] = {}
        self.get_latest_firmware_version_thread_obj: Optional[object] = None
        self.setupUi(self)

    def setupUi(self, dlg):
        Ui_WdgHwSettings.setupUi(self, self)
        WndUtils.change_widget_font_attrs(self.lblMessage, point_size_diff=3, bold=True)
        self.lblMessage.setMinimumSize(QtCore.QSize(0, 100))
        self.lblMessage.setText('<b>Connect your hardware wallet device to continue</b>')
        self.lblWipeCodeLabel.setText(f'Wipe code (<a href="{get_note_url("DMTN0004")}">help</a>):')
        self.lblWipeCodeLabel.setOpenExternalLinks(True)
        self.lblSDCardProtectionLabel.setText(f'SD card protection (<a href="{get_note_url("DMTN0005")}">help</a>):')
        self.lblSDCardProtectionLabel.setOpenExternalLinks(True)
        self.btnEnDisPin.clicked.connect(self.on_pin_enable_disable)
        self.btnChangePin.clicked.connect(self.on_pin_change)
        self.btnEnDisPass.clicked.connect(self.on_passphrase_enable_disable)
        self.btnEnDisPassAlwaysOnDevice.clicked.connect(self.on_passphrase_alwaysondevice_enable_disable)
        self.btnEnDisWipeCode.clicked.connect(self.on_wipe_code_enable_disable)
        self.btnEnDisSDCardProtection.clicked.connect(self.on_sd_card_protection_enable_disable)
        self.btnRefreshSDCardProtection.clicked.connect(self.on_sd_card_protection_refresh)
        self.btnChangeLabel.clicked.connect(self.on_change_label)

    def initialize(self):
        ActionPageBase.initialize(self)
        self.current_step = Step.STEP_NONE
        self.set_btn_cancel_visible(True)
        self.set_btn_back_visible(True)
        self.set_btn_continue_visible(False)
        self.set_hw_panel_visible(True)
        self.update_styles()
        self.update_ui()

        with MethodCallLimit(self, self.on_connected_hw_device_changed, call_count_limit=1):
            if not self.cur_hw_device:
                self.hw_devices.select_device(self.parent(), open_client_session=True)
            else:
                if not self.cur_hw_device.hw_client:
                    self.hw_devices.open_hw_session(self.cur_hw_device)
            self.on_connected_hw_device_changed(self.cur_hw_device)

    def onThemeChanged(self):
        self.update_styles()

    def update_styles(self):
        self.update_ui()

    @method_call_tracker
    def on_connected_hw_device_changed(self, cur_hw_device: HWDevice):
        self.cur_hw_device = cur_hw_device
        if self.on_validate_hw_device(cur_hw_device):
            if self.current_step in (Step.STEP_NO_HW_ERROR, Step.STEP_NONE):
                self.set_current_step(Step.STEP_SETTINGS)
            else:
                self.update_ui()
            hw_model = self.cur_hw_device.get_hw_model()
            if hw_model and not self.latest_firmwares.get(hw_model):
                WndUtils.run_thread(self, self.get_latest_firmware_thread, (hw_model,))
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

    def set_controls_initial_state_for_step(self):
        self.set_btn_cancel_enabled(True)
        self.set_btn_cancel_visible(True)
        self.set_btn_continue_visible(False)
        self.set_hw_change_enabled(True)

        if self.current_step == Step.STEP_SETTINGS:
            self.set_btn_back_enabled(True)
            self.set_btn_back_visible(True)
            self.set_btn_continue_enabled(True)
            self.set_btn_continue_visible(False)
            self.set_btn_close_visible(True)
            self.set_btn_close_enabled(True)
            self.set_hw_change_enabled(True)
        elif self.current_step == Step.STEP_NO_HW_ERROR:
            self.set_btn_back_visible(True)
            self.set_btn_continue_visible(False)

    def read_hw_features(self):
        def get_hw_feature(features, feature_name: str):
            try:
                if feature_name in features.__dir__():
                    return features.__getattribute__(feature_name)
                else:
                    return None
            except Exception:
                return False

        if self.cur_hw_device and self.cur_hw_device.hw_client:
            cl = self.cur_hw_device.hw_client
            feat = cl.features
            self.hw_opt_pin_protection = feat.pin_protection
            self.hw_opt_passphrase_protection = feat.passphrase_protection
            self.hw_opt_passphrase_always_on_device = get_hw_feature(feat, 'passphrase_always_on_device')
            self.hw_opt_wipe_code_protection = get_hw_feature(feat, 'wipe_code_protection')
            self.hw_opt_sd_protection = get_hw_feature(feat, 'sd_protection')
            self.hw_opt_firmware_version = self.cur_hw_device.firmware_version

    def update_ui(self):
        try:
            green_color = get_widget_font_color_green(self)

            if self.cur_hw_device and self.cur_hw_device.hw_client and self.cur_hw_device.hw_type != HWType.ledger_nano:
                if self.current_step == Step.STEP_SETTINGS:
                    self.show_action_page()
                    self.wdgHwSettings.setVisible(True)
                    self.lblMessage.setVisible(False)

                    self.read_hw_features()
                    version_info_msg = self.hw_opt_firmware_version
                    if self.cur_hw_device.bootloader_mode:
                        self.lblFirmwareVersionLabel.setText('Bootloader version:')
                    else:
                        self.lblFirmwareVersionLabel.setText('Firmware version:')
                        cur_fw_version = self.cur_hw_device.firmware_version
                        latest_fw_version_src = self.latest_firmwares.get(self.cur_hw_device.get_hw_model())
                        latest_fw_version = latest_fw_version_src.version if latest_fw_version_src else None
                        if cur_fw_version and latest_fw_version and \
                                app_utils.is_version_greater(latest_fw_version, cur_fw_version):
                            if re.match('\s*http(s)?://', latest_fw_version_src.notes, re.IGNORECASE):
                                ver_str = f'<a href={latest_fw_version_src.notes}>{latest_fw_version}</a>'
                            else:
                                ver_str = latest_fw_version
                            version_info_msg += f' <span style="color:{green_color}">(new version available: ' + ver_str + ')</span>'
                    self.lblFirmwareVersion.setText(version_info_msg)

                    if self.hw_opt_pin_protection is True:
                        self.lblPinStatus.setText('enabled')
                        self.btnEnDisPin.setText('Disable')
                        self.btnEnDisPin.setEnabled(True)
                        self.btnChangePin.setEnabled(True)
                        self.lblPinStatus.setStyleSheet(f'QLabel{{color: {green_color}}}')
                    elif self.hw_opt_pin_protection is False:
                        self.lblPinStatus.setText('disabled')
                        self.btnEnDisPin.setText('Enable')
                        self.btnEnDisPin.setEnabled(True)
                        self.btnChangePin.setEnabled(True)
                        self.lblPinStatus.setStyleSheet('QLabel{color: red}')
                    else:
                        self.lblPinStatus.setText('not available')
                        self.lblPinStatus.setStyleSheet('QLabel{color: orange}')
                        self.btnEnDisPin.setText('Enable')
                        self.btnEnDisPin.setDisabled(True)
                        self.btnChangePin.setDisabled(True)

                    if self.hw_opt_passphrase_protection is True:
                        self.lblPassStatus.setText('enabled')
                        self.lblPassStatus.setStyleSheet(f'QLabel{{color: {green_color}}}')
                        self.btnEnDisPass.setText('Disable')
                        self.btnEnDisPass.setEnabled(True)
                    elif self.hw_opt_passphrase_protection is False:
                        self.lblPassStatus.setText('disabled')
                        self.lblPassStatus.setStyleSheet('QLabel{color: red}')
                        self.btnEnDisPass.setText('Enable')
                        self.btnEnDisPass.setEnabled(True)
                    else:
                        self.lblPassStatus.setText('not available')
                        self.lblPassStatus.setStyleSheet('QLabel{color: orange}')
                        self.btnEnDisPass.setText('Enable')
                        self.btnEnDisPass.setDisabled(True)

                    if self.hw_opt_passphrase_always_on_device is True:
                        self.lblPassAlwaysOnDeviceStatus.setText('enabled')
                        self.lblPassAlwaysOnDeviceStatus.setStyleSheet(f'QLabel{{color: {green_color}}}')
                        self.btnEnDisPassAlwaysOnDevice.setText('Disable')
                        self.btnEnDisPassAlwaysOnDevice.setEnabled(True)
                    elif self.hw_opt_passphrase_always_on_device is False:
                        self.lblPassAlwaysOnDeviceStatus.setText('disabled')
                        self.lblPassAlwaysOnDeviceStatus.setStyleSheet('QLabel{color: red}')
                        self.btnEnDisPassAlwaysOnDevice.setText('Enable')
                        self.btnEnDisPassAlwaysOnDevice.setEnabled(True)
                    else:
                        self.lblPassAlwaysOnDeviceStatus.setText('not available')
                        self.lblPassAlwaysOnDeviceStatus.setStyleSheet('QLabel{color: orange}')
                        self.btnEnDisPassAlwaysOnDevice.setText('Enable')
                        self.btnEnDisPassAlwaysOnDevice.setDisabled(True)

                    if self.hw_opt_wipe_code_protection is True:
                        self.lblWipeCodeStatus.setText('enabled')
                        self.lblWipeCodeStatus.setStyleSheet(f'QLabel{{color: {green_color}}}')
                        self.btnEnDisWipeCode.setText('Disable')
                        self.btnEnDisWipeCode.setEnabled(True)
                    elif self.hw_opt_wipe_code_protection is False:
                        self.lblWipeCodeStatus.setText('disabled')
                        self.lblWipeCodeStatus.setStyleSheet('QLabel{color: red}')
                        self.btnEnDisWipeCode.setText('Enable')
                        self.btnEnDisWipeCode.setEnabled(True)
                    else:
                        self.lblWipeCodeStatus.setText('not available')
                        self.lblWipeCodeStatus.setStyleSheet('QLabel{color: orange}')
                        self.btnEnDisWipeCode.setText('Enable')
                        self.btnEnDisWipeCode.setDisabled(True)

                    if self.hw_opt_sd_protection is True:
                        self.lblSDCardProtectionStatus.setText('enabled')
                        self.lblSDCardProtectionStatus.setStyleSheet(f'QLabel{{color: {green_color}}}')
                        self.btnEnDisSDCardProtection.setText('Disable')
                        self.btnEnDisSDCardProtection.setEnabled(True)
                        self.btnRefreshSDCardProtection.setEnabled(True)
                    elif self.hw_opt_sd_protection is False:
                        self.lblSDCardProtectionStatus.setText('disabled')
                        self.lblSDCardProtectionStatus.setStyleSheet('QLabel{color: red}')
                        self.btnEnDisSDCardProtection.setText('Enable')
                        self.btnEnDisSDCardProtection.setEnabled(True)
                        self.btnRefreshSDCardProtection.setEnabled(True)
                    else:
                        self.lblSDCardProtectionStatus.setText('not available')
                        self.lblSDCardProtectionStatus.setStyleSheet('QLabel{color: orange}')
                        self.btnEnDisSDCardProtection.setText('Enable')
                        self.btnEnDisSDCardProtection.setDisabled(True)
                        self.btnRefreshSDCardProtection.setDisabled(True)

                    if self.cur_hw_device.device_label:
                        self.lblLabelValue.setText(self.cur_hw_device.device_label)
                    else:
                        self.lblLabelValue.setText('not set')
            else:
                self.show_message_page('Connect Trezor/Keepkey hardware wallet')
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @handle_hw_exceptions
    def on_pin_enable_disable(self, _):
        if self.cur_hw_device and self.cur_hw_device.hw_client:
            if self.hw_opt_pin_protection is True:
                # disable
                if WndUtils.query_dlg(
                        'Do you really want to disable PIN protection on %s?' %
                        self.cur_hw_device.get_description(),
                        buttons=QMessageBox.Yes | QMessageBox.Cancel, default_button=QMessageBox.Cancel,
                        icon=QMessageBox.Warning) == QMessageBox.Yes:
                    self.hw_devices.change_pin(self.cur_hw_device, remove=True)
                    self.update_ui()
            elif self.hw_opt_pin_protection is False:
                # enable PIN
                self.hw_devices.change_pin(self.cur_hw_device, remove=False)
                self.update_ui()

    @handle_hw_exceptions
    def on_pin_change(self, _):
        if self.cur_hw_device and self.cur_hw_device.hw_client:
            self.hw_devices.change_pin(self.cur_hw_device, remove=False)
            self.update_ui()

    @handle_hw_exceptions
    def on_change_label(self, _):
        new_label, ok = QInputDialog.getText(self, 'HW label', 'Enter a new label for your device')
        if ok:
            self.hw_devices.set_label(self.cur_hw_device, new_label)
            self.update_ui()

    @handle_hw_exceptions
    def on_passphrase_enable_disable(self, _):
        if self.cur_hw_device and self.cur_hw_device.hw_client:
            if self.hw_opt_passphrase_protection is True:
                # disable passphrase
                if WndUtils.query_dlg('Do you really want to disable passphrase protection on %s?' %
                                      self.cur_hw_device.get_description(),
                                      buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                      default_button=QMessageBox.Cancel,
                                      icon=QMessageBox.Warning) == QMessageBox.Yes:
                    self.hw_devices.set_passphrase_option(self.cur_hw_device, enabled=False)
                    self.update_ui()
            elif self.hw_opt_passphrase_protection is False:
                # enable passphrase
                if WndUtils.query_dlg('Do you really want to enable passphrase protection on %s?' %
                                      self.cur_hw_device.get_description(),
                                      buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                      default_button=QMessageBox.Cancel,
                                      icon=QMessageBox.Warning) == QMessageBox.Yes:
                    self.hw_devices.set_passphrase_option(self.cur_hw_device, enabled=True)
                    self.update_ui()

    @handle_hw_exceptions
    def on_passphrase_alwaysondevice_enable_disable(self, _):
        if self.cur_hw_device and self.cur_hw_device.hw_client:
            if self.hw_opt_passphrase_always_on_device is True:
                # disable passphrase
                if WndUtils.query_dlg('Do you really want to disable passphrase always on device option?',
                                      buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                      default_button=QMessageBox.Cancel,
                                      icon=QMessageBox.Warning) == QMessageBox.Yes:
                    self.hw_devices.set_passphrase_always_on_device(self.cur_hw_device, enabled=False)
                    self.update_ui()
            elif self.hw_opt_passphrase_always_on_device is False:
                # enable passphrase
                if WndUtils.query_dlg('Do you really want to enable passphrase always on device option?',
                                      buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                      default_button=QMessageBox.Cancel,
                                      icon=QMessageBox.Warning) == QMessageBox.Yes:
                    self.hw_devices.set_passphrase_always_on_device(self.cur_hw_device, enabled=True)
                    self.update_ui()

    @handle_hw_exceptions
    def on_wipe_code_enable_disable(self, _):
        if self.cur_hw_device and self.cur_hw_device.hw_client:
            if self.hw_opt_wipe_code_protection is True:
                # disable passphrase
                if WndUtils.query_dlg('Do you really want to disable wipe code?',
                                      buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                      default_button=QMessageBox.Cancel,
                                      icon=QMessageBox.Warning) == QMessageBox.Yes:
                    self.hw_devices.set_wipe_code(self.cur_hw_device, remove=True)
                    self.update_ui()
            elif self.hw_opt_wipe_code_protection is False:
                # enable passphrase
                if WndUtils.query_dlg('Do you really want to enable wipe code?',
                                      buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                      default_button=QMessageBox.Cancel,
                                      icon=QMessageBox.Warning) == QMessageBox.Yes:
                    self.hw_devices.set_wipe_code(self.cur_hw_device, remove=False)
                    self.update_ui()

    @handle_hw_exceptions
    def on_sd_card_protection_enable_disable(self, _):
        if self.cur_hw_device and self.cur_hw_device.hw_client:
            if self.hw_opt_sd_protection is True:
                # disable passphrase
                if WndUtils.query_dlg('Do you really want to disable SD card protection?',
                                      buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                      default_button=QMessageBox.Cancel,
                                      icon=QMessageBox.Warning) == QMessageBox.Yes:
                    self.hw_devices.set_sd_protect(self.cur_hw_device, 'disable')
                    self.update_ui()
            elif self.hw_opt_sd_protection is False:
                # enable passphrase
                if WndUtils.query_dlg('Do you really want to enable SD card protection?',
                                      buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                      default_button=QMessageBox.Cancel,
                                      icon=QMessageBox.Warning) == QMessageBox.Yes:
                    self.hw_devices.set_sd_protect(self.cur_hw_device, 'enable')
                    self.update_ui()

    @handle_hw_exceptions
    def on_sd_card_protection_refresh(self, _):
        if self.cur_hw_device and self.cur_hw_device.hw_client:
            if WndUtils.query_dlg('Do you really want to refresh SD card protection?',
                                  buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                  default_button=QMessageBox.Cancel,
                                  icon=QMessageBox.Warning) == QMessageBox.Yes:
                self.hw_devices.set_sd_protect(self.cur_hw_device, 'refresh')
                self.update_ui()

    def get_latest_firmware_thread(self, ctr: CtrlObject, hw_model: HWModel):
        try:
            fws = hw_intf.get_hw_firmware_web_sources((hw_model,), only_official=True, only_latest=True)
            if fws:
                self.latest_firmwares[hw_model] = fws[0]
                WndUtils.call_in_main_thread(self.update_ui)
            else:
                self.latest_firmwares[hw_model] = None  # mark that we weren't able to read the latest firmware version
        except Exception as e:
            logging.error('Error while reading the latest version of the hw firmware: ' + str(e))

