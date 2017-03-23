#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03

import os
import re
from configparser import ConfigParser
from os.path import expanduser


APP_NAME_SHORT = 'DashMasternodeTool'
APP_NAME_LONG = 'Dash Masternode Tool'


class AppConfig(object):
    def __init__(self):
        self.dashd_connect_method = 'rpc'  # values: 'rpc', 'rpc_ssh'
        self.rpc_user = ''
        self.rpc_password = ''
        self.rpc_ip = '127.0.0.1'
        self.rpc_port = '9998'

        # configuration for RPC over SSH mode
        self.ros_ssh_host = ''
        self.ros_ssh_port = '22'
        self.ros_ssh_username = ''
        self.ros_rpc_bind_ip = ''
        self.ros_rpc_bind_port = '9998'
        self.ros_rpc_username = ''
        self.ros_rpc_password = ''

        self.masternodes = []
        self.last_bip32_base_path = ''
        self.bip32_recursive_search = True
        self.modified = False
        home_dir = expanduser('~')
        app_user_dir = os.path.join(home_dir, APP_NAME_SHORT)
        if not os.path.exists(app_user_dir):
            os.makedirs(app_user_dir)
        self.app_config_file_name = os.path.join(app_user_dir, 'config.ini')

    def read_from_file(self):
        if os.path.exists(self.app_config_file_name):
            config = ConfigParser()
            try:
                section = 'CONFIG'
                config.read(self.app_config_file_name)
                self.dashd_connect_method = config.get(section, 'dashd_connect_method', fallback='rpc')
                self.rpc_user = config.get(section, 'rpc_user', fallback='')
                self.rpc_password = config.get(section, 'rpc_password', fallback='')
                self.rpc_ip = config.get(section, 'rpc_ip', fallback='')
                self.rpc_port = config.get(section, 'rpc_port', fallback='8889')
                self.ros_ssh_host = config.get(section, 'ros_ssh_host', fallback='')
                self.ros_ssh_port = config.get(section, 'ros_ssh_port', fallback='22')
                self.ros_ssh_username = config.get(section, 'ros_ssh_username', fallback='')
                self.ros_rpc_bind_ip = config.get(section, 'ros_rpc_bind_ip', fallback='127.0.0.1')
                self.ros_rpc_bind_port = config.get(section, 'ros_rpc_bind_port', fallback='9998')
                self.ros_rpc_username = config.get(section, 'ros_rpc_username', fallback='')
                self.ros_rpc_password = config.get(section, 'ros_rpc_password', fallback='')
                self.last_bip32_base_path = config.get(section, 'bip32_base_path', fallback="44'/5'/0'/0/0")
                if not self.last_bip32_base_path:
                    self.last_bip32_base_path = "44'/5'/0'/0/0/0"
                self.bip32_recursive_search = config.getboolean(section, 'bip32_recursive', fallback=True)

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
            except Exception as e:
                pass

    def save_to_file(self):
        section = 'CONFIG'
        config = ConfigParser()
        config.add_section(section)
        config.set(section, 'dashd_connect_method', self.dashd_connect_method)
        config.set(section, 'rpc_user', self.rpc_user)
        config.set(section, 'rpc_password', self.rpc_password)
        config.set(section, 'rpc_ip', self.rpc_ip)
        config.set(section, 'rpc_port', str(self.rpc_port))
        config.set(section, 'ros_ssh_host', str(self.ros_ssh_host))
        config.set(section, 'ros_ssh_port', str(self.ros_ssh_port))
        config.set(section, 'ros_ssh_username', str(self.ros_ssh_username))
        config.set(section, 'ros_rpc_bind_ip', str(self.ros_rpc_bind_ip))
        config.set(section, 'ros_rpc_bind_port', str(self.ros_rpc_bind_port))
        config.set(section, 'ros_rpc_username', str(self.ros_rpc_username))
        config.set(section, 'ros_rpc_password', str(self.ros_rpc_password))
        config.set(section, 'bip32_base_path', self.last_bip32_base_path)

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

        with open(self.app_config_file_name, 'w') as f_ptr:
            config.write(f_ptr)
        self.modified = False

    def is_config_complete(self):
        if self.dashd_connect_method == 'rpc':
            if self.rpc_user and self.rpc_password and self.rpc_ip and self.rpc_port:
                return True
        elif self.dashd_connect_method == 'rpc_ssh':
            if self.ros_ssh_host and self.ros_ssh_port and self.ros_ssh_username and self.ros_rpc_bind_ip \
                    and self.ros_rpc_bind_port and self.ros_rpc_username and self.ros_rpc_password:
                return True
        return False

    def get_mn_by_name(self, name):
        for mn in self.masternodes:
            if mn.name == name:
                return mn
        return None

    def add_mn(self, mn):
        if not mn in self.masternodes:
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
