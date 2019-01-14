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
from typing import Optional, Tuple, Dict, Callable
import bitcoin
import logging
import urllib.request
from PyQt5 import QtCore
from PyQt5 import QtWidgets
from PyQt5.QtCore import QSize, pyqtSlot, QEventLoop, QMutex, QWaitCondition, QUrl, Qt
from PyQt5.QtGui import QFont, QIcon, QDesktopServices
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QFileDialog, QMenu, QMainWindow, QPushButton, QStyle, QInputDialog, QApplication, \
    QHBoxLayout
from PyQt5.QtWidgets import QMessageBox

import reg_masternode_dlg
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
from app_config import AppConfig, MasternodeConfig, APP_NAME_SHORT
from app_defs import PROJECT_URL, HWType, get_note_url
from dash_utils import bip32_path_n_to_string
from dashd_intf import DashdInterface, DashdIndexException
from hw_common import HardwareWalletCancelException, HardwareWalletPinException, HwSessionInfo
import hw_intf
from hw_setup_dlg import HwSetupDlg
from psw_cache import SshPassCache
from sign_message_dlg import SignMessageDlg
from wnd_utils import WndUtils
from ui import ui_main_dlg


class MainWindow(QMainWindow, WndUtils, ui_main_dlg.Ui_MainWindow):
    update_status_signal = QtCore.pyqtSignal(str, str)  # signal for updating status text from inside thread

    def __init__(self, app_dir):
        QMainWindow.__init__(self)
        WndUtils.__init__(self, None)
        ui_main_dlg.Ui_MainWindow.__init__(self)

        self.hw_client = None
        self.finishing = False
        self.config = AppConfig()
        self.config.init(app_dir)
        WndUtils.set_app_config(self, self.config)

        self.dashd_intf = DashdInterface(window=None,
                                         on_connection_initiated_callback=self.show_connection_initiated,
                                         on_connection_failed_callback=self.show_connection_failed,
                                         on_connection_successful_callback=self.show_connection_successful,
                                         on_connection_disconnected_callback=self.show_connection_disconnected)
        self.hw_session = HwSessionInfo(
            self.get_hw_client,
            self.connect_hardware_wallet,
            self.disconnect_hardware_wallet,
            self.config,
            dashd_intf=self.dashd_intf)

        self.remote_app_params = {}
        self.dashd_info = {}
        self.is_dashd_syncing = False
        self.dashd_connection_ok = False
        self.connecting_to_dashd = False
        self.curMasternode = None
        self.editing_enabled = False
        self.recent_config_files = []

        # load most recently used config files from the data cache
        mru_cf = app_cache.get_value('MainWindow_ConfigFileMRUList', default_value=[], type=list)
        if isinstance(mru_cf, list):
            for file_name in mru_cf:
                if os.path.exists(file_name):
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
        self.show_hide_trezor_emulator()
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
        self.setStatus2Text('<b>HW status:</b> idle', 'black')

        # set stylesheet for editboxes, supporting different colors for read-only and edting mode
        self.styleSheet = "QLineEdit{background-color: white} QLineEdit:read-only{background-color: lightgray}"
        self.setStyleSheet(self.styleSheet)
        self.setIcon(self.action_save_config_file, 'save.png')
        self.setIcon(self.action_check_network_connection, "link-check.png")
        self.setIcon(self.action_open_settings_window, "gear.png")
        self.setIcon(self.action_open_proposals_window, "thumbs-up-down.png")
        self.setIcon(self.action_test_hw_connection, "hw-test.png")
        self.setIcon(self.action_disconnect_hw, "hw-disconnect.png")
        self.setIcon(self.action_run_trezor_emulator, "hw-emulator.png")
        self.setIcon(self.action_transfer_funds_for_any_address, "wallet.png")
        self.setIcon(self.action_sign_message_for_cur_mn, "sign@32px.png")
        self.setIcon(self.action_hw_configuration, "hw.png")
        self.setIcon(self.action_hw_initialization_recovery, "recover.png")
        # icons will not be visible in menu
        self.action_save_config_file.setIconVisibleInMenu(False)
        self.action_check_network_connection.setIconVisibleInMenu(False)
        self.action_open_settings_window.setIconVisibleInMenu(False)
        self.action_open_proposals_window.setIconVisibleInMenu(False)
        self.action_test_hw_connection.setIconVisibleInMenu(False)
        self.action_disconnect_hw.setIconVisibleInMenu(False)
        self.action_run_trezor_emulator.setIconVisibleInMenu(False)
        self.action_transfer_funds_for_any_address.setIconVisibleInMenu(False)
        self.action_sign_message_for_cur_mn.setIconVisibleInMenu(False)
        self.action_hw_configuration.setIconVisibleInMenu(False)
        self.action_hw_initialization_recovery.setIconVisibleInMenu(False)

        # register dialog-type actions:
        self.addAction(self.action_gen_mn_priv_key_uncompressed)
        self.addAction(self.action_gen_mn_priv_key_compressed)

        # add masternodes' info to the combobox
        self.curMasternode = None

        self.wdg_masternode = WdgMasternodeDetails(self, self.app_config, self.dashd_intf)
        l = self.frmMasternodeDetails.layout()
        l.insertWidget(0, self.wdg_masternode)
        self.wdg_masternode.name_modified.connect(self.on_mn_name_modified)
        self.wdg_masternode.data_changed.connect(self.on_mn_data_changed)

        self.mns_user_refused_updating = {}

        # after loading whole configuration, reset 'modified' variable
        try:
            self.config.read_from_file(hw_session=self.hw_session, create_config_file=True)
        except Exception as e:
            raise
        self.display_window_title()
        self.dashd_intf.initialize(self.config)

        self.update_edit_controls_state()
        self.setMessage("", None)

        self.run_thread(self, self.get_project_config_params_thread, (False,))

        if self.config.app_config_file_name and os.path.exists(self.config.app_config_file_name):
            self.add_item_to_config_files_mru_list(self.config.app_config_file_name)
        self.update_config_files_mru_menu_items()

        self.inside_setup_ui = False
        self.configuration_to_ui()
        logging.info('Finished setup of the main dialog.')

    def closeEvent(self, event):
        app_cache.save_window_size(self)
        self.finishing = True
        if self.dashd_intf:
            self.dashd_intf.disconnect()

        if self.config.is_modified():
            if self.queryDlg('Configuration modified. Save?',
                             buttons=QMessageBox.Yes | QMessageBox.No,
                             default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:
                self.save_configuration()
        self.config.close()

    def showEvent(self, QShowEvent):
        width = max(self.wdg_masternode.get_max_left_label_width(), self.lblMasternodeStatus.width())
        self.lblMasternodeStatus.setFixedWidth(width)
        self.wdg_masternode.set_left_label_width(width)
        self.cboMasternodes.setFixedHeight(self.btnNewMn.height())

    def get_hw_client(self):
        return self.hw_client

    def configuration_to_ui(self):
        """
        Show the information read from configuration file on the user interface.
        :return:
        """

        # add masternodes data to the combobox
        self.curMasternode = None
        self.cboMasternodes.clear()
        for mn in self.config.masternodes:
            self.cboMasternodes.addItem(mn.name, mn)
        if self.config.masternodes:
            # get last masternode selected
            idx = app_cache.get_value('MainWindow_CurMasternodeIndex', 0, int)
            if idx >= len(self.config.masternodes):
                idx = 0
            self.curMasternode = self.config.masternodes[idx]
            self.display_masternode_config(True)
        else:
            self.curMasternode = None

        self.wdg_masternode.set_masternode(self.curMasternode)
        self.action_open_log_file.setText('Open log file (%s)' % self.config.log_file)
        self.btnMigrateToDMN.setEnabled(True)
        self.update_edit_controls_state()

    def load_configuration_from_file(self, file_name: str, ask_save_changes = True) -> None:
        """
        Load configuration from a file.
        :param file_name: A name of the configuration file to be loaded into the application.
        """
        if self.config.is_modified() and ask_save_changes:
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
            dash_network_sav = self.config.dash_network
            self.config.read_from_file(hw_session=self.hw_session, file_name=file_name)
            self.editing_enabled = False
            self.configuration_to_ui()
            self.dashd_intf.reload_configuration()
            self.config.modified = False
            file_name = self.config.app_config_file_name
            if file_name:
                self.add_item_to_config_files_mru_list(file_name)
                self.update_config_files_mru_menu_items()
                if dash_network_sav != self.config.dash_network:
                    self.disconnect_hardware_wallet()
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
                                        self.config.app_config_file_name,
                                        self.on_config_file_mru_clear_triggered)

    def show_hide_trezor_emulator(self):
        enabled = False
        self.action_run_trezor_emulator.setVisible(enabled)

    def on_config_file_mru_action_triggered(self, file_name: str) -> None:
        """ Triggered by clicking one of the subitems of the 'Open Recent' menu item. Each subitem is
        related to one of recently openend configuration files.
        :param file_name: A config file name accociated with the menu action clicked.
        """
        if file_name != self.config.app_config_file_name:
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
        app_version_part = ' (v' + self.config.app_version + ')' if self.config.app_version else ''

        if self.config.dash_network == 'TESTNET':
            testnet_part = ' [TESTNET]'
        else:
            testnet_part = ''

        if self.config.app_config_file_name:
            cfg_file_name = self.config.app_config_file_name
            if cfg_file_name:
                home_dir = os.path.expanduser('~')
                if cfg_file_name.find(home_dir) == 0:
                    cfg_file_name = '~' + cfg_file_name[len(home_dir):]
                else:
                    cfg_file_name = cfg_file_name
            cfg_file_name_part = ' - ' + cfg_file_name if cfg_file_name else ''
        else:
            cfg_file_name_part = '  <UNNAMED>'

        if self.config.config_file_encrypted:
            encrypted_part = ' (Encrypted)'
        else:
            encrypted_part = ''

        title = f'{APP_NAME_SHORT}{app_version_part}{testnet_part}{cfg_file_name_part}{encrypted_part}'

        self.setWindowTitle(title)

    @pyqtSlot(bool)
    def on_action_load_config_file_triggered(self, checked):
        if self.config.app_config_file_name:
            dir = os.path.dirname(self.config.app_config_file_name)
        else:
            dir = self.config.data_dir
        file_name = self.open_config_file_query(dir, self)

        if file_name:
            if os.path.exists(file_name):
                self.load_configuration_from_file(file_name)
            else:
                WndUtils.errorMsg(f'File \'{file_name}\' does not exist.')

    def save_configuration(self, file_name: str = None):
        self.config.save_to_file(hw_session=self.hw_session, file_name=file_name)
        file_name = self.config.app_config_file_name
        if file_name:
            self.add_item_to_config_files_mru_list(file_name)
        self.update_config_files_mru_menu_items()
        self.display_window_title()
        self.editing_enabled = self.config.is_modified()
        self.wdg_masternode.set_edit_mode(self.editing_enabled )
        self.update_edit_controls_state()

    @pyqtSlot(bool)
    def on_action_save_config_file_triggered(self, checked):
        self.save_configuration()

    @pyqtSlot(bool)
    def on_action_save_config_file_as_triggered(self, checked):
        if self.config.app_config_file_name:
            dir = os.path.dirname(self.config.app_config_file_name)
        else:
            dir = self.config.data_dir
        file_name = self.save_config_file_query(dir, self)

        if file_name:
            self.save_configuration(file_name)

    @pyqtSlot(bool)
    def on_action_open_log_file_triggered(self, checked):
        if os.path.exists(self.config.log_file):
            ret = QDesktopServices.openUrl(QUrl("file:///%s" % self.config.log_file))
            if not ret:
                self.warnMsg('Could not open "%s" file in a default OS application.' % self.config.log_file)

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
            self.remote_app_params = simplejson.loads(contents)

            if self.remote_app_params:
                logging.info('Loaded the project configuration params: ' + str(self.remote_app_params))
                if self.config.check_for_updates:
                    remote_version_str = self.remote_app_params.get("appCurrentVersion")
                    if remote_version_str:
                        remote_ver = app_utils.version_str_to_number(remote_version_str)
                        local_ver = app_utils.version_str_to_number(self.config.app_version)

                        if remote_ver > local_ver:
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
                            exe_down = self.remote_app_params.get('exeDownloads')
                            if exe_down:
                                exe_url = exe_down.get(item_name)
                            if exe_url:
                                msg = "New version (" + remote_version_str + ') available: <a href="' + exe_url + '">download</a>.'
                            else:
                                msg = "New version (" + remote_version_str + ') available. Go to the project website: <a href="' + \
                                      PROJECT_URL + '">open</a>.'

                            self.setMessage(msg, 'green')
                        else:
                            if force_check:
                                self.setMessage("You have the latest version of %s." % APP_NAME_SHORT, 'green')
                    elif force_check:
                        self.setMessage("Could not read the remote version number.", 'orange')

        except Exception:
            logging.exception('Exception occurred while loading/processing the project remote configuration')

    def display_masternode_config(self, set_mn_list_index):
        if self.curMasternode:
            if set_mn_list_index:
                self.cboMasternodes.setCurrentIndex(self.config.masternodes.index(self.curMasternode))
            else:
                self.wdg_masternode.set_masternode(self.curMasternode)
            self.update_edit_controls_state()
        else:
            self.wdg_masternode.set_masternode(None)
        self.lblMnStatus.setText('')

    @pyqtSlot(bool)
    def on_action_open_settings_window_triggered(self):
        dash_network_sav = self.config.dash_network
        hw_type_sav = self.config.hw_type
        dlg = ConfigDlg(self, self.config)
        res = dlg.exec_()
        if res and dlg.get_is_modified():
            self.config.configure_cache()
            self.dashd_intf.reload_configuration()
            if dash_network_sav != self.config.dash_network or hw_type_sav != self.config.hw_type:
                self.disconnect_hardware_wallet()
            self.display_window_title()
            self.update_edit_controls_state()
        del dlg

    @pyqtSlot(bool)
    def on_action_about_app_triggered(self):
        ui = about_dlg.AboutDlg(self, self.config.app_version)
        ui.exec_()

    def show_connection_initiated(self):
        """Shows status information related to a initiated process of connection to a dash RPC. """
        self.setStatus1Text('<b>RPC network status:</b> trying %s...' % self.dashd_intf.get_active_conn_description(), 'black')

    def show_connection_failed(self):
        """Shows status information related to a failed connection attempt. There can be more attempts to connect
        to another nodes if there are such in configuration."""
        self.setStatus1Text('<b>RPC network status:</b> failed connection to %s' % self.dashd_intf.get_active_conn_description(), 'red')

    def show_connection_successful(self):
        """Shows status information after successful connetion to a Dash RPC node."""
        self.setStatus1Text('<b>RPC network status:</b> OK (%s)' % self.dashd_intf.get_active_conn_description(), 'green')

    def show_connection_disconnected(self):
        """Shows status message related to disconnection from Dash RPC node."""
        self.setStatus1Text('<b>RPC network status:</b> not connected', 'black')

    def checkDashdConnection(self, wait_for_check_finish=False, call_on_check_finished=None):
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
                    self.setMessage('Dashd is synchronizing: AssetID: %s, AssetName: %s' %
                                        (str(mnsync.get('AssetID', '')),
                                         str(mnsync.get('AssetName', ''))
                                         ), style='{background-color:rgb(255,128,0);color:white;padding:3px 5px 3px 5px; border-radius:3px}')
                    cond.wait(mtx, 5000)
                self.setMessage('')
            except Exception as e:
                self.is_dashd_syncing = False
                self.dashd_connection_ok = False
                self.setMessage(str(e),
                                style='{background-color:red;color:white;padding:3px 5px 3px 5px; border-radius:3px}')
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
                self.setMessage('')
            except Exception as e:
                err = str(e)
                if not err:
                    err = 'Connect error: %s' % type(e).__name__
                self.is_dashd_syncing = False
                self.dashd_connection_ok = False
                self.show_connection_failed()
                self.setMessage(err,
                                style='{background-color:red;color:white;padding:3px 5px 3px 5px; border-radius:3px}')

        def connect_finished():
            """
            Called after thread terminates.
            """
            del self.check_conn_thread
            self.check_conn_thread = None
            self.connecting_to_dashd = False
            if call_on_check_finished:
                call_on_check_finished()
            if event_loop:
                event_loop.exit()

        if self.config.is_config_complete():
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
        self.connect_dash_network()

    def connect_dash_network(self):
        def connection_test_finished():

            self.action_check_network_connection.setEnabled(True)
            self.btnBroadcastMn.setEnabled(True)
            self.btnMigrateToDMN.setEnabled(True)
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

        if self.config.is_config_complete():
            self.action_check_network_connection.setEnabled(False)
            self.btnBroadcastMn.setEnabled(False)
            self.btnMigrateToDMN.setEnabled(False)
            self.btnRefreshMnStatus.setEnabled(False)
            # disable all actions that utilize dash network
            self.action_transfer_funds_for_any_address.setEnabled(False)
            self.checkDashdConnection(call_on_check_finished=connection_test_finished)
        else:
            # configuration not complete: show config window
            self.errorMsg("There are no (enabled) connections to an RPC node in your configuration.")

    def setStatus1Text(self, text, color):
        def set_status(text, color):
            self.lblStatus1.setText(text)
            if not color:
                color = 'black'
            self.lblStatus1.setStyleSheet('QLabel{color: ' + color + ';margin-right:20px;margin-left:8px}')

        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(set_status, text, color)
        else:
            set_status(text, color)

    def setStatus2Text(self, text, color):
        def set_status(text, color):
            self.lblStatus2.setText(text)
            if not color:
                color = 'black'
            self.lblStatus2.setStyleSheet('QLabel{color: ' + color + '}')

        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(set_status, text, color)
        else:
            set_status(text, color)

    def setMessage(self, text, color=None, style=None):
        """
        Display message in the app message area.
        :param text: Text to be displayed. If Text is empty, message area will be hidden. 
        :param color: Color of thext.
        """
        def set_message(text, color, style):
            left, top, right, bottom = self.layMessage.getContentsMargins()

            if not text:
                self.lblMessage.setVisible(False)
                self.layMessage.setContentsMargins(left, top, right, 0)
            else:
                self.lblMessage.setVisible(True)
                self.lblMessage.setText(text)
                self.layMessage.setContentsMargins(left, top, right, 4)
                if color:
                    style = '{color:%s}' % color
                if style:
                    self.lblMessage.setStyleSheet('QLabel%s' % style)

        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(set_message, text, color, style)
        else:
            set_message(text, color, style)

    def getHwName(self):
        if self.config.hw_type == HWType.trezor:
            return 'Trezor'
        elif self.config.hw_type == HWType.keepkey:
            return 'KeepKey'
        elif self.config.hw_type == HWType.ledger_nano_s:
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
            if self.config.hw_type != cur_hw_type:
                self.on_action_disconnect_hw_triggered()

        if not self.hw_client:
            try:
                try:
                    logging.info('Connecting to a hardware wallet device. self: ' + str(self))
                    self.hw_client = hw_intf.connect_hw(hw_session=self.hw_session,
                                                        device_id=None,
                                                        passphrase_encoding=self.config.hw_keepkey_psw_encoding,
                                                        hw_type=self.config.hw_type)

                    if self.config.dash_network == 'TESTNET':
                        # check if Dash testnet is supported by this hardware wallet
                        found_testnet_support = False
                        if self.config.hw_type in (HWType.trezor, HWType.keepkey):
                            try:
                                path = dash_utils.get_default_bip32_base_path(self.config.dash_network)
                                path += "/0'/0/0"
                                path_n = dash_utils.bip32_path_string_to_n(path)
                                addr = hw_intf.get_address(self.hw_session, path_n, False)
                                if dash_utils.validate_address(addr, self.config.dash_network):
                                    found_testnet_support = True
                            except Exception as e:
                                if str(e).find('Invalid coin name') < 0:
                                    logging.exception('Failed when looking for Dash testnet support')
                        elif self.config.hw_type == HWType.ledger_nano_s:
                            addr = hw_intf.get_address(self.hw_session,
                                                       dash_utils.get_default_bip32_path(self.config.dash_network))
                            if dash_utils.validate_address(addr, self.config.dash_network):
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
                            self.setStatus2Text(msg, 'red')
                            return

                    logging.info('Connected to a hardware wallet')
                    self.setStatus2Text('<b>HW status:</b> connected to %s' % hw_intf.get_hw_label(self.hw_client),
                                        'green')
                    self.update_edit_controls_state()
                except HardwareWalletCancelException:
                    raise
                except Exception as e:
                    logging.exception('Exception while connecting hardware wallet')
                    try:
                        self.disconnect_hardware_wallet()
                    except Exception:
                        pass
                    logging.info('Could not connect to a hardware wallet')
                    self.setStatus2Text('<b>HW status:</b> cannot connect to %s device' % self.getHwName(), 'red')
                    self.errorMsg(str(e))

                ret = self.hw_client
            except HardwareWalletCancelException:
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
        self.connect_hardware_wallet()
        self.update_edit_controls_state()
        if self.hw_client:
            try:
                if self.config.hw_type in (HWType.trezor, HWType.keepkey):
                    self.infoMsg('Connection to %s device (%s) successful.' %
                                 (self.getHwName(), hw_intf.get_hw_label(self.hw_client)))
                elif self.config.hw_type == HWType.ledger_nano_s:
                    self.infoMsg('Connection to %s device successful.' %
                                 (self.getHwName(),))
            except HardwareWalletCancelException:
                if self.hw_client:
                    self.hw_client.init_device()

    def disconnect_hardware_wallet(self) -> None:
        if self.hw_client:
            hw_intf.disconnect_hw(self.hw_client)
            del self.hw_client
            self.hw_client = None
            self.setStatus2Text('<b>HW status:</b> idle', 'black')
            self.update_edit_controls_state()

    @pyqtSlot(bool)
    def on_action_disconnect_hw_triggered(self):
        self.disconnect_hardware_wallet()

    @pyqtSlot(bool)
    def on_btnNewMn_clicked(self):
        self.newMasternodeConfig(copy_values_from_current=False)

    @pyqtSlot(bool)
    def on_btnDeleteMn_clicked(self):
        if self.curMasternode:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setText('Do you really want to delete current masternode configuration?')
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            retval = msg.exec_()
            if retval == QMessageBox.No:
                return
            self.config.masternodes.remove(self.curMasternode)
            self.cboMasternodes.removeItem(self.cboMasternodes.currentIndex())
            self.config.modified = True
            self.update_edit_controls_state()

    @pyqtSlot(bool)
    def on_btnDuplicateMn_clicked(self):
        self.newMasternodeConfig(copy_values_from_current=True)

    @pyqtSlot(bool)
    def on_btnEditMn_clicked(self):
        self.editing_enabled = True
        self.wdg_masternode.set_edit_mode(self.editing_enabled )
        self.update_edit_controls_state()

    @pyqtSlot(bool)
    def on_btnCancelEditingMn_clicked(self, checked):
        if self.config.is_modified():
            if WndUtils.queryDlg('Configuration modified. Discard changes?',
                                 buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                 default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Yes:
                # reload the configuration (we don't keep the old values)
                sel_mn_idx = self.app_config.masternodes.index(self.curMasternode)
                # reload the configuration from file
                self.load_configuration_from_file(self.config.app_config_file_name, ask_save_changes=False)
                self.editing_enabled = False
                if sel_mn_idx >= 0 and sel_mn_idx < len(self.config.masternodes):
                    self.curMasternode = self.config.masternodes[sel_mn_idx]
                    self.display_masternode_config(sel_mn_idx)
                self.wdg_masternode.set_edit_mode(self.editing_enabled)
                self.update_edit_controls_state()
            return
        else:
            self.editing_enabled = False
            self.wdg_masternode.set_edit_mode(self.editing_enabled)
            self.update_edit_controls_state()

    @pyqtSlot(bool)
    def on_action_import_masternode_conf_triggered(self, checked):
        """
        Imports masternodes configuration from masternode.conf file.
        """

        file_name = self.open_file_query(self,
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
                                    in_mn.privateKey = mn_privkey
                                    in_mn.collateralAddress = mn_dash_addr
                                    in_mn.collateralTx = mn_tx_hash
                                    in_mn.collateralTxIndex = mn_tx_idx
                                    in_mn.collateralBip32Path = ''

                                mn = self.config.get_mn_by_name(mn_name)
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
                                        if self.curMasternode == mn:
                                            # current mn has been updated - update UI controls to new data
                                            self.display_masternode_config(False)
                                else:
                                    imported_cnt += 1
                                    mn = MasternodeConfig()
                                    update_mn(mn)
                                    modified = True
                                    self.config.add_mn(mn)
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
                                            if self.curMasternode == mn:
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
            editing = (self.editing_enabled and self.curMasternode is not None)
            self.action_gen_mn_priv_key_uncompressed.setEnabled(editing)
            self.action_gen_mn_priv_key_compressed.setEnabled(editing)
            self.btnDeleteMn.setEnabled(self.curMasternode is not None)
            self.btnEditMn.setEnabled(not self.editing_enabled and self.curMasternode is not None)
            self.btnCancelEditingMn.setEnabled(self.editing_enabled and self.curMasternode is not None)
            self.btnDuplicateMn.setEnabled(self.curMasternode is not None)
            self.action_save_config_file.setEnabled(self.config.is_modified())
            self.action_disconnect_hw.setEnabled(True if self.hw_client else False)
            self.btnRefreshMnStatus.setEnabled(self.curMasternode is not None)
            self.btnBroadcastMn.setEnabled(self.curMasternode is not None)
            self.btnMigrateToDMN.setEnabled(self.curMasternode is not None)
        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(update_fun)
        else:
            update_fun()

    def newMasternodeConfig(self, copy_values_from_current: bool = False):
        new_mn = MasternodeConfig()
        new_mn.new = True
        cur_masternode_sav = self.curMasternode
        self.curMasternode = new_mn

        if copy_values_from_current and cur_masternode_sav:
            mn_template = cur_masternode_sav.name
        else:
            if self.app_config.is_testnet():
                new_mn.port = '19999'
            mn_template = 'MN'
        name_found = None
        for nr in range(1, 100):
            exists = False
            for mn in self.config.masternodes:
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

        self.config.masternodes.append(new_mn)
        self.editing_enabled = True
        old_index = self.cboMasternodes.currentIndex()
        self.cboMasternodes.addItem(new_mn.name, new_mn)
        if old_index != -1:
            # if masternodes combo was not empty before adding new mn, we have to manually set combobox
            # position to a new masternode position
            self.cboMasternodes.setCurrentIndex(self.config.masternodes.index(self.curMasternode))
        self.wdg_masternode.set_masternode(self.curMasternode)
        self.wdg_masternode.set_edit_mode(self.editing_enabled )

    def curMnModified(self):
        if self.curMasternode:
            self.curMasternode.set_modified()
            self.action_save_config_file.setEnabled(self.config.is_modified())

    @pyqtSlot(int)
    def on_cboMasternodes_currentIndexChanged(self):
        if self.cboMasternodes.currentIndex() >= 0:
            self.curMasternode = self.config.masternodes[self.cboMasternodes.currentIndex()]
        else:
            self.curMasternode = None
        self.display_masternode_config(False)

    def on_mn_name_modified(self, new_name):
        if self.curMasternode:
            self.cboMasternodes.setItemText(self.cboMasternodes.currentIndex(), self.curMasternode.name)

    def on_mn_data_changed(self, masternode: MasternodeConfig):
        if self.curMasternode == masternode:
            self.curMnModified()

    def get_default_protocol(self) -> int:
        prot = None
        if self.remote_app_params:
            dp = self.remote_app_params.get('defaultDashdProtocol')
            if dp:
                prot = dp.get(self.config.dash_network.lower())
        return prot

    def get_spork_state_from_config(self, spork_nr: int, dash_network: str, default_state: bool):
        state = default_state
        if self.remote_app_params:
            sporks = self.remote_app_params.get('sporks')
            if sporks and isinstance(sporks, list):
                for spork in sporks:
                    name = spork.get('name', '')
                    active = spork.get('active')
                    if name.find('SPORK_' + str(spork_nr) + '_') == 0:
                        state = active.get(dash_network.lower(), state)
        return state

    def create_mn_broadcast_msg(self, mn_protocol_version: int,
                                ping_block_hash: bytes,
                                rpc_node_protocol_version: int,
                                masternode: MasternodeConfig,
                                sig_time: int = None) \
            -> dash_utils.CMasternodeBroadcast:

        if not sig_time:
            sig_time = int(time.time())
        mn_privkey = dash_utils.wif_to_privkey(masternode.privateKey, self.config.dash_network)
        if not mn_privkey:
            raise Exception(f'Invalid masternode private key (masternode: {masternode.name})')
        mn_pubkey = bitcoin.privkey_to_pubkey(masternode.privateKey)
        mn_pubkey = bytes.fromhex(mn_pubkey)

        addr_pubkey = hw_intf.get_address_and_pubkey(self.hw_session, masternode.collateralBip32Path)
        collateral_pubkey = addr_pubkey.get('publicKey')

        mn_broadcast = dash_utils.CMasternodeBroadcast(
            masternode.ip,
            masternode.port,
            collateral_pubkey,
            mn_pubkey,
            bytes.fromhex(masternode.collateralTx),
            int(masternode.collateralTxIndex),
            ping_block_hash,
            sig_time,
            mn_protocol_version,
            rpc_node_protocol_version,
            spork6_active=self.get_spork_state_from_config(6, self.config.dash_network, False)
        )

        signature = mn_broadcast.sign(masternode.collateralBip32Path, hw_intf.hw_sign_message, self.hw_session,
                                      masternode.privateKey, self.config.dash_network)
        if signature.address != masternode.collateralAddress.strip():
            raise Exception('%s address signature mismatch.' % self.getHwName())

        return mn_broadcast

    @pyqtSlot(bool)
    def on_btnBroadcastMn_clicked(self):
        """
        Broadcasts information about configured Masternode within Dash network using Hwrdware Wallet for signing message
        and a Dash daemon for relaying message.
        Building broadcast message is based on work of chaeplin (https://github.com/chaeplin/dashmnb)
        """
        if self.curMasternode:
            if not self.curMasternode.collateralTx:
                self.errorMsg("Collateral transaction id not set.")
                return
            try:
                int(self.curMasternode.collateralTx, 16)
            except ValueError:
                self.errorMsg('Invalid collateral transaction id (should be hexadecimal string).')
                return

            if not re.match('\d{1,4}', self.curMasternode.collateralTxIndex):
                self.errorMsg("Invalid collateral transaction index.")
                return

            if not re.match('\d{1,4}', self.curMasternode.port):
                self.errorMsg("Invalid masternode's TCP port number.")
                return

            if not re.match('\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', self.curMasternode.ip):
                self.errorMsg("Invalid masternode's IP address.")
                return

            if not self.curMasternode.privateKey:
                self.errorMsg("Masternode's private key not set.")
                return
        else:
            self.errorMsg("No masternode selected.")
            return

        self.checkDashdConnection(wait_for_check_finish=True)
        if not self.dashd_connection_ok:
            self.errorMsg("Connection to Dash daemon is not established.")
            return
        if self.is_dashd_syncing:
            self.warnMsg("The Dash daemon you are connected to is currently synchronizing. You need wait "
                         "until it's finished.")
            return

        mn_status, _ = self.get_masternode_status(self.curMasternode)
        if mn_status in ('ENABLED', 'PRE_ENABLED'):
            if self.queryDlg("Warning: masternode state is %s. \n\nDo you really want to sent 'Start masternode' "
                             "message? " % mn_status, default_button=QMessageBox.Cancel,
                             icon=QMessageBox.Warning) == QMessageBox.Cancel:
                return

        try:
            mn_privkey = dash_utils.wif_to_privkey(self.curMasternode.privateKey, self.config.dash_network)
            if not mn_privkey:
                self.errorMsg('Invalid masternode private key')
                return

            self.connect_hardware_wallet()
            if not self.hw_client:
                return

            block_count = self.dashd_intf.getblockcount()
            block_count_for_mn_ping = block_count - 12
            block_hash_for_mn_ping = bytes.fromhex(self.dashd_intf.getblockhash(block_count_for_mn_ping))
            addr = hw_intf.get_address_and_pubkey(self.hw_session, self.curMasternode.collateralBip32Path)
            hw_collateral_address = addr.get('address').strip()
            cfg_collateral_address = self.curMasternode.collateralAddress.strip()

            if not cfg_collateral_address:
                # if mn config's collateral address is empty, assign that from hardware wallet
                self.curMasternode.collateralAddress = hw_collateral_address
                self.wdg_masternode.masternode_data_to_ui()
                self.update_edit_controls_state()
            elif hw_collateral_address != cfg_collateral_address:
                # verify config's collateral addres with hardware wallet
                if self.queryDlg(message="The Dash address retrieved from the hardware wallet (%s) for the configured "
                                         "BIP32 path does not match the collateral address entered in the "
                                         "configuration: %s.\n\n"
                                         "Do you really want to continue?" %
                        (hw_collateral_address, cfg_collateral_address),
                        default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                    return

            # check if there is 1000 Dash collateral
            msg_verification_problem = 'You can continue without verification step if you are sure, that ' \
                                       'TX hash/index are correct.'
            try:
                utxos = self.dashd_intf.getaddressutxos([hw_collateral_address])
                found = False
                utxo = []
                for utxo in utxos:
                    if utxo['txid'] == self.curMasternode.collateralTx and \
                       str(utxo['outputIndex']) == self.curMasternode.collateralTxIndex:
                        found = True
                        break
                if found:
                    if utxo.get('satoshis', None) != 100000000000:
                        if self.queryDlg(
                                message="Collateral transaction output should equal 100000000000 Satoshis (1000 Dash)"
                                        ", but its value is: %d Satoshis.\n\nDo you really want to continue?"
                                        % (utxo['satoshis']),
                                buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                            return
                else:
                    if self.queryDlg(
                            message="Could not find the specified transaction id/index for the collateral address: %s."
                                    "\n\nDo you really want to continue?"
                                    % hw_collateral_address,
                            buttons=QMessageBox.Yes | QMessageBox.Cancel,
                            default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                        return

            except DashdIndexException as e:
                # likely indexing not enabled
                if self.queryDlg(
                        message="Collateral transaction verification problem: %s."
                                "\n\n%s\nContinue?" % (str(e), msg_verification_problem),
                        buttons=QMessageBox.Yes | QMessageBox.Cancel,
                        default_button=QMessageBox.Yes, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                    return

            except Exception as e:
                if self.queryDlg(
                        message="Collateral transaction verification error: %s."
                                "\n\n%s\nContinue?" % (str(e), msg_verification_problem),
                        buttons=QMessageBox.Yes | QMessageBox.Cancel,
                        default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                    return

            sig_time = int(time.time())

            info = self.dashd_intf.getinfo(verify_node=True)
            rpc_node_protocol_version = int(info['protocolversion'])
            if self.curMasternode.use_default_protocol_version or not self.curMasternode.protocol_version:
                mn_protocol_version = self.get_default_protocol()
                if not mn_protocol_version:
                    mn_protocol_version = rpc_node_protocol_version
            else:
                try:
                    mn_protocol_version = int(self.curMasternode.protocol_version)
                except Exception:
                    self.errorMsg('Invalid protocol version for this masternode. Should be integer.')
                    return

            # create a masternode broadcast message
            mn_broadcast = self.create_mn_broadcast_msg(mn_protocol_version, block_hash_for_mn_ping,
                                                        rpc_node_protocol_version, self.curMasternode,
                                                        sig_time)
            broadcast_msg = '01' + mn_broadcast.serialize()
            logging.info('MNB broadcast message: ' + broadcast_msg)
            logging.info(f'MNB Ping block count: {block_count_for_mn_ping}')
            logging.info(f'MNB Ping block hash: {block_hash_for_mn_ping.hex()}')
            logging.info(f'MNB sigTime: {sig_time}')
            logging.info(f'MNB sigTime datestr: {str(datetime.datetime.fromtimestamp(sig_time))}')
            logging.info(f'{str(mn_broadcast)}')


            ret = self.dashd_intf.masternodebroadcast("decode", broadcast_msg)
            if ret['overall'].startswith('Successfully decoded broadcast messages for 1 masternodes'):
                dashd_version = {70208: 'v0.12.2',
                                 70209: 'v0.12.3',
                                 70210: 'v0.12.3',
                                 70213: 'v0.13.0'}.get(mn_protocol_version, '')
                if dashd_version:
                    dashd_version = f', dashd {dashd_version}'

                if self.queryDlg(f'Press "Yes" if you want to broadcast start masternode message (protocol version: '
                                 f'{mn_protocol_version}{dashd_version}) or "Cancel" to exit.',
                                buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Cancel:
                    return

                ret = self.dashd_intf.masternodebroadcast("relay", broadcast_msg)

                match = re.search("relayed broadcast messages for (\d+) masternodes.*failed to relay (\d+), total 1",
                                  ret['overall'])

                failed_count = 0
                if match and len(match.groups()):
                    failed_count = int(match.group(2))

                overall = ret['overall']
                errorMessage = ''

                if failed_count:
                    del ret['overall']
                    keys = list(ret.keys())
                    if len(keys):
                        # get the first (and currently the only one) error message
                        errorMessage = ret[keys[0]].get('errorMessage')

                if failed_count == 0:
                    self.infoMsg(overall)
                else:
                    self.errorMsg('Failed to start masternode.\n\nResponse from Dash daemon: %s.' % errorMessage)
            else:
                logging.error('Start MN error: ' + str(ret))
                errorMessage = ret[list(ret.keys())[0]].get('errorMessage')
                self.errorMsg(errorMessage)

        except HardwareWalletCancelException:
            if self.hw_client:
                self.hw_client.init_device()

        except AssertionError:
            logging.exception('Exception occurred.')
            self.errorMsg('Assertion error.')

        except Exception as e:
            logging.exception('Exception occurred.')
            self.errorMsg(str(e))

    def get_masternode_status(self, masternode):
        """
        Returns tuple: the current masternode status (ENABLED, PRE_ENABLED, WATCHDOG_EXPIRED, ...)
        and a protocol version.
        :return:
        """
        if self.dashd_connection_ok:
            collateral_id = masternode.collateralTx + '-' + masternode.collateralTxIndex
            mns_info = self.dashd_intf.get_masternodelist('full', collateral_id)
            if len(mns_info):
                protocol_version = mns_info[0].protocol
                if isinstance(protocol_version, str):
                    try:
                        protocol_version = int(protocol_version)
                    except:
                        logging.warning('Invalid masternode protocol version: ' + str(protocol_version))
                return (mns_info[0].status, protocol_version)
        return '???', None

    def get_deterministic_status(self, masternode: MasternodeConfig) -> Optional[Dict]:
        try:
            txes = self.dashd_intf.protx('list', 'registered', True)
            for protx in txes:
                state = protx.get('state')
                if (state and state.get('addr') == masternode.ip + ':' + masternode.port) or \
                        (protx.get('collateralHash') == masternode.collateralTx and
                         str(protx.get('collateralIndex')) == str(masternode.collateralTxIndex) ):
                    return protx
        except Exception as e:
            pass
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

            self.dashd_intf.get_masternodelist('full', data_max_age=30)  # read new data from the network
                                                                                    # every 30 seconds
            if collateral_id:
                mn_info = self.dashd_intf.masternodes_by_ident.get(collateral_id)
            else:
                mn_info = self.dashd_intf.masternodes_by_ip_port.get(ip_port)

            dmn_tx = self.get_deterministic_status(masternode)
            if dmn_tx:
                dmn_tx_state = dmn_tx.get('state')
            else:
                dmn_tx_state = {}

            if mn_info:
                mn_ident = mn_info.ident
                mn_ip_port = mn_info.ip
                mn_protocol = mn_info.protocol
                mn_queue_position = mn_info.queue_position
            else:
                mn_protocol = ''
                mn_queue_position = '?'
                if dmn_tx_state:
                    mn_ident = str(dmn_tx.get('collateralHash')) + '-' + str(dmn_tx.get('collateralIndex'))
                    mn_ip_port = dmn_tx_state.get('addr')
                else:
                    mn_ident = None
                    mn_ip_port = None

            if mn_info or dmn_tx:
                if mn_info:
                    if mn_info.lastseen > 0:
                        lastseen = datetime.datetime.fromtimestamp(float(mn_info.lastseen))
                        lastseen_str = app_utils.to_string(lastseen)
                        lastseen_ago = int(time.time()) - int(mn_info.lastseen)
                        if lastseen_ago >= 2:
                            lastseen_ago_str = app_utils.seconds_to_human(lastseen_ago, out_unit_auto_adjust = True) + \
                                               ' ago'
                        else:
                            lastseen_ago_str = 'a few seconds ago'
                    else:
                        lastseen_str = ''
                        lastseen_ago_str = ''

                    if mn_info.activeseconds:
                        activeseconds_str = app_utils.seconds_to_human(int(mn_info.activeseconds),
                                                                       out_unit_auto_adjust=True)
                    else:
                        activeseconds_str = ''

                    if mn_info.status == 'ENABLED' or mn_info.status == 'PRE_ENABLED':
                        status_color = 'green'
                    else:
                        status_color = 'red'
                    mn_status = mn_info.status
                else:
                    lastseen_str = ''
                    lastseen_ago_str = ''
                    s = dmn_tx_state.get('PoSePenalty', 0)
                    if s:
                        mn_status = 'PoSeBan (' + str(s) + ')'
                        status_color = 'red'
                    else:
                        mn_status = 'ENABLED'
                        status_color = 'green'
                    activeseconds_str = '?'

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
                        lastpaid_ago_str = app_utils.seconds_to_human(lastpaid_ago, out_unit_auto_adjust=True) + ' ago'
                    else:
                        lastpaid_ago_str = 'a few seconds ago'
                else:
                    lastpaid_str = ''
                    lastpaid_ago_str = ''

                enabled_mns_count = len(self.dashd_intf.payment_queue)

                update_mn_info = False
                collateral_address_mismatch = False
                collateral_tx_mismatch = False
                ip_port_mismatch = False
                mn_data_modified = False
                owner_pubkey_hash_mismatch = False
                operator_pubkey_mismatch = False
                voting_pubkey_hash_mismatch = False

                if masternode not in self.mns_user_refused_updating:
                    if not masternode.collateralTx or not masternode.collateralTxIndex or \
                            not masternode.collateralAddress:
                        msg = 'In the configuration of your masternode some information is missing that is ' \
                              'available on the network. Do you want to update the configuration?'

                        if self.queryDlg(msg, buttons=QMessageBox.Yes | QMessageBox.No,
                                         default_button=QMessageBox.Yes,
                                         icon=QMessageBox.Warning) == QMessageBox.Yes:
                            update_mn_info = True
                        else:
                            self.mns_user_refused_updating[masternode] = self.curMasternode

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
                    # check outputs of the collateral transaction
                    tx_json = self.dashd_intf.getrawtransaction(masternode.collateralTx, 1)
                    if tx_json:
                        vout = tx_json.get('vout')
                        if vout and int(masternode.collateralTxIndex) < len(vout):
                            v = vout[ int(masternode.collateralTxIndex)]
                            if v and v.get('scriptPubKey'):
                                addrs = v.get('scriptPubKey').get('addresses')
                                if addrs:
                                    addr = addrs[0]
                                    if masternode.collateralAddress != addr:
                                        if update_mn_info:
                                            masternode.collateralAddress = addr
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
                    if not masternode.is_deterministic:
                        if update_mn_info:
                            masternode.dmn_tx_hash = dmn_tx.get('proTxHash')
                            self.wdg_masternode.set_deterministic(True)
                            mn_data_modified = True
                    else:
                        dmn_hash = dmn_tx.get('proTxHash')
                        if dmn_hash and masternode.dmn_tx_hash != dmn_hash:
                            if update_mn_info:
                                masternode.dmn_tx_hash = dmn_tx.get('proTxHash')
                                mn_data_modified = True

                    if dmn_tx_state:
                        owner_pubkey_network = dmn_tx_state.get('keyIDOwner')
                        owner_pubkey_cfg = masternode.dmn_owner_pubkey_hash
                        if owner_pubkey_network and owner_pubkey_cfg and owner_pubkey_network != owner_pubkey_cfg:
                            owner_pubkey_hash_mismatch = True
                            logging.warning(
                                f'Owner public key hash mismatch for masternode: {masternode.name}, '
                                f'Config pubkey hash: {owner_pubkey_cfg}, network pubkey hash: {owner_pubkey_network}')

                        voting_pubkey_network = dmn_tx_state.get('keyIDVoting')
                        voting_pubkey_cfg = masternode.dmn_voting_pubkey_hash
                        if voting_pubkey_network and voting_pubkey_cfg and voting_pubkey_network != voting_pubkey_cfg:
                            voting_pubkey_hash_mismatch = True
                            logging.warning(
                                f'Voting public key hash mismatch for masternode: {masternode.name}. '
                                f'Config pubkey hash: {voting_pubkey_cfg}, network pubkey hash: {voting_pubkey_network}')

                        operator_pubkey_network = dmn_tx_state.get('pubKeyOperator')
                        operator_pubkey_cfg = masternode.dmn_operator_pubkey
                        if operator_pubkey_network and operator_pubkey_cfg and operator_pubkey_network != operator_pubkey_cfg:
                            operator_pubkey_mismatch = True
                            logging.warning(
                                f'Operator public key mismatch for masternode: {masternode.name}. '
                                f'Config pubkey: {operator_pubkey_cfg}, network pubkey: {operator_pubkey_network}')

                if mn_data_modified:
                    def update():
                        self.wdg_masternode.masternode_data_to_ui()
                        self.wdg_masternode.set_modified()
                    if not self.finishing:
                        self.call_in_main_thread(update)

                if masternode == self.curMasternode:
                    # get balance
                    addr = masternode.collateralAddress.strip()
                    bal_entry = ''
                    if addr:
                        try:
                            bal = self.dashd_intf.getaddressbalance([addr])
                            if bal:
                                bal = round(bal.get('balance') / 1e8, 5)
                                bal_entry = f'<tr><td class="title">Balance:</td><td class="value">' \
                                            f'{app_utils.to_string(bal)}</td><td></td></tr>'
                        except Exception:
                            pass

                    errors = []
                    if collateral_address_mismatch:
                        errors.append('<td class="error" colspan="2">Collateral address missing/mismatch</td>')
                    if collateral_tx_mismatch:
                        errors.append('<td class="error" colspan="2">Collateral TX hash and/or index missing/mismatch</td>')
                    if ip_port_mismatch:
                        errors.append('<td class="error" colspan="2">Masternode IP and/or port number missing/mismatch</td>')
                    if owner_pubkey_hash_mismatch:
                        errors.append('<td class="error" colspan="2">Owner public key mismatch</td>')
                    if operator_pubkey_mismatch:
                        errors.append('<td class="error" colspan="2">Operator public key mismatch</td>')
                    if voting_pubkey_hash_mismatch:
                        errors.append('<td class="error" colspan="2">Voting public key mismatch</td>')

                    errors_msg = ''
                    if errors:
                        for idx, e in enumerate(errors):
                            if idx == 0:
                                errors_msg += '<tr><td class="title">Errors:</td>'
                            else:
                                errors_msg += '<tr><td></td>'
                            errors_msg += e + '</tr>'

                    status = '<style>td {white-space:nowrap;padding-right:8px}' \
                             '.title {text-align:right;font-weight:bold}' \
                             '.ago {font-style:normal}' \
                             '.value {color:navy}' \
                             '.error {color:red}' \
                             '</style>' \
                             '<table>' \
                             f'<tr><td class="title">Status:</td><td class="value"><span style="color:{status_color}">{mn_status}</span>' \
                             f'</td><td>{"v" + str(mn_protocol) if mn_protocol else ""}</td></tr>' \
                             f'<tr><td class="title">Last Seen:</td><td class="value">{lastseen_str}</td><td class="ago">{lastseen_ago_str}</td></tr>' \
                             f'<tr><td class="title">Last Paid:</td><td class="value">{lastpaid_str}</td><td class="ago">{lastpaid_ago_str}</td></tr>' \
                             f'{bal_entry}' \
                             f'<tr><td class="title">Active Duration:</td><td class="value" colspan="2">{activeseconds_str}</td></tr>' \
                             f'<tr><td class="title">Queue/Count:</td><td class="value" colspan="2">{str(mn_queue_position)}/{enabled_mns_count}</td></tr>' \
                             + errors_msg + '</table>'
                else:
                    status = '<span style="color:red">Masternode not found.</span>'
            else:
                status = '<span style="color:red">Masternode not found.</span>'
        else:
            status = '<span style="color:red">Problem with connection to dashd.</span>'

        if not self.finishing:
            if masternode != self.curMasternode:
                status = ''

            self.call_in_main_thread(self.lblMnStatus.setText, status)

    @pyqtSlot(bool)
    def on_btnRefreshMnStatus_clicked(self):
        def enable_buttons():
            self.btnRefreshMnStatus.setEnabled(True)
            self.btnBroadcastMn.setEnabled(True)
            self.btnMigrateToDMN.setEnabled(True)

        self.lblMnStatus.setText('<b>Retrieving masternode information, please wait...<b>')
        self.btnRefreshMnStatus.setEnabled(False)
        self.btnBroadcastMn.setEnabled(False)
        self.btnMigrateToDMN.setEnabled(False)

        self.checkDashdConnection(wait_for_check_finish=True)
        if self.dashd_connection_ok:
            try:
                self.run_thread(self, self.get_masternode_status_description_thread, (self.curMasternode,),
                                on_thread_finish=enable_buttons)
            except:
                self.lblMnStatus.setText('')
                raise
        else:
            enable_buttons()
            self.errorMsg('Dash daemon not connected')

    @pyqtSlot(bool)
    def on_action_transfer_funds_for_cur_mn_triggered(self):
        """
        Shows tranfser funds window with utxos related to current masternode. 
        """
        if self.curMasternode:
            src_addresses = []
            if not self.curMasternode.collateralBip32Path:
                self.errorMsg("Enter the masternode collateral BIP32 path. You can use the 'right arrow' button "
                              "on the right of the 'Collateral' edit box.")
            elif not self.curMasternode.collateralAddress:
                self.errorMsg("Enter the masternode collateral Dash address. You can use the 'left arrow' "
                              "button on the left of the 'BIP32 path' edit box.")
            else:
                src_addresses.append((self.curMasternode.collateralAddress, self.curMasternode.collateralBip32Path))
                mn_index = self.config.masternodes.index(self.curMasternode)
                self.show_wallet_window(mn_index)
        else:
            self.errorMsg('No masternode selected')

    @pyqtSlot(bool)
    def on_action_transfer_funds_for_all_mns_triggered(self):
        """
        Shows tranfser funds window with utxos related to all masternodes. 
        """
        self.show_wallet_window(-1)

    @pyqtSlot(bool)
    def on_action_transfer_funds_for_any_address_triggered(self):
        """
        Shows tranfser funds window for address/path specified by the user.
        """
        self.show_wallet_window(None)

    def show_wallet_window(self, initial_mn: Optional[int]):
        """ Shows the wallet/send payments dialog.
        :param initial_mn:
          if the value is from 0 to len(masternodes), show utxos for the masternode
            having the 'initial_mn' index in self.config.mastrnodes
          if the value is -1, show utxo for all masternodes
          if the value is None, show the default utxo source type
        """
        if not self.dashd_intf.open():
            self.errorMsg('Dash daemon not connected')
        else:
            ui = wallet_dlg.WalletDlg(self, initial_mn_sel=initial_mn)
            ui.exec_()

    @pyqtSlot(bool)
    def on_action_sign_message_for_cur_mn_triggered(self):
        if self.curMasternode:
            self.connect_hardware_wallet()
            if self.hw_client:
                if not self.curMasternode.collateralBip32Path:
                    self.errorMsg("Empty masternode's collateral BIP32 path")
                else:
                    ui = SignMessageDlg(self, self.curMasternode.collateralBip32Path,
                                        self.curMasternode.collateralAddress)
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
    def on_btnMigrateToDMN_clicked(self, enabled):
        reg_dlg = None
        def on_proregtx_finished(masternode: MasternodeConfig):
            nonlocal reg_dlg
            try:
                if self.curMasternode.dmn_tx_hash != reg_dlg.dmn_reg_tx_hash or \
                        self.curMasternode.dmn_owner_private_key != reg_dlg.dmn_owner_privkey or \
                        self.curMasternode.dmn_operator_private_key != reg_dlg.dmn_operator_privkey or \
                        self.curMasternode.dmn_voting_private_key != reg_dlg.dmn_voting_privkey or \
                        not self.curMasternode.is_deterministic:

                    self.curMasternode.dmn_tx_hash = reg_dlg.dmn_reg_tx_hash
                    self.curMasternode.dmn_owner_private_key = reg_dlg.dmn_owner_privkey
                    self.curMasternode.dmn_operator_private_key = reg_dlg.dmn_operator_privkey
                    self.curMasternode.dmn_voting_private_key = reg_dlg.dmn_voting_privkey
                    self.curMasternode.is_deterministic = True

                    if self.curMasternode == masternode:
                        self.wdg_masternode.masternode_data_to_ui()
                    if self.config.is_modified():
                        self.wdg_masternode.set_modified()
                    else:
                        self.save_configuration()
            except Exception as e:
                logging.exception(str(e))

        if self.curMasternode:
            reg_dlg = reg_masternode_dlg.RegMasternodeDlg(self, self.app_config, self.dashd_intf, self.curMasternode,
                                                     on_proregtx_success_callback=on_proregtx_finished)
            reg_dlg.exec_()
        else:
            WndUtils.errorMsg('No masternode selected')

