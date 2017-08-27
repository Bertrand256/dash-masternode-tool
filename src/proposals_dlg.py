#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-05
import datetime
import json
import logging
import os
import random
import re
import threading
import time
from functools import partial

from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import Qt, pyqtSlot, QModelIndex, QVariant, QAbstractTableModel, QSortFilterProxyModel, QUrl
from PyQt5.QtGui import QColor
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
from PyQt5.QtWidgets import QDialog, QTableWidgetItem, QDialogButtonBox, QHeaderView, QMessageBox
import src.wnd_utils as wnd_utils
from src import dash_utils
from src.app_config import DATE_FORMAT, DATETIME_FORMAT
from src.dashd_intf import DashdIndexException
from src.ui import ui_proposals
from src.common import AttrsProtected
from src.wnd_utils import WndUtils
import sqlite3


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


class ProposalColumn(AttrsProtected):
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
        AttrsProtected.__init__(self)
        self.name = name
        self.caption = caption
        self.visible = visible
        self.column_for_vote = column_for_vote
        self.my_masternode = None  # True, if column for masternode vote relates to user's masternode; such columns
                                   # can not be removed
        self.initial_width = None
        self.initial_order_no = None
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


class Proposal(AttrsProtected):
    def __init__(self, columns, vote_columns_by_mn_ident):
        super().__init__()
        self.visible = True
        self.columns = columns
        self.values = {}  # dictionary of proposal values (key: ProposalColumn)
        self.db_id = None
        self.marker = None
        self.modified = False
        self.voting_last_read_time = 0
        self.voting_in_progress = True
        self.vote_columns_by_mn_ident = vote_columns_by_mn_ident
        self.votes_by_masternode_ident = {}  # list of tuples: vote_timestamp, vote_result

        # voting_status:
        #   1: voting in progress, funding
        #   2: voting in progress, no funding
        #   3: deadline passed, funding
        #   4: deadline passed, no funding
        self.voting_status = None

        self.name_col_widget = None
        self.url_col_widget = None

        self.set_attr_protection()

    def set_value(self, name, value):
        """
        Sets value for a specified Proposal column.
        :returns True, if new value is different that old value
        """
        for col in self.columns:
            if col.name == name:
                old_value = self.values.get(col)
                if old_value != value:
                    self.modified = True
                    self.values[col] = value
                    return True
                else:
                    return False
        raise AttributeError('Invalid Proposal value name: ' + name)

    def get_value(self, name):
        """
        Returns value of for a specified column name.
        """
        for col in self.columns:
            if col.name == name:
                return self.values.get(col)
        raise AttributeError('Invalid Proposal value name: ' + name)

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


    def apply_values(self, masternodes, last_suberblock_time, next_superblock_datetime):
        """ Calculate voting_in_progress and voting_status values, based on colums' values.
        """

        payment_start = self.get_value('payment_start')
        payment_end = self.get_value('payment_end')
        funding_enabled = self.get_value('fCachedFunding')

        if payment_start and payment_end:
            payment_start = payment_start.timestamp()
            payment_end = payment_end.timestamp()
            now = time.time()
            self.voting_in_progress = (payment_start > last_suberblock_time) or \
                                      (payment_end > next_superblock_datetime and funding_enabled)
        else:
            self.voting_in_progress = False

        abs_yes_count = self.get_value('absolute_yes_count')
        mns_count = len(masternodes)
        if self.voting_in_progress:
            if abs_yes_count >= mns_count * 0.1:
                self.voting_status = 1  # will be funded
                self.set_value('voting_status_caption', 'Will be funded (%d of %d needed)' %
                               (abs_yes_count, int(mns_count * 0.1)))
            else:
                self.voting_status = 2  # needs additional votes
                self.set_value('voting_status_caption', 'Needs additional %d votes' % (int(mns_count * 0.1) -
                                                                                       abs_yes_count))
        else:
            if funding_enabled:
                self.voting_status = 3  # funded
                self.set_value('voting_status_caption', 'Passed with funding')
            else:
                self.voting_status = 4  # not funded
                self.set_value('voting_status_caption', 'Not funded')


class VotingMasternode(AttrsProtected):
    def __init__(self, masternode, masternode_config):
        """ Stores information about masternodes for which user has ability to vote.
        :param masternode: ref to an object storing mn information read from the network (dashd_intf.Masternode)
        :param masternode_config: ref to an object storing mn user's configuration (app_config.MasterNodeConfig)
        """
        super().__init__()
        self.masternode = masternode
        self.masternode_config = masternode_config
        self.btn_vote_yes = None  # dynamically created button for voting YES on behalf of this masternode
        self.btn_vote_no = None  # ... for voting NO
        self.btn_vote_abstain = None  # ... for voting ABSTAIN
        self.lbl_last_vote = None  # label to display last voting results for this masternode and currently focused prop
        self.set_attr_protection()


