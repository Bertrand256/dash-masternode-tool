#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-07
import threading
import time
import datetime
import logging

from PyQt5 import QtCore
from typing import List, Dict, Tuple, Optional, Generator, Callable, Union
from PyQt5.QtCore import QObject, Qt
import app_utils
import hw_intf
from common import CancelException
from dash_utils import bip32_path_string_to_n, pubkey_to_address, bip32_path_n_to_string, bip32_path_string_append_elem
from dashd_intf import DashdInterface
from hw_common import HWNotConnectedException
from db_intf import DBCache
from thread_fun_dlg import CtrlObject
from thread_utils import EnhRLock
from wallet_common import Bip44AccountType, Bip44AddressType, UtxoType, TxOutputType, xpub_to_hash, Bip44Entry, \
    address_to_hash, TxType, CacheInconsistencyException
from wnd_utils import WndUtils

TX_QUERY_ADDR_CHUNK_SIZE = 20
ADDRESS_SCAN_GAP_LIMIT = 20
MAX_ADDRESSES_TO_SCAN = 1000
MAX_BIP44_ACCOUNTS = 200
GET_BLOCKHEIGHT_MIN_SECONDS = 30
UNCONFIRMED_TX_PURGE_SECONDS = 3600
UNCONFIRMED_TX_BLOCK_HEIGHT = 99999999
DEFAULT_TX_FETCH_PRIORITY = 1  # the higher the number to higher the priority
ADDR_BALANCE_CONSISTENCY_CHECK_SECONDS = 3600

log = logging.getLogger('dmt.bip44_wallet')


class BreakFetchTransactionsException(Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, *kwargs)


class SwitchedHDIdentityException(Exception):
    def __init__(self, *args, **kwargs):
        if args or kwargs:
            Exception.__init__(self, *args, *kwargs)
        else:
            Exception.__init__(self, "SwitchedHDIdentityException")


