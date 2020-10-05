#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-05
import copy
import hashlib
import os
import sys
import logging
from typing import Optional
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import Qt, pyqtSlot, QPoint
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QInputDialog, QDialog, QLayout, QListWidgetItem, QPushButton, QCheckBox, QWidget, \
    QHBoxLayout, QMessageBox, QLineEdit, QMenu, QApplication, QDialogButtonBox, QAbstractButton, QPlainTextEdit, QLabel, \
    QAction, QFileDialog
from cryptography.hazmat.primitives import serialization

import app_config
import app_cache
from app_config import AppConfig, DashNetworkConnectionCfg
from dashd_intf import DashdInterface, control_rpc_call
from psw_cache import SshPassCache
from ui.ui_config_dlg import Ui_ConfigDlg
from ui.ui_conn_rpc_wdg import Ui_RpcConnection
from ui.ui_conn_ssh_wdg import Ui_SshConnection
from wnd_utils import WndUtils
import default_config
from app_defs import HWType, get_note_url


class SshConnectionWidget(QWidget, Ui_SshConnection):
    def __init__(self, parent_window):
        QWidget.__init__(self, parent=parent_window)
        Ui_SshConnection.__init__(self)
        self.setupUi()

    def setupUi(self):
        Ui_SshConnection.setupUi(self, self)
        icon = self.parent().getIcon('folder-open@16px.png')
        self.action_choose_private_key_file = self.edtPrivateKeyPath.addAction(icon, QLineEdit.TrailingPosition)
        self.action_choose_private_key_file.triggered.connect(self.on_actionChoosePrivateKeyFile_triggered)

    def on_actionChoosePrivateKeyFile_triggered(self):
        default_dir = os.path.join(os.path.expanduser('~'), '.ssh')
        file = QFileDialog.getOpenFileName(self.parent(), 'Select private key file', default_dir)
        if len(file) >= 2:
            self.edtPrivateKeyPath.setText(file[0])


class RpcConnectionWidget(QWidget, Ui_RpcConnection):
    def __init__(self, parent):
        QWidget.__init__(self, parent=parent)
        Ui_RpcConnection.__init__(self)
        self.setupUi()

    def setupUi(self):
        Ui_RpcConnection.setupUi(self, self)


