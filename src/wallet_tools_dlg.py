#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-12
import logging
from enum import Enum
from typing import Optional

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import pyqtSlot, QAbstractTableModel, QVariant, Qt, QPoint, QItemSelection, QItemSelectionModel, \
    QEventLoop, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QDialog, QMenu, QApplication, QLineEdit, QShortcut, QMessageBox, QTableWidgetItem, QWidget
import app_cache
import app_defs
import hw_intf
from app_config import AppConfig
from common import InternalError
from create_rpcauth_wdg import WdgCreateRpcauth
from hw_common import HWDevice
from hw_initialize_wdg import WdgInitializeHw
from hw_settings_wdg import WdgHwSettings
from hw_udev_info_wdg import WdgHwUdevRules
from hw_update_firmware_wdg import WdgHwUpdateFirmware
from hw_wipe_device_wdg import WdgWipeHwDevice
from hw_recovery_wdg import WdgRecoverHw
from ui import ui_wallet_tools_dlg
from wallet_tools_common import ActionPageBase
from hw_intf import HWDevices
from wnd_utils import WndUtils

ACTION_NONE = 0
ACTION_HW_SETTINGS = 1
ACTION_RECOVER_HW = 2
ACTION_INITIALIZE_HW = 3
ACTION_WIPE_HW = 4
ACTION_UPDATE_HW_FIRMWARE = 5
ACTION_CREATE_RPCAUTH = 6
ACTION_UDEV_RULES = 7
ACTION_SPLIT_MERGE_SEED = 8


log = logging.getLogger('dmt.wallet_tools_dlg')


class Pages(Enum):
    PAGE_MENU = 0
    PAGE_ACTION = 1
    PAGE_MESSAGE = 2


