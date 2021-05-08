#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2021-04
from __future__ import annotations
import hashlib
import logging
import re
import threading
import time
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, List, Dict, Any

import bitcoin
from PyQt5 import QtCore, QtGui
from PyQt5.QtCore import pyqtSlot, Qt, QTimer, QVariant, QModelIndex, QRect, QPoint
from PyQt5.QtGui import QTextDocument, QPen, QBrush, QPalette, QImage, QPixmap
from PyQt5.QtWidgets import QWidget, QLineEdit, QMessageBox, QAction, QApplication, QActionGroup, QTableView, \
    QItemDelegate, QStyleOptionViewItem, QStyle, QAbstractItemView, QLabel, QMenu, QPushButton

import app_cache
import app_utils
import hw_intf
from app_config import AppConfig, MasternodeConfig, DMN_ROLE_OWNER, DMN_ROLE_OPERATOR, DMN_ROLE_VOTING
from app_defs import COLOR_ERROR_STR, COLOR_WARNING_STR, COLOR_OK_STR, COLOR_ERROR, COLOR_WARNING, COLOR_OK
from dashd_intf import DashdInterface
from ext_item_model import ExtSortFilterItemModel, TableModelColumn, HorizontalAlignment
from masternode_details_wdg import WdgMasternodeDetails
from ui import ui_app_main_view_wdg
from wnd_utils import WndUtils, ReadOnlyTableCellDelegate, SpinnerWidget, IconTextItemDelegate


CACHE_ITEM_SHOW_MN_DETAILS_PANEL = 'MainWindow_ShowMNDetailsPanel'


class Pages(Enum):
    PAGE_NETWORK_INFO = 0
    PAGE_MASTERNODE_LIST = 1
    PAGE_SINGLE_MASTERNODE = 2


log = logging.getLogger('dmt.main')
SORTING_MAX_VALUE_FOR_NULL = 1e10


