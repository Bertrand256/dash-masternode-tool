#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-05

import datetime
import json
import logging
import sys
from typing import List, Tuple, Optional, Callable, Dict, Any
from urllib.error import URLError
import random
import re
import sqlite3
import threading
import time
import codecs
from functools import partial
import bitcoin
from PyQt5 import QtWidgets, QtGui
from PyQt5.QtChart import QChart, QChartView, QLineSeries, QDateTimeAxis, QValueAxis, QBarSet, QBarSeries, \
    QBarCategoryAxis
from PyQt5.QtCore import Qt, pyqtSlot, QVariant, QAbstractTableModel, QSortFilterProxyModel, \
    QDateTime, QLocale, QItemSelection, QItemSelectionModel, QUrl
from PyQt5.QtGui import QColor, QPainter, QPen, QBrush, QDesktopServices
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QTableView, QAbstractItemView, QItemDelegate, \
    QStyledItemDelegate
from math import floor
import urllib.request
import ssl
import app_cache
import app_utils
import base58
import wnd_utils as wnd_utils
import dash_utils
from app_config import MasternodeConfig, InputKeyType
from common import AttrsProtected
from dashd_intf import DashdIndexException, Masternode
from ext_item_model import ExtSortFilterTableModel, TableModelColumn
from ui import ui_proposals
from wnd_utils import WndUtils, CloseDialogException

# Definition of how long the cached proposals information is valid. If it's valid, dialog
# will display data from cache, instead of requesting them from a dash daemon, which is
# more time consuming.
PROPOSALS_CACHE_VALID_SECONDS = 3600

# Number of seconds after which voting will be reloaded for active proposals:
VOTING_RELOAD_TIME = 3600

VOTE_CODE_YES = '1'
VOTE_CODE_NO = '2'
VOTE_CODE_ABSTAIN = '3'

# definition of symbols' for DB live configuration (tabel LIVE_CONFIG)
CFG_PROPOSALS_LAST_READ_TIME = 'proposals_last_read_time'
CFG_PROPOSALS_VOTES_MAX_DATE = 'prop_votes_max_date'  # maximum date of vote(s), read last time

COLOR_YES = '#2eb82e'
COLOR_NO = 'red'
COLOR_ABSTAIN = 'orange'
QCOLOR_YES = QColor(COLOR_YES)
QCOLOR_NO = QColor(COLOR_NO)
QCOLOR_ABSTAIN = QColor(COLOR_ABSTAIN)


CACHE_ITEM_PROPOSALS_SPLITTER = 'ProposalsDlg_DetailsSplitter'
CACHE_ITEM_VOTES_SPLITTER = 'ProposalsDlg_VotesSplitter'
CACHE_ITEM_HIST_SHOW_ONLY_MY_VOTES = 'ProposalsDlg_VotesHistoryShowOnlyMyVotes'
CACHE_ITEM_HIST_FILTER_TEXT = 'ProposalsDlg_VotesHistoryFilterText'
CACHE_ITEM_DETAILS_INDEX = 'ProposalsDlg_TabDetailsCurrentIndex'
CACHE_ITEM_VOTES_COLUMNS = 'ProposalsDlg_VotesColumnsCfg'
CACHE_ITEM_PROPOSALS_COLUMNS = 'ProposalsDlg_ProposalsColumnsCfg'
CACHE_ITEM_ONLY_ONLY_ACTIVE_PROPOSALS = 'ProposalsDlg_OnlyActiveProposals'
CACHE_ITEM_ONLY_ONLY_NEW_PROPOSALS = 'ProposalsDlg_OnlyNewProposals'
CACHE_ITEM_ONLY_ONLY_NOT_VOTED_PROPOSALS = 'ProposalsDlg_OnlyNotVotedProposals'


log = logging.getLogger('dmt.proposals')


class ProposalColumn(TableModelColumn):
    def __init__(self, name, caption, visible, column_for_vote=False):
        """
        Constructor.
        :param name: Column name. There are: 1) static columns that display some piece of information about
            the proposal 2) dynamic columns, that display vote made by specified masternodes for each proposal.
            For dynamic column, name attribute equals to masternode identifier.
        :param caption: Column's caption.
        :param visible: True, if column is visible
        :param column_for_vote: True for (dynamic) columns related to mn voting.
        """
        TableModelColumn.__init__(self, name, caption, visible)
        self.remove_attr_protection()
        self.column_for_vote = column_for_vote
        self.my_masternode = None  # True, if column for masternode vote relates to user's masternode
        self.initil_order = None  # order by voting-in-progress first, then by payment_start descending
        self.set_attr_protection()


class Vote(AttrsProtected):
    def __init__(self, voting_masternode, voting_time, voting_result, voting_masternode_ident):
        super().__init__()
        self.voting_masternode = voting_masternode

        # use voting_masternode_ident only for non existing masternodes' vote:
        self.voting_masternode_ident = voting_masternode_ident if voting_masternode is None else None
        self.voting_time = voting_time
        self.voting_result = voting_result
        self.set_attr_protection()


class VotingMasternode(AttrsProtected):
    def __init__(self, masternode, masternode_config):
        """ Stores information about masternodes for which user has ability to vote.
        :param masternode: ref to an object storing mn information read from the network (dashd_intf.Masternode)
        :param masternode_config: ref to an object storing mn user's configuration (app_config.MasternodeConfig)
        """
        super().__init__()
        self.masternode: Masternode = masternode
        self.masternode_config: MasternodeConfig = masternode_config
        self.btn_vote_yes = None  # dynamically created button for voting YES on behalf of this masternode
        self.btn_vote_no = None  # ... for voting NO
        self.btn_vote_abstain = None  # ... for voting ABSTAIN
        self.lbl_last_vote = None  # label to display last voting results for this masternode and currently focused prop
        self.set_attr_protection()


class Proposal(AttrsProtected):
    def __init__(self, data_model, vote_columns_by_mn_ident, next_superblock_time,
                 user_masternodes: List[VotingMasternode],
                 get_governance_info_fun: Callable,
                 find_prev_superblock: Callable,
                 find_next_superblock: Callable):
        super().__init__()
        self.visible = True
        self.get_governance_info: Callable = get_governance_info_fun
        self.find_prev_superblock = find_prev_superblock
        self.find_next_superblock = find_next_superblock
        self.budget_cycle_hours: int = None
        self.data_model: ExtSortFilterTableModel = data_model
        self.values: Dict[ProposalColumn, Any] = {}  # dictionary of proposal values (key: ProposalColumn)
        self.db_id = None
        self.marker = None
        self.modified = False
        self.next_superblock_time = next_superblock_time
        self.voting_last_read_time = 0
        self.voting_in_progress = True
        self.vote_columns_by_mn_ident = vote_columns_by_mn_ident
        self.votes_by_masternode_ident = {}  # list of tuples: vote_timestamp, vote_result
        self.ext_attributes_loaded = False
        self.user_masternodes: List[VotingMasternode] = user_masternodes

        # voting_status:
        #   1: voting in progress, funding
        #   2: voting in progress, no funding
        #   3: deadline passed, funding
        #   4: deadline passed, no funding
        self.voting_status = None

        self.url_col_widget = None
        self.initial_order_no = 0  # initial order
        self.set_attr_protection()

    def set_value(self, name, value):
        """
        Sets value for a specified Proposal column.
        :returns True, if new value is different that old value
        """
        for col in self.data_model.columns():
            if col.name == name:
                old_value = self.values.get(col)
                if old_value != value:
                    self.modified = True
                    self.values[col] = value
                    return True
                else:
                    return False
        raise AttributeError('Invalid proposal value name: ' + name)

    def get_value(self, column):
        """
        Returns value of for a specified column name.
        """
        if isinstance(column, str):
            if column == 'no':
                return self.initial_order_no + 1
            elif column == 'active':
                return self.voting_in_progress
            else:
                for col in self.data_model.columns():
                    if col.name == column:
                        return self.values.get(col)
            raise AttributeError('Invalid proposal column name: ' + column)
        elif isinstance(column, int):
            # column is a column index
            if column >= 0 and column < self.data_model.col_count():
                return self.values.get(self.data_model.col_by_index(column))
            raise AttributeError('Invalid proposal column index: ' + str(column))
        raise AttributeError("Invalid 'column' attribute type.")

    def get_last_mn_vote(self, mn_ident: str) -> Optional[Tuple[datetime.datetime, str]]:
        """
        :return: Optional[Tuple[datetime <vote time>, str <vote>]]
        """
        return self.votes_by_masternode_ident.get(mn_ident)

    def apply_vote(self, mn_ident, vote_timestamp, vote_result):
        """ Apply vote result if a masternode is in the column list or is a user's masternode. """
        modified = False
        if mn_ident in self.votes_by_masternode_ident:
            if vote_timestamp > self.votes_by_masternode_ident[mn_ident][0]:
                self.votes_by_masternode_ident[mn_ident][0] = vote_timestamp
                self.votes_by_masternode_ident[mn_ident][1] = vote_result
                modified = True
        else:
            self.votes_by_masternode_ident[mn_ident] = [vote_timestamp, vote_result]
            modified = True

        if modified and mn_ident in self.vote_columns_by_mn_ident:
            # this vote shoud be shown in the dynamic column for vote results
            self.set_value(mn_ident, vote_result)

    def remove_vote(self, mn_ident):
        if self.votes_by_masternode_ident.get(mn_ident):
            del self.votes_by_masternode_ident[mn_ident]
            if mn_ident in self.vote_columns_by_mn_ident:
                self.set_value(mn_ident, None)

    def apply_values(self, masternodes, last_superblock_time, next_superblock_datetime):
        """ Calculate auto-calculated columns (eg. voting_in_progress and voting_status values). """

        gi = self.get_governance_info()
        cycle_blocks = gi.get('superblockcycle', 16616)
        last_superblock = gi.get('lastsuperblock', 0)
        cycle_seconds = cycle_blocks * 2.5 * 60
        self.budget_cycle_hours = round(cycle_blocks * 2.5)

        payment_start = self.get_value('payment_start')
        if payment_start:
            payment_start = payment_start.timestamp()
        else:
            payment_start = None
        payment_end = self.get_value('payment_end')
        if payment_end:
            payment_end = payment_end.timestamp()
        else:
            payment_end = None
        funding_enabled = self.get_value('fCachedFunding')

        if payment_start and payment_end and isinstance(last_superblock_time, (int, float)) \
                and isinstance(next_superblock_datetime, (int, float)):
            self.voting_in_progress = (payment_start > last_superblock_time) or \
                                      (payment_end > next_superblock_datetime)
        else:
            self.voting_in_progress = False

        start_sb = self.find_next_superblock(payment_start)
        end_sb = self.find_prev_superblock(payment_end)

        payment_cycles = int((end_sb - start_sb) / cycle_blocks) + 1

        # calculate number of payment-months that passed already for the proposal
        if start_sb > last_superblock:
            cur_cycle = 0
        else:
            cur_cycle = int(((last_superblock - start_sb) / cycle_blocks)) + 1

        self.set_value('cycles', payment_cycles)
        self.set_value('current_cycle', cur_cycle)
        amt = self.get_value('payment_amount')
        if amt is not None:
            self.set_value('payment_amount_total', amt * payment_cycles)

        if not self.get_value('title'):
            # if title value is not set (it's an external attribute, from dashcentral) then copy value from the
            # name column
            self.set_value('title', self.get_value('name'))

        abs_yes_count = self.get_value('absolute_yes_count')
        mns_count = 0
        for mn in masternodes:
            if mn.status in ('ENABLED', 'PRE_ENABLED'):
                mns_count += 1
        if self.voting_in_progress:
            if abs_yes_count >= mns_count * 0.1:
                self.voting_status = 1  # will be funded
                self.set_value('voting_status_caption', 'Passing +%d (%d of %d needed)' %
                               (abs_yes_count - int(mns_count * 0.1), abs_yes_count, int(mns_count * 0.1)))
            else:
                self.voting_status = 2  # needs additional votes
                self.set_value('voting_status_caption', 'Needs additional %d votes' % (int(mns_count * 0.1) -
                                                                                       abs_yes_count))
        else:
            if funding_enabled:
                self.voting_status = 3  # funded
                self.set_value('voting_status_caption', f'Passed with funding ({abs_yes_count} abs. yes votes)')
            else:
                self.voting_status = 4  # not funded
                self.set_value('voting_status_caption', f'Not funded ({abs_yes_count} abs. yes votes)')

    def not_voted_by_user(self):
        for umn in self.user_masternodes:
            if self.votes_by_masternode_ident.get(umn.masternode.ident) is None:
                return True
        return False

    def voted_by_user(self, vote: str):
        for umn in self.user_masternodes:
            mnv = self.votes_by_masternode_ident.get(umn.masternode.ident)
            if mnv:
                if mnv[1] == vote:
                    return True
        return False


