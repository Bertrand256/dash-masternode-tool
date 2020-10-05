#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
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
import bitcoin
import logging
import urllib.request
from PyQt5 import QtCore
from PyQt5 import QtWidgets
from PyQt5.QtCore import QSize, pyqtSlot, QEventLoop, QMutex, QWaitCondition, QUrl, Qt, QTimer
from PyQt5.QtGui import QFont, QIcon, QDesktopServices
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QFileDialog, QMenu, QMainWindow, QPushButton, QStyle, QInputDialog, QApplication, \
    QHBoxLayout, QAction, QToolButton, QWidgetAction
from PyQt5.QtWidgets import QMessageBox

import reg_masternode_dlg
import revoke_mn_dlg
import upd_mn_registrar_dlg
import upd_mn_service_dlg
from bip44_wallet import find_wallet_addresses, Bip44Wallet
from cmd_console_dlg import CmdConsoleDlg
from common import CancelException
from config_dlg import ConfigDlg
from find_coll_tx_dlg import ListCollateralTxsDlg
import about_dlg
import app_cache
import dash_utils
import hw_pass_dlg
import hw_pin_dlg
import wallet_dlg
import app_utils
from initialize_hw_dlg import HwInitializeDlg
from masternode_details import WdgMasternodeDetails
from proposals_dlg import ProposalsDlg
from app_config import AppConfig, MasternodeConfig, APP_NAME_SHORT, DMN_ROLE_OWNER, DMN_ROLE_OPERATOR, InputKeyType
from app_defs import PROJECT_URL, HWType, get_note_url
from dash_utils import bip32_path_n_to_string
from dashd_intf import DashdInterface, DashdIndexException
from hw_common import HardwareWalletPinException, HwSessionInfo
import hw_intf
from hw_setup_dlg import HwSetupDlg
from psw_cache import SshPassCache
from sign_message_dlg import SignMessageDlg
from wnd_utils import WndUtils
from ui import ui_main_dlg


class DispMessage(object):
    NEW_VERSION = 1
    DASH_NET_CONNECTION = 2

    def __init__(self, message: str, type: str):
        """
        :param type: 'warn'|'error'|'info'
        :param message: a message
        """
        self.message = message
        self.type = type
        self.hidden = False