class Bip44Wallet(QObject):
    blockheight_changed = QtCore.pyqtSignal(int)

    def __init__(self, coin_name: str, hw_session: 'HwSessionInfo', db_intf: DBCache, dashd_intf: DashdInterface,
                 dash_network: str):
        QObject.__init__(self)
        self.db = None
        self.hw_session = hw_session
        self.dash_network = dash_network
        self.db_intf = db_intf
        self.dashd_intf = dashd_intf
        self.cur_block_height = None
        self.last_get_block_height_ts = 0
        self.__coin_name = coin_name
        self.__tree_id = None
        self.__tree_ident = None
        self.__tree_label = ''
        self.__cur_tx_fetch_priority = None
        self.__waiting_tx_fetch_priority = None
        self.__tx_fetch_end_event = threading.Event()

        # list of accounts retrieved while calling self.list_accounts
        self.account_by_id: Dict[int, Bip44AccountType] = {}
        self.account_by_bip32_path: Dict[str, Bip44AccountType] = {}

        # list of addresses created within the current hd tree
        self.addresses_by_id: Dict[int, Bip44AddressType] = {}
        self.addresses_by_address: Dict[str, Bip44AddressType] = {}

        # addresses whose balance has been modified since the last call of reset_tx_diffs
        self.addr_bal_updated: Dict[int, int] = {}  # {'address.id': 'address.id' }

        # transactions added/modified since the last reset_tx_diffs call
        self.txs_added: Dict[int, int] = {}  # {'tx_id': 'tx_id'}
        self.txs_removed: Dict[int, int] = {}  # {'tx_id': 'tx_id'}

        # utxos added/removed since the last reset_tx_diffs call
        self.utxos_by_id: Dict[int, UtxoType] = {}
        self.utxos_added: Dict[int, int] = {}  # {'tx_output.id': 'tx_output.id'}
        self.utxos_removed: Dict[int, int] = {}  # {'tx_output.id': 'tx_output.id'}
        self.utxos_modified: Dict[int, int] = {}  # confirmed utxos that were unconfirmed during the previous iteration

        # individual addresses subscribed for balance change notifications
        # these are all addresses configured in the masternode view, which may but don't have to belong
        # to the bip44 tree displayed in the wallet view
        self.__chbalance_subscribed_addrs: Dict[int, int] = {}

        # individual addresses subscribed for transactions activity
        # these are all addresses selected by the user in the masternodes view
        self.__txes_subscribed_addrs: Dict[int, int] = {}

        # ... the same for accounts:
        self.__txes_subscribed_accounts: Dict[int, int] = {}

        self.subscribed_addrs_lock = EnhRLock()

        self.purge_unconf_txs_called = False
        self.external_call_level = 0

        self.scan_metrics_scanned_address_count = 0
        self.scan_metrics_txes_fetched = 0
        self.scan_metrics_bytes_received = 0
        self.scan_metrics_bytes_sent = 0
        self.scan_metrics_rpc_time_ms = 0
        self.scan_metrics_bytes_received_start_value = 0
        self.scan_metrics_bytes_sent_start_value = 0
        self.scan_metrics_rpc_time_ms_start_value = 0

        self.on_account_added_callback: Optional[Callable[[Bip44AccountType], None]] = None
        self.on_account_data_changed_callback: Optional[Callable[[Bip44AccountType], None]] = None
        self.on_account_address_added_callback: Optional[Callable[[Bip44AccountType, Bip44AddressType], None]] = None
        self.on_address_data_changed_callback: Optional[Callable[[Bip44AccountType, Bip44AddressType], None]] = None
        self.on_address_loaded_callback: Optional[Callable[[Bip44AddressType], None]] = None
        self.on_fetch_account_txs_feedback: Optional[Callable[[int], None]] = None  # args: number of txses fetched each call

    def signal_account_added(self, account: Bip44AccountType):
        if self.on_account_added_callback and account and self.__tree_id == account.tree_id and \
                self.__tree_id is not None:
            self.on_account_added_callback(account)

    def signal_account_data_changed(self, account: Bip44AccountType):
        if self.on_account_data_changed_callback and account and self.__tree_id == account.tree_id and \
                self.__tree_id is not None:
            self.on_account_data_changed_callback(account)

    def signal_account_address_added(self, account: Bip44AccountType, address: Bip44AddressType):
        if self.on_account_address_added_callback and account and self.__tree_id == account.tree_id and \
                self.__tree_id is not None:
            self.on_account_address_added_callback(account, address)

    def signal_address_data_changed(self, account: Bip44AccountType, address: Bip44AddressType):
        if self.on_address_data_changed_callback:
            if (account and self.__tree_id == account.tree_id and self.__tree_id is not None) or \
                    address.id in self.__chbalance_subscribed_addrs:
                self.on_address_data_changed_callback(account, address)

    def signal_address_loaded(self, address: Bip44AddressType):
        if self.on_address_loaded_callback:
            self.on_address_loaded_callback(address)

    def reset_tx_diffs(self):
        self.txs_added.clear()
        self.txs_removed.clear()
        self.utxos_added.clear()
        self.utxos_removed.clear()
        self.utxos_modified.clear()
        self.addr_bal_updated.clear()

    def clear(self):
        self.__tree_id = None
        self.account_by_id.clear()
        self.account_by_bip32_path.clear()
        self.addresses_by_id.clear()
        self.addresses_by_address.clear()
        self.utxos_by_id.clear()
        with self.subscribed_addrs_lock:
            self.__txes_subscribed_addrs.clear()
        self.reset_tx_diffs()

    def get_hd_identity_info(self) -> Tuple[int, str]:
        """
        :return: Tuple[int <tree id>, str <tree label>]
        """
        if not self.__tree_id:
            db_cursor = self.db_intf.get_cursor()
            try:
                self.__tree_ident = self.hw_session.get_hd_tree_ident(self.__coin_name)
                db_cursor.execute('select id, label from hd_tree where ident=?', (self.__tree_ident,))
                row = db_cursor.fetchone()
                if not row:
                    db_cursor.execute('insert into hd_tree(ident) values(?)', (self.__tree_ident,))
                    self.__tree_id = db_cursor.lastrowid
                    self.db_intf.commit()
                else:
                    self.__tree_id, self.__tree_label = row
            finally:
                self.db_intf.release_cursor()
        return self.__tree_id, self.__tree_label

    def get_tree_id(self):
        id, l = self.get_hd_identity_info()
        return id

    def validate_hd_tree(self):
        if not self.__tree_ident:
            self.get_hd_identity_info()
        else:
            if self.__tree_ident != self.hw_session.get_hd_tree_ident(self.__coin_name):
                # user switched to another hw identity (e.g. enter bip39 different passphrase)
                log.info('Switching HD identity')
                self.clear()
                raise SwitchedHDIdentityException()

    def get_block_height(self):
        if self.cur_block_height is None or \
           (time.time() - self.last_get_block_height_ts >= GET_BLOCKHEIGHT_MIN_SECONDS):
            new_bh = self.dashd_intf.getblockcount()
            self.last_get_block_height_ts = time.time()
            if self.cur_block_height != new_bh:
                self.cur_block_height = new_bh
                self.blockheight_changed.emit(new_bh)
        return self.cur_block_height

    def get_block_height_nofetch(self):
        return self.cur_block_height

    def subscribe_addresses_for_chbalance(self, addr_ids: List[int], reset=True):
        with self.subscribed_addrs_lock:
            if reset:
                self.__chbalance_subscribed_addrs.clear()
            for id in addr_ids:
                self.__chbalance_subscribed_addrs[id] = id

    def subscribe_addresses_for_txes(self, addrs_ids: List[int], reset=True):
        with self.subscribed_addrs_lock:
            if reset:
                self.__txes_subscribed_addrs.clear()
                self.__txes_subscribed_accounts.clear()
            for id in addrs_ids:
                if id:
                    self.__txes_subscribed_addrs[id] = id

    def subscribe_accounts_for_txes(self, acc_ids: List[int], reset=True):
        with self.subscribed_addrs_lock:
            if reset:
                self.__txes_subscribed_accounts.clear()
                self.__txes_subscribed_addrs.clear()
            for id in acc_ids:
                if id:
                    self.__txes_subscribed_accounts[id] = id

    def _utxo_added(self, utxo_id: int):
        if utxo_id in self.utxos_removed:
            del self.utxos_removed[utxo_id]
        if utxo_id in self.utxos_modified:
            del self.utxos_modified[utxo_id]
        self.utxos_added[utxo_id] = utxo_id

    def _utxo_removed(self, utxo_id: int):
        if utxo_id in self.utxos_added:
            del self.utxos_added[utxo_id]  # the registered utxo has just been spent
        if utxo_id in self.utxos_modified:
            del self.utxos_modified[utxo_id]
        self.utxos_removed[utxo_id] = utxo_id

    def _utxo_modified(self, utxo_id: int):
        if utxo_id not in self.utxos_added:
            self.utxos_modified[utxo_id] = utxo_id

    def _tx_added(self, tx_id: int):
        if tx_id in self.txs_removed:
            del self.txs_removed[tx_id]
        self.txs_added[tx_id] = tx_id

    def _tx_removed(self, tx_id: int):
        if tx_id in self.txs_added:
            del self.txs_added[tx_id]
        self.txs_removed[tx_id] = tx_id

    def get_utxos_diff(self, added_utxos: List[UtxoType], modified_utxos: List[UtxoType], removed_utxos: List[int]):
        with self.subscribed_addrs_lock:
            # fetch missing Utxo objects from database
            missing_utxos = []
            for utxo_id in self.utxos_added:
                if not self.utxos_by_id.get(utxo_id):
                    missing_utxos.append(utxo_id)
            for utxo_id in self.utxos_modified:
                if not self.utxos_by_id.get(utxo_id):
                    missing_utxos.append(utxo_id)
            if missing_utxos:
                for _ in self.list_utxos_for_ids(missing_utxos):
                    pass

            for utxo_id in self.utxos_added:
                utxo = self.utxos_by_id.get(utxo_id)
                if utxo:
                    if utxo.address_obj and ((utxo.address_obj.id in self.__txes_subscribed_addrs) or
                            (utxo.address_obj.bip44_account and utxo.address_obj.bip44_account.id in
                             self.__txes_subscribed_accounts)):
                        added_utxos.append(utxo)
                else:
                    log.warning('Cannot find utxo object by id: %s', utxo_id)

            for utxo_id in self.utxos_modified:
                utxo = self.utxos_by_id.get(utxo_id)
                if utxo:
                    if utxo.address_obj and ((utxo.address_obj.id in self.__txes_subscribed_addrs) or
                            (utxo.address_obj.bip44_account and utxo.address_obj.bip44_account.id in
                             self.__txes_subscribed_accounts)):
                        modified_utxos.append(utxo)
                else:
                    log.warning('Cannot find utxo object by id: %s', utxo_id)

            for utxo_id in self.utxos_removed:
                utxo = self.utxos_by_id.get(utxo_id)
                if utxo:
                    if utxo.address_obj and ((utxo.address_obj.id in self.__txes_subscribed_addrs) or
                            (utxo.address_obj.bip44_account and utxo.address_obj.bip44_account.id in
                             self.__txes_subscribed_accounts)):
                        removed_utxos.append(utxo.id)

    def get_tx_diff(self, added_utxos: List[UtxoType], removed_utxos: List[UtxoType]):
        pass

    def get_address_id(self, address: str, db_cursor):
        db_cursor.execute('select id from address where address=?', (address,))
        row = db_cursor.fetchone()
        if row:
            return row[0]
        return None

    def get_address_item(self, address: str, create: bool) -> Optional[Bip44AddressType]:
        addr = self.addresses_by_address.get(address)

        if not addr:
            db_cursor = self.db_intf.get_cursor()
            try:
                db_cursor.execute('select * from address where address=?', (address,))
                row = db_cursor.fetchone()
                if row:
                    addr_info = dict([(col[0], row[idx]) for idx, col in enumerate(db_cursor.description)])
                    if not addr_info.get('path'):
                        parent_id = addr_info.get('parent_id')
                        address_index = addr_info.get('address_index')
                        if parent_id is not None and address_index is not None:
                            db_cursor.execute('select path from address where id=?', (parent_id,))
                            row = db_cursor.fetchone()
                            if row and row[0]:
                                addr_info['path'] = bip32_path_string_append_elem(row[0], address_index)
                    addr = self._get_address_from_dict(addr_info)
                    self._address_loaded(addr)
                elif create:
                    db_cursor.execute('insert into address(address) values(?)', (address,))
                    addr = Bip44AddressType(tree_id=None)
                    addr.address = address
                    addr.id = db_cursor.lastrowid
                    self.db_intf.commit()
                    self._address_loaded(addr)
                else:
                    return None
            finally:
                self.db_intf.release_cursor()
        return addr

    def _find_address_item_in_cache_by_id(self, addr_id: int) -> Tuple[Bip44AddressType, Bip44AccountType]:
        addr = None
        acc = None
        for acc_id in self.account_by_id:
            acc = self.account_by_id[acc_id]
            addr = acc.address_by_id(addr_id)
            if addr:
                break
        if not addr:
            acc = None
            addr = self.addresses_by_id.get(addr_id)
        return addr, acc

    def _get_bip44_entry_by_xpub(self, xpub) -> Bip44Entry:
        raise Exception('ToDo')

    def _address_loaded(self, addr: Bip44AddressType):
        self.addresses_by_id[addr.id] = addr
        self.addresses_by_address[addr.address] = addr
        self.signal_address_loaded(addr)

    def _get_address_from_dict(self, address_dict) -> Bip44AddressType:
        addr = Bip44AddressType(address_dict.get('tree_id'))

        addr.id = address_dict.get('id')
        if addr.address_index is None:
            addr.address_index = address_dict.get('address_index')
        if addr.address is None:
            addr.address = address_dict.get('address')
        if not addr.bip32_path:
            addr.bip32_path = address_dict.get('path')
        if not addr.tree_id:
            addr.tree_id = address_dict.get('tree_id')
        if not addr.label:
            addr.label = address_dict.get('label')
        addr.balance = address_dict.get('balance', 0)
        addr.received = address_dict.get('received', 0)
        addr.last_scan_block_height = address_dict.get('last_scan_block_height', 0)
        return addr

    def _fill_temp_ids_table(self, ids: List[int], db_cursor, tab_sufix: str = ''):
        db_cursor.execute(f"CREATE TEMPORARY TABLE IF NOT EXISTS temp_ids{tab_sufix}(id INTEGER PRIMARY KEY)")
        db_cursor.execute(f'delete from temp_ids{tab_sufix}')
        db_cursor.executemany(f'insert into temp_ids{tab_sufix}(id) values(?)',
                              [(id,) for id in ids])

    def _get_child_address(self, parent_key_entry: Bip44Entry, child_addr_index: int) -> Bip44AddressType:
        """
        :return: Tuple[int <id db>, str <address>, int <balance in duffs>]
        """
        if parent_key_entry.id is None:
            raise Exception('parent_key_entry.is is null')

        addr = parent_key_entry.child_entries.get(child_addr_index)

        if not addr:
            db_cursor = self.db_intf.get_cursor()
            try:
                db_cursor.execute('select a.id, a.parent_id, a.address_index, a.address, a.path, a.tree_id, a.balance, '
                                  'a.received, a.last_scan_block_height, ac.is_change, a.label from address a '
                                  'join address ac on ac.id=a.parent_id '
                                  'where a.parent_id=? and a.address_index=?',
                                  (parent_key_entry.id, child_addr_index))
                row = db_cursor.fetchone()
                if not row:
                    parent_key = parent_key_entry.get_bip32key()
                    key = parent_key.ChildKey(child_addr_index)
                    address = pubkey_to_address(key.PublicKey().hex(), self.dash_network)
                    if not parent_key_entry.bip32_path:
                        raise Exception('BIP32 path of the parent key not set')
                    bip32_path = bip32_path_string_append_elem(parent_key_entry.bip32_path, child_addr_index)

                    db_cursor.execute('select * from address where address=?',
                                      (address,))
                    row = db_cursor.fetchone()
                    if row:
                        addr_info = dict([(col[0], row[idx]) for idx, col in enumerate(db_cursor.description)])
                        if addr_info.get('parent_id') != parent_key_entry.id or \
                                addr_info.get('address_index') != child_addr_index or \
                                addr_info.get('path') != bip32_path or \
                                addr_info.get('tree_id') != parent_key_entry.tree_id:

                            if addr_info.get('tree_id') and addr_info.get('tree_id') != parent_key_entry.tree_id:
                                log.warning('Address %s stored in cache has had incorrect tree_id: %s, but it'
                                            ' should have: %s.', addr_info.get('id'),
                                            addr_info.get('tree_id'), parent_key_entry.tree_id)
                                raise CacheInconsistencyException()

                            if addr_info.get('address_index') is not None and addr_info.get('address_index') != \
                                    child_addr_index:
                                log.warning('Address %s stored in cache has had incorrect address_index: %s, but it'
                                            ' should have: %s.', addr_info.get('id'),
                                            addr_info.get('child_addr_index'), child_addr_index)
                                raise CacheInconsistencyException()

                            if addr_info.get('path') and addr_info.get('path') != bip32_path:
                                log.warning('Address %s stored in cache has had incorrect bip32_path: %s, but it'
                                            ' should have: %s.', addr_info.get('id'),
                                            addr_info.get('path'), bip32_path)
                                raise CacheInconsistencyException()

                            if addr_info.get('parent_id') and addr_info.get('parent_id') != parent_key_entry.id:
                                log.warning('Address %s stored in cache has had incorrect parent_id: %s, but it'
                                            ' should have: %s.', addr_info.get('id'),
                                            addr_info.get('parent_id'), parent_key_entry.id)
                                raise CacheInconsistencyException()

                            # address wasn't initially opened as a part of xpub account scan, so update its attrs
                            db_cursor.execute('update address set parent_id=?, address_index=?, path=?, tree_id=? '
                                              'where id=?',
                                              (parent_key_entry.id, child_addr_index, bip32_path, parent_key_entry.tree_id,
                                               row[0]))

                            addr_info['parent_id'] = parent_key_entry.id
                            addr_info['address_index'] = child_addr_index
                            addr_info['path'] = bip32_path
                            addr_info['tree_id'] = parent_key_entry.tree_id

                        addr = self._get_address_from_dict(addr_info)
                    else:
                        h = address_to_hash(address)
                        db_cursor.execute('select label from labels.address_label where key=?', (h,))
                        row = db_cursor.fetchone()
                        if row:
                            label = row[0]
                        else:
                            label = ''

                        db_cursor.execute('insert into address(parent_id, address_index, address, label, path, tree_id)'
                                          ' values(?,?,?,?,?,?)',
                                          (parent_key_entry.id, child_addr_index, address, label, bip32_path,
                                           parent_key_entry.tree_id))

                        addr_id = db_cursor.lastrowid
                        addr_info = {
                            'id': addr_id,
                            'parent_id': parent_key_entry.id,
                            'address_index': child_addr_index,
                            'address': address,
                            'label': label,
                            'last_scan_block_height': 0,
                            'path': bip32_path,
                            'tree_id': parent_key_entry.tree_id
                        }
                        addr = self._get_address_from_dict(addr_info)
                else:
                    addr_info = dict([(col[0], row[idx]) for idx, col in enumerate(db_cursor.description)])
                    addr = self._get_address_from_dict(addr_info)

                self._address_loaded(addr)
                parent_key_entry.child_entries[child_addr_index] = addr
            except Exception:
                raise
            finally:
                if db_cursor.connection.total_changes > 0:
                    self.db_intf.commit()
                self.db_intf.release_cursor()
        return addr

    def _get_key_entry_by_xpub(self, xpub: str) -> Bip44Entry:
        raise Exception('ToDo')

    def _list_child_addresses(self, key_entry: Bip44Entry, addr_start_index: int, addr_count: int,
                              account: Bip44AccountType) -> Generator[Bip44AddressType, None, None]:

        tm_begin = time.time()
        count = 0
        try:
            for idx in range(addr_start_index, addr_start_index + addr_count):
                addr_info = self._get_child_address(key_entry, idx)
                if account:
                    is_new, updated, addr_index, addr = account.add_address(addr_info)
                    if is_new:
                        self.signal_account_address_added(account, addr)

                count += 1
                yield addr_info
        except Exception as e:
            log.exception('Exception occurred while listing xpub addresses')
            raise
        finally:
            diff = time.time() - tm_begin
            log.debug(f'list_xpub_addresses exec time: {diff}s, keys count: {count}')

    def increase_ext_call_level(self):
        if self.external_call_level == 0:
            self.purge_unconf_txs_called = False
        self.external_call_level += 1

    def decrease_ext_call_level(self):
        if self.external_call_level > 0:
            self.external_call_level -= 1

    def _get_account_by_index(self, account_index: int, db_cursor) -> Bip44AccountType:
        """
        :param account_index: for hardened accounts the value should be equal or grater than 0x80000000
        :return:
        """
        tm_begin = time.time()
        tree_id = self.get_tree_id()
        b32_path = self.hw_session.base_bip32_path
        if not b32_path:
            log.error('hw_session.base_bip32_path not set. Probable cause: not initialized HW session.')
            raise Exception('HW session not initialized. Look into the log file for details.')
        path_n = bip32_path_string_to_n(b32_path) + [account_index]
        account_bip32_path = bip32_path_n_to_string(path_n)

        account = self.account_by_bip32_path.get(account_bip32_path)
        if not account:
            xpub = hw_intf.get_xpub(self.hw_session, account_bip32_path)
            xpub_hash = xpub_to_hash(xpub)
            db_cursor.execute('select id, path from address where xpub_hash=? and tree_id=?', (xpub_hash, tree_id))
            row = db_cursor.fetchone()
            if row:
                id, path = row
                if path != account_bip32_path:
                    # fill the bip32 path - this entry was possibly created as a xpub address
                    db_cursor.execute('update address set path=? where id=?', (account_bip32_path, id))
                    self.db_intf.commit()

                account = Bip44AccountType(None, id, xpub=xpub, address_index=account_index,
                                           bip32_path=account_bip32_path)
                account.read_from_db(db_cursor)
                account.evaluate_address_if_null(db_cursor, self.dash_network)

            else:
                account = Bip44AccountType(self.get_tree_id(), id=None, xpub=xpub, address_index=account_index,
                                           bip32_path=account_bip32_path)
                account.evaluate_address_if_null(db_cursor, self.dash_network)
                account.create_in_db(db_cursor)
                self.db_intf.commit()

            self.account_by_id[account.id] = account
            if account.bip32_path:
                self.account_by_bip32_path[account.bip32_path] = account

            self._read_account_addresses(account, db_cursor)
            self.signal_account_added(account)

            log.debug('get_account_base_address_by_index exec time: %s', time.time() - tm_begin)
        else:
            idx = account_index - 0x80000000
            if 0 <= idx <= 25:
                try:
                    # use xpub_hash to verify if the user didn't switch the wallet identity (eg. passphrase)
                    xpub = hw_intf.get_xpub(self.hw_session, account_bip32_path)
                    if account.xpub != xpub:
                        raise SwitchedHDIdentityException()

                except ConnectionRefusedError:
                    raise HWNotConnectedException()

                except Exception as e:
                    raise

            log.debug('get_account_base_address_by_index (used cache) exec time: %s', time.time() - tm_begin)

        return account

    def _get_account_by_id(self, id: int, db_cursor, force_reload=False) -> Bip44AccountType:
        """
        Read the bip44 account data from db (for a given id) and return it as Bip44AccountType.
        """
        account = self.account_by_id.get(id)

        if not account:
            if self.__tree_ident:
                account = Bip44AccountType(None, id, xpub='', address_index=None, bip32_path=None)
                account.read_from_db(db_cursor)
                self.account_by_id[id] = account
                if account.tree_id == self.get_tree_id():
                    if account.bip32_path:
                        self.account_by_bip32_path[account.bip32_path] = account

                    if account.bip32_path:
                        account.xpub = hw_intf.get_xpub(self.hw_session, account.bip32_path)
                        account.evaluate_address_if_null(db_cursor, self.dash_network)

                    self._read_account_addresses(account, db_cursor)
                    self.signal_account_added(account)
        else:
            if force_reload:
                account.read_from_db(db_cursor)

            if not account.xpub and account.bip32_path:
                account.xpub = hw_intf.get_xpub(self.hw_session, account.bip32_path)
                account.evaluate_address_if_null(db_cursor, self.dash_network)
        return account

    def _read_account_addresses(self, account: Bip44AccountType, db_cursor):
        correct_tree_id = []

        db_cursor.execute('select a.id, a.address_index, a.address, ac.path parent_path, a.balance, '
                          'a.received, ac.is_change, a.label, a.tree_id from address a '
                          'join address ac on a.parent_id=ac.id '
                          'where ac.parent_id=? order by ac.address_index, a.address_index', (account.id,))

        for add_row in db_cursor.fetchall():
            addr = account.address_by_id(add_row[0])
            if not addr:
                addr_info = dict([(col[0], add_row[idx]) for idx, col in enumerate(db_cursor.description)])
                addr = self._get_address_from_dict(addr_info)
                if not addr.bip32_path:
                    pp = addr_info.get('parent_path')
                    if pp:
                        addr.bip32_path = pp + '/' + str(addr.address_index)
                if not addr.tree_id:
                    addr.tree_id = account.tree_id

                if addr_info.get('tree_id') and addr_info.get('tree_id') != account.tree_id:
                    log.warning('Address %s stored in cache has had incorrect tree_id: %s, but it'
                                ' should have: %s.', addr_info.get('id'),
                                addr_info.get('tree_id'), account.tree_id)
                    raise CacheInconsistencyException()

                account.add_address(addr)
                self._address_loaded(addr)
            else:
                addr.update_from_args(balance=add_row[4], received=add_row[5])

            self.db_intf.commit()

    def _fetch_child_addrs_txs(self, key_entry: Bip44Entry, account: Bip44AccountType, check_break_process_fun: Callable = None):
        total_addr_count = 0

        cur_block_height = self.get_block_height()

        if not self.purge_unconf_txs_called:
            try:
                db_cursor = self.db_intf.get_cursor()
                self._purge_unconfirmed_transactions(db_cursor)
                self.purge_unconf_txs_called = True
            finally:
                self.db_intf.release_cursor()

        empty_addresses = 0
        addresses = []
        for addr_info in self._list_child_addresses(key_entry, 0, MAX_ADDRESSES_TO_SCAN, account):
            addresses.append(addr_info)

            if len(addresses) >= TX_QUERY_ADDR_CHUNK_SIZE:

                if check_break_process_fun and check_break_process_fun():
                    break
                total_addr_count += len(addresses)
                self._check_terminate_tx_fetch()

                self._process_addresses_txs(addresses, cur_block_height, check_break_process_fun)

                if check_break_process_fun and check_break_process_fun():
                    break
                self._check_terminate_tx_fetch()

                # count the number of addresses with no associated transactions starting from the end
                _empty_addresses = 0
                db_cursor = self.db_intf.get_cursor()
                try:
                    for addr_info_rev in reversed(addresses):
                        addr_id = addr_info_rev.id

                        # check if there were no transactions for the address
                        if not self.addr_bal_updated.get(addr_id):
                            db_cursor.execute('select 1 from tx_output o join address ao on ao.address=o.address '
                                              'where ao.id=? and ao.tree_id=?', (addr_id, self.__tree_id))
                            if db_cursor.fetchone():
                                break
                        else:
                            break
                        _empty_addresses += 1
                finally:
                    self.db_intf.release_cursor()

                addresses.clear()

                if _empty_addresses < TX_QUERY_ADDR_CHUNK_SIZE:
                    empty_addresses = _empty_addresses
                else:
                    empty_addresses += _empty_addresses

                if empty_addresses >= ADDRESS_SCAN_GAP_LIMIT:
                    break

        if len(addresses):
            self._process_addresses_txs(addresses, cur_block_height, check_break_process_fun)

    def fetch_addresses_txs(self, addr_info_list: List[Bip44AddressType], check_break_process_fun: Callable):
        tm_begin = time.time()
        self.increase_ext_call_level()

        cur_block_height = self.get_block_height()
        self._reset_scan_metrics()

        if not self.purge_unconf_txs_called:
            try:
                db_cursor = self.db_intf.get_cursor()
                self._purge_unconfirmed_transactions(db_cursor)
                self.purge_unconf_txs_called = True
            finally:
                self.db_intf.release_cursor()
        try:
            # remove address duplicates
            addr_dict = {}
            for a in addr_info_list:
                addr_dict[a.address] = a

            if len(addr_dict) != len(addr_info_list):
                addr_info_list = list(addr_dict.values())

            self._process_addresses_txs(addr_info_list, cur_block_height, check_break_process_fun)
        finally:
            self.decrease_ext_call_level()

        log.debug(f'fetch_addresses_txs exec time: {time.time() - tm_begin}s')

    def _process_addresses_txs(self, addr_info_list: List[Bip44AddressType], max_block_height: int,
                               check_break_process_fun: Callable = None):

        def get_unconfirmed_missed_transactions(addr_ids: List[int]):
            """Fetch all transactions from the db cache that are marked as uncommitted, but have had
            enough time (20 minutes) to be confirmed on the network. Apply the confirmation status in the db cache
            if applicable.
            """

            self._fill_temp_ids_table(addr_ids, db_cursor)

            db_cursor.execute("""select tx_hash from tx where block_height=? and
              (exists(select * from tx_input i join address ai on ai.address=i.src_address and ai.tree_id=?
                      where i.tx_id=tx.id and ai.id in (select id from temp_ids)) or
               exists(select * from tx_output o join address ao on ao.address=o.address and ao.tree_id=? 
                      where o.tx_id=tx.id and ao.id in (select id from temp_ids))) 
              and block_timestamp < ?
            """, (UNCONFIRMED_TX_BLOCK_HEIGHT, self.__tree_id, self.__tree_id,
                  int(time.time() - 20 * 60)))

            for tx_hash, in db_cursor.fetchall():
                tx_json = self._getrawtransaction(tx_hash, skip_cache=True)
                yield tx_json

        def process_transactions(tx_iterator: Generator[Dict, None, None], skip_cache=False):
            last_time_checked = time.time()
            last_nr = 0

            tm_start = time.time()
            log.debug(f'Starting process_transactions')

            tx_nr = 0
            for tx_entry in tx_iterator:
                self.scan_metrics_txes_fetched += 1
                tx_id = tx_entry.get('txid')
                if not tx_id:
                    log.error('TX JSON does not have the "txid" attribute')
                    continue

                self._process_transaction(db_cursor, tx_id, tx_json=tx_entry, skip_cache=skip_cache)
                tx_nr += 1

                if int(time.time() - last_time_checked) > 1:  # feedback every 1s
                    if check_break_process_fun and check_break_process_fun():
                        break
                    if self.on_fetch_account_txs_feedback:
                        self.on_fetch_account_txs_feedback(tx_nr - last_nr)
                        last_time_checked = time.time()
                        last_nr = tx_nr

            tm_diff = round(time.time() - tm_start, 2)
            log.debug(f'Finished process_transactions - tx fetched count: {tx_nr}, fetch time: {tm_diff} s')

        log.debug('_process_addresses_txs, addr count: %s', len(addr_info_list))
        tm_begin = time.time()
        addrinfo_by_address = {}
        addresses = []
        addr_ids = []
        last_block_height = max_block_height

        for addr_info in addr_info_list:
            if addr_info.address:
                addrinfo_by_address[addr_info.address] = addr_info
                addresses.append(addr_info.address)
                addr_ids.append(addr_info.id)

        db_cursor = self.db_intf.get_cursor()
        try:
            self._fill_temp_ids_table(addr_ids, db_cursor)

            # Check the minimum block number from which scanning for new transactions will be done for all of the input
            # addresses; if there are any addresses not used before (last_scan_block_height=0) discard their
            # last_scan_block_height value to avoid a full-rescan of all the other addresses; here we assume that
            # fresh addresses (that weren't needed during previous scans) do not have any transactions;
            db_cursor.execute('select min(last_scan_block_height) from address where last_scan_block_height is not null'
                              ' and last_scan_block_height > 0 and id in (select id from temp_ids)')

            row = db_cursor.fetchone()
            if row:
                if row[0] is not None:
                    last_block_height = row[0]
                else:
                    last_block_height = 0
            start_height = min(last_block_height + 1, max_block_height)

            txes = self.dashd_intf.getaddressdeltasrawtx_dmt(addresses=addresses, start=start_height,
                                                              end=max_block_height, verbose=1, include_mempool=1)
            process_transactions(txes)


            # Update all unspent transaction outputs according to the db cache that seem to being spent anyway
            for addr_info in addr_info_list:
                db_cursor.execute('select o.id, o.address, i.src_address, tx1.id, '
                                  'i.input_index spent_input_index_matching,'
                                   ' tx2.tx_hash spent_tx_hash_matching '
                                   'from tx_output o '
                                   '    join tx tx1 on tx1.id=o.tx_id'
                                   '    join tx_input i on  i.src_tx_hash=tx1.tx_hash and '
                                   '         i.src_tx_output_index=o.output_index '
                                   '    join tx tx2 on tx2.id=i.tx_id '
                                   '  where (o.spent_tx_hash is null or o.spent_input_index is null)'
                                   '  and (o.address=? or i.src_address=?)',
                    (addr_info.address, addr_info.address))

                for output_id, address1, address2, tx_id, spent_index, spent_tx_hash in \
                    db_cursor.fetchall():
                    db_cursor.execute('update tx_output set spent_tx_hash=?, spent_input_index=? where id=?',
                                      (spent_tx_hash, spent_index, output_id))

                    self._utxo_modified(output_id)

                    addrs_to_update = []
                    if address1 is not None:
                        address1_id = self.get_address_id(address1, db_cursor)
                        if address1_id:
                            addrs_to_update.append(address1_id)
                    if address2 is not None:
                        address2_id = self.get_address_id(address2, db_cursor)
                        if address2_id:
                            addrs_to_update.append(address2_id)

                    if addrs_to_update:
                        self._update_addr_balances(account=None, addr_ids=addrs_to_update, db_cursor=db_cursor)
                    log.info('Fixing the spent data on transaction output id: ' + str(output_id))

            # update the last scan block height info for each of the addresses
            if last_block_height != max_block_height:
                for addr_info in addr_info_list:
                    db_cursor.execute('update address set last_scan_block_height=? where id=?',
                                      (max_block_height, addr_info.id))

                for addr_info in addr_info_list:
                    if addr_info.address:
                        addr_info.last_scan_block_height = max_block_height

            # update balances of the all addresses affected by processing transactions
            addr_ids_to_update_balance = [a.id for a in addr_info_list if a.id in self.addr_bal_updated]
            if addr_ids_to_update_balance:
                self._update_addr_balances(account=None, addr_ids=addr_ids_to_update_balance)

            # verify whether the address balances from the db cache match the balances maintained by network
            addr_ids_to_update_balance = []
            _addresses = [a.address for a in addr_info_list]
            _cur_addr_balances = self.dashd_intf.getaddressbalances_dmt(_addresses)

            # process unconfirmed transactions
            txes = get_unconfirmed_missed_transactions(addr_ids)
            process_transactions(txes)

            if last_block_height > 0:
                for a in addr_info_list:
                    if time.time() - a.last_balance_verify_ts >= ADDR_BALANCE_CONSISTENCY_CHECK_SECONDS:
                        log.debug('Verifying address balance consistency. Id: %s', a.id)
                        try:
                            b = _cur_addr_balances.get(a.address)
                            if b is None:
                                log.warning('No balance info for address: ' + a.address)
                            else:
                                # refresh data since it might have been changed in earlier stages
                                a.read_from_db(db_cursor)
                                current_balance = b.get('balance')
                                a.last_balance_verify_ts = int(time.time())
                                if current_balance is not None and current_balance != a.balance:
                                    log.warning(f'Balance of address {a.address}, id: {a.id} discrepency; cached '
                                                f'balance: {a.balance}, network balance: {current_balance}')

                                    txes = self.dashd_intf.getaddressdeltasrawtx_dmt(addresses=[a.address], start = 0,
                                                                                     end = max_block_height, verbose=1,
                                                                                     include_mempool=1)

                                    # we need to re-fetch data from the network to exclude possible invalid data
                                    # that got into the cache due to some network problems or chain reorganization
                                    process_transactions(txes, skip_cache=True)

                                    if a.id in self.addr_bal_updated:
                                        addr_ids_to_update_balance.append(a.id)
                        except Exception as e:
                            log.error('Address balance check error: %s', str(e))
                        log.debug('Finished verifying address balance consistency. Id: %s', a.id)

            if addr_ids_to_update_balance:
                self._update_addr_balances(account=None, addr_ids=addr_ids_to_update_balance)

        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()

        log.debug('_process_addresses_txs exec time: %s', time.time() - tm_begin)

    def _getrawtransaction(self, tx_hash, skip_cache: bool = False):
        tx = self.dashd_intf.getrawtransaction(tx_hash, 1, skip_cache=skip_cache)
        self.scan_metrics_txes_fetched += 1
        return tx

    def _process_transaction(self, db_cursor, tx_hash: str, tx_json: Dict = None, skip_cache=False) \
            -> Tuple[int, Optional[Dict]]:
        """
        Adds records related to transaction do a local cache database, fetching a transaction detaisl (JSON) from RPC
        node if necessary.
        :param db_cursor: cursor to a local database
        :param tx_hash: hash of the transaction
        :param tx_json: transaction details in JSON form or None if not available when calling this function
        :param skip_cache: if True, transaction details will be fetched from the network, regardless of whether they are
                    cached on the local filesystem or not;
        :return: Tuple[int <transaction db id>, Optional[Dict <transaction details json>]]
        """
        tx_hash = self._wrap_txid(tx_hash)

        try:
            if not tx_json:
                tx_json = self._getrawtransaction(tx_hash, skip_cache=skip_cache)

            if not self.__tree_id:
                log.error('Bip44Wallet error: tree_id is empty')
                raise Exception('Bip44Wallet error: tree_id is empty')

            db_cursor.execute('select id, block_height from tx where tx_hash=?', (tx_hash, ))
            row = db_cursor.fetchone()

            block_height = tx_json.get('height')
            block_timestamp = tx_json.get('time')

            if not row:
                if not block_height:
                    # if block_height equals 0, it's an unconfirmed transaction and block_timestamp stores
                    # the time when tx has been added to the cache
                    block_height = UNCONFIRMED_TX_BLOCK_HEIGHT
                    block_timestamp = int(time.time())

                tx_vin = tx_json.get('vin', [])
                is_coinbase = 1 if (len(tx_vin) == 1 and tx_vin[0].get('coinbase')) else 0

                db_cursor.execute('insert into tx(tx_hash, block_height, block_timestamp, coinbase) '
                                  'values(?,?,?,?)',
                                  (tx_hash, block_height, block_timestamp, is_coinbase))
                tx_id = db_cursor.lastrowid
                self._tx_added(tx_id)
            else:
                tx_id, prev_height = row
                was_unconfirmed = True if prev_height >= UNCONFIRMED_TX_BLOCK_HEIGHT else False

                if was_unconfirmed:
                    # it was an unconfirmed transactions; check whether it has been confirmed since the last call
                    if block_height:
                        db_cursor.execute('update tx set block_height=?, block_timestamp=? where id=?',
                                          (block_height, block_timestamp, tx_id))
                        self.db_intf.commit()

                        # list utxos for this transaction and signal they got confirmed
                        db_cursor.execute('select id from tx_output where tx_id=? and (spent_tx_hash is null '
                                          'or spent_input_index is null) and address is not null', (tx_id,))
                        for utxo_id, in db_cursor.fetchall():
                            utxo = self.utxos_by_id.get(utxo_id)
                            if utxo:
                                utxo.block_height = block_height
                            self._utxo_modified(utxo_id)

            if tx_json:
                existing_input_ids = []
                existing_output_ids = []

                for index, vout in enumerate(tx_json.get('vout', [])):
                    _id = self._process_tx_output_entry(db_cursor, tx_id, tx_hash, index, tx_json)
                    if _id:
                        existing_output_ids.append(_id)

                for index, vin in enumerate(tx_json.get('vin', [])):
                    _id = self._process_tx_input_entry(db_cursor, tx_id, tx_hash, index, tx_json)
                    if _id:
                        existing_input_ids.append(_id)

                # remove redundant outputs and inputs that may be leftover after entering orphaned forks or other read
                # errors from RCP nodes
                # 1. outputs:
                db_cursor.execute('select id, address from tx_output where tx_id=?', (tx_id,))
                for _id, _ in db_cursor.fetchall():
                    if _id not in existing_output_ids:
                        db_cursor.execute('delete from tx_output where id=?', (_id,))

                # 2. inputs:
                db_cursor.execute('select id, src_address from tx_input where tx_id=?', (tx_id,))
                for _id, _ in db_cursor.fetchall():
                    if _id not in existing_input_ids:
                        db_cursor.execute('delete from tx_input where id=?', (_id,))

        except Exception as e:
            self.db_intf.rollback()
            log.exception(str(e))
            raise
        return tx_id, tx_json

    def _process_tx_output_entry(self, db_cursor, tx_id: int, tx_hash: str, output_index: int, tx_json: Dict) \
            -> Optional[int]:
        """
        :param db_cursor: database curso
        :param tx_id: db id of the record in the 'tx' table
        :param tx_hash: transaction hash
        :param output_index: the output index in the transaction outputs list
        :param tx_json: transaction body as a JSON object
        :return: id of the related record in the 'tx_output' table
        """
        output_db_id = None

        vouts = tx_json.get('vout')
        if output_index < len(vouts):
            vout = vouts[output_index]

            spk = vout.get('scriptPubKey', {})
            if spk:
                address = spk.get('address')
                if address:
                    addr_id = self.get_address_id(address, db_cursor)
                else:
                    addr_id = None
                satoshis = vout.get('valueSat')
                scr_type = spk.get('type')

                # check if the output has already been spent
                db_cursor.execute('select tx.tx_hash, input_index from tx_input join tx on tx_input.tx_id = tx.id '
                                  'where src_tx_hash=? and src_tx_output_index=?',
                                  (tx_hash, output_index))
                row = db_cursor.fetchone()

                if row:
                    spent_tx_hash, spent_input_index = row
                else:
                    spent_input_index = None
                    spent_tx_hash = None

                db_cursor.execute('select id, address, satoshis, spent_tx_hash, spent_input_index '
                                  'from tx_output where tx_id=? and output_index=?', (tx_id, output_index))
                row = db_cursor.fetchone()

                if not row:
                    db_cursor.execute('insert into tx_output(address, tx_id, output_index, satoshis, '
                                      'spent_tx_hash, spent_input_index, script_type) '
                                      'values(?,?,?,?,?,?,?)',
                                      (address, tx_id, output_index, satoshis, spent_tx_hash,
                                       spent_input_index, scr_type))

                    utxo_id = db_cursor.lastrowid
                    self._utxo_added(utxo_id)
                    if addr_id:
                        self.addr_bal_updated[addr_id] = True
                    output_db_id = utxo_id
                else:
                    (output_db_id, address_cached, satoshis_cached, spent_tx_hash_cached, spent_input_index_cached) = row

                    if (address_cached != address or satoshis_cached != satoshis or
                        spent_tx_hash != spent_tx_hash_cached or spent_input_index_cached != spent_input_index):

                        if addr_id:
                            self.addr_bal_updated[addr_id] = True

                        # update db if there is any discrepency with the data fetched from the network; it may be
                        # caused by the network problems or the chain reorganization
                        db_cursor.execute('update tx_output set address=?, satoshis=?, spent_tx_hash=?, '
                                          'spent_input_index=? where id=?',
                                          (address, satoshis, spent_tx_hash, spent_input_index, output_db_id))
            else:
                log.warning('No scriptPub in output, txhash: %s, index: %s', tx_hash, output_index)
        else:
            log.warning(f'Ouptut index number {output_index} exceeds the number of transaction outputs ({len(vouts)}); '
                        f'tx_id: {tx_id}')

        return output_db_id

    def _process_tx_input_entry(self, db_cursor, tx_id: int, tx_hash: str, input_index: int, tx_json: Dict) \
            -> Optional[int]:
        input_db_id = None

        vins = tx_json.get('vin')
        if input_index < len(vins):
            vin = vins[input_index]

            satoshis = vin.get('valueSat')
            if satoshis:
                satoshis = -satoshis
            related_tx_hash = vin.get('txid')
            related_tx_index = vin.get('vout')

            db_cursor.execute('select id, src_address, satoshis, src_tx_hash, src_tx_output_index, coinbase '
                              'from tx_input where tx_id=? and input_index=?',
                              (tx_id, input_index))
            row = db_cursor.fetchone()
            addr = vin.get('address')
            if addr:
                addr_id = self.get_address_id(addr, db_cursor)
            else:
                addr_id = None
            coinbase = 1 if vin.get('coinbase') else 0

            if not row:
                db_cursor.execute('insert into tx_input(tx_id, input_index, src_address, satoshis,'
                                  'src_tx_hash, src_tx_output_index, coinbase) values(?,?,?,?,?,?,?)',
                                  (tx_id, input_index, addr, satoshis, related_tx_hash, related_tx_index,
                                   coinbase))
                if addr_id:
                    self.addr_bal_updated[addr_id] = True
                input_db_id = db_cursor.lastrowid
                related_tx_hash_cached = None
            else:
                (input_db_id, src_address_cached, satoshis_cached, related_tx_hash_cached, related_tx_index_cached,
                 coinbase_cached) = row

                if (src_address_cached != addr or satoshis_cached != satoshis or
                    related_tx_hash_cached != related_tx_hash or related_tx_index_cached != related_tx_index or
                    coinbase_cached != coinbase):

                    if addr_id:
                        self.addr_bal_updated[addr_id] = True

                    # update db if there is any discrepency with the data fetched from the network; it may be
                    # caused by the network problems or the chain reorganization
                    db_cursor.execute('update tx_input set src_address=?, satoshis=?, src_tx_hash=?, '
                                      'src_tx_output_index=?, coinbase=? where id=?',
                                      (addr, satoshis, related_tx_hash, related_tx_index, coinbase, input_db_id))

                    log.warning(f'Updating tx_input id {input_db_id} due to the data discrepency between cache and '
                                f'the Dash network')

            if related_tx_hash and related_tx_hash_cached != related_tx_hash:
                # mark related utxos as spent
                db_cursor.execute(
                    'update tx_output set spent_tx_hash=?, spent_input_index=? '
                    ' where exists(select 1 from tx where tx.id=tx_output.tx_id and tx.tx_hash=?) '
                    ' and output_index=? and (spent_tx_hash is null or spent_tx_hash<>? or spent_input_index is null '
                    '  or spent_input_index <> ?)',
                    (tx_hash, input_index, related_tx_hash, related_tx_index, tx_hash, input_index))
                rc = db_cursor.rowcount
        else:
            log.warning(f'Input index number {input_index} exceeds the number of transaction inputs ({len(vins)}); '
                        f'tx_id: {tx_id}')

        return input_db_id

    def _purge_unconfirmed_transactions(self, db_cursor):
        db_cursor2 = None
        try:
            limit_ts = int(time.time()) - UNCONFIRMED_TX_PURGE_SECONDS
            db_cursor.execute('select id, tx_hash from tx where block_height=? and block_timestamp<?',
                              (UNCONFIRMED_TX_BLOCK_HEIGHT, limit_ts))
            for tx_row in db_cursor.fetchall():
                if not db_cursor2:
                    db_cursor2 = self.db_intf.get_cursor()
                self.purge_transaction(tx_row[0], tx_row[1], db_cursor2)
        finally:
            if db_cursor2:
                self.db_intf.release_cursor()  # we are releasing cursor2
            self.db_intf.commit()

    def _check_terminate_tx_fetch(self):
        if self.__waiting_tx_fetch_priority is not None and \
           self.__cur_tx_fetch_priority < self.__waiting_tx_fetch_priority:
            raise BreakFetchTransactionsException('Break fetch transactions')

    def _wait_for_tx_fetch_terminate(self, new_priority: int):
        """ Waits for the current tx fetch process terminates if started from another thread. """

        if self.__tx_fetch_end_event.is_set():
            self.__tx_fetch_end_event.clear()

        while self.__waiting_tx_fetch_priority is not None:
            self.__tx_fetch_end_event.wait(1)
            if self.__tx_fetch_end_event.is_set():
                self.__tx_fetch_end_event.clear()

        self.__waiting_tx_fetch_priority = new_priority

        while self.__cur_tx_fetch_priority is not None:
            self.__tx_fetch_end_event.wait(1)
            if self.__tx_fetch_end_event.is_set():
                self.__tx_fetch_end_event.clear()

        self.__waiting_tx_fetch_priority = None
        self.__cur_tx_fetch_priority = new_priority

    def _reset_scan_metrics(self):
        self.scan_metrics_scanned_address_count = 0
        self.scan_metrics_txes_fetched = 0
        self.scan_metrics_bytes_received = 0
        self.scan_metrics_bytes_sent = 0
        self.scan_metrics_rpc_time_ms = 0
        self.scan_metrics_bytes_received_start_value = self.dashd_intf.metrics_bytes_received
        self.scan_metrics_bytes_sent_start_value = self.dashd_intf.metrics_bytes_sent
        self.scan_metrics_rpc_time_ms_start_value = self.dashd_intf.metrics_rpc_time_ms

    def compute_scan_metrics(self):
        self.scan_metrics_bytes_received = int(self.dashd_intf.metrics_bytes_received - self.scan_metrics_bytes_received_start_value)
        self.scan_metrics_bytes_sent = int(self.dashd_intf.metrics_bytes_sent - self.scan_metrics_bytes_sent_start_value)
        self.scan_metrics_rpc_time_ms = int(self.dashd_intf.metrics_rpc_time_ms - self.scan_metrics_rpc_time_ms_start_value)

    def get_scan_metrics(self) -> Dict:
        try:
            self.compute_scan_metrics()
            m = {
                'scanned_address_count': self.scan_metrics_scanned_address_count,
                'txes_fetched': self.scan_metrics_txes_fetched,
                'bytes_received': self.scan_metrics_bytes_received,
                'bytes_sent': self.scan_metrics_bytes_sent,
                'rpc_time_ms': self.scan_metrics_rpc_time_ms,
                'rpc_bytes_per_s': (self.scan_metrics_bytes_received + self.scan_metrics_bytes_sent) / self.scan_metrics_rpc_time_ms / 1000 if self.scan_metrics_rpc_time_ms else 0
            }
            return m
        except Exception as e:
            return {}

    def fetch_all_accounts_txs(self, check_break_process_fun: Callable, priority: int = DEFAULT_TX_FETCH_PRIORITY):

        def scan_account_txs(account, db_cursor):
            for change in (0, 1):
                if check_break_process_fun and check_break_process_fun():
                    break

                change_level_node = account.get_child_entry(change)
                change_level_node.read_from_db(db_cursor, create=True)
                change_level_node.evaluate_address_if_null(db_cursor, self.dash_network)
                self._fetch_child_addrs_txs(change_level_node, account, check_break_process_fun)
            self._update_addr_balances(account)
            account.read_from_db(db_cursor)
            account.evaluate_address_if_null(db_cursor, self.dash_network)

        log.debug('Starting fetching transactions for all accounts.')
        self._wait_for_tx_fetch_terminate(priority)
        try:
            self.validate_hd_tree()
            self.increase_ext_call_level()
            self._reset_scan_metrics()
            db_cursor = self.db_intf.get_cursor()

            try:
                account_ids_scanned = []

                for idx in range(MAX_BIP44_ACCOUNTS):
                    if check_break_process_fun and check_break_process_fun():
                        break

                    account_address_index = 0x80000000 + idx
                    account = self._get_account_by_index(account_address_index, db_cursor)
                    if account.status != 2:
                        scan_account_txs(account, db_cursor)
                        account_ids_scanned.append(account.id)
                    if not account.received:
                        break

                for acc_id in self.account_by_id:
                    account = self.account_by_id[acc_id]
                    if account.id not in account_ids_scanned and account.status != 2:
                        scan_account_txs(account, db_cursor)
                        account_ids_scanned.append(account.id)

            finally:
                if db_cursor.connection.total_changes > 0:
                    self.db_intf.commit()
                self.db_intf.release_cursor()
                self.decrease_ext_call_level()

        finally:
            self.__cur_tx_fetch_priority = None
            self.__tx_fetch_end_event.set()
        log.debug('Finished fetching transactions for all accounts.')

    def fetch_account_txs_xpub(self, account: Union[Bip44AccountType, str], change: int,
                               check_break_process_fun: Optional[Callable], priority: int = DEFAULT_TX_FETCH_PRIORITY):
        """
        Dedicated for scanning external xpub accounts (not managed by the current hardware wallet) to find the
        first not used ("fresh") addres to be used as a transaction destination.
        :param account: the account xpub or Bip44AccountType object
        :param change: 0 or 1
        """

        self._wait_for_tx_fetch_terminate(priority)
        try:
            tm_begin = time.time()
            self.validate_hd_tree()
            self.increase_ext_call_level()
            db_cursor = self.db_intf.get_cursor()
            self._reset_scan_metrics()
            try:
                if isinstance(account, str):
                    acc = self._get_key_entry_by_xpub(account)
                else:
                    # use the cached account object since it probably has its child keys already loaded
                    acc = self.account_by_id.get(account.id)
                    if not acc:
                        acc = account
                change_level_node = acc.get_child_entry(change)
                change_level_node.read_from_db(db_cursor, create=True)
                change_level_node.evaluate_address_if_null(db_cursor, self.dash_network)
                self._fetch_child_addrs_txs(change_level_node, acc, check_break_process_fun)
                self._update_addr_balances(acc)
            finally:
                self.decrease_ext_call_level()
                self.db_intf.release_cursor()
        finally:
            self.__cur_tx_fetch_priority = None
            self.__tx_fetch_end_event.set()

        log.debug(f'fetch_account_xpub_txs exec time: {time.time() - tm_begin}s')

    def find_xpub_first_unused_address(self, account: Union[Bip44AccountType, str], change: int) -> \
            Optional[Bip44AddressType]:

        self.fetch_account_txs_xpub(account, change, check_break_process_fun=None, priority=DEFAULT_TX_FETCH_PRIORITY+1)
        db_cursor = self.db_intf.get_cursor()
        try:
            if isinstance(account, str):
                acc = self._get_key_entry_by_xpub(account)
            else:
                # use the cached account object since it probably has its child keys already loaded
                acc = self.account_by_id.get(account.id)
                if not acc:
                    acc = account
            change_level_node = acc.get_child_entry(change)
            change_level_node.read_from_db(db_cursor, create=True)
            change_level_node.evaluate_address_if_null(db_cursor, self.dash_network)

            for addr in self._list_child_addresses(change_level_node, 0, MAX_ADDRESSES_TO_SCAN, account):
                self._check_terminate_tx_fetch()
                if not addr.received:
                    return addr
        finally:
            self.decrease_ext_call_level()
            self.db_intf.release_cursor()
        return None

    def scan_wallet_for_address(self, addr: str, check_break_process_fun: Callable,
                                feedback_fun: Callable[[int], None]) -> Optional[Bip44AddressType]:
        """
        Scans for a specific address. If necessary, the method fetches transactions to reveal the all used addresses.
        :param addr: the address being searched.
        """
        addr_found: Optional[Bip44AddressType] = None

        def new_address_fetched(new_addr: Bip44AddressType):
            nonlocal addr, addr_found
            if addr == new_addr.address:
                addr_found = new_addr

        def check_finish():
            nonlocal addr_found
            if addr_found or check_break_process_fun():
                raise BreakFetchTransactionsException()

        old_add_loaded_feedback = self.on_address_loaded_callback
        try:
            self.on_address_loaded_callback = new_address_fetched
            self.on_fetch_account_txs_feedback = feedback_fun
            self.fetch_all_accounts_txs(check_finish)
        except BreakFetchTransactionsException:
            if not addr_found:
                return None
        finally:
            self.on_address_loaded_callback = old_add_loaded_feedback
        return addr_found

    def purge_transaction(self, tx_id: int, tx_hash: str, db_cursor=None):
        log.info('Purging timed-out unconfirmed transaction (td_id: %s).', tx_id)
        if not db_cursor:
            db_cursor = self.db_intf.get_cursor()
            release_cursor = True
        else:
            release_cursor = False

        try:
            mod_addr_ids = []

            # following addressses will have the balance changed after purging the transaction
            db_cursor.execute('select a.id from tx_output o join address a on a.address=o.address '
                              'where (tx_id=? or spent_tx_hash=?)'
                              ' union '
                              'select a.id from tx_input i join address a on a.address=i.src_address '
                              'where tx_id=?',
                              (tx_id, tx_hash, tx_id))

            for row in db_cursor.fetchall():
                if not row[0] in mod_addr_ids:
                    mod_addr_ids.append(row[0])

            # list all transaction outputs that were previously spent - due to the transaction deletion
            # they are no longer spent, so we add them to the "new" utxos list
            db_cursor.execute('select id from tx_output where spent_tx_hash=?', (tx_hash,))
            for row in db_cursor.fetchall():
                self._utxo_added(row[0])
            db_cursor.execute('update tx_output set spent_tx_hash=null, spent_input_index=null where spent_tx_hash=?',
                              (tx_hash,))

            db_cursor.execute('select id from tx_output where tx_id=?', (tx_id,))
            for row in db_cursor.fetchall():
                self._utxo_removed(row[0])

            db_cursor.execute('delete from tx_output where tx_id=?', (tx_id,))
            db_cursor.execute('delete from tx_input where tx_id=?', (tx_id,))
            db_cursor.execute('delete from tx where id=?', (tx_id,))
            self._tx_removed(tx_id)

            self._update_addr_balances(account=None, addr_ids=mod_addr_ids, db_cursor=db_cursor)
        finally:
            if db_cursor.rowcount:
                self.db_intf.commit()
            if release_cursor:
                self.db_intf.release_cursor()

    def _update_addr_balances(self, account: Optional[Bip44AccountType], addr_ids: List[int]=None, db_cursor=None):
        """ Update the 'balance' and 'received' fields of all addresses belonging to a given
        bip44 account (account_id) or of all addresses whose ids has been passed in addr_ids list.
        """

        if not db_cursor:
            db_cursor = self.db_intf.get_cursor()
            release_cursor = True
        else:
            release_cursor = False

        try:
            accounts_to_update = []
            cur_tree_id = self.get_tree_id()

            if addr_ids:
                # update balances for specific addresses
                addr_ids = list(set(addr_ids))  # remove duplicate ids
                self._fill_temp_ids_table(addr_ids, db_cursor)

                db_cursor.execute(
                    "select id, account_id, real_received, "
                    "real_spent + real_received real_balance, tree_id from (select a.id id, aa.id account_id, "
                    "a.received, (select ifnull(sum(satoshis), 0) from tx_output o where o.address = a.address) "
                    "real_received, a.balance, (select ifnull(sum(satoshis), 0) "
                    "from tx_input o where o.src_address = a.address) real_spent, aa.tree_id tree_id from address a "
                    "left join address ca on ca.id = a.parent_id left join address aa on aa.id = ca.parent_id "
                    "where a.id in (select id from temp_ids)) "
                    "where received <> real_received or balance <> real_received + real_spent")
            elif account:
                account.last_verify_balance_ts = int(time.time())
                db_cursor.execute(
                   "select id, account_id, real_received, real_spent + real_received real_balance, "
                   "tree_id from (select a.id id, ca.id change_id, aa.id account_id, "
                   "a.received, (select ifnull(sum(satoshis), 0) from tx_output o where o.address = a.address) "
                   "real_received, a.balance, (select ifnull(sum(satoshis), 0) "
                   "from tx_input o where o.src_address = a.address) real_spent, aa.tree_id tree_id from address a "
                   "join address ca on ca.id = a.parent_id join address aa on aa.id = ca.parent_id where aa.id=?) "
                   "where received <> real_received or balance <> real_received + real_spent", (account.id,))
            else:
                raise Exception('Both arguments account_id and addr_ids are empty')

            for addr_id, acc_id, real_received, real_balance, tree_id in db_cursor.fetchall():
                if acc_id is not None and acc_id not in accounts_to_update:
                    # after updating balances of the addresses, update balance the related accounts
                    accounts_to_update.append(acc_id)

                db_cursor.execute('update address set balance=?, received=? where id=?',
                                  (real_balance, real_received, addr_id))

                if self.on_address_data_changed_callback:
                    if account:
                        address = account.address_by_id(addr_id)
                    else:
                        address, account = self._find_address_item_in_cache_by_id(addr_id)

                    if address:
                        address.balance = real_balance
                        address.received = real_received
                        self.signal_address_data_changed(account, address)

            if account and account.id not in accounts_to_update:
                accounts_to_update.append(account.id)

            self._fill_temp_ids_table(accounts_to_update, db_cursor)
            db_cursor.execute(
                "select balance, real_balance, received, real_received, id, tree_id from ("
                "  select aa.id, aa.tree_id, aa.balance,"
                "       (select ifnull(sum(a.balance),0) from address ca join address a"
                "            on a.parent_id=ca.id where ca.parent_id=aa.id) real_balance,"
                "       aa.received,"
                "       (select ifnull(sum(a.received),0) from address ca join address a "
                "           on a.parent_id=ca.id where ca.parent_id=aa.id) real_received "
                "from address aa where aa.id in (select id from temp_ids)) " 
                "where balance<>real_balance or received<>real_received")

            for balance, real_balance, received, real_received, acc_id, acc_tree_id in db_cursor.fetchall():
                db_cursor.execute('update address set balance=?, received=? where id=?',
                                  (real_balance, real_received, acc_id))

                if cur_tree_id and acc_tree_id == cur_tree_id:
                    account = self._get_account_by_id(acc_id, db_cursor, force_reload=True)
                    if account:
                        account.balance = real_balance
                        account.received = real_received
                        self.signal_account_data_changed(account)

        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            if release_cursor:
                self.db_intf.release_cursor()

    def _wrap_txid(self, txid: str):
        # base64 format takes less space in the db than hex string
        # return base64.b64encode(bytes.fromhex(txid))
        return txid

    def _unwrap_txid(self, txid_wrapped: str):
        # return base64.b64decode(txid_wrapped).hex()
        return txid_wrapped

    def _get_utxo(self, id: int, tx_hash: str, address_id: int, output_index: int, satoshis: int,
                  block_height: int, block_ts: int, coinbase: int):
        utxo = self.utxos_by_id.get(id)
        if not utxo:
            utxo = UtxoType()
            self.utxos_by_id[id] = utxo
        utxo.id = id
        utxo.txid = self._unwrap_txid(tx_hash)
        if not address_id:
            utxo.address_obj = None
        else:
            utxo.address_obj = self.addresses_by_id.get(address_id)
        utxo.output_index = output_index
        utxo.satoshis = satoshis
        utxo.block_height = block_height
        utxo.time_stamp = block_ts
        utxo.time_str = app_utils.to_string(datetime.datetime.fromtimestamp(block_ts))
        utxo.coinbase = coinbase
        utxo.get_cur_block_height_fun = self.get_block_height_nofetch
        return utxo

    def list_utxos_for_account(self, account_id: Optional[int], only_new = False,
                               filter_by_satoshis: Optional[int] = None) -> Generator[UtxoType, None, None]:
        """
        :param account_id: database id of the account's record or None if listing for all accounts of the current
          hd tree if.
        """
        tm_begin = time.time()
        self.validate_hd_tree()
        db_cursor = self.db_intf.get_cursor()
        try:
            params = []
            sql_text = "select o.id, tx.block_height, tx.coinbase, tx.block_timestamp," \
                       "tx.tx_hash, o.output_index, o.satoshis, a.id from tx_output o " \
                       "join address a on a.address=o.address join address cha on cha.id=a.parent_id join address aca "\
                       "on aca.id=cha.parent_id join tx on tx.id=o.tx_id where (spent_tx_hash is null " \
                       "or spent_input_index is null) and a.tree_id=?"
            params.append(self.__tree_id)

            if account_id:
                sql_text += ' and aca.id=?'
                params.append(account_id)
            else:
                sql_text += ' and aca.tree_id=?'
                params.append(self.__tree_id)

            if filter_by_satoshis:
                sql_text += ' and o.satoshis=?'
                params.append(filter_by_satoshis)

            if only_new:
                # limit returned utxos only to those existing in the self.utxos_added list
                self._fill_temp_ids_table([id for id in self.utxos_added], db_cursor)
                sql_text += ' and o.id in (select id from temp_ids)'
            sql_text += " order by tx.block_height desc"

            t = time.time()
            db_cursor.execute(sql_text, params)
            log.debug('SQL exec time: %s', time.time() - t)

            for id, block_height, coinbase, block_timestamp, tx_hash, \
                output_index, satoshis, address_id in db_cursor.fetchall():

                utxo = self._get_utxo(id, tx_hash, address_id, output_index, satoshis, block_height,
                                      block_timestamp, coinbase)
                yield utxo
        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()

        diff = time.time() - tm_begin
        log.debug('list_utxos_for_account exec time: %ss', diff)

    def list_utxos_for_addresses(self, address_ids: List[int], only_new = False,
                                 filter_by_satoshis: Optional[int] = None) -> Generator[UtxoType, None, None]:
        db_cursor = self.db_intf.get_cursor()
        try:
            params = []
            sql_text = "select o.id, tx.block_height, tx.coinbase,tx.block_timestamp, tx.tx_hash, o.output_index, " \
                       "o.satoshis, a.id from tx_output o join address a" \
                       " on a.address=o.address join tx on tx.id=o.tx_id where (spent_tx_hash is null " \
                       " or spent_input_index is null) and a.id in (select id from temp_ids2) and a.tree_id=?"
            params.append(self.__tree_id)

            self._fill_temp_ids_table(address_ids, db_cursor, tab_sufix='2')

            if only_new:
                # limit returned utxos only to those existing in the self.utxos_added list
                self._fill_temp_ids_table([id for id in self.utxos_added], db_cursor)
                sql_text += ' and o.id in (select id from temp_ids)'

            if filter_by_satoshis:
                sql_text += ' and o.satoshis=?'
                params.append(filter_by_satoshis)

            sql_text += " order by tx.block_height desc"

            db_cursor.execute(sql_text, params)

            for id, block_height, coinbase, block_timestamp, tx_hash, \
                output_index, satoshis, address_id in db_cursor.fetchall():

                utxo = self._get_utxo(id, tx_hash, address_id, output_index, satoshis, block_height,
                                      block_timestamp, coinbase)

                yield utxo

        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()

    def list_utxos_for_ids(self, utxo_ids: List[int]) -> Generator[UtxoType, None, None]:
        db_cursor = self.db_intf.get_cursor()
        try:
            self._fill_temp_ids_table(utxo_ids, db_cursor)

            sql_text = "select o.id, tx.block_height, tx.coinbase,tx.block_timestamp, tx.tx_hash, o.output_index, " \
                       "o.satoshis, a.id from tx_output o join address a" \
                       " on a.address=o.address join tx on tx.id=o.tx_id where (spent_tx_hash is null " \
                       " or spent_input_index is null) and o.id in (select id from temp_ids) " \
                       " and a.tree_id=? order by tx.block_height desc"

            db_cursor.execute(sql_text, (self.__tree_id,))

            for id, block_height, coinbase, block_timestamp, tx_hash, \
                output_index, satoshis, address_id in db_cursor.fetchall():

                utxo = self._get_utxo(id, tx_hash, address_id, output_index, satoshis, block_height,
                                      block_timestamp, coinbase)

                yield utxo

        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()

    def _prepare_cursor_for_txs_list(self, db_cursor, account_id: Optional[int], address_ids: Optional[List[int]]):

        cond_params = []
        if account_id is not None:
            condition = ' join address ach on ach.id=a.parent_id join address aca on aca.id=ach.parent_id where ' \
                        'aca.id=? '
            cond_params.append(account_id)
        elif address_ids:
            condition = ' where a.id in (select id from temp_ids) '
            self._fill_temp_ids_table(address_ids, db_cursor)
        else:
            condition = ''

        params = []
        sql_text = """
            select -1 type,
                   group_concat(DISTINCT a.id) src_addr_ids,
                   (select group_concat(DISTINCT ifnull(null,'')||':'||o.address||':'||output_index||':'||o.satoshis) 
                    from tx_output o where o.tx_id=t.id) rcp_addresses,
                   sum(i.satoshis),
                   t.id,
                   t.tx_hash,
                   t.block_height,
                   t.block_timestamp,
                   0 is_coinbase,
                   -1
            from tx_input i join tx t on t.id=i.tx_id join address a on a.address=i.src_address and a.tree_id=?"""

        params.append(self.__tree_id)
        params.extend(cond_params)

        sql_text += condition + """ group by t.id
            union
            select 1 type,
                   group_concat(DISTINCT ifnull(ai.id,'')||':'||ai.address),
                   ifnull(a.id,'')||':'||a.address||':'||o.output_index||':'||o.satoshis,
                   o.satoshis,
                   t.id,
                   t.tx_hash,
                   t.block_height,
                   t.block_timestamp, max(i.coinbase) is_coinbase,
                   o.id
            from tx_output o join tx t on t.id=o.tx_id join address a on a.address=o.address and a.tree_id=?
            join tx_input i on i.tx_id=t.id left join address ai on ai.address=i.src_address and ai.tree_id=?"""

        params.append(self.__tree_id)
        params.append(self.__tree_id)
        params.extend(cond_params)

        sql_text += condition + """ group by o.id
            order by block_height desc, type desc"""

        t = time.time()
        db_cursor.execute(sql_text, params)
        log.debug('SQL exec time: %s', time.time() - t)

    def _parse_addrs_str_gen(self, addrs_str: str) -> Generator[Union[Bip44AddressType, str], None, None]:
        """addrs_str: address:address_id:tx_index:amount """
        if addrs_str:
            for addr_str in addrs_str.split(','):
                elems = addr_str.split(':')
                id = None
                if len(elems):
                    id = elems.pop(0)
                if len(elems):
                    addr_str = elems.pop(0)
                if id:
                    id = int(id)
                    a = self.addresses_by_id.get(id)
                    if a:
                        yield a
                else:
                    yield addr_str

    def list_txs(self, account_id: Optional[int], address_ids: Optional[List[int]], only_new = False) -> \
            Generator[TxType, None, None]:

        tm_begin = time.time()
        if account_id:
            self.validate_hd_tree()  # we don't need a hw connection when scanning specific addresses
        db_cursor = self.db_intf.get_cursor()
        try:
            self._prepare_cursor_for_txs_list(db_cursor, account_id, address_ids)

            for type, snd_addrs, rcp_addrs, satoshis, tx_id, tx_hash, bh, bts, is_coinbase, output_id \
                    in db_cursor.fetchall():

                tx = TxType()
                tx.id = str(tx_id) + ':' + str(output_id) + ':' + str(type)
                tx.tx_hash = tx_hash
                tx.is_coinbase = is_coinbase
                tx.satoshis = satoshis
                tx.direction = type
                tx.block_height = bh
                tx.block_timestamp = bts
                tx.block_time_str = app_utils.to_string(datetime.datetime.fromtimestamp(bts))
                for a in self._parse_addrs_str_gen(snd_addrs):
                    tx.sender_addrs.append(a)
                for a in self._parse_addrs_str_gen(rcp_addrs):
                    tx.recipient_addrs.append(a)
                yield tx
        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()

        diff = time.time() - tm_begin
        log.debug('list_utxos_for_account exec time: %ss', diff)

    def list_accounts(self) -> Generator[Bip44AccountType, None, None]:
        tm_begin = time.time()
        self.validate_hd_tree()
        db_cursor = self.db_intf.get_cursor()
        try:
            tree_id = self.get_tree_id()

            db_cursor.execute("select id from address where parent_id is null and xpub_hash is not null and tree_id=? "
                              "order by address_index",
                              (tree_id,))

            for id, in db_cursor.fetchall():
                acc = self._get_account_by_id(id, db_cursor)

                if not acc.last_verify_balance_ts:
                    self._update_addr_balances(acc, None, db_cursor)

                yield acc
        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()
        diff = time.time() - tm_begin
        log.debug(f'Accounts read time: {diff}s')

    def force_show_account(self, account_index: int, check_break_process_fun: Optional[Callable],
                           priority: int = DEFAULT_TX_FETCH_PRIORITY) -> Bip44AccountType:
        """ Show account that hasn't been revealed during BIP44 account discovery process: it's an empty account or
        there is a gap between it and the last used account (having any tx history).
        """

        self._wait_for_tx_fetch_terminate(priority)
        try:
            self.validate_hd_tree()
            self.increase_ext_call_level()
            try:
                db_cursor = self.db_intf.get_cursor()
                try:
                    account_address_index = 0x80000000 + account_index
                    account = self._get_account_by_index(account_address_index, db_cursor)

                    if not account.last_verify_balance_ts:
                        self._update_addr_balances(account, None, db_cursor)

                    for change in (0, 1):
                        if check_break_process_fun and check_break_process_fun():
                            break

                        change_level_node = account.get_child_entry(change)
                        change_level_node.read_from_db(db_cursor, create=True)
                        change_level_node.evaluate_address_if_null(db_cursor, self.dash_network)
                        # self._fetch_child_addrs_txs(change_level_node, account, check_break_process_fun)
                    # self._update_addr_balances(account)
                    account.read_from_db(db_cursor)
                    account.evaluate_address_if_null(db_cursor, self.dash_network)
                    self.set_account_status(account, 1)
                finally:
                    if db_cursor.connection.total_changes > 0:
                        self.db_intf.commit()
                    self.db_intf.release_cursor()
            finally:
                self.decrease_ext_call_level()
        finally:
            self.__cur_tx_fetch_priority = None
            self.__tx_fetch_end_event.set()
        return account

    def register_spending_transaction(self, inputs: List[UtxoType], outputs: List[TxOutputType], tx_json: Dict):
        """
        Register outgoing transaction in the database cache. It will be used util it appears on the blockchain.
        :param inputs:
        :param outputs:
        """
        db_cursor = self.db_intf.get_cursor()
        try:
            txhash = tx_json.get('txid')
            self._process_transaction(db_cursor, txhash, tx_json)
            addr_ids = list(self.addr_bal_updated.keys())
            if addr_ids:
                # if the transaction fetch operation hasn't been completed yet, the list of addresses with updated
                # balance may be empty
                self._update_addr_balances(account=None, addr_ids=addr_ids, db_cursor=db_cursor)
        finally:
            self.db_intf.commit()
            self.db_intf.release_cursor()

    def remove_account(self, id: int):
        log.debug(f'Deleting account from db. Account address db id: {id}')
        db_cursor = self.db_intf.get_cursor()
        try:
            db_cursor.execute("delete from address where parent_id in ("
                              "select a1.id from address a1 where a1.parent_id=?)", (id,))

            db_cursor.execute("delete from address where parent_id=?", (id,))

            db_cursor.execute("delete from address where id=?", (id,))

            acc = self.account_by_id.get(id)
            if acc:
                # remove the all addresses related to this account from an helper-dictionary
                for a in acc.addresses:
                    if a.id in self.addresses_by_id:
                        del self.addresses_by_id[a.id]
                        del self.addresses_by_address[a.address]

                del self.account_by_id[id]
            acc = self.account_by_bip32_path.get(acc.bip32_path)
            if acc:
                del self.account_by_bip32_path[acc.bip32_path]
        finally:
            self.db_intf.commit()
            self.db_intf.release_cursor()

    def remove_address(self, id: int):
        log.debug(f'Deleting address from db. Account address db id: %s', id)
        db_cursor = self.db_intf.get_cursor()
        try:
            db_cursor.execute("update address set last_scan_block_height=0 where id=?", (id,))

            addr, _ = self._find_address_item_in_cache_by_id(id)
            if addr:
                addr.last_scan_block_height = 0

            self._update_addr_balances(None, [id], db_cursor)

        finally:
            self.db_intf.commit()
            self.db_intf.release_cursor()

    def set_label_for_entry(self, entry: Union[Bip44AddressType, Bip44AccountType], label: str):
        db_cursor = self.db_intf.get_cursor()
        try:
            if isinstance(entry, Bip44AddressType):
                address = entry.address
            elif isinstance(entry, Bip44AccountType):
                address = entry.address
            else:
                raise Exception('Invalid argument type')

            entry.label = label
            if entry.address:
                addr_hash = address_to_hash(entry.address)
                db_cursor.execute("select id from labels.address_label where key=?", (addr_hash,))
                row = db_cursor.fetchone()
                if not row:
                    if label:
                        db_cursor.execute('insert into labels.address_label(key, label, timestamp) values(?,?,?)',
                                          (addr_hash, label, int(time.time())))
                else:
                    if label:
                        db_cursor.execute('update labels.address_label set label=?, timestamp=? where id=?',
                                          (label, int(time.time()), row[0]))
                    else:
                        db_cursor.execute('delete from labels.address_label where id=?', (row[0],))
                db_cursor.execute('update address set label=? where id=?', (label, entry.id))
            else:
                log.error('This entry has null address value: %s', entry.id)
                return
        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()

        if isinstance(entry, Bip44AddressType):
            addr_loc = self.addresses_by_id.get(entry.id)
            if addr_loc:
                addr_loc.label = label
            self.signal_account_address_added(entry.bip44_account, entry)
        elif isinstance(entry, Bip44AccountType):
            acc_loc = self.account_by_id.get(entry.id)
            if acc_loc:
                acc_loc.label = label
            self.signal_account_data_changed(entry)

    def set_account_status(self, account: Bip44AccountType, status: int):
        if status not in (1, 2):
            raise Exception('Invalid status: ' + str(status))

        db_cursor = self.db_intf.get_cursor()
        try:
            account.status = status
            db_cursor.execute('update address set status=? where id=?', (status, account.id))

            # update status in the Bip44AccountType object maintained locally (its reference doesn't have to be the
            # same as the object ref passed as an argument to this method
            acc_loc = self.account_by_id.get(account.id)
            if acc_loc:
                acc_loc.status = status
        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()

        self.signal_account_data_changed(account)

    def set_label_for_transaction(self, tx: TxType, label: str):
        db_cursor = self.db_intf.get_cursor()
        # try:
        #
        #     entry.label = label
        #     if entry.address:
        #         addr_hash = address_to_hash(entry.address)
        #         db_cursor.execute("select id from labels.address_label where key=?", (addr_hash,))
        #         row = db_cursor.fetchone()
        #         if not row:
        #             if label:
        #                 db_cursor.execute('insert into labels.address_label(key, label, timestamp) values(?,?,?)',
        #                                   (addr_hash, label, int(time.time())))
        #         else:
        #             if label:
        #                 db_cursor.execute('update labels.address_label set label=?, timestamp=? where id=?',
        #                                   (label, int(time.time()), row[0]))
        #             else:
        #                 db_cursor.execute('delete from labels.address_label where id=?', (row[0],))
        #         db_cursor.execute('update address set label=? where id=?', (label, entry.id))
        #     else:
        #         log.error('This entry has null address value: %s', entry.id)
        #         return
        # finally:
        #     if db_cursor.connection.total_changes > 0:
        #         self.db_intf.commit()
        #     self.db_intf.release_cursor()

    def set_label_for_hw_identity(self, id: int, label: str):
        db_cursor = self.db_intf.get_cursor()
        try:
            db_cursor.execute("update hd_tree set label=? where id=?", (label, id))
            if self.__tree_id == id:
                self.__tree_label = label
        finally:
            self.db_intf.commit()
            self.db_intf.release_cursor()

    def delete_hd_identity(self, id: int):
        db_cursor = self.db_intf.get_cursor()
        try:
            db_cursor.execute("delete from address where id in (select ca.parent_id from address a join address ca "
                              "on ca.id=a.parent_id where a.tree_id=?)", (id,))
            db_cursor.execute("delete from address where id in (select a.parent_id from address a where a.tree_id=?)",
                              (id,))
            db_cursor.execute("delete from address where tree_id=?", (id,))
            db_cursor.execute("delete from main.hd_tree where id=?", (id,))
            if self.__tree_id == id:
                self.clear()
        finally:
            self.db_intf.commit()
            self.db_intf.release_cursor()


