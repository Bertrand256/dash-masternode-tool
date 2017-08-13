#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-05
import datetime
import json
import logging
import os
import re
import threading
import time
from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import Qt, pyqtSlot, QModelIndex, QVariant, QAbstractTableModel, QSortFilterProxyModel
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QDialog, QTableWidgetItem, QDialogButtonBox, QHeaderView
import src.wnd_utils as wnd_utils
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

# definition of symbols' for DB live configuration (tabel LIVE_CONFIG)
CFG_PROPOSALS_LAST_READ_TIME = 'proposals_last_read_time'
CFG_PROPOSALS_VOTES_MAX_DATE = 'prop_votes_max_date'  # maximum date of vote(s), read last time


class ProposalColumn(AttrsProtected):
    def __init__(self, name, caption, visible, voting_mn=False):
        """
        Constructor.
        :param name: Column name. There are: 1) static columns that display some piece of information about
            the proposal 2) dynamic columns, that display vote made by specified masternodes for each proposal.
            For dynamic column, name attribute equals to masternode identifier.
        :param caption: Column's caption.
        :param visible: True, if column is visible
        :param voting_mn: True for (dynamic) columns related to mn voting.
        """
        AttrsProtected.__init__(self)
        self.name = name
        self.caption = caption
        self.visible = visible
        self.voting_mn = voting_mn
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
    def __init__(self, columns):
        super().__init__()
        self.visible = True
        self.columns = columns
        self.values = {}  # dictionary of proposal values (key: ProposalColumn)
        self.votes = []
        self.db_id = None
        self.marker = None
        self.modified = False
        self.voting_last_read_time = 0
        self.voting_in_progress = True

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

    def vote_exists(self, masternode, masternode_ident, voting_time):
        """ Check if the specified vote is on the list of votes for this proposal. Votes are identified by masternode
            reference and the time it has been made.
        """
        for v in self.votes:
            if (v.voting_masternode == masternode or v.voting_masternode_ident == masternode_ident) and \
               v.voting_time == voting_time:
                return True
        return False

    def add_vote(self, vote):
        self.votes.append(vote)

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


