#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-09
import base64
import bisect
import bitcoin
from bip32utils import BIP32Key, Base58
from typing import Optional, List, Callable, Tuple, Dict, ByteString, Union

import base58
from common import AttrsProtected
from dash_utils import bip32_path_string_to_n, bip32_path_n_to_string, pubkey_to_address


def xpub_to_hash(xpub: str):
    xpub_raw = Base58.check_decode(xpub)
    if xpub_raw[0:4] in (b'\x02\xfe\x52\xcc', b'\x04\x88\xb2\x1e'):  # remove xpub prefix
        xpub_raw = xpub_raw[4:]
    xpub_hash = bitcoin.bin_sha256(xpub_raw)
    xpub_hash = base64.b64encode(xpub_hash)
    return xpub_hash


def address_to_hash(address):
    abin = base58.b58decode(address)
    hash = bitcoin.bin_sha256(abin)
    hash = base64.b64encode(hash)
    return hash.decode('ascii')


class CacheInconsistencyException(Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, *kwargs)


class TxType(AttrsProtected):
    def __init__(self):
        super(TxType, self).__init__()
        self.id = None
        self.is_coinbase = False
        self.sender_addrs: List[Union[Bip44AddressType, str]] = []
        self.recipient_addrs: List[Union[Bip44AddressType, str]] = []
        # self.rcp_address: Optional[Bip44AddressType] = None  # != None if recipient is our own address
        # self.rcp_address_str: str = None
        self.direction: Optional[int] = None  # 1: incoming, -1: outgoing
        self.satoshis: int = 0
        self.tx_hash: str = ''
        self.block_height: int = 0
        self.block_timestamp: int = 0
        self.block_time_str: Optional[str] = None
        self.label: str = ''
        self.set_attr_protection()


class UtxoType(AttrsProtected):
    def __init__(self):
        super(UtxoType, self).__init__()
        self.id = None
        # self.address: str = None
        # self.address_id: int = None
        self.address_obj: Optional['Bip44AddressType'] = None
        self.txid = None
        self.output_index = None
        self.satoshis = None
        self.block_height = None
        # self.bip32_path = None
        self.time_stamp = 0  # block timestamp
        self.time_str = None
        self.is_collateral = False
        self.coinbase = False
        self.masternode = None
        self.get_cur_block_height_fun: Optional[Callable[[], int]] = None
        self.set_attr_protection()

    @property
    def confirmations(self):
        if self.get_cur_block_height_fun:
            if not self.block_height:
                return 0
            return self.get_cur_block_height_fun() - self.block_height + 1
        else:
            return None

    @property
    def coinbase_locked(self):
        return True if self.coinbase and self.confirmations < 100 else False

    @property
    def bip32_path(self):
        if self.address_obj:
            return self.address_obj.bip32_path
        return None

    @property
    def address(self):
        if self.address_obj:
            return self.address_obj.address
        return None

    @property
    def address_id(self):
        if self.address_obj:
            return self.address_obj.id
        return None


class TxOutputType(AttrsProtected):
    def __init__(self):
        super(TxOutputType, self).__init__()
        self.__address: str = ''
        self.address_ref: Optional[Bip44AddressType] = None  # not null if the recipient of the output is the user's own address
        self.satoshis: Optional[int] = None
        self.__bip32_path: Optional[str] = None  # required only for change output
        self.is_change = False
        self.set_attr_protection()

    @property
    def address(self):
        return self.__address

    @address.setter
    def address(self, address: str):
        self.__address = address.strip()

    @property
    def bip32_path(self):
        return self.__bip32_path

    @bip32_path.setter
    def bip32_path(self, bip32_path: str):
        self.__bip32_path = bip32_path.strip()


