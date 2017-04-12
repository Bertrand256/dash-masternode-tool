#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03


import base64
import binascii
import datetime
import json
import os
import platform
import re
import sys
import threading
import time
import bitcoin
import logging
from PyQt5 import QtCore
from PyQt5 import QtWidgets
from PyQt5.QtCore import QSize, pyqtSlot, QEventLoop, QMutex, QWaitCondition
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QFileDialog, QMenu, QMainWindow, QPushButton, QStyle
from PyQt5.QtWidgets import QMessageBox
from config_dlg import ConfigDlg
from find_coll_tx_dlg import FindCollateralTxDlg
from src import about_dlg
from src import app_cache as cache
from src import dash_utils
from src import hw_pass_dlg
from src import hw_pin_dlg
from src import send_payout_dlg
from src.app_config import AppConfig, MasterNodeConfig, APP_NAME_LONG, APP_NAME_SHORT
from src.dash_utils import bip32_path_n_to_string
from src.dashd_intf import DashdInterface, DashdIndexException
from src.hw_common import HardwareWalletCancelException, HardwareWalletPinException
from src.hw_intf import connect_hw, hw_get_address, disconnect_hw
from src.hw_setup_dlg import HwSetupDlg
from src.sign_message_dlg import SignMessageDlg
from src.wnd_utils import WndUtils
from ui import ui_main_dlg


PROJECT_URL = 'https://github.com/Bertrand256/dash-masternode-tool'