#########################################################
## Util functions
#########################################################
def get_tx_address_thread(ctrl: CtrlObject, addresses: List[str], bip44_wallet: Bip44Wallet) -> \
        List[Optional[Bip44AddressType]]:
    ret_addresses = []
    break_scanning = False
    txes_cnt = 0
    msg = 'Looking for a BIP32 path of the Dash address related to the masternode collateral.<br>' \
          'This may take a while (<a href="break">break</a>)....'
    ctrl.dlg_config(dlg_title="Looking for address", show_progress_bar=False)
    ctrl.display_msg(msg)

    def check_break_scanning():
        nonlocal break_scanning
        if break_scanning:
            # stop the scanning process if the dialog finishes or the address/bip32path has been found
            raise BreakFetchTransactionsException()

    def fetch_txes_feeback(tx_cnt: int):
        nonlocal msg, txes_cnt
        txes_cnt += tx_cnt
        ctrl.display_msg(msg + '<br><br>' + 'Number of transactions fetched so far: ' + str(txes_cnt))

    def on_msg_link_activated(link: str):
        nonlocal break_scanning
        if link == 'break':
            break_scanning = True

    lbl = ctrl.get_msg_label_control()
    if lbl:
        def set():
            lbl.setOpenExternalLinks(False)
            lbl.setTextInteractionFlags(lbl.textInteractionFlags() & ~Qt.TextSelectableByMouse)
            lbl.linkActivated.connect(on_msg_link_activated)
            lbl.repaint()
        WndUtils.call_in_main_thread(set)

    # fetch the transactions that involved the addresses stored in the wallet - during this
    # all the used addresses are revealed
    for a in addresses:
        addr = bip44_wallet.scan_wallet_for_address(a, check_break_scanning, fetch_txes_feeback)
        if not addr and break_scanning:
            raise CancelException
        ret_addresses.append(addr)
    return ret_addresses


def find_wallet_addresses(address: Union[str, List[str]], bip44_wallet: Bip44Wallet) -> List[Optional[Bip44AddressType]]:
    ret = WndUtils.run_thread_dialog(get_tx_address_thread, (address, bip44_wallet), True)
    return ret


