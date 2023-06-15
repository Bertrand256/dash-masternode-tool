#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
from enum import Enum

import qdarkstyle
import simplejson
import datetime
import os
import platform
import re
import sys
import threading
import time
import ssl
from typing import Optional, Tuple, Dict, Callable, List
import logging

import urllib.request
from PyQt5 import QtCore
from PyQt5 import QtWidgets
from PyQt5.QtCore import QSize, pyqtSlot, QEventLoop, QMutex, QWaitCondition, QUrl, Qt, QTimer
from PyQt5.QtGui import QFont, QIcon, QDesktopServices, QPalette, QShowEvent
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QFileDialog, QMenu, QMainWindow, QPushButton, QStyle, QInputDialog, QApplication, \
    QHBoxLayout, QAction, QToolButton, QWidgetAction
from PyQt5.QtWidgets import QMessageBox

import reg_masternode_dlg
import revoke_mn_dlg
import upd_mn_registrar_dlg
import upd_mn_service_dlg
import wnd_utils
from app_main_view_wdg import WdgAppMainView
from app_runtime_data import AppRuntimeData
from bip44_wallet import find_wallet_addresses, Bip44Wallet
from cmd_console_dlg import CmdConsoleDlg
from common import CancelException
from config_dlg import ConfigDlg
import about_dlg
import app_cache
import wallet_dlg
import app_utils
from masternode_details_wdg import WdgMasternodeDetails
from proposals_dlg import ProposalsDlg
from app_config import AppConfig, MasternodeConfig, DMN_ROLE_OWNER, DMN_ROLE_OPERATOR, InputKeyType, MasternodeType
from app_defs import PROJECT_URL, APP_NAME_SHORT, DispMessage, AppTextMessageType
from dashd_intf import DashdInterface, DashdIndexException
from hw_common import HWPinException, HWType, HWDevice, HWNotConnectedException
import hw_intf
from hw_intf import HwSessionInfo
from psw_cache import SshPassCache
from sign_message_dlg import SignMessageDlg
from wallet_tools_dlg import WalletToolsDlg
from wnd_utils import WndUtils, QDetectThemeChange, get_widget_font_color_green, get_widget_font_color_default
from ui import ui_main_dlg

log = logging.getLogger('dmt.main')


