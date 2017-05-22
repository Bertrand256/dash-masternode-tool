#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

import os
import re
import socket
import ssl
import threading
import time
from PyQt5.QtCore import QThread
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
from paramiko import AuthenticationException, PasswordRequiredException, SSHException
from app_config import AppConfig
from random import randint
from wnd_utils import WndUtils
import socketserver
import select
from os.path import expanduser
from psw_cache import SshPassCache, UserCancelledConnection

try:
    import http.client as httplib
except ImportError:
    import httplib


class ForwardServer (socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            chan = self.ssh_transport.open_channel(kind='direct-tcpip',
                                                   dest_addr=(self.chain_host, self.chain_port),
                                                   src_addr=self.request.getpeername())
        except Exception as e:
            return
        if chan is None:
            return

        try:
            while True:
                r, w, x = select.select([self.request, chan], [], [], 10)
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
        except socket.error:
            pass
        except Exception as e:
            print(str(e))
        finally:
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


class DashdConnectionError(Exception):
    def __init__(self, org_exception):
        Exception.__init__(org_exception)
        self.org_exception = org_exception


class DashdSSH(object):
    def __init__(self, host, port, username):
        self.host = host
        self.port = port
        self.username = username
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
        # password = SshPassCache.get_password(self.username, self.host)
        # password = SshPassCache.get_password(self.cur_conn_def.ssh_conn_cfg.username,
        #                                      self.cur_conn_def.ssh_conn_cfg.host)
        # if not password:
        #     raise UserCancelledConnection()
        # SshPassCache.save_password(self.cur_conn_def.ssh_conn_cfg.username,
        #                            self.cur_conn_def.ssh_conn_cfg.host,
        #                            password)

        password = None

        # try to locate ssh private key in standard location
        home_path = expanduser('~')
        ssh_dir = os.path.join(home_path, '.ssh')
        key_filename = os.path.join(ssh_dir, 'id_rsa')
        if not os.path.exists(key_filename):
            key_filename = os.path.join(ssh_dir, 'id_dsa')
            if not os.path.exists(key_filename):
                key_filename = os.path.join(ssh_dir, 'id_ecdsa')
                if not os.path.exists(key_filename):
                    key_filename = None

        while True:
            try:
                self.ssh.connect(self.host, port=int(self.port), username=self.username, password=password,
                                 key_filename=key_filename)
                self.connected = True
                if password:
                    SshPassCache.save_password(self.username, self.host, password)
                break
            except (PasswordRequiredException, AuthenticationException) as e:
                # get password from cache or ask for it
                if key_filename:
                    message = "Enter password for RSA private key '%s'" % key_filename
                else:
                    message = None
                password = SshPassCache. get_password(self.username, self.host, message=message)
                if not password:
                    raise UserCancelledConnection()
            except SSHException as e:
                if e.args and e.args[0] == 'No authentication methods available':
                    password = SshPassCache.get_password(self.username, self.host)
                    if not password:
                        raise UserCancelledConnection()
                else:
                    raise
            except Exception as e:
                raise

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


class DashdIndexException(JSONRPCException):
    """
    Exception for notifying, that dash daemon should have indexing option tuned on
    """
    def __init__(self, parent_exception):
        JSONRPCException.__init__(self, parent_exception.error)
        self.message = self.message + \
                       '\n\nMake sure the dash daemon you are connecting to has the following options enabled in ' \
                       'its dash.conf:\n\n' + \
                       'addressindex=1\n' + \
                       'spentindex=1\n' + \
                       'timestampindex=1\n' + \
                       'txindex=1\n\n' + \
                       'Changing these parameters requires to execute dashd with "-reindex" option (linux: ./dashd -reindex)'


def control_rpc_call(func):
    """
    Decorator function for catching HTTPConnection timeout and then resetting the connection.
    :param func: DashdInterface's method decorated
    """
    def catch_timeout_wrapper(*args, **kwargs):
        ret = None
        last_exception = None
        self = args[0]
        self.mark_call_begin()
        for try_nr in range(1, 5):
            try:
                try:
                    ret = func(*args, **kwargs)
                    last_exception = None
                    self.mark_cur_conn_cfg_is_ok()
                    break
                except (ConnectionResetError, ConnectionAbortedError, httplib.CannotSendRequest, BrokenPipeError) as e:
                    last_exception = e
                    self.http_conn.close()
                except JSONRPCException as e:
                    if e.code == -5 and e.message == 'No information available for address':
                        raise DashdIndexException(e)
                    elif e.error.get('message','').find('403 Forbidden'):
                        self.http_conn.close()
                        raise DashdConnectionError(e)
                    else:
                        self.http_conn.close()

                except (socket.gaierror, ConnectionRefusedError, TimeoutError, socket.timeout) as e:
                    # exceptions raised by not likely functioning dashd node; try to switch to another node
                    # if there is any in the config
                    raise DashdConnectionError(e)

            except DashdConnectionError as e:
                # try another net config if possible
                if not self.switch_to_next_config():
                    self.last_error_message = str(e.org_exception)
                    raise e.org_exception  # couldn't use another conn config, raise last exception
                else:
                    try_nr -= 1  # another config retries do not count

        if last_exception:
            raise last_exception
        return ret
    return catch_timeout_wrapper


class DashdInterface(WndUtils):
    def __init__(self, config, window, connection=None, on_connection_begin_callback=None,
                 on_connection_try_fail_callback=None, on_connection_finished_callback=None):
        WndUtils.__init__(self, app_path=config.app_path)
        assert isinstance(config, AppConfig)

        self.config = config
        # conn configurations are used from the first item in the list; if one fails, then next is taken
        if connection:
            # this parameter is used for testing specific connection
            self.connections = [connection]
        else:
            # get connection list orderd by priority of use
            self.connections = self.config.get_ordered_conn_list()
        self.cur_conn_index = 0
        if self.connections:
            self.cur_conn_def = self.connections[self.cur_conn_index]
        else:
            self.cur_conn_def = None

        # below is the connection with which particular RPC call has started; if connection is switched because of
        # problems with some nodes, switching stops if we close round and return to the starting connection
        self.starting_conn = None

        self.ssh = None
        self.window = window
        self.active = False
        self.rpc_url = None
        self.proxy = None
        self.http_conn = None  # HTTPConnection object passed to the AuthServiceProxy (for convinient connection reset)
        self.on_connection_begin_callback = on_connection_begin_callback
        self.on_connection_try_fail_callback = on_connection_try_fail_callback
        self.on_connection_finished_callback = on_connection_finished_callback
        self.last_error_message = None

    def apply_new_cfg(self):
        """
        Called after any of connection config changed.
        """
        # get connection list orderd by priority of use
        self.disconnect()
        self.connections = self.config.get_ordered_conn_list()
        self.cur_conn_index = 0
        if not len(self.connections):
            raise Exception('There is no connections to Dash network enabled in the configuration.')
        self.cur_conn_def = self.connections[self.cur_conn_index]

    def disconnect(self):
        if self.active:
            if self.ssh:
                self.ssh.disconnect()
                del self.ssh
                self.ssh = None
            self.active = False

    def mark_call_begin(self):
        self.starting_conn = self.cur_conn_def

    def switch_to_next_config(self):
        """
        If there is another dashd config not used recently, switch to it. Called only when there was a problem
        with current connection config.
        :return: True if successfully switched ot False if there was no another config
        """
        if self.cur_conn_def:
            self.config.conn_cfg_failure(self.cur_conn_def)  # mark connection as defective
        if self.cur_conn_index < len(self.connections)-1:
            idx = self.cur_conn_index + 1
        else:
            idx = 0

        conn = self.connections[idx]
        if conn != self.starting_conn:
            self.disconnect()
            self.cur_conn_index = idx
            self.cur_conn_def = conn
            if not self.open():
                return self.switch_to_next_config()
            else:
                return True
        else:
            return False

    def mark_cur_conn_cfg_is_ok(self):
        if self.cur_conn_def:
            self.config.conn_cfg_success(self.cur_conn_def)

    def open(self):
        """
        Opens connection to dash RPC. If it fails, then the next enabled conn config will be used, if any exists.
        :return: True if successfully connected, False if user cancelled the operation. If all of the attempts 
            fail, then appropriate exception will be raised.
        """
        try:
            if not self.cur_conn_def:
                raise Exception('There is no connections to Dash network enabled in the configuration.')

            while True:
                try:
                    if self.open_internal():
                        break
                    else:
                        if not self.switch_to_next_config():
                            return False
                except UserCancelledConnection:
                    return False
                except (socket.gaierror, ConnectionRefusedError, TimeoutError, socket.timeout) as e:
                    # exceptions raised by not likely functioning dashd node; try to switch to another node
                    # if there is any in the config
                    if not self.switch_to_next_config():
                        raise e  # couldn't use another conn config, raise exception
                    else:
                        break
        except Exception as e:
            self.last_error_message = str(e)
            raise

        return True

    def open_internal(self):
        """
        Try to establish connection to dash RPC daemon for current connection config.
        :return: True, if connection successfully establishes, False if user Cancels the operation (not always 
            cancelling will be possible - only when user is prompted for a password).
        """
        if not self.active:
            if self.cur_conn_def.use_ssh_tunnel:
                # RPC over SSH
                while True:
                    self.ssh = DashdSSH(self.cur_conn_def.ssh_conn_cfg.host, self.cur_conn_def.ssh_conn_cfg.port,
                                        self.cur_conn_def.ssh_conn_cfg.username)
                    try:
                        self.ssh.connect()
                        break
                    # except AuthenticationException as e:
                    #     self.errorMsg(str(e))
                    except Exception as e:
                        # self.errorMsg(str(e))
                        # return False
                        raise

                # configure SSH tunnel
                # get random local unprivileged port number to establish SSH tunnel
                success = False
                local_port = None
                for try_nr in range(1, 10):
                    try:
                        local_port = randint(2000, 50000)
                        self.ssh.open_tunnel(local_port,
                                             self.cur_conn_def.host,
                                             int(self.cur_conn_def.port))
                        success = True
                        break
                    except Exception as e:
                        pass
                if not success:
                    return False
                else:
                    rpc_user = self.cur_conn_def.username
                    rpc_password = self.cur_conn_def.password
                    rpc_host = '127.0.0.1'  # SSH tunnel on loopback
                    rpc_port = local_port
            else:
                # direct RPC
                rpc_host = self.cur_conn_def.host
                rpc_port = self.cur_conn_def.port
                rpc_user = self.cur_conn_def.username
                rpc_password = self.cur_conn_def.password

            if self.cur_conn_def.use_ssl:
                self.rpc_url = 'https://'
                self.http_conn = httplib.HTTPSConnection(rpc_host, rpc_port, timeout=5, context=ssl._create_unverified_context())
            else:
                self.rpc_url = 'http://'
                self.http_conn = httplib.HTTPConnection(rpc_host, rpc_port, timeout=5)

            self.rpc_url += rpc_user + ':' + rpc_password + '@' + rpc_host + ':' + str(rpc_port)
            self.proxy = AuthServiceProxy(self.rpc_url, timeout=1000, connection=self.http_conn)

            try:
                if self.on_connection_begin_callback:
                    try:
                        # make the owner know, we are connecting
                        self.on_connection_begin_callback()
                    except:
                        pass

                # check the connection
                self.http_conn.connect()

                if self.on_connection_finished_callback:
                    try:
                        # make the owner know, we successfully finished connection
                        self.on_connection_finished_callback()
                    except:
                        pass
            except:
                if self.on_connection_try_fail_callback:
                    try:
                        # make the owner know, connection attempt failed
                        self.on_connection_try_fail_callback()
                    except:
                        pass
                raise
            finally:
                self.http_conn.close()
                # timeout hase been initially set to 5 seconds to perform 'quick' connection test
                self.http_conn.timeout = 20

            self.active = True
        return self.active

    def get_active_conn_description(self):
        if self.cur_conn_def:
            return self.cur_conn_def.get_description()
        else:
            return '???'

    @control_rpc_call
    def getblockcount(self):
        if self.open():
            return self.proxy.getblockcount()
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getblockhash(self, block):
        if self.open():
            return self.proxy.getblockhash(block)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getinfo(self):
        if self.open():
            return self.proxy.getinfo()
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def issynchronized(self):
        if self.open():
            # if connecting to HTTP(S) proxy do not check if dash daemon is synchronized
            if self.cur_conn_def.is_http_proxy():
                return True
            else:
                syn = self.proxy.mnsync('status')
                return syn.get('IsSynced')
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def mnsync(self):
        if self.open():
            # if connecting to HTTP(S) proxy do not call this function - it will not be exposed
            if self.cur_conn_def.is_http_proxy():
                return {}
            else:
                return self.proxy.mnsync('status')
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def masternodebroadcast(self, what, hexto):
        if self.open():
            return self.proxy.masternodebroadcast(what, hexto)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def get_masternodelist(self):
        if self.open():
            return self.proxy.masternodelist()
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def get_masternodeaddr(self):
        if self.open():
            return self.proxy.masternodelist('addr')
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getaddressbalance(self, address):
        if self.open():
            return self.proxy.getaddressbalance({'addresses': [address]}).get('balance')
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getaddressutxos(self, addresses):
        if self.open():
            return self.proxy.getaddressutxos({'addresses': addresses})
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getrawtransaction(self, txid, verbose):
        if self.open():
            return self.proxy.getrawtransaction(txid, verbose)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getblockhash(self, blockid):
        if self.open():
            return self.proxy.getblockhash(blockid)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getblockheader(self, blockhash):
        if self.open():
            return self.proxy.getblockheader(blockhash)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def validateaddress(self, address):
        if self.open():
            return self.proxy.validateaddress(address)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def decoderawtransaction(self, tx):
        if self.open():
            return self.proxy.decoderawtransaction(tx)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def sendrawtransaction(self, tx):
        if self.open():
            return self.proxy.sendrawtransaction(tx)
        else:
            raise Exception('Not connected')
