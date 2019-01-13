#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import decimal
import json

import bitcoin
import os
import re
import socket
import sqlite3
import ssl
import threading
import time
import datetime
import logging
from PyQt5.QtCore import QThread
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException, EncodeDecimal
from paramiko import AuthenticationException, PasswordRequiredException, SSHException
from paramiko.ssh_exception import NoValidConnectionsError
from typing import List, Dict, Union
import app_cache
import app_defs
import app_utils
from app_config import AppConfig
from random import randint
from wnd_utils import WndUtils
import socketserver
import select
from PyQt5.QtWidgets import QMessageBox
from psw_cache import SshPassCache
from common import AttrsProtected, CancelException

log = logging.getLogger('dmt.dashd_intf')


try:
    import http.client as httplib
except ImportError:
    import httplib


# how many seconds cached masternodes data are valid; cached masternode data is used only for non-critical
# features
MASTERNODES_CACHE_VALID_SECONDS = 60 * 60  # 60 minutes
TX_SEND_SIMULATION_MODE = False


class ForwardServer (socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            log.debug('Handler, starting ssh_transport.open_channel')
            chan = self.ssh_transport.open_channel(kind='direct-tcpip',
                                                   dest_addr=(self.chain_host, self.chain_port),
                                                   src_addr=self.request.getpeername())
            log.debug('Handler, started ssh_transport.open_channel')
        except Exception as e:
            log.error('open_channel error: ' + str(e))
            if self.broken_conn_callback is not None:
                self.broken_conn_callback()
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
                    log.debug(f'SSH tunnel - sent {len(data)} bytes')
                if chan in r:
                    data = chan.recv(1024)
                    if len(data) == 0:
                        break
                    self.request.send(data)
                    log.debug(f'SSH tunnel - received {len(data)} bytes')
            log.debug('Finishing Handler.handle')
        except socket.error as e:
            log.error('Handler socker.error occurred: ' + str(e))
        except Exception as e:
            log.error('Handler exception occurred: ' + str(e))
        finally:
            chan.close()
            self.request.close()


class SSHTunnelThread(QThread):
    def __init__(self, local_port, remote_ip, remote_port, transport, ready_event,
                 on_connection_broken_callback=None, on_finish_thread_callback=None):
        QThread.__init__(self)
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.transport = transport
        self.ready_event = ready_event
        self.forward_server = None
        self.on_connection_broken_callback = on_connection_broken_callback
        self.on_finish_thread_callback = on_finish_thread_callback
        self.setObjectName('SSHTunnelThread')

    def __del__(self):
        pass

    def stop(self):
        if self.forward_server:
            self.forward_server.shutdown()

    def handler_broken_connection_callback(self):
        try:
            self.stop()
            if self.on_connection_broken_callback is not None:
                self.on_connection_broken_callback()
        except:
            log.exception('Exception while shutting down forward server.')

    def run(self):
        class SubHander(Handler):
            chain_host = self.remote_ip
            chain_port = self.remote_port
            ssh_transport = self.transport
            broken_conn_callback = self.handler_broken_connection_callback

        try:
            self.ready_event.set()
            log.debug('Started SSHTunnelThread, local port forwarding 127.0.0.1:%s -> %s:%s' %
                          (str(self.local_port), self.remote_ip, str(self.remote_port)))
            self.forward_server = ForwardServer(('127.0.0.1', self.local_port), SubHander)
            self.forward_server.serve_forever()
            log.debug('Stopped local port forwarding 127.0.0.1:%s -> %s:%s' %
                          (str(self.local_port), self.remote_ip, str(self.remote_port)))
            if self.on_finish_thread_callback:
                self.on_finish_thread_callback()
        except Exception as e:
            log.exception('SSH tunnel exception occurred')


class UnknownError(Exception):
    pass


class DashdConnectionError(Exception):
    def __init__(self, org_exception):
        Exception.__init__(org_exception)
        self.org_exception = org_exception


class DashdSSH(object):
    def __init__(self, host, port, username, on_connection_broken_callback=None):
        self.host = host
        self.port = port
        self.username = username
        self.ssh = None
        self.channel = None
        self.fw_channel = None
        self.connected = False
        self.connection_broken = False
        self.ssh_thread = None
        self.on_connection_broken_callback = on_connection_broken_callback

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
        if self.ssh is None:
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

                if password is not None:
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

    def on_tunnel_thread_finish(self):
        self.ssh_thread = None

    def open_tunnel(self, local_port, remote_ip, remote_port):
        if self.connected:
            if self.ssh_thread is not None:
                raise Exception('SSH tunnel already open.')

            ready_event = threading.Event()
            self.ssh_thread = SSHTunnelThread(local_port, remote_ip, remote_port, self.ssh.get_transport(), ready_event,
                                              on_connection_broken_callback=self.on_connection_broken_callback,
                                              on_finish_thread_callback=self.on_tunnel_thread_finish)
            self.ssh_thread.start()
            ready_event.wait(10)

            # wait a moment for the tunnel to come-up
            time.sleep(0.1)
            log.debug('Started local port forwarding 127.0.0.1:%s -> %s:%s' %
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
            log.debug('Trying to acquire http_lock')
            self.http_lock.acquire()
            log.debug('Acquired http_lock')
            last_conn_reset_time = None
            for try_nr in range(1, 5):
                try:
                    try:
                        log.debug('Beginning call of "' + str(func) + '"')
                        begin_time = time.time()
                        ret = func(*args, **kwargs)
                        log.debug('Finished call of "' + str(func) + '". Call time: ' +
                                      str(time.time() - begin_time) + 's.')
                        last_exception = None
                        self.mark_cur_conn_cfg_is_ok()
                        break

                    except (ConnectionResetError, ConnectionAbortedError, httplib.CannotSendRequest,
                            BrokenPipeError) as e:
                        log.warning('Error while calling of "' + str(func) + ' (1)". Details: ' + str(e))
                        if last_conn_reset_time:
                            raise DashdConnectionError(e)  # switch to another config if possible
                        else:
                            last_exception = e
                            self.reset_connection()  # rettry with the same connection

                    except JSONRPCException as e:
                        log.error('Error while calling of "' + str(func) + ' (2)". Details: ' + str(e))
                        if e.code == -5 and e.message == 'No information available for address':
                            raise DashdIndexException(e)
                        elif e.error.get('message','').find('403 Forbidden') >= 0 or \
                             e.error.get('message', '').find('502 Bad Gateway') >= 0:
                            self.http_conn.close()
                            raise DashdConnectionError(e)
                        elif e.code in (-32603,):
                            # for these error codes don't retry the request with another rpc connetion
                            #  -32603: failure to verify vote
                            raise
                        else:
                            raise

                    except (socket.gaierror, ConnectionRefusedError, TimeoutError, socket.timeout,
                            NoValidConnectionsError) as e:
                        # exceptions raised most likely by not functioning dashd node; try to switch to another node
                        # if there is any in the config
                        log.warning('Error while calling of "' + str(func) + ' (3)". Details: ' + str(e))
                        raise DashdConnectionError(e)

                except DashdConnectionError as e:
                    # try another net config if possible
                    log.error('Error while calling of "' + str(func) + '" (4). Details: ' + str(e))
                    if not self.switch_to_next_config():
                        self.last_error_message = str(e.org_exception)
                        raise e.org_exception  # couldn't use another conn config, raise last exception
                    else:
                        try_nr -= 1  # another config retries do not count
                        last_exception = e.org_exception
                except Exception:
                    raise
        finally:
            self.http_lock.release()
            log.debug('Released http_lock')

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
        self.ip = None
        self.db_id = None
        self.marker = None
        self.modified = False
        self.monitor_changes = False
        self.queue_position = None
        self.set_attr_protection()

    def __setattr__(self, name, value):
        if hasattr(self, name) and name not in ('modified', 'marker', 'monitor_changes', '_AttrsProtected__allow_attr_definition'):
            if self.monitor_changes and getattr(self, name) != value:
                self.modified = True
        super().__setattr__(name, value)


def json_cache_wrapper(func, intf, cache_file_ident, skip_cache=False):
    """
    Wrapper for saving/restoring rpc-call results inside cache files.
    """
    def json_call_wrapper(*args, **kwargs):
        nonlocal skip_cache, cache_file_ident, intf, func

        fname = '/insight_dash_'
        if intf.app_config.is_testnet():
            fname += 'testnet_'

        cache_file = intf.config.tx_cache_dir + fname + cache_file_ident + '.json'
        if not skip_cache:
            try:  # looking into cache first
                with open(cache_file) as fp:
                    j = json.load(fp, parse_float=decimal.Decimal)
                log.debug('Loaded data from existing cache file: ' + cache_file)
                return j
            except:
                pass

        # if not found in cache, call the original function
        j = func(*args, **kwargs)

        try:
            with open(cache_file, 'w') as fp:
                json.dump(j, fp, default=EncodeDecimal)
        except Exception as e:
            log.exception('Cannot save data to a cache file')
            pass
        return j

    return json_call_wrapper


class DashdInterface(WndUtils):
    def __init__(self, window,
                 on_connection_initiated_callback=None,
                 on_connection_failed_callback=None,
                 on_connection_successful_callback=None,
                 on_connection_disconnected_callback=None):
        WndUtils.__init__(self, app_config=None)

        self.config = None
        self.db_intf = None
        self.connections = []
        self.cur_conn_index = 0
        self.cur_conn_def = None
        self.conf_switch_locked = False

        # below is the connection with which particular RPC call has started; if connection is switched because of
        # problems with some nodes, switching stops if we close round and return to the starting connection
        self.starting_conn = None

        self.masternodes = []  # cached list of all masternodes (Masternode object)
        self.masternodes_by_ident = {}
        self.masternodes_by_ip_port = {}
        self.payment_queue = []

        self.ssh = None
        self.window = window
        self.active = False
        self.rpc_url = None
        self.proxy = None
        self.http_conn = None  # HTTPConnection object passed to the AuthServiceProxy (for convinient connection reset)
        self.on_connection_initiated_callback = on_connection_initiated_callback
        self.on_connection_failed_callback = on_connection_failed_callback
        self.on_connection_successful_callback = on_connection_successful_callback
        self.on_connection_disconnected_callback = on_connection_disconnected_callback
        self.last_error_message = None

        # test transaction entries to be returned by the calls of the self.getaddressdeltas method
        self.test_txs_endpoints_by_address: Dict[str, List[Dict]] = {}
        self.test_txs_by_txid: Dict[str, Dict] = {}

        self.http_lock = threading.RLock()

    def initialize(self, config: AppConfig, connection=None, for_testing_connections_only=False):
        self.config = config
        self.app_config = config
        self.db_intf = self.config.db_intf

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

        if not for_testing_connections_only:
            self.load_data_from_db_cache()

    def load_data_from_db_cache(self):
        self.masternodes.clear()
        self.masternodes_by_ident.clear()
        self.masternodes_by_ip_port.clear()
        cur = self.db_intf.get_cursor()
        cur2 = self.db_intf.get_cursor()
        db_modified = False
        try:
            tm_start = time.time()
            db_correction_duration = 0.0
            log.debug("Reading masternodes' data from DB")
            cur.execute("SELECT id, ident, status, protocol, payee, last_seen, active_seconds,"
                        " last_paid_time, last_paid_block, IP from MASTERNODES where dmt_active=1")
            for row in cur.fetchall():
                db_id = row[0]
                ident = row[1]

                # correct duplicated masternodes issue
                mn_first = self.masternodes_by_ident.get(ident)
                if mn_first is not None:
                    continue

                # delete duplicated (caused by breaking the app while loading)
                tm_start_1 = time.time()
                cur2.execute('DELETE from MASTERNODES where ident=? and id<>?', (ident, db_id))
                if cur2.rowcount > 0:
                    db_modified = True
                db_correction_duration += (time.time() - tm_start_1)

                mn = Masternode()
                mn.db_id = db_id
                mn.ident = ident
                mn.status = row[2]
                mn.protocol = row[3]
                mn.payee = row[4]
                mn.lastseen = row[5]
                mn.activeseconds = row[6]
                mn.lastpaidtime = row[7]
                mn.lastpaidblock = row[8]
                mn.ip = row[9]
                self.masternodes.append(mn)
                self.masternodes_by_ident[mn.ident] = mn
                self.masternodes_by_ip_port[mn.ip] = mn

            tm_diff = time.time() - tm_start
            log.info('DB read time of %d MASTERNODES: %s s, db fix time: %s' %
                         (len(self.masternodes), str(tm_diff), str(db_correction_duration)))
            self.update_mn_queue_values()
        except Exception as e:
            log.exception('SQLite initialization error')
        finally:
            if db_modified:
                self.db_intf.commit()
            self.db_intf.release_cursor()
            self.db_intf.release_cursor()

    def reload_configuration(self):
        """Called after modification of connections' configuration or changes having impact on the file name
        associated to database cache."""

        # get connection list orderd by priority of use
        self.disconnect()
        self.connections = self.config.get_ordered_conn_list()
        self.cur_conn_index = 0
        if len(self.connections):
            self.cur_conn_def = self.connections[self.cur_conn_index]
            self.load_data_from_db_cache()
        else:
            self.cur_conn_def = None

    def disconnect(self):
        if self.active:
            log.debug('Disconnecting')
            if self.ssh:
                self.ssh.disconnect()
                del self.ssh
                self.ssh = None
            self.active = False
            if self.on_connection_disconnected_callback:
                self.on_connection_disconnected_callback()

    def mark_call_begin(self):
        self.starting_conn = self.cur_conn_def

    def switch_to_next_config(self):
        """
        If there is another dashd config not used recently, switch to it. Called only when there was a problem
        with current connection config.
        :return: True if successfully switched or False if there was no another config
        """
        if self.conf_switch_locked:
            return False

        if self.cur_conn_def:
            self.config.conn_cfg_failure(self.cur_conn_def)  # mark connection as defective
        if self.cur_conn_index < len(self.connections)-1:
            idx = self.cur_conn_index + 1
        else:
            idx = 0

        conn = self.connections[idx]
        if conn != self.starting_conn and conn != self.cur_conn_def:
            log.debug("Trying to switch to another connection: %s" % conn.get_description())
            self.disconnect()
            self.cur_conn_index = idx
            self.cur_conn_def = conn
            if not self.open():
                return self.switch_to_next_config()
            else:
                return True
        else:
            log.warning('Failed to connect: no another connection configurations.')
            return False

    def enable_conf_switching(self):
        self.conf_switch_locked = True

    def disable_conf_switching(self):
        self.conf_switch_locked = False

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
                except CancelException:
                    return False
                except (socket.gaierror, ConnectionRefusedError, TimeoutError, socket.timeout,
                        NoValidConnectionsError) as e:
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

    def reset_connection(self):
        """
        Called when communication errors are detected while sending RPC commands. Here we are closing the SSH-tunnel
        (if used) and HTTP connection object to prepare for another try.
        :return:
        """
        if self.active:
            if self.http_conn:
                self.http_conn.close()
            if self.ssh:
                self.ssh.disconnect()
                self.active = False

    def open_internal(self):
        """
        Try to establish connection to dash RPC daemon for current connection config.
        :return: True, if connection successfully establishes, False if user Cancels the operation (not always 
            cancelling will be possible - only when user is prompted for a password).
        """
        if not self.active:
            log.info("Connecting to: %s" % self.cur_conn_def.get_description())
            try:
                # make the owner know, we are connecting
                if self.on_connection_initiated_callback:
                    self.on_connection_initiated_callback()
            except:
                pass

            if self.cur_conn_def.use_ssh_tunnel:
                # RPC over SSH
                if self.ssh is None:
                    self.ssh = DashdSSH(self.cur_conn_def.ssh_conn_cfg.host, self.cur_conn_def.ssh_conn_cfg.port,
                                        self.cur_conn_def.ssh_conn_cfg.username)
                try:
                    log.debug('starting ssh.connect')
                    self.ssh.connect()
                    log.debug('finished ssh.connect')
                except Exception as e:
                    log.error('error in ssh.connect')
                    try:
                        # make the owner know, connection attempt failed
                        if self.on_connection_failed_callback:
                            self.on_connection_failed_callback()
                    except:
                        log.exception('on_connection_try_fail_callback call exception')
                    raise

                # configure SSH tunnel
                # get random local unprivileged port number to establish SSH tunnel
                success = False
                local_port = None
                for try_nr in range(1, 10):
                    try:
                        log.debug(f'beginning ssh.open_tunnel, try: {try_nr}')
                        local_port = randint(2000, 50000)
                        self.ssh.open_tunnel(local_port,
                                             self.cur_conn_def.host,
                                             int(self.cur_conn_def.port))
                        success = True
                        break
                    except Exception as e:
                        log.exception('error in ssh.open_tunnel loop: ' + str(e))
                log.debug('finished ssh.open_tunnel loop')
                if not success:
                    log.error('finished ssh.open_tunnel loop with error')
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
            log.debug('AuthServiceProxy configured to: %s' % self.rpc_url)
            self.proxy = AuthServiceProxy(self.rpc_url, timeout=1000, connection=self.http_conn)

            try:
                # check the connection
                self.http_conn.connect()
                log.debug('Successfully connected AuthServiceProxy')

                try:
                    # make the owner know, we successfully finished connection
                    if self.on_connection_successful_callback:
                        self.on_connection_successful_callback()
                except:
                    log.exception('on_connection_finished_callback call exception')
            except:
                log.exception('Connection failed')

                try:
                    # make the owner know, connection attempt failed
                    if self.on_connection_failed_callback:
                        self.on_connection_failed_callback()

                    if self.ssh:
                        # if there is a ssh connection established earlier, disconnect it because apparently it isn't
                        # functioning
                        self.ssh.disconnect()
                except:
                    log.exception('on_connection_try_fail_callback call exception')
                raise
            finally:
                log.debug('http_conn.close()')
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
    def getinfo(self, verify_node: bool = True):
        if self.open():
            info = self.proxy.getinfo()
            if verify_node:
                node_under_testnet = info.get('testnet')
                if self.config.is_testnet() and not node_under_testnet:
                    raise Exception('This RPC node works under Dash MAINNET, but your current configuration is '
                                    'for TESTNET.')
                elif self.config.is_mainnet() and node_under_testnet:
                    raise Exception('This RPC node works under Dash TESTNET, but your current configuration is '
                                    'for MAINNET.')
            return info
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

    def update_mn_queue_values(self):
        """
        Updates masternode payment queue order values.
        """

        start_tm = time.time()
        self.payment_queue = []
        d = datetime.datetime.utcnow()
        now = int(time.mktime((d.year, d.month, d.day, d.hour, d.minute, d.second, 0, 0, 0)))

        for mn in self.masternodes:
            if mn.status == 'ENABLED':
                # estimate payment queue position: after loading all masternodes
                # queue_position will be used to sort mn list and count the real queue position
                if mn.lastpaidtime == 0:
                    mn.queue_position = mn.activeseconds
                else:
                    lastpaid_ago = now - mn.lastpaidtime
                    mn.queue_position = min(lastpaid_ago, mn.activeseconds)
                self.payment_queue.append(mn)
            else:
                mn.queue_position = None

        duration1 = time.time() - start_tm
        self.payment_queue.sort(key=lambda x: x.queue_position, reverse=True)
        duration2 = time.time() - start_tm

        for mn in self.masternodes:
            if mn.status == 'ENABLED':
                mn.queue_position = self.payment_queue.index(mn)
            else:
                mn.queue_position = None
        duration3 = time.time() - start_tm
        log.info('Masternode queue build time1: %s, time2: %s, time3: %s' %
                     (str(duration1), str(duration2), str(duration3)))

    @control_rpc_call
    def get_masternodelist(self, *args, data_max_age=MASTERNODES_CACHE_VALID_SECONDS) -> List[Masternode]:
        """
        Returns masternode list, read from the Dash network or from the internal cache.
        :param args: arguments passed to the 'masternodelist' RPC call
        :param data_max_age: maximum age (in seconds) of the cached masternode data to used; if the
            cache is older than 'data_max_age', then an RPC call is performed to load newer masternode data;
            value of 0 forces reading of the new data from the network
        :return: list of Masternode objects, matching the 'args' arguments
        """
        def parse_mns(mns_raw) -> List[Masternode]:
            """
            Parses dictionary of strings returned from the RPC to Masternode object list.
            :param mns_raw: Dict of masternodes in format of RPC masternodelist command
            :return: list of Masternode object
            """
            tm_begin = time.time()
            ret_list = []
            for mn_id in mns_raw.keys():
                mn_raw = mns_raw.get(mn_id)
                mn_raw = mn_raw.strip()
                elems = mn_raw.split()
                if len(elems) >= 8:
                    mn = Masternode()
                    # (status, protocol, payee, lastseen, activeseconds, lastpaidtime, pastpaidblock, ip)
                    mn.status, mn.protocol, mn.payee, mn.lastseen, mn.activeseconds, mn.lastpaidtime, \
                        mn.lastpaidblock, mn.ip = elems

                    mn.lastseen = int(mn.lastseen)
                    mn.activeseconds = int(mn.activeseconds)
                    mn.lastpaidtime = int(mn.lastpaidtime)
                    mn.lastpaidblock = int(mn.lastpaidblock)
                    mn.ident = mn_id
                    ret_list.append(mn)
            duration = time.time() - tm_begin
            log.info('Parse masternodelist time: ' + str(duration))
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
            existing_mn.ip = new_data.ip

            # ... and finally update MN db record
            if cursor and existing_mn.modified:
                cursor.execute("UPDATE MASTERNODES set ident=?, status=?, protocol=?, payee=?,"
                               " last_seen=?, active_seconds=?, last_paid_time=?, "
                               " last_paid_block=?, ip=?"
                               "WHERE id=?",
                               (new_data.ident, new_data.status, new_data.protocol, new_data.payee,
                                new_data.lastseen, new_data.activeseconds, new_data.lastpaidtime,
                                new_data.lastpaidblock, new_data.ip, existing_mn.db_id))

        if self.open():

            if len(args) == 1 and args[0] == 'full':
                last_read_time = app_cache.get_value(f'MasternodesLastReadTime_{self.app_config.dash_network}', 0, int)
                log.info("MasternodesLastReadTime: %d" % last_read_time)

                if self.masternodes and data_max_age > 0 and \
                   int(time.time()) - last_read_time < data_max_age:
                    log.info('Using cached masternodelist (data age: %s)' % str(int(time.time()) - last_read_time))
                    return self.masternodes
                else:
                    log.info('Loading masternode list from Dash daemon...')
                    mns = self.proxy.masternodelist(*args)
                    mns = parse_mns(mns)
                    log.info('Finished loading masternode list')

                    # mark already cached masternodes to identify those to delete
                    for mn in self.masternodes:
                        mn.marker = False

                    # save masternodes to the db cache
                    db_modified = False
                    cur = None
                    try:
                        if self.db_intf.db_active:
                            cur = self.db_intf.get_cursor()

                        for mn in mns:
                            # check if newly-read masternode already exists in the cache
                            existing_mn = self.masternodes_by_ident.get(mn.ident)
                            if not existing_mn:
                                mn.marker = True
                                self.masternodes.append(mn)
                                self.masternodes_by_ident[mn.ident] = mn
                                self.masternodes_by_ip_port[mn.ip] = mn

                                if self.db_intf.db_active:
                                    cur.execute("INSERT INTO MASTERNODES(ident, status, protocol, payee, last_seen,"
                                            " active_seconds, last_paid_time, last_paid_block, ip, dmt_active,"
                                            " dmt_create_time) "
                                            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                            (mn.ident, mn.status, mn.protocol, mn.payee, mn.lastseen,
                                             mn.activeseconds, mn.lastpaidtime, mn.lastpaidblock, mn.ip, 1,
                                             datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                                    mn.db_id = cur.lastrowid
                                    db_modified = True
                            else:
                                existing_mn.marker = True
                                update_masternode_data(existing_mn, mn, cur)
                                db_modified = True

                        # remove from the cache masternodes that no longer exist
                        for mn_index in reversed(range(len(self.masternodes))):
                            mn = self.masternodes[mn_index]

                            if not mn.marker:
                                if self.db_intf.db_active:
                                    cur.execute("UPDATE MASTERNODES set dmt_active=0, dmt_deactivation_time=?"
                                                "WHERE ID=?",
                                                (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                                mn.db_id))
                                    db_modified = True
                                self.masternodes_by_ident.pop(mn.ident,0)
                                del self.masternodes[mn_index]

                        app_cache.set_value(f'MasternodesLastReadTime_{self.app_config.dash_network}', int(time.time()))
                        self.update_mn_queue_values()
                    finally:
                        if db_modified:
                            self.db_intf.commit()
                        if cur is not None:
                            self.db_intf.release_cursor()

                    return self.masternodes
            else:
                mns = self.proxy.masternodelist(*args)
                mns = parse_mns(mns)
                return mns
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getaddressbalance(self, addresses):
        if self.open():
            return self.proxy.getaddressbalance({'addresses': addresses})
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getaddressutxos(self, addresses):
        if self.open():
            return self.proxy.getaddressutxos({'addresses': addresses})
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getaddressmempool(self, addresses):
        if self.open():
            return self.proxy.getaddressmempool({'addresses': addresses})
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getrawtransaction(self, txid, verbose, skip_cache=False):
        if self.open():
            if TX_SEND_SIMULATION_MODE:
                tx = self.test_txs_by_txid.get(txid)
                if tx:
                    return tx

            return json_cache_wrapper(self.proxy.getrawtransaction, self, 'tx-' + str(verbose) + '-' + txid,
                                      skip_cache=skip_cache)(txid, verbose)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getblockhash(self, blockid, skip_cache=False):
        if self.open():
            return json_cache_wrapper(self.proxy.getblockhash, self, 'blockhash-' + str(blockid),
                                      skip_cache=skip_cache)(blockid)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getblockheader(self, blockhash, skip_cache=False):
        if self.open():
            return json_cache_wrapper(self.proxy.getblockheader, self, 'blockheader-' + str(blockhash),
                                      skip_cache=skip_cache)(blockhash)
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

    def simulate_send_transaction(self, tx):
        def get_test_tx_entry(address: str) -> List[Dict]:
            txe = self.test_txs_endpoints_by_address.get(address)
            if not txe:
                txe = []
                self.test_txs_endpoints_by_address[address] = txe
            return txe

        dts = self.decoderawtransaction(tx)
        if dts:
            txid = dts.get('txid')
            block_height = self.getblockcount()

            for idx, vin in enumerate(dts['vin']):
                _tx = self.getrawtransaction(vin['txid'], 1)
                if _tx:
                    o = _tx['vout'][vin['vout']]
                    for a in o['scriptPubKey']['addresses']:
                        tx_in = {
                            'txid': txid,
                            'index': idx,
                            'height': block_height,
                            'satoshis': -o['valueSat'],
                            'address': a
                        }
                        get_test_tx_entry(a).append(tx_in)

            for idx, vin in enumerate(dts['vout']):
                for a in vin['scriptPubKey']['addresses']:
                    tx_out = {
                        'txid': txid,
                        'index': idx,
                        'height': block_height,
                        'satoshis': vin['valueSat'],
                        'address': a
                    }
                    get_test_tx_entry(a).append(tx_out)

            _tx = dict(dts)
            _tx['hex'] = tx
            _tx['height'] = block_height
            self.test_txs_by_txid[txid] = _tx

            return dts['txid']

    @control_rpc_call
    def sendrawtransaction(self, tx, use_instant_send):
        if self.open():
            if TX_SEND_SIMULATION_MODE:
                return self.simulate_send_transaction(tx)
            else:
                return self.proxy.sendrawtransaction(tx, False, use_instant_send)
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
    def getgovernanceinfo(self):
        if self.open():
            return self.proxy.getgovernanceinfo()
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getsuperblockbudget(self, block_index):
        if self.open():
            return self.proxy.getsuperblockbudget(block_index)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def voteraw(self, masternode_tx_hash, masternode_tx_index, governance_hash, vote_signal, vote, sig_time, vote_sig):
        if self.open():
            return self.proxy.voteraw(masternode_tx_hash, masternode_tx_index, governance_hash, vote_signal, vote,
                                      sig_time, vote_sig)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getaddressdeltas(self, *args):
        if self.open():
            deltas_list = self.proxy.getaddressdeltas(*args)
            if TX_SEND_SIMULATION_MODE and len(args) > 0 and isinstance(args[0], dict):
                addrs = args[0].get('addresses')
                if addrs:
                    for a in addrs:
                        tep = self.test_txs_endpoints_by_address.get(a)
                        if tep:
                            deltas_list.extend(tep)
            return deltas_list
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getaddresstxids(self, *args):
        if self.open():
            return self.proxy.getaddresstxids(*args)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def protx(self, *args):
        if self.open():
            return self.proxy.protx(*args)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def spork(self, *args):
        if self.open():
            return self.proxy.spork(*args)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def rpc_call(self, command, *args):
        if self.open():
            c = self.proxy.__getattr__(command)
            return c(*args)
        else:
            raise Exception('Not connected')

    def get_spork_value(self, spork: Union[int, str]):
        if isinstance(spork, int):
            name = 'SPORK_' + str(spork)
        else:
            name = spork
        sporks = self.spork('show')
        for spk in sporks:
            if spk.find(name) >= 0:
                return sporks[spk]
        return None

    def get_spork_active(self, spork: Union[int, str]):
        if isinstance(spork, int):
            name = 'SPORK_' + str(spork)
        else:
            name = spork
        sporks = self.spork('active')
        for spk in sporks:
            if spk.find(name) >= 0:
                return sporks[spk]
        return None

    @control_rpc_call
    def listaddressbalances(self, minfee):
        if self.open():
            return self.proxy.listaddressbalances(minfee)
        else:
            raise Exception('Not connected')