class MainWindow(QMainWindow, QDetectThemeChange, WndUtils, ui_main_dlg.Ui_MainWindow):
    update_status_signal = QtCore.pyqtSignal(str, str)  # signal for updating status text from inside thread

    def __init__(self, app_dir, internal_ui_dark_mode_activated: bool = False):
        QMainWindow.__init__(self)
        QDetectThemeChange.__init__(self)
        WndUtils.__init__(self, None)
        ui_main_dlg.Ui_MainWindow.__init__(self)

        self.finishing = False
        self.app_messages: Dict[int, DispMessage] = {}
        self.app_config = AppConfig(internal_ui_dark_mode_activated)
        self.app_config.init(app_dir)
        self.app_config.display_app_message.connect(self.add_app_message)
        WndUtils.set_app_config(self, self.app_config)

        self.dashd_intf = DashdInterface(window=None,
                                         on_connection_initiated_callback=self.show_connection_initiated,
                                         on_connection_failed_callback=self.show_connection_failed,
                                         on_connection_successful_callback=self.show_connection_successful,
                                         on_connection_disconnected_callback=self.show_connection_disconnected)

        self.app_rt_data = AppRuntimeData(self.app_config, self.dashd_intf)
        self.hw_session = HwSessionInfo(self, self.app_config, self.app_rt_data)
        self.hw_session.sig_hw_connected.connect(self.on_hardware_wallet_connected)
        self.hw_session.sig_hw_disconnected.connect(self.on_hardware_wallet_disconnected)
        self.hw_session.sig_hw_connection_error.connect(self.on_hardware_wallet_connection_error)

        self.is_dashd_syncing = False
        self.dashd_connection_ok = False
        self.connecting_to_dashd = False
        self.editing_enabled = False
        self.recent_config_files = []

        # load most recently used config files from the data cache
        mru_cf = app_cache.get_value('MainWindow_ConfigFileMRUList', default_value=[], type=list)
        if isinstance(mru_cf, list):
            for file_name in mru_cf:
                if os.path.exists(file_name) and file_name not in self.recent_config_files:
                    self.recent_config_files.append(file_name)

        self.cmd_console_dlg = None
        self.main_view: Optional[WdgAppMainView] = None
        self.lblStatus1 = QtWidgets.QLabel(self)
        self.lblStatus2 = QtWidgets.QLabel(self)
        self.inside_setup_ui = True
        self.setupUi(self)
        ssl._create_default_https_context = ssl._create_unverified_context

    def setupUi(self, main_dlg: QMainWindow):
        ui_main_dlg.Ui_MainWindow.setupUi(self, self)
        SshPassCache.set_parent_window(self)
        self.restore_cache_settings()
        self.dashd_intf.window = self
        self.lblStatus1.setAutoFillBackground(False)
        self.lblStatus1.setOpenExternalLinks(True)
        self.lblStatus1.setOpenExternalLinks(True)
        self.statusBar.addPermanentWidget(self.lblStatus1, 1)
        self.lblStatus1.setText('')
        self.statusBar.addPermanentWidget(self.lblStatus2, 2)
        self.lblStatus2.setText('')
        self.lblStatus2.setOpenExternalLinks(True)
        self.show_connection_disconnected()
        self.set_status_text2('<b>HW status:</b> idle')
        self.update_styles()

        WndUtils.set_icon(self, self.action_save_config_file, 'action-save.png',
                          icon_disabled='action-save-disabled.png')
        WndUtils.set_icon(self, self.action_check_network_connection, "action-connect-network.png",
                          icon_disabled="action-connect-network-disabled.png")
        WndUtils.set_icon(self, self.action_open_settings_window, "action-settings.png",
                          icon_disabled='action-settings-disabled.png')
        WndUtils.set_icon(self, self.action_open_proposals_window, "action-proposals.png",
                          icon_disabled="action-proposals-disabled.png")
        WndUtils.set_icon(self, self.action_connect_hw, "action-connect-hw.png",
                          icon_disabled="action-connect-hw-disabled.png")
        WndUtils.set_icon(self, self.action_disconnect_hw, "action-disconnect-hw.png",
                          icon_disabled="action-disconnect-hw-disabled.png")
        WndUtils.set_icon(self, self.action_hw_wallet, "action-wallet.png", icon_disabled="action-wallet-disabled.png")
        WndUtils.set_icon(self, self.action_wallet_tools, "action-tools.png", icon_disabled="action-tools-disabled.png")
        WndUtils.set_icon(self, self.action_show_masternode_details, "view-list@16px.png")
        WndUtils.set_icon(self, self.action_new_masternode_entry, "add@16px.png")
        WndUtils.set_icon(self, self.action_new_masternode_entry, "add@16px.png")
        WndUtils.set_icon(self, self.action_clone_masternode_entry, "content-copy@16px.png")
        WndUtils.set_icon(self, self.action_delete_masternode_entry, "delete@16px.png")

        # icons will not be visible in menu
        self.action_save_config_file.setIconVisibleInMenu(False)
        self.action_check_network_connection.setIconVisibleInMenu(False)
        self.action_open_settings_window.setIconVisibleInMenu(False)
        self.action_open_proposals_window.setIconVisibleInMenu(False)
        self.action_connect_hw.setIconVisibleInMenu(False)
        self.action_disconnect_hw.setIconVisibleInMenu(False)
        self.action_run_trezor_emulator.setIconVisibleInMenu(False)
        self.action_run_trezor_emulator.setVisible(False)
        self.action_hw_wallet.setIconVisibleInMenu(False)

        # register dialog-type actions:
        self.addAction(self.action_gen_mn_priv_key_uncompressed)
        self.addAction(self.action_gen_mn_priv_key_compressed)

        l = self.gbMain.layout()
        self.main_view = WdgAppMainView(self, self.app_config, self.dashd_intf, self.hw_session)
        l.insertWidget(0, self.main_view)
        self.main_view.masternode_data_changed.connect(self.on_masternode_data_changed)
        self.main_view.cur_masternode_changed.connect(self.on_cur_masternode_changed)
        self.main_view.app_text_message_sent.connect(self.add_app_message)

        self.inside_setup_ui = False
        self.display_app_messages()
        logging.info('Finished setup of the main dialog.')

    def showEvent(self, event: QShowEvent):
        def load_initial_config():
            # Initial opening of the configuration file may involve showing some dialog boxes (e.g.
            # related to file encryption), so reading the configuration must be performed only after
            # the UI initialization. We do this through Qt's singleShot of this function.
            try:
                self.load_configuration_from_file(None)
                self.run_thread(self, self.get_project_config_params_thread, (False,))
                self.main_view.update_ui()
            except Exception as e:
                log.exception(str(e))
                WndUtils.error_msg(str(e))

        QTimer.singleShot(10, load_initial_config)
        QDetectThemeChange.showEvent(self, event)

    def closeEvent(self, event):
        if self.app_config.is_modified():
            res = self.query_dlg('Configuration modified. Save?',
                                 buttons=QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                                 default_button=QMessageBox.Yes, icon=QMessageBox.Information)
            if res == QMessageBox.Yes:
                self.save_configuration()
            elif res == QMessageBox.Cancel:
                event.ignore()
                return

        self.save_cache_settings()
        self.finishing = True
        if self.dashd_intf:
            self.dashd_intf.disconnect()
        self.main_view.on_close()
        self.app_config.close()

    def restore_cache_settings(self):
        app_cache.restore_window_size(self)

    def save_cache_settings(self):
        app_cache.save_window_size(self)

    def onThemeChanged(self):
        self.update_styles()
        self.display_app_messages()

    def update_styles(self):
        p = self.palette()
        bg_color_active = p.color(QPalette.Normal, p.Base).name()
        bg_color_inactive = p.color(QPalette.Inactive, p.Window).name()
        style = f"QLineEdit, QTextEdit {{background-color: {bg_color_active};}} " \
                f"QLineEdit:read-only, QTextEdit[readonly=true] {{background-color: {bg_color_inactive};}} "
        self.setStyleSheet(style)

        green_color = get_widget_font_color_green(self)
        style = f'QLabel[level="success"]{{color:{green_color}}} ' \
                f'QLabel[level="warning"]{{color:#ff6600}} ' \
                f'QLabel[level="error"]{{background-color:red;color:white}} ' \
                f'QLabel{{margin-right:20px;margin-left:8px}}'
        self.lblStatus1.setStyleSheet(style)
        self.lblStatus2.setStyleSheet(style)

    def configuration_to_ui(self):
        """
        Show the information read from the configuration file on the user interface.
        :return:
        """
        self.update_app_ui_theme()
        self.main_view.configuration_to_ui()
        self.action_open_log_file.setText('Open log file (%s)' % self.app_config.log_file)
        self.update_edit_controls_state()

    def update_app_ui_theme(self):
        if self.app_config.ui_use_dark_mode:
            if not self.app_config.internal_ui_dark_mode_activated:
                app = QApplication.instance()
                app.setStyleSheet(qdarkstyle.load_stylesheet())
                self.app_config.internal_ui_dark_mode_activated = True
        else:
            if self.app_config.internal_ui_dark_mode_activated:
                app = QApplication.instance()
                app.setStyleSheet('')
                self.app_config.internal_ui_dark_mode_activated = False

    def load_configuration_from_file(self, file_name: Optional[str], ask_save_changes=True,
                                     update_current_file_name=True) -> None:
        """
        Load configuration from a file.
        :param file_name: Name of the configuration file to be loaded into the application. If the value is Noney, then
          the default file name will be used (the last file opened).
        """
        if self.app_config.is_modified() and ask_save_changes:
            ret = self.query_dlg('Current configuration has been modified. Save?',
                                 buttons=QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                                 default_button=QMessageBox.Yes, icon=QMessageBox.Warning)
            if ret == QMessageBox.Yes:
                self.save_configuration()
            elif ret == QMessageBox.Cancel:
                self.update_config_files_mru_menu_items()
                return

        try:
            dash_network_sav = self.app_config.dash_network
            self.app_config.read_from_file(hw_session=self.hw_session, file_name=file_name,
                                           update_current_file_name=update_current_file_name,
                                           create_config_file=(not file_name))
            if not self.dashd_intf.initialized:
                self.dashd_intf.initialize(self.app_config)
            self.editing_enabled = False
            self.configuration_to_ui()
            self.dashd_intf.reload_configuration()
            file_name = self.app_config.app_config_file_name
            if file_name:
                self.add_item_to_config_files_mru_list(file_name)
                self.update_config_files_mru_menu_items()
                if dash_network_sav != self.app_config.dash_network:
                    self.app_config.reset_network_dependent_dyn_params()
            wnd_utils.set_app_config(self.app_config)
            self.display_window_title()
        except CancelException:
            self.update_config_files_mru_menu_items()

    def new_configuration_file(self) -> None:
        if self.app_config.is_modified():
            ret = self.query_dlg('Current configuration has been modified. Save?',
                                 buttons=QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                                 default_button=QMessageBox.Yes, icon=QMessageBox.Warning)
            if ret == QMessageBox.Yes:
                self.save_configuration()
            elif ret == QMessageBox.Cancel:
                self.update_config_files_mru_menu_items()
                return

        try:
            dash_network_sav = self.app_config.dash_network
            self.app_config.new_configuration()

            if not self.dashd_intf.initialized:
                self.dashd_intf.initialize(self.app_config)
            self.editing_enabled = False
            self.configuration_to_ui()
            self.dashd_intf.reload_configuration()
            file_name = self.app_config.app_config_file_name
            if file_name:
                self.add_item_to_config_files_mru_list(file_name)
                self.update_config_files_mru_menu_items()
                if dash_network_sav != self.app_config.dash_network:
                    self.disconnect_hardware_wallet()
                    self.app_config.reset_network_dependent_dyn_params()
            self.display_window_title()
        except CancelException:
            self.update_config_files_mru_menu_items()

    def add_item_to_config_files_mru_list(self, file_name: str) -> None:
        """
        Add a file name to the list of recently open config files. This list acts as a source for
        the 'Open Recent' menu subitems. This method is called after each successful loading configuration
        from the 'file_name' config file.
        :param file_name: A name of the file to be added to the list.
        """
        if file_name:
            try:
                if file_name in self.recent_config_files:
                    idx = self.recent_config_files.index(file_name)
                    del self.recent_config_files[idx]
                    self.recent_config_files.insert(0, file_name)
                else:
                    self.recent_config_files.insert(0, file_name)
                app_cache.set_value('MainWindow_ConfigFileMRUList', self.recent_config_files)
            except Exception as e:
                logging.warning(str(e))

    def update_config_files_mru_menu_items(self):
        app_utils.update_mru_menu_items(self.recent_config_files, self.action_open_recent_files,
                                        self.on_config_file_mru_action_triggered,
                                        self.app_config.app_config_file_name,
                                        self.on_config_file_mru_clear_triggered)

    def on_config_file_mru_action_triggered(self, file_name: str) -> None:
        """ Triggered by clicking one of the subitems of the 'Open Recent' menu item. Each subitem is
        related to one of recently opened configuration files.
        :param file_name: A config file name associated with the menu action clicked.
        """
        try:
            if file_name != self.app_config.app_config_file_name:
                self.load_configuration_from_file(file_name)
        except Exception as e:
            self.error_msg(str(e), True)

    def on_config_file_mru_clear_triggered(self):
        """Clear items in the recent config files menu."""
        try:
            self.recent_config_files.clear()
            app_cache.set_value('MainWindow_ConfigFileMRUList', self.recent_config_files)
            self.update_config_files_mru_menu_items()
        except Exception as e:
            self.error_msg(str(e), True)

    def display_window_title(self):
        """
        Display main window title, which is composed of the application name, nick of the creator and
        the name of the current configuration file. This method is executed after each successful loading
        of the configuration file.
        """
        app_version_part = ' (v' + self.app_config.app_version + ')' if self.app_config.app_version else ''

        if self.app_config.dash_network == 'TESTNET':
            testnet_part = ' [TESTNET]'
        else:
            testnet_part = ''

        if self.app_config.app_config_file_name:
            cfg_file_name = self.app_config.app_config_file_name
            if cfg_file_name:
                home_dir = os.path.expanduser('~')
                if cfg_file_name.find(home_dir) == 0:
                    cfg_file_name = '~' + cfg_file_name[len(home_dir):]
                else:
                    cfg_file_name = cfg_file_name
            cfg_file_name_part = ' - ' + cfg_file_name if cfg_file_name else ''
        else:
            cfg_file_name_part = '  (new file)'

        if self.app_config.config_file_encrypted:
            encrypted_part = ' (Encrypted)'
        else:
            encrypted_part = ''

        title = f'{APP_NAME_SHORT}{app_version_part}{testnet_part}{cfg_file_name_part}{encrypted_part}'

        self.setWindowTitle(title)

    @pyqtSlot(bool)
    def on_action_new_configuration_triggered(self, _):
        try:
            self.new_configuration_file()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_load_config_file_triggered(self, checked):
        try:
            if self.app_config.app_config_file_name:
                dir = os.path.dirname(self.app_config.app_config_file_name)
            else:
                dir = self.app_config.data_dir
            file_name = self.open_config_file_query(dir, self, self.app_config)

            if file_name:
                if os.path.exists(file_name):
                    self.load_configuration_from_file(file_name)
                else:
                    WndUtils.error_msg(f'File \'{file_name}\' does not exist.')
        except Exception as e:
            self.error_msg(str(e), True)

    def save_configuration(self, file_name: str = None):
        if self.main_view.is_editing_enabled():
            self.main_view.apply_masternode_changes()
        self.app_config.save_to_file(hw_session=self.hw_session, file_name=file_name)
        file_name = self.app_config.app_config_file_name
        if file_name:
            self.add_item_to_config_files_mru_list(file_name)
        self.update_config_files_mru_menu_items()
        self.display_window_title()
        self.editing_enabled = self.app_config.is_modified()
        self.main_view.set_edit_mode(self.editing_enabled)
        self.update_edit_controls_state()

    @pyqtSlot(bool)
    def on_action_save_config_file_triggered(self, checked):
        try:
            self.save_configuration()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_save_config_file_as_triggered(self, checked):
        try:
            if self.app_config.app_config_file_name:
                dir = os.path.dirname(self.app_config.app_config_file_name)
            else:
                dir = self.app_config.data_dir
            file_name = self.save_config_file_query(dir, self, self.app_config)

            if file_name:
                self.save_configuration(file_name)
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_export_configuration_triggered(self, checked):
        try:
            if self.app_config.app_config_file_name:
                dir = os.path.dirname(self.app_config.app_config_file_name)
            else:
                dir = self.app_config.data_dir
            file_name = self.save_config_file_query(dir, self, self.app_config)

            if file_name:
                self.app_config.save_to_file(hw_session=self.hw_session, file_name=file_name,
                                             update_current_file_name=False)
                WndUtils.info_msg('Configuration has been exported.')
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_import_configuration_triggered(self, checked):
        try:
            if self.app_config.app_config_file_name:
                dir = os.path.dirname(self.app_config.app_config_file_name)
            else:
                dir = self.app_config.data_dir
            file_name = self.open_config_file_query(dir, self, self.app_config)

            if file_name:
                if os.path.exists(file_name):
                    self.load_configuration_from_file(file_name, ask_save_changes=False,
                                                      update_current_file_name=False)
                    self.update_edit_controls_state()
                    WndUtils.info_msg('Configuration has been imported.')
                else:
                    WndUtils.error_msg(f'File \'{file_name}\' does not exist.')
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_open_log_file_triggered(self, checked):
        if os.path.exists(self.app_config.log_file):
            try:
                ret = QDesktopServices.openUrl(QUrl("file:///%s" % self.app_config.log_file))
                if not ret:
                    self.warn_msg('Could not open "%s" file using a default OS application.' % self.app_config.log_file)
            except Exception as e:
                self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_restore_config_from_backup_triggered(self, checked):
        try:
            input = QInputDialog(self)
            input.setComboBoxEditable(False)
            input.setOption(QInputDialog.UseListViewForComboBoxItems, True)
            input.setWindowTitle('Restore from backup')
            file_dates: List[Tuple[str, float, str]] = []

            for fname in os.listdir(self.app_config.cfg_backup_dir):
                try:
                    fpath = os.path.join(self.app_config.cfg_backup_dir, fname)
                    if os.path.isfile(fpath):
                        datetime.datetime.now().strftime('%Y-%m-%d %H_%M')
                        m = re.match(r'config_(\d{4}-\d{2}-\d{2}\s\d{2}_\d{2})', fname)
                        if m and len(m.groups()) == 1:
                            d = datetime.datetime.strptime(m.group(1), '%Y-%m-%d %H_%M')
                            file_dates.append((app_utils.to_string(d), d.timestamp(), fpath))
                except Exception as e:
                    logging.error(str(e))

            file_dates.sort(key=lambda x: x[1], reverse=True)
            cbo_items = []
            if file_dates:
                for idx, (date_str, ts, file_name) in enumerate(file_dates):
                    disp_text = str(idx + 1) + '. ' + date_str
                    file_dates[idx] = (disp_text, ts, file_name)
                    cbo_items.append(disp_text)

                input.setOkButtonText('Restore configuration')
                input.setLabelText('Select the backup date to be restored:')
                input.setComboBoxItems(cbo_items)
                if input.exec():
                    sel_item = input.textValue()
                    idx = cbo_items.index(sel_item)
                    if idx >= 0:
                        _, _, file_name_to_restore = file_dates[idx]
                        self.load_configuration_from_file(file_name_to_restore, ask_save_changes=False,
                                                          update_current_file_name=False)
                        self.update_edit_controls_state()
            else:
                self.error_msg("Couldn't find any backup file.")
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_open_data_folder_triggered(self, checked):
        if os.path.exists(self.app_config.data_dir):
            try:
                ret = QDesktopServices.openUrl(QUrl("file:///%s" % self.app_config.data_dir))
                if not ret:
                    self.warn_msg(
                        'Could not open "%s" folder using a default OS application.' % self.app_config.data_dir)
            except Exception as e:
                self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_show_contact_information_triggered(self, checked):
        try:
            WndUtils.show_contact_information()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_clear_wallet_cache_triggered(self, checked):
        if self.query_dlg('Do you really want to clear the wallet cache?',
                          buttons=QMessageBox.Yes | QMessageBox.Cancel,
                          default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Yes:
            db_cursor = self.app_config.db_intf.get_cursor()
            try:
                db_cursor.execute('drop table address')
                db_cursor.execute('drop table hd_tree')
                db_cursor.execute('drop table tx_input')
                db_cursor.execute('drop table tx_output')
                db_cursor.execute('drop table tx')
                self.app_config.db_intf.create_structures()
            finally:
                self.app_config.db_intf.release_cursor()
            self.info_msg('Wallet cache cleared.')

    @pyqtSlot(bool)
    def on_action_clear_proposals_cache_triggered(self, checked):
        if self.query_dlg('Do you really want to clear the proposals cache?',
                          buttons=QMessageBox.Yes | QMessageBox.Cancel,
                          default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Yes:
            db_cursor = self.app_config.db_intf.get_cursor()
            try:
                db_cursor.execute('drop table proposals')
                db_cursor.execute('drop table voting_results')
                self.app_config.db_intf.create_structures()
            finally:
                self.app_config.db_intf.release_cursor()
            self.info_msg('Proposals cache cleared.')

    @pyqtSlot(bool)
    def on_action_check_for_updates_triggered(self, checked, force_check=True):
        try:
            self.run_thread(self, self.get_project_config_params_thread, (force_check,))
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_command_console_triggered(self, checked):
        try:
            if not self.cmd_console_dlg:
                self.cmd_console_dlg = CmdConsoleDlg(self, self.app_config)
            self.cmd_console_dlg.exec_()
        except Exception as e:
            self.error_msg(str(e), True)

    def get_project_config_params_thread(self, ctrl, force_check):
        """
        Thread function checking whether there is a new version of the application on GitHub page.
        :param ctrl: thread control structure (not used here) 
        :param force_check: True if version-check has been invoked by the user, not the app itself.
        :return: None
        """
        try:
            response = urllib.request.urlopen(
                'https://raw.githubusercontent.com/Bertrand256/dash-masternode-tool/master/app-params.json',
                context=ssl._create_unverified_context())
            contents = response.read()

            remote_app_params = simplejson.loads(contents)
            self.app_config.set_remote_app_params(remote_app_params)

            if remote_app_params:
                logging.info('Loaded the project configuration params: ' + str(remote_app_params))
                if self.app_config.check_for_updates or force_check:
                    remote_version_str = remote_app_params.get("appCurrentVersion")
                    if remote_version_str:
                        if app_utils.is_version_greater(remote_version_str, self.app_config.app_version):
                            if sys.platform == 'win32':
                                item_name = 'win'
                                no_bits = platform.architecture()[0].replace('bit', '')
                                if no_bits == '32':
                                    item_name += '32'
                                else:
                                    item_name += '64'
                            elif sys.platform == 'darwin':
                                item_name = 'mac'
                            else:
                                item_name = 'linux'
                            exe_url = ''
                            exe_down = remote_app_params.get('exeDownloads')
                            if exe_down:
                                exe_url = exe_down.get(item_name)
                            if exe_url:
                                msg = "New version (" + remote_version_str + ') available: <a href="' + exe_url + \
                                      '">download</a>.'
                            else:
                                msg = "New version (" + remote_version_str + ') available. Go to the project ' \
                                                                             'website: <a href="' + \
                                      PROJECT_URL + '">open</a>.'

                            self.add_app_message(DispMessage.NEW_VERSION, msg, AppTextMessageType.INFO)
                        else:
                            if force_check:
                                self.add_app_message(DispMessage.NEW_VERSION, "You have the latest version of %s."
                                                     % APP_NAME_SHORT, AppTextMessageType.INFO)
                    elif force_check:
                        self.add_app_message(DispMessage.NEW_VERSION, "Could not read the remote version number.",
                                             AppTextMessageType.WARN)

        except Exception:
            logging.exception('Exception occurred while loading/processing the project remote configuration')

    @pyqtSlot(bool)
    def on_action_open_settings_window_triggered(self):
        try:
            dash_network_sav = self.app_config.dash_network
            dlg = ConfigDlg(self, self.app_config)
            res = dlg.exec_()
            if res:
                if dlg.get_global_options_modified():
                    # user modified options are not related to config file - stored in cache
                    self.update_app_ui_theme()

                if dlg.get_is_modified():
                    self.app_config.configure_cache()
                    self.dashd_intf.reload_configuration()
                    if dash_network_sav != self.app_config.dash_network:
                        self.disconnect_hardware_wallet()
                        self.app_config.reset_network_dependent_dyn_params()
                    self.main_view.config_changed()
                    self.display_window_title()
                    self.update_edit_controls_state()
            del dlg
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_about_app_triggered(self):
        try:
            ui = about_dlg.AboutDlg(self, self.app_config.app_version)
            ui.exec_()
        except Exception as e:
            self.error_msg(str(e), True)

    def show_connection_initiated(self):
        """Shows status information related to a initiated process of connection to a dash RPC. """
        self.set_status_text1('<b>RPC network status:</b> trying %s...' % self.dashd_intf.get_active_conn_description())

    def show_connection_failed(self):
        """Shows status information related to a failed connection attempt. There can be more attempts to connect
        to another nodes if there are such in configuration."""
        self.set_status_text1(
            '<b>RPC network status:</b> failed connection to %s' % self.dashd_intf.get_active_conn_description(),
            'error')

    def show_connection_successful(self):
        """Shows status information after successful connection to a Dash RPC node."""
        self.set_status_text1('<b>RPC network status:</b> OK (%s)' % self.dashd_intf.get_active_conn_description(),
                              'success')

    def show_connection_disconnected(self):
        """Shows status message related to disconnection from Dash RPC node."""
        self.set_status_text1('<b>RPC network status:</b> not connected')

    def connect_dash_network(self, wait_for_check_finish=False, call_on_check_finished=None):
        """
        Connects do dash daemon if not connected before and returns if it was successful.
        :param wait_for_check_finish: True if function is supposed to wait until connection check is finished (process
            is executed in background)
        :param call_on_check_finished: ref to function to be called after connection test (successful or unsuccessful)
            is finished
        """

        # if wait_for_check_finish is True, we have to process QT events while waiting for thread to terminate to
        # avoid deadlocking of functions: connect_thread and connect_finished
        if wait_for_check_finish:
            event_loop = QEventLoop(self)
        else:
            event_loop = None

        def wait_for_synch_finished_thread(ctrl):
            """
            Thread waiting for dash daemon to finish synchronizing.
            """
            mtx = QMutex()
            cond = QWaitCondition()
            try:
                logging.info('wait_for_synch_finished_thread')
                mtx.lock()
                while not ctrl.finish:
                    synced = self.dashd_intf.issynchronized()
                    if synced:
                        self.is_dashd_syncing = False
                        self.show_connection_successful()
                        break
                    mnsync = self.dashd_intf.mnsync()
                    self.add_app_message(
                        DispMessage.DASH_NET_CONNECTION,
                        'Dashd is synchronizing: AssetID: %s, AssetName: %s' %
                        (str(mnsync.get('AssetID', '')), str(mnsync.get('AssetName', ''))), AppTextMessageType.WARN)
                    cond.wait(mtx, 5000)
                self.del_app_message(DispMessage.DASH_NET_CONNECTION)
            except Exception as e:
                self.is_dashd_syncing = False
                self.dashd_connection_ok = False
                self.add_app_message(DispMessage.DASH_NET_CONNECTION, str(e), AppTextMessageType.ERROR)
            finally:
                mtx.unlock()
                self.wait_for_dashd_synced_thread = None

        def connect_thread(ctrl):
            """
            Test connection to dash network inside a thread to avoid blocking GUI.
            :param ctrl: control structure to communicate with WorkerThread object (not used here)
            """
            try:
                synced = self.dashd_intf.issynchronized()
                self.dashd_intf.getblockchaininfo(verify_node=True)
                self.dashd_connection_ok = True
                if not synced:
                    logging.info("dashd not synced")
                    if not self.is_dashd_syncing and not (hasattr(self, 'wait_for_dashd_synced_thread') and
                                                          self.wait_for_dashd_synced_thread is not None):
                        self.is_dashd_syncing = True
                        self.wait_for_dashd_synced_thread = self.run_thread(self, wait_for_synch_finished_thread, (),
                                                                            on_thread_finish=connect_finished)
                else:
                    self.is_dashd_syncing = False
                self.del_app_message(DispMessage.DASH_NET_CONNECTION)
            except Exception as e:
                err = str(e)
                if not err:
                    err = 'Connect error: %s' % type(e).__name__
                self.is_dashd_syncing = False
                self.dashd_connection_ok = False
                self.show_connection_failed()
                self.add_app_message(DispMessage.DASH_NET_CONNECTION, err, AppTextMessageType.ERROR)

        def connect_finished():
            """
            Called after thread terminates.
            """
            del self.check_conn_thread
            self.check_conn_thread = None
            self.connecting_to_dashd = False
            self.app_config.read_dash_network_app_params(self.dashd_intf)
            if call_on_check_finished:
                call_on_check_finished()
            if event_loop:
                event_loop.exit()

        if self.app_config.is_config_complete():
            if not hasattr(self, 'check_conn_thread') or self.check_conn_thread is None:

                if hasattr(self, 'wait_for_dashd_synced_thread') and self.wait_for_dashd_synced_thread is not None:
                    if call_on_check_finished is not None:
                        # if a thread waiting for dashd to finish synchronizing is running, call the callback function
                        call_on_check_finished()
                else:
                    self.connecting_to_dashd = True
                    self.check_conn_thread = self.run_thread(self, connect_thread, (),
                                                             on_thread_finish=connect_finished)
                    if wait_for_check_finish:
                        event_loop.exec()
        else:
            # configuration is not complete
            logging.warning("config not complete")
            self.is_dashd_syncing = False
            self.dashd_connection_ok = False

    @pyqtSlot(bool)
    def on_action_check_network_connection_triggered(self):
        try:
            self.test_dash_network_connection()
        except Exception as e:
            self.error_msg(str(e), True)

    def test_dash_network_connection(self):
        def connection_test_finished():

            self.action_check_network_connection.setEnabled(True)
            self.action_hw_wallet.setEnabled(True)

            if self.dashd_connection_ok:
                self.show_connection_successful()
                if self.is_dashd_syncing:
                    self.info_msg('Connection successful, but Dash daemon is synchronizing.')
                else:
                    self.info_msg('Connection successful.')
            else:
                if self.dashd_intf.last_error_message:
                    self.error_msg('Connection error: ' + self.dashd_intf.last_error_message)
                else:
                    self.error_msg('Connection error')

        if self.app_config.is_config_complete():
            self.action_check_network_connection.setEnabled(False)
            self.action_hw_wallet.setEnabled(False)
            self.connect_dash_network(call_on_check_finished=connection_test_finished)
        else:
            # configuration not complete: show config window
            self.error_msg("There are no (enabled) connections to an RPC node in your configuration.")

    def set_status_text1(self, text, style=None):
        def set_status(text, color):
            self.lblStatus1.setProperty('level', style)
            self.lblStatus1.setText(text)
            self.update_styles()

        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(set_status, text, style)
        else:
            set_status(text, style)

    def set_status_text2(self, text, style=None):
        def set_status(text, color):
            self.lblStatus2.setProperty('level', style)
            self.lblStatus2.setText(text)
            self.update_styles()

        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(set_status, text, style)
        else:
            set_status(text, style)

    def display_app_messages(self):
        left, top, right, bottom = self.layMessage.getContentsMargins()
        t = ''
        green_color = get_widget_font_color_green(self)
        default_color = get_widget_font_color_default(self)

        for m_id in self.app_messages:
            m = self.app_messages[m_id]
            if not m.hidden:
                if m.type == AppTextMessageType.INFO:
                    s = 'color:' + green_color
                elif m.type == AppTextMessageType.WARN:
                    s = 'background-color:rgb(255,128,0);color:white;'
                else:
                    s = 'background-color:red;color:white;'

                if t:
                    t += '<br>'
                t += f'<span style="{s}">{m.message}</span>&nbsp;' \
                     f'<span style="display:inline-box"><a style="text-decoration:none;color:{default_color};" ' \
                     f'href="{str(m_id)}">\u2715</img></a><span>'

        if not t:
            self.lblMessage.setVisible(False)
            self.layMessage.setContentsMargins(left, top, right, 0)
        else:
            self.lblMessage.setVisible(True)
            self.lblMessage.setText(t)
            self.layMessage.setContentsMargins(left, top, right, 4)

    @pyqtSlot(int, str, object)
    def add_app_message(self, msg_id: int, text: str, type: AppTextMessageType):
        """
        Display message in the app message area.
        """

        def set_message(msg_id: int, text, type):
            m = self.app_messages.get(msg_id)
            if not m:
                m = DispMessage(text, type)
                self.app_messages[msg_id] = m
            m.message = text
            m.type = type
            m.hidden = False
            self.display_app_messages()

        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(set_message, msg_id, text, type)
        else:
            set_message(msg_id, text, type)

    def del_app_message(self, msg_id: int):
        def hide(msg_id: int):
            if msg_id in self.app_messages:
                self.app_messages[msg_id].hidden = True
                self.display_app_messages()

        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(hide, msg_id)
        else:
            hide(msg_id)

    def on_lblMessage_linkActivated(self, link):
        try:
            if link.lower().find('http') >= 0:
                QDesktopServices.openUrl(QUrl(link))
            else:
                for m_id in self.app_messages:
                    if str(m_id) == link:
                        self.del_app_message(int(link))
                        break
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def connect_hardware_wallet(self) -> Optional[object]:
        try:
            return self.hw_session.connect_hardware_wallet()
        except HWNotConnectedException as e:
            self.error_msg(str(e))
        except CancelException:
            pass
        except Exception as e:
            self.error_msg(str(e), True)
        return self.hw_session.hw_client

    @pyqtSlot(bool)
    def disconnect_hardware_wallet(self) -> None:
        try:
            self.hw_session.disconnect_hardware_wallet()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_connect_hw_triggered(self):
        try:
            self.connect_hardware_wallet()
        except CancelException:
            return
        except Exception as e:
            self.error_msg(str(e), True)

        self.update_edit_controls_state()
        if self.hw_session.hw_client and self.hw_session.hw_device:
            msg = 'Successfully connected to ' + self.hw_session.hw_device.get_description()
            self.info_msg(msg)

    @pyqtSlot(HWDevice)
    def on_hardware_wallet_connected(self, hw_device: HWDevice):
        self.set_status_text2('<b>HW status:</b> connected to %s' % hw_device.get_description(), 'success')
        self.update_edit_controls_state()

    @pyqtSlot()
    def on_hardware_wallet_disconnected(self):
        self.set_status_text2('<b>HW status:</b> idle')
        self.update_edit_controls_state()

    @pyqtSlot(str)
    def on_hardware_wallet_connection_error(self, message):
        self.set_status_text2('<b>HW status:</b> connection error', 'error')
        self.update_edit_controls_state()
        self.error_msg(message)

    @pyqtSlot(bool)
    def on_action_disconnect_hw_triggered(self):
        try:
            self.disconnect_hardware_wallet()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(object)
    def on_cur_masternode_changed(self, cur_masternode: Optional[MasternodeConfig]):
        self.update_edit_controls_state()

    def on_masternode_data_changed(self):
        self.update_edit_controls_state()

    def update_edit_controls_state(self):
        def update_fun():
            cur_mn = self.main_view.get_cur_masternode()
            mn_is_selected = cur_mn is not None
            editing = (self.editing_enabled and mn_is_selected)
            self.action_gen_mn_priv_key_uncompressed.setEnabled(editing)
            self.action_gen_mn_priv_key_compressed.setEnabled(editing)
            self.action_save_config_file.setEnabled(self.app_config.is_modified())
            self.action_disconnect_hw.setEnabled(True if self.hw_session.hw_client else False)
            self.action_sign_message_with_collateral_addr.setEnabled(mn_is_selected)
            self.action_sign_message_with_owner_key.setEnabled(mn_is_selected)
            self.action_sign_message_with_voting_key.setEnabled(mn_is_selected)
            self.action_register_masternode.setEnabled(mn_is_selected and cur_mn.dmn_user_roles & DMN_ROLE_OWNER)
            self.action_show_masternode_details.setEnabled(mn_is_selected)
            self.action_clone_masternode_entry.setEnabled(mn_is_selected)
            self.action_delete_masternode_entry.setEnabled(mn_is_selected)
            self.action_update_masternode_payout_address.setEnabled(mn_is_selected and
                                                                    cur_mn.dmn_user_roles & DMN_ROLE_OWNER)
            self.action_update_masternode_operator_key.setEnabled(mn_is_selected and
                                                                  cur_mn.dmn_user_roles & DMN_ROLE_OWNER)
            self.action_update_masternode_voting_key.setEnabled(mn_is_selected and
                                                                cur_mn.dmn_user_roles & DMN_ROLE_OWNER)
            self.action_update_masternode_service.setEnabled(mn_is_selected and
                                                             cur_mn.dmn_user_roles & DMN_ROLE_OPERATOR)
            self.action_revoke_masternode.setEnabled(mn_is_selected and
                                                     cur_mn.dmn_user_roles & DMN_ROLE_OPERATOR)

        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(update_fun)
        else:
            update_fun()

    def on_mn_data_changed(self, masternode: MasternodeConfig):
        self.action_save_config_file.setEnabled(self.app_config.is_modified())

    @pyqtSlot(bool)
    def on_action_hw_wallet_triggered(self):
        """ Shows the hardware wallet window. """
        try:
            self.show_wallet_window(None)
        except Exception as e:
            self.error_msg(str(e), True)

    def show_wallet_window(self, initial_mn: Optional[int]):
        """ Shows the wallet/send payments dialog.
        :param initial_mn:
          if the value is from 0 to len(masternodes), show utxos for the masternode
            having the 'initial_mn' index in self.app_config.masternodes
          if the value is -1, show utxo for all masternodes
          if the value is None, show the default utxo source type
        """
        if not self.dashd_intf.open():
            self.error_msg('Dash daemon not connected')
        else:
            try:
                self.main_view.stop_threads()
                ui = wallet_dlg.WalletDlg(self, self.hw_session, initial_mn_sel=initial_mn)
                ui.exec_()
            except Exception as e:
                self.error_msg(str(e), True)
            finally:
                self.main_view.resume_threads()

    @pyqtSlot(bool)
    def on_action_sign_message_with_collateral_addr_triggered(self):
        mn = self.main_view.get_cur_masternode()
        if mn:
            try:
                self.connect_hardware_wallet()
                if self.hw_session.hw_client:
                    if not mn.collateral_bip32_path:
                        self.error_msg("No masternode collateral BIP32 path")
                    else:
                        ui = SignMessageDlg(self, self.hw_session, self.app_rt_data, mn.collateral_bip32_path,
                                            mn.collateral_address)
                        ui.exec_()
            except CancelException:
                return
            except Exception as e:
                self.error_msg(str(e), True)
        else:
            self.error_msg("To sign messages, you must select a masternode.")

    @pyqtSlot(bool)
    def on_action_sign_message_with_owner_key_triggered(self):
        mn = self.main_view.get_cur_masternode()
        if mn:
            try:
                pk = mn.owner_private_key
                if not pk:
                    self.error_msg("The masternode owner private key has not been configured.")
                else:
                    ui = SignMessageDlg(self, None, None, None,
                                        mn.get_owner_public_address(self.app_config.dash_network), pk)
                    ui.exec_()
            except Exception as e:
                self.error_msg(str(e), True)
        else:
            self.error_msg("To sign messages, you must select a masternode.")

    @pyqtSlot(bool)
    def on_action_sign_message_with_voting_key_triggered(self):
        mn = self.main_view.get_cur_masternode()
        if mn:
            try:
                if not mn.voting_private_key:
                    self.error_msg("The masternode voting private key has not been configured.")
                else:
                    ui = SignMessageDlg(self, None, None, None,
                                        mn.get_voting_public_address(self.app_config.dash_network),
                                        mn.voting_private_key)
                    ui.exec_()
            except Exception as e:
                self.error_msg(str(e), True)
        else:
            self.error_msg("To sign messages, you must select a masternode.")

    @pyqtSlot(bool)
    def on_action_wallet_tools_triggered(self):
        try:
            ui = WalletToolsDlg(self)
            ui.exec_()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_open_proposals_window_triggered(self):
        try:
            ui = ProposalsDlg(self, self.dashd_intf)
            ui.exec_()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_action_about_qt_triggered(self, enabled):
        QApplication.aboutQt()

    @pyqtSlot(bool)
    def on_action_register_masternode_triggered(self, enabled):
        reg_dlg = None
        cur_masternode = self.main_view.get_cur_masternode()
        config_modified_before = False

        def on_proregtx_finished(masternode: MasternodeConfig):
            nonlocal reg_dlg, self, cur_masternode
            try:
                cur_masternode.protx_hash = reg_dlg.dmn_reg_tx_hash

                cur_masternode.owner_key_type = reg_dlg.owner_key_type
                if cur_masternode.owner_key_type == InputKeyType.PRIVATE:
                    cur_masternode.owner_private_key = reg_dlg.owner_privkey
                else:
                    cur_masternode.owner_address = reg_dlg.owner_address
                    cur_masternode.owner_private_key = ''

                cur_masternode.operator_key_type = reg_dlg.operator_key_type
                if cur_masternode.operator_key_type == InputKeyType.PRIVATE:
                    cur_masternode.operator_private_key = reg_dlg.operator_privkey
                else:
                    cur_masternode.operator_public_key = reg_dlg.operator_pubkey
                    cur_masternode.operator_private_key = ''

                cur_masternode.voting_key_type = reg_dlg.voting_key_type
                if cur_masternode.voting_key_type == InputKeyType.PRIVATE:
                    cur_masternode.voting_private_key = reg_dlg.voting_privkey
                else:
                    cur_masternode.voting_address = reg_dlg.voting_address
                    cur_masternode.voting_private_key = ''

                cur_masternode.platform_node_key_type = reg_dlg.platform_node_key_type
                if cur_masternode.platform_node_key_type == InputKeyType.PRIVATE:
                    if reg_dlg.platform_node_private_key:
                        cur_masternode.platform_node_private_key = reg_dlg.platform_node_private_key
                else:
                    cur_masternode.platform_node_id = reg_dlg.platform_node_id

                cur_masternode.masternode_type = reg_dlg.masternode_type
                cur_masternode.platform_p2p_port = reg_dlg.platform_p2p_port
                cur_masternode.platform_http_port = reg_dlg.platform_http_port
                cur_masternode.collateral_tx = reg_dlg.collateral_tx
                cur_masternode.collateral_tx_index = reg_dlg.collateral_tx_index
                cur_masternode.collateral_address = reg_dlg.collateral_tx_address
                cur_masternode.collateral_bip32_path = reg_dlg.collateral_tx_address_path
                cur_masternode.ip = reg_dlg.ip
                cur_masternode.tcp_port = reg_dlg.tcp_port

                if not config_modified_before:
                    # If the configuration was modified before starting the registration window, don't save
                    # it to disk, otherwise do it.
                    self.save_configuration()
                self.main_view.set_cur_cfg_masternode_modified()
                self.dashd_intf.reset_masternode_data_cache()
                self.main_view.refresh_network_data()
            except Exception as e:
                logging.exception(str(e))

        if cur_masternode:
            try:
                config_modified_before = self.app_config.is_modified()
                reg_dlg = reg_masternode_dlg.RegMasternodeDlg(self, self.app_config, self.dashd_intf, cur_masternode,
                                                              on_proregtx_success_callback=on_proregtx_finished)
                reg_dlg.exec_()
            except Exception as e:
                self.error_msg(str(e), True)
        else:
            self.error_msg('No masternode selected')

    def update_registrar(self, show_upd_payout: bool, show_upd_operator: bool, show_upd_voting: bool):
        def on_updtx_finished(masternode: MasternodeConfig):
            try:
                if not self.app_config.is_modified():
                    self.save_configuration()
                self.main_view.set_cur_cfg_masternode_modified()
                self.dashd_intf.reset_masternode_data_cache()
                self.main_view.refresh_network_data()
            except Exception as e:
                logging.exception(str(e))

        if self.main_view.get_cur_masternode():
            upd_dlg = upd_mn_registrar_dlg.UpdMnRegistrarDlg(
                self, self.app_config, self.dashd_intf, self.main_view.get_cur_masternode(),
                on_upd_success_callback=on_updtx_finished, show_upd_payout=show_upd_payout,
                show_upd_operator=show_upd_operator, show_upd_voting=show_upd_voting)
            upd_dlg.exec_()
        else:
            self.error_msg('No masternode selected')

    def update_service(self):
        old_modified_state = self.app_config.is_modified()

        def on_mn_config_updated(masternode: MasternodeConfig):
            try:
                if not old_modified_state and self.app_config.is_modified():
                    self.save_configuration()
                self.main_view.set_cur_cfg_masternode_modified()
            except Exception as e:
                logging.exception(str(e))

        if self.main_view.get_cur_masternode():
            upd_dlg = upd_mn_service_dlg.UpdMnServiceDlg(
                self, self.app_config, self.dashd_intf, self.main_view.get_cur_masternode(),
                on_mn_config_updated_callback=on_mn_config_updated)
            upd_dlg.exec_()
            self.dashd_intf.reset_masternode_data_cache()
            if self.app_config.fetch_network_data_after_start:
                self.main_view.refresh_network_data()
        else:
            self.error_msg('No masternode selected')

    def revoke_mn_operator(self):
        if self.main_view.get_cur_masternode():
            revoke_dlg = revoke_mn_dlg.RevokeMnDlg(
                self, self.app_config, self.dashd_intf, self.main_view.get_cur_masternode())
            revoke_dlg.exec_()

            if not self.app_config.is_modified():
                self.save_configuration()
            self.main_view.set_cur_cfg_masternode_modified()
            self.dashd_intf.reset_masternode_data_cache()
            if self.app_config.fetch_network_data_after_start:
                self.main_view.refresh_network_data()
        else:
            self.error_msg('No masternode selected')

    @pyqtSlot()
    def on_action_show_masternode_details_triggered(self):
        try:
            self.main_view.goto_masternode_details()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot()
    def on_action_update_masternode_payout_address_triggered(self):
        try:
            self.update_registrar(show_upd_payout=True, show_upd_operator=False, show_upd_voting=False)
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot()
    def on_action_update_masternode_operator_key_triggered(self):
        try:
            self.update_registrar(show_upd_payout=False, show_upd_operator=True, show_upd_voting=False)
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot()
    def on_action_update_masternode_voting_key_triggered(self):
        try:
            self.update_registrar(show_upd_payout=False, show_upd_operator=False, show_upd_voting=True)
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot()
    def on_action_update_masternode_service_triggered(self):
        try:
            self.update_service()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot()
    def on_action_revoke_masternode_triggered(self):
        try:
            self.revoke_mn_operator()
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot()
    def on_action_new_masternode_entry_triggered(self):
        try:
            self.main_view.add_new_masternode(None)
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot()
    def on_action_clone_masternode_entry_triggered(self):
        try:
            self.main_view.add_new_masternode(self.main_view.get_cur_masternode())
        except Exception as e:
            self.error_msg(str(e), True)

    @pyqtSlot()
    def on_action_delete_masternode_entry_triggered(self):
        mn = self.main_view.get_cur_masternode()
        if mn:
            try:
                self.main_view.delete_masternode(mn)
            except Exception as e:
                self.error_msg(str(e), True)
