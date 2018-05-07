#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-10
import sqlite3
import logging
import threading
import thread_utils


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

        if not self.db_active:
            logging.debug('Trying to acquire db cache session')
            self.lock.acquire()
            try:
                if self.db_conn is None:
                    self.db_conn = sqlite3.connect(self.db_cache_file_name)

                self.create_structures()
                self.db_active = True
                self.db_conn.close()
                self.db_conn = None
                self.depth = 0

            except Exception as e:
                logging.exception('SQLite initialization error')

            finally:
                self.lock.release()
        else:
            raise Exception('Database cache already active.')

    def close(self):
        if self.depth > 0:
            logging.error('Database not closed yet. Depth: ' + str(self.depth))
        self.db_active = False

    def get_cursor(self):
        if self.db_active:
            logging.debug('Trying to acquire db cache session')
            self.lock.acquire()
            self.depth += 1
            if self.db_conn is None:
                self.db_conn = sqlite3.connect(self.db_cache_file_name)
            logging.debug('Acquired db cache session (%d)' % self.depth)
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
                if self.depth == 0:
                    self.db_conn.close()
                    self.db_conn = None
                self.lock.release()
                logging.debug('Released db cache session (%d)' % self.depth)
            finally:
                self.lock.release()
        else:
            logging.warning('Cannot release database session if db_active is False.')

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
            logging.warning('Cannot commit if db_active is False.')

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
            logging.warning('Cannot commit if db_active is False.')

    def create_structures(self):
        try:
            cur = self.db_conn.cursor()
            # create structires for masternodes data:
            cur.execute("CREATE TABLE IF NOT EXISTS MASTERNODES(id INTEGER PRIMARY KEY, ident TEXT, status TEXT,"
                        " protocol TEXT, payee TEXT, last_seen INTEGER, active_seconds INTEGER,"
                        " last_paid_time INTEGER, last_paid_block INTEGER, ip TEXT,"
                        " dmt_active INTEGER, dmt_create_time TEXT, dmt_deactivation_time TEXT)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_MASTERNODES_DMT_ACTIVE ON MASTERNODES(dmt_active)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_MASTERNODES_IDENT ON MASTERNODES(ident)")

            # create structures for proposals:
            cur.execute("CREATE TABLE IF NOT EXISTS PROPOSALS(id INTEGER PRIMARY KEY, name TEXT, payment_start TEXT,"
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

            cur.execute("CREATE TABLE IF NOT EXISTS ADDRESS_HD_TREE(id INTEGER PRIMARY KEY, ident TEXT)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_ADDRESS_TREE_1 ON ADDRESS_HD_TREE(ident)")

            cur.execute("CREATE TABLE IF NOT EXISTS ADDRESS(id INTEGER PRIMARY KEY,"
                        "tree_id INTEGER, path TEXT, address TEXT)")
            cur.execute("CREATE INDEX IF NOT EXISTS IDX_ADDRESS_1 ON ADDRESS(tree_id, path)")
        except Exception:
            logging.exception('Exception while initializing database.')
            raise
