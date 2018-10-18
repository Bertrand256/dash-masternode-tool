#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-09
import bisect
import hashlib
import logging
from PyQt5.QtCore import Qt, QVariant, QModelIndex, QAbstractItemModel
from PyQt5.QtGui import QColor, QFont
from more_itertools import consecutive_groups
from typing import Optional, List, Tuple, Dict
import app_utils
import thread_utils
from app_config import MasternodeConfig
from app_defs import DEBUG_MODE
from bip44_wallet import Bip44Wallet
from ext_item_model import TableModelColumn, ExtSortFilterTableModel
from wallet_common import Bip44AccountType, Bip44AddressType, UtxoType


log = logging.getLogger('dmt.wallet_dlg')


class MnAddressItem(object):
    def __init__(self):
        self.masternode: MasternodeConfig = None
        self.address: Bip44AddressType = None


class MnAddressTableModel(ExtSortFilterTableModel):
    def __init__(self, parent, masternode_list: List[MasternodeConfig], bip44_wallet: Bip44Wallet):
        ExtSortFilterTableModel.__init__(self, parent, [
            TableModelColumn('description', 'Description', True, 100)
        ], False, False)
        self.mn_items: List[MnAddressItem] = []
        for mn in masternode_list:
            mni = MnAddressItem()
            mni.masternode = mn
            if mni.masternode.collateralAddress:
                a = bip44_wallet.get_address_item(mni.masternode.collateralAddress, True)
                mni.address = a
                self.mn_items.append(mni)

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.mn_items)

    def data_by_row_index(self, row_index):
        return self.mn_items[row_index]

    def data(self, index, role=None):
        if index.isValid():
            col_idx = index.column()
            row_idx = index.row()
            if row_idx < len(self.mn_items):
                if role in (Qt.DisplayRole, Qt.EditRole):
                    col = self.col_by_index(col_idx)
                    if col:
                        field_name = col.name
                        if field_name == 'description':
                            return self.mn_items[row_idx]
        return QVariant()

    def get_mn_by_addr_hash(self, addr_hash) -> Optional[MnAddressItem]:
        for idx, mni in enumerate(self.mn_items):
            if mni.address.address:
                h = hashlib.sha256(bytes(mni.address.address, 'utf-8')).hexdigest()
                if h == addr_hash:
                    return mni
        return None

    def get_mn_index(self, mn_item: MnAddressItem) -> Optional[int]:
        if mn_item in self.mn_items:
            return self.mn_items.index(mn_item)
        return None

    def get_mn_index_by_addr(self, address: Bip44AddressType) -> Optional[int]:
        for idx, mni in enumerate(self.mn_items):
            if mni.address.id == address.id:
                return idx
        return None

    def address_data_changed(self, address: Bip44AddressType):
        idx = self.get_mn_index_by_addr(address)
        if idx is not None:
            self.mn_items[idx].address.update_from(address)
            index = self.index(idx, 0)
            self.dataChanged.emit(index, index)


