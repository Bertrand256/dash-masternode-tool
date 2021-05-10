#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-09
import bisect
import datetime
import hashlib
import logging
from PyQt5.QtCore import Qt, QVariant, QModelIndex, QAbstractItemModel, QUrl
from PyQt5.QtGui import QColor, QFont, QDesktopServices
from PyQt5.QtWidgets import QTreeView, QTableView
from PyQt5 import QtGui
from more_itertools import consecutive_groups
from typing import Optional, List, Tuple, Dict
import app_utils
import thread_utils
import wnd_utils
from app_config import MasternodeConfig
from app_defs import DEBUG_MODE
from bip44_wallet import Bip44Wallet, UNCONFIRMED_TX_BLOCK_HEIGHT
from ext_item_model import TableModelColumn, ExtSortFilterTableModel
from wallet_common import Bip44AccountType, Bip44AddressType, UtxoType, TxType

log = logging.getLogger('dmt.wallet_dlg')

FILTER_OR = 0
FILTER_AND = 1
FILTER_OPER_GTEQ = 1
FILTER_OPER_LTEQ = 2
FILTER_OPER_EQ = 3


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
                self.mn_items.append(mni)
        self.load_mn_addresses_in_bip44_wallet(bip44_wallet)

    def load_mn_addresses_in_bip44_wallet(self, bip44_wallet: Bip44Wallet):
        addr_ids = []
        for mni in self.mn_items:
            if mni.masternode.collateralAddress:
                a = bip44_wallet.get_address_item(mni.masternode.collateralAddress, True)
                address_loc = Bip44AddressType(tree_id=None)
                address_loc.copy_from(a)
                if not address_loc.bip32_path:
                    address_loc.bip32_path = mni.masternode.collateralBip32Path
                    a.bip32_path = mni.masternode.collateralBip32Path
                mni.address = address_loc
                if mni.masternode.collateralAddress not in addr_ids:
                    addr_ids.append(mni.address.id)
        if addr_ids:
            bip44_wallet.subscribe_addresses_for_chbalance(addr_ids, True)

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

    def get_mn_by_addr(self, address: Bip44AddressType) -> Optional[MasternodeConfig]:
        for idx, mni in enumerate(self.mn_items):
            if mni.address.id == address.id:
                return mni.masternode
        return None

    def address_data_changed(self, address: Bip44AddressType):
        idx = self.get_mn_index_by_addr(address)
        if idx is not None:
            self.mn_items[idx].address.update_from(address)
            index = self.index(idx, 0)
            self.dataChanged.emit(index, index)


