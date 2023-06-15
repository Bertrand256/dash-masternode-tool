#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import argparse
import codecs
import datetime
import glob
import json
import os
import re
import copy
import shutil
import subprocess
import sys
from io import StringIO
from configparser import ConfigParser
from random import randint
from shutil import copyfile
import logging
from typing import Optional, Callable, Dict, Tuple, List, Any
from enum import Enum
import bitcoin
from logging.handlers import RotatingFileHandler

import qdarkstyle
import simplejson
import hashlib
from PyQt5 import QtCore
from PyQt5.QtCore import QLocale, QObject
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import QMessageBox, QWidget
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app_defs
import dash_utils
from app_defs import APP_NAME_LONG, APP_DATA_DIR_NAME, DEFAULT_LOG_FORMAT, get_known_loggers
from app_utils import encrypt, decrypt
import app_cache
import default_config
import app_utils
from common import CancelException
from db_intf import DBCache
from encrypted_files import read_file_encrypted, write_file_encrypted
from hw_common import HWType, HWNotConnectedException
from wnd_utils import WndUtils, get_widget_font_color_blue, get_widget_font_color_green

CURRENT_CFG_FILE_VERSION = 7
CACHE_ITEM_LOGGERS_LOGLEVEL = 'LoggersLogLevel'
CACHE_ITEM_LOG_FORMAT = 'LogFormat'
GLOBAL_SETTINGS_FILE_NAME = 'dmt_global_settings.json'

DMN_ROLE_OWNER = 0x1
DMN_ROLE_OPERATOR = 0x2
DMN_ROLE_VOTING = 0x4


class MasternodeType(Enum):
    REGULAR = 1
    HPMN = 2


class InputKeyType:
    PRIVATE = 1
    PUBLIC = 2


class AppFeatureStatus(QObject):
    # Priority of the feature value.
    #  0: default value implemented in the source code
    #  2: value read from the app cache
    #  4: value read from the project GitHub repository (can be lowered or raised)
    #  6: value read from the Dash network (the highest priority by default)
    PRIORITY_DEFAULT = 0
    PRIORITY_APP_CACHE = 2
    PRIORITY_NETWORK = 6

    value_changed = QtCore.pyqtSignal(object, int)  # args: object being changed, new value

    def __init__(self, initial_value, initial_priority, initial_message: str = ''):
        QObject.__init__(self)
        self.__value = initial_value
        self.__priority = initial_priority
        self.__message = initial_message

    def set_value(self, value, priority, message: str = ''):
        if priority is not None and (self.__priority is None or priority >= self.__priority) and value is not None:
            if self.__value != value:
                changed = True
            else:
                changed = False
            self.__value = value
            self.__priority = priority
            self.__message = message
            if changed:
                self.value_changed.emit(self, value)

    def get_value(self):
        return self.__value

    def get_message(self):
        return self.__message

    def reset(self):
        self.__value = None
        self.__priority = None


class AppDeveloperContact:
    """
    Stores contact information for the application developer.
    """
    def __init__(self, method_name: str, user_id: str, url: str):
        self.method_name = method_name
        self.user_id = user_id
        self.url = url


