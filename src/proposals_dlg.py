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
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt, pyqtSlot, QModelIndex
from PyQt5.QtWidgets import QDialog, QTableWidgetItem, QDialogButtonBox
import wnd_utils as wnd_utils
from app_config import DATE_FORMAT, DATETIME_FORMAT
from dashd_intf import DashdIndexException
from ui import ui_proposals
from src.common import AttrsProtected
from src.wnd_utils import WndUtils
import sqlite3


# Definition of how long the cached proposals information is valid. If it's valid, dialog
# will display data from cache, instead of requesting them from a dash daemon, which is
# more time consuming.
PROPOSALS_CACHE_VALID_SECONDS = 3600

# Number of seconds after which voting will be reloaded for active proposals:
VOTING_RELOAD_TIME = 3600


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
        self.voting_enabled = True
        self.set_attr_protection()

    def set_value(self, name, value):
        """
        Sets value for a specified Proposal column.
        """
        for col in self.columns:
            if col.name == name:
                old_value = self.values.get(col)
                if old_value != value:
                    self.modified = True
                    self.values[col] = value
                return
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


class ProposalsDlg(QDialog, ui_proposals.Ui_ProposalsDlg, wnd_utils.WndUtils):
    def __init__(self, parent, dashd_intf):
        QDialog.__init__(self, parent=parent)
        wnd_utils.WndUtils.__init__(self, app_path=parent.app_path)
        self.main_wnd = parent
        self.dashd_intf = dashd_intf
        self.columns = [
            ProposalColumn('name', 'Name', True),
            ProposalColumn('payment_start', 'Payment start', True),
            ProposalColumn('payment_end', 'Payment end', True),
            ProposalColumn('payment_amount', 'Amount', True),
            ProposalColumn('yes_count', 'Yes count', True),
            ProposalColumn('absolute_yes_count', 'Absolute Yes count', True),
            ProposalColumn('no_count', 'No count', True),
            ProposalColumn('abstain_count', 'Abstain count', True),
            ProposalColumn('creation_time', 'Creation time', True),
            ProposalColumn('url', 'URL', True),
            ProposalColumn('payment_address', 'Payment address', True),
            ProposalColumn('type', 'Type', False),
            ProposalColumn('hash', 'Hash', True),
            ProposalColumn('collateral_hash', 'Collateral hash', True),
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
        self.masternodes_by_ident = {}
        self.masternodes_by_db_id = {}
        self.mn_count = None
        self.db_active = False

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

            cur.execute("CREATE INDEX IF NOT EXISTS IDX_VOTING_RESULTS_PROPOSAL_ID ON VOTING_RESULTS(proposal_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_VOTING_RESULTS_MASTERNODE_ID ON VOTING_RESULTS(masternode_id)")

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
            self.tableWidget.verticalHeader().setDefaultSectionSize(
                self.tableWidget.verticalHeader().fontMetrics().height() + 6)

            # let's define "dynamic" columns that show voting results for user's masternodes
            for idx, mn in enumerate(self.main_wnd.config.masternodes):
                mn_ident = mn.collateralTx + '-' + str(mn.collateralTxIndex)
                if mn_ident:
                    self.add_voting_column(mn_ident, 'Vote (' + mn.name + ')', my_masternode=True)

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
                for c in cfg_cols:
                    name = c.get('name')
                    visible = c.get('visible', True)
                    voting_mn = c.get('voting_mn')
                    caption = c.get('caption')
                    if isinstance(name, str) and isinstance(visible, bool) and isinstance(voting_mn, bool):
                        found = False
                        for col in self.columns:
                            if col.name == name:
                                col.visible = visible
                                col.caption = caption
                                found = True
                                break
                        if not found and voting_mn and caption:
                            # add voting column defined by the user
                            self.add_voting_column(name, caption, my_masternode=False)
            else:
                logging.warning('Invalid type of cached ColumnsCfg')

            # setup proposals grid
            self.tableWidget.clear()
            self.tableWidget.setColumnCount(len(self.columns))
            for idx, col in enumerate(self.columns):
                item = QtWidgets.QTableWidgetItem()
                item.setText(col.caption)
                self.tableWidget.setHorizontalHeaderItem(idx, item)
                if not col.visible:
                    self.tableWidget.hideColumn(idx)

            # todo: for testing:
            # self.save_config()

            self.runInThread(self.read_proposals_thread, (False,))
            self.updateUi()
        except:
            logging.exception('Exception occurred')
            raise

    def updateUi(self):
        items = self.tableWidget.selectedItems()
        selected = len(items) > 0
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(selected)

    def save_config(self):
        """
        Saves dynamic configuration (for example grid columns) to cache.
        :return:
        """
        cfg = []
        for col in self.columns:
            c = {
                'name': col.name,
                'visible': col.visible,
                'voting_mn': col.voting_mn,
                'caption': col.caption
            }
            cfg.append(c)
        self.set_cache_value('ColumnsCfg', cfg)

    def add_voting_column(self, mn_ident, mn_label, my_masternode=None):
        """
        Adds a dynamic column that displays a vote of the masternode with the specified identifier.
        :return:
        """
        # first check if this masternode is already added to voting columns
        for col in self.columns:
            if col.voting_mn == True and col.name == mn_ident:
                return  # column for this masternode is already added

        col = ProposalColumn(mn_ident, mn_label, visible=True, voting_mn=True)
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
                self.lblMessage.setText('<b style="color:orange">' + message + '<b>')
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

    def read_proposals_from_network(self):
        """ Reads proposals from Dash network. """

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
            proposals = self.dashd_intf.gobject("list", "valid", "proposals")

            # reset marker value in all existing Proposal object - we'll use it to check which
            # of prevoiusly read proposals do not exit anymore
            for prop in self.proposals:
                prop.marker = False
                prop.modified = False  # all modified proposals will be saved to DB cache

            for pro_key in proposals:
                prop_raw = proposals[pro_key]

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
                if is_new:
                    self.proposals.append(prop)
                    self.proposals_by_hash[prop.get_value('hash')] = prop

            db_conn = None
            db_modified = False
            try:
                db_conn = sqlite3.connect(self.main_wnd.config.db_cache_file_name)
                cur = db_conn.cursor()

                for prop in self.proposals:
                    if prop.marker:
                        if not prop.db_id:
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
                            db_modified = True
                        else:
                            # proposal's db record already exists, check if should be updated
                            if prop.modified:
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
                                db_modified = True

                # delete proposals which no longer exists in tha Dash network
                for prop_idx in reversed(range(len(self.proposals))):
                    prop = self.proposals[prop_idx]

                    if not prop.marker:
                        logging.debug('Deactivating proposal in the cache. Hash: %s, DB id: %s' %
                                      (prop.get_value('hash'), str(prop.db_id)))
                        cur.execute("UPDATE PROPOSALS set dmt_active=0, dmt_deactivation_time=? WHERE id=?",
                                    (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), prop.db_id))

                        self.proposals_by_hash.pop(prop.get_value('hash'), 0)
                        del self.proposals[prop_idx]
                        db_modified = True

            except Exception as e:
                logging.exception('Exception while saving proposals to db.')
            finally:
                if db_conn:
                    if db_modified:
                        db_conn.commit()
                    db_conn.close()

            self.set_cache_value('ProposalsLastReadTime', int(time.time()))  # save when proposals has been

        except Exception as e:
            logging.exception('Exception wile reading proposals from Dash network.')

    def read_proposals_thread(self, ctrl, force_reload):
        """ Reads proposals data from Dash daemon.
        :param ctrl:
        :param force_reload: if running
        :return:
        """

        try:
            if not self.dashd_intf.open():
                self.errorMsg('Dash daemon not connected')
            else:
                try:
                    # get list of all masternodes
                    self.display_message('Reading masternode data, please wait...')
                    mns = self.dashd_intf.get_masternodelist('full')
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

                            cur.execute(
                                "SELECT name, payment_start, payment_end, payment_amount,"
                                " yes_count, absolute_yes_count, no_count, abstain_count, creation_time,"
                                " url, payment_address, type, hash, collateral_hash, f_blockchain_validity,"
                                " f_cached_valid, f_cached_delete, f_cached_funding, f_cached_endorsed, object_type,"
                                " is_valid_reason, dmt_active, dmt_create_time, dmt_deactivation_time, id,"
                                " dmt_voting_last_read_time "
                                "FROM PROPOSALS where dmt_active=1")

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
                                self.proposals.append(prop)
                                self.proposals_by_hash[prop.get_value('hash')] = prop

                            # Read voting for each proposal
                            self.display_message('Reading voting data from DB, please wait...')

                            begin_time = time.time()
                            for prop in self.proposals:
                                cur.execute("SELECT masternode_id, masternode_ident, voting_time, voting_result "
                                            "FROM VOTING_RESULTS where proposal_id=?", (prop.db_id,))

                                for row in cur.fetchall():
                                    mn = self.masternodes_by_db_id.get(row[0])
                                    v = Vote(mn, datetime.datetime.strptime(row[2], '%Y-%m-%d %H:%M:%S'), row[3],
                                             row[1])
                                    prop.add_vote(v)

                                    if mn:
                                        for col_idx, col in enumerate(self.columns):
                                            if col.voting_mn == True and col.name == mn.ident:
                                                prop.set_value(col.name, row[3])

                            time_diff = time.time() - begin_time
                            logging.info('Voting data read from database time: %d seconds' % time_diff)

                            # display loaded proposal data on the grid
                            WndUtils.callFunInTheMainThread(self.display_data)

                        except Exception as e:
                            logging.exception('Exception while saving proposals to db.')
                        finally:
                            if db_conn:
                                db_conn.close()

                    last_read_time = self.get_cache_value('ProposalsLastReadTime', 0, int)
                    if force_reload or int(time.time()) - last_read_time > PROPOSALS_CACHE_VALID_SECONDS or \
                       len(self.proposals) == 0:
                        self.read_proposals_from_network()

                    self.runInThread(self.read_voting_results_thread, (False,))
                except DashdIndexException as e:
                    self.errorMsg(str(e))

                except Exception as e:
                    logging.exception('Exception while retrieving proposals data.')
                    self.errorMsg('Error while retrieving proposals data: ' + str(e))
        except Exception as e:
            pass

    def set_table_value(self, row_nr, value_name, proposal, horz_align=None):
        """
        Displays specified proposal's information (column) on the main grid.
        :param row_nr: grid's row number (and also then proposal index) to be displayed
        :param value_name: proposal's value name
        :param proposal: reference to a Proposal object
        :param horz_align: type of horizontal alignment in the grid's cell
        """
        col_nr = self.column_index_by_name(value_name)
        value = proposal.get_value(value_name)

        item = self.tableWidget.item(row_nr, col_nr)
        item_created = False
        if isinstance(value, (int, float)):
            if not item:
                item = QTableWidgetItem()
                item_created = True
            item.setData(Qt.DisplayRole, value)
        else:
            if value is None:
                value = ""
            if not item:
                item = QTableWidgetItem(str(value))
                item_created = True
            else:
                item.setText(str(value))
        if item_created:
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if horz_align:
                item.setTextAlignment(horz_align)
            self.tableWidget.setItem(row_nr, col_nr, item)

    def update_grid_data(self, cells_to_update):
        """
        Updates specified cells of the proposal grid due to data updatng.
        Function called from inside a thread by synchronization engine, synchronizing it with the main thread.
        It's necessary because of dealing with visual controls.
        :param cells_to_update: list of tuples row-column of the grid to be updated.
        """
        try:
            for row_idx, col_idx in cells_to_update:
                self.set_table_value(row_idx, self.columns[col_idx].name, self.proposals[row_idx])
        except Exception as e:
            self.errorMsg(str(e))

    def read_voting_results_thread(self, ctrl, force_reload):
        """
        Retrieve from a Dash daemon voting results for all defined masternodes, for all visible Proposals.
        :param ctrl:
        :param force_reload: if False (default) we read voting results only for Proposals, which hasn't
          been read yet (for example has been filtered out).
        :return:
        """

        try:
            cells_to_update = []  # list of row, column tuples, of which values has been modified - wee need
                                  # to update corresponding grid's cells
            votes_added = []  # list of tuples proposal-vote, that has been added (will be saved to database cache)

            if not self.dashd_intf.open():
                self.errorMsg('Dash daemon not connected')
            else:
                try:
                    for row_idx, prop in enumerate(self.proposals):
                        # todo: testing only
                        # if row_idx > 10:
                        #     break
                        # todo: end  testing

                        if (prop.voting_enabled or prop.voting_last_read_time == 0) and \
                           (force_reload or (time.time() - prop.voting_last_read_time) > VOTING_RELOAD_TIME):
                           # read voting results from the Dash network if:
                           #  - haven't ever read voting results for this proposal
                           #  - if voting for this proposal is still open , but VOTING_RELOAD_TIME of seconds have
                           #    passed since the last read or user forced to reload votes

                            self.display_message('Reading voting data %d of %d' % (row_idx+1, len(self.proposals)))
                            votes = self.dashd_intf.gobject("getvotes", prop.get_value('hash'))
                            for v_key in votes:
                                v = votes[v_key]
                                match = re.search("CTxIn\(COutPoint\(([A-Fa-f0-9]+)\s*\,\s*(\d+).+\:(\d+)\:(\w+)", v)
                                if len(match.groups()) == 4:
                                    mn_ident = match.group(1) + '-' + match.group(2)
                                    voting_time = datetime.datetime.fromtimestamp(int(match.group(3)))
                                    voting_result = match.group(4)
                                    mn = self.masternodes_by_ident.get(mn_ident)
                                    if not prop.vote_exists(mn, mn_ident, voting_time):
                                        v = Vote(mn, voting_time, voting_result, mn_ident)
                                        prop.add_vote(v)
                                        votes_added.append((prop, v))

                                    # check if voting masternode has its column in the main grid's;
                                    # if so, pass the voting result to a corresponding proposal field
                                    for col_idx, col in enumerate(self.columns):
                                        if col.voting_mn == True and col.name == mn_ident:
                                            if prop.get_value(col.name) != voting_result:
                                                prop.set_value(col.name, voting_result)
                                                cells_to_update.append((row_idx, col_idx))
                                            break
                                else:
                                    logging.warning('Proposal %s, parsing unsuccessful for voting: %s' % (prop.hash, v))
                        else:
                            logging.info("Proposal %d voting data valid. Skipping reading from network." % prop.db_id)

                    # display data from dynamic (voting) columns
                    WndUtils.callFunInTheMainThread(self.update_grid_data, cells_to_update)

                    # save voting results to the database cache
                    if self.db_active:
                        db_conn = None
                        db_modified = False
                        unique_proposals = []  # list of proposals for which votes were loaded
                        try:
                            db_conn = sqlite3.connect(self.main_wnd.config.db_cache_file_name)
                            cur = db_conn.cursor()

                            for prop, v in votes_added:
                                cur.execute("INSERT INTO VOTING_RESULTS(proposal_id, masternode_id, masternode_ident,"
                                            " voting_time, voting_result) VALUES(?,?,?,?,?)",
                                            (prop.db_id,
                                             v.voting_masternode.db_id if v.voting_masternode else None,
                                             v.voting_masternode_ident,
                                             v.voting_time,
                                             v.voting_result))

                                if not prop in unique_proposals:
                                    unique_proposals.append(prop)

                                db_modified = True

                            # update proposals' voting_last_read_time
                            for prop in unique_proposals:
                                prop.voting_last_read_time = time.time()
                                cur.execute("UPDATE PROPOSALS set dmt_voting_last_read_time=? where id=?",
                                            (int(time.time()), prop.db_id))

                        except Exception as e:
                            logging.exception('Exception while saving voting results to the database cache.')

                        finally:
                            if db_conn:
                                if db_modified:
                                    db_conn.commit()
                                db_conn.close()

                except DashdIndexException as e:
                    self.errorMsg(str(e))

                except Exception as e:
                    logging.exception('Exception while retrieving voting data.')
                    self.errorMsg('Error while retrieving voting data: ' + str(e))
        except Exception as e:
            pass
        finally:
            self.display_message(None)

    def display_data(self):

        try:
            row = 0

            for prop in self.proposals:
                self.tableWidget.insertRow(self.tableWidget.rowCount())

                # "name" column display as a hyperlink if possible
                if prop.get_value('url'):
                    url_lbl = QtWidgets.QLabel(self.tableWidget)
                    url_lbl.setText('<a href="%s">%s</a>' % (prop.get_value('url'), prop.get_value('name')))
                    url_lbl.setOpenExternalLinks(True)
                    self.tableWidget.setCellWidget(row, self.column_index_by_name('name'), url_lbl)
                else:
                    # url is empty, so display value as normal text, not hyperlink
                    self.set_table_value(row, 'name', prop)

                self.set_table_value(row, 'payment_start', prop)
                self.set_table_value(row, 'payment_end', prop)
                self.set_table_value(row, 'payment_amount', prop, Qt.AlignRight)
                self.set_table_value(row, 'yes_count', prop, Qt.AlignRight)
                self.set_table_value(row, 'absolute_yes_count', prop, Qt.AlignRight)
                self.set_table_value(row, 'no_count', prop, Qt.AlignRight)
                self.set_table_value(row, 'abstain_count', prop, Qt.AlignRight)
                self.set_table_value(row, 'creation_time', prop)

                if prop.get_value('url'):
                    url_lbl = QtWidgets.QLabel(self.tableWidget)
                    url_lbl.setText('<a href="%s">%s</a>' % (prop.get_value('url'), prop.get_value('url')))
                    url_lbl.setOpenExternalLinks(True)
                    self.tableWidget.setCellWidget(row, self.column_index_by_name('url'), url_lbl)
                else:
                    # url is empty, so display value as normal text
                    self.set_table_value(row, 'url', prop)

                self.set_table_value(row, 'payment_address', prop)
                self.set_table_value(row, 'type', prop)
                self.set_table_value(row, 'hash', prop)
                self.set_table_value(row, 'collateral_hash', prop)
                self.set_table_value(row, 'fBlockchainValidity', prop)
                self.set_table_value(row, 'fCachedValid', prop)
                self.set_table_value(row, 'fCachedDelete', prop)
                self.set_table_value(row, 'fCachedFunding', prop)
                self.set_table_value(row, 'fCachedEndorsed', prop)
                self.set_table_value(row, 'ObjectType', prop)
                self.set_table_value(row, 'IsValidReason', prop)

                # display voting results columns"
                for col_idx, col in enumerate(self.columns):
                    if col.voting_mn == True:
                        self.set_table_value(row, col.name, prop)

                row += 1

            self.tableWidget.resizeColumnsToContents()
            self.lblMessage.setVisible(False)
            self.centerByWindow(self.main_wnd)

        except Exception as e:
            logging.exception("Exception occurred while displaing proposals.")
            self.lblMessage.setVisible(False)
            raise Exception('Error occurred while displaying proposals: ' + str(e))

        self.updateUi()

    @pyqtSlot()
    def on_buttonBox_accepted(self):
        self.accept()

    @pyqtSlot()
    def on_buttonBox_rejected(self):
        self.reject()

    @pyqtSlot()
    def on_tableWidget_itemSelectionChanged(self):
        self.updateUi()

