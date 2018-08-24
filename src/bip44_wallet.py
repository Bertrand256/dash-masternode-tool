#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-07

import time
import base64
import bitcoin
import datetime
import logging
from bip32utils import BIP32Key, Base58
from collections import namedtuple
from typing import List, Dict, Tuple, Optional, Any, Generator, NamedTuple

import app_utils
import hw_intf
from common import namedtuple_defaults, AttrsProtected
from dash_utils import bip32_path_string_to_n, pubkey_to_address, bip32_path_n_to_string
from dashd_intf import DashdInterface
from hw_common import HwSessionInfo
from db_intf import DBCache


TX_QUERY_ADDR_CHUNK_SIZE = 10
ADDRESS_SCAN_GAP_LIMIT = 20
MAX_ADDRESSES_TO_SCAN = 1000
MAX_BIP44_ACCOUNTS = 200


Bip44AccountBaseAddress = namedtuple('Bip44AccountBaseAddress', ['id', 'xpub', 'bip32_path'])


class UtxoType(AttrsProtected):
    def __init__(self):
        super(UtxoType, self).__init__()
        self.id = None
        self.address = None
        self.txid = None
        self.output_index = None
        self.satoshis = None
        self.confirmations = None
        self.bip32_path = None
        self.time_str = None
        self.is_collateral = False
        self.coinbase_locked = False
        self.masternode = None
        self.set_attr_protection()


class AddressType(AttrsProtected):
    def __init__(self):
        super(AddressType, self).__init__()
        self.id = None
        self.xpub_hash = None
        self.parent_id = None
        self.address_index = None
        self.address = None
        self.path = None
        self.tree_id = None
        self.balance = None
        self.received = None
        self.is_change = None
        self.last_scan_block_height = None
        self.bip44_account = None
        self.set_attr_protection()


class Bip44AccountType(AttrsProtected):
    def __init__(self, id: int, xpub_hash: str, address_index: int, bip32_path: str, balance: int, received: int,
                 name: str):
        super(Bip44AccountType, self).__init__()
        self.id: Optional[int] = id
        self.xpub_hash: str = xpub_hash
        self.address_index: Optional[int] = address_index
        self.bip32_path: Optional[int] = bip32_path
        self.balance: Optional[int] = balance
        self.received: Optional[int] = received
        self.name: Optional[str] = name
        self.addresses: List[AddressType] = []
        self.set_attr_protection()

    def get_hardened_index(self):
        if self.address_index >= 0x80000000:
            return self.address_index - 0x80000000
        else:
            return None

    def get_account_name(self):
        if self.name:
            return self.name
        else:
            nr = self.get_hardened_index()
            if nr is not None:
                return f'Account #' + str(nr + 1)
            else:
                return f'Account *' + str(self.address_index)

    def update_from(self, a: 'Bip44AccountType') -> bool:
        """
        :param a:
        :return: True if any of the attributes have been updated
        """
        if a.id != self.id or a.xpub_hash != self.xpub_hash or a.address_index != self.address_index or \
            a.bip32_path != self.bip32_path or a.balance != self.balance or a.received != self.received or \
            a.name != self.name:

            self.id = a.id
            self.xpub_hash = self.xpub_hash
            self.address_index = self.address_index
            self.bip32_path = self.bip32_path
            self.balance = self.balance
            self.received = self.received
            self.name = self.name
            return True
        return False

    def add_address(self, address: AddressType):
        address.bip44_account = self
        self.addresses.append(address)

    def address_by_index(self, index):
        if index >= 0 and index < len(self.addresses):
            return self.addresses[index]
        else:
            return None


