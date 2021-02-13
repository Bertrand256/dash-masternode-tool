from typing import Callable, Optional

from PyQt5.QtWidgets import QWidget

from ui.ui_hw_settings_wdg import Ui_WdgHwSettings
from wallet_tools_common import ActionPageBase
from hw_intf import HWDevices


class WdgHwSettings(QWidget, Ui_WdgHwSettings, ActionPageBase):
    def __init__(self, parent, hw_list: HWDevices):
        QWidget.__init__(self, parent=parent)
        Ui_WdgHwSettings.__init__(self)
        ActionPageBase.__init__(self)

        self.hw_list = hw_list
        self.hw_device_index_selected: Optional[int] = None  # index in self.hw_device_instances
        self.hw_opt_pin_protection = None
        self.hw_opt_passphrase_protection = None
        self.hw_opt_passphrase_always_on_device = None
        self.hw_opt_wipe_code_protection = None  # https://wiki.trezor.io/User_manual:Wipe_code
        self.hw_opt_sd_protection = None  # https://wiki.trezor.io/User_manual:SD_card_protection
        self.hw_opt_auto_lock_delay_ms = None
        self.hw_opt_firmware_version = 'unknown'
        self.setupUi(self)

    def setupUi(self, dlg):
        Ui_WdgHwSettings.setupUi(self, self)

    def initialize(self):
        self.set_action_title('<b>Hardware wallet settings</b>')
        self.set_btn_cancel_visible(True)
        self.set_btn_back_visible(True)
        self.set_btn_back_text('Back')
        self.set_btn_continue_visible(False)
        self.set_btn_cancel_text('Close')
        self.set_hw_panel_visible(True)
        self.update_hw_settings_page()

    def on_btn_back_clicked(self):
        self.exit_page()

    def read_hw_features(self):
        return
    #     def has_field(features, field_name):
    #         try:
    #             #todo: improve this
    #             return features.HasField(field_name)
    #         except Exception:
    #             return False
    #
    #     if self.hw_device_index_selected >= 0 and self.hw_device_id_selected:
    #         hw_client = self.hw_device_instances[self.hw_device_index_selected][3]
    #         if hw_client:
    #             features = hw_client.features
    #             self.hw_opt_pin_protection = features.pin_protection
    #             self.hw_opt_passphrase_protection = features.passphrase_protection
    #             if has_field(features, 'passphrase_always_on_device'):
    #                 self.hw_opt_passphrase_always_on_device = features.passphrase_always_on_device
    #             if has_field(features, 'wipe_code_protection'):
    #                 self.hw_opt_wipe_code_protection = features.wipe_code_protection
    #             if has_field(features, 'sd_protection'):
    #                 self.hw_opt_sd_protection = features.sd_protection
    #             self.hw_opt_firmware_version = str(hw_client.features.major_version) + '.' + \
    #                    str(hw_client.features.minor_version) + '.' + \
    #                    str(hw_client.features.patch_version)

    def update_hw_settings_page(self):
        return
    #     try:
    #         self.read_hw_features()
    #         if self.hw_device_index_selected >= 0 and self.hw_device_id_selected:
    #             self.lblFirmwareVersion.setText(self.hw_opt_firmware_version)
    #
    #             if self.hw_opt_pin_protection is True:
    #                 self.lblPinStatus.setText('enabled')
    #                 self.btnEnDisPin.setText('Disable')
    #                 self.btnChangePin.setEnabled(True)
    #                 self.lblPinStatus.setStyleSheet('QLabel{color: green}')
    #             elif self.hw_opt_pin_protection is False:
    #                 self.lblPinStatus.setText('disabled')
    #                 self.btnEnDisPin.setText('Enable')
    #                 self.btnChangePin.setEnabled(False)
    #                 self.lblPinStatus.setStyleSheet('QLabel{color: red}')
    #             else:
    #                 self.lblPinStatus.setVisible(False)
    #                 self.lblPinStatusLabel.setVisible(False)
    #                 self.btnEnDisPin.setVisible(False)
    #                 self.btnChangePin.setVisible(False)
    #
    #             if self.hw_opt_passphrase_protection is True:
    #                 self.lblPassStatus.setText('enabled')
    #                 self.lblPassStatus.setStyleSheet('QLabel{color: green}')
    #                 self.btnEnDisPass.setText('Disable')
    #             elif self.hw_opt_passphrase_protection is False:
    #                 self.lblPassStatus.setText('disabled')
    #                 self.lblPassStatus.setStyleSheet('QLabel{color: red}')
    #                 self.btnEnDisPass.setText('Enable')
    #             else:
    #                 self.lblPassStatus.setVisible(False)
    #                 self.lblPassStatusLabel.setVisible(False)
    #                 self.lblPassStatus.setVisible(False)
    #                 self.btnEnDisPass.setVisible(False)
    #
    #             if self.hw_opt_passphrase_always_on_device is True:
    #                 self.lblPassAlwaysOnDeviceStatus.setText('enabled')
    #                 self.lblPassAlwaysOnDeviceStatus.setStyleSheet('QLabel{color: green}')
    #                 self.btnEnDisPassAlwaysOnDevice.setText('Disable')
    #                 self.btnEnDisPassAlwaysOnDevice.setEnabled(True)
    #             elif self.hw_opt_passphrase_always_on_device is False:
    #                 self.lblPassAlwaysOnDeviceStatus.setText('disabled')
    #                 self.lblPassAlwaysOnDeviceStatus.setStyleSheet('QLabel{color: red}')
    #                 self.btnEnDisPassAlwaysOnDevice.setText('Enable')
    #                 self.btnEnDisPassAlwaysOnDevice.setEnabled(True)
    #             else:
    #                 self.lblPassAlwaysOnDeviceStatus.setText('not available')
    #                 self.lblPassAlwaysOnDeviceStatus.setStyleSheet('QLabel{color: orange}')
    #                 self.btnEnDisPassAlwaysOnDevice.setText('Enable')
    #                 self.btnEnDisPassAlwaysOnDevice.setDisabled(True)
    #
    #             if self.hw_opt_wipe_code_protection is True:
    #                 self.lblWipeCodeStatus.setText('enabled')
    #                 self.lblWipeCodeStatus.setStyleSheet('QLabel{color: green}')
    #                 self.btnEnDisWipeCode.setText('Disable')
    #                 self.btnEnDisWipeCode.setEnabled(True)
    #             elif self.hw_opt_wipe_code_protection is False:
    #                 self.lblWipeCodeStatus.setText('disabled')
    #                 self.lblWipeCodeStatus.setStyleSheet('QLabel{color: red}')
    #                 self.btnEnDisWipeCode.setText('Enable')
    #                 self.btnEnDisWipeCode.setEnabled(True)
    #             else:
    #                 self.lblWipeCodeStatus.setText('not available')
    #                 self.lblWipeCodeStatus.setStyleSheet('QLabel{color: orange}')
    #                 self.btnEnDisWipeCode.setText('Enable')
    #                 self.btnEnDisWipeCode.setDisabled(True)
    #     except Exception as e:
    #         WndUtils.error_msg(str(e), True)
