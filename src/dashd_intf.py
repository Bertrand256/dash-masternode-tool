#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
from __future__ import annotations
import decimal
import functools
import json

import os
import re
import socket
import ssl
import threading
import time
import datetime
import logging
from PyQt5.QtCore import QThread
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException, EncodeDecimal
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from paramiko import AuthenticationException, PasswordRequiredException, SSHException
from paramiko.ssh_exception import NoValidConnectionsError, BadAuthenticationType
from typing import List, Dict, Union, Callable, Optional
import app_cache
from app_config import AppConfig
from random import randint
from wnd_utils import WndUtils
import socketserver
import select
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
        class SubHandler(Handler):
            chain_host = self.remote_ip
            chain_port = self.remote_port
            ssh_transport = self.transport
            broken_conn_callback = self.handler_broken_connection_callback

        try:
            self.ready_event.set()
            log.debug('Started SSHTunnelThread, local port forwarding 127.0.0.1:%s -> %s:%s' %
                          (str(self.local_port), self.remote_ip, str(self.remote_port)))
            self.forward_server = ForwardServer(('127.0.0.1', self.local_port), SubHandler)
            self.forward_server.serve_forever()
            log.debug('Stopped local port forwarding 127.0.0.1:%s -> %s:%s' %
                          (str(self.local_port), self.remote_ip, str(self.remote_port)))
            if self.on_finish_thread_callback:
                self.on_finish_thread_callback()
        except Exception:
            log.exception('SSH tunnel exception occurred')


class UnknownError(Exception):
    pass


class DashdConnectionError(Exception):
    def __init__(self, org_exception):
        Exception.__init__(org_exception)
        self.org_exception = org_exception