class UtxoTableModel(ExtSortFilterTableModel):
    def __init__(self, parent, masternode_list: List[MasternodeConfig]):
        ExtSortFilterTableModel.__init__(self, parent, [
            TableModelColumn('satoshis', 'Amount (Dash)', True, 100),
            TableModelColumn('confirmations', 'Confirmations', True, 100),
            TableModelColumn('bip32_path', 'Path', True, 100),
            TableModelColumn('time_str', 'TX Date/Time', True, 140),
            TableModelColumn('address', 'Address', True, 140),
            TableModelColumn('masternode', 'Masternode', False, 40),
            TableModelColumn('txid', 'TX ID', True, 220),
            TableModelColumn('output_index', 'TX Idx', True, 40)
        ], True, True)
        if DEBUG_MODE:
            self.insert_column(len(self._columns), TableModelColumn('id', 'DB id', True, 40))
        # self.sorting_column_name = 'confirmations'
        # self.sorting_order = Qt.AscendingOrder
        self.hide_collateral_utxos = True
        self.utxos: List[UtxoType] = []
        self.utxo_by_id: Dict[int, UtxoType] = {}
        self.block_height = None

        self.mn_by_collateral_tx: Dict[str, MasternodeConfig] = {}
        self.mn_by_collateral_address: Dict[str, MasternodeConfig] = {}

        for mn in masternode_list:
            ident = mn.collateralTx + '-' + str(mn.collateralTxIndex)
            self.mn_by_collateral_tx[ident] = mn
            self.mn_by_collateral_address[mn.collateralAddress] = mn

        self.set_attr_protection()

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.utxos)

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def data(self, index, role=None):
        if index.isValid():
            col_idx = index.column()
            row_idx = index.row()
            if row_idx < len(self.utxos):
                utxo = self.utxos[row_idx]
                if utxo:
                    if role in (Qt.DisplayRole, Qt.EditRole):
                        col = self.col_by_index(col_idx)
                        if col:
                            field_name = col.name
                            if field_name == 'satoshis':
                                return app_utils.to_string(round(utxo.satoshis / 1e8, 8))
                            elif field_name == 'masternode':
                                if utxo.masternode:
                                    return utxo.masternode.name
                            elif field_name == 'confirmations':
                                if utxo.confirmations == 0:
                                    return 'Unconfirmed'
                                else:
                                    return app_utils.to_string(utxo.__getattribute__(field_name))
                            else:
                                return app_utils.to_string(utxo.__getattribute__(field_name))
                    elif role == Qt.ForegroundRole:
                        if utxo.is_collateral:
                            return QColor(Qt.red)
                        elif utxo.coinbase_locked:
                            if col_idx == 1:
                                return QColor('red')
                            else:
                                return QColor('gray')

                    elif role == Qt.BackgroundRole:
                        if utxo.coinbase_locked:
                            return QColor('lightgray')

                    elif role == Qt.TextAlignmentRole:
                        col = self.col_by_index(col_idx)
                        if col:
                            if col.name in ('satoshis', 'confirmations', 'output_index'):
                                return Qt.AlignRight

        return QVariant()

    def add_utxo(self, utxo: UtxoType, insert_pos = None):
        if not utxo.id in self.utxo_by_id:
            if insert_pos is None:
                self.utxos.append(utxo)
            else:
                self.utxos.insert(insert_pos, utxo)
            self.utxo_by_id[utxo.id] = utxo
            ident = utxo.txid + '-' + str(utxo.output_index)
            if ident in self.mn_by_collateral_tx:
                utxo.is_collateral = True
            mn = self.mn_by_collateral_address.get(utxo.address, None)
            if mn:
                utxo.masternode = mn

    def clear_utxos(self):
        self.utxos.clear()
        self.utxo_by_id.clear()

    def update_utxos(self, utxos_to_add: List[UtxoType], utxos_to_delete: List[Tuple[int, int]]):
        if utxos_to_delete:
            row_indexes_to_remove = []
            for utxo_id in utxos_to_delete:
                utxo = self.utxo_by_id.get(utxo_id)
                if utxo:
                    utxo_index = self.utxos.index(utxo)
                    if utxo_index not in row_indexes_to_remove:
                        row_indexes_to_remove.append(utxo_index)
                    del self.utxo_by_id[utxo_id]
            row_indexes_to_remove.sort(reverse=True)

            for group in consecutive_groups(row_indexes_to_remove, ordering=lambda x: -x):
                l = list(group)
                self.beginRemoveRows(QModelIndex(), l[-1], l[0]) # items are sorted in reversed order
                del self.utxos[l[-1]: l[0]+1]
                self.endRemoveRows()

        if utxos_to_add:
            # in the model, the rows are sorted by the number of confirmations in the descending order, so put
            # the new ones in the right place
            utxos_to_add.sort(key=lambda x: x.block_height, reverse=True)
            row_idx = 0
            self.beginInsertRows(QModelIndex(), row_idx, row_idx + len(utxos_to_add) - 1)
            try:
                for index, utxo in enumerate(utxos_to_add):
                    self.add_utxo(utxo, index)
            finally:
                self.endInsertRows()

    def lessThan(self, col_index, left_row_index, right_row_index):
        col = self.col_by_index(col_index)
        if col:
            col_name = col.name
            reverse = False
            if col_name == 'time_str':
                col_name = 'confirmations'
                reverse = True

            if 0 <= left_row_index < len(self.utxos) and \
               0 <= right_row_index < len(self.utxos):
                left_utxo = self.utxos[left_row_index]
                right_prop = self.utxos[right_row_index]
                left_value = left_utxo.__getattribute__(col_name)
                right_value = right_prop.__getattribute__(col_name)
                if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
                    if not reverse:
                        return left_value < right_value
                    else:
                        return right_value < left_value
                elif isinstance(left_value, str) and isinstance(right_value, str):
                    left_value = left_value.lower()
                    right_value = right_value.lower()
                    if not reverse:
                        return left_value < right_value
                    else:
                        return right_value < left_value
        return False

    def filterAcceptsRow(self, source_row):
        will_show = True
        if 0 <= source_row < len(self.utxos):
            if self.hide_collateral_utxos:
                utxo = self.utxos[source_row]
                if utxo.is_collateral:
                    will_show = False
        return will_show

    def set_hide_collateral_utxos(self, hide):
        self.hide_collateral_utxos = hide
        self.proxy_model.invalidateFilter()

    def set_block_height(self, block_height: int):
        if block_height != self.block_height:
            log.debug('Block height updated to %s', block_height)
            self.block_height = block_height
            # if self.utxos:
            #     tl_index = self.index(0, self.col_index_by_name('confirmations'))
            #     br_index = self.index(len(self.utxos) - 1, self.col_index_by_name('confirmations'))
            #     self.view.dataChanged(tl_index, br_index, [Qt.DisplayRole, Qt.ForegroundRole, Qt.BackgroundColorRole])


