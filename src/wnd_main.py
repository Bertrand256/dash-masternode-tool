#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

import base64
import binascii
import re
import time
from PyQt5 import QtCore
import bitcoin
import os
import sys
import trezorlib.types_pb2 as types
from PyQt5 import QtWidgets
from PyQt5.QtCore import QObject
from PyQt5.QtCore import QSize
from PyQt5.QtCore import QThread
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtWidgets import QMessageBox
from trezorlib import client
from src import dash_utils
from src import wnd_about
from src import wnd_conn
from src import wnd_main_base
from src import wnd_trezor_pass
from src import wnd_trezor_pin
from src.app_config import AppConfig, MasterNodeConfig, APP_NAME_LONG
from src.dashd_intf import DashdInterface
from src.trezor_intf import connect_trezor, TrezorCancelException
from src.wnd_utils import WndUtils

PROJECT_URL = 'https://github.com/Bertrand256/dash-masternode-tool'


class CheckForUpdateThread(QThread):
    def __init__(self, update_status_signal, current_app_version):
        super(CheckForUpdateThread, self).__init__()
        self.update_status_signal = update_status_signal
        self.current_app_version = current_app_version

    def run(self):
        try:
            import urllib.request
            response = urllib.request.urlopen(
                'https://raw.githubusercontent.com/Bertrand256/dash-masternode-tool/master/version.txt')
            contents = response.read()
            lines = contents.decode().splitlines()
            remote_version_str = Ui_MainWindow.extractAppVersion(lines)
            remote_ver = Ui_MainWindow.versionStrToNumber(remote_version_str)
            local_ver = Ui_MainWindow.versionStrToNumber(self.current_app_version)

            if remote_ver > local_ver:
                if sys.platform == 'win32':
                    item_name = 'exe_win'
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
                    msg = 'Download URL: <a href="' + exe_url + '">' + exe_url + '</a>'
                else:
                    msg = 'Go to the project\'s website: <a href="' + PROJECT_URL + '">' + PROJECT_URL + '</a>'


                self.update_status_signal.emit("New version available (" + remote_version_str + '). ' + msg, 'green')
        except Exception as e:
            pass


