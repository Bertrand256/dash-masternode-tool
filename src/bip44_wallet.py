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


Bip44AccountBaseAddress = namedtuple('Bip44AccountBaseAddress', ['id', 'xpub', 'bip32_path'])
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

        # list of accounts retrieved while calling self.list_accounts
        self.accounts_by_id: Dict[int, Bip44AccountType] = {}

        # accounts added/modified after the last call of reset_accounts_diffs and
        # also accounts, whose addresses was modified/added:
        self.accounts_modified:List[Bip44AccountType] = []

        # transactions added/modified since the last reset_tx_diffs call
        self.txs_added: Dict[int, int] = {}  # {'tx_id': 'address_id'}
        self.txs_modified: Dict[int, int] = {}  # {'tx_id': 'address_id'}

        # utxos added/removed since the last reset_tx_diffs call
        self.utxos_added: Dict[int, int] = {}  # {'tx_output.id': 'address_id'}
        self.utxos_removed: Dict[int, int] = {}  # {'tx_output.id': 'address_id'}

    def reset_tx_diffs(self):
        self.txs_added.clear()
        self.utxos_added.clear()
        self.utxos_removed.clear()

    def reset_accounts_diffs(self):
        self.accounts_modified.clear()

    def get_tree_id(self, db_cursor):
        db_cursor.execute('select id from ADDRESS_HD_TREE where ident=?', (self.hw_session.hd_tree_ident,))
        row = db_cursor.fetchone()
        if not row:
            db_cursor.execute('insert into ADDRESS_HD_TREE(ident) values(?)', (self.hw_session.hd_tree_ident,))
            db_id = db_cursor.lastrowid
        else:
            db_id = row[0]
        return db_id

    def get_block_height(self):
        if self.cur_block_height is None or \
           (time.time() - self.last_get_block_height_ts >= GET_BLOCKHEIGHT_MIN_SECONDS):
            self.cur_block_height = self.dashd_intf.getblockcount()
            self.last_get_block_height_ts = time.time()
        return self.cur_block_height

    def get_block_height_nofetch(self):
        return self.cur_block_height

    def get_address_id(self, address: int, db_cursor):
        db_cursor.execute('select id from address where address=?', (address,))
        row = db_cursor.fetchone()
        if row:
            return row[0]
        return None

    def _get_xpub_db_addr(self, xpub: str, bip32_path: Optional[str], is_change: bool, parent_id: Optional[int]) \
            -> AddressType:
        """
        :param xpub: Externded public key
        :param bip32_path: BIP32 address of the XPUB key (if XPUB is related to the local wallet's account)
        :return:
        """
        xpub_raw = Base58.check_decode(xpub)
        if xpub_raw[0:4] in (b'\x02\xfe\x52\xcc', b'\x04\x88\xb2\x1e'):  # remove xpub prefix
            xpub_raw = xpub_raw[4:]
        xpub_hash = bitcoin.bin_sha256(xpub_raw)
        xpub_hash = base64.b64encode(xpub_hash)
        address_index = None

        db_cursor = self.db_intf.get_cursor()
        try:
            if bip32_path:
                # xpub controlled by the local hardware wallet
                hd_tree_id = self.get_tree_id(db_cursor)
                bip32path_n = bip32_path_string_to_n(bip32_path)
                address_index = bip32path_n[-1]
            else:
                hd_tree_id = None

            db_cursor.execute('select id, tree_id, path, is_change, parent_id, address_index from address where '
                              'xpub_hash=?', (xpub_hash,))
            row = db_cursor.fetchone()
            if not row:
                db_cursor.execute('insert into address(xpub_hash, tree_id, path, is_change, parent_id, address_index) '
                                  'values(?,?,?,?,?,?)',
                                  (xpub_hash, hd_tree_id, bip32_path, 1 if is_change else 0, parent_id, address_index))
                db_id = db_cursor.lastrowid
                db_cursor.execute('select id, tree_id, path, is_change, parent_id, address_index from address '
                                  'where id=?', (db_id,))
                row = db_cursor.fetchone()
            else:
                if hd_tree_id != row[1] or bip32_path != row[2] or is_change != row[3] or parent_id != row[4] or \
                        address_index != row[5]:
                    db_cursor.execute('update address set tree_id=?, path=?, is_change=?, parent_id=?, address_index=? '
                                      'where id=?',
                                      (hd_tree_id, bip32_path, 1 if is_change else 0, parent_id, address_index, row[0]))

                    db_cursor.execute('select id, tree_id, path, is_change, parent_id, address_index from address '
                                      'where id=?', (row[0],))
                    row = db_cursor.fetchone()

            addr_info = dict([(col[0], row[idx]) for idx, col in enumerate(db_cursor.description)])
            return self._get_address_from_dict(addr_info)
        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()

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

    def _get_child_address(self, parent_address_id: int, child_addr_index: int, parent_key) -> AddressType:
        """
        :return: Tuple[int <id db>, str <address>, int <balance in duffs>]
        """
        db_cursor = self.db_intf.get_cursor()
        try:
            db_cursor.execute('select * from address where parent_id=? and address_index=?',
                              (parent_address_id, child_addr_index))
            row = db_cursor.fetchone()
            if not row:
                key = parent_key.ChildKey(child_addr_index)
                address = pubkey_to_address(key.PublicKey().hex(), self.dash_network)

                db_cursor.execute('select * from address where address=?',
                                  (address,))
                row = db_cursor.fetchone()
                if row:
                    addr_info = dict([(col[0], row[idx]) for idx, col in enumerate(db_cursor.description)])
                    if addr_info.get('parent_id') != parent_address_id or addr_info.get('address_index') != child_addr_index:
                        # address wasn't initially opened as a part of xpub account scan, so update its attrs
                        db_cursor.execute('update address set parent_id=?, address_index=? where id=?',
                                          (parent_address_id, child_addr_index, row[0]))

                        addr_info['parent_id'] = parent_address_id
                        addr_info['address_index'] = child_addr_index

                    return self._get_address_from_dict(addr_info)
                else:
                    db_cursor.execute('insert into address(parent_id, address_index, address) values(?,?,?)',
                                      (parent_address_id, child_addr_index, address))

                    addr_info = {
                        'id': db_cursor.lastrowid,
                        'parent_id': parent_address_id,
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

    def get_account_base_address(self, account_index: int) -> Bip44AccountBaseAddress:
        """
        :param account_index: for hardened accounts the value should be equal or grater than 0x80000000
        :return:
        """
        b32_path = self.hw_session.base_bip32_path
        if not b32_path:
            log.error('hw_session.base_bip32_path not set. Probable cause: not initialized HW session.')
            raise Exception('HW session not initialized. Look into the log file for details.')
        path_n = bip32_path_string_to_n(b32_path) + [account_index]
        account_bip32_path = bip32_path_n_to_string(path_n)
        account_xpub = hw_intf.get_xpub(self.hw_session, account_bip32_path)
        addr = self._get_xpub_db_addr(account_xpub, account_bip32_path, False, None)
        addr_id = addr.id
        return Bip44AccountBaseAddress(addr_id, account_xpub, account_bip32_path)

    def list_account_addresses(self, base_bip32_path: str, change: int, addr_start_index: int, addr_count: int) -> \
            Generator[AddressType, None, None]:

        account_xpub = hw_intf.get_xpub(self.hw_session, base_bip32_path)
        return self.list_account_xpub_addresses(account_xpub, change, addr_start_index, addr_count, base_bip32_path)

    def list_account_xpub_addresses(self, account_xpub: str, change: int, addr_start_index: int, addr_count: int,
                                    account_bip32_path: str = None) \
            -> Generator[AddressType, None, None]:

        account_key = BIP32Key.fromExtendedKey(account_xpub)
        change_key = account_key.ChildKey(change)
        change_xpub = change_key.ExtendedKey(False, True)

        parent_addr = self._get_xpub_db_addr(account_xpub, account_bip32_path, False, None)
        parent_addr_id = parent_addr.id

        bip32_path = bip32_path_n_to_string(bip32_path_string_to_n(account_bip32_path) + [change])

        return self.list_xpub_addresses(change_xpub, addr_start_index, addr_count, bip32_path,
                                        True if change == 1 else False, parent_addr_id)

    def list_xpub_addresses(self, xpub: str, addr_start_index: int, addr_count: int, bip32_path: str = None,
                            is_change_address: bool = False, parent_addr_id: Optional[int] = None) -> \
            Generator[AddressType, None, None]:

        tm_begin = time.time()
        try:
            xpub_db_id = self._get_xpub_db_addr(xpub, bip32_path, is_change_address, parent_addr_id).id

            key = BIP32Key.fromExtendedKey(xpub)
            count = 0
            for idx in range(addr_start_index, addr_start_index + addr_count):
                addr_info = self._get_child_address(xpub_db_id, idx, key)
                count += 1
                yield addr_info
        except Exception as e:
            log.exception('Exception occurred while listing xpub addresses')
        finally:
            diff = time.time() - tm_begin
            log.debug(f'list_account_addresses exec time: {diff}s, keys count: {count}')

    def fetch_all_accounts_txs(self, check_break_process_fun: Callable):
        log.debug('Starting fetching transactions for all accounts.')
        for idx in range(MAX_BIP44_ACCOUNTS):
            if check_break_process_fun and check_break_process_fun():
                break

            account_address_index = 0x80000000 + idx
            self.fetch_account_txs(account_address_index, check_break_process_fun)

            db_cursor = self.db_intf.get_cursor()
            try:
                base_addr = self.get_account_base_address(account_address_index)
                db_cursor.execute("select id, received from address where id=?", (base_addr.id,))
                id, received = db_cursor.fetchone()
                if not id or not received:
                    break
            finally:
                self.db_intf.release_cursor()
        log.debug('Finished fetching transactions for all accounts.')

    def fetch_account_txs(self, account_index: int, check_break_process_fun: Callable):
        log.debug(f'read_account_bip32_txs account index: {account_index}')
        tm_begin = time.time()

        if account_index < 0:
            raise Exception('Invalid account number')

        base_addr = self.get_account_base_address(account_index)
        account_key = BIP32Key.fromExtendedKey(base_addr.xpub)

        for change in (0, 1):
            if check_break_process_fun and check_break_process_fun():
                break

            key = account_key.ChildKey(change)
            xpub = key.ExtendedKey(False, True)
            bip32_path = bip32_path_n_to_string(bip32_path_string_to_n(base_addr.bip32_path) + [change])
            self.fetch_xpub_txs(xpub, bip32_path, True if change == 1 else False, base_addr.id, check_break_process_fun)

        log.debug(f'read_account_bip32_txs exec time: {time.time() - tm_begin}s')

    def fetch_account_xpub_txs(self, account_xpub: str, change: int, check_break_process_fun: Callable):
        """
        Dedicated for scanning external xpub accounts (not managed by the current hardware wallet) to find the
        first not used ("fresh") addres to be used as a transaction destination.
        :param account_xpub: xpub of the account
        :param change: 0 or 1 (usually 0, since there is no reason to scan the change addresses)
        """
        tm_begin = time.time()

        parent_addr = self._get_xpub_db_addr(account_xpub, None, False, None)
        parent_addr_id = parent_addr.id

        account_key = BIP32Key.fromExtendedKey(account_xpub)
        key = account_key.ChildKey(change)
        xpub = key.ExtendedKey(False, True)
        self.fetch_xpub_txs(xpub, None, True if change == 1 else False, parent_addr_id, check_break_process_fun)

        log.debug(f'read_account_xpub_txs exec time: {time.time() - tm_begin}s')

    def fetch_xpub_txs(self, xpub: str, bip32_path: Optional[str] = None, is_change_address: bool = False,
                       parent_addr_id: Optional[int] = None, check_break_process_fun: Callable = None):
        # addresses whose balances have been changed during this processing
        addr_bal_updated: Dict[int, bool] = {}

        cur_block_height = self.get_block_height()

        empty_addresses = 0
        addresses = []
        for addr_info in self.list_xpub_addresses(xpub, 0, MAX_ADDRESSES_TO_SCAN, bip32_path,
                                                               is_change_address, parent_addr_id):
            addresses.append(addr_info)

            if len(addresses) >= TX_QUERY_ADDR_CHUNK_SIZE:

                if check_break_process_fun and check_break_process_fun():
                    break

                self._process_addresses_txs(addresses, cur_block_height, addr_bal_updated)

                if check_break_process_fun and check_break_process_fun():
                    break

                # count the number of addresses with no associated transactions starting from the end
                _empty_addresses = 0
                db_cursor = self.db_intf.get_cursor()
                try:
                    for addr_info in reversed(addresses):
                        addr_id = addr_info.id

                        # check if there was no transactions for the address
                        if not addr_bal_updated.get(addr_id):
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
            self._process_addresses_txs(addresses, cur_block_height, addr_bal_updated)

        # update addresses' 'balance' and 'received'
        if addr_bal_updated:
            db_cursor = self.db_intf.get_cursor()
            try:
                for addr_id in addr_bal_updated:
                    db_cursor.execute('update address set received=(select ifnull(sum(satoshis),0) '
                                      'from tx_output o where o.address_id=address.id) where address.id=?', (addr_id,))

                    db_cursor.execute('update address set balance=received + (select ifnull(sum(satoshis),0) '
                                      'from tx_input o where o.address_id=address.id) where address.id=?', (addr_id,))

                # update balance of the xpub address to which belong the addresses with modified balance
                xpub_address_id = self._get_xpub_db_addr(xpub, bip32_path, is_change_address, parent_addr_id).id

                db_cursor.execute('update address set balance=(select sum(balance) from address a1 '
                                  'where a1.parent_id=address.id), received=(select sum(received) from '
                                  'address a1 where a1.parent_id=address.id) where id=?', (xpub_address_id,))

                # ... and finally the same for the top level account xpub entry
                if parent_addr_id:
                    db_cursor.execute('update address set balance=(select sum(balance) from address a1 '
                                      'where a1.parent_id=address.id), received=(select sum(received) from '
                                      'address a1 where a1.parent_id=address.id) where id=?', (parent_addr_id,))

            finally:
                if db_cursor.connection.total_changes > 0:
                    self.db_intf.commit()
                self.db_intf.release_cursor()

    def _process_addresses_txs(self, addr_info_list: List[AddressType], max_block_height: int,
                               addr_bal_updated: Dict[int, bool]):

        addrinfo_by_address = {}
        addresses = []
        last_block_height = max_block_height

        for addr_info in addr_info_list:
            addrinfo_by_address[addr_info.address] = addr_info
            addresses.append(addr_info.address)
            bh = addr_info.last_scan_block_height
            if bh is None:
                bh = 0
            if bh < last_block_height:
                last_block_height = bh

            #todo: test
            if last_block_height > 3:
                last_block_height -= 3

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
                    self._process_tx_entry(tx_entry, addr_db_id, address, db_cursor, addr_bal_updated)

                # update the last scan block height info for each of the addresses
                for addr_info in addr_info_list:
                    db_cursor.execute('update address set last_scan_block_height=? where id=?',
                                      (max_block_height, addr_info.id))

            finally:
                if db_cursor.connection.total_changes > 0:
                    self.db_intf.commit()
                self.db_intf.release_cursor()

    def _process_tx_entry(self, tx_entry: Dict, addr_db_id: int, address: str, db_cursor,
                          addr_bal_updated: Dict[int, bool]):

        txid = tx_entry.get('txid')
        tx_index = tx_entry.get('index')
        satoshis = tx_entry.get('satoshis')

        if satoshis > 0:
            # incoming transaction entry
            self._process_tx_output_entry(db_cursor, txid, tx_index, None, addr_db_id, address, satoshis,
                                          addr_bal_updated)
        else:
            # outgoing transaction entry
            self._process_tx_input_entry(db_cursor, txid, tx_index, None, addr_db_id, satoshis, addr_bal_updated)

    def _process_tx_output_entry(self, db_cursor, txid: str, tx_index: int, tx_json: Optional[Dict], addr_db_id: int,
                                address: str, satoshis: int, addr_bal_updated: Dict[int, bool]):

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
            addr_bal_updated[addr_db_id] = True

    def _process_tx_input_entry(self, db_cursor, txid: str, tx_index: int, tx_json: Optional[Dict], addr_db_id: int,
                                satoshis: int, addr_bal_updated: Dict[int, bool]):

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

            addr_bal_updated[addr_db_id] = True
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
                    addr_bal_updated[addr_db_id] = True

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
                              (tx_hash, tx_json.get('height'), block_timestamp, is_coinbase))
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

    def _purge_unconfirmed_transactions(self):
        pass  # todo: continue here

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

    def list_utxos_for_address(self, address_id: int) -> Generator[UtxoType, None, None]:
        db_cursor = self.db_intf.get_cursor()
        try:
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
            tree_id = self.get_tree_id(db_cursor)

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
            addr_bal_updated = {}

            for idx, txi in enumerate(inputs):
                self._process_tx_input_entry(db_cursor, txid, idx, tx_json, txi.address_id, txi.satoshis,
                                             addr_bal_updated)

            for idx, txo in enumerate(outputs):
                address_id = self.get_address_id(txo.address, db_cursor)
                if address_id:
                    # we aren't interested in caching tx outputs which aren't directed to our wallet's addresses
                    self._process_tx_output_entry(db_cursor, txid, idx, tx_json, address_id, txo.address, txo.satoshis,
                                                  addr_bal_updated)
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
