#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import datetime
import json
import os
import re
from configparser import ConfigParser
from os.path import expanduser
from random import randint
from shutil import copyfile
import logging
import bitcoin
from dash_utils import encrypt, decrypt
import app_cache as cache
import default_config


APP_NAME_SHORT = 'DashMasternodeTool'
APP_NAME_LONG = 'Dash Masternode Tool'
MIN_TX_FEE = 10000
APP_CFG_CUR_VERSION = 2  # current version of configuration file format


class AppConfig(object):
    def __init__(self, app_path):
        self.app_path = app_path

        # List of Dash network configurations. Multiple conn configs advantage is to give the possibility to use
        # another config if particular one is not functioning (when using "public" RPC service, it could be node's
        # maintanance)
        self.dash_net_configs = []

        # to distribute the load evenly over "public" RPC services, we choose radom connection (from enabled ones)
        # if it is set to False, connections will be used accoording to its order in dash_net_configs list
        self.random_dash_net_config = True

        # list of all enabled dashd configurations (DashNetworkConnectionCfg) - they will be used accourding to
        # the order in list
        self.active_dash_net_configs = []

        # list of misbehaving dash network configurations - they will have the lowest priority during next
        # connections
        self.defective_net_configs = []

        self.hw_type = 'TREZOR'  # TREZOR or KEEPKEY

        self.check_for_updates = True
        self.backup_config_file = True

        self.masternodes = []
        self.last_bip32_base_path = ''
        self.bip32_recursive_search = True
        self.modified = False
        home_dir = expanduser('~')
        app_user_dir = os.path.join(home_dir, APP_NAME_SHORT)
        if not os.path.exists(app_user_dir):
            os.makedirs(app_user_dir)
        self.cache_dir = os.path.join(app_user_dir, 'cache')
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
        self.app_config_file_name = os.path.join(app_user_dir, 'config.ini')
        cache.init(self.cache_dir)

        # setup logging
        self.log_dir = os.path.join(app_user_dir, 'logs')
        self.log_file = os.path.join(self.log_dir, 'dmt.log')
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        logging.basicConfig(filename=self.log_file, format='%(asctime)s %(levelname)s | %(funcName)s | %(message)s',
                            level=logging.INFO, filemode='w', datefmt='%Y-%m-%d %H:%M:%S')
        logging.info('App started')

        # directory for configuration backups:
        self.cfg_backup_dir = os.path.join(app_user_dir, 'backup')
        if not os.path.exists(self.cfg_backup_dir):
            os.makedirs(self.cfg_backup_dir)

    def read_from_file(self):

        ini_version = None
        was_default_ssh_in_ini_v1 = False
        was_default_direct_localhost_in_ini_v1 = False
        ini_v1_localhost_rpc_cfg = None

        if os.path.exists(self.app_config_file_name):
            config = ConfigParser()
            try:
                section = 'CONFIG'
                config.read(self.app_config_file_name)
                ini_version = config.get(section, 'CFG_VERSION', fallback=1)  # if CFG_VERSION not set it's old config

                if ini_version == 1:
                    # read network config from old file format
                    dashd_connect_method = config.get(section, 'dashd_connect_method', fallback='rpc')
                    rpc_user = config.get(section, 'rpc_user', fallback='')
                    rpc_password = config.get(section, 'rpc_password', fallback='')
                    rpc_ip = config.get(section, 'rpc_ip', fallback='')
                    rpc_port = config.get(section, 'rpc_port', fallback='8889')
                    ros_ssh_host = config.get(section, 'ros_ssh_host', fallback='')
                    ros_ssh_port = config.get(section, 'ros_ssh_port', fallback='22')
                    ros_ssh_username = config.get(section, 'ros_ssh_username', fallback='')
                    ros_rpc_bind_ip = config.get(section, 'ros_rpc_bind_ip', fallback='127.0.0.1')
                    ros_rpc_bind_port = config.get(section, 'ros_rpc_bind_port', fallback='9998')
                    ros_rpc_username = config.get(section, 'ros_rpc_username', fallback='')
                    ros_rpc_password = config.get(section, 'ros_rpc_password', fallback='')

                    # convert dash network config from config version 1
                    if ros_ssh_host and ros_ssh_port and ros_ssh_username and ros_rpc_bind_ip and \
                       ros_rpc_bind_port and ros_rpc_username and ros_rpc_password:

                        # import RPC over SSH configuration
                        cfg = DashNetworkConnectionCfg('rpc')
                        cfg.enabled = True if dashd_connect_method == 'rpc_ssh' else False
                        cfg.host = ros_rpc_bind_ip
                        cfg.port = ros_rpc_bind_port
                        cfg.use_ssl = False
                        cfg.username = ros_rpc_username
                        cfg.password = ros_rpc_password
                        cfg.use_ssh_tunnel = True
                        cfg.ssh_conn_cfg.host = ros_ssh_host
                        cfg.ssh_conn_cfg.port = ros_ssh_port
                        cfg.ssh_conn_cfg.username = ros_ssh_username
                        self.dash_net_configs.append(cfg)
                        was_default_ssh_in_ini_v1 = cfg.enabled

                    if rpc_user and rpc_password and rpc_ip and rpc_port:
                        cfg = DashNetworkConnectionCfg('rpc')
                        cfg.enabled = True if dashd_connect_method == 'rpc' else False
                        cfg.host = rpc_ip
                        cfg.port = rpc_port
                        cfg.use_ssl = False
                        cfg.username = rpc_user
                        cfg.password = rpc_password
                        cfg.use_ssh_tunnel = False
                        self.dash_net_configs.append(cfg)
                        was_default_direct_localhost_in_ini_v1 = cfg.enabled and cfg.host == '127.0.0.1'
                        ini_v1_localhost_rpc_cfg = cfg

                self.last_bip32_base_path = config.get(section, 'bip32_base_path', fallback="44'/5'/0'/0/0")
                if not self.last_bip32_base_path:
                    self.last_bip32_base_path = "44'/5'/0'/0/0"
                self.bip32_recursive_search = config.getboolean(section, 'bip32_recursive', fallback=True)
                self.hw_type = config.get(section, 'hw_type', fallback="TREZOR")
                if self.hw_type not in ('TREZOR', 'KEEPKEY'):
                    self.hw_type = 'TREZOR'
                self.random_dash_net_config = self.value_to_bool(config.get(section, 'random_dash_net_config', fallback='1'))
                self.check_for_updates = self.value_to_bool(config.get(section, 'check_for_updates', fallback='1'))
                self.backup_config_file = self.value_to_bool(config.get(section, 'backup_config_file', fallback='1'))

                for section in config.sections():
                    if re.match('MN\d', section):
                        mn = MasterNodeConfig()
                        mn.name = config.get(section, 'name', fallback='')
                        mn.ip = config.get(section, 'ip', fallback='')
                        mn.port = config.get(section, 'port', fallback='')
                        mn.privateKey = config.get(section, 'private_key', fallback='')
                        mn.collateralBip32Path = config.get(section, 'collateral_bip32_path', fallback='')
                        mn.collateralAddress = config.get(section, 'collateral_address', fallback='')
                        mn.collateralTx = config.get(section, 'collateral_tx', fallback='')
                        mn.collateralTxIndex = config.get(section, 'collateral_tx_index', fallback='')
                        self.masternodes.append(mn)
                    elif re.match('NETCFG\d', section):
                        # read network configuration from new config file format
                        cfg = DashNetworkConnectionCfg('rpc')
                        cfg.enabled = self.value_to_bool(config.get(section, 'enabled', fallback='1'))
                        cfg.host = config.get(section, 'host', fallback='')
                        cfg.port = config.get(section, 'port', fallback='')
                        cfg.use_ssl = self.value_to_bool(config.get(section, 'use_ssl', fallback='0'))
                        cfg.username = config.get(section, 'username', fallback='')
                        cfg.password = config.get(section, 'password', fallback='')
                        cfg.use_ssh_tunnel = self.value_to_bool(config.get(section, 'use_ssh_tunnel', fallback='0'))
                        cfg.ssh_conn_cfg.host = config.get(section, 'ssh_host', fallback='')
                        cfg.ssh_conn_cfg.port = config.get(section, 'ssh_port', fallback='')
                        cfg.ssh_conn_cfg.username = config.get(section, 'ssh_username', fallback='')
                        self.dash_net_configs.append(cfg)
            except Exception:
                pass

        try:
            cfgs = self.decode_connections(default_config.dashd_default_connections)
            if cfgs:
                added, updated = self.import_connections(cfgs, force_import=False)
                if not ini_version or (ini_version == 1 and len(added) > 0):
                    # we are migrating from config.ini version 1
                    if was_default_ssh_in_ini_v1:
                        # in v 1 user used connection to RPC over SSH;
                        # we assume, that he would prefer his previus, trusted server, so we'll deactivate
                        # added default public connections (user will be able to activate them manually)
                        for new in added:
                            new.enabled = False
                    elif was_default_direct_localhost_in_ini_v1:
                        # in the old version user used local dash daemon;
                        # we assume, that user would prefer "public" connections over local, troublesome node
                        # deactivate user's old cfg
                        ini_v1_localhost_rpc_cfg.enabled = False

            if not ini_version or ini_version == 1:
                # we are migrating settings from old configuration file - save config file in a new format
                self.save_to_file()

        except Exception:
            pass

    def save_to_file(self):
        # backup old ini file
        if self.backup_config_file:
            if os.path.exists(self.app_config_file_name):
                tm_str = datetime.datetime.now().strftime('%Y-%m-%d %H_%M')
                back_file_name = os.path.join(self.cfg_backup_dir, 'config_' + tm_str + '.ini')
                try:
                    copyfile(self.app_config_file_name, back_file_name)
                except:
                    pass

        section = 'CONFIG'
        config = ConfigParser()
        config.add_section(section)
        config.set(section, 'CFG_VERSION', str(APP_CFG_CUR_VERSION))
        config.set(section, 'hw_type', self.hw_type)
        config.set(section, 'bip32_base_path', self.last_bip32_base_path)
        config.set(section, 'random_dash_net_config', '1' if self.random_dash_net_config else '0')
        config.set(section, 'check_for_updates', '1' if self.check_for_updates else '0')
        config.set(section, 'backup_config_file', '1' if self.backup_config_file else '0')

        # save mn configuration
        for idx, mn in enumerate(self.masternodes):
            section = 'MN' + str(idx+1)
            config.add_section(section)
            config.set(section, 'name', mn.name)
            config.set(section, 'ip', mn.ip)
            config.set(section, 'port', str(mn.port))
            config.set(section, 'private_key', mn.privateKey)
            config.set(section, 'collateral_bip32_path', mn.collateralBip32Path)
            config.set(section, 'collateral_address', mn.collateralAddress)
            config.set(section, 'collateral_tx', mn.collateralTx)
            config.set(section, 'collateral_tx_index', str(mn.collateralTxIndex))
            mn.modified = False

        # save dash network connections
        for idx, cfg in enumerate(self.dash_net_configs):
            section = 'NETCFG' + str(idx+1)
            config.add_section(section)
            config.set(section, 'method', cfg.method)
            config.set(section, 'enabled', '1' if cfg.enabled else '0')
            config.set(section, 'host', cfg.host)
            config.set(section, 'port', cfg.port)
            config.set(section, 'username', cfg.username)
            config.set(section, 'password', cfg.get_password_encrypted())
            config.set(section, 'use_ssl', '1' if cfg.use_ssl else '0')
            config.set(section, 'use_ssh_tunnel', '1' if cfg.use_ssh_tunnel else '0')
            if cfg.use_ssh_tunnel:
                config.set(section, 'ssh_host', cfg.ssh_conn_cfg.host)
                config.set(section, 'ssh_port', cfg.ssh_conn_cfg.port)
                config.set(section, 'ssh_username', cfg.ssh_conn_cfg.username)
                # SSH password is not saved until HW encrypting feature will be finished

        with open(self.app_config_file_name, 'w') as f_ptr:
            config.write(f_ptr)
        self.modified = False

    def value_to_bool(self, value, default=None):
        """
        Cast value to bool:
          - if value is int, 1 will return True, 0 will return False, others will be invalid
          - if value is str, '1' will return True, '0' will return False, others will be invalid 
        :param value: 
        :return: 
        """
        if isinstance(value, bool):
            v = value
        elif isinstance(value, int):
            if value == 1:
                v = True
            elif value == 0:
                v = False
            else:
                v = default
        elif isinstance(value, str):
            if value == '1':
                v = True
            elif value == '0':
                v = False
            else:
                v = default
        else:
            v = default
        return v

    def is_config_complete(self):
        for cfg in self.dash_net_configs:
            if cfg.enabled:
                return True
        return False

    def prepare_conn_list(self):
        """
        Prepare list of enabled connections for connecting to dash network. 
        :return: list of DashNetworkConnectionCfg objects order randomly (random_dash_net_config == True) or according 
            to order in configuration
        """
        tmp_list = []
        for cfg in self.dash_net_configs:
            if cfg.enabled:
                tmp_list.append(cfg)
        if self.random_dash_net_config:
            ordered_list = []
            while len(tmp_list):
                idx = randint(0, len(tmp_list)-1)
                ordered_list.append(tmp_list[idx])
                del tmp_list[idx]
            self.active_dash_net_configs = ordered_list
        else:
            self.active_dash_net_configs = tmp_list

    def get_ordered_conn_list(self):
        if not self.active_dash_net_configs:
            self.prepare_conn_list()
        return self.active_dash_net_configs

    def conn_config_changed(self):
        self.active_dash_net_configs = []
        self.defective_net_configs = []

    def conn_cfg_failure(self, cfg):
        """
        Mark conn configuration as not functioning (node could be shut down in the meantime) - this connection will
        be sent to the end of queue of active connections.
        :param cfg: 
        :return: 
        """
        self.defective_net_configs.append(cfg)

    def decode_connections(self, raw_conn_list):
        """
        Decodes list of dicts describing connection to a list of DashNetworkConnectionCfg objects.
        :param raw_conn_list: 
        :return: list of connection objects
        """
        connn_list = []
        for conn_raw in raw_conn_list:
            try:
                if 'use_ssh_tunnel' in conn_raw and 'host' in conn_raw and 'port' in conn_raw and \
                   'username' in conn_raw and 'password' in conn_raw and 'use_ssl' in conn_raw:
                    cfg = DashNetworkConnectionCfg('rpc')
                    cfg.use_ssh_tunnel = conn_raw['use_ssh_tunnel']
                    cfg.host = conn_raw['host']
                    cfg.port = conn_raw['port']
                    cfg.username = conn_raw['username']
                    cfg.password = conn_raw['password']
                    cfg.use_ssl = conn_raw['use_ssl']
                    if cfg.use_ssh_tunnel:
                        if 'ssh_host' in conn_raw:
                            cfg.ssh_conn_cfg.host = conn_raw['ssh_host']
                        if 'ssh_port' in conn_raw:
                            cfg.ssh_conn_cfg.port = conn_raw['ssh_port']
                        if 'ssh_user' in conn_raw:
                            cfg.ssh_conn_cfg.port = conn_raw['ssh_user']
                    connn_list.append(cfg)
            except Exception as e:
                print(str(e))
        return connn_list

    def decode_connections_json(self, conns_json):
        """
        Decodes connections list from JSON string.
        :param conns_json: list of connections as JSON string in the following form:
         [
            {
                'use_ssh_tunnel': bool,
                'host': str,
                'port': str,
                'username': str,
                'password': str,
                'use_ssl': bool,
                'ssh_host': str, non-mandatory
                'ssh_port': str, non-mandatory
                'ssh_user': str non-mandatory
            },
        ]
        :return: list of DashNetworkConnectionCfg objects or None if there was an error while importing
        """
        try:
            conns_json = conns_json.strip()
            if conns_json.endswith(','):
                conns_json = conns_json[:-1]
            conns = json.loads(conns_json)

            if isinstance(conns, dict):
                conns = [conns]
            return self.decode_connections(conns)
        except Exception as e:
            return None

    def encode_connections_to_json(self, conns):
        encoded_conns = []

        for conn in conns:
            ec = {
                'use_ssh_tunnel': conn.use_ssh_tunnel,
                'host': conn.host,
                'port': conn.port,
                'username': conn.username,
                'password': conn.get_password_encrypted(),
                'use_ssl': conn.use_ssl
            }
            if conn.use_ssh_tunnel:
                ec['ssh_host'] = conn.ssh_conn_cfg.host
                ec['ssh_port'] = conn.ssh_conn_cfg.port
                ec['ssh_username'] = conn.ssh_conn_cfg.username
            encoded_conns.append(ec)
        return json.dumps(encoded_conns, indent=4)

    def import_connections(self, in_conns, force_import):
        """
        Imports connections from a list. Used at the app's start to process default connections and/or from
          a configuration dialog, when user pastes from a clipboard a string, describing connections he 
          wants to add to the configuration. The latter feature is used for a convenience.
        :param in_conns: list of DashNetworkConnectionCfg objects.
        :returns: tuple (list_of_added_connections, list_of_updated_connections)
        """

        added_conns = []
        updated_conns = []
        if in_conns:
            for nc in in_conns:
                id = nc.get_conn_id()
                # check if new connection is in existing list
                conn = self.get_conn_cfg_by_id(id)
                if not conn:
                    if force_import or not cache.get_value('imported_default_conn_' + nc.get_conn_id(), False, bool):
                        # this new connection was not automatically imported before
                        self.dash_net_configs.append(nc)
                        added_conns.append(nc)
                        cache.set_value('imported_default_conn_' + nc.get_conn_id(), True)
                elif not conn.identical(nc) and force_import:
                    conn.copy_from(nc)
                    updated_conns.append(conn)
        return added_conns, updated_conns

    def get_conn_cfg_by_id(self, id):
        """
        Returns DashNetworkConnectionCfg object by its identifier or None if does not exists.
        :param id: Identifier of the sought connection.
        :return: DashNetworkConnectionCfg object or None if does not exists.
        """
        for conn in self.dash_net_configs:
            if conn.get_conn_id() == id:
                return conn
        return None

    def conn_cfg_success(self, cfg):
        """
        Mark conn configuration as functioning. If it was placed on self.defective_net_configs list before, now
        will be removed from it.
        """
        if cfg in self.defective_net_configs:
            # remove config from list of defective config
            idx = self.defective_net_configs.index(cfg)
            self.defective_net_configs.pop(idx)

    def get_mn_by_name(self, name):
        for mn in self.masternodes:
            if mn.name == name:
                return mn
        return None

    def add_mn(self, mn):
        if mn not in self.masternodes:
            existing_mn = self.get_mn_by_name(mn.name)
            if not existing_mn:
                self.masternodes.append(mn)
            else:
                raise Exception('Masternode with this name: ' + mn.name + ' already exists in configuration')


