#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-10
import os

import sqlite3
import logging
import threading
from typing import List
import thread_utils


log = logging.getLogger('dmt.db_intf')


class DBCache(object):
    """Purpose: coordinating access to a database cache (sqlite) from multiple threads.

    Usage: call 'get_cursor' when before starting dealing with the cache db and 'release_cursor' after finishing.

    Note:
        1. get_cursor call locks the cache database to be used by the calling thread only
        2. subsequent get_cursor calls by the same thread require the same number of release_cursor calls;
           this is useful if you need multiple cursors to perform the required operations in one thread
    """

    def __init__(self):
        self.db_cache_file_name = ''
        self.db_labels_file_name = ''
        self.db_active = False
        self.lock = thread_utils.EnhRLock(stackinfo_skip_lines=1)
        self.depth = 0
        self.db_conn = None

    def is_active(self):
        return self.db_active

    def open(self, db_cache_file_name):
        if not db_cache_file_name:
            raise Exception('Invalid database cache file name value.')
        self.db_cache_file_name = db_cache_file_name
        dir, ext = os.path.splitext(db_cache_file_name)
        self.db_labels_file_name = dir + '_labels' + ext

        if not self.db_active:
            log.debug('Trying to acquire db cache session')
            self.lock.acquire()
            try:
                if self.db_conn is None:
                    self.db_conn = sqlite3.connect(self.db_cache_file_name)
                    db_conn2 = sqlite3.connect(self.db_labels_file_name)
                    db_conn2.close()
                    self.db_conn.execute(f"attach database '{self.db_labels_file_name}' as labels")

                self.create_structures()
                self.db_active = True
                self.db_conn.close()
                self.db_conn = None
                self.depth = 0

            except Exception as e:
                log.exception('SQLite initialization error')

            finally:
                self.lock.release()
        else:
            raise Exception('Database cache already active.')

    def close(self):
        if self.depth > 0:
            log.error('Database not closed yet. Depth: ' + str(self.depth))
        self.db_active = False

    def get_cursor(self):
        if self.db_active:
            log.debug('Trying to acquire db cache session')
            self.lock.acquire()
            self.depth += 1
            if self.db_conn is None:
                self.db_conn = sqlite3.connect(self.db_cache_file_name)
                self.db_conn.execute(f"attach database '{self.db_labels_file_name}' as labels")
            log.debug('Acquired db cache session (%d)' % self.depth)
            return self.db_conn.cursor()
        else:
            raise Exception('Database cache not active.')

    def release_cursor(self):
        if self.db_active:
            try:
                self.lock.acquire()
                if self.depth == 0:
                    raise Exception('Cursor not acquired by this thread.')
                self.depth -= 1
                try:
                    if self.depth == 0:
                        self.db_conn.close()
                        self.db_conn = None
                finally:
                    self.lock.release()
                log.debug('Released db cache session (%d)' % self.depth)
            finally:
                self.lock.release()
        else:
            log.warning('Cannot release database session if db_active is False.')

    def commit(self):
        if self.db_active:
            try:
                self.lock.acquire()
                if self.depth == 0:
                    raise Exception('Cursor not acquired by this thread. Cannot commit.')
                self.db_conn.commit()
            finally:
                self.lock.release()
        else:
            log.warning('Cannot commit if db_active is False.')

    def rollback(self):
        if self.db_active:
            try:
                self.lock.acquire()
                if self.depth == 0:
                    raise Exception('Cursor not acquired by this thread. Cannot rollback.')
                self.db_conn.rollback()
            finally:
                self.lock.release()
        else:
            log.warning('Cannot commit if db_active is False.')

    def create_structures(self):
        try:
            cur = self.db_conn.cursor()
            # create structires for masternodes data:
            cur.execute("CREATE TABLE IF NOT EXISTS masternodes(id INTEGER PRIMARY KEY, ident TEXT, status TEXT,"
                        " protocol TEXT, payee TEXT, last_seen INTEGER, active_seconds INTEGER,"
                        " last_paid_time INTEGER, last_paid_block INTEGER, ip TEXT,"
                        " dmt_active INTEGER, dmt_create_time TEXT, dmt_deactivation_time TEXT)")

            cur.execute("CREATE INDEX IF NOT EXISTS IDX_masternodes_DMT_ACTIVE ON masternodes(dmt_active)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_masternodes_IDENT ON masternodes(ident)")

            if not self.table_columns_exist('masternodes', ['protx_hash']):
                cur.execute("ALTER TABLE masternodes ADD COLUMN protx_hash TEXT")

            if not self.table_columns_exist('masternodes', ['registered_height']):
                cur.execute("ALTER TABLE masternodes ADD COLUMN registered_height INTEGER")

            if not self.table_columns_exist('masternodes', ['queue_position']):
                cur.execute("ALTER TABLE masternodes ADD COLUMN queue_position INTEGER")

            # create structures for proposals:
            cur.execute("CREATE TABLE IF NOT EXISTS proposals(id INTEGER PRIMARY KEY, name TEXT, payment_start TEXT,"
                        " payment_end TEXT, payment_amount REAL, yes_count INTEGER, absolute_yes_count INTEGER,"
                        " no_count INTEGER, abstain_count INTEGER, creation_time TEXT, url TEXT, payment_address TEXT,"
                        " type INTEGER, hash TEXT,  collateral_hash TEXT, f_blockchain_validity INTEGER,"
                        " f_cached_valid INTEGER, f_cached_delete INTEGER, f_cached_funding INTEGER, "
                        " f_cached_endorsed INTEGER, object_type INTEGER, is_valid_reason TEXT, dmt_active INTEGER, "
                        " dmt_create_time TEXT, dmt_deactivation_time TEXT, dmt_voting_last_read_time INTEGER,"
                        " ext_attributes_loaded INTEGER, owner TEXT, title TEXT, ext_attributes_load_time INTEGER)")

            cur.execute("CREATE INDEX IF NOT EXISTS IDX_PROPOSALS_HASH ON PROPOSALS(hash)")

            # upgrade schema do v 0.9.11:
            cur.execute("PRAGMA table_info(PROPOSALS)")
            columns = cur.fetchall()
            prop_owner_exists = False
            prop_title_exists = False
            ext_attributes_loaded_exists = False
            ext_attributes_load_time_exists = False
            for col in columns:
                if col[1] == 'owner':
                    prop_owner_exists = True
                elif col[1] == 'title':
                    prop_title_exists = True
                elif col[1] == 'ext_attributes_loaded':
                    ext_attributes_loaded_exists = True
                elif col[1] == 'ext_attributes_load_time':
                    ext_attributes_load_time_exists = True
                if prop_owner_exists and prop_title_exists and ext_attributes_loaded_exists and \
                        ext_attributes_load_time_exists:
                    break

            if not ext_attributes_loaded_exists:
                # column for saving information whether additional attributes has been read from external sources
                # like DashCentral.org (1: yes, 0: no)
                cur.execute("ALTER TABLE PROPOSALS ADD COLUMN ext_attributes_loaded INTEGER")
            if not prop_owner_exists:
                # proposal's owner from an external source like DashCentral.org
                cur.execute("ALTER TABLE PROPOSALS ADD COLUMN owner TEXT")
            if not prop_title_exists:
                # proposal's title from an external source like DashCentral.org
                cur.execute("ALTER TABLE PROPOSALS ADD COLUMN title TEXT")
            if not ext_attributes_load_time_exists:
                # proposal's title from an external source like DashCentral.org
                cur.execute("ALTER TABLE PROPOSALS ADD COLUMN ext_attributes_load_time INTEGER")

            cur.execute("CREATE TABLE IF NOT EXISTS VOTING_RESULTS(id INTEGER PRIMARY KEY, proposal_id INTEGER,"
                        " masternode_ident TEXT, voting_time TEXT, voting_result TEXT,"
                        "hash TEXT)")

            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS IDX_VOTING_RESULTS_HASH ON VOTING_RESULTS(hash)")

            cur.execute("CREATE INDEX IF NOT EXISTS IDX_VOTING_RESULTS_1 ON VOTING_RESULTS(proposal_id)")

            cur.execute("CREATE INDEX IF NOT EXISTS IDX_VOTING_RESULTS_2 ON VOTING_RESULTS(masternode_ident)")

            # Create table for storing live data for example last read time of proposals
            cur.execute("CREATE TABLE IF NOT EXISTS LIVE_CONFIG(symbol text PRIMARY KEY, value TEXT)")

            cur.execute("CREATE INDEX IF NOT EXISTS IDX_LIVE_CONFIG_SYMBOL ON LIVE_CONFIG(symbol)")

            cur.execute("CREATE TABLE IF NOT EXISTS hd_tree(id INTEGER PRIMARY KEY, ident TEXT, label TEXT)")

            cur.execute("CREATE INDEX IF NOT EXISTS idx_hd_tree_1 ON hd_tree(ident)")

            if not self.table_columns_exist('address', ['parent_id', 'xpub_hash', 'balance', 'address_index',
                                                        'last_scan_block_height', 'tree_id']):
                cur.execute("drop table if exists address")

            cur.execute("CREATE TABLE IF NOT EXISTS address(id INTEGER PRIMARY KEY,"
                        "xpub_hash TEXT, parent_id INTEGER, address_index INTEGER, address TEXT, path TEXT, "
                        "tree_id INTEGER, balance INTEGER DEFAULT 0 NOT NULL, received INTEGER DEFAULT 0 NOT NULL, "
                        "is_change INTEGER, last_scan_block_height INTEGER DEFAULT 0 NOT NULL, label TEXT,"
                        "status INTEGER DEFAULT 0)")

            cur.execute("CREATE INDEX IF NOT EXISTS idx_address_1 ON address(xpub_hash)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_address_2 ON address(parent_id, address_index)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_address_3 ON address(address)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_address_4 ON address(tree_id)")

            # if tx.block_height == 0, the transaction has not yet been confirmed (it may be the transaction that
            # has just been sent from dmt wallet or the transaction which appeared in the mempool); in this case
            # tx.block_timestamp indicates the moment when the transaction was added to the cache (it will be purged
            # if will not appear on the blockchain after a defined amount of time)
            cur.execute("CREATE TABLE IF NOT EXISTS tx(id INTEGER PRIMARY KEY, tx_hash TEXT, block_height INTEGER,"
                        "block_timestamp INTEGER, coinbase INTEGER)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_1 ON tx(tx_hash)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_1 ON tx(block_height)")

            cur.execute("CREATE TABLE IF NOT EXISTS tx_output(id INTEGER PRIMARY KEY, address_id INTEGER, "
                        "address TEXT, tx_id INTEGER NOT NULL, output_index INTEGER NOT NULL, "
                        "satoshis INTEGER NOT NULL, spent_tx_id INTEGER, spent_input_index INTEGER, "
                        "script_type TEXT)")

            cur.execute("CREATE INDEX IF NOT EXISTS tx_output_1 ON tx_output(tx_id, output_index)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_output_2 ON tx_output(address_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_output_3 ON tx_output(address)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_output_4 ON tx_output(spent_tx_id)")

            cur.execute("CREATE TABLE IF NOT EXISTS tx_input(id INTEGER PRIMARY KEY, src_address TEXT, "
                        "src_address_id INTEGER, tx_id INTEGER NOT NULL, input_index INTEGER NOT NULL, "
                        "satoshis INTEGER DEFAULT 0, src_tx_hash TEXT, src_tx_id INTEGER, src_tx_output_index INTEGER, "
                        "coinbase INTEGER DEFAULT 0 NOT NULL)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_input_1 ON tx_input(tx_id, input_index)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_input_2 ON tx_input(src_address_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_input_3 ON tx_input(src_address)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_input_4 ON tx_input(src_tx_hash)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_input_5 ON tx_input(src_tx_id)")

            cur.execute('create table if not exists labels.address_label(id INTEGER PRIMARY KEY, key TEXT, label TEXT, '
                        'timestamp INTEGER)')
            cur.execute('create index if not exists labels.address_label_1 on address_label(key)')

            cur.execute('create table if not exists labels.tx_out_label(id INTEGER PRIMARY KEY, key TEXT, label TEXT, '
                        'timestamp INTEGER)')  # key: tx hash + '-' + output_index
            cur.execute('create index if not exists labels.tx_out_label_1 on address_label(key)')

        except Exception:
            log.exception('Exception while initializing database.')
            raise

    def table_columns_exist(self, table_name, column_names: List[str]):
        cur = self.db_conn.cursor()
        try:
            cur.execute(f"PRAGMA table_info({table_name})")
            cols_existing = [col[1] for col in cur.fetchall()]
            for c in column_names:
                if c not in cols_existing:
                    return False
        finally:
            cur.close()
        return True