class ConfigDlg(QDialog, Ui_ConfigDlg, WndUtils):
    def __init__(self, parent, app_config: AppConfig):
        QDialog.__init__(self, parent=parent)
        Ui_ConfigDlg.__init__(self)
        WndUtils.__init__(self, app_config)
        self.app_config = app_config
        self.main_window = parent
        self.local_config = AppConfig()
        self.local_config.copy_from(app_config)

        # list of connections from self.local_config.dash_net_configs split on separate lists for mainnet and testnet
        self.connections_mainnet = []
        self.connections_testnet = []
        self.connections_current = None
        self.current_network_cfg : Optional[DashNetworkConnectionCfg] = None

        # block ui controls -> cur config data copying while setting ui controls initial values
        self.disable_cfg_update = False
        self.is_modified = False
        self.setupUi()

    def setupUi(self):
        Ui_ConfigDlg.setupUi(self, self)
        self.resize(app_cache.get_value('ConfigDlg_Width', self.size().width(), int),
                    app_cache.get_value('ConfigDlg_Height', self.size().height(), int))

        self.setWindowTitle("Configuration")
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.accepted.connect(self.on_accepted)
        self.tabWidget.setCurrentIndex(0)

        self.disable_cfg_update = True

        layout_details = self.detailsFrame.layout()
        self.chbConnEnabled = QCheckBox("Enabled")
        self.chbConnEnabled.toggled.connect(self.on_chbConnEnabled_toggled)
        layout_details.addWidget(self.chbConnEnabled)
        self.chbUseSshTunnel = QCheckBox("Use SSH tunnel")
        self.chbUseSshTunnel.toggled.connect(self.on_chbUseSshTunnel_toggled)
        layout_details.addWidget(self.chbUseSshTunnel)
        self.ssh_tunnel_widget = SshConnectionWidget(self)
        layout_details.addWidget(self.ssh_tunnel_widget)

        # layout for button for reading RPC configuration from remote host over SSH:
        hl = QHBoxLayout()
        self.btnSshReadRpcConfig = QPushButton("\u2193 Read RPC configuration from SSH host \u2193")
        self.btnSshReadRpcConfig.clicked.connect(self.on_btnSshReadRpcConfig_clicked)
        hl.addWidget(self.btnSshReadRpcConfig)
        hl.addStretch()
        layout_details.addLayout(hl)

        # add connection-editing controls widget:
        self.rpc_cfg_widget = RpcConnectionWidget(self.detailsFrame)
        layout_details.addWidget(self.rpc_cfg_widget)

        # layout for controls related to setting up an additional encryption
        hl = QHBoxLayout()
        self.btnEncryptionPublicKey = QPushButton("RPC encryption public key")
        self.btnEncryptionPublicKey.clicked.connect(self.on_btnEncryptionPublicKey_clicked)
        hl.addWidget(self.btnEncryptionPublicKey)
        self.lblEncryptionPublicKey = QLabel(self)
        self.lblEncryptionPublicKey.setText('')
        hl.addWidget(self.lblEncryptionPublicKey)
        hl.addStretch()
        layout_details.addLayout(hl)

        # layout for the 'test connection' button:
        hl = QHBoxLayout()
        self.btnTestConnection = QPushButton("\u2713 Test connection")
        self.btnTestConnection.clicked.connect(self.on_btnTestConnection_clicked)
        sp = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Minimum)
        sp.setHorizontalStretch(0)
        sp.setVerticalStretch(0)
        sp.setHeightForWidth(self.btnTestConnection.sizePolicy().hasHeightForWidth())
        self.btnTestConnection.setSizePolicy(sp)
        hl.addWidget(self.btnTestConnection)
        hl.addStretch()
        layout_details.addLayout(hl)
        layout_details.addStretch()

        self.rpc_cfg_widget.edtRpcHost.textEdited.connect(self.on_edtRpcHost_textEdited)
        self.rpc_cfg_widget.edtRpcPort.textEdited.connect(self.on_edtRpcPort_textEdited)
        self.rpc_cfg_widget.edtRpcUsername.textEdited.connect(self.on_edtRpcUsername_textEdited)
        self.rpc_cfg_widget.edtRpcPassword.textEdited.connect(self.on_edtRpcPassword_textEdited)
        self.rpc_cfg_widget.chbRpcSSL.toggled.connect(self.chbRpcSSL_toggled)
        self.ssh_tunnel_widget.edtSshHost.textEdited.connect(self.on_edtSshHost_textEdited)
        self.ssh_tunnel_widget.edtSshPort.textEdited.connect(self.on_edtSshPort_textEdited)
        self.ssh_tunnel_widget.edtSshUsername.textEdited.connect(self.on_edtSshUsername_textEdited)
        self.ssh_tunnel_widget.cboAuthentication.currentIndexChanged.connect(self.on_cboSshAuthentication_currentIndexChanged)
        self.ssh_tunnel_widget.edtPrivateKeyPath.textChanged.connect(self.on_edtSshPrivateKeyPath_textChanged)

        self.lstConns.setContextMenuPolicy(Qt.CustomContextMenu)
        self.popMenu = QMenu(self)

        self.action_new_connection = self.popMenu.addAction("Add new connection")
        self.action_new_connection.triggered.connect(self.on_action_new_connection_triggered)
        self.setIcon(self.action_new_connection, 'add@16px.png')
        self.btnNewConn.setDefaultAction(self.action_new_connection)

        self.action_delete_connections = self.popMenu.addAction("Delete selected connection(s)")
        self.action_delete_connections.triggered.connect(self.on_action_delete_connections_triggered)
        self.setIcon(self.action_delete_connections, 'remove@16px.png')
        self.btnDeleteConn.setDefaultAction(self.action_delete_connections)

        self.action_copy_connections = self.popMenu.addAction("Copy connection(s) to clipboard",
                                                              self.on_action_copy_connections_triggered,
                                                              QKeySequence("Ctrl+C"))
        self.setIcon(self.action_copy_connections, 'content-copy@16px.png')
        self.addAction(self.action_copy_connections)

        self.action_paste_connections = self.popMenu.addAction("Paste connection(s) from clipboard",
                                                               self.on_action_paste_connections_triggered,
                                                               QKeySequence("Ctrl+V"))
        self.setIcon(self.action_paste_connections, 'content-paste@16px.png')
        self.addAction(self.action_paste_connections)

        self.btnNewConn.setText("")
        self.btnDeleteConn.setText("")
        self.btnMoveDownConn.setText("")
        self.btnMoveUpConn.setText("")
        self.btnRestoreDefault.setText("")
        self.setIcon(self.btnMoveDownConn, "arrow-downward@16px.png")
        self.setIcon(self.btnMoveUpConn, "arrow-downward@16px.png", rotate=180)
        self.setIcon(self.btnRestoreDefault, "star@16px.png")
        self.setIcon(self.rpc_cfg_widget.btnShowPassword, "eye@16px.png")

        self.rpc_cfg_widget.btnShowPassword.setText("")
        self.rpc_cfg_widget.btnShowPassword.pressed.connect(
            lambda: self.rpc_cfg_widget.edtRpcPassword.setEchoMode(QLineEdit.Normal))
        self.rpc_cfg_widget.btnShowPassword.released.connect(
            lambda: self.rpc_cfg_widget.edtRpcPassword.setEchoMode(QLineEdit.Password))

        if self.local_config.is_mainnet():
            self.cboDashNetwork.setCurrentIndex(0)
            self.connections_current = self.connections_mainnet
        else:
            self.cboDashNetwork.setCurrentIndex(1)
            self.connections_current = self.connections_testnet
        for cfg in self.local_config.dash_net_configs:
            if cfg.testnet:
                self.connections_testnet.append(cfg)
            else:
                self.connections_mainnet.append(cfg)

        if self.local_config.hw_type == HWType.trezor:
            self.chbHwTrezor.setChecked(True)
        elif self.local_config.hw_type == HWType.keepkey:
            self.chbHwKeepKey.setChecked(True)
        else:
            self.chbHwLedgerNanoS.setChecked(True)

        if self.local_config.hw_keepkey_psw_encoding == 'NFC':
            self.cboKeepkeyPassEncoding.setCurrentIndex(0)
        else:
            self.cboKeepkeyPassEncoding.setCurrentIndex(1)
        note_url = get_note_url('DMTN0001')
        self.lblKeepkeyPassEncoding.setText(f'KepKey passphrase encoding (<a href="{note_url}">see</a>)')

        self.chbCheckForUpdates.setChecked(self.local_config.check_for_updates)
        self.chbBackupConfigFile.setChecked(self.local_config.backup_config_file)
        self.chbDownloadProposalExternalData.setChecked(self.local_config.read_proposals_external_attributes)
        self.chbDontUseFileDialogs.setChecked(self.local_config.dont_use_file_dialogs)
        self.chbConfirmWhenVoting.setChecked(self.local_config.confirm_when_voting)
        self.chbAddRandomOffsetToVotingTime.setChecked(self.local_config.add_random_offset_to_vote_time)
        self.chbEncryptConfigFile.setChecked(self.local_config.encrypt_config_file)

        idx = {
                'CRITICAL': 0,
                'ERROR': 1,
                'WARNING': 2,
                'INFO': 3,
                'DEBUG': 4,
                'NOTSET': 5
              }.get(self.local_config.log_level_str, 2)
        self.cboLogLevel.setCurrentIndex(idx)

        self.display_connection_list()
        if len(self.local_config.dash_net_configs):
            self.lstConns.setCurrentRow(0)

        self.update_keepkey_pass_encoding_ui()
        self.update_connection_details_ui()
        self.disable_cfg_update = False
        self.splitter.setSizes(app_cache.get_value('ConfigDlg_ConnectionSplitter_Sizes', [100, 100], list))

    def closeEvent(self, event):
        self.on_close()

    def showEvent(self, QShowEvent):
        self.rpc_cfg_widget.btnShowPassword.setFixedHeight(self.rpc_cfg_widget.edtRpcPassword.height())

    def done(self, result_code):
        self.on_close()
        QDialog.done(self, result_code)

    def on_close(self):
        app_cache.set_value('ConfigDlg_Width', self.size().width())
        app_cache.set_value('ConfigDlg_Height', self.size().height())
        app_cache.set_value('ConfigDlg_ConnectionSplitter_Sizes', self.splitter.sizes())

    def on_accepted(self):
        """Executed after clicking the 'OK' button."""
        if self.is_modified:
            self.apply_config_changes()

    def display_connection_list(self):
        self.lstConns.clear()
        for cfg in self.connections_current:
            item = QListWidgetItem(cfg.get_description())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if cfg.enabled else Qt.Unchecked)
            item.checkState()
            self.lstConns.addItem(item)

    def update_keepkey_pass_encoding_ui(self):
        """Display widget for setting up the encoding of UTF-8 characters in passphrase when
        Keepkey HW type is selected.
        """
        self.wdgKeepkeyPassEncoding.setVisible(self.local_config.hw_type == HWType.keepkey)

    @pyqtSlot(int)
    def on_cboDashNetwork_currentIndexChanged(self, index):
        """Executed after changing configuration between MAINNET and TESTNET."""
        if not self.disable_cfg_update:
            if index == 0:
                self.connections_current = self.connections_mainnet
                self.local_config.dash_network = 'MAINNET'
            else:
                self.connections_current = self.connections_testnet
                self.local_config.dash_network = 'TESTNET'
            self.display_connection_list()
            self.set_modified()
            self.lstConns.setCurrentRow(0)

    @pyqtSlot(QPoint)
    def on_lstConns_customContextMenuRequested(self, point):
        ids = self.lstConns.selectedIndexes()
        self.action_copy_connections.setEnabled(len(ids) > 0)

        # check if the clipboard contains at least one connection configuration in the form of JSON string
        clipboard = QApplication.clipboard()
        try:
            conns = self.local_config.decode_connections_json(clipboard.text())
            if isinstance(conns, list) and len(conns):
                # disable the 'paste' action if the clipboard doesn't contain a JSON string describing a
                # dash connection(s)
                self.action_paste_connections.setEnabled(True)
            else:
                self.action_paste_connections.setEnabled(False)
        except:
            self.action_paste_connections.setEnabled(False)
        self.popMenu.exec_(self.lstConns.mapToGlobal(point))

    def on_action_copy_connections_triggered(self):
        """Action 'copy connections' executed from the context menu associated with the connection list."""
        ids = self.lstConns.selectedIndexes()
        cfgs = []
        for index in ids:
            cfgs.append(self.connections_current[index.row()])
        if len(cfgs):
            text = self.local_config.encode_connections_to_json(cfgs)
            if text:
                clipboard = QApplication.clipboard()
                clipboard.setText(text)

    def on_action_paste_connections_triggered(self):
        """Action 'paste connections' from the clipboard JSON text containing a list of connection definitions."""

        clipboard = QApplication.clipboard()
        try:
            conns = self.local_config.decode_connections_json(clipboard.text())
            if isinstance(conns, list) and len(conns):
                self.action_paste_connections.setEnabled(True)
                if self.queryDlg('Do you really want to import connection(s) from clipboard?',
                                 buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                 default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:
                    testnet = self.local_config.is_testnet()
                    for cfg in conns:
                        cfg.testnet = testnet

                    # update the main list containing connections configuration from separate  lists dedicated
                    # to mainnet and testnet - it'll be used by the import_connection method
                    self.local_config.dash_net_configs.clear()
                    self.local_config.dash_net_configs.extend(self.connections_mainnet)
                    self.local_config.dash_net_configs.extend(self.connections_testnet)

                    added, updated = self.local_config.import_connections(
                        conns, force_import=True, limit_to_network=self.local_config.dash_network)
                    for cfg in added:
                        cfg.enabled = True
                    self.connections_current.extend(added)

                    row_selected = self.lstConns.currentRow()
                    self.display_connection_list()
                    self.set_modified()
                    self.lstConns.setCurrentRow(row_selected)
                    
        except Exception as e:
            self.errorMsg(str(e))

    @pyqtSlot(bool)
    def on_btnRestoreDefault_clicked(self, enabled):
        if self.queryDlg('Do you really want to restore default connection(s)?',
                         buttons=QMessageBox.Yes | QMessageBox.Cancel,
                         default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:
            cfgs = self.local_config.decode_connections(default_config.dashd_default_connections)
            if cfgs:
                # update the main list containing connections configuration from separate  lists dedicated
                # to mainnet and testnet - it'll be used by the import_connection method
                self.local_config.dash_net_configs.clear()
                self.local_config.dash_net_configs.extend(self.connections_mainnet)
                self.local_config.dash_net_configs.extend(self.connections_testnet)

                # force import default connections if there is no any in the configuration
                added, updated = self.local_config.import_connections(
                    cfgs, force_import=True, limit_to_network=self.local_config.dash_network)
                self.connections_current.extend(added)
                if added or updated:
                    row_selected = self.lstConns.currentRow()
                    self.display_connection_list()
                    self.set_modified()
                    if row_selected < self.lstConns.count():
                        self.lstConns.setCurrentRow(row_selected)
                    self.infoMsg('Defualt connections successfully restored.')
                else:
                    self.infoMsg('All default connections are already in the connection list.')
            else:
                self.warnMsg('Unknown error occurred while restoring default connections.')

    def update_conn_tool_buttons_state(self):
        selected = (self.current_network_cfg is not None)
        last = self.lstConns.currentRow() == len(self.connections_current)-1
        first = self.lstConns.currentRow() == 0

        # disabling/enabling action connected to a button results in setting button's text from actions text
        # thats why we are saving and restoring button's text
        text = self.btnDeleteConn.text()
        self.action_delete_connections.setEnabled(selected)
        self.btnDeleteConn.setText(text)

        text = self.btnMoveDownConn.text()
        self.btnMoveDownConn.setEnabled(not last and selected)
        self.btnMoveDownConn.setText(text)

        text = self.btnMoveUpConn.text()
        self.btnMoveUpConn.setEnabled(not first and selected)
        self.btnMoveUpConn.setText(text)

    def update_cur_connection_desc(self):
        """
        Update description of the focused connection in the connections list widget.
        """
        if self.current_network_cfg:
            item = self.lstConns.currentItem()
            if item:
                old_state = self.disable_cfg_update
                try:
                    self.disable_cfg_update = True  # block updating of UI controls
                    item.setText(self.current_network_cfg.get_description())
                finally:
                    self.disable_cfg_update = old_state

    @pyqtSlot()
    def on_action_new_connection_triggered(self):
        cfg = DashNetworkConnectionCfg('rpc')
        cfg.testnet = True if self.cboDashNetwork.currentIndex() == 1 else False
        self.connections_current.append(cfg)

        # add config to the connections list:
        item = QListWidgetItem(cfg.get_description())
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if cfg.enabled else Qt.Unchecked)
        item.checkState()
        self.lstConns.addItem(item)
        self.lstConns.setCurrentItem(item)
        self.set_modified()

    @pyqtSlot()
    def on_action_delete_connections_triggered(self):
        ids = self.lstConns.selectedIndexes()
        cfgs = []
        for index in ids:
            cfgs.append(self.connections_current[index.row()])

        if len(ids) >= 0:
            if self.queryDlg('Do you really want to delete selected %d connection(s)?' % len(ids),
                             buttons=QMessageBox.Yes | QMessageBox.Cancel,
                             default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Yes:

                last_row_selected = self.lstConns.currentRow()
                rows_to_del = []
                for index in ids:
                    rows_to_del.append(index.row())
                rows_to_del.sort(reverse=True)

                # delete connection configs from topmost indexes
                for row_idx in rows_to_del:
                    del self.connections_current[row_idx]
                    self.lstConns.takeItem(row_idx)

                # try selecting the same row
                if last_row_selected < len(self.connections_current):
                    row_idx = last_row_selected
                else:
                    row_idx = len(self.connections_current) - 1

                if row_idx < len(self.connections_current):
                    # select the last row
                    item = self.lstConns.item(row_idx)
                    if item:
                        item.setSelected(True)  # select last item
                        self.lstConns.setCurrentRow(row_idx)
                self.set_modified()

    @pyqtSlot()
    def on_btnMoveUpConn_clicked(self):
        if self.lstConns.currentRow() > 0:
            idx_from = self.lstConns.currentRow()
            l = self.connections_current
            l[idx_from-1], l[idx_from] = l[idx_from], l[idx_from-1]  # swap two elements
            cur_item = self.lstConns.takeItem(idx_from)
            self.lstConns.insertItem(idx_from-1, cur_item)
            self.lstConns.setCurrentItem(cur_item)
            self.set_modified()

    @pyqtSlot()
    def on_btnMoveDownConn_clicked(self):
        idx_from = self.lstConns.currentRow()
        if idx_from >= 0 and idx_from < len(self.connections_current)-1:
            l = self.connections_current
            l[idx_from+1], l[idx_from] = l[idx_from], l[idx_from+1]  # swap two elements
            cur_item = self.lstConns.takeItem(idx_from)
            self.lstConns.insertItem(idx_from+1, cur_item)
            self.lstConns.setCurrentItem(cur_item)
            self.set_modified()

    def on_lstConns_itemChanged(self, item):
        """Executed after checking or unchecking checkbox of a connection on the connections list. Checkbox state is
        then converted to the 'enabled' connection's property."""
        cfg = None
        if item:
            row = self.lstConns.row(item)
            if row >= 0 and row < len(self.connections_current):
                cfg = self.connections_current[row]
        if not self.disable_cfg_update and cfg:
            checked = item.checkState() == Qt.Checked
            cfg.enabled = checked
            self.set_modified()
            self.update_connection_details_ui()

    @pyqtSlot(int)
    def on_lstConns_currentRowChanged(self, row_index):
        """Display a connection's edit properties after moving focus to another connection.
        :param row_index: Index of a currently focused connection on the connections list.
        """
        if row_index >= 0 and row_index < len(self.connections_current):
            self.current_network_cfg = self.connections_current[row_index]
        else:
            self.current_network_cfg = None
        self.update_conn_tool_buttons_state()
        self.update_connection_details_ui()

    def on_chbConnEnabled_toggled(self, checked):
        if not self.disable_cfg_update and self.current_network_cfg:
            self.current_network_cfg.enabled = checked
            try:
                self.disable_cfg_update = True
                item = self.lstConns.currentItem()
                if item:
                    item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            finally:
                self.disable_cfg_update = False
            self.set_modified()

    def on_chbUseSshTunnel_toggled(self, checked):
        self.ssh_tunnel_widget.setVisible(self.chbUseSshTunnel.isChecked())
        self.btnSshReadRpcConfig.setVisible(self.chbUseSshTunnel.isChecked())
        if not self.disable_cfg_update and self.current_network_cfg:
            self.current_network_cfg.use_ssh_tunnel = checked
            self.update_cur_connection_desc()
            self.update_connection_details_ui()
            self.set_modified()

    def on_edtRpcHost_textEdited(self, text):
        if not self.disable_cfg_update and self.current_network_cfg:
            self.current_network_cfg.host = text
            self.update_cur_connection_desc()
            self.set_modified()

    def on_edtRpcPort_textEdited(self, text):
        if not self.disable_cfg_update and self.current_network_cfg:
            self.current_network_cfg.port = text
            self.update_cur_connection_desc()
            self.set_modified()

    def on_edtRpcUsername_textEdited(self, text):
        if not self.disable_cfg_update and self.current_network_cfg:
            self.current_network_cfg.username = text
            self.set_modified()

    def on_edtRpcPassword_textEdited(self, text):
        if not self.disable_cfg_update and self.current_network_cfg:
            self.current_network_cfg.password = text
            self.set_modified()

    def chbRpcSSL_toggled(self, checked):
        if not self.disable_cfg_update and self.current_network_cfg:
            self.current_network_cfg.use_ssl = checked
            self.update_cur_connection_desc()
            self.set_modified()

    def on_edtSshHost_textEdited(self, text):
        if not self.disable_cfg_update and self.current_network_cfg:
            self.current_network_cfg.ssh_conn_cfg.host = text
            self.update_cur_connection_desc()
            self.set_modified()

    def on_edtSshPort_textEdited(self, text):
        if not self.disable_cfg_update and self.current_network_cfg:
            self.current_network_cfg.ssh_conn_cfg.port = text
            self.update_cur_connection_desc()
            self.set_modified()

    def on_edtSshUsername_textEdited(self, text):
        if not self.disable_cfg_update and self.current_network_cfg:
            self.current_network_cfg.ssh_conn_cfg.username = text
            self.set_modified()

    def on_cboSshAuthentication_currentIndexChanged(self, index):
        if not self.disable_cfg_update and self.current_network_cfg:
            if index == 0:
                auth_method = 'any'
            elif index == 1:
                auth_method = 'password'
            elif index == 2:
                auth_method = 'key_pair'
            else:
                auth_method = 'ssh_agent'
            self.current_network_cfg.ssh_conn_cfg.auth_method = auth_method
            self.set_modified()
        self.update_ssh_ctrls_ui()

    def on_edtSshPrivateKeyPath_textChanged(self, text):
        if not self.disable_cfg_update and self.current_network_cfg:
            self.current_network_cfg.ssh_conn_cfg.private_key_path = text
            self.set_modified()

    def on_chbRandomConn_toggled(self, checked):
        if not self.disable_cfg_update:
            self.local_config.random_dash_net_config = checked
            self.set_modified()

    def update_ssh_ctrls_ui(self):
        index = self.ssh_tunnel_widget.cboAuthentication.currentIndex()
        pkey_visible = (index == 2)
        self.ssh_tunnel_widget.lblPrivateKeyPath.setVisible(pkey_visible)
        self.ssh_tunnel_widget.edtPrivateKeyPath.setVisible(pkey_visible)

    def update_connection_details_ui(self):
        """Display properties of the currently focused connection in dedicated UI controls."""
        dis_old = self.disable_cfg_update
        self.disable_cfg_update = True
        try:
            if self.current_network_cfg:
                self.chbConnEnabled.setVisible(True)
                self.chbUseSshTunnel.setVisible(True)
                self.btnTestConnection.setVisible(True)
                self.chbConnEnabled.setChecked(self.current_network_cfg.enabled)
                self.ssh_tunnel_widget.setVisible(self.current_network_cfg.use_ssh_tunnel)
                self.btnSshReadRpcConfig.setVisible(self.current_network_cfg.use_ssh_tunnel)
                self.chbUseSshTunnel.setCheckState(Qt.Checked if self.current_network_cfg.use_ssh_tunnel
                                                   else Qt.Unchecked)
                if self.current_network_cfg.use_ssh_tunnel:
                    self.ssh_tunnel_widget.edtSshHost.setText(self.current_network_cfg.ssh_conn_cfg.host)
                    self.ssh_tunnel_widget.edtSshPort.setText(self.current_network_cfg.ssh_conn_cfg.port)
                    self.ssh_tunnel_widget.edtSshUsername.setText(self.current_network_cfg.ssh_conn_cfg.username)
                    if self.current_network_cfg.ssh_conn_cfg.auth_method == 'any':
                        index = 0
                    elif self.current_network_cfg.ssh_conn_cfg.auth_method == 'password':
                        index = 1
                    elif self.current_network_cfg.ssh_conn_cfg.auth_method == 'key_pair':
                        index = 2
                    else:
                        index = 3
                    self.ssh_tunnel_widget.cboAuthentication.setCurrentIndex(index)
                    self.ssh_tunnel_widget.edtPrivateKeyPath.\
                        setText(self.current_network_cfg.ssh_conn_cfg.private_key_path)
                    self.update_ssh_ctrls_ui()
                else:
                    self.ssh_tunnel_widget.edtSshHost.setText('')
                    self.ssh_tunnel_widget.edtSshPort.setText('')
                    self.ssh_tunnel_widget.edtSshUsername.setText('')
                    self.ssh_tunnel_widget.cboAuthentication.setCurrentIndex(0)
                    self.ssh_tunnel_widget.edtPrivateKeyPath.setText('')

                self.rpc_cfg_widget.edtRpcHost.setText(self.current_network_cfg.host)
                self.rpc_cfg_widget.edtRpcPort.setText(self.current_network_cfg.port)
                self.rpc_cfg_widget.edtRpcUsername.setText(self.current_network_cfg.username)
                self.rpc_cfg_widget.edtRpcPassword.setText(self.current_network_cfg.password)
                self.rpc_cfg_widget.chbRpcSSL.setChecked(self.current_network_cfg.use_ssl)

                self.btnEncryptionPublicKey.setVisible(True)
                self.lblEncryptionPublicKey.setVisible(True)
                pubkey_der = self.current_network_cfg.get_rpc_encryption_pubkey_str('DER')
                if pubkey_der:
                    try:
                        pub_bytes = bytearray.fromhex(pubkey_der)
                        hash = hashlib.sha256(pub_bytes).hexdigest()
                        self.lblEncryptionPublicKey.setText(f'[pubkey hash: {hash[0:8]}]')
                    except Exception as e:
                        self.lblEncryptionPublicKey.setText(f'[pubkey not set]')
                else:
                    self.lblEncryptionPublicKey.setText(f'[pubkey not set]')

                self.rpc_cfg_widget.setVisible(True)
            else:
                self.chbConnEnabled.setVisible(False)
                self.chbUseSshTunnel.setVisible(False)
                self.btnTestConnection.setVisible(False)
                self.ssh_tunnel_widget.setVisible(False)
                self.btnSshReadRpcConfig.setVisible(False)
                self.rpc_cfg_widget.setVisible(False)
                self.btnEncryptionPublicKey.setVisible(False)
                self.lblEncryptionPublicKey.setVisible(False)
            self.chbRandomConn.setChecked(self.local_config.random_dash_net_config)
        finally:
            self.disable_cfg_update = dis_old

    def on_HwType_toggled(self):
        if self.chbHwTrezor.isChecked():
            self.local_config.hw_type = HWType.trezor
        elif self.chbHwKeepKey.isChecked():
            self.local_config.hw_type = HWType.keepkey
        else:
            self.local_config.hw_type = HWType.ledger_nano_s

        self.update_keepkey_pass_encoding_ui()
        self.set_modified()

    @pyqtSlot(bool)
    def on_chbHwTrezor_toggled(self, checked):
        self.on_HwType_toggled()

    @pyqtSlot(bool)
    def on_chbHwKeepKey_toggled(self, checked):
        self.on_HwType_toggled()

    @pyqtSlot(bool)
    def on_chbHwLedgerNanoS_toggled(self, checked):
        self.on_HwType_toggled()

    @pyqtSlot(int)
    def on_cboKeepkeyPassEncoding_currentIndexChanged(self, index):
        if index == 0:
            self.local_config.hw_keepkey_psw_encoding = 'NFC'
        else:
            self.local_config.hw_keepkey_psw_encoding = 'NFKD'
        self.set_modified()

    @pyqtSlot(bool)
    def on_chbCheckForUpdates_toggled(self, checked):
        self.local_config.check_for_updates = checked
        self.set_modified()

    @pyqtSlot(bool)
    def on_chbBackupConfigFile_toggled(self, checked):
        self.local_config.backup_config_file = checked
        self.set_modified()

    @pyqtSlot(bool)
    def on_chbDownloadProposalExternalData_toggled(self, checked):
        self.local_config.read_proposals_external_attributes = checked
        self.set_modified()

    @pyqtSlot(bool)
    def on_chbDontUseFileDialogs_toggled(self, checked):
        self.local_config.dont_use_file_dialogs = checked
        self.set_modified()

    @pyqtSlot(bool)
    def on_chbConfirmWhenVoting_toggled(self, checked):
        self.local_config.confirm_when_voting = checked
        self.set_modified()

    @pyqtSlot(bool)
    def on_chbAddRandomOffsetToVotingTime_toggled(self, checked):
        self.local_config.add_random_offset_to_vote_time = checked
        self.set_modified()

    @pyqtSlot(bool)
    def on_chbEncryptConfigFile_toggled(self, checked):
        self.local_config.encrypt_config_file = checked
        self.set_modified()

    @pyqtSlot(int)
    def on_cboLogLevel_currentIndexChanged(self, index):
        """
        Event fired when loglevel changed by the user.
        :param index: index of the selected level.
        """
        if not self.disable_cfg_update:
            level = {0: 50,
                     1: 40,
                     2: 30,
                     3: 20,
                     4: 10,
                     5: 0}.get(index, 30)
            self.local_config.log_level_str = logging.getLevelName(level)
            self.set_modified()

    def on_btnSshReadRpcConfig_clicked(self):
        """Read the configuration of a remote RPC node from the node's dash.conf file."""
        if self.current_network_cfg:
            host = self.current_network_cfg.ssh_conn_cfg.host
            port = self.current_network_cfg.ssh_conn_cfg.port
            username = self.current_network_cfg.ssh_conn_cfg.username
            auth_method = self.current_network_cfg.ssh_conn_cfg.auth_method
            private_key_path = self.current_network_cfg.ssh_conn_cfg.private_key_path

            if not host:
                self.errorMsg('Host address is required')
                self.ssh_tunnel_widget.edtSshHost.setFocus()
                return

            if not port:
                self.errorMsg('Host TCP port number is required')
                self.ssh_tunnel_widget.edtSshHost.setFocus()
                return

            ok = True
            if not username:
                username, ok = QInputDialog.getText(self, 'Username Dialog', 'Enter username for SSH connection:')
            if not ok or not username:
                return
            from dashd_intf import DashdSSH
            ssh = DashdSSH(host, int(port), username, auth_method=auth_method, private_key_path=private_key_path)
            try:
                if ssh.connect():
                    dashd_conf = ssh.find_dashd_config()
                    self.disable_cfg_update = True
                    if isinstance(dashd_conf, tuple) and len(dashd_conf) >= 3:
                        if not dashd_conf[0]:
                            self.infoMsg('Remore Dash daemon seems to be shut down')
                        elif not dashd_conf[1]:
                            self.infoMsg('Could not find remote dashd.conf file')
                        else:
                            file = dashd_conf[2]
                            rpcuser = file.get('rpcuser', '')
                            rpcpassword = file.get('rpcpassword', '')
                            rpcport = file.get('rpcport', '9998')
                            modified = False
                            if rpcuser:
                                modified = modified or (self.current_network_cfg.username != rpcuser)
                                self.current_network_cfg.username = rpcuser
                            if rpcpassword:
                                modified = modified or (self.current_network_cfg.password != rpcpassword)
                                self.current_network_cfg.password = rpcpassword
                            if rpcport:
                                modified = modified or (self.current_network_cfg.port != rpcport)
                                self.current_network_cfg.port = rpcport
                            rpcbind = file.get('rpcbind', '')
                            if not rpcbind:  # listen on all interfaces if not set
                                rpcbind = '127.0.0.1'
                            modified = modified or (self.current_network_cfg.host != rpcbind)
                            self.current_network_cfg.host = rpcbind
                            if modified:
                                self.is_modified = modified

                            if file.get('server', '1') == '0':
                                self.warnMsg("Remote dash.conf parameter 'server' is set to '0', so RPC interface will "
                                             "not work.")
                            if not rpcuser:
                                self.warnMsg("Remote dash.conf parameter 'rpcuser' is not set, so RPC interface will  "
                                             "not work.")
                            if not rpcpassword:
                                self.warnMsg("Remote dash.conf parameter 'rpcpassword' is not set, so RPC interface will  "
                                             "not work.")
                        self.update_connection_details_ui()
                    elif isinstance(dashd_conf, str):
                        self.warnMsg("Couldn't read remote dashd configuration file due the following error: " +
                                     dashd_conf)
                    ssh.disconnect()
            except Exception as e:
                self.errorMsg(str(e))
                return
            finally:
                self.disable_cfg_update = False

    def on_btnTestConnection_clicked(self):
        if self.current_network_cfg:
            self.local_config.db_intf = self.app_config.db_intf
            dashd_intf = DashdInterface(window=self)
            dashd_intf.initialize(self.local_config, connection=self.current_network_cfg,
                                  for_testing_connections_only=True)
            try:
                info = dashd_intf.getinfo(verify_node=True)
                if info:
                    try:
                        ret = dashd_intf.rpc_call(True, False, "checkfeaturesupport", "enhanced_proxy")
                    except Exception as e:
                        ret = None

                    if ret and type(ret) is dict:
                        self.infoMsg('Connection successful.\n\n'
                                     'Additional info: this node supports message encryption.')
                    else:
                        self.infoMsg('Connection successful.')
                else:
                    self.errorMsg('Connection error. Details: empty return message.')
            except Exception as e:
                self.errorMsg('Connection error. Details: ' + str(e))
            finally:
                del dashd_intf

    def set_modified(self):
        if not self.disable_cfg_update:
            self.is_modified = True

    def get_is_modified(self):
        return self.is_modified

    def apply_config_changes(self):
        """
        Applies changes made by the user by moving the UI controls values to the appropriate
        fields in the self.app_config object.
        """
        if self.is_modified:
            self.local_config.dash_net_configs.clear()
            self.local_config.dash_net_configs.extend(self.connections_mainnet)
            self.local_config.dash_net_configs.extend(self.connections_testnet)

            self.app_config.copy_from(self.local_config)
            self.app_config.conn_config_changed()
            self.app_config.set_log_level(self.local_config.log_level_str)
            self.app_config.modified = True

    def on_btnEncryptionPublicKey_clicked(self):
        updated = False
        key_str = self.current_network_cfg.get_rpc_encryption_pubkey_str('PEM')
        while True:
            key_str, ok = QInputDialog.getMultiLineText(self, "RPC encryption public key",
                                                        "RSA public key (PEM/DER):",
                                                        key_str)
            if ok:
                try:
                    self.current_network_cfg.set_rpc_encryption_pubkey(key_str)
                    updated = True
                    break
                except Exception as e:
                    self.errorMsg(str(e))
            else:
                break

        if updated:
            self.set_modified()
            self.update_connection_details_ui()