class Bip44Entry(object):
    def __init__(self,
                 tree_id: Optional[int],
                 id: Optional[int],
                 parent: Optional['Bip44Entry'] = None,
                 xpub: Optional[str] = None,
                 address_index: Optional[int] = None,
                 bip32_path: Optional[str] = None,
                 bip32_key: Optional[BIP32Key] = None):
        self.tree_id: int = tree_id
        self.id: Optional[int] = id
        self.xpub: str = xpub
        self.address: Optional[str] = None
        self.label: Optional[str] = None
        self.__bip32_path: Optional[str] = ''
        self.set_bip32_path(bip32_path)
        self.address_index: Optional[int] = address_index
        self.__bip32_key: BIP32Key = bip32_key
        self.__parent: Optional['Bip44Entry'] = parent
        self.__xpub_hash: Optional[str] = None
        self.__parent_id: Optional[int] = None
        self.child_entries: Dict[int, 'Bip44Entry'] = {}
        self.db_fields = ['address_index', 'path', 'xpub_hash', 'tree_id', 'parent_id', 'address', 'label']

    def get_hardened_index(self):
        if self.address_index is not None and self.address_index >= 0x80000000:
            return self.address_index - 0x80000000
        else:
            return None

    def copy_from(self, src_entry: 'Bip44Entry'):
        self.tree_id = src_entry.tree_id
        self.id = src_entry.id
        self.xpub = src_entry.xpub
        self.address = src_entry.address
        self.label = src_entry.label
        self.__bip32_path = src_entry.__bip32_path
        self.address_index = src_entry.address_index
        self.__xpub_hash = src_entry.__xpub_hash

    def set_bip32_path(self, path):
        self.__bip32_path = path

    @property
    def bip32_path(self):
        return self.__bip32_path

    @bip32_path.setter
    def bip32_path(self, path):
        self.set_bip32_path(path)

    def get_bip32key(self) -> BIP32Key:
        if not self.__bip32_key:
            if not self.xpub:
                raise Exception('XPUB not set')
            self.__bip32_key = BIP32Key.fromExtendedKey(self.xpub)
        return self.__bip32_key

    def get_child_entry(self, index) -> 'Bip44Entry':
        child = self.child_entries.get(index)
        if not child:
            key = self.get_bip32key()
            child_key = key.ChildKey(index)
            child_xpub = child_key.ExtendedKey(False, True)
            if self.bip32_path:
                bip32_path_n = bip32_path_string_to_n(self.bip32_path)
                bip32_path_n.append(index)
                bip32_path = bip32_path_n_to_string(bip32_path_n)
            else:
                raise Exception('Unknown BIP32 path of the parrent')

            child = Bip44Entry(tree_id=self.tree_id, id=None, parent=self, xpub=child_xpub, address_index=index,
                               bip32_path=bip32_path, bip32_key=child_key)
            self.child_entries[index] = child
        return child

    def evaluate_address_if_null(self, db_cursor, dash_network: str):
        if not self.address and self.xpub:
            key = self.get_bip32key()
            self.address = pubkey_to_address(key.PublicKey().hex(), dash_network)
            if self.id:
                db_cursor.execute('update address set address=? where id=?', (self.address, self.id))

    def read_from_db(self, db_cursor, create=False):
        if self.id:
            db_cursor.execute('select ' + ','.join(self.db_fields) + ',id from address where id=?', (self.id,))
        elif self.xpub:
            xpub_hash = xpub_to_hash(self.xpub)
            db_cursor.execute('select ' + ','.join(self.db_fields) + ',id from address where xpub_hash=? and tree_id=?',
                              (xpub_hash, self.tree_id))
        else:
            raise Exception('Cannot read from db: both id and xpub_hash are null')
        row = db_cursor.fetchone()
        if row:
            for idx, f in enumerate(self.db_fields):
                if f in ('address_index', 'balance', 'received', 'tree_id', 'address', 'label', 'status'):
                    if row[idx] is not None:
                        self.__setattr__(f, row[idx])
                elif f == 'path':
                    if row[idx]:
                        self.bip32_path = row[idx]
                elif f == 'xpub_hash':
                    self.__xpub_hash = row[idx]
                elif f == 'parent_id':
                    self.__parent_id = row[idx]
                else:
                    raise Exception('Unknown field name')
            if not self.id:
                self.id = row[len(self.db_fields)]  # id is an additional field read from db when using xpub_hash as a
                                                    # key
            if self.__parent and (not self.__parent_id or self.__parent.id != self.__parent_id):
                if self.__parent_id:
                    raise CacheInconsistencyException()

                self.__parent_id = self.__parent.id
                # corrent parent_id in the database
                db_cursor.execute('update address set parent_id=? where id=?', (self.__parent.id, self.id))

        elif create:
            self.create_in_db(db_cursor)

    def create_in_db(self, db_cursor):
        values = []

        if not self.label and self.address:
            # trye to retriev label of the address, stored in a dedicated database
            h = address_to_hash(self.address)
            db_cursor.execute('select label from labels.address_label where key=?', (h,))
            row = db_cursor.fetchone()
            if row:
                self.label = row[0]

        for idx, f in enumerate(self.db_fields):
            if f in ('address_index', 'balance', 'received', 'tree_id', 'address', 'label', 'status'):
                values.append(self.__getattribute__(f))
            elif f == 'path':
                values.append(self.bip32_path)
            elif f == 'xpub_hash':
                if self.xpub:
                    xh = xpub_to_hash(self.xpub)
                else:
                    xh = None
                values.append(xh)
            elif f == 'parent_id':
                if self.__parent_id:
                    values.append(self.__parent_id)
                elif self.__parent and self.__parent.id:
                    values.append(self.__parent.id)
                else:
                    values.append(None)
            else:
                raise Exception('Unknown field name')

        db_cursor.execute('insert into address(' + ','.join(self.db_fields) + ') values(' +
                          ','.join(['?'] * len(self.db_fields)) + ')', values)
        self.id = db_cursor.lastrowid