class AccountListModel(QAbstractItemModel):
    def __init__(self, parent):
        QAbstractItemModel.__init__(self, parent)
        self.accounts: List[Bip44AccountType] = []
        self.data_lock = thread_utils.EnhRLock()

    def acquire_lock(self):
        self.data_lock.acquire()

    def release_lock(self):
        self.data_lock.release()

    def __enter__(self):
        self.acquire_lock()

    def __exit__(self, type, value, traceback):
        self.release_lock()

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def headerData(self, section, orientation, role=None):
        if role != 0:
            return QVariant()
        if orientation == 0x1:
            if section == 0:
                return ''
            elif section == 1:
                return 'Balance'
            elif section == 2:
                return 'Received'
        return ''

    def parent(self, index=None):
        try:
            if not index or not index.isValid():
                return QModelIndex()
            node = index.internalPointer()
            if isinstance(node, Bip44AccountType):
                return QModelIndex()
            else:
                acc_idx = self.accounts.index(node.bip44_account)
                return self.createIndex(acc_idx, 0, node.bip44_account)
        except Exception as e:
            log.exception('Exception while getting parent of index')
            raise

    def index(self, row, column, parent=None, *args, **kwargs):
        try:
            if not parent or not parent.isValid():
                if 0 <= row < len(self.accounts):
                    return self.createIndex(row, column, self.accounts[row])
                else:
                    return QModelIndex()
            parentNode = parent.internalPointer()
            if isinstance(parentNode, Bip44AccountType):
                addr = parentNode.address_by_index(row)
                if addr:
                    return self.createIndex(row, column, addr)
            return QModelIndex()
        except Exception as e:
            log.exception('Exception while creating index')
            raise

    def columnCount(self, parent=None, *args, **kwargs):
        return 1

    def rowCount(self, parent=None, *args, **kwargs):
        if not parent or not parent.isValid():
            return len(self.accounts)
        node = parent.internalPointer()
        if isinstance(node, Bip44AccountType):
            return len(node.addresses)
        else:
            return 0

    def data(self, index, role=None):
        if index.isValid():
            data = index.internalPointer()
            col = index.column()
            if data:
                if role in (Qt.DisplayRole, Qt.EditRole):
                    if col == 0:
                        # if isinstance(data, Bip44AccountType):
                        #     return data.get_account_name()
                        # else:
                        #     return f'/{data.address_index}: {data.address}'
                        return data
                    elif col == 1:
                        b = data.balance
                        if b:
                            b = b/1e8
                        return b
                    elif col == 2:
                        b = data.received
                        if b:
                            b = b/1e8
                        return b
        return QVariant()

    def removeRows(self, row, count, parent=None, *args, **kwargs):
        if parent is None or not parent.isValid():
            if row >=0 and row < len(self.accounts):
                self.beginRemoveRows(parent, row, row + count)
                for row_offs in range(count):
                    del self.accounts[row - row_offs]
                self.endRemoveRows()
            return True
        else:
            acc = parent.internalPointer()
            removed = False
            if acc:
                self.beginRemoveRows(parent, row, row + count)
                for row_offs in range(count):
                    removed = max(removed, acc.remove_address_by_index(row - row_offs))
                self.endRemoveRows()
            return removed

    def account_by_id(self, id: int) -> Optional[Bip44AccountType]:
        for a in self.accounts:
            if a.id == id:
                return a
        return None

    def account_index_by_id(self, id: int) -> Optional[int]:
        for idx, a in enumerate(self.accounts):
            if a.id == id:
                return idx
        return None

    def add_account(self, account: Bip44AccountType):
        existing_account = self.account_by_id(account.id)
        if not existing_account:
            idxs = [a.address_index for a in self.accounts]
            insert_idx = bisect.bisect_right(idxs, account.address_index)
            self.beginInsertRows(QModelIndex(), insert_idx, insert_idx)
            self.accounts.insert(insert_idx, account)
            self.endInsertRows()
            self.modified = True
        else:
            if existing_account.update_from(account):
                self.modified = True

    def add_account_address(self, account: Bip44AccountType, address: Bip44AddressType):
        account_idx = self.account_index_by_id(account.id)
        if account_idx is not None:
            account = self.accounts[account_idx]
            acc_index = self.index(account_idx, 0)
            addr_idx = account.address_index_by_id(address.id)
            if addr_idx is None:
                addr_idx = account.get_address_insert_index(address)
                addr_exists = False
            else:
                addr_exists = True
            self.beginInsertRows(acc_index, addr_idx, addr_idx)
            if not addr_exists:
                self.accounts.insert(addr_idx, account)
            self.endInsertRows()

    def account_data_changed(self, account: Bip44AccountType):
        idx = self.account_index_by_id(account.id)
        if idx is not None:
            index = self.index(idx, 0)
            self.dataChanged.emit(index, index)

    def address_data_changed(self, account: Bip44AccountType, address: Bip44AddressType):
        account_idx = self.account_index_by_id(account.id)
        if account_idx is not None:
            account = self.accounts[account_idx]
            acc_index = self.index(account_idx, 0)
            addr_idx = account.address_index_by_id(address.id)
            if addr_idx is not None:
                addr = account.address_by_index(addr_idx)
                if addr != address:
                    addr.update_from(address)
                addr_index = self.index(addr_idx, 0, parent=acc_index)
                self.dataChanged.emit(addr_index, addr_index)

    def clear_accounts(self):
        self.accounts.clear()

    def sort_accounts(self):
        try:
            self.accounts.sort(key=lambda x: x.address_index)
        except Exception as e:
            pass