class ProposalsDlg(QDialog, ui_proposals.Ui_ProposalsDlg, wnd_utils.WndUtils):
    def __init__(self, parent, dashd_intf):
        QDialog.__init__(self, parent=parent)
        wnd_utils.WndUtils.__init__(self, parent.app_config)
        self.main_wnd = parent
        self.app_config = parent.app_config
        self.finishing = False  # True if the dialog is closing (all thread operations will be stopped)
        self.dashd_intf = dashd_intf
        self.db_intf = self.app_config.db_intf
        self.vote_columns_by_mn_ident = {}
        self.proposals = []
        self.proposals_by_hash = {}  # dict of Proposal object indexed by proposal hash
        self.proposals_by_db_id = {}
        self.masternodes: List[Masternode] = []
        self.masternodes_by_ident = {}
        self.initial_messages = []

        self.masternodes_cfg: List[MasternodeConfig] = []
        pkeys = []
        mn_idents = []
        for idx, mn in enumerate(self.app_config.masternodes):
            mn_ident = mn.collateralTx + '-' + str(mn.collateralTxIndex)
            if mn_ident not in mn_idents:
                if mn.dmn_voting_key_type == InputKeyType.PRIVATE:
                    voting_key = mn.get_current_key_for_voting(self.app_config, self.dashd_intf)
                    if voting_key:
                        if dash_utils.validate_wif_privkey(voting_key, self.app_config.dash_network):
                            if voting_key not in pkeys:
                                pkeys.append(voting_key)
                                mn_idents.append(mn_ident)
                                self.masternodes_cfg.append(mn)
                        else:
                            log.warning(f'Invalid voting private key for masternode: "{mn.name} (idx:{idx})".')
                    else:
                        log.warning(f'Empty voting key for masternode "{mn.name} (idx:{idx})".')
                else:
                    log.warning(f'Voting key for masternode "{mn.name} (idx:{idx})" is public and '
                                f'does not allow voting.')
            else:
                dup_idx = mn_idents.index(mn_ident)
                msg = f'Duplicate collateral tx hash/index for masternodes: "{mn.name} (idx:{idx})" and ' \
                      f'"{self.masternodes_cfg[dup_idx].name} (idx:{dup_idx})". You won\'t be able to vote with the ' \
                      f'second one.'
                log.warning(msg)
                self.initial_messages.append(msg)

        # masternodes existing in the user's configuration, which can vote - list of VotingMasternode objects
        self.users_masternodes: List[VotingMasternode] = []
        self.users_masternodes_by_ident = {}

        self.mn_count = None
        self.block_timestamps: Dict[int, int] = {}
        self.governanceinfo = {}
        self.budget_cycle_days = 28.8
        self.cur_block_height = 0
        self.cur_block_timestamp = 0
        self.superblock_cycle = None
        self.last_superblock = None
        self.next_superblock = None
        self.last_superblock_time = None
        self.next_superblock_time = None
        self.voting_deadline_passed = True  # True when current block number is >= next superblock - 1662
        self.next_budget_amount = None
        self.next_budget_requested = None
        self.next_budget_approved = None
        self.next_budget_requested_pct = None
        self.next_budget_approved_pct = None
        self.next_budget_approved_by_user_yes_votes = None
        self.proposals_last_read_time = 0
        self.current_proposal = None
        self.propsModel = None
        self.votesModel = None
        self.votesProxyModel = None
        self.votes_loaded = False
        self.last_chart_type = None
        self.last_chart_proposal = None
        self.controls_initialized = False
        self.vote_chart = QChart()
        self.vote_chart_view = QChartView(self.vote_chart)
        self.refresh_details_event = threading.Event()
        self.current_chart_type = -1  # converted from UI radio buttons:
                                      #   1: incremental by date, 2: summary, 3: vote change
        self.sending_votes = False
        self.reading_vote_data = False
        self.setupUi()

    def setupUi(self):
        try:
            ui_proposals.Ui_ProposalsDlg.setupUi(self, self)

            if sys.platform == 'linux':
                self.lblBudgetSummary.setStyleSheet('font: 10pt "Ubuntu";')
            elif sys.platform == 'darwin':
                self.lblBudgetSummary.setStyleSheet('font: 11pt;')

            self.edtProposalFilter.setVisible(True)
            self.lblProposalFilter.setVisible(True)

            self.on_chart_type_change()  # get the self.current_chart_type value from radiobuttons
            self.setWindowTitle('Proposals')

            self.buttonBox.button(QDialogButtonBox.Close).setAutoDefault(False)

            self.detailsSplitter.setStretchFactor(0, 1)
            self.detailsSplitter.setStretchFactor(1, 0)

            self.votesSplitter.setStretchFactor(0, 0)
            self.votesSplitter.setStretchFactor(1, 1)

            self.propsView.verticalHeader().setDefaultSectionSize(
                self.propsView.verticalHeader().fontMetrics().height() + 6)

            # create model serving data to the view
            self.propsModel = ProposalsModel(self, self.proposals)
            self.propsModel.add_filter_column(self.propsModel.col_index_by_name('title'))
            self.propsModel.add_filter_column(self.propsModel.col_index_by_name('name'))
            self.propsModel.add_filter_column(self.propsModel.col_index_by_name('owner'))

            self.votesView.verticalHeader().setDefaultSectionSize(
                self.votesView.verticalHeader().fontMetrics().height() + 6)

            # setting up a view with voting history
            self.votesView.setSortingEnabled(True)

            # create model serving data to the view
            self.votesModel = VotesModel(self, self.masternodes, self.users_masternodes_by_ident, self.db_intf)
            self.votesProxyModel = VotesFilterProxyModel(self)
            self.votesProxyModel.setSourceModel(self.votesModel)
            self.votesView.setModel(self.votesProxyModel)

            self.btnApplyVotesViewFilter.setEnabled(False)
            self.tabsDetails.setCurrentIndex(0)

            self.layoutVotesChart.addWidget(self.vote_chart_view)
            self.vote_chart_view.setRenderHint(QPainter.Antialiasing)

            # disable voting tab until we make sure the user has voting masternodes configured
            self.tabsDetails.setTabEnabled(1, False)
            self.btnProposalsRefresh.setEnabled(False)
            self.btnVotesRefresh.setEnabled(False)
            self.restore_cache_settings()

            self.propsModel.set_view(self.propsView)
            self.propsView.selectionModel().selectionChanged.connect(self.on_propsView_selectionChanged)

            def after_data_load():
                self.setup_user_voting_controls()
                self.enable_refresh_buttons()
                self.refresh_details_tabs()

            # read initial data (from db) inside a thread and then read data from network if needed
            self.run_thread(self, self.read_data_thread, (),
                            on_thread_finish=after_data_load,
                            on_thread_exception=self.enable_refresh_buttons,
                            skip_raise_exception=True)

            # run thread reloading proposal details when the selected proposal changes
            self.run_thread(self, self.refresh_preview_panel_thread, ())
        except:
            log.exception('Exception occurred')
            raise

    def updateUi(self):
        pass

    def closeEvent(self, event):
        self.finishing = True
        self.refresh_details_event.set()
        self.votesModel.finish()
        self.save_cache_settings()
        log.info('Closing the dialog.')

    def restore_cache_settings(self):
        app_cache.restore_window_size(self)
        app_cache.restore_splitter_sizes(self, self.detailsSplitter)
        app_cache.restore_splitter_sizes(self, self.votesSplitter)

        # define "dynamic" columns showing the user voting results
        for idx, mn in enumerate(self.masternodes_cfg):
            mn_ident = mn.collateralTx + '-' + str(mn.collateralTxIndex)
            self.add_voting_column(mn_ident, 'Vote (' + mn.name + ')', my_masternode=True,
                                   insert_before_column=self.propsModel.col_index_by_name('absolute_yes_count'))

        self.propsModel.restore_col_defs(CACHE_ITEM_PROPOSALS_COLUMNS)

        # restore votes grid columns' widths
        cfg_cols = app_cache.get_value(CACHE_ITEM_VOTES_COLUMNS, [], list)
        if isinstance(cfg_cols, list):
            for col_saved_index, c in enumerate(cfg_cols):
                initial_width = c.get('width')
                if not isinstance(initial_width, int):
                    initial_width = None
                if initial_width and col_saved_index < self.votesModel.columnCount():
                    self.votesView.setColumnWidth(col_saved_index, initial_width)
        else:
            log.warning('Invalid type of cached VotesColumnsCfg')

        filter_text = app_cache.get_value(CACHE_ITEM_HIST_FILTER_TEXT, '', str)
        self.edtVotesViewFilter.setText(filter_text)
        if filter_text:
            self.votesProxyModel.set_filter_text(filter_text)

        self.chbOnlyMyVotes.setChecked(app_cache.get_value(CACHE_ITEM_HIST_SHOW_ONLY_MY_VOTES, False, bool))
        self.chb_only_active.setChecked(app_cache.get_value(CACHE_ITEM_ONLY_ONLY_ACTIVE_PROPOSALS, True, bool))
        self.chb_only_new.setChecked(app_cache.get_value(CACHE_ITEM_ONLY_ONLY_NEW_PROPOSALS, False, bool))
        self.chb_not_voted.setChecked(app_cache.get_value(CACHE_ITEM_ONLY_ONLY_NOT_VOTED_PROPOSALS, False, bool))
        self.tabsDetails.setCurrentIndex(app_cache.get_value(CACHE_ITEM_DETAILS_INDEX, self.tabsDetails.currentIndex(), int))
        self.votesProxyModel.set_only_my_votes(self.chbOnlyMyVotes.isChecked())
        self.propsModel.set_filter_only_active(self.chb_only_active.isChecked())
        self.propsModel.set_filter_only_new(self.chb_only_new.isChecked())
        self.propsModel.set_filter_only_not_voted(self.chb_not_voted.isChecked())

    def save_cache_settings(self):
        """
        Saves dynamic configuration (for example grid columns) to cache.
        :return:
        """
        try:
            app_cache.save_window_size(self)
            app_cache.save_splitter_sizes(self, self.detailsSplitter)
            app_cache.save_splitter_sizes(self, self.votesSplitter)
            self.propsModel.save_col_defs(CACHE_ITEM_PROPOSALS_COLUMNS)

            # save voting-results tab configuration
            # columns' withds
            cfg = []
            for col_idx in range(0, self.votesModel.columnCount()):
                width = self.votesView.columnWidth(col_idx)
                c = {'width': width}
                cfg.append(c)
            app_cache.set_value(CACHE_ITEM_VOTES_COLUMNS, cfg)

            app_cache.set_value(CACHE_ITEM_HIST_SHOW_ONLY_MY_VOTES, self.chbOnlyMyVotes.isChecked())
            app_cache.set_value(CACHE_ITEM_HIST_FILTER_TEXT, self.edtVotesViewFilter.text())
            app_cache.set_value(CACHE_ITEM_DETAILS_INDEX, self.tabsDetails.currentIndex())
            app_cache.set_value(CACHE_ITEM_ONLY_ONLY_ACTIVE_PROPOSALS, self.chb_only_active.isChecked())
            app_cache.set_value(CACHE_ITEM_ONLY_ONLY_NEW_PROPOSALS, self.chb_only_new.isChecked())
            app_cache.set_value(CACHE_ITEM_ONLY_ONLY_NOT_VOTED_PROPOSALS, self.chb_not_voted.isChecked())

        except Exception as e:
            log.exception('Exception while saving dialog configuration to cache.')

    def setup_user_voting_controls(self):
        # setup a user-voting tab
        mn_index = 0
        self.btnVoteYesForAll.setProperty('yes', True)
        self.btnVoteNoForAll.setProperty('no', True)
        self.btnVoteAbstainForAll.setProperty('abstain', True)
        self.btnVoteYesForAll.setEnabled(False)
        self.btnVoteNoForAll.setEnabled(False)
        self.btnVoteAbstainForAll.setEnabled(False)
        for user_mn in self.users_masternodes:
            lbl = QtWidgets.QLabel(self.scrollAreaVotingContents)
            lbl.setText('<b>%s</b> (%s)' % (user_mn.masternode_config.name,
                                            user_mn.masternode_config.ip + ':' +
                                            user_mn.masternode_config.port))
            self.layoutUserVoting.addWidget(lbl, mn_index + 1, 0, 1, 1)

            user_mn.btn_vote_yes = QtWidgets.QPushButton(self.scrollAreaVotingContents)
            user_mn.btn_vote_yes.setText("Vote Yes")
            user_mn.btn_vote_yes.setProperty('yes', True)
            user_mn.btn_vote_yes.setEnabled(False)
            user_mn.btn_vote_yes.setAutoDefault(False)
            user_mn.btn_vote_yes.clicked.connect(partial(self.on_btnVoteYes_clicked, user_mn))
            self.layoutUserVoting.addWidget(user_mn.btn_vote_yes, mn_index + 1, 1, 1, 1)

            user_mn.btn_vote_no = QtWidgets.QPushButton(self.scrollAreaVotingContents)
            user_mn.btn_vote_no.setText("Vote No")
            user_mn.btn_vote_no.setProperty('no', True)
            user_mn.btn_vote_no.setEnabled(False)
            user_mn.btn_vote_no.setAutoDefault(False)
            user_mn.btn_vote_no.clicked.connect(partial(self.on_btnVoteNo_clicked, user_mn))
            self.layoutUserVoting.addWidget(user_mn.btn_vote_no, mn_index + 1, 2, 1, 1)

            user_mn.btn_vote_abstain = QtWidgets.QPushButton(self.scrollAreaVotingContents)
            user_mn.btn_vote_abstain.setText("Vote Abstain")
            user_mn.btn_vote_abstain.setProperty('abstain', True)
            user_mn.btn_vote_abstain.setEnabled(False)
            user_mn.btn_vote_abstain.setAutoDefault(False)
            user_mn.btn_vote_abstain.clicked.connect(partial(self.on_btnVoteAbstain_clicked, user_mn))
            self.layoutUserVoting.addWidget(user_mn.btn_vote_abstain, mn_index + 1, 3, 1, 1)

            user_mn.lbl_last_vote = QtWidgets.QLabel(self.scrollAreaVotingContents)
            user_mn.lbl_last_vote.setText('')
            self.layoutUserVoting.addWidget(user_mn.lbl_last_vote, mn_index + 1, 4, 1, 1)
            mn_index += 1
        self.scrollAreaVotingContents.setStyleSheet('QPushButton[yes="true"]{color:%s} QPushButton[no="true"]{color:%s}'
                                     'QPushButton[abstain="true"]{color:%s}' %
                                     (COLOR_YES, COLOR_NO, COLOR_ABSTAIN))
        if len(self.users_masternodes) > 0:
            self.tabsDetails.setTabEnabled(1, True)
        self.controls_initialized = True

    def disable_refresh_buttons(self):
        self.btnProposalsRefresh.setEnabled(False)
        self.btnVotesRefresh.setEnabled(False)

    def enable_refresh_buttons(self, exception_in=None):
        if self.current_proposal is None and len(self.proposals) > 0:
            self.propsView.selectRow(0)
        self.btnProposalsRefresh.setEnabled(True)
        self.btnVotesRefresh.setEnabled(True)

    def keyPressEvent(self, event):
        mods = int(event.modifiers())
        processed = False

        if mods == int(Qt.ControlModifier) | int(Qt.AltModifier):

            if ord('E') == event.key():
                # CTR-ALT-E (Mac: CMD-ALT-E): reload all proposals external properties
                self.special_action_reload_external_attributes()
                processed = True

        if not processed:
            QDialog.keyPressEvent(self, event)

    def special_action_reload_external_attributes(self):
        """ Action invoked by the shortcut: CTRL/CMD-ALT-E: reload proposal external attributes. """
        if self.btnProposalsRefresh.isEnabled():
            if self.queryDlg('Do you really want to reload proposal external attributes?',
                             buttons=QMessageBox.Yes | QMessageBox.Cancel,
                             default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:

                def display_data():
                    self.display_proposals_data()
                    self.refresh_details_tabs()

                def reload_ext_attrs_thread(ctrl):
                    cur = self.db_intf.get_cursor()
                    try:
                        cur.execute("update PROPOSALS set title=null, owner=null, ext_attributes_loaded=0, "
                                    "ext_attributes_load_time=0")
                        self.db_intf.commit()
                        if self.read_external_attibutes(self.proposals):
                            WndUtils.call_in_main_thread(display_data)

                    except CloseDialogException:
                        pass
                    except Exception as e:
                        log.exception('Exception while reloading proposal external attributes')
                        self.errorMsg('Error while retrieving proposals data: ' + str(e))
                    finally:
                        self.db_intf.release_cursor()

                self.disable_refresh_buttons()
                self.run_thread(self, reload_ext_attrs_thread, (),
                                on_thread_finish=self.enable_refresh_buttons,
                                on_thread_exception=self.enable_refresh_buttons,
                                skip_raise_exception=True)

    def update_proposals_order_no(self):
        """ Executed always when number of proposals changed. """
        for index, prop in enumerate(self.proposals):
            prop.initial_order_no = self.propsModel.mapFromSource(self.propsModel.index(index, 0)).row()

    def add_voting_column(self, mn_ident, mn_label, my_masternode=None, insert_before_column=None):
        """
        Adds a dynamic column that displays a vote of the masternode with the specified identifier.
        :return:
        """
        # first check if this masternode is already added to the voting columns
        col = self.propsModel.col_by_name(mn_ident)
        if col:
            col.column_for_vote = True
        else:
            col = ProposalColumn(mn_ident, mn_label, visible=True, column_for_vote=True)
            if isinstance(insert_before_column, int) and insert_before_column < self.propsModel.col_count():
                self.propsModel.insert_column(insert_before_column, col)
            else:
                self.propsModel.insert_column(self.propsModel.col_count(), col)
            self.vote_columns_by_mn_ident[mn_ident] = col

            if my_masternode is None:
                # check if the specified masternode exists in the user configuration; if so, mark the column
                # that it can't be removed
                for mn in enumerate(self.masternodes_cfg):
                    mn_ident_cfg = mn.collateralTx + '-' + str(mn.collateralTxIndex)
                    if mn_ident_cfg == mn_ident:
                        col.my_masternode = True
                        break
            else:
                col.my_masternode = my_masternode

    def display_message(self, message):
        def disp(msg):
            if msg:
                self.lblMessage.setVisible(True)
                self.lblMessage.setText('<b style="color:#0059b3">' + msg + '<b>')
            else:
                self.lblMessage.setVisible(False)
                self.lblMessage.setText('')

        if not self.finishing:
            if threading.current_thread() != threading.main_thread():
                WndUtils.call_in_main_thread(disp, message)
            else:
                disp(message)

    def on_lblMessage_linkActivated(self, link):
        if link == '#close':
            self.lblMessage.setVisible(False)

    def calculate_budget_summary(self):
        total_amount_requested = 0.0
        total_amount_approved = 0.0
        total_amount_approved_by_user_yes_vote = 0.0
        total_pct_approved = None
        total_pct_requested = None
        for p in self.proposals:
            if p.voting_in_progress:
                total_amount_requested += p.get_value('payment_amount')
                if p.voting_status == 1:
                    total_amount_approved += p.get_value('payment_amount')
                    if p.voted_by_user('YES'):
                        total_amount_approved_by_user_yes_vote += p.get_value('payment_amount')
        if self.next_budget_amount:
            total_pct_approved = round(total_amount_approved * 100 / self.next_budget_amount, 2)
            total_pct_requested = round(total_amount_requested * 100 / self.next_budget_amount, 2)
        self.next_budget_requested = total_amount_requested
        self.next_budget_approved = total_amount_approved
        self.next_budget_left = self.next_budget_amount - self.next_budget_approved
        if self.next_budget_left < 0:
            self.next_budget_left = 0
        self.next_budget_requested_pct = total_pct_requested
        self.next_budget_approved_pct = total_pct_approved
        self.next_budget_approved_by_user_yes_votes = total_amount_approved_by_user_yes_vote

    def display_budget_summary(self):
        def disp(msg):
            if msg:
                self.lblBudgetSummary.setVisible(True)
                self.lblBudgetSummary.setText(message)
            else:
                self.lblBudgetSummary.setVisible(False)
                self.lblBudgetSummary.setText('')

        self.calculate_budget_summary()
        next_sb_dt = datetime.datetime.fromtimestamp(self.next_superblock_time)
        voting_deadline_dt = datetime.datetime.fromtimestamp(self.next_voting_deadline)
        if self.voting_deadline_passed:
            dl_add_info = '<span style="color:red"> (passed)</span>'
        else:
            dl_add_info = ''
            dl_diff = self.next_voting_deadline - time.time()
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
                dl_add_info = f'<span> ({dl_str})</span>'

        budget_approved = ''
        if self.next_budget_approved is not None:
            budget_approved = f'<td><b>Budget approved:</b> {app_utils.to_string(round(self.next_budget_approved))} Dash '
            if self.next_budget_approved_pct is not None:
                budget_approved += f'({app_utils.to_string(round(self.next_budget_approved_pct, 2))}%)'
            budget_approved += '</td>'

        budget_requested = ''
        if self.next_budget_requested is not None:
            budget_requested = f'<td><b>Budget requested:</b> {app_utils.to_string(round(self.next_budget_requested))} Dash '
            if self.next_budget_requested_pct is not None:
                budget_requested += f'({app_utils.to_string(round(self.next_budget_requested_pct, 2))}%)'
            budget_requested += '</td>'
        bra = ''
        if budget_approved and budget_requested:
            bra = '<tr>' + budget_approved + budget_requested + '</tr>'

        budget_approved_user_yes = ''
        if self.votes_loaded:
            if self.next_budget_approved_by_user_yes_votes is not None:
                budget_approved_user_yes = \
                    f'<tr><td colspan="2"><b>Budget approved by your YES votes:</b> ' \
                    f'{app_utils.to_string(round(self.next_budget_approved_by_user_yes_votes))} Dash '
                if self.next_budget_amount:
                    budget_approved_user_yes += \
                        f'({app_utils.to_string(round(self.next_budget_approved_by_user_yes_votes * 100 / self.next_budget_amount, 2))}% of the available budget'
                    if self.next_budget_approved:
                        budget_approved_user_yes += f', {app_utils.to_string(round(self.next_budget_approved_by_user_yes_votes * 100 / self.next_budget_approved, 2))}% of the approved budget'
                    budget_approved_user_yes += ')'
                budget_approved_user_yes += '</td></tr>'

        message = '<html><head></head><style>td{padding-right:10px;white-space:nowrap;}</style><body>' \
                  f'<table style="margin-left:6px">' \
                  f'<tr><td><b>Next superblock date:</b> {app_utils.to_string(next_sb_dt)}</td>' \
                  f'<td><b>Voting deadline:</b> {app_utils.to_string(voting_deadline_dt)}{dl_add_info}</td></tr>' \
                  f'{bra}<tr><td><b>Budget available:</b> {app_utils.to_string(round(self.next_budget_amount))} Dash</td>' \
                  f'<td><b>Budget left:</b> {app_utils.to_string(round(self.next_budget_left))} Dash</td></tr>' \
                  f'{budget_approved_user_yes}</table></body></html>'

        if not self.finishing:
            if threading.current_thread() != threading.main_thread():
                WndUtils.call_in_main_thread(disp, message)
            else:
                disp(message)

    def read_proposals_from_network(self):
        """ Reads proposals from the Dash network. """

        def find_prop_data(prop_data, level=1):
            """ Find proposal dict inside a list extracted from DataString field. """
            if isinstance(prop_data, list):
                if len(prop_data) > 2:
                    log.warning('len(prop_data) > 2 [level: %d]. prop_data: %s' % (level, json.dumps(prop_data)))

                if len(prop_data) >= 2 and prop_data[0] == 'proposal' and isinstance(prop_data[1], dict):
                    return prop_data[1]
                elif len(prop_data) >= 1 and isinstance(prop_data[0], list):
                    return find_prop_data(prop_data[0], level+1)
            elif isinstance(prop_data, dict):
                return prop_data
            return None

        def clean_float(data_in):
            # deals with JSON field 'payment_amount' passed as different type for different propsoals  - when it's
            # a string, then comma (if exists) is replaced wit a dot, otherwise it's converted to a float
            if isinstance(data_in, str):
                return float(data_in.replace(',', '.'))
            elif data_in is None:
                return data_in
            else:
                return float(data_in)  # cast to float regardless of the type

        try:

            self.display_message('Reading proposals data, please wait...')
            log.info('Reading proposals from the Dash network.')
            begin_time = time.time()
            proposals_new = self.dashd_intf.gobject("list", "valid", "proposals")
            log.info('Read proposals from network (gobject list). Count: %s, operation time: %s' %
                         (str(len(proposals_new)), str(time.time() - begin_time)))

            rows_added = False

            # reset marker value in all existing Proposal object - we'll use it to check which
            # of prevoiusly read proposals do not exit anymore
            for prop in self.proposals:
                prop.marker = False
                prop.modified = False  # all modified proposals will be saved to DB cache

            errors = 0
            for pro_key in proposals_new:
                hash = '?'
                try:
                    prop_raw = proposals_new[pro_key]

                    prop_dstr = prop_raw.get("DataString")
                    prop_data_json = json.loads(prop_dstr)
                    prop_data = find_prop_data(prop_data_json)
                    if prop_data is None:
                        continue
                    hash = prop_raw['Hash']
                    log.debug('Read proposal: ' + hash)
                    prop = self.proposals_by_hash.get(hash)
                    if not prop:
                        is_new = True
                        prop = Proposal(self.propsModel, self.vote_columns_by_mn_ident, self.next_superblock_time,
                                        self.users_masternodes, self.get_governance_info,
                                        self.find_prev_superblock, self.find_next_superblock)
                    else:
                        is_new = False
                    prop.marker = True

                    prop.set_value('name', prop_data['name'])
                    prop.set_value('payment_start', datetime.datetime.fromtimestamp(int(prop_data['start_epoch'])))
                    prop.set_value('payment_end', datetime.datetime.fromtimestamp(int(prop_data['end_epoch'])))
                    prop.set_value('payment_amount', clean_float(prop_data['payment_amount']))
                    prop.set_value('yes_count', int(prop_raw['YesCount']))
                    prop.set_value('absolute_yes_count', int(prop_raw['AbsoluteYesCount']))
                    prop.set_value('no_count', int(prop_raw['NoCount']))
                    prop.set_value('abstain_count', int(prop_raw['AbstainCount']))
                    prop.set_value('creation_time', datetime.datetime.fromtimestamp(int(prop_raw["CreationTime"])))
                    prop.set_value('url', prop_data['url'])
                    prop.set_value('payment_address', prop_data["payment_address"])
                    prop.set_value('type', prop_data['type'])
                    prop.set_value('hash', hash)
                    prop.set_value('collateral_hash', prop_raw['CollateralHash'])
                    prop.set_value('fBlockchainValidity', prop_raw['fBlockchainValidity'])
                    prop.set_value('fCachedValid', prop_raw['fCachedValid'])
                    prop.set_value('fCachedDelete', prop_raw['fCachedDelete'])
                    prop.set_value('fCachedFunding', prop_raw['fCachedFunding'])
                    prop.set_value('fCachedEndorsed', prop_raw['fCachedEndorsed'])
                    prop.set_value('ObjectType', prop_raw['ObjectType'])
                    prop.set_value('IsValidReason', prop_raw['IsValidReason'])
                    prop.apply_values(self.masternodes, self.last_superblock_time, self.next_superblock_time)
                    if is_new:
                        self.proposals.append(prop)
                        self.proposals_by_hash[prop.get_value('hash')] = prop
                        rows_added = True
                except Exception as e:
                    log.exception('Error while processing proposal data. Proposal hash: ' + hash)
                    errors += 1

            if len(proposals_new) > 0:
                if errors < len(proposals_new)/10:
                    try:
                        cur = self.db_intf.get_cursor()

                        for prop in self.proposals:
                            if self.finishing:
                                raise CloseDialogException

                            if prop.marker:
                                if not prop.db_id:
                                    # first, check if there is a proposal with the same hash in the database
                                    # dashd sometimes does not return some proposals, so they are deactivated id the db
                                    hash = prop.get_value('hash')
                                    cur.execute('SELECT id from PROPOSALS where hash=?', (hash,))
                                    row = cur.fetchone()
                                    if row:
                                        prop.db_id = row[0]
                                        prop.modified = True
                                        cur.execute('UPDATE PROPOSALS set dmt_active=1, dmt_deactivation_time=NULL '
                                                    'WHERE id=?', (row[0],))
                                        log.info('Proposal "%s" (db_id: %d) exists int the DB. Re-activating.' %
                                                     (hash, row[0]))

                                if not prop.db_id:
                                    log.info('Adding a new proposal to DB. Hash: ' + prop.get_value('hash'))
                                    cur.execute("INSERT INTO PROPOSALS (name, payment_start, payment_end, payment_amount,"
                                                " yes_count, absolute_yes_count, no_count, abstain_count, creation_time,"
                                                " url, payment_address, type, hash, collateral_hash, f_blockchain_validity,"
                                                " f_cached_valid, f_cached_delete, f_cached_funding, f_cached_endorsed, "
                                                " object_type, is_valid_reason, dmt_active, dmt_create_time, "
                                                " dmt_deactivation_time, dmt_voting_last_read_time)"
                                                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                                                (prop.get_value('name'),
                                                 prop.get_value('payment_start').strftime('%Y-%m-%d %H:%M:%S'),
                                                 prop.get_value('payment_end').strftime('%Y-%m-%d %H:%M:%S'),
                                                 prop.get_value('payment_amount'),
                                                 prop.get_value('yes_count'),
                                                 prop.get_value('absolute_yes_count'),
                                                 prop.get_value('no_count'),
                                                 prop.get_value('abstain_count'),
                                                 prop.get_value('creation_time').strftime('%Y-%m-%d %H:%M:%S'),
                                                 prop.get_value('url'),
                                                 prop.get_value('payment_address'),
                                                 prop.get_value('type'),
                                                 prop.get_value('hash'),
                                                 prop.get_value('collateral_hash'),
                                                 prop.get_value('fBlockchainValidity'),
                                                 prop.get_value('fCachedValid'),
                                                 prop.get_value('fCachedDelete'),
                                                 prop.get_value('fCachedFunding'),
                                                 prop.get_value('fCachedEndorsed'),
                                                 prop.get_value('ObjectType'),
                                                 prop.get_value('IsValidReason'),
                                                 1,
                                                 datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                                 None))
                                    prop.db_id = cur.lastrowid
                                    self.proposals_by_db_id[prop.db_id] = prop
                                else:
                                    # proposal's db record already exists, check if should be updated
                                    if prop.modified:
                                        log.debug('Updating proposal in the DB. Hash: %s, DB id: %d' %
                                                      (prop.get_value('hash'), prop.db_id) )
                                        cur.execute("UPDATE PROPOSALS set name=?, payment_start=?, payment_end=?, "
                                                    "payment_amount=?, yes_count=?, absolute_yes_count=?, no_count=?, "
                                                    "abstain_count=?, creation_time=?, url=?, payment_address=?, type=?,"
                                                    "hash=?, collateral_hash=?, f_blockchain_validity=?, f_cached_valid=?,"
                                                    "f_cached_delete=?, f_cached_funding=?, f_cached_endorsed=?, object_type=?,"
                                                    "is_valid_reason=? WHERE id=?",
                                                    (
                                                        prop.get_value('name'),
                                                        prop.get_value('payment_start').strftime('%Y-%m-%d %H:%M:%S'),
                                                        prop.get_value('payment_end').strftime('%Y-%m-%d %H:%M:%S'),
                                                        prop.get_value('payment_amount'),
                                                        prop.get_value('yes_count'),
                                                        prop.get_value('absolute_yes_count'),
                                                        prop.get_value('no_count'),
                                                        prop.get_value('abstain_count'),
                                                        prop.get_value('creation_time').strftime('%Y-%m-%d %H:%M:%S'),
                                                        prop.get_value('url'),
                                                        prop.get_value('payment_address'),
                                                        prop.get_value('type'),
                                                        prop.get_value('hash'),
                                                        prop.get_value('collateral_hash'),
                                                        prop.get_value('fBlockchainValidity'),
                                                        prop.get_value('fCachedValid'),
                                                        prop.get_value('fCachedDelete'),
                                                        prop.get_value('fCachedFunding'),
                                                        prop.get_value('fCachedEndorsed'),
                                                        prop.get_value('ObjectType'),
                                                        prop.get_value('IsValidReason'),
                                                        prop.db_id
                                                    ))

                        # delete proposals which no longer exists in tha Dash network
                        rows_removed = False
                        for prop_idx in reversed(range(len(self.proposals))):
                            if self.finishing:
                                raise CloseDialogException

                            prop = self.proposals[prop_idx]

                            if not prop.marker:
                                log.info('Deactivating proposal in the cache. Hash: %s, DB id: %s' %
                                              (prop.get_value('hash'), str(prop.db_id)))
                                cur.execute("UPDATE PROPOSALS set dmt_active=0, dmt_deactivation_time=? WHERE id=?",
                                            (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), prop.db_id))

                                self.proposals_by_hash.pop(prop.get_value('hash'), 0)
                                self.proposals_by_db_id.pop(prop.db_id)
                                del self.proposals[prop_idx]
                                rows_removed = True

                        # self.set_cache_value('ProposalsLastReadTime', int(time.time()))  # save when proposals has been
                        cur.execute("UPDATE LIVE_CONFIG SET value=? WHERE symbol=?",
                                    (int(time.time()), CFG_PROPOSALS_LAST_READ_TIME))
                        if cur.rowcount == 0:
                            cur.execute("INSERT INTO LIVE_CONFIG(symbol, value) VALUES(?, ?)",
                                        (CFG_PROPOSALS_LAST_READ_TIME, int(time.time())))

                        if rows_added or rows_removed:
                            WndUtils.call_in_main_thread(self.display_proposals_data)

                    except CloseDialogException:
                        raise

                    except Exception as e:
                        log.exception('Exception while saving proposals to db.')
                        self.db_intf.rollback()
                        raise
                    finally:
                        self.db_intf.commit()
                        self.db_intf.release_cursor()
                        self.display_message('')

                    if errors > 0:
                        self.warnMsg('Problems encountered while processing some of the proposals data. '
                                     'Look into the log file for details.')
                else:
                    # error count > 10% of the proposals count
                    raise Exception('Errors while processing proposals data. Look into the log file for details.')
            else:
                # no proposals read from network - skip deactivating records because probably
                # some network glitch occured
                log.warning('No proposals returned from dashd.')
            log.info('Finished reading proposals data from network.')

        except CloseDialogException:
            log.info('Closing the dialog.')

        except Exception as e:
            log.exception('Exception wile reading proposals from Dash network.')
            self.display_message('')
            self.errorMsg('Error while reading proposals data from the Dash network: ' + str(e))
            raise

    def get_governance_info(self):
        return self.governanceinfo

    def read_governance_data(self):
        try:
            self.display_message('Reading governance data, please wait...')

            # get the date-time of the last superblock and calculate the date-time of the next one
            self.governanceinfo = self.dashd_intf.getgovernanceinfo()
            self.superblock_cycle = self.governanceinfo.get('superblockcycle', 16616)
            self.budget_cycle_days = round(self.superblock_cycle * 2.5 / 60 /24, 3)
            self.propsModel.set_budget_cycle_days(self.budget_cycle_days)

            self.last_superblock = self.governanceinfo.get('lastsuperblock')
            self.next_superblock = self.governanceinfo.get('nextsuperblock')
            sb_cycle = round(self.governanceinfo.get('superblockcycle') / 10)
            self.next_budget_amount = float(self.dashd_intf.getsuperblockbudget(self.next_superblock))

            # superblocks occur every 16616 blocks (approximately 28.8 days)
            self.cur_block_height = self.dashd_intf.getblockcount()
            self.cur_block_timestamp = int(time.time())

            self.last_superblock_time = self.get_block_timestamp(self.last_superblock)
            self.next_superblock_time = 0
            if self.cur_block_height > 0 and self.cur_block_height <= self.next_superblock:
                self.next_superblock_time = self.get_block_timestamp(self.cur_block_height) + (self.next_superblock - self.cur_block_height) * 2.5 * 60

            if self.next_superblock_time == 0:
                self.next_superblock_time = self.last_superblock_time + (self.next_superblock - self.last_superblock) * 2.5 * 60

            deadline_block = self.next_superblock - sb_cycle
            self.voting_deadline_passed = deadline_block <= self.cur_block_height < self.next_superblock

            self.next_voting_deadline = self.next_superblock_time - (sb_cycle * 2.5 * 60)
            self.display_budget_summary()

        except Exception as e:
            log.exception('Exception while reading governance info.')
            self.errorMsg("Couldn't read governance info from the Dash network. "
                      "Some features may not work correctly because of this. Details: " + str(e))

    def get_block_timestamp(self, superblock: int):
        ts = self.block_timestamps.get(superblock)
        if ts is None:
            bhash = self.dashd_intf.getblockhash(superblock)
            bh = self.dashd_intf.getblockheader(bhash)
            ts = bh['time']
            self.block_timestamps[superblock] = ts
        return ts

    def find_prev_superblock(self, timestamp: int):
        if timestamp < self.last_superblock_time:
            superblock = self.last_superblock
            while True:
                prev_sb_ts = self.get_block_timestamp(superblock - self.superblock_cycle)
                if timestamp > prev_sb_ts:
                    return superblock - self.superblock_cycle
                else:
                    superblock -= self.superblock_cycle
        else:
            superblock = self.last_superblock
            sb_ts = self.last_superblock_time
            while True:
                if sb_ts + (self.superblock_cycle * 2.5 * 60) > timestamp:
                    return superblock
                else:
                    superblock += self.superblock_cycle
                    sb_ts += (self.superblock_cycle * 2.5 * 60)

    def find_next_superblock(self, timestamp: int):
        if timestamp < self.last_superblock_time:
            superblock = self.last_superblock
            while True:
                if self.finishing:
                    raise CloseDialogException
                prev_sb_ts = self.get_block_timestamp(superblock - self.superblock_cycle)
                if timestamp > prev_sb_ts:
                    return superblock
                else:
                    superblock -= self.superblock_cycle
        else:
            superblock = self.last_superblock
            sb_ts = self.last_superblock_time
            while True:
                if sb_ts + (self.superblock_cycle * 2.5 * 60) > timestamp:
                    return superblock + self.superblock_cycle
                else:
                    superblock += self.superblock_cycle
                    sb_ts += (self.superblock_cycle * 2.5 * 60)

    def refresh_filter(self):
        self.propsModel.invalidateFilter()

    def read_data_thread(self, ctrl):
        """ Reads data from the database.
        :param ctrl:
        """

        old_reading_state = self.reading_vote_data
        self.reading_vote_data = True
        try:
            self.display_message('Connecting to Dash daemon, please wait...')
            if not self.dashd_intf.open():
                self.errorMsg('Dash daemon not connected')
            else:
                try:
                    self.read_governance_data()

                    # get list of all masternodes
                    self.display_message('Reading masternode data, please wait...')

                    # prepare a dict of user's masternodes configs (app_config.MasternodeConfig); key: masternode
                    # ident (transaction id-transaction index)
                    users_mn_configs_by_ident = {}
                    for mn_cfg in self.masternodes_cfg:
                        ident = mn_cfg.collateralTx + '-' + mn_cfg.collateralTxIndex
                        if not ident in users_mn_configs_by_ident:
                            users_mn_configs_by_ident[ident] = mn_cfg

                    mns = self.dashd_intf.get_masternodelist('json')
                    self.masternodes = mns
                    self.mn_count = 0
                    statuses = {}

                    # count all active masternodes
                    for mn in mns:
                        if mn.status in ('ENABLED', 'PRE_ENABLED', 'NEW_START_REQUIRED', 'WATCHDOG_EXPIRED'):
                            self.mn_count += 1
                        if statuses.get(mn.status):
                            statuses[mn.status] += 1
                        else:
                            statuses[mn.status] = 1

                        # add mn to an ident indexed dict
                        self.masternodes_by_ident[mn.ident] = mn

                        mn_cfg = users_mn_configs_by_ident.get(mn.ident)
                        if mn_cfg:
                            if mn.ident not in self.users_masternodes_by_ident:
                                vmn = VotingMasternode(mn, mn_cfg)
                                self.users_masternodes.append(vmn)
                                self.users_masternodes_by_ident[mn.ident] = vmn

                    # sort user masternodes according to the order from the app's configuration
                    self.users_masternodes.sort(
                        key=lambda vmn: self.masternodes_cfg.index(vmn.masternode_config))

                    if self.db_intf.db_active:
                        try:
                            self.display_message('Reading proposals data from DB, please wait...')

                            # read all proposals from DB cache
                            cur = self.db_intf.get_cursor()
                            cur_fix = self.db_intf.get_cursor()
                            cur_fix_upd = self.db_intf.get_cursor()

                            cur.execute("SELECT value FROM LIVE_CONFIG WHERE symbol=?", (CFG_PROPOSALS_LAST_READ_TIME,))
                            row = cur.fetchone()
                            if row:
                                self.proposals_last_read_time = int(row[0])

                            log.info("Reading proposals' data from DB")
                            tm_begin = time.time()
                            cur.execute(
                                "SELECT name, payment_start, payment_end, payment_amount,"
                                " yes_count, absolute_yes_count, no_count, abstain_count, creation_time,"
                                " url, payment_address, type, hash, collateral_hash, f_blockchain_validity,"
                                " f_cached_valid, f_cached_delete, f_cached_funding, f_cached_endorsed, object_type,"
                                " is_valid_reason, dmt_active, dmt_create_time, dmt_deactivation_time, id,"
                                " dmt_voting_last_read_time, owner, title, ext_attributes_loaded, "
                                "ext_attributes_load_time "
                                "FROM PROPOSALS where dmt_active=1"
                            )

                            data_modified = False
                            for row in cur.fetchall():
                                if self.finishing:
                                    raise CloseDialogException

                                # fix the problem of duplicated proposals with the same hash, which could be
                                # deactivated due to some problems with previuos executions
                                # select all proposals with the same hash and move their votes to the current one
                                cur_fix.execute('select id from PROPOSALS where hash=? and id<>?',
                                                (row[12], row[24]))
                                for fix_row in cur_fix.fetchall():
                                    cur_fix_upd.execute('UPDATE VOTING_RESULTS set proposal_id=? where proposal_id=?',
                                                        (row[24], fix_row[0]))
                                    cur_fix_upd.execute('DELETE FROM PROPOSALS WHERE id=?', (fix_row[0],))
                                    data_modified = True
                                    log.warning('Deleted duplicated proposal from DB. ID: %s, HASH: %s' %
                                                    (str(fix_row[0]), row[12]))

                                log.debug('Reading proposal: ' + row[0])
                                prop = Proposal(self.propsModel, self.vote_columns_by_mn_ident,
                                                self.next_superblock_time, self.users_masternodes,
                                                self.get_governance_info,
                                                self.find_prev_superblock, self.find_next_superblock)
                                prop.set_value('name', row[0])
                                prop.set_value('payment_start', datetime.datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S'))
                                prop.set_value('payment_end',  datetime.datetime.strptime(row[2], '%Y-%m-%d %H:%M:%S'))
                                prop.set_value('payment_amount', row[3])
                                prop.set_value('yes_count', row[4])
                                prop.set_value('absolute_yes_count', row[5])
                                prop.set_value('no_count', row[6])
                                prop.set_value('abstain_count', row[7])
                                prop.set_value('creation_time', datetime.datetime.strptime(row[8], '%Y-%m-%d %H:%M:%S'))
                                prop.set_value('url', row[9])
                                prop.set_value('payment_address', row[10])
                                prop.set_value('type', row[11])
                                prop.set_value('hash', row[12])
                                prop.set_value('collateral_hash', row[13])
                                prop.set_value('fBlockchainValidity', True if row[14] else False)
                                prop.set_value('fCachedValid', True if row[15] else False)
                                prop.set_value('fCachedDelete', True if row[16] else False)
                                prop.set_value('fCachedFunding', True if row[17] else False)
                                prop.set_value('fCachedEndorsed', True if row[18] else False)
                                prop.set_value('ObjectType', row[19])
                                prop.set_value('IsValidReason', row[20])
                                prop.db_id = row[24]
                                prop.voting_last_read_time = row[25]
                                prop.set_value('owner', row[26])
                                prop.set_value('title', row[27])
                                prop.ext_attributes_loaded = True if row[28] else False

                                ext_attributes_load_time = 0 if not row[29] else row[29]
                                if prop.ext_attributes_loaded:
                                    if not row[26] and not row[27] and time.time() - ext_attributes_load_time > 86400:
                                        # reload external attributes is the 'owner' and 'title' are ampty
                                        prop.ext_attributes_loaded = False
                                    elif (time.time() - ext_attributes_load_time > 86400 * 3) and \
                                        (prop.get_value('payment_end') > datetime.datetime.now()):
                                        # reload external attributes of the active proposals every x days in case
                                        # the proposal title changed
                                        prop.ext_attributes_loaded = False

                                # todo: optimize; for very old proposals exising in the cache, especially for testnet,
                                #  apply_values may have to fetch a large number of transactions from the network (to
                                #  calculate the number of payment cycles that apply to the proposal), which can
                                #  significantly slowndown the display of the list of proposals
                                prop.apply_values(self.masternodes, self.last_superblock_time,
                                                  self.next_superblock_time)
                                self.proposals.append(prop)
                                self.proposals_by_hash[prop.get_value('hash')] = prop
                                self.proposals_by_db_id[prop.db_id] = prop

                            if data_modified:
                                self.db_intf.commit()

                            log.info("Finished reading proposals' data from DB. Time: %s s" %
                                         str(time.time() - tm_begin))

                            def disp():
                                self.propsView.sortByColumn(self.propsModel.col_index_by_name('no'),
                                                            Qt.AscendingOrder)
                                self.display_proposals_data()

                            # display data, now without voting results, which will be read below
                            WndUtils.call_in_main_thread(disp)

                        except CloseDialogException:
                            raise
                        except Exception as e:
                            log.exception('Exception while saving proposals to db.')
                            self.errorMsg('Error while saving proposals data to db. Details: ' + str(e))
                        finally:
                            self.db_intf.release_cursor()
                            self.db_intf.release_cursor()
                            self.db_intf.release_cursor()

                    # read voting data from DB (only for "voting" columns)
                    self.read_voting_from_db()
                    WndUtils.call_in_main_thread(self.refresh_filter)  # vote data can have impact on filter
                    WndUtils.call_in_main_thread(self.display_budget_summary)

                except CloseDialogException:
                    raise

                except DashdIndexException as e:
                    self.errorMsg(str(e))

                except Exception as e:
                    log.exception('Exception while retrieving proposals data.')
                    self.errorMsg('Error while retrieving proposals data: ' + str(e))

            if not self.finishing:
                if int(time.time()) - self.proposals_last_read_time > PROPOSALS_CACHE_VALID_SECONDS or \
                   len(self.proposals) == 0:
                    # read proposals from network only after a configured time
                    self.read_proposals_from_network()

            if not self.finishing:
                # read additional data from external sources, if configured (DashCentral)
                proposals = []
                if self.app_config.read_proposals_external_attributes:
                    for prop in self.proposals:
                        if not prop.ext_attributes_loaded:
                            proposals.append(prop)
                if proposals and not self.finishing:
                    if self.read_external_attibutes(proposals):
                        WndUtils.call_in_main_thread(self.display_proposals_data)  # refresh display

            if not self.finishing:
                proposals = []
                for prop in self.proposals:
                    if (((time.time() - prop.voting_last_read_time) > VOTING_RELOAD_TIME) and
                       (prop.voting_in_progress or prop.voting_last_read_time == 0)):
                        proposals.append(prop)

                if proposals and not self.finishing:
                    self.read_voting_from_network(False, proposals)

        except CloseDialogException:
            log.info('Closing the dialog.')

        except Exception as e:
            log.exception('Exception while reading data.')
            if not self.finishing:
                self.errorMsg(str(e))

        finally:
            if not self.finishing:
                if self.initial_messages:
                    msgs = ''
                    for msg in self.initial_messages:
                        msgs += f'<div style="color:red">{msg}</div>'
                    msgs += ' (<a href="#close">close</a>)'

                    self.display_message(msgs)
                else:
                    self.display_message("")

            self.reading_vote_data = old_reading_state

    def read_external_attibutes(self, proposals):
        """Method reads additional proposal attributes from an external source such as DashCentral.org/DashNexus.org
        :return True if proposals' external attributes has been updated.
        """
        self.display_message("Reading proposal external attributes, please wait...")
        begin_time = time.time()
        network_duration = 0
        modified_ext_attributes = False
        ssl._create_default_https_context = ssl._create_unverified_context
        url_err_retries = 2

        try:
            url = self.app_config.dash_central_proposal_api
            if url:
                exceptions_occurred = False
                for idx, prop in enumerate(proposals):
                    if self.finishing:
                        raise CloseDialogException
                    self.display_message("Reading proposal external attributes (%d/%d), please wait..." %
                                         (idx+1, len(proposals)))

                    prop.modified = False
                    try:
                        prop.marker = False
                        hash = prop.get_value('hash')
                        cur_url = url.replace('%HASH%', hash)
                        network_tm_begin = time.time()
                        contents = None
                        for url_try in range(0, url_err_retries+1):
                            try:
                                response = urllib.request.urlopen(cur_url, context=ssl._create_unverified_context())
                                contents = response.read()
                                break
                            except URLError:
                                if url_try >= url_err_retries:
                                    raise
                                log.info('URLError, retrying...')

                        network_duration += time.time() - network_tm_begin
                        if contents is not None:
                            contents = json.loads(contents.decode('utf-8'))
                        else:
                            contents = ''
                        prop.marker = True  # network operation went OK
                        p = contents.get('proposal')
                        if p is not None:
                            user_name = p.get('owner_username')
                            if user_name:
                                prop.set_value('owner', user_name)
                            title = p.get('title')
                            if title:
                                prop.set_value('title', title)
                        else:
                            err = contents.get('error_type')
                            if err is not None:
                                log.error('Error returned for proposal "' + hash + '": ' + err)
                            else:
                                log.error('Empty "proposal" attribute for proposal: ' + hash)
                    except CloseDialogException:
                        raise

                    except URLError as e:
                        exceptions_occurred = True
                        log.warning(str(e))

                    except Exception as e:
                        exceptions_occurred = True
                        log.error(str(e))

                if not self.finishing:
                    cur = self.db_intf.get_cursor()
                    try:
                        for prop in proposals:
                            if self.finishing:
                                raise CloseDialogException

                            if prop.marker:
                                if prop.modified:
                                    cur.execute(
                                        'UPDATE PROPOSALS set owner=?, title=?, ext_attributes_loaded=1, '
                                        'ext_attributes_load_time=? where id=?',
                                        (prop.get_value('owner'), prop.get_value('title'), int(time.time()),
                                         prop.db_id))
                                    modified_ext_attributes = True
                                elif not prop.ext_attributes_loaded:
                                    # ext attributes loaded but empty; set ext_attributes_loaded to 1 to avoid reading
                                    # the same information the next time
                                    cur.execute(
                                        'UPDATE PROPOSALS set ext_attributes_loaded=1, ext_attributes_load_time=? '
                                        'where id=?',
                                        (int(time.time()), prop.db_id))
                                prop.ext_attributes_loaded = True

                        self.db_intf.commit()
                    finally:
                        self.db_intf.release_cursor()

                    if exceptions_occurred:
                        self.errorMsg('Error(s) occurred while retrieving proposals external data from '
                                      'DashCentral.org.')

        except CloseDialogException:
            log.info('Closing the dialog.')

        except Exception as e:
            log.exception('Exception while reading external attributes.')

        finally:
            time_diff = time.time() - begin_time
            log.info('Finished reading external attributes. Overall time: %s seconds, network time: %s.' %
                         (str(time_diff), str(network_duration)))
            self.display_message('')
        return modified_ext_attributes

    def read_voting_from_db(self):
        """ Read voting results for specified voting columns
        :param columns list of voting columns for which data will be loaded from db; it is used when user adds
          a new column - wee want read data only for this column
        """
        self.display_message('Reading voting data from DB, please wait...')
        begin_time = time.time()

        try:
            cur = self.db_intf.get_cursor()

            for col in self.propsModel.columns():
                if col.column_for_vote:
                    mn_ident = col.name
                    mn = self.masternodes_by_ident.get(mn_ident)
                    if mn:
                        cur.execute("SELECT proposal_id, voting_time, voting_result "
                                    "FROM VOTING_RESULTS vr WHERE masternode_ident=? AND EXISTS "
                                    "(SELECT 1 FROM PROPOSALS p where p.id=vr.proposal_id and p.dmt_active=1)",
                                    (mn_ident,))
                        for row in cur.fetchall():
                            if self.finishing:
                                raise CloseDialogException
                            prop = self.proposals_by_db_id.get(row[0])
                            if prop:
                                prop.apply_vote(mn_ident, datetime.datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S'),
                                                row[2])
            self.votes_loaded = True
        except CloseDialogException:
            log.info('Closing the dialog.')

        except Exception as e:
            log.exception('Exception while saving proposals to db.')

        finally:
            self.db_intf.release_cursor()
            time_diff = time.time() - begin_time
            log.info('Voting data read from database time: %s seconds' % str(time_diff))

    def read_voting_from_network_thread(self, ctrl, force_reload_all, proposals):
        self.read_voting_from_network(force_reload_all, proposals)
        WndUtils.call_in_main_thread(self.display_budget_summary)

    def read_voting_from_network(self, force_reload_all, proposals: List[Proposal]):
        """
        Retrieve from a Dash daemon voting results for all defined masternodes, for all visible Proposals.
        :param force_reload_all: force reloading all votes and makre sure if a db cache contains all of them,
               if False, read only votes posted after last time when votes were read from the network
        :param proposals: list of proposals, which votes will be retrieved
        :return:
        """
        old_reading_state = self.reading_vote_data
        errors = 0

        try:
            self.reading_vote_data = True
            last_vote_max_date = 0
            cur_vote_max_date = 0
            db_modified = False
            cur = None
            refresh_preview_votes = False
            log.info('Begin reading voting data from network.')
            try:
                # read the date/time of the last vote, read from the DB the last time, to initially filter out
                # of all older votes from finding if it has its record in the DB:
                if self.db_intf.is_active():
                    cur = self.db_intf.get_cursor()
                    cur.execute("SELECT value from LIVE_CONFIG WHERE symbol=?", (CFG_PROPOSALS_VOTES_MAX_DATE,))
                    row = cur.fetchone()
                    if row:
                        last_vote_max_date = int(row[0])

                votes_added = []  # list of tuples (proposal, masternode, voting_time, voting_result, masternode ident),
                # that has been added (will be saved to the database cache)

                if not self.dashd_intf.open():
                    self.errorMsg('Dash daemon not connected')
                else:
                    try:
                        proposals_updated = []  # list of proposals for which votes were loaded
                        db_oper_duration = 0.0
                        db_oper_count = 0
                        network_duration = 0.0

                        for row_idx, prop in enumerate(proposals):
                            try:
                                if self.finishing:
                                    raise CloseDialogException

                                self.display_message('Reading voting data %d of %d' % (row_idx+1, len(proposals)))
                                tm_begin = time.time()
                                try:
                                    votes = self.dashd_intf.rpc_call(False, False, 'gobject', 'getcurrentvotes',
                                                                     prop.get_value('hash'))
                                except Exception:
                                    log.exception('Exception occurred while calling getvotes')
                                    errors += 1
                                    continue
                                network_duration += (time.time() - tm_begin)

                                for v_key in votes:
                                    try:
                                        if self.finishing:
                                            raise CloseDialogException

                                        v = votes[v_key]
                                        match = re.search("CTxIn\(COutPoint\(([A-Fa-f0-9]+)\s*\,\s*(\d+).+\:(\d+)\:(\w+)", v)  # v12.2
                                        if not match or len(match.groups()) != 4:
                                            match = re.search("([A-Fa-f0-9]+)\-(\d+)\:(\d+)\:(\w+)", v)  # v12.3

                                        if match and len(match.groups()) == 4:
                                            mn_ident = match.group(1) + '-' + match.group(2)
                                            voting_timestamp = int(match.group(3))
                                            voting_time = datetime.datetime.fromtimestamp(voting_timestamp)
                                            voting_result = match.group(4)
                                            if voting_result:
                                                voting_result = voting_result.upper()
                                            mn = self.masternodes_by_ident.get(mn_ident)

                                            if voting_timestamp > cur_vote_max_date:
                                                cur_vote_max_date = voting_timestamp

                                            # check if vote exists in the database
                                            if cur:
                                                tm_begin = time.time()
                                                cur.execute("SELECT id, proposal_id from VOTING_RESULTS "
                                                            "WHERE hash=?", (v_key,))

                                                found = False
                                                for row in cur.fetchall():
                                                    if row[1] == prop.db_id:
                                                        found = True
                                                        break

                                                db_oper_duration += (time.time() - tm_begin)
                                                db_oper_count += 1
                                                if not found:
                                                    votes_added.append((prop, mn, voting_time, voting_result, mn_ident, v_key))
                                            else:
                                                # no chance to check whether record exists in the DB, so assume it's not
                                                # to have it displayed on the grid
                                                votes_added.append((prop, mn, voting_time, voting_result, mn_ident, v_key))

                                        else:
                                            log.warning('Proposal %s, parsing unsuccessful for voting: %s' %
                                                            (prop.get_value('hash'), v))
                                            errors += 1
                                    except Exception as e:
                                        log.error('Error while parsing vote data for vote hash: ' + v_key)
                                        raise

                                log.info('DB calls duration (stage 1): %s, SQL count: %d' % (str(db_oper_duration),
                                                                                             db_oper_count))

                                # remove all votes from the db cache that no longer exist on the network
                                try:
                                    tm_begin = time.time()
                                    votes_to_remove: List[Tuple[int, str]] = []
                                    cur.execute("SELECT id, hash, masternode_ident from VOTING_RESULTS "
                                                "WHERE proposal_id=?", (prop.db_id,))

                                    for vote_id, vote_hash, masternode_ident in cur.fetchall():
                                        if vote_hash not in votes:
                                            votes_to_remove.append((vote_id, masternode_ident))

                                    for vote_id, masternode_ident in votes_to_remove:
                                        cur.execute('DELETE from VOTING_RESULTS where id=?', (vote_id,))
                                        db_oper_count += 1
                                        mn = self.masternodes_by_ident.get(masternode_ident)
                                        if mn:
                                            prop.remove_vote(masternode_ident)

                                    if votes_to_remove:
                                        log.info('Removed %s old votes from db cache for proposal %s',
                                                 len(votes_to_remove), prop.db_id)

                                    db_oper_duration += (time.time() - tm_begin)
                                    db_oper_count += 1
                                except Exception:
                                    log.exception('Couldn\'t remove old votes from db cache')

                                proposals_updated.append(prop)
                            except Exception:
                                log.exception('Exception while readoing votes for proposal ' + prop.get_value('hash'))
                                errors += 1

                        log.info('Network calls duration: %s for %d proposals' %
                                     (str(network_duration), (len(proposals))))

                        log.info('DB calls duration (stage 2): %s, SQL count: %d' % (str(db_oper_duration),
                                                                                        db_oper_count))

                        # save voting results to the database cache
                        for prop, mn, voting_time, voting_result, mn_ident, hash in votes_added:
                            if self.finishing:
                                raise CloseDialogException

                            if cur:
                                tm_begin = time.time()
                                try:
                                    cur.execute("INSERT INTO VOTING_RESULTS(proposal_id, masternode_ident,"
                                                " voting_time, voting_result, hash) VALUES(?,?,?,?,?)",
                                                (prop.db_id,
                                                 mn_ident,
                                                 voting_time,
                                                 voting_result,
                                                 hash))
                                except sqlite3.IntegrityError as e:
                                    if e.args and e.args[0].find('UNIQUE constraint failed') >= 0:
                                        # this vote is assigned to the same proposal but inactive one; correct this
                                        cur.execute("UPDATE VOTING_RESULTS"
                                            " set proposal_id=?, masternode_ident=?,"
                                            " voting_time=?, voting_result=? WHERE hash=?",
                                            (prop.db_id,
                                             mn_ident,
                                             voting_time,
                                             voting_result,
                                             hash))
                                db_modified = True
                                db_oper_duration += (time.time() - tm_begin)

                            if mn_ident in self.vote_columns_by_mn_ident:
                                prop.apply_vote(mn_ident, voting_time, voting_result)

                            # check if voting masternode has its column in the main grid;
                            # if so, pass the voting result to a corresponding proposal field
                            col = self.propsModel.col_by_name(mn_ident)
                            if col and col.column_for_vote:
                                if prop.get_value(col.name) != voting_result:
                                    prop.set_value(col.name, voting_result)

                            # check if currently selected proposal got new votes; if so, update details panel
                            if prop == self.current_proposal:
                                refresh_preview_votes = True

                        if cur:
                            # update proposals' voting_last_read_time
                            for prop in proposals_updated:
                                if self.finishing:
                                    raise CloseDialogException

                                prop.voting_last_read_time = time.time()
                                tm_begin = time.time()
                                cur.execute("UPDATE PROPOSALS set dmt_voting_last_read_time=? where id=?",
                                            (int(time.time()), prop.db_id))
                                db_modified = True
                                db_oper_duration += (time.time() - tm_begin)

                            log.info('DB calls duration (stage 3): %s' % str(db_oper_duration))

                            if cur_vote_max_date > last_vote_max_date:
                                # save max vot date to the DB
                                db_modified = True
                                cur.execute("UPDATE LIVE_CONFIG SET value=? WHERE symbol=?",
                                            (cur_vote_max_date, CFG_PROPOSALS_VOTES_MAX_DATE))
                                if not cur.rowcount:
                                    cur.execute("INSERT INTO LIVE_CONFIG(symbol, value) VALUES(?, ?)",
                                                (CFG_PROPOSALS_VOTES_MAX_DATE, cur_vote_max_date))

                        if errors:
                            self.errorMsg('Errors occurred while reading vote data. Look into the log file for '
                                          'details.')

                    except CloseDialogException:
                        raise

                    except DashdIndexException as e:
                        log.exception('Exception while retrieving voting data.')
                        self.errorMsg(str(e))

                    except Exception as e:
                        log.exception('Exception while retrieving voting data.')
                        self.errorMsg('Error while retrieving voting data: ' + str(e))

            except CloseDialogException:
                log.info('Closing the dialog.')

            except Exception as e:
                log.exception('Exception while retrieving voting data.')

            finally:
                if cur:
                    if db_modified:
                        self.db_intf.commit()
                    self.db_intf.release_cursor()
                self.display_message(None)

            if refresh_preview_votes and not self.finishing:
                self.refresh_details_event.set()
            log.info('Finished reading voting data from network.')
        finally:
            self.reading_vote_data = old_reading_state

    def display_proposals_data(self):
        try:
            tm_begin = time.time()

            # save the selected rows to restore them after refreshing
            sel_props = self.get_selected_proposals()

            # save the focused row number
            cur_index = self.propsView.currentIndex()
            current_row = -1
            if cur_index:
                source_row = self.propsModel.mapToSource(cur_index)
                if source_row:
                    current_row = source_row.row()

            self.propsModel.beginResetModel()
            self.propsModel.endResetModel()

            # restore the focused row
            if current_row >= 0:
                idx = self.propsModel.index(current_row, 0)
                idx = self.propsModel.mapFromSource(idx)
                self.propsView.setCurrentIndex(idx)

            # restore the selection
            sel = QItemSelection()
            sel_model = self.propsView.selectionModel()
            sel_modified = False
            for p in sel_props:
                try:
                    row_nr = self.proposals.index(p)
                    source_row_idx = self.propsModel.index(row_nr, 0)
                    dest_index = self.propsModel.mapFromSource(source_row_idx)
                    if dest_index:
                        sel.select(dest_index, dest_index)
                        sel_modified = True
                except Exception:
                    pass
            if sel_modified:
                sel_model.select(sel, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

            # if there is no saved column widths, resize widths to its contents
            widths_initialized = False
            for col in self.propsModel.columns():
                if col.initial_width:
                    widths_initialized = True
                    break

            if not widths_initialized:
                self.propsView.resizeColumnsToContents()

                # 'title' can be a quite long string so after auto-sizing columns we'd like to correct the
                # column's width to some reasonable value
                col_idx = self.propsModel.col_index_by_name('title')
                col = self.propsModel.col_by_index(col_idx)
                if col.visible and self.propsView.columnWidth(col_idx) > 430:
                    self.propsView.setColumnWidth(col_idx, 430)

            self.update_proposals_order_no()
            self.display_budget_summary()

            log.debug("Display proposals' data time: " + str(time.time() - tm_begin))
        except Exception as e:
            log.exception("Exception occurred while displaying proposals.")
            self.lblMessage.setVisible(False)
            raise Exception('Error occurred while displaying proposals: ' + str(e))

    @pyqtSlot()
    def on_btnProposalsRefresh_clicked(self):
        self.btnProposalsRefresh.setEnabled(False)
        self.btnVotesRefresh.setEnabled(False)
        self.run_thread(self, self.refresh_proposals_thread, (),
                        on_thread_finish=self.enable_refresh_buttons,
                        on_thread_exception=self.enable_refresh_buttons,
                        skip_raise_exception=True)

    def refresh_proposals_thread(self, ctrl):
        self.read_proposals_from_network()

        proposals = []
        if self.app_config.read_proposals_external_attributes:
            # select proposals for which we read additional data from external sources as DashCentral.org
            for prop in self.proposals:
                if not prop.ext_attributes_loaded:
                    proposals.append(prop)
        if proposals and not self.finishing:
            if self.read_external_attibutes(proposals):
                WndUtils.call_in_main_thread(self.display_proposals_data) # refresh display

        proposals = []  # refresh "live" proposals only
        for prop in self.proposals:
            if prop.voting_in_progress or prop.voting_last_read_time == 0:
                proposals.append(prop)

        if proposals and not self.finishing:
            self.read_voting_from_network(False, proposals)

    @pyqtSlot()
    def on_buttonBox_accepted(self):
        self.accept()

    @pyqtSlot()
    def on_buttonBox_rejected(self):
        self.reject()

    def on_propsView_selectionChanged(self, selected, deselected):
        rows = []
        for row_idx in selected.indexes():
            source_row = self.propsModel.mapToSource(row_idx)
            if source_row:
                if source_row.row() not in rows:
                    rows.append(source_row.row())

        source_row_idx = None
        if len(self.propsView.selectionModel().selectedRows()) == 1:
            cur_row = self.propsView.currentIndex()
            if cur_row:
                source_row = self.propsModel.mapToSource(cur_row)
                if source_row:
                    source_row_idx = source_row.row()

        if source_row_idx is None:
            current_proposal = None
        else:
            if 0 <= source_row_idx < len(self.proposals):
                current_proposal = self.proposals[source_row_idx]
            else:
                current_proposal = None

        if current_proposal != self.current_proposal:
            self.current_proposal = current_proposal
            self.votesModel.set_proposal(self.current_proposal)

        self.refresh_details_tabs()

        rows.clear()
        for row_idx in deselected.indexes():
            source_row = self.propsModel.mapToSource(row_idx)
            if source_row:
                if source_row.row() not in rows:
                    rows.append(source_row.row())

    def get_selected_proposals(self, active_voting_only: bool = False):
        props = []
        for row_idx in self.propsView.selectionModel().selectedRows():
            source_row = self.propsModel.mapToSource(row_idx)
            if source_row:
                prop = self.proposals[source_row.row()]
                if prop not in props and (not active_voting_only or prop.voting_in_progress):
                    props.append(prop)
        return props

    def refresh_details_tabs(self):
        try:
            proposals = self.get_selected_proposals(active_voting_only=False)
            active_proposals = []
            for p in proposals:
                if p.voting_in_progress:
                    active_proposals.append(p)
            self.refresh_vote_tab(proposals, active_proposals)

            if active_proposals:
                vote_link = '<tr class="main-row"><td class="first-col-label"></td><td class="padding"><table><tr>' \
                            '<td class="voting"><a href="#vote-yes">Vote Yes</a></td><td class="voting">' \
                            '<a href="#vote-no">Vote No</a></td><td class="voting">' \
                            '<a href="#vote-abstain">Vote Abstain</a></td></tr></table></td></tr>'
            else:
                vote_link = ''

            if self.current_proposal:
                prop = self.current_proposal
                url = self.current_proposal.get_value('url')
                status = str(self.current_proposal.voting_status)

                if not re.match('.*dashcentral\.org', url.lower()):
                    dc_url = 'https://www.dashcentral.org/p/' + prop.get_value('name')
                    dc_entry = f'<tr class="main-row"><td class="first-col-label">DC URL:</td><td class="padding">' \
                               f'<a href="{dc_url}">{dc_url}</a></td></tr>'
                else:
                    dc_entry = ''

                payment_addr = self.current_proposal.get_value('payment_address')
                if self.app_config.get_block_explorer_addr():
                    payment_url = self.app_config.get_block_explorer_addr().replace('%ADDRESS%', payment_addr)
                    payment_addr = '<a href="%s">%s</a>' % (payment_url, payment_addr)

                col_hash = self.current_proposal.get_value('collateral_hash')
                if self.app_config.get_block_explorer_tx():
                    col_url = self.app_config.get_block_explorer_tx().replace('%TXID%', col_hash)
                    col_hash = '<a href="%s">%s</a>' % (col_url, col_hash)

                def get_date_str(d):
                    if d is not None:
                        if self.budget_cycle_days <= 1:
                            return app_utils.to_string(d)
                        else:
                            return app_utils.to_string(d.date())
                    return None

                owner = prop.get_value('owner')
                if not owner:
                    owner = "&lt;Unknown&gt;"

                cycles = prop.get_value('cycles')
                if 25 <= self.budget_cycle_days <= 35:
                    if cycles == 1:
                        cycles_str = '1 month'
                    else:
                        cycles_str = str(cycles) + ' months'
                else:
                    if cycles == 1:
                        cycles_str = '1 cycle'
                    else:
                        cycles_str = str(cycles) + ' cycles'

                if prop.voting_in_progress:
                    class_voting_activity = 'vo-active'
                    voting_activity_str = 'Voting active'
                else:
                    class_voting_activity = 'vo-inactive'
                    voting_activity_str = 'Voting inactive'

                details = f"""<html>
<head>
<style type="text/css">
    td.first-col-label, td.padding {{padding-top:2px;padding-bottom:2px;}}
    td {{border-style: solid; border-color:darkgray}}
    .first-col-label {{font-weight: bold; text-align: right; padding-right:6px; white-space:nowrap}}
    .inter-label {{font-weight: bold; padding-right: 5px; padding-left: 5px; white-space:nowrap}}
    .status-1{{background-color:{COLOR_YES};color:white}}
    .status-2{{background-color:{COLOR_ABSTAIN};color:white}}
    .status-3{{color:{COLOR_YES}}}
    .status-4{{color:{COLOR_NO}}}
    .vo-active{{color:green;font-weight: bold}}
    .vo-inactive{{color:gray;font-weight: bold}}
    td.voting{{padding-right:20px;padding-top:5px;padding-bottom:5px;color: red}}
</style>
</head>
<body>
<table>
    <tbody>
        {vote_link}
        <tr class="main-row">
            <td class="first-col-label">Name:</td>
            <td class="padding">{prop.get_value('name')}</td>
        </tr>
        <tr class="main-row">
            <td class="first-col-label">Title:</td>
            <td class="padding">{prop.get_value('title')}</td>
        </tr>
        <tr class="main-row">
            <td class="first-col-label">Owner:</td>
            <td class="padding">{owner}</td>
        </tr>
        <tr class="main-row">
            <td class="first-col-label">URL:</td>
            <td class="padding"><a href="{url}">{url}</a></td>
        </tr>
        {dc_entry}
        <tr class="main-row">
            <td class="first-col-label">Voting:</td>
            <td>
                <table>
                    <tr >
                        <td class="padding" style="white-space:nowrap"><span class="status-{status} padding">{prop.get_value('voting_status_caption')}</span>
                        <br/><span class="{class_voting_activity}">{voting_activity_str}</span>
                        <br/><span class="inter-label padding">Absolute yes count: </span>{prop.get_value('absolute_yes_count')}
                        <span class="inter-label padding">&nbsp;&nbsp;Yes count: </span>{prop.get_value('yes_count')}
                        <span class="inter-label padding">&nbsp;&nbsp;No count: </span>{prop.get_value('no_count')}
                        <span class="inter-label padding">&nbsp;&nbsp;Abstain count: </span>{prop.get_value('abstain_count')}</td>
                    </tr>
                </table>
            </td>
        </tr>
        <tr class="main-row">
            <td class="first-col-label">Payment:</td>
            <td class="padding" style="white-space:nowrap"><span>{app_utils.to_string(prop.get_value('payment_amount'))} Dash&#47;cycle ({cycles_str}, {app_utils.to_string(prop.get_value('payment_amount_total'))} Dash total)
                <br/><span class="inter-label">start - end:</span>&nbsp;&nbsp;{get_date_str(prop.get_value('payment_start'))} - {get_date_str(prop.get_value('payment_end'))}</span>
                <br/><span class="inter-label">address:</span>&nbsp;&nbsp;{payment_addr}
            </td>
        </tr>
        <tr class="main-row">
            <td class="first-col-label">Creation time:</td>
            <td class="padding">{get_date_str(prop.get_value('creation_time'))}</td>
        </tr>
        <tr class="main-row">
            <td class="first-col-label">Proposal hash:</td>
            <td class="padding">{prop.get_value('hash')}</td>
        </tr>
        <tr class="main-row">
            <td class="first-col-label">Collateral hash:</td>
            <td class="padding">{col_hash}</td>
        </tr>
    </tbody>
</table>
 </body>
</html>"""

                self.edtDetails.setHtml(details)
                self.refresh_details_event.set()
            else:
                selected_props: List[Proposal] = self.get_selected_proposals()
                if len(selected_props) > 1:
                    total_amount_requested = 0.0
                    total_amount_approved = 0.0
                    total_pct_approved = ''
                    total_pct_requested = ''
                    for p in selected_props:
                        if p.voting_in_progress:
                            total_amount_requested += p.get_value('payment_amount')
                            if p.voting_status == 1:
                                total_amount_approved += p.get_value('payment_amount')
                    if self.next_budget_amount:
                        total_pct_approved = ' (' + app_utils.to_string(round(total_amount_approved * 100 / self.next_budget_amount, 2)) + ' %)'
                        total_pct_requested = ' (' + app_utils.to_string(round(total_amount_requested * 100 / self.next_budget_amount, 2)) + ' %)'

                    text = f"""<html>
<head>
<style type="text/css">
    td.first-col-label, td.padding {{padding-top:2px;padding-bottom:2px;}}
    td {{border-style: solid; border-color:darkgray}}
    .first-col-label {{font-weight: bold; text-align: right; padding-right:6px; white-space:nowrap}}
    .inter-label {{font-weight: bold; padding-right: 5px; padding-left: 5px; white-space:nowrap}}
    .status-1{{background-color:{COLOR_YES};color:white}}
    .status-2{{background-color:{COLOR_ABSTAIN};color:white}}
    .status-3{{color:{COLOR_YES}}}
    .status-4{{color:{COLOR_NO}}}
    .vo-active{{color:green;font-weight: bold}}
    .vo-inactive{{color:gray;font-weight: bold}}
    td.voting{{padding-right:20px;padding-top:5px;padding-bottom:5px;color: red}}
</style>
</head>
<body>
<table>
    <tbody>
        {vote_link}
        <tr class="main-row">
            <td class="first-col-label">Selected proposals:</td>
            <td class="padding">{len(selected_props)}</td>
        </tr>
        <tr class="main-row">
            <td class="first-col-label">Requested from the next budget:</td>
            <td class="padding">{app_utils.to_string(total_amount_requested)} Dash{total_pct_requested}</td>
        </tr>
        <tr class="main-row">
            <td class="first-col-label">Approved from the next budget:</td>
            <td class="padding">{app_utils.to_string(total_amount_approved)} Dash{total_pct_approved}</td>
        </tr>
    </tbody>
</table>
 </body>
</html>"""
                    self.edtDetails.setHtml(text)
                else:
                    self.edtDetails.setHtml('')
                self.refresh_details_event.set()

        except Exception:
            log.exception('Exception while refreshing proposal details panel')
            raise

    def refresh_vote_tab(self, proposals: List[Proposal], active_proposals: List[Proposal]):
        """ Refresh data displayed on the user-voting tab. Executed after changing focused proposal and after
        submitting a new votes. """
        if not self.controls_initialized:
            return

        if active_proposals:
            active = True
        else:
            active = False

        self.btnVoteYesForAll.setEnabled(active)
        self.btnVoteNoForAll.setEnabled(active)
        self.btnVoteAbstainForAll.setEnabled(active)

        for user_mn in self.users_masternodes:
            # setup voting buttons for each of user's masternodes
            user_mn.btn_vote_yes.setEnabled(active)
            user_mn.btn_vote_no.setEnabled(active)
            user_mn.btn_vote_abstain.setEnabled(active)
            user_votes = []
            vote_dates = []

            for p in proposals:
                vote = p.votes_by_masternode_ident.get(user_mn.masternode.ident)
                if vote:
                    if vote[1] not in user_votes:
                        user_votes.append(vote[1])
                    vote_dates.append(vote[0])

            if len(vote_dates) == 1:
                label = 'Last voted ' + user_votes[0] + ' on ' + app_utils.to_string(vote_dates[0])
            else:
                if len(proposals) == 0:
                    label = '' # no proposal selected
                elif len(vote_dates) == 0:
                    label = 'Not voted'
                elif len(vote_dates) == 1:
                    label = 'Last voted ' + user_votes[0]
                else:
                    label = 'Last voted ' + ','.join(user_votes)
            user_mn.lbl_last_vote.setText(label)

    def on_edtDetails_anchorClicked(self, link):
        vote = {
            '#vote-yes': VOTE_CODE_YES,
            '#vote-no': VOTE_CODE_NO,
            '#vote-abstain': VOTE_CODE_ABSTAIN
        }.get(link.url())

        mns = []
        for mn_info in self.users_masternodes:
            mns.append(mn_info)

        if vote:
            self.vote_on_selected_proposals(vote, mns)

    def draw_chart(self):
        """Draws a voting chart if proposal has changed.
        """
        try:
            new_chart_type = self.current_chart_type
            self.last_chart_proposal = self.current_proposal
            for s in self.vote_chart.series():
                self.vote_chart.removeSeries(s)

            if self.vote_chart.axisX() is not None:
                self.vote_chart.removeAxis(self.vote_chart.axisX())
            if self.vote_chart.axisY() is not None:
                self.vote_chart.removeAxis(self.vote_chart.axisY())

            if self.votesModel:
                if new_chart_type == 1:
                    # draw chart - incremental votes count by date

                    # key: vote day, type: timestamp, value, type: 3-element tuple of mn voting
                    votes_aggr = {}
                    mn_last_votes = {}
                    vote_mapper = {'YES': 0, 'NO': 1, 'ABSTAIN': 2}
                    dates = []
                    prev_vd = None
                    max_y = 1

                    for idx in range(len(self.votesModel.votes)-1, -1, -1):
                        v = self.votesModel.votes[idx]
                        ts = int(datetime.datetime(v[0].year, v[0].month, v[0].day, 0, 0, 0).timestamp()) * 1000
                        vd = votes_aggr.get(ts)
                        mn = v[2]
                        vote = v[1].upper()
                        if not vd:
                            # there is no entry for this date yet - add and copy vote counts from the previous
                            # one if any
                            if prev_vd is not None:
                                vd = [prev_vd[0], prev_vd[1], prev_vd[2]]
                            else:
                                vd = [0, 0, 0]  # yes, no, abstain
                            prev_vd = vd
                            votes_aggr[ts] = vd
                            dates.append(ts)

                        last_mn_vote = mn_last_votes.get(mn)
                        if last_mn_vote != vote:
                            if last_mn_vote is not None:
                                last_mn_vote = last_mn_vote.upper()
                                # subtract votes count for last mn vote type (yes, no, abstain), because
                                # changing vote by the mn
                                vd[vote_mapper[last_mn_vote]] -= 1
                            vd[vote_mapper[vote]] += 1
                            mn_last_votes[mn] = vote  # save the last mn vote
                            max_y = max(max_y, vd[vote_mapper[vote]])

                    ser_abs_yes = QLineSeries()
                    ser_abs_yes.setName('Absolute Yes')
                    pen = QPen(QColor('#6699ff'))
                    pen.setWidth(2)
                    ser_abs_yes.setPen(pen)

                    ser_yes = QLineSeries()
                    ser_yes.setName('Yes')
                    pen = QPen(QCOLOR_YES)
                    pen.setWidth(2)
                    ser_yes.setPen(pen)

                    ser_no = QLineSeries()
                    ser_no.setName('No')
                    pen = QPen(QCOLOR_NO)
                    pen.setWidth(2)
                    ser_no.setPen(pen)

                    ser_abstain = QLineSeries()
                    ser_abstain.setName('Abstain')
                    pen = QPen(QCOLOR_ABSTAIN)
                    pen.setWidth(2)
                    ser_abstain.setPen(pen)

                    max_absolute_yes = 1
                    min_absolute_yes = 0
                    for ts in dates:
                        vd = votes_aggr[ts]
                        sum_yes = vd[0]
                        sum_no = vd[1]
                        sum_abstain = vd[2]
                        ser_yes.append(ts, sum_yes)
                        ser_no.append(ts, sum_no)
                        ser_abstain.append(ts, sum_abstain)
                        absolute_yes = sum_yes - sum_no
                        max_absolute_yes = max(max_absolute_yes, absolute_yes)
                        min_absolute_yes = min(min_absolute_yes, absolute_yes)
                        ser_abs_yes.append(ts, absolute_yes)

                    self.vote_chart.addSeries(ser_abs_yes)
                    self.vote_chart.addSeries(ser_yes)
                    self.vote_chart.addSeries(ser_no)
                    self.vote_chart.addSeries(ser_abstain)

                    axisX = QDateTimeAxis()
                    axisX.setLabelsVisible(True)
                    axisX.setFormat("dd MMM")
                    self.vote_chart.addAxis(axisX, Qt.AlignBottom)
                    axisY = QValueAxis()
                    axisY.setLabelFormat('%d')
                    axisY.setLabelsVisible(True)

                    self.vote_chart.addAxis(axisY, Qt.AlignLeft)
                    ser_yes.attachAxis(axisX)
                    ser_yes.attachAxis(axisY)
                    ser_no.attachAxis(axisX)
                    ser_no.attachAxis(axisY)
                    ser_abstain.attachAxis(axisX)
                    ser_abstain.attachAxis(axisY)
                    ser_abs_yes.attachAxis(axisX)
                    ser_abs_yes.attachAxis(axisY)

                    try:
                        x_ticks = min(max(len(dates), 2), 10)
                        self.vote_chart.axisX().setTickCount(x_ticks)
                    except Exception as e:
                        raise

                    if len(dates) == 0:
                        min_date = datetime.datetime.now()
                        max_date = datetime.datetime.now()
                        max_date += datetime.timedelta(days=1)
                    elif len(dates) == 1:
                        min_date = datetime.datetime.fromtimestamp(dates[0] / 1000)
                        max_date = min_date
                        max_date += datetime.timedelta(days=1)
                    else:
                        min_date = datetime.datetime.fromtimestamp(dates[0] / 1000)
                        max_date = datetime.datetime.fromtimestamp(dates[len(dates)-1] / 1000)

                    self.vote_chart.axisX().setMin(min_date)
                    self.vote_chart.axisX().setMax(max_date)
                    self.vote_chart.axisY().setMin(min(0, min_absolute_yes))
                    max_y = max_y + int(max_y * 0.05)
                    self.vote_chart.axisY().setMax(max_y)

                elif new_chart_type == 2:
                    bs_abs_yes = QBarSet("Absolute Yes")
                    bs_abs_yes.setColor(QColor('#6699ff'))
                    bs_abs_yes.setLabelColor(QColor('#6699ff'))
                    bs_abs_yes.append(self.current_proposal.get_value('absolute_yes_count'))

                    bs_yes = QBarSet('Yes')
                    bs_yes.setColor(QCOLOR_YES)
                    bs_yes.setLabelColor(QCOLOR_YES)
                    bs_yes.append(self.current_proposal.get_value('yes_count'))

                    bs_no = QBarSet('No')
                    bs_no.setColor(QCOLOR_NO)
                    bs_no.setLabelColor(QCOLOR_NO)
                    bs_no.append(self.current_proposal.get_value('no_count'))

                    bs_abstain = QBarSet('Abstain')
                    bs_abstain.setColor(QCOLOR_ABSTAIN)
                    bs_abstain.setLabelColor(QCOLOR_ABSTAIN)
                    bs_abstain.append(self.current_proposal.get_value('abstain_count'))

                    ser = QBarSeries()
                    ser.setLabelsVisible(True)
                    ser.setLabelsPosition(3)  # LabelsOutsideEnd
                    ser.append(bs_abs_yes)
                    ser.append(bs_yes)
                    ser.append(bs_no)
                    ser.append(bs_abstain)
                    self.vote_chart.addSeries(ser)

                    if self.vote_chart.axisX() is None:
                        axisX = QBarCategoryAxis()
                        axisX.setLabelsVisible(False)
                        self.vote_chart.addAxis(axisX, Qt.AlignBottom)
                        self.vote_chart.setAxisX(axisX, ser)

                    if self.vote_chart.axisY() is None:
                        axisY = QValueAxis()
                        axisY.setLabelFormat('%d')
                        axisY.setLabelsVisible(True)
                        self.vote_chart.addAxis(axisY, Qt.AlignLeft)
                        self.vote_chart.setAxisX(axisY, ser)
                    else:
                        self.vote_chart.setAxisY(self.vote_chart.axisY(), ser)

                    self.vote_chart.axisY().setMin(min(0, self.current_proposal.get_value('absolute_yes_count')))
                    max_y = max(self.current_proposal.get_value('yes_count'),
                                self.current_proposal.get_value('no_count'),
                                self.current_proposal.get_value('abstain_count'),
                                self.current_proposal.get_value('absolute_yes_count'))
                    max_y = max_y + int(max_y * 0.15)  # space for label
                    self.vote_chart.axisY().setMax(max_y)

                elif new_chart_type == 3:
                    # chart of changing vote by masternodes by date

                    # dict of lists (key: timestamp) of how many vote-changes has been made within a specific date
                    votes_change_by_date = {}
                    vote_change_mapper = {
                        'No->Yes': 0,
                        'Abstain->Yes': 1,
                        'No->Abstain': 2,
                        'Yes->Abstain': 3,
                        'Yes->No': 4,
                        'Abstain->No': 5
                    }
                    vote_change_colors = {
                        0: '#47d147',
                        1: '#248f24',
                        2: '#ff9933',
                        3: '#e67300',
                        4: '#ff0000',
                        5: '#cc2900'
                    }
                    change_existence = [False] * 6
                    mn_last_votes = {}
                    dates = []
                    max_y = 0

                    for idx in range(len(self.votesModel.votes)-1, -1, -1):
                        v = self.votesModel.votes[idx]
                        ts = int(datetime.datetime(v[0].year, v[0].month, v[0].day, 0, 0, 0).timestamp()) * 1000
                        mn = v[2]
                        vote = v[1]

                        last_mn_vote = mn_last_votes.get(mn)
                        if last_mn_vote and last_mn_vote != vote:
                            vd = votes_change_by_date.get(ts)
                            if not vd:
                                # there is no entry for this date yet
                                vd = [0] * 6
                                votes_change_by_date[ts] = vd
                                dates.append(ts)
                            change_type = last_mn_vote.capitalize() + '->' + vote.capitalize()
                            change_type_idx = vote_change_mapper[change_type]
                            vd[change_type_idx] += 1
                            change_existence[change_type_idx] = True
                            max_y = max(max_y, vd[change_type_idx])
                        mn_last_votes[mn] = vote  # save the last mn vote

                    ser = QBarSeries()
                    ser.setLabelsVisible(True)
                    ser.setLabelsPosition(3)  # LabelsOutsideEnd

                    for change_type_idx in list(range(6)):
                        if change_existence[change_type_idx]:  # NO->YES
                            # get the string representation of the mn vote change
                            change_label = '?'
                            for key, value in vote_change_mapper.items():
                                if value == change_type_idx:
                                    change_label = key

                            bs = QBarSet(change_label)
                            bs.setColor(QColor(vote_change_colors[change_type_idx]))
                            bs.setLabelColor(QColor(vote_change_colors[change_type_idx]))
                            for date in dates:
                                bs.append(votes_change_by_date[date][change_type_idx] )
                            ser.append(bs)

                    self.vote_chart.addSeries(ser)

                    if self.vote_chart.axisX() is None:
                        axisX = QBarCategoryAxis()
                        self.vote_chart.addAxis(axisX, Qt.AlignBottom)
                    else:
                        axisX = self.vote_chart.axisX()

                    dates_str = []
                    for date in dates:
                        d = QDateTime(datetime.datetime.fromtimestamp(date/1000))
                        ds = QLocale.toString(app_utils.get_default_locale(), d, 'dd MMM')
                        dates_str.append(ds)
                    axisX.clear()
                    axisX.append(dates_str)
                    self.vote_chart.setAxisX(axisX, ser)
                    axisX.setLabelsVisible(True)

                    if self.vote_chart.axisY() is None:
                        axisY = QValueAxis()
                        axisY.setLabelFormat('%d')
                        axisY.setLabelsVisible(True)
                        self.vote_chart.addAxis(axisY, Qt.AlignLeft)
                        self.vote_chart.setAxisY(axisY, ser)
                    else:
                        self.vote_chart.setAxisY(self.vote_chart.axisY(), ser)
                    max_y = max_y + 1 + int(max_y * 0.15)  # space for label
                    self.vote_chart.axisY().setMax(max_y)

                self.last_chart_type = new_chart_type

        except Exception:
            log.exception('Exception while drawing vote chart.')

    def refresh_preview_panel_thread(self, ctrl):
        """Thread reloading additional proposal data after changing current proposal. This is done in the background
        to avoid blocking the UI when user jumps quickly between proposals - the work involves reading voting data
        from the cache database, so it's relatively time-consuming operation.
        """
        last_proposal_read = None
        last_chart_type = None

        def apply_grid_data():
            self.votesModel.refresh_view()
            self.draw_chart()

        while not self.finishing:
            try:
                if last_proposal_read != self.current_proposal:
                    self.votesModel.read_votes()
                    last_proposal_read = self.current_proposal
                    last_chart_type = self.current_chart_type
                    WndUtils.call_in_main_thread(apply_grid_data)
                elif last_chart_type != self.current_chart_type:
                    last_chart_type = self.current_chart_type
                    WndUtils.call_in_main_thread(self.draw_chart)

                wr = self.refresh_details_event.wait(2)
                if self.refresh_details_event.is_set():
                    self.refresh_details_event.clear()
            except Exception:
                log.exception('Exception while refreshing preview panel')

    def on_chart_type_change(self):
        if self.rbVotesChartIncremental.isChecked():
            self.current_chart_type = 1
        elif self.rbVotesChartFinal.isChecked():
            self.current_chart_type = 2
        elif self.rbVotesChartChanges.isChecked():
            self.current_chart_type = 3
        else:
            self.current_chart_type = -1
        self.refresh_details_event.set()

    @pyqtSlot(bool)
    def on_rbVotesChartIncremental_toggled(self, checked):
        self.on_chart_type_change()

    @pyqtSlot(bool)
    def on_rbVotesChartFinal_toggled(self, checked):
        self.on_chart_type_change()

    @pyqtSlot(bool)
    def on_rbVotesChartChanges_toggled(self, checked):
        self.on_chart_type_change()

    def apply_votes_filter(self):
        changed_chb = self.votesProxyModel.set_only_my_votes(self.chbOnlyMyVotes.isChecked())
        changed_text = self.votesProxyModel.set_filter_text(self.edtVotesViewFilter.text())
        if changed_chb or changed_text:
            self.votesProxyModel.invalidateFilter()
        self.btnApplyVotesViewFilter.setEnabled(False)

    @pyqtSlot()
    def on_btnVotesRefresh_clicked(self):
        def enable_button():
            self.btnVotesRefresh.setEnabled(True)
            self.btnProposalsRefresh.setEnabled(True)

        if self.current_proposal:
            self.btnVotesRefresh.setEnabled(False)
            self.btnProposalsRefresh.setEnabled(False)
            self.run_thread(self, self.read_voting_from_network_thread, (True, [self.current_proposal]),
                            on_thread_finish=enable_button)

    @pyqtSlot(int)
    def on_chbOnlyMyVotes_stateChanged(self, state):
        self.apply_votes_filter()

    @pyqtSlot(str)
    def on_edtVotesViewFilter_textEdited(self, text):
        self.btnApplyVotesViewFilter.setEnabled(True)

    def on_edtVotesViewFilter_returnPressed(self):
        self.apply_votes_filter()

    def on_btnApplyVotesViewFilter_clicked(self):
        self.apply_votes_filter()

    def vote_thread(self, ctrl, proposal_list: List[Proposal], masternodes: List[VotingMasternode],
                    vote_code: str, vote_errors_out: List[Tuple[Proposal, MasternodeConfig, str]]):

        vote = {VOTE_CODE_YES: 'yes', VOTE_CODE_NO: 'no', VOTE_CODE_ABSTAIN: 'abstain'}[vote_code]
        successful_proposal_list = []
        successful_votes = 0
        unsuccessful_votes = 0
        ctrl.dlg_config_fun(dlg_title="Applying votes to the network...", show_progress_bar=False)

        for prop in proposal_list:
            if self.finishing:
                break
            prop_hash = prop.get_value('hash')

            for vote_idx, mn_info in enumerate(masternodes):
                if self.finishing:
                    break
                ctrl.display_msg_fun(f"Processing <b>{vote.upper()}</b> vote for the proposal <b>'{prop.get_value('name')}"
                                     f"</b>'<br>on behalf of the masternode: {mn_info.masternode_config.name} "
                                     f"({mn_info.masternode_config.ip})")

                cur_ts = int(time.time())
                sig_time = cur_ts
                step = 1
                vote_sig = ''
                serialize_for_sig = ''

                try:

                    last_result = prop.get_last_mn_vote(mn_info.masternode.ident)
                    if last_result is not None:
                        last_vote_ts = last_result[0].timestamp()
                    else:
                        last_vote_ts = None

                    if self.app_config.add_random_offset_to_vote_time:

                        if last_vote_ts is not None: # and cur_ts - last_vote_ts < 1800:
                            # new vote's timestamp cannot be less than the last vote for this proposal-mn pair
                            min_bound = max(int(last_vote_ts), cur_ts + self.app_config.sig_time_offset_min)
                            max_bound = cur_ts + self.app_config.sig_time_offset_max
                            sig_time = random.randint(min_bound, max_bound)
                        else:
                            sig_time += random.randint(self.app_config.sig_time_offset_min,
                                                       self.app_config.sig_time_offset_max)

                    if last_vote_ts is not None and sig_time < last_vote_ts:
                        # if the last vote timestamp is still grater than the current vote ts, correct the new one
                        # The current ts can be less than the previus one when:
                        #   - user turned off the vote offset in the configuration and the previous offset was > 0
                        #   - last offset drawn was higher than the current one (it's random) and a user
                        #     is voting a short time after the previus one
                        sig_time = last_vote_ts + 10

                    serialize_for_sig = mn_info.masternode.ident + '|' + \
                                        prop_hash + '|' + \
                                        '1' + '|' + \
                                        vote_code + '|' + \
                                        str(sig_time)

                    log.info('Vote message to sign: ' + serialize_for_sig)
                    step = 2
                    vote_sig = dash_utils.ecdsa_sign(
                        serialize_for_sig,
                        mn_info.masternode_config.get_current_key_for_voting(self.app_config, self.dashd_intf),
                        self.app_config.dash_network)

                    step = 3
                    v_res = self.dashd_intf.voteraw(
                        masternode_tx_hash=mn_info.masternode_config.collateralTx,
                        masternode_tx_index=int(mn_info.masternode_config.collateralTxIndex),
                        governance_hash=prop_hash,
                        vote_signal='funding',
                        vote=vote,
                        sig_time=sig_time,
                        vote_sig=vote_sig)

                    step = 4
                    if v_res == 'Voted successfully':
                        prop.apply_vote(mn_ident=mn_info.masternode.ident,
                                        vote_timestamp=datetime.datetime.fromtimestamp(sig_time),
                                        vote_result=vote.upper())
                        successful_votes += 1
                        if prop not in successful_proposal_list:
                            successful_proposal_list.append(prop)
                    else:
                        vote_errors_out.append((prop, mn_info.masternode_config, v_res))
                        unsuccessful_votes += 1

                except Exception as e:
                    if step in (1, 4):
                        msg = 'Error: ' + str(e)
                    elif step == 2:
                        msg = "Error while signing vote message with masternode's private key: " + str(e)
                    else:
                        msg = "Error while broadcasting vote message: " + str(e)
                        # write some info to the log file for analysis in case of problems
                        log.info('masternode_pub_key: %s' %
                                     str(dash_utils.wif_privkey_to_pubkey(
                                         mn_info.masternode_config.get_current_key_for_voting(
                                             self.app_config, self.dashd_intf))))
                        log.info('masternode_pub_key_hash: %s' %
                                     str(dash_utils.pubkey_to_address(dash_utils.wif_privkey_to_pubkey(
                                         mn_info.masternode_config.get_current_key_for_voting(
                                             self.app_config, self.dashd_intf)), self.app_config.dash_network)))
                        log.info('masternode_tx_hash: %s' % str(mn_info.masternode_config.collateralTx))
                        log.info('masternode_tx_index: %s' % str(mn_info.masternode_config.collateralTxIndex))
                        log.info('governance_hash: %s' % prop_hash)
                        log.info('vote_sig: %s' % vote_sig)
                        log.info('sig_time: %s' % str(sig_time))
                        t = time.time()
                        log.info('cur_time: timestamp: %s, timestr local: %s, timestr UTC: %s' %
                                     (str(t), str(datetime.datetime.fromtimestamp(t)),
                                      str(datetime.datetime.utcfromtimestamp(t))))
                        log.info('serialize_for_sig: %s' % str(serialize_for_sig))
                    vote_errors_out.append((prop, mn_info.masternode_config, msg))

                    unsuccessful_votes += 1

            if successful_proposal_list:
                cur = self.db_intf.get_cursor()
                try:
                    # move back the 'last read' time to force reading vote data from the network
                    # next time and save it to the db
                    for p in successful_proposal_list:
                        cur.execute("UPDATE PROPOSALS set dmt_voting_last_read_time=? where id=?",
                                    (int(time.time()) - VOTING_RELOAD_TIME, p.db_id))
                except Exception:
                    log.exception('Exception while saving configuration data.')
                finally:
                    self.db_intf.commit()
                    self.db_intf.release_cursor()

            msg = ''
            if successful_votes > 0:
                if unsuccessful_votes > 0:
                    msg = f'Vote finished, successful votes: {successful_votes}, unsuccessful: {unsuccessful_votes}'
                else:
                    msg = f'Vote finished, successful votes: {successful_votes}'
            elif unsuccessful_votes > 0:
                msg = f'Vote finished with errors'
            if msg:
                msg += ' (<a href="#close">close</a>)'
            self.display_message(msg)

    def vote_on_selected_proposals(self, vote_code, masternodes: Optional[List]):
        vote_errors: List[Tuple[Proposal, MasternodeConfig, str]] = []

        def on_vote_thread_finished(vote_errors: List[Tuple[Proposal, MasternodeConfig, str]]):
            if vote_errors:
                msg = ''
                for prop, mn, err in vote_errors:
                    msg += err + f" (proposal: '{prop.get_value('name')}', masternode: '{mn.name}')\n\n"
                self.errorMsg(msg)
            self.sending_votes = False
            self.display_proposals_data()
            self.refresh_details_tabs()

        if self.sending_votes:
            self.errorMsg('Wait for the previus votes processing finishes.')

        if not self.dashd_intf.open():
            self.errorMsg('Dash daemon not connected')
        else:
            props = self.get_selected_proposals(active_voting_only=True)
            vote_str = {VOTE_CODE_YES: 'YES', VOTE_CODE_NO: 'NO', VOTE_CODE_ABSTAIN: 'ABSTAIN'}[vote_code]

            if not masternodes:
                masternodes = []
                for mn_info in self.users_masternodes:
                    masternodes.append(mn_info)

            if masternodes:
                if not self.app_config.confirm_when_voting or \
                        self.queryDlg(
                            f'Vote {vote_str} for {len(props)} proposal(s) on behalf of {len(masternodes)} masternode(s)?',
                            buttons=QMessageBox.Yes | QMessageBox.Cancel,
                            default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:

                    if len(props) > 0:
                        self.sending_votes = True
                        self.run_thread_dialog(self.vote_thread, (props, masternodes, vote_code, vote_errors), True,
                                               center_by_window=self)
                        on_vote_thread_finished(vote_errors)
                    else:
                        raise Exception('No selected proposals to vote')
            else:
                raise Exception('No masternodes to vote with')

    @pyqtSlot()
    def on_btnVoteYesForAll_clicked(self):
        mns = []
        for mn_info in self.users_masternodes:
            mns.append(mn_info)
        if mns:
            self.vote_on_selected_proposals(VOTE_CODE_YES, mns)

    @pyqtSlot()
    def on_btnVoteNoForAll_clicked(self):
        mns = []
        for mn_info in self.users_masternodes:
            mns.append(mn_info)
        if mns:
            self.vote_on_selected_proposals(VOTE_CODE_NO, mns)

    @pyqtSlot()
    def on_btnVoteAbstainForAll_clicked(self):
        mns = []
        for mn_info in self.users_masternodes:
            mns.append(mn_info)
        if mns:
            self.vote_on_selected_proposals(VOTE_CODE_ABSTAIN, mns)

    def on_btnVoteYes_clicked(self, mn_info):
        self.vote_on_selected_proposals(VOTE_CODE_YES, [mn_info])

    def on_btnVoteNo_clicked(self, mn_info):
        self.vote_on_selected_proposals(VOTE_CODE_NO, [mn_info])

    def on_btnVoteAbstain_clicked(self, mn_info):
        self.vote_on_selected_proposals(VOTE_CODE_ABSTAIN, [mn_info])

    @pyqtSlot()
    def on_btnProposalsSaveToCSV_clicked(self):
        """ Save the proposals' data to a CSV file. """
        file_name = self.save_file_query(self, self.app_config, 'Enter name of the CSV file to save',
                                         filter="CSV files (*.csv);;All Files (*)",
                                         initial_filter="CSV files (*.csv)")
        if file_name:
            try:
                with codecs.open(file_name, 'w', 'utf-8') as f_ptr:
                    elems = [col.caption for col in self.propsModel.columns()]
                    self.write_csv_row(f_ptr, elems)
                    for prop in sorted(self.proposals, key = lambda p: p.initial_order_no):
                        elems = [prop.get_value(col.name) for col in self.propsModel.columns()]
                        self.write_csv_row(f_ptr, elems)
                self.infoMsg('Proposals data successfully saved.')
            except Exception as e:
                log.exception("Exception saving proposals' data to a file.")
                self.errorMsg('Couldn\'t save a CSV file due to the following error: ' + str(e))

    @pyqtSlot()
    def on_btnVotesSaveToCSV_clicked(self):
        """ Save the voting data of the current proposal to a CSV file. """
        if self.votesModel and self.current_proposal:
            file_name = self.save_file_query(self, self.app_config, 'Enter name of the CSV file to save',
                                             filter="CSV files (*.csv);;All Files (*)",
                                             initial_filter="CSV files (*.csv)")
            if file_name:
                try:
                    with codecs.open(file_name, 'w', 'utf-8') as f_ptr:
                        elems = ['Vote date/time', 'Vote', 'Masternode', 'User\'s masternode']
                        self.write_csv_row(f_ptr, elems)

                        for v in self.votesModel.votes:
                            self.write_csv_row(f_ptr, v)

                    self.infoMsg('Votes of the proposal "%s" successfully saved.' %
                                 self.current_proposal.get_value('name'))
                except Exception as e:
                    log.exception("Exception saving proposals votes to a file.")
                    self.errorMsg('Couldn\'t save a CSV file due to the following error: ' + str(e))

    @pyqtSlot()
    def on_btnProposalsColumns_clicked(self):
        self.propsModel.exec_columns_dialog(self)

    @pyqtSlot(str)
    def on_edtProposalFilter_textEdited(self, text):
        self.propsModel.set_filter_text(text)
        self.propsModel.invalidateFilter()

    @pyqtSlot(bool)
    def on_chb_only_active_toggled(self, checked):
        self.propsModel.set_filter_only_active(checked)
        self.propsModel.invalidateFilter()
        self.update_proposals_order_no()

    @pyqtSlot(bool)
    def on_chb_only_new_toggled(self, checked):
        self.propsModel.set_filter_only_new(checked)
        self.propsModel.invalidateFilter()
        self.update_proposals_order_no()

    @pyqtSlot(bool)
    def on_chb_not_voted_toggled(self, checked):
        self.propsModel.set_filter_only_not_voted(checked)
        self.propsModel.invalidateFilter()
        self.update_proposals_order_no()


class ProposalsModel(ExtSortFilterTableModel):
    def __init__(self, parent, proposals):
        ExtSortFilterTableModel.__init__(self, parent, columns=[
            ProposalColumn('no', 'No', True),
            ProposalColumn('name', 'Name', False),
            ProposalColumn('title', 'Title', True),
            ProposalColumn('owner', 'Owner', True),
            ProposalColumn('voting_status_caption', 'Voting Status', True),
            ProposalColumn('active', 'Active', True),
            ProposalColumn('payment_amount', 'Amount', True),
            ProposalColumn('cycles', 'Cycles', True),
            ProposalColumn('payment_amount_total', 'Total Amount', True),  # payment_amount * cycles
            ProposalColumn('current_cycle', 'Current Cycle', True),
            ProposalColumn('absolute_yes_count', 'Absolute Yes Count', True),
            ProposalColumn('yes_count', "Yes Count", True),
            ProposalColumn('no_count', 'No Count', True),
            ProposalColumn('abstain_count', 'Abstain Count', True),
            ProposalColumn('payment_start', 'Payment Start', True),
            ProposalColumn('payment_end', 'Payment End', True),
            ProposalColumn('payment_address', 'Payment Address', False),
            ProposalColumn('creation_time', 'Creation Time', True),
            ProposalColumn('url', 'URL', False),
            ProposalColumn('type', 'Type', False),
            ProposalColumn('hash', 'Hash', False),
            ProposalColumn('collateral_hash', 'Collateral Hash', False),
            ProposalColumn('fBlockchainValidity', 'fBlockchainValidity', False),
            ProposalColumn('fCachedValid', 'fCachedValid', False),
            ProposalColumn('fCachedDelete', 'fCachedDelete', False),
            ProposalColumn('fCachedFunding', 'fCachedFunding', False),
            ProposalColumn('fCachedEndorsed', 'fCachedEndorsed', False),
            ProposalColumn('ObjectType', 'ObjectType', False),
            ProposalColumn('IsValidReason', 'IsValidReason', False)
        ], columns_movable=True, filtering_sorting=True)
        self.columns_movable = True
        self.sorting_column_name = 'no'
        self.sorting_order = Qt.AscendingOrder
        self.budget_cycle_days = 28.8
        self.parent = parent
        self.proposals = proposals
        self.filter_text = ''
        self.filter_columns = []
        self.filter_only_active = True
        self.filter_only_new = False
        self.filter_only_not_voted = False
        self.set_attr_protection()

    def set_view(self, table_view: QTableView):
        super().set_view(table_view)
        link_delagate = wnd_utils.HyperlinkItemDelegate(table_view)
        link_delagate.linkActivated.connect(self.hyperlink_activated)
        table_view.setItemDelegateForColumn(self.col_index_by_name('url'), link_delagate)
        table_view.setItemDelegateForColumn(self.col_index_by_name('name'), link_delagate)
        table_view.setItemDelegateForColumn(self.col_index_by_name('title'), link_delagate)

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.proposals)

    def setData(self, row, col, role=None):
        index = self.index(row, col)
        index = self.proxy_model.mapFromSource(index)
        self.dataChanged.emit(index, index)
        return True

    def set_budget_cycle_days(self, days):
        self.budget_cycle_days = days

    def flags(self, index):
        ret = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return ret

    def data(self, index, role=None):
        if index.isValid():
            col_idx = index.column()
            row_idx = index.row()
            if row_idx < len(self.proposals) and col_idx < self.col_count():
                prop = self.proposals[row_idx]
                col = self.col_by_index(col_idx)
                if prop:
                    if role == Qt.DisplayRole:
                        if col.name in ('payment_start', 'payment_end', 'creation_time'):
                            value = prop.get_value(col.name)
                            if value is not None:
                                if self.budget_cycle_days < 1:
                                    return app_utils.to_string(value)
                                else:
                                    return app_utils.to_string(value.date())
                            else:
                                return ''
                        elif col.name in ('active'):
                            return 'Yes' if prop.get_value(col.name) is True else 'No'
                        elif col.name in ('title', 'url', 'name'):
                            value = prop.get_value(col.name)
                            url = prop.get_value('url')
                            url = f'<a href="{url}">{value}</a>'
                            return url
                        elif col.name == 'no':
                            return str(prop.initial_order_no + 1)
                        else:
                            value = prop.get_value(col.name)
                            if isinstance(value, datetime.datetime):
                                return str(value)
                            return value

                    elif role == Qt.ForegroundRole:
                        if col.name == 'voting_status_caption':
                            if prop.voting_status == 1:
                                return QtGui.QColor('white')
                            elif prop.voting_status == 2:
                                return QtGui.QColor('white')
                            elif prop.voting_status == 3:
                                return QCOLOR_YES
                            elif prop.voting_status == 4:
                                return QCOLOR_NO
                        elif col.column_for_vote:
                            value = prop.get_value(col.name)
                            if value == 'YES':
                                return QCOLOR_YES
                            elif value == 'ABSTAIN':
                                return QCOLOR_ABSTAIN
                            elif value == 'NO':
                                return QCOLOR_NO

                    elif role == Qt.BackgroundRole:
                        if col.name == 'voting_status_caption':
                            if prop.voting_status == 1:
                                return QCOLOR_YES
                            elif prop.voting_status == 2:
                                return QCOLOR_ABSTAIN

                    elif role == Qt.TextAlignmentRole:
                        if col.name in ('payment_amount', 'payment_amount_total', 'absolute_yes_count', 'yes_count',
                                        'no_count', 'abstain_count', 'cycles', 'current_cycle'):
                            return Qt.AlignRight

                    elif role == Qt.FontRole:
                        if col.column_for_vote:
                            font = QtGui.QFont()
                            font.setBold(True)
                            return font
        return QVariant()

    def hyperlink_activated(self, link):
        QDesktopServices.openUrl(QUrl(link))

    def set_filter_text(self, text):
        self.filter_text = text

    def set_filter_only_active(self, only_active: bool):
        self.filter_only_active = only_active

    def set_filter_only_new(self, only_new: bool):
        self.filter_only_new = only_new

    def set_filter_only_not_voted(self, only_not_voted: bool):
        self.filter_only_not_voted = only_not_voted

    def add_filter_column(self, idx):
        if idx >= 0 and idx not in self.filter_columns:
            self.filter_columns.append(idx)

    def lessThan(self, col_index, left_row_index, right_row_index):
        col = self.col_by_index(col_index)
        if col:

            if 0 <= left_row_index < len(self.proposals):
                left_prop = self.proposals[left_row_index]

                if 0 <= right_row_index < len(self.proposals):
                    right_prop = self.proposals[right_row_index]
                    left_value = left_prop.get_value(col.name)
                    right_value = right_prop.get_value(col.name)

                    if col.name in ('name', 'url', 'title'):
                        # compare hyperlink columns
                        if not left_value:
                            left_value = ""
                        if not right_value:
                            right_value = ""
                        left_value = left_value.lower()
                        right_value = right_value.lower()
                        return left_value < right_value

                    elif col.name == 'voting_status_caption':

                        left_count = left_prop.get_value('absolute_yes_count')
                        right_count = right_prop.get_value('absolute_yes_count')
                        return left_count < right_count

                    elif col.name == 'no':
                        left_voting_in_progress = left_prop.voting_in_progress
                        right_voting_in_progress = right_prop.voting_in_progress

                        if left_voting_in_progress == right_voting_in_progress:
                            # statuses 1, 2: voting in progress
                            # for even statuses, order by creation time (newest first)
                            diff = right_prop.get_value('creation_time') < left_prop.get_value('creation_time')
                        else:
                            diff = left_prop.voting_status < right_prop.voting_status
                        return diff

                    elif col.name in ('payment_start', 'payment_end', 'creation_time'):
                        diff = right_value < left_value
                        return diff

    def filterAcceptsRow(self, row_index, source_parent):
        will_show = True
        try:
            if row_index >= 0 and row_index < len(self.proposals):
                prop: Proposal = self.proposals[row_index]
                if self.filter_text:
                    filter_text_lower = self.filter_text.lower()
                    will_show = False
                    for col_idx in self.filter_columns:
                        data = str(prop.get_value(col_idx))
                        if data and data.lower().find(filter_text_lower) >= 0:
                            will_show = True
                            break

                if self.filter_only_active and not prop.voting_in_progress:
                    will_show = False
                elif self.filter_only_new and prop.get_value('current_cycle') != 0:
                    will_show = False
                elif self.filter_only_not_voted:
                    if not prop.not_voted_by_user():
                        will_show = False
            else:
                pass
        except Exception:
            log.exception('Exception wile filtering votes')
        return will_show


class VotesFilterProxyModel(QSortFilterProxyModel):
    """ Proxy for votes sorting/filtering. """

    def __init__(self, parent):
        super().__init__(parent)
        self.only_my_votes = False
        self.filter_text = ''

    def set_only_my_votes(self, only_my_votes):
        if only_my_votes != self.only_my_votes:
            self.only_my_votes = only_my_votes
            return True
        else:
            return False

    def set_filter_text(self, filter_text):
        if self.filter_text != filter_text:
            self.filter_text = filter_text.lower()
            return True
        else:
            return False

    def filterAcceptsRow(self, source_row, source_parent):
        will_show = True
        try:
            if self.only_my_votes:
                index = self.sourceModel().index(source_row, 3, source_parent)
                if index:
                    data = self.sourceModel().data(index, Qt.DisplayRole)
                    if not data:
                        will_show = False

            if will_show and self.filter_text:
                # if none of remaining columns contain self.filter_text do not show record
                will_show = False
                for col_idx in (0, 1, 2, 3):
                    index = self.sourceModel().index(source_row, col_idx, source_parent)
                    if index:
                        data = str(self.sourceModel().data(index, Qt.DisplayRole))
                        if data and data.lower().find(self.filter_text) >= 0:
                            will_show = True
                            break
        except Exception:
            log.exception('Exception wile filtering votes')
        return will_show


class VotesModel(QAbstractTableModel):
    def __init__(self, proposals_dlg, masternodes, users_masternodes_by_ident, db_intf):
        QAbstractTableModel.__init__(self, proposals_dlg)
        self.proposals_dlg = proposals_dlg
        self.masternodes = masternodes
        self.db_intf = db_intf
        self.users_masternodes_by_ident = users_masternodes_by_ident
        self.only_my_votes = False
        self.proposal = None
        self.votes = []  # list of tuples: voting time (datetime), vote, masternode_label, users_masternode_name
        self.columns = ['Vote timestamp', 'Vote', 'Masternode', "User's Masternode"]

    def columnCount(self, parent=None, *args, **kwargs):
        return 4

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.votes)

    def headerData(self, section, orientation, role=None):
        if role != 0:
            return QVariant()
        if orientation == 0x1:
            return self.columns[section] if 0 <= section < len(self.columns) else ''
        else:
            return str(section + 1)

    def flags(self, index):
        ret = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return ret

    def data(self, index, role=None):
        if index.isValid():
            col_idx = index.column()
            row_idx = index.row()
            if row_idx < len(self.votes) and col_idx < len(self.columns):
                vote = self.votes[row_idx]
                if vote:
                    if role == Qt.DisplayRole:
                        if col_idx == 0:    # vote timestamp
                            value = vote[0]
                            if value is not None:
                                return app_utils.to_string(value)
                            else:
                                return ''
                        elif col_idx == 1:  # YES/NO/ABSTAIN
                            return vote[1]
                        elif col_idx == 2:  # voting masternode label
                            return vote[2]
                        elif col_idx == 3:  # voting masternode config-name if exists in the user's configuration
                            return vote[3]
                    elif role == Qt.ForegroundRole:
                        if col_idx == 1:
                            if vote[1] == 'YES':
                                return QCOLOR_YES
                            elif vote[1] == 'NO':
                                return QCOLOR_NO
                            elif vote[1] == 'ABSTAIN':
                                return QCOLOR_ABSTAIN
                    elif role == Qt.FontRole:
                        if col_idx == 1:
                            font = QtGui.QFont()
                            font.setBold(True)
                            return font

        return QVariant()

    def read_votes(self):
        try:
            self.votes.clear()
            tm_begin = time.time()
            cur = self.db_intf.get_cursor()
            if self.proposal:
                log.debug('Get votes fot proposal id: ' + str(self.proposal.db_id))
                cur.execute("SELECT voting_time, voting_result, masternode_ident, m.ip "
                            "FROM VOTING_RESULTS v "
                            "LEFT OUTER JOIN masternodes m on m.ident = v.masternode_ident "
                            "WHERE proposal_id=? order by voting_time desc", (self.proposal.db_id,))

                for row in cur.fetchall():
                    if self.proposals_dlg.finishing:
                        raise CloseDialogException
                    users_mn_name = ''
                    mn_label = row[3]
                    if not mn_label:
                        mn_label = row[2]

                    # check if this masternode is in the user's configuration
                    users_mn = self.users_masternodes_by_ident.get(row[2])
                    if users_mn:
                        users_mn_name = users_mn.masternode_config.name

                    self.votes.append((datetime.datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S'),
                                       row[1], mn_label, users_mn_name))
                log.debug('Reading votes time from DB: %s' % str(time.time() - tm_begin))

        except CloseDialogException:
            log.info('Closing the dialog.')

        except Exception as e:
            log.exception('SQLite error')

        finally:
            self.db_intf.release_cursor()

    def set_proposal(self, proposal):
        self.proposal = proposal

    def refresh_view(self):
        self.beginResetModel()
        self.endResetModel()

    def finish(self):
        pass