class DashdSSH(object):
    def __init__(self, host, port, username, on_connection_broken_callback=None, auth_method: str = 'password',
                 private_key_path: str = ''):
        self.host = host
        self.port = port
        self.username = username
        self.ssh = None
        self.channel = None
        self.fw_channel = None
        self.connected = False
        self.connection_broken = False
        self.ssh_thread = None
        self.auth_method = auth_method  #  'any', 'password', 'key_pair', 'ssh_agent'
        self.private_key_path = private_key_path
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

    def connect(self) -> bool:
        import paramiko
        if self.ssh is None:
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        password = None
        pass_message = None

        while True:
            try:
                if self.auth_method == 'any':
                    self.ssh.connect(self.host, port=int(self.port), username=self.username, password=password)
                elif self.auth_method == 'password':
                    self.ssh.connect(self.host, port=int(self.port), username=self.username, password=password,
                                     look_for_keys=False, allow_agent=False)
                elif self.auth_method == 'key_pair':
                    if not self.private_key_path:
                        raise Exception('No RSA private key path was provided.')

                    self.ssh.connect(self.host, port=int(self.port), username=self.username, password=password,
                                     key_filename=self.private_key_path, look_for_keys=False, allow_agent=False)
                elif self.auth_method == 'ssh_agent':
                    self.ssh.connect(self.host, port=int(self.port), username=self.username, password=password,
                                     look_for_keys=False, allow_agent=True)

                self.connected = True
                if password:
                    SshPassCache.save_password(self.username, self.host, password)
                break

            except PasswordRequiredException:
                # private key with password protection is used; ask user for password
                pass_message = "Enter passphrase for <b>private key</b> or password for %s" % \
                               (self.username + '@' + self.host)
                while True:
                    password = SshPassCache.get_password(self.username, self.host, message=pass_message)
                    if password:
                        break

            except BadAuthenticationType:
                raise Exception(str(e))

            except AuthenticationException:
                # This exception will be raised in the following cases:
                #  1. a private key with password protection is used, but the user enters incorrect password
                #  2. a private key exists but user's public key is not added to the server's allowed keys
                #  3. normal login to server is performed but the user enters a bad password
                # So, in the first case, the second query for password will ask for normal password to server, not
                #  for a private key.

                if self.auth_method == 'key_pair':
                    WndUtils.error_msg(message=f'Authentication failed for private key: {self.private_key_path} '
                    f'(username {self.username}).')
                    break
                else:
                    if password is not None:
                        WndUtils.error_msg(message='Incorrect password, try again...')

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
                log.exception(str(e))
                raise

        return self.connected

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
        Try to read the configuration of remote dash daemon. In particular, we need parameters concerning rpc
        configuration.
        :return: tuple (dashd_running, dashd_config_found, dashd config file contents as dict)
                or error string in error occurred.
        """
        config = {}
        if not self.ssh:
            raise Exception('SSH session not ready')
        try:
            # check if dash.conf exists under the default location
            dash_conf_path = '~/.dashcore/dash.conf'
            self.remote_command('ls ' + dash_conf_path)

            conf_lines = self.remote_command('cat ' + dash_conf_path)
            for line in conf_lines:
                elems = [e.strip() for e in line.split('=')]
                if len(elems) == 2:
                    config[elems[0]] = elems[1]
            dashd_config_found = True
            return dashd_config_found, config
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
    Exception for notifying, that dash daemon should have an indexing option tuned on
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


def control_rpc_call(_func=None, *, encrypt_rpc_arguments=False, allow_switching_conns=True):
    """
    Decorator dedicated to functions related to RPC calls, taking care of switching an active connection if the
    current one becomes faulty. It also performs argument encryption for configured RPC calls.
    """

    def control_rpc_call_inner(func):

        @functools.wraps(func)
        def catch_timeout_wrapper(*args, **kwargs):
            ret = None
            last_exception = None
            self = args[0]
            self.mark_call_begin()
            try:
                self.http_lock.acquire()
                last_conn_reset_time = None
                for try_nr in range(1, 5):
                    try:
                        try:
                            if encrypt_rpc_arguments:
                                if self.cur_conn_def:
                                    pubkey = self.cur_conn_def.get_rpc_encryption_pubkey_object()
                                else:
                                    pubkey = None

                                if pubkey:
                                    args_str = json.dumps(args[1:])
                                    max_chunk_size = int(pubkey.key_size / 8) - 75

                                    encrypted_parts = []
                                    while args_str:
                                        data_chunk = args_str[:max_chunk_size]
                                        args_str = args_str[max_chunk_size:]
                                        ciphertext = pubkey.encrypt(data_chunk.encode('ascii'),
                                                                    padding.OAEP(
                                                                        mgf=padding.MGF1(algorithm=hashes.SHA256()),
                                                                        algorithm=hashes.SHA256(),
                                                                        label=None))
                                        encrypted_parts.append(ciphertext.hex())
                                    args = (args[0], 'DMTENCRYPTEDV1') + tuple(encrypted_parts)
                                    log.info(
                                        'Arguments of the "%s" call have been encrypted with the RSA public key of '
                                        'the RPC node.', func.__name__)

                            ret = func(*args, **kwargs)

                            last_exception = None
                            self.mark_cur_conn_cfg_is_ok()
                            break

                        except (ConnectionResetError, ConnectionAbortedError, httplib.CannotSendRequest,
                                BrokenPipeError) as e:
                            # these exceptions usually occur when the established connection gets disconnected after
                            # some time of inactivity; try to reconnect within the same connection configuration
                            log.warning('Error while calling of "' + str(func) + ' (1)". Details: ' + str(e))
                            if last_conn_reset_time:
                                raise DashdConnectionError(e)  # switch to another config if possible
                            else:
                                last_exception = e
                                last_conn_reset_time = time.time()
                                self.reset_connection()  # retry with the same connection

                        except (socket.gaierror, ConnectionRefusedError, TimeoutError, socket.timeout,
                                NoValidConnectionsError) as e:
                            # exceptions raised most likely by not functioning dashd node; try to switch to another node
                            # if there is any in the config
                            log.warning('Error while calling of "' + str(func) + ' (3)". Details: ' + str(e))
                            raise DashdConnectionError(e)

                        except JSONRPCException as e:
                            log.error('Error while calling of "' + str(func) + ' (2)". Details: ' + str(e))
                            err_message = e.error.get('message','').lower()
                            self.http_conn.close()
                            if e.code == -5 and e.message == 'No information available for address':
                                raise DashdIndexException(e)
                            elif err_message.find('502 bad gateway') >= 0 or err_message.find('unknown error') >= 0:
                                raise DashdConnectionError(e)
                            else:
                                raise

                    except DashdConnectionError as e:
                        # try another net config if possible
                        log.error('Error while calling of "' + str(func) + '" (4). Details: ' + str(e))

                        if not allow_switching_conns or not self.switch_to_next_config():
                            self.last_error_message = str(e.org_exception)
                            raise e.org_exception  # couldn't use another conn config, raise last exception
                        else:
                            try_nr -= 1  # another config retry does not count
                            last_exception = e.org_exception
                    except Exception:
                        raise
            finally:
                self.http_lock.release()

            if last_exception:
                raise last_exception
            return ret
        return catch_timeout_wrapper

    if _func is None:
        return control_rpc_call_inner
    else:
        return control_rpc_call_inner(_func)


class Masternode(AttrsProtected):
    def __init__(self):
        AttrsProtected.__init__(self)
        self.ident: Optional[str] = None
        self.status: Optional[str] = None
        self.type: Optional[str] = None  # HighPerformance or Regular
        self.payout_address: Optional[str] = None
        self.lastpaidtime: int = 0
        self.lastpaidblock: int = 0
        self.ip_port = None
        self.protx_hash: Optional[str] = None
        self.db_id = None
        self.marker = None
        self.modified = False
        self.monitor_changes = False
        self.queue_position: Optional[int] = None
        self.collateral_hash: str = ''
        self.collateral_index: int = -1
        self.collateral_address: str = ''
        self.owner_address: str = ''
        self.voting_address: str = ''
        self.pubkey_operator: str = ''
        self.platform_node_id: Optional[str] = None
        self.platform_p2p_port: Optional[int] = None
        self.platform_http_port: Optional[int] = None
        self.operator_reward: float = 0.0
        self.registered_height: int = -1
        self.pose_penalty: int = 0
        self.pose_revived_height: int = -1
        self.pose_ban_height: int = -1
        self.operator_payout_address: str = ''
        self.set_attr_protection()

    def copy_from(self, src: Masternode):
        if self.ident != src.ident or self.status != src.ident or self.payout_address != src.payout_address or \
                self.lastpaidtime != src.lastpaidtime or self.lastpaidblock != src.lastpaidblock or \
                self.ip_port != src.ip_port or self.protx_hash != src.protx_hash or \
                self.queue_position != src.queue_position or self.type != src.type or \
                self.collateral_hash != src.collateral_hash or self.collateral_index != src.collateral_index or \
                self.collateral_address != src.collateral_address or self.owner_address != src.owner_address or \
                self.voting_address != src.voting_address or \
                self.pubkey_operator != src.pubkey_operator or self.platform_node_id != src.platform_node_id or \
                self.platform_p2p_port != src.platform_p2p_port or \
                self.platform_http_port != self.platform_http_port or self.operator_reward != src.operator_reward or \
                self.registered_height != src.registered_height or self.pose_penalty != src.pose_penalty or \
                self.pose_revived_height != src.pose_revived_height or self.pose_ban_height != src.pose_ban_height or \
                self.operator_payout_address != src.operator_payout_address:

            self.ident = src.ident
            self.status = src.status
            self.payout_address = src.payout_address
            self.lastpaidtime = src.lastpaidtime
            self.set_check_attr_value('lastpaidblock', src.lastpaidblock, -1)
            self.ip_port = src.ip_port
            self.protx_hash = src.protx_hash
            self.queue_position = src.queue_position
            self.type = src.type
            self.collateral_hash = src.collateral_hash
            self.collateral_index = src.collateral_index
            self.collateral_address = src.collateral_address
            self.owner_address = src.owner_address
            self.voting_address = src.voting_address
            self.pubkey_operator = src.pubkey_operator
            self.platform_node_id = src.platform_node_id
            self.platform_p2p_port = src.platform_p2p_port
            self.platform_http_port = src.platform_http_port
            self.operator_reward: float = src.operator_reward
            self.set_check_attr_value('registered_height', src.registered_height, -1)
            self.pose_penalty: int = src.pose_penalty
            self.set_check_attr_value('pose_revived_height', src.pose_revived_height, -1)
            self.set_check_attr_value('pose_ban_height', src.pose_ban_height, -1)
            self.operator_payout_address: str = src.operator_payout_address
            self.modified = True

    def copy_from_json(self, mn_ident: str, mn_json: Dict):
        m = re.match(r'([a-zA-F0-9]+)-(\d+)', mn_ident, re.IGNORECASE)
        if m and len(m.groups()) == 2:
            coll_hash = m.group(1)
            coll_index = int(m.group(2))
        else:
            raise Exception('Invalid masternode ident string: ' + mn_ident)

        self.ident = mn_ident
        self.type = mn_json.get('type')
        self.status = mn_json.get('status')
        self.payout_address = mn_json.get('payee')
        self.lastpaidtime = mn_json.get('lastpaidtime', 0)
        self.set_check_attr_value('lastpaidblock', mn_json.get('lastpaidblock'), -1)
        self.ip_port = mn_json.get('address')
        self.protx_hash = mn_json.get('proTxHash')
        self.collateral_hash = coll_hash
        self.collateral_index = coll_index
        self.collateral_address = mn_json.get('collateraladdress')
        self.owner_address = mn_json.get('owneraddress')
        self.voting_address = mn_json.get('votingaddress')
        self.pubkey_operator = mn_json.get('pubkeyoperator')
        self.platform_node_id = mn_json.get('platformNodeID')
        self.platform_p2p_port = mn_json.get('platformP2PPort', 0)
        self.platform_http_port = mn_json.get('platformHTTPPort', 0)

    def copy_from_protx_json(self, protx_json: Dict):
        state = protx_json.get('state')
        if state and isinstance(state, dict):
            self.set_check_attr_value('registered_height', state.get('registeredHeight'), -1)
            self.pose_penalty = state.get('PoSePenalty')
            self.set_check_attr_value('pose_revived_height', state.get('PoSeRevivedHeight'), -1)
            self.set_check_attr_value('pose_ban_height', state.get('PoSeBanHeight'), -1)
            self.operator_payout_address = state.get('operatorPayoutAddress')

    def set_check_attr_value(self, field_name: str, new_value: Optinal[int], default_value: int):
        """
        Set a new value to an attribute, checking if the new value is not None. If it is, then set the default value.
        """
        if new_value is None:
            new_value = -1
        self.__setattr__(field_name, new_value)

    def update_in_db(self, cursor):
        try:
            if self.db_id is None:
                cursor.execute(
                    "INSERT INTO MASTERNODES(ident, status, payee, "
                    " last_paid_time, last_paid_block, ip, protx_hash, "
                    " registered_height, dmt_active, dmt_create_time, queue_position, type, collateral_hash, "
                    " collateral_index, collateral_address, owner_address, voting_address, pubkey_operator,"
                    " platform_node_id, platform_p2p_port, platform_http_port, operator_reward, pose_penalty,"
                    " pose_revived_height, pose_ban_height, operator_payout_address) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (self.ident, self.status, self.payout_address, self.lastpaidtime, self.lastpaidblock,
                     self.ip_port, self.protx_hash, self.registered_height, 1,
                     datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), self.queue_position, self.type,
                     self.collateral_hash, self.collateral_index, self.collateral_address, self.owner_address,
                     self.voting_address, self.pubkey_operator, self.platform_node_id, self.platform_p2p_port,
                     self.platform_http_port, self.operator_reward, self.pose_penalty, self.pose_revived_height,
                     self.pose_ban_height, self.operator_payout_address))
                self.db_id = cursor.lastrowid
            else:
                cursor.execute(
                    "UPDATE MASTERNODES set ident=?, status=?, payee=?, "
                    " last_paid_time=?, last_paid_block=?, ip=?, protx_hash=?, "
                    " registered_height=?, queue_position=?, type=?, collateral_hash=?, "
                    " collateral_index=?, collateral_address=?, owner_address=?, voting_address=?, pubkey_operator=?,"
                    " platform_node_id=?, platform_p2p_port=?, platform_http_port=?, operator_reward=?, pose_penalty=?,"
                    " pose_revived_height=?, pose_ban_height=?, operator_payout_address=? "
                    " WHERE id=?",
                    (self.ident, self.status, self.payout_address, self.lastpaidtime, self.lastpaidblock,
                     self.ip_port, self.protx_hash, self.registered_height, self.queue_position, self.type,
                     self.collateral_hash, self.collateral_index, self.collateral_address, self.owner_address,
                     self.voting_address, self.pubkey_operator, self.platform_node_id, self.platform_p2p_port,
                     self.platform_http_port, self.operator_reward, self.pose_penalty, self.pose_revived_height,
                     self.pose_ban_height, self.operator_payout_address, self.db_id))
        except Exception as e:
            log.exception(str(e))

    def delete_from_db(self, cursor):
        if self.db_id is not None:
            cursor.execute("delete from MASTERNODES where id=?", (self.db_id,))

    def __setattr__(self, name, value):
        if hasattr(self, name) and name not in ('modified', 'marker', 'monitor_changes',
                                                '_AttrsProtected__allow_attr_definition'):
            if self.monitor_changes and getattr(self, name) != value:
                self.modified = True
        super().__setattr__(name, value)


def json_cache_wrapper(func, intf, cache_file_ident, skip_cache=False,
                       accept_cache_data_fun: Optional[Callable[[Dict], bool]]=None):
    """
    Wrapper for saving/restoring rpc-call results inside cache files.
    :param accept_cache_data_fun: reference to an external function verifying whether data read from cache
        can be accepted; if not, a normal call to a rpc node will be executed
    """
    def json_call_wrapper(*args, **kwargs):
        nonlocal skip_cache, cache_file_ident, intf, func

        fname = '/insight_dash_'
        if intf.app_config.is_testnet:
            fname += 'testnet_'

        cache_file = intf.app_config.tx_cache_dir + fname + cache_file_ident + '.json'
        if not skip_cache:
            try:  # looking into cache first
                with open(cache_file) as fp:
                    j = json.load(fp, parse_float=decimal.Decimal)

                if accept_cache_data_fun is None or accept_cache_data_fun(j):
                    return j
            except:
                pass

        # if not found in cache, call the original function
        j = func(*args, **kwargs)

        try:
            with open(cache_file, 'w') as fp:
                json.dump(j, fp, default=EncodeDecimal)
        except Exception:
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

        self.initialized = False
        self.app_config = None
        self.db_intf = None
        self.connections = []
        self.cur_conn_index = 0
        self.cur_conn_def: Optional['DashNetworkConnectionCfg'] = None
        self.block_timestamps: Dict[int, int] = {}

        # below is the connection with which particular RPC call has started; if connection is switched because of
        # problems with some nodes, switching stops if we close round and return to the starting connection
        self.starting_conn = None

        self.masternodes: List[Masternode] = []
        self.masternodes_by_ident: Dict[str, Masternode] = {}
        self.masternodes_by_ip_port: Dict[str, Masternode] = {}

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
        self.mempool_txes: Dict[str, Dict] = {}
        self.http_lock = threading.RLock()

    def initialize(self, config: AppConfig, connection=None, for_testing_connections_only=False):
        self.app_config = config
        self.app_config = config
        self.app_config = config
        self.db_intf = self.app_config.db_intf

        # conn configurations are used from the first item in the list; if one fails, then the next is taken
        if connection:
            # this parameter is used for testing specific connection
            self.connections = [connection]
        else:
            # get a connection list orderd by priority of use
            self.connections = self.app_config.get_ordered_conn_list()

        self.cur_conn_index = 0
        if self.connections:
            self.cur_conn_def = self.connections[self.cur_conn_index]
        else:
            self.cur_conn_def = None

        if not for_testing_connections_only:
            self.load_data_from_db_cache()
        self.initialized = True

    def load_data_from_db_cache(self):
        self.masternodes.clear()
        self.masternodes_by_ident.clear()
        self.masternodes_by_ip_port.clear()
        self.block_timestamps.clear()
        cur = self.db_intf.get_cursor()
        cur2 = self.db_intf.get_cursor()
        db_modified = False
        try:
            tm_start = time.time()
            db_correction_duration = 0.0
            log.debug("Reading masternode data from DB")
            cur.execute("SELECT id, ident, status, payee, last_paid_time, last_paid_block, IP, queue_position, "
                        "protx_hash, type, collateral_hash, collateral_index, collateral_address,"
                        "owner_address, voting_address, pubkey_operator, platform_node_id, platform_p2p_port,"
                        "platform_http_port, registered_height, operator_reward, pose_penalty, "
                        "pose_revived_height, pose_ban_height, operator_payout_address "
                        "from MASTERNODES where dmt_active=1")
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
                mn.payout_address = row[3]
                mn.lastpaidtime = row[4]
                mn.lastpaidblock = row[5]
                mn.ip_port = row[6]
                mn.queue_position = row[7]
                mn.protx_hash = row[8]
                mn.type = row[9]
                mn.collateral_hash = row[10]
                mn.collateral_index = row[11]
                mn.collateral_address = row[12]
                mn.owner_address = row[13]
                mn.voting_address = row[14]
                mn.pubkey_operator = row[15]
                mn.platform_node_id = row[16]
                mn.platform_p2p_port = row[17]
                mn.platform_http_port = row[18]
                mn.registered_height = row[19]
                mn.operator_reward = row[20]
                mn.pose_penalty = row[21]
                mn.pose_revived_height = row[22]
                mn.pose_ban_height = row[23]
                mn.operator_payout_address = row[24]

                self.masternodes.append(mn)
                self.masternodes_by_ident[mn.ident] = mn
                self.masternodes_by_ip_port[mn.ip_port] = mn

            tm_diff = time.time() - tm_start
            log.info('DB read time of %d MASTERNODES: %s s, db fix time: %s' %
                         (len(self.masternodes), str(tm_diff), str(db_correction_duration)))
        except Exception:
            log.exception('SQLite initialization error')
        finally:
            if db_modified:
                self.db_intf.commit()
            self.db_intf.release_cursor()
            self.db_intf.release_cursor()

    def reload_configuration(self):
        """Called after modification of connections' configuration or changes having impact on the file name
        associated to database cache."""

        # get a connection list orderd by priority of use
        self.disconnect()
        self.connections = self.app_config.get_ordered_conn_list()
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
        if self.cur_conn_def:
            self.app_config.conn_cfg_failure(self.cur_conn_def)  # mark connection as defective
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

    def mark_cur_conn_cfg_is_ok(self):
        if self.cur_conn_def:
            self.app_config.conn_cfg_success(self.cur_conn_def)

    def open(self):
        """
        Opens connection to dash RPC. If it fails, then the next enabled conn config will be used, if any exists.
        :return: True if successfully connected, False if the user cancelled the operation. If all of the attempts
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
            cancelling will be possible - only when a user is prompted for a password).
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
                                        self.cur_conn_def.ssh_conn_cfg.username,
                                        auth_method=self.cur_conn_def.ssh_conn_cfg.auth_method,
                                        private_key_path=self.cur_conn_def.ssh_conn_cfg.private_key_path)
                try:
                    log.debug('starting ssh.connect')
                    self.ssh.connect()
                    log.debug('finished ssh.connect')
                except Exception:
                    log.error('error in ssh.connect')
                    try:
                        # make the owner know, a connection attempt failed
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
                    # make the owner know, a connection attempt failed
                    if self.on_connection_failed_callback:
                        self.on_connection_failed_callback()

                    if self.ssh:
                        # if there is an ssh connection established earlier, disconnect it because apparently it isn't
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
    def getblockchaininfo(self, verify_node: bool = True):
        if self.open():
            info = self.proxy.getblockchaininfo()
            if verify_node:
                node_under_testnet = (info.get('chain') == 'test')
                if self.app_config.is_testnet and not node_under_testnet:
                    raise Exception('This RPC node works under Dash MAINNET, but your current configuration is '
                                    'for TESTNET.')
                elif self.app_config.is_mainnet and node_under_testnet:
                    raise Exception('This RPC node works under Dash TESTNET, but your current configuration is '
                                    'for MAINNET.')
            return info
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getnetworkinfo(self):
        if self.open():
            info = self.proxy.getnetworkinfo()
            return info
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def issynchronized(self):
        if self.open():
            try:
                syn = self.proxy.mnsync('status')
                return syn.get('IsSynced')
            except JSONRPCException as e:
                if str(e).lower().find('403 forbidden') >= 0:
                    self.http_conn.close()
                    return True
                else:
                    raise
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

    def reset_masternode_data_cache(self):
        cache_item_name = 'ProtxLastReadTime_' + self.app_config.dash_network
        app_cache.set_value(cache_item_name, 0)
        cache_item_name = f'MasternodesLastReadTime_{self.app_config.dash_network}'
        app_cache.set_value(cache_item_name, 0)

    def _update_mn_queue_values(self, masternodes: List[Masternode]):
        """
        Updates masternode payment queue order values.
        """

        payment_queue = []
        for mn in masternodes:
            if mn.status == 'ENABLED':
                if mn.lastpaidblock > 0:
                    mn.queue_position = mn.lastpaidblock
                else:
                    mn.queue_position = mn.registered_height

                if mn.pose_revived_height > 0 and mn.pose_revived_height > mn.lastpaidblock:
                    mn.queue_position = mn.pose_revived_height

                payment_queue.append(mn)
            else:
                mn.queue_position = None
        payment_queue.sort(key=lambda x: x.queue_position, reverse=False)

        for mn in masternodes:
            if mn.status == 'ENABLED':
                mn.queue_position = payment_queue.index(mn)

    @control_rpc_call
    def get_masternodelist(self, *args, data_max_age=MASTERNODES_CACHE_VALID_SECONDS,
                           feedback_fun: Optional[Callable] = None) -> List[Masternode]:
        """
        Returns a masternode list, read from the Dash network or from the internal cache.
        :param args: arguments passed to the 'masternodelist' RPC call
        :param data_max_age: maximum age (in seconds) of the cached masternode data to used; if the
            cache is older than 'data_max_age', then an RPC call is performed to load newer masternode data;
            value of 0 forces reading of the new data from the network
        :return: list of Masternode objects, matching the 'args' arguments
        """

        if self.open():
            if len(args) == 1 and args[0] == 'json':
                last_read_time = app_cache.get_value(f'MasternodesLastReadTime_{self.app_config.dash_network}', 0, int)
                if self.masternodes and data_max_age > 0 and int(time.time()) - last_read_time < data_max_age:
                    return self.masternodes
                else:
                    log.info('Fetching protx data from network')
                    protx_list = self.proxy.protx('list', 'registered', True)
                    protx_by_hash = {}
                    for protx_json in protx_list:
                        if feedback_fun:
                            feedback_fun()
                        protx_hash = protx_json.get('proTxHash')
                        if protx_hash:
                            protx_by_hash[protx_hash] = protx_json
                    log.info('Finished fetching protx data from network')

                    for mn in self.masternodes:
                        # mark to delete masternode existing in cache but no longer existing on the network
                        mn.marker = False
                        mn.modified = False

                    mns_json = self.proxy.masternodelist(*args)
                    app_cache.set_value(f'MasternodesLastReadTime_{self.app_config.dash_network}', int(time.time()))

                    for mn_id in mns_json.keys():
                        if feedback_fun:
                            feedback_fun()
                        mn_json = mns_json.get(mn_id)
                        mn = self.masternodes_by_ident.get(mn_id)
                        protx_json = protx_by_hash.get(mn_json.get('proTxHash'))
                        if not mn:
                            mn = Masternode()
                            self.masternodes.append(mn)
                            self.masternodes_by_ident[mn_id] = mn
                            self.masternodes_by_ip_port[mn.ip_port] = mn

                        mn.monitor_changes = True
                        mn.copy_from_json(mn_id, mn_json)
                        if protx_json:
                            mn.copy_from_protx_json(protx_json)
                        mn.marker = True
                    self._update_mn_queue_values(self.masternodes)

                    # save masternodes to the db cache
                    db_modified = False
                    cur = None
                    try:
                        if self.db_intf.db_active:
                            cur = self.db_intf.get_cursor()

                        for mn in self.masternodes:
                            if feedback_fun:
                                feedback_fun()

                            if self.db_intf.db_active:
                                if mn.modified:
                                    mn.update_in_db(cur)
                                    mn.modified = False
                                    db_modified = True

                        # remove non-existing masternodes from cache
                        for mn_index in reversed(range(len(self.masternodes))):
                            if feedback_fun:
                                feedback_fun()
                            mn = self.masternodes[mn_index]

                            if not mn.marker:
                                if self.db_intf.db_active:
                                    cur.execute("UPDATE MASTERNODES set dmt_active=0, dmt_deactivation_time=?"
                                                "WHERE ID=?",
                                                (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), mn.db_id))
                                    db_modified = True
                                self.masternodes_by_ident.pop(mn.ident,0)
                                del self.masternodes[mn_index]
                    finally:
                        if db_modified:
                            self.db_intf.commit()
                        if cur is not None:
                            self.db_intf.release_cursor()

                    return self.masternodes
            else:
                mns = self.proxy.masternodelist(*args)
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
    def getrawmempool(self):
        if self.open():
            return self.proxy.getrawmempool()
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getrawtransaction(self, txid, verbose, skip_cache=False):

        def check_if_tx_confirmed(tx_json):
            # cached transaction will not be accepted if the transaction stored in cache file was not confirmed
            if tx_json.get('confirmations'):
                return True
            return False

        if self.open():
            tx_json = json_cache_wrapper(self.proxy.getrawtransaction, self, 'tx-' + str(verbose) + '-' + txid,
                                         skip_cache=skip_cache, accept_cache_data_fun=check_if_tx_confirmed)\
                (txid, verbose)

            return tx_json
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

    @control_rpc_call(allow_switching_conns=False)
    def sendrawtransaction(self, tx, use_instant_send):
        if self.open():
            ni = self.rpc_call(False, False, 'getnetworkinfo')
            if ni.get('version', 180000) >= 180000:
                fee = 0
            else:
                fee = False

            return self.proxy.sendrawtransaction(tx, fee, use_instant_send)
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
            return self.proxy.getaddressdeltas(*args)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def getaddresstxids(self, *args):
        if self.open():
            return self.proxy.getaddresstxids(*args)
        else:
            raise Exception('Not connected')

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

    def rpc_call(self, encrypt_rpc_arguments: bool, allow_switching_conns: bool, command: str, *args):
        def call_command(self, *args):
            c = self.proxy.__getattr__(command)
            return c(*args)

        if self.open():
            call_command.__setattr__('__name__', command)
            fun = control_rpc_call(call_command, encrypt_rpc_arguments=encrypt_rpc_arguments,
                                   allow_switching_conns=allow_switching_conns)
            c = fun(self, *args)
            return c
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def listaddressbalances(self, minfee):
        if self.open():
            return self.proxy.listaddressbalances(minfee)
        else:
            raise Exception('Not connected')

    @control_rpc_call
    def checkfeaturesupport(self, feature_name: str, dmt_version: str, *args) -> Dict:
        if self.open():
            return self.proxy.checkfeaturesupport(feature_name, dmt_version)
        else:
            raise Exception('Not connected')

    def get_block_timestamp(self, block: int):
        ts = self.block_timestamps.get(block)
        if ts is None:
            bhash = self.getblockhash(block)
            bh = self.getblockheader(bhash)
            ts = bh['time']
            self.block_timestamps[block] = ts
        return ts

    def fetch_mempool_txes(self, feedback_fun: Optional[Callable] = None):
        cur_mempool_txes = self.proxy.getrawmempool()

        txes_to_purge = []
        for tx_hash in self.mempool_txes:
            if tx_hash not in cur_mempool_txes:
                txes_to_purge.append(tx_hash)

        for tx_hash in txes_to_purge:
            del self.mempool_txes[tx_hash]

        for tx_hash in cur_mempool_txes:
            if feedback_fun:
                feedback_fun()

            tx = self.mempool_txes.get(tx_hash)
            if not tx:
                tx = self.getrawtransaction(tx_hash, True, skip_cache=True)
                self.mempool_txes[tx_hash] = tx

    def is_protx_update_pending(self, protx_hash: str, ip_port: str = None) -> bool:
        """
        Check whether a protx transaction related to the proregtx passed as an argument exists in mempool.
        :param protx_hash: Hash of the ProRegTx transaction
        :return:
        """

        try:
            for tx_hash in self.mempool_txes:
                tx = self.mempool_txes[tx_hash]
                protx = tx.get('proUpRegTx')
                if not protx:
                    protx = tx.get('proUpRevTx')
                if not protx:
                    protx = tx.get('proUpServTx')
                if not protx:
                    protx = tx.get('proRegTx')
                if protx and (protx.get('proTxHash') == protx_hash) or (ip_port and protx.get('service') == ip_port):
                    return True
            return False
        except Exception:
            return False