class AppConfig(QObject):
    display_app_message = QtCore.pyqtSignal(int, str, object)

    def __init__(self, ui_dark_mode_activated: bool):
        QObject.__init__(self)
        self.initialized = False
        self.app_dir = ''  # will be passed in the init method
        self.app_version = ''

        # Hash of the configuration data, last saved to disk. If None, config isn't saved or read from disk yet.
        self.config_file_data_hash: Optional[str] = None

        self.global_config = Optional[app_cache.AppCache]
        QLocale.setDefault(app_utils.get_default_locale())
        self.date_format = app_utils.get_default_locale().dateFormat(QLocale.ShortFormat)
        self.date_time_format = app_utils.get_default_locale().dateTimeFormat(QLocale.ShortFormat)
        self._internal_ui_dark_mode_activated = ui_dark_mode_activated
        self.app_dev_contact: List[AppDeveloperContact] = []

        # List of Dash network configurations. Multiple conn configs advantage is to give the possibility to use
        # another config if a particular one is not functioning (when using "public" RPC service, it could be node's
        # maintenance)
        self.dash_net_configs: List[DashNetworkConnectionCfg] = []

        # to distribute the load evenly over "public" RPC services, we choose random connection (from enabled ones)
        # if it is set to False, connections will be used according to its order in dash_net_configs list
        self.random_dash_net_config = True

        # list of all enabled dashd configurations (DashNetworkConnectionCfg) - they will be used according to
        # the order in list
        self.active_dash_net_configs = []

        # list of misbehaving dash network configurations - they will have the lowest priority during next
        # connections
        self.defective_net_configs = []

        # the contents of the app-params.json configuration file read from the project GitHub repository
        self._remote_app_params = {}
        self._dash_blockchain_info = {}
        self.feature_register_dmn_automatic = AppFeatureStatus(True, 0, '')
        self.feature_update_registrar_automatic = AppFeatureStatus(True, 0, '')
        self.feature_update_service_automatic = AppFeatureStatus(True, 0, '')
        self.feature_revoke_operator_automatic = AppFeatureStatus(True, 0, '')
        self.feature_new_bls_scheme = AppFeatureStatus(True, 0, '')

        # obsolete and will be removed in the future (we are leaving it to
        # preserve compatibility of the config file with older versions)
        self.__hw_type: Optional[HWType] = None

        # Keepkey passphrase UTF8 chars encoding:
        #  NFC: compatible with official Keepkey client app
        #  NFKD: compatible with Trezor
        self.hw_keepkey_psw_encoding = 'NFC'

        self.dash_network = 'MAINNET'
        self.block_explorer_tx_mainnet: str = ''
        self.block_explorer_addr_mainnet: str = ''
        self.block_explorer_tx_testnet: str = ''
        self.block_explorer_addr_testnet: str = ''
        self.tx_api_url_mainnet: str = ''
        self.tx_api_url_testnet: str = ''
        self.dash_central_proposal_api: str = ''
        self.dash_nexus_proposal_api: str = ''

        # public RPC connection configurations
        self.public_conns_mainnet: Dict[str, DashNetworkConnectionCfg] = {}
        self.public_conns_testnet: Dict[str, DashNetworkConnectionCfg] = {}

        self.check_for_updates = True
        self.backup_config_file = True
        self.read_proposals_external_attributes = True  # if True, some additional attributes will be downloaded from
        # external sources
        self.dont_use_file_dialogs = False
        self.confirm_when_voting = True
        self.add_random_offset_to_vote_time = True  # To avoid identifying one user's masternodes by vote time
        self._proposal_vote_time_offset_lower: int = -30  # in minutes
        self._proposal_vote_time_offset_upper: int = 30
        self.proposal_vote_time_offset_min: int = -60
        self.proposal_vote_time_offset_max: int = 60
        self.csv_delimiter = ';'
        self.masternodes = []
        self.last_bip32_base_path = ''
        self.bip32_recursive_search = True
        self.cache_dir = ''
        self.tx_cache_dir = ''
        self.app_config_file_name = ''
        self.log_dir = ''
        self.log_file = ''
        self.log_level_str = ''
        self.db_intf: Optional[DBCache] = None
        self.db_cache_file_name = ''
        self.cfg_backup_dir = ''
        self.app_last_version = ''
        self.data_dir = ''
        self.encrypt_config_file = False
        self.config_file_encrypted = False
        self.fetch_network_data_after_start = True
        self.show_dash_value_in_fiat = True
        self.ui_use_dark_mode = False  # Use dark mode independently of the OS settings
        self.show_network_masternodes_tab = False

        # attributes related to encryption cache data with hardware wallet:
        self.hw_generated_key = b"\xab\x0fs}\x8b\t\xb4\xc3\xb8\x05\xba\xd1\x96\x9bq`I\xed(8w\xbf\x95\xf0-\x1a\x14\xcb\x1c\x1d+\xcd"
        self.hw_encryption_key = None
        self.fernet = None
        self.log_handler = None

        # options for trezor:
        self.trezor_webusb = True
        self.trezor_bridge = True
        self.trezor_udp = True
        self.trezor_hid = True
        self.reset_configuration()

        try:
            self.default_rpc_connections = self.decode_connections(default_config.dashd_default_connections)
        except Exception:
            self.default_rpc_connections = []
            logging.exception('Exception while parsing default RPC connections.')

    @staticmethod
    def get_default_user_data_dir():
        user_home_dir = os.path.expanduser('~')

        # below: let's currently stick to v5 dir; in the future we're going to migrate to a new configuraion file
        # format that will stop using the configuration version number in the directory name
        app_user_data_dir = os.path.join(user_home_dir, APP_DATA_DIR_NAME + '-v5')
        return app_user_data_dir

    @staticmethod
    def get_default_global_settings_file_name():
        return os.path.join(AppConfig.get_default_user_data_dir(), GLOBAL_SETTINGS_FILE_NAME)

    def init(self, app_dir):
        """ Initialize configuration after opening the application. """
        self.app_dir = app_dir
        app_defs.APP_PATH = app_dir
        app_defs.APP_IMAGE_DIR = self.get_app_img_dir()

        try:
            with open(os.path.join(app_dir, 'version.txt')) as fptr:
                lines = fptr.read().splitlines()
                self.app_version = app_utils.extract_app_version(lines)
        except:
            pass

        self.global_config = app_cache.AppCache(self.app_version)

        parser = argparse.ArgumentParser()
        parser.add_argument('--config', help="Path to a configuration file", dest='config')
        parser.add_argument('--data-dir', help="Root directory for configuration file, cache and log subdirs",
                            dest='data_dir')
        parser.add_argument('--scan-for-ssh-agent-vars', type=app_utils.str2bool,
                            help="If 0, skip scanning shell profile files for the SSH_AUTH_SOCK env variable "
                                 "(Mac only)", dest='scan_for_ssh_agent_vars', default=True)
        parser.add_argument('--trezor-webusb', type=app_utils.str2bool, help="Disable WebUsbTransport for Trezor",
                            dest='trezor_webusb', default=True)
        parser.add_argument('--trezor-bridge', type=app_utils.str2bool, help="Disable BridgeTransport for Trezor",
                            dest='trezor_bridge', default=True)
        parser.add_argument('--trezor-udp', type=app_utils.str2bool, help="Disable UdpTransport for Trezor",
                            dest='trezor_udp', default=True)
        parser.add_argument('--trezor-hid', type=app_utils.str2bool, help="Disable HidTransport for Trezor",
                            dest='trezor_hid', default=True)

        args = parser.parse_args()
        self.trezor_webusb = args.trezor_webusb
        self.trezor_bridge = args.trezor_bridge
        self.trezor_udp = args.trezor_udp
        self.trezor_hid = args.trezor_hid

        app_user_dir = ''
        if args.data_dir:
            if os.path.exists(args.data_dir):
                if os.path.isdir(args.data_dir):
                    app_user_dir = args.data_dir
                else:
                    app_user_dir = ''
                    WndUtils.error_msg('--data-dir parameter doesn\'t point to a directory. Using the default '
                                       'data directory.')
            else:
                app_user_dir = ''
                WndUtils.error_msg('--data-dir parameter doesn\'t point to an existing directory. Using the default '
                                   'data directory.')

        migrate_config = False
        old_user_data_dir = ''
        user_home_dir = os.path.expanduser('~')
        if not app_user_dir:
            app_user_dir = AppConfig.get_default_user_data_dir()

        self.data_dir = app_user_dir
        self.cache_dir = os.path.join(self.data_dir, 'cache')
        cache_file_name = os.path.join(self.cache_dir, 'dmt_cache_v2.json')
        global_settings_file_name = os.path.join(self.data_dir, GLOBAL_SETTINGS_FILE_NAME)

        if migrate_config:
            try:
                dirs_do_copy_later: List[Tuple[str, str]] = []

                def ignore_fun(cur_dir: str, items: List):
                    """In the first stage, ignore directories with a lot of files inside."""
                    nonlocal dirs_do_copy_later
                    to_ignore = []
                    if cur_dir == os.path.join(old_user_data_dir, 'cache'):
                        # subfolders with the cached tx data will be copied in the background to not delay
                        # the app startup
                        for item in items:
                            item_path = os.path.join(cur_dir, item)
                            if os.path.isdir(item_path):
                                to_ignore.append(item)
                                dest_path = item_path.replace(old_user_data_dir, self.data_dir)
                                dirs_do_copy_later.append((item_path, dest_path))
                    elif cur_dir == os.path.join(old_user_data_dir, 'logs'):
                        to_ignore.extend(items)
                    return to_ignore

                def delayed_copy_thread(ctrl, dirs_to_copy: List[Tuple[str, str]]):
                    """Directories with a possible large number of files copy in the background."""
                    try:
                        logging.info('Beginning to copy data in the background')
                        for (src_dir, dest_dir) in dirs_to_copy:
                            shutil.copytree(src_dir, dest_dir)
                        logging.info('Finished copying data in the background')
                    except Exception as e:
                        logging.exception('Exception while copying data in the background')

                shutil.copytree(old_user_data_dir, self.data_dir, ignore=ignore_fun)
                if dirs_do_copy_later:
                    WndUtils.run_thread(None, delayed_copy_thread, (dirs_do_copy_later,))

                if os.path.exists(cache_file_name):
                    # correct the configuration file paths stored in the cache file using the
                    # newly created data folder
                    cache_data = json.load(open(cache_file_name))
                    fn = cache_data.get('AppConfig_ConfigFileName')

                    old_dir = old_user_data_dir.replace('\\', '/')  # windows: paths stored in the cache file
                    # have possibly '/' characters instead od '\'
                    fn = fn.replace('\\', '/')

                    if fn.find(old_dir) >= 0 and len(fn) > len(old_dir) \
                            and fn[len(old_dir)] in ('/', '\\'):
                        fn = self.data_dir + fn[len(old_dir):]
                        if sys.platform == 'win32':
                            fn = fn.replace('/', '\\')
                        cache_data['AppConfig_ConfigFileName'] = fn

                    mru = cache_data.get('MainWindow_ConfigFileMRUList')
                    modified = False
                    for idx, fn in enumerate(mru):
                        fn = fn.replace('\\', '/')
                        if fn.find(old_dir) >= 0 and len(fn) > len(old_dir) \
                                and fn[len(old_dir)] in ('/', '\\'):
                            fn = self.data_dir + fn[len(old_dir):]
                            if sys.platform == 'win32':
                                fn = fn.replace('/', '\\')
                            mru[idx] = fn
                            modified = True
                    if modified:
                        cache_data['MainWindow_ConfigFileMRUList'] = mru

                    json.dump(cache_data, open(cache_file_name, 'w'))
            except Exception as e:
                logging.exception('Exception occurred while copying the data directory')
                # if there was an error when migrating to a new configuration, use the old data directory
                self.data_dir = old_user_data_dir
                self.cache_dir = os.path.join(self.data_dir, 'cache')
                cache_file_name = os.path.join(self.cache_dir, 'dmt_cache_v2.json')

        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

        app_cache.init(cache_file_name, self.app_version)
        self.app_last_version = app_cache.get_value('app_version', '', str)
        self.app_config_file_name = ''
        self.global_config.set_file_name(global_settings_file_name)
        self.global_config.start()
        self.ui_use_dark_mode = self.global_config.get_value('UI_USE_DARK_MODE', False, bool)

        if args.config is not None:
            # set config file name to what user passed in the 'config' argument
            self.app_config_file_name = args.config
            if not os.path.exists(self.app_config_file_name):
                msg = 'Config file "%s" does not exist.' % self.app_config_file_name
                print(msg)
                raise Exception(msg)

        if not self.app_config_file_name:
            # if the user hasn't passed a config file name in command line argument, read the config file name used the
            # last time the application was running (use cache data); if there is no information in cache, use the
            # default name 'config.ini'
            self.app_config_file_name = app_cache.get_value(
                'AppConfig_ConfigFileName', default_value=os.path.join(self.data_dir, 'config.ini'), type=str)

        if sys.platform == 'darwin' and args.scan_for_ssh_agent_vars:
            # on Mac try to read the SSH_AUTH_SOCK variable from shell profile files - on mac, shell profile files
            # aren't used in GUI apps, so setting SSH_AUTH_SOCK there has no effect in this case
            try:
                for fname in ('.bash_profile', '.zshrc', '.bashrc'):
                    cmd = f'echo $(source {os.path.join(user_home_dir, fname)}; echo $SSH_AUTH_SOCK)'
                    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
                    ssh_auth_sock = p.stdout.readlines()[0].strip().decode('ASCII')
                    if ssh_auth_sock:
                        os.environ['SSH_AUTH_SOCK'] = ssh_auth_sock
                        break
            except Exception:
                pass

        # setup logging
        self.log_dir = os.path.join(self.data_dir, 'logs')
        self.log_file = os.path.join(self.log_dir, 'dmt.log')
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

        self.log_handler = RotatingFileHandler(filename=self.log_file, mode='a', maxBytes=2000000, backupCount=30)
        logger = logging.getLogger()
        formatter = logging.Formatter(fmt=DEFAULT_LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S')
        self.log_handler.setFormatter(formatter)
        logger.addHandler(self.log_handler)
        self.set_log_level('INFO')
        logging.info(f'===========================================================================')
        logging.info(f'Application started (v {self.app_version})')

        self.restore_loggers_config()

        # directory for configuration backups:
        self.cfg_backup_dir = os.path.join(self.data_dir, 'backup')
        if not os.path.exists(self.cfg_backup_dir):
            os.makedirs(self.cfg_backup_dir)

        if not self.app_last_version or app_utils.is_version_greater(self.app_version, self.app_last_version):
            app_cache.save_data()

        try:
            app_params_json_file = os.path.join(self.app_dir, 'app-params.json')
            if os.path.exists(app_params_json_file):
                with open(app_params_json_file, 'rb') as fptr:
                    strs = fptr.read()
                    local_app_params = simplejson.loads(strs)
                    self.set_remote_app_params(local_app_params)
        except Exception as e:
            logging.exception(str(e))

        self.initialized = True

    def close(self):
        self.save_cache_settings()
        self.save_loggers_config()
        app_cache.finish()

        self.global_config.set_value('UI_USE_DARK_MODE', self.ui_use_dark_mode)
        app_cache.save_data(True)
        self.global_config.save_data()

        if self.db_intf:
            self.db_intf.close()

    def save_cache_settings(self):
        if self.feature_register_dmn_automatic.get_value() is not None:
            app_cache.set_value('FEATURE_REGISTER_DMN_AUTOMATIC_' + self.dash_network,
                                self.feature_register_dmn_automatic.get_value())
        if self.feature_update_registrar_automatic.get_value() is not None:
            app_cache.set_value('FEATURE_UPDATE_REGISTRAR_AUTOMATIC_' + self.dash_network,
                                self.feature_update_registrar_automatic.get_value())
        if self.feature_update_service_automatic.get_value() is not None:
            app_cache.set_value('FEATURE_UPDATE_SERVICE_AUTOMATIC_' + self.dash_network,
                                self.feature_update_service_automatic.get_value())
        if self.feature_revoke_operator_automatic.get_value() is not None:
            app_cache.set_value('FEATURE_REVOKE_OPERATOR_AUTOMATIC_' + self.dash_network,
                                self.feature_revoke_operator_automatic.get_value())
        if self.feature_new_bls_scheme.get_value() is not None:
            app_cache.set_value('FEATURE_NEW_BLS_SCHEME_' + self.dash_network,
                                self.feature_new_bls_scheme.get_value())

    def restore_cache_settings(self):
        ena = app_cache.get_value('FEATURE_REGISTER_AUTOMATIC_DMN_' + self.dash_network, True, bool)
        self.feature_register_dmn_automatic.set_value(ena, AppFeatureStatus.PRIORITY_APP_CACHE)
        ena = app_cache.get_value('FEATURE_UPDATE_REGISTRAR_AUTOMATIC_' + self.dash_network, True, bool)
        self.feature_update_registrar_automatic.set_value(ena, AppFeatureStatus.PRIORITY_APP_CACHE)
        ena = app_cache.get_value('FEATURE_UPDATE_SERVICE_AUTOMATIC_' + self.dash_network, True, bool)
        self.feature_update_service_automatic.set_value(ena, AppFeatureStatus.PRIORITY_APP_CACHE)
        ena = app_cache.get_value('FEATURE_REVOKE_OPERATOR_AUTOMATIC_' + self.dash_network, True, bool)
        self.feature_revoke_operator_automatic.set_value(ena, AppFeatureStatus.PRIORITY_APP_CACHE)
        ena = app_cache.get_value('FEATURE_NEW_BLS_SCHEME_' + self.dash_network, True, bool)
        self.feature_new_bls_scheme.set_value(ena, AppFeatureStatus.PRIORITY_APP_CACHE)

    def copy_from(self, src_config):
        self.dash_network = src_config.dash_network
        self.dash_net_configs = copy.deepcopy(src_config.dash_net_configs)
        self.random_dash_net_config = src_config.random_dash_net_config
        self.__hw_type = src_config.__hw_type
        self.hw_keepkey_psw_encoding = src_config.hw_keepkey_psw_encoding
        self.block_explorer_tx_mainnet = src_config.block_explorer_tx_mainnet
        self.block_explorer_tx_testnet = src_config.block_explorer_tx_testnet
        self.block_explorer_addr_mainnet = src_config.block_explorer_addr_mainnet
        self.block_explorer_addr_testnet = src_config.block_explorer_addr_testnet
        self.dash_central_proposal_api = src_config.dash_central_proposal_api
        self.check_for_updates = src_config.check_for_updates
        self.backup_config_file = src_config.backup_config_file
        self.read_proposals_external_attributes = src_config.read_proposals_external_attributes
        self.dont_use_file_dialogs = src_config.dont_use_file_dialogs
        self.confirm_when_voting = src_config.confirm_when_voting
        self.add_random_offset_to_vote_time = src_config.add_random_offset_to_vote_time
        self._proposal_vote_time_offset_lower = src_config._proposal_vote_time_offset_lower
        self._proposal_vote_time_offset_upper = src_config._proposal_vote_time_offset_upper
        self.proposal_vote_time_offset_min = src_config.proposal_vote_time_offset_min
        self.proposal_vote_time_offset_max = src_config.proposal_vote_time_offset_max
        self.fetch_network_data_after_start = src_config.fetch_network_data_after_start
        self.show_dash_value_in_fiat = src_config.show_dash_value_in_fiat
        self.csv_delimiter = src_config.csv_delimiter
        if self.initialized:
            # if this object is the main AppConfig object (it's initialized)
            if self.log_level_str != src_config.log_level_str:
                self.set_log_level(src_config.log_level_str)
                self.reset_loggers()
        else:
            # ... otherwise just copy attribute without reconfiguring logger
            self.log_level_str = src_config.log_level_str
        self.encrypt_config_file = src_config.encrypt_config_file
        self.ui_use_dark_mode = src_config.ui_use_dark_mode
        self.show_network_masternodes_tab = src_config.show_network_masternodes_tab

    def configure_cache(self):
        if self.is_testnet:
            db_cache_file_name = 'dmt_cache_testnet_v2.db'
        else:
            db_cache_file_name = 'dmt_cache_v2.db'
        self.tx_cache_dir = os.path.join(self.cache_dir, 'tx-' + self.hw_coin_name)
        if not os.path.exists(self.tx_cache_dir):
            os.makedirs(self.tx_cache_dir)
            if self.is_testnet:
                # move testnet json files to a subdir (don't do this for mainnet files
                # util there most of the users move to dmt v0.9.22
                try:
                    for file in glob.glob(os.path.join(self.cache_dir, 'insight_dash_testnet*.json')):
                        shutil.move(file, self.tx_cache_dir)
                except Exception as e:
                    logging.exception(str(e))

        new_db_cache_file_name = os.path.join(self.cache_dir, db_cache_file_name)
        if self.db_intf:
            if self.db_cache_file_name != new_db_cache_file_name:
                self.db_cache_file_name = new_db_cache_file_name
                self.db_intf.close()
                self.db_intf.open(self.db_cache_file_name)
        else:
            self.db_intf = DBCache()
            self.db_intf.open(new_db_cache_file_name)
            self.db_cache_file_name = new_db_cache_file_name

        try:
            cur = self.db_intf.get_cursor()

            # reset the cached user votes because of the network votes reset caused by spork 15
            cur.execute('select voting_time from VOTING_RESULTS where id=(select min(id) from VOTING_RESULTS)')
            row = cur.fetchone()
            if row and row[0]:
                d = datetime.datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                vts = d.timestamp()
                if vts < 1554246129:  # timestamp of the block (1047200) that activated spork 15
                    logging.info('Cleared the cached votes because of the spork 15 activation')
                    cur.execute('delete from VOTING_RESULTS')
                    cur.execute('delete from LIVE_CONFIG')
                    cur.execute('update proposals set dmt_voting_last_read_time=0')
                    self.db_intf.commit()
                    self.display_app_message.emit(1000,
                                                  'Some of your voting results on proposals have been reset in '
                                                  'relation to the activation of Spork 15. Verify this in the '
                                                  'voting window and vote again if needed.',
                                                  app_defs.AppTextMessageType.WARN)

            # check and clean the wallet addresses inconsistency
            cur.execute('select parent_id, address_index, count(*) from address where parent_id is not null '
                        'group by parent_id, address_index having count(*)>1')
            row = cur.fetchone()
            if row:
                bck_name = 'address_' + datetime.datetime.now().strftime('%Y%m%d_%H%M')
                cur.execute(f'create table {bck_name} as select * from address')
                cur.execute('delete from address')
                cur.execute('delete from tx_input')
                cur.execute('delete from tx_output')
                cur.execute('delete from tx')
                self.db_intf.commit()
                logging.warning('Cleared the wallet address cache because of inconsistencies found.')
                self.display_app_message.emit(1001, 'The wallet cache has been cleared because of '
                                                    'inconsistencies found.', app_defs.AppTextMessageType.WARN)
        except Exception as e:
            logging.error('Error while clearing voting results. Details: ' + str(e))
        finally:
            self.db_intf.release_cursor()

        self.restore_cache_settings()

    def reset_configuration(self):
        """
        Clears all the data structures that are loaded during the reading of the
        configuration file. This method is called before the reading new configuration
        from a file.
        :return:
        """
        self.dash_net_configs.clear()
        self.active_dash_net_configs.clear()
        self.defective_net_configs.clear()
        self.masternodes.clear()
        self.random_dash_net_config = True
        self._dash_blockchain_info.clear()
        self.public_conns_mainnet.clear()
        self.public_conns_testnet.clear()
        self.hw_keepkey_psw_encoding = 'NFC'
        self.dash_network = 'MAINNET'
        self.block_explorer_tx_mainnet = 'https://insight.dash.org/insight/tx/%TXID%'
        self.block_explorer_addr_mainnet = 'https://insight.dash.org/insight/address/%ADDRESS%'
        self.block_explorer_tx_testnet = 'https://testnet-insight.dashevo.org/insight/tx/%TXID%'
        self.block_explorer_addr_testnet = 'https://testnet-insight.dashevo.org/insight/address/%ADDRESS%'
        self.tx_api_url_mainnet = 'https://insight.dash.org/insight'
        self.tx_api_url_testnet = 'https://testnet-insight.dashevo.org/insight'
        self.dash_central_proposal_api = 'https://www.dashcentral.org/api/v1/proposal?hash=%HASH%'
        self.dash_nexus_proposal_api = 'https://api.dashnexus.org/proposals/%HASH%'
        self.check_for_updates = True
        self.backup_config_file = True
        self.read_proposals_external_attributes = True
        self.dont_use_file_dialogs = False
        self.confirm_when_voting = True
        self.add_random_offset_to_vote_time = True
        self._proposal_vote_time_offset_lower = -30
        self._proposal_vote_time_offset_upper = 30
        self.csv_delimiter = ';'
        self.app_config_file_name = ''
        self.encrypt_config_file = False
        self.config_file_encrypted = False
        self.fetch_network_data_after_start = True
        self.show_dash_value_in_fiat = True
        self.trezor_webusb = True
        self.trezor_bridge = True
        self.trezor_udp = True
        self.trezor_hid = True
        self.show_network_masternodes_tab = False

    def simple_decrypt(self, str_to_decrypt: str, string_can_be_unencrypted: bool = False, validator: Callable = None) -> str:
        """"
        :param string_can_be_unencrypted: passed True when importing data from the old config format where some
            data wasn't encrypted yet; we want to avoid clogging a log file with errors when actually
            there is no error
        """
        decrypted = ''
        try:
            if str_to_decrypt:
                decrypted = decrypt(str_to_decrypt, APP_NAME_LONG, iterations=5)
            else:
                decrypted = ''
        except Exception as e:
            if string_can_be_unencrypted:
                if validator:
                    if not validator(str_to_decrypt):
                        logging.exception('Unencrypted data validation failed')
                    else:
                        return str_to_decrypt
            logging.exception('String decryption error: ' + str(e))
        return decrypted

    def simple_encrypt(self, str_to_encrypt: str) -> str:
        return encrypt(str_to_encrypt, APP_NAME_LONG, iterations=5)

    def read_from_file(self, hw_session: 'HwSessionInfo', file_name: Optional[str] = None,
                       create_config_file: bool = False, update_current_file_name=True):
        if not file_name:
            file_name = self.app_config_file_name

        if os.path.exists(file_name):
            config = ConfigParser()
            try:
                while True:
                    mem_file = ''
                    ret_info = {}
                    try:
                        for data_chunk in read_file_encrypted(file_name, ret_info, hw_session):
                            mem_file += data_chunk.decode('utf-8')
                        break
                    except HWNotConnectedException as e:
                        ret = WndUtils.query_dlg(
                            'Configuration file read error: ' + str(e) + '\n\n' +
                            'Click \'Retry\' to try again, \'Open\' to choose another configuration file or '
                            '\'Cancel\' to exit.',
                            buttons=QMessageBox.Retry | QMessageBox.Cancel | QMessageBox.Open,
                            default_button=QMessageBox.Yes, icon=QMessageBox.Critical)

                        if ret == QMessageBox.Cancel:
                            raise CancelException('Couldn\'t read configuration file.')
                        elif ret == QMessageBox.Default:
                            break
                        elif ret == QMessageBox.Open:
                            if self.app_config_file_name:
                                dir = os.path.dirname(self.app_config_file_name)
                            else:
                                dir = self.data_dir

                            file_name = WndUtils.open_config_file_query(dir, None, None)
                            if file_name:
                                self.read_from_file(hw_session, file_name,
                                                    update_current_file_name=update_current_file_name)
                                return
                            else:
                                raise CancelException('Cancelled')

                config_file_encrypted = ret_info.get('encrypted', False)

                config.read_string(mem_file)
                self.reset_configuration()

                section = 'CONFIG'
                ini_version = config.get(section, 'CFG_VERSION', fallback=CURRENT_CFG_FILE_VERSION)
                try:
                    ini_version = int(ini_version)
                except Exception:
                    ini_version = CURRENT_CFG_FILE_VERSION

                if ini_version > CURRENT_CFG_FILE_VERSION:
                    self.display_app_message.emit(1002,
                                                  'The configuration file is created by a newer app version. '
                                                  'If you save any changes, you may lose some settings '
                                                  'that are not supported in this version. It is suggested to save '
                                                  'the configuration under a different file name.',
                                                  app_defs.AppTextMessageType.WARN)

                log_level_str = config.get(section, 'log_level', fallback='WARNING')
                if log_level_str not in ('CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'NOTSET'):
                    log_level_str = 'WARNING'
                if self.log_level_str != log_level_str:
                    self.set_log_level(log_level_str)

                dash_network = config.get(section, 'dash_network', fallback='MAINNET')
                if dash_network not in ('MAINNET', 'TESTNET'):
                    logging.warning(f'Invalid dash_network value: {dash_network}')
                    dash_network = 'MAINNET'
                self.dash_network = dash_network

                if self.is_mainnet:
                    def_bip32_path = "44'/5'/0'/0/0"
                else:
                    def_bip32_path = "44'/1'/0'/0/0"
                self.last_bip32_base_path = config.get(section, 'bip32_base_path', fallback=def_bip32_path)
                if not self.last_bip32_base_path:
                    self.last_bip32_base_path = def_bip32_path
                self.bip32_recursive_search = config.getboolean(section, 'bip32_recursive', fallback=True)

                type = config.get(section, 'hw_type', fallback=HWType.trezor.value)
                self.__hw_type = HWType.from_string(type)

                self.hw_keepkey_psw_encoding = config.get(section, 'hw_keepkey_psw_encoding', fallback='NFC')
                if self.hw_keepkey_psw_encoding not in ('NFC', 'NFKD'):
                    logging.warning('Invalid value of the hw_keepkey_psw_encoding config option: ' +
                                    self.hw_keepkey_psw_encoding)
                    self.hw_keepkey_psw_encoding = 'NFC'

                self.random_dash_net_config = self.value_to_bool(config.get(section, 'random_dash_net_config',
                                                                            fallback='1'))
                self.check_for_updates = self.value_to_bool(config.get(section, 'check_for_updates', fallback='1'))
                self.backup_config_file = self.value_to_bool(config.get(section, 'backup_config_file', fallback='1'))
                self.read_proposals_external_attributes = \
                    self.value_to_bool(config.get(section, 'read_external_proposal_attributes', fallback='1'))
                self.dont_use_file_dialogs = self.value_to_bool(config.get(section, 'dont_use_file_dialogs',
                                                                           fallback='0'))
                self.confirm_when_voting = self.value_to_bool(config.get(section, 'confirm_when_voting',
                                                                         fallback='1'))
                self.add_random_offset_to_vote_time = \
                    self.value_to_bool(config.get(section, 'add_random_offset_to_vote_time', fallback='1'))

                lower = config.get(section, 'proposal_vote_time_offset_lower', fallback='')
                if lower:
                    try:
                        lower = int(lower)
                    except Exception:
                        logging.error('Invalid value for config attribute: "proposal_vote_time_offset_lower"')

                upper = config.get(section, 'proposal_vote_time_offset_upper', fallback='')
                if upper:
                    try:
                        upper = int(upper)
                    except Exception:
                        logging.error('Invalid value for config attribute: "proposal_vote_time_offset_upper"')

                if isinstance(lower, int) and isinstance(upper, int):
                    if lower > upper:
                        lower = upper

                if isinstance(lower, int):
                    self._proposal_vote_time_offset_lower = lower
                if isinstance(upper, int):
                    self._proposal_vote_time_offset_upper = upper

                self.encrypt_config_file = \
                    self.value_to_bool(config.get(section, 'encrypt_config_file', fallback='0'))

                self.fetch_network_data_after_start = self.value_to_bool(
                    config.get(section, 'fetch_network_data_after_start', fallback='1'))

                self.show_dash_value_in_fiat = self.value_to_bool(
                    config.get(section, 'show_dash_value_in_fiat', fallback='1'))

                self.show_network_masternodes_tab = self.value_to_bool(
                    config.get(section, 'show_network_masternodes_tab', fallback='1'))

                # with ini ver 3 we changed the connection password encryption scheme, so connections in new ini
                # file will be saved under different section names - with this we want to disallow the old app
                # version to read such network configuration entries, because passwords won't be decoded properly
                if ini_version < 3:
                    conn_cfg_section_name = 'NETCFG'
                else:
                    conn_cfg_section_name = 'CONNECTION'

                was_error = False
                for section in config.sections():
                    try:
                        if re.match('MN\d', section):
                            try:
                                mn = MasternodeConfig()
                                mn.name = config.get(section, 'name', fallback='')
                                mn.ip = config.get(section, 'ip', fallback='')
                                mn.tcp_port = config.get(section, 'port', fallback='')
                                mn.collateral_bip32_path = config.get(section, 'collateral_bip32_path',
                                                                      fallback='').strip()
                                mn.collateral_address = config.get(section, 'collateral_address', fallback='').strip()
                                mn.collateral_tx = config.get(section, 'collateral_tx', fallback='').strip()
                                mn.collateral_tx_index = config.get(section, 'collateral_tx_index', fallback='').strip()
                                mn.use_default_protocol_version = self.value_to_bool(
                                    config.get(section, 'use_default_protocol_version', fallback='1'))
                                mn.protocol_version = config.get(section, 'protocol_version', fallback='').strip()

                                roles = int(config.get(section, 'dmn_user_roles', fallback='0').strip())
                                if not roles:
                                    role_old = int(config.get(section, 'dmn_user_role', fallback='0').strip())
                                    # try reading the pre v0.9.22 role and map it to the current role-set
                                    if role_old:
                                        if role_old == 1:
                                            mn.dmn_user_roles = DMN_ROLE_OWNER | DMN_ROLE_OPERATOR | DMN_ROLE_VOTING
                                        elif role_old == 2:
                                            mn.dmn_user_roles = DMN_ROLE_OPERATOR
                                        elif role_old == 3:
                                            mn.dmn_user_roles = DMN_ROLE_VOTING
                                else:
                                    mn.dmn_user_roles = roles
                                if not mn.dmn_user_roles:
                                    mn.dmn_user_roles = DMN_ROLE_OWNER | DMN_ROLE_OPERATOR | DMN_ROLE_VOTING

                                mn.protx_hash = config.get(section, 'dmn_tx_hash', fallback='').strip()
                                mn.owner_key_type = int(config.get(section, 'dmn_owner_key_type',
                                                                   fallback=str(InputKeyType.PRIVATE)).strip())
                                mn.operator_key_type = int(config.get(section, 'dmn_operator_key_type',
                                                                      fallback=str(InputKeyType.PRIVATE)).strip())
                                mn.voting_key_type = int(config.get(section, 'dmn_voting_key_type',
                                                                    fallback=str(InputKeyType.PRIVATE)).strip())
                                mn.platform_node_key_type = int(config.get(section, 'platform_node_key_type',
                                                                    fallback=str(InputKeyType.PRIVATE)).strip())

                                if mn.owner_key_type == InputKeyType.PRIVATE:
                                    mn.owner_private_key = self.simple_decrypt(
                                        config.get(section, 'dmn_owner_private_key', fallback='').strip(), False)
                                else:
                                    mn.owner_address = config.get(section, 'dmn_owner_address', fallback='').strip()

                                if mn.operator_key_type == InputKeyType.PRIVATE:
                                    mn.operator_private_key = self.simple_decrypt(
                                        config.get(section, 'dmn_operator_private_key', fallback='').strip(), False)
                                else:
                                    mn.operator_public_key = config.get(section, 'dmn_operator_public_key',
                                                                        fallback='').strip()

                                if mn.voting_key_type == InputKeyType.PRIVATE:
                                    mn.voting_private_key = self.simple_decrypt(
                                        config.get(section, 'dmn_voting_private_key', fallback='').strip(), False)
                                else:
                                    mn.voting_address = config.get(section, 'dmn_voting_address',
                                                                   fallback='').strip()

                                try:
                                    tmp_str = config.get(section, 'masternode_type', fallback='').strip()
                                    if tmp_str:
                                        mn.masternode_type = MasternodeType(int(tmp_str))
                                    else:
                                        mn.masternode_type = MasternodeType.REGULAR
                                except Exception as e:
                                    mn.masternode_type = MasternodeType.REGULAR
                                    logging.error('Error reading masternode type from configuration file: ' + str(e))

                                if mn.platform_node_key_type == InputKeyType.PRIVATE:
                                    try:
                                        mn.platform_node_private_key = self.simple_decrypt(
                                            config.get(section, 'platform_node_private_key', fallback='').strip(),
                                            False)
                                    except Exception as e:
                                        logging.error('Error reading platform_node_private_key from configuration '
                                                      'file: ' + str(e))
                                else:
                                    try:
                                        mn.platform_node_id = config.get(section, 'platform_node_id',
                                                                         fallback='').strip()
                                    except Exception as e:
                                        logging.error(
                                            'Error reading platform_node_id from configuration file: ' + str(e))

                                try:
                                    tmp_str = config.get(section, 'platform_p2p_port', fallback='')
                                    if tmp_str:
                                        mn.platform_p2p_port = int(tmp_str)
                                except Exception as e:
                                    logging.error('Error reading platform_p2p_port from configuration file: ' + str(e))

                                try:
                                    tmp_str = config.get(section, 'platform_http_port', fallback='')
                                    if tmp_str:
                                        mn.platform_http_port = int(tmp_str)
                                except Exception as e:
                                    logging.error('Error reading platform_http_port from configuration file: ' + str(e))

                                if ini_version == 6:
                                    if not mn.platform_node_private_key:
                                        try:
                                            platform_key = config.get(section, 'platform_node_id_private_key',
                                                                      fallback='').strip()
                                            if platform_key:
                                                mn.platform_node_private_key = platform_key
                                        except Exception as e:
                                            logging.exception(
                                                'Error reading platform_node_private_key from configuration '
                                                'file: ' + str(e))

                                mn.update_data_hash()
                                self.masternodes.append(mn)
                            except Exception as e:
                                logging.error('Error reading masternode configuration from file. '
                                              'Config section name: ' + section + ': ' + str(e))
                                was_error = True
                        elif re.match(conn_cfg_section_name + '\d', section):
                            # read network configuration from new config file format
                            cfg = DashNetworkConnectionCfg('rpc')
                            cfg.enabled = self.value_to_bool(config.get(section, 'enabled', fallback='1'))
                            cfg.host = config.get(section, 'host', fallback='').strip()
                            cfg.port = config.get(section, 'port', fallback='').strip()
                            if cfg.port:
                                cfg.port = int(cfg.port)
                            else:
                                cfg.port = None
                            cfg.use_ssl = self.value_to_bool(config.get(section, 'use_ssl', fallback='0').strip())
                            cfg.username = config.get(section, 'username', fallback='').strip()
                            cfg.set_encrypted_password(config.get(section, 'password', fallback=''),
                                                       config_version=ini_version)
                            cfg.use_ssh_tunnel = self.value_to_bool(config.get(section, 'use_ssh_tunnel', fallback='0'))
                            cfg.ssh_conn_cfg.host = config.get(section, 'ssh_host', fallback='').strip()
                            cfg.ssh_conn_cfg.port = config.get(section, 'ssh_port', fallback='').strip()
                            cfg.ssh_conn_cfg.username = config.get(section, 'ssh_username', fallback='').strip()
                            auth_method = config.get(section, 'ssh_auth_method', fallback='any').strip()
                            if auth_method and auth_method not in ('any', 'password', 'key_pair', 'ssh_agent'):
                                auth_method = 'password'
                            cfg.ssh_conn_cfg.auth_method = auth_method
                            cfg.ssh_conn_cfg.private_key_path = config.get(section, 'ssh_private_key_path',
                                                                           fallback='').strip()

                            cfg.testnet = self.value_to_bool(config.get(section, 'testnet', fallback='0'))
                            skip_adding = False

                            if cfg.host.lower() == 'test.stats.dash.org':
                                skip_adding = True
                                configuration_corrected = True
                            elif cfg.get_conn_id() == '9b73e3fad66e8d07597c3afcf14f8f3513ed63dfc903b5d6e02c46f59c2ffadc':
                                # delete obsolete "public" connection to luna.dash-masternode-tool.org
                                skip_adding = True
                                configuration_corrected = True

                            if config.has_option(section, 'rpc_encryption_pubkey'):
                                pubkey = config.get(section, 'rpc_encryption_pubkey', fallback='')
                                if pubkey:
                                    try:
                                        cfg.set_rpc_encryption_pubkey(pubkey)
                                    except Exception as e:
                                        logging.warning('Error while setting RPC encryption key: ' + str(e))
                            else:
                                # not existent rpc_encryption_pubkey parameter in the configuration file could mean
                                # we are opwnninf the old configuration file or the parameter was deleted by the old
                                # dmt version; if the connection belongs to the default connections, restore
                                # the RPC encryption key
                                for c in self.default_rpc_connections:
                                    if c.get_conn_id() == cfg.get_conn_id():
                                        matching_default_conn = c
                                        break
                                else:
                                    matching_default_conn = None

                                if matching_default_conn:
                                    cfg.set_rpc_encryption_pubkey(
                                        matching_default_conn.get_rpc_encryption_pubkey_str('DER'))
                                    if cfg.is_rpc_encryption_configured():
                                        configuration_corrected = True

                            if not skip_adding:
                                self.dash_net_configs.append(cfg)

                    except Exception as e:
                        logging.exception(str(e))

                if update_current_file_name:
                    self.app_config_file_name = file_name
                    app_cache.set_value('AppConfig_ConfigFileName', self.app_config_file_name)
                self.config_file_encrypted = config_file_encrypted

                if was_error:
                    WndUtils.warn_msg('There was an error reading configuration file. '
                                      'Look into the log file for more details.')
                self.update_config_data_hash()

            except CancelException:
                raise

            except Exception as e:
                logging.exception('Read configuration error:')
                errors_while_reading = True
                ret = WndUtils.query_dlg('Configuration file read error: ' + str(e) + '\n\n' +
                                         'Click \'Open\' to choose another configuration file or \'\Cancel\' to exit.',
                                         buttons=QMessageBox.Cancel | QMessageBox.Open,
                                         default_button=QMessageBox.Yes, icon=QMessageBox.Critical)
                if ret == QMessageBox.Cancel:
                    raise CancelException('Couldn\'t read configuration file.')
                elif ret == QMessageBox.Open:
                    if self.app_config_file_name:
                        dir = os.path.dirname(self.app_config_file_name)
                    else:
                        dir = self.data_dir

                    file_name = WndUtils.open_config_file_query(dir, None, None)
                    if file_name:
                        self.read_from_file(hw_session, file_name)
                        return
                    else:
                        raise CancelException('Cancelled')
                if update_current_file_name:
                    self.app_config_file_name = None
                self.config_file_data_hash = ''

        elif file_name:
            if not create_config_file:
                raise Exception(f'The configuration file \'{file_name}\' does not exist.')
            else:
                self.config_file_data_hash = ''

        self.load_default_connections()
        self.configure_cache()

    def load_default_connections(self):
        try:
            if self.default_rpc_connections:
                added, updated = self.import_connections(self.default_rpc_connections, force_import=False,
                                                         limit_to_network=None)
                for c in self.default_rpc_connections:
                    if c.mainnet:
                        self.public_conns_mainnet[c.get_conn_id()] = c
                    else:
                        self.public_conns_testnet[c.get_conn_id()] = c
        except Exception:
            logging.exception('An exception occurred while loading default connection configuration.')

    def save_to_file(self, hw_session: 'HwSessionInfo', file_name: Optional[str] = None,
                     update_current_file_name=True):
        """
        Saves current configuration to a file with the name 'file_name'. If the 'file_name' argument is empty
        configuration is saved under the current configuration file name (self.app_config_file_name).
        :return:
        """

        if not file_name:
            file_name = self.app_config_file_name
        if not file_name:
            if self.app_config_file_name:
                dir = os.path.dirname(self.app_config_file_name)
            else:
                dir = self.data_dir

            file_name = WndUtils.save_config_file_query(dir, None, None)
            if not file_name:
                return

        # backup old config file
        if self.backup_config_file and update_current_file_name:
            if os.path.exists(file_name):
                tm_str = datetime.datetime.now().strftime('%Y-%m-%d')
                back_file_name = os.path.join(self.cfg_backup_dir, 'config_' + tm_str + '.ini')
                if not os.path.exists(back_file_name):  # create no more than one backup per day
                    try:
                        copyfile(file_name, back_file_name)
                    except Exception:
                        pass

        section = 'CONFIG'
        config = ConfigParser()
        config.add_section(section)
        config.set(section, 'CFG_VERSION', str(CURRENT_CFG_FILE_VERSION))
        config.set(section, 'log_level', self.log_level_str)
        config.set(section, 'dash_network', self.dash_network)
        if self.__hw_type:
            config.set(section, 'hw_type', self.__hw_type.value)
        config.set(section, 'hw_keepkey_psw_encoding', self.hw_keepkey_psw_encoding)
        config.set(section, 'bip32_base_path', self.last_bip32_base_path)
        config.set(section, 'random_dash_net_config', '1' if self.random_dash_net_config else '0')
        config.set(section, 'check_for_updates', '1' if self.check_for_updates else '0')
        config.set(section, 'backup_config_file', '1' if self.backup_config_file else '0')
        config.set(section, 'dont_use_file_dialogs', '1' if self.dont_use_file_dialogs else '0')
        config.set(section, 'read_external_proposal_attributes',
                   '1' if self.read_proposals_external_attributes else '0')
        config.set(section, 'confirm_when_voting', '1' if self.confirm_when_voting else '0')
        config.set(section, 'fetch_network_data_after_start', '1' if self.fetch_network_data_after_start else '0')
        config.set(section, 'show_dash_value_in_fiat', '1' if self.show_dash_value_in_fiat else '0')
        config.set(section, 'add_random_offset_to_vote_time', '1' if self.add_random_offset_to_vote_time else '0')
        config.set(section, 'proposal_vote_time_offset_lower', str(self._proposal_vote_time_offset_lower))
        config.set(section, 'proposal_vote_time_offset_upper', str(self._proposal_vote_time_offset_upper))
        config.set(section, 'encrypt_config_file', '1' if self.encrypt_config_file else '0')
        config.set(section, 'show_network_masternodes_tab', '1' if self.show_network_masternodes_tab else '0')

        # save mn configuration
        for idx, mn in enumerate(self.masternodes):
            section = 'MN' + str(idx + 1)
            config.add_section(section)
            config.set(section, 'name', mn.name)
            config.set(section, 'ip', mn.ip)
            config.set(section, 'port', str(mn.tcp_port))
            # the private key encryption method used below is a very basic one, just to not have them stored
            # in plain text; more serious encryption is used when enabling the 'Encrypt config file' option
            config.set(section, 'collateral_bip32_path', mn.collateral_bip32_path)
            config.set(section, 'collateral_address', mn.collateral_address)
            config.set(section, 'collateral_tx', mn.collateral_tx)
            config.set(section, 'collateral_tx_index', str(mn.collateral_tx_index))
            config.set(section, 'use_default_protocol_version', '1' if mn.use_default_protocol_version else '0')
            config.set(section, 'protocol_version', str(mn.protocol_version))
            config.set(section, 'dmn_user_roles', str(mn.dmn_user_roles))
            config.set(section, 'dmn_tx_hash', mn.protx_hash)
            config.set(section, 'dmn_owner_private_key', self.simple_encrypt(mn.owner_private_key))
            config.set(section, 'dmn_operator_private_key', self.simple_encrypt(mn.operator_private_key))
            config.set(section, 'dmn_voting_private_key', self.simple_encrypt(mn.voting_private_key))
            config.set(section, 'dmn_owner_key_type', str(mn.owner_key_type))
            config.set(section, 'dmn_operator_key_type', str(mn.operator_key_type))
            config.set(section, 'dmn_voting_key_type', str(mn.voting_key_type))
            config.set(section, 'dmn_owner_address', mn.owner_address)
            config.set(section, 'dmn_operator_public_key', mn.operator_public_key)
            config.set(section, 'dmn_voting_address', mn.voting_address)
            config.set(section, 'masternode_type', str(mn.masternode_type.value))
            config.set(section, 'platform_node_key_type', str(mn.platform_node_key_type))
            config.set(section, 'platform_node_id', mn.platform_node_id)
            config.set(section, 'platform_node_private_key', self.simple_encrypt(mn.platform_node_private_key))
            config.set(section, 'platform_p2p_port', str(mn.platform_p2p_port) if mn.platform_p2p_port else '')
            config.set(section, 'platform_http_port', str(mn.platform_http_port) if mn.platform_http_port else '')
            mn.update_data_hash()

        # save dash network connections
        for idx, cfg in enumerate(self.dash_net_configs):
            section = 'CONNECTION' + str(idx + 1)
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
                config.set(section, 'ssh_auth_method', cfg.ssh_conn_cfg.auth_method)
                config.set(section, 'ssh_private_key_path', cfg.ssh_conn_cfg.private_key_path)
                # SSH password is not saved until HW encrypting feature will be finished
            config.set(section, 'testnet', '1' if cfg.testnet else '0')
            config.set(section, 'rpc_encryption_pubkey', cfg.get_rpc_encryption_pubkey_str('DER'))

        # ret_info = {}
        # read_file_encrypted(file_name, ret_info, hw_session)
        if self.encrypt_config_file:
            f_ptr = StringIO()
            config.write(f_ptr)
            f_ptr.seek(0)
            mem_data = bytes()
            while True:
                data_chunk = f_ptr.read(1000)
                if not data_chunk:
                    break
                if isinstance(data_chunk, str):
                    mem_data += bytes(data_chunk, 'utf-8')
                else:
                    mem_data += data_chunk

            write_file_encrypted(file_name, hw_session, mem_data)
            encrypted = True
        else:
            config.write(codecs.open(file_name, 'w', 'utf-8'))
            encrypted = False

        if update_current_file_name:
            self.config_file_encrypted = encrypted
            self.app_config_file_name = file_name
            app_cache.set_value('AppConfig_ConfigFileName', self.app_config_file_name)
        self.update_config_data_hash()

    def new_configuration(self):
        """ Creates a new configuration with defaults """
        self.reset_configuration()
        self.load_default_connections()
        self.configure_cache()
        self.config_file_data_hash = ''

    def get_cfg_data_str(self):
        """
        Returns saveable configuration data packed as a string. Used for hashing configuration data
        to be used as a comparison method if configration has changed.
        """
        all_data = ''
        all_data += str(self.log_level_str)
        all_data += str(self.dash_network)
        all_data += str(self.__hw_type.value) if self.__hw_type is not None else ''
        all_data += str(self.hw_keepkey_psw_encoding)
        all_data += str(self.last_bip32_base_path)
        all_data += str(self.random_dash_net_config)
        all_data += str(self.check_for_updates)
        all_data += str(self.backup_config_file)
        all_data += str(self.dont_use_file_dialogs)
        all_data += str(self.read_proposals_external_attributes)
        all_data += str(self.confirm_when_voting)
        all_data += str(self.fetch_network_data_after_start)
        all_data += str(self.show_dash_value_in_fiat)
        all_data += str(self.add_random_offset_to_vote_time)
        all_data += str(self._proposal_vote_time_offset_lower)
        all_data += str(self._proposal_vote_time_offset_upper)
        all_data += str(self.encrypt_config_file)
        all_data += str(self.show_network_masternodes_tab)

        for mn in self.masternodes:
            all_data += mn.get_data_str()

        for cfg in self.dash_net_configs:
            all_data += cfg.get_data_str()

        return all_data

    def get_config_data_hash(self):
        data = self.get_cfg_data_str()
        h = hashlib.sha256(data.encode('ascii', 'ignore'))
        return h.hexdigest()

    def update_config_data_hash(self):
        self.config_file_data_hash = self.get_config_data_hash()

    def reset_network_dependent_dyn_params(self):
        self.apply_remote_app_params()

    def set_remote_app_params(self, params: Dict):
        """ Set the dictionary containing the app live parameters stored in the project repository
        (remote app-params.json).
        """
        self._remote_app_params.clear()
        self._remote_app_params = params
        self.apply_remote_app_params()

    def apply_remote_app_params(self):
        def get_feature_config_remote(symbol) -> Tuple[Optional[bool], Optional[int], Optional[str]]:
            features = self._remote_app_params.get('features')
            if features:
                feature = features.get(symbol)
                if feature:
                    a = feature.get(self.dash_network.lower())
                    if a:
                        prio = a.get('priority', 0)
                        status = a.get('status')
                        message = a.get('message', '')
                        if status in ('enabled', 'disabled'):
                            return True if status == 'enabled' else False, prio, message
            return None, None, None

        def read_param_from_json(json_param_symbol: str, cfg_attr_name: str) -> Any:
            params = self._remote_app_params.get('params')
            if params:
                value = params.get(json_param_symbol)
                if value is not None:
                    if hasattr(self, cfg_attr_name):
                        self.__setattr__(cfg_attr_name, value)
                    else:
                        logging.error(f'Attribute {cfg_attr_name} does not exist.')
            return

        if self._remote_app_params:
            self.feature_register_dmn_automatic.set_value(*get_feature_config_remote('REGISTER_DMN_AUTOMATIC'))
            self.feature_update_registrar_automatic.set_value(*get_feature_config_remote('UPDATE_REGISTRAR_AUTOMATIC'))
            self.feature_update_service_automatic.set_value(*get_feature_config_remote('UPDATE_SERVICE_AUTOMATIC'))
            self.feature_revoke_operator_automatic.set_value(*get_feature_config_remote('REVOKE_OPERATOR_AUTOMATIC'))
            self.feature_new_bls_scheme.set_value(*get_feature_config_remote('NEW_BLS_SCHEME'))

            read_param_from_json('voteTimeRandomOffsetMin', 'proposal_vote_time_offset_min')
            read_param_from_json('voteTimeRandomOffsetMax', 'proposal_vote_time_offset_max')

            if self._remote_app_params.get('appDeveloperContact') and \
                    isinstance(self._remote_app_params.get('appDeveloperContact'), list):

                self.app_dev_contact = []
                for ci in self._remote_app_params.get('appDeveloperContact'):
                    name = self.simple_decrypt(ci.get('name'))
                    user_id = self.simple_decrypt(ci.get('userId'))
                    url = self.simple_decrypt(ci.get('url'))
                    if name and user_id:
                        dci = AppDeveloperContact(name, user_id, url)
                        self.app_dev_contact.append(dci)

    def read_dash_network_app_params(self, dashd_intf):
        """ Read parameters having impact on the app's behavior (sporks/dips) from the Dash network. Called
        after connecting to the network. """
        pass

    def get_default_protocol(self) -> int:
        prot = None
        if self._remote_app_params:
            dp = self._remote_app_params.get('defaultDashdProtocol')
            if dp:
                prot = dp.get(self.dash_network.lower())
        return prot

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

    @property
    def proposal_vote_time_offset_lower(self):
        value = self._proposal_vote_time_offset_lower
        if isinstance(value, int):
            try:
                if value < self.proposal_vote_time_offset_min:
                    value = self.proposal_vote_time_offset_min
                if value > self.proposal_vote_time_offset_max:
                    value = self.proposal_vote_time_offset_max
                if value > self._proposal_vote_time_offset_upper:
                    return self._proposal_vote_time_offset_upper
            except Exception as e:
                logging.exception(str(e))
        return value

    @proposal_vote_time_offset_lower.setter
    def proposal_vote_time_offset_lower(self, value):
        self._proposal_vote_time_offset_lower = value

    @property
    def proposal_vote_time_offset_upper(self):
        value = self._proposal_vote_time_offset_upper
        if isinstance(value, int):
            try:
                if value < self.proposal_vote_time_offset_min:
                    value = self.proposal_vote_time_offset_min
                if value > self.proposal_vote_time_offset_max:
                    value = self.proposal_vote_time_offset_max
                if value < self._proposal_vote_time_offset_lower:
                    return self._proposal_vote_time_offset_lower
            except Exception as e:
                logging.exception(str(e))
        return value

    @proposal_vote_time_offset_upper.setter
    def proposal_vote_time_offset_upper(self, value):
        self._proposal_vote_time_offset_upper = value

    def set_log_level(self, new_log_level_str: str):
        """
        Method called when log level has been changed by the user. New log
        :param new_log_level_str: new log level (symbol as INFO,WARNING,etc) to be set.
        """
        if self.log_level_str != new_log_level_str:
            ll_sav = self.log_level_str
            lg = logging.getLogger()
            if lg:
                lg.setLevel(new_log_level_str)
                if ll_sav:
                    logging.info('Changed log level to: %s' % new_log_level_str)
            self.log_level_str = new_log_level_str

    def reset_loggers(self):
        """Resets loggers to the default log level """
        for lname in logging.Logger.manager.loggerDict:
            l = logging.Logger.manager.loggerDict[lname]
            if isinstance(l, logging.Logger):
                l.setLevel(0)

    def save_loggers_config(self):
        lcfg = {}
        for lname in logging.Logger.manager.loggerDict:
            l = logging.Logger.manager.loggerDict[lname]
            if isinstance(l, logging.Logger):
                lcfg[lname] = l.level
        app_cache.set_value(CACHE_ITEM_LOGGERS_LOGLEVEL, lcfg)

        if self.log_handler and self.log_handler.formatter:
            fmt = self.log_handler.formatter._fmt
            app_cache.set_value(CACHE_ITEM_LOG_FORMAT, fmt)

    def restore_loggers_config(self):
        lcfg = app_cache.get_value(CACHE_ITEM_LOGGERS_LOGLEVEL, {}, dict)
        if lcfg:
            for lname in lcfg:
                level = lcfg[lname]
                l = logging.getLogger(lname)
                if isinstance(l, logging.Logger):
                    l.setLevel(level)
        else:
            # setting-up log level of external (non-dmt) loggers to avoid cluttering the log file
            for lname in get_known_loggers():
                if lname.external:
                    l = logging.getLogger(lname.name)
                    if isinstance(l, logging.Logger):
                        l.setLevel('WARNING')

        fmt = app_cache.get_value(CACHE_ITEM_LOG_FORMAT, DEFAULT_LOG_FORMAT, str)
        if fmt and self.log_handler:
            formatter = logging.Formatter(fmt=fmt, datefmt='%Y-%m-%d %H:%M:%S')
            self.log_handler.setFormatter(formatter)

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
            if cfg.enabled and self.is_testnet == cfg.testnet:
                tmp_list.append(cfg)
        if self.random_dash_net_config:
            ordered_list = []
            while len(tmp_list):
                idx = randint(0, len(tmp_list) - 1)
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

    def decode_connections(self, raw_conn_list) -> List['DashNetworkConnectionCfg']:
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
                    cfg.set_encrypted_password(conn_raw['password'], config_version=CURRENT_CFG_FILE_VERSION)
                    cfg.use_ssl = conn_raw['use_ssl']
                    cfg.set_rpc_encryption_pubkey(conn_raw.get('rpc_encryption_pubkey'))
                    if cfg.use_ssh_tunnel:
                        if 'ssh_host' in conn_raw:
                            cfg.ssh_conn_cfg.host = conn_raw['ssh_host']
                        if 'ssh_port' in conn_raw:
                            cfg.ssh_conn_cfg.port = conn_raw['ssh_port']
                        if 'ssh_user' in conn_raw:
                            cfg.ssh_conn_cfg.port = conn_raw['ssh_user']
                    cfg.testnet = conn_raw.get('testnet', False)
                    cfg.set_rpc_encryption_pubkey(conn_raw.get('rpc_encryption_pubkey'))
                    connn_list.append(cfg)
            except Exception as e:
                logging.exception('Exception while decoding connections.')
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
                'rpc_encryption_pubkey': str,
                'ssh_host': str, non-mandatory
                'ssh_port': str, non-mandatory
                'ssh_user': str, non-mandatory
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
                'use_ssl': conn.use_ssl,
                'rpc_encryption_pubkey': conn.get_rpc_encryption_pubkey_str('DER')
            }
            if conn.use_ssh_tunnel:
                ec['ssh_host'] = conn.ssh_conn_cfg.host
                ec['ssh_port'] = conn.ssh_conn_cfg.port
                ec['ssh_username'] = conn.ssh_conn_cfg.username
            encoded_conns.append(ec)
        return json.dumps(encoded_conns, indent=4)

    def import_connections(self, in_conns, force_import, limit_to_network: Optional[str]):
        """
        Imports connections from a list. Used at the app's start to process default connections and/or from
          a configuration dialog, when a user pastes a string, describing connections he
          wants to add to the configuration. The latter feature is used for a convenience.
        :param in_conns: list of DashNetworkConnectionCfg objects.
        :returns: tuple (list_of_added_connections, list_of_updated_connections)
        """

        added_conns = []
        updated_conns = []
        if in_conns:
            # import default mainnet connections if there is so mainnet connections in the current configuration
            # the same for testnet
            mainnet_conn_count = 0
            testnet_conn_count = 0
            for conn in self.dash_net_configs:
                if conn.testnet:
                    testnet_conn_count += 1
                else:
                    mainnet_conn_count += 1

            for nc in in_conns:
                if (self.dash_network == 'MAINNET' and nc.testnet == False) or \
                        (self.dash_network == 'TESTNET' and nc.testnet == True) or not limit_to_network:
                    id = nc.get_conn_id()
                    # check if new connection is in existing list
                    conn = self.get_conn_cfg_by_id(id)
                    if not conn:
                        if force_import or not app_cache.get_value('imported_default_conn_' + nc.get_conn_id(),
                                                                   False, bool) or \
                                (testnet_conn_count == 0 and nc.testnet) or (mainnet_conn_count == 0 and nc.mainnet):
                            # this new connection was not automatically imported before
                            self.dash_net_configs.append(nc)
                            added_conns.append(nc)
                            app_cache.set_value('imported_default_conn_' + nc.get_conn_id(), True)
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

    def is_modified(self) -> bool:
        if self.config_file_data_hash is not None:
            mod = self.config_file_data_hash != self.get_config_data_hash()
        else:
            mod = False
        return mod

    @property
    def is_testnet(self) -> bool:
        return self.dash_network == 'TESTNET'

    @property
    def is_mainnet(self) -> bool:
        return self.dash_network == 'MAINNET'

    @property
    def hw_coin_name(self):
        if self.is_testnet:
            return 'Dash Testnet'
        else:
            return 'Dash'

    def get_block_explorer_tx(self):
        if self.dash_network == 'MAINNET':
            return self.block_explorer_tx_mainnet
        else:
            return self.block_explorer_tx_testnet

    def get_block_explorer_addr(self):
        if self.dash_network == 'MAINNET':
            return self.block_explorer_addr_mainnet
        else:
            return self.block_explorer_addr_testnet

    def get_tx_api_url(self):
        if self.dash_network == 'MAINNET':
            return self.tx_api_url_mainnet
        else:
            return self.tx_api_url_testnet

    def get_app_img_dir(self):
        return os.path.join(self.app_dir, '', 'img')

    @property
    def internal_ui_dark_mode_activated(self):
        return self._internal_ui_dark_mode_activated

    @internal_ui_dark_mode_activated.setter
    def internal_ui_dark_mode_activated(self, activated: bool):
        self._internal_ui_dark_mode_activated = activated

    def get_widget_font_color_blue(self, wdg: QWidget) -> str:
        if self.internal_ui_dark_mode_activated:
            bg_color = qdarkstyle.Palette.COLOR_BACKGROUND_1
        else:
            palette = wdg.palette()
            bg_col = palette.color(QPalette.Normal, palette.Base)
            bg_color = bg_col.name()
        return get_widget_font_color_blue(bg_color)

    def get_widget_font_color_green(self, wdg: QWidget) -> str:
        if self.internal_ui_dark_mode_activated:
            bg_color = qdarkstyle.Palette.COLOR_BACKGROUND_1
        else:
            palette = wdg.palette()
            bg_col = palette.color(QPalette.Normal, palette.Base)
            bg_color = bg_col.name()
        return get_widget_font_color_green(bg_color)

    def get_hyperlink_font_color(self, wdg: QWidget) -> str:
        palette = wdg.palette()
        bg_col = palette.color(QPalette.Normal, palette.Link)

        if self.internal_ui_dark_mode_activated:
            bg_col = bg_col.lighter(140)
        bg_color = bg_col.name()
        return bg_color

    def get_widget_background_color(self, wdg: QWidget) -> str:
        if self.internal_ui_dark_mode_activated:
            bg_color = qdarkstyle.DarkPalette.COLOR_BACKGROUND_1
        else:
            palette = wdg.palette()
            bg_col = palette.color(QPalette.Normal, palette.Base)
            bg_color = bg_col.name()
        return bg_color

    def is_network_masternodes_enabled(self) -> bool:
        return self.show_network_masternodes_tab


class MasternodeConfig:
    def __init__(self):
        self.__name: str = ''
        self.__ip: str = ''
        self.__port: Optional[int] = 9999
        self.__collateral_bip32_path: str = ''
        self.__collateral_address: str = ''
        self.__collateral_tx: str = ''
        self.__collateral_tx_index: str = ''
        self.__protocol_version: str = ''
        self.__dmn_user_roles = DMN_ROLE_OWNER | DMN_ROLE_OPERATOR | DMN_ROLE_VOTING
        self.__tx_hash: str = ''
        self.__owner_key_type: int = InputKeyType.PRIVATE
        self.__operator_key_type: int = InputKeyType.PRIVATE
        self.__voting_key_type: int = InputKeyType.PRIVATE
        self.__platform_node_key_type: int = InputKeyType.PRIVATE
        self.__owner_private_key: str = ''
        self.__operator_private_key: str = ''
        self.__voting_private_key: str = ''
        self.__owner_address: str = ''
        self.__operator_public_key: str = ''
        self.__voting_address: str = ''
        self.__masternode_type: MasternodeType = MasternodeType.REGULAR
        self.__platform_node_private_key: str = ''
        self.__platform_node_id: str = ''
        self.__platform_p2p_port: Optional[int] = None
        self.__platform_http_port: Optional[int] = None
        self.use_default_protocol_version = True
        self.is_new = False  # True if this mn configuration entry isn't included in the app configuration yet
        self.saved_data_hash = ''
        self.lock_modified_change = False

    def copy_from(self, src_mn: 'MasternodeConfig'):
        self.name = src_mn.name
        self.ip = src_mn.ip
        self.tcp_port = src_mn.tcp_port
        self.collateral_bip32_path = src_mn.collateral_bip32_path
        self.collateral_address = src_mn.collateral_address
        self.collateral_tx = src_mn.collateral_tx
        self.collateral_tx_index = src_mn.collateral_tx_index
        self.use_default_protocol_version = src_mn.use_default_protocol_version
        self.protocol_version = src_mn.protocol_version
        self.dmn_user_roles = src_mn.dmn_user_roles
        self.protx_hash = src_mn.protx_hash
        self.owner_key_type = src_mn.owner_key_type
        self.operator_key_type = src_mn.operator_key_type
        self.voting_key_type = src_mn.voting_key_type
        self.owner_private_key = src_mn.owner_private_key
        self.operator_private_key = src_mn.operator_private_key
        self.voting_private_key = src_mn.voting_private_key
        self.platform_node_key_type = src_mn.platform_node_key_type
        self.owner_address = src_mn.owner_address
        self.operator_public_key = src_mn.operator_public_key
        self.voting_address = src_mn.voting_address
        self.masternode_type = src_mn.masternode_type
        self.platform_node_id = src_mn.platform_node_id
        self.platform_node_private_key = src_mn.platform_node_private_key
        self.platform_p2p_port = src_mn.platform_p2p_port
        self.platform_http_port = src_mn.platform_http_port
        self.is_new = src_mn.is_new
        self.modified = True
        self.lock_modified_change = False
        self.saved_data_hash = src_mn.saved_data_hash

    def get_data_str(self) -> str:
        """
        Returns masternode data packed as string to be used for hashing.
        """
        all_attrs = ''
        for attr, value in self.__dict__.items():
            m = re.match('(_MasternodeConfig)?(.+)', attr)
            if m:
                name = m.group(2)
                if name.startswith('__'):
                    all_attrs += str(value)
        return all_attrs

    def get_hash(self) -> str:
        data = self.get_data_str()
        h = hashlib.sha256(data.encode('ascii', 'ignore'))
        return h.hexdigest()

    def update_data_hash(self):
        self.saved_data_hash = self.get_hash()

    def is_modified(self):
        h = self.get_hash()
        return self.saved_data_hash != h

    @property
    def name(self) -> str:
        return self.__name

    @name.setter
    def name(self, new_name: str):
        self.__name = new_name

    @property
    def ip(self) -> str:
        if self.__ip:
            return self.__ip.strip()
        else:
            return self.__ip

    @ip.setter
    def ip(self, new_ip: str):
        if new_ip:
            self.__ip = new_ip.strip()
        else:
            self.__ip = new_ip

    @property
    def tcp_port(self) -> Optional[int]:
        return self.__port

    @tcp_port.setter
    def tcp_port(self, new_port: Optional[int]):
        self.__port = new_port

    @property
    def collateral_bip32_path(self) -> str:
        if self.__collateral_bip32_path:
            return self.__collateral_bip32_path.strip()
        else:
            return self.__collateral_bip32_path

    @collateral_bip32_path.setter
    def collateral_bip32_path(self, new_collateral_bip32_path: str):
        if new_collateral_bip32_path:
            self.__collateral_bip32_path = new_collateral_bip32_path.strip()
        else:
            self.__collateral_bip32_path = new_collateral_bip32_path

    @property
    def collateral_address(self) -> str:
        if self.__collateral_address:
            return self.__collateral_address.strip()
        else:
            return self.__collateral_address

    @collateral_address.setter
    def collateral_address(self, new_collateral_address: str):
        if new_collateral_address:
            self.__collateral_address = new_collateral_address.strip()
        else:
            self.__collateral_address = new_collateral_address

    @property
    def collateral_tx(self) -> str:
        if self.__collateral_tx:
            return self.__collateral_tx.strip()
        else:
            return self.__collateral_tx

    @collateral_tx.setter
    def collateral_tx(self, new_collateral_tx: str):
        if new_collateral_tx:
            self.__collateral_tx = new_collateral_tx.strip()
        else:
            self.__collateral_tx = new_collateral_tx

    @property
    def collateral_tx_index(self) -> str:
        if self.__collateral_tx_index:
            return self.__collateral_tx_index.strip()
        else:
            return self.__collateral_tx_index

    @collateral_tx_index.setter
    def collateral_tx_index(self, new_collateral_tx_index: str):
        if new_collateral_tx_index:
            self.__collateral_tx_index = new_collateral_tx_index.strip()
        else:
            self.__collateral_tx_index = new_collateral_tx_index

    @property
    def protocol_version(self) -> str:
        if self.__protocol_version:
            return self.__protocol_version.strip()
        else:
            return self.__protocol_version

    @protocol_version.setter
    def protocol_version(self, new_protocol_version: str):
        if new_protocol_version:
            self.__protocol_version = new_protocol_version.strip()
        else:
            self.__protocol_version = new_protocol_version

    @property
    def dmn_user_roles(self):
        return self.__dmn_user_roles

    @dmn_user_roles.setter
    def dmn_user_roles(self, roles):
        self.__dmn_user_roles = roles

    @property
    def protx_hash(self) -> str:
        return self.__tx_hash

    @protx_hash.setter
    def protx_hash(self, tx_hash: str):
        if tx_hash is None:
            tx_hash = ''
        self.__tx_hash = tx_hash.strip()

    @property
    def owner_private_key(self) -> str:
        return self.__owner_private_key

    @owner_private_key.setter
    def owner_private_key(self, owner_private_key: str):
        if owner_private_key is None:
            owner_private_key = ''
        self.__owner_private_key = owner_private_key.strip()

    @property
    def owner_address(self) -> str:
        return self.__owner_address

    @owner_address.setter
    def owner_address(self, address: str):
        self.__owner_address = address

    @property
    def operator_private_key(self) -> str:
        return self.__operator_private_key

    @operator_private_key.setter
    def operator_private_key(self, operator_private_key: str):
        if operator_private_key is None:
            operator_private_key = ''
        self.__operator_private_key = operator_private_key.strip()

    @property
    def operator_public_key(self) -> str:
        return self.__operator_public_key

    @operator_public_key.setter
    def operator_public_key(self, key: str):
        self.__operator_public_key = key

    @property
    def voting_private_key(self) -> str:
        return self.__voting_private_key

    @voting_private_key.setter
    def voting_private_key(self, voting_private_key: str):
        if voting_private_key is None:
            voting_private_key = ''
        self.__voting_private_key = voting_private_key.strip()

    @property
    def voting_address(self) -> str:
        return self.__voting_address

    @voting_address.setter
    def voting_address(self, address: str):
        self.__voting_address = address

    @property
    def owner_key_type(self) -> int:
        return self.__owner_key_type

    @owner_key_type.setter
    def owner_key_type(self, key_type: int):
        if key_type not in (InputKeyType.PRIVATE, InputKeyType.PUBLIC):
            raise Exception('Invalid owner key type')
        self.__owner_key_type = key_type

    @property
    def operator_key_type(self) -> int:
        return self.__operator_key_type

    @operator_key_type.setter
    def operator_key_type(self, key_type: int):
        if key_type not in (InputKeyType.PRIVATE, InputKeyType.PUBLIC):
            raise Exception('Invalid operator key type')
        self.__operator_key_type = key_type

    @property
    def voting_key_type(self) -> int:
        return self.__voting_key_type

    @voting_key_type.setter
    def voting_key_type(self, key_type: int):
        if key_type not in (InputKeyType.PRIVATE, InputKeyType.PUBLIC):
            raise Exception('Invalid voting key type')
        self.__voting_key_type = key_type

    def get_current_key_for_voting(self, app_config: AppConfig, dashd_intf) -> str:
        return self.voting_private_key

    @property
    def platform_node_key_type(self):
        return self.__platform_node_key_type

    @platform_node_key_type.setter
    def platform_node_key_type(self, key_type: int):
        if key_type not in (InputKeyType.PRIVATE, InputKeyType.PUBLIC):
            raise Exception('Invalid voting key type')
        self.__platform_node_key_type = key_type

    @property
    def masternode_type(self) -> MasternodeType:
        return self.__masternode_type

    @masternode_type.setter
    def masternode_type(self, mn_type: MasternodeType):
        self.__masternode_type = mn_type

    @property
    def platform_node_id(self) -> str:
        return self.__platform_node_id

    @platform_node_id.setter
    def platform_node_id(self, node_id: str):
        if node_id is None:
            node_id = ''
        self.__platform_node_id = node_id

    @property
    def platform_node_private_key(self):
        return self.__platform_node_private_key

    @platform_node_private_key.setter
    def platform_node_private_key(self, private_key: str):
        if private_key is None:
            private_key = ''
        self.__platform_node_private_key = private_key

    @property
    def platform_p2p_port(self) -> Optional[int]:
        return self.__platform_p2p_port

    @platform_p2p_port.setter
    def platform_p2p_port(self, p2p_port: Optional[int]):
        if p2p_port and not (1 <= p2p_port <= 65535):
            raise Exception("Platform P2P port must be a valid TCP port [1-65535]")
        self.__platform_p2p_port = p2p_port

    @property
    def platform_http_port(self) -> Optional[int]:
        return self.__platform_http_port

    @platform_http_port.setter
    def platform_http_port(self, http_port: Optional[int]):
        if http_port and not (1 <= http_port <= 65535):
            raise Exception("Platform HTTP port must be a valid TCP port [1-65535]")
        self.__platform_http_port = http_port

    def get_owner_public_address(self, dash_network) -> Optional[str]:
        if self.__owner_key_type == InputKeyType.PRIVATE:
            if self.__owner_private_key:
                try:
                    address = dash_utils.wif_privkey_to_address(self.__owner_private_key, dash_network)
                except Exception as e:
                    logging.exception(str(e))
                    address = ''
                return address
        else:
            if self.__owner_address:
                return self.__owner_address
        return ''

    def get_owner_pubkey_hash(self) -> Optional[str]:
        if self.owner_key_type == InputKeyType.PRIVATE:
            if self.__owner_private_key:
                try:
                    pubkey = dash_utils.wif_privkey_to_pubkey(self.__owner_private_key)
                    pubkey_bin = bytes.fromhex(pubkey)
                    pub_hash = bitcoin.bin_hash160(pubkey_bin)
                    pub_hash = pub_hash.hex()
                except Exception as e:
                    logging.exception(str(e))
                    pub_hash = ''
                return pub_hash
        else:
            if self.__owner_address:
                ret = dash_utils.address_to_pubkey_hash(self.__owner_address)
                if ret:
                    return ret.hex()
        return ''

    def get_voting_public_address(self, dash_network) -> Optional[str]:
        if self.__voting_key_type == InputKeyType.PRIVATE:
            if self.__voting_private_key:
                try:
                    address = dash_utils.wif_privkey_to_address(self.__voting_private_key, dash_network)
                except Exception as e:
                    logging.exception(str(e))
                    address = ''
                return address
        else:
            if self.__voting_address:
                return self.__voting_address
        return ''

    def get_voting_pubkey_hash(self) -> Optional[str]:
        if self.__voting_key_type == InputKeyType.PRIVATE:
            if self.__voting_private_key:
                try:
                    pubkey = dash_utils.wif_privkey_to_pubkey(self.__voting_private_key)
                    pubkey_bin = bytes.fromhex(pubkey)
                    pub_hash = bitcoin.bin_hash160(pubkey_bin)
                    pub_hash = pub_hash.hex()
                except Exception as e:
                    logging.exception(str(e))
                    pub_hash = ''
                return pub_hash
        else:
            if self.__voting_address:
                ret = dash_utils.address_to_pubkey_hash(self.__voting_address)
                if ret:
                    return ret.hex()
        return ''

    def get_operator_pubkey(self, new_bls_scheme: bool) -> Optional[str]:
        if self.__operator_key_type == InputKeyType.PRIVATE:
            if self.__operator_private_key:
                try:
                    pubkey = dash_utils.bls_privkey_to_pubkey(self.__operator_private_key, new_bls_scheme)
                except Exception as e:
                    logging.exception(str(e))
                    pubkey = ''
                return pubkey
        else:
            return self.__operator_public_key
        return ''

    def get_platform_node_id(self) -> Optional[str]:
        if self.__platform_node_key_type == InputKeyType.PRIVATE:
            if self.__platform_node_private_key:
                try:
                    node_id = dash_utils.ed25519_private_key_to_platform_node_id(self.__platform_node_private_key)
                except Exception as e:
                    logging.exception(str(e))
                    node_id = ''
                return node_id
        else:
            return self.__platform_node_id
        return ''

    def get_platform_node_private_key_for_editing(self) -> Optional[str]:
        if self.__platform_node_key_type == InputKeyType.PRIVATE:
            if self.__platform_node_private_key:
                try:
                    key = dash_utils.ed25519_private_key_to_tenderdash(self.__platform_node_private_key)
                except Exception as e:
                    logging.exception(str(e))
                    key = ''
                return key
        return ''


class SSHConnectionCfg(object):
    def __init__(self):
        self.__host = ''
        self.__port = ''
        self.__username = ''
        self.__password = ''
        self.__auth_method = 'any'  # 'any', 'password', 'key_pair', 'ssh_agent'
        self.private_key_path = ''

    def get_data_str(self) -> str:
        all_data = str(self.__host)
        all_data += str(self.__port)
        all_data += str(self.__username)
        all_data += str(self.__password)
        all_data += str(self.__auth_method)
        all_data += str(self.private_key_path)
        return all_data

    @property
    def host(self):
        return self.__host

    @host.setter
    def host(self, host):
        self.__host = host

    @property
    def port(self):
        if self.__port:
            return self.__port
        else:
            return '22'

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

    @property
    def auth_method(self):
        return self.__auth_method

    @auth_method.setter
    def auth_method(self, method):
        if method not in ('any', 'password', 'key_pair', 'ssh_agent'):
            raise Exception('Invalid authentication method')
        self.__auth_method = method


class DashNetworkConnectionCfg(object):
    def __init__(self, method):
        self.__enabled = True
        self.method = method  # now only 'rpc'
        self.__host = ''
        self.__port = ''
        self.__username = ''
        self.__password = ''
        self.__use_ssl = False
        self.__use_ssh_tunnel = False
        self.__ssh_conn_cfg = SSHConnectionCfg()
        self.__testnet = False
        self.__rpc_encryption_pubkey_der = ''
        self.__rpc_encryption_pubkey_object = None

    def get_data_str(self) -> str:
        """
        Returns data packed as string to be used for hashing.
        """
        all_attrs = str(self.__enabled)
        all_attrs += str(self.__host)
        all_attrs += str(self.__port)
        all_attrs += str(self.__username)
        all_attrs += str(self.__password)
        all_attrs += str(self.__use_ssl)
        all_attrs += str(self.__use_ssh_tunnel)
        all_attrs += self.__ssh_conn_cfg.get_data_str()
        all_attrs += str(self.__testnet)
        all_attrs += str(self.__rpc_encryption_pubkey_der)

        return all_attrs

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
        Returns identifier of this connection, built on attributes that uniquely characterize the connection.
        :return: 
        """
        if self.__use_ssh_tunnel:
            id = 'SSH:' + self.ssh_conn_cfg.host + ':' + self.__host + ':' + self.__port + ':' + str(self.__testnet)
        else:
            id = 'DIRECT:' + self.__host + ':' + self.__port + ':' + str(self.__testnet)
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
                                         self.ssh_conn_cfg.username == cfg2.ssh_conn_cfg.username and
                                         self.ssh_conn_cfg.auth_method == cfg2.ssh_conn_cfg.auth_method and
                                         self.ssh_conn_cfg.private_key_path == cfg2.ssh_conn_cfg.private_key_path)) \
            and self.testnet == cfg2.testnet and \
            self.__rpc_encryption_pubkey_der == cfg2.__rpc_encryption_pubkey_der

    def __deepcopy__(self, memodict):
        newself = DashNetworkConnectionCfg(self.method)
        newself.copy_from(self)
        return newself

    def copy_from(self, cfg2):
        """
        Copies all the attributes from another instance of this class.
        :param cfg2: Another instance of this type from which attributes will be copied.
        """
        self.host = cfg2.host
        self.port = cfg2.port
        self.username = cfg2.username
        self.password = cfg2.password
        self.use_ssh_tunnel = cfg2.use_ssh_tunnel
        self.use_ssl = cfg2.use_ssl
        self.testnet = cfg2.testnet
        self.enabled = cfg2.enabled
        if self.use_ssh_tunnel:
            self.ssh_conn_cfg.host = cfg2.ssh_conn_cfg.host
            self.ssh_conn_cfg.port = cfg2.ssh_conn_cfg.port
            self.ssh_conn_cfg.username = cfg2.ssh_conn_cfg.username
            self.ssh_conn_cfg.auth_method = cfg2.ssh_conn_cfg.auth_method
            self.ssh_conn_cfg.private_key_path = cfg2.ssh_conn_cfg.private_key_path
        if self.__rpc_encryption_pubkey_object and self.__rpc_encryption_pubkey_der != cfg2.__rpc_encryption_pubkey_der:
            self.__rpc_encryption_pubkey_object = None
        self.__rpc_encryption_pubkey_der = cfg2.__rpc_encryption_pubkey_der

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
        if method != 'rpc':
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
        self.__password = password

    def get_password_encrypted(self):
        try:
            psw = encrypt(self.__password, APP_NAME_LONG, iterations=5)
            return psw
        except:
            return self.__password

    def set_encrypted_password(self, password, config_version: int):
        try:
            # check if password is a hexadecimal string - then it probably is an encrypted string with AES
            if config_version < 3:
                iterations = 100000
            else:
                # we don't need strong encryption of passwords from connections saved in ini file
                # for strong encryption user can encrypt the whole ini file with hardware wallet
                iterations = 5
            int(password, 16)
            try:
                p = decrypt(password, APP_NAME_LONG, iterations=iterations)
            except Exception:
                p = ''
            password = p
        except Exception as e:
            logging.warning('Password decryption error: ' + str(e))

        self.__password = password

    @property
    def use_ssl(self):
        return self.__use_ssl

    @use_ssl.setter
    def use_ssl(self, use_ssl):
        if not isinstance(use_ssl, bool):
            raise Exception('Invalid type of "use_ssl" argument')
        self.__use_ssl = use_ssl

    @property
    def use_ssh_tunnel(self):
        return self.__use_ssh_tunnel

    @use_ssh_tunnel.setter
    def use_ssh_tunnel(self, use_ssh_tunnel):
        if not isinstance(use_ssh_tunnel, bool):
            raise Exception('Invalid type of "use_ssh_tunnel" argument')
        self.__use_ssh_tunnel = use_ssh_tunnel

    @property
    def ssh_conn_cfg(self):
        return self.__ssh_conn_cfg

    @property
    def testnet(self):
        return self.__testnet

    @property
    def mainnet(self):
        return not self.__testnet

    @testnet.setter
    def testnet(self, testnet):
        if not isinstance(testnet, bool):
            raise Exception('Invalid type of "testnet" argument')
        self.__testnet = testnet

    def set_rpc_encryption_pubkey(self, key: str):
        """
        AES public key for additional RPC encryption, dedicated for calls transmitting sensitive information
        like protx. Accepted formats: PEM, DER.
        """
        try:
            if key:
                # validate public key by deserializing it
                if re.fullmatch(r'^([0-9a-fA-F]{2})+$', key):
                    serialization.load_der_public_key(bytes.fromhex(key), backend=default_backend())
                else:
                    pubkey = serialization.load_pem_public_key(key.encode('ascii'), backend=default_backend())
                    raw = pubkey.public_bytes(serialization.Encoding.DER,
                                              format=serialization.PublicFormat.SubjectPublicKeyInfo)
                    key = raw.hex()

            if self.__rpc_encryption_pubkey_object and (self.__rpc_encryption_pubkey_der != key or not key):
                self.__rpc_encryption_pubkey_der = None

            self.__rpc_encryption_pubkey_der = key
        except Exception as e:
            logging.exception('Exception occurred')
            raise

    def get_rpc_encryption_pubkey_str(self, format: str):
        """
        :param format: PEM | DER
        """
        if self.__rpc_encryption_pubkey_der:
            if format == 'DER':
                return self.__rpc_encryption_pubkey_der
            elif format == 'PEM':
                pubkey = self.get_rpc_encryption_pubkey_object()
                pem = pubkey.public_bytes(encoding=serialization.Encoding.PEM,
                                          format=serialization.PublicFormat.SubjectPublicKeyInfo)
                return pem.decode('ascii')
            else:
                raise Exception('Invalid key format')
        else:
            return ''

    def get_rpc_encryption_pubkey_object(self):
        if self.__rpc_encryption_pubkey_der:
            if not self.__rpc_encryption_pubkey_object:
                self.__rpc_encryption_pubkey_object = serialization.load_der_public_key(
                    bytes.fromhex(self.__rpc_encryption_pubkey_der), backend=default_backend())
            return self.__rpc_encryption_pubkey_object
        else:
            return None

    def is_rpc_encryption_configured(self):
        if self.__rpc_encryption_pubkey_der:
            return True
        else:
            return False