class WdgAppMainView(QWidget, ui_app_main_view_wdg.Ui_WdgAppMainView):
    masternode_data_changed = QtCore.pyqtSignal()
    cur_masternode_changed = QtCore.pyqtSignal(object)

    def __init__(self, parent, app_config: AppConfig, dashd_intf: DashdInterface, hw_session: hw_intf.HwSessionInfo):
        QWidget.__init__(self, parent)
        self.current_view = Pages.PAGE_MASTERNODE_LIST
        self.main_window = parent
        self.app_config = app_config
        self.dashd_intf = dashd_intf
        self.hw_session = hw_session
        self.cur_masternode: Optional[MasternodeConfig] = None
        self.editing_enabled = False
        self.mns_status: Dict[MasternodeConfig, MasternodeStatus] = {}
        self.masternodes_table_model = MasternodesTableModel(self, self.app_config.masternodes, self.mns_status)
        self.mn_list_columns_cache_name: str = ''
        self.mn_list_columns_resized_by_user = False
        self.refresh_status_thread = None
        self.refresh_status_count = 0
        self.network_status: NetworkStatus = NetworkStatus()
        self.loading_data_spinner: Optional[SpinnerWidget] = None
        self.mn_details_panel_visible = True
        self.mnu_masternode_actions = QMenu()
        self.finishing = False
        self.mn_view_column_delegates: Dict[int, QItemDelegate] = {}
        self.setupUi(self)

    def setupUi(self, widget: QWidget):
        ui_app_main_view_wdg.Ui_WdgAppMainView.setupUi(self, self)
        self.restore_cache_settings()
        self.lblNoMasternodeMessage.setVisible(False)
        self.lblNavigation1.linkActivated.connect(self.on_link_activated)
        self.lblNavigation2.linkActivated.connect(self.on_link_activated)
        self.lblNoMasternodeMessage.linkActivated.connect(self.on_link_activated)

        self.wdg_masternode = WdgMasternodeDetails(self, self.app_config, self.dashd_intf, self.hw_session)
        l = self.frmMasternodeDetails.layout()
        l.insertWidget(1, self.wdg_masternode)
        self.wdg_masternode.setVisible(True)
        self.wdg_masternode.data_changed.connect(self.on_mn_data_changed)
        self.stackedWidget.setCurrentIndex(self.current_view.value)
        l = self.pnlNavigation.layout()
        self.loading_data_spinner = SpinnerWidget(self.pnlNavigation, 18,
                                                  'Fetching data from the network, please wait...')
        self.loading_data_spinner.hide()
        l.insertWidget(l.indexOf(self.btnMnListColumns) + 1, self.loading_data_spinner)

        # setup the masternode list view
        self.viewMasternodes.setSortingEnabled(True)
        self.viewMasternodes.setItemDelegate(ReadOnlyTableCellDelegate(self.viewMasternodes))
        self.viewMasternodes.verticalHeader().setDefaultSectionSize(
            self.viewMasternodes.verticalHeader().fontMetrics().height() + 10)
        self.viewMasternodes.horizontalHeader().setSortIndicator(
            self.masternodes_table_model.col_index_by_name('no'), Qt.AscendingOrder)
        self.masternodes_table_model.set_view(self.viewMasternodes)
        self.viewMasternodes.horizontalHeader().sectionResized.connect(self.on_mn_list_column_resized)
        self.viewMasternodes.selectionModel().selectionChanged.connect(self.on_mn_view_selection_changed)
        self.viewMasternodes.setContextMenuPolicy(Qt.CustomContextMenu)

        # configure the masternode actions menu:
        self.mnu_masternode_actions.addAction(self.main_window.action_show_masternode_details)
        self.mnu_masternode_actions.addAction(self.main_window.action_new_masternode_entry)
        self.mnu_masternode_actions.addSeparator()
        self.mnu_masternode_actions.addAction(self.main_window.action_register_masternode)
        self.mnu_masternode_actions.addAction(self.main_window.action_update_masternode_payout_address)
        self.mnu_masternode_actions.addAction(self.main_window.action_update_masternode_operator_key)
        self.mnu_masternode_actions.addAction(self.main_window.action_update_masternode_voting_key)
        self.mnu_masternode_actions.addAction(self.main_window.action_update_masternode_service)
        self.mnu_masternode_actions.addAction(self.main_window.action_revoke_masternode)
        self.mnu_masternode_actions.addSeparator()
        self.mnu_masternode_actions.addAction(self.main_window.action_sign_message_with_collateral_addr)
        self.mnu_masternode_actions.addAction(self.main_window.action_sign_message_with_owner_key)
        self.mnu_masternode_actions.addAction(self.main_window.action_sign_message_with_voting_key)
        self.btnMnActions.setMenu(self.mnu_masternode_actions)

        self.update_details_panel_controls()
        self.configure_mn_view_delegates()

    def on_close(self):
        """closeEvent is not fired for widgets, so this method will be called from the closeEvent method of the
        containing dialog"""
        self.save_cache_settings()

    def restore_cache_settings(self):
        ena = app_cache.get_value(CACHE_ITEM_SHOW_MN_DETAILS_PANEL, True, bool)
        self.mn_details_panel_visible = ena

    def save_cache_settings(self):
        app_cache.set_value(CACHE_ITEM_SHOW_MN_DETAILS_PANEL, self.mn_details_panel_visible)
        self.save_cache_config_config_dependent()

    def save_cache_config_config_dependent(self):
        """Save runtime configuration (stored in cache) that is dependent on the main configuration file.
        Currently it's the configuration of the masternode list view columns (order, widths, visibility).
        """
        if self.mn_list_columns_cache_name:
            if self.mn_list_columns_resized_by_user:
                self.masternodes_table_model.save_col_defs(self.mn_list_columns_cache_name)

    def restore_cache_config_config_dependent(self):
        """Save runtime configuration (stored in cache) that is dependent on the main configuration file."""

        old_block = self.viewMasternodes.horizontalHeader().blockSignals(True)
        try:
            if not self.masternodes_table_model.restore_col_defs(self.mn_list_columns_cache_name):
                self.viewMasternodes.resizeColumnsToContents()
            else:
                self.masternodes_table_model.set_view(self.viewMasternodes)
            self.configure_mn_view_delegates()
        finally:
            self.viewMasternodes.horizontalHeader().blockSignals(old_block)

    def configure_mn_view_delegates(self):
        # delete old column delegates for viewMasternodes
        for col_idx in self.mn_view_column_delegates.keys():
            d = self.mn_view_column_delegates[col_idx]
            del d
            self.viewMasternodes.setItemDelegateForColumn(col_idx, None)
        self.mn_view_column_delegates.clear()

        col_idx = self.masternodes_table_model.col_index_by_name('status')
        if col_idx is not None:
            deleg = IconTextItemDelegate(self.viewMasternodes)
            self.mn_view_column_delegates[col_idx] = deleg
            self.viewMasternodes.setItemDelegateForColumn(col_idx, deleg)

    def configuration_to_ui(self):
        def set_cur_mn():
            try:
                self.network_status.loaded = False
                self.refresh_status_count = 0
                if self.cur_masternode and self.cur_masternode not in self.app_config.masternodes:
                    self.cur_masternode = None
                self.masternodes_table_model.set_masternodes(self.app_config.masternodes, self.mns_status)
                self.refresh_masternodes_view()
                self.save_cache_config_config_dependent()
                h = hashlib.sha256(self.app_config.app_config_file_name.encode('ascii', 'ignore')).hexdigest()
                self.mn_list_columns_cache_name = 'MainWindow_MnListColumns_' + h[0:8]
                self.mn_list_columns_resized_by_user = False
                self.restore_cache_config_config_dependent()

                if len(self.app_config.masternodes) and not self.cur_masternode:
                    self.set_current_masternode(self.app_config.masternodes[0])
                self.update_navigation_panel()
                self.update_ui()
                self.update_info_page()

                if self.app_config.fetch_network_data_after_start:
                    self.fetch_network_data()
            except Exception as e:
                logging.exception(str(e))

        QTimer.singleShot(10, set_cur_mn)

    def refresh_masternodes_view(self):
        self.masternodes_table_model.beginResetModel()
        self.masternodes_table_model.endResetModel()

        # restore the focused row
        if self.get_cur_masternode_from_view() != self.cur_masternode:
            old_state = self.viewMasternodes.selectionModel().blockSignals(True)
            try:
                self.set_cur_masternode_in_view(self.cur_masternode)
            finally:
                self.viewMasternodes.selectionModel().blockSignals(old_state)

    def set_current_masternode(self, masternode: Optional[MasternodeConfig]):
        if self.cur_masternode != masternode:
            self.editing_enabled = False
            self.cur_masternode = masternode
            self.wdg_masternode.set_masternode(masternode)
            if self.get_cur_masternode_from_view() != self.cur_masternode:
                old_state = self.viewMasternodes.selectionModel().blockSignals(True)
                try:
                    self.set_cur_masternode_in_view(self.cur_masternode)
                finally:
                    self.viewMasternodes.selectionModel().blockSignals(old_state)
            self.update_ui()
            self.update_actions_state()
            self.cur_masternode_changed.emit(masternode)

    def set_edit_mode(self, editing_enabled: bool):
        self.editing_enabled = editing_enabled
        self.wdg_masternode.set_edit_mode(editing_enabled)
        self.update_navigation_panel()
        self.update_actions_state()

    def get_cur_masternode(self) -> Optional[MasternodeConfig]:
        return self.cur_masternode

    def set_cur_masternode_modified(self):
        pass

    def update_ui(self):
        if self.current_view.value != self.stackedWidget.currentIndex():
            self.stackedWidget.setCurrentIndex(self.current_view.value)
            if self.current_view == Pages.PAGE_SINGLE_MASTERNODE:
                self.wdg_masternode.set_masternode(self.cur_masternode)
            self.update_navigation_panel()

        if self.current_view == Pages.PAGE_MASTERNODE_LIST:
            if not self.app_config.masternodes and not self.lblNoMasternodeMessage.isVisible():
                msg = '<h3>No masternodes in your configuration... <a href="add_mn">add a new one</a></h3>'
                self.lblNoMasternodeMessage.setVisible(True)
                self.lblNoMasternodeMessage.setText(msg)
                self.viewMasternodes.setVisible(False)
                self.btnMnListColumns.setVisible(False)
            elif self.app_config.masternodes:
                self.lblNoMasternodeMessage.setVisible(False)
                self.viewMasternodes.setVisible(True)
                self.btnMnListColumns.setVisible(True)
        else:
            self.btnMnListColumns.setVisible(False)

        self.update_details_panel_controls()
        self.wdg_masternode.masternode_data_to_ui()
        self.update_mn_preview()

    def update_actions_state(self):
        def update_fun():
            editing = (self.editing_enabled and self.cur_masternode is not None and
                       self.current_view == Pages.PAGE_SINGLE_MASTERNODE)
            self.btnEditMn.setVisible(not editing)
            self.btnCancelEditingMn.setVisible(editing)
            self.btnApplyMnChanges.setVisible(editing)
            self.btnApplyMnChanges.setEnabled(self.wdg_masternode.is_modified())
            self.btnEditMn.setEnabled(not self.editing_enabled and self.cur_masternode is not None)
            self.btnCancelEditingMn.setEnabled(self.editing_enabled and self.cur_masternode is not None)

        if threading.current_thread() != threading.main_thread():
            self.call_in_main_thread(update_fun)
        else:
            update_fun()

    def update_navigation_panel(self):
        if self.current_view == Pages.PAGE_MASTERNODE_LIST:
            mns_link = '<span style="color:black">\u25B6 <b>Masternodes</b></span>'
        else:
            if self.current_view == Pages.PAGE_SINGLE_MASTERNODE and self.editing_enabled:
                # don't allow changing view when in edit mode
                mns_link = '<span style="color:gray">Masternodes</span>'
            else:
                mns_link = '<a style="text-decoration:none" href="masternodes">Masternodes</a>'
        mns_link = '<span>' + mns_link + '</span>'
        self.lblNavigation1.setText(mns_link)

        if self.current_view == Pages.PAGE_NETWORK_INFO:
            network_info_link = '<span style="color:black">\u25B6 <b>Network info</b></span>'
        else:
            if self.current_view == Pages.PAGE_SINGLE_MASTERNODE and self.editing_enabled:
                # don't allow changing view when in edit mode
                network_info_link = '<span style="color:gray">Network info</span>'
            else:
                network_info_link = '<a style="text-decoration:none" href="netinfo">Network info</a>'
        self.lblNavigation2.setText(network_info_link)

    @pyqtSlot(str)
    def on_link_activated(self, link):
        if link == 'netinfo':
            self.current_view = Pages.PAGE_NETWORK_INFO
        elif link == 'masternodes':
            self.current_view = Pages.PAGE_MASTERNODE_LIST
        elif link == 'add_mn':
            WndUtils.info_msg('Not implemented')
            return
        self.update_navigation_panel()
        self.update_ui()

    def on_mn_list_column_resized(self, logical_index, old_size, new_size):
        self.mn_list_columns_resized_by_user = True

    def on_mn_data_changed(self):
        self.update_actions_state()

    @pyqtSlot(bool)
    def on_btnEditMn_clicked(self):
        try:
            self.set_edit_mode(True)
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnCancelEditingMn_clicked(self):
        try:
            self.set_edit_mode(False)
            if self.wdg_masternode.is_modified():
                mod = self.cur_masternode.modified
                self.wdg_masternode.set_masternode(self.cur_masternode)  # restore the original (non-modified) data
                self.cur_masternode.modified = mod
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnApplyMnChanges_clicked(self):
        try:
            self.set_edit_mode(False)
            if self.wdg_masternode.is_modified():
                self.wdg_masternode.get_masternode_data(self.cur_masternode)
                self.app_config.modified = True
                self.masternode_data_changed.emit()
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnSingleMnGoBack_clicked(self):
        try:
            if self.editing_enabled:
                self.set_edit_mode(False)
            self.current_view = Pages.PAGE_MASTERNODE_LIST
            self.update_navigation_panel()
            self.update_ui()
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnMnListColumns_clicked(self):
        self.masternodes_table_model.exec_columns_dialog(self)

    @pyqtSlot(str)
    def on_lblMnStatusLabel_linkActivated(self, link: str):
        self.mn_details_panel_visible = not self.mn_details_panel_visible
        self.update_details_panel_controls()

    def update_details_panel_controls(self):
        panel_visible = self.cur_masternode is not None and \
                        self.current_view in (Pages.PAGE_SINGLE_MASTERNODE, Pages.PAGE_MASTERNODE_LIST) and \
                        self.mn_details_panel_visible

        link_text = 'hide' if self.mn_details_panel_visible else 'show'
        t = f'Masternode status details (<a href="{link_text}">{link_text}</a>)'
        self.lblMnStatusLabel.setText(t)
        self.lblMnStatus.setVisible(panel_visible)

    def fetch_network_data(self):
        def update():
            self.hide_loading_animation()
            self.update_info_page()
            self.update_mn_preview()
            self.refresh_masternodes_view()

        if not self.refresh_status_thread:
            self.refresh_status_thread = WndUtils.run_thread(self, self.get_masternode_status_thread, (),
                                                             on_thread_finish=update)

    @pyqtSlot(bool)
    def on_btnRefreshMnStatus_clicked(self):
        self.fetch_network_data()

    @pyqtSlot(QModelIndex)
    def on_viewMasternodes_doubleClicked(self, index):
        try:
            self.goto_cur_masternode_details()
        except Exception as e:
            WndUtils.error_msg(str(e))

    @pyqtSlot(QPoint)
    def on_viewMasternodes_customContextMenuRequested(self, point):
        try:
            p = self.viewMasternodes.mapToGlobal(point)
            p.setY(p.y() + 12)
            self.mnu_masternode_actions.exec_(p)
        except Exception as e:
            self.error_msg(str(e))

    def goto_cur_masternode_details(self):
        self.current_view = Pages.PAGE_SINGLE_MASTERNODE
        self.update_ui()

    def get_cur_masternode_from_view(self) -> Optional[MasternodeConfig]:
        mn: Optional[MasternodeConfig] = None
        cur_index = self.viewMasternodes.currentIndex()
        if cur_index:
            source_row = self.masternodes_table_model.mapToSource(cur_index)
            if source_row:
                current_row = source_row.row()
                if current_row is not None and 0 <= current_row < len(self.app_config.masternodes):
                    mn = self.app_config.masternodes[current_row]
        return mn

    def set_cur_masternode_in_view(self, mn: MasternodeConfig):
        idx = self.app_config.masternodes.index(mn)
        if idx >= 0:
            midx = self.masternodes_table_model.index(idx, 0)
            if midx and midx.isValid():
                self.viewMasternodes.setCurrentIndex(midx)

    def on_mn_view_selection_changed(self, selected, deselected):
        mn = self.get_cur_masternode_from_view()
        self.set_current_masternode(mn)

    def delete_masternode(self, masternode: MasternodeConfig):
        if masternode and masternode in self.app_config.masternodes:
            idx = self.app_config.masternodes.index(masternode)
            try:
                if self.query_dlg(f'Do you really want to remove masternode "{masternode.name}" from configuration?',
                                  buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                  default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Yes:
                    self.app_config.masternodes.remove(self.cur_masternode)
                    self.app_config.modified = True
            except Exception as e:
                self.error_msg(str(e), True)

    def add_new_masternode(self, src_masternode: Optional[MasternodeConfig]):
        new_mn = MasternodeConfig()
        new_mn.new = True
        self.cur_masternode = new_mn

        if src_masternode:
            mn_template = src_masternode.name
        else:
            if self.app_config.is_testnet:
                new_mn.port = '19999'
            mn_template = 'MN'
        name_found = None
        for nr in range(1, 100):
            exists = False
            for mn in self.app_config.masternodes:
                if mn.name == mn_template + str(nr):
                    exists = True
                    break
            if not exists:
                name_found = mn_template + str(nr)
                break
        if name_found:
            new_mn.name = name_found

        if src_masternode:
            new_mn.copy_from(src_masternode)

        self.app_config.masternodes.append(new_mn)
        self.set_masternode(self.cur_masternode)
        self.set_edit_mode(self.editing_enabled)

    def fetch_governance_info(self):
        gi = self.network_status
        _ginfo = self.dashd_intf.getgovernanceinfo()
        cur_block_height = self.dashd_intf.getblockcount()
        gi.last_superblock = _ginfo.get('lastsuperblock')
        gi.next_superblock = _ginfo.get('nextsuperblock')
        gi.superblock_cycle = _ginfo.get('superblockcycle')
        deadline_blocks = round(gi.superblock_cycle / 10)

        last_superblock_ts = self.dashd_intf.get_block_timestamp(gi.last_superblock)
        gi.next_superblock_ts = 0
        if 0 < cur_block_height <= gi.next_superblock:
            gi.next_superblock_ts = self.dashd_intf.get_block_timestamp(cur_block_height) + (
                    gi.next_superblock - cur_block_height) * 2.5 * 60

        if gi.next_superblock_ts == 0:
            gi.next_superblock_ts = last_superblock_ts + (gi.next_superblock - gi.last_superblock) * 2.5 * 60

        gi.voting_deadline_ts = gi.next_superblock_ts - (deadline_blocks * 2.5 * 60)
        gi.next_superblock_date = datetime.fromtimestamp(gi.next_superblock_ts)
        gi.voting_deadline_date = datetime.fromtimestamp(gi.voting_deadline_ts)
        gi.budget_available = float(self.dashd_intf.getsuperblockbudget(gi.next_superblock))
        deadline_block = gi.next_superblock - deadline_blocks
        gi.voting_deadline_passed = deadline_block <= cur_block_height < gi.next_superblock

        if gi.voting_deadline_passed:
            gi.voting_deadline_in = 'passed'
        else:
            gi.voting_deadline_in = ''
            dl_diff = gi.voting_deadline_ts - time.time()
            if dl_diff > 0:
                if dl_diff < 3600:
                    dl_str = app_utils.seconds_to_human(dl_diff, out_seconds=False, out_minutes=True, out_hours=False,
                                                        out_days=False, out_weeks=False)
                elif dl_diff < 3600 * 3:
                    dl_str = app_utils.seconds_to_human(dl_diff, out_seconds=False, out_minutes=True, out_hours=True,
                                                        out_days=False, out_weeks=False)
                elif dl_diff < 3600 * 24:
                    dl_str = app_utils.seconds_to_human(dl_diff, out_seconds=False, out_minutes=False, out_hours=True,
                                                        out_days=False, out_weeks=False)
                elif dl_diff < 3600 * 24 * 3:
                    dl_str = app_utils.seconds_to_human(dl_diff, out_seconds=False, out_minutes=False, out_hours=True,
                                                        out_days=True, out_weeks=False)
                else:
                    dl_str = app_utils.seconds_to_human(dl_diff, out_seconds=False, out_minutes=False, out_hours=False,
                                                        out_days=True, out_weeks=False)
                gi.voting_deadline_in = dl_str

        # masternodes
        mns = self.dashd_intf.masternodes
        gi.masternode_count_by_status.clear()
        gi.masternode_count = len(mns)
        for mn in mns:
            gi.masternode_count_by_status[mn.status] = gi.masternode_count_by_status.get(mn.status, 0) + 1

        bi = self.dashd_intf.getblockchaininfo()
        gi.blockchain_size_on_disk = bi.get('size_on_disk')
        gi.blocks = bi.get('blocks')

        gi.last_block_ts = self.dashd_intf.get_block_timestamp(cur_block_height)
        gi.loaded = True

    def get_mn_protx(self, masternode: MasternodeConfig, protx_list_registered: List[Dict]) -> Optional[Dict]:
        protx = None
        protx_state = None

        if masternode.dmn_tx_hash:
            try:
                protx = self.dashd_intf.protx('info', masternode.dmn_tx_hash)
                if protx:
                    protx_state = protx.get('state')
            except Exception as e:
                logging.exception('Cannot read protx info')

            if not protx:
                try:
                    # protx transaction is not confirmed yet, so look for it in the mempool
                    tx = self.dashd_intf.getrawtransaction(masternode.dmn_tx_hash, 1, skip_cache=True)
                    confirmations = tx.get('confirmations', 0)
                    if confirmations < 3:
                        # in this case dmn tx should have been found by the 'protx info' call above;
                        # it hasn't been, so it is no longer valid a protx transaction
                        ptx = tx.get('proRegTx')
                        if ptx:
                            protx = {
                                'proTxHash': masternode.dmn_tx_hash,
                                'collateralHash': ptx.get('collateralHash'),
                                'collateralIndex': ptx.get('collateralIndex'),
                                'state': {
                                    'service': ptx.get('service'),
                                    'ownerAddress': ptx.get('ownerAddress'),
                                    'votingAddress': ptx.get('votingAddress'),
                                    'pubKeyOperator': ptx.get('pubKeyOperator'),
                                    'payoutAddress': ptx.get('payoutAddress')
                                }
                            }
                        if protx:
                            protx_state = protx.get('state')
                except Exception as e:
                    pass

        if not (protx_state and ((protx_state.get('service') == masternode.ip + ':' + masternode.port) or
                                 (protx.get('collateralHash') == masternode.collateral_tx and
                                  str(protx.get('collateralIndex')) == str(masternode.collateral_tx_index)))):
            try:
                if not protx_list_registered:
                    protx_list_registered.extend(self.dashd_intf.protx('list', 'registered', True))

                for protx in protx_list_registered:
                    protx_state = protx.get('state')
                    if (protx_state and ((protx_state.get('service') == masternode.ip + ':' + masternode.port) or
                                         (protx.get('collateralHash') == masternode.collateral_tx and
                                          str(protx.get('collateralIndex')) == str(masternode.collateral_tx_index)))):
                        return protx
            except Exception as e:
                pass
        else:
            return protx
        return None

    def get_masternode_status_thread(self, ctrl):
        def on_start():
            self.show_loading_animation()
            self.update_mn_preview()

        protx_list_registered: List[Dict] = []  # result of the call: protx list registered

        try:
            if self.finishing:
                return
            WndUtils.call_in_main_thread(on_start)

            self.dashd_intf.get_masternodelist('json', data_max_age=30)
            self.fetch_governance_info()
            block_height = self.dashd_intf.getblockcount()

            mempool = self.dashd_intf.getrawmempool()
            self.network_status.mempool_entries_count = len(mempool)

            mns = list(self.app_config.masternodes)
            for mn in mns:
                ms = self.mns_status.get(mn)
                if not ms:
                    ms = MasternodeStatus()
                    self.mns_status[mn] = ms
                else:
                    ms.clear()

                if mn.collateral_tx and str(mn.collateral_tx_index):
                    collateral_id = mn.collateral_tx + '-' + mn.collateral_tx_index
                else:
                    collateral_id = None
                if mn.ip and mn.port:
                    ip_port = mn.ip + ':' + str(mn.port)
                else:
                    ip_port = None

                if not collateral_id and not ip_port:
                    if not mn.collateral_tx:
                        ms.not_found = True
                        continue

                if collateral_id:
                    mn_info = self.dashd_intf.masternodes_by_ident.get(collateral_id)
                elif ip_port:
                    mn_info = self.dashd_intf.masternodes_by_ip_port.get(ip_port)
                else:
                    mn_info = None

                if not mn_info:
                    ms.not_found = True
                    continue

                ms.status = mn_info.status
                if mn_info.queue_position:
                    ms.next_payment_block = block_height + mn_info.queue_position + 1
                    ms.next_payment_ts = int(time.time()) + (mn_info.queue_position * 2.5 * 60)

                if mn_info.status == 'ENABLED' or mn_info.status == 'PRE_ENABLED':
                    ms.status_warning = False
                else:
                    ms.status_warning = True

                if mn_info.protx:
                    if mn_info.protx.pose_penalty:
                        ms.pose_penalty = mn_info.protx.pose_penalty
                        ms.status_warning = True

                    if re.match('^0+$', mn_info.protx.pubkey_operator):
                        no_operator_pub_key = True
                    else:
                        no_operator_pub_key = False

                    if mn_info.protx.service == '[0:0:0:0:0:0:0:0]:0':
                        if no_operator_pub_key:
                            ms.operator_key_update_required = True
                        else:
                            ms.operator_service_update_required = True

                    if mn.dmn_user_roles & DMN_ROLE_OWNER:
                        if not mn.collateral_address or mn.collateral_address != mn_info.protx.collateral_address:
                            ms.collateral_address_mismatch = True

                        owner_address_cfg = mn.get_dmn_owner_public_address(self.app_config.dash_network)
                        if not owner_address_cfg or mn_info.protx.owner_address != owner_address_cfg:
                            ms.owner_public_address_mismatch = True

                    if mn.dmn_user_roles & DMN_ROLE_OPERATOR:
                        operator_pubkey_cfg = mn.get_dmn_operator_pubkey()
                        if not operator_pubkey_cfg or operator_pubkey_cfg != mn_info.protx.pubkey_operator:
                            ms.operator_pubkey_mismatch = True

                    if mn.dmn_user_roles & DMN_ROLE_VOTING:
                        voting_address_cfg = mn.get_dmn_voting_public_address(self.app_config.dash_network)
                        if not voting_address_cfg or voting_address_cfg != mn_info.protx.voting_address:
                            ms.voting_public_address_mismatch = True

                if not mn.collateral_tx or not mn.collateral_tx_index or \
                        str(mn.collateral_tx) + '-' + str(mn.collateral_tx_index) != mn_info.ident:
                    ms.collateral_tx_mismatch = True

                if mn_info.protx and mn.dmn_tx_hash != mn_info.protx_hash:
                    ms.protx_mismatch = True

                if mn_info.ip != mn.ip + ':' + str(mn.port):
                    ms.ip_port_mismatch = True

                if not ms.collateral_address_mismatch:
                    coll_bal = self.dashd_intf.getaddressbalance([mn.collateral_address])
                    ms.collateral_addr_balance = round(coll_bal.get('balance') / 1e8, 5)

                if mn_info.protx and mn_info.protx.payout_address:
                    ms.payout_address = mn_info.protx.payout_address
                    payout_bal = self.dashd_intf.getaddressbalance([mn_info.protx.payout_address])
                    ms.payout_addr_balance = round(payout_bal.get('balance') / 1e8, 5)

                if mn_info.protx and mn_info.protx.operator_payout_address:
                    ms.operator_payout_address = mn_info.protx.operator_payout_address
                    if mn_info.protx.operator_payout_address != mn_info.protx.payout_address:
                        payout_bal = self.dashd_intf.getaddressbalance([mn_info.protx.operator_payout_address])
                        ms.operator_payout_addr_balance = round(payout_bal.get('balance') / 1e8, 5)
                    else:
                        ms.operator_payout_addr_balance = ms.payout_addr_balance

                ms.last_paid_ts = 0
                if mn_info.lastpaidtime > time.time() - 3600 * 24 * 365:
                    # fresh dmns have lastpaidtime set to some day in the year 2014
                    ms.last_paid_ts = mn_info.lastpaidtime

                if mn_info.protx and mn_info.protx.last_paid_height and mn_info.protx.last_paid_height > 0:
                    ms.last_paid_block = mn_info.protx.last_paid_height
                    if not ms.last_paid_ts:
                        ms.last_paid_ts = self.dashd_intf.get_block_timestamp(ms.last_paid_block)

                if ms.last_paid_ts:
                    ms.last_paid_dt = datetime.fromtimestamp(float(ms.last_paid_ts))
                    ms.last_paid_ago = int(time.time()) - int(ms.last_paid_ts)
                    ago_str = app_utils.seconds_to_human(ms.last_paid_ago, out_unit_auto_adjust=True)
                    ms.last_paid_ago_str = ago_str + ' ago' if ago_str else ''

                if ms.next_payment_block and ms.next_payment_ts:
                    ms.next_payment_dt = datetime.fromtimestamp(float(ms.next_payment_ts))
                    ms.next_payment_in = ms.next_payment_ts - int(time.time())
                    in_str = app_utils.seconds_to_human(ms.next_payment_in, out_unit_auto_adjust=True)
                    ms.next_payment_in_str = 'in ' + in_str if in_str else ''

                # todo: verify masternodes' confirmations and protx updates pending

            self.refresh_status_count += 1
        except Exception as e:
            if not self.finishing:
                log.exception(str(e))
                WndUtils.call_in_main_thread(WndUtils.error_msg, str(e))

        finally:
            self.refresh_status_thread = None

    def update_info_page(self):
        gi = self.network_status
        try:
            status = (
                '<style>td {white-space:nowrap;padding-right:8px;padding-top:4px}'
                '.title {text-align:right;font-weight:normal}'
                '.value {color:navy}'
                '</style>'
                '<table>'
                f'<tr><td class="title">Next superblock date</td><td class="value">{app_utils.to_string(gi.next_superblock_date) if gi.loaded else "?"}</td></tr>'
                f'<tr><td class="title">Voting deadline</td><td class="value">{app_utils.to_string(gi.voting_deadline_date) if gi.loaded else "?"}</td></tr>'
                f'<tr><td class="title">Voting deadline in</td><td class="value">{gi.voting_deadline_in if gi.loaded else "?"}</td></tr>'
                f'<tr><td class="title">Budget available</td><td class="value">{app_utils.to_string(round(gi.budget_available, 2)) + " Dash" if gi.loaded else "?"}</td></tr>'
                f'<tr><td class="title">Masternodes (ALL)</td><td class="value">{str(gi.masternode_count) if gi.loaded else "?"}</td></tr>'
            )

            for mn_status in gi.masternode_count_by_status.keys():
                status += f'<tr><td class="title">Masternodes ({mn_status})</td><td class="value">{str(gi.masternode_count_by_status.get(mn_status)) if gi.loaded else "?"}</td></tr>'

            status += f'<tr><td class="title">Blockchain size on disk</td><td class="value">{app_utils.bytes_to_human(gi.blockchain_size_on_disk) if gi.loaded else "?"}</td></tr>'
            status += f'<tr><td class="title">Block count</td><td class="value">{str(gi.blocks) if gi.loaded else "?"}</td></tr>'

            if gi.last_block_ts > 0:
                ago_seconds = int(time.time() - gi.last_block_ts)
                last_block_ago_str = app_utils.seconds_to_human(ago_seconds, out_unit_auto_adjust=True) + ' ago'
            else:
                last_block_ago_str = '?'
            status += f'<tr><td class="title">Last block</td><td class="value">{last_block_ago_str}</td></tr>'

            status += f'<tr><td class="title">Transactions in mempool</td><td class="value">{str(gi.mempool_entries_count) if gi.loaded else "?"}</td></tr>'

            status += '</table>'
            self.lblNetworkInfo.setText(status)
        except Exception as e:
            log.exception(str(e))

    def update_mn_preview(self):
        status_lines = []

        def add_status_line(label: str, value: str, value_color: Optional[str] = None):
            col = f'style="color:{value_color}"' if value_color else ''
            status_lines.append(f'<tr><td class="title">{label}</td><td class="value" colspan="2" '
                                f'{col}>{value}</td></tr>')

        status = ''
        mn = self.cur_masternode
        if mn:
            st = self.mns_status.get(mn)
            if st:
                errors: List[str] = []
                warnings: List[str] = []

                if st.is_error():
                    status_color = COLOR_ERROR_STR
                elif st.is_warning():
                    status_color = COLOR_WARNING_STR
                else:
                    status_color = COLOR_OK_STR
                status_text = st.get_status()
                if st.pose_penalty:
                    status_text += ', PoSePenalty: ' + str(st.pose_penalty)
                add_status_line('Status', status_text, status_color)

                if st.payout_address:
                    url = self.app_config.get_block_explorer_addr().replace('%ADDRESS%', st.payout_address)
                    link = '<a href="%s">%s</a>' % (url, st.payout_address)
                else:
                    link = ''
                add_status_line('Payout address', link)

                add_status_line('Payout addr. balance',
                                app_utils.to_string(st.payout_addr_balance) if st.payout_addr_balance else '')

                if mn.collateral_address.strip() and mn.collateral_address.strip() != st.payout_address:
                    url = self.app_config.get_block_explorer_addr().replace('%ADDRESS%', mn.collateral_address.strip())
                    link = '<a href="%s">%s</a>' % (url, mn.collateral_address.strip())
                    add_status_line('Collateral address', link)

                    add_status_line('Collateral addr. balance',
                                    app_utils.to_string(st.collateral_addr_balance) if st.collateral_addr_balance
                                    else '')

                if st.operator_payout_address:
                    url = self.app_config.get_block_explorer_addr().replace('%ADDRESS%', st.operator_payout_address)
                    link = '<a href="%s">%s</a>' % (url, st.operator_payout_address)
                    add_status_line('Operator payout address', link)

                if st.last_paid_dt:
                    lp = app_utils.to_string(st.last_paid_dt)
                    if st.last_paid_block:
                        lp += ' / block# ' + str(st.last_paid_block)
                    if st.last_paid_ago_str:
                        lp += ' / ' + st.last_paid_ago_str
                    add_status_line('Last paid', lp)

                if st.next_payment_dt:
                    np = app_utils.to_string(st.next_payment_dt)
                    if st.next_payment_block:
                        np += ' / block# ' + str(st.next_payment_block)
                    if st.next_payment_in_str:
                        np += ' / ' + st.next_payment_in_str
                    add_status_line('Next payment', np)

                if st.operator_service_update_required:
                    errors.append('Operator service update required')
                if st.operator_key_update_required:
                    errors.append('Operator key update required')
                if st.ip_port_mismatch:
                    warnings.append('Masternode IP/port mismatch (config)')
                if st.collateral_tx_mismatch:
                    warnings.append('Collateral tx mismatch between (config)')
                if st.collateral_address_mismatch:
                    warnings.append('Collateral address mismatch (config)')
                if st.owner_public_address_mismatch:
                    warnings.append('Owner address mismatch (config)')
                if st.operator_pubkey_mismatch:
                    warnings.append('Operator public key mismatch (config)')
                if st.voting_public_address_mismatch:
                    warnings.append('Voting address mismatch (config)')

                for idx, val in enumerate(errors):
                    if idx == 0:
                        label = 'Errors'
                    else:
                        label = ''
                    add_status_line(label, val, COLOR_ERROR_STR)

                for idx, val in enumerate(warnings):
                    if idx == 0:
                        label = 'Warnings'
                    else:
                        label = ''
                    add_status_line(label, val, COLOR_WARNING_STR)

                status = \
                    '<style>td {white-space:nowrap;padding-right:8px}' \
                    '.title {text-align:right;font-weight:bold}' \
                    '.ago {font-style:normal}' \
                    '.value {color:navy}' \
                    '.error {color:' + COLOR_ERROR_STR + '}' \
                                                         '.warning {color: ' + COLOR_WARNING_STR + '}' \
                                                                                                   '</style>' \
                                                                                                   '<table>' + ''.join(
                        status_lines) + '</table>'
            else:
                if self.refresh_status_count == 0:
                    if self.refresh_status_thread:
                        status = 'Fetching data from the network, please wait...'
                    else:
                        status = 'Status data will be available after fetching data from the network'
        self.lblMnStatus.setText(status)

    def show_loading_animation(self):
        def show():
            self.loading_data_spinner.show()
            self.loading_data_spinner.set_spinner_active(True)

        if threading.current_thread() != threading.main_thread():
            if not self.finishing:
                WndUtils.call_in_main_thread_ext(show, skip_if_main_thread_locked=True)
        else:
            show()

    def hide_loading_animation(self):
        def hide():
            self.loading_data_spinner.set_spinner_active(False)
            self.loading_data_spinner.hide()

        if threading.current_thread() != threading.main_thread():
            if not self.finishing:
                WndUtils.call_in_main_thread_ext(hide, skip_if_main_thread_locked=True)
        else:
            hide()


class MasternodesTableModel(ExtSortFilterItemModel):
    def __init__(self, parent, masternodes: List[MasternodeConfig],
                 mns_status: Dict[MasternodeConfig, MasternodeStatus]):
        ExtSortFilterItemModel.__init__(self, parent, [
            TableModelColumn('no', '', True, 20, horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('name', 'Name', True, 100),
            TableModelColumn('status', 'Status', True, 100),
            TableModelColumn('ip_port', 'IP/port', True, 140),
            TableModelColumn('collateral', 'Collateral address', False, 100),
            TableModelColumn('collateral_tx', 'Collateral tx/index', False, 100),
            TableModelColumn('roles', 'Roles', False, 100),
            TableModelColumn('protx', 'Protx', False, 100),
            TableModelColumn('last_paid_block', 'Last paid (block)', False, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('last_paid_time', 'Last paid (time)', True, 100),
            TableModelColumn('last_paid_ago', 'Last paid (ago)', True, 100),
            TableModelColumn('next_payment_block', 'Next payment (block)', False, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('next_payment_time', 'Next payment (time)', True, 100),
            TableModelColumn('next_payment_in', 'Next payment (in)', True, 100),
            TableModelColumn('collateral_addr_balance', 'Collateral balance', True, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('payout_addr_balance', 'Payout balance', True, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT)
        ], True, True)
        self.masternodes = masternodes
        self.mns_status = mns_status
        self.background_color = QtGui.QColor('lightgray')
        self.set_attr_protection()

    def set_masternodes(self, mns: List[MasternodeConfig], mns_status: Dict[MasternodeConfig, MasternodeStatus]):
        self.masternodes = mns
        self.mns_status = mns_status

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.masternodes)

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def set_view(self, table_view: QTableView):
        super().set_view(table_view)
        h = table_view.horizontalHeader()
        self.background_color = h.palette().color(QPalette.Active, h.palette().Background)

    def data(self, index, role=None):
        if index.isValid():
            col_idx = index.column()
            row_idx = index.row()
            if row_idx < len(self.masternodes):
                mn = self.masternodes[row_idx]
                if mn:
                    if role in (Qt.DisplayRole, Qt.EditRole):
                        val = self.get_cell_value(row_idx, col_idx, for_sorting=False)
                        if val is None:
                            val = QVariant()
                        return val

                    elif role == Qt.ForegroundRole:
                        st = self.mns_status.get(mn)
                        col: TableModelColumn = self.col_by_index(col_idx)
                        if col:
                            if col.name == 'status':
                                if st:
                                    if st.is_error():
                                        return COLOR_ERROR
                                    elif st.is_warning():
                                        return COLOR_WARNING
                                    else:
                                        return COLOR_OK
                        return None

                    elif role == Qt.TextAlignmentRole:
                        col: TableModelColumn = self.col_by_index(col_idx)
                        if col and col.horizontal_alignment:
                            return Qt.AlignRight | Qt.AlignVCenter if col.horizontal_alignment == \
                                                                      HorizontalAlignment.RIGHT else \
                                Qt.AlignLeft | Qt.AlignVCenter
                        return None

                    elif role == Qt.FontRole:
                        col: TableModelColumn = self.col_by_index(col_idx)
                        if col and col.name == 'name':
                            font = QtGui.QFont()
                            font.setBold(True)
                            return font

        return QVariant()

    def get_cell_value(self, row_idx: int, col_idx: int, for_sorting: bool):
        ret_val: Any = None
        if row_idx < len(self.masternodes):
            mn = self.masternodes[row_idx]
            if mn:
                st = self.mns_status.get(mn)

            st = self.mns_status.get(mn)
            col = self.col_by_index(col_idx)
            if col:
                col_name = col.name
                if col_name == 'no':
                    ret_val = row_idx + 1
                    if not for_sorting:
                        ret_val = str(ret_val) + '.'
                elif col_name == 'name':
                    ret_val = mn.name
                elif col_name == 'ip_port':
                    ret_val = mn.ip + (':' + str(mn.port) if mn.port else '')
                elif col_name == 'collateral':
                    ret_val = mn.collateral_address
                elif col_name == 'collateral_tx':
                    ret_val = mn.collateral_tx + (
                        ':' + str(mn.collateral_tx_index) if mn.collateral_tx_index else '')
                elif col_name == 'roles':
                    val = ''
                    if mn.dmn_user_roles & DMN_ROLE_OWNER > 0:
                        val = 'owner'
                    if mn.dmn_user_roles & DMN_ROLE_OPERATOR > 0:
                        val = 'operator' if not val else val + ' | operator'
                    if mn.dmn_user_roles & DMN_ROLE_VOTING > 0:
                        val = 'voting' if not val else val + ' | voting'
                    ret_val = val
                elif col_name == 'protx':
                    ret_val = mn.dmn_tx_hash
                elif col_name == 'status':
                    if for_sorting:
                        ret_val = st.status if st else ''
                    else:
                        if st:
                            if st.is_error():
                                img_file = 'error@16px.png'
                            elif st.is_warning():
                                img_file = 'warning@16px.png'
                            else:
                                img_file = 'check-circle@16px.png'

                            pix = WndUtils.get_pixmap(self, img_file)
                            ret_val = (pix, st.get_status())

                elif col_name == 'last_paid_block':
                    if st:
                        ret_val = st.last_paid_block
                        if ret_val is None and for_sorting:
                            ret_val = SORTING_MAX_VALUE_FOR_NULL
                elif col_name == 'last_paid_time':
                    if st:
                        if for_sorting:
                            ret_val = st.last_paid_ts
                            if ret_val is None:
                                ret_val = 0
                        else:
                            ret_val = app_utils.to_string(st.last_paid_dt)
                elif col_name == 'last_paid_ago':
                    if st:
                        if for_sorting:
                            ret_val = st.last_paid_ago
                            if ret_val is None:
                                ret_val = SORTING_MAX_VALUE_FOR_NULL
                        else:
                            ret_val = st.last_paid_ago_str
                elif col_name == 'next_payment_block':
                    if st:
                        ret_val = st.next_payment_block
                        if ret_val is None and for_sorting:
                            ret_val = SORTING_MAX_VALUE_FOR_NULL
                elif col_name == 'next_payment_time':
                    if st:
                        if for_sorting:
                            ret_val = st.next_payment_ts
                            if ret_val is None:
                                ret_val = SORTING_MAX_VALUE_FOR_NULL
                        else:
                            ret_val = app_utils.to_string(st.next_payment_dt)
                elif col_name == 'next_payment_in':
                    if st:
                        if for_sorting:
                            ret_val = st.next_payment_ts
                            if ret_val is None:
                                ret_val = SORTING_MAX_VALUE_FOR_NULL
                        else:
                            ret_val = st.next_payment_in_str
                elif col_name == 'collateral_addr_balance':
                    if st:
                        if for_sorting:
                            ret_val = st.collateral_addr_balance
                            if ret_val is None:
                                ret_val = 0
                        else:
                            ret_val = app_utils.to_string(st.collateral_addr_balance)
                elif col_name == 'payout_addr_balance':
                    if st:
                        if for_sorting:
                            ret_val = st.payout_addr_balance
                            if ret_val is None:
                                ret_val = 0
                        else:
                            ret_val = app_utils.to_string(st.payout_addr_balance)
        return ret_val

    def lessThan(self, col_index, left_row_index, right_row_index):
        col = self.col_by_index(col_index)
        if col:
            reverse = False

            left_value = self.get_cell_value(left_row_index, col_index, True)
            right_value = self.get_cell_value(right_row_index, col_index, True)

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
        return will_show


class NetworkStatus:
    def __init__(self):
        self.loaded = False
        self.last_superblock = -1
        self.next_superblock = -1
        self.superblock_cycle = 0
        self.next_superblock_ts = -1
        self.next_superblock_date: Optional[datetime] = None
        self.voting_deadline_ts = -1
        self.voting_deadline_date: Optional[datetime] = None
        self.voting_deadline_in: str = ''
        self.voting_deadline_passed = False
        self.budget_available: Optional[float] = None
        self.masternode_count_by_status: Dict[str, int] = {}
        self.masternode_count = 0
        self.blocks = 0
        self.blockchain_size_on_disk = 0
        self.mempool_entries_count = 0
        self.last_block_ts = -1


class MasternodeStatus:
    def __init__(self):
        self.not_found = False
        self.status = ''
        self.status_warning = False
        self.protx_conf_pending = False
        self.pose_penalty = 0
        self.operator_pub_key = ''
        self.operator_key_update_required = False
        self.operator_service_update_required = False
        self.ip_port_mismatch = False
        self.protx_mismatch = False
        self.collateral_tx_mismatch = False
        self.collateral_address_mismatch = False
        self.owner_public_address_mismatch = False
        self.operator_pubkey_mismatch = False
        self.voting_public_address_mismatch = False
        self.payout_address: Optional[str] = None
        self.payout_addr_balance = 0
        self.operator_payout_address: Optional[str] = None
        self.operator_payout_addr_balance = 0
        self.collateral_addr_balance = 0
        self.last_paid_block: Optional[int] = None
        self.last_paid_ts: Optional[int] = None
        self.last_paid_dt: Optional[datetime] = None
        self.last_paid_ago: Optional[int] = None  # used for sorting
        self.last_paid_ago_str: Optional[str] = None  # used for displaying
        self.next_payment_block: Optional[int] = None
        self.next_payment_ts: Optional[int] = None
        self.next_payment_dt: Optional[datetime] = None
        self.next_payment_in: Optional[int] = None  # used for sorting
        self.next_payment_in_str: Optional[str] = None  # used for displaying
        self.messages: List[str] = []

    def clear(self):
        self.status_warning = False
        self.operator_key_update_required = False
        self.operator_service_update_required = False
        self.ip_port_mismatch = False
        self.protx_mismatch = False
        self.collateral_tx_mismatch = False
        self.collateral_address_mismatch = False
        self.owner_public_address_mismatch = False
        self.operator_pubkey_mismatch = False
        self.voting_public_address_mismatch = False
        self.payout_address = None
        self.payout_addr_balance = 0
        self.operator_payout_address = None
        self.operator_payout_addr_balance = 0
        self.collateral_addr_balance = 0
        self.last_paid_block = None
        self.last_paid_ts = None
        self.last_paid_dt = None
        self.last_paid_ago = None
        self.last_paid_ago_str = None
        self.next_payment_block = None
        self.next_payment_ts = None
        self.next_payment_dt = None
        self.next_payment_in = None
        self.next_payment_in_str = None
        self.messages.clear()

    def is_error(self):
        return self.not_found or re.match(r".*BAN.*", self.status, re.IGNORECASE)

    def is_warning(self):
        return self.operator_key_update_required or self.operator_service_update_required or self.ip_port_mismatch or \
               self.protx_mismatch or self.collateral_tx_mismatch or self.collateral_address_mismatch or \
               self.owner_public_address_mismatch or self.operator_pubkey_mismatch or \
               self.voting_public_address_mismatch or self.pose_penalty

    def get_status(self):
        if self.status:
            return self.status
        else:
            if self.not_found:
                return 'DOES NOT EXIST'