class Bip44AddressType(AttrsProtected, Bip44Entry):
    def __init__(self, tree_id: Optional[int]):
        AttrsProtected.__init__(self)
        Bip44Entry.__init__(self, tree_id=tree_id, id=None, parent=None)
        self.balance = 0
        self.received = 0
        self.name = ''
        self.last_scan_block_height = None
        self.db_fields.extend(('balance', 'received'))
        self.bip44_account = None
        self.__is_change = False

        # timestamp of the last db-network balance consictency check
        self.last_balance_verify_ts = 0

        self.set_attr_protection()

    def set_bip32_path(self, path):
        Bip44Entry.set_bip32_path(self, path)
        if path:
            path_n = bip32_path_string_to_n(path)
            if path_n[-2] == 1:
                self.__is_change = True
            else:
                self.__is_change = False

    def copy_from(self, src_entry: 'Bip44AddressType'):
        Bip44Entry.copy_from(self, src_entry)
        self.balance = src_entry.balance
        self.received = src_entry.received
        self.name = src_entry.name
        self.last_scan_block_height = src_entry.last_scan_block_height
        self.__is_change = src_entry.__is_change

    def update_from(self, src_addr: 'Bip44AddressType') -> bool:
        """
        Update fields which can change after fetching transactions.
        :param src_addr: The source address.
        :return: True if any of the fields had different value before and was updated.
        """
        if self != src_addr:
            if self.balance != src_addr.balance or self.received != src_addr.received or \
               self.last_scan_block_height != src_addr.last_scan_block_height:

                self.balance = src_addr.balance
                self.received = src_addr.received
                self.last_scan_block_height = src_addr.last_scan_block_height
                return True
        return False

    def update_from_args(self, balance, received) -> bool:
        """
        Update fields used in UI which can change after fetching transactions.
        :param src_addr: The source address.
        :return: True if any of the fields had different value before and was updated.
        """
        if self.balance != balance or self.received != received:
            self.balance = balance
            self.received = received
            return True
        return False

    @property
    def is_change(self):
        return self.__is_change

    def __gt__(self, other: 'Bip44AddressType'):
        if self.is_change == other.is_change:
            gt = self.address_index > other.address_index
        else:
            gt = self.is_change > other.is_change
        return gt

    def __ge__(self, other: 'Bip44AddressType'):
        if self.is_change == other.is_change:
            ge = self.address_index >= other.address_index
        else:
            ge = self.is_change > other.is_change
        return ge

    def __lt__(self, other: 'Bip44AddressType'):
        if self.is_change == other.is_change:
            lt = self.address_index < other.address_index
        else:
            lt = self.is_change < other.is_change
        return lt

    def __le__(self, other: 'Bip44AddressType'):
        if self.is_change == other.is_change:
            le = self.address_index <= other.address_index
        else:
            le = self.is_change < other.is_change
        return le


