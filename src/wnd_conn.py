#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

from PyQt5.QtWidgets import QInputDialog
from src import wnd_conn_base
from src.app_config import AppConfig
from src.dashd_intf import DashdInterface
from src.wnd_utils import WndUtils
from src.psw_cache import SshPassCache


class Ui_DialogConnection(wnd_conn_base.Ui_DialogConnection, WndUtils):
    def __init__(self, config):
        super().__init__()
        assert isinstance(config, AppConfig)
        self.config = config
        self.window = None

    def setupUi(self, window):
        self.window = window
        wnd_conn_base.Ui_DialogConnection.setupUi(self, window)
        window.setWindowTitle("Dash daemon connection")
        self.btnOk.clicked.connect(self.okClicked)
        self.btnCancel.clicked.connect(self.cancelClicked)
        self.btnTestConnection.clicked.connect(self.testConnection)
        self.edtRpcIP.setText(self.config.rpc_ip)
        self.edtRpcPort.setText(str(self.config.rpc_port))
        self.edtRpcUsername.setText(self.config.rpc_user)
        self.edtRpcPassword.setText(self.config.rpc_password)
        # RPC over SSH
        self.edtRosSshHost.setText(self.config.ros_ssh_host)
        self.edtRosSshPort.setText(self.config.ros_ssh_port)
        self.edtRosSshUsername.setText(self.config.ros_ssh_username)
        self.edtRosRpcBindIp.setText(self.config.ros_rpc_bind_ip)
        self.edtRosRpcBindPort.setText(self.config.ros_rpc_bind_port)
        self.edtRosRpcUsername.setText(self.config.ros_rpc_username)
        self.edtRosRpcPassword.setText(self.config.ros_rpc_password)
        self.btnRosReadDashdConfig.clicked.connect(self.readDashdConfigOverSsh)
        if self.config.dashd_connect_method == 'rpc':
            self.tabConnectMethod.setCurrentIndex(0)
        else:
            self.tabConnectMethod.setCurrentIndex(1)

    def controlsToConfig(self, cfg):
        """
        Reads window control's values into AppConfig object
        :param cfg: AppCnfig object
        """
        assert isinstance(cfg, AppConfig)
        modified = False
        if self.tabConnectMethod.currentIndex() == 0:
            modified = modified or cfg.dashd_connect_method != 'rpc'
            cfg.dashd_connect_method = 'rpc'
        else:
            modified = modified or cfg.dashd_connect_method != 'rpc_ssh'
            cfg.dashd_connect_method = 'rpc_ssh'

        # configuration for Dashd direct RPC mode
        modified = modified or cfg.rpc_ip != self.edtRpcIP.text()
        cfg.rpc_ip = self.edtRpcIP.text()
        try:
            modified = modified or cfg.rpc_port != self.edtRpcPort.text()
            cfg.rpc_port = str(int(self.edtRpcPort.text()))  # validate input string as integer
        except Exception as e:
            self.errorMsg("Invalid RPC port number.")
            self.edtRpcPort.setFocus()
            return False
        modified = modified or cfg.rpc_user != self.edtRpcUsername.text()
        cfg.rpc_user = self.edtRpcUsername.text()
        modified = modified or cfg.rpc_password != self.edtRpcPassword.text()
        cfg.rpc_password = self.edtRpcPassword.text()

        # configuration for Dashd over SSH tunnel mode
        modified = modified or cfg.ros_ssh_host != self.edtRosSshHost.text()
        cfg.ros_ssh_host = self.edtRosSshHost.text()

        modified = modified or cfg.ros_ssh_port != self.edtRosSshPort.text()
        try:
            cfg.ros_ssh_port = str(int(self.edtRosSshPort.text()))  # validate input string
        except Exception as e:
            self.errorMsg("Invalid SSH port number.")
            self.edtRosSshPort.setFocus()
            return False
        modified = modified or cfg.ros_ssh_username != self.edtRosSshUsername.text()
        cfg.ros_ssh_username = self.edtRosSshUsername.text()
        modified = modified or cfg.ros_rpc_bind_ip != self.edtRosRpcBindIp.text()
        cfg.ros_rpc_bind_ip = self.edtRosRpcBindIp.text()
        modified = modified or cfg.ros_rpc_bind_port != self.edtRosRpcBindPort.text()
        cfg.ros_rpc_bind_port = self.edtRosRpcBindPort.text()
        try:
            cfg.ros_rpc_bind_port = str(int(self.edtRosRpcBindPort.text()))  # validate input string
        except Exception as e:
            self.errorMsg("Invalid RPC port number.")
            self.edtRosRpcBindPort.setFocus()
            return False
        modified = modified or cfg.ros_rpc_username != self.edtRosRpcUsername.text()
        cfg.ros_rpc_username = self.edtRosRpcUsername.text()
        modified = modified or cfg.ros_rpc_password != self.edtRosRpcPassword.text()
        cfg.ros_rpc_password = self.edtRosRpcPassword.text()

        if modified:
            cfg.modified = modified
        return True

    def okClicked(self):
        cfg = AppConfig()
        if self.controlsToConfig(cfg):  # test if values are correct
            # values OK, so fill main app's config object
            try:
                self.window.accept()
            except Exception as e:
                self.errorMsg(str(e))

    def cancelClicked(self):
        self.window.close()

    def readDashdConfigOverSsh(self):
        host = self.edtRosSshHost.text()
        port = self.edtRosSshPort.text()
        username = self.edtRosSshUsername.text()
        if not host:
            self.errorMsg('Host address is required')
            self.edtRosSshHost.setFocus()
        if not port:
            self.errorMsg('Host TCP port number is required')
            self.edtRosSshPort.setFocus()

        ok = True
        if not username:
            username, ok = QInputDialog.getText(self.window, 'Username Dialog', 'Enter username for SSH connection:')
        if not ok or not username:
            return
        password = SshPassCache.get_password(self.window, username, host)
        if password:
            from src.dashd_intf import DashdSSH
            ssh = DashdSSH(host, int(port), username, password)
            try:
                ssh.connect()
                SshPassCache.save_password(username, host, password)  # save password in cache
                dashd_conf = ssh.find_dashd_config()
                if isinstance(dashd_conf, tuple) and len(dashd_conf) >= 3:
                    if not dashd_conf[0]:
                        self.infoMsg('Remore Dash daemon seems to be shut down')
                    elif not dashd_conf[1]:
                        self.infoMsg('Could not find remote dashd.conf file')
                    else:
                        file = dashd_conf[2]
                        rpcuser = file.get('rpcuser', '')
                        rpcpassword = file.get('rpcpassword', '')
                        if file.get('rpcuser', ''):
                            self.edtRosRpcUsername.setText(rpcuser)
                        if file.get('rpcpassword', ''):
                            self.edtRosRpcPassword.setText(rpcpassword)
                        if file.get('rpcport', ''):
                            self.edtRosRpcBindPort.setText(file.get('rpcport', '9998'))
                        rpcbind = file.get('rpcbind', '')
                        if not rpcbind:  # listen on all interfaces if not set
                            self.edtRosRpcBindIp.setText('127.0.0.1')
                        if file.get('server', '1') == '0':
                            self.warnMsg("Remote dash.conf parameter 'server' is set to '0', so RPC interface will "
                                         "not work.")
                        if not rpcuser:
                            self.warnMsg("Remote dash.conf parameter 'rpcuser' is not set, so RPC interface will  "
                                         "not work.")
                        if not rpcpassword:
                            self.warnMsg("Remote dash.conf parameter 'rpcpassword' is not set, so RPC interface will  "
                                         "not work.")
                elif isinstance(dashd_conf, str):
                    self.warnMsg("Couldn't read the remote dashd configuration file due the following error: " +
                                 dashd_conf)
                ssh.disconnect()
            except Exception as e:
                self.errorMsg(str(e))
                return
            pass

    def testConnection(self):
        cfg = AppConfig()
        if self.controlsToConfig(cfg):
            try:
                dashd_intf = DashdInterface(cfg, self.window)
                info = dashd_intf.getinfo()
                if info.get('protocolversion'):
                    self.infoMsg('Connection successful')
                del dashd_intf
            except Exception as e:
                self.errorMsg('Connect error. Details: ' + str(e))
        del cfg