class Ui_MainWindow(wnd_main_base.Ui_MainWindow, WndUtils, QObject):
    update_status_signal = QtCore.pyqtSignal(str, str)  # signal for updating status text from inside thread

    def __init__(self, app_path):
        wnd_main_base.Ui_MainWindow.__init__(self)
        WndUtils.__init__(self)
        QObject.__init__(self)
        self.config = AppConfig()
        self.config.read_from_file()
        self.dashd_intf = DashdInterface(self.config, window=None)
        self.dashd_info = {}
        self.is_dashd_syncing = False
        self.dashd_connection_ok = False
        self.trezor_client = None
        self.curMasternode = None
        self.editingEnabled = False
        self.app_path = app_path
        self.version_str = ''
        try:
            with open(os.path.join(app_path, 'version.txt')) as fptr:
                lines = fptr.read().splitlines()
                self.version_str = self.extractAppVersion(lines)
        except:
            pass

    def setupUi(self, main_window):
        wnd_main_base.Ui_MainWindow.setupUi(self, main_window)
        main_window.setWindowTitle(APP_NAME_LONG + ' by Bertrand256' + (
            ' (v. ' + self.version_str + ')' if self.version_str else ''))

        self.window = main_window
        self.dashd_intf.window = main_window
        self.btnConfigureDashdConnection.clicked.connect(self.btnDashdConnConfigClick)
        self.btnCheckConnection.clicked.connect(self.btnDashdConnCheckClick)
        self.cboMasternodes.currentIndexChanged.connect(self.cboMasternodesIndexChanged)
        self.btnNewMn.clicked.connect(self.btnNewMnClick)
        self.btnDeleteMn.clicked.connect(self.btnDeleteMnClick)
        self.btnImportMasternodeConf.clicked.connect(self.btnImportMasternodesConfClick)
        self.btnEditConfiguration.clicked.connect(self.btnEditConfigurationClick)
        self.btnSaveConfiguration.clicked.connect(self.btnSaveConfigurationClick)
        self.btnReadAddressFromTrezor.setEnabled(False)
        self.btnAbout.clicked.connect(self.btnAboutClick)
        self.edtMnName.textChanged.connect(self.edtMnNameModified)
        self.edtMnIp.textChanged.connect(self.edtMnIpModified)
        self.edtMnPort.textChanged.connect(self.edtMnPortModified)
        self.edtMnPrivateKey.textChanged.connect(self.edtMnPrivateKeyModified)
        self.edtMnCollateralBip32Path.textChanged.connect(self.edtMnCollateralBip32PathModified)
        self.edtMnCollateralAddress.textChanged.connect(self.edtMnCollateralAddressModified)
        self.edtMnCollateralTx.textChanged.connect(self.edtMnCollateralTxModified)
        self.edtMnCollateralTxIndex.textChanged.connect(self.edtMnCollateralTxIndexModified)
        self.btnGenerateMNPrivateKey.clicked.connect(self.btnGenerateMnPrivkeyClick)
        self.edtMnCollateralAddress.setStyleSheet('QLineEdit{background-color: lightgray}')
        self.btnReadAddressFromTrezor.clicked.connect(self.btnReadAddressFromTrezorClick)
        self.btnBroadcastMn.clicked.connect(self.broadcastMasternode)
        self.edtMnStatus.setReadOnly(True)
        self.edtMnStatus.setStyleSheet('QLineEdit{background-color: lightgray}')
        self.btnRefreshMnStatus.clicked.connect(self.btnRefreshMnStatusClick)
        main_window.closeEvent = self.closeEvent
        self.lblStatus = QtWidgets.QLabel(main_window)
        self.lblStatus.setTextFormat(QtCore.Qt.RichText)
        self.lblStatus.setAutoFillBackground(False)
        self.lblStatus.setOpenExternalLinks(True)
        self.statusBar.addPermanentWidget(self.lblStatus, 1)
        self.lblStatus.setText('')
        self.lblStatusDashd = QtWidgets.QLabel(main_window)
        self.statusBar.addPermanentWidget(self.lblStatusDashd, 2)
        self.lblStatusDashd.setText('')
        self.processConnConfig()
        self.checkControlsState()
        img = QPixmap(os.path.join(self.app_path, "img/dmt.png"))
        img = img.scaled(QSize(64, 64))
        self.lblAbout.setPixmap(img)
        if sys.platform == 'win32':
            f = QFont("MS Shell Dlg 2", 10)
            self.cboMasternodes.setFont(f)
            self.edtMnName.setFont(f)
            self.edtMnIp.setFont(f)
            self.edtMnPort.setFont(f)
            self.edtMnPrivateKey.setFont(f)
            self.edtMnCollateralBip32Path.setFont(f)
            self.edtMnCollateralAddress.setFont(f)
            self.edtMnCollateralTx.setFont(f)
            self.edtMnCollateralTxIndex.setFont(f)
            self.edtMnStatus.setFont(f)

        # add masternodes to the combobox
        self.cboMasternodes.clear()
        for mn in self.config.masternodes:
            self.cboMasternodes.addItem(mn.name, mn)
        if not self.config.masternodes:
            self.newMasternodeConfig()
        else:
            self.curMasternode = self.config.masternodes[0]
            self.displayMasternodeConfig(True)

        # create a thread for checking if there is a new version
        self.update_thread = CheckForUpdateThread(self.update_status_signal, self.version_str)
        self.update_status_signal.connect(self.setStatus1Text)
        self.update_thread.start()

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
                self.btnSaveConfigurationClick()

    def processConnConfig(self):
        if not self.config.is_config_complete():
            self.lblConnectionType.setText('Not configured')
        else:
            if self.config.dashd_connect_method == 'rpc':
                self.lblConnectionType.setText('RPC')
            elif self.config.dashd_connect_method == 'rpc_ssh':
                self.lblConnectionType.setText('RPC over SSH')

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

    def btnDashdConnConfigClick(self):
        dialog = QtWidgets.QDialog()
        ui = wnd_conn.Ui_DialogConnection(self.config)
        ui.setupUi(dialog)
        if dialog.exec_():
            if ui.controlsToConfig(self.config):
                try:
                    self.dashd_intf.disconnect()
                    self.processConnConfig()
                    self.checkControlsState()
                except Exception as e:
                    self.errorMsg(str(e))

    def btnAboutClick(self):
        dialog = QtWidgets.QDialog()
        ui = wnd_about.Ui_DialogAbout(self.app_path, self.version_str)
        ui.setupUi(dialog)
        dialog.exec_()

    def checkDashdConnection(self):
        def stopTimer():
            if hasattr(self, 'timer'):
                self.timer.timeout.disconnect(self.checkDashdConnectionStatusTimer)
                del self.timer

        if self.config.is_config_complete():
            for idx in range(1, 4):
                # retry if ConnectionResetError occures
                try:
                    synced = self.dashd_intf.issynchronized()
                    self.dashd_info = self.dashd_intf.getinfo()
                    self.dashd_connection_ok = True
                    if not synced:
                        if not self.is_dashd_syncing:
                            self.is_dashd_syncing = True
                            self.lblConnectionStatus.setText('Dash deamon synchronizing...')
                            self.lblConnectionStatus.setStyleSheet('QLabel{color: orange}')
                            if not hasattr(self, 'timer'):
                                self.timer = QTimer()
                                self.timer.timeout.connect(self.checkDashdConnectionStatusTimer)
                                self.timer.start(2000)
                    else:
                        self.is_dashd_syncing = False
                        self.lblConnectionStatus.setText('Connection successful')
                        self.lblConnectionStatus.setStyleSheet('QLabel{color: green}')
                        stopTimer()
                    if self.dashd_info:
                        self.setStatus1Text('Dashd info: blocks: %s, connections: %s, version: %s, protovol '
                                            'version: %s' %
                                            (str(self.dashd_info.get('blocks', '')),
                                             str(self.dashd_info.get('connections', '')),
                                             str(self.dashd_info.get('version', '')),
                                             str(self.dashd_info.get('protocolversion', ''))
                                             ), 'green')
                    break
                except ConnectionResetError:
                    self.setStatus1Text('', 'black')
                    continue
                except Exception as e:
                    self.is_dashd_syncing = False
                    self.dashd_connection_ok = False
                    self.lblConnectionStatus.setText(str(e))
                    self.lblConnectionStatus.setStyleSheet('QLabel{color: red}')
                    self.setStatus1Text('', 'black')
                    break
        else:
            # configuration is not complete; if timer was created before, delete it
            self.is_dashd_syncing = False
            self.dashd_connection_ok = False
            stopTimer()

    def btnDashdConnCheckClick(self):
        if self.config.is_config_complete():
            self.checkDashdConnection()
        else:
            # configuration not complete: show config window
            self.btnConfigureDashdConnection.click()
            self.checkDashdConnection()

    def checkDashdConnectionStatusTimer(self):
        self.checkDashdConnection()

    @staticmethod
    def askForPinCallback(msg):
        dialog = QtWidgets.QDialog()
        ui = wnd_trezor_pin.Ui_DialogTrezorPin(msg)
        ui.setupUi(dialog)
        if dialog.exec_():
            return ui.pin
        else:
            return None

    @staticmethod
    def askForPassCallback(msg):
        dialog = QtWidgets.QDialog()
        ui = wnd_trezor_pass.Ui_DialogTrezorPin(msg)
        ui.setupUi(dialog)
        if dialog.exec_():
            return ui.getPassphrase()
        else:
            return None

    def setStatus1Text(self, text, color):
        self.lblStatus.setText(text)
        if not color:
            color = 'black'
        self.lblStatus.setStyleSheet('QLabel{color: ' + color + '}')

    def connectTrezor(self):
        if not self.trezor_client:
            try:
                self.trezor_client = connect_trezor(self.askForPinCallback, self.askForPassCallback)
                if self.trezor_client:
                    self.setStatus1Text('Trezor status: Connected', 'green')
                else:
                    self.setStatus1Text('Trezor status: Cannot find Trezor device', 'red')
                    self.errorMsg('Cannot find Trezor device.')
            except client.PinException as e:
                self.errorMsg(e.args[1])
                if self.trezor_client:
                    self.trezor_client.clear_session()
            except OSError as e:
                self.errorMsg('Cannot open Trezor device.')
            except Exception as e:
                self.errorMsg(str(e))
                if self.trezor_client:
                    self.trezor_client.init_device()

    def btnConnectTrezorClick(self):
        self.connectTrezor()

    def btnNewMnClick(self):
        self.newMasternodeConfig()

    def btnDeleteMnClick(self):
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
            self.checkControlsState()

    def btnEditConfigurationClick(self):
        self.editingEnabled = True
        self.checkControlsState()

    def btnImportMasternodesConfClick(self):
        """
        Imports masternodes configuration from masternode.conf file.
        """
        fileName = QFileDialog.getOpenFileName(self.window,
                                               caption='Open masternode configuration file',
                                               directory='',
                                               filter="All Files (*);;Conf files (*.conf)",
                                               initialFilter="Conf files (*.conf)"
                                               )

        if fileName and len(fileName) > 0 and fileName[1]:
            if os.path.exists(fileName[0]):
                try:
                    with open(fileName[0], 'r') as f_ptr:
                        modified = False
                        imported_cnt = 0
                        skipped_cnt = 0
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

                                def update_mn(mn):
                                    mn.name = mn_name
                                    ipelems = mn_ipport.split(':')
                                    if len(ipelems) >= 2:
                                        mn.ip = ipelems[0]
                                        mn.port = ipelems[1]
                                    else:
                                        mn.ip = mn_ipport
                                        mn.port = '9999'
                                    mn.privateKey = mn_privkey
                                    mn.collateralAddress = mn_dash_addr
                                    mn.collateralTx = mn_tx_hash
                                    mn.collateralTxIndex = mn_tx_idx
                                    mn.collateralBip32Path = ''

                                mn = self.config.get_mn_by_name(mn_name)
                                if mn:
                                    msg = QMessageBox()
                                    msg.setIcon(QMessageBox.Information)
                                    msg.setText('Masternode ' + mn_name +' exists. Overwrite?')
                                    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                                    msg.setDefaultButton(QMessageBox.Ok)
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
                            else:
                                # incorrenct number of elements
                                skipped_cnt += 1
                        if modified:
                            self.checkControlsState()
                        if imported_cnt:
                            msg = 'Successfully imported %s masternode(s)' % str(imported_cnt)
                            if skipped_cnt:
                                msg += ', skipped: %s' % str(skipped_cnt)
                            msg += ".\n\nNow you have to manually fill out the BIP32 path of the collateral " \
                                   "for each of imported Masternodes."
                            self.infoMsg(msg)
                        elif skipped_cnt:
                            self.infoMsg('Operation finished with no imported and %s skipped masternodes.'
                                         % str(skipped_cnt))

                except Exception as e:
                    self.errorMsg('Reading file failed: ' + str(e))
            else:
                if fileName[0]:
                    self.errorMsg("File '" + fileName[0] + "' does not exist")

    def btnSaveConfigurationClick(self):
        self.config.save_to_file()
        self.editingEnabled = False
        self.checkControlsState()

    def checkControlsState(self):
        editing = (self.editingEnabled and self.curMasternode is not None)
        self.edtMnIp.setReadOnly(not editing)
        self.edtMnName.setReadOnly(not editing)
        self.edtMnPort.setReadOnly(not editing)
        self.edtMnPrivateKey.setReadOnly(not editing)
        self.edtMnCollateralBip32Path.setReadOnly(not editing)
        self.edtMnCollateralTx.setReadOnly(not editing)
        self.edtMnCollateralTxIndex.setReadOnly(not editing)
        self.btnGenerateMNPrivateKey.setEnabled(editing)
        self.btnReadAddressFromTrezor.setEnabled(editing)
        self.btnEditConfiguration.setEnabled(editing)
        self.btnDeleteMn.setEnabled(self.curMasternode is not None)
        self.btnEditConfiguration.setEnabled(not self.editingEnabled)
        if not editing:
            bg_color = 'QLineEdit{background-color: lightgray}'
        else:
            bg_color = 'QLineEdit{background-color: white}'
        self.edtMnIp.setStyleSheet(bg_color)
        self.edtMnName.setStyleSheet(bg_color)
        self.edtMnPort.setStyleSheet(bg_color)
        self.edtMnPrivateKey.setStyleSheet(bg_color)
        self.edtMnCollateralBip32Path.setStyleSheet(bg_color)
        self.edtMnCollateralTx.setStyleSheet(bg_color)
        self.edtMnCollateralTxIndex.setStyleSheet(bg_color)
        self.btnSaveConfiguration.setEnabled(self.configModified())

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

    def cboMasternodesIndexChanged(self):
        if self.cboMasternodes.currentIndex() >= 0:
            self.curMasternode = self.config.masternodes[self.cboMasternodes.currentIndex()]
        else:
            self.curMasternode = None
        self.displayMasternodeConfig(False)
        self.checkControlsState()

    def edtMnNameModified(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.name = self.edtMnName.text()
            self.cboMasternodes.setItemText(self.cboMasternodes.currentIndex(), self.curMasternode.name)

    def edtMnIpModified(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.ip = self.edtMnIp.text()

    def edtMnPortModified(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.port = self.edtMnPort.text()

    def edtMnPrivateKeyModified(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.privateKey = self.edtMnPrivateKey.text()

    def edtMnCollateralBip32PathModified(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.collateralBip32Path = self.edtMnCollateralBip32Path.text()
            if self.curMasternode.collateralBip32Path:
                self.btnReadAddressFromTrezor.setEnabled(True)
            else:
                self.btnReadAddressFromTrezor.setEnabled(False)

    def edtMnCollateralAddressModified(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.collateralAddress = self.edtMnCollateralAddress.text()

    def edtMnCollateralTxModified(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.collateralTx = self.edtMnCollateralTx.text()

    def edtMnCollateralTxIndexModified(self):
        if self.curMasternode:
            self.curMnModified()
            self.curMasternode.collateralTxIndex = self.edtMnCollateralTxIndex.text()

    def btnGenerateMnPrivkeyClick(self):
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
        self.edtMnPrivateKey.setText(wif)

    def btnReadAddressFromTrezorClick(self):
        try:
            self.connectTrezor()
            if not self.trezor_client:
                return
            address_n = self.trezor_client.expand_path(self.curMasternode.collateralBip32Path)
            dash_addr = self.trezor_client.get_address('Dash', address_n, False, script_type=types.SPENDADDRESS)
            self.edtMnCollateralAddress.setText(dash_addr)
        except TrezorCancelException:
            if self.trezor_client:
                self.trezor_client.init_device()
        except Exception as e:
            self.errorMsg(str(e))

    def broadcastMasternode(self):
        """
        Broadcasts information about configured Masternode within Dash network using Trezor for signing message
        and a Dash daemon for relaying message.
        Building broadcast message is based on work of chaeplin (https://github.com/chaeplin/dashmnb)
        """
        if self.curMasternode:
            if not self.curMasternode.collateralTx:
                self.errorMsg("Collateral transaction id not set.")
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

        self.checkDashdConnection()
        if not self.dashd_connection_ok:
            self.errorMsg("Connection to Dash daemon is not established")
            return

        try:
            mn_privkey = dash_utils.wif_to_privkey(self.curMasternode.privateKey)
            if not mn_privkey:
                self.errorMsg('Cannot convert Masternode private key')
                return
            mn_pubkey = bitcoin.privkey_to_pubkey(mn_privkey)

            self.connectTrezor()
            if not self.trezor_client:
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

            address_n = self.trezor_client.expand_path(self.curMasternode.collateralBip32Path)
            dash_addr = self.trezor_client.get_address('Dash', address_n, False, script_type=types.SPENDADDRESS)
            if not self.curMasternode.collateralAddress:
                # if mn config's collateral address is empty, assign that from Trezor
                self.curMasternode.collateralAddress = dash_addr
                self.edtMnCollateralAddress.setText(self.curMasternode.collateralAddress)
            elif dash_addr != self.curMasternode.collateralAddress:
                # werify config's collateral addres with Trezor
                self.errorMsg('Dash address got from Trezor (path: ' + self.curMasternode.collateralBip32Path +
                              ') does not match with address from current configuration.')
                return
            collateral_pubkey = self.trezor_client.get_public_node(address_n).node.public_key.hex()

            collateral_in = dash_utils.num_to_varint(len(collateral_pubkey) / 2).hex() + collateral_pubkey
            delegate_in = dash_utils.num_to_varint(len(mn_pubkey) / 2).hex() + mn_pubkey
            info = self.dashd_intf.getinfo()
            sig_time = int(time.time())

            serialize_for_sig = self.curMasternode.ip + ':' + self.curMasternode.port + str(int(sig_time)) + \
                                binascii.unhexlify(bitcoin.hash160(bytes.fromhex(collateral_pubkey)))[::-1].hex() + \
                                binascii.unhexlify(bitcoin.hash160(bytes.fromhex(mn_pubkey)))[::-1].hex() + \
                                str(info['protocolversion'])

            sig = self.trezor_client.sign_message('Dash', address_n, serialize_for_sig)
            if sig.address != self.curMasternode.collateralAddress:
                self.errorMsg('Trezor address mismatch after signing.')
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
                if ret['overall'].startswith('Successfully relayed broadcast messages for 1 masternodes'):
                    self.infoMsg(ret['overall'])
                    self.btnRefreshMnStatusClick()
                else:
                    self.errorMsg(ret['overall'])
            else:
                self.errorMsg(ret['overall'])

        except TrezorCancelException:
            if self.trezor_client:
                self.trezor_client.init_device()

        except Exception as e:
            self.errorMsg(str(e))

    def btnRefreshMnStatusClick(self):
        self.checkDashdConnection()
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
                    status = status + "; warning: collateral configured is not the same as current MN's collateral"
            else:
                status = 'Masternode not found'
        else:
            status = "Problem with connection to dashd"
        self.edtMnStatus.setText(status)
        if status.strip().upper().startswith('ENABLED'):
            self.edtMnStatus.setStyleSheet('QLineEdit{color: green; background-color: lightgray}')
        else:
            self.edtMnStatus.setStyleSheet('QLineEdit{color: black; background-color: lightgray}')
