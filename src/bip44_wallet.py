#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-07

import time
import base64
import bisect
import bitcoin
import datetime
import logging
from bip32utils import BIP32Key, Base58
from collections import namedtuple
from typing import List, Dict, Tuple, Optional, Any, Generator, NamedTuple, Callable, ByteString, Union
import app_utils
import hw_intf
from common import AttrsProtected
from dash_utils import bip32_path_string_to_n, pubkey_to_address, bip32_path_n_to_string, bip32_path_string_append_elem
from dashd_intf import DashdInterface
from hw_common import HwSessionInfo
from db_intf import DBCache
from wallet_common import Bip44AccountType, Bip44AddressType, UtxoType, TxOutputType, xpub_to_hash, Bip44Entry, \
    address_to_hash

TX_QUERY_ADDR_CHUNK_SIZE = 10
ADDRESS_SCAN_GAP_LIMIT = 20
MAX_ADDRESSES_TO_SCAN = 1000
MAX_BIP44_ACCOUNTS = 200
GET_BLOCKHEIGHT_MIN_SECONDS = 30
UNCONFIRMED_TX_PURGE_SECONDS = 60


log = logging.getLogger('dmt.bip44_wallet')


class Bip44Wallet(object):
    def __init__(self, coin_name: str, hw_session: HwSessionInfo, db_intf: DBCache, dashd_intf: DashdInterface, dash_network: str):
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

        # list of accounts retrieved while calling self.list_accounts
        self.account_by_id: Dict[int, Bip44AccountType] = {}
        self.account_by_bip32_path: Dict[str, Bip44AccountType] = {}  # todo: clear when switching

        # list of addresses created withing the current hd tree
        self.addresses_by_id: Dict[int, Bip44AddressType] = {}
        # addresses whose balance has been modified since the last call of reset_tx_diffs
        self.addr_bal_updated: Dict[int, int] = {}  # {'address_id': 'address_id' }
        self.addr_ids_created: Dict[int, int] = {}  # {'address_id': 'address_id' }

        # transactions added/modified since the last reset_tx_diffs call
        self.txs_added: Dict[int, int] = {}  # {'tx_id': 'address_id'}
        self.txs_removed: Dict[int, int] = {}  # {'tx_id': 'tx_id'}

        # utxos added/removed since the last reset_tx_diffs call
        self.utxos_by_id: Dict[int, UtxoType] = {}
        self.utxos_added: Dict[int, int] = {}  # {'tx_output.id': 'tx_output.id'}
        self.utxos_removed: Dict[int, int] = {}  # {'tx_output.id': 'tx_output.id'}

        self.purge_unconf_txs_called = False
        self.external_call_level = 0

        self.on_account_added_callback: Callable[[Bip44AccountType], None] = None
        self.on_account_data_changed_callback: Callable[[Bip44AccountType], None] = None
        self.on_account_address_added_callback: Callable[[Bip44AccountType, Bip44AddressType], None] = None
        self.on_address_data_changed_callback: Callable[[Bip44AccountType, Bip44AddressType], None] = None

    def reset_tx_diffs(self):
        self.txs_added.clear()
        self.txs_removed.clear()
        self.utxos_added.clear()
        self.utxos_removed.clear()
        self.addr_bal_updated.clear()
        self.addr_ids_created.clear()

    def clear(self):
        self.__tree_id = None
        self.account_by_id.clear()
        self.account_by_bip32_path.clear()
        self.addresses_by_id.clear()
        self.utxos_by_id.clear()
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
        if self.__tree_ident != self.hw_session.get_hd_tree_ident(self.__coin_name):
            # user switched to another hw identity (e.g. enter bip39 different passphrase)
            log.info('Switching HD identity')
            self.clear()

    def get_block_height(self):
        if self.cur_block_height is None or \
           (time.time() - self.last_get_block_height_ts >= GET_BLOCKHEIGHT_MIN_SECONDS):
            self.cur_block_height = self.dashd_intf.getblockcount()
            self.last_get_block_height_ts = time.time()
        return self.cur_block_height

    def get_block_height_nofetch(self):
        return self.cur_block_height

    def get_address_id(self, address: str, db_cursor):
        db_cursor.execute('select id from address where address=?', (address,))
        row = db_cursor.fetchone()
        if row:
            return row[0]
        return None

    def get_address_item(self, address: str, create: bool) -> Optional[Bip44AddressType]:
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
            elif create:
                db_cursor.execute('insert into address(address) values(?)', (address,))
                addr = Bip44AddressType(tree_id=None)
                addr.address = address
                addr.id = db_cursor.lastrowid
                self.addresses_by_id[addr.id] = addr
                self.db_intf.commit()
                self.addr_ids_created[addr.id] = addr.id
            else:
                return None
            self.addresses_by_id[addr.id] = addr
            return addr
        finally:
            self.db_intf.release_cursor()

    def _find_address_item_in_cache_by_id(self, addr_id: int, db_cursor) -> Tuple[Bip44AddressType, Bip44AccountType]:
        addr = None
        acc = None
        for acc_id in self.account_by_id:
            acc = self.account_by_id[acc_id]
            addr = acc.address_by_id(addr_id)
            if addr:
                break
        if not addr:
            addr = self.addresses_by_id[addr_id]
        return (addr, acc)

    def _get_bip44_entry_by_xpub(self, xpub) -> Bip44Entry:
        raise Exception('ToDo')

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
        self.addresses_by_id[addr.id] = addr
        return addr

    def _fill_temp_ids_table(self, ids: List[int], db_cursor):
        db_cursor.execute("CREATE TEMPORARY TABLE IF NOT EXISTS temp_ids(id INTEGER PRIMARY KEY)")
        db_cursor.execute('delete from temp_ids')
        db_cursor.executemany('insert into temp_ids(id) values(?)',
                              [(id,) for id in ids])

    def _get_child_address(self, parent_key_entry: Bip44Entry, child_addr_index: int) -> Bip44AddressType:
        """
        :return: Tuple[int <id db>, str <address>, int <balance in duffs>]
        """
        if parent_key_entry.id is None:
            raise Exception('parent_key_entry.is is null')

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
                        addr_info.get('address_index') != child_addr_index or addr_info.get('path') != bip32_path or \
                        addr_info.get('tree_id') != parent_key_entry.tree_id:
                        # address wasn't initially opened as a part of xpub account scan, so update its attrs
                        db_cursor.execute('update address set parent_id=?, address_index=?, path=? where id=?',
                                          (parent_key_entry.id, child_addr_index, bip32_path, row[0]))

                        addr_info['parent_id'] = parent_key_entry.id
                        addr_info['address_index'] = child_addr_index
                        addr_info['path'] = bip32_path
                        addr_info['tree_id'] = parent_key_entry.tree_id

                    return self._get_address_from_dict(addr_info)
                else:
                    h = address_to_hash(address)
                    db_cursor.execute('select label from labels.address_label where key=?', (h,))
                    row = db_cursor.fetchone()
                    if row:
                        label = row[0]
                    else:
                        label = ''

                    db_cursor.execute('insert into address(parent_id, address_index, address, label, path, tree_id) '
                                      'values(?,?,?,?,?,?)',
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
                    self.addr_ids_created[addr_id] = addr_id
                    return self._get_address_from_dict(addr_info)
            else:
                addr_info = dict([(col[0], row[idx]) for idx, col in enumerate(db_cursor.description)])
            return self._get_address_from_dict(addr_info)
        except Exception:
            raise
        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()

    def _get_key_entry_by_xpub(self, xpub: str) -> Bip44Entry:
        raise Exception('ToDo')

    def _list_child_addresses(self, key_entry: Bip44Entry, addr_start_index: int, addr_count: int,
                              account: Bip44AccountType) -> Generator[Bip44AddressType, None, None]:

        tm_begin = time.time()
        try:
            count = 0
            for idx in range(addr_start_index, addr_start_index + addr_count):
                addr_info = self._get_child_address(key_entry, idx)
                if account:
                    is_new, updated, addr_index, addr = account.add_address(addr_info)
                    if is_new:
                        if self.on_account_address_added_callback:
                            self.on_account_address_added_callback(account, addr)

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
            db_cursor.execute('select id, path from address where xpub_hash=?', (xpub_hash,))
            row = db_cursor.fetchone()
            if row:
                id, path = row
                if path != account_bip32_path:
                    # correct the bip32 path since this account could be opened as a xpub address before
                    db_cursor.execute('update address set path=? where id=?', (account_bip32_path, id))
                    self.db_intf.commit()

                account = Bip44AccountType(self.get_tree_id(), id, xpub=xpub, address_index=account_index,
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
            if self.on_account_added_callback:
                self.on_account_added_callback(account)

            log.debug('get_account_base_address_by_index exec time: %s', time.time() - tm_begin)
        else:
            log.debug('get_account_base_address_by_index (used cache) exec time: %s', time.time() - tm_begin)

        return account

    def _get_account_by_id(self, id: int, db_cursor, force_reload=False) -> Bip44AccountType:
        """
        Read the bip44 account data from db (for a given id) and return it as Bip44AccountType.
        """
        account = self.account_by_id.get(id)

        if not account:
            account = Bip44AccountType(self.get_tree_id(), id, xpub='', address_index=None, bip32_path=None)
            account.read_from_db(db_cursor)
            self.account_by_id[id] = account
            if account.bip32_path:
                self.account_by_bip32_path[account.bip32_path] = account

            if account.bip32_path:
                account.xpub = hw_intf.get_xpub(self.hw_session, account.bip32_path)
                account.evaluate_address_if_null(db_cursor, self.dash_network)

            self._read_account_addresses(account, db_cursor)
            if self.on_account_added_callback:
                self.on_account_added_callback(account)
        else:
            if force_reload:
                account.read_from_db(db_cursor)

            if not account.xpub and account.bip32_path:
                account.xpub = hw_intf.get_xpub(self.hw_session, account.bip32_path)
                account.evaluate_address_if_null(db_cursor, self.dash_network)
        return account

    def _read_account_addresses(self, account: Bip44AccountType, db_cursor):
        db_cursor.execute('select a.id, a.address_index, a.address, ac.path parent_path, a.balance, '
                          'a.received, ac.is_change, a.label from address a join address ac on a.parent_id=ac.id '
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
                account.add_address(addr)
            else:
                addr.update_from_args(balance=add_row[4], received=add_row[5])

    def _process_addresses_created(self, db_cursor):
        if self.addr_ids_created:
            self._fill_temp_ids_table([id for id in self.addr_ids_created], db_cursor)
            db_cursor.execute('select id, address from address where id in (select id from temp_ids)')
            for id, address in db_cursor.fetchall():
                db_cursor.execute('update tx_input set src_address_id=? where src_address_id is null and src_address=?',
                                  (id, address))
                db_cursor.execute('update tx_output set address_id=? where address_id is null and address=?',
                                  (id, address))
            if db_cursor.connection.total_changes:
                self.db_intf.commit()

    def fetch_all_accounts_txs(self, check_break_process_fun: Callable):
        log.debug('Starting fetching transactions for all accounts.')

        self.validate_hd_tree()
        self.addr_ids_created.clear()
        self.increase_ext_call_level()
        try:
            for idx in range(MAX_BIP44_ACCOUNTS):
                if check_break_process_fun and check_break_process_fun():
                    break

                db_cursor = self.db_intf.get_cursor()
                try:
                    account_address_index = 0x80000000 + idx
                    account = self._get_account_by_index(account_address_index, db_cursor)
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
                    self._process_addresses_created(db_cursor)
                    if not account.received:
                        break
                finally:
                    if db_cursor.connection.total_changes > 0:
                        self.db_intf.commit()
                    self.db_intf.release_cursor()
        finally:
            self.decrease_ext_call_level()
        log.debug('Finished fetching transactions for all accounts.')

    # def fetch_account_txs(self, account_index: int, check_break_process_fun: Callable):
    #     log.debug(f'fetch_account_txs account index: {account_index}')
    #     tm_begin = time.time()
    #
    #     self.increase_ext_call_level()
    #     try:
    #         if account_index < 0:
    #             raise Exception('Invalid account number')
    #
    #         account_entry = self._get_account_id_by_index(account_index)
    #         account = self.accounts_by_id.get(account_entry.id)
    #
    #         for change in (0, 1):
    #             if check_break_process_fun and check_break_process_fun():
    #                 break
    #
    #             change_level_entry = account_entry.get_child(change)
    #             self._fetch_child_addrs_txs(change_level_entry, account, check_break_process_fun)
    #         self._update_addr_balances(account)
    #     finally:
    #         self.decrease_ext_call_level()
    #
    #     log.debug(f'fetch_account_txs exec time: {time.time() - tm_begin}s')

    def fetch_account_txs_xpub(self, account_xpub: str, change: int, check_break_process_fun: Callable):
        """
        Dedicated for scanning external xpub accounts (not managed by the current hardware wallet) to find the
        first not used ("fresh") addres to be used as a transaction destination.
        :param account_xpub: xpub of the account
        :param change: 0 or 1 (usually 0, since there is no reason to scan the change addresses)
        """

        tm_begin = time.time()
        self.validate_hd_tree()
        self.addr_ids_created.clear()
        self.increase_ext_call_level()
        db_cursor = self.db_intf.get_cursor()
        try:
            account_entry = self._get_key_entry_by_xpub(account_xpub)
            account = self.account_by_id.get(account_entry.id)
            change_level_node = account_entry.get_child_entry(change)
            change_level_node.read_from_db(db_cursor, create=True)
            change_level_node.evaluate_address_if_null(db_cursor, self.dash_network)
            self._fetch_child_addrs_txs(change_level_node, account, check_break_process_fun)
            self._update_addr_balances(account)
            self._process_addresses_created(db_cursor)
        finally:
            self.decrease_ext_call_level()
            self.db_intf.release_cursor()

        log.debug(f'fetch_account_xpub_txs exec time: {time.time() - tm_begin}s')

    def _fetch_child_addrs_txs(self, key_entry: Bip44Entry, account: Bip44AccountType, check_break_process_fun: Callable = None):
        """

        :param key_entry:
        :param check_break_process_fun:
        :return:
        """

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

                self._process_addresses_txs(addresses, cur_block_height)

                if check_break_process_fun and check_break_process_fun():
                    break

                # count the number of addresses with no associated transactions starting from the end
                _empty_addresses = 0
                db_cursor = self.db_intf.get_cursor()
                try:
                    for addr_info in reversed(addresses):
                        addr_id = addr_info.id

                        # check if there was no transactions for the address
                        if not self.addr_bal_updated.get(addr_id):
                            db_cursor.execute('select 1 from tx_output where address_id=?', (addr_id,))
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
            self._process_addresses_txs(addresses, cur_block_height)

    def fetch_addresses_txs(self, addr_info_list: List[Bip44AddressType], check_break_process_fun: Callable):
        tm_begin = time.time()
        self.validate_hd_tree()
        self.increase_ext_call_level()

        cur_block_height = self.get_block_height()

        if not self.purge_unconf_txs_called:
            try:
                db_cursor = self.db_intf.get_cursor()
                self._purge_unconfirmed_transactions(db_cursor)
                self.purge_unconf_txs_called = True
            finally:
                self.db_intf.release_cursor()
        try:
            self._process_addresses_txs(addr_info_list, cur_block_height)
            self._update_addr_balances(account=None, addr_ids=[a.id for a in addr_info_list])
        finally:
            self.decrease_ext_call_level()

        log.debug(f'fetch_addresses_txs exec time: {time.time() - tm_begin}s')

    def _process_addresses_txs(self, addr_info_list: List[Bip44AddressType], max_block_height: int):

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
            db_cursor.execute('select min(last_scan_block_height) from address where id in (select id from temp_ids)')
            row = db_cursor.fetchone()
            if row:
                last_block_height = row[0]

            if last_block_height < max_block_height:
                log.debug(f'getaddressdeltas for {addresses}, start: {last_block_height + 1}, end: {max_block_height}')
                txids = self.dashd_intf.getaddressdeltas({'addresses': addresses,
                                                         'start': last_block_height + 1,
                                                         'end': max_block_height})

                for tx_entry in txids:
                    self._process_tx(db_cursor, tx_entry.get('txid'))

                # update the last scan block height info for each of the addresses
                for addr_info in addr_info_list:
                    db_cursor.execute('update address set last_scan_block_height=? where id=?',
                                      (max_block_height, addr_info.id))

                for addr_info in addr_info_list:
                    if addr_info.address:
                        addr_info.last_scan_block_height = max_block_height
        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()

        log.debug('_process_addresses_txs exec time: %s', time.time() - tm_begin)

    def _process_tx(self, db_cursor, txhash: str, tx_json: Optional[Dict] = None):
        self._get_tx_db_id(db_cursor, txhash, tx_json)

    def _get_tx_db_id(self, db_cursor, txhash: str, tx_json: Dict = None, create=True) -> Tuple[int, Optional[Dict]]:
        """
        :param tx_entry:
        :param db_cursor:
        :return: Tuple[int <transaction db id>, Optional[Dict <transaction details json>]]
        """
        tx_hash = self._wrap_txid(txhash)

        db_cursor.execute('select id, block_height from tx where tx_hash=?', (tx_hash,))
        row = db_cursor.fetchone()
        if not row:
            if create:
                if not tx_json:
                    tx_json = self.dashd_intf.getrawtransaction(txhash, 1)

                block_height = tx_json.get('height', 0)
                if block_height:
                    block_hash = self.dashd_intf.getblockhash(block_height)
                    block_header = self.dashd_intf.getblockheader(block_hash)
                    block_timestamp = block_header.get('time')
                else:
                    # if block_height equals 0, it's non confirmed transaction and block_timestamp stores
                    # the time when tx has been added to the cache
                    block_timestamp = int(time.time())

                tx_vin = tx_json.get('vin', [])
                is_coinbase = 1 if (len(tx_vin) == 1 and tx_vin[0].get('coinbase')) else 0

                db_cursor.execute('insert into tx(tx_hash, block_height, block_timestamp, coinbase) values(?,?,?,?)',
                                  (tx_hash, block_height, block_timestamp, is_coinbase))
                tx_id = db_cursor.lastrowid
                self.txs_added[tx_id] = tx_id

                db_cursor.execute('update tx_input set src_tx_id=? where src_tx_id is null and src_tx_hash=?',
                                  (tx_id, txhash))
            else:
                tx_id = None
                tx_json = None
        else:
            tx_id = row[0]
            height = row[1]

            if not tx_json:
                tx_json = self.dashd_intf.getrawtransaction(txhash, 1)

            if not height:
                # it is unconfirmed transactions; check whether it has been confirmed since the last call

                block_height = tx_json.get('height', 0)
                if block_height:
                    block_hash = self.dashd_intf.getblockhash(block_height)
                    block_header = self.dashd_intf.getblockheader(block_hash)
                    block_timestamp = block_header.get('time')
                    db_cursor.execute('update tx set block_height=?, block_timestamp=? where id=?',
                                      (block_height, block_timestamp, tx_id))
                    self.db_intf.commit()

        if tx_json:
            for index, vout in enumerate(tx_json.get('vout', [])):
                self._process_tx_output_entry(db_cursor, tx_id, txhash, index, tx_json)

            for index, vin in enumerate(tx_json.get('vin', [])):
                self._process_tx_input_entry(db_cursor, tx_id, tx_hash, index, tx_json)

        return tx_id, tx_json

    def _process_tx_output_entry(self, db_cursor, tx_id: Optional[int], txhash: str, tx_index: int,
                                 tx_json: Optional[Dict]):

        if not tx_id:
            tx_id, tx_json_ = self._get_tx_db_id(db_cursor, txhash, tx_json)
            if not tx_json and tx_json_:
                tx_json = tx_json_

        if not tx_json:
            tx_json = self.dashd_intf.getrawtransaction(txhash, 1)

        vouts = tx_json.get('vout')
        if tx_index < len(vouts):
            vout = vouts[tx_index]

            spk = vout.get('scriptPubKey', {})
            if spk:
                address = ','.join(spk.get('addresses', []))
                if address:
                    # I assume that there will never be more than one address
                    addr_id = self.get_address_id(address, db_cursor)
                else:
                    addr_id = None

                db_cursor.execute('select id, address_id, spent_tx_id, spent_input_index '
                                  'from tx_output where tx_id=? and output_index=?', (tx_id, tx_index))
                row = db_cursor.fetchone()

                if not row:
                    satoshis = vout.get('valueSat')
                    scr_type = spk.get('type')

                    # check if this output has already been spent
                    db_cursor.execute('select tx_id, input_index from tx_input where src_tx_hash=? and '
                                      'src_tx_output_index=?', (txhash, tx_index))
                    row = db_cursor.fetchone()
                    if row:
                        spent_tx_id, spent_input_index = row
                    else:
                        spent_input_index = None
                        spent_tx_id = None

                    db_cursor.execute('insert into tx_output(address_id, address, tx_id, output_index, satoshis, '
                                      'spent_tx_id, spent_input_index, script_type) '
                                      'values(?,?,?,?,?,?,?,?)',
                                      (addr_id, address, tx_id, tx_index, satoshis, spent_tx_id, spent_input_index,
                                       scr_type))
                    utxo_id = db_cursor.lastrowid
                    self.utxos_added[utxo_id] = utxo_id
                    if addr_id:
                        self.addr_bal_updated[addr_id] = True
                else:
                    if addr_id != row[1]:
                        if addr_id:
                            self.addr_bal_updated[addr_id] = True
                        db_cursor.execute('update tx_output set address_id=? where id=?', (addr_id, row[0]))
            else:
                log.warning('No scriptPub in output, txhash: %s, index: %s', txhash, tx_index)

    def _process_tx_input_entry(self, db_cursor, tx_id: Optional[int], txhash: Optional[str], tx_index: int,
                                tx_json: Optional[Dict]):

        # for this outgoing tx entry find a related incoming one and mark it as spent
        if not tx_id:
            tx_id, tx_json_ = self._get_tx_db_id(db_cursor, txhash, tx_json)
            if not tx_json and tx_json_:
                tx_json = tx_json_

        if not tx_json:
            tx_json = self.dashd_intf.getrawtransaction(txhash, 1)

        vins = tx_json.get('vin')
        if tx_index < len(vins):
            vin = vins[tx_index]

            db_cursor.execute('select id, src_address_id from tx_input where tx_id=? and input_index=?',
                              (tx_id, tx_index))
            row = db_cursor.fetchone()
            addr = vin.get('address')
            if addr:
                addr_id = self.get_address_id(addr, db_cursor)
            else:
                addr_id = None
            coinbase = 1 if vin.get('coinbase') else 0

            if not row:
                satoshis = vin.get('valueSat')
                if satoshis:
                    satoshis = -satoshis
                related_txhash = vin.get('txid')
                related_tx_index = vin.get('vout')
                if related_txhash:
                    related_tx_id, _ = self._get_tx_db_id(db_cursor, related_txhash, create=False)
                else:
                    related_tx_id = None

                db_cursor.execute('insert into tx_input(tx_id, input_index, src_address, src_address_id, satoshis,'
                                  'src_tx_hash, src_tx_id, src_tx_output_index, coinbase) values(?,?,?,?,?,?,?,?,?)',
                                  (tx_id, tx_index, addr, addr_id, satoshis, related_txhash, related_tx_id,
                                   related_tx_index, coinbase))
                if addr_id:
                    self.addr_bal_updated[addr_id] = True

                # update spent fields of the related transaction
                if related_tx_id:
                    db_cursor.execute('select id, spent_tx_id, spent_input_index, address_id from tx_output '
                                      'where tx_id=? and output_index=?', (related_tx_id, related_tx_index))
                    row = db_cursor.fetchone()
                    if row:
                        utxo_id = row[0]
                        addr_id = row[3]
                        if row[1] != tx_id or row[2] != tx_index:
                            db_cursor.execute('update tx_output set spent_tx_id=?, spent_input_index=? where id=?',
                                              (tx_id, tx_index, utxo_id))

                            if utxo_id in self.utxos_added:
                                del self.utxos_added[utxo_id]  # the registered utxo has just been spent
                            else:
                                self.utxos_removed[utxo_id] = utxo_id
                            self.addr_bal_updated[addr_id] = True
            else:
                if row[1] != addr_id:
                    if addr_id:
                        self.addr_bal_updated[addr_id] = True
                    db_cursor.execute('update tx_input set src_address_id=? where id=?', (addr_id, row[0]))

    def _purge_unconfirmed_transactions(self, db_cursor):
        db_cursor2 = None
        try:
            limit_ts = int(time.time()) - UNCONFIRMED_TX_PURGE_SECONDS
            db_cursor.execute('select id from tx where block_height=0 and block_timestamp<?', (limit_ts,))
            for tx_row in db_cursor.fetchall():
                if not db_cursor2:
                    db_cursor2 = self.db_intf.get_cursor()
                self.purge_transaction(tx_row[0], db_cursor2)
        finally:
            if db_cursor2:
                self.db_intf.release_cursor()  # we are releasing cursor2
            self.db_intf.commit()

    def purge_transaction(self, tx_id: int, db_cursor=None):
        log.debug('Purging timed-out unconfirmed transaction (td_id: %s).', tx_id)
        if not db_cursor:
            db_cursor = self.db_intf.get_cursor()
            release_cursor = True
        else:
            release_cursor = False

        try:
            mod_addr_ids = []

            # following addressses will have balance changed after purging the transaction
            db_cursor.execute('select address_id from tx_output where address_id is not null and '
                              '(tx_id=? or spent_tx_id=?) union '
                              'select src_address_id from tx_input where address_id is not null and tx_id=?',
                              (tx_id, tx_id, tx_id))

            for row in db_cursor.fetchall():
                if not row[0] in mod_addr_ids:
                    mod_addr_ids.append(row[0])

            # list all transaction outputs that was prevoiusly spent - due to the transaction deletion
            # they are no longer spent, so we add them to the "new" utxos list
            db_cursor.execute('select id, address_id from tx_output where spent_tx_id=?', (tx_id,))
            for row in db_cursor.fetchall():
                self.utxos_added[row[0]] = row[1]
            db_cursor.execute('update tx_output set spent_tx_id=null, spent_input_index=null where spent_tx_id=?',
                              (tx_id,))

            db_cursor.execute('select id, address_id from tx_output where tx_id=?', (tx_id,))
            for row in db_cursor.fetchall():
                self.utxos_removed[row[0]] = row[0]

            db_cursor.execute('delete from tx_output where tx_id=?', (tx_id,))
            db_cursor.execute('delete from tx_input where tx_id=?', (tx_id,))
            db_cursor.execute('delete from tx where id=?', (tx_id,))
            self.txs_removed[tx_id] = tx_id

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
            account_ids: Dict[int, int] = {}  # account ids whose balances are modified

            if addr_ids:
                # update balances for specific addresses
                self._fill_temp_ids_table(addr_ids, db_cursor)

                db_cursor.execute(
                    "select id, account_id, real_received, "
                    "real_spent + real_received real_balance from (select a.id id, ca.id change_id, aa.id account_id, "
                    "a.received, (select ifnull(sum(satoshis), 0) from tx_output o where o.address_id = a.id) "
                    "real_received, a.balance, (select ifnull(sum(satoshis), 0) "
                    "from tx_input o where o.src_address_id = a.id) real_spent from address a "
                    "join address ca on ca.id = a.parent_id join address aa on aa.id = ca.parent_id "
                    "where a.id in (select id from temp_ids)) "
                    "where received <> real_received or balance <> real_received + real_spent")
            elif account:
                db_cursor.execute(
                   "select id, account_id, real_received, " 
                   "real_spent + real_received real_balance from (select a.id id, ca.id change_id, aa.id account_id, "
                   "a.received, (select ifnull(sum(satoshis), 0) from tx_output o where o.address_id = a.id) "
                   "real_received, a.balance, (select ifnull(sum(satoshis), 0) "
                   "from tx_input o where o.src_address_id = a.id) real_spent from address a "
                   "join address ca on ca.id = a.parent_id join address aa on aa.id = ca.parent_id where aa.id=?) "
                   "where received <> real_received or balance <> real_received + real_spent", (account.id,))
            else:
                raise Exception('Both arguments account_id and addr_ids are empty')

            for id, acc_id, real_received, real_balance in db_cursor.fetchall():
                if acc_id not in account_ids:
                    account_ids[acc_id] = acc_id

                db_cursor.execute('update address set balance=?, received=? where id=?',
                                  (real_balance, real_received, id))

                if self.on_address_data_changed_callback:
                    if account:
                        address = account.address_by_id(id)
                    else:
                        address, account = self._find_address_item_in_cache_by_id(id, db_cursor)
                    if address:
                        address.balance = real_balance
                        address.received = real_received
                        self.on_address_data_changed_callback(account, address)

            # update balance/received at the account level
            for addr_id in account_ids:
                db_cursor.execute(
                    "update address set balance=(select sum(a.balance) from address ca join address a "
                    "on a.parent_id=ca.id where ca.parent_id=address.id), received=(select sum(a.received) "
                    "from address ca join address a on a.parent_id=ca.id where ca.parent_id=address.id) where id=?",
                    (addr_id,))

                account = self._get_account_by_id(addr_id, db_cursor, force_reload=True)
                if self.on_account_data_changed_callback:
                    self.on_account_data_changed_callback(account)

            if account is not None and account.id not in account_ids:
                # update balance/received of the account if it was inconsistent with its the balance of its child
                # addresses when none of these address was modified during the current execution
                db_cursor.execute(
                    "select id, real_balance, real_received from (select id, balance, received, "
                    "(select ifnull(sum(a.balance),0) from address ca join address a on a.parent_id=ca.id "
                    "where ca.parent_id=address.id) real_balance, (select ifnull(sum(a.received),0) from address ca "
                    "join address a on a.parent_id=ca.id where ca.parent_id=address.id) real_received from address "
                    "where id=?) "
                    "where received <> real_received or balance <> real_balance", (account.id,))

                for id, real_balance, real_received in db_cursor.fetchall():
                    db_cursor.execute('update address set balance=?, received=? where id=?',
                                      (real_balance, real_received, id))

                    account = self._get_account_by_id(id, db_cursor, force_reload=True)
                    if self.on_account_data_changed_callback:
                        self.on_account_data_changed_callback(account)

        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            if release_cursor:
                self.db_intf.release_cursor()

    def _wrap_txid(self, txid: str):
        # base64 format takes less space in the db than hex string
        # return base64.b64encode(bytes.fromhex(txid))
        return txid # todo: store txid instead of tx hash to simplify testing

    def _unwrap_txid(self, txid_wrapped: str):
        # return base64.b64decode(txid_wrapped).hex()
        return txid_wrapped  # todo: for testling only

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

    def list_utxos_for_account(self, account_id: int, only_new = False) -> Generator[UtxoType, None, None]:
        """
        :param account_id: database id of the account's record
        """
        tm_begin = time.time()
        self.validate_hd_tree()
        db_cursor = self.db_intf.get_cursor()
        try:
            sql_text = "select o.id, tx.block_height, tx.coinbase, tx.block_timestamp," \
                       "tx.tx_hash, o.output_index, o.satoshis, o.address_id from tx_output o " \
                       "join address a on a.id=o.address_id join address cha on cha.id=a.parent_id join address aca " \
                       "on aca.id=cha.parent_id join tx on tx.id=o.tx_id where (spent_tx_id is null " \
                       "or spent_input_index is null) and aca.id=?"

            if only_new:
                # limit returned utxos only to those existing in the self.utxos_added list
                self._fill_temp_ids_table([id for id in self.utxos_added], db_cursor)
                sql_text += ' and o.id in (select id from temp_ids)'
            sql_text += " order by tx.block_height desc"

            t = time.time()
            db_cursor.execute(sql_text, (account_id,))
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

            for id in self.utxos_removed:
                if id in self.utxos_by_id:
                    del self.utxos_by_id[id]

        diff = time.time() - tm_begin
        log.debug('list_utxos_for_account exec time: %ss', diff)

    def list_utxos_for_addresses(self, address_ids: List[int], only_new = False) -> Generator[UtxoType, None, None]:
        self.validate_hd_tree()
        db_cursor = self.db_intf.get_cursor()
        try:
            in_part = ','.join(['?'] * len(address_ids))
            sql_text = "select o.id, tx.block_height, tx.coinbase,tx.block_timestamp, tx.tx_hash, o.output_index, " \
                       "o.satoshis, o.address_id from tx_output o join address a" \
                       " on a.id=o.address_id join address cha on cha.id=a.parent_id join address aca" \
                       " on aca.id=cha.parent_id join tx on tx.id=o.tx_id where (spent_tx_id is null" \
                       " or spent_input_index is null) and a.id in (" + in_part + ')'

            if only_new:
                # limit returned utxos only to those existing in the self.utxos_added list
                self._fill_temp_ids_table([id for id in self.utxos_added], db_cursor)
                sql_text += ' and o.id in (select id from temp_ids)'
            sql_text += " order by tx.block_height desc"

            db_cursor.execute(sql_text, address_ids)

            for id, block_height, coinbase, block_timestamp, tx_hash, \
                output_index, satoshis, address_id in db_cursor.fetchall():

                utxo = self._get_utxo(id, tx_hash, address_id, output_index, satoshis, block_height,
                                      block_timestamp, coinbase)

                yield utxo

        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()

            for id in self.utxos_removed:
                if id in self.utxos_by_id:
                    del self.utxos_by_id[id]

    def list_accounts(self) -> Generator[Bip44AccountType, None, None]:
        tm_begin = time.time()
        self.validate_hd_tree()
        self.addr_ids_created.clear()
        db_cursor = self.db_intf.get_cursor()
        try:
            tree_id = self.get_tree_id()

            db_cursor.execute("select id from address where parent_id is null and xpub_hash is not null and tree_id=? "
                              "order by address_index",
                              (tree_id,))

            for id, in db_cursor.fetchall():
                acc = self._get_account_by_id(id, db_cursor)
                yield acc
        finally:
            self._process_addresses_created(db_cursor)

            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()
        diff = time.time() - tm_begin
        log.debug(f'Accounts read time: {diff}s')

    def register_spending_transaction(self, inputs: List[UtxoType], outputs: List[TxOutputType], tx_json: Dict):
        """
        Register outgoing transaction in the database cache. It will be used util it appears on the blockchain.
        :param inputs:
        :param outputs:
        """
        db_cursor = self.db_intf.get_cursor()
        try:
            txhash = tx_json.get('txid')
            self._process_tx(db_cursor, txhash, tx_json)
            self._update_addr_balances(account=None, addr_ids=list(self.addr_bal_updated.keys()), db_cursor=db_cursor)
        finally:
            self.db_intf.commit()
            self.db_intf.release_cursor()

    def remove_account(self, id: int):
        log.debug(f'Deleting account from db. Account address db id: {id}')
        db_cursor = self.db_intf.get_cursor()
        try:
            db_cursor.execute("update tx_output set address_id=null where address_id in ("
                              "select a.id from address a join address a1 on a1.id=a.parent_id "
                              "join address a2 on a2.id=a1.parent_id where a2.id=?)",
                              (id,))

            db_cursor.execute("update tx_input set src_address_id=null where src_address_id in ("
                              "select a.id from address a join address a1 on a1.id=a.parent_id "
                              "join address a2 on a2.id=a1.parent_id where a2.id=?)",
                              (id,))

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
            db_cursor.execute("delete from tx_output where address_id=?", (id,))

            db_cursor.execute("delete from tx_input where src_address_id=?", (id,))

            db_cursor.execute("update address set last_scan_block_height=0 where id=?", (id,))

            addr, _ = self._find_address_item_in_cache_by_id(id, db_cursor)
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
            if self.on_account_address_added_callback:
                self.on_account_address_added_callback(entry.bip44_account, entry)
        elif isinstance(entry, Bip44AccountType):
            acc_loc = self.account_by_id.get(entry.id)
            if acc_loc:
                acc_loc.label = label
            if self.on_account_data_changed_callback:
                self.on_account_data_changed_callback(entry)

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
            db_cursor.execute("update tx_input set src_address_id=null where src_address_id in (select id from "
                              "address where tree_id=?)", (id,))
            db_cursor.execute("update tx_output set address_id=null where address_id in (select id from address "
                              "where tree_id=?)", (id,))
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