class MainWindow(QMainWindow, WndUtils, ui_main_dlg.Ui_MainWindow):
    update_status_signal = QtCore.pyqtSignal(str, str)  # signal for updating status text from inside thread

    def __init__(self, app_path):
        QMainWindow.__init__(self)
        WndUtils.__init__(self, app_path=app_path)
        ui_main_dlg.Ui_MainWindow.__init__(self)
        self.config = AppConfig(app_path)
        self.config.read_from_file()
        self.dashd_intf = DashdInterface(self.config, window=None,
                                         on_connection_begin_callback=self.on_connection_begin,
                                         on_connection_try_fail_callback=self.on_connection_failed,
                                         on_connection_finished_callback=self.on_connection_finished)
        self.dashd_info = {}
        self.is_dashd_syncing = False
        self.dashd_connection_ok = False
        self.hw_client = None
        self.curMasternode = None
        self.editingEnabled = False
        self.app_path = app_path
        self.version_str = ''

        # bip32 cache:
        #   { "dash_address_of_the_parent": { bip32_path: dash_address }
        self.bip32_cache = { }
        try:
            with open(os.path.join(app_path, 'version.txt')) as fptr:
                lines = fptr.read().splitlines()
                self.version_str = self.extractAppVersion(lines)
        except:
            pass
        self.setupUi()

    def setupUi(self):
        ui_main_dlg.Ui_MainWindow.setupUi(self, self)
        self.setWindowTitle(APP_NAME_LONG + ' by Bertrand256' + (
            ' (v. ' + self.version_str + ')' if self.version_str else ''))

        self.inside_setup_ui = True
        self.dashd_intf.window = self
        self.btnHwBip32ToAddress.setEnabled(False)
        self.edtMnStatus.setReadOnly(True)
        self.edtMnStatus.setStyleSheet('QLineEdit{background-color: lightgray}')
        self.closeEvent = self.closeEvent
        self.lblStatus1 = QtWidgets.QLabel(self)
        self.lblStatus1.setAutoFillBackground(False)
        self.lblStatus1.setOpenExternalLinks(True)
        self.statusBar.addPermanentWidget(self.lblStatus1, 1)
        self.lblStatus1.setText('')
        self.lblStatus2 = QtWidgets.QLabel(self)
        self.statusBar.addPermanentWidget(self.lblStatus2, 2)
        self.lblStatus2.setText('')
        img = QPixmap(os.path.join(self.app_path, "img/dmt.png"))
        img = img.scaled(QSize(64, 64))
        self.lblAbout.setPixmap(img)
        self.setStatus1Text('<b>RPC network status:</b> not connected', 'black')
        self.setStatus2Text('<b>HW status:</b> idle', 'black')

        if sys.platform == 'win32':
            # improve buttons' ugly look on windows
            styleSheet = """QPushButton {padding: 3px 10px 3px 10px}"""
            btns = self.groupBox.findChildren(QPushButton)
            for btn in btns:
                btn.setStyleSheet(styleSheet)

        # set stylesheet for editboxes, supporting different colors for read-only and edting mode
        styleSheet = """
          QLineEdit{background-color: white}
          QLineEdit:read-only{background-color: lightgray}
        """
        self.setStyleSheet(styleSheet)

        self.setIcon(self.btnHwCheck, 'hw-test.ico')
        self.setIcon(self.btnHwDisconnect, "hw-lock.ico")
        self.setIcon(self.btnHwAddressToBip32, QStyle.SP_ArrowRight)
        self.setIcon(self.btnHwBip32ToAddress, QStyle.SP_ArrowLeft)
        self.setIcon(self.btnConfiguration, "gear.png")
        self.setIcon(self.btnActions, "tools.png")
        self.setIcon(self.btnCheckConnection, QStyle.SP_CommandLink)
        self.setIcon(self.btnSaveConfiguration, QStyle.SP_DriveFDIcon)
        self.setIcon(self.btnAbout, QStyle.SP_MessageBoxInformation)

        # create popup menu for actions button
        mnu = QMenu()

        # transfer for current mn
        self.actTransferFundsSelectedMn = mnu.addAction("Transfer funds from current Masternode's address...")
        self.setIcon(self.actTransferFundsSelectedMn, "dollar.png")
        self.actTransferFundsSelectedMn.triggered.connect(self.on_actTransferFundsSelectedMn_triggered)

        # transfer for all mns
        self.actTransferFundsForAllMns = mnu.addAction("Transfer funds from all Masternodes addresses...")
        self.setIcon(self.actTransferFundsForAllMns, "money-bag.png")
        self.actTransferFundsForAllMns.triggered.connect(self.on_actTransferFundsForAllMns_triggered)

        # sign message with HW
        self.actSignMessageWithHw = mnu.addAction("Sign message with HW for current Masternode's address...")
        self.setIcon(self.actSignMessageWithHw, "sign.png")
        self.actSignMessageWithHw.triggered.connect(self.on_actSignMessageWithHw_triggered)

        # hardware wallet setup tools
        self.actHwSetup = mnu.addAction("Hardware Wallet PIN/Passphrase configuration...")
        self.setIcon(self.actHwSetup, "hw.png")
        self.actHwSetup.triggered.connect(self.on_actHwSetup_triggered)

        # check for updates
        self.actCheckForUpdates = mnu.addAction("Check for updates")
        self.actCheckForUpdates.triggered.connect(self.on_actCheckForUpdates_triggered)
        self.btnActions.setMenu(mnu)

        # add masternodes to the combobox
        self.cboMasternodes.clear()
        for mn in self.config.masternodes:
            self.cboMasternodes.addItem(mn.name, mn)
        if not self.config.masternodes:
            self.newMasternodeConfig()
        else:
            # get last masternode selected
            idx = cache.get_value('WndMainCurMasternodeIndex', 0, int)
            if idx >= len(self.config.masternodes):
                idx = 0
            self.curMasternode = self.config.masternodes[idx]
            self.displayMasternodeConfig(True)

        # after loading whole configuration, reset 'modified' variable
        self.config.modified = False
        self.updateControlsState()
        self.setMessage("", None)

        self.on_actCheckForUpdates_triggered(force_check=False)

        self.inside_setup_ui = False
        logging.info('Finished setup of the main dialog.')

    @staticmethod
    def extractAppVersion(lines):
        """
        Extracts version string from array of files (content of version.txt file)
        :param lines:
        :return: version string
        """
        for line in lines:
            parts = [elem.strip() for elem in line.split('=')]
            if len(parts) == 2 and parts[0].lower() == 'version_str':
                return parts[1].strip("'")
        return ''

    @staticmethod
    def versionStrToNumber(version_str):
        elems = version_str.split('.')
        version_nr_str = ''.join([n.zfill(4) for n in elems])
        version_nr = int(version_nr_str)
        return version_nr

    @pyqtSlot()
    def on_actCheckForUpdates_triggered(self, force_check=True):
        if self.config.check_for_updates:
            cur_date = datetime.datetime.now().strftime('%Y-%m-%d')
            last_ver_check_date = cache.get_value('check_for_updates_last_date', '', str)
            if force_check or cur_date != last_ver_check_date:
                self.runInThread(self.checkForUpdates, (cur_date, force_check))

    def checkForUpdates(self, ctrl, cur_date_str, force_check):
        """
        Thread function, checking on GitHub if there is a new version of the application.
        :param ctrl: thread control structure (not used here) 
        :param cur_date_str: Current date string - it will be saved in the cache file as the date of the 
            last-version-check date.
        :param force_check: True if version-check has been invoked by the user, not the app itself.
        :return: None
        """
        try:
            import urllib.request
            response = urllib.request.urlopen(
                'https://raw.githubusercontent.com/Bertrand256/dash-masternode-tool/master/version.txt')
            contents = response.read()
            lines = contents.decode().splitlines()
            remote_version_str = self.extractAppVersion(lines)
            remote_ver = self.versionStrToNumber(remote_version_str)
            local_ver = self.versionStrToNumber(self.version_str)
            cache.set_value('check_for_updates_last_date', cur_date_str)

            if remote_ver > local_ver:
                if sys.platform == 'win32':
                    item_name = 'exe_win'
                    no_bits = platform.architecture()[0].replace('bit', '')
                    if no_bits == '32':
                        item_name += '32'
                elif sys.platform == 'darwin':
                    item_name = 'exe_mac'
                else:
                    item_name = 'exe_linux'
                exe_url = ''
                for line in lines:
                    elems = [x.strip() for x in line.split('=')]
                    if len(elems) == 2 and elems[0] == item_name:
                        exe_url = elems[1].strip("'")
                        break
                if exe_url:
                    msg = "New version (" + remote_version_str + ') available: <a href="' + exe_url + '">download</a>.'
                else:
                    msg = "New version (" + remote_version_str + ') available. Go to the project website: <a href="' + PROJECT_URL + '">open</a>.'

                self.setMessage(msg, 'green')
            else:
                if force_check:
                    self.setMessage("You have the latest version of %s." % APP_NAME_SHORT, 'green')
        except Exception as e:
            pass

    def closeEvent(self, event):
        if self.dashd_intf:
            self.dashd_intf.disconnect()

        if self.configModified():
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setText('Do you want to save configuration before exit?')
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.Yes)
            retval = msg.exec_()
            if retval == QMessageBox.Yes:
                self.on_btnSaveConfiguration_clicked()

    def displayMasternodeConfig(self, set_mn_list_index):
        if self.curMasternode and set_mn_list_index:
            self.cboMasternodes.setCurrentIndex(self.config.masternodes.index(self.curMasternode))
        try:
            if self.curMasternode:
                self.curMasternode.lock_modified_change = True
            self.edtMnName.setText(self.curMasternode.name if self.curMasternode else '')
            self.edtMnIp.setText(self.curMasternode.ip if self.curMasternode else '')
            self.edtMnPort.setText(str(self.curMasternode.port) if self.curMasternode else '')
            self.edtMnPrivateKey.setText(self.curMasternode.privateKey if self.curMasternode else '')
            self.edtMnCollateralBip32Path.setText(self.curMasternode.collateralBip32Path
                                                  if self.curMasternode else '')
            self.edtMnCollateralAddress.setText(self.curMasternode.collateralAddress if self.curMasternode else '')
            self.edtMnCollateralTx.setText(self.curMasternode.collateralTx if self.curMasternode else '')
            self.edtMnCollateralTxIndex.setText(self.curMasternode.collateralTxIndex if self.curMasternode else '')
            self.edtMnStatus.setText('')
        finally:
            if self.curMasternode:
                self.curMasternode.lock_modified_change = False

    @pyqtSlot(bool)
    def on_btnConfiguration_clicked(self):
        dlg = ConfigDlg(self, self.config)
        dlg.exec_()
        del dlg

    def connsCfgChanged(self):
        """
        If connections config is changed, we must apply the changes to the dashd interface object
        :return: 
        """
        try:
            self.dashd_intf.apply_new_cfg()
            self.updateControlsState()
        except Exception as e:
            self.errorMsg(str(e))

    @pyqtSlot(bool)
    def on_btnAbout_clicked(self):
        ui = about_dlg.AboutDlg(self, self.app_path, self.version_str)
        ui.exec_()

    def on_connection_begin(self):
        """
        Called just before establising connection to a dash RPC.
        """
        self.setStatus1Text('<b>RPC network status:</b> trying %s...' % self.dashd_intf.get_active_conn_description(), 'black')

    def on_connection_failed(self):
        """
        Called after failed connection attempt. There can be more attempts to connect to another nodes if there are 
        such in configuration. 
        """
        self.setStatus1Text('<b>RPC network status:</b> failed connection to %s' % self.dashd_intf.get_active_conn_description(), 'red')

    def on_connection_finished(self):
        """
        Called after connection to dash daemon sucessufully establishes.
        """
        self.setStatus1Text('<b>RPC network status:</b> OK (%s)' % self.dashd_intf.get_active_conn_description(), 'green')

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
                mtx.lock()
                while not ctrl.finish:
                    synced = self.dashd_intf.issynchronized()
                    if synced:
                        self.is_dashd_syncing = False
                        self.on_connection_finished()
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
                self.dashd_info = self.dashd_intf.getinfo()
                self.dashd_connection_ok = True
                if not synced:
                    if not self.is_dashd_syncing and not (hasattr(self, 'wait_for_dashd_synced_thread') and
                                                                  self.wait_for_dashd_synced_thread is not None):
                        self.is_dashd_syncing = True
                        self.wait_for_dashd_synced_thread = self.runInThread(wait_for_synch_finished_thread, (),
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
                self.setMessage(err,
                                style='{background-color:red;color:white;padding:3px 5px 3px 5px; border-radius:3px}')

        def connect_finished():
            """
            Called after thread terminates.
            """
            del self.check_conn_thread
            self.check_conn_thread = None
            if call_on_check_finished:
                call_on_check_finished()
            if event_loop:
                event_loop.exit()

        if self.config.is_config_complete():
            if (not hasattr(self, 'check_conn_thread') or self.check_conn_thread is None):

                if hasattr(self, 'wait_for_dashd_synced_thread') and self.wait_for_dashd_synced_thread is not None:
                    if call_on_check_finished is not None:
                        # if a thread waiting for dashd to finish synchronizing is running, call the callback function
                        call_on_check_finished()
                else:
                    self.check_conn_thread = self.runInThread(connect_thread, (), on_thread_finish=connect_finished)
                    if wait_for_check_finish:
                        event_loop.exec()
        else:
            # configuration is not complete
            self.is_dashd_syncing = False
            self.dashd_connection_ok = False

    @pyqtSlot(bool)
    def on_btnCheckConnection_clicked(self):
        def connection_test_finished():
            if self.dashd_connection_ok:
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
            self.checkDashdConnection(call_on_check_finished=connection_test_finished)
        else:
            # configuration not complete: show config window
            if self.queryDlg("There is no (enabled) connections to RPC node in your configuration. Open configuration dialog?",
                             buttons=QMessageBox.Yes | QMessageBox.Cancel, default_button=QMessageBox.Yes,
                             icon=QMessageBox.Warning) == QMessageBox.Yes:
                self.on_btnConfiguration_clicked()

    @staticmethod
    def askForPinCallback(msg):
        def dlg():
            ui = hw_pin_dlg.HardwareWalletPinDlg(msg)
            if ui.exec_():
                return ui.pin
            else:
                return None

        if threading.current_thread() != threading.main_thread():
            return WndUtils.callFunInTheMainThread(dlg)
        else:
            return dlg()

    @staticmethod
    def askForPassCallback(msg):
        def dlg():
            ui = hw_pass_dlg.HardwareWalletPassDlg()
            if ui.exec_():
                return ui.getPassphrase()
            else:
                return None

        if threading.current_thread() != threading.main_thread():
            return WndUtils.callFunInTheMainThread(dlg)
        else:
            return dlg()


    def setStatus1Text(self, text, color):
        def set_status(text, color):
            self.lblStatus1.setText(text)
            if not color:
                color = 'black'
            self.lblStatus1.setStyleSheet('QLabel{color: ' + color + ';margin-right:20px;margin-left:8px}')

        if threading.current_thread() != threading.main_thread():
            self.callFunInTheMainThread(set_status, text, color)
        else:
            set_status(text, color)

    def setStatus2Text(self, text, color):
        def set_status(text, color):
            self.lblStatus2.setText(text)
            if not color:
                color = 'black'
            self.lblStatus2.setStyleSheet('QLabel{color: ' + color + '}')

        if threading.current_thread() != threading.main_thread():
            self.callFunInTheMainThread(set_status, text, color)
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
            self.callFunInTheMainThread(set_message, text, color, style)
        else:
            set_message(text, color, style)

    def getHwName(self):
        if self.config.hw_type == 'TREZOR':
            return 'Trezor'
        else:
            return 'KeepKey'

    def connectHardwareWallet(self):
        """
        Connects to hardware wallet if not connected before.
        :return: True, if successfully connected, False if not
        """
        if self.hw_client:
            t = type(self.hw_client).__name__
            cur_hw_type = ''
            if t.lower().find('trezor') >= 0:
                cur_hw_type = 'TREZOR'
            elif t.lower().find('keepkey') >= 0:
                cur_hw_type = 'KEEPKEY'
            if self.config.hw_type != cur_hw_type:
                self.on_btnHwDisconnect_clicked()

        if not self.hw_client:
            try:
                if sys.platform == 'linux':
                    if (self.config.hw_type == 'TREZOR' and 'keepkeylib' in sys.modules.keys()) or \
                       (self.config.hw_type == 'KEEPKEY' and 'trezorlib' in sys.modules.keys()):
                        self.warnMsg('On linux OS switching between hardware wallets requires reastarting the '
                                     'application.\n\nPlease restart the application to continue.')
                        return False

                logging.info('Connecting to hardware wallet device')
                self.hw_client = connect_hw(self.config.hw_type, self.askForPinCallback, self.askForPassCallback)
                if self.hw_client:
                    logging.info('Connected do hardware wallet')
                    self.setStatus2Text('<b>HW status:</b> connected to %s' % self.hw_client.features.label, 'green')
                    self.updateControlsState()
                    return True
                else:
                    logging.info('Could not connect do hardware wallet')
                    self.setStatus2Text('<b>HW status:</b> cannot find %s device' % self.getHwName(), 'red')
                    self.errorMsg('Cannot find %s device.' % self.getHwName())
            except HardwareWalletPinException as e:
                self.errorMsg(e.msg)
                if self.hw_client:
                    self.hw_client.clear_session()
                self.updateControlsState()
            except OSError as e:
                self.errorMsg('Cannot open %s device.' % self.getHwName())
                self.updateControlsState()
            except Exception as e:
                logging.exception('Exception occurred')
                self.errorMsg(str(e))
                if self.hw_client:
                    self.hw_client.init_device()
                self.updateControlsState()
            return False
        else:
            return True  # already connected

    def btnConnectTrezorClick(self):
        self.connectHardwareWallet()

    @pyqtSlot(bool)
    def on_btnHwCheck_clicked(self):
        self.connectHardwareWallet()
        self.updateControlsState()
        if self.hw_client:
            try:
                features = self.hw_client.features
                self.hw_client.ping('Hello, press the button', button_protection=False,
                                    pin_protection=features.pin_protection,
                                    passphrase_protection=features.passphrase_protection)
                self.infoMsg('Connection to %s device (%s) successful.' % (self.getHwName(), features.label))
            except HardwareWalletCancelException:
                if self.hw_client:
                    self.hw_client.init_device()

    @pyqtSlot(bool)
    def on_btnHwDisconnect_clicked(self):
        if self.hw_client:
            disconnect_hw(self.hw_client)
            del self.hw_client
            self.hw_client = None
            self.setStatus2Text('<b>HW status:</b> idle', 'black')
            self.updateControlsState()

    @pyqtSlot(bool)
    def on_btnNewMn_clicked(self):
        self.newMasternodeConfig()

    @pyqtSlot(bool)
    def on_btnDeleteMn_clicked(self):
        if self.curMasternode:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setText('Do you really want to delete current Masternode configuration?')
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            retval = msg.exec_()
            if retval == QMessageBox.No:
                return
            self.config.masternodes.remove(self.curMasternode)
            self.cboMasternodes.removeItem(self.cboMasternodes.currentIndex())
            self.config.modified = True
            self.updateControlsState()

    @pyqtSlot(bool)
    def on_btnEditMn_clicked(self):
        self.editingEnabled = True
        self.updateControlsState()

    def hwScanForBip32Paths(self, addresses):
        """
        Scans hardware wallet for bip32 paths of all Dash addresses passed in the addresses list.
        :param addresses: list of Dash addresses to scan
        :return: dict {dash_address: bip32_path}
        """
        def scan_for_bip32_thread(ctrl, addresses):
            """
            Function run inside a thread which purpose is to scan hawrware wallet
            for a bip32 paths with given Dash addresses.
            :param cfg: Thread dialog configuration object.
            :param addresses: list of Dash addresses to find bip32 path
            :return: 
            """

            paths_found = 0
            paths_checked = 0
            found_adresses = {}
            user_cancelled = False
            ctrl.dlg_config_fun(dlg_title="Scanning hardware wallet...", show_progress_bar=False)
            self.connectHardwareWallet()
            if self.hw_client:

                # get dash address of the parent
                address_n = [2147483692,  # 44'
                             2147483653,  # 5'
                            ]
                addr_of_cur_path = hw_get_address(self.hw_client, address_n)
                b32cache = self.bip32_cache.get(addr_of_cur_path, None)
                modified_b32cache = False
                cache_file = os.path.join(self.config.cache_dir, 'bip32cache_%s.json' % addr_of_cur_path)
                if not b32cache:
                    # entry for parrent address was not scanned since starting the app, find cache file on disk
                    try:  # looking into cache first
                        b32cache = json.load(open(cache_file))
                    except:
                        # cache file not found
                        b32cache = {}

                    # create in cache entry for tree beginning from our parent path (different hw passphrase
                    # gives different bip32 parent path)
                    self.bip32_cache[addr_of_cur_path] = b32cache

                for addr_to_find_bip32 in addresses:
                    if not found_adresses.get(addr_to_find_bip32):
                        # check 10 addresses of account 0 (44'/5'/0'/0), then 10 addreses
                        # of account 1 (44'/5'/1'/0) and so on until 9th account.
                        # if not found, then check next 10 addresses of account 0 (44'/5'/0'/0)
                        # and so on; we assume here, that user rather puts collaterals
                        # under first addresses of subsequent accounts than under far addresses
                        # of the first account; if so, following iteration shuld be faster
                        found = False
                        if ctrl.finish:
                            break
                        for tenth_nr in range(0, 10):
                            if ctrl.finish:
                                break
                            for account_nr in range(0, 10):
                                if ctrl.finish:
                                    break
                                for index in range(0, 10):
                                    if ctrl.finish:
                                        break
                                    address_n = [2147483692,  # 44'
                                                 2147483653,  # 5'
                                                 2147483648 + account_nr,  # 0' + account_nr
                                                 0,
                                                 (tenth_nr * 10) + index]

                                    cur_bip32_path = bip32_path_n_to_string(address_n)

                                    ctrl.display_msg_fun(
                                        '<b>Scanning hardware wallet for BIP32 paths, please wait...</b><br><br>'
                                        'Paths scanned: <span style="color:black">%d</span><br>'
                                        'Keys found: <span style="color:green">%d</span><br>'
                                        'Current path: <span style="color:blue">%s</span><br>'
                                        % (paths_checked, paths_found, cur_bip32_path))

                                    # first, find dash address in cache by bip32 path
                                    addr_of_cur_path = b32cache.get(cur_bip32_path, None)
                                    if not addr_of_cur_path:
                                        addr_of_cur_path = hw_get_address(self.hw_client, address_n)
                                        b32cache[cur_bip32_path] = addr_of_cur_path
                                        modified_b32cache = True

                                    paths_checked += 1
                                    if addr_to_find_bip32 == addr_of_cur_path:
                                        found_adresses[addr_to_find_bip32] = cur_bip32_path
                                        found = True
                                        paths_found += 1
                                        break
                                    elif not found_adresses.get(addr_of_cur_path, None) and \
                                                    addr_of_cur_path in addresses:
                                        # address of current bip32 path is in the search list
                                        found_adresses[addr_of_cur_path] = cur_bip32_path

                                if found:
                                    break
                            if found:
                                break

                if modified_b32cache:
                    # save modified cache to file
                    if cache_file:
                        try:  # saving into cache
                            json.dump(b32cache, open(cache_file, 'w'))
                        except Exception as e:
                            pass

                if ctrl.finish:
                    user_cancelled = True
            return found_adresses, user_cancelled

        paths_found, user_cancelled = self.threadFunctionDialog(scan_for_bip32_thread, (addresses,), True,
                                                buttons=[{'std_btn': QtWidgets.QDialogButtonBox.Cancel}],
                                                center_by_window=self)
        return paths_found, user_cancelled

    @pyqtSlot(bool)
    def on_btnImportMasternodesConf_clicked(self):
        """
        Imports masternodes configuration from masternode.conf file.
        """
        fileName = QFileDialog.getOpenFileName(self,
                                               caption='Open masternode configuration file',
                                               directory='',
                                               filter="All Files (*);;Conf files (*.conf)",
                                               initialFilter="Conf files (*.conf)"
                                               )

        if fileName and len(fileName) > 0 and fileName[1]:
            if not self.editingEnabled:
                self.on_btnEditMn_clicked()

            if os.path.exists(fileName[0]):
                try:
                    with open(fileName[0], 'r') as f_ptr:
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
                                            self.displayMasternodeConfig(False)
                                else:
                                    imported_cnt += 1
                                    mn = MasterNodeConfig()
                                    update_mn(mn)
                                    modified = True
                                    self.config.add_mn(mn)
                                    self.cboMasternodes.addItem(mn.name, mn)
                                    mns_imported.append(mn)
                            else:
                                # incorrenct number of elements
                                skipped_cnt += 1
                        if modified:
                            self.updateControlsState()
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

                                addresses_to_scan = []
                                for mn in mns_imported:
                                    if not mn.collateralBip32Path and mn.collateralAddress:
                                        addresses_to_scan.append(mn.collateralAddress)
                                found_paths, user_cancelled = self.hwScanForBip32Paths(addresses_to_scan)

                                paths_missing = 0
                                for mn in mns_imported:
                                    if not mn.collateralBip32Path and mn.collateralAddress:
                                        path = found_paths.get(mn.collateralAddress)
                                        mn.collateralBip32Path = path
                                        if path:
                                            if self.curMasternode == mn:
                                                # current mn has been updated - update UI controls
                                                # to new data
                                                self.displayMasternodeConfig(False)
                                        else:
                                            paths_missing += 1

                                if paths_missing:
                                    self.warnMsg('Not all BIP32 paths were found. You have to manually enter '
                                                 'missing paths.')

                        elif skipped_cnt:
                            self.infoMsg('Operation finished with no imported and %s skipped masternodes.'
                                         % str(skipped_cnt))

                except Exception as e:
                    self.errorMsg('Reading file failed: ' + str(e))
            else:
                if fileName[0]:
                    self.errorMsg("File '" + fileName[0] + "' does not exist")

    @pyqtSlot(bool)
    def on_btnSaveConfiguration_clicked(self):
        self.config.save_to_file()
        self.editingEnabled = False
        self.updateControlsState()

    def updateControlsState(self):
        def update_fun():
            editing = (self.editingEnabled and self.curMasternode is not None)
            self.edtMnIp.setReadOnly(not editing)
            self.edtMnName.setReadOnly(not editing)
            self.edtMnPort.setReadOnly(not editing)
            self.edtMnPrivateKey.setReadOnly(not editing)
            self.edtMnCollateralBip32Path.setReadOnly(not editing)
            self.edtMnCollateralAddress.setReadOnly(not editing)
            self.edtMnCollateralTx.setReadOnly(not editing)
            self.edtMnCollateralTxIndex.setReadOnly(not editing)
            self.btnGenerateMNPrivateKey.setEnabled(editing)
            self.btnFindCollateral.setEnabled(editing and self.curMasternode.collateralAddress is not None and
                                              self.curMasternode.collateralAddress != '')
            self.btnHwBip32ToAddress.setEnabled(editing)
            self.btnHwAddressToBip32.setEnabled(editing)
            self.btnEditMn.setEnabled(editing)
            self.btnDeleteMn.setEnabled(self.curMasternode is not None)
            self.btnEditMn.setEnabled(not self.editingEnabled)
            self.btnSaveConfiguration.setEnabled(self.configModified())
            self.btnHwDisconnect.setEnabled(True if self.hw_client else False)

        if threading.current_thread() != threading.main_thread():
            self.callFunInTheMainThread(update_fun)
        else:
            update_fun()

    def configModified(self):
        # check if masternodes config was changed
        modified = self.config.modified
        if not modified:
            for mn in self.config.masternodes:
                if mn.modified:
                    modified = True
                    break
        return modified

    def newMasternodeConfig(self):
        new_mn = MasterNodeConfig()
        new_mn.new = True
        self.curMasternode = new_mn
        # find new, not used masternode name proposal
        name_found = None
        for nr in range(1, 100):
            exists = False
            for mn in self.config.masternodes:
                if mn.name == 'MN' + str(nr):
                    exists = True
                    break
            if not exists:
                name_found = 'MN' + str(nr)
                break
        if name_found:
            new_mn.name = name_found
        self.config.masternodes.append(new_mn)
        self.editingEnabled = True
        old_index = self.cboMasternodes.currentIndex()
        self.cboMasternodes.addItem(new_mn.name, new_mn)
        if old_index != -1:
            # if masternodes combo was not empty before adding new mn, we have to manually set combobox
            # position to a new masternode position
            self.cboMasternodes.setCurrentIndex(self.config.masternodes.index(self.curMasternode))

    def curMnModified(self):
        if self.curMasternode:
            self.curMasternode.set_modified()
            self.btnSaveConfiguration.setEnabled(self.configModified())

    @pyqtSlot(int)
    def on_cboMasternodes_currentIndexChanged(self):
        if self.cboMasternodes.currentIndex() >= 0:
            self.curMasternode = self.config.masternodes[self.cboMasternodes.currentIndex()]
        else:
            self.curMasternode = None
        self.displayMasternodeConfig(False)
        self.updateControlsState()
        if not self.inside_setup_ui:
            cache.set_value('WndMainCurMasternodeIndex', self.cboMasternodes.currentIndex())

    @pyqtSlot(str)
    def on_edtMnName_textEdited(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.name = self.edtMnName.text()
            self.cboMasternodes.setItemText(self.cboMasternodes.currentIndex(), self.curMasternode.name)

    @pyqtSlot(str)
    def on_edtMnIp_textEdited(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.ip = self.edtMnIp.text()

    @pyqtSlot(str)
    def on_edtMnPort_textEdited(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.port = self.edtMnPort.text()

    @pyqtSlot(str)
    def on_edtMnPrivateKey_textEdited(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.privateKey = self.edtMnPrivateKey.text()

    @pyqtSlot(str)
    def on_edtMnCollateralBip32Path_textEdited(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.collateralBip32Path = self.edtMnCollateralBip32Path.text()
            if self.curMasternode.collateralBip32Path:
                self.btnHwBip32ToAddress.setEnabled(True)
            else:
                self.btnHwBip32ToAddress.setEnabled(False)

    @pyqtSlot(str)
    def on_edtMnCollateralAddress_textEdited(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.collateralAddress = self.edtMnCollateralAddress.text()
            self.updateControlsState()
            if self.curMasternode.collateralAddress:
                self.btnHwAddressToBip32.setEnabled(True)
            else:
                self.btnHwAddressToBip32.setEnabled(False)

    @pyqtSlot(str)
    def on_edtMnCollateralTx_textEdited(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.collateralTx = self.edtMnCollateralTx.text()

    @pyqtSlot(str)
    def on_edtMnCollateralTxIndex_textEdited(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.collateralTxIndex = self.edtMnCollateralTxIndex.text()

    @pyqtSlot(bool)
    def on_btnGenerateMNPrivateKey_clicked(self):
        if self.edtMnPrivateKey.text():
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setText('This will overwrite current private key value. Do you really want to proceed?')
            msg.setStandardButtons(QMessageBox.Ok | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            retval = msg.exec_()
            if retval == QMessageBox.No:
                return

        wif = dash_utils.generate_privkey()
        self.curMasternode.privateKey = wif
        self.edtMnPrivateKey.setText(wif)

    @pyqtSlot(bool)
    def on_btnHwBip32ToAddress_clicked(self):
        """
        Convert BIP32 path to Dash address.
        :return: 
        """
        try:
            self.connectHardwareWallet()
            if not self.hw_client:
                return
            if self.curMasternode and self.curMasternode.collateralBip32Path:
                address_n = self.hw_client.expand_path(self.curMasternode.collateralBip32Path)
                dash_addr = hw_get_address(self.hw_client, address_n)
                self.edtMnCollateralAddress.setText(dash_addr)
                self.curMasternode.collateralAddress = dash_addr
                self.updateControlsState()
        except HardwareWalletCancelException:
            if self.hw_client:
                self.hw_client.init_device()
        except Exception as e:
            self.errorMsg(str(e))

    @pyqtSlot(bool)
    def on_btnHwAddressToBip32_clicked(self):
        """
        Converts Dash address to BIP32 path, using hardware wallet.
        :return: 
        """

        try:
            self.connectHardwareWallet()
            if not self.hw_client:
                return
            if self.curMasternode and self.curMasternode.collateralAddress:
                paths, user_cancelled = self.hwScanForBip32Paths([self.curMasternode.collateralAddress])
                if not user_cancelled:
                    if not paths or len(paths) == 0:
                        self.errorMsg("Couldn't find Dash address in your hardware wallet. If you are using HW passphrase, "
                                      "make sure, that you entered the correct one.")
                    else:
                        self.edtMnCollateralBip32Path.setText(paths.get(self.curMasternode.collateralAddress, ''))
                        self.curMasternode.collateralBip32Path = paths.get(self.curMasternode.collateralAddress, '')

        except HardwareWalletCancelException:
            if self.hw_client:
                self.hw_client.init_device()
        except Exception as e:
            self.errorMsg(str(e))

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
                self.edtMnCollateralTx.setFocus()
                return

            if not re.match('\d{1,4}', self.curMasternode.collateralTxIndex):
                self.errorMsg("Invalid collateral transaction index.")
                return

            if not re.match('\d{1,4}', self.curMasternode.port):
                self.errorMsg("Invalid Masternode's port number.")
                return

            if not re.match('\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', self.curMasternode.ip):
                self.errorMsg("Invalid Masternode's IP address.")
                return

            if not self.curMasternode.privateKey:
                self.errorMsg("Masternode's private key not set.")
                return

        self.checkDashdConnection(wait_for_check_finish=True)
        if not self.dashd_connection_ok:
            self.errorMsg("Connection to Dash daemon is not established.")
            return
        if self.is_dashd_syncing:
            self.warnMsg("You must wait until the Dash daemon finishes synchronizing.")
            return

        mn_status = self.getMnStatus()
        if mn_status in ('ENABLED', 'PRE_ENABLED'):
            if self.queryDlg("Warning: masternode's state is %s. \n\nDo you really want to broadcast MN start "
                             "message?" % mn_status, default_button=QMessageBox.Cancel,
                             icon=QMessageBox.Warning) == QMessageBox.Cancel:
                return

        try:
            mn_privkey = dash_utils.wif_to_privkey(self.curMasternode.privateKey)
            if not mn_privkey:
                self.errorMsg('Cannot convert Masternode private key')
                return
            mn_pubkey = bitcoin.privkey_to_pubkey(mn_privkey)

            self.connectHardwareWallet()
            if not self.hw_client:
                return

            seq = 0xffffffff
            block_count = self.dashd_intf.getblockcount()
            block_hash = self.dashd_intf.getblockhash(block_count - 12)
            vintx = bytes.fromhex(self.curMasternode.collateralTx)[::-1].hex()
            vinno = int(self.curMasternode.collateralTxIndex).to_bytes(4, byteorder='big')[::-1].hex()
            vinsig = '00'
            vinseq = seq.to_bytes(4, byteorder='big')[::-1].hex()
            ipv6map = '00000000000000000000ffff'
            ipdigit = map(int, self.curMasternode.ip.split('.'))
            for i in ipdigit:
                ipv6map += i.to_bytes(1, byteorder='big')[::-1].hex()
            ipv6map += int(self.curMasternode.port).to_bytes(2, byteorder='big').hex()

            address_n = self.hw_client.expand_path(self.curMasternode.collateralBip32Path)
            dash_addr = hw_get_address(self.hw_client, address_n)
            if not self.curMasternode.collateralAddress:
                # if mn config's collateral address is empty, assign that from hardware wallet
                self.curMasternode.collateralAddress = dash_addr
                self.edtMnCollateralAddress.setText(self.curMasternode.collateralAddress)
                self.updateControlsState()
            elif dash_addr != self.curMasternode.collateralAddress:
                # verify config's collateral addres with hardware wallet
                if self.queryDlg(message="Dash address from %s's path %s (%s) does not match address from current "
                                 'configuration (%s).\n\nDou you really want to continue?' %
                        (self.getHwName(), self.curMasternode.collateralBip32Path, dash_addr,
                         self.curMasternode.collateralAddress),
                        default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                    return

            # check if there is 1000 Dash collateral
            msg_verification_problem = 'You can continue without verification step if you are sure, that ' \
                                       'TX ID/Index are correct.'
            try:
                utxos = self.dashd_intf.getaddressutxos([dash_addr])
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
                                message="Collateral's transaction output should equal 100000000000 Satoshis (1000 Dash)"
                                        ", but its value is: %d.\n\nDo you really want to continue?"
                                        % (utxo['satoshis']),
                                buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Cancel:
                            return
                else:
                    if self.queryDlg(
                            message="Could not find specified transaction id/index for collateral's address: %s."
                                    "\n\nDo you really want to continue?"
                                    % dash_addr,
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

            collateral_pubkey = self.hw_client.get_public_node(address_n).node.public_key.hex()
            collateral_in = dash_utils.num_to_varint(len(collateral_pubkey) / 2).hex() + collateral_pubkey
            delegate_in = dash_utils.num_to_varint(len(mn_pubkey) / 2).hex() + mn_pubkey
            info = self.dashd_intf.getinfo()
            sig_time = int(time.time())

            serialize_for_sig = self.curMasternode.ip + ':' + self.curMasternode.port + str(int(sig_time)) + \
                                binascii.unhexlify(bitcoin.hash160(bytes.fromhex(collateral_pubkey)))[::-1].hex() + \
                                binascii.unhexlify(bitcoin.hash160(bytes.fromhex(mn_pubkey)))[::-1].hex() + \
                                str(info['protocolversion'])

            sig = self.hw_client.sign_message('Dash', address_n, serialize_for_sig)
            if sig.address != dash_addr:
                self.errorMsg('%s address mismatch after signing.' % self.getHwName())
                return
            sig1 = sig.signature.hex()

            work_sig_time = sig_time.to_bytes(8, byteorder='big')[::-1].hex()
            work_protoversion = int(info['protocolversion']).to_bytes(4, byteorder='big')[::-1].hex()
            last_ping_block_hash = bytes.fromhex(block_hash)[::-1].hex()

            last_ping_serialize_for_sig = dash_utils.serialize_input_str(
                self.curMasternode.collateralTx,
                self.curMasternode.collateralTxIndex,
                seq,
                '') + block_hash + str(sig_time)

            r = dash_utils.ecdsa_sign(last_ping_serialize_for_sig, self.curMasternode.privateKey)
            sig2 = (base64.b64decode(r).hex())

            work = vintx + vinno + vinsig + vinseq \
                   + ipv6map + collateral_in + delegate_in \
                   + dash_utils.num_to_varint(len(sig1) / 2).hex() + sig1 \
                   + work_sig_time + work_protoversion \
                   + vintx + vinno + vinsig + vinseq \
                   + last_ping_block_hash + work_sig_time \
                   + dash_utils.num_to_varint(len(sig2) / 2).hex() + sig2

            work = '01' + work
            ret = self.dashd_intf.masternodebroadcast("decode", work)
            if ret['overall'].startswith('Successfully decoded broadcast messages for 1 masternodes'):
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Information)
                msg.setText('Press <OK> if you want to broadcast Masternode configuration or <Cancel> to exit.')
                msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
                msg.setDefaultButton(QMessageBox.Ok)
                retval = msg.exec_()
                if retval == QMessageBox.Cancel:
                    return

                ret = self.dashd_intf.masternodebroadcast("relay", work)

                match = re.search("relayed broadcast messages for (\d+) masternodes.*failed to relay (\d+), total 1",
                                  ret['overall'])

                failed_count = 0
                ok_count = 0
                if match and len(match.groups()):
                    ok_count = int(match.group(1))
                    failed_count = int(match.group(2))

                overall = ret['overall']
                errorMessage = ''

                if failed_count:
                    del ret['overall']
                    keys = list(ret.keys())
                    if len(keys):
                        # get the first (and currently the only) error message
                        errorMessage = ret[keys[0]].get('errorMessage')

                if failed_count == 0:
                    self.infoMsg(overall)
                    self.on_btnRefreshMnStatus_clicked()
                else:
                    self.errorMsg('Failed to start masternode.\n\nResponse from Dash daemon: %s.' % errorMessage)
            else:
                self.errorMsg(ret['overall'])

        except HardwareWalletCancelException:
            if self.hw_client:
                self.hw_client.init_device()

        except Exception as e:
            self.errorMsg(str(e))
            logging.exception('Exception occurred.')

    def getMnStatus(self):
        """
        Gets current masternode status.
        :return: masternode's status
        """
        if self.dashd_connection_ok:
            addr_ip = self.curMasternode.ip + ':' + self.curMasternode.port
            collateral_id = self.curMasternode.collateralTx + '-' + self.curMasternode.collateralTxIndex
            mn_list = self.dashd_intf.get_masternodelist()
            mn_addr = self.dashd_intf.get_masternodeaddr()
            found = False
            cur_collateral_id = ''
            for cur_collateral_id in mn_addr:
                cur_addr_ip = mn_addr[cur_collateral_id]
                if addr_ip == cur_addr_ip:
                    found = True
                    break

            if found:
                status = mn_list.get(cur_collateral_id, 'Unknown')
                if collateral_id != cur_collateral_id:
                    status += "; warning: collateral configured is not the same as current MN's collateral"
            else:
                status = 'Masternode not found'
        else:
            status = "Problem with connection to dashd"
        return status

    @pyqtSlot(bool)
    def on_btnRefreshMnStatus_clicked(self):
        self.checkDashdConnection(wait_for_check_finish=True)
        status = self.getMnStatus()
        self.edtMnStatus.setText(status)
        if status.strip().startswith('ENABLED') or status.strip().startswith('PRE_ENABLED'):
            self.edtMnStatus.setStyleSheet('QLineEdit{color: green; background-color: lightgray}')
        else:
            self.edtMnStatus.setStyleSheet('QLineEdit{color: black; background-color: lightgray}')

    @pyqtSlot(bool)
    def on_actTransferFundsSelectedMn_triggered(self):
        """
        Shows tranfser funds window with utxos related to current masternode. 
        """
        if self.curMasternode:
            src_addresses = []
            if self.curMasternode.collateralAddress and self.curMasternode.collateralBip32Path:
                src_addresses.append((self.curMasternode.collateralAddress, self.curMasternode.collateralBip32Path))
                self.executeTransferFundsDialog(src_addresses)
            else:
                self.errorMsg("Empty Masternpde collateral's BIP32 path and/or address")
        else:
            self.errorMsg('No masternode selected')

    def on_actTransferFundsForAllMns_triggered(self):
        """
        Shows tranfser funds window with utxos related to all masternodes. 
        """
        src_addresses = []
        for mn in self.config.masternodes:
            if mn.collateralAddress and mn.collateralBip32Path:
                src_addresses.append((mn.collateralAddress, mn.collateralBip32Path))
        if len(src_addresses):
            self.executeTransferFundsDialog(src_addresses)
        else:
            self.errorMsg('No masternode with set collateral BIP32 path and address')

    def executeTransferFundsDialog(self, src_addresses):
        if not self.dashd_intf.open():
            self.errorMsg('Dash daemon not connected')
        else:
            ui = send_payout_dlg.SendPayoutDlg(src_addresses, self)
            ui.exec_()

    def on_actSignMessageWithHw_triggered(self):
        if self.curMasternode:
            self.connectHardwareWallet()
            if self.hw_client:
                if not self.curMasternode.collateralBip32Path:
                    self.errorMsg("Empty Masternode's collateral BIP32 path")
                else:
                    ui = SignMessageDlg(self, self.curMasternode.collateralBip32Path,
                                        self.curMasternode.collateralAddress)
                    ui.exec_()

    def on_actHwSetup_triggered(self):
        """
        Hardware wallet setup.
        """
        self.connectHardwareWallet()
        if self.hw_client:
            ui = HwSetupDlg(self)
            ui.exec_()

    @pyqtSlot(bool)
    def on_btnFindCollateral_clicked(self):
        """
        Open dialog with list of utxos of collateral dash address.
        :return: 
        """
        if self.curMasternode and self.curMasternode.collateralAddress:
            ui = FindCollateralTxDlg(self, self.dashd_intf, self.curMasternode.collateralAddress)
            if ui.exec_():
                tx, txidx = ui.getSelection()
                if tx:
                    self.curMasternode.collateralTx = tx
                    self.curMasternode.collateralTxIndex = str(txidx)
                    self.edtMnCollateralTx.setText(tx)
                    self.edtMnCollateralTxIndex.setText(str(txidx))
                    self.updateControlsState()
        else:
            logging.warning("curMasternode or collateralAddress empty")
