#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-05
import copy
import sys
import logging
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import Qt, pyqtSlot, QPoint
from PyQt5.QtWidgets import QInputDialog, QDialog, QLayout, QListWidgetItem, QPushButton, QCheckBox, QWidget, \
    QHBoxLayout, QMessageBox, QLineEdit, QMenu, QApplication, QDialogButtonBox, QAbstractButton

import app_config
from app_config import AppConfig, DashNetworkConnectionCfg
from dashd_intf import DashdInterface
from psw_cache import SshPassCache
from ui.ui_config_dlg import Ui_ConfigDlg
from ui.ui_conn_rpc_wdg import Ui_RpcConnection
from ui.ui_conn_ssh_wdg import Ui_SshConnection
from wnd_utils import WndUtils
import default_config
from app_config import HWType


class SshConnectionWidget(QWidget, Ui_SshConnection):
    def __init__(self, parent):
        QWidget.__init__(self, parent=parent)
        Ui_SshConnection.__init__(self)
        self.setupUi()

    def setupUi(self):
        Ui_SshConnection.setupUi(self, self)


class RpcConnectionWidget(QWidget, Ui_RpcConnection):
    def __init__(self, parent):
        QWidget.__init__(self, parent=parent)
        Ui_RpcConnection.__init__(self)
        self.setupUi()

    def setupUi(self):
        Ui_RpcConnection.setupUi(self, self)


