#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

import os
import re
import socket
import sqlite3
import ssl
import threading
import time
import datetime
import logging

import simplejson
from PyQt5.QtCore import QThread
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
from paramiko import AuthenticationException, PasswordRequiredException, SSHException
from app_config import AppConfig
from random import randint
from wnd_utils import WndUtils
import socketserver
import select
from os.path import expanduser
from PyQt5.QtWidgets import QMessageBox
from psw_cache import SshPassCache, UserCancelledConnection
from common import AttrsProtected

try:
    import http.client as httplib
except ImportError:
    import httplib


# how many seconds cached masternodes data are valid; cached masternode data is used only for non-critical
# features
MASTERNODES_CACHE_VALID_SECONDS = 60 * 60  # 60 minutes


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
        password = None
        pass_message = None

        while True:
            try:
                self.ssh.connect(self.host, port=int(self.port), username=self.username, password=password)
                self.connected = True
                if password:
                    SshPassCache.save_password(self.username, self.host, password)
                break
            except PasswordRequiredException as e:
                # private key with password protection is used; ask user for password
                pass_message = "Enter passphrase for <b>private key</b> or password for %s" % \
                               (self.username + '@' + self.host)
                while True:
                    password = SshPassCache.get_password(self.username, self.host, message=pass_message)
                    if password:
                        break

            except AuthenticationException as e:
                # This exception will be raised in the following cases:
                #  1. a private key with password protectection is used but the user enters incorrect password
                #  2. a private key exists but user's public key is not added to the server's allowed keys
                #  3. normal login to server is performed but the user enters bad password
                # So, in the first case, the second query for password will ask for normal password to server, not
                #  for a private key.

                WndUtils.errorMsg(message='Incorrect password, try again...')

                while True:
                    password = SshPassCache.get_password(self.username, self.host, message=pass_message)
                    if password:
                        break

            except SSHException as e:
                if e.args and e.args[0] == 'No authentication methods available':
                    while True:
                        password = SshPassCache.get_password(self.username, self.host)
                        if password:
                            break
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
        try:
            logging.info('Trying to acquire http_lock')
            self.http_lock.acquire()
            logging.info('Acquired http_lock')
            for try_nr in range(1, 5):
                try:
                    try:
                        logging.info('Beginning call of "' + str(func) + '"')
                        begin_time = time.time()
                        ret = func(*args, **kwargs)
                        logging.info('Ended call of "' + str(func) + '". Call time: ' + str(time.time() - begin_time)
                                     + 's.')
                        last_exception = None
                        self.mark_cur_conn_cfg_is_ok()
                        break
                    except (ConnectionResetError, ConnectionAbortedError, httplib.CannotSendRequest, BrokenPipeError) as e:
                        logging.error('Error while calling of "' + str(func) + '". Details: ' + str(e))
                        last_exception = e
                        self.http_conn.close()
                    except JSONRPCException as e:
                        logging.error('Error while calling of "' + str(func) + '". Details: ' + str(e))
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
                        logging.error('Error while calling of "' + str(func) + '". Details: ' + str(e))
                        raise DashdConnectionError(e)

                except DashdConnectionError as e:
                    # try another net config if possible
                    logging.error('Error while calling of "' + str(func) + '". Details: ' + str(e))
                    if not self.switch_to_next_config():
                        self.last_error_message = str(e.org_exception)
                        raise e.org_exception  # couldn't use another conn config, raise last exception
                    else:
                        try_nr -= 1  # another config retries do not count
                except Exception as e:
                    logging.exception('Error while calling of "' + str(func) + '". Details: ' + str(e))
                    raise
        finally:
            self.http_lock.release()
            logging.info('Released http_lock')

        if last_exception:
            raise last_exception
        return ret
    return catch_timeout_wrapper


class Masternode(AttrsProtected):
    def __init__(self):
        AttrsProtected.__init__(self)
        self.ident = None
        self.status = None
        self.protocol = None
        self.payee = None
        self.lastseen = None
        self.activeseconds = None
        self.lastpaidtime = None
        self.lastpaidblock = None
        self.IP = None
        self.db_id = None
        self.marker = None
        self.modified = False
        self.monitor_changes = False
        self.set_attr_protection()

    def __setattr__(self, name, value):
        if hasattr(self, name) and name not in ('modified', 'marker', 'monitor_changes', '_AttrsProtected__allow_attr_definition'):
            if self.monitor_changes and getattr(self, name) != value:
                self.modified = True
        super().__setattr__(name, value)


