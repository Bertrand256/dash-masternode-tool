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


# Definition of how long the cached proposals information is valid. If it's valid, dialog
# will display data from cache, instead of requesting them from a dash daemon, which is
# more time consuming.
PROPOSALS_CACHE_VALID_SECONDS = 3600


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
    def __init__(self, voting_masternode, vote_time, vote_result):
        super().__init__()
        self.voting_masternode = voting_masternode
        self.vote_time = vote_time
        self.vote_result = vote_result
        self.set_attr_protection()


class Proposal(AttrsProtected):
    def __init__(self, columns):
        super().__init__()
        self.voting_loaded = False
        self.visible = True
        self.columns = columns
        self.values = {}  # dictionary of proposal values (key: ProposalColumn)
        self.votes = []
        self.set_attr_protection()

    def set_value(self, name, value):
        """
        Sets value for a specified Proposal column.
        """
        for col in self.columns:
            if col.name == name:
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
            ProposalColumn('no_count', 'No count', True),
            ProposalColumn('abstain_count', 'Abstain count', True),
            ProposalColumn('creation_time', 'Creation time', True),
            ProposalColumn('url', 'URL', True),
            ProposalColumn('payment_address', 'Payment address', True),
            ProposalColumn('hash', 'Hash', True),
            ProposalColumn('collateral_hash', 'Collateral hash', True),
            ProposalColumn('fCachedDelete', 'fCachedDelete', True),
            ProposalColumn('fCachedFunding', 'fCachedFunding', True),
            ProposalColumn('fCachedEndorsed', 'fCachedEndorsed', True),
            ProposalColumn('ObjectType', 'ObjectType', True),
            ProposalColumn('fBlockchainValidity', 'fBlockchainValidity', True),
            ProposalColumn('IsValidReason', 'IsValidReason', True)
        ]
        self.proposals = []
        self.masternodes_by_ident = {}
        self.mn_count = None
        self.setupUi()

    def setupUi(self):
        try:
            ui_proposals.Ui_ProposalsDlg.setupUi(self, self)
            self.setWindowTitle('Proposals')

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
                    name: Column name (str),
                    visible: (bool),
                    voting_mn: Whether column relates to masternode voting (bool),
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

            self.display_message('Reading proposals data, please wait...')
            self.runInThread(self.read_proposals_thread, (False,), self.display_data)
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

    def read_proposals_thread(self, ctrl, force_reload):
        """
        Reads proposals data from Dash daemon.
        :param ctrl:
        :param force_reload: if running
        :return:
        """
        def find_prop_data(prop_data, level=1):
            """
            Find proposal dict inside a list extracted from DataString field
            """
            if isinstance(prop_data, list):
                if len(prop_data) > 2:
                    logging.warning('len(prop_data) > 2 [level: %d]. prop_data: %s' % (level, json.dumps(prop_data)))

                if len(prop_data) >= 2 and prop_data[0] == 'proposal' and isinstance(prop_data[1], dict):
                    return prop_data[1]
                elif len(prop_data) >= 1 and isinstance(prop_data[0], list):
                    return find_prop_data(prop_data[0], level+1)
            return None

        try:
            if not self.dashd_intf.open():
                self.errorMsg('Dash daemon not connected')
            else:
                try:
                    # get list of all masternodes
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

                    skip_reading_from_dash_network = False
                    cache_file_name = os.path.join(self.main_wnd.config.cache_dir, 'proposals.json')

                    last_read_time = self.get_cache_value('ProposalsLastReadTime', 0, int)
                    if not (force_reload or int(time.time()) - last_read_time > PROPOSALS_CACHE_VALID_SECONDS):
                        # try to read information from cache
                        if self.main_wnd.config.cache_dir:
                            if os.path.exists(cache_file_name):
                                try:  # looking into cache first
                                    proposals = json.load(open(cache_file_name))
                                    skip_reading_from_dash_network = True
                                except:
                                    pass

                    if not skip_reading_from_dash_network:
                        proposals = self.dashd_intf.gobject("list", "valid", "proposals")
                        self.set_cache_value('ProposalsLastReadTime', int(time.time()))  # save when proposals has been
                                                                                         # retrieved the last time
                        try:
                            json.dump(proposals, open(cache_file_name, 'w'))
                        except Exception as e:
                            logging.exception('Could not save proposal data to cache.')

                    for pro_key in proposals:
                        prop_raw = proposals[pro_key]

                        prop_dstr = prop_raw.get("DataString")
                        prop_data_json = json.loads(prop_dstr)
                        prop_data = find_prop_data(prop_data_json)
                        if prop_data is None:
                            continue

                        prop = Proposal(self.columns)
                        prop.set_value('name', prop_data['name'])
                        prop.set_value('hash', prop_raw['Hash'])
                        prop.set_value('collateral_hash', prop_raw['CollateralHash'])
                        prop.set_value('payment_start', datetime.datetime.fromtimestamp(int(prop_data['start_epoch'])))
                        prop.set_value('payment_end', datetime.datetime.fromtimestamp(int(prop_data['end_epoch'])))
                        prop.set_value('payment_amount', float(prop_data['payment_amount']))
                        prop.set_value('yes_count', int(prop_raw['YesCount']))
                        prop.set_value('no_count', int(prop_raw['NoCount']))
                        prop.set_value('abstain_count', int(prop_raw['AbstainCount']))
                        prop.set_value('creation_time', datetime.datetime.fromtimestamp(int(prop_raw["CreationTime"])))
                        prop.set_value('url', prop_data['url'])
                        prop.set_value('payment_address', prop_data["payment_address"])
                        prop.set_value('fCachedDelete', prop_raw['fCachedDelete'])
                        prop.set_value('fCachedFunding', prop_raw['fCachedFunding'])
                        prop.set_value('fCachedEndorsed', prop_raw['fCachedEndorsed'])
                        prop.set_value('ObjectType', prop_raw['ObjectType'])
                        prop.set_value('fBlockchainValidity', prop_raw['fBlockchainValidity'])
                        prop.set_value('IsValidReason', prop_raw['IsValidReason'])
                        self.proposals.append(prop)

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

            if not self.dashd_intf.open():
                self.errorMsg('Dash daemon not connected')
            else:
                try:
                    for row_idx, prop in enumerate(self.proposals):
                        # todo: testing only
                        if row_idx > 10:
                            break
                        # todo: end  testing

                        if prop.visible and (not prop.voting_loaded or force_reload):
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
                                    if mn:
                                        v = Vote(mn, voting_time, voting_result)
                                        prop.add_vote(v)

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
                    # display data from dynamict (voting) columns
                    WndUtils.callFunInTheMainThread(self.update_grid_data, cells_to_update)

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

                self.set_table_value(row, 'hash', prop)
                self.set_table_value(row, 'collateral_hash', prop)
                self.set_table_value(row, 'payment_start', prop)
                self.set_table_value(row, 'payment_end', prop)
                self.set_table_value(row, 'payment_amount', prop, Qt.AlignRight)
                self.set_table_value(row, 'yes_count', prop, Qt.AlignRight)
                self.set_table_value(row, 'no_count', prop, Qt.AlignRight)
                self.set_table_value(row, 'abstain_count', prop, Qt.AlignRight)
                self.set_table_value(row, 'creation_time', prop)
                self.set_table_value(row, 'payment_address', prop)
                self.set_table_value(row, 'fCachedDelete', prop)
                self.set_table_value(row, 'fCachedFunding', prop)
                self.set_table_value(row, 'fCachedEndorsed', prop)
                self.set_table_value(row, 'ObjectType', prop)
                self.set_table_value(row, 'fBlockchainValidity', prop)
                self.set_table_value(row, 'IsValidReason', prop)

                # "name" column display as a hyperlink if possible
                if prop.get_value('url'):
                    url_lbl = QtWidgets.QLabel(self.tableWidget)
                    url_lbl.setText('<a href="%s">%s</a>' % (prop.get_value('url'), prop.get_value('name')))
                    url_lbl.setOpenExternalLinks(True)
                    self.tableWidget.setCellWidget(row, self.column_index_by_name('name'), url_lbl)
                else:
                    # url is empty, so display value as normal text, not hyperlink
                    self.set_table_value(row, 'name', prop)

                if prop.get_value('url'):
                    url_lbl = QtWidgets.QLabel(self.tableWidget)
                    url_lbl.setText('<a href="%s">%s</a>' % (prop.get_value('url'), prop.get_value('url')))
                    url_lbl.setOpenExternalLinks(True)
                    self.tableWidget.setCellWidget(row, self.column_index_by_name('url'), url_lbl)
                else:
                    # url is empty, so display value as normal text
                    self.set_table_value(row, 'url', prop)

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