class ConfigDlg(QDialog, Ui_ConfigDlg, WndUtils):
    def __init__(self, parent, config):
        QDialog.__init__(self, parent=parent)
        Ui_ConfigDlg.__init__(self)
        WndUtils.__init__(self, config)
        self.config = config
        self.main_window = parent
        self.local_config = AppConfig()
        self.local_config.copy_from(config)

        # block ui controls -> cur config data copying while setting ui controls initial values
        self.disable_cfg_update = False
        self.is_modified = False
        self.setupUi()

    def setupUi(self):
        Ui_ConfigDlg.setupUi(self, self)
        self.setWindowTitle("Configuration")
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.accepted.connect(self.on_accepted)
        self.tabWidget.setCurrentIndex(0)

        if sys.platform == 'win32':
            a_link = '<a href="file:///' + self.config.app_config_file_name + '">' + self.config.app_config_file_name + '</a>'
        else:
            a_link = '<a href="file://' + self.config.app_config_file_name + '">' + self.config.app_config_file_name + '</a>'
        self.lblStatus.setText('Config file: ' + a_link)
        self.lblStatus.setOpenExternalLinks(True)
        self.disable_cfg_update = True

        # display all connection configs
        self.displayConnsConfigs()

        lay = self.detailsFrame.layout()

        self.chbConnEnabled = QCheckBox("Enabled")
        self.chbConnEnabled.toggled.connect(self.on_chbConnEnabled_toggled)
        lay.addWidget(self.chbConnEnabled)

        self.chbUseSshTunnel = QCheckBox("Use SSH tunnel")
        self.chbUseSshTunnel.toggled.connect(self.on_chbUseSshTunnel_toggled)
        lay.addWidget(self.chbUseSshTunnel)
        self.ssh_tunnel_widget = SshConnectionWidget(self.detailsFrame)
        lay.addWidget(self.ssh_tunnel_widget)

        # layout for button for reading RPC configuration from remote host over SSH:
        hl = QHBoxLayout()
        self.btnSshReadRpcConfig = QPushButton("\u2B07 Read RPC configuration from SSH host \u2B07")
        self.btnSshReadRpcConfig.clicked.connect(self.on_btnSshReadRpcConfig_clicked)
        hl.addWidget(self.btnSshReadRpcConfig)
        hl.addStretch()
        lay.addLayout(hl)

        # widget with RPC controls:
        self.rpc_cfg_widget = RpcConnectionWidget(self.detailsFrame)
        lay.addWidget(self.rpc_cfg_widget)

        # layout for test button:
        hl = QHBoxLayout()
        self.btnTestConnection = QPushButton("\u2705 Test connection")
        self.btnTestConnection.clicked.connect(self.on_btnTestConnection_clicked)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Minimum)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.btnTestConnection.sizePolicy().hasHeightForWidth())
        self.btnTestConnection.setSizePolicy(sizePolicy)
        hl.addWidget(self.btnTestConnection)
        hl.addStretch()
        lay.addLayout(hl)
        lay.addStretch()

        # set the default size of the left and right size of the splitter
        sh1 = self.lstConns.sizeHintForColumn(0) + 5
        sh2 = self.detailsFrame.sizeHint()
        self.splitter.setSizes([sh1, sh2.width()])

        self.rpc_cfg_widget.edtRpcHost.textEdited.connect(self.on_edtRpcHost_textEdited)
        self.rpc_cfg_widget.edtRpcPort.textEdited.connect(self.on_edtRpcPort_textEdited)
        self.rpc_cfg_widget.edtRpcUsername.textEdited.connect(self.on_edtRpcUsername_textEdited)
        self.rpc_cfg_widget.edtRpcPassword.textEdited.connect(self.on_edtRpcPassword_textEdited)
        self.rpc_cfg_widget.chbRpcSSL.toggled.connect(self.chbRpcSSL_toggled)
        self.ssh_tunnel_widget.edtSshHost.textEdited.connect(self.on_edtSshHost_textEdited)
        self.ssh_tunnel_widget.edtSshPort.textEdited.connect(self.on_edtSshPort_textEdited)
        self.ssh_tunnel_widget.edtSshUsername.textEdited.connect(self.on_edtSshUsername_textEdited)

        self.lstConns.setContextMenuPolicy(Qt.CustomContextMenu)
        self.popMenu = QMenu(self)

        # add new connection action
        self.actNewConn = self.popMenu.addAction("\u2795 Add new connection")
        self.actNewConn.triggered.connect(self.on_actNewConn_triggered)
        self.btnNewConn.setDefaultAction(self.actNewConn)

        # delete connection(s) action
        self.actDeleteConnections = self.popMenu.addAction("\u2796 Delete selected connection(s)")
        self.actDeleteConnections.triggered.connect(self.on_actDeleteConnections_triggered)
        self.btnDeleteConn.setDefaultAction(self.actDeleteConnections)

        # copy connection(s) to clipboard
        self.actCopyConnections = self.popMenu.addAction("\u274f Copy connection(s) to clipboard")
        self.actCopyConnections.triggered.connect(self.on_copyConns_triggered)

        # paste connection(s) from clipboard
        self.actPasteConnections = self.popMenu.addAction("\u23ce Paste connection(s) from clipboard")
        self.actPasteConnections.triggered.connect(self.on_pasteConns_triggered)

        # set unicode symbols to the buttons
        self.btnNewConn.setText("\u2795")
        self.btnDeleteConn.setText("\u2796")
        self.btnMoveDownConn.setText("\u2B07")
        self.btnMoveUpConn.setText("\u2B06")
        self.btnRestoreDefault.setText('\u2606')
        self.rpc_cfg_widget.btnShowPassword.setText("\u29BF")
        self.rpc_cfg_widget.btnShowPassword.pressed.connect(self.on_btnShowPassword_pressed)
        self.rpc_cfg_widget.btnShowPassword.released.connect(self.on_btnShowPassword_released)

        if len(self.local_config.dash_net_configs):
            self.lstConns.setCurrentRow(0)

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
        note_url = app_config.PROJECT_URL + '/blob/master/doc/notes.md#note-dmtn0001'
        self.lblKeepkeyPassEncoding.setText(f'KepKey passphrase encoding (<a href="{note_url}">see</a>)')

        self.chbCheckForUpdates.setChecked(self.local_config.check_for_updates)
        self.chbBackupConfigFile.setChecked(self.local_config.backup_config_file)
        self.chbDownloadProposalExternalData.setChecked(self.local_config.read_proposals_external_attributes)
        self.chbDontUseFileDialogs.setChecked(self.local_config.dont_use_file_dialogs)
        self.chbConfirmWhenVoting.setChecked(self.local_config.confirm_when_voting)
        self.chbAddRandomOffsetToVotingTime.setChecked(self.local_config.add_random_offset_to_vote_time)

        idx = {
                'CRITICAL': 0,
                'ERROR': 1,
                'WARNING': 2,
                'INFO': 3,
                'DEBUG': 4,
                'NOTSET': 5
              }.get(self.local_config.log_level_str, 2)
        self.cboLogLevel.setCurrentIndex(idx)

        self.update_keepkey_pass_encoding_ui()
        self.updateUi()
        self.disable_cfg_update = False

    def closeEvent(self, event):
        if self.is_modified:
            if self.queryDlg('Configuration modified. Save?',
                             buttons=QMessageBox.Yes | QMessageBox.No,
                             default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:
                self.applyConfigChanges()

    def displayConnsConfigs(self):
        # display all connection configs
        self.lstConns.clear()
        for cfg in self.local_config.dash_net_configs:
            item = QListWidgetItem(cfg.get_description())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if cfg.enabled else Qt.Unchecked)
            item.checkState()
            self.lstConns.addItem(item)

    def update_keepkey_pass_encoding_ui(self):
        """
        Display the widget with controls for defining of the encoding of UTF-8 characters in passphrase only when
        Keepkey HW type is selected.
        :return:
        """
        self.wdgKeepkeyPassEncoding.setVisible(self.local_config.hw_type == HWType.keepkey)

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

    @pyqtSlot(QPoint)
    def on_lstConns_customContextMenuRequested(self, point):
        ids = self.lstConns.selectedIndexes()
        self.actCopyConnections.setEnabled(len(ids) > 0)

        # check if clipboard contains at least one connection configuration
        clipboard = QApplication.clipboard()
        try:
            conns = self.local_config.decode_connections_json(clipboard.text())
            if isinstance(conns, list) and len(conns):
                # disable paste action if clipboard doesn't contain connections data JSON string
                self.actPasteConnections.setEnabled(True)
            else:
                self.actPasteConnections.setEnabled(False)
        except:
            self.actPasteConnections.setEnabled(False)

        self.popMenu.exec_(self.lstConns.mapToGlobal(point))

    @pyqtSlot(bool)
    def on_copyConns_triggered(self):
        ids = self.lstConns.selectedIndexes()
        cfgs = []
        for index in ids:
            cfgs.append(self.local_config.dash_net_configs[index.row()])
        if len(cfgs):
            text = self.local_config.encode_connections_to_json(cfgs)
            if text:
                clipboard = QApplication.clipboard()
                clipboard.setText(text)

    @pyqtSlot(bool)
    def on_pasteConns_triggered(self):
        """
        Action executed after user pastes from the clipboard text, containing JSON with list of connections.
        """

        clipboard = QApplication.clipboard()
        try:
            conns = self.local_config.decode_connections_json(clipboard.text())
            if isinstance(conns, list) and len(conns):
                self.actPasteConnections.setEnabled(True)
                if self.queryDlg('Do you really want to import connection(s) from clipboard?',
                                 buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                 default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:
                    new, updated = self.local_config.import_connections(conns, force_import=True)
                    for cfg in new:
                        cfg.enabled = True
                    row_selected = self.lstConns.currentRow()
                    self.displayConnsConfigs()
                    self.set_modified()
                    self.lstConns.setCurrentRow(row_selected)
                    
        except Exception as e:
            self.errorMsg(str(e))

    @pyqtSlot()
    def on_btnRestoreDefault_clicked(self):
        if self.queryDlg('Do you really want to restore default connection(s)?',
                         buttons=QMessageBox.Yes | QMessageBox.Cancel,
                         default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:
            cfgs = self.local_config.decode_connections(default_config.dashd_default_connections)
            if cfgs:
                # force import default connections if there is no any in the configuration
                added, updated = self.local_config.import_connections(cfgs, force_import=True)
                if added or updated:
                    row_selected = self.lstConns.currentRow()
                    self.displayConnsConfigs()
                    self.set_modified()
                    self.lstConns.setCurrentRow(row_selected)
                    self.infoMsg('Defualt connections successfully restored.')
                else:
                    self.infoMsg('All default connections are already in the connection list.')
            else:
                self.warnMsg('Unknown error occurred while restoring default connections.')

    def set_modified(self):
        if not self.disable_cfg_update:
            self.is_modified = True
            self.buttonBox.button(QDialogButtonBox.Apply).setEnabled(self.get_is_modified())

    def get_is_modified(self):
        return self.is_modified

    def applyConfigChanges(self):
        if self.is_modified:
            self.config.copy_from(self.local_config)
            self.config.conn_config_changed()
            self.config.set_log_level(self.local_config.log_level_str)
            self.config.modified = True
            self.main_window.connsCfgChanged()
            self.main_window.save_configuration()

    def on_accepted(self):
        self.applyConfigChanges()

    def updateToolButtonsState(self):
        selected = self.lstConns.currentRow() >= 0
        last = self.lstConns.currentRow() == len(self.local_config.dash_net_configs)-1
        first = self.lstConns.currentRow() == 0

        # disabling/enabling action connected to a button results in setting button's text from actions text
        # thats why we are saving and restoring button's text
        text = self.btnDeleteConn.text()
        self.actDeleteConnections.setEnabled(selected)
        self.btnDeleteConn.setText(text)

        text = self.btnMoveDownConn.text()
        self.btnMoveDownConn.setEnabled(not last and selected)
        self.btnMoveDownConn.setText(text)

        text = self.btnMoveUpConn.text()
        self.btnMoveUpConn.setEnabled(not first and selected)
        self.btnMoveUpConn.setText(text)

    def updateCurConnDesc(self):
        """
        Update current connection description on list 
        """
        if self.lstConns.currentRow() >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]
            item = self.lstConns.currentItem()
            if item:
                old_state = self.disable_cfg_update
                try:
                    self.disable_cfg_update = True  # block updating of UI controls
                    item.setText(cfg.get_description())
                finally:
                    self.disable_cfg_update = old_state

    @pyqtSlot()
    def on_actNewConn_triggered(self):
        cfg = DashNetworkConnectionCfg('rpc')
        self.local_config.dash_net_configs.append(cfg)

        # add config to the connections list:
        item = QListWidgetItem(cfg.get_description())
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if cfg.enabled else Qt.Unchecked)
        item.checkState()
        self.lstConns.addItem(item)
        self.lstConns.setCurrentItem(item)
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

    @pyqtSlot()
    def on_actDeleteConnections_triggered(self):
        ids = self.lstConns.selectedIndexes()
        cfgs = []
        for index in ids:
            cfgs.append(self.local_config.dash_net_configs[index.row()])

        if len(ids) >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]

            if self.queryDlg('Do you really want to delete selected %d connection(s)?' % len(ids),
                             buttons=QMessageBox.Yes | QMessageBox.Cancel,
                             default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Yes:

                last_row_selected = self.lstConns.currentRow()
                rows_to_del = []
                for index in ids:
                    rows_to_del.append(index.row())
                rows_to_del.sort(reverse=True)
                # delete connections with descending order to not renumerate indexes items to-delete while deleting
                # items
                for row in rows_to_del:
                    del self.local_config.dash_net_configs[row]
                    self.lstConns.takeItem(row)

                # try to select the same row
                if last_row_selected < len(self.local_config.dash_net_configs):
                    row = last_row_selected
                else:
                    row = len(self.local_config.dash_net_configs) - 1

                if row < len(self.local_config.dash_net_configs):
                    # select the last row
                    item = self.lstConns.item(row)
                    if item:
                        item.setSelected(True)  # select last item
                        self.lstConns.setCurrentRow(row)
                self.set_modified()

    @pyqtSlot()
    def on_btnMoveUpConn_clicked(self):
        if self.lstConns.currentRow() > 0:
            idx_from = self.lstConns.currentRow()
            l = self.local_config.dash_net_configs
            l[idx_from-1], l[idx_from] = l[idx_from], l[idx_from-1]  # swap two elements
            cur_item = self.lstConns.takeItem(idx_from)
            self.lstConns.insertItem(idx_from-1, cur_item)
            self.lstConns.setCurrentItem(cur_item)
            self.set_modified()

    @pyqtSlot()
    def on_btnMoveDownConn_clicked(self):
        idx_from = self.lstConns.currentRow()
        if idx_from >= 0 and idx_from < len(self.local_config.dash_net_configs)-1:
            l = self.local_config.dash_net_configs
            l[idx_from+1], l[idx_from] = l[idx_from], l[idx_from+1]  # swap two elements
            cur_item = self.lstConns.takeItem(idx_from)
            self.lstConns.insertItem(idx_from+1, cur_item)
            self.lstConns.setCurrentItem(cur_item)
            self.set_modified()

    @pyqtSlot()
    def on_btnShowPassword_pressed(self):
        """
        Show RPC password while button pressed
        """
        self.rpc_cfg_widget.edtRpcPassword.setEchoMode(QLineEdit.Normal)

    @pyqtSlot()
    def on_btnShowPassword_released(self):
        """
        Hide RPC password when button released
        """
        self.rpc_cfg_widget.edtRpcPassword.setEchoMode(QLineEdit.Password)

    @pyqtSlot(QAbstractButton)
    def on_buttonBox_clicked(self, button):
        if button == self.buttonBox.button(QDialogButtonBox.Apply):
            # saving configuration
            self.applyConfigChanges()
            self.config.save_to_file()
            self.is_modified = False
            self.updateUi()

    def on_lstConns_itemChanged(self, item):
        idx = self.lstConns.row(item)
        if not self.disable_cfg_update and idx >= 0 and idx < len(self.local_config.dash_net_configs):
            checked = item.checkState() == Qt.Checked
            cfg = self.local_config.dash_net_configs[idx]
            cfg.enabled = checked
            self.set_modified()
            self.updateUi()

    def on_lstConns_currentRowChanged(self, row):
        self.updateToolButtonsState()
        self.updateUi()

    def on_chbConnEnabled_toggled(self, checked):
        if not self.disable_cfg_update and self.lstConns.currentRow() >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]
            cfg.enabled = checked
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
        if not self.disable_cfg_update and self.lstConns.currentRow() >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]
            cfg.use_ssh_tunnel = checked
            self.updateCurConnDesc()
            self.set_modified()

    def on_edtRpcHost_textEdited(self, text):
        if not self.disable_cfg_update and self.lstConns.currentRow() >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]
            cfg.host = text
            self.updateCurConnDesc()
            self.set_modified()

    def on_edtRpcPort_textEdited(self, text):
        if not self.disable_cfg_update and self.lstConns.currentRow() >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]
            cfg.port = text
            self.updateCurConnDesc()
            self.set_modified()

    def on_edtRpcUsername_textEdited(self, text):
        if not self.disable_cfg_update and self.lstConns.currentRow() >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]
            cfg.username = text
            self.set_modified()

    def on_edtRpcPassword_textEdited(self, text):
        if not self.disable_cfg_update and self.lstConns.currentRow() >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]
            cfg.password = text
            self.set_modified()

    def chbRpcSSL_toggled(self, checked):
        if not self.disable_cfg_update and self.lstConns.currentRow() >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]
            cfg.use_ssl = checked
            self.updateCurConnDesc()
            self.set_modified()

    def on_edtSshHost_textEdited(self, text):
        if not self.disable_cfg_update and self.lstConns.currentRow() >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]
            cfg.ssh_conn_cfg.host = text
            self.updateCurConnDesc()
            self.set_modified()

    def on_edtSshPort_textEdited(self, text):
        if not self.disable_cfg_update and self.lstConns.currentRow() >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]
            cfg.ssh_conn_cfg.port = text
            self.updateCurConnDesc()
            self.set_modified()

    def on_edtSshUsername_textEdited(self, text):
        if not self.disable_cfg_update and self.lstConns.currentRow() >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]
            cfg.ssh_conn_cfg.username = text
            self.set_modified()

    def on_chbRandomConn_toggled(self, checked):
        if not self.disable_cfg_update:
            self.local_config.random_dash_net_config = checked
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

    def updateUi(self):
        dis_old = self.disable_cfg_update
        self.disable_cfg_update = True
        try:
            if self.lstConns.currentRow() >= 0:
                self.chbConnEnabled.setVisible(True)
                self.chbUseSshTunnel.setVisible(True)
                self.btnTestConnection.setVisible(True)
                cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]
                self.chbConnEnabled.setChecked(cfg.enabled)
                self.ssh_tunnel_widget.setVisible(cfg.use_ssh_tunnel)
                self.btnSshReadRpcConfig.setVisible(cfg.use_ssh_tunnel)
                self.chbUseSshTunnel.setCheckState(Qt.Checked if cfg.use_ssh_tunnel else Qt.Unchecked)
                if cfg.use_ssh_tunnel:
                    self.ssh_tunnel_widget.edtSshHost.setText(cfg.ssh_conn_cfg.host)
                    self.ssh_tunnel_widget.edtSshPort.setText(cfg.ssh_conn_cfg.port)
                    self.ssh_tunnel_widget.edtSshUsername.setText(cfg.ssh_conn_cfg.username)
                else:
                    self.ssh_tunnel_widget.edtSshHost.setText('')
                    self.ssh_tunnel_widget.edtSshPort.setText('')
                    self.ssh_tunnel_widget.edtSshUsername.setText('')
                self.rpc_cfg_widget.edtRpcHost.setText(cfg.host)
                self.rpc_cfg_widget.edtRpcPort.setText(cfg.port)
                self.rpc_cfg_widget.edtRpcUsername.setText(cfg.username)
                self.rpc_cfg_widget.edtRpcPassword.setText(cfg.password)
                self.rpc_cfg_widget.chbRpcSSL.setChecked(cfg.use_ssl)
                self.rpc_cfg_widget.setVisible(True)
            else:
                self.chbConnEnabled.setVisible(False)
                self.chbUseSshTunnel.setVisible(False)
                self.btnTestConnection.setVisible(False)
                self.ssh_tunnel_widget.setVisible(False)
                self.btnSshReadRpcConfig.setVisible(False)
                self.rpc_cfg_widget.setVisible(False)
            self.chbRandomConn.setChecked(self.local_config.random_dash_net_config)
            self.buttonBox.button(QDialogButtonBox.Apply).setEnabled(self.get_is_modified())
        finally:
            self.disable_cfg_update = dis_old

    def on_btnSshReadRpcConfig_clicked(self):
        if self.lstConns.currentRow() >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]
            host = cfg.ssh_conn_cfg.host
            port = cfg.ssh_conn_cfg.port
            username = cfg.ssh_conn_cfg.username
            if not host:
                self.errorMsg('Host address is required')
                self.ssh_tunnel_widget.edtSshHost.setFocus()
            if not port:
                self.errorMsg('Host TCP port number is required')
                self.ssh_tunnel_widget.edtSshHost.setFocus()

            ok = True
            if not username:
                username, ok = QInputDialog.getText(self, 'Username Dialog', 'Enter username for SSH connection:')
            if not ok or not username:
                return
            from dashd_intf import DashdSSH
            ssh = DashdSSH(host, int(port), username)
            try:
                ssh.connect()
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
                            modified = modified or (cfg.username != rpcuser)
                            cfg.username = rpcuser
                        if rpcpassword:
                            modified = modified or (cfg.password != rpcpassword)
                            cfg.password = rpcpassword
                        if rpcport:
                            modified = modified or (cfg.port != rpcport)
                            cfg.port = rpcport
                        rpcbind = file.get('rpcbind', '')
                        if not rpcbind:  # listen on all interfaces if not set
                            rpcbind = '127.0.0.1'
                        modified = modified or (cfg.host != rpcbind)
                        cfg.host = rpcbind
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
                    self.updateUi()
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
        if self.lstConns.currentRow() >= 0:
            cfg = self.local_config.dash_net_configs[self.lstConns.currentRow()]

            dashd_intf = DashdInterface(self.config, window=self, connection=cfg)  # we are testing a specific connection
            try:
                info = dashd_intf.getinfo()
                if info:
                    if info.get('protocolversion'):
                        self.infoMsg('Connection successful')
                else:
                    self.errorMsg('Connect error. Details: empty return message')
            except Exception as e:
                self.errorMsg('Connect error. Details: ' + str(e))
            finally:

                del dashd_intf