class WalletToolsDlg(QDialog, ui_wallet_tools_dlg.Ui_WalletToolsDlg, WndUtils):
    def __init__(self, parent) -> None:
        QDialog.__init__(self, parent)
        ui_wallet_tools_dlg.Ui_WalletToolsDlg.__init__(self)
        WndUtils.__init__(self, parent.app_config)
        self.finishing = False
        self.main_ui = parent
        self.app_config: AppConfig = parent.app_config
        self.current_action = ACTION_NONE
        self.action_widget: Optional[ActionPageBase] = None
        self.action_layout: Optional[QtWidgets.QVBoxLayout] = None
        self.hw_devices = HWDevices.get_instance()
        if not self.hw_devices:
            raise InternalError('HWDevices not initialized')
        self.hw_devices.save_state()  # save the hw device currently connected in the main window
        self.hw_devices.set_allow_bootloader_mode(True)
        self.wdg_select_hw_device = CurrentHwDeviceWdg(self, self.hw_devices, True)
        self.hw_devices.sig_connected_hw_device_changed.connect(self.on_connected_hw_device_changed)
        self.setupUi(self)

    def setupUi(self, dlg):
        ui_wallet_tools_dlg.Ui_WalletToolsDlg.setupUi(self, self)
        self.setWindowTitle("Toolbox")
        WndUtils.change_widget_font_attrs(self.lblMessage, point_size_diff=3, bold=True)
        for action in (self.actHwSettings, self.actRecoverHw, self.actInitializeHw, self.actWipeHw,
                  self.actUpdateHwFirmware, self.actCreateRpcauth, self.actUdevRulesInfo):
            WndUtils.change_widget_font_attrs(action, point_size_diff=1, bold=False)
        self.activate_menu_page()

        lay = self.layout()
        lay.insertWidget(1, self.wdg_select_hw_device)  # hardware wallet selection panel is inserted just below the
                                                        # main title

        self.action_layout = QtWidgets.QVBoxLayout(self.fraActionContainer)
        self.action_layout.setContentsMargins(6, 6, 6, 6)
        self.action_layout.setSpacing(3)
        self.action_layout.setObjectName("action_layout")
        WndUtils.change_widget_font_attrs(self.lblTitle, point_size_diff=3, bold=True)

    def on_close(self):
        self.finishing = True
        if self.action_widget:
            self.action_widget.finishing = True
        self.hw_devices.sig_connected_hw_device_changed.disconnect(self.on_connected_hw_device_changed)
        self.hw_devices.restore_state()
        if self.action_widget:
            self.action_widget.on_close()

    def closeEvent(self, event):
        self.on_close()

    @pyqtSlot(bool)
    def on_btnCancel_clicked(self):
        try:
            if self.action_widget:
                if self.action_widget.on_before_cancel() is False:
                    # the action widget decided not to close
                    return
            self.close()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnClose_clicked(self):
        try:
            if self.action_widget:
                if self.action_widget.on_before_cancel() is False:
                    # the action widget decided not to close
                    return
            self.close()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnBack_clicked(self):
        try:
            if self.action_widget:
                self.action_widget.on_btn_back_clicked()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnContinue_clicked(self):
        try:
            if self.action_widget:
                self.action_widget.on_btn_continue_clicked()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_actHwSettings_clicked(self):
        try:
            self.setup_action_widget(ACTION_HW_SETTINGS)
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_actRecoverHw_clicked(self):
        try:
            self.setup_action_widget(ACTION_RECOVER_HW)
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_actInitializeHw_clicked(self):
        try:
            self.setup_action_widget(ACTION_INITIALIZE_HW)
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_actWipeHw_clicked(self):
        try:
            self.setup_action_widget(ACTION_WIPE_HW)
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_actUpdateHwFirmware_clicked(self):
        try:
            self.setup_action_widget(ACTION_UPDATE_HW_FIRMWARE)
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_actCreateRpcauth_clicked(self):
        try:
            self.setup_action_widget(ACTION_CREATE_RPCAUTH)
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_actUdevRulesInfo_clicked(self):
        try:
            self.setup_action_widget(ACTION_UDEV_RULES)
        except Exception as e:
            self.error_msg(str(e), True)

    def on_connected_hw_device_changed(self, cur_hw_device: HWDevice):
        self.wdg_select_hw_device.update()

    def activate_menu_page(self):
        self.tabsMain.setCurrentIndex(Pages.PAGE_MENU.value)
        self.lblTitle.setText('<a>Choose action</a>')
        self.btnCancel.setVisible(True)
        self.btnCancel.setEnabled(True)
        self.btnClose.setVisible(False)
        self.btnBack.setVisible(False)
        self.btnBack.setEnabled(True)
        self.btnContinue.setText('Continue')
        self.btnContinue.setVisible(False)
        self.btnContinue.setEnabled(True)
        self.wdg_select_hw_device.setVisible(False)
        self.wdg_select_hw_device.set_hw_change_enabled(True)
        self.current_action = ACTION_NONE

    def set_action_title(self, title: str):
        self.lblTitle.setText(title)

    def set_btn_close_visible(self, visible: bool):
        self.btnClose.setVisible(visible)

    def set_btn_close_enabled(self, enabled: bool):
        self.btnClose.setEnabled(enabled)

    def set_btn_cancel_visible(self, visible: bool):
        self.btnCancel.setVisible(visible)

    def set_btn_cancel_enabled(self, enabled: bool):
        self.btnCancel.setEnabled(enabled)

    def set_btn_cancel_text(self, label: str, tool_tip: Optional[str]):
        self.btnCancel.setText(label)
        if tool_tip:
            self.btnCancel.setToolTip(tool_tip)

    def set_btn_back_visible(self, visible: bool):
        self.btnBack.setVisible(visible)

    def set_btn_back_enabled(self, enabled: bool):
        self.btnBack.setEnabled(enabled)

    def set_btn_back_text(self, label: str, tool_tip: Optional[str]):
        self.btnBack.setText(label)
        if tool_tip:
            self.btnBack.setToolTip(tool_tip)

    def set_btn_continue_visible(self, visible: bool):
        self.btnContinue.setVisible(visible)

    def set_btn_continue_enabled(self, enabled: bool):
        self.btnContinue.setEnabled(enabled)

    def set_btn_continue_text(self, label: str, tool_tip: Optional[str]):
        self.btnContinue.setText(label)
        if tool_tip:
            self.btnContinue.setToolTip(tool_tip)

    def set_hw_panel_visible(self, visible: bool):
        if visible:
            self.wdg_select_hw_device.update()
        self.wdg_select_hw_device.setVisible(visible)

    def set_hw_change_enabled(self, enabled: bool):
        self.wdg_select_hw_device.set_hw_change_enabled(enabled)

    def show_message_page(self, message: Optional[str]):
        if message:
            self.lblMessage.setText(message)
        self.tabsMain.setCurrentIndex(Pages.PAGE_MESSAGE.value)

    def show_action_page(self):
        if self.tabsMain.currentIndex() != Pages.PAGE_ACTION.value:
            self.tabsMain.setCurrentIndex(Pages.PAGE_ACTION.value)

    def get_widget_action_type(self) -> int:
        # returns one of action type constants based on the widget class type in self.action_widget
        if self.action_widget:
            if isinstance(self.action_widget, WdgHwSettings):
                return ACTION_HW_SETTINGS
            elif isinstance(self.action_widget, WdgRecoverHw):
                return ACTION_RECOVER_HW
            elif isinstance(self.action_widget, WdgInitializeHw):
                return ACTION_INITIALIZE_HW
            elif isinstance(self.action_widget, WdgWipeHwDevice):
                return ACTION_WIPE_HW
            elif isinstance(self.action_widget, WdgHwUpdateFirmware):
                return ACTION_UPDATE_HW_FIRMWARE
            elif isinstance(self.action_widget, WdgCreateRpcauth):
                return ACTION_CREATE_RPCAUTH
            elif isinstance(self.action_widget, WdgHwUdevRules):
                return ACTION_UDEV_RULES
            else:
                raise Exception('Internal error: not supported type of the action widget')
        else:
            return ACTION_NONE

    # noinspection PyTypeChecker
    def setup_action_widget(self, action: int):
        try:
            if self.get_widget_action_type() != action:
                if self.action_widget is not None:
                    self.action_widget.on_close()
                    self.action_layout.removeWidget(self.action_widget)
                    self.action_widget.setParent(None)
                    del self.action_widget
                    self.action_widget = None

                if action == ACTION_HW_SETTINGS:
                    self.action_widget = WdgHwSettings(self, self.hw_devices)
                    self.action_layout.addWidget(self.action_widget)
                elif action == ACTION_RECOVER_HW:
                    self.action_widget = WdgRecoverHw(self, self.hw_devices)
                    self.action_layout.addWidget(self.action_widget)
                elif action == ACTION_INITIALIZE_HW:
                    self.action_widget = WdgInitializeHw(self, self.hw_devices)
                    self.action_layout.addWidget(self.action_widget)
                elif action == ACTION_WIPE_HW:
                    self.action_widget = WdgWipeHwDevice(self, self.hw_devices)
                    self.action_layout.addWidget(self.action_widget)
                elif action == ACTION_UPDATE_HW_FIRMWARE:
                    self.action_widget = WdgHwUpdateFirmware(self, self.hw_devices)
                    self.action_layout.addWidget(self.action_widget)
                elif action == ACTION_CREATE_RPCAUTH:
                    self.action_widget = WdgCreateRpcauth(self, self.hw_devices)
                    self.action_layout.addWidget(self.action_widget)
                elif action == ACTION_UDEV_RULES:
                    self.action_widget = WdgHwUdevRules(self, self.hw_devices)
                    self.action_layout.addWidget(self.action_widget)
                else:
                    raise Exception('Internal error: not supported action type')

                self.action_widget.set_control_functions(
                    fn_exit_page=self.activate_menu_page,
                    fn_set_action_title=self.set_action_title,
                    fn_set_btn_close_visible=self.set_btn_close_visible,
                    fn_set_btn_close_enabled=self.set_btn_close_enabled,
                    fn_set_btn_cancel_visible=self.set_btn_cancel_visible,
                    fn_set_btn_cancel_enabled=self.set_btn_cancel_enabled,
                    fn_set_btn_cancel_text=self.set_btn_cancel_text,
                    fn_set_btn_back_visible=self.set_btn_back_visible,
                    fn_set_btn_back_enabled=self.set_btn_back_enabled,
                    fn_set_btn_back_text=self.set_btn_back_text,
                    fn_set_btn_continue_visible=self.set_btn_continue_visible,
                    fn_set_btn_continue_enabled=self.set_btn_continue_enabled,
                    fn_set_btn_continue_text=self.set_btn_continue_text,
                    fn_set_hw_panel_visible=self.set_hw_panel_visible,
                    fn_set_hw_change_enabled=self.set_hw_change_enabled,
                    fn_show_message_page=self.show_message_page,
                    fn_show_action_page=self.show_action_page
                )

            self.current_action = action
            self.tabsMain.setCurrentIndex(Pages.PAGE_ACTION.value)
            self.action_widget.initialize()

        except Exception as e:
            self.error_msg(str(e), True)