class ProposalsDlg(QDialog, ui_proposals.Ui_ProposalsDlg, wnd_utils.WndUtils):
    def __init__(self, parent, dashd_intf):
        QDialog.__init__(self, parent=parent)
        wnd_utils.WndUtils.__init__(self, app_path=parent.app_path)
        self.main_wnd = parent
        self.dashd_intf = dashd_intf
        self.columns = [
            ProposalColumn('name', 'Name', True),
            ProposalColumn('voting_status_caption', 'Voting Status', True),
            ProposalColumn('payment_amount', 'Amount', True),
            ProposalColumn('absolute_yes_count', 'Absolute YES Count', True),
            ProposalColumn('yes_count', 'YES Count', True),
            ProposalColumn('no_count', 'NO Count', True),
            ProposalColumn('abstain_count', 'Abstain Count', True),
            ProposalColumn('payment_start', 'Payment Start', True),
            ProposalColumn('payment_end', 'Payment End', True),
            ProposalColumn('payment_address', 'Payment Address', True),
            ProposalColumn('creation_time', 'Creation Time', True),
            ProposalColumn('url', 'URL', True),
            ProposalColumn('type', 'Type', False),
            ProposalColumn('hash', 'Hash', True),
            ProposalColumn('collateral_hash', 'Collateral Hash', True),
            ProposalColumn('fBlockchainValidity', 'fBlockchainValidity', False),
            ProposalColumn('fCachedValid', 'fCachedValid', False),
            ProposalColumn('fCachedDelete', 'fCachedDelete', False),
            ProposalColumn('fCachedFunding', 'fCachedFunding', False),
            ProposalColumn('fCachedEndorsed', 'fCachedEndorsed', False),
            ProposalColumn('ObjectType', 'ObjectType', True),
            ProposalColumn('IsValidReason', 'IsValidReason', True)
        ]
        self.vote_columns_by_mn_ident = {}
        self.proposals = []
        self.proposals_by_hash = {}  #  dict of Proposal object indexed by proposal hash
        self.proposals_by_db_id = {}
        self.masternodes = []
        self.masternodes_by_ident = {}
        self.masternodes_by_db_id = {}

        # masternodes existing in the user's configuration, which can vote - list of VotingMasternode objects
        self.users_masternodes = []
        self.users_masternodes_by_ident = {}

        self.mn_count = None
        self.db_active = False
        self.governanceinfo = None
        self.last_superblock_time = None
        self.next_superblock_time = None
        self.proposals_last_read_time = 0
        self.current_proposal = None

        # open and initialize database for caching proposals data
        db_conn = None
        try:
            db_conn = sqlite3.connect(self.main_wnd.config.db_cache_file_name)
            cur = db_conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS PROPOSALS(id INTEGER PRIMARY KEY, name TEXT, payment_start TEXT," 
                        " payment_end TEXT, payment_amount REAL, yes_count INTEGER, absolute_yes_count INTEGER,"
                        " no_count INTEGER, abstain_count INTEGER, creation_time TEXT, url TEXT, payment_address TEXT,"
                        " type INTEGER, hash TEXT,  collateral_hash TEXT, f_blockchain_validity INTEGER,"
                        " f_cached_valid INTEGER, f_cached_delete INTEGER, f_cached_funding INTEGER, "
                        " f_cached_endorsed INTEGER, object_type INTEGER, "
                        " is_valid_reason TEXT, dmt_active INTEGER, dmt_create_time TEXT, dmt_deactivation_time TEXT,"
                        " dmt_voting_last_read_time INTEGER)")

            # Below: masternode_ident column is for identifying votes of no longer existing masternodes. For existing
            # masternodes we use masternode_id (db identifier)
            cur.execute("CREATE TABLE IF NOT EXISTS VOTING_RESULTS(id INTEGER PRIMARY KEY, proposal_id INTEGER,"
                        " masternode_id INTEGER, masternode_ident TEXT, voting_time TEXT, voting_result TEXT,"
                        "hash TEXT)")  #todo: has column for testing only
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS IDX_VOTING_RESULTS_HASH ON VOTING_RESULTS(hash)")  # todo: testing
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_VOTING_RESULTS_1 ON VOTING_RESULTS(proposal_id)")
            # cur.execute("CREATE INDEX IF NOT EXISTS IDX_VOTING_RESULTS_2 ON VOTING_RESULTS(masternode_id)")
            # cur.execute("CREATE INDEX IF NOT EXISTS IDX_VOTING_RESULTS_3 ON VOTING_RESULTS(masternode_ident)")
            # cur.execute("CREATE INDEX IF NOT EXISTS IDX_VOTING_RESULTS_4 ON VOTING_RESULTS(voting_time)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_VOTING_RESULTS_3 ON VOTING_RESULTS(proposal_id, voting_time, "
                        "masternode_id, masternode_ident)")  # for finding if vote already exists in the DB

            # Create table for storing live data for example last read time of proposals
            cur.execute("CREATE TABLE IF NOT EXISTS LIVE_CONFIG(symbol text PRIMARY KEY, value TEXT)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_LIVE_CONFIG_SYMBOL ON LIVE_CONFIG(symbol)")

            cur.execute("SELECT value FROM LIVE_CONFIG WHERE symbol=?", (CFG_PROPOSALS_LAST_READ_TIME,))
            row = cur.fetchone()
            if row:
                self.proposals_last_read_time = int(row[0])

            self.db_active = True
        except Exception as e:
            logging.exception('SQLite initialization error')
        finally:
            if db_conn:
                db_conn.close()

        self.setupUi()

    def setupUi(self):
        try:
            ui_proposals.Ui_ProposalsDlg.setupUi(self, self)
            self.setWindowTitle('Proposals')

            self.resize(self.get_cache_value('WindowWidth', self.size().width(), int),
                        self.get_cache_value('WindowHeight', self.size().height(), int))

            self.splitter.setStretchFactor(0, 1)
            self.splitter.setStretchFactor(1, 0)

            self.votesSplitter.setStretchFactor(0, 0)
            self.votesSplitter.setStretchFactor(1, 1)

            self.lblDetailsName.setProperty('data', True)
            self.lblDetailsUrl.setProperty('data', True)
            self.lblDetailsVotingStatus.setProperty('data', True)
            self.lblDetailsYesCount.setProperty('data', True)
            self.lblDetailsNoCount.setProperty('data', True)
            self.lblDetailsAbstainCount.setProperty('data', True)
            self.lblDetailsCreationTime.setProperty('data', True)
            self.lblDetailsPaymentAmount.setProperty('data', True)
            self.lblDetailsPaymentAddress.setProperty('data', True)
            self.lblDetailsPaymentStart.setProperty('data', True)
            self.lblDetailsPaymentEnd.setProperty('data', True)
            self.lblDetailsProposalHash.setProperty('data', True)
            self.lblDetailsCollateralHash.setProperty('data', True)

            self.lblDetailsNameLabel.setProperty('label', True)
            self.lblDetailsUrlLabel.setProperty('label', True)
            self.lblDetailsVotingStatusLabel.setProperty('label', True)
            self.lblDetailsYesCountLabel.setProperty('label', True)
            self.lblDetailsNoCountLabel.setProperty('label', True)
            self.lblDetailsAbstainCountLabel.setProperty('label', True)
            self.lblDetailsCreationTimeLabel.setProperty('label', True)
            self.lblDetailsPaymentAmountLabel.setProperty('label', True)
            self.lblDetailsPaymentAddressLabel.setProperty('label', True)
            self.lblDetailsPaymentStartLabel.setProperty('label', True)
            self.lblDetailsPaymentEndLabel.setProperty('label', True)
            self.lblDetailsProposalHashLabel.setProperty('label', True)
            self.lblDetailsCollateralHashLabel.setProperty('label', True)

            # self.tabDetails.setStyleSheet('QLabel[data="true"]{border:1px solid lightgray;padding:2px;
            # background-color:white}')
            self.tabDetails.setStyleSheet('QLabel[label="true"]{font-weight:bold}')

            # assign a new currentChanged handler; solution not very pretty, but there is no
            # signal for this purpose in QTableView
            self.propsView.currentChanged = self.on_propsView_currentChanged

            # let's define "dynamic" columns that show voting results for user's masternodes
            for idx, mn in enumerate(self.main_wnd.config.masternodes):
                mn_ident = mn.collateralTx + '-' + str(mn.collateralTxIndex)
                if mn_ident:
                    self.add_voting_column(mn_ident, 'Vote (' + mn.name + ')', my_masternode=True,
                                           insert_before_column=self.column_index_by_name('absolute_yes_count'))

            """ Read configuration of grid columns such as: display order, visibility. Also read configuration
             of dynamic columns: when user decides to display voting results of a masternode, which is not 
             in his configuration (because own mns are shown by defailt).
             Format: list of dicts:
             1. for static columns
                {
                   name:  Column name (str), 
                   visible: (bool)
                },
             2. for dynamic (masternode voting) columns:
                {
                    name: Masternode ident (str),
                    visible: (bool),
                    column_for_vote: True if the column relates to masternode voting (bool),
                    caption: Column's caption (str)
                }
            """
            cfg_cols = self.get_cache_value('ProposalsColumnsCfg', [], list)
            if isinstance(cfg_cols, list):
                for col_saved_index, c in enumerate(cfg_cols):
                    name = c.get('name')
                    visible = c.get('visible', True)
                    column_for_vote = c.get('column_for_vote')
                    caption = c.get('caption')
                    initial_width = c.get('width')
                    if not isinstance(initial_width, int):
                        initial_width = None

                    if isinstance(name, str) and isinstance(visible, bool) and isinstance(column_for_vote, bool):
                        found = False
                        for col in self.columns:
                            if col.name == name:
                                col.visible = visible
                                col.initial_width = initial_width
                                col.initial_order_no = col_saved_index
                                found = True
                                break
                        if not found and column_for_vote and caption:
                            # add voting column defined by the user
                            self.add_voting_column(name, caption, my_masternode=False,
                                                   insert_before_column=self.column_index_by_name('payment_start'))
            else:
                logging.warning('Invalid type of cached ProposalsColumnsCfg')
            self.columns.sort(key = lambda x: x.initial_order_no if x.initial_order_no is not None else 100)

            self.propsView.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
            self.propsView.setSortingEnabled(True)

            # create model serving data to the view
            self.propsModel = ProposalsModel(self, self.columns, self.proposals)
            self.proxyModel = ProposalFilterProxyModel(self, self.proposals, self.columns)
            self.proxyModel.setSourceModel(self.propsModel)
            self.propsView.setModel(self.proxyModel)

            # set initial column widths
            for col_idx, col in enumerate(self.columns):
                if col.initial_width:
                    self.propsView.setColumnWidth(col_idx, col.initial_width)

            self.propsView.verticalHeader().setDefaultSectionSize(
                self.propsView.verticalHeader().fontMetrics().height() + 6)

            self.votesView.verticalHeader().setDefaultSectionSize(
                self.votesView.verticalHeader().fontMetrics().height() + 6)

            # setup a proposal's web-page preview
            self.webView = QWebEngineView(self.tabWebPreview)
            self.webView.settings().setAttribute(QWebEngineSettings.FocusOnNavigationEnabled, False)
            sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
            sizePolicy.setHorizontalStretch(0)
            sizePolicy.setVerticalStretch(0)
            self.webView.setSizePolicy(sizePolicy)
            self.layoutWebPreview.addWidget(self.webView)
            self.tabsDetails.resize(self.tabsDetails.size().width(),
                                   self.get_cache_value('DetailsHeight', 200, int))

            # setting up a view with voting history
            self.votesView.setSortingEnabled(True)

            # create model serving data to the view
            self.votesModel = VotesModel(self, self.masternodes, self.masternodes_by_db_id,
                                         self.users_masternodes_by_ident,
                                         self.main_wnd.config.db_cache_file_name)
            self.votesProxyModel = VotesFilterProxyModel(self)
            self.votesProxyModel.setSourceModel(self.votesModel)
            self.votesView.setModel(self.votesProxyModel)

            # restore votes grid columns' widths
            cfg_cols = self.get_cache_value('VotesColumnsCfg', [], list)
            if isinstance(cfg_cols, list):
                for col_saved_index, c in enumerate(cfg_cols):
                    initial_width = c.get('width')
                    if not isinstance(initial_width, int):
                        initial_width = None
                    if initial_width and col_saved_index < self.votesModel.columnCount():
                        self.votesView.setColumnWidth(col_saved_index, initial_width)
            else:
                logging.warning('Invalid type of cached VotesColumnsCfg')
            self.votesSplitter.setSizes([self.get_cache_value('VotesGridWidth', 600, int)])
            self.chbOnlyMyVotes.setChecked(self.get_cache_value('VotesHistoryShowOnlyMyVotes', False, bool))

            filter_text = self.get_cache_value('VotesHistoryFilterText', '', str)
            self.edtVotesViewFilter.setText(filter_text)
            if filter_text:
                self.votesProxyModel.set_filter_text(filter_text)
            self.btnApplyVotesViewFilter.setEnabled(False)
            self.tabsDetails.setCurrentIndex(0)

            def setup_user_voting_controls():
                # setup a user-voting tab
                mn_index = 0
                self.btnVoteYesForAll.setProperty('yes', True)
                self.btnVoteNoForAll.setProperty('no', True)
                self.btnVoteAbstainForAll.setProperty('abstain', True)
                self.btnVoteYesForAll.setEnabled(False)
                self.btnVoteNoForAll.setEnabled(False)
                self.btnVoteAbstainForAll.setEnabled(False)
                for user_mn in self.users_masternodes:
                    lbl = QtWidgets.QLabel(self.tabVoting)
                    lbl.setText('<b>%s</b> (%s)' % (user_mn.masternode_config.name, user_mn.masternode.IP))
                    lbl.setAlignment(Qt.AlignRight|Qt.AlignTrailing|Qt.AlignVCenter)
                    self.layoutUserVoting.addWidget(lbl, mn_index + 1, 0, 1, 1)

                    user_mn.btn_vote_yes = QtWidgets.QPushButton(self.tabVoting)
                    user_mn.btn_vote_yes.setText("Vote Yes")
                    user_mn.btn_vote_yes.setProperty('yes', True)
                    user_mn.btn_vote_yes.setEnabled(False)
                    user_mn.btn_vote_yes.clicked.connect(partial(self.on_btnVoteYes_clicked, user_mn))
                    self.layoutUserVoting.addWidget(user_mn.btn_vote_yes, mn_index + 1, 1, 1, 1)

                    user_mn.btn_vote_no = QtWidgets.QPushButton(self.tabVoting)
                    user_mn.btn_vote_no.setText("Vote No")
                    user_mn.btn_vote_no.setProperty('no', True)
                    user_mn.btn_vote_no.setEnabled(False)
                    user_mn.btn_vote_no.clicked.connect(partial(self.on_btnVoteNo_clicked, user_mn))
                    self.layoutUserVoting.addWidget(user_mn.btn_vote_no, mn_index + 1, 2, 1, 1)

                    user_mn.btn_vote_abstain = QtWidgets.QPushButton(self.tabVoting)
                    user_mn.btn_vote_abstain.setText("Vote Abstain")
                    user_mn.btn_vote_abstain.setProperty('abstain', True)
                    user_mn.btn_vote_abstain.setEnabled(False)
                    user_mn.btn_vote_abstain.clicked.connect(partial(self.on_btnVoteAbstain_clicked, user_mn))
                    self.layoutUserVoting.addWidget(user_mn.btn_vote_abstain, mn_index + 1, 3, 1, 1)

                    user_mn.lbl_last_vote = QtWidgets.QLabel(self.tabVoting)
                    user_mn.lbl_last_vote.setText('')
                    self.layoutUserVoting.addWidget(user_mn.lbl_last_vote, mn_index + 1, 4, 1, 1)
                    mn_index += 1
                self.tabVoting.setStyleSheet('QPushButton[yes="true"]{color:green} QPushButton[no="true"]{color:red}'
                                             'QPushButton[abstain="true"]{color:orange}')

            def finished_read_proposals_from_network():
                """ Called after finished reading proposals data from the Dash network. It invokes a thread
                  reading voting data from the Dash network.  """

                if self.current_proposal is None and len(self.proposals) > 0:
                    self.propsView.selectRow(0)

                self.runInThread(self.read_voting_from_network_thread, (False, self.proposals))

            def finished_read_data_thread():
                """ Called after finished reading initial data from the DB. Funtion executes reading proposals'
                   data from network if needed.
                """
                setup_user_voting_controls()

                if self.current_proposal is None and len(self.proposals) > 0:
                    self.propsView.selectRow(0)

                if int(time.time()) - self.proposals_last_read_time > PROPOSALS_CACHE_VALID_SECONDS or \
                                len(self.proposals) == 0:
                    # read proposals from network only after a configured time
                    self.runInThread(self.read_proposals_from_network_thread, (),
                                     on_thread_finish=finished_read_proposals_from_network)

            # read initial data (from db) inside a thread and then read data from network if needed
            self.runInThread(self.read_data_thread, (), on_thread_finish=finished_read_data_thread)
        except:
            logging.exception('Exception occurred')
            raise

    def updateUi(self):
        pass

    def closeEvent(self, event):
        self.save_config()

    def save_config(self):
        """
        Saves dynamic configuration (for example grid columns) to cache.
        :return:
        """
        try:
            cfg = []
            for col_idx, col in enumerate(self.columns):
                c = {
                    'name': col.name,
                    'visible': col.visible,
                    'column_for_vote': col.column_for_vote,
                    'caption': col.caption,
                    'width': self.propsView.columnWidth(col_idx)
                }
                cfg.append(c)
            self.set_cache_value('ProposalsColumnsCfg', cfg)

            # save voting-results tab configuration
            # columns' withds
            cfg.clear()
            for col_idx in range(0, self.votesModel.columnCount()):
                width = self.votesView.columnWidth(col_idx)
                c = {'width': width}
                cfg.append(c)
            self.set_cache_value('VotesColumnsCfg', cfg)
            self.set_cache_value('VotesGridWidth', self.votesView.size().width())

            self.set_cache_value('WindowWidth', self.size().width())
            self.set_cache_value('WindowHeight', self.size().height())
            self.set_cache_value('DetailsHeight', self.tabsDetails.size().height())
            self.set_cache_value('VotesHistoryShowOnlyMyVotes', self.chbOnlyMyVotes.isChecked())
            self.set_cache_value('VotesHistoryFilterText', self.edtVotesViewFilter.text())
            self.set_cache_value('TabDetailsCurrentIndex', self.tabsDetails.currentIndex())

        except Exception as e:
            logging.exception('Exception while saving dialog configuration to cache.')

    def add_voting_column(self, mn_ident, mn_label, my_masternode=None, insert_before_column=None):
        """
        Adds a dynamic column that displays a vote of the masternode with the specified identifier.
        :return:
        """
        # first check if this masternode is already added to voting columns
        for col in self.columns:
            if col.column_for_vote == True and col.name == mn_ident:
                return  # column for this masternode is already added

        col = ProposalColumn(mn_ident, mn_label, visible=True, column_for_vote=True)
        if isinstance(insert_before_column, int) and insert_before_column < len(self.columns):
            self.columns.insert(insert_before_column, col)
        else:
            self.columns.append(col)
        self.vote_columns_by_mn_ident[mn_ident] = col

        if my_masternode is None:
            # check if the specified masternode is in the user configuration; if so, mark the column
            # that it can't be removed
            for idx, mn in enumerate(self.main_wnd.config.masternodes):
                mn_ident_cfg = mn.collateralTx + '-' + str(mn.collateralTxIndex)
                if mn_ident_cfg == mn_ident:
                    col.my_masternode = True
                    break
        else:
            col.my_masternode = my_masternode

    def display_message(self, message):
        def disp(message):
            if message:
                self.lblMessage.setVisible(True)
                self.lblMessage.setText('<b style="color:blue">' + message + '<b>')
            else:
                self.lblMessage.setVisible(False)
                self.lblMessage.setText('')

        if threading.current_thread() != threading.main_thread():
            WndUtils.callFunInTheMainThread(disp, message)
        else:
            disp(message)

    def column_index_by_name(self, name):
        """
        Returns index of a column with a given name.
        :param name: name of a column
        :return: index of a column
        """
        for idx, pc in enumerate(self.columns):
            if pc.name == name:
                return idx
        raise Exception('Invalid column name: ' + name)

    def column_by_name(self, name):
        for idx, pc in enumerate(self.columns):
            if pc.name == name:
                return pc
        raise Exception('Invalid column name: ' + name)

    def read_proposals_from_network(self):
        """ Reads proposals from the Dash network. """

        def find_prop_data(prop_data, level=1):
            """ Find proposal dict inside a list extracted from DataString field. """
            if isinstance(prop_data, list):
                if len(prop_data) > 2:
                    logging.warning('len(prop_data) > 2 [level: %d]. prop_data: %s' % (level, json.dumps(prop_data)))

                if len(prop_data) >= 2 and prop_data[0] == 'proposal' and isinstance(prop_data[1], dict):
                    return prop_data[1]
                elif len(prop_data) >= 1 and isinstance(prop_data[0], list):
                    return find_prop_data(prop_data[0], level+1)
            return None

        try:
            self.display_message('Reading proposals data, please wait...')
            logging.debug('Reading proposals from the Dash network.')
            proposals_new = self.dashd_intf.gobject("list", "valid", "proposals")
            rows_added = False

            # reset marker value in all existing Proposal object - we'll use it to check which
            # of prevoiusly read proposals do not exit anymore
            for prop in self.proposals:
                prop.marker = False
                prop.modified = False  # all modified proposals will be saved to DB cache

            for pro_key in proposals_new:
                prop_raw = proposals_new[pro_key]

                prop_dstr = prop_raw.get("DataString")
                prop_data_json = json.loads(prop_dstr)
                prop_data = find_prop_data(prop_data_json)
                if prop_data is None:
                    continue

                prop = self.proposals_by_hash.get(prop_raw['Hash'])
                if not prop:
                    is_new = True
                    prop = Proposal(self.columns, self.vote_columns_by_mn_ident)
                else:
                    is_new = False
                prop.marker = True

                prop.set_value('name', prop_data['name'])
                prop.set_value('payment_start', datetime.datetime.fromtimestamp(int(prop_data['start_epoch'])))
                prop.set_value('payment_end', datetime.datetime.fromtimestamp(int(prop_data['end_epoch'])))
                prop.set_value('payment_amount', float(prop_data['payment_amount']))
                prop.set_value('yes_count', int(prop_raw['YesCount']))
                prop.set_value('absolute_yes_count', int(prop_raw['AbsoluteYesCount']))
                prop.set_value('no_count', int(prop_raw['NoCount']))
                prop.set_value('abstain_count', int(prop_raw['AbstainCount']))
                prop.set_value('creation_time', datetime.datetime.fromtimestamp(int(prop_raw["CreationTime"])))
                prop.set_value('url', prop_data['url'])
                prop.set_value('payment_address', prop_data["payment_address"])
                prop.set_value('type', prop_data['type'])
                prop.set_value('hash', prop_raw['Hash'])
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

            db_conn = None
            try:
                db_conn = sqlite3.connect(self.main_wnd.config.db_cache_file_name)
                cur = db_conn.cursor()

                for prop in self.proposals:
                    if prop.marker:
                        if not prop.db_id:
                            logging.debug('Adding new proposal to DB. Hash: ' + prop.get_value('hash'))
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
                                logging.debug('Updating proposal in the DB. Hash: %s, DB id: %d' %
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
                    prop = self.proposals[prop_idx]

                    if not prop.marker:
                        logging.debug('Deactivating proposal in the cache. Hash: %s, DB id: %s' %
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
                    WndUtils.callFunInTheMainThread(self.display_proposals_data)

            except Exception as e:
                logging.exception('Exception while saving proposals to db.')
            finally:
                if db_conn:
                    db_conn.commit()
                    db_conn.close()

            logging.debug('Finished updating proposals data.')

        except Exception as e:
            logging.exception('Exception wile reading proposals from Dash network.')

    def read_proposals_from_network_thread(self, ctrl):
        """ Reads proposals data from netowrk (Dash daemon).
        :param ctrl:
        :return:
        """
        try:
            logging.info('Started thread read_proposals_from_network_thread')
            self.read_proposals_from_network()
        except Exception as e:
            logging.exception('Exception while reading proposals from network.')

    def read_data_thread(self, ctrl):
        """ Reads data from the database.
        :param ctrl:
        """

        try:
            self.display_message('Connecting to Dash daemon, please wait...')
            if not self.dashd_intf.open():
                self.errorMsg('Dash daemon not connected')
            else:
                try:

                    try:
                        self.display_message('Reading governance data, please wait...')

                        # get the date-time of the last superblock and calculate the date-time of the next one
                        self.governanceinfo = self.dashd_intf.getgovernanceinfo()

                        sb_last = self.governanceinfo.get('lastsuperblock')
                        sb_next = self.governanceinfo.get('nextsuperblock')

                        sb_last_hash = self.dashd_intf.getblockhash(sb_last)
                        bh = self.dashd_intf.getblockheader(sb_last_hash)
                        self.last_superblock_time = bh['time']
                        self.next_superblock_time = bh['time'] + (sb_next - sb_last) * 2.5 * 60

                    except Exception as e:
                        self.errorMsg("Coundn't read governanceinfo from the Dash network. "
                                      "Because ot this, some features may not work correcly. Error details: " + str(e))

                    # get list of all masternodes
                    self.display_message('Reading masternode data, please wait...')

                    # prepare a dict of user's masternodes configs (app_config.MasterNodeConfig); key: masternode
                    # ident (transaction id-transaction index)
                    users_mn_configs_by_ident = {}
                    for mn_cfg in self.main_wnd.config.masternodes:
                        ident = mn_cfg.collateralTx + '-' + mn_cfg.collateralTxIndex
                        users_mn_configs_by_ident[ident] = mn_cfg

                    mns = self.dashd_intf.get_masternodelist('full')
                    self.masternodes = mns
                    self.mn_count = 0
                    statuses = {}

                    # count all active masternodes
                    for mn in mns:
                        if mn.status in ('ENABLED','PRE_ENABLED','NEW_START_REQUIRED','WATCHDOG_EXPIRED'):
                            self.mn_count += 1
                        if statuses.get(mn.status):
                            statuses[mn.status] += 1
                        else:
                            statuses[mn.status] = 1

                        # add mn to an ident indexed dict
                        self.masternodes_by_ident[mn.ident] = mn
                        self.masternodes_by_db_id[mn.db_id] = mn

                        mn_cfg = users_mn_configs_by_ident.get(mn.ident)
                        if mn_cfg:
                            if not mn.ident in self.users_masternodes_by_ident:
                                vmn = VotingMasternode(mn, mn_cfg)
                                self.users_masternodes.append(vmn)
                                self.users_masternodes_by_ident[mn.ident] = vmn

                    if self.db_active:
                        db_conn = None
                        try:
                            self.display_message('Reading proposals data from DB, please wait...')

                            # read all proposals from DB cache
                            db_conn = sqlite3.connect(self.main_wnd.config.db_cache_file_name)
                            cur = db_conn.cursor()

                            logging.debug("Reading proposals' data from DB")
                            cur.execute(
                                "SELECT name, payment_start, payment_end, payment_amount,"
                                " yes_count, absolute_yes_count, no_count, abstain_count, creation_time,"
                                " url, payment_address, type, hash, collateral_hash, f_blockchain_validity,"
                                " f_cached_valid, f_cached_delete, f_cached_funding, f_cached_endorsed, object_type,"
                                " is_valid_reason, dmt_active, dmt_create_time, dmt_deactivation_time, id,"
                                " dmt_voting_last_read_time "
                                "FROM PROPOSALS where dmt_active=1"
                            )

                            for row in cur.fetchall():
                                prop = Proposal(self.columns, self.vote_columns_by_mn_ident)
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
                                prop.apply_values(self.masternodes, self.last_superblock_time,
                                                  self.next_superblock_time)
                                self.proposals.append(prop)
                                self.proposals_by_hash[prop.get_value('hash')] = prop
                                self.proposals_by_db_id[prop.db_id] = prop

                            logging.debug("Finished reading proposals' data from DB")

                            def disp():
                                self.propsView.sortByColumn(self.column_index_by_name('voting_status_caption'),
                                                            Qt.AscendingOrder)
                                self.display_proposals_data()

                            # display data, now without voting results, which will be read below
                            WndUtils.callFunInTheMainThread(disp)

                        except Exception as e:
                            logging.exception('Exception while saving proposals to db.')
                        finally:
                            if db_conn:
                                db_conn.close()

                    # read voting data from DB (only for "voting" columns)
                    self.read_voting_from_db(self.columns)

                except DashdIndexException as e:
                    self.errorMsg(str(e))

                except Exception as e:
                    logging.exception('Exception while retrieving proposals data.')
                    self.errorMsg('Error while retrieving proposals data: ' + str(e))
        except Exception as e:
            logging.exception('Exception while reading data.')
        finally:
            self.display_message("")

    def read_voting_from_db(self, columns):
        """ Read voting results for specified voting columns
        :param columns list of voting columns for which data will be loaded from db; it is used when user adds
          a new column - wee want read data only for this column
        """
        db_conn = None
        self.display_message('Reading voting data from DB, please wait...')
        begin_time = time.time()

        try:
            db_conn = sqlite3.connect(self.main_wnd.config.db_cache_file_name)
            cur = db_conn.cursor()

            for col in columns:
                if col.column_for_vote:
                    mn_ident = col.name
                    mn = self.masternodes_by_ident.get(mn_ident)
                    if mn:
                        cur.execute("SELECT proposal_id, voting_time, voting_result "
                                    "FROM VOTING_RESULTS WHERE masternode_id=?", (mn.db_id,))
                        for row in cur.fetchall():
                            prop = self.proposals_by_db_id.get(row[0])
                            if prop:
                                prop.apply_vote(mn_ident, datetime.datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S'),
                                                row[2])

        except Exception as e:
            logging.exception('Exception while saving proposals to db.')
        finally:
            if db_conn:
                db_conn.close()
            time_diff = time.time() - begin_time
            logging.info('Voting data read from database time: %s seconds' % str(time_diff))

    def read_voting_from_network_thread(self, ctrl, force_reload, proposals):
        """
        Retrieve from a Dash daemon voting results for all defined masternodes, for all visible Proposals.
        :param ctrl:
        :param force_reload: if False (default) we read voting results only for Proposals, which hasn't
          been read yet (for example has been filtered out).
        :param proposals: list of proposals, which votes will be retrieved
        :return:
        """

        last_vote_max_date = 0
        cur_vote_max_date = 0
        db_conn = None
        db_modified = False
        refresh_preview_votes = False
        try:
            # read the date/time of the last vote, read from the DB the last time, to initially filter out
            # of all older votes from finding if it has its record in the DB:
            db_conn = sqlite3.connect(self.main_wnd.config.db_cache_file_name)
            cur = db_conn.cursor()
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

                    for row_idx, prop in enumerate(proposals):

                        if force_reload or \
                           (((time.time() - prop.voting_last_read_time) > VOTING_RELOAD_TIME) and
                            (prop.voting_in_progress or prop.voting_last_read_time == 0)):
                           # read voting results from the Dash network if:
                           #  - haven't ever read voting results for this proposal
                           #  - if voting for this proposal is still open , but VOTING_RELOAD_TIME of seconds have
                           #    passed since the last read or user forced to reload votes

                            self.display_message('Reading voting data %d of %d' % (row_idx+1, len(proposals)))
                            logging.debug('Reading votes for proposal ' + prop.get_value('hash'))
                            votes = self.dashd_intf.gobject("getvotes", prop.get_value('hash'))
                            logging.debug('Votes read finished')

                            for v_key in votes:
                                v = votes[v_key]
                                match = re.search("CTxIn\(COutPoint\(([A-Fa-f0-9]+)\s*\,\s*(\d+).+\:(\d+)\:(\w+)", v)
                                if len(match.groups()) == 4:
                                    mn_ident = match.group(1) + '-' + match.group(2)
                                    voting_timestamp = int(match.group(3))
                                    voting_time = datetime.datetime.fromtimestamp(voting_timestamp)
                                    voting_result = match.group(4)
                                    mn = self.masternodes_by_ident.get(mn_ident)

                                    if voting_timestamp > cur_vote_max_date:
                                        cur_vote_max_date = voting_timestamp

                                    if (voting_timestamp >= last_vote_max_date or force_reload):
                                        # check if vote exists in the database
                                        if db_conn:
                                            tm_begin = time.time()
                                            cur.execute("SELECT id from VOTING_RESULTS WHERE proposal_id=? AND "
                                                        "voting_time=? and (masternode_id=? or masternode_ident=?)",
                                                        (prop.db_id, voting_time, mn.db_id if mn else None, mn_ident))

                                            row = cur.fetchone()
                                            db_oper_duration += (time.time() - tm_begin)
                                            db_oper_count += 1
                                            if not row:
                                                votes_added.append((prop, mn, voting_time, voting_result, mn_ident, v_key))  # todo: hash column only for testing
                                        else:
                                            # no chance to check wherher record exists in the DB, so assume it's not
                                            # to have it displayed on the grid
                                            votes_added.append((prop, mn, voting_time, voting_result, mn_ident))

                                else:
                                    logging.warning('Proposal %s, parsing unsuccessful for voting: %s' % (prop.hash, v))

                            proposals_updated.append(prop)
                        else:
                            logging.debug("Proposal %d voting data valid - no need to load data from Dash network." %
                                          prop.db_id)

                    # display data from dynamic (voting) columns
                    # WndUtils.callFunInTheMainThread(self.update_grid_data, cells_to_update)
                    logging.debug('DB oper duration (stage 1): %s, SQL count: %d' % (str(db_oper_duration),
                                                                                     db_oper_count))

                    # save voting results to the database cache
                    for prop, mn, voting_time, voting_result, mn_ident, hash in votes_added:
                        if self.db_active:
                            tm_begin = time.time()
                            cur.execute("INSERT INTO VOTING_RESULTS(proposal_id, masternode_id, masternode_ident,"
                                    " voting_time, voting_result, hash) VALUES(?,?,?,?,?,?)",
                                    (prop.db_id,
                                     mn.db_id if mn else None,
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
                        for col_idx, col in enumerate(self.columns):
                            if col.column_for_vote == True and col.name == mn_ident:
                                if prop.get_value(col.name) != voting_result:
                                    prop.set_value(col.name, voting_result)
                                break

                        # check if currently selected proposal got new votes; if so, update details panel
                        if prop == self.current_proposal:
                            refresh_preview_votes = True

                    if self.db_active:
                        # update proposals' voting_last_read_time
                        for prop in proposals_updated:
                            prop.voting_last_read_time = time.time()
                            tm_begin = time.time()
                            cur.execute("UPDATE PROPOSALS set dmt_voting_last_read_time=? where id=?",
                                        (int(time.time()), prop.db_id))
                            db_modified = True
                            db_oper_duration += (time.time() - tm_begin)

                        logging.debug('DB oper duration (stage 2): %s' % str(db_oper_duration))

                        if cur_vote_max_date > last_vote_max_date:
                            # save max vot date to the DB
                            db_modified = True
                            cur.execute("UPDATE LIVE_CONFIG SET value=? WHERE symbol=?",
                                        (cur_vote_max_date, CFG_PROPOSALS_VOTES_MAX_DATE))
                            if not cur.rowcount:
                                cur.execute("INSERT INTO LIVE_CONFIG(symbol, value) VALUES(?, ?)",
                                            (CFG_PROPOSALS_VOTES_MAX_DATE, cur_vote_max_date))

                except DashdIndexException as e:
                    logging.exception('Exception while retrieving voting data.')
                    self.errorMsg(str(e))

                except Exception as e:
                    logging.exception('Exception while retrieving voting data.')
                    self.errorMsg('Error while retrieving voting data: ' + str(e))

        except Exception as e:
            logging.exception('Exception while retrieving voting data.')
        finally:
            if db_conn:
                if db_modified:
                    db_conn.commit()
                db_conn.close()
            self.display_message(None)

        try:
            if refresh_preview_votes:
                def refresh_votes_view():
                    self.votesModel.refresh_view()
                WndUtils.callFunInTheMainThread(refresh_votes_view)
        except Exception as e:
            logging.exception('Exception while refreshing voting data grid.')

    def display_proposals_data(self):
        try:
            tm_begin = time.time()
            # reset special columns' widgets assigned to proposals
            for prop in self.proposals:
                prop.name_col_widget = None
                prop.url_col_widget = None

            self.propsModel.beginResetModel()
            self.propsModel.endResetModel()
            self.propsModel.displaySpecialCells()

            # if there is no saved column widths, resize widths to its contents
            widths_initialized = False
            for col in self.columns:
                if col.initial_width:
                    widths_initialized = True
                    break

            if not widths_initialized:
                self.propsView.resizeColumnsToContents()

            logging.debug("Display proposals' data time: " + str(time.time() - tm_begin))
        except Exception as e:
            logging.exception("Exception occurred while displaing proposals.")
            self.lblMessage.setVisible(False)
            raise Exception('Error occurred while displaying proposals: ' + str(e))

    @pyqtSlot()
    def on_btnRefreshProposals_clicked(self):
        def finished_read_proposals_from_network():
            """ Called after finished reading proposals data from the Dash network. It invokes a thread
              reading voting data from the Dash network.  """

            if self.current_proposal is None and len(self.proposals) > 0:
                self.propsView.selectRow(0)

            live_proposals = []  # refresh "live" proposals only
            for prop in self.proposals:
                if prop.voting_in_progress:
                    live_proposals.append(prop)

            self.runInThread(self.read_voting_from_network_thread, (True, live_proposals))

        self.runInThread(self.read_proposals_from_network_thread, (),
                         on_thread_finish=finished_read_proposals_from_network)

    @pyqtSlot()
    def on_buttonBox_accepted(self):
        self.accept()

    @pyqtSlot()
    def on_buttonBox_rejected(self):
        self.reject()

    def refresh_vote_tab(self):
        """ Refresh data displayed on the user-voting tab. Executed after changing focused proposal and after
        submitting a new votes. """

        if self.current_proposal is None:
            for user_mn in self.users_masternodes:
                # setup voting buttons for each of user's masternodes
                user_mn.btn_vote_yes.setEnabled(False)
                user_mn.btn_vote_no.setEnabled(False)
                user_mn.btn_vote_abstain.setEnabled(False)
            self.btnVoteYesForAll.setEnabled(False)
            self.btnVoteNoForAll.setEnabled(False)
            self.btnVoteAbstainForAll.setEnabled(False)
        else:
            self.btnVoteYesForAll.setEnabled(True)
            self.btnVoteNoForAll.setEnabled(True)
            self.btnVoteAbstainForAll.setEnabled(True)

            for user_mn in self.users_masternodes:
                # setup voting buttons for each of user's masternodes
                user_mn.btn_vote_yes.setEnabled(True)
                user_mn.btn_vote_no.setEnabled(True)
                user_mn.btn_vote_abstain.setEnabled(True)
                vote = self.current_proposal.votes_by_masternode_ident.get(user_mn.masternode.ident)
                if vote:
                    user_mn.lbl_last_vote.setText('Last voted ' + vote[1] + ' on ' +
                                                  vote[0].strftime(DATETIME_FORMAT))
                else:
                    user_mn.lbl_last_vote.setText('No votes for this masternode')

    def on_propsView_currentChanged(self, newIndex, oldIndex):
        """ Triggered when changing focused row in proposals' grid. """

        def correct_hyperlink_color_focused(prop):
            """ On proposals' grid there are some columns displaying hyperlinks. When rows are focused though, default
            colors make it hard to read: both, background and font are blue. To make it readable, set font's color to
            white."""
            if prop:
                url = prop.get_value('url')
                if url:
                    if prop.name_col_widget:
                        prop.name_col_widget.setText('<a href="%s" style="color:white">%s</a>' %
                                                     (url, prop.get_value('name')))
                    if prop.url_col_widget:
                        prop.url_col_widget.setText('<a href="%s" style="color:white">%s</a>' % (url, url))

        def correct_hyperlink_color_nonfocused(prop):
            """ After loosing focus, restore hyperlink's font color."""
            if prop:
                url = prop.get_value('url')
                if url:
                    if prop.name_col_widget:
                        prop.name_col_widget.setText('<a href="%s">%s</a>' % (url, prop.get_value('name')))
                    if prop.url_col_widget:
                        prop.url_col_widget.setText('<a href="%s">%s</a>' % (url, url))

        try:

            new_row = None
            old_row = None

            if newIndex:
                newIndex = self.proxyModel.mapToSource(newIndex)
                if newIndex:
                    new_row = newIndex.row()
            if oldIndex:
                oldIndex = self.proxyModel.mapToSource(oldIndex)
                if oldIndex:
                    old_row = oldIndex.row()

            if new_row != old_row:
                if new_row is None:
                    self.current_proposal = None  # hide the details
                    self.votesModel.set_proposal(self.current_proposal)
                else:
                    if new_row >= 0 and new_row < len(self.proposals):
                        correct_hyperlink_color_nonfocused(self.current_proposal)
                        self.current_proposal = self.proposals[new_row]  # show the details
                        self.votesModel.set_proposal(self.current_proposal)
                        correct_hyperlink_color_focused(self.current_proposal)
                self.refresh_vote_tab()

                self.refresh_preview_panel()
        except Exception:
            logging.exception('Exception while changing proposal selected.')

    def refresh_preview_panel(self):
        if self.current_proposal:
            url = self.current_proposal.get_value('url')
            if url:
                self.webView.load(QUrl(url))
                self.edtURL.setText(url)
                self.lblDetailsUrl.setText('<a href="%s">%s</a>' % (url, url))
            else:
                self.lblDetailsUrl.setText('')
            self.lblDetailsName.setText(self.current_proposal.get_value('name'))
            self.lblDetailsVotingStatus.setText(self.current_proposal.get_value('voting_status_caption'))
            self.lblDetailsYesCount.setText(str(self.current_proposal.get_value('yes_count')))
            self.lblDetailsNoCount.setText(str(self.current_proposal.get_value('no_count')))
            self.lblDetailsAbstainCount.setText(str(self.current_proposal.get_value('abstain_count')))
            self.lblDetailsCreationTime.setText(str(self.current_proposal.get_value('creation_time')))
            self.lblDetailsPaymentAmount.setText(str(self.current_proposal.get_value('payment_amount')) + ' Dash')
            addr = self.current_proposal.get_value('payment_address')
            if self.main_wnd.config.block_explorer_addr:
                url = self.main_wnd.config.block_explorer_addr.replace('%ADDRESS%', addr)
                addr = '<a href="%s">%s</a>' % (url, addr)
            self.lblDetailsPaymentAddress.setText(addr)
            self.lblDetailsPaymentStart.setText(str(self.current_proposal.get_value('payment_start')))
            self.lblDetailsPaymentEnd.setText(str(self.current_proposal.get_value('payment_end')))
            self.lblDetailsProposalHash.setText(self.current_proposal.get_value('hash'))
            hash = self.current_proposal.get_value('collateral_hash')
            if self.main_wnd.config.block_explorer_tx:
                url = self.main_wnd.config.block_explorer_tx.replace('%TXID%', hash)
                hash = '<a href="%s">%s</a>' % (url, hash)
            self.lblDetailsCollateralHash.setText(hash)

    def apply_votes_filter(self):
        changed_chb = self.votesProxyModel.set_only_my_votes(self.chbOnlyMyVotes.isChecked())
        changed_text = self.votesProxyModel.set_filter_text(self.edtVotesViewFilter.text())
        if changed_chb or changed_text:
            self.votesProxyModel.invalidateFilter()
        self.btnApplyVotesViewFilter.setEnabled(False)

    @pyqtSlot()
    def on_btnReloadVotes_clicked(self):
        if self.current_proposal:
            self.runInThread(self.read_voting_from_network_thread, (True,[self.current_proposal]))

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

    @pyqtSlot()
    def on_btnVoteYesForAll_clicked(self):
        if self.main_wnd.config.dont_confirm_when_voting or \
            self.queryDlg('Vote YES for all masternodes?',
                          buttons=QMessageBox.Yes | QMessageBox.Cancel,
                          default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:
            vl = []
            for mn_info in self.users_masternodes:
                vl.append((mn_info, VOTE_CODE_YES))
            if vl:
                self.vote(vl)

    @pyqtSlot()
    def on_btnVoteNoForAll_clicked(self):
        if self.main_wnd.config.dont_confirm_when_voting or \
            self.queryDlg('Vote NO for all masternodes?',
                          buttons=QMessageBox.Yes | QMessageBox.Cancel,
                          default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:
            vl = []
            for mn_info in self.users_masternodes:
                vl.append((mn_info, VOTE_CODE_NO))
            if vl:
                self.vote(vl)

    @pyqtSlot()
    def on_btnVoteAbstainForAll_clicked(self):
        if self.main_wnd.config.dont_confirm_when_voting or \
            self.queryDlg('Vote ABSTAIN for all masternodes?',
                          buttons=QMessageBox.Yes | QMessageBox.Cancel,
                          default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:
            vl = []
            for mn_info in self.users_masternodes:
                vl.append((mn_info, VOTE_CODE_ABSTAIN))
            if vl:
                self.vote(vl)

    def on_btnVoteYes_clicked(self, mn_info):
        if self.main_wnd.config.dont_confirm_when_voting or \
           self.queryDlg('Vote YES for masternode %s?' % mn_info.masternode_config.name,
                          buttons=QMessageBox.Yes | QMessageBox.Cancel,
                          default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:
            self.vote([(mn_info, VOTE_CODE_YES)])

    def on_btnVoteNo_clicked(self, mn_info):
        if self.main_wnd.config.dont_confirm_when_voting or \
           self.queryDlg('Vote NO for masternode %s?' % mn_info.masternode_config.name,
                          buttons=QMessageBox.Yes | QMessageBox.Cancel,
                          default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:
            self.vote([(mn_info, VOTE_CODE_NO)])

    def on_btnVoteAbstain_clicked(self, mn_info):
        if self.main_wnd.config.dont_confirm_when_voting or \
           self.queryDlg('Vote ABSTAIN for masternode %s?' % mn_info.masternode_config.name,
                          buttons=QMessageBox.Yes | QMessageBox.Cancel,
                          default_button=QMessageBox.Yes, icon=QMessageBox.Information) == QMessageBox.Yes:
            self.vote([(mn_info, VOTE_CODE_ABSTAIN)])

    def vote(self, vote_list):
        """ Process votes for currently focused proposal. """

        if self.current_proposal:
            if not self.dashd_intf.open():
                self.errorMsg('Dash daemon not connected')
            else:
                prop_hash = self.current_proposal.get_value('hash')

                step = 1
                successful_votes = 0
                unsuccessful_votes = 0

                for vote_idx, v in enumerate(vote_list):
                    mn_info = None
                    try:
                        mn_info = v[0]
                        vote_code = v[1]
                        vote = {VOTE_CODE_YES: 'yes', VOTE_CODE_NO: 'no', VOTE_CODE_ABSTAIN: 'abstain'}[vote_code]

                        sig_time = int(time.time())
                        if self.main_wnd.config.add_random_affset_to_vote_time:
                            sig_time += random.randint(-1800, 1800)

                        serialize_for_sig = mn_info.masternode.ident + '|' \
                                            + prop_hash + '|' \
                                            + '1' + '|' \
                                            + vote_code + '|' \
                                            + str(sig_time)

                        step = 2
                        vote_sig = dash_utils.ecdsa_sign(serialize_for_sig, mn_info.masternode_config.privateKey)

                        self.current_proposal.apply_vote(mn_ident=mn_info.masternode.ident,
                                                         vote_timestamp=datetime.datetime.fromtimestamp(sig_time),
                                                         vote_result=vote.upper())

                        # step =3
                        # v_res = self.dashd_intf.voteraw(masternode_tx_hash=mn_info.masternode_config.collateralTx,
                        #                         masternode_tx_index=int(mn_info.masternode_config.collateralTxIndex),
                        #                         governance_hash=prop_hash,
                        #                         vote_signal='funding',
                        #                         vote=vote, sig_time=sig_time, vote_sig=vote_sig)
                        v_res = 'Voted successfully'

                        if v_res == 'Voted successfully':
                            self.current_proposal.apply_vote(mn_ident=mn_info.masternode.ident,
                                                             vote_timestamp=datetime.datetime.fromtimestamp(sig_time),
                                                             vote_result=vote.upper())
                            successful_votes += 1
                        else:
                            self.warnMsg(v_res)
                            unsuccessful_votes += 1

                    except Exception as e:
                        if step == 1:
                            msg = "Error for masternode %s: %s " %  (mn_info.masternode_config.name, str(e))
                        elif step == 2:
                            msg = "Error while signing voting message with masternode's %s private key." % \
                                  mn_info.masternode_config.name
                        else:
                            msg = "Error while broadcasting vote message for masternode %s: %s" % \
                            (mn_info.masternode_config.name, str(e))
                        unsuccessful_votes += 1

                        logging.exception(msg)
                        if vote_idx < len(vote_list) - 1:
                            if self.queryDlg(msg, buttons=QMessageBox.Ok | QMessageBox.Abort,
                                          default_button=QMessageBox.Cancel, icon=QMessageBox.Critical) ==\
                               QMessageBox.Abort:
                                break
                        else:
                            self.errorMsg(msg)

                if successful_votes > 0:
                    self.refresh_vote_tab()

                if unsuccessful_votes == 0 and successful_votes > 0:
                    self.infoMsg('Voted successfully')


class ProposalFilterProxyModel(QSortFilterProxyModel):
    """ Proxy for proposals sorting. """

    def __init__(self, parent, proposals, columns):
        super().__init__(parent)
        self.columns = columns
        self.proposals = proposals

    def lessThan(self, left, right):
        """ Custom comparison method: for comparing data from columns which have custom widget controls
          associated with it, such as hyperlink columns (name, url). Such "widget" columns
          can't be compared with the use of default method, because data to be compared is hidden
          behind widget.
        """
        col_index = left.column()
        col = self.columns[col_index]
        left_row_index = left.row()
        if col.name in ('name', 'url'):
            # compare hyperlink columns
            if left_row_index >= 0 and left_row_index < len(self.proposals):
                left_prop = self.proposals[left_row_index]
                right_row_index = right.row()

                if right_row_index >= 0 and right_row_index < len(self.proposals):
                    right_prop = self.proposals[right_row_index]
                    left_value = left_prop.get_value(col.name).lower()
                    if not left_value:
                        left_value = ""
                    right_value = right_prop.get_value(col.name).lower()
                    if not right_value:
                        right_value = ""
                    return left_value < right_value

        elif col.name == 'voting_status_caption':
            # compare status column by its status code, not status text
            if left_row_index >= 0 and left_row_index < len(self.proposals):
                left_prop = self.proposals[left_row_index]
                right_row_index = right.row()

                if right_row_index >= 0 and right_row_index < len(self.proposals):
                    right_prop = self.proposals[right_row_index]
                    left_value = left_prop.voting_status
                    right_value = right_prop.voting_status

                    if left_value == right_value:
                        # for even statuses, order by creation time (newest first)
                        diff = right_prop.get_value('creation_time') < left_prop.get_value('creation_time')
                    else:
                        diff = left_value < right_value

                    return diff

        return super().lessThan(left, right)


class ProposalsModel(QAbstractTableModel):
    def __init__(self, parent, columns, proposals):
        QAbstractTableModel.__init__(self, parent)
        self.parent = parent
        self.columns = columns
        self.proposals = proposals

    def columnCount(self, parent=None, *args, **kwargs):
        return len(self.columns)

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.proposals)

    def headerData(self, section, orientation, role=None):
        if role != 0:
            return QVariant()
        if orientation == 0x1:
            if section < len(self.columns):
                return self.columns[section].caption
            return ''
        else:
            return str(section + 1)

    def setData(self, row, col, role=None):
        index = self.index(row, col)
        index = self.parent.proxyModel.mapFromSource(index)

        self.dataChanged.emit(index, index)
        return True

    def flags(self, index):
        ret = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return ret

    def data(self, index, role=None):
        if index.isValid():
            col_idx = index.column()
            row_idx = index.row()
            if row_idx < len(self.proposals) and col_idx < len(self.columns):
                prop = self.proposals[row_idx]
                col = self.columns[col_idx]
                value = prop.get_value(col.name)
                if prop:
                    if role == Qt.DisplayRole:
                        if col.name not in ('url', 'name'):
                            # Hyperlink cells will be processed within displaySpecialCells method
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
                                return QtGui.QColor('green')
                            elif prop.voting_status == 4:
                                return QtGui.QColor('red')
                        elif col.column_for_vote:
                            if value == 'YES':
                                return QtGui.QColor('green')
                            elif value == 'ABSTAIN':
                                return QtGui.QColor('orange')
                            elif value == 'NO':
                                return QtGui.QColor('red')

                    # elif role == Qt.TextColorRole:
                    #     if col.name == 'name':
                    #         QtGui.QColor('green')

                    elif role == Qt.BackgroundRole:
                        if col.name == 'voting_status_caption':
                            if prop.voting_status == 1:
                                return QtGui.QColor('green')
                            elif prop.voting_status == 2:
                                return QtGui.QColor('orange')

                    elif role == Qt.FontRole:
                        if col.column_for_vote:
                            font = QtGui.QFont()
                            font.setBold(True)
                            return font

        return QVariant()

    def sort(self, p_int, order=None):
        pass

    def displaySpecialCells(self):
        col_url_idx = self.parent.column_index_by_name('url')
        col_name_idx = self.parent.column_index_by_name('name')

        for row_idx, prop in enumerate(self.proposals):
            if not prop.url_col_widget:
                index = self.index(row_idx, col_url_idx)
                index = self.parent.proxyModel.mapFromSource(index)
                url = prop.get_value('url')
                prop.url_col_widget = QtWidgets.QLabel(self.parent.propsView)
                prop.url_col_widget.setText('<a href="%s">%s</a>' % (url, url))
                prop.url_col_widget.setOpenExternalLinks(True)
                self.parent.propsView.setIndexWidget(index, prop.url_col_widget)

            if not prop.name_col_widget:
                index = self.index(row_idx, col_name_idx)
                index = self.parent.proxyModel.mapFromSource(index)
                name = prop.get_value('name')
                prop.name_col_widget = QtWidgets.QLabel(self.parent.propsView)
                url = prop.get_value('url')
                prop.name_col_widget.setText('<a href="%s">%s</a>' % (url, name))
                prop.name_col_widget.setOpenExternalLinks(True)
                self.parent.propsView.setIndexWidget(index, prop.name_col_widget)


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
            logging.exception('Exception wile filtering votes')
        return will_show


class VotesModel(QAbstractTableModel):
    def __init__(self, parent, masternodes, masternodes_by_db_id, users_masternodes_by_ident, db_cache_file_name):
        QAbstractTableModel.__init__(self, parent)
        self.parent = parent
        self.masternodes = masternodes
        self.masternodes_by_db_id = masternodes_by_db_id
        self.db_cache_file_name = db_cache_file_name
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
            return self.columns[section] if section >= 0 and section < len(self.columns) else ''
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
                            return str(vote[0])
                        elif col_idx == 1:  # YES/NO/ABSTAIN
                            return vote[1]
                        elif col_idx == 2:  # voting masternode label
                            return vote[2]
                        elif col_idx == 3:  # voting masternode config-name if exists in the user's configuration
                            return vote[3]
                    elif role == Qt.ForegroundRole:
                        if col_idx == 1:
                            if vote[1] == 'YES':
                                return QtGui.QColor('green')
                            elif vote[1] == 'NO':
                                return QtGui.QColor('red')
                            elif vote[1] == 'ABSTAIN':
                                return QtGui.QColor('orange')
                    elif role == Qt.FontRole:
                        if col_idx == 1:
                            font = QtGui.QFont()
                            font.setBold(True)
                            return font

        return QVariant()

    def th_read_votes(self):
        db_conn = None
        try:
            self.votes.clear()
            tm_begin = time.time()
            db_conn = sqlite3.connect(self.db_cache_file_name)
            cur = db_conn.cursor()
            logging.debug('Get vots fot proposal id: ' + str(self.proposal.db_id))
            cur.execute("SELECT voting_time, voting_result, masternode_id, masternode_ident, m.ip "
                        "FROM VOTING_RESULTS v "
                        "LEFT OUTER JOIN MASTERNODES m on m.id = v.masternode_id "
                        "WHERE proposal_id=? order by voting_time desc", (self.proposal.db_id,))

            for row in cur.fetchall():
                users_mn_name = ''
                mn_label = row[4]
                if not mn_label:
                    mn_label = row[3]

                if row[2]:
                    mn = self.masternodes_by_db_id.get(row[2])
                    if mn:
                        # check if this masternode is in the user's configuration
                        users_mn = self.users_masternodes_by_ident.get(mn.ident)
                        if users_mn:
                            users_mn_name = users_mn.masternode_config.name

                self.votes.append((datetime.datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S'),
                                   row[1], mn_label, users_mn_name ))
            logging.debug('Reading votes time from DB: %s' % str(time.time() - tm_begin))
        except Exception as e:
            logging.exception('SQLite error')
        finally:
            if db_conn:
                db_conn.close()

    def set_proposal(self, proposal):
        if self.proposal != proposal:
            self.proposal = proposal
            self.refresh_view()

    def set_only_my_votes(self, only_my_votes):
        if only_my_votes != self.only_my_votes:
            self.only_my_votes = only_my_votes
            self.th_read_votes()

    def refresh_view(self):
        self.th_read_votes()
        self.beginResetModel()
        self.endResetModel()