class ProposalsDlg(QDialog, ui_proposals.Ui_ProposalsDlg, wnd_utils.WndUtils):
    def __init__(self, parent, dashd_intf):
        QDialog.__init__(self, parent=parent)
        wnd_utils.WndUtils.__init__(self, app_path=parent.app_path)
        self.main_wnd = parent
        self.dashd_intf = dashd_intf
        self.columns = [
            ProposalColumn('name', 'Name', True),
            ProposalColumn('voting_status_caption', 'Voting Status', True),
            ProposalColumn('payment_start', 'Payment Start', True),
            ProposalColumn('payment_end', 'Payment End', True),
            ProposalColumn('payment_amount', 'Amount', True),
            ProposalColumn('yes_count', 'YES Count', True),
            ProposalColumn('absolute_yes_count', 'Absolute YES Count', True),
            ProposalColumn('no_count', 'NO Count', True),
            ProposalColumn('abstain_count', 'Abstain Count', True),
            ProposalColumn('creation_time', 'Creation Time', True),
            ProposalColumn('url', 'URL', True),
            ProposalColumn('payment_address', 'Payment Address', True),
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
        self.proposals = []
        self.proposals_by_hash = {}  #  dict of Proposal object indexed by proposal hash
        self.proposals_by_db_id = {}
        self.masternodes = []
        self.masternodes_by_ident = {}
        self.masternodes_by_db_id = {}
        self.mn_count = None
        self.db_active = False
        self.governanceinfo = None
        self.last_superblock_time = None
        self.next_superblock_time = None
        self.proposals_last_read_time = 0

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
                        " masternode_id INTEGER, masternode_ident TEXT, voting_time TEXT, voting_result TEXT)")
            # cur.execute("CREATE INDEX IF NOT EXISTS IDX_VOTING_RESULTS_1 ON VOTING_RESULTS(proposal_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_VOTING_RESULTS_2 ON VOTING_RESULTS(masternode_id)")
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
            # s1 = self.tabDetails.size()
            # s2 = self.propsView.size()

            self.tabDetails.resize(self.tabDetails.size().width(),
                                   self.get_cache_value('DetailsHeight', 200, int))

            # let's define "dynamic" columns that show voting results for user's masternodes
            for idx, mn in enumerate(self.main_wnd.config.masternodes):
                mn_ident = mn.collateralTx + '-' + str(mn.collateralTxIndex)
                if mn_ident:
                    self.add_voting_column(mn_ident, 'Vote (' + mn.name + ')', my_masternode=True,
                                           insert_before_column=self.column_index_by_name('payment_start'))

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
                    voting_mn: True if the column relates to masternode voting (bool),
                    caption: Column's caption (str)
                }
            """
            cfg_cols = self.get_cache_value('ColumnsCfg', [], list)
            if isinstance(cfg_cols, list):
                for col_saved_index, c in enumerate(cfg_cols):
                    name = c.get('name')
                    visible = c.get('visible', True)
                    voting_mn = c.get('voting_mn')
                    caption = c.get('caption')
                    initial_width = c.get('width')
                    if not isinstance(initial_width, int):
                        initial_width = None

                    if isinstance(name, str) and isinstance(visible, bool) and isinstance(voting_mn, bool):
                        found = False
                        for col in self.columns:
                            if col.name == name:
                                col.visible = visible
                                col.initial_width = initial_width
                                col.initial_order_no = col_saved_index
                                found = True
                                break
                        if not found and voting_mn and caption:
                            # add voting column defined by the user
                            self.add_voting_column(name, caption, my_masternode=False,
                                                   insert_before_column=self.column_index_by_name('payment_start'))
            else:
                logging.warning('Invalid type of cached ColumnsCfg')
            self.columns.sort(key = lambda x: x.initial_order_no if x.initial_order_no is not None else 100)

            self.propsView.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
            self.propsView.setSortingEnabled(True)
            self.propsView.sortByColumn(self.column_index_by_name('voting_status_caption'), Qt.AscendingOrder)

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

            ##################################
            def finished_read_proposals_from_network():
                """ Called after finished reading proposals data from the Dash network. It invokes a thread
                  reading voting data from the Dash network.  """
                self.runInThread(self.read_voting_from_network_thread, (False,), self.sort_proposals_initially)

            ##################################
            def finished_read_data_thread():
                """ Called after finished reading initial data from the DB. Funtion executes reading proposals'
                   data from network if needed.
                """

                if int(time.time()) - self.proposals_last_read_time > PROPOSALS_CACHE_VALID_SECONDS or \
                                len(self.proposals) == 0:
                    # read proposals from network only after a configured time
                    self.read_proposals_from_network()
                    self.runInThread(self.read_proposals_from_network_thread, (),
                                     on_thread_finish=finished_read_proposals_from_network)

            # read initial data (from db) inside a thread and then read data from network if needed
            self.runInThread(self.read_data_thread, (), on_thread_finish=finished_read_data_thread)
            self.updateUi()
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
                    'voting_mn': col.voting_mn,
                    'caption': col.caption,
                    'width': self.propsView.columnWidth(col_idx)
                }
                cfg.append(c)
            self.set_cache_value('ColumnsCfg', cfg)
            self.set_cache_value('WindowWidth', self.size().width())
            self.set_cache_value('WindowHeight', self.size().height())

            self.set_cache_value('DetailsHeight', self.tabDetails.size().height())
            pass

        except Exception as e:
            logging.exception('Exception while saving dialog configuration to cache.')

    def add_voting_column(self, mn_ident, mn_label, my_masternode=None, insert_before_column=None):
        """
        Adds a dynamic column that displays a vote of the masternode with the specified identifier.
        :return:
        """
        # first check if this masternode is already added to voting columns
        for col in self.columns:
            if col.voting_mn == True and col.name == mn_ident:
                return  # column for this masternode is already added

        col = ProposalColumn(mn_ident, mn_label, visible=True, voting_mn=True)
        if isinstance(insert_before_column, int) and insert_before_column < len(self.columns):
            self.columns.insert(insert_before_column, col)
        else:
            self.columns.append(col)

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

    def sort_proposals_initially(self):
        # make the initial proposals' sorting - with active voting first
        cur_tm = time.time()
        def cmp(prop):
            # sort by voting_status asc, creation_time desc:
            ret = (cur_tm * prop.voting_status) + cur_tm - prop.get_value('creation_time').timestamp()
            return ret

        self.proposals.sort(key=cmp)

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
                    prop = Proposal(self.columns)
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

                # self.set_cache_value('ProposalsLastReadTime', int(time.time()))  # save when proposals has been
                cur.execute("UPDATE LIVE_CONFIG SET value=? WHERE symbol=?",
                            (int(time.time()), CFG_PROPOSALS_LAST_READ_TIME))
                if cur.rowcount == 0:
                    cur.execute("INSERT INTO LIVE_CONFIG(symbol, value) VALUES(?, ?)",
                                (CFG_PROPOSALS_LAST_READ_TIME, int(time.time())))

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
                                # " LIMIT 20"  #todo: testing only
                            )

                            for row in cur.fetchall():
                                prop = Proposal(self.columns)
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

                            # display data, now without voting results, which will be read below
                            self.sort_proposals_initially()
                            WndUtils.callFunInTheMainThread(self.display_proposals_data)

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
                if col.voting_mn:
                    mn_ident = col.name
                    mn = self.masternodes_by_ident.get(mn_ident)
                    if mn:
                        cur.execute("SELECT proposal_id, voting_time, voting_result "
                                    "FROM VOTING_RESULTS WHERE masternode_id=?", (mn.db_id,))
                        for row in cur.fetchall():
                            prop = self.proposals_by_db_id.get(row[0])
                            if prop:
                                if prop.set_value(col.name, row[2]):
                                    pass

        except Exception as e:
            logging.exception('Exception while saving proposals to db.')
        finally:
            if db_conn:
                db_conn.close()
            time_diff = time.time() - begin_time
            logging.info('Voting data read from database time: %s seconds' % str(time_diff))

    def read_voting_from_network_thread(self, ctrl, force_reload):
        """
        Retrieve from a Dash daemon voting results for all defined masternodes, for all visible Proposals.
        :param ctrl:
        :param force_reload: if False (default) we read voting results only for Proposals, which hasn't
          been read yet (for example has been filtered out).
        :return:
        """

        last_vote_max_date = 0
        cur_vote_max_date = 0
        db_conn = None
        db_modified = False
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

                    for row_idx, prop in enumerate(self.proposals):

                        if (prop.voting_in_progress or prop.voting_last_read_time == 0) and \
                           (force_reload or (time.time() - prop.voting_last_read_time) > VOTING_RELOAD_TIME):
                           # read voting results from the Dash network if:
                           #  - haven't ever read voting results for this proposal
                           #  - if voting for this proposal is still open , but VOTING_RELOAD_TIME of seconds have
                           #    passed since the last read or user forced to reload votes

                            self.display_message('Reading voting data %d of %d' % (row_idx+1, len(self.proposals)))
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

                                    if voting_timestamp > last_vote_max_date:
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
                                                votes_added.append((prop, mn, voting_time, voting_result, mn_ident))
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
                    for prop, mn, voting_time, voting_result, mn_ident in votes_added:
                        if self.db_active:
                            tm_begin = time.time()
                            cur.execute("INSERT INTO VOTING_RESULTS(proposal_id, masternode_id, masternode_ident,"
                                    " voting_time, voting_result) VALUES(?,?,?,?,?)",
                                    (prop.db_id,
                                     mn.db_id if mn else None,
                                     mn_ident,
                                     voting_time,
                                     voting_result))
                            db_modified = True
                            db_oper_duration += (time.time() - tm_begin)

                        # check if voting masternode has its column in the main grid's;
                        # if so, pass the voting result to a corresponding proposal field
                        for col_idx, col in enumerate(self.columns):
                            if col.voting_mn == True and col.name == mn_ident:
                                if prop.get_value(col.name) != voting_result:
                                    prop.set_value(col.name, voting_result)
                                break

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
    def on_buttonBox_accepted(self):
        self.accept()

    @pyqtSlot()
    def on_buttonBox_rejected(self):
        self.reject()

    @pyqtSlot()
    def on_tableWidget_itemSelectionChanged(self):
        self.updateUi()


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
                        elif col.voting_mn:
                            if value == 'YES':
                                return QtGui.QColor('white')
                            elif value == 'ABSTAIN':
                                return QtGui.QColor('white')
                            elif value == 'NO':
                                return QtGui.QColor('white')

                    elif role == Qt.BackgroundRole:
                        if col.name == 'voting_status_caption':
                            if prop.voting_status == 1:
                                return QtGui.QColor('green')
                            elif prop.voting_status == 2:
                                return QtGui.QColor('orange')
                        elif col.voting_mn:
                            if value == 'YES':
                                return QtGui.QColor('green')
                            elif value == 'ABSTAIN':
                                return QtGui.QColor('orange')
                            elif value == 'NO':
                                return QtGui.QColor('red')

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