class CurrentHwDeviceWdg(QWidget):
    """
    Widget presenting the currently selected hardware wallet and allowing it to be changed to another one.

    It is displayed at the top of the dialog, but only in the tabs whose functionality relates to operations
    using the hardware wallets.
    """

    def __init__(self, parent, hw_devices: HWDevices, hw_change_enabled: bool = True):
        QWidget.__init__(self, parent=parent,)
        self.hw_devices: HWDevices = hw_devices
        self.hw_change_enabled: bool = hw_change_enabled
        self.setupUi(self)

    def setupUi(self, dlg):
        dlg.setObjectName("SelectHwDeviceWdg")
        self.layout_main = QtWidgets.QHBoxLayout(dlg)
        self.layout_main.setContentsMargins(0, 0, 0, 0)
        self.layout_main.setSpacing(0)

        self.lbl_current_hw_device = QtWidgets.QLabel(dlg)
        self.lbl_current_hw_device.linkActivated.connect(self.on_hw_device_selected)
        self.layout_main.addWidget(self.lbl_current_hw_device)

        WndUtils.change_widget_font_attrs(self.lbl_current_hw_device, point_size_diff=-1, bold=False)
        spacer = QtWidgets.QSpacerItem(20, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.layout_main.addItem(spacer)

    def set_hw_change_enabled(self, enabled):
        self.hw_change_enabled = enabled
        self.update()

    def update(self):
        try:
            dev = self.hw_devices.get_selected_device()
            if dev:
                lbl = 'Device selected: <b>' + dev.get_description()
                if self.hw_change_enabled:
                    lbl += '</b> [<a href="select-hw-device">change</a>]'
            else:
                lbl = 'No hardware wallet device selected'
                if self.hw_change_enabled:
                    lbl += ' [<a href="select-hw-device">select</a>]'
            self.lbl_current_hw_device.setText(lbl)

        except Exception as e:
            logging.exception(str(e))

    def on_hw_device_selected(self, anchor: str):
        try:
            if self.hw_change_enabled:
                self.hw_devices.select_device(self.parent(), open_client_session=True)
        except Exception as e:
            WndUtils.error_msg(str(e))