class MainWindow(QMainWindow, WndUtils, ui_main_dlg.Ui_MainWindow):
    update_status_signal = QtCore.pyqtSignal(str, str)  # signal for updating status text from inside thread

    def __init__(self, app_dir):
        QMainWindow.__init__(self)
        WndUtils.__init__(self, None)
        ui_main_dlg.Ui_MainWindow.__init__(self)

        self.hw_client = None
        self.finishing = False
        self.app_messages: Dict[int, DispMessage] = {}
        self.app_config = AppConfig()
        self.app_config.init(app_dir)
        self.app_config.sig_display_message.connect(self.add_app_message)
        WndUtils.set_app_config(self, self.app_config)

        self.dashd_intf = DashdInterface(window=None,
                                         on_connection_initiated_callback=self.show_connection_initiated,
                                         on_connection_failed_callback=self.show_connection_failed,
                                         on_connection_successful_callback=self.show_connection_successful,
                                         on_connection_disconnected_callback=self.show_connection_disconnected)
        self.hw_session = HwSessionInfo(
            self.get_hw_client,
            self.connect_hardware_wallet,
            self.disconnect_hardware_wallet,
            self.app_config,
            dashd_intf=self.dashd_intf)

        self.dashd_info = {}
        self.is_dashd_syncing = False
        self.dashd_connection_ok = False
        self.connecting_to_dashd = False
        self.cur_masternode: MasternodeConfig = None
        self.editing_enabled = False
        self.recent_config_files = []

        # load most recently used config files from the data cache
        mru_cf = app_cache.get_value('MainWindow_ConfigFileMRUList', default_value=[], type=list)
        if isinstance(mru_cf, list):
            for file_name in mru_cf:
                if os.path.exists(file_name) and file_name not in self.recent_config_files:
                    self.recent_config_files.append(file_name)

        self.cmd_console_dlg = None
        self.setupUi()
        ssl._create_default_https_context = ssl._create_unverified_context

    def setupUi(self):
        ui_main_dlg.Ui_MainWindow.setupUi(self, self)
        SshPassCache.set_parent_window(self)
        app_cache.restore_window_size(self)
        self.inside_setup_ui = True
        self.dashd_intf.window = self
        self.closeEvent = self.closeEvent
        self.lblStatus1 = QtWidgets.QLabel(self)
        self.lblStatus1.setAutoFillBackground(False)
        self.lblStatus1.setOpenExternalLinks(True)
        self.lblStatus1.setOpenExternalLinks(True)
        self.statusBar.addPermanentWidget(self.lblStatus1, 1)
        self.lblStatus1.setText('')
        self.lblStatus2 = QtWidgets.QLabel(self)
        self.statusBar.addPermanentWidget(self.lblStatus2, 2)
        self.lblStatus2.setText('')
        self.lblStatus2.setOpenExternalLinks(True)
        self.show_connection_disconnected()
        self.set_status_text2('<b>HW status:</b> idle', 'black')

        # set stylesheet for editboxes, supporting different colors for read-only and edting mode
        style_sheet = "QLineEdit{background-color: white;} QLineEdit:read-only{background-color: lightgray;}" \
                      "QPushButton{background-color: white;border: 1px solid #bfbfbf;border-radius: 3px; padding:2px 12px 2px 12px;} QPushButton:pressed{background-color: gray;}"
        self.setStyleSheet(style_sheet)
        self.setIcon(self.action_save_config_file, 'save.png')
        self.setIcon(self.action_check_network_connection, "link-check.png")
        self.setIcon(self.action_open_settings_window, "gear.png")
        self.setIcon(self.action_open_proposals_window, "thumbs-up-down.png")
        self.setIcon(self.action_test_hw_connection, "hw-test.png")
        self.setIcon(self.action_disconnect_hw, "hw-disconnect.png")
        self.setIcon(self.action_transfer_funds_for_any_address, "wallet.png")
        self.setIcon(self.action_hw_configuration, "hw.png")
        self.setIcon(self.action_hw_initialization_recovery, "recover.png")
        self.setIcon(self.btnMoveMnUp, "arrow-downward@16px.png", rotate=180)
        self.setIcon(self.btnMoveMnDown, "arrow-downward@16px.png")

        self.mnuSignMessage = QMenu()
        self.mnuSignMessage.addAction(self.action_sign_message_with_collateral_addr)
        self.mnuSignMessage.addAction(self.action_sign_message_with_owner_key)
        self.mnuSignMessage.addAction(self.action_sign_message_with_voting_key)

        self.btnSignMessage = QToolButton()
        self.btnSignMessage.setMenu(self.mnuSignMessage)
        self.btnSignMessage.setPopupMode(QToolButton.InstantPopup)
        self.setIcon(self.btnSignMessage, "sign@32px.png")
        self.toolBar.addWidget(self.btnSignMessage)

        # icons will not be visible in menu
        self.action_save_config_file.setIconVisibleInMenu(False)
        self.action_check_network_connection.setIconVisibleInMenu(False)
        self.action_open_settings_window.setIconVisibleInMenu(False)
        self.action_open_proposals_window.setIconVisibleInMenu(False)
        self.action_test_hw_connection.setIconVisibleInMenu(False)
        self.action_disconnect_hw.setIconVisibleInMenu(False)
        self.action_run_trezor_emulator.setIconVisibleInMenu(False)
        self.action_run_trezor_emulator.setVisible(False)
        self.action_transfer_funds_for_any_address.setIconVisibleInMenu(False)
        self.action_hw_configuration.setIconVisibleInMenu(False)
        self.action_hw_initialization_recovery.setIconVisibleInMenu(False)

        # register dialog-type actions:
        self.addAction(self.action_gen_mn_priv_key_uncompressed)
        self.addAction(self.action_gen_mn_priv_key_compressed)

        self.app_config.feature_update_registrar_automatic.value_changed.connect(self.update_mn_controls_state)

        # add masternodes' info to the combobox
        self.cur_masternode = None

        self.wdg_masternode = WdgMasternodeDetails(self, self.app_config, self.dashd_intf)
        l = self.frmMasternodeDetails.layout()
        l.insertWidget(0, self.wdg_masternode)
        self.wdg_masternode.name_modified.connect(self.on_mn_name_modified)
        self.wdg_masternode.role_modified.connect(self.update_mn_controls_state)
        self.wdg_masternode.data_changed.connect(self.on_mn_data_changed)
        self.wdg_masternode.label_width_changed.connect(self.set_mn_labels_width)

        self.mns_user_refused_updating = {}

        # after loading whole configuration, reset 'modified' variable
        try:
            self.app_config.read_from_file(hw_session=self.hw_session, create_config_file=True)
        except Exception as e:
            raise
        self.display_window_title()
        self.dashd_intf.initialize(self.app_config)

        self.update_edit_controls_state()

        self.run_thread(self, self.get_project_config_params_thread, (False,))

        if self.app_config.app_config_file_name and os.path.exists(self.app_config.app_config_file_name):
            self.add_item_to_config_files_mru_list(self.app_config.app_config_file_name)
        self.update_config_files_mru_menu_items()

        self.inside_setup_ui = False
        self.configuration_to_ui()
        self.display_app_messages()
        logging.info('Finished setup of the main dialog.')

    def showEvent(self, QShowEvent):
        h = self.btnNewMn.height()
        self.btnMoveMnUp.setFixedHeight(h)

    def closeEvent(self, event):
        app_cache.save_window_size(self)
        self.finishing = True
        if self.dashd_intf:
            self.dashd_intf.disconnect()

        if self.app_config.is_modified():
            if self.queryDlg('Configuration modified. Save?',
                             buttons=QMessageBox.Yes | QMessageBox.No,
                             default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:
                self.save_configuration()
        self.app_config.close()

    def set_mn_labels_width(self, width):
        self.lblMasternodeStatus.setFixedWidth(width)

    def get_hw_client(self):
        return self.hw_client

    def configuration_to_ui(self):
        """
        Show the information read from configuration file on the user interface.
        :return:
        """

        # add masternodes data to the combobox
        self.cur_masternode = None
        self.cboMasternodes.clear()
        try:
            self.cboMasternodes.blockSignals(True)
            for mn in self.app_config.masternodes:
                self.cboMasternodes.addItem(mn.name, mn)
        finally:
            self.cboMasternodes.blockSignals(False)

        if self.app_config.masternodes:
            # get last masternode selected
            idx = app_cache.get_value('MainWindow_CurMasternodeIndex', 0, int)
            if idx >= len(self.app_config.masternodes):
                idx = 0
            self.cur_masternode = self.app_config.masternodes[idx]
            self.display_masternode_config(True)
        else:
            self.cur_masternode = None

        self.wdg_masternode.set_masternode(self.cur_masternode)
        self.action_open_log_file.setText('Open log file (%s)' % self.app_config.log_file)
        self.update_edit_controls_state()

    def load_configuration_from_file(self, file_name: str, ask_save_changes = True,
                                     update_current_file_name = True) -> None:
        """
        Load configuration from a file.
        :param file_name: A name of the configuration file to be loaded into the application.
        """
        if self.app_config.is_modified() and ask_save_changes:
            ret = self.queryDlg('Current configuration has been modified. Save?',
                                buttons=QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                                default_button=QMessageBox.Yes, icon=QMessageBox.Warning)
            if ret == QMessageBox.Yes:
                self.save_configuration()
            elif ret == QMessageBox.Cancel:
                self.update_config_files_mru_menu_items()
                return

        try:
            self.disconnect_hardware_wallet()
            dash_network_sav = self.app_config.dash_network
            self.app_config.read_from_file(hw_session=self.hw_session, file_name=file_name,
                                           update_current_file_name=update_current_file_name)
            self.editing_enabled = False
            self.configuration_to_ui()
            self.dashd_intf.reload_configuration()
            self.app_config.modified = False
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
        related to one of recently openend configuration files.
        :param file_name: A config file name accociated with the menu action clicked.
        """
        if file_name != self.app_config.app_config_file_name:
            self.load_configuration_from_file(file_name)

    def on_config_file_mru_clear_triggered(self):
        """Clear items in the recent config files menu."""
        self.recent_config_files.clear()
        app_cache.set_value('MainWindow_ConfigFileMRUList', self.recent_config_files)
        self.update_config_files_mru_menu_items()

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
            cfg_file_name_part = '  <UNNAMED>'

        if self.app_config.config_file_encrypted:
            encrypted_part = ' (Encrypted)'
        else:
            encrypted_part = ''

        title = f'{APP_NAME_SHORT}{app_version_part}{testnet_part}{cfg_file_name_part}{encrypted_part}'

        self.setWindowTitle(title)

    @pyqtSlot(bool)
    def on_action_load_config_file_triggered(self, checked):
        if self.app_config.app_config_file_name:
            dir = os.path.dirname(self.app_config.app_config_file_name)
        else:
            dir = self.app_config.data_dir
        file_name = self.open_config_file_query(dir, self, self.app_config)

        if file_name:
            if os.path.exists(file_name):
                self.load_configuration_from_file(file_name)
            else:
                WndUtils.errorMsg(f'File \'{file_name}\' does not exist.')

    def save_configuration(self, file_name: str = None):
        self.app_config.save_to_file(hw_session=self.hw_session, file_name=file_name)
        file_name = self.app_config.app_config_file_name
        if file_name:
            self.add_item_to_config_files_mru_list(file_name)
        self.update_config_files_mru_menu_items()
        self.display_window_title()
        self.editing_enabled = self.app_config.is_modified()
        self.wdg_masternode.set_edit_mode(self.editing_enabled )
        self.update_edit_controls_state()

    @pyqtSlot(bool)
    def on_action_save_config_file_triggered(self, checked):
        self.save_configuration()

    @pyqtSlot(bool)
    def on_action_save_config_file_as_triggered(self, checked):
        if self.app_config.app_config_file_name:
            dir = os.path.dirname(self.app_config.app_config_file_name)
        else:
            dir = self.app_config.data_dir
        file_name = self.save_config_file_query(dir, self, self.app_config)

        if file_name:
            self.save_configuration(file_name)

    @pyqtSlot(bool)
    def on_action_export_configuration_triggered(self, checked):
        if self.app_config.app_config_file_name:
            dir = os.path.dirname(self.app_config.app_config_file_name)
        else:
            dir = self.app_config.data_dir
        file_name = self.save_config_file_query(dir, self, self.app_config)

        if file_name:
            self.app_config.save_to_file(hw_session=self.hw_session, file_name=file_name, update_current_file_name=False)
            WndUtils.infoMsg('Configuration has been exported.')

    @pyqtSlot(bool)
    def on_action_import_configuration_triggered(self, checked):
        if self.app_config.app_config_file_name:
            dir = os.path.dirname(self.app_config.app_config_file_name)
        else:
            dir = self.app_config.data_dir
        file_name = self.open_config_file_query(dir, self, self.app_config)

        if file_name:
            if os.path.exists(file_name):
                self.load_configuration_from_file(file_name, ask_save_changes=False,
                                                  update_current_file_name=False)
                self.app_config.modified = True
                self.update_edit_controls_state()
                WndUtils.infoMsg('Configuration has been imported.')
            else:
                WndUtils.errorMsg(f'File \'{file_name}\' does not exist.')

    @pyqtSlot(bool)
    def on_action_open_log_file_triggered(self, checked):
        if os.path.exists(self.app_config.log_file):
            ret = QDesktopServices.openUrl(QUrl("file:///%s" % self.app_config.log_file))
            if not ret:
                self.warnMsg('Could not open "%s" file using a default OS application.' % self.app_config.log_file)

    @pyqtSlot(bool)
    def on_action_restore_config_from_backup_triggered(self, checked):
        input = QInputDialog(self)
        input.setComboBoxEditable(False)
        input.setOption(QInputDialog.UseListViewForComboBoxItems, True)
        input.setWindowTitle('Restore from backup')
        file_dates:List[Tuple[str, int, str]] = []

        for fname in os.listdir(self.app_config.cfg_backup_dir):
            try:
                fpath = os.path.join(self.app_config.cfg_backup_dir, fname)
                if os.path.isfile(fpath):
                    datetime.datetime.now().strftime('%Y-%m-%d %H_%M')
                    m = re.match('config_(\d{4}-\d{2}-\d{2}\s\d{2}_\d{2})', fname)
                    if m and len(m.groups()) == 1:
                        d = datetime.datetime.strptime(m.group(1), '%Y-%m-%d %H_%M')
                        file_dates.append((app_utils.to_string(d), d.timestamp(), fpath))
            except Exception as e:
                logging.error(str(e))

        file_dates.sort(key=lambda x: x[1], reverse=True)
        cbo_items = []
        if file_dates:
            for idx, (date_str, ts, file_name) in enumerate(file_dates):
                disp_text = str(idx+1) +'. ' + date_str
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
                    self.app_config.modified = True
                    self.update_edit_controls_state()
        else:
            self.errorMsg("Couldn't find any backup file.")

    @pyqtSlot(bool)
    def on_action_open_data_folder_triggered(self, checked):
        if os.path.exists(self.app_config.data_dir):
            ret = QDesktopServices.openUrl(QUrl("file:///%s" % self.app_config.data_dir))
            if not ret:
                self.warnMsg('Could not open "%s" folder using a default OS application.' % self.app_config.data_dir)

    @pyqtSlot(bool)
    def on_action_clear_wallet_cache_triggered(self, checked):
        if self.queryDlg('Do you really want to clear the wallet cache?',
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
            self.infoMsg('Wallet cache cleared.')

    @pyqtSlot(bool)
    def on_action_clear_proposals_cache_triggered(self, checked):
        if self.queryDlg('Do you really want to clear the proposals cache?',
                         buttons=QMessageBox.Yes | QMessageBox.Cancel,
                         default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Yes:
            db_cursor = self.app_config.db_intf.get_cursor()
            try:
                db_cursor.execute('drop table proposals')
                db_cursor.execute('drop table voting_results')
                self.app_config.db_intf.create_structures()
            finally:
                self.app_config.db_intf.release_cursor()
            self.infoMsg('Proposals cache cleared.')

    @pyqtSlot(bool)
    def on_action_check_for_updates_triggered(self, checked, force_check=True):
        self.run_thread(self, self.get_project_config_params_thread, (force_check,))

    @pyqtSlot(bool)
    def on_action_command_console_triggered(self, checked):
        if not self.cmd_console_dlg:
            self.cmd_console_dlg = CmdConsoleDlg(self, self.app_config)
        self.cmd_console_dlg.exec_()

    def get_project_config_params_thread(self, ctrl, force_check):
        """
        Thread function checking whether there is a new version of the application on Github page.
        :param ctrl: thread control structure (not used here) 
        :param cur_date_str: Current date string - it will be saved in the cache file as the date of the 
            last-version-check date.
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
                        if app_utils.is_version_bigger(remote_version_str, self.app_config.app_version):
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
                                msg = "New version (" + remote_version_str + ') available: <a href="' + exe_url + '">download</a>.'
                            else:
                                msg = "New version (" + remote_version_str + ') available. Go to the project website: <a href="' + \
                                      PROJECT_URL + '">open</a>.'

                            self.add_app_message(DispMessage.NEW_VERSION, msg, 'info')
                        else:
                            if force_check:
                                self.add_app_message(DispMessage.NEW_VERSION, "You have the latest version of %s."
                                                     % APP_NAME_SHORT, 'info')
                    elif force_check:
                        self.add_app_message(DispMessage.NEW_VERSION, "Could not read the remote version number.",
                                              'warn')

        except Exception:
            logging.exception('Exception occurred while loading/processing the project remote configuration')

    def display_masternode_config(self, set_mn_list_index):
        if self.cur_masternode:
            if set_mn_list_index:
                self.cboMasternodes.setCurrentIndex(self.app_config.masternodes.index(self.cur_masternode))
            else:
                self.wdg_masternode.set_masternode(self.cur_masternode)
            self.update_edit_controls_state()
        else:
            self.wdg_masternode.set_masternode(None)
        self.update_mn_controls_state()
        self.lblMnStatus.setText('')

    @pyqtSlot(bool)
    def on_action_open_settings_window_triggered(self):
        dash_network_sav = self.app_config.dash_network
        hw_type_sav = self.app_config.hw_type
        dlg = ConfigDlg(self, self.app_config)
        res = dlg.exec_()
        if res and dlg.get_is_modified():
            self.app_config.configure_cache()
            self.dashd_intf.reload_configuration()
            if dash_network_sav != self.app_config.dash_network or hw_type_sav != self.app_config.hw_type:
                self.disconnect_hardware_wallet()
                self.app_config.reset_network_dependent_dyn_params()
            self.display_window_title()
            self.update_edit_controls_state()
        del dlg

    @pyqtSlot(bool)
    def on_action_about_app_triggered(self):
        ui = about_dlg.AboutDlg(self, self.app_config.app_version)
        ui.exec_()

    def show_connection_initiated(self):
        """Shows status information related to a initiated process of connection to a dash RPC. """
        self.set_status_text1('<b>RPC network status:</b> trying %s...' % self.dashd_intf.get_active_conn_description(), 'black')

    def show_connection_failed(self):
        """Shows status information related to a failed connection attempt. There can be more attempts to connect
        to another nodes if there are such in configuration."""
        self.set_status_text1('<b>RPC network status:</b> failed connection to %s' % self.dashd_intf.get_active_conn_description(), 'red')

    def show_connection_successful(self):
        """Shows status information after successful connetion to a Dash RPC node."""
        self.set_status_text1('<b>RPC network status:</b> OK (%s)' % self.dashd_intf.get_active_conn_description(), 'green')

    def show_connection_disconnected(self):
        """Shows status message related to disconnection from Dash RPC node."""
        self.set_status_text1('<b>RPC network status:</b> not connected', 'black')

    def connect_dash_network(self, wait_for_check_finish=False, call_on_check_finished=None):
        """
        Connects do dash daemon if not connected before and returnes if it was successful.
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
                        (str(mnsync.get('AssetID', '')), str(mnsync.get('AssetName', ''))), 'warn')
                    cond.wait(mtx, 5000)
                self.del_app_message(DispMessage.DASH_NET_CONNECTION)
            except Exception as e:
                self.is_dashd_syncing = False
                self.dashd_connection_ok = False
                self.add_app_message(DispMessage.DASH_NET_CONNECTION, str(e), 'error')
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
                self.dashd_info = self.dashd_intf.getinfo(verify_node=True)
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
                self.add_app_message(DispMessage.DASH_NET_CONNECTION, err, 'error')

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
        self.test_dash_network_connection()

    def test_dash_network_connection(self):
        def connection_test_finished():

            self.action_check_network_connection.setEnabled(True)
            self.btnRegisterDmn.setEnabled(True)
            self.btnUpdMnPayoutAddr.setEnabled(True)
            self.btnRefreshMnStatus.setEnabled(True)
            self.action_transfer_funds_for_any_address.setEnabled(True)

            if self.dashd_connection_ok:
                self.show_connection_successful()
                if self.is_dashd_syncing:
                    self.infoMsg('Connection successful, but Dash daemon is synchronizing.')
                else:
                    self.infoMsg('Connection successful.')
            else:
                if self.dashd_intf.last_error_message:
                    self.errorMsg('Connection error: ' + self.dashd_intf.last_error_message)
                else:
                    self.errorMsg('Connection error')

        if self.app_config.is_config_complete():
            self.action_check_network_connection.setEnabled(False)
            self.btnRegisterDmn.setEnabled(False)
            self.btnUpdMnPayoutAddr.setEnabled(False)
            self.btnRefreshMnStatus.setEnabled(False)
            self.action_transfer_funds_for_any_address.setEnabled(False)
            self.connect_dash_network(call_on_check_finished=connection_test_finished)
        else:
            # configuration not complete: show config window
            self.errorMsg("There are no (enabled) connections to an RPC node in your configuration.")

    def set_status_text1(self, text, color):
        def set_status(text, color):
            self.lblStatus1.setText(text)
            if not color:
                color = 'black'
            self.lblStatus1.setStyleSheet('QLabel{color: ' + color + ';margin-right:20px;margin-left:8px}')

        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(set_status, text, color)
        else:
            set_status(text, color)

    def set_status_text2(self, text, color):
        def set_status(text, color):
            self.lblStatus2.setText(text)
            if not color:
                color = 'black'
            self.lblStatus2.setStyleSheet('QLabel{color: ' + color + '}')

        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(set_status, text, color)
        else:
            set_status(text, color)

    def display_app_messages(self):
        left, top, right, bottom = self.layMessage.getContentsMargins()
        img_path = os.path.join(self.app_config.app_dir if self.app_config.app_dir else '', 'img')
        h = int(self.lblMasternodeStatus.height() * 0.6)

        t = ''
        for m_id in self.app_messages:
            m = self.app_messages[m_id]
            if not m.hidden:
                if m.type == 'info':
                    s = 'color:green'
                elif m.type == 'warn':
                    s = 'background-color:rgb(255,128,0);color:white;'
                else:
                    s = 'background-color:red;color:white;'

                if t:
                    t += '<br>'
                # t += f'<span style="{s}">{m.message}</span><a href="{str(m_id)}"><img height={h} src="{img_path+"/highlight-off@16px"}"></img></a>'
                t += f'<span style="{s}">{m.message}</span>&nbsp;' \
                    f'<span style="display:inline-box"><a style="text-decoration:none;color:black;" href="{str(m_id)}">\u2715</img></a><span>'

        if not t:
            self.lblMessage.setVisible(False)
            self.layMessage.setContentsMargins(left, top, right, 0)
        else:
            self.lblMessage.setVisible(True)
            self.lblMessage.setText(t)
            self.layMessage.setContentsMargins(left, top, right, 4)

    def add_app_message(self, msg_id: int, text: str, type: str):
        """
        Display message in the app message area.
        :param text: Text to be displayed. If Text is empty, message area will be hidden. 
        :param color: Color of thext.
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
        if link.lower().find('http') >= 0:
            QDesktopServices.openUrl(QUrl(link))
        else:
            for m_id in self.app_messages:
                if str(m_id) == link:
                    self.del_app_message(int(link))
                    break

    def getHwName(self):
        if self.app_config.hw_type == HWType.trezor:
            return 'Trezor'
        elif self.app_config.hw_type == HWType.keepkey:
            return 'KeepKey'
        elif self.app_config.hw_type == HWType.ledger_nano_s:
            return 'Ledger Nano S'
        else:
            return 'Unknown HW Type'

    def connect_hardware_wallet(self) -> Optional[object]:
        """
        Connects to hardware wallet if not connected before.
        :return: Reference to hw client or None if not connected.
        """
        ret = None
        if self.hw_client:
            cur_hw_type = hw_intf.get_hw_type(self.hw_client)
            if self.app_config.hw_type != cur_hw_type:
                self.on_action_disconnect_hw_triggered()

        if not self.hw_client:
            try:
                try:
                    logging.info('Connecting to a hardware wallet device. self: ' + str(self))
                    self.hw_client = hw_intf.connect_hw(hw_session=self.hw_session,
                                                        device_id=None,
                                                        passphrase_encoding=self.app_config.hw_keepkey_psw_encoding,
                                                        hw_type=self.app_config.hw_type)

                    if self.app_config.dash_network == 'TESTNET':
                        # check if Dash testnet is supported by this hardware wallet
                        found_testnet_support = False
                        if self.app_config.hw_type in (HWType.trezor, HWType.keepkey):
                            try:
                                path = dash_utils.get_default_bip32_base_path(self.app_config.dash_network)
                                path += "/0'/0/0"
                                path_n = dash_utils.bip32_path_string_to_n(path)
                                addr = hw_intf.get_address(self.hw_session, path_n, False)
                                if addr and dash_utils.validate_address(addr, self.app_config.dash_network):
                                    found_testnet_support = True
                            except Exception as e:
                                if str(e).find('Invalid coin name') < 0:
                                    logging.exception('Failed when looking for Dash testnet support')
                        elif self.app_config.hw_type == HWType.ledger_nano_s:
                            addr = hw_intf.get_address(self.hw_session,
                                                       dash_utils.get_default_bip32_path(self.app_config.dash_network))
                            if dash_utils.validate_address(addr, self.app_config.dash_network):
                                found_testnet_support = False

                        if not found_testnet_support:
                            url = get_note_url('DMT0002')
                            msg = f'Your hardware wallet device does not support Dash TESTNET ' \
                                  f'(<a href="{url}">see details</a>).'
                            self.errorMsg(msg)
                            try:
                                self.disconnect_hardware_wallet()
                            except Exception:
                                pass
                            self.set_status_text2(msg, 'red')
                            return

                    logging.info('Connected to a hardware wallet')
                    self.set_status_text2('<b>HW status:</b> connected to %s' % hw_intf.get_hw_label(self.hw_client),
                                        'green')
                    self.update_edit_controls_state()
                    self.hw_session.signal_hw_connected()
                except CancelException:
                    raise
                except Exception as e:
                    logging.exception('Exception while connecting hardware wallet')
                    try:
                        self.disconnect_hardware_wallet()
                    except Exception:
                        pass
                    logging.info('Could not connect to a hardware wallet')
                    self.set_status_text2('<b>HW status:</b> cannot connect to %s device' % self.getHwName(), 'red')
                    self.errorMsg(str(e))

                ret = self.hw_client
            except CancelException:
                raise
            except HardwareWalletPinException as e:
                self.errorMsg(e.msg)
                if self.hw_client:
                    self.hw_client.clear_session()
                self.update_edit_controls_state()
            except OSError as e:
                logging.exception('Exception occurred')
                self.errorMsg('Cannot open %s device.' % self.getHwName())
                self.update_edit_controls_state()
            except Exception as e:
                logging.exception('Exception occurred')
                self.errorMsg(str(e))
                if self.hw_client:
                    self.hw_client.init_device()
                self.update_edit_controls_state()
        else:
            ret = self.hw_client
        return ret

    def btnConnectTrezorClick(self):
        self.connect_hardware_wallet()

    @pyqtSlot(bool)
    def on_action_test_hw_connection_triggered(self):
        try:
            self.connect_hardware_wallet()
        except CancelException:
            return

        self.update_edit_controls_state()
        if self.hw_client:
            try:
                if self.app_config.hw_type in (HWType.trezor, HWType.keepkey):
                    self.infoMsg('Connection to %s device (%s) successful.' %
                                 (self.getHwName(), hw_intf.get_hw_label(self.hw_client)))
                elif self.app_config.hw_type == HWType.ledger_nano_s:
                    self.infoMsg('Connection to %s device successful.' %
                                 (self.getHwName(),))
            except CancelException:
                if self.hw_client:
                    self.hw_client.init_device()

    def disconnect_hardware_wallet(self) -> None:
        if self.hw_client:
            hw_intf.disconnect_hw(self.hw_client)
            del self.hw_client
            self.hw_client = None
            self.set_status_text2('<b>HW status:</b> idle', 'black')
            self.update_edit_controls_state()
            self.hw_session.signal_hw_disconnected()

    @pyqtSlot(bool)
    def on_action_disconnect_hw_triggered(self):
        self.disconnect_hardware_wallet()

    @pyqtSlot(bool)
    def on_btnNewMn_clicked(self):
        self.add_new_masternode_cfg(copy_values_from_current=False)

    @pyqtSlot(bool)
    def on_btnDeleteMn_clicked(self):
        if self.cur_masternode:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setText('Do you really want to delete current masternode configuration?')
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            retval = msg.exec_()
            if retval == QMessageBox.No:
                return
            self.app_config.masternodes.remove(self.cur_masternode)
            self.cboMasternodes.removeItem(self.cboMasternodes.currentIndex())
            self.app_config.modified = True
            self.update_edit_controls_state()

    @pyqtSlot(bool)
    def on_btnDuplicateMn_clicked(self):
        self.add_new_masternode_cfg(copy_values_from_current=True)

    @pyqtSlot(bool)
    def on_btnEditMn_clicked(self):
        self.editing_enabled = True
        self.wdg_masternode.set_edit_mode(self.editing_enabled )
        self.update_edit_controls_state()
        self.update_mn_controls_state()

    @pyqtSlot(bool)
    def on_btnCancelEditingMn_clicked(self, checked):
        if self.app_config.is_modified():
            if WndUtils.queryDlg('Configuration modified. Discard changes?',
                                 buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                 default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Yes:
                # reload the configuration (we don't keep the old values)
                sel_mn_idx = self.app_config.masternodes.index(self.cur_masternode)
                # reload the configuration from file
                self.load_configuration_from_file(self.app_config.app_config_file_name, ask_save_changes=False)
                self.editing_enabled = False
                if sel_mn_idx >= 0 and sel_mn_idx < len(self.app_config.masternodes):
                    self.cur_masternode = self.app_config.masternodes[sel_mn_idx]
                    self.display_masternode_config(sel_mn_idx)
                self.wdg_masternode.set_edit_mode(self.editing_enabled)
                self.update_edit_controls_state()
        else:
            if self.cur_masternode and self.cur_masternode.new:
                idx = self.app_config.masternodes.index(self.cur_masternode)
                if idx >= 0:
                    self.app_config.masternodes.remove(self.cur_masternode)
                    self.cboMasternodes.removeItem(self.cboMasternodes.currentIndex())
            self.editing_enabled = False
            self.wdg_masternode.set_edit_mode(self.editing_enabled)
            self.update_edit_controls_state()
        self.update_mn_controls_state()

    @pyqtSlot(bool)
    def on_action_import_masternode_conf_triggered(self, checked):
        """
        Imports masternodes configuration from masternode.conf file.
        """

        file_name = self.open_file_query(self, self.app_config,
                                         message='Enter the path to the masternode.conf configuration file',
                                         directory='', filter="All Files (*);;Conf files (*.conf)",
                                         initial_filter="Conf files (*.conf)")

        if file_name:
            if os.path.exists(file_name):
                if not self.editing_enabled:
                    self.on_btnEditMn_clicked()

                bip44_wallet = None
                try:
                    with open(file_name, 'r') as f_ptr:
                        bip44_wallet = Bip44Wallet(self.app_config.hw_coin_name, self.hw_session,
                                                   self.app_config.db_intf, self.dashd_intf,
                                                   self.app_config.dash_network)

                        modified = False
                        imported_cnt = 0
                        skipped_cnt = 0
                        mns_imported = []
                        for line in f_ptr.readlines():
                            line = line.strip()
                            if not line:
                                continue
                            elems = line.split()
                            if len(elems) >= 5 and not line.startswith('#'):
                                mn_name = elems[0]
                                mn_ipport = elems[1]
                                mn_privkey = elems[2]
                                mn_tx_hash = elems[3]
                                mn_tx_idx = elems[4]
                                mn_dash_addr = ''
                                if len(elems) > 5:
                                    mn_dash_addr = elems[5]

                                def update_mn(in_mn):
                                    in_mn.name = mn_name
                                    ipelems = mn_ipport.split(':')
                                    if len(ipelems) >= 2:
                                        in_mn.ip = ipelems[0]
                                        in_mn.port = ipelems[1]
                                    else:
                                        in_mn.ip = mn_ipport
                                        in_mn.port = '9999'
                                    in_mn.collateralAddress = mn_dash_addr
                                    in_mn.collateralTx = mn_tx_hash
                                    in_mn.collateralTxIndex = mn_tx_idx
                                    in_mn.collateralBip32Path = ''

                                mn = self.app_config.get_mn_by_name(mn_name)
                                if mn:
                                    msg = QMessageBox()
                                    msg.setIcon(QMessageBox.Information)
                                    msg.setText('Masternode ' + mn_name + ' exists. Overwrite?')
                                    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                                    msg.setDefaultButton(QMessageBox.Yes)
                                    retval = msg.exec_()
                                    del msg
                                    if retval == QMessageBox.No:
                                        skipped_cnt += 1
                                        continue
                                    else:
                                        # overwrite data
                                        imported_cnt += 1
                                        update_mn(mn)
                                        mn.modified = True
                                        modified = True
                                        mns_imported.append(mn)
                                        if self.cur_masternode == mn:
                                            # current mn has been updated - update UI controls to new data
                                            self.display_masternode_config(False)
                                else:
                                    imported_cnt += 1
                                    mn = MasternodeConfig()
                                    update_mn(mn)
                                    modified = True
                                    self.app_config.add_mn(mn)
                                    self.cboMasternodes.addItem(mn.name, mn)
                                    mns_imported.append(mn)
                            else:
                                # incorrenct number of elements
                                skipped_cnt += 1
                        if modified:
                            self.update_edit_controls_state()
                        if imported_cnt:
                            msg_text = 'Successfully imported %s masternode(s)' % str(imported_cnt)
                            if skipped_cnt:
                                msg_text += ', skipped: %s' % str(skipped_cnt)
                            msg_text += ".\n\nIf you want to scan your " + self.getHwName() + \
                                        " for BIP32 path(s) corresponding to collateral addresses, connect your " + \
                                        self.getHwName() + " and click Yes." + \
                                        "\n\nIf you want to enter BIP32 path(s) manually, click No."

                            if self.queryDlg(message=msg_text, buttons=QMessageBox.Yes | QMessageBox.No,
                                             default_button=QMessageBox.Yes) == QMessageBox.Yes:
                                # scan all Dash addresses from imported masternodes for BIP32 path, starting from
                                # first standard Dash BIP32 path
                                if not self.connect_hardware_wallet():
                                    return

                                addresses_to_scan = []
                                for mn in mns_imported:
                                    if not mn.collateralBip32Path and mn.collateralAddress:
                                        addresses_to_scan.append(mn.collateralAddress)

                                found_paths = {}
                                try:
                                    bip44_addrs = find_wallet_addresses(addresses_to_scan, bip44_wallet)
                                    for a in bip44_addrs:
                                        if a and a.bip32_path:
                                            found_paths[a.address] = a.bip32_path
                                except CancelException:
                                    pass

                                paths_missing = 0
                                for mn in mns_imported:
                                    if not mn.collateralBip32Path and mn.collateralAddress:
                                        path = found_paths.get(mn.collateralAddress)
                                        mn.collateralBip32Path = path
                                        mn.set_modified()
                                        if path:
                                            if self.cur_masternode == mn:
                                                # current mn has been updated - update UI controls
                                                # to new data
                                                self.display_masternode_config(False)
                                                self.wdg_masternode.set_modified()
                                        else:
                                            paths_missing += 1

                                if paths_missing:
                                    self.warnMsg('Not all BIP32 paths were found. You have to manually enter '
                                                 'missing paths.')

                        elif skipped_cnt:
                            self.infoMsg('Operation finished with no imported and %s skipped masternodes.'
                                         % str(skipped_cnt))

                        if modified:
                            self.update_edit_controls_state()

                except Exception as e:
                    self.errorMsg('Reading file failed: ' + str(e))

                finally:
                    if bip44_wallet:
                        del bip44_wallet
            else:
                if file_name:
                    self.errorMsg("File '" + file_name + "' does not exist")

    def update_edit_controls_state(self):
        def update_fun():
            editing = (self.editing_enabled and self.cur_masternode is not None)
            self.action_gen_mn_priv_key_uncompressed.setEnabled(editing)
            self.action_gen_mn_priv_key_compressed.setEnabled(editing)
            self.btnDeleteMn.setEnabled(self.cur_masternode is not None)
            self.btnEditMn.setEnabled(not self.editing_enabled and self.cur_masternode is not None)
            self.btnCancelEditingMn.setEnabled(self.editing_enabled and self.cur_masternode is not None)
            self.btnDuplicateMn.setEnabled(self.cur_masternode is not None)
            self.action_save_config_file.setEnabled(self.app_config.is_modified())
            self.action_disconnect_hw.setEnabled(True if self.hw_client else False)
            self.btnRefreshMnStatus.setEnabled(self.cur_masternode is not None)
            self.btnRegisterDmn.setEnabled(self.cur_masternode is not None)
            self.action_sign_message_with_collateral_addr.setEnabled(self.cur_masternode is not None)
            self.action_sign_message_with_owner_key.setEnabled(self.cur_masternode is not None)
            self.action_sign_message_with_voting_key.setEnabled(self.cur_masternode is not None)
            self.update_mn_controls_state()
        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(update_fun)
        else:
            update_fun()

    def update_mn_controls_state(self):
        if self.cur_masternode:
            enabled = self.cur_masternode.dmn_user_roles & DMN_ROLE_OWNER > 0
        else:
            enabled = False
        self.btnRegisterDmn.setEnabled(enabled)

        if self.cur_masternode:
            enabled = self.cur_masternode.dmn_user_roles & DMN_ROLE_OWNER > 0
        else:
            enabled = False
        self.btnUpdMnPayoutAddr.setEnabled(enabled)
        self.btnUpdMnOperatorKey.setEnabled(enabled)
        self.btnUpdMnVotingKey.setEnabled(enabled)

        if self.cur_masternode:
            enabled = self.cur_masternode.dmn_user_roles & DMN_ROLE_OPERATOR > 0
        else:
            enabled = False
        self.btnUpdMnService.setEnabled(enabled)
        self.btnRevokeMn.setEnabled(enabled)

        if self.cur_masternode:
            idx = self.app_config.masternodes.index(self.cur_masternode)
            self.btnMoveMnUp.setEnabled(idx > 0)
            self.btnMoveMnDown.setEnabled(idx < len(self.app_config.masternodes) - 1)
        else:
            self.btnMoveMnUp.setEnabled(False)
            self.btnMoveMnDown.setEnabled(False)

    def add_new_masternode_cfg(self, copy_values_from_current: bool = False):
        new_mn = MasternodeConfig()
        new_mn.new = True
        cur_masternode_sav = self.cur_masternode
        self.cur_masternode = new_mn

        if copy_values_from_current and cur_masternode_sav:
            mn_template = cur_masternode_sav.name
        else:
            if self.app_config.is_testnet():
                new_mn.port = '19999'
            mn_template = 'MN'
        name_found = None
        for nr in range(1, 100):
            exists = False
            for mn in self.app_config.masternodes:
                if mn.name == mn_template + str(nr):
                    exists = True
                    break
            if not exists:
                name_found = mn_template + str(nr)
                break
        if name_found:
            new_mn.name = name_found

        if copy_values_from_current and cur_masternode_sav:
            new_mn.copy_from(cur_masternode_sav)

        self.app_config.masternodes.append(new_mn)
        self.editing_enabled = True
        old_index = self.cboMasternodes.currentIndex()
        self.cboMasternodes.addItem(new_mn.name, new_mn)
        if old_index != -1:
            # if masternodes combo was not empty before adding new mn, we have to manually set combobox
            # position to a new masternode position
            self.cboMasternodes.setCurrentIndex(self.app_config.masternodes.index(self.cur_masternode))
        self.wdg_masternode.set_masternode(self.cur_masternode)
        self.wdg_masternode.set_edit_mode(self.editing_enabled )

    @pyqtSlot(int)
    def on_cboMasternodes_currentIndexChanged(self):
        if self.cboMasternodes.currentIndex() >= 0:
            self.cur_masternode = self.app_config.masternodes[self.cboMasternodes.currentIndex()]
        else:
            self.cur_masternode = None
        self.display_masternode_config(False)

    def on_mn_name_modified(self, new_name):
        if self.cur_masternode:
            self.cboMasternodes.setItemText(self.cboMasternodes.currentIndex(), self.cur_masternode.name)

    def on_mn_data_changed(self, masternode: MasternodeConfig):
        if self.cur_masternode == masternode:
            self.cur_masternode.set_modified()
            self.action_save_config_file.setEnabled(self.app_config.is_modified())

    @pyqtSlot(bool)
    def on_btnMoveMnUp_clicked(self, enabled):
        if self.cur_masternode:
            idx = self.app_config.masternodes.index(self.cur_masternode)
            if idx > 0:
                old = self.cboMasternodes.blockSignals(True)
                try:
                    self.cboMasternodes.insertItem(idx-1, self.cur_masternode.name, self.cur_masternode)
                    self.cboMasternodes.removeItem(idx+1)
                    self.cboMasternodes.setCurrentIndex(idx-1)

                    self.app_config.masternodes[idx - 1], self.app_config.masternodes[idx] = self.app_config.masternodes[idx], \
                                                                                             self.app_config.masternodes[idx - 1]
                    self.app_config.modified = True
                finally:
                    self.cboMasternodes.blockSignals(old)
                    self.update_mn_controls_state()
                    self.update_edit_controls_state()

    @pyqtSlot(bool)
    def on_btnMoveMnDown_clicked(self, enabled):
        if self.cur_masternode:
            idx = self.app_config.masternodes.index(self.cur_masternode)
            if idx < len(self.app_config.masternodes) - 1:
                old = self.cboMasternodes.blockSignals(True)
                try:
                    self.cboMasternodes.removeItem(idx)
                    self.cboMasternodes.insertItem(idx+1, self.cur_masternode.name, self.cur_masternode)
                    self.cboMasternodes.setCurrentIndex(idx+1)

                    self.app_config.masternodes[idx + 1], self.app_config.masternodes[idx] = self.app_config.masternodes[idx], \
                                                                                             self.app_config.masternodes[idx + 1]
                    self.app_config.modified = True
                finally:
                    self.cboMasternodes.blockSignals(old)
                    self.update_mn_controls_state()
                    self.update_edit_controls_state()

    def get_deterministic_tx(self, masternode: MasternodeConfig) -> Optional[Dict]:
        protx = None
        protx_state = None

        if masternode.dmn_tx_hash:
            try:
                protx = self.dashd_intf.protx('info', masternode.dmn_tx_hash)
                if protx:
                    protx_state = protx.get('state')
            except Exception as e:
                logging.exception('Cannot read protx info')

            if not protx:
                try:
                    # protx transaction is not confirmed yet, so look for it in the mempool
                    tx = self.dashd_intf.getrawtransaction(masternode.dmn_tx_hash, 1, skip_cache=True)
                    confirmations = tx.get('confirmations', 0)
                    if confirmations < 3:
                        # in this case dmn tx should have been found by the 'protx info' call above;
                        # it hasn't been, so it is no longer valid a protx transaction
                        ptx = tx.get('proRegTx')
                        if ptx:
                            protx = {
                                'proTxHash': masternode.dmn_tx_hash,
                                'collateralHash': ptx.get('collateralHash'),
                                'collateralIndex': ptx.get('collateralIndex'),
                                'state': {
                                    'service': ptx.get('service'),
                                    'ownerAddress': ptx.get('ownerAddress'),
                                    'votingAddress': ptx.get('votingAddress'),
                                    'pubKeyOperator': ptx.get('pubKeyOperator'),
                                    'payoutAddress': ptx.get('payoutAddress')
                                }
                            }
                        if protx:
                            protx_state = protx.get('state')
                except Exception as e:
                    pass

        if not (protx_state and ((protx_state.get('service') == masternode.ip + ':' + masternode.port) or
                (protx.get('collateralHash') == masternode.collateralTx and
                str(protx.get('collateralIndex')) == str(masternode.collateralTxIndex)))):
            try:
                txes = self.dashd_intf.protx('list', 'registered', True)
                for protx in txes:
                    protx_state = protx.get('state')
                    if (protx_state and ((protx_state.get('service') == masternode.ip + ':' + masternode.port) or
                            (protx.get('collateralHash') == masternode.collateralTx and
                             str(protx.get('collateralIndex')) == str(masternode.collateralTxIndex)))):
                        return protx
            except Exception as e:
                pass
        else:
            return protx
        return None

    def get_masternode_status_description_thread(self, ctrl, masternode: MasternodeConfig):
        """
        Get current masternode's extended status.
        """
        if self.dashd_connection_ok:
            if masternode.collateralTx and str(masternode.collateralTxIndex):
                collateral_id = masternode.collateralTx + '-' + masternode.collateralTxIndex
            else:
                collateral_id = None
            if masternode.ip and masternode.port:
                ip_port = masternode.ip + ':' + str(masternode.port)
            else:
                ip_port = None

            if not collateral_id and not ip_port:
                if not masternode.collateralTx:
                    return '<span style="color:red">Enter the collateral TX hash + index or IP + port</span>'

            self.dashd_intf.get_masternodelist('json', data_max_age=30)  # read new data from the network
                                                                         # every 30 seconds
            if collateral_id:
                mn_info = self.dashd_intf.masternodes_by_ident.get(collateral_id)
            else:
                mn_info = self.dashd_intf.masternodes_by_ip_port.get(ip_port)

            block_height = self.dashd_intf.getblockcount()
            dmn_tx = self.get_deterministic_tx(masternode)
            if dmn_tx:
                dmn_tx_state = dmn_tx.get('state')
            else:
                dmn_tx_state = {}
                dmn_tx = {}

            next_payment_block = None
            next_payout_ts = None

            if mn_info:
                mn_ident = mn_info.ident
                mn_ip_port = mn_info.ip
                if mn_info.queue_position is not None:
                    next_payment_block = block_height + mn_info.queue_position + 1
                    next_payout_ts = int(time.time()) + (mn_info.queue_position * 2.5 * 60)
            else:
                if dmn_tx_state:
                    mn_ident = str(dmn_tx.get('collateralHash')) + '-' + str(dmn_tx.get('collateralIndex'))
                    mn_ip_port = dmn_tx_state.get('service')
                else:
                    mn_ident = None
                    mn_ip_port = None

            status_color = 'black'
            if mn_info or dmn_tx:
                mn_status = ''
                no_operator_pub_key = False

                if mn_info:
                    if mn_info.status == 'ENABLED' or mn_info.status == 'PRE_ENABLED':
                        status_color = 'green'
                    else:
                        status_color = 'red'
                    mn_status = mn_info.status

                if dmn_tx:
                    pose = dmn_tx_state.get('PoSePenalty', 0)
                    if pose:
                        mn_status += (', ' if mn_status else '') + 'PoSePenalty: ' + str(pose)
                        status_color = 'red'

                    oper_pub_key = dmn_tx_state.get('pubKeyOperator', '')
                    if re.match('^0+$', oper_pub_key):
                        no_operator_pub_key = True

                    service = dmn_tx_state.get('service', '')
                    if service == '[0:0:0:0:0:0:0:0]:0':
                        if no_operator_pub_key:
                            mn_status += (', ' if mn_status else '') + 'operator key update required'
                        else:
                            mn_status += (', ' if mn_status else '') + 'service update required'
                        status_color = 'red'

                update_mn_info = False
                collateral_address_mismatch = False
                collateral_tx_mismatch = False
                ip_port_mismatch = False
                mn_data_modified = False
                owner_public_address_mismatch = False
                operator_pubkey_mismatch = False
                voting_public_address_mismatch = False

                if masternode not in self.mns_user_refused_updating:
                    missing_data = []
                    if not masternode.collateralTx or not masternode.collateralTxIndex:
                        missing_data.append('collateral tx/index')
                    if not masternode.collateralAddress and masternode.dmn_user_roles & DMN_ROLE_OWNER:
                        missing_data.append('collateral address')
                    if dmn_tx and masternode.dmn_tx_hash != dmn_tx.get('proTxHash'):
                        missing_data.append('protx hash')

                    if missing_data:
                        msg = 'In the configuration of your masternode the following information is ' \
                            f'missing/incorrect: {", ".join(missing_data)}.<br><br>' \
                            f'Do you want to update your configuration from the information that exsits on ' \
                            f'the network?'

                        if self.queryDlg(msg, buttons=QMessageBox.Yes | QMessageBox.No,
                                         default_button=QMessageBox.Yes,
                                         icon=QMessageBox.Warning) == QMessageBox.Yes:
                            update_mn_info = True
                        else:
                            self.mns_user_refused_updating[masternode] = self.cur_masternode

                if masternode.collateralTx + '-' + str(masternode.collateralTxIndex) != mn_ident:
                    elems = mn_ident.split('-')
                    if len(elems) == 2:
                        if update_mn_info:
                            masternode.collateralTx = elems[0]
                            masternode.collateralTxIndex = elems[1]
                            mn_data_modified = True
                        else:
                            collateral_tx_mismatch = True

                if not collateral_tx_mismatch:
                    if masternode.dmn_user_roles & DMN_ROLE_OWNER:

                        # check outputs of the collateral transaction
                        tx_json = self.dashd_intf.getrawtransaction(masternode.collateralTx, 1)
                        if tx_json:
                            vout = tx_json.get('vout')
                            if vout and int(masternode.collateralTxIndex) < len(vout):
                                v = vout[ int(masternode.collateralTxIndex)]
                                if v and v.get('scriptPubKey'):
                                    addrs = v.get('scriptPubKey').get('addresses')
                                    if addrs:
                                        collateral_address = addrs[0]
                                        if masternode.collateralAddress != collateral_address:
                                            if update_mn_info:
                                                masternode.collateralAddress = collateral_address
                                                mn_data_modified = True
                                            else:
                                                collateral_address_mismatch = True

                if masternode.ip + ':' + masternode.port != mn_ip_port:
                    elems = mn_ip_port.split(':')
                    if len(elems) == 2:
                        if update_mn_info:
                            masternode.ip = elems[0]
                            masternode.port = elems[1]
                            mn_data_modified = True
                        else:
                            ip_port_mismatch = True

                if dmn_tx:
                    dmn_hash = dmn_tx.get('proTxHash')
                    if dmn_hash and masternode.dmn_tx_hash != dmn_hash:
                        if update_mn_info:
                            masternode.dmn_tx_hash = dmn_tx.get('proTxHash')
                            mn_data_modified = True

                    if dmn_tx_state:
                        owner_address_network = dmn_tx_state.get('ownerAddress')
                        owner_address_cfg = masternode.get_dmn_owner_public_address(self.app_config.dash_network)
                        if owner_address_network and owner_address_cfg and owner_address_network != owner_address_cfg:
                            owner_public_address_mismatch = True
                            logging.warning(
                                f'The owner public address mismatch for masternode: {masternode.name}, '
                                f'address from the app configuration: {owner_address_cfg}, address from the Dash '
                                f'network: {owner_address_network}')

                        voting_address_network = dmn_tx_state.get('votingAddress')
                        voting_address_cfg = masternode.get_dmn_voting_public_address(self.app_config.dash_network)
                        if voting_address_network and voting_address_cfg and voting_address_network != voting_address_cfg:
                            voting_public_address_mismatch = True
                            logging.warning(
                                f'The voting public address mismatch for masternode: {masternode.name}. '
                                f'address from the app configuration: {voting_address_cfg}, address from the Dash '
                                f'network: {voting_address_network}')

                        if not no_operator_pub_key:
                            operator_pubkey_network = dmn_tx_state.get('pubKeyOperator')
                            operator_pubkey_cfg = masternode.get_dmn_operator_pubkey()
                            if operator_pubkey_network and operator_pubkey_cfg and \
                                    operator_pubkey_network != operator_pubkey_cfg:
                                operator_pubkey_mismatch = True
                                logging.warning(
                                    f'The operator public key mismatch for masternode: {masternode.name}. '
                                    f'pubkey from the app configuration: {operator_pubkey_cfg}, pubkey from the Dash '
                                    f'network: {operator_pubkey_network}')

                if mn_data_modified:
                    def update():
                        self.wdg_masternode.masternode_data_to_ui()
                        self.wdg_masternode.set_modified()
                    if not self.finishing:
                        self.call_in_main_thread(update)

                if masternode == self.cur_masternode:
                    # get balance
                    collateral_address = masternode.collateralAddress.strip()
                    payout_address = dmn_tx_state.get('payoutAddress','')
                    payment_url = self.app_config.get_block_explorer_addr().replace('%ADDRESS%', payout_address)
                    payout_link = '<a href="%s">%s</a>' % (payment_url, payout_address)
                    payout_entry = f'<tr><td class="title">Payout address:</td><td class="value" colspan="2">' \
                        f'{payout_link}</td></tr>'
                    balance_entry = ''
                    last_paid_entry = ''
                    next_payment_entry = ''
                    operator_payout_entry = ''

                    try:
                        if collateral_address:
                            collateral_bal = self.dashd_intf.getaddressbalance([collateral_address])
                            collateral_bal = round(collateral_bal.get('balance') / 1e8, 5)

                            if collateral_address == payout_address:
                                balance_entry = f'<tr><td class="title">Balance:</td><td class="value">' \
                                            f'{app_utils.to_string(collateral_bal)}</td><td></td></tr>'
                            else:
                                balance_entry = f'<tr><td class="title">Collateral addr. balance:</td><td class="value">' \
                                            f'{app_utils.to_string(collateral_bal)}</td><td></td></tr>'

                        if collateral_address != payout_address and payout_address:
                            payout_bal = self.dashd_intf.getaddressbalance([payout_address])
                            payout_bal = round(payout_bal.get('balance') / 1e8, 5)
                            balance_entry += f'<tr><td class="title">Payout addr. balance:</td><td class="value" ' \
                                f'colspan="2">{app_utils.to_string(payout_bal)}</td></tr>'

                        operator_reward = float(dmn_tx.get('operatorReward', 0))
                        if operator_reward:
                            operator_payout_addr = dmn_tx_state.get('operatorPayoutAddress', '')
                            if operator_payout_addr:
                                addr_info = operator_payout_addr
                            else:
                                addr_info = 'not claimed'

                            operator_payout_entry = \
                                f'<tr><td class="title">Operator payout:</td><td class="value" ' \
                                f'colspan="2">{app_utils.to_string(operator_reward)}%, {addr_info}</td></tr>'

                        lastpaid_ts = 0
                        if mn_info:
                            if mn_info.lastpaidtime > time.time() - 3600 * 24 * 365:
                                # fresh dmns have lastpaidtime set to some day in the year 2014
                                lastpaid_ts = mn_info.lastpaidtime
                        else:
                            paid_block = dmn_tx_state.get('lastPaidHeight')
                            if paid_block:
                                bh = self.dashd_intf.getblockhash(paid_block)
                                blk = self.dashd_intf.getblockheader(bh, 1)
                                lastpaid_ts = blk.get('time')

                        if lastpaid_ts:
                            lastpaid_dt = datetime.datetime.fromtimestamp(float(lastpaid_ts))
                            lastpaid_str = app_utils.to_string(lastpaid_dt)
                            lastpaid_ago = int(time.time()) - int(lastpaid_ts)
                            if lastpaid_ago >= 2:
                                lastpaid_ago_str = ' / ' + app_utils.seconds_to_human(lastpaid_ago,
                                                                              out_unit_auto_adjust=True) + ' ago'
                            else:
                                lastpaid_ago_str = ' / a few seconds ago'
                            lastpaid_block_str = f' / block# {str(mn_info.lastpaidblock)}' if mn_info.lastpaidblock \
                                else ''

                            last_paid_entry = f'<tr><td class="title">Last Paid:</td><td class="value">' \
                                f'{lastpaid_str}{lastpaid_block_str}{lastpaid_ago_str}</td><td class="ago"></td></tr>'

                        if next_payment_block and next_payout_ts:
                            nextpayment_dt = datetime.datetime.fromtimestamp(float(next_payout_ts))
                            nextpayment_str = app_utils.to_string(nextpayment_dt)
                            next_payment_block_str = f' / block# {next_payment_block}'

                            next_payment_in = next_payout_ts - int(time.time())
                            if next_payment_in >= 2:
                                next_payment_in_str = ' / in ' + app_utils.seconds_to_human(next_payment_in,
                                                                                  out_unit_auto_adjust=True)
                            else:
                                next_payment_in_str = ' / in a few seconds'

                            next_payment_entry = f'<tr><td class="title">Next payment:</td><td class="value">' \
                                f'{nextpayment_str}{next_payment_block_str}' \
                                f'{next_payment_in_str}</td><td></td></tr>'

                    except Exception:
                        pass

                    errors = []
                    warnings  = []
                    skip_data_mismatch = False
                    if dmn_tx and not dmn_tx.get('confirmations'):
                        warnings.append('<td class="warning" colspan="2">ProRegTx not yet confirmed</td>')
                    else:
                        if self.dashd_intf.is_protx_update_pending(self.cur_masternode.dmn_tx_hash):
                            warnings.append('<td class="warning" colspan="2">The related protx update transaction '
                                            'is awaiting confirmations</td>')
                            skip_data_mismatch = True

                    if collateral_address_mismatch:
                        errors.append('<td class="error" colspan="2">Collateral address missing&frasl;mismatch</td>')
                    if collateral_tx_mismatch:
                        errors.append('<td class="error" colspan="2">Collateral TX hash and&frasl;or index '
                                      'missing&frasl;mismatch</td>')
                    if ip_port_mismatch and not skip_data_mismatch:
                        errors.append('<td class="error" colspan="2">Masternode IP and&frasl;or TCP port number '
                                      'missing&frasl;mismatch</td>')
                    if owner_public_address_mismatch and not skip_data_mismatch:
                        errors.append('<td class="error" colspan="2">Owner Dash address mismatch</td>')
                    if operator_pubkey_mismatch and not skip_data_mismatch:
                        errors.append('<td class="error" colspan="2">Operator public key mismatch</td>')
                    if voting_public_address_mismatch and not skip_data_mismatch:
                        errors.append('<td class="error" colspan="2">Voting Dash address mismatch</td>')
                    if not dmn_tx:
                        warnings.append('<td class="warning" colspan="2">Couldn\'d read protx info for this masternode'
                                        ' (look into the logfile for details)</td>')

                    errors_msg = ''
                    if errors:
                        for idx, e in enumerate(errors):
                            if idx == 0:
                                errors_msg += '<tr><td class="title">Errors:</td>'
                            else:
                                errors_msg += '<tr><td></td>'
                            errors_msg += e + '</tr>'
                    warnings_msg = ''
                    if warnings:
                        for idx, e in enumerate(warnings):
                            if idx == 0:
                                warnings_msg += '<tr><td class="title">Warnings:</td>'
                            else:
                                warnings_msg += '<tr><td></td>'
                            warnings_msg += e + '</tr>'

                    last_seen_html = ''

                    status = '<style>td {white-space:nowrap;padding-right:8px}' \
                             '.title {text-align:right;font-weight:bold}' \
                             '.ago {font-style:normal}' \
                             '.value {color:navy}' \
                             '.error {color:red}' \
                             '.warning {color:#e65c00}' \
                             '</style>' \
                             '<table>' \
                             f'<tr><td class="title">Status:</td><td class="value"><span style="color:{status_color}">{mn_status}</span>' \
                             f'</td><td></td></tr>' + \
                             last_seen_html + \
                             f'{payout_entry}' + \
                             f'{balance_entry}' + \
                             f'{operator_payout_entry}' + \
                             f'{last_paid_entry}' + \
                             f'{next_payment_entry}' + \
                             errors_msg + warnings_msg + '</table>'
                else:
                    status = '<span style="color:red">Masternode not found.</span>'
            else:
                status = '<span style="color:red">Masternode not found.</span>'
        else:
            status = '<span style="color:red">Problem with connection to dashd.</span>'

        if not self.finishing:
            if masternode != self.cur_masternode:
                status = ''

            self.call_in_main_thread(self.lblMnStatus.setText, status)

    @pyqtSlot(bool)
    def on_btnRefreshMnStatus_clicked(self):
        def enable_buttons():
            self.btnRefreshMnStatus.setEnabled(True)
            self.btnRegisterDmn.setEnabled(True)
            self.update_mn_controls_state()

        def on_get_status_exception(exception):
            enable_buttons()
            self.lblMnStatus.setText('')
            WndUtils.errorMsg(str(exception))

        self.lblMnStatus.setText('<b>Retrieving masternode information, please wait...<b>')
        self.btnRefreshMnStatus.setEnabled(False)
        self.btnRegisterDmn.setEnabled(False)
        self.btnUpdMnPayoutAddr.setEnabled(False)
        self.btnUpdMnOperatorKey.setEnabled(False)
        self.btnUpdMnVotingKey.setEnabled(False)
        self.btnUpdMnService.setEnabled(False)
        self.btnRevokeMn.setEnabled(False)

        self.connect_dash_network(wait_for_check_finish=True)
        if self.dashd_connection_ok:
            try:
                self.run_thread(self, self.get_masternode_status_description_thread, (self.cur_masternode,),
                                on_thread_finish=enable_buttons, on_thread_exception=on_get_status_exception)
            except Exception as e:
                self.lblMnStatus.setText('')
                raise
        else:
            enable_buttons()
            self.lblMnStatus.setText('')
            self.errorMsg('Dash daemon not connected')

    @pyqtSlot(bool)
    def on_action_transfer_funds_for_cur_mn_triggered(self):
        """
        Shows tranfser funds window with utxos related to current masternode. 
        """
        if self.cur_masternode:
            src_addresses = []
            if not self.cur_masternode.collateralBip32Path:
                self.errorMsg("Enter the masternode collateral BIP32 path. You can use the 'right arrow' button "
                              "on the right of the 'Collateral' edit box.")
            elif not self.cur_masternode.collateralAddress:
                self.errorMsg("Enter the masternode collateral Dash address. You can use the 'left arrow' "
                              "button on the left of the 'BIP32 path' edit box.")
            else:
                src_addresses.append((self.cur_masternode.collateralAddress, self.cur_masternode.collateralBip32Path))
                mn_index = self.app_config.masternodes.index(self.cur_masternode)
                self.show_wallet_window(mn_index)
        else:
            self.errorMsg('No masternode selected')

    @pyqtSlot(bool)
    def on_action_transfer_funds_for_all_mns_triggered(self):
        """
        Shows tranfser funds window with utxos related to all masternodes. 
        """
        self.show_wallet_window(None)

    @pyqtSlot(bool)
    def on_action_transfer_funds_for_any_address_triggered(self):
        """
        Shows tranfser funds window for address/path specified by the user.
        """
        if self.cur_masternode:
            mn_index = self.app_config.masternodes.index(self.cur_masternode)
        else:
            mn_index = None
        self.show_wallet_window(mn_index)

    def show_wallet_window(self, initial_mn: Optional[int]):
        """ Shows the wallet/send payments dialog.
        :param initial_mn:
          if the value is from 0 to len(masternodes), show utxos for the masternode
            having the 'initial_mn' index in self.app_config.mastrnodes
          if the value is -1, show utxo for all masternodes
          if the value is None, show the default utxo source type
        """
        if not self.dashd_intf.open():
            self.errorMsg('Dash daemon not connected')
        else:
            ui = wallet_dlg.WalletDlg(self, initial_mn_sel=initial_mn)
            ui.exec_()

    @pyqtSlot(bool)
    def on_action_sign_message_with_collateral_addr_triggered(self):
        if self.cur_masternode:
            self.connect_hardware_wallet()
            if self.hw_client:
                if not self.cur_masternode.collateralBip32Path:
                    self.errorMsg("No masternode collateral BIP32 path")
                else:
                    ui = SignMessageDlg(self, self.hw_session, self.cur_masternode.collateralBip32Path,
                                        self.cur_masternode.collateralAddress)
                    ui.exec_()
        else:
            self.errorMsg("To sign messages, you must select a masternode.")

    @pyqtSlot(bool)
    def on_action_sign_message_with_owner_key_triggered(self):
        if self.cur_masternode:
            pk = self.cur_masternode.dmn_owner_private_key
            if not pk:
                self.errorMsg("The masternode owner private key has not been configured.")
            else:
                ui = SignMessageDlg(self, None, None, None, pk)
                ui.exec_()
        else:
            self.errorMsg("To sign messages, you must select a masternode.")

    @pyqtSlot(bool)
    def on_action_sign_message_with_voting_key_triggered(self):
        if self.cur_masternode:
            pk = self.cur_masternode.dmn_voting_private_key
            if not pk:
                self.errorMsg("The masternode voting private key has not been configured.")
            else:
                ui = SignMessageDlg(self, None, None, None, pk)
                ui.exec_()
        else:
            self.errorMsg("To sign messages, you must select a masternode.")

    @pyqtSlot(bool)
    def on_action_hw_configuration_triggered(self):
        """
        Hardware wallet setup.
        """
        self.connect_hardware_wallet()
        if self.hw_client:
            ui = HwSetupDlg(self)
            ui.exec_()

    @pyqtSlot(bool)
    def on_action_hw_initialization_recovery_triggered(self):
        """
        Hardware wallet initialization from a seed.
        """
        ui = HwInitializeDlg(self)
        ui.exec_()

    @pyqtSlot(bool)
    def on_action_open_proposals_window_triggered(self):
        ui = ProposalsDlg(self, self.dashd_intf)
        ui.exec_()

    @pyqtSlot(bool)
    def on_action_about_qt_triggered(self, enabled):
        QApplication.aboutQt()

    @pyqtSlot(bool)
    def on_btnRegisterDmn_clicked(self, enabled):
        reg_dlg = None

        def on_proregtx_finished(masternode: MasternodeConfig):
            nonlocal reg_dlg, self
            try:
                if self.cur_masternode.dmn_tx_hash != reg_dlg.dmn_reg_tx_hash or \
                        self.cur_masternode.dmn_owner_key_type != reg_dlg.dmn_owner_key_type or \
                        (self.cur_masternode.dmn_owner_key_type == InputKeyType.PRIVATE and
                         self.cur_masternode.dmn_owner_private_key != reg_dlg.dmn_owner_privkey) or \
                        (self.cur_masternode.dmn_owner_key_type == InputKeyType.PUBLIC and
                         self.cur_masternode.dmn_owner_address != reg_dlg.dmn_owner_address) or \
                        self.cur_masternode.dmn_operator_key_type != reg_dlg.dmn_operator_key_type or \
                        (self.cur_masternode.dmn_operator_key_type == InputKeyType.PRIVATE and
                         self.cur_masternode.dmn_operator_private_key != reg_dlg.dmn_operator_privkey) or \
                        (self.cur_masternode.dmn_operator_key_type == InputKeyType.PUBLIC and
                         self.cur_masternode.dmn_operator_public_key != reg_dlg.dmn_operator_pubkey) or \
                        self.cur_masternode.dmn_voting_key_type != reg_dlg.dmn_voting_key_type or \
                        (self.cur_masternode.dmn_voting_key_type == InputKeyType.PRIVATE and
                         self.cur_masternode.dmn_voting_private_key != reg_dlg.dmn_voting_privkey) or \
                        (self.cur_masternode.dmn_voting_key_type == InputKeyType.PUBLIC and
                         self.cur_masternode.dmn_voting_address != reg_dlg.dmn_voting_address):

                    self.cur_masternode.dmn_tx_hash = reg_dlg.dmn_reg_tx_hash

                    self.cur_masternode.dmn_owner_key_type = reg_dlg.dmn_owner_key_type
                    if self.cur_masternode.dmn_owner_key_type == InputKeyType.PRIVATE:
                        self.cur_masternode.dmn_owner_private_key = reg_dlg.dmn_owner_privkey
                    else:
                        self.cur_masternode.dmn_owner_address = reg_dlg.dmn_owner_address
                        self.cur_masternode.dmn_owner_private_key = ''

                    self.cur_masternode.dmn_operator_key_type = reg_dlg.dmn_operator_key_type
                    if self.cur_masternode.dmn_operator_key_type == InputKeyType.PRIVATE:
                        self.cur_masternode.dmn_operator_private_key = reg_dlg.dmn_operator_privkey
                    else:
                        self.cur_masternode.dmn_operator_public_key = reg_dlg.dmn_operator_pubkey
                        self.cur_masternode.dmn_operator_private_key = ''

                    self.cur_masternode.dmn_voting_key_type = reg_dlg.dmn_voting_key_type
                    if self.cur_masternode.dmn_voting_key_type == InputKeyType.PRIVATE:
                        self.cur_masternode.dmn_voting_private_key = reg_dlg.dmn_voting_privkey
                    else:
                        self.cur_masternode.dmn_voting_address = reg_dlg.dmn_voting_address
                        self.cur_masternode.dmn_voting_private_key = ''

                    if self.cur_masternode == masternode:
                        self.wdg_masternode.masternode_data_to_ui()
                    if self.app_config.is_modified():
                        self.wdg_masternode.set_modified()
                    else:
                        self.save_configuration()
            except Exception as e:
                logging.exception(str(e))

        if self.cur_masternode:
            reg_dlg = reg_masternode_dlg.RegMasternodeDlg(self, self.app_config, self.dashd_intf, self.cur_masternode,
                                                          on_proregtx_success_callback=on_proregtx_finished)
            reg_dlg.exec_()
        else:
            WndUtils.errorMsg('No masternode selected')

    def update_registrar(self, show_upd_payout: bool, show_upd_operator: bool, show_upd_voting: bool):
        def on_updtx_finished(masternode: MasternodeConfig):
            try:
                if self.cur_masternode == masternode:
                    self.wdg_masternode.masternode_data_to_ui()
                if self.app_config.is_modified():
                    self.wdg_masternode.set_modified()
                else:
                    self.save_configuration()
            except Exception as e:
                logging.exception(str(e))

        if self.cur_masternode:
            upd_dlg = upd_mn_registrar_dlg.UpdMnRegistrarDlg(
                self, self.app_config, self.dashd_intf, self.cur_masternode,
                on_upd_success_callback=on_updtx_finished, show_upd_payout=show_upd_payout,
                show_upd_operator=show_upd_operator, show_upd_voting=show_upd_voting)
            upd_dlg.exec_()
        else:
            WndUtils.errorMsg('No masternode selected')

    def update_service(self):
        def on_mn_config_updated(masternode: MasternodeConfig):
            try:
                if self.cur_masternode == masternode:
                    self.wdg_masternode.masternode_data_to_ui()
                if self.app_config.is_modified():
                    self.wdg_masternode.set_modified()
                else:
                    self.save_configuration()
            except Exception as e:
                logging.exception(str(e))

        if self.cur_masternode:
            upd_dlg = upd_mn_service_dlg.UpdMnServiceDlg(
                self, self.app_config, self.dashd_intf, self.cur_masternode,
                on_mn_config_updated_callback=on_mn_config_updated)
            upd_dlg.exec_()
        else:
            WndUtils.errorMsg('No masternode selected')

    def revoke_mn_operator(self):
        if self.cur_masternode:
            revoke_dlg = revoke_mn_dlg.RevokeMnDlg(
                self, self.app_config, self.dashd_intf, self.cur_masternode)
            revoke_dlg.exec_()
        else:
            WndUtils.errorMsg('No masternode selected')

    @pyqtSlot()
    def on_btnUpdMnPayoutAddr_clicked(self):
        self.update_registrar(show_upd_payout=True, show_upd_operator=False, show_upd_voting=False)

    @pyqtSlot()
    def on_btnUpdMnOperatorKey_clicked(self):
        self.update_registrar(show_upd_payout=False, show_upd_operator=True, show_upd_voting=False)

    @pyqtSlot()
    def on_btnUpdMnVotingKey_clicked(self):
        self.update_registrar(show_upd_payout=False, show_upd_operator=False, show_upd_voting=True)

    @pyqtSlot()
    def on_btnUpdMnService_clicked(self):
        self.update_service()

    @pyqtSlot()
    def on_btnRevokeMn_clicked(self):
        self.revoke_mn_operator()

