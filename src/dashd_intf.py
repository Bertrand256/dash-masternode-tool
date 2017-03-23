#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

import os
import re
import threading
import time
from PyQt5.QtCore import QThread
from bitcoinrpc.authproxy import AuthServiceProxy
from paramiko import AuthenticationException
from src.app_config import AppConfig
from random import randint
from src.wnd_utils import WndUtils
import socketserver
import select
from src.psw_cache import SshPassCache


class ForwardServer (socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            chan = self.ssh_transport.open_channel('direct-tcpip',
                                                   (self.chain_host, self.chain_port),
                                                   self.request.getpeername())
        except Exception as e:
            return
        if chan is None:
            return

        while True:
            r, w, x = select.select([self.request, chan], [], [])
            if self.request in r:
                data = self.request.recv(1024)
                if len(data) == 0:
                    break
                chan.send(data)
            if chan in r:
                data = chan.recv(1024)
                if len(data) == 0:
                    break
                self.request.send(data)

        chan.close()
        self.request.close()


class SSHTunnelThread(QThread):
    def __init__(self, local_port, remote_ip, remote_port, transport, ready_event):
        QThread.__init__(self)
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.transport = transport
        self.ready_event = ready_event
        self.forward_server = None
        self.setObjectName('SSHTunnelThread')

    def __del__(self):
        pass

    def stop(self):
        if self.forward_server:
            self.forward_server.shutdown()

    def run(self):
        class SubHander(Handler):
            chain_host = self.remote_ip
            chain_port = self.remote_port
            ssh_transport = self.transport

        self.ready_event.set()
        self.forward_server = ForwardServer(('127.0.0.1', self.local_port), SubHander)
        self.forward_server.serve_forever()
        print('Stopped local port forwarding 127.0.0.1:%s -> %s:%s' % (str(self.local_port), self.remote_ip,
                                                                       str(self.remote_port)))


class UnknownError(Exception):
    pass


class DashdSSH(object):
    def __init__(self, host, port, username, password):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.ssh = None
        self.channel = None
        self.fw_channel = None
        self.connected = False
        self.ssh_thread = None

    def __del__(self):
        self.disconnect()

    def remote_command(self, cmd):
        channel = None
        try:
            channel = self.ssh.get_transport().open_session()
            channel.exec_command(cmd)
            ret_code = channel.recv_exit_status()

            if ret_code == 0:
                for idx in range(1, 20):
                    if channel.recv_ready():
                        break
                    time.sleep(0.1)
                if not channel.recv_ready():
                    raise Exception('Data not ready')
                data = channel.recv(500)
                return data.decode().split('\n')
            else:
                for idx in range(1, 20):
                    if channel.recv_stderr_ready():
                        break
                    time.sleep(0.1)
                if channel.recv_stderr_ready():
                    data = channel.recv_stderr(500)
                    error = data.decode()
                    raise Exception(error)
                else:
                    raise UnknownError('Unknown error executing remote command: ' + cmd)
        finally:
            if channel:
                channel.close()

    def connect(self):
        import paramiko
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(self.host, port=int(self.port), username=self.username, password=self.password)
        self.connected = True

    def open_tunnel(self, local_port, remote_ip, remote_port):
        if self.connected:
            ready_event = threading.Event()
            self.ssh_thread = SSHTunnelThread(local_port, remote_ip, remote_port, self.ssh.get_transport(), ready_event)
            self.ssh_thread.start()
            ready_event.wait(10)
            print('Started local port forwarding 127.0.0.1:%s -> %s:%s' %
                  (str(local_port), remote_ip, str(remote_port)))
        else:
            raise Exception('SSH not connected')

    def find_dashd_config(self):
        """
        Try to read configuration of remote dash daemon. In particular we need parameters concering rpc
        configuration.
        :return: tuple (dashd_running, dashd_config_found, dashd config file contents as dict)
                or error string in error occured
        """
        dashd_running = False
        dashd_config_found = False
        if not self.ssh:
            raise Exception('SSH session not ready')
        try:
            # find dashd process id if running
            try:
                pids = self.remote_command('ps -C "dashd" -o pid')
            except UnknownError:
                raise Exception('is dashd running on the remote machine?')
            pid = None
            if isinstance(pids, list):
                pids = [pid.strip() for pid in pids]
            if len(pids) >= 2 and pids[0] == 'PID' and re.match('\d+', pids[1]):
                pid = pids[1]
            elif len(pids) >= 1 and re.match('\d+', pids[0]):
                pid = pids[1]
            config = {}
            if pid:
                dashd_running = True
                # using dashd pid find its executable path and then .dashcore directory and finally dash.conf file
                executables = self.remote_command('ls -l /proc/' + str(pid) + '/exe')
                if executables and len(executables) >= 1:
                    elems = executables[0].split('->')
                    if len(elems) == 2:
                        executable = elems[1].strip()
                        dashd_dir = os.path.dirname(executable)
                        dash_conf_file = dashd_dir + '/.dashcore/dash.conf'
                        conf_lines = []
                        try:
                            conf_lines = self.remote_command('cat ' + dash_conf_file)
                        except Exception as e:
                            # probably error no such file or directory
                            # try to read dashd's cwd + cmdline
                            cwd_lines = self.remote_command('ls -l /proc/' + str(pid) + '/cwd')
                            if cwd_lines:
                                elems = cwd_lines[0].split('->')
                                if len(elems) >= 2:
                                    cwd = elems[1]
                                    dash_conf_file = cwd + '/.dashcore/dash.conf'
                                    try:
                                        conf_lines = self.remote_command('cat ' + dash_conf_file)
                                    except Exception as e:
                                        # second method did not suceed, so assume, that conf file is located
                                        # i /home/<username>/.dashcore directory
                                        dash_conf_file = '/home/' + self.username + '/.dashcore/dash.conf'
                                        conf_lines = self.remote_command('cat ' + dash_conf_file)

                        for line in conf_lines:
                            elems = [e.strip() for e in line.split('=')]
                            if len(elems) == 2:
                                config[elems[0]] = elems[1]
                        dashd_config_found = True
            return dashd_running, dashd_config_found, config
        except Exception as e:
            return str(e)

    def disconnect(self):
        if self.ssh:
            if self.ssh_thread:
                self.ssh_thread.stop()
            self.ssh.close()
            del self.ssh
            self.ssh = None
            self.connected = False


class DashdInterface(WndUtils):
    def __init__(self, config, window):
        WndUtils.__init__(self)
        assert isinstance(config, AppConfig)
        self.config = config
        self.last_connect_method = config.dashd_connect_method
        self.ssh = None
        self.window = window
        self.active = False
        self.rpc_url = None
        self.proxy = None

    def disconnect(self):
        if self.active:
            if self.last_connect_method == 'rpc_ssh' and self.ssh:
                self.ssh.disconnect()
                del self.ssh
                self.ssh = None
            self.active = False

    def open(self):
        if not self.active:
            rpc_host = None
            rpc_port = None
            rpc_user = None
            rpc_password = None

            if self.config.dashd_connect_method == 'rpc_ssh':
                # RPC over SSH
                while True:
                    password = SshPassCache.get_password(self.window, self.config.ros_ssh_username,
                                                         self.config.ros_ssh_host)
                    if not password:
                        return False

                    self.ssh = DashdSSH(self.config.ros_ssh_host, self.config.ros_ssh_port,
                                        self.config.ros_ssh_username, password)
                    try:
                        self.ssh.connect()
                        SshPassCache.save_password(self.config.ros_ssh_username, self.config.ros_ssh_host,
                                                   password)
                        break
                    except AuthenticationException as e:
                        self.errorMsg(str(e))
                    except Exception as e:
                        self.errorMsg(str(e))

                # configure SSH tunnel
                # get random local unprivileged port number to establish SSH tunnel
                success = False
                local_port = None
                for try_nr in range(1, 10):
                    try:
                        local_port = randint(2000, 50000)
                        self.ssh.open_tunnel(local_port, self.config.ros_rpc_bind_ip,
                                             int(self.config.ros_rpc_bind_port))
                        success = True
                        break
                    except Exception as e:
                        pass
                if not success:
                    return False
                else:
                    rpc_user = self.config.ros_rpc_username
                    rpc_password = self.config.ros_rpc_password
                    rpc_host = '127.0.0.1'  # SSH tunnel on loopback
                    rpc_port = local_port
            elif self.config.dashd_connect_method == 'rpc':
                # direct RPC
                rpc_host = self.config.rpc_ip
                rpc_port = self.config.rpc_port
                rpc_user = self.config.rpc_user
                rpc_password = self.config.rpc_password
            else:
                raise Exception('Invalid connection method')

            self.rpc_url = 'http://' + rpc_user + ':' + rpc_password + '@' + rpc_host + ':' + str(rpc_port)
            self.proxy = AuthServiceProxy(self.rpc_url)
            self.active = True
        return self.active

    def getblockcount(self):
        if self.open():
            return self.proxy.getblockcount()
        else:
            raise Exception('Not connected')

    def getblockhash(self, block):
        if self.open():
            return self.proxy.getblockhash(block)
        else:
            raise Exception('Not connected')

    def getinfo(self):
        if self.open():
            return self.proxy.getinfo()
        else:
            raise Exception('Not connected')

    def issynchronized(self):
        if self.open():
            syn = self.proxy.mnsync('status')
            return syn.get('IsSynced')
        else:
            raise Exception('Not connected')

    def masternodebroadcast(self, what, hexto):
        if self.open():
            return self.proxy.masternodebroadcast(what, hexto)
        else:
            raise Exception('Not connected')

    def get_masternodelist(self):
        if self.open():
            return self.proxy.masternodelist()
        else:
            raise Exception('Not connected')

    def get_masternodeaddr(self):
        if self.open():
            return self.proxy.masternodelist('addr')
        else:
            raise Exception('Not connected')
