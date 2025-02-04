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

    def open(self, db_cache_file_name, db_labels_file_name):
        if not db_cache_file_name:
            raise Exception('Invalid database cache file name value.')
        self.db_cache_file_name = db_cache_file_name
        self.db_labels_file_name = db_labels_file_name

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
            # create structures for masternodes data:
            cur.execute("CREATE TABLE IF NOT EXISTS masternodes(id INTEGER PRIMARY KEY, ident TEXT, status TEXT,"
                        " type TEXT, protocol TEXT, payee TEXT, last_seen INTEGER, active_seconds INTEGER,"
                        " last_paid_time INTEGER, last_paid_block INTEGER, ip TEXT,"
                        " collateral_hash TEXT, collateral_index INTEGER, collateral_address TEXT, "
                        " owner_address TEXT, voting_address TEXT, pubkey_operator TEXT,"
                        " platform_node_id TEXT, platform_p2p_port INTEGER, platform_http_port INTEGER, "
                        " dmt_active INTEGER, dmt_create_time TEXT, dmt_deactivation_time TEXT, "
                        " protx_hash TEXT, queue_position INTEGER, registered_height INTEGER, "
                        " operator_reward REAL, pose_penalty INTEGER, pose_revived_height INTEGER, "
                        " pose_ban_height INTEGER, operator_payout_address TEXT, pose_ban_timestamp INTEGER)")

            cur.execute("CREATE INDEX IF NOT EXISTS IDX_masternodes_DMT_ACTIVE ON masternodes(dmt_active)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_masternodes_IDENT ON masternodes(ident)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_masternodes_DMT_CREATE_TIME ON masternodes(dmt_create_time)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_masternodes_DMT_DEACTIVATION_TIME ON "
                        "masternodes(dmt_deactivation_time)")

            # create structures for proposals:
            cur.execute("CREATE TABLE IF NOT EXISTS proposals(id INTEGER PRIMARY KEY, name TEXT, payment_start TEXT,"
                        " payment_end TEXT, payment_amount REAL, yes_count INTEGER, absolute_yes_count INTEGER,"
                        " no_count INTEGER, abstain_count INTEGER, creation_time TEXT, url TEXT, payment_address TEXT,"
                        " type INTEGER, hash TEXT,  collateral_hash TEXT, f_blockchain_validity INTEGER,"
                        " f_cached_valid INTEGER, f_cached_delete INTEGER, f_cached_funding INTEGER, "
                        " f_cached_endorsed INTEGER, object_type INTEGER, is_valid_reason TEXT, dmt_active INTEGER, "
                        " dmt_create_time TEXT, dmt_deactivation_time TEXT, dmt_voting_last_read_time INTEGER,"
                        " ext_attributes_loaded INTEGER, owner TEXT, title TEXT, ext_attributes_load_time INTEGER)")

            cur.execute("CREATE INDEX IF NOT EXISTS idx_proposals_hash ON proposals(hash)")

            # structure for protx info
            cur.execute("CREATE TABLE IF NOT EXISTS protx(id INTEGER PRIMARY KEY, protx_hash TEXT, "
                        "operator_reward REAL, service TEXT, registered_height INTEGER, "
                        "pose_penalty INTEGER, pose_revived_height INTEGER, pose_ban_height INTEGER, "                        
                        "operator_payout_address TEXT)")

            cur.execute("CREATE TABLE IF NOT EXISTS voting_results(id INTEGER PRIMARY KEY, proposal_id INTEGER,"
                        " masternode_ident TEXT, voting_time TEXT, voting_result TEXT, signal TEXT, weight INTEGER,"
                        " hash TEXT)")

            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_voting_results_hash ON voting_results(hash)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_voting_results_1 ON voting_results(proposal_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_voting_results_2 ON voting_results(masternode_ident)")

            # Create table for storing live data, for example, last read time of proposals
            cur.execute("CREATE TABLE IF NOT EXISTS LIVE_CONFIG(symbol text PRIMARY KEY, value TEXT)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_LIVE_CONFIG_SYMBOL ON LIVE_CONFIG(symbol)")
            cur.execute("CREATE TABLE IF NOT EXISTS hd_tree(id INTEGER PRIMARY KEY, ident TEXT, label TEXT)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_hd_tree_1 ON hd_tree(ident)")

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
            cur.execute("CREATE INDEX IF NOT EXISTS tx_2 ON tx(block_height)")

            cur.execute("CREATE TABLE IF NOT EXISTS tx_output(id INTEGER PRIMARY KEY, "
                        "address TEXT, tx_id INTEGER NOT NULL, output_index INTEGER NOT NULL, "
                        "satoshis INTEGER NOT NULL, spent_tx_hash TEXT, spent_input_index INTEGER, "
                        "script_type TEXT)")

            cur.execute("CREATE INDEX IF NOT EXISTS tx_output_1 ON tx_output(tx_id, output_index)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_output_3 ON tx_output(address)")

            cur.execute("CREATE TABLE IF NOT EXISTS tx_input(id INTEGER PRIMARY KEY, src_address TEXT, "
                        "tx_id INTEGER NOT NULL, input_index INTEGER NOT NULL, "
                        "satoshis INTEGER DEFAULT 0, src_tx_hash TEXT, src_tx_output_index INTEGER, "
                        "coinbase INTEGER DEFAULT 0 NOT NULL)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_input_1 ON tx_input(tx_id, input_index)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_input_3 ON tx_input(src_address)")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_input_4 ON tx_input(src_tx_hash)")

            cur.execute('create table if not exists labels.address_label(id INTEGER PRIMARY KEY, key TEXT, label TEXT, '
                        'timestamp INTEGER)')
            cur.execute('create index if not exists labels.address_label_1 on address_label(key)')

            cur.execute('create table if not exists labels.tx_out_label(id INTEGER PRIMARY KEY, key TEXT, label TEXT, '
                        'timestamp INTEGER)')  # key: tx hash + '-' + output_index
            cur.execute('create index if not exists labels.tx_out_label_1 on address_label(key)')

            # Upgrade to schema 0.9.33
            cur.execute("PRAGMA table_info(masternodes)")
            columns = [x[1] for x in cur.fetchall()]
            if 'protx_hash' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN protx_hash TEXT")
            if 'registered_height' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN registered_height INTEGER")
            if 'queue_position' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN queue_position INTEGER")
            if 'type' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN type TEXT")
            if 'platform_node_id' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN platform_node_id TEXT")
            if 'platform_p2p_port' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN platform_p2p_port INTEGER")
            if 'platform_http_port' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN platform_http_port INTEGER")
            if 'collateral_hash' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN collateral_hash TEXT")
            if 'collateral_index' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN collateral_index INTEGER")
            if 'collateral_address' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN collateral_address TEXT")
            if 'owner_address' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN owner_address TEXT")
            if 'voting_address' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN voting_address TEXT")
            if 'pubkey_operator' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN pubkey_operator TEXT")
            if 'operator_reward' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN operator_reward REAL")
            if 'pose_penalty' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN pose_penalty INTEGER")
            if 'pose_revived_height' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN pose_revived_height INTEGER")
            if 'pose_ban_height' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN pose_ban_height INTEGER")
            if 'operator_payout_address' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN operator_payout_address TEXT")
            if 'pose_ban_timestamp' not in columns:
                cur.execute("ALTER TABLE masternodes ADD COLUMN pose_ban_timestamp INTEGER")
            if not self.table_columns_exist('voting_results', ['signal']):
                cur.execute("ALTER TABLE voting_results ADD COLUMN signal TEXT")
            if not self.table_columns_exist('voting_results', ['weight']):
                cur.execute("ALTER TABLE voting_results ADD COLUMN weight INTEGER")

            # Upgrade to schema 0.9.40
            # Here we're introducing the 'spent_tx_hash' column as a replacement of 'spent_tx_id' to avoid storing
            # the transactions in db cache that are not strictly related to the addresses from our hardware wallet
            cur.execute("PRAGMA table_info(tx_output)")
            columns = [x[1] for x in cur.fetchall()]
            if 'spent_tx_hash' not in columns:
                cur.execute("ALTER TABLE tx_output ADD COLUMN spent_tx_hash TEXT")
            cur.execute("CREATE INDEX IF NOT EXISTS tx_output_5 ON tx_output(spent_tx_hash)")
            if 'spent_tx_id' in columns:
                cur.execute("DROP INDEX IF EXISTS tx_output_4")
                cur.execute('ALTER TABLE tx_output DROP COLUMN spent_tx_id')
            if 'address_id' in columns:
                cur.execute("DROP INDEX IF EXISTS tx_output_2")
                cur.execute('ALTER TABLE tx_output DROP COLUMN address_id')

            cur.execute("PRAGMA table_info(tx_input)")
            columns = [x[1] for x in cur.fetchall()]
            if 'src_tx_id' in columns:
                cur.execute("DROP INDEX IF EXISTS tx_input_5")
                cur.execute('ALTER TABLE tx_input DROP COLUMN src_tx_id')  # similar to 'spent_tx_id'
            if 'src_address_id' in columns:
                cur.execute("DROP INDEX IF EXISTS tx_input_2")
                cur.execute('ALTER TABLE tx_input DROP COLUMN src_address_id')  # similar to 'spent_tx_id'

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