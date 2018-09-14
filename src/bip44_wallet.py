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
from typing import List, Dict, Tuple, Optional, Any, Generator, NamedTuple, Callable
import app_utils
import hw_intf
from common import AttrsProtected
from dash_utils import bip32_path_string_to_n, pubkey_to_address, bip32_path_n_to_string
from dashd_intf import DashdInterface
from hw_common import HwSessionInfo
from db_intf import DBCache
from wallet_common import Bip44AccountType, AddressType, UtxoType, TxOutputType


TX_QUERY_ADDR_CHUNK_SIZE = 10
ADDRESS_SCAN_GAP_LIMIT = 20
MAX_ADDRESSES_TO_SCAN = 1000
MAX_BIP44_ACCOUNTS = 200
GET_BLOCKHEIGHT_MIN_SECONDS = 30
UNCONFIRMED_TX_PURGE_SECONDS = 60


log = logging.getLogger('dmt.bip44_wallet')


class Bip44KeysEntry(object):
    def __init__(self, tree_id, db_intf: DBCache):
        self.__db_intf: DBCache = db_intf
        self.__tree_id = tree_id
        self.xpub: str = None
        self.bip32_path = None
        self.is_change = False
        self.__bip32_key: BIP32Key = None
        self.__id = None
        self.childs: Dict[int, 'Bip44KeysEntry'] = {}  # key: child bip32/44 index
        self.parent: 'Bip44KeysEntry' = None

    def get_bip32key(self) -> BIP32Key:
        if not self.__bip32_key:
            if not self.xpub:
                raise Exception('XPUB not set')
            self.__bip32_key = BIP32Key.fromExtendedKey(self.xpub)
        return self.__bip32_key

    def set_bip32key(self, key: BIP32Key):
        self.__bip32_key = key

    def get_child(self, index) -> 'Bip44KeysEntry':
        child = self.childs.get(index)
        if not child:
            key = self.get_bip32key()
            child_key = key.ChildKey(index)
            child_xpub = child_key.ExtendedKey(False, True)
            child = Bip44KeysEntry(self.__tree_id, self.__db_intf)
            child.set_bip32key(child_key)
            child.xpub = child_xpub
            child.parent = self
            child.is_change = (index == 1)
            if self.bip32_path:
                path_n = bip32_path_string_to_n(self.bip32_path)
                path_n.append(index)
                path = bip32_path_n_to_string(path_n)
                child.bip32_path = path
            self.childs[index] = child
        return child

    def get_child_by_xpub(self, xpub: str):
        for index in self.childs:
            child = self.childs[index]
            if child.xpub == xpub:
                return child
        return None

    @property
    def id(self):
        if not self.__id:
            self.__id = self._get_xpub_db_addr()
        return self.__id

    def _get_xpub_db_addr(self) -> int:
        """
        :param xpub: Externded public key
        :param bip32_path: BIP32 address of the XPUB key (if XPUB is related to the local wallet's account)
        :return:
        """
        log.debug('Getting db id for path: %s', self.bip32_path)
        xpub_raw = Base58.check_decode(self.xpub)
        if xpub_raw[0:4] in (b'\x02\xfe\x52\xcc', b'\x04\x88\xb2\x1e'):  # remove xpub prefix
            xpub_raw = xpub_raw[4:]
        xpub_hash = bitcoin.bin_sha256(xpub_raw)
        xpub_hash = base64.b64encode(xpub_hash)
        address_index = None

        db_cursor = self.__db_intf.get_cursor()
        try:
            if self.bip32_path:
                # xpub controlled by the local hardware wallet
                bip32path_n = bip32_path_string_to_n(self.bip32_path)
                address_index = bip32path_n[-1]
            if self.parent:
                parent_id = self.parent.id
            else:
                parent_id = None

            db_cursor.execute('select id, tree_id, path, is_change, parent_id, address_index from address where '
                              'xpub_hash=?', (xpub_hash,))
            row = db_cursor.fetchone()
            if not row:
                db_cursor.execute('insert into address(xpub_hash, tree_id, path, is_change, parent_id, address_index) '
                                  'values(?,?,?,?,?,?)',
                                  (xpub_hash, self.__tree_id, self.bip32_path, 1 if self.is_change else 0, parent_id,
                                   address_index))
                db_id = db_cursor.lastrowid
                self.__db_intf.commit()
            else:
                if (self.__tree_id != row[1] and self.__tree_id is not None) or \
                   (self.bip32_path != row[2] and not not self.bip32_path) or self.is_change != row[3] or \
                   parent_id != row[4] or (address_index != row[5] and address_index is not None):
                    db_cursor.execute('update address set tree_id=?, path=?, is_change=?, parent_id=?, address_index=? '
                                      'where id=?',
                                      (self.__tree_id, self.bip32_path, 1 if self.is_change else 0, parent_id,
                                       address_index, row[0]))
                    self.__db_intf.commit()
                else:
                    if not self.bip32_path:
                        self.bip32_path = row[2]
                db_id = row[0]
            return db_id
        finally:
            self.__db_intf.release_cursor()


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
        self.accounts_by_id: Dict[int, Bip44AccountType] = {}

        # accounts added/modified after the last call of reset_accounts_diffs and
        # also accounts, whose addresses was modified/added:
        self.accounts_modified:List[Bip44AccountType] = []

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

        # todo: clear after hw tree_id change
        self.account_keys_by_path: Dict[str, Bip44KeysEntry] = {}
        self.account_keys_by_xpub: Dict[str, Bip44KeysEntry] = {}

    def reset_tx_diffs(self):
        self.txs_added.clear()
        self.txs_modified.clear()
        self.txs_removed.clear()
        self.utxos_added.clear()
        self.utxos_removed.clear()
        self.addr_bal_updated.clear()

    def reset_accounts_diffs(self):
        self.accounts_modified.clear()

    def get_tree_id(self):
        if not self.__tree_id:
            db_cursor = self.db_intf.get_cursor()
            try:
                db_cursor.execute('select id from ADDRESS_HD_TREE where ident=?', (self.hw_session.hd_tree_ident,))
                row = db_cursor.fetchone()
                if not row:
                    db_cursor.execute('insert into ADDRESS_HD_TREE(ident) values(?)', (self.hw_session.hd_tree_ident,))
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

    def get_address_item(self, address: str, create: bool) -> Optional[AddressType]:
        db_cursor = self.db_intf.get_cursor()
        try:
            db_cursor.execute('select * from address where address=?', (address,))
            row = db_cursor.fetchone()
            if row:
                addr_info = dict([(col[0], row[idx]) for idx, col in enumerate(db_cursor.description)])
                return self._get_address_from_dict(addr_info)
            elif create:
                db_cursor.execute('insert into address(address) values(?)', (address,))
                a = AddressType()
                a.id = db_cursor.lastrowid
                return a
            else:
                return None
        finally:
            self.db_intf.release_cursor()

    def _get_bip44_entry_by_xpub(self, xpub) -> Bip44KeysEntry:
        for x in self.account_keys_by_xpub:
            e = self.account_keys_by_xpub[x]
            if x == xpub:
                return e
            return e.get_child_by_xpub(xpub)

    def _get_address_from_dict(self, address_dict):
        addr = AddressType()
        addr.id = address_dict.get('id')
        addr.xpub_hash = address_dict.get('xpub_hash')
        addr.parent_id = address_dict.get('parent_id')
        addr.address_index = address_dict.get('address_index')
        addr.address = address_dict.get('address')
        addr.path = address_dict.get('path')
        addr.tree_id = address_dict.get('tree_id')
        addr.balance = address_dict.get('balance')
        addr.received = address_dict.get('received')
        addr.is_change = address_dict.get('is_change')
        addr.last_scan_block_height = address_dict.get('last_scan_block_height')
        return addr

    def _get_child_address(self, parent_key_entry: Bip44KeysEntry, child_addr_index: int) -> AddressType:
        """
        :return: Tuple[int <id db>, str <address>, int <balance in duffs>]
        """
        db_cursor = self.db_intf.get_cursor()
        try:
            db_cursor.execute('select * from address where parent_id=? and address_index=?',
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

    def _get_key_entry_by_xpub(self, xpub: str) -> Bip44KeysEntry:
        key_entry = self._get_bip44_entry_by_xpub(xpub)
        if not key_entry:
            key_entry = Bip44KeysEntry(self.get_tree_id(), self.db_intf)
            key_entry.xpub = xpub
            self.account_keys_by_xpub[xpub] = key_entry
        return key_entry

    def _get_key_entry_by_account_index(self, account_index: int) -> Bip44KeysEntry:
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

        key_entry = self.account_keys_by_path.get(account_bip32_path)
        if not key_entry:
            xpub = hw_intf.get_xpub(self.hw_session, account_bip32_path)
            key_entry = self._get_key_entry_by_xpub(xpub)
            key_entry.bip32_path = account_bip32_path
            self.account_keys_by_path[account_bip32_path] = key_entry
            log.debug('get_account_base_address_by_index exec time: %s', time.time() - tm_begin)
        else:
            log.debug('get_account_base_address_by_index (used cache) exec time: %s', time.time() - tm_begin)

        return key_entry

    def _list_xpub_addresses(self, key_entry: Bip44KeysEntry, addr_start_index: int, addr_count: int) -> \
            Generator[AddressType, None, None]:

        tm_begin = time.time()
        try:
            count = 0
            for idx in range(addr_start_index, addr_start_index + addr_count):
                addr_info = self._get_child_address(key_entry, idx)
                count += 1
                yield addr_info
        except Exception as e:
            log.exception('Exception occurred while listing xpub addresses')
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

    def fetch_all_accounts_txs(self, check_break_process_fun: Callable):
        log.debug('Starting fetching transactions for all accounts.')

        self.increase_ext_call_level()
        try:
            for idx in range(MAX_BIP44_ACCOUNTS):
                if check_break_process_fun and check_break_process_fun():
                    break

                account_address_index = 0x80000000 + idx
                self.fetch_account_txs(account_address_index, check_break_process_fun)

                db_cursor = self.db_intf.get_cursor()
                try:
                    base_addr = self._get_key_entry_by_account_index(account_address_index)
                    db_cursor.execute("select id, received from address where id=?", (base_addr.id,))
                    id, received = db_cursor.fetchone()
                    if not id or not received:
                        break
                finally:
                    self.db_intf.release_cursor()
        finally:
            self.decrease_ext_call_level()
        log.debug('Finished fetching transactions for all accounts.')

    def fetch_account_txs(self, account_index: int, check_break_process_fun: Callable):
        log.debug(f'fetch_account_txs account index: {account_index}')
        tm_begin = time.time()

        self.increase_ext_call_level()
        try:
            if account_index < 0:
                raise Exception('Invalid account number')

            base_addr = self._get_key_entry_by_account_index(account_index)

            for change in (0, 1):
                if check_break_process_fun and check_break_process_fun():
                    break

                child = base_addr.get_child(change)
                self._fetch_xpub_txs(child, check_break_process_fun)
        finally:
            self.decrease_ext_call_level()

        log.debug(f'fetch_account_txs exec time: {time.time() - tm_begin}s')

    def fetch_account_xpub_txs(self, account_xpub: str, change: int, check_break_process_fun: Callable):
        """
        Dedicated for scanning external xpub accounts (not managed by the current hardware wallet) to find the
        first not used ("fresh") addres to be used as a transaction destination.
        :param account_xpub: xpub of the account
        :param change: 0 or 1 (usually 0, since there is no reason to scan the change addresses)
        """

        tm_begin = time.time()
        self.increase_ext_call_level()
        try:
            key_entry = self._get_key_entry_by_xpub(account_xpub)
            child = key_entry.get_child(change)
            self._fetch_xpub_txs(child, check_break_process_fun)
        finally:
            self.decrease_ext_call_level()

        log.debug(f'fetch_account_xpub_txs exec time: {time.time() - tm_begin}s')

    def _fetch_xpub_txs(self, key_entry: Bip44KeysEntry, check_break_process_fun: Callable = None):

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
        for addr_info in self._list_xpub_addresses(key_entry, 0, MAX_ADDRESSES_TO_SCAN):
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

        self._update_modified_addresses_balance()

    def fetch_addresses_txs(self, addr_info_list: List[AddressType], check_break_process_fun: Callable):
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
        finally:
            self.decrease_ext_call_level()

        log.debug(f'fetch_addresses_txs exec time: {time.time() - tm_begin}s')

    def _process_addresses_txs(self, addr_info_list: List[AddressType], max_block_height: int):

        tm_begin = time.time()
        addrinfo_by_address = {}
        addresses = []
        last_block_height = max_block_height

        for addr_info in addr_info_list:
            if addr_info.address:
                addrinfo_by_address[addr_info.address] = addr_info
                addresses.append(addr_info.address)
                bh = addr_info.last_scan_block_height
                if bh is None:
                    bh = 0
                if bh < last_block_height:
                    last_block_height = bh

            #todo: test
            # if last_block_height > 3:
            #     last_block_height -= 3

        if last_block_height < max_block_height:
            log.debug(f'getaddressdeltas for {addresses}, start: {last_block_height + 1}, end: {max_block_height}')
            txids = self.dashd_intf.getaddressdeltas({'addresses': addresses,
                                                     'start': last_block_height + 1,
                                                     'end': max_block_height})

            db_cursor = self.db_intf.get_cursor()
            try:
                for tx_entry in txids:
                    address = tx_entry.get('address')
                    addr_db_id = addrinfo_by_address[address].id
                    self._process_tx_entry(tx_entry, addr_db_id, address, db_cursor)

                # update the last scan block height info for each of the addresses
                for addr_info in addr_info_list:
                    db_cursor.execute('update address set last_scan_block_height=? where id=?',
                                      (max_block_height, addr_info.id))

            finally:
                if db_cursor.connection.total_changes > 0:
                    self.db_intf.commit()
                self.db_intf.release_cursor()

            for addr_info in addr_info_list:
                if addr_info.address:
                    addr_info.last_scan_block_height = max_block_height

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
                db_cursor.execute('update tx_output set address_id=?, address=? where id=?', (addr_db_id, address,
                                                                                              utxo_id))

                changed = True
                log.debug('Updating address_id of a tx_output entry (address_id: %s, tx_id: %s)', addr_db_id,
                          tx_db_id)
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
            # following addressses will have balance changed after purging the transaction
            db_cursor.execute('select address_id from tx_output where address_id is not null and '
                              '(tx_id=? or spent_tx_id=?) union '
                              'select address_id from tx_input where address_id is not null and tx_id=?',
                              (tx_id, tx_id, tx_id))

            for row in db_cursor.fetchall():
                self.addr_bal_updated[row[0]] = True

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

            self._update_modified_addresses_balance(db_cursor)
        finally:
            if db_cursor.rowcount:
                self.db_intf.commit()
            if release_cursor:
                self.db_intf.release_cursor()

    def _update_modified_addresses_balance(self, db_cursor=None):
        # Update the addresses' 'balance' and 'received' fields, limiting modifications to those
        # existing in self.addr_bal_updated dict

        if self.addr_bal_updated:
            if not db_cursor:
                db_cursor = self.db_intf.get_cursor()
                release_cursor = True
            else:
                release_cursor = False

            try:
                account_addresses: List[int, int] = {}
                change_addresses: List[int, int] = {}

                for addr_id in self.addr_bal_updated:
                    db_cursor.execute('select aa.id, ca.id from address a join address ca on ca.id=a.parent_id '
                                      'join address aa on aa.id=ca.parent_id where a.id=?', (addr_id,))
                    for account_id, change_id in db_cursor.fetchall():
                        if account_id:
                            account_addresses[account_id] = account_id
                        if change_id:
                            change_addresses[change_id] = change_id

                    db_cursor.execute('update address set received=(select ifnull(sum(satoshis),0) '
                                      'from tx_output o where o.address_id=address.id) where address.id=?', (addr_id,))

                    db_cursor.execute('update address set balance=received + (select ifnull(sum(satoshis),0) '
                                      'from tx_input o where o.address_id=address.id) where address.id=?', (addr_id,))

                # update the 'change' level of the bip44 address hierarchy
                for addr_id in change_addresses:
                    db_cursor.execute('update address set balance=(select sum(balance) from address a1 '
                                      'where a1.parent_id=address.id), received=(select sum(received) from '
                                      'address a1 where a1.parent_id=address.id) where id=?', (addr_id,))

                # ... and finally the 'account' level
                for addr_id in account_addresses:
                    db_cursor.execute('update address set balance=(select sum(balance) from address a1 '
                                      'where a1.parent_id=address.id), received=(select sum(received) from '
                                      'address a1 where a1.parent_id=address.id) where id=?', (addr_id,))

            finally:
                if db_cursor.connection.total_changes > 0:
                    self.db_intf.commit()
                if release_cursor:
                    self.db_intf.release_cursor()
                self.addr_bal_updated.clear()

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
                utxo_ids = [utxo_id for utxo_id in self.utxos_added]
                sql_text += ' and o.id=?'
            else:
                # return all utxos for the required account
                utxo_ids = [None]

            for utxo_id in utxo_ids:
                if utxo_id is None:
                    db_cursor.execute(sql_text, (account_id,))
                else:
                    db_cursor.execute(sql_text, (account_id, utxo_id))

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

    def list_utxos_for_addresses(self, address_ids: List[int]) -> Generator[UtxoType, None, None]:
        db_cursor = self.db_intf.get_cursor()
        try:
            for address_id in address_ids:
                db_cursor.execute("select o.id, cha.path, a.address_index, tx.block_height, tx.coinbase, "
                                  "tx.block_timestamp,"
                                  "tx.tx_hash, o.address, o.output_index, o.satoshis, o.address_id from tx_output o "
                                  "join address a "
                                  "on a.id=o.address_id join address cha on cha.id=a.parent_id join address aca "
                                  "on aca.id=cha.parent_id join tx on tx.id=o.tx_id where (spent_tx_id is null "
                                  "or spent_input_index is null) and a.id=?", (address_id,))

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

            db_cursor.execute("select id, xpub_hash, address_index, path, balance, received from address where "
                              "parent_id is null and xpub_hash is not null and tree_id=? order by address_index",
                              (tree_id,))

            for id, xpub_hash, address_index, bip32_path, balance, received in db_cursor.fetchall():
                acc = self.accounts_by_id.get(id)
                if not acc:
                    acc = Bip44AccountType(id, xpub_hash, address_index, bip32_path, balance, received, '')
                    self.accounts_by_id[id] = acc
                    modified = True
                else:
                    modified = acc.update_from_args(balance=balance, received=received, name='')

                if modified:
                    self.accounts_modified.append(acc)

                db_cursor.execute('select a.id, a.address_index, a.address, ac.path parent_path, a.balance, '
                                  'a.received, ac.is_change from address a join address ac on a.parent_id=ac.id '
                                  'where ac.parent_id=? order by ac.address_index, a.address_index', (acc.id,))
                for add_row in db_cursor.fetchall():
                    addr = acc.address_by_id(add_row[0])
                    if not addr:
                        addr_info = dict([(col[0], add_row[idx]) for idx, col in enumerate(db_cursor.description)])
                        addr = self._get_address_from_dict(addr_info)
                        if addr.path:
                            addr.path = addr.path + '/' + str(addr.address_index)
                        acc.add_address(addr)
                        if acc not in self.accounts_modified:
                            self.accounts_modified.append(acc)
                    else:
                        modified = addr.update_from_args(balance=add_row[4], received=add_row[5])
                        if modified and acc not in self.accounts_modified:
                            self.accounts_modified.append(acc)
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

            self._update_modified_addresses_balance(db_cursor)
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

            db_cursor.execute("update tx_input set address_id=null where address_id in ("
                              "select a.id from address a join address a1 on a1.id=a.parent_id "
                              "join address a2 on a2.id=a1.parent_id where a2.id=?)",
                              (id,))

            db_cursor.execute("delete from address where parent_id in ("
                              "select a1.id from address a1 where a1.parent_id=?)", (id,))

            db_cursor.execute("delete from address where parent_id=?", (id,))

            db_cursor.execute("delete from address where id=?", (id,))
            acc = self.accounts_by_id.get(id)
            if acc:
                del self.accounts_by_id[id]
        finally:
            self.db_intf.commit()
            self.db_intf.release_cursor()

    def remove_address(self, id: int):
        log.debug(f'Deleting address from db. Account address db id: %s', id)
        db_cursor = self.db_intf.get_cursor()
        try:
            db_cursor.execute("update tx_output set address_id=null, address=null where address_id=?", (id,))

            db_cursor.execute("delete from tx_input where address_id=?", (id,))

            # db_cursor.execute("delete from address where parent_id=?", (id,))

            # db_cursor.execute("delete from address where id=?", (id,))

            db_cursor.execute("update address set last_scan_block_height=0 where id=?", (id,))
        finally:
            self.db_intf.commit()
            self.db_intf.release_cursor()