def json_cache_wrapper(func, intf, cache_file_ident):
    """
    Wrapper for saving/restoring rpc-call results inside cache files.
    """
    def json_call_wrapper(*args, **kwargs):
        cache_file = intf.config.cache_dir + '/insight_dash_' + cache_file_ident + '.json'

        try:  # looking into cache first
            j = simplejson.load(open(cache_file))
            logging.debug('Loaded data from existing cache file: ' + cache_file)
            return j
        except:
            pass

        # if not found, call the function
        j = func(*args, **kwargs)

        try:
            simplejson.dump(j, open(cache_file, 'w'))
        except Exception as e:
            logging.exception('Cannot save data to a cache file')
            pass
        return j

    return json_call_wrapper


class DashdInterface(WndUtils):
    def __init__(self, config, window, connection=None, on_connection_begin_callback=None,
                 on_connection_try_fail_callback=None, on_connection_finished_callback=None):
        WndUtils.__init__(self, app_config=config)
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

        self.masternodes = []  # cached list of all masternodes (Masternode object)
        self.masternodes_by_ident = {}

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
        self.db_active = False
        self.governanceinfo = None  # cached result of getgovernanceinfo query
        self.http_lock = threading.Lock()

        # open and initialize database for caching masternode data
        db_conn = None
        try:
            tm_start = time.time()
            db_conn = sqlite3.connect(self.config.db_cache_file_name)
            cur = db_conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS MASTERNODES(id INTEGER PRIMARY KEY, ident TEXT, status TEXT," 
                        " protocol TEXT, payee TEXT, last_seen INTEGER, active_seconds INTEGER,"
                        " last_paid_time INTEGER, last_paid_block INTEGER, ip TEXT,"
                        " dmt_active INTEGER, dmt_create_time TEXT, dmt_deactivation_time TEXT)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_MASTERNODES_DMT_ACTIVE ON MASTERNODES(dmt_active)")

            logging.debug("Reading masternodes' data from DB")
            cur.execute("SELECT id, ident, status, protocol, payee, last_seen, active_seconds,"
                        " last_paid_time, last_paid_block, IP from MASTERNODES where dmt_active=1")
            for row in cur.fetchall():
                mn = Masternode()
                mn.db_id = row[0]
                mn.ident = row[1]
                mn.status = row[2]
                mn.protocol = row[3]
                mn.payee = row[4]
                mn.lastseen = row[5]
                mn.activeseconds = row[6]
                mn.lastpaidtime = row[7]
                mn.lastpaidblock = row[8]
                mn.IP = row[9]
                self.masternodes.append(mn)
                self.masternodes_by_ident[mn.ident] = mn

            tm_diff = time.time() - tm_start
            logging.info('DB read time of %d MASTERNODES: %d seconds' % (len(self.masternodes), int(tm_diff)))
            self.db_active = True
        except Exception as e:
            logging.exception('SQLite initialization error')
        finally:
            if db_conn:
                db_conn.close()


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
            logging.debug('Disconnecting')
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
        :return: True if successfully switched or False if there was no another config
        """
        if self.cur_conn_def:
            self.config.conn_cfg_failure(self.cur_conn_def)  # mark connection as defective
        if self.cur_conn_index < len(self.connections)-1:
            idx = self.cur_conn_index + 1
        else:
            idx = 0

        conn = self.connections[idx]
        if conn != self.starting_conn and conn != self.cur_conn_def:
            logging.debug("Trying to switch to another connection: %s" % conn.get_description())
            self.disconnect()
            self.cur_conn_index = idx
            self.cur_conn_def = conn
            if not self.open():
                return self.switch_to_next_config()
            else:
                return True
        else:
            logging.warning('Failed to connect: no another connection configurations.')
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
            logging.debug("Trying to open connection: %s" % self.cur_conn_def.get_description())
            if self.cur_conn_def.use_ssh_tunnel:
                # RPC over SSH
                while True:
                    self.ssh = DashdSSH(self.cur_conn_def.ssh_conn_cfg.host, self.cur_conn_def.ssh_conn_cfg.port,
                                        self.cur_conn_def.ssh_conn_cfg.username)
                    try:
                        logging.debug('starting ssh.connect')
                        self.ssh.connect()
                        logging.debug('finished ssh.connect')
                        break
                    except Exception as e:
                        logging.error('error in ssh.connect')
                        raise

                # configure SSH tunnel
                # get random local unprivileged port number to establish SSH tunnel
                success = False
                local_port = None
                for try_nr in range(1, 10):
                    try:
                        logging.debug('beginning ssh.open_tunnel')
                        local_port = randint(2000, 50000)
                        self.ssh.open_tunnel(local_port,
                                             self.cur_conn_def.host,
                                             int(self.cur_conn_def.port))
                        success = True
                        break
                    except Exception as e:
                        logging.error('error in ssh.open_tunnel loop')
                        pass
                logging.debug('finished ssh.open_tunnel loop')
                if not success:
                    logging.error('finished ssh.open_tunnel loop with error')
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
            logging.debug('AuthServiceProxy begin: %s' % self.rpc_url)
            self.proxy = AuthServiceProxy(self.rpc_url, timeout=1000, connection=self.http_conn)
            logging.debug('AuthServiceProxy end')

            try:
                if self.on_connection_begin_callback:
                    try:
                        # make the owner know, we are connecting
                        logging.debug('on_connection_begin_callback begin')
                        self.on_connection_begin_callback()
                        logging.debug('on_connection_begin_callback end')
                    except:
                        pass

                # check the connection
                self.http_conn.connect()
                logging.debug('Successfully connected')

                if self.on_connection_finished_callback:
                    try:
                        # make the owner know, we successfully finished connection
                        self.on_connection_finished_callback()
                    except:
                        logging.exception('on_connection_finished_callback call exception')
            except:
                logging.exception('Connection failed')
                if self.on_connection_try_fail_callback:
                    try:
                        # make the owner know, connection attempt failed
                        self.on_connection_try_fail_callback()
                    except:
                        logging.exception('on_connection_try_fail_callback call exception')
                raise
            finally:
                logging.debug('http_conn.close()')
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
    def get_masternodelist(self, *args, skip_cache=False):
        def parse_mns(mns_raw):
            """
            Parses dictionary of strings returned from the RPC to Masternode object list.
            :param mns_raw: Dict of masternodes in format of RPC masternodelist command
            :return: list of Masternode object
            """
            ret_list = []
            for mn_id in mns_raw.keys():
                mn_raw = mns_raw.get(mn_id)
                mn_raw = mn_raw.strip()
                elems = mn_raw.split()
                if len(elems) >= 8:
                    mn = Masternode()
                    mn.status, mn.protocol, mn.payee, mn.lastseen, mn.activeseconds, mn.lastpaidtime, \
                    mn.lastpaidblock, mn.IP = elems
                    mn.lastseen = int(mn.lastseen)
                    mn.activeseconds = int(mn.activeseconds)
                    mn.lastpaidtime = int(mn.lastpaidtime)
                    mn.lastpaidblock = int(mn.lastpaidblock)
                    mn.ident = mn_id
                    ret_list.append(mn)
            return ret_list

        def update_masternode_data(existing_mn, new_data, cursor):
            # update cached masternode's properties
            existing_mn.modified = False
            existing_mn.monitor_changes = True
            existing_mn.ident = new_data.ident
            existing_mn.status = new_data.status
            existing_mn.protocol = new_data.protocol
            existing_mn.payee = new_data.payee
            existing_mn.lastseen = new_data.lastseen
            existing_mn.activeseconds = new_data.activeseconds
            existing_mn.lastpaidtime = new_data.lastpaidtime
            existing_mn.lastpaidblock = new_data.lastpaidblock
            existing_mn.IP = new_data.IP

            # ... and finally update MN db record
            if cursor and existing_mn.modified:
                cursor.execute("UPDATE MASTERNODES set ident=?, status=?, protocol=?, payee=?,"
                               " last_seen=?, active_seconds=?, last_paid_time=?, "
                               " last_paid_block=?, ip=?"
                               "WHERE id=?",
                               (new_data.ident, new_data.status, new_data.protocol, new_data.payee,
                                new_data.lastseen, new_data.activeseconds, new_data.lastpaidtime,
                                new_data.lastpaidblock, new_data.IP, new_data.db_id))

        if self.open():

            if len(args) == 1 and args[0] == 'full':
                last_read_time = self.get_cache_value('MasternodesLastReadTime', 0, int)
                logging.debug("MasternodesLastReadTime: %d" % last_read_time)

                if self.masternodes and not skip_cache and \
                   int(time.time()) - last_read_time < MASTERNODES_CACHE_VALID_SECONDS:
                    # if masternode list has been read before, return cached version
                    return self.masternodes
                else:
                    logging.debug('Loading masternode list from Dash daemon...')
                    mns = self.proxy.masternodelist(*args)
                    mns = parse_mns(mns)
                    logging.debug('Finished loading masternode list')

                    if self.db_active:
                        # save masternodes to db cache
                        db_conn = None
                        db_modified = False
                        try:
                            db_conn = sqlite3.connect(self.config.db_cache_file_name)
                            cur = db_conn.cursor()

                            # mark already cached masternodes to identify those to delete
                            for mn in self.masternodes:
                                mn.marker = False

                            for mn in mns:
                                # check if new-read masternode is alterady in the cache
                                existing_mn = self.masternodes_by_ident.get(mn.ident)
                                if not existing_mn:
                                    mn.marker = True
                                    self.masternodes.append(mn)
                                    self.masternodes_by_ident[mn.ident] = mn

                                    cur.execute("INSERT INTO MASTERNODES(ident, status, protocol, payee, last_seen,"
                                                " active_seconds, last_paid_time, last_paid_block, ip, dmt_active,"
                                                " dmt_create_time) "
                                                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                                (mn.ident, mn.status, mn.protocol, mn.payee, mn.lastseen,
                                                 mn.activeseconds, mn.lastpaidtime, mn.lastpaidblock, mn.IP, 1,
                                                 datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                                    mn.db_id = cur.lastrowid
                                    db_modified = True
                                else:
                                    existing_mn.marker = True
                                    update_masternode_data(existing_mn, mn, cur)
                                    db_modified = True

                            # remove from cache masternodes no longer existing
                            for mn_index in reversed(range(len(self.masternodes))):
                                mn = self.masternodes[mn_index]

                                if not mn.marker:
                                    if self.db_active:
                                        cur.execute("UPDATE MASTERNODES set dmt_active=0, dmt_deactivation_time=?"
                                                    "WHERE ID=?",
                                                    (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                                    mn.db_id))
                                        db_modified = True
                                    self.masternodes_by_ident.pop(mn.ident,0)
                                    del self.masternodes[mn_index]

                            self.set_cache_value('MasternodesLastReadTime', int(time.time()))
                        except Exception as e:
                            logging.exception('SQLite initialization error')
                        finally:
                            if db_conn:
                                if db_modified:
                                    db_conn.commit()
                                db_conn.close()
                    else:
                        # cache database is not availabale, apply retrieved data to self.masternodes list
                        for mn in mns:
                            existing_mn = self.masternodes_by_ident.get(mn.ident)
                            if existing_mn:
                                update_masternode_data(existing_mn, mn, None)
                            else:
                                self.masternodes.append(mn)
                                self.masternodes_by_ident[mn.ident] = mn

                    return self.masternodes
            else:
                mns = self.proxy.masternodelist(*args)
                mns = parse_mns(mns)
                return mns
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
            return json_cache_wrapper(self.proxy.getrawtransaction, self, 'tx-' + str(verbose) + '-' + txid)(txid, verbose)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getblockhash(self, blockid):
        if self.open():
            return json_cache_wrapper(self.proxy.getblockhash, self, 'blockhash-' + str(blockid))(blockid)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getblockheader(self, blockhash):
        if self.open():
            return json_cache_wrapper(self.proxy.getblockheader, self, 'blockheader-' + str(blockhash))(blockhash)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def validateaddress(self, address):
        if self.open():
            return self.proxy.validateaddress(address)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def decoderawtransaction(self, rawtx):
        if self.open():
            return self.proxy.decoderawtransaction(rawtx)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def sendrawtransaction(self, tx):
        if self.open():
            return self.proxy.sendrawtransaction(tx)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getcurrentvotes(self, hash):
        if self.open():
            return self.proxy.getcurrentvotes(hash)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def gobject(self, *args):
        if self.open():
            return self.proxy.gobject(*args)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def masternode(self, *args):
        if self.open():
            return self.proxy.masternode(*args)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getgovernanceinfo(self, skip_cache=False):
        if self.open():
            if skip_cache or not self.governanceinfo:
                self.governanceinfo = self.proxy.getgovernanceinfo()
            return self.governanceinfo
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def voteraw(self, masternode_tx_hash, masternode_tx_index, governance_hash, vote_signal, vote, sig_time, vote_sig):
        if self.open():
            return self.proxy.voteraw(masternode_tx_hash, masternode_tx_index, governance_hash, vote_signal, vote,
                                      sig_time, vote_sig)
        else:
            raise Exception('Not connected')

