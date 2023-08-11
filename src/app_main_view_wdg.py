#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2021-04
from __future__ import annotations
import hashlib
import logging
import re
import sys
import threading
import time
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, List, Dict, Any, Tuple

import requests
from PyQt5 import QtCore, QtGui
from PyQt5.QtCore import pyqtSlot, Qt, QTimer, QVariant, QModelIndex, QPoint, QUrl, QItemSelectionModel, QItemSelection
from PyQt5.QtGui import QPalette, QColor, QDesktopServices
from PyQt5.QtWidgets import QWidget, QMessageBox, QApplication, QTableView, QItemDelegate, QMenu

import app_cache
import app_utils
import hw_intf
from app_config import AppConfig, MasternodeConfig, MasternodeType, DMN_ROLE_OWNER, DMN_ROLE_OPERATOR, DMN_ROLE_VOTING
from app_defs import COLOR_ERROR_STR, COLOR_WARNING_STR, COLOR_ERROR, COLOR_WARNING, \
    AppTextMessageType, SCREENSHOT_MODE
from common import CancelException
from dashd_intf import DashdInterface, Masternode
from ext_item_model import ExtSortFilterItemModel, TableModelColumn, HorizontalAlignment
from masternode_details_wdg import WdgMasternodeDetails
from ui import ui_app_main_view_wdg
from wnd_utils import WndUtils, ReadOnlyTableCellDelegate, SpinnerWidget, IconTextItemDelegate, \
    QDetectThemeChange, get_widget_font_color_blue, get_widget_font_color_green

CACHE_ITEM_SHOW_MN_DETAILS_PANEL = 'MainWindow_ShowMNDetailsPanel'
CACHE_ITEM_SHOW_NET_MNS_FILTER_PANEL = 'MainWindow_ShowNetMNsFilterPanel'
CACHE_ITEM_NET_MNS_FILTER_CONDITION = 'MainWindow_NetMNsFilterCondition'
CACHE_ITEM_NET_MNS_FILTER_CTRL_PREFIX = 'MainWindow_NetMNsFilter_'
DASH_PRICE_FETCH_INTERVAL_SECONDS = 120
MN_BALANCE_FETCH_INTERVAL_SECONDS = 240


class Pages(Enum):
    PAGE_NETWORK_INFO = 0
    PAGE_MASTERNODE_LIST = 1
    PAGE_SINGLE_MASTERNODE = 2
    PAGE_NET_MASTERNODES = 3


class FilterOperator(Enum):
    OR = 0
    AND = 1


log = logging.getLogger('dmt.main')
SORTING_MAX_VALUE_FOR_NULL = 1e10