class MasterNodeConfig:
    def __init__(self):
        self.name = ''
        self.ip = ''
        self.port = '9999'
        self.privateKey = ''
        self.collateralBip32Path = "44'/5'/0'/0/0"
        self.collateralAddress = ''
        self.collateralTx = ''
        self.collateralTxIndex = ''
        self.new = False
        self.modified = False
        self.lock_modified_change = False

    def set_modified(self):
        if not self.lock_modified_change:
            self.modified = True


class SSHConnectionCfg(object):
    def __init__(self):
        self.__host = ''
        self.__port = ''
        self.__username = ''
        self.__password = ''

    @property
    def host(self):
        return self.__host

    @host.setter
    def host(self, host):
        self.__host = host

    @property
    def port(self):
        return self.__port

    @port.setter
    def port(self, port):
        self.__port = port

    @property
    def username(self):
        return self.__username

    @username.setter
    def username(self, username):
        self.__username = username

    @property
    def password(self):
        return self.__password

    @password.setter
    def password(self, password):
        self.__password = password


class DashNetworkConnectionCfg(object):
    def __init__(self, method):
        self.__enabled = True
        self.method = method    # now only 'rpc'
        self.__host = ''
        self.__port = ''
        self.__username = ''
        self.__password = ''
        self.__use_ssl = False
        self.__use_ssh_tunnel = False
        self.__ssh_conn_cfg = SSHConnectionCfg()

    def get_description(self):
        if self.__use_ssh_tunnel:
            desc, host, port = ('SSH ', self.ssh_conn_cfg.host, self.ssh_conn_cfg.port)
        else:
            if self.__use_ssl:
                desc, host, port = ('https://', self.__host, self.__port)
            else:
                desc, host, port = ('', self.__host, self.__port)
        desc = '%s%s:%s' % (desc, (host if host else '???'), (port if port else '???'))
        return desc

    def get_conn_id(self):
        """
        Returns identifier of this connection, built on attributes that uniquely characteraize the connection. 
        :return: 
        """
        if self.__use_ssh_tunnel:
            id = 'SSH:' + self.ssh_conn_cfg.host + ':' + self.__host + ':' + self.__port
        else:
            id = 'DIRECT:' + self.__host
        id = bitcoin.sha256(id)
        return id

    def identical(self, cfg2):
        """
        Checks if connection object passed as an argument has exactly the same values as self object.
        :param cfg2: DashNetworkConnectionCfg object to compare
        :return: True, if objects have identical attributes.
        """
        return self.host == cfg2.host and self.port == cfg2.port and self.username == cfg2.username and \
               self.password == cfg2.password and self.use_ssl == cfg2.use_ssl and \
               self.use_ssh_tunnel == cfg2.use_ssh_tunnel and \
               (not self.use_ssh_tunnel or (self.ssh_conn_cfg.host == cfg2.ssh_conn_cfg.host and
                                            self.ssh_conn_cfg.port == cfg2.ssh_conn_cfg.port and
                                            self.ssh_conn_cfg.username == cfg2.ssh_conn_cfg.username))

    def copy_from(self, cfg2):
        """
        Copies alle attributes from another instance of this class.
        :param cfg2: Another instance of this type from which attributes will be copied.
        """
        self.host = cfg2.host
        self.port = cfg2.port
        self.username = cfg2.username
        self.password = cfg2.password
        self.use_ssh_tunnel = cfg2.use_ssh_tunnel
        self.use_ssl = cfg2.use_ssl
        if self.use_ssh_tunnel:
            self.ssh_conn_cfg.host = cfg2.ssh_conn_cfg.host
            self.ssh_conn_cfg.port = cfg2.ssh_conn_cfg.port
            self.ssh_conn_cfg.username = cfg2.ssh_conn_cfg.username

    def is_http_proxy(self):
        """
        Returns if current config is a http proxy. Method is not very brilliant for now: we assume, that 
        proxy uses SSL while normal, "local" dashd does not. 
        """
        if self.__use_ssl:
            return True
        else:
            return False

    @property
    def enabled(self):
        return self.__enabled

    @enabled.setter
    def enabled(self, active):
        if not isinstance(active, bool):
            raise Exception('Invalid type of "enabled" argument')
        else:
            self.__enabled = active

    @property
    def method(self):
        return self.__method

    @method.setter
    def method(self, method):
        if method not in ('rpc'):
            raise Exception('Not allowed method type: %s' % method)
        self.__method = method

    @property
    def host(self):
        return self.__host

    @host.setter
    def host(self, host):
        self.__host = host

    @property
    def port(self):
        return self.__port

    @port.setter
    def port(self, port):
        if isinstance(port, int):
            port = str(port)
        self.__port = port

    @property
    def username(self):
        return self.__username

    @username.setter
    def username(self, username):
        self.__username = username

    @property
    def password(self):
        return self.__password

    @password.setter
    def password(self, password):
        try:
            # check if password is a hexadecimal string - then it probably is an encrypted string with AES
            int(password, 16)
            p = decrypt(password, APP_NAME_LONG)
            password = p
        except Exception as e:
            pass

        self.__password = password

    def get_password_encrypted(self):
        try:
            return encrypt(self.__password, APP_NAME_LONG)
        except:
            return self.__password

    @property
    def use_ssl(self):
        return self.__use_ssl

    @use_ssl.setter
    def use_ssl(self, use_ssl):
        if not isinstance(use_ssl, bool):
            raise Exception('Ivalid type of "use_ssl" argument')
        self.__use_ssl = use_ssl

    @property
    def use_ssh_tunnel(self):
        return self.__use_ssh_tunnel

    @use_ssh_tunnel.setter
    def use_ssh_tunnel(self, use_ssh_tunnel):
        if not isinstance(use_ssh_tunnel, bool):
            raise Exception('Ivalid type of "use_ssh_tunnel" argument')
        self.__use_ssh_tunnel = use_ssh_tunnel

    @property
    def ssh_conn_cfg(self):
        return self.__ssh_conn_cfg