class Bip44AccountType(AttrsProtected, Bip44Entry):
    def __init__(self,
                 tree_id: Optional[int],
                 id: Optional[int],
                 xpub: Optional[str],
                 address_index: Optional[int],
                 bip32_path: Optional[str]):
        AttrsProtected.__init__(self)
        Bip44Entry.__init__(self, tree_id=tree_id, id=id, parent=None, xpub=xpub, address_index=address_index,
                            bip32_path=bip32_path)
        self.balance: Optional[int] = 0
        self.received: Optional[int] = 0
        self.addresses: List[Bip44AddressType] = []
        self.status: int = 0  # 0: default, 1: force show (used when received = 0), 2: force hide (used when received > 0)
        self.view_fresh_addresses_count = 1  # how many unused addresses will be shown in GUI

        # timestamp of the last balance/received verification, based on the child addresses:
        self.last_verify_balance_ts = 0

        self.db_fields.extend(('balance', 'received', 'status'))
        self.set_attr_protection()

    def get_account_name(self):
        nr = self.get_hardened_index()
        if self.label:
            return self.label + ' (#' + str(nr + 1) + ')'
        else:
            if nr is not None:
                return f'Account #' + str(nr + 1)
            else:
                return f'Account *' + str(self.address_index)

    @property
    def status_force_show(self):
        return True if self.status == 1 else False

    @property
    def status_force_hide(self):
        return True if self.status == 2 else False

    def copy_from(self, src_entry: 'Bip44AccountType'):
        Bip44Entry.copy_from(self, src_entry)
        self.balance = src_entry.balance
        self.received = src_entry.received
        self.status = src_entry.status
        for a in src_entry.addresses:
            new_a = self.address_by_id(a.id)
            if not new_a:
                new_a = Bip44AddressType(None)
                new_a.copy_from(a)
                self.add_address(new_a)
            else:
                new_a.copy_from(a)

    def update_from(self, src_account: 'Bip44AccountType') -> bool:
        """
        Updates the account atttributes which can be changed by fetching new transactions process.
        :param src_account:
        :return: True if any of the attributes have been updated.
        """
        if src_account.balance != self.balance or src_account.received != self.received or \
            src_account.label != self.label or src_account.status != self.status:
            self.balance = src_account.balance
            self.received = src_account.received
            self.label = src_account.label
            self.status = src_account.status
            return True
        return False

    def update_from_args(self, balance: int, received: int, label: str, bip32_path: str) -> bool:
        """
        Updates the account atttributes which can be changed by fetching new transactions process.
        :param src_account:
        :return: True if any of the attributes have been updated.
        """
        if balance != self.balance or received != self.received:
            self.balance = balance
            self.received = received
            self.label = label
            return True

        if label != self.label and label:
            self.label = label
            return True

        if self.bip32_path != bip32_path and bip32_path:
            self.bip32_path = bip32_path
            return True
        return False

    def add_address(self, address: Bip44AddressType, insert_index: int = None) -> Tuple[bool, bool, int, Bip44AddressType]:
        """
        :param address:
        :return:
            [0]: True if this is a new address - not existed before in self.addresses
            [1]: True if the address attributes has been updated within this call
            [2]: Address index within the internal list
            [3]: The Bip44AddressType ref (for an existing address it's a ref to an existing object, not
                the one passed as an argument)
        """
        is_new = False
        updated = False
        address.bip44_account = self
        if not address.bip32_path:
            if self.bip32_path and address.address_index is not None:
                if address.is_change:
                    change = 1
                else:
                    change = 0
                address.bip32_path = f"{self.bip32_path}/{change}/{address.address_index}"

        addr_index = self.address_index_by_id(address.id)
        if addr_index is None:
            if not insert_index:
                addr_index = self.get_address_insert_index(address)
            else:
                addr_index = insert_index

            self.addresses.insert(addr_index, address)
            addr = address
            is_new = True
        else:
            addr = self.addresses[addr_index]
            updated = addr.update_from(address)
        return is_new, updated, addr_index, addr

    def get_address_insert_index(self, address) -> int:
        if self.addresses and address < self.addresses[-1]:
            addr_index = bisect.bisect_right(self.addresses, address)
        else:
            addr_index = len(self.addresses)
        return addr_index

    def address_by_index(self, index):
        if index >= 0 and index < len(self.addresses):
            return self.addresses[index]
        else:
            return None

    def address_by_id(self, id):
        for a in self.addresses:
            if a.id == id:
                return a
        return None

    def address_index_by_id(self, id):
        for idx, a in enumerate(self.addresses):
            if a.id == id:
                return idx
        return None

    def remove_address_by_id(self, id: int):
        index = self.address_index_by_id(id)
        if index is not None:
            del self.addresses[index]
            return True
        return False

    def remove_address_by_index(self, index: int):
        if 0 <= index < len(self.addresses):
            del self.addresses[index]
            return True
        return False


