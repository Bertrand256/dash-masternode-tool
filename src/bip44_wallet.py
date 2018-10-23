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
from typing import List, Dict, Tuple, Optional, Any, Generator, NamedTuple, Callable, ByteString
import app_utils
import hw_intf
from common import AttrsProtected
from dash_utils import bip32_path_string_to_n, pubkey_to_address, bip32_path_n_to_string
from dashd_intf import DashdInterface
from hw_common import HwSessionInfo
from db_intf import DBCache
from wallet_common import Bip44AccountType, Bip44AddressType, UtxoType, TxOutputType, xpub_to_hash, Bip44Entry

TX_QUERY_ADDR_CHUNK_SIZE = 10
ADDRESS_SCAN_GAP_LIMIT = 20
MAX_ADDRESSES_TO_SCAN = 1000
MAX_BIP44_ACCOUNTS = 200
GET_BLOCKHEIGHT_MIN_SECONDS = 30
UNCONFIRMED_TX_PURGE_SECONDS = 60


log = logging.getLogger('dmt.bip44_wallet')


class Bip44Wallet(object):
    def __init__(self, hw_session: HwSessionInfo, db_intf: DBCache, dashd_intf: DashdInterface, dash_network: str):
        self.db = None
        self.hw_session = hw_session
        self.dash_network = dash_network
        self.db_intf = db_intf
        self.dashd_intf = dashd_intf
        self.cur_block_height = None
        self.last_get_block_height_ts = 0
        self.__tree_id = None

        # list of accounts retrieved while calling self.list_accounts
        self.account_by_id: Dict[int, Bip44AccountType] = {}
        self.account_by_bip32_path: Dict[str, Bip44AccountType] = {}  # todo: clear when switching

        # list of addresses used by the app by not belonging to an account
        self.addresses_by_id: Dict[int, Bip44AddressType] = {}

        # transactions added/modified since the last reset_tx_diffs call
        self.txs_added: Dict[int, int] = {}  # {'tx_id': 'address_id'}
        self.txs_modified: Dict[int, int] = {}  # {'tx_id': 'address_id'}
        self.txs_removed: Dict[int, int] = {}  # {'tx_id': 'tx_id'}

        # utxos added/removed since the last reset_tx_diffs call
        self.utxos_added: Dict[int, int] = {}  # {'tx_output.id': 'address_id'}
        self.utxos_removed: Dict[int, int] = {}  # {'tx_output.id': 'address_id'}

        # addresses whose balance has been modified since the last call of reset_tx_diffs
        self.addr_bal_updated: Dict[int, int] = {}  # {'address_id': 'address_id' }

        self.purge_unconf_txs_called = False
        self.external_call_level = 0

        self.on_account_added_callback: Callable[[Bip44AccountType], None] = None
        self.on_account_data_changed_callback: Callable[[Bip44AccountType], None] = None
        self.on_account_address_added_callback: Callable[[Bip44AccountType, Bip44AddressType], None] = None
        self.on_address_data_changed_callback: Callable[[Bip44AccountType, Bip44AddressType], None] = None

    def reset_tx_diffs(self):
        self.txs_added.clear()
        self.txs_modified.clear()
        self.txs_removed.clear()
        self.utxos_added.clear()
        self.utxos_removed.clear()
        self.addr_bal_updated.clear()

    def clear(self):
        self.__tree_id = None
        self.account_by_id.clear()
        self.addresses_by_id.clear()

    def get_tree_id(self):
        if not self.__tree_id:
            db_cursor = self.db_intf.get_cursor()
            try:
                db_cursor.execute('select id from hd_tree where ident=?', (self.hw_session.hd_tree_ident,))
                row = db_cursor.fetchone()
                if not row:
                    db_cursor.execute('insert into hd_tree(ident) values(?)', (self.hw_session.hd_tree_ident,))
                    self.__tree_id = db_cursor.lastrowid
                    self.db_intf.commit()
                else:
                    self.__tree_id = row[0]
            finally:
                self.db_intf.release_cursor()
        return self.__tree_id

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
                addr = self._get_address_from_dict(addr_info)
            elif create:
                db_cursor.execute('insert into address(address) values(?)', (address,))
                addr = Bip44AddressType(tree_id=None)
                addr.id = db_cursor.lastrowid
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
        #todo: verify if needed: address.parent_id = address_dict.get('parent_id')
        if addr.address_index is None:
            addr.address_index = address_dict.get('address_index')
        if addr.address is None:
            addr.address = address_dict.get('address')
        if not addr.bip32_path:
            addr.bip32_path = address_dict.get('path')
        if not addr.tree_id:
            addr.tree_id = address_dict.get('tree_id')
        addr.balance = address_dict.get('balance', 0)
        addr.received = address_dict.get('received', 0)
        addr.last_scan_block_height = address_dict.get('last_scan_block_height', 0)
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
                              'a.received, a.last_scan_block_height, ac.is_change from address a '
                              'join address ac on ac.id=a.parent_id '
                              'where a.parent_id=? and a.address_index=?',
                              (parent_key_entry.id, child_addr_index))
            row = db_cursor.fetchone()
            if not row:
                parent_key = parent_key_entry.get_bip32key()
                key = parent_key.ChildKey(child_addr_index)
                address = pubkey_to_address(key.PublicKey().hex(), self.dash_network)

                db_cursor.execute('select * from address where address=?',
                                  (address,))
                row = db_cursor.fetchone()
                if row:
                    addr_info = dict([(col[0], row[idx]) for idx, col in enumerate(db_cursor.description)])
                    if addr_info.get('parent_id') != parent_key_entry.id or addr_info.get('address_index') != child_addr_index:
                        # address wasn't initially opened as a part of xpub account scan, so update its attrs
                        db_cursor.execute('update address set parent_id=?, address_index=? where id=?',
                                          (parent_key_entry.id, child_addr_index, row[0]))

                        addr_info['parent_id'] = parent_key_entry.id
                        addr_info['address_index'] = child_addr_index

                    return self._get_address_from_dict(addr_info)
                else:
                    db_cursor.execute('insert into address(parent_id, address_index, address) values(?,?,?)',
                                      (parent_key_entry.id, child_addr_index, address))

                    addr_info = {
                        'id': db_cursor.lastrowid,
                        'parent_id': parent_key_entry.id,
                        'address_index': child_addr_index,
                        'address': address,
                        'last_scan_block_height': 0
                    }

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
            else:
                account = Bip44AccountType(self.get_tree_id(), id=None, xpub=xpub, address_index=account_index,
                                           bip32_path=account_bip32_path)
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

            self._read_account_addresses(account, db_cursor)
            if self.on_account_added_callback:
                self.on_account_added_callback(account)
        else:
            if force_reload:
                account.read_from_db(db_cursor)

            if not account.xpub and account.bip32_path:
                account.xpub = hw_intf.get_xpub(self.hw_session, account.bip32_path)
        return account

    def _read_account_addresses(self, account: Bip44AccountType, db_cursor):
        db_cursor.execute('select a.id, a.address_index, a.address, ac.path parent_path, a.balance, '
                          'a.received, ac.is_change from address a join address ac on a.parent_id=ac.id '
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

    def fetch_all_accounts_txs(self, check_break_process_fun: Callable):
        log.debug('Starting fetching transactions for all accounts.')

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
                        self._fetch_child_addrs_txs(change_level_node, account, check_break_process_fun)
                    self._update_addr_balances(account)
                    account.read_from_db(db_cursor)
                    if not account.received:
                        break
                finally:
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
        self.increase_ext_call_level()
        db_cursor = self.db_intf.get_cursor()
        try:
            account_entry = self._get_key_entry_by_xpub(account_xpub)
            account = self.account_by_id.get(account_entry.id)
            change_level_entry = account_entry.get_child_entry(change)
            change_level_entry.read_from_db(db_cursor, create=True)
            self._fetch_child_addrs_txs(change_level_entry, account, check_break_process_fun)
            self._update_addr_balances(account)
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
                    address = tx_entry.get('address')
                    addr_db_id = addrinfo_by_address[address].id
                    self._process_tx_entry(tx_entry, addr_db_id, address, db_cursor)

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

    def _process_tx_entry(self, tx_entry: Dict, addr_db_id: int, address: str, db_cursor):

        txid = tx_entry.get('txid')
        tx_index = tx_entry.get('index')
        satoshis = tx_entry.get('satoshis')

        if satoshis > 0:
            # incoming transaction entry
            self._process_tx_output_entry(db_cursor, txid, tx_index, None, addr_db_id, address, satoshis)
        else:
            # outgoing transaction entry
            self._process_tx_input_entry(db_cursor, txid, tx_index, None, addr_db_id, satoshis)

    def _process_tx_output_entry(self, db_cursor, txid: str, tx_index: int, tx_json: Optional[Dict], addr_db_id: int,
                                address: str, satoshis: int):

        tx_db_id, tx_json, tx_is_new = self._get_tx_db_id(txid, db_cursor, tx_json)
        if tx_is_new:
            self.txs_added[tx_db_id] = addr_db_id

        db_cursor.execute('select id, address_id, spent_tx_id, spent_input_index '
                          'from tx_output where tx_id=? and output_index=?', (tx_db_id, tx_index))
        row = db_cursor.fetchone()
        changed = False
        if not row:
            db_cursor.execute('insert into tx_output(address_id, address, tx_id, output_index, satoshis) '
                              'values(?,?,?,?,?)', (addr_db_id, address, tx_db_id, tx_index, satoshis))

            changed = True
            utxo_id = db_cursor.lastrowid
            log.debug('Adding a new tx_output entry (address: %s, address id: %s, tx_id: %s)',
                      address, addr_db_id, tx_db_id)
        else:
            utxo_id = row[0]
            if addr_db_id != row[1]:
                t = time.time()
                db_cursor.execute('update tx_output set address_id=?, address=? where id=?', (addr_db_id, address,
                                                                                              utxo_id))

                changed = True
                log.debug('Updating address_id of a tx_output entry (address_id: %s, tx_id: %s, exec time: %s)',
                          addr_db_id, tx_db_id, time.time() - t)
        if changed:
            if not tx_db_id in self.txs_added:
                self.txs_modified[tx_db_id] = addr_db_id
            if not row or not row[2]:
                self.utxos_added[utxo_id] = addr_db_id
            self.addr_bal_updated[addr_db_id] = True

    def _process_tx_input_entry(self, db_cursor, txid: str, tx_index: int, tx_json: Optional[Dict], addr_db_id: int,
                                satoshis: int):

        tx_db_id, tx_json, tx_is_new = self._get_tx_db_id(txid, db_cursor, tx_json)
        if tx_is_new:
            self.txs_added[tx_db_id] = addr_db_id

        db_cursor.execute('select id from tx_input where tx_id=? and input_index=?', (tx_db_id, tx_index))
        row = db_cursor.fetchone()

        # for this outgoing tx entry find a related incoming one and mark it as spent
        if not tx_json:
            tx_json = self.dashd_intf.getrawtransaction(txid, 1)

        if not row:
            db_cursor.execute('insert into tx_input(tx_id, input_index, address_id, satoshis) values(?,?,?,?)',
                              (tx_db_id, tx_index, addr_db_id, satoshis))

            if not tx_db_id in self.txs_added:
                self.txs_modified[tx_db_id] = addr_db_id

            self.addr_bal_updated[addr_db_id] = True
            log.debug('Adding a new tx_input entry (tx_id: %s, input_index: %s, address_id: %s)',
                      tx_db_id, tx_index, addr_db_id)

        tx_vin = tx_json.get('vin')
        if tx_index < len(tx_vin):
            related_tx_vin = tx_vin[tx_index]
            related_txid = related_tx_vin.get('txid')
            related_tx_index = related_tx_vin.get('vout')
            related_tx_db_id, _, tx_is_new = self._get_tx_db_id(related_txid, db_cursor)

            # the related transaction should already be in the database cache
            db_cursor.execute('select id, spent_tx_id, spent_input_index, address_id from tx_output where tx_id=? '
                              'and output_index=?', (related_tx_db_id, related_tx_index))
            row = db_cursor.fetchone()
            if row:
                utxo_id = row[0]
                addr_db_id = row[3]
                if row[1] != tx_db_id or row[2] != tx_index:
                    db_cursor.execute('update tx_output set spent_tx_id=?, spent_input_index=? where id=?',
                                      (tx_db_id, tx_index, utxo_id))

                    if tx_is_new:
                        self.txs_added[related_tx_db_id] = addr_db_id

                    if utxo_id in self.utxos_added:
                        del self.utxos_added[utxo_id]  # the registered utxo has just been spent
                    else:
                        self.utxos_removed[utxo_id] = addr_db_id
                    self.addr_bal_updated[addr_db_id] = True

                    log.debug('Updating spent-related fields of an tx_output entry (tx_id: %s, spent_tx_id: %s, '
                              'spent_input_index: %s)', utxo_id, tx_db_id, tx_index)
            else:
                log.warning(f'Could not find the related transaction for this tx entry. Txid: {related_txid}, '
                            f'index: {tx_index}')
        else:
            log.warning('Could not find vin of the related transaction for this transaction entry. '
                        f'Txid: {tx_db_id}, index: {tx_index}.')

    def _get_tx_db_id(self, txid: str, db_cursor, tx_json: Dict = None) -> Tuple[int, Optional[Dict], bool]:
        """
        :param tx_entry:
        :param db_cursor:
        :return: Tuple[int <transaction db id>, Optional[Dict <transaction details json>], bool <True if
                 it's a new transaction>]
        """
        tx_hash = self._wrap_txid(txid)
        new = False

        db_cursor.execute('select id, block_height from tx where tx_hash=?', (tx_hash,))
        row = db_cursor.fetchone()
        if not row:
            new = True
            if not tx_json:
                tx_json = self.dashd_intf.getrawtransaction(txid, 1)

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

            for index, vout in enumerate(tx_json.get('vout', [])):
                spk = vout.get('scriptPubKey', {})
                if spk:
                    addrs = ','.join(spk.get('addresses',[]))
                    value = vout.get('valueSat')
                    if addrs and value:
                        db_cursor.execute('insert into tx_output(address,tx_id,output_index,satoshis) values(?,?,?,?)',
                                          (addrs, tx_id, index, value))
        else:
            tx_id = row[0]
            height = row[1]

            if not height:
                # it is unconfirmed transactions; check whether it has been confirmed since the last call
                if not tx_json:
                    tx_json = self.dashd_intf.getrawtransaction(txid, 1)

                block_height = tx_json.get('height', 0)
                if block_height:
                    block_hash = self.dashd_intf.getblockhash(block_height)
                    block_header = self.dashd_intf.getblockheader(block_hash)
                    block_timestamp = block_header.get('time')
                    db_cursor.execute('update tx set block_height=?, block_timestamp=? where id=?',
                                      (block_height, block_timestamp, tx_id))
                    self.db_intf.commit()
        return tx_id, tx_json, new

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
                              'select address_id from tx_input where address_id is not null and tx_id=?',
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
                self.utxos_removed[row[0]] = row[1]

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
                    "from tx_input o where o.address_id = a.id) real_spent from address a "
                    "join address ca on ca.id = a.parent_id join address aa on aa.id = ca.parent_id "
                    "where a.id in (select id from temp_ids)) "
                    "where received <> real_received or balance <> real_received + real_spent")
            elif account:
                db_cursor.execute(
                   "select id, account_id, real_received, " 
                   "real_spent + real_received real_balance from (select a.id id, ca.id change_id, aa.id account_id, "
                   "a.received, (select ifnull(sum(satoshis), 0) from tx_output o where o.address_id = a.id) "
                   "real_received, a.balance, (select ifnull(sum(satoshis), 0) "
                   "from tx_input o where o.address_id = a.id) real_spent from address a "
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

    def list_utxos_for_account(self, account_id: int, only_new = False) -> Generator[UtxoType, None, None]:
        """
        :param account_id: database id of the account's record
        """
        tm_begin = time.time()
        db_cursor = self.db_intf.get_cursor()
        try:
            sql_text = "select o.id, cha.path, a.address_index, tx.block_height, tx.coinbase, " \
                       "tx.block_timestamp," \
                       "tx.tx_hash, o.address, o.output_index, o.satoshis, o.address_id from tx_output o " \
                       "join address a " \
                       "on a.id=o.address_id join address cha on cha.id=a.parent_id join address aca " \
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

            for id, path, addr_index, block_height, coinbase, block_timestamp, tx_hash, address, output_index,\
                satoshis, address_id in db_cursor.fetchall():

                utxo = UtxoType()
                utxo.id = id
                utxo.txid = self._unwrap_txid(tx_hash)
                utxo.address = address
                utxo.address_id = address_id
                utxo.output_index = output_index
                utxo.satoshis = satoshis
                utxo.block_height = block_height
                utxo.bip32_path = path + '/' + str(addr_index) if path else ''
                utxo.time_stamp = block_timestamp
                utxo.time_str = app_utils.to_string(datetime.datetime.fromtimestamp(block_timestamp))
                utxo.coinbase = coinbase
                utxo.get_cur_block_height_fun = self.get_block_height_nofetch
                yield utxo
        finally:
            self.db_intf.release_cursor()
        diff = time.time() - tm_begin
        log.debug('list_utxos_for_account exec time: %ss', diff)

    def list_utxos_for_addresses(self, address_ids: List[int], only_new = False) -> Generator[UtxoType, None, None]:
        db_cursor = self.db_intf.get_cursor()
        try:
            in_part = ','.join(['?'] * len(address_ids))
            sql_text = "select o.id, cha.path, a.address_index, tx.block_height, tx.coinbase," \
                       "tx.block_timestamp, tx.tx_hash, o.address, o.output_index, o.satoshis," \
                       "o.address_id from tx_output o join address a" \
                       " on a.id=o.address_id join address cha on cha.id=a.parent_id join address aca" \
                       " on aca.id=cha.parent_id join tx on tx.id=o.tx_id where (spent_tx_id is null" \
                       " or spent_input_index is null) and a.id in (" + in_part + ')'

            if only_new:
                # limit returned utxos only to those existing in the self.utxos_added list
                self._fill_temp_ids_table([id for id in self.utxos_added], db_cursor)
                sql_text += ' and o.id in (select id from temp_ids)'
            sql_text += " order by tx.block_height desc"

            db_cursor.execute(sql_text, address_ids)

            for id, path, addr_index, block_height, coinbase, block_timestamp, tx_hash, address, output_index,\
                satoshis, address_id in db_cursor.fetchall():

                utxo = UtxoType()
                utxo.id = id
                utxo.txid = self._unwrap_txid(tx_hash)
                utxo.address = address
                utxo.address_id = address_id
                utxo.output_index = output_index
                utxo.satoshis = satoshis
                utxo.block_height = block_height
                utxo.bip32_path = path + '/' + str(addr_index) if path else ''
                utxo.time_stamp = block_timestamp
                utxo.time_str = app_utils.to_string(datetime.datetime.fromtimestamp(block_timestamp))
                utxo.coinbase = coinbase
                utxo.get_cur_block_height_fun = self.get_block_height_nofetch
                yield utxo

        finally:
            self.db_intf.release_cursor()

    def list_accounts(self) -> Generator[Bip44AccountType, None, None]:
        tm_begin = time.time()
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
            self.db_intf.release_cursor()
        diff = time.time() - tm_begin
        log.debug(f'Accounts read time: {diff}s')

    def list_bip32_address_utxos(self):
        pass

    def list_bip32_account_txs(self):
        pass

    def register_spending_transaction(self, inputs: List[UtxoType], outputs: List[TxOutputType], tx_json: Dict):
        """
        Register outgoing transaction in the database cache. It will be used util it appears on the blockchain.
        :param inputs:
        :param outputs:
        """
        db_cursor = self.db_intf.get_cursor()
        try:
            txid = tx_json.get('txid')

            for idx, txi in enumerate(inputs):
                self._process_tx_input_entry(db_cursor, txid, idx, tx_json, txi.address_id, txi.satoshis)

            for idx, txo in enumerate(outputs):
                address_id = self.get_address_id(txo.address, db_cursor)
                if address_id:
                    # we aren't interested in caching tx outputs which aren't directed to our wallet's addresses
                    self._process_tx_output_entry(db_cursor, txid, idx, tx_json, address_id, txo.address, txo.satoshis)

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

            db_cursor.execute("delete from tx_input where address_id in ("
                              "select a.id from address a join address a1 on a1.id=a.parent_id "
                              "join address a2 on a2.id=a1.parent_id where a2.id=?)",
                              (id,))

            db_cursor.execute("delete from address where parent_id in ("
                              "select a1.id from address a1 where a1.parent_id=?)", (id,))

            db_cursor.execute("delete from address where parent_id=?", (id,))

            db_cursor.execute("delete from address where id=?", (id,))
            acc = self.account_by_id.get(id)
            if acc:
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

            db_cursor.execute("delete from tx_input where address_id=?", (id,))

            db_cursor.execute("update address set last_scan_block_height=0 where id=?", (id,))

            addr, _ = self._find_address_item_in_cache_by_id(id, db_cursor)
            if addr:
                addr.last_scan_block_height = 0

            self._update_addr_balances(None, [id], db_cursor)

        finally:
            self.db_intf.commit()
            self.db_intf.release_cursor()
