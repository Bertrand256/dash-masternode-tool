import time

import base64
import bitcoin
import logging
from bip32utils import BIP32Key, Base58
from typing import List, Dict, Tuple, Optional
import hw_intf
from dash_utils import bip32_path_string_to_n, pubkey_to_address, bip32_path_n_to_string
from dashd_intf import DashdInterface
from hw_common import HwSessionInfo
from db_intf import DBCache


TX_QUERY_ADDR_CHUNK_SIZE = 10
ADDRESS_STOP_GAP_SIZE = 20
MAX_ADDRESSES_TO_SCAN = 1000


class Bip32Addresses(object):
    def __init__(self, hw_session: HwSessionInfo, db_intf: DBCache, dashd_intf: DashdInterface, dash_network: str):
        self.db = None
        self.hw_session = hw_session
        self.dash_network = dash_network
        self.db_intf = db_intf
        self.dashd_intf = dashd_intf
        self._xpub_cache: Dict[str, str] =  {}  # Dict[str <hd_tree_id + ':' + bip32_path>, str <xpub>]

    def get_tree_id(self, db_cursor):
        db_cursor.execute('select id from ADDRESS_HD_TREE where ident=?', (self.hw_session.hd_tree_ident,))
        row = db_cursor.fetchone()
        if not row:
            db_cursor.execute('insert into ADDRESS_HD_TREE(ident) values(?)', (self.hw_session.hd_tree_ident,))
            db_id = db_cursor.lastrowid
        else:
            db_id = row[0]
        return db_id

    def get_address_db_id(self, path_n: List[int], db_cursor):
        if len(path_n) > 1:
            return self.get_address_db_id(path_n[:-1], db_cursor)
        elif len(path_n) == 1:
            tree_id = self.get_tree_id(db_cursor)
            db_cursor.execute('select id from address where tree_id=?', (tree_id,))
            r = db_cursor.fetchone()
            if r:
                return r[0]
            else:
                pass

    def get_xpub_db_addr(self, xpub: str, bip32_path: str, is_change: bool) -> Dict:
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

        db_cursor = self.db_intf.get_cursor()
        try:
            if bip32_path:
                # xpub controlled by the local hardware wallet
                hd_tree_id = self.get_tree_id(db_cursor)
            else:
                hd_tree_id = None

            db_cursor.execute('select id, tree_id, path, is_change from address where xpub_hash=?', (xpub_hash,))
            row = db_cursor.fetchone()
            if not row:
                db_cursor.execute('insert into address(xpub_hash, tree_id, path, is_change) values(?,?,?,?)',
                                  (xpub_hash, hd_tree_id, bip32_path, 1 if is_change else 0))
                db_id = db_cursor.lastrowid
                db_cursor.execute('select id, tree_id, path, is_change from address where id=?', (db_id,))
                row = db_cursor.fetchone()
                addr = dict([(col[0], row[idx]) for idx, col in enumerate(db_cursor.description)])
            else:
                addr = dict([(col[0], row[idx]) for idx, col in enumerate(db_cursor.description)])
                if hd_tree_id != row[1] or bip32_path != row[2] or is_change != row[3]:
                    db_cursor.execute('update address set tree_id=?, path=?, is_change=? where id=?',
                                      (hd_tree_id, bip32_path, 1 if is_change else 0, row[0]))
        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()
        return addr

    def get_child_address(self, parent_address_id: int, child_addr_index: int, parent_key) \
            -> Tuple[int, str, Optional[int]]:
        """
        :return: Tuple[int <id db>, str <address>, int <balance in duffs>]
        """
        db_cursor = self.db_intf.get_cursor()
        try:
            db_cursor.execute('select id, address, balance from address where parent_id=? and address_index=?',
                              (parent_address_id, child_addr_index))
            row = db_cursor.fetchone()
            if not row:
                key = parent_key.ChildKey(child_addr_index)
                address = pubkey_to_address(key.PublicKey().hex(), self.dash_network)
                # address = hw_intf.get_address(self.hw_session, path)

                db_cursor.execute('select id, address, balance, parent_id, address_index from address where address=?',
                                  (address,))
                row = db_cursor.fetchone()
                if row:
                    if row[3] != parent_address_id or row[4] != child_addr_index:
                        # address wasn't initially opened as a part of xpub account scan, so update its attrs
                        db_cursor.execute('update address set parent_id=?, address_index=? where id=?',
                                          (parent_address_id, child_addr_index, row[0]))
                    return row[0], row[1], row[2]
                else:
                    db_cursor.execute('insert into address(parent_id, address_index, address) values(?,?,?)',
                                      (parent_address_id, child_addr_index, address))
                    return (db_cursor.lastrowid, address, None)
            return row
        except Exception:
            raise
        finally:
            if db_cursor.connection.total_changes > 0:
                self.db_intf.commit()
            self.db_intf.release_cursor()

    def list_account_addresses(self, base_bip32_path: str, change: int, addr_start_index: int, addr_count: int):
        account_xpub = hw_intf.get_xpub(self.hw_session, base_bip32_path)
        return self.list_account_xpub_addresses(account_xpub, change, addr_start_index, addr_count, base_bip32_path)

    def list_account_xpub_addresses(self, account_xpub: str, change: int, addr_start_index: int, addr_count: int,
                                    account_bip32_path: str = None):
        account_key = BIP32Key.fromExtendedKey(account_xpub)
        change_key = account_key.ChildKey(change)
        change_xpub = change_key.ExtendedKey(False, True)
        bip32_path = bip32_path_n_to_string(bip32_path_string_to_n(account_bip32_path) + [change])
        return self.list_xpub_addresses(change_xpub, addr_start_index, addr_count, bip32_path,
                                        True if change == 1 else False)

    def list_xpub_addresses(self, xpub: str, addr_start_index: int, addr_count: int, bip32_path: str = None,
                            is_change_address: bool = False):
        tm_begin = time.time()
        try:
            xpub_db_id = self.get_xpub_db_addr(xpub, bip32_path, is_change_address).get('id')

            key = BIP32Key.fromExtendedKey(xpub)
            count = 0
            for idx in range(addr_start_index, addr_start_index + addr_count):
                db_id, address, _ = self.get_child_address(xpub_db_id, idx, key)
                count += 1
                yield (db_id, address)
        finally:
            diff = time.time() - tm_begin
            logging.info(f'list_account_addresses exec time: {diff}s, keys count: {count}')

    def read_account_txs(self, base_path: str):
        account_xpub = hw_intf.get_xpub(self.hw_session, base_path)
        return self.read_account_xpub_txs(account_xpub, base_path)

    def read_account_xpub_txs(self, account_xpub: str, base_bip32_path: str = None):
        tm_begin = time.time()

        account_key = BIP32Key.fromExtendedKey(account_xpub)
        for change in (0, 1):
            key = account_key.ChildKey(change)
            xpub = key.ExtendedKey(False, True)
            bip32_path = bip32_path_n_to_string(bip32_path_string_to_n(base_bip32_path) + [change])

            self.read_xpub_txs(xpub, bip32_path, True if change == 1 else False)

        logging.info(f'read_account_xpub_txs exec time: {time.time() - tm_begin}s')

    def read_xpub_txs(self, xpub: str, bip32_path: str = None, is_change_address: bool = False):
        # addresses whose balances have been changed during this processing
        addr_bal_updated: Dict[int, bool] = {}

        # new transactions or transactions whose utxos have been spent during this processing:
        txs_updated: Dict[int, bool] = {}

        def process_addrs_transactions(addr_db_ids: Dict[str, int]):
            txids = self.dashd_intf.getaddresstxids({'addresses': list(addr_db_ids.keys()),
                                                     'start': last_scan_block_height})
            if txids:
                db_cursor = self.db_intf.get_cursor()
                try:
                    for tx_entry in txids:
                        address = tx_entry.get('address')
                        addr_db_id = addr_db_ids.get(address)
                        self.process_tx_entry(tx_entry, addr_db_id, address, db_cursor, addr_bal_updated, txs_updated)
                finally:
                    if db_cursor.connection.total_changes > 0:
                        self.db_intf.commit()
                    self.db_intf.release_cursor()

        account_addr = self.get_xpub_db_addr(xpub, bip32_path, is_change_address)
        last_scan_block_height = account_addr.get('last_scan_block_height')
        if last_scan_block_height is None:
            last_scan_block_height = 0

        addr_id_map = {}
        addr_ids = []
        empty_addresses = 0
        for address_db_id, address in self.list_xpub_addresses(xpub, 0, MAX_ADDRESSES_TO_SCAN, bip32_path,
                                                               is_change_address):
            addr_id_map[address] = address_db_id
            addr_ids.append(address_db_id)

            if len(addr_id_map) >= TX_QUERY_ADDR_CHUNK_SIZE:

                process_addrs_transactions(addr_id_map)
                addr_id_map.clear()

                # count the number of addresses with no associated transactions starting from the end
                _empty_addresses = 0
                db_cursor = self.db_intf.get_cursor()
                try:
                    for a_id in reversed(addr_ids):
                        # check if there was no transactions for the address
                        if not addr_bal_updated.get(a_id):
                            db_cursor.execute('select 1 from tx_output where address_id=?', (a_id,))
                            if db_cursor.fetchone():
                                break
                        else:
                            break
                        _empty_addresses += 1
                finally:
                    self.db_intf.release_cursor()

                if _empty_addresses < TX_QUERY_ADDR_CHUNK_SIZE:
                    empty_addresses = _empty_addresses
                else:
                    empty_addresses += _empty_addresses

                addr_ids.clear()

                if empty_addresses >= ADDRESS_STOP_GAP_SIZE:
                    break

        if len(addr_id_map):
            process_addrs_transactions(addr_id_map)

    def process_tx_entry(self, tx_entry: Dict, addr_db_id: int, address: str, db_cursor,
                         addr_bal_updated: Dict[int, bool], txs_updated: Dict[int, bool]):

        tx_id, tx_json = self.get_tx_db_id(tx_entry.get('txid'), db_cursor)
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
                txs_updated[tx_id] = True
                addr_bal_updated[addr_db_id] = True
            else:
                if addr_db_id != row[1]:
                    db_cursor.execute('update tx_output set address_id=? where id=?', (addr_db_id, row[0]))
                    txs_updated[tx_id] = True
                    addr_bal_updated[addr_db_id] = True
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
                txs_updated[tx_id] = True
                addr_bal_updated[addr_db_id] = True

            tx_vin = tx_json.get('vin')
            if tx_index < len(tx_vin):
                related_tx_vin = tx_vin[tx_index]
                related_txid = related_tx_vin.get('txid')
                related_tx_index = related_tx_vin.get('vout')
                related_tx_db_id, _ = self.get_tx_db_id(related_txid, db_cursor)

                # related transaction should already be in the database cache
                db_cursor.execute('select id, spent_tx_id, spent_input_index from tx_output where tx_id=? '
                                  'and output_index=?', (related_tx_db_id, related_tx_index))
                row = db_cursor.fetchone()
                if row:
                    if row[1] != tx_id or row[2] != tx_index:
                        db_cursor.execute('update tx_output set spent_tx_id=?, spent_input_index=? where id=?',
                                          (tx_id, tx_index, row[0]))
                        txs_updated[related_tx_db_id] = True
                        addr_bal_updated[addr_db_id] = True
                else:
                    logging.warning(f'Could not find the related transaction for this tx entry. Txid: {related_txid}, '
                                    f'index: {tx_index}')
            else:
                logging.warning('Could not find vin of the related transaction for this transaction entry. '
                                f'Txid: {tx_id}, index: {tx_index}.')

    def get_tx_db_id(self, txid: str, db_cursor) -> Tuple[int, Optional[Dict]]:
        """
        :param tx_entry:
        :param db_cursor:
        :return: Tuple[int <transaction db id>, Optional[Dict <transaction details json>]]
        """
        tx_json = None
        # tx_hash = base64.b64encode(bytes.fromhex(txid))  # base64 format takes less space in db than hex string
        tx_hash = txid # todo: save txid instead of hash to simplify testing

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