class AccountListModel(ExtSortFilterTableModel):
    def __init__(self, parent):
        ExtSortFilterTableModel.__init__(self, parent, [
            TableModelColumn('address', 'Address', True, 100)
        ], False, True)
        self.accounts: List[Bip44AccountType] = []
        self.__data_modified = False
        self.show_zero_balance_addresses = False
        self.show_not_used_addresses = False
        self.set_attr_protection()

    def reset_modified(self):
        self.__data_modified = False

    @property
    def data_modified(self):
        return self.__data_modified

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

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

    def rowCount(self, parent=None, *args, **kwargs):
        if not parent or not parent.isValid():
            ret = len(self.accounts)
        else:
            node = parent.internalPointer()
            if isinstance(node, Bip44AccountType):
                ret = len(node.addresses)
            else:
                ret = 0
        return ret

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

    def filterAcceptsRow(self, source_row, source_parent):
        def count_prev_zero_received(acc: Bip44AccountType, start_index: int):
            cnt = 0
            index = start_index
            while index >= 0:
                a = acc.address_by_index(index)
                if not a.received:
                    cnt += 1
                else:
                    break
                index -= 1
            return cnt

        try:
            will_show = True
            if source_parent.isValid():
                acc = source_parent.internalPointer()
                if isinstance(acc, Bip44AccountType):
                    addr = acc.address_by_index(source_row)
                    if addr:
                        if addr.received == 0:
                            will_show = False
                            if self.show_not_used_addresses:
                                will_show = True
                            else:
                                if not addr.is_change:
                                    prev_cnt = count_prev_zero_received(acc, source_row - 1)
                                    if prev_cnt < acc.view_fresh_addresses_count:
                                        will_show = True
                        elif addr.balance == 0:
                            will_show = self.show_zero_balance_addresses
            else:
                if source_row < len(self.accounts):
                    acc = self.accounts[source_row]
                    will_show = self.is_account_visible(acc)
                else:
                    will_show = False
        except Exception as e:
            log.exception('Exception occurred while filtering account/address')
            raise
        return will_show

    def is_account_visible(self, account: Bip44AccountType):
        if account.status_force_hide:
            return False
        if account.status_force_show or account.address_index == 0x80000000:
            return True
        if account.received > 0:
            return True
        else:
            return False

    def increase_account_fresh_addr_count(self, acc: Bip44AccountType, increase_count=1):
        acc.view_fresh_addresses_count += increase_count
        self.invalidateFilter()

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

    def account_by_bip44_index(self, bip44_index: int) -> Optional[Bip44AccountType]:
        for a in self.accounts:
            if a.address_index == bip44_index:
                return a
        return None

    def add_account(self, account: Bip44AccountType):
        existing_account = self.account_by_id(account.id)
        self.__data_modified = True
        if not existing_account:
            account_loc = Bip44AccountType(None, None, None, None, None)
            account_loc.copy_from(account)

            idxs = [a.address_index for a in self.accounts]
            insert_idx = bisect.bisect_right(idxs, account.address_index)
            self.beginInsertRows(QModelIndex(), insert_idx, insert_idx)
            self.accounts.insert(insert_idx, account_loc)
            self.endInsertRows()
        else:
            existing_account.copy_from(account)

    def add_account_address(self, account: Bip44AccountType, address: Bip44AddressType):
        account_idx = self.account_index_by_id(account.id)
        if account_idx is not None:
            account_loc = self.accounts[account_idx]
            acc_index = self.index(account_idx, 0)
            addr_idx = account_loc.address_index_by_id(address.id)
            if addr_idx is None:
                self.__data_modified = True
                addr_loc = Bip44AddressType(None)
                addr_loc.copy_from(address)
                addr_idx = account_loc.get_address_insert_index(addr_loc)
                self.beginInsertRows(acc_index, addr_idx, addr_idx)
                account_loc.add_address(addr_loc, addr_idx)
                self.endInsertRows()

    def account_data_changed(self, account: Bip44AccountType):
        account_idx = self.account_index_by_id(account.id)
        if account_idx is not None:
            account_loc = self.accounts[account_idx]
            if account != account_loc:
                account_loc.update_from(account)
                self.__data_modified = True
            index = self.index(account_idx, 0)
            self.dataChanged.emit(index, index)

    def address_data_changed(self, account: Bip44AccountType, address: Bip44AddressType):
        account_idx = self.account_index_by_id(account.id)
        if account_idx is not None:
            account = self.accounts[account_idx]
            acc_index = self.index(account_idx, 0)
            addr_idx = account.address_index_by_id(address.id)
            if addr_idx is not None:
                addr_loc = account.address_by_index(addr_idx)
                if addr_loc != address:
                    addr_loc.update_from(address)
                addr_index = self.index(addr_idx, 0, parent=acc_index)
                self.__data_modified = True
                self.dataChanged.emit(addr_index, addr_index)

    def remove_account(self, index):
        if 0 <= index < len(self.accounts):
            self.__data_modified = True
            self.beginRemoveRows(QModelIndex(), index, index)
            del self.accounts[index]
            self.endRemoveRows()

    def clear_accounts(self):
        log.debug('Clearing accounts')
        self.__data_modified = True
        self.accounts.clear()

    def get_first_unused_bip44_account_index(self):
        """ Get first unused not yet visible account index. """
        cur_index = 0x80000000
        for a in self.accounts:
            if a.address_index >= cur_index and not self.is_account_visible(a) and a.received == 0:
                return a.address_index
            else:
                cur_index = a.address_index
        return cur_index + 1


