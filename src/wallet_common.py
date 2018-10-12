#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-09
import bisect
from typing import Optional, List, Callable, Tuple
from common import AttrsProtected


class UtxoType(AttrsProtected):
    def __init__(self):
        super(UtxoType, self).__init__()
        self.id = None
        self.address: str = None
        self.address_id: int = None
        self.txid = None
        self.output_index = None
        self.satoshis = None
        self.block_height = None
        self.bip32_path = None
        self.time_stamp = 0  # block timestamp
        self.time_str = None
        self.is_collateral = False
        self.coinbase = False
        self.masternode = None
        self.get_cur_block_height_fun: Callable[[], int] = None
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


class TxOutputType(AttrsProtected):
    def __init__(self):
        super(TxOutputType, self).__init__()
        self.__address: str = ''
        self.satoshis: int = None
        self.__bip32_path: str = None  # required only for change output
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


class AddressType(AttrsProtected):
    def __init__(self):
        super(AddressType, self).__init__()
        self.id = None
        self.xpub_hash = None
        self.parent_id = None
        self.address_index: Optional[int] = None
        self.address = None
        self.path: str = None
        self.tree_id = None
        self.balance = None
        self.received = None
        self.is_change = None
        self.last_scan_block_height = None
        self.bip44_account = None
        self.set_attr_protection()

    def update_from(self, src_addr: 'AddressType') -> bool:
        """
        Update fields used in UI which can change after fetching transactions.
        :param src_addr: The source address.
        :return: True if any of the fields had different value before and was updated.
        """
        if self != src_addr:
            if self.balance != src_addr.balance or \
               self.received != src_addr.received:
                self.balance = src_addr.balance
                self.received = src_addr.received
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

    def __gt__(self, other: 'AddressType'):
        if self.is_change == other.is_change:
            gt = self.address_index > other.address_index
        else:
            gt = self.is_change > other.is_change
        return gt

    def __ge__(self, other: 'AddressType'):
        if self.is_change == other.is_change:
            ge = self.address_index >= other.address_index
        else:
            ge = self.is_change > other.is_change
        return ge

    def __lt__(self, other: 'AddressType'):
        if self.is_change == other.is_change:
            lt = self.address_index < other.address_index
        else:
            lt = self.is_change < other.is_change
        return lt

    def __le__(self, other: 'AddressType'):
        if self.is_change == other.is_change:
            le = self.address_index <= other.address_index
        else:
            le = self.is_change < other.is_change
        return le


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
        if self.address_index is not None and self.address_index >= 0x80000000:
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

    def update_from(self, src_account: 'Bip44AccountType') -> bool:
        """
        Updates the account atttributes which can be changed by fetching new transactions process.
        :param src_account:
        :return: True if any of the attributes have been updated.
        """
        if src_account.balance != self.balance or src_account.received != self.received or \
            src_account.name != self.name:
            self.balance = src_account.balance
            self.received = src_account.received
            self.name = src_account.name
            return True
        return False

    def update_from_args(self, balance: int, received: int, name: str) -> bool:
        """
        Updates the account atttributes which can be changed by fetching new transactions process.
        :param src_account:
        :return: True if any of the attributes have been updated.
        """
        if balance != self.balance or received != self.received or name != self.name:
            self.balance = balance
            self.received = received
            self.name = name
            return True
        return False

    def add_address(self, address: AddressType) -> Tuple[bool, bool, int, AddressType]:
        """
        :param address:
        :return:
            [0]: True if this is a new address - not existed before in self.addresses
            [1]: True if the address attributes has been updated within this call
            [2]: Address index within the internal list
            [3]: The AddressType ref (for an existing address it's a ref to an existing object, not
                the one passed as an argument)
        """
        is_new = False
        updated = False
        address.bip44_account = self
        if not address.path:
            if self.bip32_path and address.address_index is not None:
                if address.is_change:
                    change = 1
                else:
                    change = 0
                address.path = f"{self.bip32_path}/{change}/{address.address_index}"

        addr_index = self.address_index_by_id(address.id)
        if addr_index is None:
            addr_index = self.get_address_insert_index(address)
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