class WdgAppMainView(QWidget, QDetectThemeChange, ui_app_main_view_wdg.Ui_WdgAppMainView):
    masternode_data_changed = QtCore.pyqtSignal()
    cur_masternode_changed = QtCore.pyqtSignal(object)
    app_text_message_sent = QtCore.pyqtSignal(int, str, object)

    def __init__(self, parent, app_config: AppConfig, dashd_intf: DashdInterface, hw_session: hw_intf.HwSessionInfo):
        QWidget.__init__(self, parent)
        QDetectThemeChange.__init__(self)
        self.current_view = Pages.PAGE_MASTERNODE_LIST
        self.main_window = parent
        self.app_config = app_config
        self.dashd_intf = dashd_intf
        self.hw_session = hw_session
        self.cur_masternode: Optional[MasternodeConfig] = None
        self.edited_masternode: Optional[MasternodeConfig] = None
        self.editing_enabled = False
        self.cur_masternode_edited = False
        self.mns_status: Dict[MasternodeConfig, MasternodeStatus] = {}
        self.cfg_masternodes_model = MasternodesFromConfigTableModel(self, self.app_config.masternodes,
                                                                     self.mns_status, self.get_dash_amount_str)
        self.mn_list_columns_cache_name: str = ''
        self.mn_list_columns_resized_by_user = False

        self.net_masternodes: List[Masternode] = []
        self.net_masternodes_model = MasternodesFromNetworkTableModel(self, self.net_masternodes)
        self.last_net_masternodes_db_read_params_hash = ''
        self.network_masternodes_filter_visible = False
        self.net_masternodes_last_db_timestamp = 0
        self.net_mn_list_columns_cache_name: str = ''
        self.net_mn_list_columns_resized_by_user = False
        self.net_mn_list_last_where_cond = ''
        self.cur_network_masternode: Optional[Masternode] = None
        self.network_masternodes_enabled: bool = self.app_config.is_network_masternodes_enabled()

        self.refresh_status_thread_ref = None
        self.refresh_price_thread_ref = None
        self.refresh_net_mnasternodes_thred_ref = None
        self.refresh_status_count = 0
        self.network_status: NetworkStatus = NetworkStatus()
        self.loading_data_spinner: Optional[SpinnerWidget] = None
        self.mn_details_panel_visible = True
        self.mnu_masternode_actions = QMenu()
        self.finishing = False
        self.mn_view_column_delegates: Dict[int, QItemDelegate] = {}
        self.mn_info_by_mn_cfg: Dict[MasternodeConfig, Masternode] = {}
        self.wdg_masternode = WdgMasternodeDetails(self, self.app_config, self.dashd_intf, self.hw_session)
        self.last_dash_price_usd = None
        self.last_dash_price_fetch_ts = 0
        self.setupUi(self)

    def setupUi(self, widget: QWidget):
        ui_app_main_view_wdg.Ui_WdgAppMainView.setupUi(self, self)
        self.lblNoMasternodeMessage.setVisible(False)
        self.lblNavigation1.linkActivated.connect(self.on_cur_tab_link_activated)
        self.lblNavigation2.linkActivated.connect(self.on_cur_tab_link_activated)
        self.lblNavigation3.linkActivated.connect(self.on_cur_tab_link_activated)
        self.lblNavigation4.linkActivated.connect(self.on_cur_tab_link_activated)
        self.lblNoMasternodeMessage.linkActivated.connect(self.on_cur_tab_link_activated)
        WndUtils.set_icon(self, self.btnMoveMnUp, 'arrow-downward@16px.png', 180)
        WndUtils.set_icon(self, self.btnMoveMnDown, 'arrow-downward@16px.png')
        if sys.platform == 'win32':
            self.pnlNavigation.layout().setSpacing(12)
            self.layMasternodesControl.layout().setSpacing(12)

        l = self.frmMasternodeDetails.layout()
        l.insertWidget(1, self.wdg_masternode)
        self.wdg_masternode.setVisible(True)
        self.wdg_masternode.data_changed.connect(self.on_mn_data_changed)
        self.stackedWidget.setCurrentIndex(self.current_view.value)
        l = self.pnlNavigation.layout()
        self.loading_data_spinner = SpinnerWidget(self.pnlNavigation, 18,
                                                  'Fetching data from the network, please wait...')
        self.loading_data_spinner.hide()
        l.insertWidget(l.indexOf(self.btnMoveMnDown) + 1, self.loading_data_spinner)
        self.wdg_masternode.app_text_message_sent.connect(self.on_app_text_message_sent)

        # set up the masternodes from config list view
        self.viewMasternodes.setSortingEnabled(True)
        self.viewMasternodes.setItemDelegate(ReadOnlyTableCellDelegate(self.viewMasternodes))
        self.viewMasternodes.verticalHeader().setDefaultSectionSize(
            self.viewMasternodes.verticalHeader().fontMetrics().height() + 10)
        self.cfg_masternodes_model.set_sort_column('no', Qt.AscendingOrder)
        self.cfg_masternodes_model.set_view(self.viewMasternodes)
        self.viewMasternodes.horizontalHeader().sectionResized.connect(self.on_mn_list_column_resized)
        self.viewMasternodes.selectionModel().selectionChanged.connect(self.on_cfg_mn_view_selection_changed)
        self.viewMasternodes.setContextMenuPolicy(Qt.CustomContextMenu)

        # set up the network masternodes list view
        self.viewNetMasternodes.setSortingEnabled(True)
        self.viewNetMasternodes.setItemDelegate(ReadOnlyTableCellDelegate(self.viewNetMasternodes))
        self.viewNetMasternodes.verticalHeader().setDefaultSectionSize(
            self.viewNetMasternodes.verticalHeader().fontMetrics().height() + 10)
        self.net_masternodes_model.set_sort_column('id', Qt.AscendingOrder)
        self.net_masternodes_model.set_view(self.viewNetMasternodes)
        self.viewNetMasternodes.horizontalHeader().sectionResized.connect(self.on_net_mn_list_column_resized)
        self.viewNetMasternodes.selectionModel().selectionChanged.connect(self.on_net_mn_view_selection_changed)
        self.viewNetMasternodes.setContextMenuPolicy(Qt.CustomContextMenu)

        # configure the masternode actions menu:
        self.mnu_masternode_actions.addAction(self.main_window.action_new_masternode_entry)
        self.mnu_masternode_actions.addAction(self.main_window.action_clone_masternode_entry)
        self.mnu_masternode_actions.addAction(self.main_window.action_delete_masternode_entry)
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

        self.restore_cache_settings()

        for ctrl in (self.edtNetMnsFilterIP, self.edtNetMnsFilterProtx, self.edtNetMnsFilterPayee,
                     self.edtNetMnsFilterCollateralHash, self.edtNetMnsFilterCollateralAddress,
                     self.edtNetMnsFilterOwnerAddress, self.edtNetMnsFilterVotingAddress,
                     self.edtNetMnsFilterOperatorPubkey, self.edtNetMnsFilterPlatformNodeId):
            ctrl.returnPressed.connect(self.apply_net_masternodes_filter)

        self.update_details_panel_controls()
        self.configure_mn_view_delegates()
        self.update_net_masternodes_ui()

    def on_close(self):
        """closeEvent is not fired for widgets, so this method will be called from the closeEvent method of the
        containing dialog"""
        self.save_cache_settings()
        self.stop_threads()

    def restore_cache_settings(self):
        try:
            ena = app_cache.get_value(CACHE_ITEM_SHOW_MN_DETAILS_PANEL, True, bool)
            self.mn_details_panel_visible = ena
            ena = app_cache.get_value(CACHE_ITEM_SHOW_NET_MNS_FILTER_PANEL, True, bool)
            self.network_masternodes_filter_visible = ena
            idx = app_cache.get_value(CACHE_ITEM_NET_MNS_FILTER_CONDITION, 0, int)
            if idx == 0:
                self.rbFilterTypeAnd.setChecked(True)
            else:
                self.rbFilterTypeOr.setChecked(True)
            idx = app_cache.get_value(CACHE_ITEM_NET_MNS_FILTER_CTRL_PREFIX + 'cboNetMnsFilterType', 0, int)
            if idx in (0, 1, 2):
                self.cboNetMnsFilterType.setCurrentIndex(idx)
            idx = app_cache.get_value(CACHE_ITEM_NET_MNS_FILTER_CTRL_PREFIX + 'cboNetMnsFilterStatus', 0, int)
            if idx in (0, 1, 2):
                self.cboNetMnsFilterStatus.setCurrentIndex(idx)
            ena = app_cache.get_value(CACHE_ITEM_NET_MNS_FILTER_CTRL_PREFIX + 'chbNetMnsFilterWasActiveOn', False, bool)
            self.chbNetMnsFilterWasActiveOn.setChecked(ena)
            active_date_str = app_cache.get_value(CACHE_ITEM_NET_MNS_FILTER_CTRL_PREFIX +
                                                  'edtNetMnsFilterWasActiveOn', '', str)
            if active_date_str:
                active_date = datetime.strptime(active_date_str, '%Y-%m-%d')
                self.edtNetMnsFilterWasActiveOn.setDate(active_date)
            else:
                self.edtNetMnsFilterWasActiveOn.setDate(datetime.now())

            for ctrl in (self.edtNetMnsFilterIP, self.edtNetMnsFilterProtx, self.edtNetMnsFilterPayee,
                         self.edtNetMnsFilterCollateralHash, self.edtNetMnsFilterCollateralAddress,
                         self.edtNetMnsFilterOwnerAddress, self.edtNetMnsFilterVotingAddress,
                         self.edtNetMnsFilterOperatorPubkey, self.edtNetMnsFilterPlatformNodeId):
                t = app_cache.get_value(CACHE_ITEM_NET_MNS_FILTER_CTRL_PREFIX + ctrl.objectName(), '', str)
                ctrl.setText(t)

        except Exception as e:
            log.exception(str(e))

    def save_cache_settings(self):
        app_cache.set_value(CACHE_ITEM_SHOW_MN_DETAILS_PANEL, self.mn_details_panel_visible)
        app_cache.set_value(CACHE_ITEM_SHOW_NET_MNS_FILTER_PANEL, self.network_masternodes_filter_visible)
        app_cache.set_value(CACHE_ITEM_NET_MNS_FILTER_CONDITION, 0 if self.rbFilterTypeAnd.isChecked() else 1)
        app_cache.set_value(CACHE_ITEM_NET_MNS_FILTER_CTRL_PREFIX + 'cboNetMnsFilterType',
                            self.cboNetMnsFilterType.currentIndex())
        app_cache.set_value(CACHE_ITEM_NET_MNS_FILTER_CTRL_PREFIX + 'cboNetMnsFilterStatus',
                            self.cboNetMnsFilterStatus.currentIndex())

        app_cache.set_value(CACHE_ITEM_NET_MNS_FILTER_CTRL_PREFIX + 'chbNetMnsFilterWasActiveOn',
                            self.chbNetMnsFilterWasActiveOn.isChecked())
        active_date = self.edtNetMnsFilterWasActiveOn.date()
        active_date_str = datetime.strftime(datetime(*active_date.getDate()), '%Y-%m-%d')
        app_cache.set_value(CACHE_ITEM_NET_MNS_FILTER_CTRL_PREFIX + 'edtNetMnsFilterWasActiveOn', active_date_str)

        # save text-related filter control values:
        for ctrl in (self.edtNetMnsFilterIP, self.edtNetMnsFilterProtx, self.edtNetMnsFilterPayee,
                     self.edtNetMnsFilterCollateralHash, self.edtNetMnsFilterCollateralAddress,
                     self.edtNetMnsFilterOwnerAddress, self.edtNetMnsFilterVotingAddress,
                     self.edtNetMnsFilterOperatorPubkey, self.edtNetMnsFilterPlatformNodeId):
            app_cache.set_value(CACHE_ITEM_NET_MNS_FILTER_CTRL_PREFIX + ctrl.objectName(), ctrl.text())

        self.save_cache_config_dependent()

    def save_cache_config_dependent(self):
        """Save runtime configuration (stored in cache) that is dependent on the main configuration file.
        Currently, it's the configuration of the masternode list view columns (order, widths, visibility).
        """
        if self.mn_list_columns_cache_name:
            if self.mn_list_columns_resized_by_user:
                self.cfg_masternodes_model.save_col_defs(self.mn_list_columns_cache_name)
        if self.net_mn_list_columns_cache_name:
            if self.net_mn_list_columns_resized_by_user:
                self.net_masternodes_model.save_col_defs(self.net_mn_list_columns_cache_name)

    def restore_cache_config_dependent(self):
        """Save runtime configuration (stored in cache) that is dependent on the main configuration file."""

        old_block = self.viewMasternodes.horizontalHeader().blockSignals(True)
        try:
            if not self.cfg_masternodes_model.restore_col_defs(self.mn_list_columns_cache_name):
                self.viewMasternodes.resizeColumnsToContents()
            else:
                self.cfg_masternodes_model.set_view(self.viewMasternodes)
            self.configure_mn_view_delegates()
        finally:
            self.viewMasternodes.horizontalHeader().blockSignals(old_block)

        old_block = self.viewNetMasternodes.horizontalHeader().blockSignals(True)
        try:
            if not self.net_masternodes_model.restore_col_defs(self.net_mn_list_columns_cache_name):
                self.viewNetMasternodes.resizeColumnsToContents()
            else:
                self.net_masternodes_model.set_view(self.viewNetMasternodes)
        finally:
            self.viewNetMasternodes.horizontalHeader().blockSignals(old_block)

    def configure_mn_view_delegates(self):
        # delete old column delegates for viewMasternodes
        for col_idx in self.mn_view_column_delegates.keys():
            d = self.mn_view_column_delegates[col_idx]
            del d
            self.viewMasternodes.setItemDelegateForColumn(col_idx, None)
        self.mn_view_column_delegates.clear()

        col_idx = self.cfg_masternodes_model.col_index_by_name('status')
        if col_idx is not None:
            deleg = IconTextItemDelegate(self.viewMasternodes)
            self.mn_view_column_delegates[col_idx] = deleg
            self.viewMasternodes.setItemDelegateForColumn(col_idx, deleg)

    def stop_threads(self):
        self.finishing = True
        if self.refresh_status_thread_ref:
            log.info('Waiting for refresh_status_thread to finish...')
            self.refresh_status_thread_ref.wait(5000)
        if self.refresh_price_thread_ref:
            log.info('Waiting for refresh_price_thread to finish...')
            self.refresh_price_thread_ref.wait(5000)

    def resume_threads(self):
        self.finishing = False

    def onThemeChanged(self):
        self.update_info_page()
        self.update_mn_preview()

    def configuration_to_ui(self):
        def set_cur_mn():
            try:
                self.network_status.loaded = False
                self.refresh_status_count = 0
                if self.cur_masternode and self.cur_masternode not in self.app_config.masternodes:
                    self.cur_masternode = None
                self.cfg_masternodes_model.set_masternodes(self.app_config.masternodes, self.mns_status)
                self.refresh_cfg_masternodes_view()
                self.refresh_net_masternodes_view()
                self.save_cache_config_dependent()
                h = hashlib.sha256(self.app_config.app_config_file_name.encode('ascii', 'ignore')).hexdigest()
                self.mn_list_columns_cache_name = 'MainWindow_MnListColumns_' + h[0:8]
                self.mn_list_columns_resized_by_user = False
                self.net_mn_list_columns_cache_name = 'MainWindow_NetMnListColumns_' + h[0:8]
                self.net_mn_list_columns_resized_by_user = False
                self.restore_cache_config_dependent()

                if len(self.app_config.masternodes) and not self.cur_masternode:
                    self.set_cur_cfg_masternode(self.app_config.masternodes[0])
                self.config_changed()
                self.update_navigation_panel()
                self.update_ui()
                self.update_info_page()

                if self.app_config.fetch_network_data_after_start:
                    self.refresh_network_data()
            except Exception as e:
                logging.exception(str(e))

        QTimer.singleShot(10, set_cur_mn)

    def config_changed(self):
        new_enabled = self.app_config.is_network_masternodes_enabled()

        try:
            if self.network_masternodes_enabled != new_enabled:
                if not new_enabled:
                    self.network_masternodes_enabled = new_enabled
                    if self.current_view == Pages.PAGE_NET_MASTERNODES:
                        self.current_view = Pages.PAGE_MASTERNODE_LIST
                    self.set_cur_net_masternode(None)
                    self.last_net_masternodes_db_read_params_hash = ''
                    self.net_masternodes_last_db_timestamp = 0
                    self.net_mn_list_last_where_cond = ''
                    self.net_masternodes.clear()
                else:
                    self.network_masternodes_enabled = new_enabled
                    self.refresh_net_masternodes_view()
                    self.update_navigation_panel()

            self.update_ui()
        except Exception as e:
            logging.exception(str(e))

    def is_editing_enabled(self):
        return self.editing_enabled

    def refresh_cfg_masternodes_view(self):
        self.cfg_masternodes_model.beginResetModel()
        self.cfg_masternodes_model.endResetModel()

        # restore the focused row
        if self.get_cur_masternode_from_cfg_view() != self.cur_masternode:
            old_state = self.viewMasternodes.selectionModel().blockSignals(True)
            try:
                self.set_cur_masternode_in_cfg_view(self.cur_masternode)
            finally:
                self.viewMasternodes.selectionModel().blockSignals(old_state)

    def get_cur_masternode(self) -> Optional[MasternodeConfig]:
        return self.cur_masternode

    def get_net_masternodes_sql_where_cond(self) -> str:
        if self.chbNetMnsFilterWasActiveOn.isChecked():
            active_date = self.edtNetMnsFilterWasActiveOn.date()
            dt = datetime(*active_date.getDate())
            if dt < datetime.now():
                active_date_str = datetime.strftime(dt, '%Y-%m-%d')
                cond = f"dmt_create_time < '{active_date_str}' and (dmt_deactivation_time is null or " \
                       f"dmt_deactivation_time > '{active_date_str}')"
            else:
                # actually we can't predict whhiw masternode will be active in the future, so show none
                cond = 'true=false'
        else:
            cond = 'dmt_active=1'
        return cond

    def refresh_net_masternodes_view_thread(self, _, new_hash):
        def on_start():
            self.show_loading_animation()

        try:
            WndUtils.call_in_main_thread(on_start)
            updated = []
            removed = []

            tm_begin = time.time()
            self.dashd_intf.read_masternode_data_from_db(self.net_masternodes, self.net_mn_list_last_where_cond,
                                                         updated, removed)
            self.last_net_masternodes_db_read_params_hash = new_hash
            self.net_masternodes_last_db_timestamp = self.dashd_intf.masternodes_last_db_timestamp

            diff1 = time.time() - tm_begin
            logging.info('Masternodes read time from db: ' + str(round(diff1, 2)) + 's')
        finally:
            self.refresh_net_mnasternodes_thred_ref = None

    def refresh_net_masternodes_view(self):
        def update_on_thread_finish():
            try:
                logging.info('Finished thread "refresh_net_masternodes_view_thread"')

                tm_begin = time.time()
                self.net_masternodes_model.beginResetModel()
                self.net_masternodes_model.endResetModel()
                self.apply_net_masternodes_filter()
                diff2 = time.time() - tm_begin
                self.update_net_masternodes_ui()
                logging.info('Masternodes UI refresh time: ' + str(round(diff2, 2)) + 's')

                if not self.refresh_status_thread_ref and not self.refresh_price_thread_ref and \
                   not self.refresh_net_mnasternodes_thred_ref:
                    self.hide_loading_animation()
            except Exception as e:
                logging.exception(str(e))

        if self.network_masternodes_enabled:
            try:
                self.net_mn_list_last_where_cond = self.get_net_masternodes_sql_where_cond()
                new_hash = self.dashd_intf.get_masternode_db_query_hash(self.net_masternodes,
                                                                        self.net_mn_list_last_where_cond)

                if new_hash != self.last_net_masternodes_db_read_params_hash or \
                        self.net_masternodes_last_db_timestamp != self.dashd_intf.masternodes_last_db_timestamp:

                    if self.refresh_net_mnasternodes_thred_ref is None and self.refresh_status_thread_ref is None:
                        logging.info('Starting thread "refresh_net_masternodes_view_thread"')

                        self.refresh_net_mnasternodes_thred_ref = WndUtils.run_thread(
                            self, self.refresh_net_masternodes_view_thread, (new_hash,),
                            on_thread_finish=update_on_thread_finish)
            except Exception as e:
                logging.exception(str(e))

            # restore the focused row
            if self.get_cur_masternode_from_net_view() != self.cur_network_masternode:
                if self.cur_network_masternode not in self.net_masternodes:
                    self.set_cur_net_masternode(None)
                old_state = self.viewNetMasternodes.selectionModel().blockSignals(True)
                try:
                    self.set_cur_masternode_in_net_view(self.cur_network_masternode)
                finally:
                    self.viewNetMasternodes.selectionModel().blockSignals(old_state)

    def set_cur_cfg_masternode_modified(self):
        self.refresh_cfg_masternodes_view()
        self.update_mn_preview()
        self.masternode_data_changed.emit()
        self.wdg_masternode.set_masternode(self.cur_masternode)

    def update_ui(self):
        if self.current_view.value != self.stackedWidget.currentIndex():
            self.stackedWidget.setCurrentIndex(self.current_view.value)
            self.update_navigation_panel()

        if self.current_view == Pages.PAGE_MASTERNODE_LIST:
            self.btnMoveMnUp.setVisible(True)
            self.btnMoveMnDown.setVisible(True)
            if not self.app_config.masternodes and not self.lblNoMasternodeMessage.isVisible():
                msg = '<h3>No masternodes in your configuration... <a href="add_mn">add a new one</a></h3>'
                self.lblNoMasternodeMessage.setVisible(True)
                self.lblNoMasternodeMessage.setText(msg)
                self.viewMasternodes.setVisible(False)
                self.btnMnListColumns.setVisible(False)
                self.btnMnActions.setVisible(False)
            elif self.app_config.masternodes:
                self.lblNoMasternodeMessage.setVisible(False)
                self.viewMasternodes.setVisible(True)
                self.btnMnListColumns.setVisible(True)
                self.btnMnActions.setVisible(True)
        elif self.current_view == Pages.PAGE_SINGLE_MASTERNODE:
            self.btnMoveMnUp.setVisible(False)
            self.btnMoveMnDown.setVisible(False)
            if self.cur_masternode:
                self.btnMnActions.setVisible(True)
            self.btnMnListColumns.setVisible(False)
        elif self.current_view == Pages.PAGE_NET_MASTERNODES:
            self.btnMoveMnUp.setVisible(False)
            self.btnMoveMnDown.setVisible(False)
            self.btnMnListColumns.setVisible(True)
            self.btnMnActions.setVisible(False)
        else:
            self.btnMoveMnUp.setVisible(False)
            self.btnMoveMnDown.setVisible(False)
            self.btnMnListColumns.setVisible(False)
            self.btnMnActions.setVisible(False)

        self.lblNavigation3.setVisible(self.network_masternodes_enabled)

        if self.cur_masternode and self.cur_masternode in self.app_config.masternodes:
            is_first = self.app_config.masternodes.index(self.cur_masternode) == 0
            is_last = self.app_config.masternodes.index(self.cur_masternode) == len(self.app_config.masternodes) - 1
            self.btnMoveMnUp.setEnabled(not is_first)
            self.btnMoveMnDown.setEnabled(not is_last)
        else:
            self.btnMoveMnUp.setEnabled(False)
            self.btnMoveMnDown.setEnabled(False)

        self.update_details_panel_controls()
        self.wdg_masternode.masternode_data_to_ui()
        self.update_mn_preview()
        self.update_net_masternodes_ui()

    def update_actions_state(self):
        def update_fun():
            editing = (self.editing_enabled and self.edited_masternode is not None and
                       self.current_view == Pages.PAGE_SINGLE_MASTERNODE)
            self.btnEditMn.setVisible(not editing)
            self.btnCancelEditingMn.setVisible(editing)
            self.btnApplyMnChanges.setVisible(editing)
            self.btnApplyMnChanges.setEnabled(self.cur_masternode_edited)
            self.btnEditMn.setEnabled(not self.editing_enabled and self.cur_masternode is not None)
            self.btnCancelEditingMn.setEnabled(self.editing_enabled)

        if threading.current_thread() != threading.main_thread():
            WndUtils.call_in_main_thread(update_fun)
        else:
            update_fun()

    def update_navigation_panel(self):
        tab_lbl_masternodes = 'Masternodes (config)'
        tab_lbl_mn_details = 'MN details'
        tab_lbl_network = 'Network info'
        tab_lbl_net_masternodes = 'Masternodes (network)'

        if self.current_view == Pages.PAGE_MASTERNODE_LIST:
            mns_link = f'<span style="color:black">\u25B6 <b>{tab_lbl_masternodes}</b></span>'
        else:
            if self.current_view == Pages.PAGE_SINGLE_MASTERNODE and self.editing_enabled:
                # don't allow changing view when in edit mode
                mns_link = f'<span style="color:gray">{tab_lbl_masternodes}</span>'
            else:
                mns_link = f'<a style="text-decoration:none" href="masternodes">{tab_lbl_masternodes}</a>'
        mns_link = '<span>' + mns_link + '</span>'
        self.lblNavigation1.setText(mns_link)

        if self.current_view == Pages.PAGE_SINGLE_MASTERNODE:
            mn_link = f'<span style="color:black">\u25B6 <b>{tab_lbl_mn_details}</b></span>'
        else:
            if not self.cur_masternode:
                mn_link = f'<span style="color:gray">{tab_lbl_mn_details}</span>'
            else:
                mn_link = f'<a style="text-decoration:none" href="masternode_details">{tab_lbl_mn_details}</a>'
        mn_link = '<span>' + mn_link + '</span>'
        self.lblNavigation2.setText(mn_link)

        if self.network_masternodes_enabled:
            if self.current_view == Pages.PAGE_NET_MASTERNODES:
                network_info_link = f'<span style="color:black">\u25B6 <b>{tab_lbl_net_masternodes}</b></span>'
            else:
                if self.current_view == Pages.PAGE_SINGLE_MASTERNODE and self.editing_enabled:
                    # don't allow changing view when in edit mode
                    network_info_link = f'<span style="color:gray">{tab_lbl_net_masternodes}</span>'
                else:
                    network_info_link = f'<a style="text-decoration:none" href="net-masternodes">{tab_lbl_net_masternodes}</a>'
            self.lblNavigation3.setText(network_info_link)

        if self.current_view == Pages.PAGE_NETWORK_INFO:
            network_info_link = f'<span style="color:black">\u25B6 <b>{tab_lbl_network}</b></span>'
        else:
            if self.current_view == Pages.PAGE_SINGLE_MASTERNODE and self.editing_enabled:
                # don't allow changing view when in edit mode
                network_info_link = f'<span style="color:gray">{tab_lbl_network}</span>'
            else:
                network_info_link = f'<a style="text-decoration:none" href="netinfo">{tab_lbl_network}</a>'
        self.lblNavigation4.setText(network_info_link)

    def update_net_masternodes_ui(self):
        cnt = self.net_masternodes_model.proxy_model.rowCount()
        if self.network_masternodes_filter_visible:
            lbl = 'hide filter'
        else:
            lbl = 'show filter'
        lbl = f'Masternodes shown: {cnt} (<a href="toggle-filter">{lbl}</a>)'

        if self.network_masternodes_filter_visible:
            lbl += f'&nbsp;&nbsp;<span style="background-color:#999999;color:white">Use \'*\' as a wildcard character</span>'
        self.lblNetMasternodesInfo.setText(lbl)

        if self.network_masternodes_filter_visible and not self.frameNetMnsTop.isVisible():
            self.frameNetMnsTop.setVisible(True)
            self.gbFilterCondType.setVisible(True)
        elif not self.network_masternodes_filter_visible and self.frameNetMnsTop.isVisible():
            self.frameNetMnsTop.setVisible(False)
            self.gbFilterCondType.setVisible(False)

        self.edtNetMnsFilterWasActiveOn.setEnabled(self.chbNetMnsFilterWasActiveOn.isChecked())

    def update_info_page(self):
        gi = self.network_status
        try:
            # palette = self.palette()
            # bg_color = palette.color(QPalette.Normal, palette.Window)
            value_color = get_widget_font_color_blue(self)

            status = (
                '<style>td {white-space:nowrap;padding-right:8px;padding-top:4px}'
                '.title {text-align:right;font-weight:normal}'
                f'.value {{color:{value_color}}}'
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

            if (self.app_config.is_mainnet or SCREENSHOT_MODE) and self.app_config.show_dash_value_in_fiat:
                price_str = app_utils.to_string(self.last_dash_price_usd) if self.last_dash_price_usd is not None \
                    else '?'
                status += f'<tr><td class="title">Dash price (Kraken)</td><td class="value">{price_str} USD</td></tr>'

            status += '</table>'
            self.lblNetworkInfo.setText(status)
        except Exception as e:
            log.exception(str(e))

    def update_mn_preview(self):
        status_lines = []

        # def add_status_line(label: str, value: str, value_color: Optional[str] = None):
        def add_status_line(lines: List[Tuple[str, str, Optional[str]]]):
            ls = ''
            for idx, (label, value, value_color) in enumerate(lines):
                if idx > 0:
                    color = f'style="color:{value_color}"' if value_color else ''
                    ls += f'&nbsp;&nbsp;|&nbsp;&nbsp;<span class="title">{label + ": " if label else ""}</span>' \
                          f'<span class="value" {color}>{value}</span>'

            label, value, value_color = lines[0]
            color = f'style="color:{value_color}"' if value_color else ''
            status_lines.append(f'<tr><td class="title">{label + ": " if label else ""} </td><td colspan="2">'
                                f'<span class="value" {color}>{value}</span>{ls}</td></tr>')

        def short_address_str(addr: str, chars_begin_end: int) -> str:
            if not addr:
                return 'empty'
            else:
                if len(addr) <= chars_begin_end:
                    return addr
                else:
                    return addr[:chars_begin_end] + '..' + addr[-chars_begin_end:]

        value_color = self.app_config.get_widget_font_color_blue(self)
        link_color = self.app_config.get_hyperlink_font_color(self)
        status = ''
        if self.current_view in (Pages.PAGE_MASTERNODE_LIST, Pages.PAGE_SINGLE_MASTERNODE):
            mn = self.cur_masternode
            if mn:
                st = self.mns_status.get(mn)
                if st:
                    errors: List[str] = []
                    warnings: List[str] = []

                    if st.protx_conf_pending:
                        add_status_line([('', '<b>Protx transaction pending, please wait...</b>',
                                         self.app_config.get_widget_font_color_blue(self.viewMasternodes))])
                    if st.is_error():
                        status_color = COLOR_ERROR_STR
                    elif st.is_warning():
                        status_color = COLOR_WARNING_STR
                    else:
                        status_color = self.app_config.get_widget_font_color_green(self.viewMasternodes)
                    status_text = st.get_status()
                    if st.pose_penalty:
                        status_text += ', PoSePenalty: ' + str(st.pose_penalty)
                        if st.pose_ban_timestamp is not None and st.pose_ban_timestamp > 0:
                            status_text += ', PoSeBan time: ' + \
                                           app_utils.to_string(datetime.fromtimestamp(st.pose_ban_timestamp))
                    add_status_line([('Status', status_text, status_color)])

                    if st.payout_address:
                        url = self.app_config.get_block_explorer_addr().replace('%ADDRESS%', st.payout_address)
                        link = '<a href="%s">%s</a>' % (url, st.payout_address)
                    else:
                        link = ''
                    add_status_line([('Payout address', link, None)])

                    add_status_line([('Payout addr. balance',
                                    self.get_dash_amount_str(st.payout_addr_balance, True, True, True, True), None)])

                    if mn.collateral_address.strip() and mn.collateral_address.strip() != st.payout_address:
                        url = self.app_config.get_block_explorer_addr().replace('%ADDRESS%',
                                                                                mn.collateral_address.strip())
                        link = '<a href="%s">%s</a>' % (url, mn.collateral_address.strip())
                        add_status_line([('Collateral address', link, None)])

                        add_status_line([('Collateral addr. balance',
                                          self.get_dash_amount_str(st.collateral_addr_balance, True, True, True, True),
                                          None)])

                    if st.operator_payout_address:
                        url = self.app_config.get_block_explorer_addr().replace('%ADDRESS%', st.operator_payout_address)
                        link = '<a href="%s">%s</a>' % (url, st.operator_payout_address)
                        add_status_line([('Operator payout address', link, None)])

                    if st.last_paid_dt:
                        lp = app_utils.to_string(st.last_paid_dt)
                        if st.last_paid_block:
                            lp += ' / block# ' + str(st.last_paid_block)
                        if st.last_paid_ago_str:
                            lp += ' / ' + st.last_paid_ago_str
                        add_status_line([('Last paid', lp, None)])

                    if st.next_payment_dt:
                        np = app_utils.to_string(st.next_payment_dt)
                        if st.next_payment_block:
                            np += ' / block# ' + str(st.next_payment_block)
                        if st.next_payment_in_str:
                            np += ' / ' + st.next_payment_in_str
                        add_status_line([('Next payment', np, None)])

                    if not st.protx_conf_pending:
                        if st.operator_service_update_required:
                            errors.append('Operator service update required')
                        if st.operator_key_update_required:
                            errors.append('Operator key update required')
                        if st.ip_port_mismatch and not st.operator_service_update_required:
                            warnings.append('Masternode IP/port mismatch between config and the network')
                        if st.collateral_tx_mismatch:
                            warnings.append('Collateral tx mismatch between config and the network')
                        if st.collateral_address_mismatch:
                            warnings.append('Collateral address mismatch between config and the network')
                        if st.protx_mismatch:
                            warnings.append(f'Protx mismatch (<a href="copy_protx_to_config">use the value from '
                                            f'the network in the configuration</a>)')
                        if st.owner_public_address_mismatch:
                            warnings.append(
                                f'Owner address mismatch (config: '
                                f'{short_address_str(mn.get_owner_public_address(self.app_config.dash_network), 6)} '
                                f'[<a href="copy_owner_addr_cfg">copy</a>], '
                                f'network: {short_address_str(st.network_owner_public_address, 6)} '
                                f'[<a href="copy_owner_addr_net">copy</a>])')
                        if st.operator_pubkey_mismatch:
                            warnings.append(
                                f'Operator public key mismatch (config: {short_address_str(mn.get_operator_pubkey(self.app_config.feature_new_bls_scheme.get_value()), 6)} '
                                f'[<a href="copy_operator_key_cfg">copy</a>], '
                                f'network: {short_address_str(st.network_operator_public_key, 6)}'
                                f'[<a href="copy_operator_key_net">copy</a>])')
                        if st.voting_public_address_mismatch:
                            warnings.append(
                                f'Voting address mismatch (config: '
                                f'{short_address_str(mn.get_voting_public_address(self.app_config.dash_network), 6)} '
                                f'[<a href="copy_voting_addr_cfg">copy</a>], '
                                f'network: {short_address_str(st.network_voting_public_address, 6)}'
                                f'[<a href="copy_voting_addr_net">copy</a>])')
                        if st.masternode_type_mismatch:
                            warnings.append(
                                f'Masternode type mismatch (config: {mn.masternode_type.name}, '
                                f'network: {st.masternode_type.name})')
                        if st.platform_node_id_mismatch and not st.operator_service_update_required:
                            warnings.append(
                                f'Platform Node Id mismatch (config: {short_address_str(mn.get_platform_node_id(), 6)}, '
                                f'network: {short_address_str(st.platform_node_id, 6)})')
                        if st.platform_p2p_port_mismatch:
                            warnings.append(
                                f'Platform P2P port mismatch (config: {mn.platform_p2p_port}, '
                                f'network: {st.platform_p2p_port})')
                        if st.platform_http_port_mismatch:
                            warnings.append(
                                f'Platform HTTP port mismatch (config: {mn.platform_http_port}, '
                                f'network: {st.platform_http_port})')

                    for idx, val in enumerate(errors):
                        if idx == 0:
                            label = 'Errors'
                        else:
                            label = ''
                        add_status_line([(label, val, COLOR_ERROR_STR)])

                    for idx, val in enumerate(warnings):
                        if idx == 0:
                            label = 'Warnings'
                        else:
                            label = ''
                        add_status_line([(label, val, COLOR_WARNING_STR)])
                else:
                    if self.refresh_status_count == 0:
                        if self.refresh_status_thread_ref:
                            status = 'Fetching data from the network, please wait...'
                        else:
                            status = 'Status data will be available after fetching data from the network'
        elif self.current_view == Pages.PAGE_NET_MASTERNODES:
            mn = self.cur_network_masternode
            if mn:
                add_status_line([('IP/port', mn.ip_port, None), ('Type', mn.type, None), ('Status', mn.status, None)])
                add_status_line([('Protx hash', mn.protx_hash, None)])
                add_status_line([('Ident', mn.ident, None)])
                add_status_line([('Payout address', mn.payout_address, None)])
                add_status_line([('Collateral address', mn.collateral_address, None)])
                add_status_line([('Owner address', mn.owner_address, None),
                                 ('Voting address', mn.voting_address, None)])
                add_status_line([('Operator pubkey', mn.pubkey_operator, None)])
                add_status_line([('Operator reward', str(mn.operator_reward), None),
                                 ('Operator payout address', mn.operator_payout_address if mn.operator_payout_address else '&lt;empty&gt;', None)])
                add_status_line([('Platform Node Id', mn.platform_node_id if mn.platform_node_id else '&lt;empty&gt;', None),
                                 ('Platform P2P port', str(mn.platform_p2p_port) if mn.platform_p2p_port else '&lt;empty&gt;', None),
                                 ('Platform HTTP port', str(mn.platform_http_port) if mn.platform_http_port else '&lt;empty&gt;', None)])
                add_status_line([('PoSe penalty', str(mn.pose_penalty) if mn.pose_penalty is not None else '&lt;empty&gt;', None),
                                 ('PoSe ban height', str(mn.pose_ban_height) if mn.pose_ban_height is not None else '&lt;empty&gt;', None),
                                 ('PoSe ban time', app_utils.to_string(datetime.fromtimestamp(mn.pose_ban_timestamp)) if mn.pose_ban_timestamp is not None and mn.pose_ban_timestamp > 0 else '&lt;empty&gt;', None),
                                 ('Payment queue position', str(mn.queue_position) if mn.queue_position is not None else '&lt;empty&gt;', None)])

        if not status:
            status = f"""<style>td {{white-space:nowrap;padding-right:8px}}
                .title {{text-align:right;font-weight:bold;display:block;}}
                span.title {{margin-right:10px;display:block;}}
                a {{color: {link_color}}}
                .ago {{font-style:normal}}
                .value {{color:{value_color}}}
                span.value {{padding-right:10px}}
                .error {{color:{COLOR_ERROR_STR} }}
                .warning {{color:{COLOR_WARNING_STR} }}
                </style>
                <table> {''.join(status_lines) }</table>"""

        self.lblMnStatus.setText(status)
        # self.textBrowser.setHtml(status)

    @pyqtSlot(str)
    def on_lblNetMasternodesInfo_linkActivated(self, _):
        self.network_masternodes_filter_visible = not self.network_masternodes_filter_visible
        self.update_net_masternodes_ui()

    @pyqtSlot(int, str, object)
    def on_app_text_message_sent(self, msg_id: int, text: str, type: AppTextMessageType):
        # forward text message to the caller window (main dialog)
        self.app_text_message_sent.emit(msg_id, text, type)

    @pyqtSlot(int)
    def on_chbNetMnsFilterWasActiveOn_stateChanged(self, _):
        self.update_net_masternodes_ui()

    @pyqtSlot(str)
    def on_cur_tab_link_activated(self, link):
        try:
            if link == 'netinfo':
                self.current_view = Pages.PAGE_NETWORK_INFO
            elif link == 'masternodes':
                self.current_view = Pages.PAGE_MASTERNODE_LIST
            elif link == 'masternode_details':
                self.current_view = Pages.PAGE_SINGLE_MASTERNODE
            elif link == 'net-masternodes':
                self.current_view = Pages.PAGE_NET_MASTERNODES
            elif link == 'add_mn':
                self.add_new_masternode(None)
                return
            self.update_navigation_panel()
            self.update_ui()
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    def on_mn_list_column_resized(self, logical_index, old_size, new_size):
        self.mn_list_columns_resized_by_user = True

    def on_net_mn_list_column_resized(self, logical_index, old_size, new_size):
        self.net_mn_list_columns_resized_by_user = True

    def on_mn_data_changed(self):
        if self.cur_masternode or self.edited_masternode:
            self.cur_masternode_edited = True
            try:
                mn_info = self.mn_info_by_mn_cfg.get(self.cur_masternode)
                ms = self.mns_status.get(self.cur_masternode)
                if mn_info and ms:
                    ms.check_mismatch(self.cur_masternode, mn_info)
            except Exception:
                pass
        self.refresh_cfg_masternodes_view()
        self.update_mn_preview()
        self.masternode_data_changed.emit()
        self.update_actions_state()

    @pyqtSlot(bool)
    def on_btnEditMn_clicked(self):
        try:
            self.edit_masternode()
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnCancelEditingMn_clicked(self):
        try:
            self.cancel_masternode_changes()
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnApplyMnChanges_clicked(self):
        try:
            self.apply_masternode_changes()
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnMnListColumns_clicked(self):
        if self.current_view == Pages.PAGE_MASTERNODE_LIST:
            self.cfg_masternodes_model.exec_columns_dialog(self)
        elif self.current_view == Pages.PAGE_NET_MASTERNODES:
            self.net_masternodes_model.exec_columns_dialog(self)

    def verify_sorting_for_mn_reorder(self) -> bool:
        col = self.cfg_masternodes_model.get_sort_column()
        if col and col.name == 'no':
            order = self.cfg_masternodes_model.get_sort_order()
            if order == Qt.AscendingOrder:
                return True
        else:
            return False

    @pyqtSlot(bool)
    def on_btnMoveMnUp_clicked(self):
        try:
            if not self.verify_sorting_for_mn_reorder():
                WndUtils.error_msg('To reorder masternode entries, you have to sort them by the first column '
                                   '(order no).')
                return

            mns = self.app_config.masternodes
            if self.cur_masternode and self.cur_masternode in mns:
                cur_idx = mns.index(self.cur_masternode)
                if cur_idx > 0:
                    mns[cur_idx-1], mns[cur_idx] = mns[cur_idx], mns[cur_idx-1]
                    self.refresh_cfg_masternodes_view()
                    self.masternode_data_changed.emit()
                    self.update_ui()
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(bool)
    def on_btnMoveMnDown_clicked(self):
        try:
            if not self.verify_sorting_for_mn_reorder():
                WndUtils.error_msg('To reorder masternode entries, you have to sort them by the first column '
                                   '(order no).')
                return

            mns = self.app_config.masternodes
            if self.cur_masternode and self.cur_masternode in mns:
                cur_idx = mns.index(self.cur_masternode)
                if cur_idx < len(mns) - 1:
                    mns[cur_idx+1], mns[cur_idx] = mns[cur_idx], mns[cur_idx+1]
                    self.refresh_cfg_masternodes_view()
                    self.masternode_data_changed.emit()
                    self.update_ui()
        except Exception as e:
            WndUtils.error_msg(str(e), True)

    @pyqtSlot(str)
    def on_lblMnStatusLabel_linkActivated(self, link: str):
        self.mn_details_panel_visible = not self.mn_details_panel_visible
        self.update_details_panel_controls()

    @pyqtSlot(str)
    def on_lblMnStatus_linkActivated(self, link: str):
        if self.cur_masternode:
            cl = QApplication.clipboard()
            if link == 'copy_protx_to_config':
                mn_info: Masternode = self.mn_info_by_mn_cfg.get(self.cur_masternode)
                ms = self.mns_status.get(self.cur_masternode)
                if mn_info and mn_info.protx_hash and ms:
                    self.cur_masternode.protx_hash = mn_info.protx_hash
                    self.cur_masternode.modified = True
                    ms.check_mismatch(self.cur_masternode, mn_info)
                    self.set_cur_cfg_masternode_modified()

            elif link == 'copy_owner_addr_cfg':
                cl.setText(self.cur_masternode.get_owner_public_address(self.app_config.dash_network))

            elif link == 'copy_owner_addr_net':
                ms = self.mns_status.get(self.cur_masternode)
                if ms:
                    cl.setText(ms.network_owner_public_address)

            elif link == 'copy_operator_key_cfg':
                cl.setText(self.cur_masternode.get_operator_pubkey(self.app_config.feature_new_bls_scheme.get_value()))

            elif link == 'copy_operator_key_net':
                ms = self.mns_status.get(self.cur_masternode)
                if ms:
                    cl.setText(ms.network_operator_public_key)

            elif link == 'copy_voting_addr_cfg':
                cl.setText(self.cur_masternode.get_voting_public_address(self.app_config.dash_network))

            elif link == 'copy_voting_addr_net':
                ms = self.mns_status.get(self.cur_masternode)
                if ms:
                    cl.setText(ms.network_voting_public_address)

            elif link.lower().find('http') >= 0:
                QDesktopServices.openUrl(QUrl(link))

    def update_details_panel_controls(self):
        lbl_visible = (self.current_view in (Pages.PAGE_SINGLE_MASTERNODE, Pages.PAGE_MASTERNODE_LIST)) or \
                      (self.current_view == Pages.PAGE_NET_MASTERNODES)
        panel_visible = lbl_visible and self.mn_details_panel_visible

        link_text = 'hide' if self.mn_details_panel_visible else 'show'
        link_color = self.app_config.get_hyperlink_font_color(self.lblMnStatusLabel)
        if self.current_view in (Pages.PAGE_SINGLE_MASTERNODE, Pages.PAGE_MASTERNODE_LIST):
            t = f'<style>a {{color: {link_color}}}</style>Masternode status details (<a href="{link_text}">{link_text}</a>)'
        else:
            t = f'<style>a {{color: {link_color}}}</style>Masternode details (<a href="{link_text}">{link_text}</a>)'
        self.lblMnStatusLabel.setText(t)
        self.lblMnStatusLabel.setVisible(lbl_visible)
        self.lblMnStatus.setVisible(panel_visible)

    @pyqtSlot(bool)
    def on_btnRefreshMnStatus_clicked(self):
        self.refresh_network_data()

    @pyqtSlot(QModelIndex)
    def on_viewMasternodes_doubleClicked(self, index):
        try:
            self.goto_masternode_details()
        except Exception as e:
            WndUtils.error_msg(str(e))

    @pyqtSlot(QPoint)
    def on_viewMasternodes_customContextMenuRequested(self, point):
        try:
            p = self.viewMasternodes.mapToGlobal(point)
            p.setY(p.y() + 12)
            self.mnu_masternode_actions.exec_(p)
        except Exception as e:
            WndUtils.error_msg(str(e))

    def goto_masternode_details(self):
        self.current_view = Pages.PAGE_SINGLE_MASTERNODE
        self.update_ui()

    def goto_masternode_list(self):
        if self.editing_enabled:
            self.set_edit_mode(False)
        self.current_view = Pages.PAGE_MASTERNODE_LIST
        self.update_navigation_panel()
        self.update_ui()

    def get_cur_masternode_from_cfg_view(self) -> Optional[MasternodeConfig]:
        mn: Optional[MasternodeConfig] = None
        cur_index = self.viewMasternodes.currentIndex()
        if cur_index:
            source_row = self.cfg_masternodes_model.mapToSource(cur_index)
            if source_row:
                current_row = source_row.row()
                if current_row is not None and 0 <= current_row < len(self.app_config.masternodes):
                    mn = self.app_config.masternodes[current_row]
        return mn

    def get_cur_masternode_from_net_view(self) -> Optional[Masternode]:
        mn: Optional[Masternode] = None
        cur_index = self.viewNetMasternodes.currentIndex()
        if cur_index:
            source_row = self.net_masternodes_model.mapToSource(cur_index)
            if source_row:
                current_row = source_row.row()
                if current_row is not None and 0 <= current_row < len(self.net_masternodes):
                    mn = self.net_masternodes[current_row]
        return mn

    def set_cur_masternode_in_cfg_view(self, mn: MasternodeConfig):
        idx = self.app_config.masternodes.index(mn)
        if idx >= 0:
            midx = self.cfg_masternodes_model.index(idx, 0)
            if midx and midx.isValid():
                self.viewMasternodes.setCurrentIndex(midx)

    def set_cur_masternode_in_net_view(self, mn: Optional[Masternode]):
        if mn:
            idx = self.net_masternodes.index(mn)
            if idx is not None and idx >= 0:
                sel = QItemSelection()
                source_row_idx = self.net_masternodes_model.index(idx, 0)
                if source_row_idx and source_row_idx.isValid():
                    dest_index = self.net_masternodes_model.mapFromSource(source_row_idx)
                    self.viewNetMasternodes.setCurrentIndex(dest_index)
                    sel.select(dest_index, dest_index)
                    self.viewNetMasternodes.selectionModel().select(
                        sel, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self.viewNetMasternodes.selectionModel().clearSelection()

    def on_cfg_mn_view_selection_changed(self, selected, deselected):
        mn = self.get_cur_masternode_from_cfg_view()
        self.set_cur_cfg_masternode(mn)

    def on_net_mn_view_selection_changed(self, selected, deselected):
        mn = self.get_cur_masternode_from_net_view()
        self.set_cur_net_masternode(mn)

    def set_cur_cfg_masternode(self, masternode: Optional[MasternodeConfig]):
        if self.cur_masternode != masternode:
            self.editing_enabled = False
            self.cur_masternode = masternode
            self.wdg_masternode.set_masternode(masternode)
            if self.get_cur_masternode_from_cfg_view() != self.cur_masternode:
                old_state = self.viewMasternodes.selectionModel().blockSignals(True)
                try:
                    self.set_cur_masternode_in_cfg_view(self.cur_masternode)
                finally:
                    self.viewMasternodes.selectionModel().blockSignals(old_state)
            self.update_ui()
            self.update_actions_state()
            self.cur_masternode_changed.emit(masternode)

    def set_cur_net_masternode(self, masternode: Optional[Masternode]):
        if self.cur_network_masternode != masternode:
            self.cur_network_masternode = masternode
            if self.get_cur_masternode_from_net_view() != self.cur_network_masternode:
                old_state = self.viewNetMasternodes.selectionModel().blockSignals(True)
                try:
                    self.set_cur_masternode_in_net_view(self.cur_network_masternode)
                finally:
                    self.viewNetMasternodes.selectionModel().blockSignals(old_state)
            self.update_ui()

    def set_edit_mode(self, editing_enabled: bool):
        self.editing_enabled = editing_enabled
        self.wdg_masternode.set_edit_mode(editing_enabled)
        if not editing_enabled:
            self.edited_masternode = None
        self.update_navigation_panel()
        self.update_actions_state()

    def edit_masternode(self):
        if not self.editing_enabled:
            if self.cur_masternode:
                self.edited_masternode = self.cur_masternode
                self.wdg_masternode.set_masternode(self.edited_masternode)
                self.set_edit_mode(True)
        else:
            WndUtils.error_msg('Editing already enabled!')

    def add_new_masternode(self, src_masternode: Optional[MasternodeConfig]):
        def mn_name_exists(name: str):
            for mn in self.app_config.masternodes:
                if mn.name == name:
                    return True

        if not self.editing_enabled:
            new_mn = MasternodeConfig()

            force_append_numbers = False
            if src_masternode:
                mn_template = src_masternode.name + '-Clone'
            else:
                if self.app_config.is_testnet:
                    new_mn.tcp_port = 19999
                mn_template = 'MN'
                force_append_numbers = True
            name_found = None

            if force_append_numbers or mn_name_exists(mn_template):
                # look for a unique mn name by adding consecutive numbers at the end
                for nr in range(1, 100):
                    if not mn_name_exists(mn_template + str(nr)):
                        name_found = mn_template + str(nr)
                        break
            else:
                name_found = mn_template

            if src_masternode:
                new_mn.copy_from(src_masternode)
            if name_found:
                new_mn.name = name_found
            new_mn.is_new = True

            self.edited_masternode = new_mn
            self.wdg_masternode.set_masternode(self.edited_masternode)
            self.goto_masternode_details()
            self.set_edit_mode(True)
            self.wdg_masternode.on_mn_data_modified()
        else:
            WndUtils.error_msg('Editing already enabled!')

    def apply_masternode_changes(self):
        if self.wdg_masternode.is_modified():
            self.wdg_masternode.get_masternode_data(self.edited_masternode)
            is_new = False
            if self.edited_masternode.is_new:
                self.edited_masternode.is_new = False
                self.app_config.add_mn(self.edited_masternode)
                self.set_cur_cfg_masternode(self.edited_masternode)
                is_new = True
            self.on_mn_data_changed()
            if is_new:
                self.goto_masternode_list()
        self.cur_masternode_edited = False
        self.set_edit_mode(False)

    def cancel_masternode_changes(self):
        if self.edited_masternode.is_new:
            self.wdg_masternode.set_masternode(self.cur_masternode)
            self.goto_masternode_list()
        else:
            if self.wdg_masternode.is_modified():
                self.wdg_masternode.set_masternode(self.cur_masternode)  # restore the original (non-modified) data
        self.cur_masternode_edited = False
        self.set_edit_mode(False)

    def delete_masternode(self, masternode: MasternodeConfig):
        if masternode and masternode in self.app_config.masternodes:
            idx = self.app_config.masternodes.index(masternode)
            try:
                if WndUtils.query_dlg(f'Do you really want to remove masternode "{masternode.name}" from configuration?',
                                  buttons=QMessageBox.Yes | QMessageBox.Cancel,
                                  default_button=QMessageBox.Cancel, icon=QMessageBox.Warning) == QMessageBox.Yes:
                    self.app_config.masternodes.remove(self.cur_masternode)
                    mn = None
                    if self.app_config.masternodes:
                        if idx > len(self.app_config.masternodes) - 1:
                            mn = self.app_config.masternodes[-1]
                        else:
                            mn = self.app_config.masternodes[idx]
                    if self.edited_masternode:
                        self.set_edit_mode(False)
                    self.set_cur_cfg_masternode(mn)
                    self.goto_masternode_list()
            except Exception as e:
                WndUtils.error_msg(str(e), True)

    def refresh_network_data(self):
        def update():
            if not self.refresh_status_thread_ref and not self.refresh_price_thread_ref and \
               not self.refresh_net_mnasternodes_thred_ref:
                self.hide_loading_animation()
            self.update_info_page()
            self.update_mn_preview()
            self.refresh_cfg_masternodes_view()
            self.refresh_net_masternodes_view()

        if not self.refresh_status_thread_ref:
            logging.info('Starting thread "refresh_status_thread"')
            self.refresh_status_thread_ref = WndUtils.run_thread(self, self.refresh_status_thread, (),
                                                                 on_thread_finish=update)

        if self.app_config.show_dash_value_in_fiat and (self.app_config.is_mainnet or SCREENSHOT_MODE):
            if not self.refresh_price_thread_ref and \
                    int(time.time()) - self.last_dash_price_fetch_ts >= DASH_PRICE_FETCH_INTERVAL_SECONDS:
                self.refresh_price_thread_ref = WndUtils.run_thread(self, self.refresh_price_thread, (),
                                                                    on_thread_finish=self.update_info_page)

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

        if masternode.protx_hash:
            try:
                protx = self.dashd_intf.protx('info', masternode.protx_hash)
                if protx:
                    protx_state = protx.get('state')
            except Exception:
                logging.exception('Cannot read protx info')

            if not protx:
                try:
                    # protx transaction is not confirmed yet, so look for it in the mempool
                    tx = self.dashd_intf.getrawtransaction(masternode.protx_hash, 1, skip_cache=True)
                    confirmations = tx.get('confirmations', 0)
                    if confirmations < 3:
                        # in this case, dmn tx should have been found by the 'protx info' call above;
                        # it hasn't been, so it is no longer valid a protx transaction
                        ptx = tx.get('proRegTx')
                        if ptx:
                            protx = {
                                'proTxHash': masternode.protx_hash,
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
                except Exception:
                    pass

        if not (protx_state and ((protx_state.get('service') == masternode.ip + ':' + str(masternode.tcp_port)) or
                                 (protx.get('collateralHash') == masternode.collateral_tx and
                                  str(protx.get('collateralIndex')) == str(masternode.collateral_tx_index)))):
            try:
                if not protx_list_registered:
                    protx_list_registered.extend(self.dashd_intf.protx('list', 'registered', True))

                for protx in protx_list_registered:
                    protx_state = protx.get('state')
                    if (protx_state and ((protx_state.get('service') == masternode.ip + ':' + str(masternode.tcp_port)) or
                                         (protx.get('collateralHash') == masternode.collateral_tx and
                                          str(protx.get('collateralIndex')) == str(masternode.collateral_tx_index)))):
                        return protx
            except Exception:
                pass
        else:
            return protx
        return None

    def refresh_status_thread(self, _):
        def on_start():
            self.show_loading_animation()
            self.update_mn_preview()

        def check_finishing():
            if self.finishing:
                raise CancelException()

        try:
            check_finishing()
            WndUtils.call_in_main_thread(on_start)

            # check if any of the masternodes from config had waited protx transaction; if so, we will minimize
            # the cache max data age attribute
            cache_max_age = 60
            for mn_cfg in self.mns_status:
                mn_stat = self.mns_status[mn_cfg]
                if mn_stat.protx_conf_pending:
                    cache_max_age = 1

            self.dashd_intf.get_masternodelist('json', data_max_age=cache_max_age, feedback_fun=check_finishing)
            check_finishing()

            block_height = self.dashd_intf.getblockcount()
            check_finishing()

            mns_cfg_list = list(self.app_config.masternodes)
            for mn_cfg in mns_cfg_list:
                assert isinstance(mn_cfg, MasternodeConfig)
                check_finishing()
                mn_stat = self.mns_status.get(mn_cfg)
                if not mn_stat:
                    mn_stat = MasternodeStatus(self.app_config.dash_network,
                                               self.app_config.feature_new_bls_scheme.get_value())
                    self.mns_status[mn_cfg] = mn_stat

                if mn_cfg.collateral_tx and str(mn_cfg.collateral_tx_index):
                    collateral_id = mn_cfg.collateral_tx + '-' + str(mn_cfg.collateral_tx_index)
                else:
                    collateral_id = None
                if mn_cfg.ip and mn_cfg.tcp_port:
                    ip_port = mn_cfg.ip + ':' + str(mn_cfg.tcp_port)
                else:
                    ip_port = None

                mn_stat.not_found = False
                if not collateral_id and not ip_port:
                    if not mn_cfg.collateral_tx:
                        mn_stat.not_found = True
                        continue

                if collateral_id:
                    mn_info = self.dashd_intf.masternodes_by_ident.get(collateral_id)
                elif ip_port:
                    mn_info = self.dashd_intf.masternodes_by_ip_port.get(ip_port)
                else:
                    mn_info = None

                if not mn_info:
                    mn_stat.not_found = True
                    continue
                self.mn_info_by_mn_cfg[mn_cfg] = mn_info

                mn_stat.status = mn_info.status
                if mn_info.queue_position:
                    mn_stat.next_payment_block = block_height + mn_info.queue_position + 1
                    mn_stat.next_payment_ts = int(time.time()) + (mn_info.queue_position * 2.5 * 60)
                else:
                    mn_stat.next_payment_block = None
                    mn_stat.next_payment_ts = None

                if mn_info.status == 'ENABLED' or mn_info.status == 'PRE_ENABLED':
                    mn_stat.status_warning = False
                else:
                    mn_stat.status_warning = True

                mn_stat.masternode_type = {
                    'HighPerformance': MasternodeType.HPMN,
                    'Regular': MasternodeType.REGULAR
                }.get(mn_info.type, MasternodeType.REGULAR)

                if mn_info.pose_penalty:
                    mn_stat.pose_penalty = mn_info.pose_penalty
                    mn_stat.status_warning = True
                    mn_stat.pose_ban_height = mn_info.pose_ban_height
                    mn_stat.pose_ban_timestamp = mn_info.pose_ban_timestamp
                else:
                    mn_stat.pose_penalty = 0

                if mn_info.pubkey_operator and re.match('^0+$', mn_info.pubkey_operator):
                    no_operator_pub_key = True
                else:
                    no_operator_pub_key = False

                mn_stat.operator_key_update_required = False
                mn_stat.operator_service_update_required = False
                if mn_info.ip_port in ('[0:0:0:0:0:0:0:0]:0', '[::]:0'):
                    if no_operator_pub_key:
                        mn_stat.operator_key_update_required = True
                    else:
                        mn_stat.operator_service_update_required = True

                mn_stat.platform_node_id = mn_info.platform_node_id
                mn_stat.platform_p2p_port = mn_info.platform_p2p_port
                mn_stat.platform_http_port = mn_info.platform_http_port

                mn_stat.check_mismatch(mn_cfg, mn_info)

            check_finishing()
            # in the mn list view show the data that has been read so far
            WndUtils.call_in_main_thread(self.refresh_cfg_masternodes_view)

            # fetch non-cachaed data
            check_finishing()
            self.fetch_governance_info()
            check_finishing()

            try:
                log.info('fetch_mempool_txes start')
                self.dashd_intf.fetch_mempool_txes(check_finishing)
                log.info('fetch_mempool_txes finish')
            except CancelException:
                raise
            except Exception as e:
                # sometimes the `getrawmempool` results in error "'NoneType' object has no attribute 'settimeout'
                # suppress the error message as it is not as importand;
                log.exception(str(e))

            check_finishing()
            self.network_status.mempool_entries_count = len(self.dashd_intf.mempool_txes)
            log.info('get address balances start')
            for mn_cfg in mns_cfg_list:
                check_finishing()
                mn_stat = self.mns_status.get(mn_cfg)
                mn_info: Optional[Masternode] = self.mn_info_by_mn_cfg.get(mn_cfg)
                if not mn_info:
                    continue

                if int(time.time()) - mn_stat.last_addr_balance_fetch_ts >= MN_BALANCE_FETCH_INTERVAL_SECONDS:
                    if not mn_stat.collateral_address_mismatch and mn_cfg.collateral_address:
                        try:
                            coll_bal = self.dashd_intf.getaddressbalance([mn_cfg.collateral_address])
                            mn_stat.collateral_addr_balance = round(coll_bal.get('balance') / 1e8, 5)
                        except Exception as e:
                            log.exception(str(e))

                    if mn_info.payout_address:
                        try:
                            mn_stat.payout_address = mn_info.payout_address
                            payout_bal = self.dashd_intf.getaddressbalance([mn_info.payout_address])
                            mn_stat.payout_addr_balance = round(payout_bal.get('balance') / 1e8, 5)
                        except Exception as e:
                            log.exception(str(e))

                    if mn_info.operator_payout_address:
                        try:
                            mn_stat.operator_payout_address = mn_info.operator_payout_address
                            if mn_info.operator_payout_address != mn_info.payout_address:
                                payout_bal = self.dashd_intf.getaddressbalance([mn_info.operator_payout_address])
                                mn_stat.operator_payout_addr_balance = round(payout_bal.get('balance') / 1e8, 5)
                            else:
                                mn_stat.operator_payout_addr_balance = mn_stat.payout_addr_balance
                        except Exception as e:
                            log.exception(str(e))
                    mn_stat.last_addr_balance_fetch_ts = int(time.time())

                mn_stat.last_paid_ts = 0
                if mn_info.lastpaidtime > time.time() - 3600 * 24 * 365:
                    # fresh dmns have lastpaidtime set to some day in the year 2014
                    mn_stat.last_paid_ts = mn_info.lastpaidtime

                if mn_info.lastpaidblock and mn_info.lastpaidblock > 0:
                    prev_last_paid_block = mn_stat.last_paid_block
                    if not prev_last_paid_block or prev_last_paid_block != mn_info.lastpaidblock:
                        mn_stat.last_paid_block = mn_info.lastpaidblock
                        if not mn_stat.last_paid_ts:
                            mn_stat.last_paid_ts = self.dashd_intf.get_block_timestamp(mn_stat.last_paid_block)

                if mn_stat.last_paid_ts:
                    mn_stat.last_paid_dt = datetime.fromtimestamp(float(mn_stat.last_paid_ts))
                    mn_stat.last_paid_ago = int(time.time()) - int(mn_stat.last_paid_ts)
                    ago_str = app_utils.seconds_to_human(mn_stat.last_paid_ago, out_unit_auto_adjust=True)
                    mn_stat.last_paid_ago_str = ago_str + ' ago' if ago_str else ''

                if mn_stat.next_payment_block and mn_stat.next_payment_ts:
                    mn_stat.next_payment_dt = datetime.fromtimestamp(float(mn_stat.next_payment_ts))
                    mn_stat.next_payment_in = mn_stat.next_payment_ts - int(time.time())
                    in_str = app_utils.seconds_to_human(mn_stat.next_payment_in, out_unit_auto_adjust=True)
                    mn_stat.next_payment_in_str = 'in ' + in_str if in_str else ''

                if self.dashd_intf.is_protx_update_pending(mn_info.protx_hash, mn_info.ip_port):
                    mn_stat.protx_conf_pending = True
                else:
                    mn_stat.protx_conf_pending = False
            log.info('get address balances finish')

            self.refresh_status_count += 1

        except CancelException:
            log.info('Stopping the fetch data thread...')

        except Exception as e:
            if not self.finishing:
                log.exception(str(e))
                WndUtils.call_in_main_thread(WndUtils.error_msg, str(e))

        finally:
            self.refresh_status_thread_ref = None

    def refresh_price_thread(self, _):
        try:
            if self.app_config.show_dash_value_in_fiat and (self.app_config.is_mainnet or SCREENSHOT_MODE):
                resp = requests.get('https://api.kraken.com/0/public/Ticker?pair=DASHUSD')
                j = resp.json()
                r = j.get('result')
                if r:
                    r = r.get('DASHUSD')
                    if r:
                        c = r.get('c')
                        if c:
                            v = float(c[0])
                            self.last_dash_price_usd = v

            self.last_dash_price_fetch_ts = int(time.time())
        except Exception as e:
            log.info('Error when fetching Dash price: ' + str(e))

        finally:
            self.refresh_price_thread_ref = None

    def get_dash_amount_str(self, amount: float, show_dash_part: bool, show_fiat_part: bool,
                            show_dash_lbl: bool = False, show_fiat_lbl: bool = False) -> str:
        if amount is not None:
            ret_str = ''
            if show_dash_part:
                ret_str = app_utils.to_string(amount)
                if show_dash_lbl:
                    ret_str += ' DASH'

            if (self.app_config.is_mainnet or SCREENSHOT_MODE) and self.last_dash_price_usd is not None and \
                    self.app_config.show_dash_value_in_fiat and show_fiat_part:
                if ret_str:
                    ret_str += ' / '
                ret_str += app_utils.to_string(round(amount * self.last_dash_price_usd, 2))
                if show_fiat_lbl:
                    ret_str += ' USD'
        else:
            ret_str = ''
        return ret_str

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

    def apply_net_masternodes_filter(self):
        m = self.net_masternodes_model
        m.filter_type = FilterOperator.AND if self.rbFilterTypeAnd.isChecked() else FilterOperator.OR
        m.filter_mn_type = {
            0: None,
            1: 'Regular',
            2: 'HighPerformance'
        }.get(self.cboNetMnsFilterType.currentIndex(), None)
        m.filter_protx = self.edtNetMnsFilterProtx.text()
        m.filter_ip_port = self.edtNetMnsFilterIP.text()
        m.filter_payment_addr = self.edtNetMnsFilterPayee.text()
        m.filter_collateral_hash = self.edtNetMnsFilterCollateralHash.text()
        m.filter_collateral_address = self.edtNetMnsFilterCollateralAddress.text()
        m.filter_owner_address = self.edtNetMnsFilterOwnerAddress.text()
        m.filter_voting_address = self.edtNetMnsFilterVotingAddress.text()
        m.filter_operator_pubkey = self.edtNetMnsFilterOperatorPubkey.text()
        m.filter_platform_node_id = self.edtNetMnsFilterPlatformNodeId.text()
        m.filter_mn_status = {
            0: None,
            1: 'ENABLED',
            2: 'POSE_BANNED'
        }.get(self.cboNetMnsFilterStatus.currentIndex())

        if self.net_mn_list_last_where_cond == self.get_net_masternodes_sql_where_cond():
            tm_begin = time.time()

            m.invalidateFilter()
            self.update_net_masternodes_ui()

            diff = time.time() - tm_begin
            logging.info(f'Network masternode filer time: {round(diff,2)}s')
        else:
            # control(s) impacting the way the masternode data is read from the database has changed
            # so, instead of just applying filter, we need to re-fetch data from db
            self.refresh_net_masternodes_view()

    @pyqtSlot(bool)
    def on_btnNetMnsApplyFilter_clicked(self, _):
        try:
            self.apply_net_masternodes_filter()
        except Exception as e:
            log.exception(str(e))

    @pyqtSlot(bool)
    def on_btnNetMnsClearFilter_clicked(self, _):
        try:
            self.cboNetMnsFilterType.setCurrentIndex(0)
            self.cboNetMnsFilterStatus.setCurrentIndex(0)
            self.edtNetMnsFilterIP.clear()
            self.edtNetMnsFilterProtx.clear()
            self.edtNetMnsFilterCollateralAddress.clear()
            self.edtNetMnsFilterPayee.clear()
            self.edtNetMnsFilterOwnerAddress.clear()
            self.edtNetMnsFilterVotingAddress.clear()
            self.edtNetMnsFilterCollateralHash.clear()
            self.edtNetMnsFilterPlatformNodeId.clear()
            self.edtNetMnsFilterOperatorPubkey.clear()
            self.chbNetMnsFilterWasActiveOn.setChecked(False)
        except Exception as e:
            log.exception(str(e))


class MasternodesFromConfigTableModel(ExtSortFilterItemModel):
    def __init__(self, parent, masternodes: List[MasternodeConfig],
                 mns_status: Dict[MasternodeConfig, MasternodeStatus],
                 get_dash_amount_str_fun: Callable[[float, bool, bool, Optional[bool], Optional[bool]], str]):
        ExtSortFilterItemModel.__init__(self, parent, [
            TableModelColumn('no', '', True, 25, horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('name', 'Name', True, 150),
            TableModelColumn('status', 'Status', True, 140),
            TableModelColumn('ip_port', 'IP/port', True, 160),
            TableModelColumn('collateral', 'Collateral address', False, 100),
            TableModelColumn('collateral_tx', 'Collateral tx/index', False, 100),
            TableModelColumn('roles', 'Roles', False, 100),
            TableModelColumn('protx', 'Protx', False, 100),
            TableModelColumn('last_paid_block', 'Last paid (block)', False, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('last_paid_time', 'Last paid (time)', True, 150),
            TableModelColumn('last_paid_ago', 'Last paid (ago)', True, 150),
            TableModelColumn('next_payment_block', 'Next payment (block)', False, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('next_payment_time', 'Next payment (time)', True, 150),
            TableModelColumn('next_payment_in', 'Next payment (in)', True, 150),
            TableModelColumn('collateral_addr_balance_dash', 'Collateral balance [DASH]', False, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('collateral_addr_balance_fiat', 'Collateral balance [USD]', False, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('payout_addr_balance_dash', 'Payout balance [DASH]', False, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('payout_addr_balance_fiat', 'Payout balance [USD]', False, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT)
        ], True, True)
        self.masternodes = masternodes
        self.mns_status = mns_status
        self.background_color = QtGui.QColor('lightgray')
        self.get_dash_amount_str = get_dash_amount_str_fun
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
                                    if st.protx_conf_pending:
                                        return QColor(get_widget_font_color_blue(self.view))
                                    elif st.is_error():
                                        return COLOR_ERROR
                                    elif st.is_warning():
                                        return COLOR_WARNING
                                    else:
                                        return QColor(get_widget_font_color_green(self.view))
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
                    ret_val = mn.ip + (':' + str(mn.tcp_port) if mn.tcp_port else '')
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
                    ret_val = mn.protx_hash
                elif col_name == 'status':
                    if for_sorting:
                        ret_val = st.status if st else ''
                    else:
                        if st:
                            if st.protx_conf_pending:
                                img_file = 'hourglass-full@16px.png'
                            elif st.is_error():
                                img_file = 'error@16px.png'
                            elif st.is_warning():
                                img_file = 'warning@16px.png'
                            else:
                                img_file = 'check-circle@16px.png'

                            pix = WndUtils.get_icon_pixmap(img_file)
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
                elif col_name == 'collateral_addr_balance_dash':
                    if st:
                        if for_sorting:
                            ret_val = st.collateral_addr_balance
                            if ret_val is None:
                                ret_val = 0
                        else:
                            ret_val = self.get_dash_amount_str(st.collateral_addr_balance, True, False, False, False)
                elif col_name == 'collateral_addr_balance_fiat':
                    if st:
                        if for_sorting:
                            ret_val = st.collateral_addr_balance
                            if ret_val is None:
                                ret_val = 0
                        else:
                            ret_val = self.get_dash_amount_str(st.collateral_addr_balance, False, True, False, False)
                elif col_name == 'payout_addr_balance_dash':
                    if st:
                        if for_sorting:
                            ret_val = st.payout_addr_balance
                            if ret_val is None:
                                ret_val = 0
                        else:
                            ret_val = self.get_dash_amount_str(st.payout_addr_balance, True, False, False, False)
                elif col_name == 'payout_addr_balance_fiat':
                    if st:
                        if for_sorting:
                            ret_val = st.payout_addr_balance
                            if ret_val is None:
                                ret_val = 0
                        else:
                            ret_val = self.get_dash_amount_str(st.payout_addr_balance, False, True, False, False)
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


class MasternodesFromNetworkTableModel(ExtSortFilterItemModel):
    def __init__(self, parent, masternodes: List[Masternode]):
        ExtSortFilterItemModel.__init__(self, parent, [
            TableModelColumn('id', 'Id', False, 25, horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('ip_port', 'IP/Port', True, 100),
            TableModelColumn('ident', 'Ident', False, 150),
            TableModelColumn('status', 'Status', True, 140),
            TableModelColumn('type', 'Type', True, 100),
            TableModelColumn('queue_position', 'Queue position', True, 150,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('payee', 'Payout address', False, 160),
            TableModelColumn('last_paid_time', 'Last paid time', False, 100),
            TableModelColumn('last_paid_block', 'Last paid block', False, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('protx', 'Protx', False, 100),
            TableModelColumn('dmt_active', 'DMT active', False, 100),
            TableModelColumn('dmt_creation_time', 'DMT creation time', False, 150),
            TableModelColumn('dmt_deactivation_time', 'DMT deactivation time', False, 150),
            TableModelColumn('registered_height', 'Registered height', False, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('platform_node_id', 'Platform Node Id', False, 150),
            TableModelColumn('platform_p2p_port', 'Platform P2P port', False, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('platform_http_port', 'Platform HTTP port', False, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('collateral_hash', 'Collateral hash', False, 100),
            TableModelColumn('collateral_index', 'Collateral index', False, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('collateral_address', 'Collateral address', False, 100),
            TableModelColumn('owner_address', 'Owner address', False, 100),
            TableModelColumn('voting_address', 'Voting address', False, 100),
            TableModelColumn('operator_pubkey', 'Operator pubkey', False, 100),
            TableModelColumn('pose_penalty', 'PoSe penalty', True, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('pose_ban_height', 'PoSe ban height', True, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('pose_ban_time', 'PoSe ban time', True, 100),
            TableModelColumn('pose_revived_height', 'PoSe revived height', True, 100,
                             horizontal_alignment=HorizontalAlignment.RIGHT),
            TableModelColumn('operator_reward', 'Operator reward', True, 100)
        ], True, True)
        self.masternodes = masternodes
        self.background_color = QtGui.QColor('lightgray')

        self.filter_type: FilterOperator = FilterOperator.AND
        self.filter_mn_type = None
        self.filter_protx = None
        self.filter_ip_port = None
        self.filter_payment_addr = None
        self.filter_collateral_hash = None
        self.filter_collateral_address = None
        self.filter_owner_address = None
        self.filter_voting_address = None
        self.filter_operator_pubkey = None
        self.filter_platform_node_id = None
        self.filter_mn_status = None
        self.filter_was_active_on_date = None

        self.set_attr_protection()

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
                        col: TableModelColumn = self.col_by_index(col_idx)
                        if col:
                            if col.name == 'status':
                                v = self.get_cell_value(row_idx, col_idx, for_sorting=False)
                                if v == 'POSE_BANNED':
                                    return COLOR_ERROR
                                else:
                                    return QColor(get_widget_font_color_green(self.view))
                        return None

                    elif role == Qt.TextAlignmentRole:
                        col: TableModelColumn = self.col_by_index(col_idx)
                        if col and col.horizontal_alignment:
                            return Qt.AlignRight | Qt.AlignVCenter if col.horizontal_alignment == \
                                                                      HorizontalAlignment.RIGHT else \
                                   Qt.AlignLeft | Qt.AlignVCenter
                        return None

        return QVariant()

    def get_cell_value(self, row_idx: int, col_idx: int, for_sorting: bool):
        ret_val: Any = None
        if row_idx < len(self.masternodes):
            mn: Masternode = self.masternodes[row_idx]
            col = self.col_by_index(col_idx)
            if col:
                col_name = col.name
                if col_name == 'id':
                    ret_val = mn.db_id
                elif col_name == 'ident':
                    ret_val = mn.ident
                elif col_name == 'status':
                    ret_val = mn.status
                elif col_name == 'payee':
                    ret_val = mn.payout_address
                elif col_name == 'last_paid_time':
                    if for_sorting:
                        ret_val = mn.lastpaidtime
                        if ret_val is None:
                            ret_val = 0
                    else:
                        if mn.lastpaidtime:
                            ret_val = app_utils.to_string(datetime.fromtimestamp(mn.lastpaidtime))
                elif col_name == 'last_paid_block':
                    ret_val = mn.lastpaidblock
                elif col_name == 'ip_port':
                    ret_val = mn.ip_port
                elif col_name == 'protx':
                    ret_val = mn.protx_hash
                elif col_name == 'registered_height':
                    ret_val = mn.registered_height
                elif col_name == 'queue_position':
                    ret_val = mn.queue_position
                elif col_name == 'type':
                    ret_val = mn.type
                elif col_name == 'platform_node_id':
                    ret_val = mn.platform_node_id
                elif col_name == 'platform_p2p_port':
                    ret_val = mn.platform_p2p_port
                elif col_name == 'platform_http_port':
                    ret_val = mn.platform_http_port
                elif col_name == 'collateral_hash':
                    ret_val = mn.collateral_hash
                elif col_name == 'collateral_index':
                    ret_val = mn.collateral_index
                elif col_name == 'collateral_address':
                    ret_val = mn.collateral_address
                elif col_name == 'owner_address':
                    ret_val = mn.owner_address
                elif col_name == 'voting_address':
                    ret_val = mn.voting_address
                elif col_name == 'operator_pubkey':
                    ret_val = mn.pubkey_operator
                elif col_name == 'pose_penalty':
                    ret_val = mn.pose_penalty
                elif col_name == 'pose_revived_height':
                    ret_val = mn.pose_revived_height
                elif col_name == 'pose_ban_height':
                    ret_val = mn.pose_ban_height
                elif col_name == 'operator_payout_address':
                    ret_val = mn.operator_payout_address
                elif col_name == 'operator_reward':
                    ret_val = mn.operator_reward
                elif col_name == 'pose_ban_time':
                    if for_sorting:
                        ret_val = mn.pose_ban_timestamp
                        if ret_val is None:
                            ret_val = 0
                    else:
                        if mn.pose_ban_timestamp:
                            ret_val = app_utils.to_string(datetime.fromtimestamp(mn.pose_ban_timestamp))
                elif col_name == 'dmt_creation_time':
                    if for_sorting:
                        ret_val = mn.dmt_creation_time
                        if ret_val is None:
                            ret_val = 0
                    else:
                        if mn.dmt_creation_time:
                            ret_val = app_utils.to_string(datetime.fromtimestamp(mn.dmt_creation_time))
                elif col_name == 'dmt_deactivation_time':
                    if for_sorting:
                        ret_val = mn.dmt_deactivation_time
                        if ret_val is None:
                            ret_val = 0
                    else:
                        if mn.dmt_deactivation_time:
                            ret_val = app_utils.to_string(datetime.fromtimestamp(mn.dmt_deactivation_time))
                elif col_name == 'dmt_active':
                    ret_val = mn.dmt_active
            return ret_val

    def lessThan(self, col_index, left_row_index, right_row_index):
        col = self.col_by_index(col_index)
        if col:
            reverse = False

            left_value = self.get_cell_value(left_row_index, col_index, True)
            right_value = self.get_cell_value(right_row_index, col_index, True)

            if col.name == 'queue_position':
                if isinstance(left_value, (int, float)) and right_value is None:
                    right_value = 1e8
                elif isinstance(right_value, (int, float)) and left_value is None:
                    left_value = 1e8

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
            nonlocal any_cond_met, any_cond_not_met, was_any_condition
            if cond is False:
                any_cond_not_met = True
                was_any_condition = True
                if self.filter_type == FilterOperator.AND:
                    return False
            elif cond is True:
                any_cond_met = True
                was_any_condition = True
                if self.filter_type == FilterOperator.OR:
                    return True
            return None

        will_show = True

        if 0 <= source_row < len(self.masternodes):
            mn = self.masternodes[source_row]

            if self.filter_mn_type:
                cond_met = mn.type == self.filter_mn_type
                r = check_cond(cond_met)
                if r is False:
                    return False
                elif r is True:
                    return True

            if self.filter_mn_status:
                cond_met = mn.status == self.filter_mn_status
                r = check_cond(cond_met)
                if r is False:
                    return False
                elif r is True:
                    return True

            for cur_filter_text, cur_value in ((self.filter_protx, mn.protx_hash),
                                               (self.filter_ip_port, mn.ip_port),
                                               (self.filter_payment_addr, mn.payout_address),
                                               (self.filter_collateral_hash, mn.collateral_hash),
                                               (self.filter_collateral_address, mn.collateral_address),
                                               (self.filter_owner_address, mn.owner_address),
                                               (self.filter_voting_address, mn.voting_address),
                                               (self.filter_operator_pubkey, mn.pubkey_operator),
                                               (self.filter_platform_node_id, mn.platform_node_id)):
                if cur_filter_text:
                    if cur_value is None:
                        cur_value = ''
                    if cur_filter_text.find('*') >= 0:
                        # when used a wildchard character, switch to regexp
                        m = re.match('^' + cur_filter_text.replace('*', '.*') + '$', cur_value)
                        cond_met = m is not None
                    else:
                        cond_met = cur_value == cur_filter_text
                    r = check_cond(cond_met)
                    if r is False:
                        return False
                    elif r is True:
                        return True

            if was_any_condition:
                if (self.filter_type == FilterOperator.OR and not any_cond_met) or \
                        (self.filter_type == FilterOperator.AND and any_cond_not_met):
                    will_show = False
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
    def __init__(self, dash_network, new_bls_scheme):
        self.dash_network = dash_network
        self.new_bls_scheme = new_bls_scheme
        self.not_found = False
        self.status = ''
        self.status_warning = False
        self.masternode_type: MasternodeType = MasternodeType.REGULAR
        self.masternode_type_mismatch = False
        self.protx_conf_pending = False
        self.pose_penalty = 0
        self.pose_ban_height: int = -1
        self.pose_ban_timestamp: int = 0
        self.operator_pub_key = ''
        self.operator_key_update_required = False
        self.operator_service_update_required = False
        self.ip_port_mismatch = False
        self.protx_mismatch = False
        self.collateral_tx_mismatch = False
        self.collateral_address_mismatch = False
        self.network_owner_public_address = ''
        self.network_operator_public_key = ''
        self.network_voting_public_address = ''
        self.owner_public_address_mismatch = False
        self.operator_pubkey_mismatch = False
        self.voting_public_address_mismatch = False
        self.payout_address: Optional[str] = None
        self.payout_addr_balance = 0
        self.operator_payout_address: Optional[str] = None
        self.operator_payout_addr_balance = 0
        self.collateral_addr_balance = 0
        self.platform_node_id: Optional[str] = None
        self.platform_node_id_mismatch = False
        self.platform_p2p_port: Optional[int] = None
        self.platform_p2p_port_mismatch = False
        self.platform_http_port: Optional[int] = None
        self.platform_http_port_mismatch = False
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
        self.last_addr_balance_fetch_ts = 0
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
        self.last_addr_balance_fetch_ts = 0
        self.messages.clear()

    def check_mismatch(self, masternode_cfg: MasternodeConfig, masternode_info: Masternode):
        if not masternode_cfg.collateral_tx or masternode_cfg.collateral_tx_index is None or \
                str(masternode_cfg.collateral_tx) + '-' + str(masternode_cfg.collateral_tx_index) != \
                masternode_info.ident:
            self.collateral_tx_mismatch = True
        else:
            self.collateral_tx_mismatch = False

        if masternode_cfg.protx_hash != masternode_info.protx_hash:
            self.protx_mismatch = True
        else:
            self.protx_mismatch = False

        if masternode_info.ip_port != masternode_cfg.ip + ':' + str(masternode_cfg.tcp_port):
            self.ip_port_mismatch = True
        else:
            self.ip_port_mismatch = False

        if masternode_cfg.dmn_user_roles & DMN_ROLE_OWNER:
            if not masternode_cfg.collateral_address or masternode_cfg.collateral_address != \
                    masternode_info.collateral_address:
                self.collateral_address_mismatch = True
            else:
                self.collateral_address_mismatch = False

            owner_address_cfg = masternode_cfg.get_owner_public_address(self.dash_network)
            self.network_owner_public_address = masternode_info.owner_address
            if not owner_address_cfg or masternode_info.owner_address != owner_address_cfg:
                self.owner_public_address_mismatch = True
            else:
                self.owner_public_address_mismatch = False
        else:
            self.owner_public_address_mismatch = False

        if masternode_cfg.dmn_user_roles & DMN_ROLE_OPERATOR:
            operator_pubkey_cfg = masternode_cfg.get_operator_pubkey(self.new_bls_scheme)
            self.network_operator_public_key = masternode_info.pubkey_operator
            if not operator_pubkey_cfg or operator_pubkey_cfg[2:] != masternode_info.pubkey_operator[2:]:
                # don't compare the first byte to overcome the difference being the result of the new-old BLS
                # public key generation scheme
                self.operator_pubkey_mismatch = True
            else:
                self.operator_pubkey_mismatch = False
        else:
            self.operator_pubkey_mismatch = False

        if masternode_cfg.dmn_user_roles & DMN_ROLE_VOTING:
            voting_address_cfg = masternode_cfg.get_voting_public_address(self.dash_network)
            self.network_voting_public_address = masternode_info.voting_address
            if not voting_address_cfg or voting_address_cfg != masternode_info.voting_address:
                self.voting_public_address_mismatch = True
            else:
                self.voting_public_address_mismatch = False
        else:
            self.voting_public_address_mismatch = False

        if masternode_cfg.masternode_type != self.masternode_type:
            self.masternode_type_mismatch = True
        else:
            self.masternode_type_mismatch = False

        self.platform_node_id_mismatch = False
        self.platform_p2p_port_mismatch = False
        self.platform_http_port_mismatch = False
        if masternode_cfg.masternode_type == MasternodeType.HPMN:
            if masternode_cfg.get_platform_node_id() != self.platform_node_id:
                self.platform_node_id_mismatch = True
            if masternode_cfg.platform_p2p_port != self.platform_p2p_port:
                self.platform_p2p_port_mismatch = True
            if masternode_cfg.platform_http_port != self.platform_http_port:
                self.platform_http_port_mismatch = True

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