class UtxoTableModel(ExtSortFilterTableModel):
    def __init__(self, parent, masternode_list: List[MasternodeConfig], tx_explorer_url: str):
        ExtSortFilterTableModel.__init__(self, parent, [
            TableModelColumn('satoshis', 'Amount (FIRO)', True, 100),
            TableModelColumn('confirmations', 'Confirmations', True, 100),
            TableModelColumn('bip32_path', 'Path', True, 100),
            TableModelColumn('time_str', 'TX Date/Time', True, 140),
            TableModelColumn('address', 'Address', True, 140),
            TableModelColumn('masternode', 'Masternode', False, 40),
            TableModelColumn('txid', 'TX Hash', True, 220),
            TableModelColumn('output_index', 'TX Idx', True, 40)
        ], True, True)
        if DEBUG_MODE:
            self.insert_column(len(self._columns), TableModelColumn('id', 'DB id', True, 40))
        self.tx_explorer_url = tx_explorer_url
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

    def set_view(self, table_view: QTableView):
        super().set_view(table_view)
        link_delagate = wnd_utils.HyperlinkItemDelegate(table_view)
        link_delagate.linkActivated.connect(self.hyperlink_activated)
        table_view.setItemDelegateForColumn(self.col_index_by_name('txid'), link_delagate)

    def hyperlink_activated(self, link):
        QDesktopServices.openUrl(QUrl(link))

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
                                if utxo.block_height >= UNCONFIRMED_TX_BLOCK_HEIGHT:
                                    return 'Unconfirmed'
                                else:
                                    return app_utils.to_string(utxo.__getattribute__(field_name))
                            elif field_name == 'address':
                                if utxo.address_obj and utxo.address_obj.label:
                                    return utxo.address_obj.label
                                else:
                                    return utxo.address
                            elif col.name == 'txid':
                                if self.tx_explorer_url:
                                    url = self.tx_explorer_url.replace('%TXID%', utxo.txid)
                                    url = f'<a href="{url}">{utxo.txid}</a>'
                                    return url
                                else:
                                    return utxo.txid
                            else:
                                return app_utils.to_string(utxo.__getattribute__(field_name))
                    elif role == Qt.ForegroundRole:
                        if utxo.is_collateral:
                            return QColor(Qt.white)
                        elif utxo.coinbase_locked or utxo.block_height >= UNCONFIRMED_TX_BLOCK_HEIGHT:
                            return QColor('red')

                    elif role == Qt.BackgroundRole:
                        if utxo.is_collateral:
                            return QColor(Qt.red)

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

    def update_utxos(self, utxos_to_add: List[UtxoType], utxos_to_update: List[UtxoType], utxos_to_delete: List[Tuple[int, int]]):
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

            # filter out the already existing utxos
            utxos_to_add_verified = []
            for utxo in utxos_to_add:
                if utxo.id not in self.utxo_by_id:
                    utxos_to_add_verified.append(utxo)

            utxos_to_add_verified.sort(key=lambda x: x.block_height, reverse=True)
            row_idx = 0
            self.beginInsertRows(QModelIndex(), row_idx, row_idx + len(utxos_to_add_verified) - 1)
            try:
                for index, utxo in enumerate(utxos_to_add_verified):
                    if utxo.id not in self.utxo_by_id:
                        self.add_utxo(utxo, index)
            finally:
                self.endInsertRows()

        if utxos_to_update:
            for utxo_new in utxos_to_update:
                utxo = self.utxo_by_id.get(utxo_new.id)
                if utxo:
                    utxo.block_height = utxo_new.block_height  # block_height is the only field that can be updated
                    utxo_index = self.utxos.index(utxo)
                    ui_index = self.index(utxo_index, 0)
                    self.dataChanged.emit(ui_index, ui_index)

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
                right_utxo = self.utxos[right_row_index]
                left_value = left_utxo.__getattribute__(col_name)
                right_value = right_utxo.__getattribute__(col_name)
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

    def filterAcceptsRow(self, source_row, source_parent):
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