class Bip44Wallet(object):
    def __init__(self, hw_session: HwSessionInfo, db_intf: DBCache, dashd_intf: DashdInterface, dash_network: str):
        self.db = None
        self.hw_session = hw_session
        self.dash_network = dash_network
        self.db_intf = db_intf
        self.dashd_intf = dashd_intf
        self.txs_added: Dict[int, int] = {}
        self.utxos_added: Dict[int, int] = {}
        self.utxos_removed: Dict[int, int] = {}

    def reset_tx_diffs(self):
        self.txs_added.clear()
        self.utxos_added.clear()
        self.utxos_removed.clear()

    def get_tree_id(self, db_cursor):
        db_cursor.execute('select id from ADDRESS_HD_TREE where ident=?', (self.hw_session.hd_tree_ident,))
        row = db_cursor.fetchone()
        if not row:
            db_cursor.execute('insert into ADDRESS_HD_TREE(ident) values(?)', (self.hw_session.hd_tree_ident,))
            db_id = db_cursor.lastrowid
        else:
            db_id = row[0]
        return db_id

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

    def _get_child_address(self, parent_address_id: int, child_addr_index: int, parent_key) \
            -> AddressType:
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
        finally:
            diff = time.time() - tm_begin
            logging.info(f'list_account_addresses exec time: {diff}s, keys count: {count}')

    def fetch_all_accounts_txs(self):
        for idx in range(MAX_BIP44_ACCOUNTS):
            account_address_index = 0x80000000 + idx
            self.read_account_txs(account_address_index)

            db_cursor = self.db_intf.get_cursor()
            try:
                base_addr = self.get_account_base_address(account_address_index)
                db_cursor.execute("select id, received from address where id=?", (base_addr.id,))
                id, received = db_cursor.fetchone()
                if not id or not received:
                    break
            finally:
                self.db_intf.release_cursor()

    def read_account_txs(self, account_index: int):
        logging.info(f'read_account_bip32_txs account index: {account_index}')
        tm_begin = time.time()

        if account_index < 0:
            raise Exception('Invalid account number')

        base_addr = self.get_account_base_address(account_index)
        account_key = BIP32Key.fromExtendedKey(base_addr.xpub)

        for change in (0, 1):
            key = account_key.ChildKey(change)
            xpub = key.ExtendedKey(False, True)
            bip32_path = bip32_path_n_to_string(bip32_path_string_to_n(base_addr.bip32_path) + [change])
            self.read_xpub_txs(xpub, bip32_path, True if change == 1 else False, base_addr.id)

        logging.info(f'read_account_bip32_txs exec time: {time.time() - tm_begin}s')

    def read_account_xpub_txs(self, account_xpub: str, change: int):
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
        self.read_xpub_txs(xpub, None, True if change == 1 else False, parent_addr_id)

        logging.info(f'read_account_xpub_txs exec time: {time.time() - tm_begin}s')

    def read_xpub_txs(self, xpub: str, bip32_path: Optional[str] = None, is_change_address: bool = False,
                      parent_addr_id: Optional[int] = None):
        # addresses whose balances have been changed during this processing
        addr_bal_updated: Dict[int, bool] = {}

        cur_block_height = self.dashd_intf.getblockcount()

        empty_addresses = 0
        addresses = []
        for addr_info in self.list_xpub_addresses(xpub, 0, MAX_ADDRESSES_TO_SCAN, bip32_path,
                                                               is_change_address, parent_addr_id):
            addresses.append(addr_info)

            if len(addresses) >= TX_QUERY_ADDR_CHUNK_SIZE:

                self._process_addresses_txs(addresses, cur_block_height, addr_bal_updated)

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

        if last_block_height < max_block_height:
            txids = self.dashd_intf.getaddresstxids({'addresses': addresses,
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

        tx_id, tx_json = self._get_tx_db_id(tx_entry.get('txid'), db_cursor)
        tx_index = tx_entry.get('index')
        satoshis = tx_entry.get('satoshis')

        if satoshis > 0:
            # incoming transaction entry
            db_cursor.execute('select id, address_id from tx_output where tx_id=? and output_index=?',
                              (tx_id, tx_index))
            row = db_cursor.fetchone()
            if not row:
                db_cursor.execute('insert into tx_output(address_id, address, tx_id, output_index, satoshis) '
                                  'values(?,?,?,?,?)', (addr_db_id, address, tx_id, tx_index, satoshis))
                self.txs_added[tx_id] = tx_id
                addr_bal_updated[addr_db_id] = True
                out_db_id = db_cursor.lastrowid
            else:
                out_db_id = row[0]
                if addr_db_id != row[1]:
                    db_cursor.execute('update tx_output set address_id=? where id=?', (addr_db_id, out_db_id))
                    self.txs_added[tx_id] = tx_id
                    addr_bal_updated[addr_db_id] = True

            if out_db_id not in self.utxos_added:
                self.utxos_added[out_db_id] = out_db_id
        else:
            # outgoing transaction entry
            db_cursor.execute('select id from tx_input where tx_id=? and input_index=?', (tx_id, tx_index))
            row = db_cursor.fetchone()

            # for this outgoing tx entry find a related incoming one and mark it as spent
            if not tx_json:
                tx_json = self.dashd_intf.getrawtransaction(tx_entry.get('txid'), 1)

            if not row:
                db_cursor.execute('insert into tx_input(tx_id, input_index, address_id, satoshis) values(?,?,?,?)',
                                  (tx_id, tx_index, addr_db_id, satoshis))
                self.txs_added[tx_id] = tx_id
                addr_bal_updated[addr_db_id] = True

            tx_vin = tx_json.get('vin')
            if tx_index < len(tx_vin):
                related_tx_vin = tx_vin[tx_index]
                related_txid = related_tx_vin.get('txid')
                related_tx_index = related_tx_vin.get('vout')
                related_tx_db_id, _ = self._get_tx_db_id(related_txid, db_cursor)

                # the related transaction should already be in the database cache
                db_cursor.execute('select id, spent_tx_id, spent_input_index from tx_output where tx_id=? '
                                  'and output_index=?', (related_tx_db_id, related_tx_index))
                row = db_cursor.fetchone()
                if row:
                    out_db_id = row[0]
                    if row[1] != tx_id or row[2] != tx_index:
                        db_cursor.execute('update tx_output set spent_tx_id=?, spent_input_index=? where id=?',
                                          (tx_id, tx_index, out_db_id))
                        self.txs_added[tx_id] = tx_id
                        addr_bal_updated[addr_db_id] = True

                    if out_db_id in self.utxos_added:
                        del self.utxos_added[out_db_id]
                    else:
                        self.utxos_removed[out_db_id] = out_db_id
                else:
                    logging.warning(f'Could not find the related transaction for this tx entry. Txid: {related_txid}, '
                                    f'index: {tx_index}')
            else:
                logging.warning('Could not find vin of the related transaction for this transaction entry. '
                                f'Txid: {tx_id}, index: {tx_index}.')

    def _wrap_txid(self, txid: str):
        # base64 format takes less space in the db than hex string
        # return base64.b64encode(bytes.fromhex(txid))
        return txid # todo: store txid instead of tx hash to simplify testing

    def _unwrap_txid(self, txid_wrapped: str):
        # return base64.b64decode(txid_wrapped).hex()
        return txid_wrapped  # todo: for testling only

    def _get_tx_db_id(self, txid: str, db_cursor) -> Tuple[int, Optional[Dict]]:
        """
        :param tx_entry:
        :param db_cursor:
        :return: Tuple[int <transaction db id>, Optional[Dict <transaction details json>]]
        """
        tx_json = None
        tx_hash = self._wrap_txid(txid)

        db_cursor.execute('select id from tx where tx_hash=?', (tx_hash,))
        row = db_cursor.fetchone()
        if not row:
            tx_json = self.dashd_intf.getrawtransaction(txid, 1)
            block_hash = self.dashd_intf.getblockhash(tx_json.get('height'))
            block_header = self.dashd_intf.getblockheader(block_hash)
            tx_vin = tx_json.get('vin', [])
            is_coinbase = 1 if (len(tx_vin) == 1 and tx_vin[0].get('coinbase')) else 0

            db_cursor.execute('insert into tx(tx_hash, block_height, block_timestamp, coinbase) values(?,?,?,?)',
                              (tx_hash, tx_json.get('height'), block_header.get('time'), is_coinbase))
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
        return tx_id, tx_json

    def list_utxos_for_account(self, account_id: int) -> Generator[UtxoType, None, None]:
        """
        :param account_id: database id of the account's record
        """

        cur_block_height = self.dashd_intf.getblockcount()

        db_cursor = self.db_intf.get_cursor()
        try:
            db_cursor.execute("select o.id, cha.path, a.address_index, tx.block_height, tx.coinbase, "
                              "tx.block_timestamp,"
                              "tx.tx_hash, o.address, o.output_index, o.satoshis from tx_output o join address a "
                              "on a.id=o.address_id join address cha on cha.id=a.parent_id join address aca "
                              "on aca.id=cha.parent_id join tx on tx.id=o.tx_id where (spent_tx_id is null "
                              "or spent_input_index is null) and aca.id=?", (account_id,))

            for id, path, addr_index, block_height, coinbase, block_timestamp, tx_hash, address, output_index,\
                satoshis in db_cursor.fetchall():

                utxo = UtxoType()
                utxo.id = id
                utxo.txid = self._unwrap_txid(tx_hash)
                utxo.address = address
                utxo.output_index = output_index
                utxo.satoshis = satoshis
                utxo.confirmations = cur_block_height - block_height
                utxo.bip32_path = path + '/' + str(addr_index) if path else ''
                utxo.time_str = app_utils.to_string(datetime.datetime.fromtimestamp(block_timestamp))
                utxo.coinbase_locked = True if coinbase and utxo.confirmations < 100 else False
                yield utxo

        finally:
            self.db_intf.release_cursor()

    def list_utxos_for_address(self, address_id: int) -> Generator[UtxoType, None, None]:
        cur_block_height = self.dashd_intf.getblockcount()

        db_cursor = self.db_intf.get_cursor()
        try:
            db_cursor.execute("select o.id, cha.path, a.address_index, tx.block_height, tx.coinbase, "
                              "tx.block_timestamp,"
                              "tx.tx_hash, o.address, o.output_index, o.satoshis from tx_output o join address a "
                              "on a.id=o.address_id join address cha on cha.id=a.parent_id join address aca "
                              "on aca.id=cha.parent_id join tx on tx.id=o.tx_id where (spent_tx_id is null "
                              "or spent_input_index is null) and a.id=?", (address_id,))

            for id, path, addr_index, block_height, coinbase, block_timestamp, tx_hash, address, output_index,\
                satoshis in db_cursor.fetchall():

                utxo = UtxoType()
                utxo.id = id
                utxo.txid = self._unwrap_txid(tx_hash)
                utxo.address = address
                utxo.output_index = output_index
                utxo.satoshis = satoshis
                utxo.confirmations = cur_block_height - block_height
                utxo.bip32_path = path + '/' + str(addr_index) if path else ''
                utxo.time_str = app_utils.to_string(datetime.datetime.fromtimestamp(block_timestamp))
                utxo.coinbase_locked = True if coinbase and utxo.confirmations < 100 else False
                yield utxo

        finally:
            self.db_intf.release_cursor()

    def list_accounts(self) -> Generator[Bip44AccountType, None, None]:
        tm_begin = time.time()
        db_cursor = self.db_intf.get_cursor()
        try:
            tree_id = self.get_tree_id(db_cursor)

            db_cursor.execute("select id, xpub_hash, address_index, path, balance, received from address where "
                              "parent_id is null and tree_id=? order by address_index", (tree_id,))

            for id, xpub_hash, address_index, bip32_path, balance, received in db_cursor.fetchall():
                acc = Bip44AccountType(id, xpub_hash, address_index, bip32_path, balance, received, '')

                db_cursor.execute('select a.id, a.address_index, a.address, ac.path parent_path, a.balance, '
                                  'a.received, ac.is_change from address a join address ac on a.parent_id=ac.id '
                                  'where ac.parent_id=? order by ac.address_index, a.address_index', (acc.id,))
                for add_row in db_cursor.fetchall():
                    addr_info = dict([(col[0], add_row[idx]) for idx, col in enumerate(db_cursor.description)])
                    add = self._get_address_from_dict(addr_info)
                    if add.path:
                        add.path = add.path + '/' + str(add.address_index)
                    acc.add_address(add)
                yield acc
        finally:
            self.db_intf.release_cursor()
        diff = time.time() - tm_begin
        logging.info(f'Accounts read time: {diff}s')

    def list_bip32_address_utxos(self):
        pass

    def list_bip32_account_txs(self):
        pass