class TransactionTableModel(ExtSortFilterTableModel):
    def __init__(self, parent, tx_explorer_url: str):
        ExtSortFilterTableModel.__init__(self, parent, [
            TableModelColumn('direction', 'Direction', True, 50),
            TableModelColumn('satoshis', 'Amount', True, 100),
            TableModelColumn('block_time_str', 'Date', True, 100),
            TableModelColumn('block_height', 'Height', True, 100),
            TableModelColumn('confirmations', 'Confirmations', True, 100),
            TableModelColumn('senders', 'Sender', True, 100),
            TableModelColumn('recipient', 'Recipient', True, 100),
            TableModelColumn('tx_hash', 'TX Hash', False, 100),
            TableModelColumn('is_coinbase', 'Coinbase TX', True, 100),
            TableModelColumn('label', 'Comment', True, 100)
        ], True, True)
        if DEBUG_MODE:
            self.insert_column(len(self._columns), TableModelColumn('id', 'DB id', True, 40))
        self.txes: List[TxType] = []
        self.txes_by_id: Dict[int, TxType] = {}
        self.tx_explorer_url = tx_explorer_url
        self.__current_block_height = None
        self.__data_modified = False

        # filter:
        self.filter_type = FILTER_OR
        self.filter_incoming = False
        self.filter_outgoing = False
        self.filter_coinbase = False
        self.filter_recipient = None
        self.filter_sender = None
        self.filter_amount_oper = None
        self.filter_amount_value = None  # in satoshis
        self.filter_date_oper = None
        self.filter_date_value = None

    def set_view(self, table_view: QTableView):
        super().set_view(table_view)
        link_delagate = wnd_utils.HyperlinkItemDelegate(table_view)
        link_delagate.linkActivated.connect(self.hyperlink_activated)
        table_view.setItemDelegateForColumn(self.col_index_by_name('tx_hash'), link_delagate)

    def hyperlink_activated(self, link):
        QDesktopServices.openUrl(QUrl(link))

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.txes)

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def data(self, index, role=None):
        if index.isValid():
            col_idx = index.column()
            row_idx = index.row()
            col = self.col_by_index(col_idx)
            if row_idx < len(self.txes):
                tx = self.txes[row_idx]
                if role in (Qt.DisplayRole, Qt.EditRole):
                    if col.name == 'direction':
                        if tx.direction == 1:
                            if tx.is_coinbase:
                                return 'In - New coins'
                            else:
                                return 'In'
                        else:
                            return 'Out'
                    elif col.name == 'satoshis':
                        return app_utils.to_string(round(tx.satoshis / 1e8, 8))
                    elif col.name == 'senders':
                        return tx
                    elif col.name == 'recipient':
                        return tx
                    elif col.name == 'block_height':
                        if tx.block_height == UNCONFIRMED_TX_BLOCK_HEIGHT:
                            return 0
                        else:
                            return tx.block_height
                    elif col.name == 'tx_hash':
                        if self.tx_explorer_url:
                            url = self.tx_explorer_url.replace('%TXID%', tx.tx_hash)
                            url = f'<a href="{url}">{tx.tx_hash}</a>'
                            return url
                        else:
                            return tx.tx_hash
                    elif col.name == 'confirmations':
                        if self.__current_block_height is None:
                            return ''
                        else:
                            if tx.block_height == UNCONFIRMED_TX_BLOCK_HEIGHT:
                                return 'Unconfirmed'
                            else:
                                return app_utils.to_string(self.__current_block_height - tx.block_height + 1)
                    else:
                        return app_utils.to_string(tx.__getattribute__(col.name))
                elif role == Qt.ForegroundRole:
                    if col.name == 'direction':
                        if tx.direction == 1:
                            if tx.is_coinbase:
                                return QtGui.QColor(Qt.darkBlue)
                            else:
                                return QtGui.QColor(Qt.darkGreen)
                        else:
                            return QtGui.QColor(Qt.red)
                    elif col.name == 'satoshis':
                        if tx.satoshis < 0:
                            return QtGui.QColor(Qt.red)

                elif role == Qt.BackgroundRole:
                    pass

                elif role == Qt.TextAlignmentRole:
                    col = self.col_by_index(col_idx)
                    if col:
                        if col.name in ('satoshis', 'block_height', 'confirmations'):
                            return Qt.AlignRight
                        else:
                            return Qt.AlignLeft
        return QVariant()

    def setData(self, index, value, role=None):
        if index.isValid():
            col_idx = index.column()
            row_idx = index.row()
            col = self.col_by_index(col_idx)
            if row_idx < len(self.txes):
                tx = self.txes[row_idx]
                if role == Qt.EditRole:
                    if col.name == 'label':
                        tx.label = str(value)
                        return True
        return False

    def headerData(self, column, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Vertical:
            idx = self.index(column, 0)
            if idx.isValid():
                idx = self.mapFromSource(idx)
                return str(idx.row() + 1)
        else:
            return ExtSortFilterTableModel.headerData(self, column, orientation, role)

    def set_blockheight(self, cur_blockheight):
        if self.__current_block_height != cur_blockheight:
            self.__current_block_height = cur_blockheight

    def add_tx(self, tx: TxType, insert_pos = None):
        if not tx.id in self.txes_by_id:
            if insert_pos is None:
                self.txes.append(tx)
            else:
                self.txes.insert(insert_pos, tx)
            self.txes_by_id[tx.id] = tx

    def clear_txes(self):
        self.txes_by_id.clear()
        self.txes.clear()

    def lessThan(self, col_index, left_row_index, right_row_index):
        col = self.col_by_index(col_index)
        if col:
            col_name = col.name
            reverse = False

            if 0 <= left_row_index < len(self.txes) and \
               0 <= right_row_index < len(self.txes):
                left_tx = self.txes[left_row_index]
                right_tx = self.txes[right_row_index]
                if col_name == 'block_time_str':
                    col_name = 'block_timestamp'
                    left_value = left_tx.__getattribute__(col_name)
                    right_value = right_tx.__getattribute__(col_name)
                elif col_name in ('senders', 'recipient'):
                    return False
                elif col_name == 'confirmations':
                    if self.__current_block_height is not None:
                        left_value = self.__current_block_height - left_tx.block_height + 1
                        right_value = self.__current_block_height - right_tx.block_height + 1
                    else:
                        return False
                else:
                    left_value = left_tx.__getattribute__(col_name)
                    right_value = right_tx.__getattribute__(col_name)

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

    def filterAcceptsRow(self, source_row, source_parent):
        any_cond_met = False
        any_cond_not_met = False
        was_any_condition = False

        def check_cond(cond) -> Optional[bool]:
            """:return True if the item should be shown without checking other conditions
                       False if the item will not be shown without checking other conditions
                       None check next conditions
            """
            nonlocal any_cond_met, any_cond_not_met, was_any_condition
            if cond is False:
                any_cond_not_met = False
                was_any_condition = True
                if self.filter_type == FILTER_AND:
                    return False
            elif cond is True:
                any_cond_met = True
                was_any_condition = True
                if self.filter_type == FILTER_OR:
                    return True
            return None

        will_show = True

        if 0 <= source_row < len(self.txes):
            tx = self.txes[source_row]

            if self.filter_incoming or self.filter_outgoing or self.filter_coinbase:
                cond_met = (self.filter_incoming and tx.direction == 1 and tx.is_coinbase == 0) or \
                           (self.filter_coinbase and tx.direction == 1 and tx.is_coinbase == 1) or \
                           (self.filter_outgoing and tx.direction == -1)

                r = check_cond(cond_met)
                if r is False:
                    return False
                elif r is True:
                    return True

            if self.filter_amount_oper:
                sat_val = abs(tx.satoshis)
                cond_met = (self.filter_amount_oper == FILTER_OPER_EQ and sat_val == self.filter_amount_value) or \
                           (self.filter_amount_oper == FILTER_OPER_GTEQ and sat_val >= self.filter_amount_value) or \
                           (self.filter_amount_oper == FILTER_OPER_LTEQ and sat_val <= self.filter_amount_value)
                r = check_cond(cond_met)
                if r is False:
                    return False
                elif r is True:
                    return True

            if self.filter_date_oper:
                dt = datetime.datetime.fromtimestamp(tx.block_timestamp)
                dt = dt.replace(hour=0, minute=0, second=0)
                ts = int(dt.timestamp())
                cond_met = (self.filter_date_oper == FILTER_OPER_EQ and ts == self.filter_date_value) or \
                           (self.filter_date_oper == FILTER_OPER_GTEQ and ts >= self.filter_date_value) or \
                           (self.filter_date_oper == FILTER_OPER_LTEQ and ts <= self.filter_date_value)
                r = check_cond(cond_met)
                if r is False:
                    return False
                elif r is True:
                    return True

            if self.filter_recipient:
                cond_met = False
                for addr in tx.recipient_addrs:
                    if (isinstance(addr, Bip44AddressType) and addr.address == self.filter_recipient) or \
                       (addr == self.filter_recipient):
                        cond_met = True
                        break
                r = check_cond(cond_met)
                if r is False:
                    return False
                elif r is True:
                    return True

            if self.filter_sender:
                cond_met = False
                for addr in tx.sender_addrs:
                    if (isinstance(addr, Bip44AddressType) and addr.address == self.filter_sender) or \
                       (addr == self.filter_sender):
                        cond_met = True
                        break
                r = check_cond(cond_met)
                if r is False:
                    return False
                elif r is True:
                    return True

            if was_any_condition:
                if (self.filter_type == FILTER_OR and not any_cond_met) or \
                   (self.filter_type == FILTER_AND and any_cond_not_met):
                    will_show = False
        return will_show
